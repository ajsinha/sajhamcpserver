#!/usr/bin/env python3
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA load harness, federation scenario: proxied tool calls through SAJHA to an upstream MCP server.

It starts the example upstream (``sajha/examples/federation/units_server.py``) on a local port, then,
for each server configuration (``backend:workers:pool``), ``run_sajha_web.py`` with federation on and
that upstream configured (approval off, a scratch store), and drives ``tools/call`` on ``/mcp``
(2026-07-28, stateless) with ``--concurrency`` requests in flight:

    local      calc_future_value, a local tool (the baseline on the same server)
    proxied    units__celsius_to_fahrenheit, answered by the upstream through the federation pool
    shed       units__countdown (about 100 ms upstream) with federation.max_in_flight = --shed-limit and
               no queue: calls over the bound are refused at once (counted as "shed", not as errors)

The upstream, SAJHA and the load generator share the machine: say so when citing the numbers.
Output: ``bench-federation-<timestamp>.json`` and ``.md`` in ``--out``. The server start-up, the
hardware block and the load processes are those of ``tools/bench/bench.py``.

    .venv/bin/python tools/bench/bench_federation.py --out /tmp/sajha-bench
    .venv/bin/python tools/bench/bench_federation.py --configs memory:1:1,memory:1:4 --duration 10

Published results: docs/architecture/Scaling and State.md, section "Measured performance".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402  (tools/bench/bench.py: server start-up, hardware, percentiles)

UPSTREAM_ID = "units"
PHASES = {
    "local": ("calc_future_value", lambda: {"present_value": round(random.uniform(1, 1e6), 2),
                                            "rate": round(random.uniform(0.1, 15), 3), "years": random.randint(1, 40)}),
    "proxied": (f"{UPSTREAM_ID}__celsius_to_fahrenheit", lambda: {"celsius": round(random.uniform(-50, 50), 4)}),
    "shed": (f"{UPSTREAM_ID}__countdown", lambda: {"steps": 2, "seconds_per_step": 0.05,
                                                   "_n": random.random()}),
}


def start_upstream(port: int, log: Path) -> subprocess.Popen:
    out = open(log, "wb")
    proc = subprocess.Popen([sys.executable, "-m", "sajha.examples.federation.units_server", "--port", str(port)],
                            cwd=str(bench.ROOT), stdout=out, stderr=subprocess.STDOUT)
    end = time.time() + 30
    while time.time() < end:
        if proc.poll() is not None:
            raise RuntimeError(f"upstream exited; see {log}")
        if not bench.port_free(port):
            return proc
        time.sleep(0.2)
    raise RuntimeError("upstream did not start")


def federation_env(env: Dict[str, str], scratch: Path, upstream_url: str, pool: int,
                   shed_limit: int) -> Dict[str, str]:
    env = dict(env)
    env.update({
        "SAJHA_FEDERATION_ENABLED": "true",
        "SAJHA_FEDERATION_ALLOW_LOCALHOST": "true",
        "SAJHA_FEDERATION_REQUIRE_APPROVAL": "false",
        "SAJHA_FEDERATION_STATE_PATH": str(scratch / "federation.json"),
        "SAJHA_FEDERATION_MCP_SERVERS_FILE": str(scratch / "mcp_servers.json"),     # none: only this upstream
        "SAJHA_FEDERATION_STARTUP_WAIT_SECONDS": "15",
        "SAJHA_FEDERATION_POOL_SIZE": str(pool),
        "SAJHA_FEDERATION_MAX_QUEUE": "0",
        "SAJHA_FEDERATION_UPSTREAMS": json.dumps([
            {"id": UPSTREAM_ID, "url": upstream_url, "retries": 0},
            # the same upstream under a second id, bounded: the shedding phase calls it
            {"id": "unitsbounded", "prefix": "unitsbounded", "url": upstream_url, "retries": 0,
             "max_in_flight": shed_limit, "max_queue": 0}]),
    })
    return env


