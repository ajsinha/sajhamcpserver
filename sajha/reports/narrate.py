"""
SAJHA MCP Server — report narration with a numbers check (docs/architecture/Reports.md §5).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``report_narrate`` writes commentary over one stored report run and checks it before it is
returned. The narrator is a model reached only through the LLM layer
(``llm_factory().model(alias)``, alias ``reports.narrate_model``); it sees the run's data and
nothing else, and has no tools.

The check
---------
1. **Numbers.** The numbers validator of the quantitative workspace
   (``sajha.ai.planners_engine.numbers.unmatched``, the ``numbers_in_workspace`` check) runs over
   the commentary with the run's section data as the tool results and the run's computed
   comparisons as workspace quantities. A figure the validator does not match is matched once
   more at the precision it is written (``1.2bn`` for 1,234,000,000; ``12.3%`` for 0.1234), by
   magnitude (``fell 3.2%`` for a change of -3.2). Anything else is unmatched: an invented
   number, a number rounded past what it says (``about 1,200`` for 1,234.56), or a percent the
   report did not compute.
2. **Comparisons as quantities.** The run's ``comparisons`` (when the engine stored them) and,
   failing that, the comparisons computed here from the run and the previous run of the same
   report: each value's previous value, change and percent change (a change in points for a
   rate), and each numeric table column's shares of its total. They are workspace quantities
   built with the operation library, so the arithmetic is SAJHA's, not the model's.
3. **Dates.** Every date (ISO, ``9 October 2026``, ``Oct 9, 2026``, ``October 2026``,
   ``2026-10``, ``9 Oct``) and bare year must be a parameter of the run, the run's own date, or
   appear in its data. Section references (``section 3``) and ordinals (``21st``) are ignored.
4. **Reject.** Commentary with any unmatched figure gets one revision, with the figures named.
   A figure still unmatched is replaced by ``[unverified figure removed]`` and a caveat names
   it; the audit records ``report.narrate.rejected``. An invented figure is never returned.

Run access
----------
A run is read through a :class:`RunSource` (``load(run_id, caller) -> dict``, raising
``KeyError`` for an unknown run and ``PermissionError`` for one the caller may not see;
``previous(run, caller) -> dict | None``; ``warn(run, message)``). :func:`default_source` reads the
engine's run store (sajha/reports/history.py): only the runner and administrators may narrate a
run, and a run whose commentary lost figures gets a warning in its record. The run dict this module reads::

    {"run_id", "report", "title"?, "parameters": {...}, "started_at"?,
     "sections": [{"id", "title"?, "kind"?, ...section data...}],
     "comparisons"?: [{"label", "value", "unit"?}]}

Public API: :func:`narrate`, :func:`check_commentary`, :func:`build_context`,
:func:`comparisons_workspace`, :class:`RunSource`, :func:`default_source`.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

REMOVED = "[unverified figure removed]"
LABEL = "Model-written commentary. Every figure and date was checked against this run's data."
LENGTHS = {"short": 90, "medium": 180, "long": 350}
MAX_DATA_CHARS = 40000
MAX_COMPARISONS = 4000
_META_KEYS = {"provenance", "source", "attribution", "tool", "tool_version", "version", "arguments", "trace_id",
              "error", "status", "call", "as_of_time"}

SYSTEM_PROMPT = (
    "You write short commentary for a business report. You are given the report's data and the comparisons "
    "the report computed. Rules: every number you write must appear in the data or the comparisons, written at "
    "the precision shown there or coarser only by ordinary rounding of the last digit; never compute a new "
    "figure (no sums, differences, averages or percentages of your own); every date must appear in the data or "
    "the parameters; use no outside knowledge. Write plain prose, no headings, no tables, no markdown.")

REVISE_PROMPT = (
    "The draft below cites figures or dates that are not in the report data or its computed comparisons. "
    "Rewrite it so that every figure and date is one given above; correct or drop each one listed, and change "
    "nothing else.")


# ── run access ───────────────────────────────────────────────────

class RunSource:
    """Where narration reads a run. ``load`` raises KeyError (unknown) or PermissionError."""

    def load(self, run_id: str, caller: Any) -> Dict[str, Any]:     # pragma: no cover - interface
        raise NotImplementedError

    def previous(self, run: Dict[str, Any], caller: Any) -> Optional[Dict[str, Any]]:
        return None

    def warn(self, run: Dict[str, Any], message: str) -> None:
        return None

    def store(self, run: Dict[str, Any], section_id: str, result: Dict[str, Any], warning: Optional[str]) -> bool:
        """Put the commentary in the run's waiting text section (True when stored)."""
        return False


