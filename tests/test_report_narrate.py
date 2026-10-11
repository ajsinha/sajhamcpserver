"""
report_narrate and its numbers check (docs/architecture/Reports.md §5; sajha/reports/narrate.py):
the commentary is checked against the run's data and its computed comparisons, with the mock
provider standing in for the model.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import copy
import json
from pathlib import Path

import pytest

from sajha.observability.caller import Caller
from sajha.reports import narrate as N
from tests.ai.conftest import make_gateway

ROOT = Path(__file__).resolve().parents[1]

RUN = {
    "run_id": "daily_risk-20261009T073000-abc123", "report": "daily_risk", "title": "Daily risk report",
    "parameters": {"as_of": "2026-10-09", "book": "TRADING"}, "started_at": "2026-10-09T07:30:00Z",
    "runner": {"user_id": "alice"}, "status": "succeeded",
    "sections": [
        {"id": "headline", "kind": "kpis", "title": "Headline",
         "values": [{"label": "VaR 99% 1d", "value": 1234567.89, "format": "currency"},
                    {"label": "ES 97.5%", "value": 2345678.0, "format": "currency"}]},
        {"id": "stress", "kind": "table", "title": "Stress",
         "rows": [{"scenario": "Rates up", "pnl": -450000.0, "pnl_pct": -1.25},
                  {"scenario": "Equity crash", "pnl": -1200000.0, "pnl_pct": -3.4}]},
        {"id": "limits", "kind": "table", "title": "Limits",
         "rows": [{"limit": "VaR", "utilisation_pct": 92.5, "used": 185.0},
                  {"limit": "Stress", "utilisation_pct": 40.0, "used": 15.0}]},
    ],
}
PREVIOUS = {
    "run_id": "daily_risk-20261008T073000-def456", "report": "daily_risk",
    "parameters": {"as_of": "2026-10-08", "book": "TRADING"},
    "sections": [{"id": "headline", "kind": "kpis",
                  "values": [{"label": "VaR 99% 1d", "value": 1100000.0}, {"label": "ES 97.5%", "value": 2345678.0}]}],
}


class Source(N.RunSource):
    def __init__(self, run=RUN, previous=PREVIOUS, owner="alice"):
        self.run, self.prev, self.owner = copy.deepcopy(run), previous, owner
        self.warnings = []

    def load(self, run_id, caller):
        if run_id != self.run["run_id"]:
            raise KeyError(run_id)
        if caller.user_id != self.owner and not caller.is_admin:
            raise PermissionError("not yours")
        return self.run

    def previous(self, run, caller):
        return self.prev

    def warn(self, run, message):
        self.warnings.append(message)


ALICE = Caller("alice", roles=("user",))


@pytest.fixture
def ctx():
    return N.build_context(RUN, None, PREVIOUS)


def bad(text, ctx):
    return [(f["kind"], f["raw"]) for f in N.check_commentary(text, ctx)]


# ── what is rejected (Reports §12.3) ─────────────────────────────

def test_an_invented_number_is_rejected(ctx):
    assert bad("VaR stood at 1,500,000 against a limit of 2,000,000.", ctx) == [
        ("number", "1,500,000"), ("number", "2,000,000")]


def test_a_rounded_number_is_rejected(ctx):
    # 1,234,567.89 written to whole units is 1,234,568; 1,230,000 claims a precision it does not have
    assert bad("VaR was 1,230,000.", ctx) == [("number", "1,230,000")]
    assert bad("VaR was 1,234,600.", ctx) == [("number", "1,234,600")]
    assert bad("Equity crash loses 3.5% of the book.", ctx) == [("number", "3.5%")]


def test_a_percent_of_a_value_not_in_the_data_is_rejected(ctx):
    # the report computed VaR's change since the previous run (12.23%), not ES's share of anything
    assert bad("ES is 15.2% above VaR's level.", ctx) == [("number", "15.2%")]
    assert bad("Stress used 8.1% of the total limit.", ctx) == [("number", "8.1%")]


def test_a_date_not_in_the_run_is_rejected(ctx):
    assert bad("On 8 October 2026 VaR was 1,234,567.89.", ctx) == [("date", "8 October 2026")]
    assert bad("VaR is the highest since 2025-12-31.", ctx) == [("date", "2025-12-31")]
    assert bad("VaR is the highest since 2019.", ctx) == [("date", "2019")]
    assert bad("As of Sep 30, 2026 ES was unchanged.", ctx) == [("date", "Sep 30, 2026")]


# ── what passes ──────────────────────────────────────────────────

def test_figures_in_the_data_pass_at_the_precision_written(ctx):
    for text in ("VaR was 1,234,567.89 and ES 2,345,678.",
                 "VaR was 1,234,568, about 1.23 million (1.2mn).",
                 "Equity crash would lose 1,200,000, or 3.4% of the book; rates up 1.25%.",   # sign in the words
                 "VaR limit utilisation reached 92.5%, stress 40%."):
        assert bad(text, ctx) == [], text


def test_the_runs_computed_comparisons_pass_as_quantities(ctx):
    # VaR rose 134,567.89 (12.23%) since the previous run; the VaR limit is 92.5% of the used total
    assert bad("VaR rose 134,567.89, or 12.2%, since the previous run; it was 1,100,000 then.", ctx) == []
    assert bad("The VaR limit holds 92.5% of usage and stress the other 7.5%.", ctx) == []
    names = N.build_context(RUN, None, PREVIOUS).comparisons.labels.values()
    assert any("percent change since the previous run" in n for n in names)
    assert not any("share of value total" in n for n in names)          # KPIs are not parts of a total


def test_without_a_previous_run_a_change_is_rejected():
    ctx = N.build_context(RUN, None, None)
    assert bad("VaR rose 12.2% since the previous run.", ctx) == [("number", "12.2%")]


def test_stored_comparisons_are_used_when_the_engine_stored_them():
    run = dict(RUN, comparisons=[{"label": "VaR change", "value": 4.75, "unit": "percent", "section": "headline"}])
    assert bad("VaR rose 4.75%.", N.build_context(run)) == []
    assert bad("VaR rose 4.75 bp.", N.build_context(run)) == [("number", "4.75 bp")]


def test_dates_of_the_run_section_refs_and_ordinals_pass(ctx):
    assert bad("As of 9 October 2026 (2026-10-09; October 2026), see section 3 and the 21st row.", ctx) == []
    assert bad("On Oct 9, 2026, in 2026, VaR was 1,234,567.89.", ctx) == []


def test_unknown_sections_are_refused():
    with pytest.raises(ValueError, match="no section nope"):
        N.build_context(RUN, ["nope"])


# ── the flow: one revision, then removal with a caveat ───────────

def scripted(*texts):
    gw = make_gateway({"aliases": {"default": ["mock/mock-scripted"]}, "cache": {"enabled": False}})
    gw.providers["mock"].set_script([{"text": t} for t in texts], mode="ordered")
    return gw


def test_a_clean_draft_is_returned_as_is():
    src = Source()
    out = N.narrate(RUN["run_id"], caller=ALICE, source=src, gateway=scripted("VaR rose 12.2% to 1,234,567.89."))
    assert out["commentary"] == "VaR rose 12.2% to 1,234,567.89."
    assert out["revised"] is False and out["rejected"] == [] and out["removed"] == [] and out["caveats"] == []
    assert out["label"] == N.LABEL and out["sections"] == ["headline", "stress", "limits"]
    assert src.warnings == []


def test_a_rejected_draft_gets_one_revision():
    src = Source()
    gw = scripted("VaR rose 17% to 1,234,567.89.", "VaR rose 12.2% to 1,234,567.89.")
    out = N.narrate(RUN["run_id"], caller=ALICE, source=src, gateway=gw)
    assert out["revised"] is True and out["rejected"] == [{"kind": "number", "raw": "17%"}]
    assert out["commentary"] == "VaR rose 12.2% to 1,234,567.89." and out["removed"] == []
    assert gw.providers["mock"].calls == 2 and src.warnings == []


def test_figures_still_unmatched_after_the_revision_are_removed_with_a_caveat():
    src = Source()
    gw = scripted("VaR was 1,500,000 on 8 October 2026.", "VaR was 1,500,000 on 8 October 2026, up 12.2%.")
    out = N.narrate(RUN["run_id"], caller=ALICE, source=src, gateway=gw, length="medium", audience="risk committee")
    assert out["commentary"] == f"VaR was {N.REMOVED} on {N.REMOVED}, up 12.2%."
    assert {f["raw"] for f in out["removed"]} == {"1,500,000", "8 October 2026"}
    assert "2 figures could not be traced" in out["caveats"][0] and "1,500,000" in out["caveats"][0]
    assert len(src.warnings) == 1 and "1,500,000" in src.warnings[0]
    assert "1,500,000" not in out["commentary"]                         # an invented figure is never returned


def test_the_narrator_sees_the_data_and_the_comparisons_and_no_tools(monkeypatch):
    seen = {}
    gw = scripted("Nothing to add.")
    real = gw.model

    def model(alias, context=None):
        seen["alias"], seen["ctx"] = alias, context
        m = real(alias, context=context)
        orig = m.chat_completions_create

        def create(**kw):
            seen.update(kw)
            return orig(**kw)
        m.chat_completions_create = create
        return m
    monkeypatch.setattr(gw, "model", model)
    N.narrate(RUN["run_id"], sections=["headline"], caller=ALICE, source=Source(), gateway=gw, alias="default")
    user = seen["messages"][-1].text
    assert "1234567.89" in user and "percent change since the previous run" in user and "Rates up" not in user
    assert "tools" not in seen and seen["ctx"].user_id == "alice" and seen["ctx"].can_use_tool("anything") is False


def test_access_and_unknown_runs():
    with pytest.raises(PermissionError):
        N.narrate(RUN["run_id"], caller=Caller("bob"), source=Source(), gateway=scripted("x"))
    with pytest.raises(ValueError, match="no report run"):
        N.narrate("daily_risk-20000101T000000-000000", caller=ALICE, source=Source(), gateway=scripted("x"))
    with pytest.raises(ValueError, match="length"):
        N.narrate(RUN["run_id"], length="epic", caller=ALICE, source=Source(), gateway=scripted("x"))


def test_the_engine_source_reads_the_run_store(monkeypatch):
    from sajha.reports import history
    runs = {RUN["run_id"]: copy.deepcopy(RUN)}
    monkeypatch.setattr(history, "load", lambda rid: copy.deepcopy(runs.get(rid)))
    monkeypatch.setattr(history, "save", lambda data: runs.__setitem__(data["run_id"], data))
    monkeypatch.setattr(history, "previous", lambda report, params, caller, before: None)
    src = N.default_source()
    assert src.load(RUN["run_id"], ALICE)["report"] == "daily_risk"
    assert src.load(RUN["run_id"], Caller("root", is_admin=True))
    with pytest.raises(PermissionError):
        src.load(RUN["run_id"], Caller("bob"))
    with pytest.raises(KeyError):
        src.load("nope", ALICE)
    src.warn(RUN, "a warning")
    assert runs[RUN["run_id"]]["warnings"] == ["a warning"]


# ── the tool ─────────────────────────────────────────────────────

def test_the_tool_config_and_class(monkeypatch):
    cfg = json.loads((ROOT / "config/tools/reports/report_narrate.json").read_text())
    from sajha.tools.impl.report_narrate_tool import ReportNarrateTool
    tool = ReportNarrateTool(cfg)
    assert tool.name == "report_narrate" and cfg["annotations"]["destructiveHint"] is False
    assert "default" not in cfg["inputSchema"]["properties"]["length"]     # the definition's length applies
    assert set(tool.get_input_schema()["properties"]) == {"run_id", "sections", "length", "audience"}
    monkeypatch.setattr(N, "default_source", lambda: Source())
    monkeypatch.setattr(N, "_gateway", lambda: scripted("VaR was 1,234,567.89."))
    from sajha.observability import caller as C
    token = C._current.set(ALICE)
    try:
        out = tool.execute({"run_id": RUN["run_id"], "sections": ["headline"]})
    finally:
        C._current.reset(token)
    assert out["commentary"] == "VaR was 1,234,567.89." and out["sections"] == ["headline"]


# ── with the engine's run data (sajha/reports/__init__.py: run.json) ──

def engine_run():
    from sajha.reports import engine
    sections = [
        {"id": "headline", "kind": "kpis", "title": "Headline", "status": "ok",
         "source": {"tool": "qlrisk_value_at_risk", "as_of": "2026-10-08", "called_at": "2026-10-09T07:30:01Z"},
         "kpis": [{"label": "VaR 99% 1d", "key": "var", "format": "currency", "value": 1234567.89},
                  {"label": "Hit rate", "key": "hit", "format": "percent", "value": 4.5}]},
        {"id": "desks", "kind": "table", "title": "Desks", "status": "ok",
         "table": {"columns": [{"key": "desk", "label": "Desk", "format": "text"},
                               {"key": "pnl", "label": "P&L", "format": "number"}],
                   "rows": [{"desk": "Rates", "pnl": 300.0}, {"desk": "FX", "pnl": 100.0}], "row_count": 2}},
        {"id": "commentary", "kind": "text", "title": "Commentary", "status": "pending_narration", "text": "",
         "narrate": {"sections": ["headline", "desks"], "length": "medium"}},
    ]
    previous = {"run_id": "daily_risk-20261008T073000-def456", "sections": [
        {"id": "headline", "kpis": [{"label": "VaR 99% 1d", "key": "var", "value": 1100000.0},
                                    {"label": "Hit rate", "key": "hit", "value": 4.0}]}]}
    return dict(copy.deepcopy(RUN), sections=sections, quantities=engine.quantities(sections, previous),
                previous_run_id=previous["run_id"], narration=None, files={"markdown": "x"}, warnings=[])


def test_the_engines_quantities_are_the_comparisons():
    run = engine_run()
    ctx = N.build_context(run)
    assert [s["id"] for s in ctx.sections] == ["headline", "desks"]          # not the section waiting for it
    ok = ("VaR rose 12.2% (134,567.89) from 1,100,000; the hit rate rose 0.5 pp to 4.5%. "
          "Rates made 75% of P&L, 300 of 500.")
    assert bad(ok, ctx) == [("number", "500")]                               # a total the report did not compute
    assert bad("The hit rate rose 0.5 bp.", ctx) == [("number", "0.5 bp")]
    assert bad("Data as of 8 October 2026.", ctx) == []                       # the source's as-of date


def test_commentary_is_stored_in_the_waiting_section_and_the_files_rendered_again(monkeypatch):
    from sajha.reports import engine, history
    run = engine_run()
    runs = {run["run_id"]: copy.deepcopy(run)}
    rendered = []
    monkeypatch.setattr(history, "load", lambda rid: copy.deepcopy(runs.get(rid)))
    monkeypatch.setattr(history, "save", lambda data: runs.__setitem__(data["run_id"], copy.deepcopy(data)))
    monkeypatch.setattr(engine, "render_and_store", lambda data, fmts: rendered.append(list(fmts)))
    gw = scripted("VaR was 1,234,567.89 and 9,999 trades.", "VaR was 1,234,567.89 and 9,999 trades.")
    out = N.narrate(run["run_id"], caller=ALICE, gateway=gw)
    assert out["sections"] == ["headline", "desks"] and out["length"] == "medium"   # from the definition
    assert out["stored_in"] == "commentary" and rendered == [["markdown"]]
    stored = runs[run["run_id"]]
    sec = next(s for s in stored["sections"] if s["id"] == "commentary")
    assert sec["status"] == "text" and sec["text"].startswith(f"VaR was 1,234,567.89 and {N.REMOVED} trades.")
    assert "could not be traced" in sec["text"]
    assert stored["narration"]["model"] and stored["narration"]["removed"] == ["9,999"]
    assert stored["warnings"] and "9,999" in stored["warnings"][0]
