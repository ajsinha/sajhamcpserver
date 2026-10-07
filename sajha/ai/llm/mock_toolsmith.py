"""
SAJHA Intelligence Layer — ``mock-toolsmith``, the mock provider's tool designer.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Answers the "describe a tool" request (sajha/studio/describe.py) with no network and no
keys, deterministically, so Studio's "Describe a tool" page, the CLI and the tests work out
of the box. Like every mock model it reads only the request: the description block and
the context block the generator sends (existing tools, the databases SAJHA can query).

It recognises a few shapes and otherwise writes an honest skeleton:

    a URL that looks like an OpenAPI / Swagger spec  -> kind openapi (hand-off to API Import)
    any other URL                                     -> kind rest (path params from {braces})
    "table X" / a table the context lists            -> kind dbquery ("by <column>" filters)
    two or more existing tools named, or "combine"    -> kind composite (sibling)
    a treasury / FRED series and "change over N days" -> kind python (FRED CSV, sandboxed)
    mean / median / standard deviation of numbers     -> kind python (statistics module)
    summarise / classify into ... / extract ... from  -> kind llm (an LLM tool: complete, classify,
    / answer questions using <tools> / from the docs     extract, answer or grounded mode)
    anything else                                     -> kind python skeleton, with a note

A real model behind the ``toolsmith`` alias does the same job from the same prompt.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

DESC_RE = re.compile(r"<<<DESCRIPTION ([0-9a-f]{8,})\n(.*?)\nDESCRIPTION \1>>>", re.S)
CONTEXT_RE = re.compile(r"<<<CONTEXT\n(.*?)\nCONTEXT>>>", re.S)
KIND_RE = re.compile(r"^Preferred kind: (\w+)$", re.M)
_URL = re.compile(r"https?://[^\s\"'<>`]+")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_STOP = {"the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "at", "by", "with", "me", "my", "get",
         "fetch", "return", "returns", "give", "show", "find", "list", "tool", "that", "this", "it", "its", "from",
         "over", "into", "as", "is", "are", "be", "wrap", "make", "build", "create", "call", "please", "using",
         "endpoint", "rest", "api", "query", "table", "data", "value", "values", "which", "what", "each", "all",
         "one", "new", "like", "use", "uses", "then", "also", "both", "combine", "together"}

FRED_SERIES = [  # (pattern, series id, short name)
    (r"\b(3|three)[- ]?(month|mo)\b", "DGS3MO", "3m"),
    (r"\b(2|two)[- ]?(year|yr|y)\b", "DGS2", "2y"),
    (r"\b(5|five)[- ]?(year|yr|y)\b", "DGS5", "5y"),
    (r"\b(30|thirty)[- ]?(year|yr|y)\b", "DGS30", "30y"),
    (r"\b(10|ten)[- ]?(year|yr|y)\b", "DGS10", "10y"),
]

FRED_CODE = '''from sajha.studio import sajhamcptool


@sajhamcptool(description=__DESC__, category="Fixed Income", tags=["fred", "treasury", "described"])
def __FUNC__(days: int = __DAYS__, series_id: str = "__SERIES__") -> dict:
    """The latest value of a FRED daily series and its change over the last `days` days."""
    import csv
    import datetime
    import io
    import re
    import urllib.request

    if not 1 <= int(days) <= 365:
        raise ValueError("days must be between 1 and 365")
    if not re.fullmatch(r"[A-Z0-9]{2,20}", series_id or ""):
        raise ValueError("series_id must be a FRED series id such as DGS10")
    start = (datetime.date.today() - datetime.timedelta(days=int(days) + 14)).isoformat()
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series_id + "&cosd=" + start
    with urllib.request.urlopen(url, timeout=20) as resp:
        text = resp.read().decode("utf-8")
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            rows.append((datetime.date.fromisoformat(row[0]), float(row[1])))
        except ValueError:
            continue                       # the header row
    if not rows:
        raise ValueError("FRED returned no observations for " + series_id)
    latest_date, latest = rows[-1]
    cutoff = latest_date - datetime.timedelta(days=int(days))
    past = [r for r in rows if r[0] <= cutoff] or rows[:1]
    past_date, past_value = past[-1]
    change = round(latest - past_value, 4)
    return {
        "series_id": series_id,
        "latest_date": latest_date.isoformat(),
        "latest_value": latest,
        "past_date": past_date.isoformat(),
        "past_value": past_value,
        "days": int(days),
        "change": change,
        "change_bps": round(change * 100, 1),
    }
'''

STATS_CODE = '''from sajha.studio import sajhamcptool


@sajhamcptool(description=__DESC__, category="Statistics", tags=["statistics", "described"])
def __FUNC__(values: list) -> dict:
    """Summary statistics of a list of numbers."""
    import statistics

    nums = [float(v) for v in (values or [])]
    if not nums:
        raise ValueError("values must contain at least one number")
    out = {"count": len(nums), "mean": statistics.fmean(nums), "median": statistics.median(nums),
           "min": min(nums), "max": max(nums)}
    out["stdev"] = statistics.stdev(nums) if len(nums) > 1 else 0.0
    return out
'''

SKELETON_CODE = '''from sajha.studio import sajhamcptool


@sajhamcptool(description=__DESC__, category="Described", tags=["described", "skeleton"])
def __FUNC__(text: str) -> dict:
    """A skeleton: replace this body with the real logic before you deploy."""
    if not text:
        raise ValueError("text is required")
    return {"input": text, "status": "skeleton", "note": "edit this tool's code before relying on it"}
'''


def parse_request(user_text: str) -> Tuple[str, Dict[str, Any], str]:
    """(description, context, preferred kind) from the generator's prompt."""
    m = DESC_RE.search(user_text or "")
    desc = m.group(2).strip() if m else (user_text or "").strip()
    ctx: Dict[str, Any] = {}
    c = CONTEXT_RE.search(user_text or "")
    if c:
        try:
            ctx = json.loads(c.group(1))
        except ValueError:
            ctx = {}
    k = KIND_RE.search(user_text or "")
    return desc, ctx if isinstance(ctx, dict) else {}, (k.group(1).lower() if k else "auto")