class _EngineSource(RunSource):
    """The run store of the report engine (sajha/reports/history.py)."""

    def load(self, run_id: str, caller: Any) -> Dict[str, Any]:
        from sajha.reports import history
        run = history.load(run_id)
        if run is None:
            raise KeyError(run_id)
        if not history.may_see(run, caller):
            raise PermissionError(f"only the user who ran {run_id} and administrators may narrate it")
        return run

    def previous(self, run: Dict[str, Any], caller: Any) -> Optional[Dict[str, Any]]:
        from sajha.reports import history
        return history.previous(str(run.get("report") or ""), run.get("parameters") or {}, caller,
                                str(run.get("run_id") or ""))

    def warn(self, run: Dict[str, Any], message: str) -> None:
        """Record a warning on the run (Reports §5.4: the run record gets a warning)."""
        from sajha.reports import history
        fresh = history.load(str(run.get("run_id") or ""))
        if fresh is None:
            return
        fresh.setdefault("warnings", []).append(message)
        history.save(fresh)

    def store(self, run: Dict[str, Any], section_id: str, result: Dict[str, Any], warning: Optional[str]) -> bool:
        """The commentary into the waiting text section, ``narration`` on the run, then the run's
        files rendered again (sajha/reports/__init__.py: "To store commentary")."""
        from sajha.reports import engine, history
        fresh = history.load(str(run.get("run_id") or ""))
        sec = next((s for s in (fresh or {}).get("sections") or [] if s.get("id") == section_id), None)
        if sec is None:
            return False
        text = result["commentary"] + ("\n\n" + " ".join(result["caveats"]) if result["caveats"] else "")
        sec.update(text=text, status="text")
        fresh["narration"] = {"model": result["model"], "section": section_id, "sections": result["sections"],
                              "length": result["length"], "audience": result["audience"],
                              "revised": result["revised"], "removed": [f["raw"] for f in result["removed"]],
                              "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "label": LABEL}
        if warning:
            fresh.setdefault("warnings", []).append(warning)
        history.save(fresh)
        if fresh.get("files"):
            try:
                engine.render_and_store(fresh, list(fresh["files"]))
                history.save(fresh)
            except Exception as e:
                logger.warning(f"report_narrate: re-rendering {fresh.get('run_id')}: {e}")
        return True


def default_source() -> RunSource:
    return _EngineSource()


# ── settings ─────────────────────────────────────────────────────

def narrate_model() -> str:
    """``reports.narrate_model``; the ``default`` alias when it is empty."""
    try:
        from sajha.reports import settings
        return (settings.narrate_model() or "default").strip()
    except Exception:
        return "default"


# ── walking the data ─────────────────────────────────────────────

def _section_data(sec: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in sec.items() if k not in _META_KEYS}


def _strings(v: Any, out: List[str], depth: int = 0) -> None:
    if depth > 40:
        return
    if isinstance(v, str):
        out.append(v)
    elif isinstance(v, dict):
        for k, x in v.items():
            out.append(str(k))
            _strings(x, out, depth + 1)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _strings(x, out, depth + 1)
    elif isinstance(v, (date, datetime)):
        out.append(v.isoformat())


def _ints(v: Any, out: List[int], depth: int = 0) -> None:
    if depth > 40 or isinstance(v, bool):
        return
    if isinstance(v, (int, float)) and float(v).is_integer():
        out.append(int(v))
    elif isinstance(v, dict):
        for x in v.values():
            _ints(x, out, depth + 1)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _ints(x, out, depth + 1)


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _row_key(row: Dict[str, Any], i: int) -> str:
    for v in row.values():
        if isinstance(v, str) and v.strip():
            return v.strip()
    return f"#{i + 1}"


def _leaves(v: Any, path: str = "", out: Optional[Dict[str, float]] = None, depth: int = 0) -> Dict[str, float]:
    """Numeric leaves by path; rows of a table are keyed by their first text field."""
    out = {} if out is None else out
    if depth > 30 or len(out) > MAX_COMPARISONS:
        return out
    n = _num(v)
    if n is not None:
        out[path] = n
    elif isinstance(v, dict):
        for k, x in v.items():
            _leaves(x, f"{path}.{k}" if path else str(k), out, depth + 1)
    elif isinstance(v, list):
        keys = [_row_key(r, i) if isinstance(r, dict) else f"#{i + 1}" for i, r in enumerate(v)]
        if len(set(keys)) != len(keys):
            keys = [f"#{i + 1}" for i in range(len(v))]
        for k, x in zip(keys, v):
            _leaves(x, f"{path}[{k}]", out, depth + 1)
    return out


def _unit_for(path: str, sec: Dict[str, Any]) -> str:
    """``percent``/``bp`` when the section formats this value as a rate; else ``unitless``."""
    p = path.lower()
    for v in sec.get("values") or sec.get("kpis") or []:
        if isinstance(v, dict) and str(v.get("format", "")).lower() in ("percent", "pct", "%", "bp"):
            label = str(v.get("label", "")).lower()
            if label and label in p:
                return "bp" if str(v.get("format")).lower() == "bp" else "percent"
    if p.endswith(("_pct", "pct", "_percent", "percent")):
        return "percent"
    if p.endswith(("_bp", "_bps")):
        return "bp"
    return "unitless"


def _tables(v: Any, path: str = "", depth: int = 0):
    """(path, rows) for every list of row dicts."""
    if depth > 20:
        return
    if isinstance(v, list) and v and all(isinstance(r, dict) for r in v):
        yield path, v
    if isinstance(v, dict):
        for k, x in v.items():
            yield from _tables(x, f"{path}.{k}" if path else str(k), depth + 1)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            if isinstance(x, (dict, list)):
                yield from _tables(x, f"{path}[{i}]", depth + 1)


# ── comparisons as quantities ────────────────────────────────────

@dataclass
class Comparisons:
    workspace: Any
    labels: Dict[str, str] = field(default_factory=dict)     # quantity name -> what it is

    def lines(self, limit: int = 400) -> List[str]:
        out = []
        for name, label in list(self.labels.items())[:limit]:
            q = self.workspace.get(name)
            out.append(f"{label}: {_fmt(q.value)} {q.unit}".rstrip())
        return out


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return format(v, ".10g")
    return str(v)


_FORMAT_UNITS = {"percent": "percent", "ratio": "ratio", "bps": "bp", "bp": "bp"}


def _engine_unit(q: Dict[str, Any]) -> str:
    """The unit of one of the engine's quantities: shares and percent changes are percent; a
    change of a rate is in points of it; otherwise the value's display format decides."""
    kind, fmt = q.get("kind"), str(q.get("format") or "number")
    if kind in ("share", "pct_change"):
        return "percent"
    unit = _FORMAT_UNITS.get(fmt, "unitless")
    if kind == "change" and unit in ("percent", "ratio"):
        return "pp" if unit == "percent" else "ratio"
    return unit


def comparisons_workspace(run: Dict[str, Any], previous: Optional[Dict[str, Any]] = None,
                          sections: Optional[Iterable[str]] = None) -> Comparisons:
    """The run's computed comparisons as workspace quantities: those the engine stored, else
    changes against ``previous`` and each table column's shares (Reports §5.2)."""
    from sajha.ai.quant import Quantity, QuantError, Workspace
    ws = Workspace()
    cmp = Comparisons(ws)
    want = set(sections) if sections else None
    counter = [0]

    def put(q, label: str) -> Optional[str]:
        counter[0] += 1
        name = f"c{counter[0]}"
        ws.put(name, q)
        cmp.labels[name] = label
        return name

    engine_qs = run.get("quantities")
    if isinstance(engine_qs, list) and engine_qs:          # the engine's (sajha/reports/engine.py::quantities)
        for c in engine_qs[:MAX_COMPARISONS]:
            if not isinstance(c, dict) or (want and c.get("section") not in want) or _num(c.get("value")) is None:
                continue
            try:
                put(Quantity.of(c["value"], _engine_unit(c)),
                    f"{c.get('section')} {c.get('label')}: {c.get('kind', 'value')}")
            except (QuantError, ValueError, TypeError):
                continue
        return cmp
    stored = run.get("comparisons")
    if isinstance(stored, list) and stored:
        for c in stored[:MAX_COMPARISONS]:
            if not isinstance(c, dict):
                continue
            if want and c.get("section") and c["section"] not in want:
                continue
            try:
                put(Quantity.of(c.get("value"), c.get("unit") or "unitless"), str(c.get("label") or c.get("name")))
            except (QuantError, ValueError, TypeError):
                continue
        return cmp

    prev_secs = {s.get("id"): s for s in (previous or {}).get("sections") or [] if isinstance(s, dict)}
    for sec in run.get("sections") or []:
        if not isinstance(sec, dict) or (want and sec.get("id") not in want):
            continue
        sid = str(sec.get("id") or "")
        data = _section_data(sec)
        if sid in prev_secs:
            before = _leaves(_section_data(prev_secs[sid]))
            for path, now in _leaves(data).items():
                if path not in before or len(ws) > MAX_COMPARISONS:
                    continue
                unit = _unit_for(path, sec)
                try:
                    a = Quantity.of(before[path], unit)
                    b = Quantity.of(now, unit)
                    pa = put(a, f"{sid} {path}: previous run")
                    pb = put(b, f"{sid} {path}: this run")
                    counter[0] += 1
                    name = f"c{counter[0]}"
                    ws.run("diff", pb, pa, name=name)
                    cmp.labels[name] = f"{sid} {path}: change since the previous run"
                    if unit == "unitless" and before[path] != 0:
                        counter[0] += 1
                        name = f"c{counter[0]}"
                        ws.run("pct_change", pa, pb, name=name)
                        cmp.labels[name] = f"{sid} {path}: percent change since the previous run"
                except QuantError:
                    continue
        for tpath, rows in _tables(data):
            if str(sec.get("kind", "")).lower() == "kpis" or tpath.split(".")[-1] in ("values", "kpis"):
                continue                          # KPIs are not parts of one total
            cols: Dict[str, List[Tuple[str, float]]] = {}
            for i, r in enumerate(rows):
                for k, v in r.items():
                    n = _num(v)
                    if n is not None:
                        cols.setdefault(k, []).append((_row_key(r, i), n))
            for col, vals in cols.items():
                total = sum(v for _, v in vals)
                if len(vals) < 2 or total <= 0 or any(v < 0 for _, v in vals) or len(ws) > MAX_COMPARISONS:
                    continue
                if _unit_for(col, sec) != "unitless":
                    continue
                for key, v in vals:
                    try:
                        put(Quantity.of(v / total * 100.0, "percent"), f"{sid} {tpath} {key}: share of {col} total")
                    except QuantError:
                        continue
    return cmp


# ── dates ────────────────────────────────────────────────────────

_MONTH = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
          r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                            "nov", "dec"])}
