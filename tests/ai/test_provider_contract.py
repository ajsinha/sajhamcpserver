"""
Provider contract suite: every registered provider family, offline against recorded-shape fake
APIs (httpx.MockTransport; a fake boto3 client for Bedrock), plus live runs when a key is set.

Each provider must: list models, chat, round-trip a tool call in its own wire format, return
structured output when it declares the capability, stream events in order (deltas, usage, Done
last) and map vendor errors onto the SAJHA taxonomy.
"""

import json
import os

import pytest

from sajha.ai.llm import (AuthenticationFailed, ContentFiltered, ContextTooLong, ProviderUnavailable, RateLimited,
                          UnsupportedFeature)
from sajha.ai.llm.types import (ChatRequest, Done, Message, TextDelta, ToolCallDelta, ToolCallPart, ToolSpec,
                                UsageEvent)
from sajha.ai.llm import registry
from tests.ai.fakes import TOOL_ARGS, TOOL_NAME, FakeBedrockClient, FakeVendor

QUESTION = "What is the percentage change from 80 to 100?"
SPEC = ToolSpec(TOOL_NAME, "Calculate percentage change between two values",
                {"type": "object", "properties": {"old_value": {"type": "number"}, "new_value": {"type": "number"}},
                 "required": ["old_value", "new_value"]})
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


def _h(rec, name):
    return rec["headers"].get(name)


# provider -> (fake kind, extra config, model, chat-shape check, tool-result check, embedding model)
CASES = {
    "openai": ("openai", {}, "gpt-6.1-sol",
               lambda r: r["path"] == "/v1/chat/completions" and _h(r, "authorization") == "Bearer k"
               and "max_completion_tokens" in r["body"],
               lambda r: any(m["role"] == "tool" and m["tool_call_id"] == "call_abc" for m in r["body"]["messages"]),
               "text-embedding-3-small"),
    "azure_openai": ("openai", {"base_url": "https://res.openai.azure.com", "deployments": {"gpt-x": "dep1"}},
                     "gpt-x",
                     lambda r: r["path"] == "/openai/v1/chat/completions" and _h(r, "api-key") == "k"
                     and r["body"]["model"] == "dep1",
                     lambda r: any(m["role"] == "tool" for m in r["body"]["messages"]), "text-embedding-3-small"),
    "groq": ("openai", {}, "llama-3.3-70b-versatile",
             lambda r: r["url"].startswith("https://api.groq.com/openai/v1/chat/completions")
             and "max_tokens" in r["body"],
             lambda r: any(m["role"] == "tool" for m in r["body"]["messages"]), None),
    "mistral": ("openai", {}, "mistral-large-4-0",
                lambda r: r["url"].startswith("https://api.mistral.ai/v1/chat/completions"),
                lambda r: any(m["role"] == "tool" for m in r["body"]["messages"]), "mistral-embed"),
    "vllm": ("openai", {"base_url": "http://gpu-box:8000/v1"}, "my-local-model",
             lambda r: r["url"].startswith("http://gpu-box:8000/v1/chat/completions"),
             lambda r: any(m["role"] == "tool" for m in r["body"]["messages"]), "bge-m3"),
    "anthropic": ("anthropic", {}, "claude-sonnet-5-5",
                  lambda r: r["path"] == "/v1/messages" and _h(r, "x-api-key") == "k"
                  and _h(r, "anthropic-version") and r["body"]["max_tokens"] > 0
                  and "temperature" not in r["body"],          # sampling removed on this model
                  lambda r: any(isinstance(m["content"], list) and any(c.get("type") == "tool_result"
                                and c["tool_use_id"] == "toolu_1" for c in m["content"])
                                for m in r["body"]["messages"])
                  and any(c.get("type") == "thinking" for m in r["body"]["messages"] if m["role"] == "assistant"
                          for c in m["content"]),                # thinking block echoed back verbatim
                  None),
    "gemini": ("gemini", {}, "gemini-3.8-flash",
               lambda r: r["path"] == "/v1beta/models/gemini-3.8-flash:generateContent"
               and _h(r, "x-goog-api-key") == "k" and "systemInstruction" in r["body"],
               lambda r: any("functionResponse" in p and p["functionResponse"]["name"] == TOOL_NAME
                             for c in r["body"]["contents"] for p in c["parts"])
               and any(p.get("thoughtSignature") == "abc" for c in r["body"]["contents"] for p in c["parts"]),
               "gemini-embedding-2"),
    "cohere": ("cohere", {}, "command-a-03-2025",
               lambda r: r["path"] == "/v2/chat" and _h(r, "authorization") == "Bearer k",
               lambda r: any(m["role"] == "tool" and m["tool_call_id"] == "co_1" for m in r["body"]["messages"]),
               "embed-v4.0"),
    "ollama": ("ollama", {"live_models": False}, "llama3.2",
               lambda r: r["path"] == "/api/chat" and r["body"]["options"]["num_predict"] > 0,
               lambda r: any(m["role"] == "tool" and m["tool_name"] == TOOL_NAME for m in r["body"]["messages"]),
               "nomic-embed-text"),
    "bedrock": ("bedrock", {"region": "us-east-1"}, "anthropic.claude-haiku-4-5",
                lambda r: r["body"]["modelId"] == "anthropic.claude-haiku-4-5" and "inferenceConfig" in r["body"],
                lambda r: any("toolResult" in c and c["toolResult"]["toolUseId"] == "tu_1"
                              for m in r["body"]["messages"] for c in m["content"]),
                "amazon.titan-embed-text-v2:0"),
}
MOCK_ERRORS = {"rate": "rate_limited", "auth": "auth", "context": "context_too_long", "server": "unavailable",
               "filter": "content_filtered", "connect": "unavailable", "notfound": "unsupported"}


