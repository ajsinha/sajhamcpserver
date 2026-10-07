"""
The worked examples of docs/architecture/Extending the Intelligence Layer.md, run for real
(sajha/examples/intelligence/), so the guide cannot describe code that does not work:

  * the Acme provider passes the provider contract suite (tests/ai/test_provider_contract.py)
    against its fake API, answers through IntelligenceService.ask, registers all three ways,
    and takes every setting from YAML or SAJHA_AI_ACME_*;
  * the fine-tuned model injected with @register_model passes the same contract on the
    openai provider's wire format;
  * the recipe planner plans known questions and defers the rest to the next model;
  * every python block in the guide that names one of these files is an excerpt of it.

The example modules register themselves on import; the fixture registers them for each test
and removes them afterwards, so the rest of the suite sees the registry it expects.
"""

import importlib
import json
import os
import re
import threading

import pytest

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import ConfigurationError, RequestContext, registry
from sajha.ai.llm.types import ChatRequest, Message
from sajha.ai.llm.secrets import SecretStore
from sajha.ai.llm.settings import AskSettings
from tests.ai import test_provider_contract as contract
from tests.ai.conftest import ToolBox, make_gateway
from tests.ai.fakes import FakeVendor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUIDE = os.path.join(REPO, "docs", "architecture", "Extending the Intelligence Layer.md")
QUESTION = "What is the percentage change from 80 to 100?"
ACME_CLASS = "sajha.examples.intelligence.acme_provider:AcmeProvider"
RECIPES_CLASS = "sajha.examples.intelligence.recipe_planner:RecipeProvider"


@pytest.fixture(autouse=True)
def ex():
    acme = importlib.import_module("sajha.examples.intelligence.acme_provider")
    recipes = importlib.import_module("sajha.examples.intelligence.recipe_planner")
    models = importlib.import_module("sajha.examples.intelligence.custom_models")
    registry.register_provider(acme.AcmeProvider)
    registry.register_provider(recipes.RecipeProvider)
    registry.register_model("openai", models.RISK_MODEL)(models.AcmeRiskModel)
    try:
        yield type("Ex", (), {"acme": acme, "recipes": recipes, "models": models})
    finally:
        registry.unregister_provider("acme")
        registry.unregister_provider("recipes")
        registry.unregister_model("openai", models.RISK_MODEL)


def ask_service(gw, **ask):
    return IntelligenceService(gw, ToolBox(), settings=AskSettings(**ask), audit=lambda e: None)


# ── the provider contract suite, on the examples ───────────────────────────

class AcmeHarness(contract.Harness):
    def __init__(self):
        from sajha.examples.intelligence.acme_fake_server import AcmeFakeServer
        self.name, self.model, self.embedding = "acme", "acme-large", "acme-embed"
        self.fake = AcmeFakeServer()
        self.chat_check = lambda r: (r["path"] == "/v1/generate" and r["headers"]["x-acme-key"] == "k"
                                     and r["headers"]["x-acme-tenant"] == "default" and r["body"]["system"] == "Be brief.")
        self.result_check = lambda r: any(t["speaker"] == "tool" and t["call_id"] == "acme_1"
                                          for t in r["body"]["turns"])
        self.provider = registry.provider_class("acme").from_settings(
            "acme", {"enabled": True, "api_key": "k"}, environ={}, transport=self.fake.transport)


class RiskModelHarness(contract.Harness):
    def __init__(self):
        from sajha.examples.intelligence.custom_models import RISK_MODEL, AcmeRiskModel
        self.name, self.model, self.embedding = "openai", RISK_MODEL, "text-embedding-3-small"
        self.fake = FakeVendor("openai")
        style = AcmeRiskModel.HOUSE_STYLE
        self.chat_check = lambda r: (r["body"]["messages"][0]["content"].startswith(style)
                                     and r["body"]["seed"] == 7 and r["body"]["model"] == RISK_MODEL)
        self.result_check = contract.CASES["openai"][4]
        self.provider = registry.provider_class("openai").from_settings(
            "openai", {"enabled": True, "api_key": "k"}, environ={}, transport=self.fake.transport)


