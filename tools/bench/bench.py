#!/usr/bin/env python3
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA load harness: latency and throughput of ``/mcp`` on both protocol eras.

For each server configuration (a ``state.backend`` and a number of uvicorn workers) it
starts ``run_sajha_web.py`` on a local port with a scratch database and scratch credential
files, waits for ``/health``, and drives four phases against ``/mcp``:

    modern  tools/list          2026-07-28, stateless (``_meta`` + ``MCP-Protocol-Version``)
    modern  tools/call          calc_future_value (a local tool: pure Python, no network)
    legacy  tools/list          2025-11-25: ``initialize`` once per client connection, then
    legacy  tools/call          requests on the ``Mcp-Session-Id``

Each phase runs ``--concurrency`` requests in flight (spread over ``--clients`` load
processes, each an asyncio loop with one httpx connection pool) for ``--warmup`` seconds
unmeasured, then ``--duration`` seconds measured. The tool's arguments change on every call,
so the tool output cache never answers. Every response is checked: a non-200 status, a
JSON-RPC error or a tool result with ``isError`` counts as an error, not as a latency sample.

Output: ``bench-<timestamp>.json`` (every number, the configuration and the hardware) and
``bench-<timestamp>.md`` (a table) in ``--out``. The hardware block records the CPU model,
logical cores, RAM, OS, Python and the SAJHA version and commit. The load generator runs on
the same machine as the server, so the two share the CPU: say so when citing the numbers.

Backends: ``memory`` (one worker only: several memory workers do not share sessions),
``database`` (a scratch SQLite file), ``redis`` (only when a server answers at
``--redis-url``; otherwise skipped with a note in the output) and ``pg`` (SAJHA's database and the
state store on PostgreSQL: a scratch database, created with SAJHA's schema and seed and dropped
afterwards, on the server named by the environment variable ``SAJHA_BENCH_PG_URL``; skipped when it
is unset; the URL is never printed or logged).

High concurrency (``--scenario highconc``): ``tools/call`` on both eras at each of ``--levels``
requests in flight (64, 256, 512 by default) against ``database:1,database:4,pg:1,pg:4``, with
``/health`` probed every half second during each phase and a pass/fail check (exit 2 on a fail):
no request unanswered or slower than ``--max-latency`` seconds, ``/health`` answering within
``--health-bound`` seconds throughout, and errors at most ``--max-error-rate`` of the requests.
A 503 with ``Retry-After`` (the server shedding load because its database pool stayed dry) is
counted apart ("shed"), not as an error. ``--check`` adds the same check to the standard scenario.

    .venv/bin/python tools/bench/bench.py --out /tmp/sajha-bench
    .venv/bin/python tools/bench/bench.py --configs memory:1,database:1,database:4 --duration 30
    .venv/bin/python tools/bench/bench.py --scenario highconc --out /tmp/sajha-bench

Dependencies: the standard library and httpx (already a SAJHA dependency).
Published results and how they were produced: docs/architecture/Scaling and State.md,
section "Measured performance".
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import platform
import random
import secrets
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
MODERN = "2026-07-28"
LEGACY = "2025-11-25"
TOOL = "calc_future_value"
META = {"io.modelcontextprotocol/protocolVersion": MODERN,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "sajha-bench", "version": "1"}}
ACCEPT = "application/json, text/event-stream"
PHASES = [("modern", "tools/list"), ("modern", "tools/call"), ("legacy", "tools/list"), ("legacy", "tools/call")]


# ── hardware and build ──────────────────────────────────────────────

def hardware() -> Dict[str, object]:
    cpu = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    ram_gb = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                ram_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
                break
    except OSError:
        pass
    return {"cpu": cpu, "logical_cores": os.cpu_count(), "ram_gb": ram_gb,
            "os": platform.platform(), "python": platform.python_version()}


