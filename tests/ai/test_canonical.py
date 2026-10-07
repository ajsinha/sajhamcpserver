"""
The canonical Chat Completions format: lossless converters from the original types, the
request refusals of §13.6, the six behaviours that used to be silent, the gateway's canonical
interface (sync, stream, native async, embeddings), and cloud credentials (Vertex AI, Entra ID).
"""

import json
import time

import anyio
import httpx
import pytest

from sajha.ai.llm import (InvalidRequest, ModelFailed, NoModelAvailable, RequestContext, UnsupportedFeature,
                          registry)
from sajha.ai.llm.canonical import (ChatCompletionRequest, ChatMessage, ContentPart, ResponseFormat,
                                    SajhaRequest, ToolDefinition, check_request, decode_base64_floats)
from sajha.ai.llm.convert import (from_canonical_request, from_canonical_response, to_canonical_request,
                                  to_canonical_response)
from sajha.ai.llm.types import (ChatRequest, ChatResponse, ImagePart, Message, TextPart, ToolCallPart,
                                ToolSpec, Usage)
from tests.ai.conftest import make_gateway
from tests.ai.fakes import FakeVendor
from tests.ai.test_provider_contract import QUESTION, SPEC

TOOL = ToolDefinition.of(SPEC.name, SPEC.description, SPEC.input_schema)
FX = ToolDefinition.of("get_fx", "FX rate", {"type": "object", "properties": {"pair": {"type": "string"}}})


def provider(kind, transport=None, **cfg):
    base = {"enabled": True, "api_key": "k", **cfg}
    return registry.provider_class(kind).from_settings(kind, base, environ={}, transport=transport)


def vendor(kind, handler):
    """A one-off fake vendor: ``handler(body, request) -> json``; records requests."""
    seen = []

    def handle(request):
        body = json.loads(request.content) if request.content else {}
        seen.append({"path": request.url.path, "body": body, "headers": dict(request.headers),
                     "params": dict(request.url.params)})
        return httpx.Response(200, json=handler(body, request))
    return httpx.MockTransport(handle), seen


# ── converters ──────────────────────────────────────────────────────

def test_legacy_request_round_trips_losslessly():
    legacy = ChatRequest(
        messages=[Message.user("hi"), Message("user", [TextPart("look"), ImagePart(b"\x89PNG", "image/png")]),
                  Message("assistant", [TextPart("calling"), ToolCallPart("c1", "calc", {"a": 1})],
                          meta={"anthropic_content": [{"type": "thinking", "signature": "s"}], "provider": "anthropic"}),
                  Message.tool_result("c1", {"result": 2}, name="calc"),
                  Message.tool_result("c2", "boom", is_error=True),
                  Message.system("extra system")],
        system="Be brief.", tools=[SPEC], tool_choice=SPEC.name, response_schema={"type": "object"},
        temperature=0.0, max_output_tokens=99, stop=["END"], metadata=RequestContext(user_id="u"))
    canon = to_canonical_request(legacy)
    back = from_canonical_request(canon)
    assert back.system == legacy.system and back.tools == legacy.tools and back.tool_choice == SPEC.name
    assert back.response_schema == legacy.response_schema and back.stop == ["END"]
    assert back.temperature == 0.0 and back.max_output_tokens == 99 and back.metadata is legacy.metadata
    assert [m.to_dict() for m in back.messages] == [m.to_dict() for m in legacy.messages]
    assert back.messages[2].meta == legacy.messages[2].meta          # provider state survives
    assert "anthropic_content" not in json.dumps(canon.to_dict())    # ... but is never serialised


def test_legacy_response_round_trips():
    resp = ChatResponse(Message.assistant("ok", [ToolCallPart("c1", "calc", {"a": 1})]), "tool_calls",
                        Usage(10, 5, 2, 0.01), "m", "p", 12, refusal="", notes={"ignored": ["temperature"]})
    back = from_canonical_response(to_canonical_response(resp))
    assert back.text == "ok" and back.tool_calls == resp.tool_calls and back.finish_reason == "tool_calls"
    assert (back.usage.input_tokens, back.usage.output_tokens, back.usage.cached_tokens) == (10, 5, 2)
    assert back.usage.cost_usd == 0.01 and back.provider == "p" and back.notes["ignored"] == ["temperature"]