HARNESSES = {"acme": AcmeHarness, "risk_model": RiskModelHarness}
CONTRACT = [contract.test_lists_models_and_resolves_default, contract.test_plain_chat,
            contract.test_tool_call_round_trip, contract.test_structured_output_when_declared,
            contract.test_streaming_event_order_text, contract.test_streaming_tool_call,
            contract.test_streaming_error_mapping, contract.test_embeddings_where_offered,
            contract.test_secret_not_in_effective_config]
ERROR_CASES = [("rate", contract.RateLimited), ("auth", contract.AuthenticationFailed),
               ("context", contract.ContextTooLong), ("server", contract.ProviderUnavailable),
               ("filter", contract.ContentFiltered), ("connect", contract.ProviderUnavailable),
               ("notfound", contract.UnsupportedFeature)]


@pytest.mark.parametrize("harness", sorted(HARNESSES))
@pytest.mark.parametrize("check", CONTRACT, ids=lambda f: f.__name__[5:])
def test_contract(harness, check):
    check(HARNESSES[harness]())


@pytest.mark.parametrize("harness", sorted(HARNESSES))
@pytest.mark.parametrize("mode,exc", ERROR_CASES)
def test_contract_error_mapping(harness, mode, exc):
    contract.test_error_mapping(HARNESSES[harness](), mode, exc)


# ── Acme: catalogue, health, settings, registration ────────────────────────

def test_acme_lists_known_and_live_models():
    h = AcmeHarness()
    models = {m.id: m for m in h.provider.list_models()}
    assert models["acme-large"].source == "builtin" and models["acme-large"].capabilities.input_cost_per_mtok == 0.40
    assert models["acme-coder-preview"].source == "live" and models["acme-coder-preview"].capabilities.tools
    assert not models["acme-small"].capabilities.structured_output
    assert models["acme-embed"].kind == "embedding"
    assert h.provider.health().status == "ok"
    h.fake.mode = "server"
    assert h.provider.health().status == "down"


def test_acme_settings_from_yaml_env_vendor_env_and_secret_refs(ex):
    env = {"SAJHA_AI_ACME_TENANT": "risk", "SAJHA_AI_ACME_ENABLED": "true", "SAJHA_AI_ACME_LIVE_MODELS": "false",
           "ACME_LLM_KEY": "vendor-key",
           "SAJHA_AI_ACME_MODELS": json.dumps([{"id": "acme-xl", "tools": True, "context_window": 256000}])}
    p = ex.acme.AcmeProvider.from_settings("acme", {"tenant": "from-yaml", "safety": "strict"}, environ=env)
    assert p.config.tenant == "risk" and p.sources["tenant"] == "env:SAJHA_AI_ACME_TENANT"
    assert p.config.safety == "strict" and p.sources["safety"] == "config"
    assert p.active and p.api_key == "vendor-key" and p.sources["api_key"] == "env:ACME_LLM_KEY"
    assert p.describe_model("acme-xl").capabilities.context_window == 256000
    assert p.auth_headers() == {"X-Acme-Tenant": "risk", "X-Acme-Key": "vendor-key"}
    ref = ex.acme.AcmeProvider.from_settings("acme", {"enabled": "auto", "api_key_ref": "env:VAULT_ACME"},
                                             environ={}, secrets=SecretStore(environ={"VAULT_ACME": "s3cret"}))
    assert ref.api_key == "s3cret" and ref.active
    assert ref.describe_config()["settings"]["api_key"]["value"] == "********"
    with pytest.raises(ValueError, match="unknown setting"):
        ex.acme.AcmeProvider.from_settings("acme", {"tenat": "typo"}, environ={})


