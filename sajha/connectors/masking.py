"""
SAJHA MCP Server — Data Connectors: column masking.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Applies a connection's ``masking`` rules to result rows, sample rows and search metadata.
Modes: hide (column removed), null, redact, hash (stable, per connection), partial (last four
letters/digits kept) and pii (the policy engine's PII redaction, sajha/policy/redact.py).
The guard (sajha/connectors/guard.py) stops queries that would rename or probe a masked
column. Design: docs/architecture/Data Connectors.md, section 7.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from sajha.connectors.model import Connection, MaskRule

REDACTED = '[REDACTED]'


def _partial(s: str) -> str:
    total = sum(ch.isalnum() for ch in s)
    out, seen = [], 0
    for ch in s:
        if ch.isalnum():
            seen += 1
            out.append(ch if seen > total - 4 else '*')
        else:
            out.append(ch)
    return ''.join(out)


_PII_SPEC = None


def _pii(s: str) -> str:
    global _PII_SPEC
    from sajha.policy.redact import redact_text
    if _PII_SPEC is None:
        from sajha.policy.model import NATIONAL_IDS, RedactSpec
        _PII_SPEC = RedactSpec(('emails', 'phones', 'cards') + tuple(NATIONAL_IDS), (), 'mask')
    return redact_text(s, _PII_SPEC, Counter())


def mask_value(conn: Connection, rule: MaskRule, value: Any) -> Any:
    if value is None:
        return None
    mode = rule.mode
    if mode == 'null':
        return None
    if mode == 'redact':
        return REDACTED
    text = value if isinstance(value, str) else str(value)
    if mode == 'hash':
        return hashlib.sha256(f'{conn.id}:{text}'.encode('utf-8', 'replace')).hexdigest()[:16]
    if mode == 'partial':
        return _partial(text)
    if mode == 'pii':
        if isinstance(value, (dict, list)):
            from sajha.policy.redact import walk
            return walk(value, _pii)
        return _pii(text)
    return REDACTED


def plan(conn: Connection, columns: List[str], tables: List[Tuple[str, str]]) -> Dict[str, MaskRule]:
    """{column name: rule} for the columns of a result that reads ``tables``."""
    out = {}
    for c in columns:
        r = conn.mask_rules_for(str(c), tables)
        if r is not None:
            out[str(c)] = r
    return out


def apply_rows(conn: Connection, rows: List[Dict[str, Any]], rules: Dict[str, MaskRule]) -> List[Dict[str, Any]]:
    if not rules:
        return rows
    out = []
    for row in rows:
        new = {}
        for k, v in row.items():
            r = rules.get(k)
            if r is None:
                new[k] = v
            elif r.mode != 'hide':
                new[k] = mask_value(conn, r, v)
        out.append(new)
    return out


def apply_mapping(conn: Connection, data: Optional[Dict[str, Any]], tables: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Mask a flat or nested mapping (a search hit's metadata) by top-level key."""
    if not isinstance(data, dict):
        return data or {}
    rules = plan(conn, list(data.keys()), tables)
    return apply_rows(conn, [data], rules)[0]
