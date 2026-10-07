"""LLM tools (sajha/ai/llm_tools; docs/architecture/LLM Tools.md): load-time validation, every mode on
the mock (answer, complete, extract with its one retry, classify, judge, grounded, narrate), caching,
identity (inner calls run as the caller, never with more access), derived annotations, recursion and
depth, conversation memory, isError results, lint rules, the sajha_ask shim and LLM-tool eval sets."""

import json

import pytest
from sqlalchemy import create_engine

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings, MemorySettings
from sajha.ai.llm_tools import LLMConfigError, LLMTool, LLMToolSettings, set_settings
from sajha.ai.llm_tools.runtime import Runtime, set_runtime
from tests.ai.conftest import FakeTool, ToolBox, make_gateway

ADMIN = RequestContext(user_id="", roles=["admin"], is_admin=True)


@pytest.fixture(autouse=True)
def fresh_runtime(tmp_path):
    from sajha import notices as N
    from sajha.ai.llm_tools.config import SpoolSettings
    from sajha.core.state.memory import MemoryStateStore
    N.set_service(N.NoticeService(MemoryStateStore("llmt:"), forward=[]))     # notices stay in this test
    s = LLMToolSettings(spool=SpoolSettings(dir=str(tmp_path / "spool")))
    set_settings(s)
    set_runtime(Runtime(s))
    yield
    set_runtime(None)
    set_settings(None)
    N.set_service(None)


def shipped(name):
    with open(f"config/tools/{name}.json") as f:
        return json.load(f)


def wire(tool, toolbox=None, gw=None, svc=None):
    toolbox = toolbox or ToolBox()
    gw = gw or make_gateway()
    tool.registry, tool.gateway = toolbox, gw
    tool.service = svc or IntelligenceService(gw, toolbox, settings=AskSettings(), audit=lambda e: None)
    return tool


def cfg(mode, llm=None, inputs=None, outputs=None, name="t_llm"):
    base = {"name": name, "implementation": "sajha.ai.llm_tools.LLMTool", "description": "A test LLM tool.",
            "inputSchema": {"type": "object", "properties": inputs or {"question": {"type": "string"}},
                            "required": list((inputs or {"question": 1}).keys())[:1]},
            "outputSchema": {"type": "object", "properties": outputs or {"answer": {"type": "string"},
                                                                          "stopped_by": {"type": "string"}}},
            "llm": {"mode": mode, **(llm or {})}}
    return base


def scripted(steps, mode="ordered"):
    gw = make_gateway({"aliases": {a: ["mock/mock-scripted"] for a in ("default", "fast", "reasoning")},
                       "cache": {"enabled": False}})
    gw.providers["mock"].set_script(steps, mode=mode)
    return gw


# ── load-time validation (§5.2) ─────────────────────────────────────────

@pytest.mark.parametrize("config,expected", [
    (cfg("chat"), "llm.mode must be one of"),
    (cfg("classify", {"template": "{{input.question}}", "planner": "react"}), "llm.planner does not apply"),
    (cfg("answer", inputs={"q": {"type": "string"}}), "needs a question property"),
    (cfg("classify", {"template": "{{input.question}}"}, outputs={"label": {"type": "string"}}),
     "label property with an enum"),
    (cfg("complete", {"template": "{{input.missing}}"}, outputs={"text": {"type": "string"}}),
     "not an inputSchema property"),
    (cfg("answer", {"limits": {"max_steps": 0}}), "must be a positive number"),
    (cfg("answer", {"sampling": "prefer"}), "build step 11"),
    (cfg("answer", {"planner_choices": ["react"]}), "wave 3"),
    (cfg("answer", {"planner": "no_such_planner"}), "llm.planner"),
    (cfg("narrate", {"template": "x"}, outputs={"text": {"type": "string"}, "data": {}}), "needs llm.source"),
    (cfg("judge", {"template": "{{input.question}}"}, outputs={"scores": {}, "verdict": {}}), "llm.rubric"),
    (cfg("answer", {"memory": {"mode": "conversation"}}), "conversation_id property"),
    (cfg("complete", {"template": "{{input.question}}", "tools": {"allow": ["calc_*"]}},
         outputs={"text": {"type": "string"}}), "does not apply to mode complete"),
    (cfg("answer", {"system_prompt": "a", "prompt": {"name": "p"}}), "mutually exclusive"),
])
def test_the_loader_refuses_a_bad_llm_block(config, expected):
    with pytest.raises(LLMConfigError) as e:
        LLMTool(config)
    assert expected in str(e.value)


