"""
SAJHA Intelligence Layer — the canonical model format: OpenAI Chat Completions, typed.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every model call in SAJHA can be expressed in these types. They are pydantic models of the
OpenAI Chat Completions and Embeddings shapes, so a request stripped of its ``sajha`` field is
a valid OpenAI request and a response stripped of ``sajha`` is a valid OpenAI response.
Provider adapters (``sajha/ai/llm/providers/``) translate them to each vendor at the edge.
What is supported, passed through or refused is docs/architecture/LLM Tools.md §13.6.

Public API (stable; the LLM-tool type builds on it):

    Requests     ChatCompletionRequest, ChatMessage, ContentPart, ImageURL, ToolDefinition,
                 FunctionDefinition, ToolCall, FunctionCall, ResponseFormat, JSONSchemaFormat,
                 StreamOptions, SajhaRequest
    Responses    ChatCompletion, Choice, CompletionUsage, PromptTokensDetails,
                 CompletionTokensDetails, ResponseSajha, MessageSajha
    Streaming    ChatCompletionChunk, ChunkChoice, ChoiceDelta, DeltaToolCall, DeltaFunction,
                 ChunkAccumulator (chunks -> one ChatCompletion), completion_to_chunks
    Embeddings   EmbeddingsRequest, EmbeddingsResponse, EmbeddingData, EmbeddingsUsage
    Rules        check_request (provider-independent refusals), passthrough_used (fields only
                 OpenAI-compatible servers understand), FINISH_REASONS

    from sajha.ai.llm.canonical import ChatCompletionRequest, ChatMessage
    req = ChatCompletionRequest(model="reasoning", messages=[ChatMessage.user("Hello")])
    completion = gateway.chat_completions_create(req)          # or **fields
    completion.text, completion.tool_calls, completion.sajha.cost_usd

SAJHA-only data rides in ``sajha``: on a request the caller's RequestContext (identity for
policy and budgets, the access check for tool calls), capability needs and the embedding input
purpose; on a response the provider, qualified model, cost, cache hit, latency, fallback
attempts, trace id and the markers ``ignored``, ``usage_estimated`` and ``structured_output``.
Provider round-trip state (Anthropic thinking blocks, Gemini thought signatures) rides on an
assistant message's ``sajha.provider_state``, which is excluded from every dump and never logged.
"""

from __future__ import annotations

import base64
import json
import struct
import time
import uuid
from typing import Any, Dict, Iterable, Iterator, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from sajha.ai.llm.errors import InvalidRequest

FINISH_REASONS = ("stop", "length", "tool_calls", "content_filter")
ROLES = ("system", "developer", "user", "assistant", "tool")
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")


class _Model(BaseModel):
    """Base: unknown fields are kept (so they can be refused by name, or passed through)."""
    model_config = ConfigDict(extra="allow", populate_by_name=True, protected_namespaces=(),
                              arbitrary_types_allowed=True)

    def to_dict(self, **kw) -> Dict[str, Any]:
        """The wire form: aliases, no None values, SAJHA's private state excluded."""
        return self.model_dump(by_alias=True, exclude_none=True, mode="json", **kw)


def new_id(prefix: str = "chatcmpl") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:24]}"


# ── Request pieces ────────────────────────────────────────────────

class FunctionCall(_Model):
    name: str = ""
    arguments: str = "{}"                      # a JSON string, as in OpenAI

    def args(self) -> Dict[str, Any]:
        """The arguments parsed to a dict (``{"_raw": text}`` when not valid JSON)."""
        return parse_arguments(self.arguments)


class ToolCall(_Model):
    id: str
    type: str = "function"
    function: FunctionCall = Field(default_factory=FunctionCall)

    @classmethod
    def of(cls, id: str, name: str, arguments: Any) -> "ToolCall":
        args = arguments if isinstance(arguments, str) else json.dumps(arguments or {}, ensure_ascii=False)
        return cls(id=id, function=FunctionCall(name=name, arguments=args))