class Harness:
    def __init__(self, name):
        self.name = name
        if name == "mock":
            cls = registry.provider_class("mock")
            self.provider = cls.from_settings("mock", {"enabled": True, "scripts_dir": ""}, environ={})
            self.model, self.fake, self.embedding = "mock-planner", None, "mock-embed"
            self.chat_check = self.result_check = lambda r: True
            return
        kind, extra, self.model, self.chat_check, self.result_check, self.embedding = CASES[name]
        self.fake = FakeBedrockClient() if kind == "bedrock" else FakeVendor(kind)
        transport = self.fake if kind == "bedrock" else self.fake.transport
        cfg = {"enabled": True, **extra}
        if kind != "bedrock":
            cfg["api_key"] = "k"
        self.provider = registry.provider_class(name).from_settings(name, cfg, environ={}, transport=transport)

    def set_mode(self, mode):
        if self.fake is None:
            self.provider.config.fail_every = 1 if mode else 0
            self.provider.config.fail_with = MOCK_ERRORS.get(mode, "rate_limited")
            self.provider.config.retry_after_s = 3
        else:
            self.fake.mode = mode

    def last(self):
        return self.fake.last if self.fake is not None else {}

    def chat_model(self):
        return self.provider.chat_model(self.model)


PROVIDERS = ["mock"] + list(CASES)


@pytest.fixture(params=PROVIDERS)
def h(request):
    return Harness(request.param)


def test_lists_models_and_resolves_default(h):
    models = h.provider.list_models()
    assert models, f"{h.name} lists no models"
    cm = h.chat_model()
    assert cm.provider is h.provider and cm.id == h.model
    assert h.provider.active


def test_plain_chat(h):
    cm = h.chat_model()
    resp = cm.generate(ChatRequest([Message.user(QUESTION)], system="Be brief.", max_output_tokens=200))
    assert resp.text
    assert resp.finish_reason == "stop"
    assert resp.provider == h.name
    assert resp.usage.input_tokens > 0 and resp.usage.output_tokens > 0
    if h.fake is not None:
        assert resp.text == "Hello there"
        assert h.chat_check(h.last()), h.last()


def test_tool_call_round_trip(h):
    cm = h.chat_model()
    assert cm.capabilities.tools
    req = ChatRequest([Message.user(QUESTION)], tools=[SPEC])
    r1 = cm.generate(req)
    assert r1.finish_reason == "tool_calls"
    call = r1.tool_calls[0]
    assert isinstance(call, ToolCallPart) and call.name == TOOL_NAME
    assert call.arguments == TOOL_ARGS and call.id
    tool_msg = Message.tool_result(call.id, {"percentage_change": 25.0}, name=call.name)
    r2 = cm.generate(ChatRequest([Message.user(QUESTION), r1.message, tool_msg], tools=[SPEC]))
    assert r2.finish_reason == "stop" and r2.text and not r2.tool_calls
    if h.fake is not None:
        assert h.result_check(h.last()), h.last()


