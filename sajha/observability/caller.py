"""
SAJHA MCP Server — who is calling, for the usage ledger.

A context variable set where the caller is known (the MCP handlers from the session
dict, the REST execute endpoint and the ask service from the AuthContext) and read where
a tool or a model runs. Context variables follow the call into Starlette's and anyio's
worker threads, so the tool sees the caller its request came from.

The caller also carries its tool access (``access``: name -> may execute), recorded where
the caller is set, so a tool that calls other tools (``sajha_ask``, composites, workflow
steps) runs each inner call as the original caller and with no more than the caller's
access (:func:`sajha.core.inner_calls.check`). ``access`` is None only where no entry point
recorded one (code that runs a tool directly, outside any request).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, Callable, List, Mapping, Optional


@dataclass(frozen=True)
class Caller:
    user_id: str = 'anonymous'
    api_key: str = ''
    roles: tuple = field(default_factory=tuple)
    auth_type: str = ''
    #: the caller's tool access (name -> may execute); None: not recorded by any entry point
    access: Optional[Callable[[str], bool]] = field(default=None, compare=False, repr=False)
    is_admin: bool = False

    def can_execute(self, tool_name: str) -> Optional[bool]:
        """True/False from the recorded access; None when no access was recorded."""
        if self.access is None:
            return None
        try:
            return bool(self.access(tool_name))
        except Exception:
            return False


ANONYMOUS = Caller()
_current: contextvars.ContextVar[Optional[Caller]] = contextvars.ContextVar('sajha_caller', default=None)


def current() -> Caller:
    return _current.get() or ANONYMOUS


def _api_key_of(user_id: str, api_key: Optional[str]) -> str:
    if api_key:
        return str(api_key)
    if user_id and user_id.startswith('apikey:'):
        return user_id[len('apikey:'):]
    return ''


def _session_access(s: Mapping[str, Any]) -> Optional[Callable[[str], bool]]:
    """The tool policy an MCP session dict carries (sajha/auth/access.py), if it carries one."""
    if not isinstance(s, Mapping) or 'tools' not in s:
        return None
    try:
        from sajha.auth.access import ToolPolicy
        return ToolPolicy.from_session(dict(s)).can_execute
    except Exception:
        return None


def from_session(session: Optional[Mapping[str, Any]]) -> Caller:
    s = session or {}
    uid = str(s.get('user_id') or 'anonymous')
    return Caller(uid, _api_key_of(uid, s.get('api_key_name')), tuple(s.get('roles') or ()),
                  str(s.get('auth_type') or ''), _session_access(s), bool(s.get('is_admin')))


def from_auth(auth: Any) -> Caller:
    """The caller of an AuthContext, with its tool access (an unauthenticated one: anonymous)."""
    access = None
    try:
        from sajha.auth.access import policy_for
        access = policy_for(auth).can_execute
    except Exception:
        access = None
    if auth is None or not getattr(auth, 'authenticated', False):
        return Caller(access=access)
    uid = str(getattr(auth, 'user_id', '') or 'anonymous')
    return Caller(uid, _api_key_of(uid, getattr(auth, 'api_key_name', None)),
                  tuple(getattr(auth, 'roles', None) or ()), str(getattr(auth, 'auth_type', '') or ''),
                  access, bool(getattr(auth, 'is_admin', False)))


def from_request_context(ctx: Any) -> Caller:
    """An LLM RequestContext (user_id, roles); keeps the API key of the current caller."""
    if ctx is None:
        return current()
    cur = current()
    uid = str(getattr(ctx, 'user_id', '') or cur.user_id)
    roles: List[str] = list(getattr(ctx, 'roles', None) or cur.roles)
    same = cur.user_id == uid
    access = getattr(ctx, 'can_use_tool', None) or (cur.access if same else None)
    return Caller(uid, _api_key_of(uid, cur.api_key if same else ''), tuple(roles),
                  cur.auth_type if same else '', access,
                  bool(getattr(ctx, 'is_admin', False) or (same and cur.is_admin)))


def set_caller(caller: Caller):
    """Set the caller; returns a token for :func:`reset`."""
    return _current.set(caller)


def reset(token) -> None:
    try:
        _current.reset(token)
    except (ValueError, RuntimeError):
        pass