class ImageURL(_Model):
    url: str
    detail: Optional[str] = None


class ContentPart(_Model):
    """A content part. ``text`` and ``image_url`` are supported; any other ``type`` is refused."""
    type: str
    text: Optional[str] = None
    image_url: Optional[ImageURL] = None

    @classmethod
    def of_text(cls, text: str) -> "ContentPart":
        return cls(type="text", text=text)

    @classmethod
    def of_image(cls, data: bytes, mime_type: str = "image/png", detail: Optional[str] = None) -> "ContentPart":
        url = f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"
        return cls(type="image_url", image_url=ImageURL(url=url, detail=detail))


class MessageSajha(_Model):
    """SAJHA's own data on a message. ``provider_state`` never leaves the process."""
    is_error: bool = False                     # role tool: the result is an error
    tool_name: str = ""                        # role tool: the tool's name (Gemini, Ollama need it)
    structured: bool = False                   # role tool: content is JSON text of a structured value
    system_field: bool = False                 # role system: came from the legacy ChatRequest.system
    provider: str = ""                         # role assistant: the provider instance that wrote it
    provider_state: Optional[Dict[str, Any]] = Field(default=None, exclude=True, repr=False)


class ChatMessage(_Model):
    role: str
    content: Union[str, List[ContentPart], None] = None
    name: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    refusal: Optional[str] = None
    annotations: Optional[List[Dict[str, Any]]] = None
    sajha: Optional[MessageSajha] = None

    # constructors
    @classmethod
    def system(cls, text: str) -> "ChatMessage":
        return cls(role="system", content=text)

    @classmethod
    def developer(cls, text: str) -> "ChatMessage":
        return cls(role="developer", content=text)

    @classmethod
    def user(cls, content: Union[str, List[ContentPart]]) -> "ChatMessage":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, text: Optional[str] = None, tool_calls: Optional[List[ToolCall]] = None) -> "ChatMessage":
        return cls(role="assistant", content=text or None, tool_calls=tool_calls or None)

    @classmethod
    def tool(cls, tool_call_id: str, content: Any, *, is_error: bool = False, tool_name: str = "") -> "ChatMessage":
        structured = not isinstance(content, str)
        text = content if isinstance(content, str) else json.dumps(content, default=str, ensure_ascii=False)
        sj = MessageSajha(is_error=is_error, tool_name=tool_name, structured=structured) \
            if (is_error or tool_name or structured) else None
        return cls(role="tool", tool_call_id=tool_call_id, content=text, sajha=sj)

    # views
    @property
    def text(self) -> str:
        """All text content joined (image parts skipped)."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "".join(p.text or "" for p in self.content if p.type == "text")
        return ""

    @property
    def parts(self) -> List[ContentPart]:
        if isinstance(self.content, list):
            return list(self.content)
        return [ContentPart.of_text(self.content)] if isinstance(self.content, str) and self.content else []

    @property
    def images(self) -> List[ContentPart]:
        return [p for p in self.parts if p.type == "image_url"]

    @property
    def provider_state(self) -> Optional[Dict[str, Any]]:
        return self.sajha.provider_state if self.sajha else None

    def state_for(self, provider: str) -> Optional[Dict[str, Any]]:
        """Round-trip state, only when it was written by ``provider`` (never sent elsewhere)."""
        if self.sajha and self.sajha.provider == provider and self.sajha.provider_state:
            return self.sajha.provider_state
        return None

    @property
    def is_error(self) -> bool:
        return bool(self.sajha and self.sajha.is_error)


class FunctionDefinition(_Model):
    name: str
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    strict: Optional[bool] = None


class ToolDefinition(_Model):
    type: str = "function"
    function: Optional[FunctionDefinition] = None

    @classmethod
    def of(cls, name: str, description: str = "", parameters: Optional[Dict[str, Any]] = None,
           strict: Optional[bool] = None) -> "ToolDefinition":
        return cls(function=FunctionDefinition(name=name, description=description or None,
                                               parameters=parameters, strict=strict))

    @property
    def name(self) -> str:
        return self.function.name if self.function else ""

    @property
    def parameters_or_default(self) -> Dict[str, Any]:
        p = self.function.parameters if self.function else None
        return p if isinstance(p, dict) and p else {"type": "object", "properties": {}}


class JSONSchemaFormat(_Model):
    name: str = "response"
    description: Optional[str] = None
    schema_: Optional[Dict[str, Any]] = Field(default=None, alias="schema")
    strict: Optional[bool] = None


class ResponseFormat(_Model):
    type: str = "text"                         # text | json_object | json_schema
    json_schema: Optional[JSONSchemaFormat] = None

    @classmethod
    def of_schema(cls, schema: Dict[str, Any], name: str = "response", strict: Optional[bool] = None
                  ) -> "ResponseFormat":
        return cls(type="json_schema", json_schema=JSONSchemaFormat(name=name, schema=schema, strict=strict))


class StreamOptions(_Model):
    include_usage: Optional[bool] = None


class SajhaRequest(_Model):
    """SAJHA's own request data; never sent to a vendor."""
    context: Optional[Any] = Field(default=None, exclude=True)   # RequestContext (identity, roles, ...)
    needs: Optional[Any] = Field(default=None, exclude=True)     # extra capability needs ("tools+fast")
    trace_id: str = ""
    input_purpose: Optional[Literal["query", "document"]] = None   # embeddings only


