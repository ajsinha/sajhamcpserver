"""
SAJHA MCP Server — relaying a 2025-11-25 upstream's requests to SAJHA's own client.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A session-based (2025-11-25) upstream may ask its client for something in the middle of a
tool call: ``sampling/createMessage``, ``elicitation/create`` or ``roots/list``. SAJHA is that
client; the one who can answer is SAJHA's own caller. When the caller is a 2025-11-25 client
that declared the capability and takes a streamed response (``Accept: text/event-stream``),
the transport binds a :class:`ClientRelay` around the call (``bound``); the federation manager
then makes the upstream call on a connection opened for this call, whose callbacks send each
request to the caller on the call's SSE stream and return the caller's answer. Without a
relay, or for a capability the caller did not declare, the upstream gets a clear error.
Design: docs/architecture/Federation.md (section 7, "Requests from the upstream").
"""

from __future__ import annotations

import asyncio
import contextvars
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

SAMPLING = 'sampling/createMessage'
ELICITATION = 'elicitation/create'
ROOTS = 'roots/list'
METHODS = (SAMPLING, ELICITATION, ROOTS)
_CAPABILITY = {SAMPLING: 'sampling', ELICITATION: 'elicitation', ROOTS: 'roots'}


def capability_for(method: str) -> str:
    return _CAPABILITY.get(method, method)


def caller_supports(capabilities: Optional[Dict[str, Any]], method: str,
                    params: Optional[Dict[str, Any]] = None) -> bool:
    """Did the caller declare the client capability ``method`` needs (elicitation: in this mode)?"""
    caps = capabilities if isinstance(capabilities, dict) else {}
    cap = _CAPABILITY.get(method)
    if cap is None or cap not in caps:
        return False
    if method == ELICITATION:
        declared = caps.get('elicitation')
        mode = (params or {}).get('mode') or 'form'
        if not isinstance(declared, dict) or not declared:
            return mode == 'form'              # an empty elicitation capability means form mode
        return mode in declared
    return True


def wanted(capabilities: Optional[Dict[str, Any]]) -> bool:
    """Is a relay worth binding for a caller with these capabilities (sampling or elicitation)?
    Roots alone do not open a connection per call; they are answered when a relay is open."""
    caps = capabilities if isinstance(capabilities, dict) else {}
    return 'sampling' in caps or 'elicitation' in caps


class ClientRelay:
    """The calling client's side of one tools/call: ``call_ctx.request`` sends a server-to-client
    request on the call's SSE stream and resolves with the client's answer (a POST to /mcp)."""

    def __init__(self, call_ctx: Any, loop: asyncio.AbstractEventLoop, capabilities: Dict[str, Any],
                 timeout_s: float = 300.0):
        self.call_ctx = call_ctx
        self.loop = loop
        self.capabilities = dict(capabilities or {})
        self.timeout_s = timeout_s

    def supports(self, method: str, params: Optional[Dict[str, Any]] = None) -> bool:
        return caller_supports(self.capabilities, method, params)

    async def request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Ask the caller (from any event loop: the federation loop awaits it)."""
        fut = asyncio.run_coroutine_threadsafe(self.call_ctx.request(method, params, timeout=self.timeout_s),
                                               self.loop)
        return await asyncio.wrap_future(fut)


_BOUND: contextvars.ContextVar = contextvars.ContextVar('sajha_federation_relay', default=None)  # (tool, relay)


@contextmanager
def bound(relay: Optional[ClientRelay], tool_name: str) -> Iterator[None]:
    """Make ``relay`` the client channel of ``tool_name`` for the code inside."""
    token = _BOUND.set((tool_name, relay))
    try:
        yield
    finally:
        _BOUND.reset(token)


def current(tool_name: str) -> Optional[ClientRelay]:
    """The relay bound for the MCP call of ``tool_name`` (not for a tool it calls in turn), or None."""
    held = _BOUND.get()
    if held is None or held[0] != tool_name:
        return None
    return held[1]


def refusal(upstream_id: str, method: str, relayed: bool) -> str:
    """The error an upstream gets when its request cannot be relayed."""
    cap = capability_for(method)
    if relayed:
        return (f'SAJHA proxies {upstream_id} for a client that did not declare the {cap} capability, '
                f'so {method} cannot be answered')
    return (f'SAJHA proxies {upstream_id} and cannot pass {method} to its caller: that needs a call over MCP '
            f'2025-11-25 with a streamed response (Accept: text/event-stream) from a client that declares '
            f'the {cap} capability')
