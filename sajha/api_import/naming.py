"""
SAJHA MCP Server — API Import: tool, prefix and argument names.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Tool names follow the Studio rule (``^[a-z][a-z0-9_]{2,63}$``), a subset of the MCP tool
name rule, so an imported tool can be deleted and renamed like any Studio tool. Argument
(property) names are kept unless they fall outside ``[A-Za-z0-9_.-]{1,64}``, which some
model APIs require of tool input properties.
"""

from __future__ import annotations

import hashlib
import re

TOOL_NAME_RE = re.compile(r'^(?!.*__)[a-z][a-z0-9_]{2,63}$')   # no '__': reserved (sajha/tools/naming.py)
PREFIX_RE = re.compile(r'^[a-z][a-z0-9_]{1,30}$')
ARG_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
MAX_NAME = 64


def snake(text: str) -> str:
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', str(text or ''))
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_').lower()
    return re.sub(r'_+', '_', s)


def prefix_from(title: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '_', str(title or '').lower()).strip('_')[:30].strip('_') or 'api'
    if not s[0].isalpha():
        s = 'api_' + s
    return s[:30].strip('_') if len(s) > 1 else s + '_api'


def valid_prefix(prefix: str) -> bool:
    return bool(PREFIX_RE.match(prefix or ''))


def base_from_operation(operation_id: str, method: str, path: str) -> str:
    if operation_id and snake(operation_id):
        return snake(operation_id)
    parts = [method.lower()]
    for seg in [s for s in path.split('/') if s]:
        if seg.startswith('{') and seg.endswith('}'):
            parts.append('by_' + snake(seg[1:-1]))
        else:
            parts.append(snake(seg))
    return '_'.join(p for p in parts if p) or method.lower()


def tool_name(prefix: str, base: str) -> str:
    name = f'{prefix}_{base}'.strip('_')
    name = re.sub(r'_+', '_', name)
    if not name[:1].isalpha():
        name = 't_' + name
    if len(name) > MAX_NAME:
        digest = hashlib.sha1(name.encode()).hexdigest()[:8]
        name = name[:MAX_NAME - 9].rstrip('_') + '_' + digest
    if len(name) < 3:
        name = (name + '_op')[:MAX_NAME]
    return name


def dedupe(name: str, taken: set) -> str:
    if name not in taken:
        return name
    n = 2
    while True:
        suffix = f'_{n}'
        candidate = name[:MAX_NAME - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


def arg_name(name: str) -> str:
    if ARG_RE.match(name or ''):
        return name
    s = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(name or '')).strip('_') or 'arg'
    return s[:64]