class ChatCompletionRequest(_Model):
    """A Chat Completions request. ``model`` is an alias (``default``) or ``provider/model``."""
    model: str = "default"
    messages: List[ChatMessage] = Field(default_factory=list)
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    parallel_tool_calls: Optional[bool] = None
    response_format: Optional[ResponseFormat] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_completion_tokens: Optional[int] = None
    max_tokens: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    seed: Optional[int] = None
    n: Optional[int] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    logit_bias: Optional[Dict[str, Any]] = None
    logprobs: Optional[bool] = None
    top_logprobs: Optional[int] = None
    stream: Optional[bool] = None
    stream_options: Optional[StreamOptions] = None
    user: Optional[str] = None
    metadata: Optional[Dict[str, str]] = None
    store: Optional[bool] = None
    service_tier: Optional[str] = None
    reasoning_effort: Optional[str] = None
    modalities: Optional[List[str]] = None
    prediction: Optional[Dict[str, Any]] = None
    extra_body: Optional[Dict[str, Any]] = None     # provider-specific options with no standard field
    sajha: Optional[SajhaRequest] = None

    @classmethod
    def coerce(cls, request: Any = None, **fields) -> "ChatCompletionRequest":
        """Accept a request object, a dict, keyword fields, or a request plus field overrides."""
        if request is None:
            return cls.model_validate(fields)
        if isinstance(request, cls):
            return request.model_copy(update=fields) if fields else request
        if isinstance(request, dict):
            return cls.model_validate({**request, **fields})
        raise InvalidRequest(f"not a chat completion request: {type(request).__name__}")

    # derived views used by the adapters
    @property
    def context(self) -> Any:
        return self.sajha.context if self.sajha else None

    @property
    def max_output_tokens(self) -> Optional[int]:
        """``max_completion_tokens`` wins over ``max_tokens``."""
        return self.max_completion_tokens if self.max_completion_tokens is not None else self.max_tokens

    @property
    def stop_list(self) -> List[str]:
        if self.stop is None:
            return []
        return [self.stop] if isinstance(self.stop, str) else [s for s in self.stop if s]

    @property
    def tool_choice_mode(self) -> str:
        """auto | none | required | named"""
        tc = self.tool_choice
        if tc is None:
            return "auto"
        if isinstance(tc, dict):
            return "named"
        return tc

    @property
    def tool_choice_name(self) -> str:
        tc = self.tool_choice
        if isinstance(tc, dict):
            return ((tc.get("function") or {}).get("name")) or ""
        return ""

    @property
    def wants_tools(self) -> bool:
        return bool(self.tools) and self.tool_choice_mode != "none"

    @property
    def has_images(self) -> bool:
        return any(m.images for m in self.messages)

    @property
    def output_kind(self) -> Optional[str]:
        """json_schema | json_object | None (plain text)."""
        rf = self.response_format
        if rf is None or rf.type == "text":
            return None
        return rf.type

    @property
    def output_schema(self) -> Optional[Dict[str, Any]]:
        rf = self.response_format
        if rf is not None and rf.type == "json_schema" and rf.json_schema is not None:
            return rf.json_schema.schema_
        return None

    @property
    def include_usage(self) -> bool:
        return bool(self.stream_options and self.stream_options.include_usage)

    def cache_key(self) -> Dict[str, Any]:
        """A JSON-able form for the response cache: the request without delivery-only fields."""
        d = self.to_dict(exclude={"sajha", "stream", "stream_options", "user", "metadata", "model"})
        for m, raw in zip(d.get("messages") or [], self.messages):
            if raw.sajha and raw.sajha.provider_state:
                m["_state"] = json.dumps(raw.sajha.provider_state, sort_keys=True, default=str)
        return d

    def openai_dict(self) -> Dict[str, Any]:
        """The request as an OpenAI wire body (``sajha`` and SAJHA-meaning fields removed)."""
        d = self.to_dict(exclude={"sajha", "user", "metadata", "store", "extra_body"})
        for m in d.get("messages") or []:
            m.pop("sajha", None)
        return d