def build_info() -> Dict[str, str]:
    version = ""
    try:
        text = (ROOT / "config" / "application.yml").read_text()
        in_app = False
        for line in text.splitlines():
            if line.startswith("app:"):
                in_app = True
            elif in_app and line.strip().startswith("version:"):
                version = line.split(":", 1)[1].split("#")[0].strip().strip("'\"")
                break
            elif in_app and line and not line.startswith((" ", "#")):
                in_app = False
    except OSError:
        pass
    commit = ""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        if dirty:
            commit += " (uncommitted changes)"
    except Exception:
        pass
    return {"sajha_version": version, "commit": commit}


# ── servers ─────────────────────────────────────────────────────────

def redis_reachable(url: str) -> bool:
    try:
        import redis  # optional
        redis.Redis.from_url(url, socket_connect_timeout=0.5).ping()
        return True
    except Exception:
        return False


def free_port(start: int, avoid=()) -> int:
    """The first free port from ``start`` on (not one of ``avoid``), else one the OS picks."""
    for port in range(max(1024, start), max(1024, start) + 200):
        if port not in avoid and port_free(port):
            return port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_free(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # uvicorn does the same; TIME_WAIT is fine
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def listeners(port: int) -> List[int]:
    """PIDs listening on 127.0.0.1:<port> (from ``ss -ltnp``)."""
    try:
        out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    pids = []
    for line in out.splitlines():
        if f":{port} " in line:
            for part in line.split("pid=")[1:]:
                pid = part.split(",", 1)[0]
                if pid.isdigit():
                    pids.append(int(pid))
    return pids


#: the API key the load clients send; written into the server's scratch key file only
BENCH_KEY = "sja_bench_" + secrets.token_hex(16)


def write_key_file(path: Path) -> None:
    path.write_text(json.dumps({"format": "sajha-persistent-apikeys/1", "keys": [{
        "id": "bench", "name": "Load harness", "key": BENCH_KEY, "owner": "bench", "owner_name": "Load harness",
        "roles": ["user"], "enabled": True, "expires_at": None, "tool_access_mode": "all",
        "tool_access_list": []}]}))


def server_env(scratch: Path, backend: str, redis_url: str, db_url: str = "",
               extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The server's environment: scratch files everywhere. ``backend`` ``pg`` means SAJHA's database and
    the state store on PostgreSQL (``db_url``, a scratch database); ``database`` a scratch SQLite file."""
    write_key_file(scratch / "apikeys.json")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SAJHA_", "DB_"))}
    if db_url:
        env.update({"SAJHA_DB_URL": db_url, "SAJHA_DB_TYPE": "postgresql"})
    env.update({
        "SAJHA_DB_PATH": str(scratch / "sajha.db"),
        "SAJHA_STATE_BACKEND": "database" if backend == "pg" else backend,
        "SAJHA_STATE_REDIS_URL": redis_url,
        "SAJHA_STATE_KEY_PREFIX": f"bench{secrets.token_hex(3)}:",
        "SAJHA_AI_RAG_PERSIST": "false",
        "SAJHA_AI_RAG_BUILD_ON_START": "false",
        "SAJHA_AI_RAG_STORES_SQLITE_VEC_PATH": str(scratch / "vectors.db"),
        "SAJHA_AUTH_USERS_FILE_PATH": str(scratch / "users.json"),
        "SAJHA_AUTH_API_KEYS_DB_DUMP_PATH": str(scratch / "apikeys_db.json"),
        "SAJHA_CONFIG_APIKEYS_PATH": str(scratch / "apikeys.json"),
        "SAJHA_AUTH_SECRETS_FILE": str(scratch / "secrets.json"),
        "SAJHA_CACHE_DIR": str(scratch / "cache"),
        "SAJHA_SNAPSHOTS_ENABLED": "false",
        "SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED": "false",
        "SAJHA_MCP_AUTH_MODE": "optional",
        "SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PATH": str(scratch / "signing_key.pem"),
        "SAJHA_LOGGING_DIR": str(scratch),
        "SAJHA_LOGGING_FILE": "app.log",
        "JWT_SECRET": "bench-jwt-" + "x" * 40,
        "SESSION_SECRET": "bench-session-" + "y" * 40,
        "PYTHONUNBUFFERED": "1",
    })
    env.update(extra or {})
    return env


# ── PostgreSQL (SAJHA_BENCH_PG_URL) ─────────────────────────────────

PG_ENV = "SAJHA_BENCH_PG_URL"


def _scrub(text: str, url: str) -> str:
    """``text`` without the PostgreSQL URL or its password (never printed or logged)."""
    if not url:
        return text
    try:
        from sqlalchemy.engine import make_url
        pw = make_url(url).password
    except Exception:
        pw = None
    text = text.replace(url, "<SAJHA_BENCH_PG_URL>")
    return text.replace(pw, "***") if pw else text


class ScratchPostgres:
    """A scratch database on the server ``SAJHA_BENCH_PG_URL`` points at, with SAJHA's schema and seed
    applied (SAJHA itself never runs DDL on PostgreSQL: Database Setup), dropped afterwards."""

    def __init__(self, url: str):
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
        self._text = text
        base = make_url(url)
        if base.drivername == "postgresql":
            base = base.set(drivername="postgresql+psycopg2")
        self.name = "sajha_bench_" + secrets.token_hex(4)
        self._admin = create_engine(base, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
        with self._admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{self.name}"'))
        self.url_obj = base.set(database=self.name)
        eng = create_engine(self.url_obj)
        try:
            root = ROOT / "db" / "scripts" / "postgresql"
            raw = eng.raw_connection()
            try:
                cur = raw.cursor()
                for f in ("schema.sql", "seed.sql"):
                    cur.execute((root / f).read_text())
                raw.commit()
            finally:
                raw.close()
        finally:
            eng.dispose()

    @property
    def url(self) -> str:
        return self.url_obj.render_as_string(hide_password=False)

    def drop(self) -> None:
        try:
            with self._admin.connect() as c:
                c.execute(self._text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        finally:
            self._admin.dispose()


class Server:
    def __init__(self, port: int, workers: int, env: Dict[str, str], log: Path):
        if not port_free(port):
            raise RuntimeError(f"port {port} is in use")
        self.port, self.workers = port, workers
        self.base = f"http://127.0.0.1:{port}"
        self.log = open(log, "wb")
        args = [sys.executable, "run_sajha_web.py", "--host", "127.0.0.1", "--port", str(port),
                "--log-level", "warning"]
        if workers > 1:
            args += ["--workers", str(workers)]
        self.proc = subprocess.Popen(args, cwd=str(ROOT), env=env, stdout=self.log, stderr=subprocess.STDOUT)

    def wait(self, timeout: float = 120) -> Dict[str, object]:
        end = time.time() + timeout
        seen = set()
        health: Dict[str, object] = {}
        with httpx.Client(timeout=5) as c:
            while time.time() < end:
                if self.proc.poll() is not None:
                    raise RuntimeError(f"server exited; see {self.log.name}")
                try:
                    r = c.get(self.base + "/health", headers={"Connection": "close"})
                    if r.status_code == 200:
                        health = r.json()
                        seen.add((health.get("state") or {}).get("worker_id"))
                        if len(seen) >= self.workers:
                            return health
                except httpx.HTTPError:
                    pass
                time.sleep(0.3)
        raise RuntimeError(f"server did not become ready; see {self.log.name}")

    def stop(self) -> None:
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
        end = time.time() + 10
        while time.time() < end and listeners(self.port):
            time.sleep(0.3)
        for pid in listeners(self.port):          # a worker that outlived its parent
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        self.log.close()


# ── load ────────────────────────────────────────────────────────────

class Client:
    """One logical MCP client (one coroutine): owns a legacy session when the era needs one."""

    def __init__(self, http: httpx.AsyncClient, era: str, key: str):
        self.http, self.era, self.key = http, era, key
        self.session: Optional[str] = None
        self.rid = 0
        self.last_error = ""       # why the last call counted as an error (HTTP status, JSON-RPC error)

    async def open(self) -> None:
        if self.era != "legacy":
            return
        r = await self.http.post("/mcp", json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": LEGACY, "capabilities": {}, "clientInfo": {"name": "sajha-bench", "version": "1"}}},
            headers={"Accept": ACCEPT, "Content-Type": "application/json", "X-API-Key": self.key})
        r.raise_for_status()
        self.session = r.headers.get("mcp-session-id")
        if not self.session:
            raise RuntimeError("initialize returned no Mcp-Session-Id")
        await self.http.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                             headers=self._headers("notifications/initialized"))

    def _headers(self, method: str, name: str = "") -> Dict[str, str]:
        h = {"Accept": ACCEPT, "Content-Type": "application/json", "X-API-Key": self.key}
        if self.era == "modern":
            h.update({"MCP-Protocol-Version": MODERN, "Mcp-Method": method})
            if name:
                h["Mcp-Name"] = name
        else:
            h.update({"MCP-Protocol-Version": LEGACY, "Mcp-Session-Id": self.session or ""})
        return h

    async def call(self, method: str) -> bool:
        self.rid += 1
        params: Dict[str, object] = {}
        name = ""
        if method == "tools/call":
            name = TOOL
            params = {"name": TOOL, "arguments": {"present_value": round(random.uniform(1, 1e6), 2),
                                                  "rate": round(random.uniform(0.1, 15), 3),
                                                  "years": random.randint(1, 40)}}
        if self.era == "modern":
            params["_meta"] = META
        r = await self.http.post("/mcp", json={"jsonrpc": "2.0", "id": self.rid, "method": method, "params": params},
                                 headers=self._headers(method, name))
        if r.status_code == 503 and r.headers.get("retry-after"):
            return "shed"                   # deliberate load shedding (a dry database pool): retryable
        if r.status_code != 200:
            self.last_error = f"HTTP {r.status_code}"
            return "error"
        body = _parse(r)
        if not isinstance(body, dict) or "result" not in body:
            err = body.get("error") if isinstance(body, dict) else None
            self.last_error = (f"JSON-RPC {err.get('code')}: {str(err.get('message'))[:60]}"
                               if isinstance(err, dict) else "no result")
            return "error"
        res = body["result"]
        if method == "tools/call":
            ok = not res.get("isError") and res.get("resultType", "complete") == "complete"
            if not ok:
                text = " ".join(b.get("text", "") for b in res.get("content") or [] if isinstance(b, dict))
                self.last_error = f"isError: {text[:60]}"
        else:
            ok = bool(res.get("tools"))
            if not ok:
                self.last_error = "empty tools/list"
        return "ok" if ok else "error"


def _parse(r: httpx.Response):
    if r.headers.get("content-type", "").startswith("text/event-stream"):
        last = None
        for line in r.text.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(msg, dict) and "id" in msg:
                    last = msg
        return last
    try:
        return r.json()
    except ValueError:
        return None


async def _drive(base: str, key: str, era: str, method: str, conc: int, warmup: float, duration: float,
                 timeout: float = 30.0):
    """One load process: ``conc`` clients in a loop. Returns (latencies of good calls in ms, errors, shed,
    hung, slowest call in ms). A call that gets no answer within ``timeout`` counts as hung."""
    limits = httpx.Limits(max_connections=conc, max_keepalive_connections=conc)
    lat: List[float] = []
    counts = {"error": 0, "shed": 0, "hung": 0}
    reasons: Dict[str, int] = {}
    slowest = 0.0
    async with httpx.AsyncClient(base_url=base, timeout=timeout, limits=limits) as http:
        clients = [Client(http, era, key) for _ in range(conc)]
        opened = await asyncio.gather(*(c.open() for c in clients), return_exceptions=True)
        for o in opened:
            if isinstance(o, BaseException):
                why = f"initialize: {type(o).__name__}"
                reasons[why] = reasons.get(why, 0) + 1
        clients = [c for c, o in zip(clients, opened) if not isinstance(o, BaseException)]
        counts["error"] += conc - len(clients)
        start = time.perf_counter()
        t_measure, t_end = start + warmup, start + warmup + duration

        async def loop(c: Client):
            nonlocal slowest
            while True:
                t0 = time.perf_counter()
                if t0 >= t_end:
                    return
                try:
                    outcome = await c.call(method)
                except httpx.TimeoutException:
                    outcome = "hung"
                except Exception as e:
                    outcome = "error"
                    c.last_error = type(e).__name__
                t1 = time.perf_counter()
                if t0 >= t_measure:
                    slowest = max(slowest, (t1 - t0) * 1000.0)
                    if outcome == "ok":
                        if t1 <= t_end:
                            lat.append((t1 - t0) * 1000.0)
                    else:
                        counts[outcome] += 1
                        if outcome == "error":
                            reasons[c.last_error] = reasons.get(c.last_error, 0) + 1
                if outcome == "shed":
                    await asyncio.sleep(0.05)       # a client honouring Retry-After backs off a little

        await asyncio.gather(*(loop(c) for c in clients))
    return lat, counts["error"], counts["shed"], counts["hung"], slowest, reasons


def _proc(args):
    return asyncio.run(_drive(*args))


def percentile(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


class HealthProbe:
    """Asks ``/health`` every ``interval`` seconds while a phase runs (its own connection each time) and
    records how long each answer took; a probe with no answer within ``timeout`` is a failure."""

    def __init__(self, base: str, interval: float = 0.5, timeout: float = 10.0):
        import threading
        self.base, self.interval, self.timeout = base, interval, timeout
        self.latencies: List[float] = []
        self.failures = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                r = httpx.get(self.base + "/health", timeout=self.timeout, headers={"Connection": "close"})
                if r.status_code == 200:
                    self.latencies.append((time.perf_counter() - t0) * 1000.0)
                else:
                    self.failures += 1
            except httpx.HTTPError:
                self.failures += 1
            self._stop.wait(self.interval)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(self.timeout + 5)

    def summary(self) -> Dict[str, object]:
        return {"probes": len(self.latencies) + self.failures, "failures": self.failures,
                "max_ms": round(max(self.latencies), 2) if self.latencies else None}


def run_phase(base: str, era: str, method: str, concurrency: int, clients: int, warmup: float,
              duration: float, timeout: float = 30.0, probe_health: bool = False) -> Dict[str, object]:
    clients = max(1, min(clients, concurrency))
    load_before = round(os.getloadavg()[0], 2) if hasattr(os, "getloadavg") else None
    share = [concurrency // clients + (1 if i < concurrency % clients else 0) for i in range(clients)]
    ctx = mp.get_context("spawn")
    probe = HealthProbe(base, timeout=min(timeout, 10.0)) if probe_health else None
    if probe:
        probe.__enter__()
    try:
        with ctx.Pool(clients) as pool:
            results = pool.map(_proc, [(base, BENCH_KEY, era, method, n, warmup, duration, timeout) for n in share])
    finally:
        if probe:
            probe.__exit__(None, None, None)
    lat = sorted(x for r in results for x in r[0])
    errors = sum(r[1] for r in results)
    reasons: Dict[str, int] = {}
    for r in results:
        for k, v in r[5].items():
            reasons[k] = reasons.get(k, 0) + v
    out = {"era": era, "method": method, "concurrency": concurrency, "requests": len(lat), "errors": errors,
           "shed": sum(r[2] for r in results), "hung": sum(r[3] for r in results),
           "slowest_ms": round(max(r[4] for r in results), 2),
           "throughput_rps": round(len(lat) / duration, 1),
           "p50_ms": round(percentile(lat, 0.50), 2), "p95_ms": round(percentile(lat, 0.95), 2),
           "p99_ms": round(percentile(lat, 0.99), 2),
           "mean_ms": round(statistics.fmean(lat), 2) if lat else None,
           "loadavg_1m_before": load_before,       # other work on the machine skews the numbers
           "error_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:5])}
    if probe:
        out["health"] = probe.summary()
    return out


def judge(ph: Dict[str, object], max_latency_s: float, max_error_rate: float, health_bound_s: float) -> List[str]:
    """Why a phase fails the pass/fail check ([] = it passes): a request hung or answered later than the
    bound, /health failed or answered later than its bound, or errors (deliberate 503 shedding excluded)
    exceeded the threshold."""
    why = []
    if ph["hung"]:
        why.append(f"{ph['hung']} request(s) got no answer within {max_latency_s:g} s")
    if ph["slowest_ms"] > max_latency_s * 1000:
        why.append(f"slowest request {ph['slowest_ms'] / 1000:.1f} s > {max_latency_s:g} s")
    h = ph.get("health") or {}
    if h.get("failures"):
        why.append(f"/health failed {h['failures']} time(s)")
    if not h.get("probes"):
        why.append("/health was not probed")
    elif h.get("max_ms") is not None and h["max_ms"] > health_bound_s * 1000:
        why.append(f"/health took {h['max_ms'] / 1000:.1f} s > {health_bound_s:g} s")
    total = ph["requests"] + ph["errors"] + ph["hung"]
    if total and ph["errors"] / total > max_error_rate:
        why.append(f"error rate {ph['errors'] / total:.2%} > {max_error_rate:.2%}")
    if not ph["requests"]:
        why.append("no request succeeded")
    return why


# ── report ──────────────────────────────────────────────────────────

def markdown(report: Dict[str, object]) -> str:
    hw, b, p = report["hardware"], report["build"], report["parameters"]
    high = p.get("scenario") == "highconc"
    load = (f"concurrency levels {', '.join(str(x) for x in p['levels'])}" if high
            else f"{p['concurrency']} requests in flight")
    lines = [f"SAJHA load harness, {report['date']}",
             "",
             f"Hardware: {hw['cpu']}, {hw['logical_cores']} logical cores, {hw['ram_gb']} GB RAM; "
             f"{hw['os']}; Python {hw['python']}. SAJHA {b['sajha_version']} at {b['commit']}.",
             f"Load: {load} from {p['clients']} load processes on the same machine; "
             f"{p['warmup_s']} s warm-up, {p['duration_s']} s measured per row; tool `{TOOL}` with new arguments "
             f"on every call (no cache hits). Load average (1 min) before the run: {report.get('loadavg_start')}.",
             ""]
    if high:
        lines += [f"Check: no request unanswered or slower than {p['max_latency_s']} s, /health answering within "
                  f"{p['health_bound_s']} s throughout, errors (503 shedding excluded) at most "
                  f"{p['max_error_rate']:.1%}. Verdict: **{report.get('verdict', 'n/a')}**.", "",
                  "| Database | Workers | Era | In flight | Requests | Shed (503) | Errors | Hung | Throughput (req/s) "
                  "| p50 (ms) | p99 (ms) | Slowest (ms) | /health max (ms) | Load avg | Check |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    else:
        lines += ["| Backend | Workers | Era | Method | Requests | Errors | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
    for s in report["scenarios"]:
        db = "PostgreSQL" if s["backend"] == "pg" else ("SQLite" if s["backend"] == "database" else s["backend"])
        if s.get("skipped"):
            lines.append(f"| {db if high else s['backend']} | {s['workers']} | skipped: {s['skipped']} |")
            continue
        if s.get("error"):
            lines.append(f"| {db if high else s['backend']} | {s['workers']} | failed: {s['error']} |")
            continue
        for ph in s["phases"]:
            era = f"{ph['era']} ({MODERN if ph['era'] == 'modern' else LEGACY})"
            if high:
                h = ph.get("health") or {}
                verdict = "pass" if not ph.get("check") else "FAIL: " + "; ".join(ph["check"])
                lines.append(f"| {db} | {s['workers']} | {era} | {ph['concurrency']} | {ph['requests']} | {ph['shed']} | "
                             f"{ph['errors']} | {ph['hung']} | {ph['throughput_rps']} | {ph['p50_ms']} | {ph['p99_ms']} | "
                             f"{ph['slowest_ms']} | {h.get('max_ms')} | {ph['loadavg_1m_before']} | {verdict} |")
            else:
                lines.append(f"| {s['backend']} | {s['workers']} | {era} | {ph['method']} | {ph['requests']} | "
                             f"{ph['errors']} | {ph['throughput_rps']} | {ph['p50_ms']} | {ph['p95_ms']} | {ph['p99_ms']} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=("standard", "highconc"), default="standard",
                    help="standard: the four phases at --concurrency; highconc: tools/call on both eras at each "
                         "of --levels, /health probed throughout, with the pass/fail check")
    ap.add_argument("--configs", default=None,
                    help="backend:workers, comma separated (memory accepts 1 worker only; pg = PostgreSQL from "
                         f"${PG_ENV}, skipped when unset). Default: memory:1,database:1,database:4,redis:1,redis:4 "
                         "(standard), database:1,database:4,pg:1,pg:4 (highconc)")
    ap.add_argument("--duration", type=float, default=None, help="measured seconds per phase (20; highconc 10)")
    ap.add_argument("--warmup", type=float, default=None, help="unmeasured seconds before each phase (3; highconc 2)")
    ap.add_argument("--concurrency", type=int, default=32, help="requests in flight (standard)")
    ap.add_argument("--levels", default="64,256,512", help="requests in flight, comma separated (highconc)")
    ap.add_argument("--clients", type=int, default=4, help="load-generator processes")
    ap.add_argument("--port", type=int, default=3151, help="first port; each configuration takes the next one")
    ap.add_argument("--redis-url", default=os.environ.get("SAJHA_TEST_REDIS_URL", "redis://127.0.0.1:6379/15"))
    ap.add_argument("--phases", default="all", help="all, or a comma list of era:method (modern:tools/call,...)")
    ap.add_argument("--check", action="store_true", help="pass/fail: exit 2 when a phase fails the check "
                                                         "(always on for highconc)")
    ap.add_argument("--max-latency", type=float, default=30.0,
                    help="seconds: a request unanswered (or answered) later than this fails the check")
    ap.add_argument("--max-error-rate", type=float, default=0.01, help="errors / requests allowed, 503 shedding excluded")
    ap.add_argument("--health-bound", type=float, default=5.0, help="seconds /health may take during a phase")
    ap.add_argument("--pool-size", type=int, default=None, help="db.pool.size of the server (default: its own)")
    ap.add_argument("--pool-timeout", type=float, default=None, help="db.pool.timeout_seconds of the server")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "sajha-bench"))
    ap.add_argument("--scratch", default=None, help="parent folder of each server's scratch folder (default: the temp dir)")
    ap.add_argument("--keep-scratch", action="store_true", help="keep each server's scratch folder and log")
    a = ap.parse_args(argv)

    high = a.scenario == "highconc"
    check = a.check or high
    configs = a.configs or ("database:1,database:4,pg:1,pg:4" if high else "memory:1,database:1,database:4,redis:1,redis:4")
    duration = a.duration if a.duration is not None else (10.0 if high else 20.0)
    warmup = a.warmup if a.warmup is not None else (2.0 if high else 3.0)
    if a.phases != "all":
        phases = [tuple(x.split(":", 1)) for x in a.phases.split(",")]
    else:
        phases = [("modern", "tools/call"), ("legacy", "tools/call")] if high else PHASES
    levels = [int(x) for x in a.levels.split(",") if x.strip()] if high else [a.concurrency]
    extra: Dict[str, str] = {}
    if a.pool_size is not None:
        extra["SAJHA_DB_POOL_SIZE"] = str(a.pool_size)
    if a.pool_timeout is not None:
        extra["SAJHA_DB_POOL_TIMEOUT_SECONDS"] = str(a.pool_timeout)
    pg_url = os.environ.get(PG_ENV, "").strip()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report: Dict[str, object] = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "hardware": hardware(), "build": build_info(),
        "loadavg_start": [round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else None,
        "parameters": {"scenario": a.scenario, "duration_s": duration, "warmup_s": warmup,
                       "concurrency": a.concurrency, "levels": levels, "clients": a.clients, "tool": TOOL,
                       "max_latency_s": a.max_latency, "max_error_rate": a.max_error_rate,
                       "health_bound_s": a.health_bound, "pool_size": a.pool_size, "pool_timeout_s": a.pool_timeout},
        "scenarios": []}
    port = a.port
    failed_checks = 0
    for spec in [c.strip() for c in configs.split(",") if c.strip()]:
        backend, _, w = spec.partition(":")
        workers = int(w or 1)
        scen: Dict[str, object] = {"backend": backend, "workers": workers}
        report["scenarios"].append(scen)
        if backend == "memory" and workers > 1:
            scen["skipped"] = "memory is one worker only (sessions and tasks are per process)"
            continue
        if backend == "redis" and not redis_reachable(a.redis_url):
            scen["skipped"] = f"no Redis server answered at {a.redis_url}"
            print(f"[bench] {spec}: skipped ({scen['skipped']})", flush=True)
            continue
        if backend == "pg" and not pg_url:
            scen["skipped"] = f"{PG_ENV} is not set"
            print(f"[bench] {spec}: skipped ({scen['skipped']})", flush=True)
            continue
        scratch = Path(tempfile.mkdtemp(prefix=f"sajha-bench-{backend}{workers}-", dir=a.scratch))
        pg = None
        srv = None
        try:
            if backend == "pg":
                pg = ScratchPostgres(pg_url)
            print(f"[bench] {spec}: starting on port {port} (scratch {scratch})", flush=True)
            srv = Server(port, workers, server_env(scratch, backend, a.redis_url, pg.url if pg else "", extra),
                         scratch / "server.log")
            health = srv.wait()
            scen["state"] = health.get("state")
            scen["phases"] = []
            for conc in levels:
                for era, method in phases:
                    ph = run_phase(srv.base, era, method, conc, a.clients, warmup, duration,
                                   timeout=a.max_latency, probe_health=check)
                    if check:
                        ph["check"] = judge(ph, a.max_latency, a.max_error_rate, a.health_bound)
                        failed_checks += bool(ph["check"])
                    scen["phases"].append(ph)
                    h = ph.get("health") or {}
                    print(f"[bench]   {era:6} {method:10} x{conc:<4} {ph['throughput_rps']:>8} req/s  "
                          f"p50 {ph['p50_ms']} ms  p99 {ph['p99_ms']} ms  slowest {ph['slowest_ms']} ms  "
                          f"errors {ph['errors']}  shed {ph['shed']}  hung {ph['hung']}"
                          + (f"  /health max {h.get('max_ms')} ms" if h else "")
                          + (f"  ({ph['error_reasons']})" if ph.get("error_reasons") else "")
                          + (("  FAIL: " + "; ".join(ph["check"])) if ph.get("check") else ""), flush=True)
        except Exception as e:
            scen["error"] = _scrub(str(e), pg_url)
            print(f"[bench] {spec}: failed: {scen['error']}", flush=True)
        finally:
            if srv is not None:
                srv.stop()
            if pg is not None:
                try:
                    pg.drop()
                except Exception as e:
                    print(f"[bench] {spec}: scratch database not dropped: {_scrub(str(e), pg_url)}", flush=True)
            if not a.keep_scratch and "error" not in scen:
                shutil.rmtree(scratch, ignore_errors=True)
        port += 1
    if check:
        report["verdict"] = "pass" if not failed_checks and not any("error" in s for s in report["scenarios"]) \
            else "fail"
    (out / f"bench-{stamp}.json").write_text(json.dumps(report, indent=2))
    (out / f"bench-{stamp}.md").write_text(markdown(report))
    print(f"[bench] wrote {out / f'bench-{stamp}.json'} and {out / f'bench-{stamp}.md'}", flush=True)
    if any("error" in s for s in report["scenarios"]):
        return 1
    return 2 if check and failed_checks else 0


if __name__ == "__main__":
    sys.exit(main())