def test_structured_output_when_declared(h):
    cm = h.chat_model()
    if not cm.capabilities.structured_output:
        with pytest.raises(UnsupportedFeature):
            cm.generate(ChatRequest([Message.user("x")], response_schema=SCHEMA))
        return
    resp = cm.generate(ChatRequest([Message.user(QUESTION)], response_schema=SCHEMA))
    data = resp.json()
    assert isinstance(data, dict) and "answer" in data


def _collect(cm, req):
    return list(cm.stream(req))


def test_streaming_event_order_text(h):
    cm = h.chat_model()
    req = ChatRequest([Message.user(QUESTION)])
    if h.name == "mock":
        cm = h.provider.chat_model("mock-echo")
    events = _collect(cm, req)
    assert isinstance(events[-1], Done)
    assert isinstance(events[-2], UsageEvent)
    deltas = [e.text for e in events if isinstance(e, TextDelta)]
    assert deltas and "".join(deltas) == events[-1].response.text
    kinds = [type(e).__name__ for e in events]
    assert kinds.index("UsageEvent") > max(i for i, k in enumerate(kinds) if k == "TextDelta")


def test_streaming_tool_call(h):
    cm = h.chat_model()
    events = _collect(cm, ChatRequest([Message.user(QUESTION)], tools=[SPEC]))
    assert isinstance(events[-1], Done)
    deltas = [e for e in events if isinstance(e, ToolCallDelta)]
    assert deltas and deltas[0].name == TOOL_NAME
    final = events[-1].response
    assert final.tool_calls and final.tool_calls[0].arguments == TOOL_ARGS
    assert final.finish_reason == "tool_calls"


@pytest.mark.parametrize("mode,exc", [
    ("rate", RateLimited), ("auth", AuthenticationFailed), ("context", ContextTooLong),
    ("server", ProviderUnavailable), ("filter", ContentFiltered), ("connect", ProviderUnavailable),
    ("notfound", UnsupportedFeature),
])
def test_error_mapping(h, mode, exc):
    h.set_mode(mode)
    cm = h.chat_model()
    with pytest.raises(exc) as ei:
        cm.generate(ChatRequest([Message.user(QUESTION)]))
    if mode == "rate" and h.name not in ("bedrock",):
        assert ei.value.retry_after == 3
    assert ei.value.provider == h.name


def test_streaming_error_mapping(h):
    h.set_mode("rate")
    cm = h.chat_model()
    with pytest.raises(RateLimited):
        list(cm.stream(ChatRequest([Message.user(QUESTION)])))


def test_embeddings_where_offered(h):
    emb_id = h.embedding
    if not emb_id:
        with pytest.raises(UnsupportedFeature):
            h.provider.embedding_model("")
        return
    em = h.provider.embedding_model(emb_id)
    vecs = em.embed(["alpha", "beta"])
    assert len(vecs) == 2 and all(isinstance(v, list) and v for v in vecs)


def test_secret_not_in_effective_config(h):
    d = h.provider.describe_config()
    blob = json.dumps(d, default=str)
    if h.fake is not None and h.name != "bedrock":
        assert d["settings"]["api_key"]["value"] == "********"
        assert '"k"' not in blob


# ── presets: base URL and key header for every OpenAI-compatible vendor ──

@pytest.mark.parametrize("name,host", [
    ("groq", "api.groq.com"), ("together", "api.together.xyz"), ("fireworks", "api.fireworks.ai"),
    ("deepseek", "api.deepseek.com"), ("xai", "api.x.ai"), ("openrouter", "openrouter.ai"),
    ("perplexity", "api.perplexity.ai"), ("lmstudio", "localhost:1234"),
])
def test_openai_compatible_presets(name, host):
    fake = FakeVendor("openai")
    p = registry.provider_class(name).from_settings(name, {"enabled": True, "api_key": "k"}, environ={},
                                                    transport=fake.transport)
    resp = p.chat_model(p.default_chat_model_id() or "some-model").generate(ChatRequest([Message.user("hi")]))
    assert resp.text == "Hello there"
    assert host in fake.last["url"] and fake.last["headers"]["authorization"] == "Bearer k"


def test_vendor_env_and_sajha_env_precedence():
    env = {"OPENAI_API_KEY": "vendor", "SAJHA_AI_OPENAI_BASE_URL": "https://proxy.example/v1"}
    p = registry.provider_class("openai").from_settings("openai", {"api_key": "cfg", "base_url": "https://cfg/v1"},
                                                        environ=env)
    assert p.api_key == "vendor" and p.sources["api_key"] == "env:OPENAI_API_KEY"
    assert p.base_url == "https://proxy.example/v1" and p.sources["base_url"] == "env:SAJHA_AI_OPENAI_BASE_URL"
    env["SAJHA_AI_OPENAI_API_KEY"] = "sajha"
    p = registry.provider_class("openai").from_settings("openai", {"api_key": "cfg"}, environ=env)
    assert p.api_key == "sajha"
    # a key alone never enables a provider
    assert p.active is False


