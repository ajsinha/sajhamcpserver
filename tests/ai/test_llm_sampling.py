"""MCP sampling for LLM tools (sajha/ai/llm_tools/sampling.py; docs/architecture/LLM Tools.md §12):
``llm.sampling: prefer | require | never`` on modes complete, extract, classify and judge; on 2026-07-28
the model call is an MRTR input request, on 2025-11-25 a server request on the session's stream;
without a channel ``prefer`` uses SAJHA's model and ``require`` refuses; only the MCP call's own tool
samples; sampled runs skip the result cache."""

import asyncio
import json
import os
import sys
import threading
import uuid
from pathlib import Path

import pytest

from sajha.ai.llm import RequestContext
from sajha.ai.llm_tools import LLMConfigError, LLMTool, LLMToolSettings, set_settings
from sajha.ai.llm_tools import sampling as S
from sajha.ai.llm_tools.runtime import Runtime, set_runtime
from sajha.core.mcp_mrtr import InputRequired
from sajha.core.mcp_tool_context import ModernToolContext
from tests.ai.conftest import ToolBox, make_gateway

ROOT = Path(__file__).resolve().parent.parent.parent
ADMIN = RequestContext(user_id="", roles=["admin"], is_admin=True)


@pytest.fixture(autouse=True)
def fresh_runtime(tmp_path):
    from sajha.ai.llm_tools.config import SpoolSettings
    s = LLMToolSettings(spool=SpoolSettings(dir=str(tmp_path / "spool")))
    set_settings(s)
    set_runtime(Runtime(s))
    yield
    set_runtime(None)
    set_settings(None)


def summariser(sampling="prefer", name="t_sum", cache=False):
    with open(ROOT / "config/tools/llm_summarise.json") as f:
        cfg = json.load(f)
    cfg.update(name=name, enabled=True)
    cfg["llm"] = {**cfg["llm"], "sampling": sampling, "cache": cache}
    t = LLMTool(cfg)
    t.registry, t.gateway = ToolBox(), make_gateway()
    return t


def extractor(sampling="require"):
    cfg = {"name": "t_ext", "implementation": "sajha.ai.llm_tools.LLMTool", "description": "Extracts a vendor.",
           "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
           "outputSchema": {"type": "object", "properties": {"vendor": {"type": "string"},
                                                             "amount": {"type": "number"}},
                            "required": ["vendor", "amount"]},
           "llm": {"mode": "extract", "template": "Extract from: {{input.text}}", "sampling": sampling}}
    t = LLMTool(cfg)
    t.registry, t.gateway = ToolBox(), make_gateway()
    return t


def modern_ctx(tool_name, responses=None, caps=None):
    ctx = ModernToolContext(client_capabilities={"sampling": {}} if caps is None else caps,
                            input_responses=responses or {})
    ctx.tool_name = tool_name
    return ctx


def run_in(ctx, tool, args):
    token = ctx.activate()
    try:
        return tool.run(args, ctx=ADMIN, audit=False)
    finally:
        ctx.deactivate(token)


def reply(text, model="client-model", stop="endTurn"):
    return {"role": "assistant", "content": {"type": "text", "text": text}, "model": model, "stopReason": stop}


# ── the loader ───────────────────────────────────────────────────────

def test_sampling_is_accepted_on_single_call_modes_only():
    assert summariser("prefer").spec.sampling == "prefer"
    assert summariser("never").spec.sampling == "never"
    cfg = {"name": "t_a", "implementation": "sajha.ai.llm_tools.LLMTool", "description": "x",
           "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}},
           "outputSchema": {"type": "object", "properties": {"answer": {"type": "string"}}},
           "llm": {"mode": "answer", "sampling": "prefer"}}
    with pytest.raises(LLMConfigError, match="built for modes complete, extract, classify and judge"):
        LLMTool(cfg)


# ── 2026-07-28: MRTR ────────────────────────────────────────────────

def test_mrtr_asks_the_client_then_uses_its_answer():
    t = summariser("prefer")
    args = {"text": "Rates rose. Markets fell.", "max_sentences": 1}
    with pytest.raises(InputRequired) as ir:
        run_in(modern_ctx("t_sum"), t, args)
    (key, req), = ir.value.requests.items()
    assert key == "sajha_sample_1" and req["method"] == "sampling/createMessage"
    p = req["params"]
    assert p["messages"][-1]["role"] == "user" and "Rates rose." in p["messages"][-1]["content"]["text"]
    assert p["maxTokens"] > 0 and p["systemPrompt"]
    calls = t.gateway.providers["mock"].calls
    info = run_in(modern_ctx("t_sum", {key: reply("Rates rose.")}), t, args)
    assert info.result == {"text": "Rates rose.", "stopped_by": "answer"} and info.sampled == "mrtr"
    assert info.models == ["client/client-model"] and info.usage.cost_usd == 0
    assert t.gateway.providers["mock"].calls == calls             # SAJHA's model was not called


