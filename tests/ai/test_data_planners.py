# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The data_analyst and research_writer planners (docs/architecture/Quantitative Planners.md §3.4,
§3.7) and the load_results and sql stage types (sajha/ai/planners_engine/data_stages.py), on the
mock models: tool results loaded uncapped into the caller's scratch database, the model's SELECT
run read-only, DuckDB's error sent back at most max_queries times, query results matched by the
numbers check, the query and its source calls in the run record and audit, and the cited write-up
from the existing stage library."""

import os

import pytest

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm.settings import AskSettings
from sajha.ai.planners_engine import PlannerRegistry, set_registry
from tests.ai.conftest import FakeTool, ToolBox, make_gateway
from tests.ai.test_planner_engine import PCT, ctx, path, scripted, service

REGIONS = ["east", "west", "north", "south"]
QUESTION = "Fetch the sales rows by region and give the total sales"


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("SAJHA_BI_SCRATCH_DIR", str(tmp_path / "scratch"))
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)


def sales_box(n_months=9):
    box = ToolBox(with_calc=False)
    rows = [{"region": r, "month": f"2024-{m:02d}-01", "sales": 100 * m + i}
            for i, r in enumerate(REGIONS) for m in range(1, n_months + 1)]
    tool = box.add(FakeTool("sales_rows_fetch", "Fetch the sales rows by region",
                            {"type": "object", "properties": {"region": {"type": "string"}}},
                            output={"source": "test", "rows": rows}))
    return box, tool, rows


def gather_then(*steps):
    """A gateway playing an ordered script: one tool call, then 'done', then ``steps`` (sql, draft, ...)."""
    return scripted([{"tool_calls": [{"id": "c1", "name": "sales_rows_fetch", "arguments": {}}]}, {"text": "done"},
                     *steps], mode="ordered")


def sql(text):
    return {"json": {"sql": text, "why": "test"}}


def draft(answer, cites=("query_1",)):
    return {"json": {"answer": answer, "citations": list(cites), "caveats": []}}


# ── the shipped files ────────────────────────────────────────────

@pytest.mark.parametrize("name", ["data_analyst", "research_writer"])
def test_the_new_planner_files_load(registry, name):
    e = registry.entry(name)
    assert e.pdef is not None and e.version == "1.0.0" and not registry.errors and not e.warnings


def test_research_writer_uses_only_the_existing_stage_library(registry):
    from sajha.ai.planners_engine.model import BUILTIN_DEF
    pdef = registry.entry("research_writer").pdef
    assert {st.type for st in pdef.stages.values()} <= set(BUILTIN_DEF)
    verify = pdef.stages["verify"].cfg["checks"]
    assert {"check": "citations_present", "per": "paragraph"} in verify


# ── data_analyst ─────────────────────────────────────────────────

def test_data_analyst_path_on_the_mock_planner():
    box, tool, rows = sales_box()
    r = service(box, planner="data_analyst").ask(QUESTION, ctx())
    assert path(r) == ["gather", "gather", "load", "query", "draft", "verify", "answer"]
    assert r.stopped_by == "answer" and r.planner == "data_analyst" and tool.calls
    q = r.queries[0]
    assert q["ok"] and q["id"] == "query_1" and q["tables"] == ["sales_rows_fetch"] and q["sources"] == [r.steps[0].id]
    assert "query_1" not in r.citations and r.citations == [r.steps[0].id]    # cited through its source call
    assert not any("does not appear" in c for c in r.caveats)
    assert r.to_dict()["queries"] == r.queries


def test_a_large_result_is_loaded_whole_and_the_query_figures_pass_the_numbers_check():
    box, _tool, rows = sales_box(n_months=120)                     # far beyond max_result_chars
    total = sum(x["sales"] for x in rows)
    gw = gather_then(sql("SELECT count(*) AS n, sum(sales) AS total FROM sales_rows_fetch"),
                     draft(f"Total sales were {total:,} across {len(rows)} rows [query_1]."))
    r = service(box, gw=gw, planner="data_analyst").ask(QUESTION, ctx())
    assert path(r) == ["gather", "gather", "load", "query", "draft", "verify", "answer"]
    assert r.queries[0]["ok"] and r.queries[0]["row_count"] == 1
    assert f"{total:,}" in r.answer and not any("does not appear" in c for c in r.caveats)


def test_a_figure_from_nowhere_is_still_caught():
    box, _tool, _rows = sales_box()
    gw = gather_then(sql("SELECT sum(sales) AS total FROM sales_rows_fetch"),
                     draft("Total sales were 987,654 [query_1]."), draft("Total sales were 987,654."))
    r = service(box, gw=gw, planner="data_analyst").ask(QUESTION, ctx())
    assert path(r)[-4:] == ["verify", "revise", "verify", "answer"]
    assert any("987,654 does not appear" in c for c in r.caveats)


def test_a_failed_query_goes_back_with_duckdbs_error():
    box, _tool, _rows = sales_box()
    gw = gather_then(sql("SELECT sum(revenue) FROM sales_rows_fetch"),
                     sql("SELECT sum(sales) AS total FROM sales_rows_fetch"),
                     draft("Total sales were 18,054 [query_2]."))
    r = service(box, gw=gw, planner="data_analyst").ask(QUESTION, ctx())
    first, second = r.queries
    assert not first["ok"] and "revenue" in first["error"] and first["attempt"] == 1
    assert second["ok"] and second["attempt"] == 2 and second["sources"] == [r.steps[0].id]
    assert path(r)[-4:] == ["query", "draft", "verify", "answer"]


def test_the_retry_request_carries_duckdbs_error():
    box, _tool, _rows = sales_box()
    gw = scripted([{"stage": "act", "tool_calls": [{"id": "c1", "name": "sales_rows_fetch", "arguments": {}}]},
                   {"stage": "sql", "match": "DuckDB said: .*revenue",
                    "json": {"sql": "SELECT sum(sales) AS total FROM sales_rows_fetch", "why": "fixed"}},
                   {"stage": "sql", "json": {"sql": "SELECT sum(revenue) FROM sales_rows_fetch", "why": "first"}},
                   {"stage": "draft", "json": {"answer": "Done [query_2].", "citations": ["query_2"], "caveats": []}}],
                  mode="rules")
    r = service(box, gw=gw, planner="data_analyst").ask(QUESTION, ctx())
    assert [q["ok"] for q in r.queries] == [False, True] and r.queries[1]["why"] == "fixed"


def test_at_most_max_queries_then_the_draft_uses_the_results():
    box, _tool, _rows = sales_box()
    bad = [sql("DROP TABLE sales_rows_fetch"), sql("SELECT * FROM read_csv('/etc/passwd')"), sql("SELECT nope FROM x")]
    gw = gather_then(*bad, draft("I could not compute the total.", cites=()))
    r = service(box, gw=gw, planner="data_analyst").ask(QUESTION, ctx())
    assert [q["ok"] for q in r.queries] == [False, False, False]
    assert "SELECT" in r.queries[0]["error"] and "read_csv" in r.queries[1]["error"]
    assert any("failed after 3 attempt" in c for c in r.caveats)
    assert path(r)[-4:] == ["query", "draft", "verify", "answer"]


def test_without_rows_the_answer_comes_from_the_results():
    r = service(planner="data_analyst").ask(PCT, ctx())               # calc tools: one flat object, one row
    assert r.stopped_by == "answer" and "load" in path(r)
    box = ToolBox(with_calc=False)
    box.add(FakeTool("echo_text_fetch", "Fetch the echo text", output="just words"))
    r = service(box, planner="data_analyst").ask("Fetch the echo text", ctx())
    assert path(r) == ["gather", "gather", "load", "draft", "verify", "answer"] and not r.queries


def test_each_user_has_their_own_scratch_database(tmp_path):
    from sajha.analytics.scratch import ScratchDB, settings
    box, _tool, _rows = sales_box()
    service(box, planner="data_analyst").ask(QUESTION, ctx())
    alice = ScratchDB("u", settings())
    assert [t["table"] for t in alice.tables()] == ["sales_rows_fetch"]
    assert ScratchDB("someone-else", settings()).tables() == []
    assert os.path.dirname(alice.path) == str(tmp_path / "scratch")


def test_queries_are_in_the_audit_record():
    seen = []
    box, _tool, _rows = sales_box()
    svc = IntelligenceService(make_gateway(), box, settings=AskSettings(planner="data_analyst"), audit=seen.append)
    svc.ask(QUESTION, ctx())
    q = seen[0]["queries"][0]
    assert q["id"] == "query_1" and q["ok"] and q["sql"].startswith("SELECT") and q["sources"]


def test_query_and_table_events_are_on_the_stream():
    box, _tool, _rows = sales_box()
    events = list(service(box, planner="data_analyst").stream_ask(QUESTION, ctx()))
    kinds = [e["type"] for e in events]
    assert "table_loaded" in kinds and "query" in kinds


# ── research_writer ──────────────────────────────────────────────

def test_research_writer_mock_run_passes_through():
    r = service(planner="research_writer").ask(PCT, ctx())
    # mock-planner's draft cites the call ids in square brackets, as the draft prompt asks, so it passes first time
    assert path(r) == ["outline", "sections", "draft", "verify", "answer"]
    assert r.stopped_by == "answer" and r.steps and r.steps[0].ok and r.answer
    assert f"[{r.citations[0]}]" in r.answer
    assert any("react" in p for p in r.planner_path if "/" in p)


def test_research_writer_passes_when_every_paragraph_cites():
    box = ToolBox()
    gw = scripted([{"json": {"steps": [{"id": "s1", "tool": "calc_percentage_change",
                                        "arguments": '{"old_value": 80, "new_value": 100}',
                                        "depends_on": [], "why": "The change"}]}},
                   {"tool_calls": [{"id": "c1", "name": "calc_percentage_change",
                                    "arguments": {"old_value": 80, "new_value": 100}}]},
                   {"text": "done"},
                   {"json": {"answer": "From 80 to 100 is a 25% change [c1].\n\nThat is all.", "citations": ["c1"],
                             "caveats": []}}], mode="ordered")
    r = service(box, gw=gw, planner="research_writer").ask(PCT, ctx())
    assert path(r) == ["outline", "sections", "draft", "verify", "answer"], r.caveats