_ORD = r"(?:st|nd|rd|th)?"
_DATE_PATTERNS = [
    ("ymd", re.compile(r"(?<![\w.-])(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?(?![\w-])")),
    ("ymd", re.compile(r"(?<![\w.-])(\d{4})/(\d{1,2})/(\d{1,2})(?![\w/])")),
    ("slash", re.compile(r"(?<![\w./])(\d{1,2})/(\d{1,2})/(\d{4})(?![\w/])")),
    ("dmy", re.compile(rf"(?<![\w.])(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MONTH}\.?,?\s+(\d{{4}})(?!\w)", re.I)),
    ("mdy", re.compile(rf"(?<![\w.]){_MONTH}\.?\s+(\d{{1,2}}){_ORD},?\s+(\d{{4}})(?!\w)", re.I)),
    ("my", re.compile(rf"(?<![\w.]){_MONTH}\.?,?\s+(\d{{4}})(?!\w)", re.I)),
    ("ym", re.compile(r"(?<![\w.-])(\d{4})-(\d{2})(?![\w-])")),
    ("dm", re.compile(rf"(?<![\w.])(\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MONTH}(?![a-z])", re.I)),
    ("md", re.compile(rf"(?<![\w.]){_MONTH}\.?\s+(\d{{1,2}}){_ORD}(?!\w)", re.I)),
    ("y", re.compile(r"(?<![\w.,$€£-])((?:19|20)\d{2})(?![\w%]|[.,]\d|\s*(?:%|bps?\b|pp\b|bn\b|mn\b|k\b|million|"
                     r"billion|thousand|trillion|per ?cent))", re.I)),
]


