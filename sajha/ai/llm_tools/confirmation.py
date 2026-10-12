"""
SAJHA MCP Server — destructive-tool confirmation asked of the MCP client (Ask SAJHA over MCP).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

When an answer-mode LLM tool (``sajha_ask``) is the MCP call's own tool and the model wants to run a
destructive tool (or a policy rule asks the caller to approve a call), the user is asked through the
client instead of the ask stopping with ``needs_confirmation``. Design and as-built:
docs/architecture/Intelligence Layer.md §6 ("Confirmation over MCP").

Two channels, one per protocol era, chosen exactly as for sampling (sajha/ai/llm_tools/sampling.py):

* **2026-07-28** (stateless): an MRTR input request. The ask raises ``InputRequired`` with one
  form-mode ``elicitation/create`` request per pending call, keyed ``sajha_confirm_<fingerprint>``;
  the client answers in ``inputResponses`` and calls again; the ask runs from the start and, when the
  model asks for the same call (same tool, same arguments, so the same fingerprint), finds the answer
  under its key (sajha/core/mcp_mrtr.py). The request is the one ``mcp.confirm_destructive_tools``
  sends (sajha/core/mcp_modern.py): a boolean ``confirm``.
* **2025-11-25** (sessions): an ``elicitation/create`` server request on the call's SSE response
  stream, bound by the transport (sajha/routes/mcp_routes.py) when the session declared form-mode
  elicitation and the call accepts ``text/event-stream``; the worker thread waits for the answer.

Without a channel the ask stops with ``needs_confirmation`` as before (re-ask with ``confirm``).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

KEY_PREFIX = "sajha_confirm_"
METHOD = "elicitation/create"
SCHEMA = {"type": "object",
          "properties": {"confirm": {"type": "boolean", "title": "Run this tool", "default": False}},
          "required": ["confirm"]}


def key_for(fingerprint: str) -> str:
    return f"{KEY_PREFIX}{fingerprint}"


def message_for(pending: Dict[str, Any]) -> str:
    """The question put to the user for one pending call (``{name, arguments, reason, ...}``)."""
    args = json.dumps(pending.get("arguments") or {}, sort_keys=True, default=str, ensure_ascii=False)
    if len(args) > 400:
        args = args[:399] + "…"
    reason = str(pending.get("reason") or "destructive")
    why = "it can modify or delete data" if reason == "destructive" else reason
    return f"Ask SAJHA wants to run '{pending.get('name')}' with {args} ({why}). Run it?"


def request_for(pending: Dict[str, Any]) -> Dict[str, Any]:
    """The form-mode elicitation for one pending call; its schema also says which tool it confirms."""
    from sajha.core.mcp_mrtr import elicitation_request
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["confirm"]["description"] = f"Confirm running {pending.get('name')}"
    return elicitation_request(message_for(pending), schema)


def decision_of(response: Any) -> bool:
    """True when the user accepted and ticked ``confirm``; anything else (declined, cancelled) is no."""
    from sajha.core.mcp_mrtr import accepted_content
    content = accepted_content(response)
    return bool(content is not None and content.get("confirm") is True)


class ClientConfirmer:
    """A way to ask the calling client's user. ``kind`` is ``mrtr`` or ``session``."""
    kind = ""

    def decide(self, pending: Dict[str, Any]) -> Optional[bool]:      # pragma: no cover
        """True: run it; False: the user said no; None: not answered yet (MRTR asks after the step)."""
        raise NotImplementedError

    def ask(self, pending: List[Dict[str, Any]]) -> None:
        """Ask for the calls still unanswered (MRTR raises ``InputRequired``; a session asked already)."""
        return None


class MRTRConfirmer(ClientConfirmer):
    """2026-07-28: the answer comes back in ``inputResponses`` on the client's next call."""
    kind = "mrtr"

    def __init__(self, tool_ctx: Any):
        self.ctx = tool_ctx

    def decide(self, pending: Dict[str, Any]) -> Optional[bool]:
        resp = (self.ctx.input_responses or {}).get(key_for(str(pending.get("fingerprint") or "")))
        if resp is None:
            return None
        return decision_of(resp)

    def ask(self, pending: List[Dict[str, Any]]) -> None:
        requests = {key_for(str(p.get("fingerprint") or "")): request_for(p) for p in pending}
        if requests:
            self.ctx.require_input(requests)          # raises InputRequired


class SessionConfirmer(ClientConfirmer):
    """2025-11-25: a server request on the session's response stream, answered by a client POST."""
    kind = "session"

    def __init__(self, call_ctx: Any, loop: asyncio.AbstractEventLoop, timeout_s: float = 300.0):
        self.call_ctx = call_ctx
        self.loop = loop
        self.timeout_s = timeout_s

    def decide(self, pending: Dict[str, Any]) -> Optional[bool]:
        params = request_for(pending)["params"]
        fut = asyncio.run_coroutine_threadsafe(self.call_ctx.request(METHOD, params, timeout=self.timeout_s),
                                               self.loop)
        try:
            return decision_of(fut.result(self.timeout_s + 5))
        except Exception as e:
            fut.cancel()
            logger.info(f"ask: the client did not answer the confirmation for {pending.get('name')} ({e})")
            return None                                # falls back to needs_confirmation


_SESSION: contextvars.ContextVar = contextvars.ContextVar("sajha_session_confirmer", default=None)   # (tool, confirmer)


@contextmanager
def bound(confirmer: Optional[ClientConfirmer], tool_name: str) -> Iterator[None]:
    """Make ``confirmer`` the confirmation channel of ``tool_name`` for the code inside (the 2025-11-25
    transport binds it around the tools/call it streams)."""
    token = _SESSION.set((tool_name, confirmer))
    try:
        yield
    finally:
        _SESSION.reset(token)


def client_confirmer(tool_name: str) -> Optional[ClientConfirmer]:
    """The calling client's confirmation channel when ``tool_name`` is the MCP call's own tool and the
    client declared form-mode elicitation, else None."""
    bound_to = _SESSION.get()
    if bound_to is not None:
        return bound_to[1] if bound_to[0] == tool_name else None
    try:
        from sajha.core.mcp_mrtr import elicitation_form_supported
        from sajha.core.mcp_tool_context import TransportToolContext, current_context
        mctx = current_context()
        if mctx is not None and not isinstance(mctx, TransportToolContext) and \
                getattr(mctx, "tool_name", None) == tool_name and elicitation_form_supported(mctx.client_capabilities):
            return MRTRConfirmer(mctx)
    except Exception:
        return None
    return None


def wants_confirmation(tool: Any) -> bool:
    """Does this tool (an answer-mode LLM tool) run other tools that may need the user's confirmation?"""
    spec = getattr(tool, "spec", None)
    return getattr(spec, "mode", "") == "answer"