def test_every_shipped_llm_tool_loads_and_is_off_by_default():
    for name in ("llm_markets_assistant", "llm_summarise", "llm_triage_ticket", "llm_docs_qa"):
        c = shipped(name)
        assert c["enabled"] is False and c["implementation"] == "sajha.ai.llm_tools.LLMTool"
        LLMTool(c)
    assert shipped("sajha_ask")["enabled"] is False


def test_limits_are_clamped_to_the_server_ceilings():
    t = LLMTool(cfg("answer", {"limits": {"max_steps": 100, "max_cost_usd": 0.5}}))
    lim = t.spec.effective_limits(LLMToolSettings())
    assert lim.max_steps == 8 and lim.max_cost_usd == 0.5
    anon = t.spec.effective_limits(LLMToolSettings(), anonymous=True)
    assert anon.max_steps == 3 and anon.max_cost_usd == 0.02


# ── modes on the mock ─────────────────────────────────────────────────

def test_complete_and_its_cache():
    t = wire(LLMTool(shipped("llm_summarise")))
    args = {"text": "Rates rose 25 basis points. Markets fell. Bonds rallied.", "max_sentences": 1}
    one = t.run(args, ctx=ADMIN, audit=False)
    assert one.result == {"text": "Rates rose 25 basis points.", "stopped_by": "answer"} and not one.cached
    calls = t.gateway.providers["mock"].calls
    two = t.run(args, ctx=ADMIN, audit=False)
    assert two.cached and two.result == one.result and t.gateway.providers["mock"].calls == calls


def test_complete_reports_a_refusal():
    t = wire(LLMTool(cfg("complete", {"template": "{{input.question}}"}, outputs={"text": {"type": "string"},
                                                                               "stopped_by": {"type": "string"}})),
             gw=scripted([{"refusal": "I cannot help with that."}]))
    info = t.run({"question": "x"}, ctx=ADMIN, audit=False)
    assert info.stopped_by == "refused" and info.result["text"] == "I cannot help with that."
    assert not info.result.is_error


EXTRACT = cfg("extract", {"template": "Extract from: {{input.question}}"},
              outputs={"vendor": {"type": "string"}, "amount": {"type": "number"}, "stopped_by": {"type": "string"}})
EXTRACT["outputSchema"]["required"] = ["vendor", "amount"]


def test_extract_validates_and_retries_once():
    gw = scripted([{"json": {"vendor": "Acme"}}, {"json": {"vendor": "Acme", "amount": 12.5}}])
    t = wire(LLMTool(EXTRACT), gw=gw)
    info = t.run({"question": "Acme invoice 12.5"}, ctx=ADMIN, audit=False)
    assert info.result == {"vendor": "Acme", "amount": 12.5, "stopped_by": "answer"} and info.model_calls == 2


def test_extract_gives_up_after_the_retry():
    gw = scripted([{"text": "not json"}, {"json": {"vendor": 5}}])
    t = wire(LLMTool(EXTRACT), gw=gw)
    info = t.run({"question": "x"}, ctx=ADMIN, audit=False)
    assert info.stopped_by == "invalid_output" and info.result.is_error and info.model_calls == 2


def test_extract_on_the_mock_reads_fields():
    t = wire(LLMTool(EXTRACT))
    info = t.run({"question": "Vendor: Acme Corp\nAmount 99.5 due"}, ctx=ADMIN, audit=False)
    assert info.result["vendor"] == "Acme Corp" and info.result["amount"] == 99.5