def _slug(words: List[str], limit: int = 5) -> str:
    out = [w.lower() for w in words if w.lower() not in _STOP and len(w) > 1][:limit]
    s = "_".join(out) or "described_tool"
    s = re.sub(r"[^a-z0-9_]", "", s)
    if not s or not s[0].isalpha():
        s = "tool_" + s
    return s[:48].rstrip("_")


def _first_sentence(text: str, limit: int = 200) -> str:
    s = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _sub(code: str, **kw) -> str:
    for k, v in kw.items():
        code = code.replace(f"__{k.upper()}__", str(v))
    return code


# ── recipes ──────────────────────────────────────────────────────

def _openapi(desc: str, url: str) -> Dict[str, Any]:
    host = (urlsplit(url).hostname or "api").split(".")
    base = host[-2] if len(host) >= 2 else host[0]
    prefix = re.sub(r"[^a-z0-9_]", "", base.lower())[:24] or "api"
    if not prefix[0].isalpha():
        prefix = "api_" + prefix
    return {
        "kind": "openapi", "name": prefix,
        "description": f"Operations of the API described at {url}",
        "category": "Imported API",
        "input_schema": {"type": "object", "properties": {}}, "output_schema": {"type": "object"},
        "implementation": {"url": url, "prefix": prefix},
        "tests": [{"name": "the spec parses and lists operations", "arguments": {}, "live": True,
                   "expect": {"ok": True}}],
        "notes": ["API Import turns each operation into its own tool; choose the operations there."],
    }


