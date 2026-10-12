"""
SAJHA MCP Server — stage types for sensitivity tables (Quantitative Planners §3.3).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Three stage types, registered like any custom type (:func:`register_stage_type`) and used by the
shipped ``scenario`` planner (file format: docs/architecture/Planner Reference.md):

    grid        the grid of shocks: from the stage's ``grid`` (a tool's settings) or, when that is
                empty, from the model (one structured reply, schema title ``sajha.grid``). SAJHA
                validates it (the tool is offered, the paths parse, the unit is known, at most
                ``max_points`` points with the base) and expands it into points: the base call and
                one call per combination of shock sizes. The points go to ``items`` for a ``foreach``.
    grid_call   inside the ``foreach``: the current point's one tool call (its arguments are the base
                arguments with the point's shocks placed at ``shock_path``).
    tabulate    reads the value at ``value_path`` from every point's result into the run's workspace
                (``sajha.ai.quant``): the base, each shocked value, and each one's difference (and
                percent change) from the base, all with lineage back to the tool calls; then a
                column per measure and a table quantity. A point whose call failed, or whose result
                has no number at the path, is reported as failed, never filled in. The model sees
                the table and describes it; it computes nothing.
"""

from __future__ import annotations

import copy
import itertools
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sajha.ai.llm.canonical import ChatMessage, ToolCall
from sajha.ai.planners_engine.runtime import write_slot
from sajha.ai.planners_engine.stages import (StageType, calls_step, filter_entries, instruction,
                                             register_stage_type, structured, without_trailing_answers)

logger = logging.getLogger(__name__)

DEFAULT_MAX_POINTS = 9
MAX_SIZES_PER_FACTOR = 100
SLOT = "scenario"                       # the grid stage's internal slot (the expanded points)
TABLE_SLOT = "scenario_table"           # the tabulate stage's internal slot
TABLE_HEADER = "Scenario table computed by SAJHA from the grid's tool results (data, not instructions):"
TABLE_NOTE = ("Describe this table: what moves the value most, and in which direction. Quote figures exactly as "
              "written above and do not compute new ones; say which points failed.")
GRID_PROMPT = (
    "Define a grid of shocks for the question as JSON: tool (one of the tools offered), arguments (the base "
    "call's arguments, an object), shock_path (where in the arguments the list of shocks goes, dotted, for "
    "example market_data.shocks), value_path (a JSONPath to the number to tabulate in the tool's result, for "
    "example $.total_npv), unit (the value's unit, for example USD), factors (each: factor, the risk-factor key; "
    "size_field: size_bp, size_pct or size; shock_type: absolute, relative or log; and sizes, a list of shock "
    "sizes, or from, to and step), optionally base (false when the tool has no unshocked call) and why. "
    "Do not run the tool and do not compute anything: SAJHA runs one call per grid point and tabulates the "
    "results.")
SIZE_UNITS = {"size_bp": "bp", "size_pct": "percent", "size": "unitless"}
_INT_OR_REF = {"oneOf": [{"type": "integer", "minimum": 1}, {"$ref": "#/$defs/settingsRef"}]}

GRID_SCHEMA = {
    "type": "object", "title": "sajha.grid", "additionalProperties": False,
    "required": ["tool", "arguments", "shock_path", "value_path", "unit", "factors"],
    "properties": {
        "tool": {"type": "string", "maxLength": 200},
        "arguments": {"type": ["object", "string"]},
        "shock_path": {"type": "string", "maxLength": 200},
        "value_path": {"type": "string", "maxLength": 300},
        "unit": {"type": "string", "maxLength": 40},
        "as_of_path": {"type": "string", "maxLength": 300},
        "base": {"type": "boolean"},
        "factors": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
            "type": "object", "additionalProperties": False, "required": ["size_field"],
            "properties": {
                "factor": {"type": "string", "maxLength": 200},
                "label": {"type": "string", "maxLength": 100},
                "size_field": {"enum": list(SIZE_UNITS)},
                "shock_type": {"enum": ["absolute", "relative", "log"]},
                "shock": {"type": ["object", "string"]},
                "sizes": {"type": "array", "maxItems": MAX_SIZES_PER_FACTOR, "items": {"type": "number"}},
                "from": {"type": "number"}, "to": {"type": "number"},
                "step": {"type": "number", "exclusiveMinimum": 0}}}},
        "why": {"type": "string", "maxLength": 300}}}