def _month(word: str) -> int:
    return _MONTHS.get(word.lower()[:3], 0)


def _valid(y: int, m: int, d: int = 1) -> bool:
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def find_dates(text: str) -> List[Dict[str, Any]]:
    """Dates in ``text``: [{kind, key, raw, start, end}] where ``key`` is a (y, m, d), (y, m),
    (m, d) or (y,) tuple; ``slash`` dates carry both readings in ``keys``. Spans never overlap."""
    taken: List[Tuple[int, int]] = []
    out: List[Dict[str, Any]] = []
    for kind, pat in _DATE_PATTERNS:
        for m in pat.finditer(text or ""):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            g = m.groups()
            keys: List[tuple] = []
            if kind == "ymd":
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
                keys = [("ymd", y, mo, d)] if _valid(y, mo, d) else []
            elif kind == "slash":
                a, b, y = int(g[0]), int(g[1]), int(g[2])
                keys = [("ymd", y, mo, d) for mo, d in ((a, b), (b, a)) if _valid(y, mo, d)]
            elif kind == "dmy":
                y, mo, d = int(g[2]), _month(g[1]), int(g[0])
                keys = [("ymd", y, mo, d)] if _valid(y, mo, d) else []
            elif kind == "mdy":
                y, mo, d = int(g[2]), _month(g[0]), int(g[1])
                keys = [("ymd", y, mo, d)] if _valid(y, mo, d) else []
            elif kind == "my":
                keys = [("ym", int(g[1]), _month(g[0]))]
            elif kind == "ym":
                y, mo = int(g[0]), int(g[1])
                keys = [("ym", y, mo)] if 1 <= mo <= 12 and 1900 <= y <= 2100 else []
            elif kind == "dm":
                mo, d = _month(g[1]), int(g[0])
                keys = [("md", mo, d)] if _valid(2000, mo, d) else []
            elif kind == "md":
                mo, d = _month(g[0]), int(g[1])
                keys = [("md", mo, d)] if _valid(2000, mo, d) else []
            elif kind == "y":
                keys = [("y", int(g[0]))]
            if not keys:
                continue
            taken.append((s, e))
            out.append({"kind": "date", "keys": keys, "raw": m.group(0).strip(), "start": s, "end": e})
    out.sort(key=lambda d: d["start"])
    return out


