"""
SAJHA MCP Server — tools that call other tools: run as the caller, bounded depth, no cycles.

A tool that calls other tools (``sajha_ask``, a composite's steps, later LLM tools) runs
each inner call as the original caller: the caller context variable
(``sajha/observability/caller.py``) is kept, so policy rules, the usage ledger and
connected accounts see the same person, and :func:`check` refuses an inner tool the
caller may not execute. A tool can therefore never give a caller more than the caller
already has.

The call chain is a second context variable: the names of the tools currently running
one inside another. :func:`entered` adds a name, refuses a name already in the chain (a
cycle) and a chain deeper than ``tools.max_call_depth`` (default 8). The workflow engine
keeps its own chain of workflow names (``sajha/workflows/engine.py``, ``CHAIN``); this
one is for tools.

Context variables do not follow work into a ``ThreadPoolExecutor`` by themselves; submit
with :func:`in_context` so the caller and the chain go along.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Callable, Iterator, Optional, Tuple

DEFAULT_MAX_DEPTH = 8

CHAIN: contextvars.ContextVar = contextvars.ContextVar('sajha_tool_chain', default=())


class InnerCallRefused(PermissionError):
    """An inner tool call the caller may not make, or that would loop or nest too deep."""


class CallCycle(InnerCallRefused):
    pass


class CallTooDeep(InnerCallRefused):
    pass


def max_depth() -> int:
    try:
        from sajha.core.config import _int
        return max(1, _int('tools.max_call_depth', DEFAULT_MAX_DEPTH))
    except Exception:
        return DEFAULT_MAX_DEPTH


def chain() -> Tuple[str, ...]:
    return tuple(CHAIN.get())


def depth() -> int:
    return len(CHAIN.get())


@contextmanager
def entered(name: str, limit: Optional[int] = None) -> Iterator[Tuple[str, ...]]:
    """Run the body with ``name`` on the chain; refuses a cycle or a chain over the limit."""
    cur = tuple(CHAIN.get())
    if name in cur:
        raise CallCycle(f'{name} is already running in this call chain ({" > ".join(cur + (name,))})')
    lim = limit if limit is not None else max_depth()
    if len(cur) >= lim:
        raise CallTooDeep(f'calling {name} would nest tools {len(cur) + 1} deep (limit {lim}: tools.max_call_depth)')
    token = CHAIN.set(cur + (name,))
    try:
        yield cur + (name,)
    finally:
        CHAIN.reset(token)


def caller_may_run(tool_name: str) -> bool:
    """May the current caller execute ``tool_name``?  True when no entry point recorded an access
    (code running a tool directly, outside any request)."""
    from sajha.observability.caller import current
    ok = current().can_execute(tool_name)
    return True if ok is None else ok


def check(tool_name: str) -> None:
    """Raise :class:`InnerCallRefused` when the current caller may not execute ``tool_name``."""
    if not caller_may_run(tool_name):
        from sajha.observability.caller import current
        raise InnerCallRefused(f'the caller {current().user_id!r} may not execute {tool_name}')


def in_context(fn: Callable, *args, **kwargs):
    """A callable for an executor that runs ``fn`` in a copy of this context (caller, chain, source)."""
    ctx = contextvars.copy_context()
    return lambda: ctx.run(fn, *args, **kwargs)
