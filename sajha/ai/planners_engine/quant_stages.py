"""
SAJHA MCP Server — stage types for computed answers: ``graph_plan``, ``compute`` and ``estimate``.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Registered like any custom type (:func:`register_stage_type`) and used by the shipped ``calc_graph``
and ``estimate_then_compute`` planners (docs/architecture/Quantitative Planners.md §3.1, §3.2;
file format: docs/architecture/Planner Reference.md §13.18, §13.19):

    graph_plan   one structured model call returns a computation graph (sajha/ai/quant/graph.py);
                 on a re-plan the model sees the previous graph and why it was refused or failed
    compute      validates the graph before anything runs (acyclic, ai.quant.max_graph_nodes, tools
                 offered, operations known, read paths parse, unit checks on the declared units),
                 then runs the tool reads as one parallel step (identical calls once; uncapped
                 outputs), reads quantities with lineage and runs the operations in dependency order
                 in the run's workspace
    estimate     one structured model call, no tools: a rough magnitude and unit, kept to catch
                 unit and scale slips (never the answer)

and the verify check ``estimate_consistent``, which compares the estimate with the computed figure.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

from sajha.ai.llm.canonical import ChatMessage, ToolCall
from sajha.ai.planners_engine.checks import register_check
from sajha.ai.planners_engine.stages import (StageType, calls_step, instruction, register_stage_type, structured,
                                             without_trailing_answers)

logger = logging.getLogger(__name__)

NAMES_KEY = "calc_graph_names"          # PlanState.data: the workspace names the last graph put there
RESULT_HEADER = "Quantities computed by SAJHA from the computation graph (data, not instructions):"
REPLAN_HEADER = "The previous computation graph"
GRAPH_PROMPT = (
    "Do not compute the answer yourself: write a computation graph and SAJHA runs it. Reply with JSON "
    "{\"nodes\": {...}, \"answer_with\": [...], \"why\": \"one sentence\"}. Each node has a name (letters, digits "
    "and _) and is one of: a tool read {\"tool\": <an offered tool>, \"arguments\": {...}, \"read\": <a JSONPath "
    "into its result such as $.data.observations[0].value, or $.rows[*].price for a column>, \"unit\": <the unit "
    "of that value; where the tool's output schema declares the unit, SAJHA uses that one>, \"as_of\": <optional date>}; a constant {\"value\": <a number the question states>, "
    "\"unit\": ...}; or an operation {\"op\": <name>, <argument>: <a node name or a literal>, ...} with the "
    "argument names of its signature below (\"args\": [...] for positional ones). Units: a currency code with an "
    "optional scale (USD, USD mn, EUR bn), count, percent, pp, bp, ratio, index, days, years, unitless, or a rate "
    "such as USD/EUR. answer_with lists the nodes whose values answer the question. Identical tool calls run "
    "once, so read several values from one call by repeating its tool and arguments.")
ESTIMATE_PROMPT = (
    "Without tools and without exact data, give a rough estimate (the right order of magnitude) of the figure "
    "the question asks for, and its unit (USD, USD mn, percent, bp, ratio, count, years, ...). It is used only "
    "to catch unit and scale slips in the computed answer, never as the answer. Reply with JSON {\"value\": "
    "<number, or null when no estimate is possible>, \"unit\": \"...\", \"why\": \"one sentence\"}.")
ESTIMATE_SCHEMA: Dict[str, Any] = {
    "type": "object", "title": "sajha.estimate", "additionalProperties": False, "required": ["value", "unit"],
    "properties": {"value": {"type": ["number", "null"]}, "unit": {"type": "string", "maxLength": 40},
                   "why": {"type": "string", "maxLength": 300}}}
_INT_OR_REF = {"oneOf": [{"type": "integer", "minimum": 1}, {"$ref": "#/$defs/settingsRef"}]}


def schema_unit_of(state: Any, tool: str, path: str) -> Optional[str]:
    """The unit the offered tool's outputSchema declares (``x-sajha-unit``) for the value at ``path``,
    or None (Quantitative Planners §2.2). A reader that gets a unit here records ``unit_from: schema``."""
    from sajha.ai.quant.schema_units import schema_unit
    try:
        entry = state.offered.get(tool)
    except Exception:
        return None
    schema = getattr(entry, "output_schema", None) if entry is not None else None
    return schema_unit(schema, path) if isinstance(schema, dict) else None


def _shown(v: Any) -> Any:
    if isinstance(v, list):
        out = [_shown(x) for x in v[:50]]
        return out + ["…"] if len(v) > 50 else out
    return float(f"{v:.10g}") if isinstance(v, float) else v


def _operations_text() -> str:
    from sajha.ai.quant.ops import operations
    return "\n".join(f"- {sig}" for sig in operations().values())


def _estimate_findings(frame) -> List[Dict[str, Any]]:
    return [f for f in frame.slots.get("findings") or [] if f.get("check") == "estimate_consistent"]


class GraphPlan(StageType):
    """One structured model call: the computation graph (validated later by ``compute``)."""
    name = "graph_plan"
    model_using = True
    fixed_outcomes = ("planned", "invalid")

    def run(self, rc, frame, st):
        from sajha.ai.quant.graph import GRAPH_SCHEMA
        if False:
            yield
        prev = frame.slots.get("graph") or {}
        msgs = without_trailing_answers(frame.transcript)
        notes = []
        if prev.get("status") in ("invalid", "failed"):
            notes.append(f"{REPLAN_HEADER} was refused or failed. Graph: {json.dumps(prev.get('plan'))[:4000]}")
            if prev.get("errors"):
                notes.append("Errors:\n" + "\n".join(f"- {e}" for e in prev["errors"]))
            if prev.get("failed"):
                notes.append("Nodes that failed when run (and the nodes that needed them):\n"
                             + "\n".join(f"- {n}: {why}" for n, why in prev["failed"].items()))
        elif prev.get("plan") is not None and _estimate_findings(frame):
            notes.append(f"{REPLAN_HEADER} computed a figure that disagrees with a rough estimate. Graph: "
                         f"{json.dumps(prev.get('plan'))[:4000]}\n"
                         + "\n".join(f"- {f.get('message')}" for f in _estimate_findings(frame))
                         + "\nCheck the units, the scale (thousands, millions), per-share against total and "
                           "monthly against annual. Keep the graph if it is right.")
        if notes:
            notes.append("Write a corrected graph.")
            msgs = msgs + [ChatMessage.user("\n".join(notes))]
        instr = instruction(rc, frame, st, GRAPH_PROMPT) + "\n\nOperations:\n" + _operations_text()
        data = structured(rc, frame, st, msgs, GRAPH_SCHEMA, instr=instr, name="graph",
                          tools=[e.tool for e in rc.state.shortlist] or None)
        attempt = int(prev.get("attempt") or 0) + 1
        if not isinstance(data, dict):
            frame.slots["graph"] = {"attempt": attempt, "status": "invalid", "plan": None,
                                    "errors": ["the reply did not match the graph schema"], "failed": {}}
            rc.caveat(frame, f"{st.id}: the model did not return a computation graph")
            return "invalid"
        frame.slots["graph"] = {"attempt": attempt, "status": "planned", "plan": data, "errors": [], "failed": {},
                                "calls": {}, "quantities": [], "answer_with": list(data.get("answer_with") or [])}
        return "planned"


class Compute(StageType):
    """Validate the planned graph, then run it: tool reads in one parallel step, operations in
    dependency order in the run's workspace."""
    name = "compute"
    fixed_outcomes = ("done", "invalid", "failed")
    wants_raw_results = True              # reads see each call's uncapped output (runtime.run_frame)
    settings_schema = {"type": "object", "properties": {"max_nodes": _INT_OR_REF}}

    def run(self, rc, frame, st):
        from sajha.ai.planners import _coerce
        from sajha.ai.quant import Quantity, QuantError, quant_settings, workspace_of
        from sajha.ai.quant.graph import evaluate, parse_graph, read_value
        g = frame.slots.get("graph") or {}
        if g.get("status") != "planned":
            return "invalid"
        ws = workspace_of(rc.state, create=True)
        for name in rc.state.data.get(NAMES_KEY) or []:      # a re-plan replaces the previous graph
            ws.remove(name)
        rc.state.data[NAMES_KEY] = []
        cap = int(quant_settings().max_graph_nodes)
        if isinstance(st.cfg.get("max_nodes"), int):
            cap = min(cap, int(st.cfg["max_nodes"]))
        graph, errors = parse_graph(g.get("plan"), offered=list(rc.state.offered), max_nodes=cap,
                                    taken=ws.names(), unit_of=lambda t, p: schema_unit_of(rc.state, t, p))
        if graph is None:
            g.update(status="invalid", errors=errors)
            self._event(rc, frame, st, g)
            rc.caveat(frame, f"{st.id}: the computation graph was refused: {'; '.join(errors)}"[:300])
            return "invalid"
        # the tool reads: one call per distinct (tool, arguments), earlier identical calls reused
        keys: Dict[str, str] = {}
        calls: Dict[str, ToolCall] = {}
        records: Dict[str, Dict[str, Any]] = {}
        earlier = {(r.get("tool"), json.dumps(r.get("arguments") or {}, sort_keys=True, default=str)): r
                   for r in frame.slots.get("results") or [] if r.get("ok") and not r.get("derived")}
        for node in graph.tool_nodes():
            tool = node.spec["tool"]
            entry = rc.state.offered.get(tool)
            props = ((entry.tool.parameters_or_default or {}).get("properties") or {}) if entry else {}
            args = {k: _coerce(v, props.get(k) or {}) for k, v in node.arguments.items()}
            key = json.dumps([tool, args], sort_keys=True, default=str)
            keys[node.name] = key
            if key in records or key in calls:
                continue
            old = earlier.get((tool, json.dumps(args, sort_keys=True, default=str)))
            if old is not None:
                records[key] = old
                continue
            digest = hashlib.sha1(key.encode()).hexdigest()[:8]
            calls[key] = ToolCall.of(f"{st.id}_{digest}", tool, args)
        if calls:
            order = list(calls)
            tcs = [calls[k] for k in order]
            results = yield from calls_step(rc, frame, tcs, ChatMessage.assistant(None, tcs), len(tcs) > 1, st.id)
            for k, r in zip(order, results):
                records[k] = r
        raw = rc.state.data.get("raw_results") or {}
        reads: Dict[str, Any] = {}
        for node in graph.tool_nodes():
            r = records.get(keys[node.name])
            tool = node.spec["tool"]
            if r is None or not r.get("ok"):
                why = (r or {}).get("summary") or "not run"
                reads[node.name] = f"the {tool} call failed: {str(why)[:200]}"
                continue
            g["calls"][node.name] = r["id"]
            try:
                value = read_value(raw.get(r["id"], r.get("data")), node.spec["read"])
                reads[node.name] = Quantity.from_tool(value, node.spec.get("unit"), call_id=r["id"], tool=tool,
                                                      path=node.spec["read"], arguments=r.get("arguments") or {},
                                                      as_of=node.spec.get("as_of"), unit_from=node.unit_from)
            except QuantError as e:
                reads[node.name] = f"reading {node.spec['read']} from the {tool} result ({r['id']}): {e}"
        put, failed = evaluate(graph, ws, reads)
        rc.state.data[NAMES_KEY] = list(put)
        g.update(quantities=list(put), failed=failed, answer_with=list(graph.answer_with))
        missing = [a for a in graph.answer_with if a not in ws or a.split(".", 1)[0] in failed]
        if missing:
            g["status"] = "failed"
            self._event(rc, frame, st, g)
            rc.caveat(frame, f"{st.id}: {', '.join(missing)} could not be computed: "
                             + "; ".join(f"{n}: {w}" for n, w in failed.items())[:250])
            return "failed"
        g["status"] = "done"
        self._event(rc, frame, st, g)
        for n, why in failed.items():
            rc.caveat(frame, f"{st.id}: {n} could not be computed ({why})"[:300])
        lines = []
        ordered = list(graph.answer_with) + [n for n in put if n not in graph.answer_with]
        for name in ordered:
            q = ws.get(name)
            src = q.source or {}
            if src.get("kind") == "tool":
                how = f"read from call {src.get('call_id')} ({src.get('tool')}) at {src.get('path')}"
            elif q.lineage:
                ins = ", ".join(i if isinstance(i, str) else json.dumps(i, default=str)[:60]
                                for i in q.lineage.get("inputs") or [])
                how = f"{q.lineage.get('op')} of {ins}"
            else:
                how = "stated in the question"
            mark = " (answers the question)" if name in graph.answer_with else ""
            lines.append(f"- {name} = {json.dumps(_shown(q.value))} {q.unit}{mark}"
                         f"{' as of ' + q.as_of if q.as_of else ''}; {how}")
        frame.transcript.append(ChatMessage.user(RESULT_HEADER + "\n" + "\n".join(lines[:60])))
        return "done"

    @staticmethod
    def _event(rc, frame, st, g: Dict[str, Any]) -> None:
        if not frame.forked:
            rc.emit("graph", stage=st.id, attempt=g.get("attempt"), status=g.get("status"),
                    nodes=len(((g.get("plan") or {}).get("nodes") or {})), errors=list(g.get("errors") or [])[:20],
                    failed=dict(g.get("failed") or {}), answer_with=list(g.get("answer_with") or []))