# ── refusals that apply to every provider (§13.6) ───────────────────

@pytest.mark.parametrize("extra,field", [
    ({"functions": [{"name": "x"}]}, "functions"),
    ({"function_call": "auto"}, "function_call"),
    ({"web_search_options": {}}, "web_search_options"),
    ({"store": True}, "store"),
    ({"modalities": ["text", "audio"]}, "modalities"),
    ({"audio": {"voice": "alloy"}}, "audio"),
    ({"tools": [{"type": "web_search"}]}, "tools[0]"),
    ({"tools": [TOOL.to_dict()], "tool_choice": {"type": "allowed_tools", "allowed_tools": {}}}, "tool_choice"),
    ({"messages": [{"role": "function", "name": "f", "content": "x"}]}, "role"),
    ({"messages": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {}}]}]}, "content[0]"),
    ({"messages": [{"role": "user", "content": [{"type": "file", "file": {}}]}]}, "content[0]"),
    ({"frobnicate": 1}, "frobnicate"),
])
def test_refused_fields_name_the_field(extra, field):
    req = ChatCompletionRequest.model_validate({"messages": [{"role": "user", "content": "hi"}], **extra})
    with pytest.raises(InvalidRequest) as ei:
        check_request(req)
    assert field in str(ei.value)


def test_store_false_and_text_modality_are_accepted():
    check_request(ChatCompletionRequest(messages=[ChatMessage.user("hi")], store=False, modalities=["text"]))


# ── the six behaviours that used to be silent ────────────────────────

def test_1_openai_refusal_is_kept():
    transport, _ = vendor("openai", lambda b, r: {"model": "gpt-x", "choices": [{"index": 0, "finish_reason": "stop",
                          "message": {"role": "assistant", "content": None, "refusal": "I can't help with that."}}]})
    cm = provider("openai", transport).chat_model("gpt-6.1-sol")
    c = cm.chat_completions_create(messages=[ChatMessage.user("x")])
    assert c.refusal == "I can't help with that." and c.finish_reason == "content_filter" and c.text == ""
    legacy = cm.generate(ChatRequest([Message.user("x")]))
    assert legacy.refusal == "I can't help with that." and legacy.finish_reason == "content_filter"


@pytest.mark.parametrize("choice", ["required", {"type": "function", "function": {"name": SPEC.name}}])
def test_2_forced_tool_choice_is_refused_where_not_declared_and_the_gateway_moves_on(choice):
    cm = provider("ollama", live_models=False).chat_model("llama3.2")
    assert not cm.capabilities.forced_tool_choice
    with pytest.raises(UnsupportedFeature):
        cm.chat_completions_create(messages=[ChatMessage.user(QUESTION)], tools=[TOOL], tool_choice=choice)
    gw = make_gateway({"providers": [{"name": "ollama", "config": {"enabled": True, "live_models": False}}],
                       "aliases": {"default": ["ollama/llama3.2", "mock/mock-planner"]}},
                      transports={"ollama": FakeVendor("ollama").transport})
    c = gw.chat_completions_create(messages=[ChatMessage.user(QUESTION)], tools=[TOOL], tool_choice=choice)
    assert c.sajha.provider == "mock"
    assert any(a["candidate"] == "ollama/llama3.2" and "tool_choice" in a["detail"] for a in c.sajha.attempts)


def test_3_cohere_named_choice_only_when_it_is_the_one_tool_offered():
    transport, seen = vendor("cohere", lambda b, r: {"finish_reason": "COMPLETE", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "ok"}]}, "usage": {"tokens": {"input_tokens": 1}}})
    cm = provider("cohere", transport).chat_model("command-a-03-2025")
    named = {"type": "function", "function": {"name": SPEC.name}}
    with pytest.raises(UnsupportedFeature):
        cm.chat_completions_create(messages=[ChatMessage.user("x")], tools=[TOOL, FX], tool_choice=named)
    assert not seen                                     # refused before any call
    cm.chat_completions_create(messages=[ChatMessage.user("x")], tools=[TOOL], tool_choice=named)
    assert seen[-1]["body"]["tool_choice"] == "REQUIRED" and len(seen[-1]["body"]["tools"]) == 1


