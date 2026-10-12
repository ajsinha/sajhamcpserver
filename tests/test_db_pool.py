# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The database connection pool (docs/architecture/Scaling and State.md §7):

* ``db.pool.*`` is validated, and both SQLite files and PostgreSQL get a counting QueuePool;
* a dry pool answers fast: HTTP 503 with ``Retry-After`` (a JSON-RPC error with retry data on
  ``/mcp``), never a hang and never a misleading 401, counted in ``sajha_db_pool_exhausted_total``;
* no leaks: a tool that raises, a route that raises after a database read and a client that
  disconnects mid-request all leave the pool's checked-out count at its baseline;
* the pool's status is on ``/api/admin/system-monitor`` and in ``/metrics``.
"""

import secrets
import time
from types import SimpleNamespace

import pytest

httpx = pytest.importorskip("httpx")

from sajha.db import engine as eng  # noqa: E402

V = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": V, "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "pytest-pool", "version": "1"}}
RAISING_TOOL = "zz_pool_raising_tool"


# ── configuration ───────────────────────────────────────────────────

def _settings(**kw):
    base = dict(db_pool_size=10, db_pool_max_overflow=-1, db_pool_timeout_seconds=5.0)
    base.update(kw)
    return SimpleNamespace(**base)


def test_pool_options_defaults_and_validation():
    assert eng.pool_options(_settings()) == {'pool_size': 10, 'max_overflow': 10, 'pool_timeout': 5.0}
    assert eng.pool_options(_settings(db_pool_max_overflow=0))['max_overflow'] == 0
    for bad in (dict(db_pool_size=0), dict(db_pool_timeout_seconds=0), dict(db_pool_timeout_seconds=301)):
        with pytest.raises(ValueError):
            eng.pool_options(_settings(**bad))


def test_sqlite_file_gets_the_counting_pool(tmp_path):
    s = SimpleNamespace(database_url=f"sqlite:///{tmp_path / 'p.db'}", db_type='sqlite', db_echo=False,
                        db_pool_size=2, db_pool_max_overflow=1, db_pool_timeout_seconds=0.5)
    e = eng.create_db_engine(s)
    try:
        assert isinstance(e.pool, eng.CountingQueuePool)
        assert e.pool.size() == 2 and e.pool.timeout() == 0.5
        with e.connect() as c:
            assert c.exec_driver_sql('PRAGMA synchronous').scalar() == 1      # NORMAL
            assert str(c.exec_driver_sql('PRAGMA journal_mode').scalar()).lower() == 'wal'
    finally:
        e.dispose()
    mem = eng.create_db_engine(SimpleNamespace(database_url='sqlite://', db_type='sqlite', db_echo=False,
                                               db_pool_size=2, db_pool_max_overflow=1, db_pool_timeout_seconds=1))
    assert not isinstance(mem.pool, eng.CountingQueuePool)       # in-memory keeps SQLAlchemy's own pool
    mem.dispose()


def test_db_type_switches_by_environment(monkeypatch):
    """db.type comes from DB_TYPE (the YAML reads ${DB_TYPE:sqlite}); without the key in the YAML the
    code reads DB_TYPE and the other DB_* names itself; SAJHA_DB_* always wins."""
    from sajha.core import config as C
    monkeypatch.delenv('SAJHA_DB_TYPE', raising=False)
    monkeypatch.delenv('SAJHA_DB_HOST', raising=False)
    monkeypatch.setenv('DB_TYPE', 'postgresql')
    monkeypatch.setenv('DB_HOST', 'db.example')
    assert C.load_yaml_config().get('db.type') == 'postgresql'          # the shipped YAML
    monkeypatch.setattr(C, '_CFG', {k: v for k, v in C._CFG.items() if k not in ('db.type', 'db.host')})
    s = C.Settings()
    assert s.db_type == 'postgresql' and s.db_host == 'db.example'
    assert s.database_url.startswith('postgresql+') and '@db.example:' in s.database_url
    monkeypatch.setenv('SAJHA_DB_TYPE', 'sqlite')
    assert C.Settings().db_type == 'sqlite'


# ── the app with a one-connection pool ──────────────────────────────

@pytest.fixture
def tiny_pool_app(monkeypatch):
    """A started app whose pool holds one connection (no overflow, 0.5 s checkout timeout), a tool
    that raises, and an administrator-owned API key."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setenv("SAJHA_POLICY_ENABLED", "false")
    from sajha.app import create_app
    from sajha.tools.base_mcp_tool import BaseMCPTool

    class Raising(BaseMCPTool):
        def __init__(self):
            super().__init__({"name": RAISING_TOOL, "description": "raises (pool test)",
                              "inputSchema": {"type": "object", "properties": {}}})

        def get_input_schema(self):
            return self._input_schema

        def get_output_schema(self):
            return {}

        def execute(self, arguments):
            raise RuntimeError("deliberate failure")

    app = create_app()
    from fastapi import Depends, Request
    from sajha.db.engine import get_db

    async def raise_after_read(request: Request, db=Depends(get_db)):
        from sajha.db.dao import UserDAO
        UserDAO(db).get_by_user_id("admin")
        raise RuntimeError("deliberate failure after a database read")

    async def read_then_wait_for_body(request: Request, db=Depends(get_db)):
        from sajha.db.dao import UserDAO
        UserDAO(db).get_by_user_id("admin")
        await request.body()            # the client disconnects here
        return {"ok": True}

    app.add_api_route("/__pool_test/raise", raise_after_read, methods=["POST"])
    app.add_api_route("/__pool_test/body", read_then_wait_for_body, methods=["POST"])
    with TestClient(app, raise_server_exceptions=False) as c:
        tiny = create_engine(eng._engine.url, poolclass=eng.CountingQueuePool, pool_size=1, max_overflow=0,
                             pool_timeout=0.5, connect_args={"check_same_thread": False, "timeout": 30})
        eng._engine, eng._SessionLocal = tiny, sessionmaker(autocommit=False, autoflush=False, bind=tiny)
        # (the autouse _keep_the_database_engine fixture puts the app's engine back and disposes this one)
        from sajha.app import tools_registry
        tools_registry.register_tool(Raising())
        from sajha.auth import apikeys as keys
        from sajha.db.dao import UserDAO
        with eng.session_scope() as db:
            _, raw = keys.create_key(db, name="pool-" + secrets.token_hex(3), created_by="test",
                                     owner=UserDAO(db).get_by_user_id("admin"))
        try:
            yield c, raw, app
        finally:
            tools_registry.unregister_tool(RAISING_TOOL)