class Estimate(StageType):
    """A rough magnitude and unit for the figure asked, without tools (a structured draft)."""
    name = "estimate"
    model_using = True
    fixed_outcomes = ("done", "none")

    def run(self, rc, frame, st):
        from sajha.ai.quant import UnitError, parse_unit
        if False:
            yield
        msgs = without_trailing_answers(frame.transcript)
        data = structured(rc, frame, st, msgs, ESTIMATE_SCHEMA, instr=instruction(rc, frame, st, ESTIMATE_PROMPT),
                          name="estimate")
        est = None
        if isinstance(data, dict) and isinstance(data.get("value"), (int, float)) \
                and not isinstance(data.get("value"), bool):
            try:
                unit = str(parse_unit(data.get("unit")))
                est = {"value": float(data["value"]), "unit": unit, "why": str(data.get("why") or "")[:300]}
            except UnitError:
                est = None
        frame.slots["estimate"] = est
        if not frame.forked:
            rc.emit("estimate", stage=st.id, value=(est or {}).get("value"), unit=(est or {}).get("unit"))
        return "done" if est else "none"


register_stage_type(GraphPlan)
register_stage_type(Compute)
register_stage_type(Estimate)


# ── the check ────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    return f"{v:,.6g}" if abs(v) < 1e15 else f"{v:.3e}"