async def _drive(base: str, key: str, phase: str, conc: int, warmup: float, duration: float):
    tool, make_args = PHASES[phase]
    if phase == "shed":
        tool = tool.replace(f"{UPSTREAM_ID}__", "unitsbounded__")
    limits = httpx.Limits(max_connections=conc, max_keepalive_connections=conc)
    lat: List[float] = []
    errors = shed = 0
    async with httpx.AsyncClient(base_url=base, timeout=30, limits=limits) as http:
        clients = [bench.Client(http, "modern", key) for _ in range(conc)]
        start = time.perf_counter()
        t_measure, t_end = start + warmup, start + warmup + duration

        async def loop(c):
            nonlocal errors, shed
            rid = 0
            while True:
                t0 = time.perf_counter()
                if t0 >= t_end:
                    return
                rid += 1
                args = make_args()
                args.pop("_n", None)
                kind = "err"
                try:
                    r = await http.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                                                      "params": {"name": tool, "arguments": args,
                                                                 "_meta": bench.META}},
                                        headers=c._headers("tools/call", tool))
                    body = bench._parse(r) if r.status_code == 200 else None
                    res = body.get("result") if isinstance(body, dict) else None
                    if isinstance(res, dict):
                        text = " ".join(b.get("text", "") for b in res.get("content") or [] if isinstance(b, dict))
                        if not res.get("isError"):
                            kind = "ok"
                        elif "at capacity" in text:
                            kind = "shed"
                except Exception:
                    kind = "err"
                t1 = time.perf_counter()
                if t0 >= t_measure and t1 <= t_end:
                    if kind == "ok":
                        lat.append((t1 - t0) * 1000.0)
                    elif kind == "shed":
                        shed += 1
                    else:
                        errors += 1

        await asyncio.gather(*(loop(c) for c in clients))
    return lat, errors, shed


def _proc(args):
    return asyncio.run(_drive(*args))