def _modern(method, params=None, rid=1):
    p = dict(params or {})
    p["_meta"] = META
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": p}


def _mcp_headers(key, method, name=""):
    h = {"X-API-Key": key, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": V,
         "Mcp-Method": method}
    if name:
        h["Mcp-Name"] = name
    return h


def test_a_dry_pool_answers_503_fast_not_a_hang_or_a_401(tiny_pool_app):
    c, key, _ = tiny_pool_app
    before = eng.POOL_COUNTERS.exhausted
    held = eng._engine.connect()        # the pool's only connection: every checkout now times out
    try:
        t0 = time.time()
        r = c.post("/mcp", json=_modern("tools/list"), headers=_mcp_headers(key, "tools/list"))
        took = time.time() - t0
        assert r.status_code == 503, r.text
        assert r.headers.get("retry-after") == "1"
        body = r.json()
        assert body["jsonrpc"] == "2.0" and body["error"]["code"] == -32000
        assert body["error"]["data"]["reason"] == "db_pool_exhausted" and body["error"]["data"]["retryable"]
        assert took < 5, f"the shed took {took:.1f}s"
        r = c.post("/api/tools/execute", headers={"X-API-Key": key}, json={"tool": "calc_future_value",
                                                                            "arguments": {}})
        assert r.status_code == 503 and r.json()["reason"] == "db_pool_exhausted", r.text
        assert r.headers.get("retry-after") == "1"
        assert c.get("/health").status_code == 200             # the event loop is free
    finally:
        held.close()
    assert eng.POOL_COUNTERS.exhausted >= before + 2
    r = c.post("/mcp", json=_modern("tools/list"), headers=_mcp_headers(key, "tools/list"))
    assert r.status_code == 200 and r.json()["result"]["tools"], r.text
    from sajha.observability.metrics import REGISTRY, render
    text = render(REGISTRY.collect())
    assert "sajha_db_pool_exhausted_total" in text and "sajha_db_pool_checked_out" in text