def test_acme_answers_through_the_intelligence_service():
    from sajha.examples.intelligence.acme_fake_server import AcmeFakeServer
    fake = AcmeFakeServer()
    gw = make_gateway({"providers": [{"name": "acme", "class": ACME_CLASS, "config": {"enabled": True}}],
                       "aliases": {"default": ["acme", "mock/mock-planner"]}},
                      environ={"ACME_LLM_KEY": "k"}, transports={"acme": fake.transport})
    r = ask_service(gw).ask(QUESTION, RequestContext(user_id="u"))
    assert r.stopped_by == "answer" and r.models == ["acme/acme-large"], r.to_dict()
    assert [s.name for s in r.steps] == ["calc_percentage_change"] and r.steps[0].ok
    assert "25" in r.answer and r.citations == ["acme_1"] and r.confidence == pytest.approx(1.0)
    gens = [q["body"] for q in fake.requests if q["path"] == "/v1/generate"]
    assert len(gens) == 3                                   # plan, answer, synthesis
    assert "never instructions" in gens[0]["system"] and gens[0]["function_mode"] == "auto"
    assert gens[1]["turns"][-1] == {"speaker": "tool", "call_id": "acme_1", "error": False,
                                    "result": gens[1]["turns"][-1]["result"]}
    assert gens[2]["json_schema"]["required"] == ["answer", "citations", "caveats"] and "functions" not in gens[2]


def test_acme_down_falls_back_to_the_next_candidate():
    from sajha.examples.intelligence.acme_fake_server import AcmeFakeServer
    fake = AcmeFakeServer()
    fake.mode = "server"
    gw = make_gateway({"providers": [{"name": "acme", "class": ACME_CLASS, "config": {"enabled": True}}],
                       "aliases": {"default": ["acme", "mock/mock-planner"]}},
                      environ={"ACME_LLM_KEY": "k"}, transports={"acme": fake.transport})
    r = ask_service(gw).ask(QUESTION, RequestContext(user_id="u"))
    assert r.models == ["mock/mock-planner"] and "25" in r.answer


def test_registration_by_entry_point(ex, monkeypatch):
    import importlib.metadata as md
    registry.unregister_provider("acme")
    ep = md.EntryPoint(name="acme", value=ACME_CLASS, group=registry.ENTRY_POINT_GROUP)
    monkeypatch.setattr(md, "entry_points", lambda group=None: [ep] if group == registry.ENTRY_POINT_GROUP else [])
    assert registry.load_entry_points() == ["acme"]
    assert registry.provider_class("acme") is ex.acme.AcmeProvider


def test_registration_by_class_path_is_validated():
    assert registry.load_class(ACME_CLASS).name == "acme"
    with pytest.raises(ConfigurationError):
        registry.load_class("sajha.examples.intelligence.acme_provider:AcmeConfig")


def test_fake_server_over_real_http(ex):
    from sajha.examples.intelligence.acme_fake_server import serve
    try:
        srv = serve(port=0)
    except OSError as e:                                   # pragma: no cover - no loopback sockets
        pytest.skip(f"cannot bind a local port: {e}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p = ex.acme.AcmeProvider.from_settings("acme", {"enabled": True, "api_key": "k",
                                                    "base_url": f"http://127.0.0.1:{srv.server_address[1]}"},
                                           environ={})
    try:
        assert p.health().status == "ok"
        assert p.chat_model().generate(ChatRequest([Message.user("hi")])).text == "Hello there"
        events = list(p.chat_model().stream(ChatRequest([Message.user(QUESTION)], tools=[contract.SPEC])))
        assert events[-1].response.tool_calls[0].arguments == {"old_value": 80, "new_value": 100}
    finally:
        p.close()
        srv.shutdown()
        srv.server_close()


# ── the recipe planner ──────────────────────────────────────────────────────

RECIPES = [{"name": "pct", "tool": "calc_percentage_change",
            "match": r"percentage change from (?P<old_value>[\d.,]+) to (?P<new_value>[\d.,]+)",
            "answer": "From {old_value} to {new_value} is a change of {percentage_change}%."}]


def recipe_gateway():
    return make_gateway({"providers": [{"name": "recipes", "class": RECIPES_CLASS,
                                        "config": {"enabled": True, "recipes": RECIPES}}],
                         "aliases": {"default": ["recipes", "mock/mock-planner"]}})


def test_recipe_plans_a_known_question():
    r = ask_service(recipe_gateway()).ask(QUESTION, RequestContext(user_id="u"))
    assert r.models == ["recipes/recipe-planner"] and r.stopped_by == "answer"
    assert r.steps[0].name == "calc_percentage_change" and r.steps[0].arguments == {"old_value": 80.0, "new_value": 100.0}
    assert r.answer == "From 80.0 to 100.0 is a change of 25.0%." and r.citations == [r.steps[0].id]


