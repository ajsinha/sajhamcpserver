# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
State store (sajha.core.state) and the components that keep their state in it.

Every test runs against each backend that is available here:

* memory     always
* fakeredis  when the ``fakeredis`` package (with ``lupa`` for Lua) is installed
* redis      a real server at SAJHA_TEST_REDIS_URL (default redis://127.0.0.1:6379/15), when it answers
* database   SQLite in a temporary directory

"Two workers" are simulated in one process by two component instances (two
AuthorizationStores, two MCPSessionStores, two TaskStores, two ChangeBuses)
sharing one store; tests/test_state_multiworker.py does it with real processes.
"""

import asyncio
import os
import tempfile
import threading
import time
import uuid

import pytest

from sajha.core import state as state_mod
from sajha.core.state.database import DatabaseStateStore
from sajha.core.state.memory import MemoryStateStore

REDIS_URL = os.environ.get("SAJHA_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")


def _real_redis():
    try:
        import redis
        r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=0.5)
        r.ping()
        return True
    except Exception:
        return False


def _fakeredis_ok():
    try:
        import fakeredis
        import lupa  # noqa: F401  (Lua scripts)
        return fakeredis
    except Exception:
        return None


def _make(kind, tmp):
    prefix = f"t{uuid.uuid4().hex[:8]}:"
    if kind == "memory":
        return MemoryStateStore(prefix)
    if kind == "fakeredis":
        fr = _fakeredis_ok()
        if fr is None:
            pytest.skip("fakeredis/lupa not installed")
        from sajha.core.state.redis_store import RedisStateStore
        return RedisStateStore("redis://fake", prefix, client=fr.FakeRedis(server=fr.FakeServer(),
                                                                            decode_responses=True))
    if kind == "redis":
        if not _real_redis():
            pytest.skip(f"no Redis server at {REDIS_URL}")
        from sajha.core.state.redis_store import RedisStateStore
        return RedisStateStore(REDIS_URL, prefix)
    return DatabaseStateStore(url=f"sqlite:///{tmp}/state.db", prefix=prefix, poll_interval=0.05)


BACKENDS = ["memory", "fakeredis", "redis", "database"]


@pytest.fixture(params=BACKENDS)
def store(request):
    with tempfile.TemporaryDirectory() as tmp:
        s = _make(request.param, tmp)
        yield s
        try:
            s.delete_prefix("")
        finally:
            s.close()


@pytest.fixture
def installed(store):
    """``store`` installed as the process state store (and task record store)."""
    state_mod.set_state_store(store, store)
    yield store
    state_mod.set_state_store(None)


def eventually(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


# ── the contract ──────────────────────────────────────────────────────

class TestContract:
    def test_key_value(self, store):
        store.set("a", {"x": [1, 2]})
        assert store.get("a") == {"x": [1, 2]}
        assert store.add("a", 1) is False
        assert store.add("b", "v") is True and store.get("b") == "v"
        assert store.pop("a") == {"x": [1, 2]} and store.get("a") is None
        assert store.pop("a") is None
        assert store.delete("b") is True and store.delete("b") is False

    def test_ttl(self, store):
        store.set("t", 1, ttl=0.3)
        store.add("u", 1, ttl=0.3)
        assert store.get("t") == 1
        time.sleep(0.5)
        assert store.get("t") is None and store.get("u") is None

    def test_update_is_atomic(self, store):
        def bump(cur):
            return (cur or 0) + 1

        threads = [threading.Thread(target=lambda: [store.update("n", bump) for _ in range(20)]) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert store.get("n") == 80
        assert store.update("n", lambda cur: None) is None and store.get("n") is None

    def test_update_keeps_ttl_unless_given(self, store):
        store.set("k", 1, ttl=0.4)
        store.update("k", lambda c: c + 1)
        time.sleep(0.6)
        assert store.get("k") is None

    def test_incr(self, store):
        assert store.incr("c") == 1
        assert store.incr("c", 2) == 3
        assert store.incr("f", 0.5) == 0.5 and store.incr("f", 0.25) == 0.75
        threads = [threading.Thread(target=lambda: [store.incr("p") for _ in range(25)]) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert store.get("p") == 100

    def test_scan_and_delete_prefix(self, store):
        store.set("s:1", 1)
        store.set("s:2", 2)
        store.set("other", 3)
        assert dict(store.scan("s:")) == {"s:1": 1, "s:2": 2}
        store.delete_prefix("s:")
        assert dict(store.scan("s:")) == {} and store.get("other") == 3

    def test_windows(self, store):
        assert store.window_add("w", 10, 2) == (True, 1)
        assert store.window_add("w", 10, 2) == (True, 2)
        assert store.window_add("w", 10, 2) == (False, 2)
        assert store.window_count("w", 10) == 2
        store.window_add("short", 0.2)
        time.sleep(0.3)
        assert store.window_count("short", 0.2) == 0

    def test_pubsub(self, store):
        got = []
        unsubscribe = store.subscribe("ch", got.append)
        store.publish("ch", {"m": 1})
        store.publish("other", {"m": 2})
        assert eventually(lambda: got == [{"m": 1}])
        unsubscribe()
        store.publish("ch", {"m": 3})
        time.sleep(0.2)
        assert got == [{"m": 1}]


# ── OAuth: codes, refresh tokens, DCR clients ────────────────────────

def _pending():
    from sajha.auth.oauth.authorization_server import PendingAuthorization
    return PendingAuthorization(client_id="c1", client_name="C", client_host="h", redirect_uri="http://localhost/cb",
                                state=None, code_challenge="x" * 43, scopes=["mcp"], resource="http://r/mcp",
                                issuer="http://r", browser_hash="b")


class TestOAuthShared:
    def test_code_issued_on_one_worker_redeems_on_another_once(self, installed):
        from sajha.auth.oauth.authorization_server import AuthorizationStore, OAuthError
        a, b = AuthorizationStore(installed), AuthorizationStore(installed)
        req = a.add_pending(_pending())
        assert b.get_pending(req).client_id == "c1"
        assert b.pop_pending(req) is not None and a.get_pending(req) is None
        code = a.issue_code(_pending(), "alice")
        rec = b.redeem_code(code)
        assert rec.user_id == "alice" and rec.family
        token = b.issue_refresh(rec.family, "c1", "alice", rec.scopes, rec.resource, rec.issuer)
        with pytest.raises(OAuthError, match="already used"):
            a.redeem_code(code)
        # the replay revoked the family the first redemption minted
        with pytest.raises(OAuthError):
            a.use_refresh(token, "c1")

    def test_refresh_rotation_and_reuse_detection_across_workers(self, installed):
        from sajha.auth.oauth.authorization_server import AuthorizationStore, OAuthError
        a, b = AuthorizationStore(installed), AuthorizationStore(installed)
        t1 = a.issue_refresh("fam", "c1", "alice", ["mcp"], "r", "i")
        with pytest.raises(OAuthError, match="another client"):
            b.use_refresh(t1, "c2")
        rec = b.use_refresh(t1, "c1")
        t2 = b.issue_refresh(rec.family, "c1", "alice", rec.scopes, "r", "i", expires=rec.expires)
        with pytest.raises(OAuthError, match="reuse"):
            a.use_refresh(t1, "c1")
        with pytest.raises(OAuthError):
            a.use_refresh(t2, "c1")              # the whole family is revoked

    def test_dynamically_registered_client_is_known_to_every_worker(self, installed):
        from sajha.auth.oauth.clients import ClientRegistry
        info = ClientRegistry().register({"redirect_uris": ["http://localhost:9/cb"],
                                          "token_endpoint_auth_method": "client_secret_post"})
        other = ClientRegistry().local_client(info["client_id"])
        assert other is not None and other.check_secret(info["client_secret"])


# ── rate limits, sign-in throttle, LLM budgets ───────────────────────

class TestCountersShared:
    def test_rate_limit_counts_once_for_all_workers(self, installed):
        from sajha.security import RateLimiter
        a = RateLimiter(3, 60, name="t")
        b = RateLimiter(3, 60, name="t")
        assert [a.is_allowed("ip"), b.is_allowed("ip"), a.is_allowed("ip"), b.is_allowed("ip")] == \
            [True, True, True, False]
        assert a.remaining("ip") == 0
        b.reset("ip")
        assert a.remaining("ip") == 3

    def test_login_failures_shared(self, installed):
        from sajha.security import FailureThrottle
        a, b = FailureThrottle(), FailureThrottle()
        for _ in range(20):
            a.record_failure("login:1.2.3.4")
        assert b.blocked("login:1.2.3.4")
        b.reset()
        assert not a.blocked("login:1.2.3.4")

    def test_token_budget_shared_when_store_is_shared(self, installed):
        from sajha.ai.llm.governed import TokenTracker
        from sajha.ai.llm.types import Usage
        a, b = TokenTracker(installed), TokenTracker(installed)
        a.record_usage("u", ["analyst"], "p", "m", Usage(10, 5, 0, 0.01))
        b.record_usage("u", ["analyst"], "p", "m", Usage(1, 1, 0, 0.0))
        assert a.daily_user_tokens("u") == 17 and b.daily_role_tokens("analyst") == 17
        assert b.get_usage("u")["p"]["m"]["count"] == 2
        assert set(a.get_usage()) == {"u"}


# ── MCP sessions (2025-11-25) and the legacy SSE relay ───────────────

class TestSessionsShared:
    def test_session_created_on_one_worker_is_found_and_ended_on_another(self, installed):
        from sajha.core.mcp_sessions import MCPSessionStore
        a, b = MCPSessionStore(), MCPSessionStore()
        a.attach_store(installed)
        b.attach_store(installed)
        try:
            s = a.create("2025-11-25", {"name": "cli"}, {"sampling": {}}, user_id="alice")
            s.initialized = True
            seen = b.get(s.session_id)
            assert seen is not None and seen.user_id == "alice" and seen.supports("sampling") and seen.initialized
            assert b.delete(s.session_id)
            assert a.get(s.session_id) is None
        finally:
            a.detach_store()
            b.detach_store()

    def test_client_response_reaches_the_worker_holding_the_stream(self, installed):
        from sajha.core.mcp_sessions import MCPSessionStore

        async def run():
            a, b = MCPSessionStore(), MCPSessionStore()
            a.attach_store(installed)
            b.attach_store(installed)
            try:
                s = a.create("2025-11-25")
                fut = asyncio.get_running_loop().create_future()
                rid = a.new_request_id()
                s.pending[rid] = fut
                remote = b.get(s.session_id)
                assert b.resolve_response(remote, {"jsonrpc": "2.0", "id": rid, "result": {"ok": 1}})
                msg = await asyncio.wait_for(fut, 3)
                assert msg["result"] == {"ok": 1}
            finally:
                a.detach_store()
                b.detach_store()

        asyncio.run(run())


# ── MCP tasks (2026-07-28 extension) ─────────────────────────────────

class TestTasksShared:
    def test_task_created_on_one_worker_is_visible_on_another(self, installed):
        from sajha.core.mcp_tasks import TaskNotFound, TaskStore

        async def run():
            a, b = TaskStore(installed), TaskStore(installed)

            async def runner(task):
                return {"content": [{"type": "text", "text": "done"}]}

            t = a.create("alice", runner)
            assert b.get(t.task_id, "alice").status in ("working", "completed")
            await asyncio.sleep(0.05)
            got = b.get(t.task_id, "alice")
            assert got.status == "completed" and got.result["content"][0]["text"] == "done"
            with pytest.raises(TaskNotFound):
                b.get(t.task_id, "bob")

        asyncio.run(run())

    def test_cancel_on_another_worker_stops_the_running_job(self, installed):
        from sajha.core.mcp_tasks import TaskStore

        async def run():
            a, b = TaskStore(installed), TaskStore(installed)
            a._relay = b._relay = None
            a._unsubscribe = installed.subscribe("mcp.tasks", a._on_message)
            b._relay = installed
            started = asyncio.Event()

            async def runner(task):
                started.set()
                await asyncio.sleep(30)
                return {}

            t = a.create("alice", runner)
            await started.wait()
            b.cancel(t.task_id, "alice")
            for _ in range(150):
                if t._job.done():
                    break
                await asyncio.sleep(0.02)
            assert t._job.done()
            assert a.get(t.task_id, "alice").status == "cancelled"
            a._unsubscribe()

        asyncio.run(run())

    def test_input_answered_on_another_worker_resumes_there(self, installed):
        from sajha.core.mcp_mrtr import InputRequired
        from sajha.core.mcp_tasks import TaskStore

        def make_runner(spec):
            async def runner(task):
                if "name" not in task.responses:
                    raise InputRequired({"name": {"method": "elicitation/create", "params": {}}})
                return {"content": [{"type": "text", "text": f"hi {task.responses['name']} via {spec['tag']}"}]}
            return runner

        async def run():
            a, b = TaskStore(installed), TaskStore(installed)
            b.set_resumer(make_runner)
            t = a.create("alice", make_runner({"tag": "a"}), spec={"tag": "b"})
            await asyncio.sleep(0.05)
            assert b.get(t.task_id, "alice").status == "input_required"
            b.update(t.task_id, "alice", {"name": "Ada"})
            await asyncio.sleep(0.1)
            got = a.get(t.task_id, "alice")
            assert got.status == "completed"
            assert got.result["content"][0]["text"] == "hi Ada via b"

        asyncio.run(run())

    def test_task_of_a_dead_worker_is_failed_not_rerun(self, installed):
        from sajha.core.mcp_tasks import ORPHANED_MESSAGE, TaskStore
        store = TaskStore(installed)
        installed.set("mcp:task:orphan", {
            "task_id": "orphan", "owner": "alice", "ttl_ms": 60000, "poll_interval_ms": 500,
            "status": "working", "status_message": None, "created_at": time.time(), "updated_at": time.time(),
            "result": None, "error": None, "pending": {}, "responses": {}, "state": {},
            "worker": "gone-host:1:abc", "spec": None}, ttl=60)
        got = store.get("orphan", "alice")
        assert got.status == "failed" and got.error["message"] == ORPHANED_MESSAGE


# ── change bus ────────────────────────────────────────────────────────

class TestChangeBusShared:
    def test_event_published_on_one_worker_reaches_subscribers_on_another(self, installed):
        from sajha.core.change_bus import ChangeBus, PROMPTS, TOOLS

        async def run():
            a, b = ChangeBus(), ChangeBus()
            a.attach_store(installed)
            b.attach_store(installed)
            try:
                sub_b = b.subscribe({TOOLS})
                sub_a = a.subscribe({TOOLS})
                a.publish(TOOLS)
                a.publish(PROMPTS)                          # not subscribed: filtered
                ev_b = await asyncio.wait_for(sub_b.get(), 3)
                ev_a = await asyncio.wait_for(sub_a.get(), 3)
                assert ev_b.kind == TOOLS and ev_a.kind == TOOLS
                await asyncio.sleep(0.3)
                assert sub_a.queue.empty()                  # no echo of its own event
            finally:
                a.detach_store()
                b.detach_store()

        asyncio.run(run())


# ── async executor records ───────────────────────────────────────────

class TestAsyncExecutorShared:
    def test_task_queued_on_one_worker_is_visible_and_cancellable_on_another(self, installed):
        if not installed.shared:
            pytest.skip("records are shared only with a shared backend")
        from sajha.core.async_executor import AsyncExecutor
        a = AsyncExecutor(num_workers=1, queue_size=10)       # not started: tasks stay queued
        b = AsyncExecutor(num_workers=1, queue_size=10)
        t = a.submit("echo", {"x": 1}, "file", "out.json")
        seen = b.get_task(t.task_id)
        assert seen is not None and seen.status.value == "queued"
        assert t.task_id in {d["task_id"] for d in b.list_tasks()}
        assert b.cancel_task(t.task_id)
        a._execute_task(t)                                     # A checks the shared record first
        assert t.status.value == "cancelled"


# ── configuration, health ────────────────────────────────────────────

class TestConfiguration:
    def test_backend_selection_and_validation(self, monkeypatch):
        monkeypatch.setenv("SAJHA_STATE_BACKEND", "memory")
        assert state_mod.build_store().backend == "memory"
        assert state_mod.tasks_durable() is False
        monkeypatch.setenv("SAJHA_STATE_BACKEND", "database")
        assert state_mod.tasks_durable() is True
        monkeypatch.setenv("SAJHA_STATE_TASKS_DURABLE", "false")
        assert state_mod.tasks_durable() is False
        monkeypatch.setenv("SAJHA_STATE_BACKEND", "bogus")
        with pytest.raises(ValueError):
            state_mod.configured_backend()

    def test_worker_count_hint(self, monkeypatch):
        monkeypatch.setenv("WEB_CONCURRENCY", "4")
        assert state_mod.worker_count_hint() == 4

    def test_memory_backend_with_several_workers_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("WEB_CONCURRENCY", "3")
        state_mod.set_state_store(MemoryStateStore())
        try:
            with caplog.at_level("WARNING"):
                info = state_mod.startup_check()
            assert info["backend"] == "memory"
            assert any("state.backend=memory" in r.message for r in caplog.records)
        finally:
            state_mod.set_state_store(None)

    def test_health_reports_the_backend(self):
        from fastapi.testclient import TestClient
        from sajha.app import create_app
        with TestClient(create_app()) as c:
            body = c.get("/health").json()
        assert body["state"]["backend"] == "memory" and body["state"]["reachable"] is True


def test_signing_key_from_pem_env(monkeypatch):
    """Hosts that share no data directory sign with the same key given as PEM text."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from sajha.auth.oauth import keys
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    monkeypatch.setenv("SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM", pem.replace("\n", "\\n"))
    k1 = keys.get_signing_key()
    assert k1.private_pem.decode().strip() == pem.strip()
    assert keys.get_signing_key().kid == k1.kid      # the file-based key is used again once unset