def test_mrtr_structured_output_and_its_retry_take_two_rounds():
    t = extractor("require")
    args = {"text": "Acme invoice 12.5"}
    with pytest.raises(InputRequired) as ir:
        run_in(modern_ctx("t_ext"), t, args)
    assert "JSON Schema" in ir.value.requests["sajha_sample_1"]["params"]["systemPrompt"]
    first = {"sajha_sample_1": reply(json.dumps({"vendor": "Acme"}))}
    with pytest.raises(InputRequired) as ir:                       # invalid: the one retry is a second sample
        run_in(modern_ctx("t_ext", first), t, args)
    assert list(ir.value.requests) == ["sajha_sample_2"]
    both = {**first, "sajha_sample_2": reply('```json\n{"vendor": "Acme", "amount": 12.5}\n```')}
    info = run_in(modern_ctx("t_ext", both), t, args)
    assert info.result["vendor"] == "Acme" and info.result["amount"] == 12.5 and info.model_calls == 2


def test_prefer_falls_back_and_require_refuses_without_a_channel():
    t = summariser("prefer")
    info = t.run({"text": "One. Two.", "max_sentences": 1}, ctx=ADMIN, audit=False)
    assert info.result["text"] == "One." and not info.sampled
    info = run_in(modern_ctx("t_sum", caps={}), t, {"text": "One. Two.", "max_sentences": 1})
    assert not info.sampled                                        # the client did not declare sampling
    r = summariser("require")
    info = r.run({"text": "One. Two."}, ctx=ADMIN, audit=False)
    assert info.result.is_error and info.result["code"] == "sampling_required"


def test_only_the_calls_own_tool_samples():
    t = summariser("require")
    info = run_in(modern_ctx("some_composite"), t, {"text": "One. Two."})
    assert info.result.is_error and info.result["code"] == "sampling_required"


def test_never_ignores_the_client_and_sampled_runs_skip_the_cache():
    t = summariser("never")
    info = run_in(modern_ctx("t_sum"), t, {"text": "One. Two.", "max_sentences": 1})
    assert info.result["text"] == "One." and not info.sampled
    c = summariser("prefer", cache=True)
    args = {"text": "One. Two.", "max_sentences": 1}
    c.run(args, ctx=ADMIN, audit=False)                            # SAJHA's model: cached
    info = run_in(modern_ctx("t_sum", {"sajha_sample_1": reply("Client says one.")}), c, args)
    assert info.result["text"] == "Client says one." and not info.cached


def test_a_client_refusal_and_max_tokens_map_to_stop_reasons():
    t = summariser("prefer")
    info = run_in(modern_ctx("t_sum", {"sajha_sample_1": reply("Too long", stop="maxTokens")}), t, {"text": "x"})
    assert info.stopped_by == "token_limit"
    info = run_in(modern_ctx("t_sum", {"sajha_sample_1": reply("No.", stop="refusal")}), t, {"text": "x"})
    assert info.stopped_by == "refused"


# ── 2025-11-25: a server request on the session's stream ─────────────

class FakeCallContext:
    def __init__(self, answer=None, error=None):
        self.seen, self.answer, self.error = [], answer, error

    async def request(self, method, params, timeout=120.0):
        self.seen.append((method, params))
        if self.error:
            raise RuntimeError(self.error)
        return self.answer


def _loop_thread():
    loop = asyncio.new_event_loop()
    th = threading.Thread(target=loop.run_forever, daemon=True)
    th.start()
    return loop, th


def test_session_sampler_bridges_the_worker_thread_to_the_loop():
    loop, th = _loop_thread()
    try:
        t = summariser("require")
        call = FakeCallContext(reply("From the session."))
        with S.bound(S.SessionSampler(call, loop, timeout_s=5), "t_sum"):
            info = t.run({"text": "One. Two."}, ctx=ADMIN, audit=False)
        assert info.result["text"] == "From the session." and info.sampled == "session"
        assert call.seen[0][0] == "sampling/createMessage"
        bad = FakeCallContext(error="user rejected")
        with S.bound(S.SessionSampler(bad, loop, timeout_s=5), "t_sum"):
            info = t.run({"text": "One. Two."}, ctx=ADMIN, audit=False)
        assert info.result.is_error and info.result["code"] == "sampling_failed"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        th.join(2)


