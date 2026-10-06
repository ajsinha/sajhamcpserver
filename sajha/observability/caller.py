"""
SAJHA MCP Server — who is calling, for the usage ledger.

A context variable set where the caller is known (the MCP handlers from the session
dict, the REST execute endpoint and the ask service from the AuthContext) and read where
a tool or a model runs. Context variables follow the call into Starlette's and anyio's
worker threads, so the tool sees the caller its request came from.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional


@dataclass(frozen=True)
class Caller:
    user_id: str = 'anonymous'
    api_key: str = ''
    roles: tuple = field(default_factory=tuple)
    auth_type: str = ''


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


def from_session(session: Optional[Mapping[str, Any]]) -> Caller:
    s = session or {}
    uid = str(s.get('user_id') or 'anonymous')
    return Caller(uid, _api_key_of(uid, s.get('api_key_name')), tuple(s.get('roles') or ()),
                  str(s.get('auth_type') or ''))


def from_auth(auth: Any) -> Caller:
    if auth is None or not getattr(auth, 'authenticated', False):
        return ANONYMOUS
    uid = str(getattr(auth, 'user_id', '') or 'anonymous')
    return Caller(uid, _api_key_of(uid, getattr(auth, 'api_key_name', None)),
                  tuple(getattr(auth, 'roles', None) or ()), str(getattr(auth, 'auth_type', '') or ''))


def from_request_context(ctx: Any) -> Caller:
    """An LLM RequestContext (user_id, roles); keeps the API key of the current caller."""
    if ctx is None:
        return current()
    cur = current()
    uid = str(getattr(ctx, 'user_id', '') or cur.user_id)
    roles: List[str] = list(getattr(ctx, 'roles', None) or cur.roles)
    return Caller(uid, _api_key_of(uid, cur.api_key if cur.user_id == uid else ''), tuple(roles),
                  cur.auth_type if cur.user_id == uid else '')


def set_caller(caller: Caller):
    """Set the caller; returns a token for :func:`reset`."""
    return _current.set(caller)


def reset(token) -> None:
    try:
        _current.reset(token)
    except (ValueError, RuntimeError):
        pass
