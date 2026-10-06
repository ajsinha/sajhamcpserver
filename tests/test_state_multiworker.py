"""
Several SAJHA processes sharing one state backend, end to end over HTTP.

Two servers (worker A and worker B: separate processes, separate ports, the
same database and the same state backend, as behind a load balancer) and
the checks that used to fail when that state was per process:

* an OAuth authorization code issued by A is redeemed at B (once)
* a task created on A is visible (and finishes) through B
* sign-in failure counts are shared: failures on A and B add up
* a change-bus event published on A reaches a subscriptions/listen stream on B

Backends: ``database`` (a shared SQLite file: always runs) and ``redis`` (a
real server at SAJHA_TEST_REDIS_URL, default redis://127.0.0.1:6379/15:
skipped when none answers).  A final test starts ``run_server.py --workers 2``
and checks that both workers come up on the shared backend.

Set SAJHA_SKIP_MULTIPROCESS_TESTS=1 to skip this module.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

httpx = pytest.importorskip("httpx")

ROOT = Path(__file__).resolve().parent.parent
REDIS_URL = os.environ.get("SAJHA_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
PUBLIC = "http://sajha.test"
REDIRECT = "http://127.0.0.1:3999/callback"
CLIENT_ID = "mw-client"
V = "2026-07-28"
META = {"io.modelcontextprotocol/protocolVersion": V,
        "io.modelcontextprotocol/clientCapabilities": {"extensions": {"io.modelcontextprotocol/tasks": {}}},
        "io.modelcontextprotocol/clientInfo": {"name": "pytest-mw", "version": "1"}}

pytestmark = pytest.mark.skipif(os.environ.get("SAJHA_SKIP_MULTIPROCESS_TESTS") == "1",
                                reason="SAJHA_SKIP_MULTIPROCESS_TESTS=1")


def _redis_ok():
    try:
        import redis
        r = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=0.5)
        r.ping()
        return True
    except Exception:
        return False


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(tmp, backend, prefix):
    env = dict(os.environ)
    for k in [k for k in env if k.startswith("SAJHA_")]:
        env.pop(k)
    env.update({
        "SAJHA_DB_PATH": str(tmp / "sajha.db"),
        "SAJHA_STATE_BACKEND": backend,
        "SAJHA_STATE_REDIS_URL": REDIS_URL,
        "SAJHA_STATE_KEY_PREFIX": prefix,
        "SAJHA_STATE_DATABASE_POLL_INTERVAL_MS": "100",
        "SAJHA_MCP_CONFORMANCE_FIXTURES": "true",
        "SAJHA_AI_RAG_PERSIST": "false",            # never write the document index under data/
        "SAJHA_AI_RAG_BUILD_ON_START": "false",
        "SAJHA_MCP_AUTH_MODE": "optional",
        "SAJHA_MCP_AUTH_PUBLIC_URL": PUBLIC,
        "SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PATH": str(tmp / "signing_key.pem"),
        "SAJHA_MCP_AUTH_BUILTIN_CLIENTS": json.dumps([{"client_id": CLIENT_ID, "redirect_uris": [REDIRECT]}]),
        "SAJHA_AUTH_LOGIN_IP_MAX_FAILURES": "3",
        "JWT_SECRET": "multiworker-test-jwt-" + "x" * 32,
        "SESSION_SECRET": "multiworker-test-session-" + "y" * 32,
        "PYTHONUNBUFFERED": "1",
    })
    return env


class Server:
    def __init__(self, env, tmp, name, workers=1):
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.log = open(tmp / f"{name}.log", "wb")
        args = [sys.executable, "run_server.py", "--host", "127.0.0.1", "--port", str(self.port),
                "--log-level", "warning"]
        if workers > 1:
            args += ["--workers", str(workers)]
        self.proc = subprocess.Popen(args, cwd=str(ROOT), env=env, stdout=self.log, stderr=subprocess.STDOUT)
        self.client = httpx.Client(base_url=self.base, timeout=20)

    def wait(self, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited: see {self.log.name}")
            try:
                if self.client.get("/health").status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"server did not start: see {self.log.name}")

    def stop(self):
        self.client.close()
        self.proc.terminate()
        try:
            self.proc.wait(15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


@pytest.fixture(scope="module", params=["database", "redis"])
def pair(request, tmp_path_factory):
    backend = request.param
    if backend == "redis" and not _redis_ok():
        pytest.skip(f"no Redis server at {REDIS_URL}")
    tmp = tmp_path_factory.mktemp(f"mw-{backend}")
    env = _env(tmp, backend, f"mw{secrets.token_hex(4)}:")
    a = Server(env, tmp, "a").wait()          # A first: it creates the SQLite schema
    b = Server(env, tmp, "b").wait()
    yield backend, a, b
    a.stop()
    b.stop()


def _modern(server, method, params=None, rid=1, name=None):
    params = dict(params or {}, _meta=META)
    headers = {"MCP-Protocol-Version": V, "Mcp-Method": method, "Accept": "application/json, text/event-stream"}
    if name:
        headers["Mcp-Name"] = name
    r = server.client.post("/mcp", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
                           headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, body
    return body["result"]


def test_both_workers_report_the_shared_backend(pair):
    backend, a, b = pair
    sa, sb = a.client.get("/health").json()["state"], b.client.get("/health").json()["state"]
    assert sa["backend"] == sb["backend"] == backend
    assert sa["reachable"] and sb["reachable"]
    assert sa["worker_id"] != sb["worker_id"]
    assert sa["tasks"] == "durable (database)"


def test_oauth_code_from_a_redeems_on_b_once(pair):
    _, a, b = pair
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT, "state": "s",
              "code_challenge": challenge, "code_challenge_method": "S256", "resource": PUBLIC + "/mcp",
              "scope": "mcp:read mcp:tools offline_access"}
    r = a.client.get("/oauth/authorize", params=params)
    assert r.status_code == 200, r.text
    req_id = re.search(r'name="req_id" value="([^"]+)"', r.text).group(1)
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    # the consent form is answered on B: the pending request lives in the shared store
    b.client.cookies.update(a.client.cookies)
    r2 = b.client.post("/oauth/authorize", data={"req_id": req_id, "csrf": csrf, "decision": "approve",
                                                  "user_id": "admin", "password": "admin123"})
    assert r2.status_code == 302, r2.text
    code = parse_qs(urlsplit(r2.headers["location"]).query)["code"][0]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
            "code_verifier": verifier, "client_id": CLIENT_ID, "resource": PUBLIC + "/mcp"}
    tok = a.client.post("/oauth/token", data=form)
    assert tok.status_code == 200, tok.text
    assert tok.json()["access_token"] and tok.json()["refresh_token"]
    replay = b.client.post("/oauth/token", data=form)
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    # the replay revoked the grant: the refresh token minted on A is dead on B too
    ref = b.client.post("/oauth/token", data={"grant_type": "refresh_token", "client_id": CLIENT_ID,
                                              "refresh_token": tok.json()["refresh_token"]})
    assert ref.status_code == 400


def test_task_created_on_a_is_visible_on_b(pair):
    _, a, b = pair
    created = _modern(a, "tools/call", {"name": "slow_compute", "arguments": {"seconds": 0.5, "label": "mw"}},
                      name="slow_compute")
    assert created["resultType"] == "task"
    tid = created["taskId"]
    first = _modern(b, "tasks/get", {"taskId": tid}, name=tid)
    assert first["status"] in ("working", "completed")
    end = time.time() + 15
    while time.time() < end:
        got = _modern(b, "tasks/get", {"taskId": tid}, name=tid)
        if got["status"] == "completed":
            break
        time.sleep(0.1)
    assert got["status"] == "completed", got
    # cancel from B of a task running on A
    created = _modern(a, "tools/call", {"name": "slow_compute", "arguments": {"seconds": 30}}, name="slow_compute")
    _modern(b, "tasks/cancel", {"taskId": created["taskId"]}, name=created["taskId"])
    assert _modern(a, "tasks/get", {"taskId": created["taskId"]}, name=created["taskId"])["status"] == "cancelled"


def test_sign_in_failures_are_counted_across_workers(pair):
    _, a, b = pair
    bad = {"user_id": f"nobody-{secrets.token_hex(3)}", "password": "wrong"}
    assert a.client.post("/api/auth/login", json=bad).status_code == 401
    assert b.client.post("/api/auth/login", json=bad).status_code == 401
    assert a.client.post("/api/auth/login", json=bad).status_code == 401
    # three failures from this IP (limit 3), two on A and one on B: both workers now refuse
    assert b.client.post("/api/auth/login", json=bad).status_code == 429
    assert a.client.post("/api/auth/login", json=bad).status_code == 429


def test_change_event_on_a_reaches_listen_stream_on_b(pair):
    _, a, b = pair
    lines, acked, done = [], threading.Event(), threading.Event()

    def listen():
        headers = {"MCP-Protocol-Version": V, "Mcp-Method": "subscriptions/listen",
                   "Accept": "application/json, text/event-stream"}
        body = {"jsonrpc": "2.0", "id": 7, "method": "subscriptions/listen",
                "params": {"notifications": {"toolsListChanged": True}, "_meta": META}}
        with httpx.Client(base_url=b.base, timeout=30) as c:
            with c.stream("POST", "/mcp", json=body, headers=headers) as r:
                for line in r.iter_lines():
                    lines.append(line)
                    if "subscriptions/acknowledged" in line:
                        acked.set()
                    if "notifications/tools/list_changed" in line:
                        done.set()
                        return

    t = threading.Thread(target=listen, daemon=True)
    t.start()
    assert acked.wait(15), lines
    time.sleep(0.3)
    _modern(a, "tools/call", {"name": "test_trigger_tool_change", "arguments": {}}, name="test_trigger_tool_change")
    assert done.wait(15), lines


def test_two_uvicorn_workers_on_one_port(tmp_path):
    backend = "redis" if _redis_ok() else "database"
    env = _env(tmp_path, backend, f"mw{secrets.token_hex(4)}:")
    srv = Server(env, tmp_path, "workers", workers=2).wait()
    try:
        seen = set()
        end = time.time() + 30
        while len(seen) < 2 and time.time() < end:
            with httpx.Client(base_url=srv.base, timeout=10) as c:      # new connection: any worker
                st = c.get("/health").json()["state"]
            assert st["backend"] == backend and st["workers_hint"] == 2
            seen.add(st["worker_id"])
        assert len(seen) == 2, seen
    finally:
        srv.stop()