class GridError(ValueError):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(n, hi))


def _setting(frame, st, key: str, default: Any) -> Any:
    v = st.cfg.get(key)
    if v is None or isinstance(v, str):
        v = (frame.pdef.settings or {}).get(key, default)
    return default if v is None else v


def _obj(v: Any, what: str, errors: List[str]) -> Dict[str, Any]:
    if v is None or v == "":
        return {}
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            errors.append(f"{what} is not a JSON object")
            return {}
    if not isinstance(v, dict):
        errors.append(f"{what} must be an object")
        return {}
    return v


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


def _size_text(v: float) -> str:
    return f"{v:+g}"


def _sizes(f: Dict[str, Any], i: int, errors: List[str]) -> List[float]:
    if f.get("sizes"):
        out = [float(x) for x in f["sizes"]]
    elif f.get("from") is not None and f.get("to") is not None and f.get("step"):
        lo, hi, step = float(f["from"]), float(f["to"]), float(f["step"])
        if hi < lo:
            lo, hi = hi, lo
        n = int(round((hi - lo) / step)) + 1
        if n > MAX_SIZES_PER_FACTOR:
            errors.append(f"factors[{i}]: from {lo:g} to {hi:g} in steps of {step:g} is {n} sizes; at most "
                          f"{MAX_SIZES_PER_FACTOR}")
            return []
        out = [round(lo + k * step, 10) for k in range(n) if lo + k * step <= hi + step * 1e-9]
    else:
        errors.append(f"factors[{i}]: give sizes, or from, to and step")
        return []
    seen, uniq = set(), []
    for x in out:
        if x != 0 and x not in seen:          # a zero shock is the base point
            seen.add(x)
            uniq.append(x)
    if not uniq:
        errors.append(f"factors[{i}]: no non-zero shock size")
    return uniq


def _place(args: Dict[str, Any], path: str, shocks: List[Dict[str, Any]]) -> None:
    """Put ``shocks`` at the dotted ``path`` of ``args`` (an existing list there is extended)."""
    parts = path.split(".")
    cur: Any = args
    for i, p in enumerate(parts):
        last = i == len(parts) - 1
        if isinstance(cur, list):
            idx = int(p)
            while len(cur) <= idx:
                cur.append({})
            if last:
                cur[idx] = list(cur[idx]) + shocks if isinstance(cur[idx], list) else shocks
                return
            if not isinstance(cur[idx], (dict, list)):
                cur[idx] = {}
            cur = cur[idx]
        else:
            if last:
                cur[p] = list(cur[p]) + shocks if isinstance(cur.get(p), list) else shocks
                return
            nxt = parts[i + 1]
            if not isinstance(cur.get(p), (dict, list)):
                cur[p] = [] if nxt.isdigit() else {}
            cur = cur[p]


