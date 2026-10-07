"""
SAJHA MCP Server — MCP sampling for LLM tools: the model call goes to the calling client's model.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

An LLM tool with ``llm.sampling: prefer`` or ``require`` (modes ``complete``, ``extract``,
``classify``, ``judge``) sends its model call to the MCP client instead of SAJHA's gateway when
the client declared the ``sampling`` capability and the call is the MCP request's own tool (not an
inner call of a composite, a workflow or another LLM tool). Design and as-built:
docs/architecture/LLM Tools.md §12.

Two channels, one per protocol era:

* **2026-07-28** (stateless): an MRTR input request. The tool raises ``InputRequired`` with a
  ``sampling/createMessage`` request keyed ``sajha_sample_<n>`` (n counts the model calls of the
  run); the client answers in ``inputResponses`` and calls again; the run starts from scratch and
  finds the answer under the same key (sajha/core/mcp_mrtr.py, sajha/core/mcp_tool_context.py).
* **2025-11-25** (sessions): a server request on the session's SSE response stream. The
  transport (sajha/routes/mcp_routes.py) binds a :class:`SessionSampler` for the call; the worker
  thread waits for the client's JSON-RPC response.

Without a channel, ``prefer`` uses SAJHA's own model and ``require`` refuses the call. A sampled
call costs SAJHA nothing: it is recorded in the usage ledger under provider ``client`` with no
cost, and the result cache is not used (the client's model is not part of its key).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from sajha.ai.llm.errors import LLMError

SAMPLING_MODES = ("complete", "extract", "classify", "judge")
SAMPLING_VALUES = ("never", "prefer", "require")
KEY_PREFIX = "sajha_sample_"
METHOD = "sampling/createMessage"


class SamplingFailed(LLMError):
    """The client could not or would not sample (it answered with an error, or timed out)."""
    code = "sampling_failed"


class ClientSampler:
    """A way to ask the calling client's model. ``kind`` is ``mrtr`` or ``session``."""
    kind = ""

    def create_message(self, params: Dict[str, Any], key: str) -> Dict[str, Any]:     # pragma: no cover
        raise NotImplementedError


class MRTRSampler(ClientSampler):
    """2026-07-28: the answer comes back in ``inputResponses`` on the client's next call."""
    kind = "mrtr"

    def __init__(self, tool_ctx: Any):
        self.ctx = tool_ctx

    def create_message(self, params: Dict[str, Any], key: str) -> Dict[str, Any]:
        resp = self.ctx.input_responses.get(key)
        if isinstance(resp, dict):
            return resp
        self.ctx.require_input({key: {"method": METHOD, "params": params}})   # raises InputRequired
        raise SamplingFailed("the client did not answer the sampling request")   # pragma: no cover


class SessionSampler(ClientSampler):
    """2025-11-25: a server request on the session's response stream, answered by a client POST."""
    kind = "session"

    def __init__(self, call_ctx: Any, loop: asyncio.AbstractEventLoop, timeout_s: float = 120.0):
        self.call_ctx = call_ctx
        self.loop = loop
        self.timeout_s = timeout_s

    def create_message(self, params: Dict[str, Any], key: str) -> Dict[str, Any]:
        fut = asyncio.run_coroutine_threadsafe(self.call_ctx.request(METHOD, params, timeout=self.timeout_s),
                                               self.loop)
        try:
            return fut.result(self.timeout_s + 5)
        except Exception as e:
            fut.cancel()
            raise SamplingFailed(f"sampling by the client failed: {e}") from e


_SESSION: contextvars.ContextVar = contextvars.ContextVar("sajha_session_sampler", default=None)   # (tool, sampler)


@contextmanager
def bound(sampler: Optional[ClientSampler], tool_name: str) -> Iterator[None]:
    """Make ``sampler`` the client channel of ``tool_name`` for the code inside (the 2025-11-25
    transport binds it around the tools/call it streams)."""
    token = _SESSION.set((tool_name, sampler))
    try:
        yield
    finally:
        _SESSION.reset(token)