def test_classify_on_the_mock_and_outside_the_enum():
    t = wire(LLMTool(shipped("llm_triage_ticket")))
    assert t.run({"message": "Please refund the double charge"}, ctx=ADMIN, audit=False).result["label"] == "billing"
    bad = wire(LLMTool(shipped("llm_triage_ticket")), gw=scripted([{"json": {"label": "spam"}}] * 2))
    bad.spec.cache = False
    info = bad.run({"message": "x"}, ctx=ADMIN, audit=False)
    assert info.stopped_by == "invalid_output" and info.result.is_error


JUDGE = cfg("judge", {"template": "Review: {{input.question}}",
                      "rubric": {"criteria": [{"name": "clarity", "min": 1, "max": 5},
                                              {"name": "accuracy", "min": 1, "max": 5, "weight": 2}],
                                 "pass_score": 4}},
            outputs={"scores": {"type": "object"}, "overall": {"type": "number"}, "verdict": {"type": "string"},
                     "stopped_by": {"type": "string"}})


def test_judge_scores_against_the_rubric():
    t = wire(LLMTool(JUDGE))
    info = t.run({"question": "The answer has clarity and accuracy."}, ctx=ADMIN, audit=False)
    assert info.result["scores"] == {"clarity": 5, "accuracy": 5} and info.result["verdict"] == "pass"
    info = t.run({"question": "Nothing relevant here."}, ctx=ADMIN, audit=False)
    assert info.result["scores"] == {"clarity": 3, "accuracy": 3} and info.result["verdict"] == "fail"
    out_of_range = wire(LLMTool(JUDGE), gw=scripted([{"json": {"scores": {"clarity": 9, "accuracy": 1}}}] * 2))
    assert out_of_range.run({"question": "x"}, ctx=ADMIN, audit=False).stopped_by == "invalid_output"


class FakeIndex:
    def __init__(self, hits):
        self.hits, self.queries = hits, []

    def search(self, query, top_k=None, sources=None):
        self.queries.append((query, top_k, sources))
        return list(self.hits)


@pytest.fixture
def doc_index(monkeypatch):
    from sajha.ai.rag import index as rag_index
    idx = FakeIndex([{"citation": 1, "document": "docs/a.md", "title": "Guide A", "section": "Setup",
                      "url": "/help/guides/A.md#setup", "text": "Set ai.memory.retention_days to keep fewer days. More."}])
    monkeypatch.setattr(rag_index, "_index", idx)
    return idx


def test_grounded_answers_from_passages_with_citations(doc_index):
    t = wire(LLMTool(shipped("llm_docs_qa")))
    info = t.run({"question": "How long is memory kept?"}, ctx=ADMIN, audit=False)
    r = info.result
    assert r["stopped_by"] == "answer" and "[1]" in r["answer"] and r["citations"] == ["[1] /help/guides/A.md#setup"]
    assert r["confidence"] == 1.0 and doc_index.queries[0][2] == ["sajha_docs"]
    doc_index.hits = []
    r = t.run({"question": "Unrelated?"}, ctx=ADMIN, audit=False).result
    assert r["stopped_by"] == "no_sources" and r["answer"] == "Not found in the sources." and not r.is_error


def test_grounded_needs_the_callers_document_search_access(doc_index):
    from sajha.core.inner_calls import InnerCallRefused
    t = wire(LLMTool(shipped("llm_docs_qa")))
    ctx = RequestContext(user_id="", can_use_tool=lambda n: False)
    with pytest.raises(InnerCallRefused):
        t.run({"question": "q"}, ctx=ctx, audit=False)


def test_narrate_runs_the_source_and_keeps_its_data():
    box = ToolBox(with_calc=False)
    src = box.add(FakeTool("cmp_quarter", "Quarter figures", output={"revenue": 120, "growth_pct": 4.5}))
    c = cfg("narrate", {"template": "Write one paragraph about the quarter for {{input.question}}.",
                        "source": {"composite": "cmp_quarter", "arguments": {"who": "{{input.question}}"}}},
            outputs={"text": {"type": "string"}, "data": {"type": "object"}, "stopped_by": {"type": "string"}})
    t = wire(LLMTool(c), toolbox=box)
    info = t.run({"question": "the board"}, ctx=ADMIN, audit=False)
    assert src.calls == [{"who": "the board"}]
    assert info.result["data"] == {"revenue": 120, "growth_pct": 4.5} and "revenue is 120" in info.result["text"]
    assert t.config["annotations"]["readOnlyHint"] is False          # the source does not say it is read-only