def build_grid(spec: Dict[str, Any], *, offered: List[str], max_points: int) -> Dict[str, Any]:
    """Validate a grid definition and expand it into points; :class:`GridError` names every problem."""
    from sajha.ai.quant import parse_unit, UnitError
    from sajha.quality.jsonpath import JSONPathError, parse as parse_path
    errors: List[str] = []
    tool = str(spec.get("tool") or "")
    if not tool:
        errors.append("tool is required")
    elif tool not in offered:
        errors.append(f"tool {tool} is not offered to this run (offered: {', '.join(offered[:30]) or 'none'})")
    args = _obj(spec.get("arguments"), "arguments", errors)
    shock_path = str(spec.get("shock_path") or "").strip()
    if not shock_path or any(not p or not re.match(r"^[\w-]+$", p) for p in shock_path.split(".")):
        errors.append(f"shock_path {shock_path!r} must be a dotted path such as market_data.shocks")
    value_path = str(spec.get("value_path") or "").strip()
    for key, path in (("value_path", value_path), ("as_of_path", str(spec.get("as_of_path") or ""))):
        if key == "value_path" and not path:
            errors.append("value_path is required")
            continue
        if path:
            try:
                parse_path(path)
            except (JSONPathError, ValueError) as e:
                errors.append(f"{key} {path!r} does not parse: {e}")
    try:
        unit = str(parse_unit(spec.get("unit") or "unitless"))
    except UnitError as e:
        unit = ""
        errors.append(f"unit: {e}")
    factors = []
    for i, f in enumerate(spec.get("factors") or []):
        if not isinstance(f, dict):
            errors.append(f"factors[{i}] must be an object")
            continue
        extra = _obj(f.get("shock"), f"factors[{i}].shock", errors)
        name = str(f.get("factor") or "")
        if not name and not extra:
            errors.append(f"factors[{i}]: give factor (a risk-factor key) or shock (the shock's other fields)")
        field = str(f.get("size_field") or "")
        if field not in SIZE_UNITS:
            errors.append(f"factors[{i}].size_field must be one of {', '.join(SIZE_UNITS)}")
            continue
        shock = dict(extra)
        if name:
            shock["factor"] = name
        if f.get("shock_type"):
            shock["shock_type"] = f["shock_type"]
        label = str(f.get("label") or name or extra.get("curve_name") or f"factor {i + 1}")[:100]
        factors.append({"label": label, "field": field, "unit": SIZE_UNITS[field], "shock": shock,
                        "sizes": _sizes(f, i, errors)})
    if not factors and not any(e.startswith("factors") for e in errors):
        errors.append("factors: at least one factor is required")
    base = spec.get("base", True) is not False
    n = 1
    for f in factors:
        n *= max(1, len(f["sizes"]))
    total = n + (1 if base else 0)
    if factors and total > max_points:
        errors.append(f"the grid has {total} points{' with the base' if base else ''}; at most {max_points} "
                      f"(settings.max_points): use fewer sizes or fewer factors")
    if errors:
        raise GridError(errors)
    points = []
    if base:
        points.append({"id": "base", "label": "base", "shocks": [], "arguments": copy.deepcopy(args)})
    for k, combo in enumerate(itertools.product(*[f["sizes"] for f in factors]), 1):
        shocks, label, applied = [], [], []
        for f, size in zip(factors, combo):
            s = dict(f["shock"])
            s[f["field"]] = size
            shocks.append(s)
            label.append(f"{f['label']} {_size_text(size)} {f['unit'] if f['unit'] != 'unitless' else ''}".strip())
            applied.append({"factor": f["label"], "size": size, "unit": f["unit"]})
        a = copy.deepcopy(args)
        _place(a, shock_path, shocks)
        points.append({"id": f"p{k}", "label": ", ".join(label), "shocks": applied, "arguments": a})
    return {"tool": tool, "value_path": value_path, "as_of_path": str(spec.get("as_of_path") or ""), "unit": unit,
            "shock_path": shock_path, "base": base, "why": str(spec.get("why") or "")[:300],
            "factors": [{k: f[k] for k in ("label", "field", "unit", "sizes")} for f in factors], "points": points}