def _rest(desc: str, url: str) -> Dict[str, Any]:
    method = next((m for m in ("POST", "PUT", "PATCH", "DELETE") if re.search(rf"\b{m}\b", desc)), "GET")
    url = url.rstrip(".,;:)")
    parts = urlsplit(url)
    path_params = re.findall(r"\{(\w+)\}", parts.path)
    segs = [s for s in parts.path.split("/") if s and not s.startswith("{") and not re.fullmatch(r"v\d+", s)]
    host = (parts.hostname or "api").split(".")
    base = host[-2] if len(host) >= 2 else host[0]
    name = _slug([base] + re.findall(r"[A-Za-z]+", " ".join(segs[-2:])), 4)
    props = {p: {"type": "string", "description": f"the {p.replace('_', ' ')} path segment"} for p in path_params}
    sample = {p: "sample" for p in path_params}
    tests = [
        {"name": "a JSON reply is returned as data", "arguments": sample,
         "fixture": {"status": 200, "json": {"ok": True, "items": [1, 2, 3]}},
         "expect": {"ok": True, "keys": ["data", "status_code"]}},
        {"name": "an HTTP error is reported, not raised", "arguments": sample,
         "fixture": {"status": 503, "text": "unavailable"}, "expect": {"ok": False}},
        {"name": "the live endpoint answers", "arguments": sample, "live": True, "expect": {"ok": True}},
    ]
    return {
        "kind": "rest", "name": name,
        "description": f"{method} {url}: {_first_sentence(desc, 160)}",
        "category": "REST API",
        "input_schema": {"type": "object", "properties": props, "required": list(path_params)},
        "output_schema": {"type": "object"},
        "implementation": {"endpoint": url, "method": method, "response_format": "json", "timeout": 30,
                           "headers": {}},
        "tests": tests,
        "notes": ["Credentials are never generated; add an API key or basic auth in the REST creator if needed."],
    }


_PTYPE = {"VARCHAR": "string", "TEXT": "string", "BIGINT": "integer", "INTEGER": "integer", "INT": "integer",
          "SMALLINT": "integer", "DOUBLE": "float", "FLOAT": "float", "REAL": "float", "DECIMAL": "float",
          "DATE": "date", "TIMESTAMP": "datetime", "BOOLEAN": "boolean"}