def test_4_temperature_dropped_is_named_in_sajha_ignored():
    transport, seen = vendor("anthropic", lambda b, r: {"model": b["model"], "stop_reason": "end_turn",
                                                       "content": [{"type": "text", "text": "ok"}],
                                                       "usage": {"input_tokens": 3, "output_tokens": 1}})
    cm = provider("anthropic", transport).chat_model("claude-sonnet-5-5")     # catalogue flag n
    c = cm.chat_completions_create(messages=[ChatMessage.user("x")], temperature=0.0)
    assert c.sajha.ignored == ["temperature"] and "temperature" not in seen[-1]["body"]
    legacy = cm.generate(ChatRequest([Message.user("x")], temperature=0.0))
    assert legacy.notes["ignored"] == ["temperature"]


def test_5_vendor_error_finish_is_a_gateway_error_and_the_next_candidate_answers():
    transport, _ = vendor("gemini", lambda b, r: {"candidates": [{"finishReason": "MALFORMED_FUNCTION_CALL",
                                                                  "content": {"parts": []}}]})
    cm = provider("gemini", transport).chat_model("gemini-3.8-flash")
    with pytest.raises(ModelFailed):
        cm.chat_completions_create(messages=[ChatMessage.user(QUESTION)], tools=[TOOL])
    gw = make_gateway({"providers": [{"name": "gemini", "config": {"enabled": True, "api_key": "k"}}],
                       "aliases": {"default": ["gemini/gemini-3.8-flash", "mock/mock-planner"]}},
                      transports={"gemini": transport})
    c = gw.chat_completions_create(messages=[ChatMessage.user(QUESTION)], tools=[TOOL])
    assert c.sajha.provider == "mock" and c.sajha.attempts[0]["outcome"] == "failed"
    assert gw.breaker("gemini").to_dict().get("failure_count", 0) == 0     # not an outage


@pytest.mark.parametrize("kind,model,field,query,document", [
    ("cohere", "embed-v4.0", "input_type", "search_query", "search_document"),
    ("gemini", "gemini-embedding-2", "taskType", "RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT"),
])
def test_6_query_embeddings_use_the_query_input_purpose(kind, model, field, query, document):
    fake = FakeVendor(kind)
    em = provider(kind, fake.transport).embedding_model(model)

    def sent():
        b = fake.last["body"]
        return b[field] if field in b else b["requests"][0][field]
    em.embeddings_create(input=["q"], sajha=SajhaRequest(input_purpose="query"))
    assert sent() == query
    em.embeddings_create(input=["d"], sajha=SajhaRequest(input_purpose="document"))
    assert sent() == document
    em.embed(["legacy"])
    assert sent() == document                           # no purpose: the configured value


def test_gateway_embed_purpose_reaches_the_vendor():
    fake = FakeVendor("cohere")
    gw = make_gateway({"providers": [{"name": "cohere", "config": {"enabled": True, "api_key": "k"}}],
                       "aliases": {"embedding": ["cohere/embed-v4.0"]}}, transports={"cohere": fake.transport})
    gw.embed(["what is risk"], purpose="query")
    assert fake.last["body"]["input_type"] == "search_query"


# ── structured output fallback, n, embeddings formats ───────────────