# ── Responses ────────────────────────────────────────────────────

class PromptTokensDetails(_Model):
    cached_tokens: Optional[int] = None


class CompletionTokensDetails(_Model):
    reasoning_tokens: Optional[int] = None


class CompletionUsage(_Model):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_tokens_details: Optional[PromptTokensDetails] = None
    completion_tokens_details: Optional[CompletionTokensDetails] = None

    @classmethod
    def of(cls, prompt: int, completion: int, cached: Optional[int] = None,
           reasoning: Optional[int] = None) -> "CompletionUsage":
        prompt, completion = int(prompt or 0), int(completion or 0)
        return cls(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion,
                   prompt_tokens_details=PromptTokensDetails(cached_tokens=int(cached)) if cached is not None else None,
                   completion_tokens_details=(CompletionTokensDetails(reasoning_tokens=int(reasoning))
                                              if reasoning is not None else None))

    @property
    def cached_tokens(self) -> int:
        return int((self.prompt_tokens_details.cached_tokens or 0) if self.prompt_tokens_details else 0)

    @property
    def reasoning_tokens(self) -> Optional[int]:
        return self.completion_tokens_details.reasoning_tokens if self.completion_tokens_details else None

    def __add__(self, other: "CompletionUsage") -> "CompletionUsage":
        def _sum(a, b):
            return None if a is None and b is None else (a or 0) + (b or 0)
        return CompletionUsage.of(self.prompt_tokens + other.prompt_tokens,
                                  self.completion_tokens + other.completion_tokens,
                                  _sum(self.prompt_tokens_details and self.prompt_tokens_details.cached_tokens,
                                       other.prompt_tokens_details and other.prompt_tokens_details.cached_tokens),
                                  _sum(self.reasoning_tokens, other.reasoning_tokens))


class ResponseSajha(_Model):
    """SAJHA's markers on a response (or on the last chunk of a stream)."""
    provider: str = ""
    qualified_model: str = ""
    cost_usd: float = 0.0
    cached: bool = False                        # served from the gateway's response cache
    latency_ms: int = 0
    attempts: List[Dict[str, str]] = Field(default_factory=list)   # fallback attempts before this one
    trace_id: str = ""
    ignored: List[str] = Field(default_factory=list)               # parameters left out on the caller's behalf
    usage_estimated: bool = False
    structured_output: Optional[str] = None                        # native | emulated
    citations: Optional[List[Dict[str, Any]]] = None