def test_ollama_live_models_and_capabilities():
    fake = FakeVendor("ollama")
    p = registry.provider_class("ollama").from_settings("ollama", {"enabled": True}, environ={},
                                                        transport=fake.transport)
    assert p.health().ok
    ids = {m.id: m for m in p.list_models()}
    assert "qwen3:8b" in ids and ids["qwen3:8b"].capabilities.tools        # pulled -> listed, /api/show caps
    assert ids["nomic-embed-text"].kind == "embedding"
    assert ids["llama3.2"].capabilities.context_window == 131072
    assert p.model_available("llama3.2") and not p.model_available("not-pulled")


def test_ollama_host_env_normalised():
    p = registry.provider_class("ollama").from_settings("ollama", {}, environ={"OLLAMA_HOST": "0.0.0.0:11500"})
    assert p.base_url == "http://127.0.0.1:11500"


def test_ollama_unreachable_is_down_quickly():
    fake = FakeVendor("ollama")
    fake.mode = "connect"
    p = registry.provider_class("ollama").from_settings("ollama", {"enabled": True}, environ={},
                                                        transport=fake.transport)
    assert p.health().status == "down"
    n = len(fake.requests)
    p.health()
    assert len(fake.requests) == n          # cached


def test_gemini_bad_key_is_auth_error():
    import httpx
    t = httpx.MockTransport(lambda req: httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT",
                                                                            "message": "API key not valid."}}))
    p = registry.provider_class("gemini").from_settings("gemini", {"enabled": True, "api_key": "bad"}, environ={},
                                                        transport=t)
    with pytest.raises(AuthenticationFailed):
        p.chat_model("gemini-3.8-flash").generate(ChatRequest([Message.user("hi")]))


def test_model_overrides_from_config_add_a_model_without_code():
    p = registry.provider_class("openai").from_settings("openai", {"models": [
        {"id": "ft:gpt-acme", "tools": True, "structured_output": True, "input_cost_per_mtok": 1.0,
         "output_cost_per_mtok": 2.0, "context_window": 64000}]}, environ={})
    cm = p.chat_model("ft:gpt-acme")
    assert cm.capabilities.context_window == 64000
    assert cm.make_usage(1_000_000, 1_000_000).cost_usd == pytest.approx(3.0)


def test_register_model_injects_a_custom_model_class():
    from sajha.ai.llm.spi import register_model
    from sajha.ai.llm.providers.openai_compat import OpenAIChatModel
    from sajha.ai.llm.registry import unregister_model
    from sajha.ai.llm.model import ModelCapabilities

    @register_model(provider="openai", model_id="ft:gpt-acme-risk")
    class AcmeRisk(OpenAIChatModel):
        capabilities = ModelCapabilities(tools=True, structured_output=True, tags=frozenset({"risk"}))

    try:
        p = registry.provider_class("openai").from_settings("openai", {}, environ={})
        cm = p.chat_model("ft:gpt-acme-risk")
        assert isinstance(cm, AcmeRisk) and "risk" in cm.capabilities.tags
    finally:
        unregister_model("openai", "ft:gpt-acme-risk")


# ── live providers: only when a key is configured ──────────────

LIVE = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
        "mistral": "MISTRAL_API_KEY", "cohere": "COHERE_API_KEY", "groq": "GROQ_API_KEY"}


@pytest.mark.parametrize("name", sorted(LIVE))
def test_live_provider_tool_round_trip(name):
    if not os.environ.get(LIVE[name]):
        pytest.skip(f"{LIVE[name]} not set")
    p = registry.provider_class(name).from_settings(name, {"enabled": True})
    cm = p.chat_model()
    r1 = cm.generate(ChatRequest([Message.user(QUESTION)], tools=[SPEC], max_output_tokens=512))
    assert r1.tool_calls and r1.tool_calls[0].name == TOOL_NAME
    call = r1.tool_calls[0]
    r2 = cm.generate(ChatRequest([Message.user(QUESTION), r1.message,
                                  Message.tool_result(call.id, {"percentage_change": 25.0}, name=call.name)],
                                 tools=[SPEC], max_output_tokens=512))
    assert "25" in r2.text
