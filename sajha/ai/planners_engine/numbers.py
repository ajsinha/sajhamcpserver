"""
SAJHA MCP Server — the reserved planner setting ``numbers_check`` (Quantitative Planners §2.5).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every planner accepts ``numbers_check: off | warn | enforce`` (default ``ai.planners.numbers_check``).
After the planner's answer the service (sajha/ai/intelligence.py) runs the numbers validator:
``numbers_in_workspace`` when the run has a quantitative workspace, else ``numbers_in_results``.

- ``warn``: one caveat names every unmatched figure.
- ``enforce``: one revision of the answer naming the unmatched figures; a figure still unmatched is
  removed from the answer, with a caveat that says so.

This module holds the parts that are not model calls: the mode, the results in the shape the
checks read, finding the unmatched figures and removing them. The one revision call is the
service's.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sajha.ai.planners_engine.checks import (CheckContext, _figures, _in_results, _in_workspace, _result_numbers,
                                             _unit_tag, _UNIT_TAG)
from sajha.ai.planners_engine.model import NUMBERS_CHECK_MODES

logger = logging.getLogger(__name__)

REMOVED = "[unverified figure removed]"
REVISE_PROMPT = ("Some figures in the draft answer do not match any tool result or computed quantity. Rewrite the "
                 "answer so that every figure is one that appears in the tool results above (or was computed from "
                 "them by SAJHA); correct or remove each figure listed, and change nothing else. Reply with JSON "
                 "matching the schema.")


def mode_for(settings: Optional[Dict[str, Any]], default: Optional[str] = None) -> str:
    """The run's ``numbers_check``: the planner's setting, else ``default`` (``ai.planners.numbers_check``)."""
    value = (settings or {}).get("numbers_check")
    if value is False:                          # YAML reads a bare ``off`` as false
        value = "off"
    if value is None:
        if default is None:
            try:
                from sajha.ai.planners_engine import get_registry
                default = get_registry().settings.numbers_check
            except Exception:
                default = "off"
        value = default
    if value not in NUMBERS_CHECK_MODES:
        logger.warning(f"numbers_check {value!r} is not one of {', '.join(NUMBERS_CHECK_MODES)}; using off")
        return "off"
    return value


def results_from_messages(steps: List[Any], tool_messages: Dict[str, Any],
                          raw: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The ask's results as the checks read them (``{id, ok, data, preview}``), from its steps and
    tool messages; ``raw`` (call id -> uncapped output) wins where present."""
    out = []
    for st in steps:
        cid = getattr(st, "id", "")
        data: Any = None
        if raw and cid in raw:
            data = raw[cid]
        else:
            msg = tool_messages.get(cid)
            text = getattr(msg, "content", None) if msg is not None else None
            if isinstance(text, str):
                try:
                    data = json.loads(text)
                except ValueError:
                    data = text
        out.append({"id": cid, "ok": bool(getattr(st, "ok", False)), "data": data,
                    "preview": getattr(st, "summary", "")})
    return out


def unmatched(answer: str, question: str, results: List[Dict[str, Any]], workspace: Any = None,
              settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The answer's figures that match no result (and, with a workspace, no quantity): each
    ``{raw, value, start, end, tag}`` with ``end`` past a written rate unit (" bp")."""
    s = dict(settings or {})
    tol = float(s.get("tolerance", 0.005))
    ctx = CheckContext(draft=answer or "", draft_json=None, citations=[], question=question or "",
                       results=results, output_schema=None, lookup=lambda r: None, evaluate=lambda e: True,
                       workspace=workspace)
    pool = _result_numbers(results)
    figures = workspace.figures() if workspace is not None and hasattr(workspace, "figures") else []
    out = []
    for n in _figures(ctx, s):
        tag = _unit_tag(ctx.draft, n)
        if _in_results(n, pool, tol) or (figures and _in_workspace(n, tag, figures, tol)):
            continue
        end = n["end"]
        if tag in ("bp", "pp", "percent") and not n["pct"]:
            m = _UNIT_TAG.match(ctx.draft, end)
            end = m.end() if m else end
        out.append({"raw": ctx.draft[n["start"]:end].strip(), "value": n["value"], "start": n["start"],
                    "end": end, "tag": tag})
    return out


def remove_figures(answer: str, figures: List[Dict[str, Any]]) -> str:
    """``answer`` with each figure's text replaced by a marker (spans from the last to the first)."""
    text = answer
    for f in sorted(figures, key=lambda f: f["start"], reverse=True):
        text = text[:f["start"]] + REMOVED + text[f["end"]:]
    return text


def names(figures: List[Dict[str, Any]], limit: int = 20) -> str:
    shown = list(dict.fromkeys(f["raw"] for f in figures))
    more = len(shown) - limit
    return ", ".join(shown[:limit]) + (f" and {more} more" if more > 0 else "")


def warn_caveat(figures: List[Dict[str, Any]]) -> str:
    return f"These figures could not be traced to a tool result or a computed quantity: {names(figures)}."


def removed_caveat(figures: List[Dict[str, Any]]) -> str:
    return (f"{len(figures)} figure{'s' if len(figures) != 1 else ''} could not be traced to a tool result or a "
            f"computed quantity and {'were' if len(figures) != 1 else 'was'} removed: {names(figures)}.")


def revision_text(question: str, answer: str, figures: List[Dict[str, Any]]) -> str:
    return (f"Question: {question}\n\nDraft answer:\n{answer}\n\nFigures that match no tool result or computed "
            f"quantity:\n" + "\n".join(f"- {f['raw']}" for f in figures))