def test_answer_runs_as_the_caller_and_never_widens_access():
    from sajha.observability.caller import Caller, reset, set_caller
    t = wire(LLMTool(shipped("llm_markets_assistant")))
    q = {"question": "What is the percentage change from 80 to 100?"}
    token = set_caller(Caller("erin", roles=("user",), access=lambda n: n != "calc_percentage_change"))
    try:
        info = t.run(q, remember=False, audit=False)
    finally:
        reset(token)
    assert "calc_percentage_change" not in [s.name for s in info.steps]
    token = set_caller(Caller("erin", roles=("user",), access=lambda n: True))
    try:
        info = t.run(q, remember=False, audit=False)
    finally:
        reset(token)
    assert [s.name for s in info.steps] == ["calc_percentage_change"] and "25" in info.result["answer"]


def test_anonymous_callers_are_refused_by_default():
    from sajha.observability.caller import Caller, reset, set_caller
    t = wire(LLMTool(shipped("llm_summarise")))
    token = set_caller(Caller("anonymous", access=lambda n: True))
    try:
        with pytest.raises(PermissionError, match="anonymous"):
            t.run({"text": "x"})
    finally:
        reset(token)


def test_annotations_are_derived_from_the_allowed_tools():
    box = ToolBox(with_calc=False)
    box.add(FakeTool("x_delete_all", "Deletes everything", destructive=True))
    c = cfg("answer", {"tools": {"allow": ["x_*"]}})
    c["annotations"] = {"readOnlyHint": True, "destructiveHint": False, "title": "T"}
    t = wire(LLMTool(c), toolbox=box)
    ann = t.to_mcp_format()["annotations"]
    assert ann == {"title": "T", "readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}
    from sajha.quality.lint import lint_registry
    box.add(t)
    rules = {(f.rule, f.level) for f in lint_registry(box, "t_llm")}
    assert ("llm-annotations", "warning") in rules
    refuse = cfg("answer", {"tools": {"allow": ["x_*"]}, "confirm": "refuse"})
    assert wire(LLMTool(refuse), toolbox=box).allowed_tools() == []


def test_lint_reports_catalog_problems_and_refused_configs():
    from sajha.quality.lint import lint_registry
    box = ToolBox()
    t = wire(LLMTool(cfg("answer", {"tools": {"allow": ["calc_*", "nothing_*"]}})), toolbox=box)
    box.add(t)
    box.tool_configs = {"broken_llm": cfg("chat", name="broken_llm")}
    found = {(f.tool, f.rule) for f in lint_registry(box)}
    assert ("t_llm", "llm-catalog") in found and ("broken_llm", "llm-config") in found


def test_nesting_depth_and_cycles():
    from sajha.ai.llm_tools.tool import LLM_CHAIN
    from sajha.core.inner_calls import CallCycle, CallTooDeep
    t = wire(LLMTool(shipped("llm_summarise")))
    token = LLM_CHAIN.set(("a", "b"))
    try:
        with pytest.raises(CallTooDeep):
            t.run({"text": "x"}, ctx=ADMIN, audit=False)
    finally:
        LLM_CHAIN.reset(token)
    token = LLM_CHAIN.set(("llm_summarise",))
    try:
        with pytest.raises(CallCycle):
            t.run({"text": "x"}, ctx=ADMIN, audit=False)
    finally:
        LLM_CHAIN.reset(token)
    # an outer LLM tool offers other LLM tools only with nesting.allow
    box = ToolBox(with_calc=False)
    box.add(LLMTool(shipped("llm_summarise")))
    assert wire(LLMTool(cfg("answer", {"tools": {"allow": ["llm_*"]}})), toolbox=box).allowed_tools() == []
    nested = wire(LLMTool(cfg("answer", {"tools": {"allow": ["llm_*"]}, "nesting": {"allow": True}})), toolbox=box)
    assert nested.allowed_tools() == ["llm_summarise"]


def test_conversation_memory_round_trip(tmp_path):
    from sajha.ai.memory import ConversationMemory, ConversationStore
    box, gw = ToolBox(), make_gateway()
    mem = ConversationMemory(gw, MemorySettings(), ConversationStore(create_engine(f"sqlite:///{tmp_path / 'm.db'}")))
    svc = IntelligenceService(gw, box, settings=AskSettings(), audit=lambda e: None, memory=mem)
    t = wire(LLMTool(shipped("llm_markets_assistant")), toolbox=box, gw=gw, svc=svc)
    alice = RequestContext(user_id="alice", roles=["admin"])
    first = t.run({"question": "What is the percentage change from 80 to 100?"}, ctx=alice, audit=False).result
    cid = first["conversation_id"]
    second = t.run({"question": "and from 100 to 150?", "conversation_id": cid}, ctx=alice, audit=False).result
    assert second["conversation_id"] == cid and "50" in second["answer"]
    lost = t.run({"question": "q", "conversation_id": cid}, ctx=RequestContext(user_id="mallory"), audit=False).result
    assert lost.is_error and lost["error"] == "conversation not found"


def test_error_results_are_mcp_errors():
    from sajha.core.mcp_handler import MCPHandler
    from sajha.ai.llm_tools.tool import LLMToolResult
    t = LLMTool(shipped("llm_summarise"))
    res = t._error("busy", "busy: full", retry_after=7)
    assert isinstance(res, LLMToolResult) and res.is_error and res.http_status == 503 and res.retry_after == 7
    handler = MCPHandler.__new__(MCPHandler)
    handler._advertise_output_schema = lambda: True
    import logging
    handler.logger = logging.getLogger("t")
    out = handler._format_tool_result(t, res)
    assert out["isError"] is True and out["structuredContent"]["stopped_by"] == "busy"
    ok = handler._format_tool_result(t, t._fit({"text": "x", "stopped_by": "answer"}))
    assert "isError" not in ok


# ── sajha_ask on the type (§18) ───────────────────────────────────────

def test_sajha_ask_is_an_llm_tool_switched_by_the_ask_setting(monkeypatch):
    from sajha.ai import intelligence
    from sajha.ai.ask_tool import SajhaAskTool, register_if_enabled
    box = ToolBox()
    svc = IntelligenceService(make_gateway(), box, settings=AskSettings(mcp_allowed_tools=["calc_*"]),
                              audit=lambda e: None)
    monkeypatch.setattr(intelligence, "_service", svc)
    assert register_if_enabled(box, AskSettings()) is False
    assert register_if_enabled(box, AskSettings(mcp_tool_enabled=True)) is True
    tool = box.get_tool("sajha_ask")
    assert isinstance(tool, SajhaAskTool) and isinstance(tool, LLMTool) and tool.enabled
    out = tool.execute({"question": "What is the percentage change from 80 to 100?"})
    assert out["stopped_by"] == "answer" and "25" in out["answer"] and "sajha_ask" not in out["shortlist"]
    assert register_if_enabled(box, AskSettings()) is False and not tool.enabled


# ── eval sets over LLM tools ─────────────────────────────────────────

def test_llm_tool_eval_sets_pass_on_the_mock(doc_index):
    from sajha.quality import evals as E
    box = ToolBox()
    for name in ("llm_markets_assistant", "llm_summarise", "llm_triage_ticket", "llm_docs_qa"):
        box.add(LLMTool(shipped(name)))
    svc = IntelligenceService(make_gateway(), box, settings=AskSettings(), audit=lambda e: None)
    sets = E.load_sets("config/evals")
    for name in ("llm_markets_assistant", "llm_summarise", "llm_triage_ticket", "llm_docs_qa"):
        es = sets[name]
        assert es.tool == name
        run = E.run_set(svc, es, "mock/mock-planner")
        assert run["summary"]["passed"] == run["summary"]["questions"], [q["reasons"] for q in run["questions"]]
