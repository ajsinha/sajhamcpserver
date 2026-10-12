# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Failure tests: the documented failure behaviour of docs/architecture/Scaling and State.md §7,
exercised rather than described (Roadmap X14).

* the state store lost
    - at start-up: a shared backend that does not answer stops start-up (redis at a closed
      port; database at a path that cannot be opened), never a silent fallback;
    - at run time (redis, simulated with fakeredis's ``connected = False``): requests that touch
      shared state fail with HTTP 500, ``/health`` reports ``state.reachable: false``, nothing
      falls back to per-process state, and everything works again when the store is back;
    - at run time (database): store operations raise while the database cannot be opened and
      the data is intact when it can again.
* a worker killed mid-task: two real server processes share a SQLite state database; the task's
  worker is killed with SIGKILL; the other worker reports the task ``failed`` with -32603 once
  the dead worker's heartbeat is gone, and never re-runs it.
* an upstream federated server broken: its tools stay listed, calls fail fast, the circuit
  breaker opens after the threshold and stops calls reaching the upstream, and a probe after
  the recovery timeout closes it once the upstream is back.
* the database pool under concurrent calls: more slow calls in flight than the pool has
  connections (REST tool endpoint, OpenAI-compatible chat, A2A) all complete, and ``/health``
  answers throughout, because no request holds a connection across its slow work.

Each test is bounded (explicit timeouts) and isolated (its own scratch folder, key prefix and
ports). Marker: ``failure`` (``pytest -m failure``). Set SAJHA_SKIP_MULTIPROCESS_TESTS=1 to skip
the tests that start server processes.
"""

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")

pytestmark = pytest.mark.failure

ROOT = Path(__file__).resolve().parent.parent
V = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": V,
        "io.modelcontextprotocol/clientCapabilities": {"extensions": {"io.modelcontextprotocol/tasks": {}}},
        "io.modelcontextprotocol/clientInfo": {"name": "pytest-failure", "version": "1"}}
multiprocess = pytest.mark.skipif(os.environ.get("SAJHA_SKIP_MULTIPROCESS_TESTS") == "1",
                                  reason="SAJHA_SKIP_MULTIPROCESS_TESTS=1")


# ── server processes ────────────────────────────────────────────────

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(tmp, backend, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SAJHA_")}
    env.update({
        "SAJHA_DB_PATH": str(tmp / "sajha.db"),
        "SAJHA_STATE_BACKEND": backend,
        "SAJHA_STATE_KEY_PREFIX": f"fail{secrets.token_hex(4)}:",
        "SAJHA_STATE_DATABASE_POLL_INTERVAL_MS": "100",
        "SAJHA_MCP_CONFORMANCE_FIXTURES": "true",
        "SAJHA_AI_RAG_PERSIST": "false",
        "SAJHA_AI_RAG_BUILD_ON_START": "false",
        "SAJHA_AI_RAG_STORES_SQLITE_VEC_PATH": str(tmp / "vectors.db"),
        "SAJHA_AUTH_USERS_FILE_PATH": str(tmp / "users.json"),
        "SAJHA_AUTH_API_KEYS_DB_DUMP_PATH": str(tmp / "apikeys_db.json"),
        "SAJHA_CONFIG_APIKEYS_PATH": str(tmp / "apikeys.json"),
        "SAJHA_AUTH_SECRETS_FILE": str(tmp / "secrets.json"),
        "SAJHA_CACHE_DIR": str(tmp / "cache"),
        "SAJHA_SNAPSHOTS_ENABLED": "false",
        "SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED": "false",
        "SAJHA_MCP_AUTH_MODE": "optional",
        "SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PATH": str(tmp / "signing_key.pem"),
        "SAJHA_LOGGING_DIR": str(tmp),
        "SAJHA_LOGGING_FILE": "app.log",
        "JWT_SECRET": "failure-test-jwt-" + "x" * 32,
        "SESSION_SECRET": "failure-test-session-" + "y" * 32,
        "PYTHONUNBUFFERED": "1",
    })
    env.update(extra)
    return env


class Server:
    def __init__(self, env, tmp, name):
        self.tmp = tmp
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.log_path = tmp / f"{name}.log"
        self.log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, "run_sajha_web.py", "--host", "127.0.0.1", "--port", str(self.port),
             "--log-level", "warning"], cwd=str(ROOT), env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.client = httpx.Client(base_url=self.base, timeout=20)

    def wait(self, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited: see {self.log_path}")
            try:
                if self.client.get("/health").status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"server did not start: see {self.log_path}")

    def stop(self):
        self.client.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)
        self.log.close()


def _modern(server, method, params=None, name=None):
    headers = {"MCP-Protocol-Version": V, "Mcp-Method": method, "Accept": "application/json, text/event-stream"}
    if name:
        headers["Mcp-Name"] = name
    r = server.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method,
                                         "params": dict(params or {}, _meta=META)}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, body
    return body["result"]


# ── 1. the state store lost ─────────────────────────────────────────

@multiprocess
@pytest.mark.parametrize("backend", ["redis", "database"])
def test_unreachable_shared_store_stops_start_up(backend, tmp_path):
    """§6/§7: a shared store that does not answer at start-up stops the server; it never starts
    on per-process state instead."""
    if backend == "redis":
        pytest.importorskip("redis")
        extra = {"SAJHA_STATE_REDIS_URL": f"redis://127.0.0.1:{_free_port()}/0"}      # nothing listens
    else:
        extra = {"SAJHA_STATE_DATABASE_URL": f"sqlite:///{tmp_path / 'no-such-dir' / 'state.db'}"}
    srv = Server(_env(tmp_path, backend, **extra), tmp_path, f"down-{backend}")
    try:
        code = srv.proc.wait(120)
    except subprocess.TimeoutExpired:
        pytest.fail(f"the server kept running with an unreachable {backend} store: see {srv.log_path}")
    finally:
        srv.stop()
    log = srv.log_path.read_text(errors="replace")
    assert code != 0, log[-2000:]
    assert "refusing to start" in log, log[-2000:]


@pytest.fixture
def lost_redis(web):
    """The session app (``web``) on a fakeredis-backed state store, with a switch to stop it."""
    fakeredis = pytest.importorskip("fakeredis")
    pytest.importorskip("lupa")
    from sajha.core import state as st
    from sajha.core.mcp_sessions import get_session_store
    from sajha.core.state.redis_store import RedisStateStore
    server = fakeredis.FakeServer()
    store = RedisStateStore("redis://fake", f"lost{secrets.token_hex(3)}:",
                            client=fakeredis.FakeRedis(server=server, decode_responses=True))
    saved = (st._store, st._task_store)
    sessions = get_session_store()
    saved_shared = sessions._shared
    st.set_state_store(store, saved[1] or st.get_task_record_store())
    sessions.attach_store(store)
    try:
        yield web[0], server, store
    finally:
        server.connected = True
        sessions.detach_store()
        if saved_shared is not None:
            sessions.attach_store(saved_shared)
        st.set_state_store(*saved)
        store.close()


def _initialize(client, api_key=None):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}}})


def _ping(client, sid):
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25",
               "Mcp-Session-Id": sid}
    return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "ping"})


def test_redis_lost_at_run_time_fails_requests_and_recovers(lost_redis):
    """§7 "Redis unavailable at runtime": requests that touch shared state fail with HTTP 500
    until Redis is back; nothing falls back to per-process state."""
    from fastapi.testclient import TestClient
    client, server, store = lost_redis
    c = TestClient(client.app, raise_server_exceptions=False)        # see the 500, as a client would
    r = _initialize(c)
    assert r.status_code == 200, r.text
    sid = r.headers["mcp-session-id"]
    assert store.get(f"mcp:session:{sid}") is not None                # the session is in the shared store

    server.connected = False                                         # Redis stops
    from redis.exceptions import ConnectionError as RedisConnectionError
    with pytest.raises(RedisConnectionError):
        store.get("anything")                                       # no silent per-process fallback
    assert c.get("/health").json()["state"]["reachable"] is False
    down = _initialize(c)
    assert down.status_code == 500, down.text                       # a new session needs the store
    assert "mcp-session-id" not in down.headers

    server.connected = True                                          # Redis is back
    assert c.get("/health").json()["state"]["reachable"] is True
    assert _ping(c, sid).status_code == 200                          # the session made before survived
    again = _initialize(c)
    assert again.status_code == 200 and again.headers.get("mcp-session-id")


def test_database_store_lost_at_run_time_raises_then_recovers(tmp_path):
    """The database backend's operations raise while its database cannot be opened (no fallback),
    and the rows written before are there when it can be opened again."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    from sajha.core.state.database import DatabaseStateStore
    home = tmp_path / "state"
    home.mkdir()
    engine = create_engine(f"sqlite:///{home / 'state.db'}", poolclass=NullPool)   # a new connection per use
    store = DatabaseStateStore(engine=engine, prefix="lostdb:")
    try:
        store.set("k", {"v": 1})
        assert store.ping()
        home.rename(tmp_path / "state.away")                        # the database goes away
        assert store.ping() is False
        with pytest.raises(Exception):
            store.get("k")
        with pytest.raises(Exception):
            store.set("k2", {"v": 2})
        (tmp_path / "state.away").rename(home)                      # and comes back
        assert store.ping()
        assert store.get("k") == {"v": 1}
        assert store.get("k2") is None                               # the failed write did not land anywhere
    finally:
        store.close()
        engine.dispose()


# ── 2. a worker killed mid-task ─────────────────────────────────────

@multiprocess
def test_worker_killed_mid_task_orphans_the_task(tmp_path):
    """§4.4 Orphans: a working task whose worker has no heartbeat is failed with -32603 when read,
    and never re-run on another worker."""
    from sqlalchemy import create_engine
    from sajha.core.mcp_tasks import ORPHANED_MESSAGE
    from sajha.core.state.database import DatabaseStateStore
    env = _env(tmp_path, "database")
    a = Server(env, tmp_path, "a").wait()          # A first: it creates the SQLite schema
    b = Server(env, tmp_path, "b").wait()
    engine = create_engine(f"sqlite:///{tmp_path / 'sajha.db'}")
    store = DatabaseStateStore(engine=engine, prefix=env["SAJHA_STATE_KEY_PREFIX"])
    try:
        a_worker = a.client.get("/health").json()["state"]["worker_id"]
        created = _modern(a, "tools/call", {"name": "slow_compute", "arguments": {"seconds": 60}},
                          name="slow_compute")
        assert created["resultType"] == "task"
        tid = created["taskId"]
        assert _modern(b, "tasks/get", {"taskId": tid}, name=tid)["status"] == "working"

        a.proc.send_signal(signal.SIGKILL)                            # the worker dies mid-task
        a.proc.wait(10)
        # its heartbeat has not expired yet: the task is still reported working, not failed early
        assert store.get(f"worker:{a_worker}") is not None
        assert _modern(b, "tasks/get", {"taskId": tid}, name=tid)["status"] == "working"

        store.delete(f"worker:{a_worker}")                            # the heartbeat TTL runs out
        got = _modern(b, "tasks/get", {"taskId": tid}, name=tid)
        assert got["status"] == "failed", got
        assert got.get("statusMessage") == ORPHANED_MESSAGE, got
        rec = store.get(f"mcp:task:{tid}") or {}
        assert rec.get("status") == "failed" and (rec.get("error") or {}).get("code") == -32603, rec

        time.sleep(1.0)                                               # never re-run elsewhere
        assert _modern(b, "tasks/get", {"taskId": tid}, name=tid)["status"] == "failed"
    finally:
        engine.dispose()
        a.stop()
        b.stop()


# ── 3. an upstream federated server broken ──────────────────────────

def test_broken_upstream_opens_the_breaker_and_recovers(tmp_path, monkeypatch):
    """Federation §8 and Scaling and State §7: tools of an upstream that went away stay listed,
    calls fail fast, the breaker opens after the threshold (calls stop reaching the upstream), and
    a probe after the recovery timeout closes it once the upstream answers again."""
    pytest.importorskip("mcp.server.mcpserver")
    monkeypatch.setenv("SAJHA_POLICY_ENABLED", "false")
    from tests.test_federation import Registry, Upstream, wait_for
    from sajha.core.circuit_breaker import get_circuit_registry
    from sajha.federation.config import FederationSettings
    from sajha.federation.manager import FederationManager
    from sajha.federation.store import FederationStore

    up = Upstream()
    port = up.port
    prefix = f"brk{secrets.token_hex(2)}"
    settings = FederationSettings(enabled=True, allow_localhost=True, require_approval=False,
                                  startup_wait_seconds=10, default_timeout_seconds=2,
                                  upstreams=[{"id": prefix, "url": up.url, "prefix": prefix,
                                              "breaker": {"failure_threshold": 2, "recovery_timeout": 1}}])
    reg = Registry()
    m = FederationManager(reg, settings, FederationStore(str(tmp_path / "fed.json")))
    m.start()
    name = f"{prefix}__celsius_to_fahrenheit"
    try:
        tool = reg.tools[name]
        assert tool.execute_with_tracking({"celsius": 100})["structuredContent"] == {"result": 212.0}
        breaker = get_circuit_registry().get_breaker(name)
        assert breaker is not None and breaker.state.value == "closed"

        up._uv.force_exit = True                                      # the upstream breaks (at once: no
        up.stop()                                                     # graceful wait for open streams)
        for _ in range(2):
            t0 = time.time()
            with pytest.raises(Exception):
                tool.execute_with_tracking({"celsius": 1})
            assert time.time() - t0 < 8                               # fails fast, bounded by the timeout
        assert breaker.state.value == "open"
        calls = m.status(prefix)["calls"]
        t0 = time.time()
        with pytest.raises(RuntimeError, match="circuit breaker open"):
            tool.execute_with_tracking({"celsius": 2})
        assert time.time() - t0 < 1.0                                 # open: no network at all
        assert m.status(prefix)["calls"] == calls                     # never reached the upstream
        assert name in reg.tools and any(t["name"] == name for t in reg.get_all_tools())   # still listed

        up = Upstream(port=port)                                      # the upstream is back
        m._upstreams[prefix].conn.kick()                             # reconnect now, not after the backoff
        assert wait_for(lambda: m.status(prefix)["state"] == "connected", 30), m.status(prefix)
        time.sleep(1.2)                                               # past recovery_timeout: half-open
        assert tool.execute_with_tracking({"celsius": 0})["structuredContent"] == {"result": 32.0}
        assert breaker.state.value == "closed"
    finally:
        m.stop()
        up.stop()


# ── 4. the database pool under concurrent calls ─────────────────────

def test_mcp_identity_gives_the_database_connection_back():
    """§7 "Database connections and concurrent calls": once the call path has the caller's
    identity and tool policy (``to_legacy_session``), the request's database session is closed,
    so a request never holds a pool connection while its call runs or its stream is open (with
    pool-size requests in flight, the next request's authentication blocked the event loop)."""
    from sajha.auth import AuthContext

    class Session:
        closed = 0

        def close(self):
            Session.closed += 1

        def query(self, *a, **k):            # the anonymous policy may look up roles
            raise RuntimeError("no database in this test")

    out = AuthContext(authenticated=False, _db=Session()).to_legacy_session()
    assert isinstance(out, dict)
    assert Session.closed == 1


POOL_SIZE = 3            # the database pool in the test below: smaller than the calls in flight
POOL_TIMEOUT = 2.0       # seconds a request waits for a pool connection before it fails
SLOW = 2.5               # seconds each call takes: longer than the pool timeout
PER_ENDPOINT = 4         # calls in flight on each of the three endpoints (12 > POOL_SIZE)
SLOW_TOOL = "zz_pool_slow_tool"


@pytest.fixture
def small_pool_app(monkeypatch):
    """A started app whose database pool holds POOL_SIZE connections (no overflow), a slow
    registry tool, a slow mock model behind /v1/chat/completions, and an administrator-owned
    API key (the owned-key path commits on sign-in, the hardest case for releasing early)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setenv("SAJHA_AI_OPENAI_API_ENABLED", "true")
    monkeypatch.setenv("SAJHA_POLICY_ENABLED", "false")
    from sajha.app import create_app
    from sajha.db import engine as eng
    from sajha.tools.base_mcp_tool import BaseMCPTool

    class Slow(BaseMCPTool):
        def __init__(self):
            super().__init__({"name": SLOW_TOOL, "description": "sleeps (pool test)",
                              "inputSchema": {"type": "object", "properties": {}}})

        def get_input_schema(self):
            return self._input_schema

        def get_output_schema(self):
            return {}

        def execute(self, arguments):
            time.sleep(SLOW)
            return {"slept": SLOW, "i": arguments.get("i")}

    with TestClient(create_app()) as c:
        small = create_engine(eng._engine.url, pool_size=POOL_SIZE, max_overflow=0, pool_timeout=POOL_TIMEOUT,
                              connect_args={"check_same_thread": False, "timeout": 30})
        eng._engine, eng._SessionLocal = small, sessionmaker(autocommit=False, autoflush=False, bind=small)
        # (the autouse _keep_the_database_engine fixture puts the app's engine back and disposes this one)
        from sajha.app import tools_registry
        tools_registry.register_tool(Slow())
        from sajha.ai import openai_api
        real_chat_create = openai_api.chat_create

        def slow_chat_create(req):
            time.sleep(SLOW)
            return real_chat_create(req)

        monkeypatch.setattr(openai_api, "chat_create", slow_chat_create)
        from sajha.auth import apikeys as keys
        from sajha.db.dao import UserDAO
        db = eng.get_db_session()
        try:
            _, raw = keys.create_key(db, name="pool-" + secrets.token_hex(3), created_by="test",
                                     owner=UserDAO(db).get_by_user_id("admin"))
        finally:
            db.close()
        try:
            yield c, raw
        finally:
            tools_registry.unregister_tool(SLOW_TOOL)


def test_concurrent_slow_calls_never_exhaust_the_database_pool(small_pool_app):
    """§7 "Database connections and concurrent calls", end to end: more slow calls in flight than
    the pool has connections, on the REST tool endpoint, the OpenAI-compatible chat endpoint and
    A2A at once. A request gives its connection back before it awaits the slow work, so every call
    completes in about one call's time (a request that held its connection made the later ones
    wait past the pool timeout and fail), and /health answers throughout (the A2A tool used to run
    on the event loop)."""
    from concurrent.futures import ThreadPoolExecutor
    import threading
    c, key = small_pool_app

    def rest(i):
        r = c.post("/api/tools/execute", headers={"X-API-Key": key},
                   json={"tool": SLOW_TOOL, "arguments": {"i": i}})
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True, r.text
        return "rest"

    def chat(i):
        r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": "default", "messages": [{"role": "user", "content": f"hello {i}"}]})
        assert r.status_code == 200, r.text
        assert r.json()["choices"], r.text
        return "chat"

    def a2a(i):
        r = c.post("/a2a", headers={"X-API-Key": key}, json={
            "jsonrpc": "2.0", "id": i, "method": "tasks/send",
            "params": {"message": {"parts": [{"type": "text", "text": SLOW_TOOL}]}}})
        assert r.status_code == 200, r.text
        assert r.json().get("result", {}).get("status", {}).get("state") == "completed", r.text
        return "a2a"

    done = threading.Event()
    health = []

    def probe():
        while not done.is_set():
            t0 = time.time()
            assert c.get("/health").status_code == 200
            health.append(time.time() - t0)
            time.sleep(0.1)

    calls = [(f, i) for i in range(PER_ENDPOINT) for f in (rest, chat, a2a)]
    with ThreadPoolExecutor(max_workers=len(calls) + 1) as pool:
        prober = pool.submit(probe)
        t0 = time.time()
        futures = [pool.submit(f, i) for f, i in calls]
        try:
            results = [f.result(timeout=60) for f in futures]
        finally:
            elapsed = time.time() - t0
            done.set()
        prober.result(timeout=10)
    assert sorted(results) == sorted(f.__name__ for f, _ in calls)
    # in parallel, not one pool's worth at a time (that would take ceil(12 / 3) * SLOW = 10 s)
    assert elapsed < SLOW + 5, f"{len(calls)} calls took {elapsed:.1f}s"
    assert health and max(health) < 1.0, f"/health took up to {max(health):.2f}s under load"


def test_slo_rules_match_the_documented_objectives():
    """Observability §6 names the SLO alert rules; the shipped rule file has exactly those."""
    import re
    import yaml
    rules = yaml.safe_load((ROOT / "deployment/observability/sajha-alerts.yml").read_text(encoding="utf-8"))
    slo = next(g for g in rules["groups"] if g["name"] == "sajha-slo")
    shipped = {r["alert"] for r in slo["rules"]}
    guide = (ROOT / "docs/architecture/Observability.md").read_text(encoding="utf-8")
    section = guide.split("## 6. Service level objectives", 1)[1].split("\n## ", 1)[0]
    assert shipped == set(re.findall(r"`(SajhaSlo\w+)`", section))
    assert all(r["labels"].get("slo") for r in slo["rules"])


@multiprocess
def test_128_concurrent_calls_on_a_small_pool_shed_or_succeed_never_hang(tmp_path):
    """The bounded load check of tools/bench/bench.py (--scenario highconc), in the suite: one real
    worker whose database pool holds two connections (no overflow, 1 s checkout timeout), 128 MCP
    tools/call requests in flight on both eras. Every request is answered within the bound, each
    answer is a success or a deliberate 503 with Retry-After (never a hang, a 401 or another error),
    and /health answers throughout."""
    import asyncio
    sys.path.insert(0, str(ROOT / "tools" / "bench"))
    try:
        import bench
    finally:
        sys.path.pop(0)
    scratch = tmp_path / "srv"
    scratch.mkdir()
    env = bench.server_env(scratch, "database", "", extra={
        "SAJHA_DB_POOL_SIZE": "2", "SAJHA_DB_POOL_MAX_OVERFLOW": "0", "SAJHA_DB_POOL_TIMEOUT_SECONDS": "1"})
    srv = bench.Server(_free_port(), 1, env, scratch / "server.log")
    try:
        srv.wait(timeout=120)
        bound = 30.0
        with bench.HealthProbe(srv.base, interval=0.25, timeout=10) as probe:
            async def run(era):
                outcomes = []
                limits = httpx.Limits(max_connections=128, max_keepalive_connections=128)
                async with httpx.AsyncClient(base_url=srv.base, timeout=bound, limits=limits) as http:
                    clients = [bench.Client(http, era, bench.BENCH_KEY) for _ in range(128)]
                    await asyncio.gather(*(c.open() for c in clients))

                    async def three(c):
                        for _ in range(3):
                            try:
                                outcomes.append(await c.call("tools/call"))
                            except httpx.TimeoutException:
                                outcomes.append("hung")
                    await asyncio.wait_for(asyncio.gather(*(three(c) for c in clients)), bound * 3)
                return outcomes

            results = {era: asyncio.run(run(era)) for era in ("modern", "legacy")}
        for era, outcomes in results.items():
            assert len(outcomes) == 128 * 3, era
            assert set(outcomes) <= {"ok", "shed"}, (era, {o: outcomes.count(o) for o in set(outcomes)})
            assert outcomes.count("ok") > 0, era
        h = probe.summary()
        assert h["probes"] > 0 and h["failures"] == 0, h
        assert h["max_ms"] < 10_000, h
    finally:
        srv.stop()