def client_sampler(tool_name: str) -> Optional[ClientSampler]:
    """The calling client's sampling channel when ``tool_name`` is the MCP call's own tool, else None."""
    bound_to = _SESSION.get()
    if bound_to is not None:
        return bound_to[1] if bound_to[0] == tool_name else None
    try:
        from sajha.core.mcp_tool_context import current_context
        mctx = current_context()
    except Exception:
        mctx = None
    if mctx is not None and getattr(mctx, "tool_name", None) == tool_name and mctx.client_supports("sampling"):
        return MRTRSampler(mctx)
    return None


def wants_sampling(tool: Any) -> bool:
    """Does this tool (an LLMTool) use sampling when a client offers it?"""
    spec = getattr(tool, "spec", None)
    return getattr(spec, "sampling", "never") in ("prefer", "require")


# ── format: canonical messages <-> sampling/createMessage ─────────────────

def _text_content(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def to_create_message(messages: List[Any], *, max_tokens: int, temperature: Optional[float] = None,
                      schema: Optional[Dict[str, Any]] = None, tool_name: str = "") -> Dict[str, Any]:
    """``sampling/createMessage`` params for canonical ChatMessages. System text becomes
    ``systemPrompt``; a JSON Schema (structured output) is asked for in words, since sampling has
    no response format."""
    system: List[str] = []
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = getattr(m, "role", "user")
        text = m.text if hasattr(m, "text") else str(m)
        if role in ("system", "developer"):
            system.append(text)
        elif role in ("user", "assistant"):
            out.append({"role": role, "content": _text_content(text)})
    if schema is not None:
        system.append("Reply with only a JSON object (no prose, no code fence) that matches this JSON Schema:\n"
                      + json.dumps(schema, ensure_ascii=False))
    params: Dict[str, Any] = {"messages": out, "maxTokens": int(max_tokens or 1000)}
    if system:
        params["systemPrompt"] = "\n\n".join(s for s in system if s)
    if temperature is not None:
        params["temperature"] = float(temperature)
    if tool_name:
        params["metadata"] = {"sajha_llm_tool": tool_name}
    return params


def result_text(result: Dict[str, Any]) -> str:
    content = result.get("content") if isinstance(result, dict) else None
    items = content if isinstance(content, list) else [content]
    return "".join(c.get("text", "") for c in items if isinstance(c, dict) and c.get("type", "text") == "text")


def to_completion(result: Dict[str, Any], *, trace_id: str = "", latency_ms: int = 0):
    """A canonical ChatCompletion from a CreateMessageResult (provider ``client``, no cost)."""
    from sajha.ai.llm.canonical import ChatCompletion, ChatMessage, Choice, CompletionUsage, ResponseSajha
    if not isinstance(result, dict):
        raise SamplingFailed("the client's sampling result is not an object")
    model = str(result.get("model") or "unknown")
    stop = str(result.get("stopReason") or "endTurn")
    finish = "length" if stop == "maxTokens" else "stop"
    msg = ChatMessage.assistant(result_text(result))
    if stop == "refusal":
        msg.refusal, finish = msg.text or "the client's model refused", "content_filter"
    comp = ChatCompletion(model=model, choices=[Choice(index=0, message=msg, finish_reason=finish)],
                          usage=CompletionUsage.of(0, 0),
                          sajha=ResponseSajha(provider="client", qualified_model=f"client/{model}", cost_usd=0.0,
                                              latency_ms=latency_ms, trace_id=trace_id, usage_estimated=True))
    return comp


def sample(sampler: ClientSampler, key: str, messages: List[Any], *, max_tokens: int,
           temperature: Optional[float], schema: Optional[Dict[str, Any]], tool_name: str, ctx: Any = None):
    """One model call answered by the client; records it in the usage ledger as provider ``client``."""
    params = to_create_message(messages, max_tokens=max_tokens, temperature=temperature, schema=schema,
                               tool_name=tool_name)
    t0 = time.perf_counter()
    result = sampler.create_message(params, key)
    secs = time.perf_counter() - t0
    comp = to_completion(result, trace_id=getattr(ctx, "trace_id", "") or "", latency_ms=int(secs * 1000))
    try:
        from sajha.observability.metrics import record_llm      # metrics and the usage ledger
        record_llm("client", comp.model, "ok", secs, 0, 0, 0.0, ctx=ctx)
    except Exception:
        pass
    return comp
