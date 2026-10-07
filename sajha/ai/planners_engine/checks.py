"""
SAJHA MCP Server — the deterministic checks of the planner ``verify`` stage.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Planner Reference.md §9. Each check is a pure function of the draft
and the state that returns findings ``{check, message, value}`` (none when it passes). Custom
checks are registered in code with :func:`register_check` and are then usable in planner files
like the built-in ones.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

_NUM = re.compile(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)(\s*%|\s*(?:k|thousand|mn|m|million|bn|billion|tn|trillion)\b)?",
                  re.IGNORECASE)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9,
          "tn": 1e12, "trillion": 1e12}
STOP_WORDS = set("""a about above after again against all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having he
her here hers him his how i if in into is it its itself just me more most my no nor not now of off on once only or
other our out over own same she should so some such than that the their them then there these they this those
through to too under until up very was we were what when where which while who whom why will with would you your
please tell give show find get much many""".split())


@dataclass
class CheckContext:
    draft: str
    draft_json: Any
    citations: List[str]
    question: str
    results: List[Dict[str, Any]]
    output_schema: Optional[Dict[str, Any]]
    lookup: Callable[[str], Any]
    evaluate: Callable[[Any], bool]       # the `expression` check (a compiled expression)


Check = Callable[[CheckContext, Dict[str, Any]], List[Dict[str, Any]]]
_CHECKS: Dict[str, Check] = {}
SETTINGS: Dict[str, Dict[str, Any]] = {}


def register_check(name: str, fn: Optional[Check] = None, settings_schema: Optional[Dict[str, Any]] = None):
    """Register a verify check (decorator or call). ``fn(ctx, settings) -> [finding]``."""
    def deco(f: Check) -> Check:
        _CHECKS[name] = f
        SETTINGS[name] = settings_schema or {"type": "object"}
        return f
    return deco(fn) if fn is not None else deco


def checks() -> Dict[str, Check]:
    return dict(_CHECKS)


def _finding(check: str, message: str, value: Any = None) -> Dict[str, Any]:
    return {"check": check, "message": message[:300], "value": value}


# ── numbers (§9.1) ───────────────────────────────────────────────

def extract_numbers(text: str) -> List[Dict[str, Any]]:
    """Numbers in ``text``: [{value, mantissa, pct, decimals, raw, start}]."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(1)
        try:
            mant = float(raw.replace(",", ""))
        except ValueError:
            continue
        suffix = (m.group(2) or "").strip().lower()
        pct = suffix == "%"
        scale = _SCALE.get(suffix, 1.0) if suffix and not pct else 1.0
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        out.append({"value": mant * scale, "mantissa": mant, "pct": pct, "scaled": scale != 1.0,
                    "decimals": decimals, "raw": m.group(0).strip(), "start": m.start()})
    return out


def _result_numbers(results: List[Dict[str, Any]]) -> List[float]:
    nums: List[float] = []

    def walk(v: Any):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            nums.append(float(v))
        elif isinstance(v, str):
            nums.extend(n["value"] for n in extract_numbers(v))
            nums.extend(n["mantissa"] for n in extract_numbers(v) if n["scaled"])
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    for r in results:
        if not r.get("ok"):
            continue
        walk(r.get("data") if r.get("data") is not None else r.get("preview"))
    return nums


def _matches(d: float, decimals: int, r: float, tol: float) -> bool:
    if abs(d - r) <= tol * max(abs(d), abs(r)):
        return True
    try:
        return round(r, decimals) == d
    except (OverflowError, ValueError):
        return False


