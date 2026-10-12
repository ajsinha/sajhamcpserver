"""
SAJHA MCP Server — the policy engine: declarative rules evaluated before every tool call.

``BaseMCPTool.execute_with_tracking`` (the one place every path runs a tool through)
calls :func:`enforce` first and applies the returned enforcement to the result. Rules
live in ``config/policies/*.yaml|yml|json`` (storage backend, hot-reloaded). The default is
permissive: the shipped policy has no rules. Design: docs/architecture/Policy and Audit.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sajha.policy.errors import ApprovalRequired, PolicyDenied, PolicyError, RateLimited  # noqa: F401


def enforce(tool, arguments: Dict[str, Any]):
    """Check a call against the policies; raises to stop it, returns None or an Enforcement."""
    from sajha.policy.engine import get_engine
    return get_engine().enforce(tool, arguments)


def apply_output(enforcement, result: Any) -> Any:
    return result if enforcement is None else enforcement.apply_output(result)


def offered(tool, source: str, caller: Any = None) -> bool:
    """False when the policy would deny every call of ``tool`` from ``source`` by ``caller`` (default:
    the current caller): such a tool is not offered to a model. No side effects; an error offers it
    (the call-time check still applies)."""
    try:
        from sajha.policy.engine import get_engine as _g
        return _g().denies(tool, source, caller) is None
    except Exception:
        return True


def get_engine():
    from sajha.policy.engine import get_engine as _g
    return _g()


__all__ = ['enforce', 'apply_output', 'offered', 'get_engine', 'PolicyError', 'PolicyDenied', 'ApprovalRequired',
           'RateLimited']