def run_phase(base: str, phase: str, concurrency: int, clients: int, warmup: float, duration: float):
    clients = max(1, min(clients, concurrency))
    share = [concurrency // clients + (1 if i < concurrency % clients else 0) for i in range(clients)]
    with mp.get_context("spawn").Pool(clients) as pool:
        results = pool.map(_proc, [(base, bench.BENCH_KEY, phase, n, warmup, duration) for n in share])
    lat = sorted(x for r in results for x in r[0])
    return {"phase": phase, "tool": PHASES[phase][0] if phase != "shed" else "unitsbounded__countdown",
            "requests": len(lat), "errors": sum(r[1] for r in results), "shed": sum(r[2] for r in results),
            "throughput_rps": round(len(lat) / duration, 1),
            "p50_ms": round(bench.percentile(lat, 0.50), 2), "p95_ms": round(bench.percentile(lat, 0.95), 2),
            "p99_ms": round(bench.percentile(lat, 0.99), 2),
            "mean_ms": round(statistics.fmean(lat), 2) if lat else None}


def markdown(report: Dict[str, object]) -> str:
    hw, b, p = report["hardware"], report["build"], report["parameters"]
    lines = [f"SAJHA load harness, federation scenario, {report['date']}", "",
             f"Hardware: {hw['cpu']}, {hw['logical_cores']} logical cores, {hw['ram_gb']} GB RAM; {hw['os']}; "
             f"Python {hw['python']}. SAJHA {b['sajha_version']} at {b['commit']}.",
             f"Load: {p['concurrency']} requests in flight from {p['clients']} load processes; {p['warmup_s']} s "
             f"warm-up, {p['duration_s']} s measured per row; MCP 2026-07-28 tools/call. The upstream, SAJHA and "
             f"the load generator share the machine. Shedding row: max_in_flight {p['shed_limit']} per worker, "
             f"no queue.", "",
             "| Backend | Workers | Pool | Phase | Tool | Requests | Shed | Errors | Throughput (req/s) | "
             "p50 (ms) | p95 (ms) | p99 (ms) |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in report["scenarios"]:
        if s.get("skipped") or s.get("error"):
            lines.append(f"| {s['backend']} | {s['workers']} | {s['pool']} | | | | | | "
                         f"{'skipped: ' + s['skipped'] if s.get('skipped') else 'failed: ' + s['error']} | | | |")
            continue
        for ph in s["phases"]:
            lines.append(f"| {s['backend']} | {s['workers']} | {s['pool']} | {ph['phase']} | `{ph['tool']}` | "
                         f"{ph['requests']} | {ph['shed']} | {ph['errors']} | {ph['throughput_rps']} | "
                         f"{ph['p50_ms']} | {ph['p95_ms']} | {ph['p99_ms']} |")
    return "\n".join(lines) + "\n"


def parse_configs(text: str) -> List[Tuple[str, int, int]]:
    out = []
    for spec in [c.strip() for c in text.split(",") if c.strip()]:
        parts = spec.split(":")
        out.append((parts[0], int(parts[1]) if len(parts) > 1 else 1, int(parts[2]) if len(parts) > 2 else 1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--configs", default="memory:1:1,memory:1:4,database:4:1",
                    help="backend:workers:pool_size, comma separated")
    ap.add_argument("--phases", default="local,proxied,shed")
    ap.add_argument("--duration", type=float, default=15.0)
    ap.add_argument("--warmup", type=float, default=3.0)
    ap.add_argument("--concurrency", type=int, default=32)
    ap.add_argument("--clients", type=int, default=4)
    ap.add_argument("--shed-limit", type=int, default=4, help="max_in_flight of the bounded upstream (shed phase)")
    ap.add_argument("--port", type=int, default=3171, help="SAJHA's first port; the upstream takes --upstream-port")
    ap.add_argument("--upstream-port", type=int, default=3170)
    ap.add_argument("--redis-url", default=os.environ.get("SAJHA_TEST_REDIS_URL", "redis://127.0.0.1:6379/15"))
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "sajha-bench"))
    ap.add_argument("--scratch", default=None)
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    phases = [p.strip() for p in a.phases.split(",") if p.strip() in PHASES]
    report: Dict[str, object] = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "hardware": bench.hardware(),
        "build": bench.build_info(),
        "parameters": {"duration_s": a.duration, "warmup_s": a.warmup, "concurrency": a.concurrency,
                       "clients": a.clients, "shed_limit": a.shed_limit},
        "scenarios": []}
    up_scratch = Path(tempfile.mkdtemp(prefix="sajha-bench-upstream-", dir=a.scratch))
    upstream = start_upstream(a.upstream_port, up_scratch / "upstream.log")
    upstream_url = f"http://127.0.0.1:{a.upstream_port}/mcp"
    port = a.port
    try:
        for backend, workers, pool in parse_configs(a.configs):
            scen: Dict[str, object] = {"backend": backend, "workers": workers, "pool": pool}
            report["scenarios"].append(scen)
            if backend == "memory" and workers > 1:
                scen["skipped"] = "memory is one worker only"
                continue
            if backend == "redis" and not bench.redis_reachable(a.redis_url):
                scen["skipped"] = f"no Redis server answered at {a.redis_url}"
                continue
            scratch = Path(tempfile.mkdtemp(prefix=f"sajha-bench-fed-{backend}{workers}p{pool}-", dir=a.scratch))
            env = federation_env(bench.server_env(scratch, backend, a.redis_url), scratch, upstream_url, pool,
                                 a.shed_limit)
            print(f"[bench-federation] {backend}:{workers} pool {pool}: starting on port {port}", flush=True)
            srv = bench.Server(port, workers, env, scratch / "server.log")
            try:
                scen["state"] = srv.wait().get("state")
                scen["phases"] = []
                for phase in phases:
                    ph = run_phase(srv.base, phase, a.concurrency, a.clients, a.warmup, a.duration)
                    scen["phases"].append(ph)
                    print(f"[bench-federation]   {phase:8} {ph['throughput_rps']:>8} req/s  p50 {ph['p50_ms']} ms  "
                          f"p95 {ph['p95_ms']} ms  p99 {ph['p99_ms']} ms  shed {ph['shed']}  errors {ph['errors']}",
                          flush=True)
            except Exception as e:
                scen["error"] = str(e)
                print(f"[bench-federation] failed: {e}", flush=True)
            finally:
                srv.stop()
                if "error" not in scen:
                    shutil.rmtree(scratch, ignore_errors=True)
            port += 1
    finally:
        upstream.terminate()
        try:
            upstream.wait(10)
        except subprocess.TimeoutExpired:
            upstream.kill()
        shutil.rmtree(up_scratch, ignore_errors=True)
    (out / f"bench-federation-{stamp}.json").write_text(json.dumps(report, indent=2))
    (out / f"bench-federation-{stamp}.md").write_text(markdown(report))
    print(f"[bench-federation] wrote {out / f'bench-federation-{stamp}.md'}", flush=True)
    return 1 if any("error" in s for s in report["scenarios"]) else 0


if __name__ == "__main__":
    sys.exit(main())