def _find_table(desc: str, ctx: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    words = {w.lower() for w in _WORD.findall(desc)}
    named = re.search(r"\btable\s+[`\"']?([A-Za-z_][\w]*)", desc, re.I)
    for db in ctx.get("databases") or []:
        tables = db.get("tables") or {}
        if named and named.group(1).lower() in {t.lower() for t in tables}:
            t = next(t for t in tables if t.lower() == named.group(1).lower())
            return db, t
    for db in ctx.get("databases") or []:
        for t in db.get("tables") or {}:
            if t.lower() in words and re.search(r"\b(table|rows?|query|records?|by)\b", desc, re.I):
                return db, t
    if named:
        return None, named.group(1)
    return None, None


def _dbquery(desc: str, db: Optional[Dict[str, Any]], table: str) -> Dict[str, Any]:
    cols = (db or {}).get("tables", {}).get(table) or []
    by_name = {c["name"].lower(): c for c in cols if isinstance(c, dict) and c.get("name")}
    filters: List[Dict[str, Any]] = []
    for m in re.finditer(r"\bby\s+([A-Za-z_][\w ,]*)", desc, re.I):
        phrase = re.split(r"\s+(?:with|for|from|over|where|limit|in|on|or)\b", m.group(1), flags=re.I)[0]
        for raw in re.split(r"\s*(?:,|\band\b)\s*", phrase):
            key = raw.strip().lower().replace(" ", "_")
            col = by_name.get(key) or by_name.get(key.rstrip("s")) or next(
                (c for n, c in by_name.items() if n.endswith("_" + key) or n.startswith(key + "_")), None)
            if col and col not in filters:
                filters.append(col)
    params, where = [], []
    for col in filters:
        ptype = _PTYPE.get(str(col.get("type", "")).upper().split("(")[0], "string")
        params.append({"name": col["name"], "param_type": ptype, "required": True,
                       "description": f"rows whose {col['name'].replace('_', ' ')} equals this value"})
        where.append(f"{col['name']} = {{{{{col['name']}}}}}")
    params.append({"name": "limit", "param_type": "integer", "required": False, "default": 100,
                   "description": "most rows to return"})
    sql = f"SELECT * FROM {table}" + (" WHERE " + " AND ".join(where) if where else "") + " LIMIT {{limit}}"
    sample = {c["name"]: (c.get("examples") or ["sample"])[0] for c in filters}
    tests = [{"name": "a known value returns rows", "arguments": {**sample, "limit": 5},
              "expect": {"ok": True, "keys": ["data", "row_count"]}}]
    if filters:
        tests.append({"name": "an unknown value returns no rows",
                      "arguments": {**{c["name"]: "__no_such_value__" for c in filters}, "limit": 5},
                      "expect": {"ok": True, "equals": {"row_count": 0}}})
    name = _slug([table, "by"] + [c["name"] for c in filters], 4) if filters else _slug([table, "rows"])
    notes = [] if db else [f"table {table} is not in any database SAJHA lists; pick a database before deploying"]
    return {
        "kind": "dbquery", "name": name,
        "description": (f"Rows of {table}" + (" filtered by " + ", ".join(c["name"] for c in filters) if filters
                                              else "") + f". {_first_sentence(desc, 120)}"),
        "category": "Database",
        "input_schema": {"type": "object", "properties": {p["name"]: {"type": p["param_type"]} for p in params}},
        "output_schema": {"type": "object"},
        "implementation": {"db_type": (db or {}).get("db_type", "duckdb"),
                           "connection_string": (db or {}).get("connection_string", ""),
                           "query_template": sql, "parameters": params, "max_rows": 1000},
        "tests": tests, "notes": notes,
    }


def _tool_terms(tool: Dict[str, Any]) -> set:
    words = re.findall(r"[a-z]+", (tool.get("name", "") + " " + tool.get("description", "")).lower().replace("_", " "))
    return {w for w in words if w not in _STOP and len(w) > 2}


def _composite(desc: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tools = [t for t in ctx.get("existing_tools") or [] if isinstance(t, dict) and t.get("name")]
    lower = desc.lower()
    named = [t for t in tools if re.search(rf"\b{re.escape(t['name'].lower())}\b", lower)]
    named.sort(key=lambda t: lower.index(t["name"].lower()))
    picks = named
    if len(picks) < 2 and re.search(r"\b(combine|together|alongside|snapshot|side by side)\b", lower):
        q = {w for w in re.findall(r"[a-z]+", lower) if w not in _STOP and len(w) > 2}
        scored = sorted(((len(q & _tool_terms(t)), i, t) for i, t in enumerate(tools)), key=lambda x: (-x[0], x[1]))
        picks = [t for s, _, t in scored[:3] if s >= 2]
    if len(picks) < 2:
        return None
    master, rest = picks[0], picks[1:4]
    name = _slug(["combined"] + [p["name"].split("_")[-1] for p in picks[:3]], 4)
    return {
        "kind": "composite", "name": name,
        "description": "Runs " + ", ".join(p["name"] for p in picks[:4]) + f" together. {_first_sentence(desc, 120)}",
        "category": "Composite",
        "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
        "implementation": {"arrangement": "sibling", "master_tool": master["name"], "master_output_key": master["name"],
                           "steps": [{"tool_name": t["name"], "output_key": t["name"], "param_mapping": {},
                                      "static_params": {}} for t in rest]},
        "tests": [{"name": "every part answers", "arguments": {}, "live": True, "expect": {"ok": True}}],
        "notes": ["The parts run in parallel with the composite's arguments; map arguments per step if they differ."],
    }


def _fred(desc: str) -> Optional[Dict[str, Any]]:
    low = desc.lower()
    explicit = re.search(r"\b(DGS\d+MO|DGS\d+|T10Y2Y|DFF|SOFR)\b", desc)
    if not (explicit or re.search(r"\b(treasury|yield|fred)\b", low)):
        return None
    series, short = (explicit.group(1), explicit.group(1).lower()) if explicit else ("DGS10", "10y")
    if not explicit:
        for pat, sid, sh in FRED_SERIES:
            if re.search(pat, low):
                series, short = sid, sh
                break
    m = re.search(r"\b(\d{1,3})[- ]?(?:days?|d)\b", low)
    days = int(m.group(1)) if m and 1 <= int(m.group(1)) <= 365 else 30
    func = f"us_treasury_{short}_change" if series.startswith("DGS") else f"fred_{series.lower()}_change"
    text = f"Latest {series} value from FRED and its change over the last {days} days"
    code = _sub(FRED_CODE, desc=json.dumps(text), func=func, days=days, series=series)
    return {
        "kind": "python", "name": func, "description": text, "category": "Fixed Income",
        "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "default": days},
                                                          "series_id": {"type": "string", "default": series}}},
        "output_schema": {"type": "object", "properties": {
            "series_id": {"type": "string"}, "latest_date": {"type": "string"}, "latest_value": {"type": "number"},
            "past_date": {"type": "string"}, "past_value": {"type": "number"}, "days": {"type": "integer"},
            "change": {"type": "number"}, "change_bps": {"type": "number"}},
            "required": ["series_id", "latest_value", "change"]},
        "implementation": {"code": code,
                           "sandbox": {"network": "allowlist", "allow_hosts": ["fred.stlouisfed.org:443"],
                                       "timeout_seconds": 30}},
        "tests": [
            {"name": "rejects a zero-day window", "arguments": {"days": 0},
             "expect": {"ok": False, "error_contains": "days must be between"}},
            {"name": "rejects a malformed series id", "arguments": {"series_id": "not a series"},
             "expect": {"ok": False, "error_contains": "series_id"}},
            {"name": f"fetches {series} and its {days}-day change", "arguments": {"days": days}, "live": True,
             "expect": {"ok": True, "keys": ["latest_value", "change"]}},
        ],
        "notes": ["Uses FRED's public CSV download (no API key); the sandbox allows only fred.stlouisfed.org.",
                  "Yields are in percent; change_bps is the change in basis points."],
    }