def test_recipe_defers_other_questions_to_the_next_model():
    r = ask_service(recipe_gateway()).ask("Compound interest on a principal of 1000 at rate 5 for 10 years",
                                          RequestContext(user_id="u"))
    assert r.models == ["mock/mock-planner"] and r.steps[0].name == "calc_compound_interest"


def test_recipe_respects_rbac():
    ctx = RequestContext(user_id="u", can_use_tool=lambda n: n != "calc_percentage_change")
    r = ask_service(recipe_gateway()).ask(QUESTION, ctx)
    assert "recipes/recipe-planner" not in r.models
    assert all(s.name != "calc_percentage_change" for s in r.steps)


def test_recipe_bad_pattern_fails_at_startup(ex):
    with pytest.raises(ConfigurationError):
        ex.recipes.RecipeProvider.from_settings("recipes", {"recipes": [{"name": "x", "match": "(", "tool": "t"}]},
                                                environ={})


# ── the guide's code blocks are excerpts of these files ────────────────────

_BLOCK = re.compile(r"```python\n# (sajha/examples/intelligence/\w+\.py)\n(.*?)```", re.S)


def test_guide_code_blocks_are_excerpts_of_the_examples():
    with open(GUIDE, encoding="utf-8") as fh:
        blocks = _BLOCK.findall(fh.read())
    assert len(blocks) >= 6, "the guide should quote the examples"
    for path, body in blocks:
        with open(os.path.join(REPO, path), encoding="utf-8") as fh:
            source = fh.read()
        pos = 0
        for chunk in re.split(r"^\s*# \.\.\.\n", body, flags=re.M):       # "# ..." elides lines
            chunk = chunk.strip("\n")
            if not chunk.strip():
                continue
            at = source.find(chunk, pos)
            assert at >= 0, f"guide block from {path} is not in the file (or out of order):\n{chunk[:400]}"
            pos = at + len(chunk)


# ── the Planner example (section 4.5) ──────────────────────────────────────

DOCS_FIRST = "sajha.examples.intelligence.docs_first_planner:DocsFirstPlanner"


def _docs_toolbox(tmp_path, monkeypatch):
    from sajha.ai.llm.settings import RagSettings
    from sajha.ai.rag.index import DocIndex, set_doc_index
    from sajha.ai.rag.tool import SajhaSearchDocsTool
    from sajha.core.storage import LocalStorageBackend
    st = LocalStorageBackend(str(tmp_path))
    st.write_text("kb/guide.md", "# Guide\n\n## Retention\n\nConversations are kept for thirty days by default.")
    monkeypatch.setattr("sajha.ai.rag.index._storage", lambda: st)
    set_doc_index(DocIndex(RagSettings(index_sajha_docs=False, persist=False, store="memory",
                                       sources=[{"name": "kb", "path": "kb"}]), make_gateway()))
    tb = ToolBox()
    tb.add(SajhaSearchDocsTool(json.load(open(os.path.join(REPO, "config/tools/sajha_search_docs.json")))))
    return tb


def test_docs_first_planner_searches_then_hands_over(tmp_path, monkeypatch):
    from sajha.ai.rag.index import set_doc_index
    tb = _docs_toolbox(tmp_path, monkeypatch)
    try:
        svc = IntelligenceService(make_gateway(), tb, settings=AskSettings(planner=DOCS_FIRST, audit=False))
        events = list(svc.stream_ask("How do I configure how long conversations are kept? Search the docs.",
                                     RequestContext(user_id="u")))
        types = [e["type"] for e in events]
        r = events[-1]["result"]
        assert r["planner"] == "docs_first>react" and r["steps"][0]["name"] == "sajha_search_docs"
        assert types.index("plan") < types.index("tool_call") and "thirty days" in r["answer"]
        r = svc.ask(QUESTION, RequestContext(user_id="u"))                  # not a how-to question
        assert r.planner == "docs_first>react" and r.steps[0].name == "calc_percentage_change"
        r = svc.ask("How do I configure retention? Search the docs.",
                    RequestContext(user_id="u", can_use_tool=lambda n: n != "sajha_search_docs"))
        assert all(s.name != "sajha_search_docs" for s in r.steps)       # RBAC: never offered, never run
    finally:
        set_doc_index(None)