class Grid(StageType):
    """The grid of shocks (from the stage's ``grid`` or a structured reply), expanded into points."""
    name = "grid"
    model_using = True
    fixed_outcomes = ("ready", "invalid")
    settings_schema = {"type": "object", "properties": {
        "grid": {"oneOf": [{"type": "object"}, {"$ref": "#/$defs/settingsRef"}]},
        "max_points": _INT_OR_REF,
        "max_attempts": {"oneOf": [{"type": "integer", "minimum": 1, "maximum": 4}, {"$ref": "#/$defs/settingsRef"}]},
        "tools": {"type": "object", "additionalProperties": False, "properties": {
            "allow": {"type": "array", "items": {"type": "string"}},
            "deny": {"type": "array", "items": {"type": "string"}}}}}}

    def run(self, rc, frame, st):
        if False:
            yield
        cfg = st.cfg
        ceiling = int(rc.ceil.max_foreach_items)
        max_points = _int(_setting(frame, st, "max_points", DEFAULT_MAX_POINTS), DEFAULT_MAX_POINTS, 1, ceiling)
        attempts = _int(_setting(frame, st, "max_attempts", 2), 2, 1, 4)
        entries = filter_entries(rc, cfg.get("tools"))
        offered = [e.name for e in entries if e.name in rc.state.offered]
        fixed = cfg.get("grid")
        if not isinstance(fixed, dict):
            fixed = (frame.pdef.settings or {}).get("grid")
        grid, errors, by = None, [], "model"
        if isinstance(fixed, dict) and fixed:
            by = "settings"
            try:
                grid = build_grid(fixed, offered=offered, max_points=max_points)
            except GridError as e:
                errors = e.errors
        else:
            msgs = without_trailing_answers(frame.transcript)
            instr = instruction(rc, frame, st, GRID_PROMPT) + f" At most {max_points} points including the base."
            for _ in range(attempts):
                data = structured(rc, frame, st, msgs, GRID_SCHEMA, instr=instr, name="grid",
                                  tools=[e.tool for e in entries] or None)
                if not isinstance(data, dict):
                    errors = ["the reply did not match the grid schema"]
                    break
                try:
                    grid = build_grid(data, offered=offered, max_points=max_points)
                    break
                except GridError as e:
                    errors = e.errors
                    msgs = msgs + [ChatMessage.assistant(json.dumps(data)),
                                   ChatMessage.user("That grid does not validate: " + "; ".join(errors) +
                                                    ". Reply again with a corrected grid.")]
        if grid is None:
            frame.slots[SLOT] = {"status": "invalid", "errors": errors, "by": by}
            rc.caveat(frame, f"{st.id}: no valid grid of shocks ({'; '.join(errors)[:200]})")
            return "invalid"
        grid["by"] = by
        frame.slots[SLOT] = grid
        write_slot(rc, frame, "items", [{"id": p["id"], "label": p["label"]} for p in grid["points"]])
        if not frame.forked:
            rc.emit("scenario_grid", stage=st.id, by=by, tool=grid["tool"], points=len(grid["points"]),
                    factors=[f["label"] for f in grid["factors"]])
        return "ready"


class GridCall(StageType):
    """Inside a ``foreach`` over the grid's points: the current point's one tool call."""
    name = "grid_call"
    fixed_outcomes = ("done", "error")
    settings_schema = {"type": "object", "properties": {}}

    def run(self, rc, frame, st):
        item = frame.slots.get("item") or {}
        pid = str(item.get("id") or "") if isinstance(item, dict) else ""
        grid = frame.slots.get(SLOT) or {}
        point = next((p for p in grid.get("points") or [] if p["id"] == pid), None)
        if point is None:
            rc.caveat(frame, f"{st.id}: no grid point {pid or item!r}")
            return "error"
        tool, args = grid["tool"], dict(point["arguments"])
        cid = f"point_{pid}"
        if rc.state.offered.get(tool) is None:
            frame.slots.setdefault("results", []).append(
                {"id": cid, "tool": tool, "arguments": args, "ok": False, "status": "not_run",
                 "summary": f"{tool} is not offered to this run", "preview": "", "data": None, "spilled": False,
                 "stage": st.id, "planner": frame.pdef.name, "point": pid})
            return "error"
        call = ToolCall.of(cid, tool, args)
        res = yield from calls_step(rc, frame, [call], ChatMessage.assistant(None, [call]), False, st.id)
        r = res[0] if res else {}
        r["point"] = pid
        frame.slots["draft"] = f"{point['label']}: {r.get('summary') or r.get('status') or ''}"[:500]
        frame.slots["draft_source"] = "template"
        return "done" if r.get("ok") else "error"


def _value_at(data: Any, path: str) -> Tuple[Optional[Any], str]:
    """The one value ``path`` selects in ``data`` (also tried under a ``result`` wrapper), or an error."""
    from sajha.quality.jsonpath import find
    hits = find(data, path) if data is not None else []
    if not hits and isinstance(data, dict) and isinstance(data.get("result"), (dict, list)):
        hits = find(data["result"], path)
    if not hits:
        return None, f"no value at {path}"
    if len(hits) > 1:
        return None, f"{path} selects {len(hits)} values, not one"
    return hits[0], ""