# ── end to end over /mcp ────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(ROOT))
    os.chdir(str(ROOT))
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        from sajha.app import tools_registry
        from sajha.auth import apikeys as svc
        from sajha.auth.password import hash_password
        from sajha.db.dao import RoleDAO, UserDAO
        from sajha.db.engine import get_db_session
        from sajha.db.models import User
        t = summariser("require", name="e2e_sampled_sum")
        t.registry = t.gateway = None
        tools_registry.register_tool(t)
        uid = f"smp_{uuid.uuid4().hex[:8]}"
        db = get_db_session()
        try:
            user = User(user_id=uid, user_name=uid, email="", password_hash=hash_password("Smp-Pass-12345"),
                        enabled=True)
            user.roles.append(RoleDAO(db).get_or_create("user"))
            UserDAO(db).create(user)
            _, raw = svc.create_key(db, name="smp-" + uuid.uuid4().hex[:6], created_by="test", owner=user)
        finally:
            db.close()
        yield c, raw
        tools_registry.unregister_tool("e2e_sampled_sum")


def test_2026_07_28_round_trip(app):
    c, key = app
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {"sampling": {}},
            "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1"}}
    hdrs = {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "e2e_sampled_sum",
            "Accept": "application/json, text/event-stream", "X-API-Key": key}
    params = {"name": "e2e_sampled_sum", "arguments": {"text": "Alpha. Beta."}, "_meta": meta}
    r = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    res = r.json()["result"]
    assert res["resultType"] == "input_required", res
    assert res["inputRequests"]["sajha_sample_1"]["method"] == "sampling/createMessage"
    params2 = {**params, "inputResponses": {"sajha_sample_1": reply("Alpha, sampled.")},
               "requestState": res["requestState"]}
    r = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params2})
    res = r.json()["result"]
    assert res.get("isError") is not True and res["structuredContent"]["text"] == "Alpha, sampled.", res
    # a client without the sampling capability: require refuses as a tool error
    meta_none = {**meta, "io.modelcontextprotocol/clientCapabilities": {}}
    r = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                           "params": {**params, "_meta": meta_none}})
    res = r.json()["result"]
    assert res["isError"] is True and "requires MCP sampling" in json.dumps(res)


def test_2025_11_25_round_trip_over_the_session_stream(app):
    """Over a real socket (the TestClient buffers a streamed response): uvicorn on a free port."""
    import socket
    import time as _time
    import httpx
    import uvicorn
    c, key = app
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(c.app, host="127.0.0.1", port=port, lifespan="off", log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    try:
        for _ in range(100):
            if server.started:
                break
            _time.sleep(0.05)
        base = f"http://127.0.0.1:{port}/mcp"
        with httpx.Client(timeout=20) as hc:
            init = hc.post(base, headers={"X-API-Key": key}, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {"sampling": {}},
                    "clientInfo": {"name": "pytest", "version": "1"}}})
            h = {"X-API-Key": key, "Mcp-Session-Id": init.headers["mcp-session-id"],
                 "MCP-Protocol-Version": "2025-11-25"}
            hc.post(base, headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            final = None
            with httpx.Client(timeout=20) as other, hc.stream(
                    "POST", base, headers={**h, "Accept": "application/json, text/event-stream"}, json={
                        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": "e2e_sampled_sum", "arguments": {"text": "Gamma. Delta."}}}) as r:
                for line in r.iter_lines():
                    if not line.startswith("data:") or not line[5:].strip():
                        continue
                    msg = json.loads(line[5:])
                    if msg.get("method") == "sampling/createMessage":
                        assert msg["params"]["messages"][-1]["role"] == "user"
                        ack = other.post(base, headers=h, json={"jsonrpc": "2.0", "id": msg["id"],
                                                                "result": reply("Gamma, from the session.")})
                        assert ack.status_code == 202
                    elif msg.get("id") == 7:
                        final = msg
                        break
        assert final["result"]["structuredContent"]["text"] == "Gamma, from the session.", final
    finally:
        server.should_exit = True
        th.join(5)