def allowed_dates(run: Dict[str, Any], sections: List[Dict[str, Any]]) -> Set[tuple]:
    """Every date key the run supports: its parameters, its own date and its data's dates and years."""
    texts: List[str] = []
    _strings(run.get("parameters") or {}, texts)
    for k in ("started_at", "finished_at", "created_at", "as_of", "run_at"):
        if run.get(k):
            _strings(run.get(k), texts)
    for sec in sections:
        _strings(sec, texts)
    keys: Set[tuple] = set()
    for t in texts:
        for d in find_dates(t):
            keys.update(d["keys"])
    ints: List[int] = []
    _ints(run.get("parameters") or {}, ints)
    for sec in sections:
        _ints(sec, ints)
    keys.update(("y", i) for i in ints if 1900 <= i <= 2100)
    derived: Set[tuple] = set()
    for k in keys:
        if k[0] == "ymd":
            derived.update({("ym", k[1], k[2]), ("y", k[1]), ("md", k[2], k[3])})
        elif k[0] == "ym":
            derived.add(("y", k[1]))
    return keys | derived


# ── the check ────────────────────────────────────────────────────

_SECTION_REF = re.compile(r"(?i)(?:\bsections?|§)\s*\d+(?:\.\d+)*(?:\s*(?:and|to|-|,)\s*\d+(?:\.\d+)*)*")
_ORDINAL = re.compile(r"(?i)(?<![\w.])\d+(?:st|nd|rd|th)\b")