def _stats(desc: str) -> Optional[Dict[str, Any]]:
    if not re.search(r"\b(mean|average|median|standard deviation|stdev|std dev|statistics)\b", desc, re.I):
        return None
    text = "Summary statistics (count, mean, median, min, max, standard deviation) of a list of numbers"
    return {
        "kind": "python", "name": "summary_statistics", "description": text, "category": "Statistics",
        "input_schema": {"type": "object", "properties": {"values": {"type": "array", "items": {"type": "number"}}},
                         "required": ["values"]},
        "output_schema": {"type": "object", "properties": {k: {"type": "number"} for k in
                                                           ("count", "mean", "median", "min", "max", "stdev")},
                          "required": ["count", "mean", "median"]},
        "implementation": {"code": _sub(STATS_CODE, desc=json.dumps(text), func="summary_statistics"),
                           "sandbox": {"network": "none"}},
        "tests": [
            {"name": "summarises 1..5", "arguments": {"values": [1, 2, 3, 4, 5]},
             "expect": {"ok": True, "equals": {"count": 5, "mean": 3.0, "median": 3}}},
            {"name": "rejects an empty list", "arguments": {"values": []},
             "expect": {"ok": False, "error_contains": "at least one number"}},
        ],
        "notes": [],
    }


def _skeleton(desc: str) -> Dict[str, Any]:
    name = _slug(_WORD.findall(desc), 4)
    text = _first_sentence(desc, 160) or "A described tool"
    return {
        "kind": "python", "name": name, "description": text, "category": "Described",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        "output_schema": {"type": "object", "properties": {"input": {"type": "string"},
                                                           "status": {"type": "string"}}},
        "implementation": {"code": _sub(SKELETON_CODE, desc=json.dumps(text), func=name),
                           "sandbox": {"network": "none"}},
        "tests": [{"name": "echoes its input", "arguments": {"text": "hello"},
                   "expect": {"ok": True, "equals": {"input": "hello"}}},
                  {"name": "rejects empty text", "arguments": {"text": ""},
                   "expect": {"ok": False, "error_contains": "text is required"}}],
        "notes": ["mock-toolsmith could not infer an implementation and wrote a skeleton. Edit the code, or "
                  "point the toolsmith alias at a real model."],
    }


# ── LLM tools (kind llm): the model does the work ───────────────────

_LLM_WORDS = re.compile(r"\b(summari[sz]e|summari[sz]es|summary of|classif(y|ies)|categori[sz]e|triage|route .* to|"
                        r"sentiment|extract(s)? .{1,80} from|answer(s)? questions?|an? (llm|language model)|"
                        r"assistant)\b", re.I)


def _labels(desc: str) -> List[str]:
    m = re.search(r"\b(?:into|as|among|between)\s+(?:one of\s+)?([A-Za-z][\w -]*(?:,\s*[\w -]+)*(?:,?\s+(?:or|and)\s+[\w -]+))",
                  desc, re.I)
    if not m:
        return []
    parts = re.split(r"\s*,\s*|\s+(?:or|and)\s+", m.group(1).strip().rstrip("."))
    out = []
    for x in parts:
        w = re.sub(r"[^a-z0-9_]", "_", x.strip().lower()).strip("_")
        w = re.sub(r"_+", "_", w)
        if w and w[0].isalpha() and w not in out and len(w) <= 40:
            out.append(w)
    return out[:12] if len(out) >= 2 else []


