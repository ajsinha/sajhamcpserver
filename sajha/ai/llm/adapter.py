"""
SAJHA Intelligence Layer — the base for provider adapters over HTTP.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

An adapter translates the canonical format (canonical.py) to one vendor's API and back, at the
edge, once. Over HTTP it implements three pure functions and inherits the I/O, sync and native
async alike:

    wire(request, stream)   -> WireCall(path, body, params)   canonical request -> vendor request
    parse(data, request)    -> ChatCompletion                 vendor reply      -> canonical
    translator(request)     -> StreamTranslator               vendor events     -> chunks

Because the translation is pure, the golden tests (tests/ai/test_golden_translation.py) check
it against recorded vendor payloads without any network.

StreamTranslator turns vendor stream events into ChatCompletionChunk objects: it keeps one id,
assigns tool-call indexes, sends the role on the first delta, and on ``close()`` emits the
finishing chunk (with provider round-trip state) and the usage chunk (estimated, and marked
``sajha.usage_estimated``, when the vendor sent none).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChatMessage,
                                    ChoiceDelta, ChunkChoice, CompletionUsage, DeltaFunction, DeltaToolCall,
                                    MessageSajha, ResponseSajha, new_id)
from sajha.ai.llm.http import (aiter_ndjson, aiter_sse, apost_json, astream_post, iter_ndjson, iter_sse,
                               post_json, safe_json_loads, stream_post)
from sajha.ai.llm.model import ChatModel


@dataclass
class WireCall:
    path: str
    body: Dict[str, Any]
    params: Optional[Dict[str, str]] = None


class StreamTranslator:
    """Vendor stream events -> chunks. Subclasses implement ``feed``; ``close`` finishes."""

    def __init__(self, model: ChatModel, request: ChatCompletionRequest):
        self.model, self.request = model, request
        self.id = new_id()
        self.created = int(time.time())
        self.model_name = model.id
        self.role_sent = False
        self.chars = 0
        self.finish: Optional[str] = None
        self.usage: Optional[CompletionUsage] = None
        self.refusal: Optional[str] = None
        self.state: Optional[Dict[str, Any]] = None
        self._calls: Dict[Any, int] = {}
        self.has_calls = False

    # chunk builders
    def chunk(self, delta: Optional[ChoiceDelta] = None, finish: Optional[str] = None,
              logprobs: Any = None) -> ChatCompletionChunk:
        d = delta or ChoiceDelta()
        if not self.role_sent:
            d.role = "assistant"
            self.role_sent = True
        return ChatCompletionChunk(id=self.id, created=self.created, model=self.model_name,
                                   choices=[ChunkChoice(index=0, delta=d, finish_reason=finish, logprobs=logprobs)])

    def text(self, s: str) -> List[ChatCompletionChunk]:
        if not s:
            return []
        self.chars += len(s)
        return [self.chunk(ChoiceDelta(content=s))]

    def call_index(self, key: Any) -> int:
        if key not in self._calls:
            self._calls[key] = len(self._calls)
        return self._calls[key]

    def tool_start(self, key: Any, call_id: str, name: str, args: str = "") -> List[ChatCompletionChunk]:
        self.has_calls = True
        self.chars += len(args or "")
        return [self.chunk(ChoiceDelta(tool_calls=[DeltaToolCall(
            index=self.call_index(key), id=call_id, type="function",
            function=DeltaFunction(name=name, arguments=args or ""))]))]

    def tool_args(self, key: Any, frag: str) -> List[ChatCompletionChunk]:
        if not frag:
            return []
        self.chars += len(frag)
        return [self.chunk(ChoiceDelta(tool_calls=[DeltaToolCall(index=self.call_index(key),
                                                                 function=DeltaFunction(arguments=frag))]))]

    def feed(self, event: str, data: Any) -> List[ChatCompletionChunk]:      # pragma: no cover - abstract
        raise NotImplementedError

    def close(self) -> List[ChatCompletionChunk]:
        finish = self.finish or ("tool_calls" if self.has_calls else "stop")
        if finish == "stop" and self.has_calls:
            finish = "tool_calls"
        sj = MessageSajha(provider=self.model.provider.name, provider_state=self.state) if self.state else None
        out = [self.chunk(ChoiceDelta(refusal=self.refusal, sajha=sj), finish=finish)]
        usage, estimated = self.usage, False
        if usage is None:
            usage = self.model.estimate_usage(self.request, output_chars=self.chars)
            estimated = True
        out.append(ChatCompletionChunk(id=self.id, created=self.created, model=self.model_name, choices=[],
                                       usage=usage, sajha=ResponseSajha(usage_estimated=estimated)))
        return out


class HTTPChatModel(ChatModel):
    """A chat model reached over HTTP: implement wire / parse / translator; I/O is inherited."""

    stream_format: str = "sse"            # sse | ndjson

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:   # pragma: no cover - abstract
        raise NotImplementedError

    def parse(self, data: Dict[str, Any], request: ChatCompletionRequest) -> ChatCompletion:  # pragma: no cover
        raise NotImplementedError

    def translator(self, request: ChatCompletionRequest) -> StreamTranslator:   # pragma: no cover - abstract
        raise NotImplementedError

    def classify(self, resp) -> Any:
        """Vendor-specific HTTP error mapping (None = the generic map_http_error)."""
        return None

    def _kw(self, call: WireCall, headers: Dict[str, str]) -> Dict[str, Any]:
        return dict(params=call.params, headers=headers or None, provider=self.provider.name, model=self.id,
                    classify=self.classify)

    def _create(self, request: ChatCompletionRequest) -> ChatCompletion:
        call = self.wire(request, False)
        with self.provider.slot():
            data = post_json(self.provider.http, call.path, call.body,
                             **self._kw(call, self.provider.request_headers()))
        comp = self.parse(data, request)
        comp._raw = data
        return comp

    async def _acreate(self, request: ChatCompletionRequest) -> ChatCompletion:
        call = self.wire(request, False)
        headers = await self.provider.arequest_headers()
        async with self.provider.aslot():
            data = await apost_json(self.provider.ahttp, call.path, call.body, **self._kw(call, headers))
        comp = self.parse(data, request)
        comp._raw = data
        return comp

    def _stream(self, request: ChatCompletionRequest) -> Iterator[ChatCompletionChunk]:
        call = self.wire(request, True)
        tr = self.translator(request)
        with self.provider.slot():
            with stream_post(self.provider.http, call.path, call.body,
                             **self._kw(call, self.provider.request_headers())) as resp:
                if self.stream_format == "ndjson":
                    for obj in iter_ndjson(resp):
                        yield from tr.feed("", obj)
                else:
                    for event, data in iter_sse(resp):
                        yield from tr.feed(event, data)
        yield from tr.close()

    async def _astream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        call = self.wire(request, True)
        tr = self.translator(request)
        headers = await self.provider.arequest_headers()
        async with self.provider.aslot():
            async with astream_post(self.provider.ahttp, call.path, call.body, **self._kw(call, headers)) as resp:
                if self.stream_format == "ndjson":
                    async for obj in aiter_ndjson(resp):
                        for c in tr.feed("", obj):
                            yield c
                else:
                    async for event, data in aiter_sse(resp):
                        for c in tr.feed(event, data):
                            yield c
        for c in tr.close():
            yield c


# ── shared translation helpers ────────────────────────────────────

def system_text(request: ChatCompletionRequest) -> str:
    """System and developer messages joined with a blank line (for vendors with one system field)."""
    return "\n\n".join(m.text for m in request.messages if m.role in ("system", "developer") and m.text)


def tool_names(request: ChatCompletionRequest) -> Dict[str, str]:
    """tool_call_id -> function name, from the assistant messages of the history."""
    out: Dict[str, str] = {}
    for m in request.messages:
        for c in m.tool_calls or []:
            out[c.id] = c.function.name
    return out


def tool_result_text(m: ChatMessage, error_prefix: bool = True) -> str:
    """A tool message's content as text; an error result gets an ``ERROR: `` prefix."""
    t = m.text
    return ("ERROR: " + t) if (error_prefix and m.is_error) else t


def assistant_text(m: ChatMessage) -> str:
    """An assistant message's text; a refusal in history is sent as assistant text."""
    return m.text or (m.refusal or "")


def json_loads_maybe(s: str) -> Any:
    v = safe_json_loads(s)
    return None if "_raw" in v and len(v) == 1 else v


def finish_with_calls(finish: str, has_calls: bool) -> str:
    return "tool_calls" if has_calls and finish == "stop" else finish
