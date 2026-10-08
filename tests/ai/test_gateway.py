# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Gateway: aliases, capability matching, retry/backoff, fallback, breaker, budgets, policy, cache,
preferences, configuration precedence, registry loading, secrets and the legacy API shims."""

import json

import pytest

from sajha.ai.llm import LLMFactory
from sajha.ai.llm import BudgetExceeded, ContentFiltered, NoModelAvailable, PolicyDenied, RequestContext
from sajha.ai.llm.types import ChatRequest, Done, Message, TextDelta, ToolSpec
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.settings import AISettings
from tests.ai.conftest import make_gateway

SPEC = ToolSpec("calc_percentage_change", "Calculate percentage change between two values",
                {"type": "object", "properties": {"old_value": {"type": "number"}, "new_value": {"type": "number"}}})


def two_mocks(**extra):
    raw = {"providers": [{"name": "mock", "config": {"enabled": True, "scripts_dir": ""}},
                         {"name": "backup", "type": "mock", "config": {"enabled": True, "scripts_dir": ""}}],
           "aliases": {"default": ["mock/mock-scripted", "backup/mock-echo"]}}
    raw.update(extra)
    return make_gateway(raw)


def req(text="hello", **kw):
    return ChatRequest([Message.user(text)], **kw)


# ── resolution ──────────────────────────────────────────────────

def test_out_of_the_box_everything_is_the_mock(gateway):
    assert list(gateway._providers) == ["mock"]
    assert gateway.resolve("default").qualified_id == "mock/mock-planner"
    assert gateway.embedding_model().qualified_id == "mock/mock-embed"
    d = gateway.describe_config()
    assert d["mock_active"] is True and "SAJHA_AI_ALIASES_DEFAULT" in d["note"]
    assert d["providers"]["openai"]["active"] is False


def test_key_in_env_does_not_enable_a_provider():
    gw = make_gateway(environ={"OPENAI_API_KEY": "sk-live-123456789"})
    assert not gw.providers["openai"].active
    gw = make_gateway(environ={"OPENAI_API_KEY": "sk-live-123456789", "SAJHA_AI_OPENAI_ENABLED": "true"})
    assert gw.providers["openai"].active


def test_explicit_and_bare_provider_candidates(gateway):
    assert gateway.resolve("mock/mock-echo").id == "mock-echo"
    assert gateway.resolve("mock").id == "mock-planner"


def test_capability_matching_skips_models_without_tools():
    gw = make_gateway({"aliases": {"default": ["mock/mock-echo", "mock/mock-planner"]}})
    r = gw.chat(req("What is the percentage change from 80 to 100?", tools=[SPEC]))
    assert r.model == "mock-planner" and r.tool_calls
    assert gw.chat(req("hi")).model == "mock-echo"


def test_disabled_and_unknown_candidates_are_skipped_with_reasons():
    gw = make_gateway({"aliases": {"default": ["openai/gpt-6.1-sol", "nope/x"]}})
    with pytest.raises(NoModelAvailable) as ei:
        gw.chat(req())
    assert "provider disabled" in str(ei.value) and "no such provider" in str(ei.value)


# ── reliability ─────────────────────────────────────────────────

def test_retry_with_retry_after_then_success():
    gw = two_mocks()
    gw.providers["mock"].set_script([{"error": "rate_limited", "retry_after": 0.25}, {"text": "ok"}])
    r = gw.chat(req())
    assert r.text == "ok" and r.provider == "mock"
    assert gw.sleeps == [0.25]


def test_jittered_backoff_bounds():
    gw = two_mocks(retry={"max_retries": 3, "backoff_base_s": 1.0, "backoff_max_s": 3.0, "jitter": 0.5})
    gw.providers["mock"].set_script([{"error": "unavailable"}] * 3 + [{"text": "ok"}])
    assert gw.chat(req()).text == "ok"
    lo_hi = [(0.5, 1.5), (1.0, 3.0), (1.5, 4.5)]          # base*2^n capped at 3, +/-50%
    assert len(gw.sleeps) == 3
    for d, (lo, hi) in zip(gw.sleeps, lo_hi):
        assert lo <= d <= hi


def test_fallback_after_retries_exhausted():
    gw = two_mocks(retry={"max_retries": 1})
    gw.providers["mock"].set_script([{"error": "unavailable"}], loop=True)
    r = gw.chat(req("hi"))
    assert r.provider == "backup" and r.text == "echo: hi"
    assert len(gw.sleeps) == 1


def test_fault_injection_fail_every_with_fallback():
    gw = make_gateway({"providers": [
        {"name": "mock", "config": {"enabled": True, "scripts_dir": "", "fail_every": 1, "fail_with": "unavailable",
                                    "latency_ms": [1, 3], "seed": 7}},
        {"name": "backup", "type": "mock", "config": {"enabled": True, "scripts_dir": ""}}],
        "aliases": {"default": ["mock/mock-echo", "backup/mock-echo"]}, "retry": {"max_retries": 0}})
    r = gw.chat(req("x"))
    assert r.provider == "backup"


def test_circuit_breaker_opens_and_skips_provider():
    gw = two_mocks(retry={"max_retries": 0}, breaker={"failure_threshold": 2, "recovery_timeout_s": 60})
    gw.providers["mock"].set_script([{"error": "unavailable"}], loop=True)
    for _ in range(2):
        assert gw.chat(req("x")).provider == "backup"
    calls = gw.providers["mock"].calls
    assert gw.breaker("mock").state.value == "open"
    assert gw.chat(req("x")).provider == "backup"
    assert gw.providers["mock"].calls == calls            # not even tried


def test_auth_failure_marks_provider_down():
    gw = two_mocks()
    gw.providers["mock"].set_script([{"error": "auth"}], loop=True)
    assert gw.chat(req("x")).provider == "backup"
    calls = gw.providers["mock"].calls
    assert gw.chat(req("y")).provider == "backup"
    assert gw.providers["mock"].calls == calls
    assert gw.provider_health("mock").status == "down"


def test_content_filtered_is_not_retried_or_fallen_back():
    gw = two_mocks()
    gw.providers["mock"].set_script([{"error": "content_filtered"}], loop=True)
    with pytest.raises(ContentFiltered):
        gw.chat(req())
    assert gw.sleeps == []


def test_stream_falls_back_before_first_event():
    gw = two_mocks(retry={"max_retries": 0})
    gw.providers["mock"].set_script([{"error": "unavailable"}], loop=True)
    events = list(gw.stream(req("hi")))
    assert isinstance(events[-1], Done) and events[-1].response.provider == "backup"
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "echo: hi"


# ── budgets and policy ──────────────────────────────────────────

def test_budget_refusal_per_user():
    gw = make_gateway({"budgets": {"per_user_daily_tokens": 5}})
    ctx = RequestContext(user_id="alice")
    gw.chat(req("a fairly long question to use some tokens", metadata=ctx))
    with pytest.raises(BudgetExceeded):
        gw.chat(req("again", metadata=ctx))
    gw.chat(req("someone else", metadata=RequestContext(user_id="bob")))


def test_budget_per_role_and_role_policy_daily_tokens():
    gw = make_gateway({"budgets": {"per_role_daily_tokens": {"analyst": 3}}})
    ctx = RequestContext(user_id="a", roles=["analyst"])
    gw.chat(req("question with tokens", metadata=ctx))
    with pytest.raises(BudgetExceeded):
        gw.chat(req("x", metadata=RequestContext(user_id="b", roles=["analyst"])))
    gw2 = make_gateway({"policy": {"roles": {"user": {"daily_tokens": 2}}}})
    gw2.chat(req("question with tokens", metadata=RequestContext(user_id="c", roles=["user"])))
    with pytest.raises(BudgetExceeded):
        gw2.chat(req("x", metadata=RequestContext(user_id="c", roles=["user"])))


def test_policy_allowed_models_tools_and_token_cap():
    gw = make_gateway({"policy": {"roles": {"viewer": {"allowed": ["mock/mock-echo"], "tools": False,
                                                       "max_output_tokens": 50}}},
                       "aliases": {"default": ["mock/mock-planner", "mock/mock-echo"]}})
    viewer = RequestContext(user_id="v", roles=["viewer"])
    assert gw.chat(req("hi", metadata=viewer)).model == "mock-echo"
    with pytest.raises(PolicyDenied):
        gw.chat(req("hi", tools=[SPEC], metadata=viewer))
    prepared = gw._prepare(req("hi", max_output_tokens=4000, metadata=viewer), viewer)
    assert prepared.max_output_tokens == 50
    with pytest.raises(NoModelAvailable) as ei:
        gw.chat(req("hi", metadata=viewer), model="mock/mock-planner")
    assert "not allowed" in str(ei.value)
    # roles without a policy (and no default) are unrestricted
    assert gw.chat(req("hi", metadata=RequestContext(user_id="u", roles=["user"]))).model == "mock-planner"


# ── cache and preferences ───────────────────────────────────────

def test_response_cache_hits_for_temperature_zero_only():
    gw = make_gateway()
    p = gw.providers["mock"]
    r1 = gw.chat(req("cache me", temperature=0), model="mock/mock-echo")
    n = p.calls
    r2 = gw.chat(req("cache me", temperature=0), model="mock/mock-echo")
    assert r2.cached and r2.text == r1.text and p.calls == n
    gw.chat(req("cache me", temperature=0.7), model="mock/mock-echo")
    gw.chat(req("cache me", temperature=0.7), model="mock/mock-echo")
    assert p.calls == n + 2
    assert gw._cache.stats()["hits"] == 1


def test_user_preference_overrides_alias():
    gw = two_mocks()
    gw.set_user_preference("u1", provider="backup", model="mock-echo")
    assert gw.resolve("default", ctx=RequestContext(user_id="u1")).qualified_id == "backup/mock-echo"
    assert gw.resolve("default", ctx=RequestContext(user_id="u2")).qualified_id == "mock/mock-scripted"
    gw.set_system_default("backup", "mock-planner")
    assert gw.resolve("default").qualified_id == "backup/mock-planner"


# ── configuration ───────────────────────────────────────────────

def test_settings_env_precedence_and_sources():
    s = AISettings({"ask": {"max_steps": 3}, "aliases": {"fast": ["mock/mock-echo"]}},
                   environ={"SAJHA_AI_ASK_MAX_STEPS": "9", "SAJHA_AI_ALIASES_DEFAULT": "openai, mock/mock-planner",
                            "SAJHA_AI_CACHE_ENABLED": "false",
                            "SAJHA_AI_POLICY_ROLES": json.dumps({"viewer": {"tools": False}})})
    assert s.ask.max_steps == 9 and s.sources["ask"]["max_steps"] == "env:SAJHA_AI_ASK_MAX_STEPS"
    assert s.aliases["default"] == ["openai", "mock/mock-planner"]
    assert s.aliases["fast"] == ["mock/mock-echo"] and s.sources["aliases"]["fast"] == "config"
    assert s.cache.enabled is False
    assert s.policy.roles["viewer"].tools is False
    assert s.sources["ask"]["timeout_s"] == "default"


def test_unknown_setting_fails_with_a_clear_message():
    with pytest.raises(ValueError) as ei:
        AISettings({"ask": {"max_stepz": 3}})
    assert "max_stepz" in str(ei.value)
    gw = make_gateway({"providers": [{"name": "openai", "config": {"api_keyy": "x"}}]})
    assert any("api_keyy" in e for e in gw.build_errors)


def test_every_provider_field_is_env_overridable():
    gw = make_gateway(environ={"SAJHA_AI_OLLAMA_NUM_CTX": "16384", "SAJHA_AI_OLLAMA_KEEP_ALIVE": "10m",
                               "SAJHA_AI_AZURE_OPENAI_API_VERSION": "2025-01-01",
                               "SAJHA_AI_OPENAI_EXTRA_HEADERS": '{"X-Team": "risk", "X-Api-Token": "s"}',
                               "SAJHA_AI_ANTHROPIC_MODELS": '[{"id": "claude-next", "tools": true}]',
                               "SAJHA_AI_MOCK_FAIL_EVERY": "4"})
    p = gw.providers
    assert p["ollama"].config.num_ctx == 16384 and p["ollama"].config.keep_alive == "10m"
    assert p["azure_openai"].config.api_version == "2025-01-01"
    assert p["anthropic"].chat_model("claude-next").capabilities.tools
    assert p["mock"].config.fail_every == 4
    desc = p["openai"].describe_config()["settings"]["extra_headers"]
    assert desc["value"]["X-Api-Token"] == "********" and desc["value"]["X-Team"] == "risk"
    assert desc["source"] == "env:SAJHA_AI_OPENAI_EXTRA_HEADERS"


def test_api_key_ref_and_secret_store(tmp_path):
    f = tmp_path / "key.txt"
    f.write_text("sk-from-file-000000\n")
    gw = make_gateway({"providers": [{"name": "openai", "config": {"enabled": True, "api_key_ref": f"file:{f}"}}]})
    assert gw.providers["openai"].api_key == "sk-from-file-000000"
    d = gw.providers["openai"].describe_config()
    assert d["settings"]["api_key"]["value"] == "********" and "sk-from-file" not in json.dumps(d)
    store = SecretStore(db_lookup=lambda t, k: "db-secret" if (t, k) == ("llm_providers", "openai") else None,
                        environ={"X": "env-secret"})
    assert store.resolve("env:X") == "env-secret"
    assert store.resolve("db:llm_providers/openai") == "db-secret"
    assert SecretStore.redact("key sk-abcdefghijk123 here") == "key ******** here"
    with pytest.raises(ValueError):
        store.resolve("vault:x")


def test_db_table_is_lowest_precedence_source():
    from sajha.ai.llm import registry
    cls = registry.provider_class("openai")
    p = cls.from_settings("openai", {}, db={"api_key": "db-key"}, environ={})
    assert p.api_key == "db-key" and p.sources["api_key"] == "db"
    p = cls.from_settings("openai", {"api_key": "cfg"}, db={"api_key": "db-key"}, environ={})
    assert p.api_key == "cfg"


# ── registry: class path, entry points, legacy providers ────────

def test_class_path_entry_and_bad_class_path():
    gw = make_gateway({"providers": [
        {"name": "lab", "class": "sajha.ai.llm.mock:MockProvider", "config": {"enabled": True, "scripts_dir": ""}},
        {"name": "broken", "class": "no.such.module:Thing"}],
        "aliases": {"default": ["lab/mock-echo"]}})
    assert gw.chat(req("hi")).provider == "lab"
    assert any("broken" in e and "cannot load" in e for e in gw.build_errors)


def test_entry_point_plugins(monkeypatch):
    from sajha.ai.llm import registry
    from sajha.ai.llm.mock import MockProvider

    class PluginProvider(MockProvider):
        name = "plugged"

    class EP:
        name = "plugged"

        def load(self):
            return PluginProvider

    import importlib.metadata as md
    monkeypatch.setattr(md, "entry_points", lambda group=None: [EP()] if group == registry.ENTRY_POINT_GROUP else [])
    try:
        assert registry.load_entry_points() == ["plugged"]
        assert registry.provider_class("plugged") is PluginProvider
    finally:
        registry.unregister_provider("plugged")


def test_register_provider_validates():
    from sajha.ai.llm import ConfigurationError
    from sajha.ai.llm.spi import register_provider

    with pytest.raises(ConfigurationError):
        register_provider(object)


def test_legacy_provider_class_is_wrapped():
    from sajha.ai.llm.spi import LegacyLLMProvider as OldProvider, LegacyModelInfo as ModelInfo, LLMResponse
    from sajha.ai.llm.spi import register_provider_class, unregister_provider_class

    class OldStyle(OldProvider):
        provider_type = "oldstyle"

        def __init__(self, **kw):
            self.kw = kw

        def complete(self, messages, model, temperature=0.7, max_tokens=1024, system="", tools=None, **kw):
            return LLMResponse(content=f"old:{messages[-1]['content']}", model=model, provider="oldstyle",
                               input_tokens=3, output_tokens=2)

        def stream(self, *a, **k):
            yield "x"

        def list_models(self):
            return [ModelInfo(id="old-1", name="Old 1", provider="oldstyle")]

        def health_check(self):
            return True

    register_provider_class("oldstyle", OldStyle)
    try:
        gw = make_gateway({"providers": [{"name": "oldstyle", "class": "sajha.ai.llm.legacy:LegacyProviderAdapter",
                                          "config": {"enabled": True, "legacy_type": "oldstyle"}}],
                           "aliases": {"default": ["oldstyle/old-1"]}})
        r = gw.chat(req("hi"))
        assert r.text == "old:hi" and r.provider == "oldstyle"
    finally:
        unregister_provider_class("oldstyle")


# ── the factory's catalog and admin surface (ai_routes, settings page) ──

def test_factory_catalog_and_admin(gateway):
    from sajha.ai.llm import ChatMessage, RequestContext
    ctx = RequestContext(user_id="u")
    c = gateway.model("mock/mock-echo", context=ctx).chat_completions_create(messages=[ChatMessage.user("hello")])
    assert c.text == "echo: hello" and c.sajha.provider == "mock" and c.usage.total_tokens > 0
    assert gateway.qualify("mock", "mock-echo") == "mock/mock-echo"
    assert gateway.qualify("", "mock-echo") == "mock/mock-echo"       # bare model id: provider found by listing
    assert gateway.qualify("", "fast") == "fast" and gateway.qualify() == "default"
    emb = gateway.embed(["a b", "c"])
    assert len(emb.embeddings) == 2 and emb.dimensions == 256 and emb.provider == "mock"
    assert {m.id for m in gateway.models()} >= {"mock-echo", "mock-planner", "mock-embed"}
    assert gateway.health_check_all() == {"mock": True}
    st = gateway.get_stats()
    assert st["providers"] == ["mock"] and st["default_provider"] == "mock"
    assert gateway.get_token_usage("u")["mock"]["mock-echo"]["count"] == 1
    assert gateway.config.default_model == "mock-planner"


def test_mock_embed_is_deterministic_and_similar_text_is_closer(gateway):
    a, b, c = gateway.embed(["percentage change between values", "percentage change of two values",
                             "black scholes option price"])
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert gateway.embed(["percentage change between values"])[0] == a
    assert dot(a, b) > dot(a, c)


def test_tool_resolver_gateway_embedder_works_with_mock(toolbox):
    from sajha.ai.embedders import GatewayEmbedder
    gw = make_gateway()
    vecs = GatewayEmbedder(gw).embed(["hello"])
    assert len(vecs) == 1 and len(vecs[0]) == 256


def test_shipped_application_yml_builds_cleanly_and_describes_as_json():
    from sajha.ai.llm.settings import load_ai_yaml
    raw = load_ai_yaml("config/application.yml")
    raw.setdefault("gateway", {})["use_db_providers"] = False
    gw = make_gateway(raw)
    assert gw.build_errors == []
    assert list(gw._providers) == ["mock"]                    # every real provider ships disabled
    d = json.loads(json.dumps(gw.describe_config()))
    assert d["mock_active"] is True
    assert set(d["resolved_aliases"]) >= {"default", "fast", "reasoning", "embedding"}


def test_async_wrappers(gateway):
    import anyio

    async def main():
        r = await gateway.achat(req("hi"), model="mock/mock-echo")
        v = await gateway.aembed(["x"])
        return r, v

    r, v = anyio.run(main)
    assert r.text == "echo: hi" and len(v[0]) == 256