def _llm(desc: str, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    low = desc.lower()
    first = _first_sentence(desc, 200)
    text_in = {"type": "object", "properties": {"text": {"type": "string", "description": "The text to work on."}},
               "required": ["text"]}
    note = "An LLM tool: review the instructions and the limits; tests run against the mock model."
    labels = _labels(desc)
    if re.search(r"\b(classif|categori|triage|sentiment|route)", low) and (labels or "sentiment" in low):
        labels = labels or ["positive", "negative", "neutral"]
        name = _slug(["classify"] + [w for w in _WORD.findall(desc) if w.lower() not in ("classify", "into")], 3)
        return {
            "kind": "llm", "name": name, "description": first, "category": "Intelligence",
            "input_schema": text_in,
            "output_schema": {"type": "object", "properties": {
                "label": {"type": "string", "enum": labels}, "reason": {"type": "string"},
                "confidence": {"type": "number"}, "stopped_by": {"type": "string"}},
                "required": ["label", "stopped_by"]},
            "implementation": {"mode": "classify", "model": "fast",
                               "system_prompt": "Choose exactly one label: " + ", ".join(labels) + ".",
                               "template": "Classify this text:\n\n{{input.text}}", "cache": True},
            "tests": [{"name": f"labels a {labels[0]} text", "arguments": {"text": f"This is about {labels[0]}."},
                       "expect": {"ok": True, "equals": {"label": labels[0]}}},
                      {"name": f"labels a {labels[1]} text", "arguments": {"text": f"This is about {labels[1]}."},
                       "expect": {"ok": True, "equals": {"label": labels[1]}}}],
            "notes": [note, "Describe each label in the system prompt so the model can tell them apart."],
        }
    m = re.search(r"\bextract(?:s)?\s+(?:the\s+)?(.{1,120}?)\s+from\b", desc, re.I)
    if m:
        fields = [re.sub(r"[^a-z0-9_]", "_", f.strip().lower()).strip("_")
                  for f in re.split(r"\s*,\s*|\s+and\s+", m.group(1))]
        fields = [re.sub(r"_+", "_", f) for f in fields if f and f[0].isalpha()][:10]
        if fields:
            return {
                "kind": "llm", "name": _slug(["extract"] + fields, 4), "description": first, "category": "Intelligence",
                "input_schema": text_in,
                "output_schema": {"type": "object", "properties": {
                    **{f: {"type": "string"} for f in fields}, "stopped_by": {"type": "string"}},
                    "required": ["stopped_by"]},
                "implementation": {"mode": "extract", "model": "fast",
                                   "template": "Extract the fields from this text:\n\n{{input.text}}", "cache": True},
                "tests": [{"name": "reads labelled fields", "arguments":
                           {"text": "\n".join(f"{f.replace('_', ' ')}: sample {i + 1}" for i, f in enumerate(fields))},
                           "expect": {"ok": True, "keys": fields}}],
                "notes": [note, "Give each field a description and a type in the output schema."],
            }
    if re.search(r"\bsummari[sz]e|\bsummary of\b", low):
        n = re.search(r"\b(\d{1,2})\s+sentences?\b", low)
        k = int(n.group(1)) if n else 3
        return {
            "kind": "llm", "name": _slug(["summarise"] + _WORD.findall(desc)[1:], 3), "description": first,
            "category": "Intelligence", "input_schema": text_in,
            "output_schema": {"type": "object", "properties": {"text": {"type": "string"},
                                                               "stopped_by": {"type": "string"}},
                              "required": ["text", "stopped_by"]},
            "implementation": {"mode": "complete", "model": "fast",
                               "system_prompt": "You write short, faithful summaries. Keep names and numbers exactly.",
                               "template": f"Summarise the following text in at most {k} sentences.\n\n{{{{input.text}}}}",
                               "cache": True},
            "tests": [{"name": "summarises a short text", "arguments": {"text": "SAJHA serves tools. It runs them "
                                                                                  "as the caller. It audits each call."},
                       "expect": {"ok": True, "keys": ["text"]}}],
            "notes": [note],
        }
    if re.search(r"\banswer(s)? questions?\b|\bassistant\b", low):
        tools = [t["name"] for t in ctx.get("existing_tools") or [] if isinstance(t, dict) and t.get("name")]
        prefixes = sorted({n.split("_")[0] for n in tools if re.search(rf"\b{re.escape(n.split('_')[0])}\b", low)})
        named = [n for n in tools if re.search(rf"\b{re.escape(n)}\b", low)]
        allow = named + [f"{p}_*" for p in prefixes if not any(n.startswith(p + "_") for n in named)]
        q = {"type": "object", "properties": {
            "question": {"type": "string", "description": "The question, in plain words."},
            "conversation_id": {"type": "string", "description": "From a previous answer, to continue."}},
            "required": ["question"]}
        out = {"type": "object", "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"},
                                                "citations": {"type": "array", "items": {"type": "string"}},
                                                "conversation_id": {"type": "string"},
                                                "stopped_by": {"type": "string"}},
               "required": ["answer", "stopped_by"]}
        memory = {"mode": "conversation", "ttl_minutes": 240, "max_turns": 10}
        tests = [{"name": "answers a question", "arguments": {"question": "What can you tell me?"},
                  "expect": {"ok": True, "keys": ["answer"]}}]
        if not allow:
            return {"kind": "llm", "name": _slug(["docs", "qa"] + _WORD.findall(desc), 3), "description": first,
                    "category": "Intelligence", "input_schema": q, "output_schema": out,
                    "implementation": {"mode": "grounded", "model": "default", "rag": {"sources": ["sajha_docs"], "top_k": 4},
                                       "memory": memory},
                    "tests": tests,
                    "notes": [note, "No tools were named, so it answers from document search (mode grounded); "
                                    "name tools or tool prefixes to make it an assistant that calls them."]}
        return {"kind": "llm", "name": _slug(["assistant"] + prefixes + _WORD.findall(desc), 3), "description": first,
                "category": "Intelligence", "input_schema": q, "output_schema": out,
                "implementation": {"mode": "answer", "model": "reasoning",
                                   "system_prompt": "Answer with figures from tool results; say when data is missing.",
                                   "tools": {"allow": allow, "deny": ["*_delete*"]},
                                   "limits": {"max_steps": 6, "max_tool_calls": 10, "max_cost_usd": 0.2},
                                   "memory": memory},
                "tests": tests, "notes": [note, "Check that tools.allow matches only the tools it should call."]}
    return None