def test_error_paths_give_every_connection_back(tiny_pool_app):
    import anyio
    c, key, app = tiny_pool_app
    pool = eng._engine.pool
    # idle: nothing checked out. (Background jobs of apps started by earlier tests share this engine and
    # may hold a connection for a moment, so each check waits, bounded, for the pool to be idle again.)
    baseline = 0

    def back_to_baseline():
        # a request's session is closed by its dependency's cleanup, which may finish just after the
        # response reached the client: wait (bounded) for it
        end = time.time() + 3
        while pool.checkedout() != baseline and time.time() < end:
            time.sleep(0.02)
        return pool.checkedout() == baseline

    # a tool that raises: through MCP and through the REST tool endpoint
    r = c.post("/mcp", json=_modern("tools/call", {"name": RAISING_TOOL, "arguments": {}}),
               headers=_mcp_headers(key, "tools/call", RAISING_TOOL))
    assert r.status_code == 200 and (r.json().get("result", {}).get("isError") or "error" in r.json()), r.text
    assert back_to_baseline(), pool.checkedout()
    c.post("/api/tools/execute", headers={"X-API-Key": key}, json={"tool": RAISING_TOOL, "arguments": {}})
    assert back_to_baseline(), pool.checkedout()

    # a route that raises after a database read
    r = c.post("/__pool_test/raise", headers={"X-API-Key": key})
    assert r.status_code == 500
    assert back_to_baseline(), pool.checkedout()

    # a client that disconnects mid-request (after the route read the database, while it waits for the body)
    async def disconnecting_call():
        sent = []
        msgs = iter([{"type": "http.request", "body": b"{", "more_body": True}, {"type": "http.disconnect"}])

        async def receive():
            try:
                return next(msgs)
            except StopIteration:
                await anyio.sleep(3600)

        async def send(m):
            sent.append(m)

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                 "scheme": "http", "path": "/__pool_test/body", "raw_path": b"/__pool_test/body",
                 "query_string": b"", "root_path": "", "server": ("testserver", 80), "client": ("127.0.0.1", 5),
                 "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                             (b"content-length", b"100"), (b"x-api-key", key.encode())]}
        with anyio.fail_after(10):
            await app(scope, receive, send)
        return sent

    c.portal.call(disconnecting_call)
    assert back_to_baseline(), pool.checkedout()
    # and the pool still serves
    assert c.post("/mcp", json=_modern("tools/list"), headers=_mcp_headers(key, "tools/list")).status_code == 200
    assert back_to_baseline(), pool.checkedout()


def test_system_monitor_shows_the_pool(web):
    client, admin = web
    r = client.get("/api/admin/system-monitor", cookies=admin)
    assert r.status_code == 200
    workers = r.json()["db_pool"]["workers"]
    me = [w for w in workers if w["this_worker"]][0]
    assert me["db_type"] in ("sqlite", "postgresql")
    for field in ("size", "max_overflow", "checked_out", "overflow_in_use", "waiting", "exhausted_total", "url"):
        assert field in me, field
    assert ":" not in me["url"].split("@")[0].split("//")[-1] or "***" in me["url"]    # no password
    page = client.get("/admin/system-monitor", cookies=admin)
    assert page.status_code == 200 and "Database Connection Pool" in page.text
