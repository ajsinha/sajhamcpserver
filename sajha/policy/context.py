"""
SAJHA MCP Server — the facts about a call that the tool itself does not carry.

* the **source**: which entry point the call came in through (``mcp``, ``stdio``,
  ``websocket``, ``rest``, ``playground``, ``a2a``, ``ask``, ``async``, ``workflow``; ``other`` when none
  said). The first entry point to set it wins (:func:`ensure_source`), so a stdio call stays
  ``stdio`` when it reaches the shared MCP handler; :func:`set_source` overrides (Ask SAJHA,
  whose tool calls a model chooses).
* **confirmed**: the caller confirmed this call interactively (Ask SAJHA's Confirm button),
  which satisfies ``require_approval`` with ``approver: caller``;
* **confirmable**: the entry point can ask its user to confirm (Ask SAJHA), so an
  unconfirmed ``approver: caller`` call is answered "needs confirmation" instead of being
  queued for an administrator.

Context variables follow a request into Starlette's and anyio's worker threads, like the
caller (sajha/observability/caller.py). Design: docs/architecture/Policy and Audit.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextlib
import contextvars
from typing import Iterator, Optional

SOURCES = ('mcp', 'stdio', 'websocket', 'rest', 'playground', 'a2a', 'ask', 'async', 'workflow', 'other')

_source: contextvars.ContextVar[str] = contextvars.ContextVar('sajha_policy_source', default='')
_confirmed: contextvars.ContextVar[bool] = contextvars.ContextVar('sajha_policy_confirmed', default=False)
_confirmable: contextvars.ContextVar[bool] = contextvars.ContextVar('sajha_policy_confirmable', default=False)
_era: contextvars.ContextVar[str] = contextvars.ContextVar('sajha_mcp_era', default='')


def source() -> str:
    return _source.get() or 'other'


def set_source(name: str):
    """Set the source (overriding any earlier one); returns a token for :func:`reset_source`."""
    return _source.set(name if name in SOURCES else 'other')


def ensure_source(name: str) -> Optional[contextvars.Token]:
    """Set the source unless an outer entry point already did; a token, or None when unchanged."""
    if _source.get():
        return None
    return set_source(name)


def reset_source(token) -> None:
    if token is None:
        return
    try:
        _source.reset(token)
    except (ValueError, RuntimeError):
        pass


@contextlib.contextmanager
def using_source(name: str, override: bool = False) -> Iterator[None]:
    token = set_source(name) if override else ensure_source(name)
    try:
        yield
    finally:
        reset_source(token)


def era() -> str:
    """The MCP era of the current call (``2026-07-28`` or ``2025-11-25``); '' when not MCP."""
    return _era.get()


def ensure_era(name: str) -> Optional[contextvars.Token]:
    """Set the MCP era unless already set (as :func:`ensure_source`); a token or None."""
    if _era.get():
        return None
    return _era.set(str(name)[:20])


def reset_era(token) -> None:
    if token is None:
        return
    try:
        _era.reset(token)
    except (ValueError, RuntimeError):
        pass


def confirmed() -> bool:
    return _confirmed.get()


@contextlib.contextmanager
def caller_confirmed(value: bool = True) -> Iterator[None]:
    """Mark the calls made inside as interactively confirmed by the caller."""
    token = _confirmed.set(bool(value))
    try:
        yield
    finally:
        try:
            _confirmed.reset(token)
        except (ValueError, RuntimeError):
            pass


def confirmable() -> bool:
    return _confirmable.get()


@contextlib.contextmanager
def interactive(confirmed_: bool = False) -> Iterator[None]:
    """The calls made inside come from a client that can ask its user (Ask SAJHA);
    ``confirmed_``: the user already confirmed this call."""
    t1, t2 = _confirmable.set(True), _confirmed.set(bool(confirmed_))
    try:
        yield
    finally:
        for var, tok in ((_confirmable, t1), (_confirmed, t2)):
            try:
                var.reset(tok)
            except (ValueError, RuntimeError):
                pass