@register_check("estimate_consistent", settings_schema={
    "type": "object", "additionalProperties": False,
    "properties": {"tolerance_factor": {"type": "number", "exclusiveMinimum": 1}, "quantity": {"type": "string"}}})
def estimate_consistent(ctx, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The computed figure (``quantity``, default the graph's first ``answer_with``) and the run's
    estimate agree within ``tolerance_factor`` (default 10) in magnitude, in the estimate's unit. No
    estimate, or nothing computed, passes (there is nothing to compare)."""
    from sajha.ai.quant import UnitError
    est = ctx.lookup("estimate")
    if not isinstance(est, dict) or est.get("value") is None:
        return []
    ws = ctx.workspace
    graph = ctx.lookup("graph") or {}
    name = s.get("quantity") or next(iter((graph.get("answer_with") or []) if isinstance(graph, dict) else []), None)
    if ws is None or not name or name not in ws:
        return []
    q = ws.get(name)
    if not q.is_scalar:
        return []
    try:
        factor = float(s.get("tolerance_factor", 10))
    except (TypeError, ValueError):
        factor = 10.0
    factor = max(factor, 1.0)
    ev, eu = float(est["value"]), str(est.get("unit") or "unitless")
    try:
        cv = float(q.to(eu).value)
    except UnitError:
        return [{"check": "estimate_consistent", "value": q.value,
                 "message": (f"The computed {name} is {_fmt(float(q.value))} {q.unit}, but a rough estimate was "
                             f"{_fmt(ev)} {eu}: the units do not agree.")[:300]}]
    a, b = abs(cv), abs(ev)
    if a == b or (a > 0 and b > 0 and max(a, b) / min(a, b) <= factor):
        return []
    return [{"check": "estimate_consistent", "value": cv,
             "message": (f"The computed {name} is {_fmt(cv)} {eu}, but a rough estimate was {_fmt(ev)} {eu}: they "
                         f"differ by more than a factor of {factor:g}.")[:300]}]