def _mask(text: str, spans: Iterable[Tuple[int, int]]) -> str:
    chars = list(text)
    for s, e in spans:
        for i in range(s, e):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


@dataclass
class Context:
    run: Dict[str, Any]
    sections: List[Dict[str, Any]]
    results: List[Dict[str, Any]]
    comparisons: Comparisons
    dates: Set[tuple]
    tolerance: float = 1e-9


def build_context(run: Dict[str, Any], sections: Optional[List[str]] = None,
                  previous: Optional[Dict[str, Any]] = None) -> Context:
    secs = [s for s in run.get("sections") or [] if isinstance(s, dict)]
    if not sections:
        secs = [s for s in secs if s.get("status") != "pending_narration"]
    if sections:
        known = {s.get("id") for s in secs}
        missing = [s for s in sections if s not in known]
        if missing:
            raise ValueError(f"the run has no section {', '.join(missing)}; it has "
                             f"{', '.join(str(k) for k in known if k) or 'none'}")
        secs = [s for s in secs if s.get("id") in set(sections)]
    results = [{"id": str(s.get("id") or i), "ok": True, "data": _section_data(s), "preview": ""}
               for i, s in enumerate(secs)]
    results.append({"id": "parameters", "ok": True, "data": run.get("parameters") or {}, "preview": ""})
    cmp = comparisons_workspace(run, previous, [s.get("id") for s in secs] if sections else None)
    return Context(run, secs, results, cmp, allowed_dates(run, secs))


def _pool(ctx: Context) -> List[float]:
    from sajha.ai.planners_engine.checks import _result_numbers
    return _result_numbers(ctx.results)


def _eq(d: float, dec: int, r: float) -> bool:
    try:
        return round(abs(r), dec) == round(abs(d), dec)
    except (OverflowError, ValueError):
        return False


def _precise(f: Dict[str, Any], pool: List[float], figures: List[tuple]) -> bool:
    """The reports rule on top of the validator: a figure matches at the precision written, by
    magnitude (the sign is in the words: "fell 3.2%"). A figure written with a rate unit matches a
    quantity in that unit, or (in percent) a tool-result number known to be in percent or any one as a
    fraction; a bare figure matches a number of the data or a quantity in its own unit (Reports §5)."""
    from sajha.ai.planners_engine.checks import _own_unit_figures
    n, tag = f["n"], f["tag"]
    dec, v, mant = n["decimals"], n["value"], n["mantissa"]
    if n["pct"] or tag == "percent":
        return (any(_eq(mant, dec, r) for r in getattr(pool, "percent", []))
                or any(_eq(mant / 100.0, dec + 2, r) for r in pool)
                or any(u.kind == "percent" and _eq(mant, dec, r) for r, u, _ in figures))
    if tag:
        return any(u.kind == tag and _eq(mant, dec, r) for r, u, _ in figures)
    cands = [(v, 1.0)] + ([(mant, v / mant)] if n["scaled"] and mant else [])
    values = list(pool) + [r for r, _u, _ in _own_unit_figures(figures)]
    return any(_eq(d, dec, r / scale) for d, scale in cands for r in values)


