"""
SAJHA MCP Server — ``inputSchema`` defaults applied before a tool runs.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A client reads a tool's ``default`` and expects the tool to behave that way when it leaves the
argument out. :func:`apply_schema_defaults` makes that true: ``BaseMCPTool.execute_with_tracking``
(the one place every transport runs a tool through: MCP in both eras, the REST API, Ask SAJHA,
workflows, SAJHA Net, async tasks) calls it once, after version routing and before policy,
validation, the cache, execution and audit, so all of them see the same arguments. The composite
step executor and the quality harness, which call ``execute`` directly, call it too.

Rules (docs/architecture/Tool Quality.md §12.1):

1. Only absent keys are filled. A key that is present is never replaced, even when it is ``null``.
2. A ``required`` property is never filled (a required property with a default is a
   contradiction; lint reports ``required-default``).
3. A nested ``type: object`` property with its own ``properties`` is filled inside only when the
   caller supplied that object; a ``default`` on the object property itself fills it when absent.
4. Nothing is read through ``oneOf``, ``anyOf``, ``allOf``, ``if``/``then``, ``$ref`` or array
   ``items``: which branch applies is not known before validation (lint: ``unapplied-default``).
5. Defaults are deep-copied, and the caller's dict is never changed.
6. A default that does not validate against its own property schema is not applied (logged
   once), so a bad default cannot turn a call that used to work into an argument error.

``tools.apply_schema_defaults`` (default true) turns the whole thing off; it is an escape hatch
for one release (8.8.0) and is removed in the release after.
"""

from __future__ import annotations

import copy
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# A plan is a tuple of entries (name, has_default, default, nested_plan_or_None)
_Plan = Tuple[Tuple[str, bool, Any, Optional[tuple]], ...]

_PLANS: Dict[int, Tuple[dict, _Plan]] = {}      # id(schema) -> (schema, plan); the schema keeps the id alive
_LOCK = threading.Lock()


def enabled() -> bool:
    """``tools.apply_schema_defaults`` (env ``SAJHA_TOOLS_APPLY_SCHEMA_DEFAULTS``), default true."""
    try:
        from sajha.core.config import _bool
        return _bool('tools.apply_schema_defaults', True)
    except Exception:
        return True


def _default_is_valid(sub: dict, value: Any, where: str) -> bool:
    if '$ref' in str(sub):
        return True                       # cannot resolve a reference out of context; validation judges
    try:
        from jsonschema import Draft202012Validator
        check = {k: v for k, v in sub.items() if k != 'default'}
        errors = list(Draft202012Validator(check).iter_errors(value))
    except ImportError:
        return True
    except Exception:
        return True
    if errors:
        logger.warning(f"inputSchema default for '{where}' does not match its own schema "
                       f"({errors[0].message}); it is not applied")
        return False
    return True


def _is_object_with_properties(sub: dict) -> bool:
    t = sub.get('type')
    is_object = t == 'object' or (isinstance(t, list) and 'object' in t) or (t is None and 'properties' in sub)
    return is_object and isinstance(sub.get('properties'), dict) and bool(sub['properties'])


def build_plan(schema: Any, _prefix: str = '') -> Optional[_Plan]:
    """The defaults a schema can apply, or None when it has none (applying is then a no-op)."""
    if not isinstance(schema, dict):
        return None
    props = schema.get('properties')
    if not isinstance(props, dict):
        return None
    required = set(schema.get('required') or []) if isinstance(schema.get('required'), list) else set()
    entries = []
    for name, sub in props.items():
        if not isinstance(sub, dict):
            continue
        where = f'{_prefix}{name}'
        has_default = 'default' in sub and name not in required and _default_is_valid(sub, sub['default'], where)
        nested = build_plan(sub, where + '.') if _is_object_with_properties(sub) else None
        if has_default or nested:
            entries.append((name, has_default, sub.get('default') if has_default else None, nested))
    return tuple(entries) or None


def _plan_for(schema: dict) -> Optional[_Plan]:
    hit = _PLANS.get(id(schema))
    if hit is not None and hit[0] is schema:
        return hit[1]
    plan = build_plan(schema)
    with _LOCK:
        if len(_PLANS) > 4096:
            _PLANS.clear()
        _PLANS[id(schema)] = (schema, plan)
    return plan


def _apply(plan: _Plan, arguments: dict, prefix: str, filled: List[str]) -> dict:
    out = dict(arguments)
    for name, has_default, default, nested in plan:
        if name not in out:
            if has_default:
                out[name] = copy.deepcopy(default)
                filled.append(prefix + name)
        elif nested and isinstance(out[name], dict):
            out[name] = _apply(nested, out[name], prefix + name + '.', filled)
    return out


def apply_schema_defaults(schema: Any, arguments: Any) -> Tuple[Any, List[str]]:
    """``(arguments with the schema's defaults filled in, the dotted names that were filled)``.

    Returns the caller's own object (unchanged) when nothing applies, and a new dict otherwise.
    Arguments that are not a dict are returned as they are; validation reports them."""
    if not isinstance(arguments, dict) or not isinstance(schema, dict):
        return arguments, []
    plan = _plan_for(schema)
    if not plan:
        return arguments, []
    filled: List[str] = []
    out = _apply(plan, arguments, '', filled)
    return (out, filled) if filled else (arguments, [])


def apply_for_tool(tool: Any, arguments: Any) -> Tuple[Any, List[str]]:
    """Apply ``tool``'s ``inputSchema`` defaults, honouring the switch and the tool's opt-out
    (``apply_schema_defaults = False`` on proxies of other servers, which own their contract)."""
    if not getattr(tool, 'apply_schema_defaults', True) or not enabled():
        return arguments, []
    try:
        schema = tool.input_schema
    except Exception:
        return arguments, []
    try:
        return apply_schema_defaults(schema, arguments)
    except Exception as e:                       # never let defaults break a call
        logger.debug(f'schema defaults for {getattr(tool, "name", tool)}: {e}')
        return arguments, []
