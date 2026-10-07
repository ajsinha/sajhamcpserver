"""
SAJHA Intelligence Layer — converters between the legacy types (types.py) and the canonical
Chat Completions format (canonical.py).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Lossless both ways for everything the legacy types can express, so callers move to the
canonical format one at a time:

    to_canonical_request(ChatRequest)      -> ChatCompletionRequest
    from_canonical_request(request)        -> ChatRequest
    to_canonical_response(ChatResponse)    -> ChatCompletion
    from_canonical_response(completion)    -> ChatResponse
    chunks_from_events(events)             legacy stream events -> ChatCompletionChunk
    events_from_chunks(chunks)             ChatCompletionChunk  -> legacy stream events

What the legacy types cannot express (developer role, participant names, http image URLs,
top_p, seed, n, reasoning_effort, logprobs, ...) is dropped by ``from_canonical_request``;
that direction is used only for models still written against ``generate(ChatRequest)``.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterable, Iterator, List, Optional

from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChatMessage,
                                    Choice, ChoiceDelta, ChunkAccumulator, ChunkChoice, CompletionUsage,
                                    ContentPart, DeltaFunction, DeltaToolCall, MessageSajha, ResponseFormat,
                                    ResponseSajha, SajhaRequest, ToolCall, ToolDefinition, new_id,
                                    parse_arguments, split_data_url)
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, TextDelta, TextPart,
                                ToolCallDelta, ToolCallPart, ToolResultPart, ToolSpec, Usage, UsageEvent)


# ── requests ─────────────────────────────────────────────────────

def message_to_canonical(m: Message, provider_hint: str = "") -> List[ChatMessage]:
    """One legacy Message -> one or more canonical messages (tool results become tool messages)."""
    out: List[ChatMessage] = []
    if m.role == "tool" or (m.role == "user" and m.tool_results):
        for r in m.tool_results:
            out.append(ChatMessage.tool(r.call_id, r.content, is_error=r.is_error, tool_name=r.name))
        rest = [p for p in m.parts if not isinstance(p, ToolResultPart)]
        if m.role == "tool" or not rest:
            return out
        m = Message(m.role, rest, meta=m.meta)
    if m.role == "assistant":
        calls = [ToolCall.of(c.id, c.name, c.arguments) for c in m.tool_calls]
        msg = ChatMessage(role="assistant", content=m.text or None, tool_calls=calls or None)
        if m.meta:
            state = {k: v for k, v in m.meta.items() if k != "provider"}
            msg.sajha = MessageSajha(provider=m.meta.get("provider", provider_hint), provider_state=state or None)
        out.append(msg)
        return out
    parts = []
    for p in m.parts:
        if isinstance(p, TextPart):
            parts.append(ContentPart.of_text(p.text))
        elif isinstance(p, ImagePart):
            parts.append(ContentPart.of_image(p.data, p.mime_type))
    if any(p.type != "text" for p in parts) or len(parts) > 1:
        out.append(ChatMessage(role=m.role, content=parts))
    else:
        out.append(ChatMessage(role=m.role, content=m.text))
    return out


def to_canonical_request(req: ChatRequest, model: str = "default") -> ChatCompletionRequest:
    messages: List[ChatMessage] = []
    if req.system:
        messages.append(ChatMessage(role="system", content=req.system, sajha=MessageSajha(system_field=True)))
    for m in req.messages:
        messages.extend(message_to_canonical(m))
    tc: Any = req.tool_choice or "auto"
    if tc not in ("auto", "none", "required"):
        tc = {"type": "function", "function": {"name": tc}}
    return ChatCompletionRequest(
        model=model, messages=messages,
        tools=[ToolDefinition.of(t.name, t.description, t.input_schema) for t in req.tools] or None,
        tool_choice=(tc if req.tools else None) if tc != "auto" else None,
        response_format=ResponseFormat.of_schema(req.response_schema) if req.response_schema else None,
        temperature=req.temperature, max_completion_tokens=req.max_output_tokens,
        stop=list(req.stop) or None,
        sajha=SajhaRequest(context=req.metadata, trace_id=(req.metadata.trace_id if req.metadata else "")))


def _image_part(p: ContentPart) -> ImagePart:
    mime, data = split_data_url(p.image_url.url if p.image_url else "")
    return ImagePart(base64.b64decode(data), mime)


def from_canonical_request(req: ChatCompletionRequest) -> ChatRequest:
    system: List[str] = []
    messages: List[Message] = []
    for m in req.messages:
        if m.role == "system" and m.sajha and m.sajha.system_field:
            system.append(m.text)
            continue
        if m.role in ("system", "developer"):
            messages.append(Message.system(m.text))
        elif m.role == "user":
            parts: List[Any] = []
            for p in m.parts:
                if p.type == "text":
                    parts.append(TextPart(p.text or ""))
                elif p.type == "image_url":
                    parts.append(_image_part(p))
            messages.append(Message("user", parts))
        elif m.role == "assistant":
            parts = [TextPart(m.text)] if m.text else []
            if m.refusal and not m.text:
                parts.append(TextPart(m.refusal))
            parts += [ToolCallPart(c.id, c.function.name, c.function.args()) for c in m.tool_calls or []]
            meta: Dict[str, Any] = {}
            if m.sajha and m.sajha.provider_state:
                meta = dict(m.sajha.provider_state)
                meta["provider"] = m.sajha.provider
            messages.append(Message("assistant", parts, meta=meta))
        elif m.role == "tool":
            sj = m.sajha or MessageSajha()
            content: Any = m.text
            if sj.structured:
                try:
                    content = json.loads(content)
                except Exception:
                    pass
            messages.append(Message.tool_result(m.tool_call_id or "", content, sj.is_error, sj.tool_name))
    tc = req.tool_choice_mode
    tool_choice = req.tool_choice_name if tc == "named" else tc
    ctx = req.context
    return ChatRequest(
        messages=messages, system="\n\n".join(s for s in system if s),
        tools=[ToolSpec(t.name, (t.function.description or "") if t.function else "", t.parameters_or_default)
               for t in req.tools or []],
        tool_choice=tool_choice, response_schema=req.output_schema if req.output_kind == "json_schema" else (
            {"type": "object"} if req.output_kind == "json_object" else None),
        temperature=req.temperature, max_output_tokens=req.max_output_tokens, stop=req.stop_list,
        metadata=ctx)


# ── responses ────────────────────────────────────────────────────

def usage_to_canonical(u: Usage) -> CompletionUsage:
    return CompletionUsage.of(u.input_tokens, u.output_tokens, u.cached_tokens if u.cached_tokens else None)


def usage_from_canonical(u: Optional[CompletionUsage], cost_usd: float = 0.0) -> Usage:
    if u is None:
        return Usage(cost_usd=cost_usd)
    return Usage(u.prompt_tokens, u.completion_tokens, u.cached_tokens, cost_usd)


def assistant_to_canonical(m: Message, provider: str = "") -> ChatMessage:
    return message_to_canonical(Message("assistant", list(m.parts), meta=m.meta), provider)[0]


def to_canonical_response(resp: ChatResponse) -> ChatCompletion:
    msg = assistant_to_canonical(resp.message, resp.provider)
    finish = resp.finish_reason if resp.finish_reason in ("stop", "length", "tool_calls", "content_filter") \
        else "stop"
    if resp.refusal:
        msg.refusal = resp.refusal
    comp = ChatCompletion(model=resp.model, choices=[Choice(index=0, message=msg, finish_reason=finish)],
                          usage=usage_to_canonical(resp.usage),
                          sajha=ResponseSajha(provider=resp.provider, qualified_model=f"{resp.provider}/{resp.model}",
                                              cost_usd=resp.usage.cost_usd, cached=resp.cached,
                                              latency_ms=resp.latency_ms,
                                              ignored=list((resp.notes or {}).get("ignored", [])),
                                              usage_estimated=bool((resp.notes or {}).get("usage_estimated")),
                                              structured_output=(resp.notes or {}).get("structured_output")))
    comp._raw = resp.raw
    return comp


def assistant_from_canonical(m: ChatMessage) -> Message:
    parts: List[Any] = [TextPart(m.text)] if m.text else []
    parts += [ToolCallPart(c.id, c.function.name, c.function.args()) for c in m.tool_calls or []]
    meta: Dict[str, Any] = {}
    if m.sajha and m.sajha.provider_state:
        meta = dict(m.sajha.provider_state)
        meta["provider"] = m.sajha.provider
    return Message("assistant", parts, meta=meta)


def from_canonical_response(comp: ChatCompletion) -> ChatResponse:
    sj = comp.sajha or ResponseSajha()
    notes: Dict[str, Any] = {}
    if sj.ignored:
        notes["ignored"] = list(sj.ignored)
    if sj.usage_estimated:
        notes["usage_estimated"] = True
    if sj.structured_output:
        notes["structured_output"] = sj.structured_output
    if sj.attempts:
        notes["attempts"] = list(sj.attempts)
    return ChatResponse(assistant_from_canonical(comp.message), comp.finish_reason,
                        usage_from_canonical(comp.usage, sj.cost_usd), comp.model, sj.provider, sj.latency_ms,
                        raw=comp.raw, cached=sj.cached, refusal=comp.refusal or "", notes=notes)


# ── streams ──────────────────────────────────────────────────────

def chunks_from_events(events: Iterable[Any]) -> Iterator[ChatCompletionChunk]:
    """Legacy stream events -> chunks (deltas as they come, the Done response as the finish)."""
    cid = new_id()
    started = False
    seen_calls: Dict[int, bool] = {}
    for ev in events:
        if isinstance(ev, TextDelta):
            if ev.text:
                yield ChatCompletionChunk(id=cid, choices=[ChunkChoice(delta=ChoiceDelta(
                    role=None if started else "assistant", content=ev.text))])
                started = True
        elif isinstance(ev, ToolCallDelta):
            first = not seen_calls.get(ev.index)
            seen_calls[ev.index] = True
            yield ChatCompletionChunk(id=cid, choices=[ChunkChoice(delta=ChoiceDelta(
                role=None if started else "assistant",
                tool_calls=[DeltaToolCall(index=ev.index, id=(ev.id or None) if first else None,
                                          type="function" if first else None,
                                          function=DeltaFunction(name=ev.name or None,
                                                                 arguments=ev.arguments_json_fragment or None))]))])
            started = True
        elif isinstance(ev, Done):
            comp = to_canonical_response(ev.response)
            m = comp.message
            if not started and (m.text or m.tool_calls):    # a non-streaming model: replay the content
                yield ChatCompletionChunk(id=cid, choices=[ChunkChoice(delta=ChoiceDelta(
                    role="assistant", content=m.text or None))])
                if m.tool_calls:
                    yield ChatCompletionChunk(id=cid, choices=[ChunkChoice(delta=ChoiceDelta(tool_calls=[
                        DeltaToolCall(index=i, id=c.id, type="function",
                                      function=DeltaFunction(name=c.function.name, arguments=c.function.arguments))
                        for i, c in enumerate(m.tool_calls)]))])
            yield ChatCompletionChunk(id=cid, model=comp.model, choices=[ChunkChoice(
                delta=ChoiceDelta(refusal=m.refusal, sajha=m.sajha), finish_reason=comp.finish_reason)])
            yield ChatCompletionChunk(id=cid, model=comp.model, choices=[], usage=comp.usage, sajha=comp.sajha)


def events_from_chunks(chunks: Iterable[ChatCompletionChunk]) -> Iterator[Any]:
    """Chunks -> legacy events: TextDelta / ToolCallDelta as they come, then UsageEvent and Done."""
    acc = ChunkAccumulator()
    names: Dict[int, str] = {}
    ids: Dict[int, str] = {}
    for c in chunks:
        acc.add(c)
        for ch in c.choices:
            if ch.index != 0:
                continue
            d = ch.delta
            if d.content:
                yield TextDelta(d.content)
            for tc in d.tool_calls or []:
                if tc.id:
                    ids[tc.index] = tc.id
                fn = tc.function or DeltaFunction()
                if fn.name:
                    names[tc.index] = names.get(tc.index, "") + fn.name
                yield ToolCallDelta(ids.get(tc.index, ""), fn.name or "", fn.arguments or "", tc.index)
    resp = from_canonical_response(acc.result())
    yield UsageEvent(resp.usage)
    yield Done(resp)


def parse_args_text(s: str) -> Dict[str, Any]:
    return parse_arguments(s)