def check_commentary(text: str, ctx: Context) -> List[Dict[str, Any]]:
    """The commentary's figures and dates that the run does not support:
    [{kind: number|date, raw, start, end}] in text order."""
    from sajha.ai.planners_engine.checks import (CheckContext, _figures, _in_results, _in_workspace, _named_unit,
                                                 _unit_tag, _UNIT_TAG)
    text = text or ""
    bad: List[Dict[str, Any]] = []
    dates = find_dates(text)
    for d in dates:
        if not any(k in ctx.dates for k in d["keys"]):
            bad.append({"kind": "date", "raw": d["raw"], "start": d["start"], "end": d["end"]})
    spans = [(d["start"], d["end"]) for d in dates]
    spans += [m.span() for m in _SECTION_REF.finditer(text)] + [m.span() for m in _ORDINAL.finditer(text)]
    masked = _mask(text, spans)
    settings = {"tolerance": ctx.tolerance}
    cctx = CheckContext(draft=masked, draft_json=None, citations=[], question="", results=ctx.results,
                        output_schema=None, lookup=lambda r: None, evaluate=lambda e: True,
                        workspace=ctx.comparisons.workspace)
    pool = _pool(ctx)
    figures = ctx.comparisons.workspace.figures()
    for n in _figures(cctx, settings):
        tag = _unit_tag(masked, n)
        if (_in_results(n, pool, ctx.tolerance, tag)
                or (figures and _in_workspace(n, tag, figures, ctx.tolerance, masked))):
            continue
        if _precise({"n": n, "tag": tag or _named_unit(masked, n)}, pool, figures):
            continue
        end = n["end"]
        if tag in ("bp", "pp", "percent") and not n["pct"]:
            m = _UNIT_TAG.match(masked, end)
            end = m.end() if m else end
        bad.append({"kind": "number", "raw": text[n["start"]:end].strip(), "start": n["start"], "end": end})
    bad.sort(key=lambda f: f["start"])
    return bad


def remove_figures(text: str, figures: List[Dict[str, Any]]) -> str:
    for f in sorted(figures, key=lambda f: f["start"], reverse=True):
        text = text[:f["start"]] + REMOVED + text[f["end"]:]
    return text


def _names(figures: List[Dict[str, Any]]) -> str:
    return ", ".join(dict.fromkeys(f["raw"] for f in figures))


# ── the model call ───────────────────────────────────────────────

def _gateway():
    from sajha.ai.llm import build_llm_factory, llm_factory, set_llm_factory
    gw = llm_factory()
    if gw is None:
        gw = build_llm_factory()
        set_llm_factory(gw)
    return gw


def _request_context(caller: Any):
    from sajha.ai.llm import RequestContext
    ctx = RequestContext(user_id=str(getattr(caller, "user_id", "") or ""),
                         roles=list(getattr(caller, "roles", None) or []),
                         is_admin=bool(getattr(caller, "is_admin", False)), can_use_tool=lambda name: False)
    try:
        from sajha.observability import tracing
        ctx.trace_id = tracing.current_trace_id() or ""
    except Exception:
        pass
    return ctx


def _data_text(ctx: Context) -> str:
    payload = {"report": ctx.run.get("report"), "title": ctx.run.get("title"),
               "parameters": ctx.run.get("parameters") or {},
               "run_date": str(ctx.run.get("started_at") or ctx.run.get("created_at") or ""),
               "sections": [_section_data(s) for s in ctx.sections]}
    text = json.dumps(payload, default=str, separators=(",", ":"))
    if len(text) > MAX_DATA_CHARS:
        text = text[:MAX_DATA_CHARS] + " ...(truncated)"
    lines = ctx.comparisons.lines()
    if lines:
        text += "\n\nComparisons the report computed:\n" + "\n".join(f"- {line}" for line in lines)
    return text


def _ask(gw, alias: str, rctx, messages) -> Tuple[str, str]:
    from sajha.ai.llm import LLMError
    try:
        resp = gw.model(alias, context=rctx).chat_completions_create(messages=messages, temperature=0.0,
                                                                     max_completion_tokens=1500)
    except LLMError as e:
        raise RuntimeError(f"the narration model ({alias}) is not available: {e}")
    if getattr(resp, "refusal", None):
        raise RuntimeError(f"the narration model declined: {resp.refusal}")
    model = resp.sajha.qualified_model if getattr(resp, "sajha", None) else getattr(resp, "model", alias)
    return (resp.text or "").strip(), model or alias


