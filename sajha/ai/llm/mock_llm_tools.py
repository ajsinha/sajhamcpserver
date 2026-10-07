"""
SAJHA Intelligence Layer — the mock's replies for LLM-tool modes (offline, deterministic).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

An LLM tool (sajha/ai/llm_tools) marks its model calls with ``metadata.sajha_llm_mode``; the
``mock-planner`` model then answers in the shape that mode needs, so every shipped LLM tool,
test and eval runs with no key (docs/architecture/LLM Tools.md §17):

    complete   an extractive summary: the first sentences of the text after the instruction
    extract    the output schema's fields from "<field>: value" lines, numbers and enums in the text
    classify   the enum label whose words best overlap the text (ties: the first label)
    judge      per-criterion scores: the maximum when the criterion's words appear in the text,
               the midpoint otherwise
    grounded   the first sentence of passage [1], cited as [1]; "Not found in the sources." when
               the message carries no passage
    narrate    one sentence per top-level field of the data block

A test that needs other replies (a refusal, invalid JSON for the retry) uses ``mock-scripted``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

_SENT = re.compile(r"(?<=[.!?])\s+")
_WORDS = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _words(text: str) -> set:
    from sajha.ai.llm.mock import _stem
    return {_stem(w.lower()) for w in _WORDS.findall(text or "")}


def _first_sentences(text: str, n: int) -> str:
    parts = [p.strip() for p in _SENT.split(" ".join((text or "").split())) if p.strip()]
    return " ".join(parts[:n])


def _body(text: str) -> str:
    """The text after the instruction: everything after the first blank line, else all of it."""
    chunks = re.split(r"\n\s*\n", (text or "").strip(), maxsplit=1)
    return chunks[1] if len(chunks) == 2 and chunks[1].strip() else chunks[0]


def complete(user: str) -> str:
    m = re.search(r"at most (\d+) sentences?", user or "", re.I)
    n = int(m.group(1)) if m else 2
    return _first_sentences(_body(user), max(1, n)) or "(nothing to summarise)"


def _default_of(ps: Dict[str, Any]) -> Any:
    t = ps.get("type")
    t = next((x for x in t if x != "null"), None) if isinstance(t, list) else t
    return {"string": "", "number": 0, "integer": 0, "boolean": False, "array": [], "object": {}}.get(t, "")


def extract(user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    from sajha.ai.llm.mock import fill_arguments
    props = (schema or {}).get("properties") or {}
    text = _body(user)
    out: Dict[str, Any] = {}
    for name, ps in props.items():
        if not isinstance(ps, dict):
            continue
        label = re.escape(name).replace("_", "[ _]")
        m = re.search(rf"(?im)\b{label}\s*[:=]\s*(.+?)\s*$", text)
        if m and ps.get("type") in ("string", None) and "enum" not in ps:
            out[name] = m.group(1)
    filled = fill_arguments({"properties": {k: v for k, v in props.items() if k not in out},
                             "required": [k for k in schema.get("required") or [] if k not in out]}, text)
    for k, v in filled.items():
        ps = props.get(k) or {}
        if ps.get("type") == "string" and "enum" not in ps and v == text:
            continue                      # fill_arguments' whole-text fallback is no extraction
        out[k] = v
    for k in schema.get("required") or []:
        if k not in out:
            out[k] = _default_of(props.get(k) or {})
    return {k: out[k] for k in props if k in out}


def classify(user: str, schema: Dict[str, Any], system: str = "") -> Dict[str, Any]:
    props = (schema or {}).get("properties") or {}
    labels = [str(x) for x in ((props.get("label") or {}).get("enum") or [])]
    words = _words(_body(user))
    best, score = (labels[0] if labels else ""), 0
    for lab in labels:
        m = re.search(rf"(?:^|[\s.;]){re.escape(lab)}\s*:\s*([^\n.]+)", system or "", re.I)
        terms = _words(lab.replace("_", " ").replace("-", " ")) | (_words(m.group(1)) if m else set())
        s = len(terms & words)
        if s > score:
            best, score = lab, s
    out: Dict[str, Any] = {"label": best}
    if "reason" in props:
        out["reason"] = f"the text mentions {best.replace('_', ' ')}" if score else "no label word in the text"
    if "confidence" in props:
        out["confidence"] = 0.9 if score else 0.5
    return out


def judge(user: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    props = (schema or {}).get("properties") or {}
    scores = ((props.get("scores") or {}).get("properties") or {})
    words = _words(_body(user))
    out: Dict[str, Any] = {"scores": {}}
    for name, ps in scores.items():
        lo, hi = int(ps.get("minimum", 1)), int(ps.get("maximum", 5))
        out["scores"][name] = hi if _words(name.replace("_", " ")) & words else (lo + hi) // 2
    if "reasons" in props:
        out["reasons"] = {n: "mentioned" if out["scores"][n] == int(ps.get("maximum", 5)) else "not mentioned"
                          for n, ps in scores.items()}
    if "summary" in props:
        out["summary"] = "Scored by the mock judge from the words in the text."
    return out


def grounded(user: str) -> Dict[str, Any]:
    m = re.search(r"^\[1\][^\n]*\n(.+?)(?:\n\[\d+\]|\n\s*\n|\Z)", user or "", re.S | re.M)
    if not m:
        return {"answer": "Not found in the sources.", "citations": []}
    first = _first_sentences(m.group(1), 1)
    return {"answer": f"{first} [1]", "citations": [1]}


def narrate(user: str) -> str:
    m = re.search(r"Data \(JSON[^\n]*\n(.+)\Z", user or "", re.S)
    try:
        data = json.loads(m.group(1)) if m else None
    except Exception:
        data = None
    if isinstance(data, dict):
        lines = []
        for k, v in list(data.items())[:8]:
            if isinstance(v, (dict, list)):
                v = json.dumps(v, default=str)[:80]
            lines.append(f"{k.replace('_', ' ')} is {v}.")
        return " ".join(lines) or "The data is empty."
    return "The data could not be read."


def reply(mode: str, user: str, schema: Optional[Dict[str, Any]], system: str = "") -> Optional[str]:
    """The reply text for an LLM-tool call in ``mode``; None when the mode is not one of these."""
    if mode == "complete":
        return complete(user)
    if mode == "narrate":
        return narrate(user)
    if mode == "extract":
        return json.dumps(extract(user, schema or {}))
    if mode == "classify":
        return json.dumps(classify(user, schema or {}, system))
    if mode == "judge":
        return json.dumps(judge(user, schema or {}))
    if mode == "grounded":
        return json.dumps(grounded(user))
    return None


def system_text(messages: List[Any]) -> str:
    return "\n".join(m.text or "" for m in messages if getattr(m, "role", "") in ("system", "developer"))


def last_user(messages: List[Any]) -> str:
    for m in reversed(messages):
        if getattr(m, "role", "") == "user":
            return m.text or ""
    return ""