@register_check("numbers_in_results")
def numbers_in_results(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    tol = float(s.get("tolerance", 0.005))
    ignore = set(s.get("ignore") or ["question", "years", "ordinals", "small_integers"])
    limit = int(s.get("max_numbers", 200))
    q_nums = {n["value"] for n in extract_numbers(ctx.question)} if "question" in ignore else set()
    pool = _result_numbers(ctx.results)
    out = []
    checked = 0
    for n in extract_numbers(ctx.draft):
        v = n["value"]
        is_int = float(v).is_integer() and n["decimals"] == 0 and not n["scaled"] and not n["pct"]
        if "question" in ignore and (v in q_nums or n["mantissa"] in q_nums):
            continue
        if "years" in ignore and is_int and 1900 <= v <= 2100:
            continue
        if "small_integers" in ignore and is_int and 0 <= v <= 10:
            continue
        if "ordinals" in ignore:
            line_start = ctx.draft.rfind("\n", 0, n["start"]) + 1
            if ctx.draft[line_start:n["start"]].strip() == "" and re.match(r"\d+[.)]", ctx.draft[n["start"]:]):
                continue
        checked += 1
        if checked > limit:
            break
        cands = [(v, n["decimals"])]
        if n["pct"]:
            cands.append((v / 100.0, n["decimals"] + 2))
        if n["scaled"]:
            cands.append((n["mantissa"], n["decimals"]))
        if not any(_matches(d, dec, r, tol) for d, dec in cands for r in pool):
            shown = int(v) if float(v).is_integer() else v
            out.append(_finding("numbers_in_results", f"{n['raw']} does not appear in any tool result", shown))
    return out


# ── citations (§9.2) ─────────────────────────────────────────────

@register_check("citations_present")
def citations_present(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    ok_ids = {r["id"] for r in ctx.results if r.get("ok")}
    out = []
    if ok_ids:
        if not ctx.citations:
            out.append(_finding("citations_present", "the answer cites no tool result"))
        bad = [c for c in ctx.citations if c not in ok_ids]
        for c in bad:
            out.append(_finding("citations_present", f"citation {c} is not a successful tool result", c))
    if s.get("per") == "paragraph":
        for para in re.split(r"\n\s*\n", ctx.draft or ""):
            if re.search(r"\d", para) and not any(f"[{i}]" in para for i in ok_ids):
                out.append(_finding("citations_present", f"no citation in: {para[:120]}", para[:200]))
    return out


@register_check("no_failed_citations")
def no_failed_citations(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    bad_ids = {r["id"] for r in ctx.results if not r.get("ok")}
    return [_finding("no_failed_citations", f"citation {c} names a failed, refused or skipped call", c)
            for c in ctx.citations if c in bad_ids]


# ── parts answered (§9.3) ────────────────────────────────────────

def question_parts(question: str) -> List[str]:
    parts = [p.strip() for p in re.findall(r"[^?.!\n]*\?", question or "") if p.strip()]
    for line in (question or "").splitlines():
        m = re.match(r"\s*(?:\d+[.)]|[a-z]\)|[-*])\s+(.*)", line)
        if m:
            parts.append(m.group(1).strip())
    return list(dict.fromkeys(parts))


def content_words(text: str) -> List[str]:
    out = []
    for w in re.findall(r"[A-Za-z]{3,}", (text or "").lower()):
        if w in STOP_WORDS:
            continue
        out.append(w[:-1] if w.endswith("s") and len(w) > 3 else w)
    return list(dict.fromkeys(out))


@register_check("parts_answered")
def parts_answered(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    parts = question_parts(ctx.question)
    if len(parts) < 2:
        return []
    need = float(s.get("min_overlap", 0.5))
    low = (ctx.draft or "").lower()
    out = []
    for p in parts:
        words = content_words(p)
        if not words:
            continue
        hit = sum(1 for w in words if w in low)
        if hit / len(words) < need:
            out.append(_finding("parts_answered", f"no answer to: {p}", p))
    return out


# ── the rest (§9.4, §9.5) ────────────────────────────────────────

@register_check("schema_valid")
def schema_valid(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    schema = s.get("schema", "output")
    if schema == "output":
        schema = ctx.output_schema
    if not isinstance(schema, dict):
        return [_finding("schema_valid", "no schema to validate against")]
    ref = s.get("from")
    value = ctx.lookup(ref) if ref else ctx.draft_json
    if value is None:
        return [_finding("schema_valid", "there is no structured draft to validate")]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [_finding("schema_valid", "the value is not JSON")]
    import jsonschema
    errs = list(jsonschema.Draft202012Validator(schema).iter_errors(value))
    return [_finding("schema_valid", f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}",
                     "/".join(str(p) for p in e.absolute_path)) for e in errs[:20]]


@register_check("results_present")
def results_present(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    need = int(s.get("min", 1))
    have = sum(1 for r in ctx.results if r.get("ok"))
    return [] if have >= need else [_finding("results_present", f"{have} successful results; at least {need} needed",
                                             have)]


@register_check("length")
def length(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    n = len(ctx.draft or "")
    lo, hi = s.get("min_chars"), s.get("max_chars")
    if lo is not None and n < lo:
        return [_finding("length", f"the answer has {n} characters; at least {lo} needed", n)]
    if hi is not None and n > hi:
        return [_finding("length", f"the answer has {n} characters; at most {hi} allowed", n)]
    return []


@register_check("contains")
def contains(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [_finding("contains", f"the answer does not match {p}", p) for p in s.get("patterns") or []
            if not re.search(p, ctx.draft or "", re.IGNORECASE)]


@register_check("not_contains")
def not_contains(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [_finding("not_contains", f"the answer matches {p}", p) for p in s.get("patterns") or []
            if re.search(p, ctx.draft or "", re.IGNORECASE)]


@register_check("expression")
def expression(ctx: CheckContext, s: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        ok = ctx.evaluate(s.get("_compiled"))
    except Exception as e:
        return [_finding("expression", str(e))]
    return [] if ok else [_finding("expression", s.get("message") or f"{s.get('expr')} is false")]