def _pending(run: Dict[str, Any], sections: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    """The text section this narration fills: with no ``sections``, the first one waiting for
    commentary; else the first waiting one whose ``narrate.sections`` are those sections."""
    for s in run.get("sections") or []:
        if not isinstance(s, dict) or s.get("status") != "pending_narration":
            continue
        spec = s.get("narrate") if isinstance(s.get("narrate"), dict) else {}
        if not sections or set(spec.get("sections") or []) == set(sections):
            return s
    return None


def narrate(run_id: str, sections: Optional[List[str]] = None, length: Optional[str] = None, audience: str = "",
            caller: Any = None, source: Optional[RunSource] = None, gateway: Any = None,
            alias: Optional[str] = None) -> Dict[str, Any]:
    """Commentary over run ``run_id`` that passed the numbers check (Reports §5). When the run has a
    text section waiting for this commentary (``narrate:`` in the definition), the commentary is
    stored in it and the run's files are rendered again."""
    from sajha.ai.llm import ChatMessage
    if caller is None:
        from sajha.observability.caller import current
        caller = current()
    if length is not None and length not in LENGTHS:
        raise ValueError(f"length must be one of {', '.join(LENGTHS)}, not {length!r}")
    src = source or default_source()
    try:
        run = src.load(str(run_id), caller)
    except KeyError:
        raise ValueError(f"there is no report run {run_id!r}")
    target = _pending(run, sections)
    spec = (target or {}).get("narrate") or {}
    if not sections and spec.get("sections"):
        sections = list(spec["sections"])
    length = length or (spec.get("length") if spec.get("length") in LENGTHS else None) or "short"
    audience = audience or str(spec.get("audience") or "")
    try:
        previous = None if run.get("quantities") or run.get("comparisons") else src.previous(run, caller)
    except Exception as e:
        logger.debug(f"report_narrate: previous run of {run_id}: {e}")
        previous = None
    ctx = build_context(run, sections, previous)
    if not ctx.sections:
        raise ValueError(f"run {run_id} has no sections to narrate")
    gw = gateway or _gateway()
    alias = alias or narrate_model()
    rctx = _request_context(caller)
    ask = (f"Report data:\n{_data_text(ctx)}\n\nWrite about {LENGTHS[length]} words of commentary for "
           f"{audience.strip() or 'a general business reader'}.")
    messages = [ChatMessage.system(SYSTEM_PROMPT), ChatMessage.user(ask)]
    draft, model = _ask(gw, alias, rctx, messages)
    bad = check_commentary(draft, ctx)
    first = list(bad)
    revised = False
    if bad:
        revised = True
        revise = (f"{REVISE_PROMPT}\n\nDraft:\n{draft}\n\nNot in the report:\n"
                  + "\n".join(f"- {f['raw']}" for f in bad))
        draft, model = _ask(gw, alias, rctx, messages + [ChatMessage.user(revise)])
        bad = check_commentary(draft, ctx)
    caveats = []
    text = draft
    if bad:
        text = remove_figures(draft, bad)
        caveats.append(f"{len(bad)} figure{'s' if len(bad) != 1 else ''} could not be traced to this run's data "
                       f"and {'were' if len(bad) != 1 else 'was'} removed: {_names(bad)}.")
    if first:
        _audit(run, caller, model, first, bad, revised)
    out = {"run_id": str(run.get("run_id") or run_id), "report": run.get("report"),
           "sections": [s.get("id") for s in ctx.sections], "length": length, "audience": audience or None,
           "model": model, "commentary": text, "label": LABEL, "revised": revised,
           "rejected": [{"kind": f["kind"], "raw": f["raw"]} for f in first],
           "removed": [{"kind": f["kind"], "raw": f["raw"]} for f in bad], "caveats": caveats,
           "comparisons": len(ctx.comparisons.labels), "stored_in": None}
    warning = (f"report_narrate: commentary had {len(bad)} figure(s) not in the report, removed: {_names(bad)}"
               if bad else None)
    try:
        if target is not None and text.strip():
            if src.store(run, str(target.get("id")), out, warning):
                out["stored_in"] = target.get("id")
        elif warning:
            src.warn(run, warning)
    except Exception as e:
        logger.warning(f"report_narrate: could not record the commentary on run {run_id}: {e}")
    return out


def _audit(run, caller, model, first, still, revised) -> None:
    try:
        from sajha import audit
        audit.record("report.narrate.rejected", actor={"user": getattr(caller, "user_id", "") or "anonymous"},
                     resource={"type": "report_run", "name": str(run.get("run_id") or ""),
                               "report": run.get("report")},
                     outcome="removed" if still else "revised",
                     details={"model": model, "rejected": [f["raw"] for f in first][:50],
                              "removed": [f["raw"] for f in still][:50], "revised": revised})
    except Exception as e:
        logger.debug(f"report_narrate audit: {e}")