class Choice(_Model):
    index: int = 0
    message: ChatMessage = Field(default_factory=lambda: ChatMessage(role="assistant"))
    finish_reason: Optional[str] = "stop"
    logprobs: Optional[Any] = None


class ChatCompletion(_Model):
    id: str = Field(default_factory=new_id)
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: List[Choice] = Field(default_factory=list)
    usage: Optional[CompletionUsage] = None
    system_fingerprint: Optional[str] = None
    service_tier: Optional[str] = None
    sajha: Optional[ResponseSajha] = None
    _raw: Any = PrivateAttr(default=None)       # the vendor payload; never logged

    @property
    def message(self) -> ChatMessage:
        return self.choices[0].message if self.choices else ChatMessage(role="assistant")

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def tool_calls(self) -> List[ToolCall]:
        return list(self.message.tool_calls or [])

    @property
    def refusal(self) -> Optional[str]:
        return self.message.refusal

    @property
    def finish_reason(self) -> str:
        return (self.choices[0].finish_reason if self.choices else None) or "stop"

    @property
    def raw(self) -> Any:
        return self._raw

    def parsed(self) -> Any:
        """Parse the first choice's text as JSON (structured output; tolerant of code fences)."""
        from sajha.ai.llm.types import parse_json_text
        return parse_json_text(self.text)

    def ensure_sajha(self) -> ResponseSajha:
        if self.sajha is None:
            self.sajha = ResponseSajha()
        return self.sajha


# ── Streaming ────────────────────────────────────────────────────

class DeltaFunction(_Model):
    name: Optional[str] = None
    arguments: Optional[str] = None


class DeltaToolCall(_Model):
    index: int = 0
    id: Optional[str] = None
    type: Optional[str] = None
    function: Optional[DeltaFunction] = None


class ChoiceDelta(_Model):
    role: Optional[str] = None
    content: Optional[str] = None
    refusal: Optional[str] = None
    tool_calls: Optional[List[DeltaToolCall]] = None
    sajha: Optional[MessageSajha] = None        # provider round-trip state, on the finishing chunk


class ChunkChoice(_Model):
    index: int = 0
    delta: ChoiceDelta = Field(default_factory=ChoiceDelta)
    finish_reason: Optional[str] = None
    logprobs: Optional[Any] = None


class ChatCompletionChunk(_Model):
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: List[ChunkChoice] = Field(default_factory=list)
    usage: Optional[CompletionUsage] = None
    system_fingerprint: Optional[str] = None
    service_tier: Optional[str] = None
    sajha: Optional[ResponseSajha] = None

    @property
    def is_usage(self) -> bool:
        return self.usage is not None and not self.choices


