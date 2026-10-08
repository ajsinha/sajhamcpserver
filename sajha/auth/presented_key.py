"""
SAJHA MCP Server — the API key a caller presented, for this request only.

SAJHA Net's ``api_key`` identity forwards the caller's own key to the instance hosting a remote
tool (docs/architecture/SAJHA Net.md §10.2). Keys are stored only as hashes, so the raw key exists
only in memory while the request that presented it runs: :func:`remember` is called where an API
key authenticates (``AuthManager.authenticate_apikey``) and records it in a context variable of
the request, and :func:`presented` reads it back where a call is forwarded. A caller's key NAME
(``Caller.api_key``) is never a key. The value is never
logged, stored, traced or audited, and its ``repr`` hides it.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class PresentedKey:
    key_id: str
    user_id: str                                   # the owner's login name (users.user_id)
    raw: str = field(repr=False)

    def __repr__(self) -> str:                     # never the key
        return f'PresentedKey(key_id={self.key_id!r}, user_id={self.user_id!r})'


_current: contextvars.ContextVar[Optional[PresentedKey]] = contextvars.ContextVar('sajha_presented_key', default=None)


def remember(raw: str, key_id: str, user_id: str):
    """Record the key this request authenticated with; returns a token for :func:`forget`."""
    return _current.set(PresentedKey(str(key_id or ''), str(user_id or ''), raw))


def bind(auth) -> None:
    """Re-bind, in the current context, the key an AuthContext authenticated with. FastAPI runs a
    synchronous dependency in a worker thread, so the :func:`remember` made there does not reach the
    endpoint; the entry points that set the caller (REST, A2A, the OpenAI-compatible API) call this.
    A context without an API key (session, JWT, anonymous) clears any key left in the context."""
    held = getattr(auth, '_presented', None) if auth is not None else None
    if isinstance(held, PresentedKey) and held.raw:
        _current.set(held)
    elif auth is not None and getattr(auth, 'auth_type', None) != 'apikey':
        _current.set(None)


def presented() -> Optional[PresentedKey]:
    return _current.get()


def forget(token=None) -> None:
    if token is not None:
        try:
            _current.reset(token)
            return
        except (ValueError, RuntimeError):
            pass
    _current.set(None)
