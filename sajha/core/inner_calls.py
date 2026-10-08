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

Across SAJHA Net the chain continues: a forwarded call carries its hop count, the instances it
passed and the nesting depth it had there (``params._meta["io.sajha/net"].depth``). The host runs
the tool inside :func:`net_entered`, so its own nesting adds to that, and a call it forwards onward
carries the incoming hops and visited list (:func:`outgoing`). Hops plus nesting depth on every
instance passed is one budget, ``sajhanet.max_call_chain`` (default 8; :func:`max_chain`):
:func:`entered` refuses a nested tool that would exceed it while running a forwarded call, and the
home and host refuse a forwarded call over it (``-32016 chain_limit``; docs/architecture/SAJHA Net.md §14).

Context variables do not follow work into a ``ThreadPoolExecutor`` by themselves; submit
with :func:`in_context` so the caller and the chain go along.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Callable, Iterator, List, Optional, Tuple

DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_CHAIN = 8
MAX_CHAIN_CAP = 32

CHAIN: contextvars.ContextVar = contextvars.ContextVar('sajha_tool_chain', default=())
# a forwarded SAJHA Net call this context runs for: (hop, visited, depth carried from earlier instances)
NET_IN: contextvars.ContextVar = contextvars.ContextVar('sajha_net_chain', default=None)


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


def max_chain() -> int:
    """The combined budget of a call chain across SAJHA Net: hops plus nesting depth on every instance."""
    try:
        from sajha.core.config import _int
        return max(1, min(MAX_CHAIN_CAP, _int('sajhanet.max_call_chain', DEFAULT_MAX_CHAIN)))
    except Exception:
        return DEFAULT_MAX_CHAIN


def chain() -> Tuple[str, ...]:
    return tuple(CHAIN.get())


def depth() -> int:
    return len(CHAIN.get())


def net_base() -> int:
    """What earlier instances used of the combined budget: hops plus the depth they carried (0 locally)."""
    n = NET_IN.get()
    return int(n[0]) + int(n[2]) if n else 0


def outgoing() -> Tuple[Optional[Tuple[int, List[str]]], int]:
    """For a call this context forwards: the incoming ``(hop, visited)`` (None when the chain starts
    here) and the nesting depth to carry (the depth carried in plus this instance's own)."""
    n = NET_IN.get()
    if not n:
        return None, depth()
    return (int(n[0]), list(n[1])), int(n[2]) + depth()


@contextmanager
def net_entered(hop: int, visited: List[str], carried: int = 0) -> Iterator[None]:
    """Run a forwarded call's tool: a fresh local chain, with the net chain it arrived on."""
    t1 = NET_IN.set((int(hop), tuple(visited), max(0, int(carried))))
    t2 = CHAIN.set(())
    try:
        yield
    finally:
        CHAIN.reset(t2)
        NET_IN.reset(t1)


@contextmanager
def entered(name: str, limit: Optional[int] = None) -> Iterator[Tuple[str, ...]]:
    """Run the body with ``name`` on the chain; refuses a cycle or a chain over the limit (and, for a
    forwarded call, over the combined budget ``sajhanet.max_call_chain``)."""
    cur = tuple(CHAIN.get())
    if name in cur:
        raise CallCycle(f'{name} is already running in this call chain ({" > ".join(cur + (name,))})')
    lim = limit if limit is not None else max_depth()
    if len(cur) >= lim:
        raise CallTooDeep(f'calling {name} would nest tools {len(cur) + 1} deep (limit {lim}: tools.max_call_depth)')
    n = NET_IN.get()
    if n:
        total, cap = net_base() + len(cur) + 1, max_chain()
        if total > cap:
            raise CallTooDeep(f'calling {name} would make the call chain {total} long across SAJHA Net '
                              f'({n[0]} hop(s), {int(n[2]) + len(cur) + 1} nested tool(s); limit {cap}: '
                              f'sajhanet.max_call_chain)')
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