class ChunkAccumulator:
    """Folds a chunk stream into one ChatCompletion (as OpenAI SDKs' stream helpers do)."""

    def __init__(self):
        self.id, self.created, self.model = "", 0, ""
        self.usage: Optional[CompletionUsage] = None
        self.sajha: Optional[ResponseSajha] = None
        self.fingerprint: Optional[str] = None
        self.service_tier: Optional[str] = None
        self._choices: Dict[int, Dict[str, Any]] = {}

    def add(self, chunk: ChatCompletionChunk) -> None:
        self.id = self.id or chunk.id
        self.created = self.created or chunk.created
        self.model = chunk.model or self.model
        self.fingerprint = chunk.system_fingerprint or self.fingerprint
        self.service_tier = chunk.service_tier or self.service_tier
        if chunk.usage is not None:
            self.usage = chunk.usage
        if chunk.sajha is not None:
            self.sajha = chunk.sajha if self.sajha is None else self.sajha.model_copy(
                update={k: v for k, v in chunk.sajha.model_dump(exclude_unset=True).items()})
        for ch in chunk.choices:
            st = self._choices.setdefault(ch.index, {"content": [], "refusal": [], "calls": {}, "finish": None,
                                                     "sajha": None, "logprobs": []})
            d = ch.delta
            if d.content:
                st["content"].append(d.content)
            if d.refusal:
                st["refusal"].append(d.refusal)
            for tc in d.tool_calls or []:
                slot = st["calls"].setdefault(tc.index, {"id": "", "type": "function", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function is not None:
                    if tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["args"] += tc.function.arguments
            if d.sajha is not None:
                st["sajha"] = d.sajha
            if ch.logprobs is not None:
                st["logprobs"].append(ch.logprobs)
            if ch.finish_reason:
                st["finish"] = ch.finish_reason

    def result(self) -> ChatCompletion:
        choices = []
        for idx in sorted(self._choices):
            st = self._choices[idx]
            calls = [ToolCall(id=c["id"] or f"call_{i}", function=FunctionCall(name=c["name"],
                                                                                arguments=c["args"] or "{}"))
                     for i, c in sorted(st["calls"].items())]
            msg = ChatMessage(role="assistant", content="".join(st["content"]) or None,
                              refusal="".join(st["refusal"]) or None, tool_calls=calls or None,
                              sajha=st["sajha"])
            finish = st["finish"] or ("tool_calls" if calls else "stop")
            choices.append(Choice(index=idx, message=msg, finish_reason=finish,
                                  logprobs=_merge_logprobs(st["logprobs"])))
        if not choices:
            choices = [Choice(index=0, message=ChatMessage(role="assistant"), finish_reason="stop")]
        return ChatCompletion(id=self.id or new_id(), created=self.created or int(time.time()), model=self.model,
                              choices=choices, usage=self.usage, system_fingerprint=self.fingerprint,
                              service_tier=self.service_tier, sajha=self.sajha)


def _merge_logprobs(items: List[Any]) -> Any:
    if not items:
        return None
    if all(isinstance(i, dict) for i in items):
        out: Dict[str, Any] = {}
        for i in items:
            for k, v in i.items():
                if isinstance(v, list):
                    out.setdefault(k, []).extend(v)
                else:
                    out[k] = v
        return out
    return items[-1]


def completion_to_chunks(comp: ChatCompletion, *, include_usage: bool = True) -> Iterator[ChatCompletionChunk]:
    """Replay a finished completion as a stream: role+content, tool calls, finish, usage."""
    base = dict(id=comp.id, created=comp.created, model=comp.model)
    for ch in comp.choices:
        m = ch.message
        yield ChatCompletionChunk(**base, choices=[ChunkChoice(index=ch.index, delta=ChoiceDelta(
            role="assistant", content=m.text or None, refusal=m.refusal))])
        if m.tool_calls:
            yield ChatCompletionChunk(**base, choices=[ChunkChoice(index=ch.index, delta=ChoiceDelta(tool_calls=[
                DeltaToolCall(index=i, id=c.id, type="function",
                              function=DeltaFunction(name=c.function.name, arguments=c.function.arguments))
                for i, c in enumerate(m.tool_calls)]))])
        yield ChatCompletionChunk(**base, choices=[ChunkChoice(index=ch.index, delta=ChoiceDelta(sajha=m.sajha),
                                                               finish_reason=ch.finish_reason or "stop",
                                                               logprobs=ch.logprobs)],
                                  system_fingerprint=comp.system_fingerprint)
    if include_usage:
        yield ChatCompletionChunk(**base, choices=[], usage=comp.usage or CompletionUsage(), sajha=comp.sajha)


# ── Embeddings ───────────────────────────────────────────────────

class EmbeddingsRequest(_Model):
    model: str = "embedding"
    input: Union[str, List[str], List[int], List[List[int]]] = Field(default_factory=list)
    encoding_format: Optional[str] = None      # float | base64
    dimensions: Optional[int] = None
    user: Optional[str] = None
    sajha: Optional[SajhaRequest] = None

    @classmethod
    def coerce(cls, request: Any = None, **fields) -> "EmbeddingsRequest":
        if request is None:
            return cls.model_validate(fields)
        if isinstance(request, cls):
            return request.model_copy(update=fields) if fields else request
        if isinstance(request, dict):
            return cls.model_validate({**request, **fields})
        raise InvalidRequest(f"not an embeddings request: {type(request).__name__}")

    @property
    def is_tokens(self) -> bool:
        inp = self.input
        return bool(inp) and isinstance(inp, list) and not isinstance(inp[0], str)

    @property
    def texts(self) -> List[str]:
        if isinstance(self.input, str):
            return [self.input]
        if self.is_tokens:
            raise InvalidRequest("input as token arrays is passed through to OpenAI-compatible servers only")
        return list(self.input)

    @property
    def purpose(self) -> Optional[str]:
        return self.sajha.input_purpose if self.sajha else None


class EmbeddingData(_Model):
    object: str = "embedding"
    embedding: Union[List[float], str]
    index: int = 0

    @property
    def vector(self) -> List[float]:
        if isinstance(self.embedding, str):
            return decode_base64_floats(self.embedding)
        return list(self.embedding)


class EmbeddingsUsage(_Model):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingsResponse(_Model):
    object: str = "list"
    data: List[EmbeddingData] = Field(default_factory=list)
    model: str = ""
    usage: EmbeddingsUsage = Field(default_factory=EmbeddingsUsage)
    sajha: Optional[ResponseSajha] = None

    @property
    def vectors(self) -> List[List[float]]:
        return [d.vector for d in sorted(self.data, key=lambda d: d.index)]


def encode_base64_floats(vec: List[float]) -> str:
    """OpenAI's base64 encoding: little-endian float32."""
    return base64.b64encode(struct.pack(f"<{len(vec)}f", *vec)).decode("ascii")


def decode_base64_floats(s: str) -> List[float]:
    raw = base64.b64decode(s)
    return list(struct.unpack(f"<{len(raw) // 4}f", raw))


# ── Coverage rules (docs/architecture/LLM Tools.md §13.6) ───────────

_REFUSED_FIELDS = {
    "functions": "deprecated by OpenAI; use tools",
    "function_call": "deprecated by OpenAI; use tool_choice",
    "web_search_options": "search at the vendor bypasses SAJHA's governance; offer SAJHA's search tools as functions",
    "audio": "audio output is not in scope",
}


def _refuse(field: str, why: str) -> InvalidRequest:
    return InvalidRequest(f"'{field}' is not accepted: {why}")


def check_request(req: ChatCompletionRequest) -> None:
    """Refuse what no provider gets (InvalidRequest naming the field). Provider-independent."""
    for k in (req.model_extra or {}):
        raise _refuse(k, _REFUSED_FIELDS.get(k, "not a supported Chat Completions field"))
    if not req.messages:
        raise InvalidRequest("'messages' must not be empty")
    offered = {t.name for t in req.tools or []}
    for i, m in enumerate(req.messages):
        where = f"messages[{i}]"
        for k in (m.model_extra or {}):
            raise _refuse(f"{where}.{k}", "not a supported message field")
        if m.role == "function":
            raise _refuse(f"{where}.role", "role 'function' is deprecated by OpenAI; use role 'tool'")
        if m.role not in ROLES:
            raise InvalidRequest(f"{where}.role: unknown role '{m.role}'")
        if m.role == "tool" and not m.tool_call_id:
            raise InvalidRequest(f"{where}: a tool message needs tool_call_id")
        for j, p in enumerate(m.content if isinstance(m.content, list) else []):
            if p.type in ("input_audio", "file"):
                raise _refuse(f"{where}.content[{j}]", f"content part '{p.type}' is not in scope")
            if p.type == "text":
                continue
            if p.type == "image_url":
                if m.role != "user":
                    raise InvalidRequest(f"{where}.content[{j}]: images are accepted on user messages only")
                if p.image_url is None or not p.image_url.url:
                    raise InvalidRequest(f"{where}.content[{j}]: image_url.url is required")
                continue
            raise _refuse(f"{where}.content[{j}]", f"content part type '{p.type}' is not supported")
    for i, t in enumerate(req.tools or []):
        if t.type != "function":
            raise _refuse(f"tools[{i}]", f"tool type '{t.type}' runs at the vendor, outside SAJHA's access "
                                         f"rules, policy, audit and budgets; SAJHA's tools are offered as functions")
        if t.function is None or not t.function.name:
            raise InvalidRequest(f"tools[{i}].function.name is required")
    tc = req.tool_choice
    if isinstance(tc, dict):
        if tc.get("type") == "allowed_tools":
            raise _refuse("tool_choice", "allowed_tools: offer only the allowed tools instead")
        if tc.get("type") != "function" or not req.tool_choice_name:
            raise InvalidRequest("tool_choice: expected {type: 'function', function: {name}}")
        if req.tool_choice_name not in offered:
            raise InvalidRequest(f"tool_choice names '{req.tool_choice_name}', which is not among the tools offered")
    elif tc is not None and tc not in ("auto", "none", "required"):
        raise InvalidRequest(f"tool_choice: unknown value '{tc}'")
    if tc is not None and tc != "none" and not req.tools:
        if tc == "required" or isinstance(tc, dict):
            raise InvalidRequest("tool_choice requires tools")
    rf = req.response_format
    if rf is not None:
        if rf.type not in ("text", "json_object", "json_schema"):
            raise _refuse("response_format.type", f"'{rf.type}' is not supported")
        if rf.type == "json_schema" and (rf.json_schema is None or not isinstance(rf.json_schema.schema_, dict)):
            raise InvalidRequest("response_format.json_schema.schema is required")
    if req.store:
        raise _refuse("store", "storing completions at a vendor bypasses SAJHA's retention and audit")
    if req.modalities is not None and [m for m in req.modalities if m != "text"]:
        raise _refuse("modalities", "only ['text'] is in scope")
    if req.n is not None and req.n < 1:
        raise InvalidRequest("n must be at least 1")
    if req.reasoning_effort is not None and req.reasoning_effort not in REASONING_EFFORTS:
        raise InvalidRequest(f"reasoning_effort: unknown value '{req.reasoning_effort}'")


def passthrough_used(req: ChatCompletionRequest) -> List[str]:
    """The passed-through features this request uses (only OpenAI-compatible servers take them)."""
    used = [f for f in ("presence_penalty", "frequency_penalty", "logit_bias", "logprobs", "top_logprobs",
                        "service_tier", "prediction") if getattr(req, f) not in (None, False)]
    for i, m in enumerate(req.messages):
        if m.name and m.role != "tool":
            used.append(f"messages[{i}].name")
        for p in m.images:
            url = p.image_url.url if p.image_url else ""
            if not url.startswith("data:"):
                used.append(f"messages[{i}] image http(s) URL")
            if p.image_url and p.image_url.detail not in (None, "auto"):
                used.append(f"messages[{i}] image detail")
    return used


def parse_arguments(s: Any) -> Dict[str, Any]:
    if isinstance(s, dict):
        return s
    if not s:
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {"value": v}
    except Exception:
        return {"_raw": s}


def split_data_url(url: str) -> tuple:
    """``data:<mime>;base64,<data>`` -> (mime, base64 text). Raises InvalidRequest otherwise."""
    if not url.startswith("data:") or ";base64," not in url:
        raise InvalidRequest("only data: URLs (base64) are accepted for images on this provider")
    head, _, data = url.partition(";base64,")
    return head[5:] or "image/png", data


def iter_text(chunks: Iterable[ChatCompletionChunk]) -> Iterator[str]:
    """Convenience: the content deltas of a chunk stream."""
    for c in chunks:
        for ch in c.choices:
            if ch.delta.content:
                yield ch.delta.content