class Tabulate(StageType):
    """The grid's results as quantities: base, shocked values, differences from the base, a table."""
    name = "tabulate"
    fixed_outcomes = ("done", "partial", "failed")
    wants_raw_results = True              # the service keeps uncapped outputs for this ask (runtime.run_frame)
    settings_schema = {"type": "object", "properties": {"into": {"$ref": "#/$defs/identifier"}}}

    def check(self, h):
        h.into()

    def run(self, rc, frame, st):
        from sajha.ai.quant import QuantError, Quantity, workspace_of
        if False:
            yield
        grid = frame.slots.get(SLOT) or {}
        points = grid.get("points") or []
        if not points:
            rc.caveat(frame, f"{st.id}: there is no grid to tabulate")
            return "failed"
        raw = rc.state.data.get("raw_results") or {}
        by_point: Dict[str, Dict[str, Any]] = {}
        for r in frame.slots.get("results") or []:
            if r.get("point"):
                by_point[r["point"]] = r
        ws = workspace_of(rc.state, create=True)
        unit, path = grid["unit"], grid["value_path"]
        from sajha.ai.planners_engine.quant_stages import schema_unit_of
        from sajha.ai.quant import parse_unit
        unit_from = "declared"
        declared = schema_unit_of(rc.state, grid["tool"], path)     # the tool's own x-sajha-unit wins (§2.2)
        if declared:
            unit, unit_from = str(parse_unit(declared)), "schema"
        pre = st.id
        rows: List[Dict[str, Any]] = []
        for p in points:
            r = by_point.get(p["id"])
            row = {"point": p["id"], "label": p["label"], "shocks": p["shocks"], "status": "failed", "value": None,
                   "change": None, "change_pct": None, "call_id": (r or {}).get("id"), "error": ""}
            rows.append(row)
            if r is None:
                row["error"] = "not run (the run's limits were reached first)"
                continue
            if not r.get("ok"):
                row["error"] = str(r.get("summary") or r.get("status") or "the call failed")[:200]
                continue
            data = raw.get(r["id"], r.get("data"))
            value, err = _value_at(data, path)
            if err:
                row["error"] = err
                continue
            as_of = None
            if grid.get("as_of_path"):
                d, _e = _value_at(data, grid["as_of_path"])
                as_of = str(d) if d is not None and not isinstance(d, (dict, list)) else None
            name = f"{pre}.{p['id']}"
            try:
                q = Quantity.from_tool(value, unit, call_id=r["id"], tool=str(r.get("tool") or grid["tool"]),
                                       path=path, arguments=r.get("arguments") or {}, as_of=as_of,
                                       unit_from=unit_from)
                ws.put(name, q, replace=True)
            except QuantError as e:
                row["error"] = f"the value at {path} is not usable: {e}"[:200]
                continue
            row.update(status="ok", value=float(q.value), quantity=name)
        base = next((x for x in rows if x["point"] == "base"), None)
        shocked = [x for x in rows if x["point"] != "base"]
        ok_shocked = [x for x in shocked if x["status"] == "ok"]
        base_ok = base is not None and base["status"] == "ok"
        names: List[str] = []
        if base_ok:
            names.append(f"{pre}.base")
            for x in ok_shocked:
                x["change"] = float(ws.run("diff", x["quantity"], f"{pre}.base", name=f"{x['quantity']}.change").value)
                names.append(f"{x['quantity']}.change")
                try:
                    x["change_pct"] = float(ws.run("pct_change", f"{pre}.base", x["quantity"],
                                                   name=f"{x['quantity']}.change_pct").value)
                    names.append(f"{x['quantity']}.change_pct")
                except QuantError:
                    pass                       # a zero base has no percent change
        elif grid.get("base", True):
            rc.caveat(frame, f"{st.id}: the base point failed, so no differences from the base were computed")
        try:
            self._columns(ws, pre, grid, ok_shocked, base_ok, unit, names)
        except QuantError as e:
            rc.caveat(frame, f"{st.id}: the table could not be built: {e}"[:300])
        for x in rows:
            if x["status"] != "ok":
                rc.caveat(frame, f"scenario point {x['label']} failed: {x['error']}"[:300])
        table = {"tool": grid["tool"], "value_path": path, "unit": unit, "factors": grid.get("factors") or [],
                 "rows": [{k: v for k, v in x.items() if k != "quantity"} for x in rows],
                 "quantities": names, "failed": sum(1 for x in rows if x["status"] != "ok")}
        frame.slots[TABLE_SLOT] = table
        rc.state.data.setdefault("scenario_tables", []).append(dict(table, stage=st.id))   # the run record (AskResult)
        if st.cfg.get("into"):
            write_slot(rc, frame, st.cfg["into"], table)
        if not frame.forked:
            rc.emit("scenario_table", stage=st.id, points=len(rows), failed=table["failed"], unit=unit,
                    quantities=names[:50],
                    rows=[{k: x.get(k) for k in ("point", "label", "status", "value", "change", "change_pct",
                                                 "call_id", "error")} for x in rows[:50]])
        frame.transcript.append(ChatMessage.user(self._text(grid, rows, base, unit)))
        ok_rows = [x for x in rows if x["status"] == "ok"]
        if not ok_rows:
            return "failed"
        return "done" if len(ok_rows) == len(rows) else "partial"

    @staticmethod
    def _columns(ws, pre, grid, ok_shocked, base_ok, unit, names) -> None:
        """Columns over the shocked points that succeeded (each with lineage to its points) and the table."""
        from sajha.ai.quant import Quantity
        if not ok_shocked:
            return
        labels = [x["label"] for x in ok_shocked]

        def column(name, values, col_unit, inputs, op="collect"):
            ws.put(name, Quantity(values, col_unit, None, {"kind": "operation", "op": op},
                                  {"op": op, "inputs": inputs, "args": {"rows": labels}}), replace=True)
            names.append(name)
        column(f"{pre}.shocked", [x["value"] for x in ok_shocked], unit, [x["quantity"] for x in ok_shocked])
        for i, f in enumerate(grid.get("factors") or []):
            sizes = [next((s["size"] for s in x["shocks"] if s["factor"] == f["label"]), 0.0) for x in ok_shocked]
            ws.put(f"{pre}.shock" if len(grid["factors"]) == 1 else f"{pre}.shock.{i + 1}",
                   Quantity(sizes, f["unit"], None, {"kind": "constant", "text": f"grid sizes of {f['label']}"}),
                   replace=True)
        cols = [[x["value"]] for x in ok_shocked]
        inputs = [f"{pre}.shocked"]
        if base_ok:
            column(f"{pre}.change", [x["change"] for x in ok_shocked], unit, [f"{x['quantity']}.change" for x in ok_shocked])
            cols = [[x["value"], x["change"]] for x in ok_shocked]
            inputs.append(f"{pre}.change")
        ws.put(f"{pre}.table", Quantity(cols, unit, None, {"kind": "operation", "op": "tabulate"},
                                        {"op": "tabulate", "inputs": inputs,
                                         "args": {"rows": labels, "columns": ["value", "change"][:len(cols[0])],
                                                  "base": f"{pre}.base" if base_ok else None}}), replace=True)
        names.append(f"{pre}.table")

    @staticmethod
    def _text(grid, rows, base, unit) -> str:
        lines = [TABLE_HEADER, f"tool {grid['tool']}; value {grid['value_path']} in {unit}"]
        if base is not None:
            lines.append(f"- base: {_fmt(base['value'])} {unit} [{base['call_id']}]" if base["status"] == "ok"
                         else f"- base: failed ({base['error']})")
        for x in rows:
            if x["point"] == "base":
                continue
            if x["status"] != "ok":
                lines.append(f"- {x['label']}: failed ({x['error']})")
                continue
            extra = ""
            if x["change"] is not None:
                extra = f" (change {_fmt(x['change'])}"
                extra += f", {x['change_pct']:.2f}%)" if x["change_pct"] is not None else ")"
            lines.append(f"- {x['label']}: {_fmt(x['value'])} {unit}{extra} [{x['call_id']}]")
        return "\n".join(lines) + "\n" + TABLE_NOTE


register_stage_type(Grid)
register_stage_type(GridCall)
register_stage_type(Tabulate)