def test_json_mode_model_gets_emulated_structured_output_validated():
    replies = iter(['{"wrong": 1}', '{"answer": "ok"}'])
    transport, seen = vendor("openai", lambda b, r: {"model": "deepseek-chat", "choices": [{
        "index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": next(replies)}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
    cm = provider("deepseek", transport).chat_model("deepseek-chat")
    assert not cm.capabilities.structured_output and cm.capabilities.json_mode
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
    c = cm.chat_completions_create(messages=[ChatMessage.user("x")], response_format=ResponseFormat.of_schema(schema))
    assert c.parsed() == {"answer": "ok"} and c.sajha.structured_output == "emulated"
    assert seen[0]["body"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in seen[0]["body"]["messages"][-1]["content"] and len(seen) == 2   # one retry
    assert c.usage.prompt_tokens == 10                                                       # both calls


def test_embeddings_base64_and_dimensions():
    gw = make_gateway()
    r = gw.embeddings_create(model="embedding", input=["alpha"], encoding_format="base64")
    assert isinstance(r.data[0].embedding, str)
    assert decode_base64_floats(r.data[0].embedding) == pytest.approx(gw.embed(["alpha"])[0], rel=1e-6)
    assert r.object == "list" and r.data[0].object == "embedding" and r.usage.total_tokens > 0
    assert r.sajha.usage_estimated
    em = provider("cohere", FakeVendor("cohere").transport).embedding_model("embed-v4.0")
    em.embeddings_create(input=["x"], dimensions=256)      # variable size: accepted
    em2 = provider("anthropic").chat_model("claude-sonnet-5-5")
    assert em2                                            # (anthropic has no embeddings)
    fixed = make_gateway().providers["mock"].embedding_model("mock-embed")
    fixed.capabilities = fixed.capabilities.merged(variable_dimensions=False)
    with pytest.raises(UnsupportedFeature):
        fixed.embeddings_create(input=["x"], dimensions=12)


# ── the gateway's canonical interface ──────────────────────────────

def test_gateway_create_markers_cache_and_audit():
    gw = make_gateway()
    records = []
    gw.audit_hook = records.append
    ctx = RequestContext(user_id="u1", roles=["user"], trace_id="t-1")
    kw = dict(model="default", messages=[ChatMessage.user(QUESTION)], temperature=0, user="end-user-7",
              metadata={"ticket": "42"}, sajha=SajhaRequest(context=ctx))
    c1 = gw.chat_completions_create(**kw)
    assert c1.sajha.provider == "mock" and c1.sajha.qualified_model == "mock/mock-planner"
    assert c1.sajha.trace_id == "t-1" and not c1.sajha.cached
    c2 = gw.chat_completions_create(**kw)
    assert c2.sajha.cached and c2.usage.total_tokens == 0 and c2.text == c1.text
    assert records[0]["end_user"] == "end-user-7" and records[0]["metadata"] == {"ticket": "42"}
    assert records[1]["outcome"] == "cache_hit"


def test_gateway_refusals_are_not_cached():
    gw = make_gateway({"aliases": {"default": ["mock/mock-scripted"]}})
    gw.providers["mock"].set_script([{"refusal": "no."}, {"text": "fine"}])
    kw = dict(messages=[ChatMessage.user("x")], temperature=0)
    first = gw.chat_completions_create(**kw)
    assert first.finish_reason == "content_filter" and first.refusal == "no."
    assert gw.chat_completions_create(**kw).text == "fine"         # not served from the cache


def test_gateway_stream_usage_chunk_only_when_asked():
    gw = make_gateway()
    plain = list(gw.chat_completions_stream(messages=[ChatMessage.user("hello there")], model="mock/mock-echo"))
    assert not any(c.is_usage for c in plain) and plain[-1].choices[0].finish_reason == "stop"
    asked = list(gw.chat_completions_stream(messages=[ChatMessage.user("hello there")], model="mock/mock-echo",
                                            stream_options={"include_usage": True}))
    assert asked[-1].is_usage and asked[-1].sajha.provider == "mock"


def test_gateway_native_async_with_fallback():
    transport, seen = vendor("openai", lambda b, r: {"choices": [{"index": 0, "finish_reason": "stop", "message": {
        "role": "assistant", "content": "async ok"}}], "usage": {"prompt_tokens": 2, "completion_tokens": 2}})
    gw = make_gateway({"providers": [{"name": "openai", "config": {"enabled": True, "api_key": "k"}}],
                       "aliases": {"default": ["openai/gpt-6.1-sol", "mock/mock-planner"]}},
                      transports={"openai": transport})

    async def run():
        c = await gw.achat_completions_create(messages=[ChatMessage.user("x")])
        chunks = [ch async for ch in gw.achat_completions_stream(messages=[ChatMessage.user("x")], model="mock/mock-echo")]
        legacy = await gw.achat(ChatRequest([Message.user("x")]))
        return c, chunks, legacy
    c, chunks, legacy = anyio.run(run)
    assert c.text == "async ok" and c.sajha.provider == "openai" and seen
    assert gw.providers["openai"]._aclients is not None
    assert "".join(ch.choices[0].delta.content or "" for ch in chunks if ch.choices) == "echo: x"
    assert legacy.text == "async ok"


def test_gateway_n_cap_and_models_listing():
    gw = make_gateway({"gateway": {"load_entry_points": False, "use_db_providers": False, "max_samples": 2}})
    with pytest.raises(InvalidRequest):
        gw.chat_completions_create(messages=[ChatMessage.user("x")], n=3)
    infos = gw.models()
    assert any(i.qualified_id == "mock/mock-planner" and i.capabilities.tools for i in infos)
    assert infos[0].to_dict()["object"] == "model"


def test_gateway_refuses_before_trying_candidates():
    gw = make_gateway()
    with pytest.raises(InvalidRequest):
        gw.chat_completions_create(messages=[ChatMessage.user("x")], store=True)
    with pytest.raises(NoModelAvailable):
        gw.chat_completions_create(messages=[ChatMessage.user("x")],
                                   tools=[ToolDefinition.of("t", "", {"type": "object"})], model="mock/mock-echo")


def test_image_http_url_passes_through_only_to_openai_compatible():
    transport, seen = vendor("openai", lambda b, r: {"choices": [{"index": 0, "finish_reason": "stop", "message": {
        "role": "assistant", "content": "a chart"}}]})
    img = ChatMessage.user([ContentPart(type="image_url", image_url={"url": "https://x/c.png"})])
    provider("openai", transport).chat_model("gpt-6.1-sol").chat_completions_create(messages=[img])
    assert seen[-1]["body"]["messages"][0]["content"][0]["image_url"]["url"] == "https://x/c.png"
    with pytest.raises(UnsupportedFeature):
        provider("anthropic").chat_model("claude-haiku-4-5").chat_completions_create(messages=[img])


# ── cloud credentials: Vertex AI and Entra ID ─────────────────────

def _service_account(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    p = tmp_path / "sa.json"
    p.write_text(json.dumps({"type": "service_account", "client_email": "sajha@acme-prj.iam.gserviceaccount.com",
                             "private_key_id": "kid1", "private_key": pem,
                             "token_uri": "https://oauth2.googleapis.com/token"}))
    return str(p), key.public_key()


def test_vertex_gemini_uses_a_service_account_token_and_refreshes_it(tmp_path):
    import jwt
    path, pub = _service_account(tmp_path)
    calls = {"token": 0}

    def handle(request):
        if request.url.host == "oauth2.googleapis.com":
            calls["token"] += 1
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            claims = jwt.decode(form["assertion"], pub, algorithms=["RS256"], audience="https://oauth2.googleapis.com/token")
            assert claims["iss"].startswith("sajha@") and "cloud-platform" in claims["scope"]
            return httpx.Response(200, json={"access_token": f"ya29.t{calls['token']}", "expires_in": 3599})
        assert request.headers["authorization"] == f"Bearer ya29.t{calls['token']}"
        assert request.url.path == ("/v1/projects/acme-prj/locations/europe-west4/publishers/google/models/"
                                    "gemini-3.8-flash:generateContent")
        assert request.url.host == "europe-west4-aiplatform.googleapis.com"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hi"}]}, "finishReason": "STOP"}],
                                         "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}})
    p = registry.provider_class("gemini").from_settings("gemini", {
        "enabled": True, "platform": "vertex", "vertex_project": "acme-prj", "vertex_location": "europe-west4",
        "credentials_file": path}, environ={}, transport=httpx.MockTransport(handle))
    assert p.active and p.health().ok
    cm = p.chat_model("gemini-3.8-flash")
    assert cm.chat_completions_create(messages=[ChatMessage.user("x")]).text == "hi"
    cm.chat_completions_create(messages=[ChatMessage.user("x")])
    assert calls["token"] == 1                                   # cached
    p.token_source._expires_at = time.time() + 10                # inside the refresh margin
    cm.chat_completions_create(messages=[ChatMessage.user("x")])
    assert calls["token"] == 2
    assert anyio.run(lambda: cm.achat_completions_create(messages=[ChatMessage.user("x")])).text == "hi"


def test_vertex_claude_uses_raw_predict_and_workload_identity():
    def handle(request):
        if request.url.host == "metadata.google.internal":
            assert request.headers["metadata-flavor"] == "Google"
            return httpx.Response(200, json={"access_token": "ya29.wi", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer ya29.wi"
        assert request.url.path.endswith("/publishers/anthropic/models/claude-haiku-4-5@20251001:rawPredict")
        body = json.loads(request.content)
        assert body["anthropic_version"] == "vertex-2023-10-16" and "model" not in body
        assert "x-api-key" not in request.headers
        return httpx.Response(200, json={"content": [{"type": "text", "text": "from vertex"}], "stop_reason": "end_turn",
                                         "usage": {"input_tokens": 2, "output_tokens": 2}})
    p = registry.provider_class("anthropic").from_settings("anthropic", {
        "enabled": True, "platform": "vertex", "vertex_project": "acme-prj", "vertex_location": "us-east5"},
        environ={}, transport=httpx.MockTransport(handle))
    assert p.base_url == "https://us-east5-aiplatform.googleapis.com"
    c = p.chat_model("claude-haiku-4-5@20251001").chat_completions_create(messages=[ChatMessage.user("x")])
    assert c.text == "from vertex"


@pytest.mark.parametrize("mode", ["client_secret", "workload_identity", "managed_identity"])
def test_azure_openai_entra_id_tokens(mode, tmp_path):
    fed = tmp_path / "token"
    fed.write_text("federated-jwt")
    tokens = {"n": 0}

    def handle(request):
        if request.url.host in ("login.microsoftonline.com", "169.254.169.254"):
            tokens["n"] += 1
            if mode == "managed_identity":
                assert request.headers["metadata"] == "true"
                assert request.url.params["resource"] == "https://cognitiveservices.azure.com"
            else:
                form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
                assert form["grant_type"] == "client_credentials" and form["client_id"] == "app-1"
                if mode == "client_secret":
                    assert form["client_secret"] == "s3cret"
                else:
                    assert form["client_assertion"] == "federated-jwt"
                assert request.url.path == "/tenant-1/oauth2/v2.0/token"
            return httpx.Response(200, json={"access_token": f"entra-{tokens['n']}", "expires_in": "3600"})
        assert request.headers["authorization"] == f"Bearer entra-{tokens['n']}"
        assert "api-key" not in request.headers
        return httpx.Response(200, json={"choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": "ok"}}]})
    cfg = {"enabled": True, "base_url": "https://res.openai.azure.com", "auth": "entra", "deployments": {"gpt-x": "d1"},
           "tenant_id": "tenant-1", "client_id": "app-1"}
    if mode == "client_secret":
        cfg["client_secret"] = "s3cret"
    elif mode == "workload_identity":
        cfg["federated_token_file"] = str(fed)
    p = registry.provider_class("azure_openai").from_settings("azure_openai", cfg, environ={},
                                                              transport=httpx.MockTransport(handle))
    assert p.active and p.token_source.effective_mode() == mode
    cm = p.chat_model("gpt-x")
    assert cm.chat_completions_create(messages=[ChatMessage.user("x")]).text == "ok"
    cm.chat_completions_create(messages=[ChatMessage.user("x")])
    assert tokens["n"] == 1
    p.token_source.invalidate()
    assert anyio.run(lambda: cm.achat_completions_create(messages=[ChatMessage.user("x")])).text == "ok"
    assert tokens["n"] == 2
    assert "s3cret" not in json.dumps(p.describe_config(), default=str)


def test_entra_token_refusal_is_an_authentication_error():
    from sajha.ai.llm.cloud_auth import EntraTokenSource
    from sajha.ai.llm.errors import AuthenticationFailed
    src = EntraTokenSource("t", "c", "bad", transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error": "invalid_client"})), environ={})
    with pytest.raises(AuthenticationFailed):
        src.token()


def test_legacy_tool_spec_is_unchanged_for_old_callers():
    assert ToolSpec.from_mcp({"name": "a", "description": "d", "inputSchema": {"type": "object"}}).name == "a"