def design(user_text: str) -> Dict[str, Any]:
    """The proposal for the generator's prompt (the toolsmith schema)."""
    desc, ctx, prefer = parse_request(user_text)
    urls = _URL.findall(desc)
    low = desc.lower()
    order = ["openapi", "rest", "llm", "dbquery", "composite", "python"]
    if prefer in order:
        order.remove(prefer)
        order.insert(0, prefer)
    for kind in order:
        if kind == "openapi" and urls and (re.search(r"\b(openapi|swagger|spec|api-docs)\b", low)
                                           or re.search(r"(openapi|swagger)[^/]*\.(json|ya?ml)$", urls[0], re.I)):
            return _openapi(desc, urls[0].rstrip(".,;:)"))
        if kind == "rest" and urls:
            return _rest(desc, urls[0])
        if kind == "dbquery":
            db, table = _find_table(desc, ctx)
            if table:
                return _dbquery(desc, db, table)
        if kind == "composite":
            c = _composite(desc, ctx)
            if c:
                return c
        if kind == "llm" and (prefer == "llm" or _LLM_WORDS.search(desc)):
            p = _llm(desc, ctx)
            if p:
                return p
        if kind == "python":
            for recipe in (_fred, _stats):
                p = recipe(desc)
                if p:
                    return p
    return _skeleton(desc)


# ── the model ────────────────────────────────────────────────────

def _model_class():
    from sajha.ai.llm.mock import _MockChat, _last_user_text

    class ToolsmithModel(_MockChat):
        """Structured output only: replies with the proposal JSON for the last user message."""

        def _reply(self, request):
            return json.dumps(design(_last_user_text(request))), [], "stop"

    return ToolsmithModel


ToolsmithModel = _model_class()
