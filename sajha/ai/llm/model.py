"""
SAJHA Intelligence Layer — model abstractions.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A provider is a factory for models; a model does the work. One ChatModel / EmbeddingModel
object per configured model, carrying its declared capabilities.

The model interface is shaped like an OpenAI-style client (docs/architecture/LLM Tools.md §13.3):

    class ChatModel:
        chat_completions_create(request=None, **fields)  -> ChatCompletion
        chat_completions_stream(request=None, **fields)  -> Iterator[ChatCompletionChunk]
        achat_completions_create(...)                     -> ChatCompletion        (async)
        achat_completions_stream(...)                     -> AsyncIterator[chunk]  (async)
        capabilities: ModelCapabilities                   what it declares
        info() -> ModelInfo                               like one entry of GET /v1/models

    class EmbeddingModel:
        embeddings_create(request=None, **fields)  -> EmbeddingsResponse

Each call first runs ``prepare``: the provider-independent refusals of canonical.check_request,
then the model's declared capabilities. A feature the model does not declare raises
UnsupportedFeature (the gateway moves to the alias's next candidate), or uses the declared
fallback and says so on the response (``sajha.ignored`` for temperature/top_p on models without
sampling controls, ``sajha.structured_output: "emulated"`` for JSON mode plus validation),
never a silent downgrade.

Writing a model: implement the canonical hooks ``_create(request)`` and, for streaming,
``_stream(request)`` (plus ``_acreate`` / ``_astream`` for native async). Models written
against the original interface (``generate(ChatRequest)`` and optionally ``stream``) keep
working: the base class converts at the boundary (sajha/ai/llm/convert.py).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from typing import (TYPE_CHECKING, Any, AsyncIterator, Dict, FrozenSet, Iterator, List, Optional, Tuple,
                    Union)

from sajha.ai.llm.base import LLMModel
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionChunk, ChatCompletionRequest, ChatMessage,
                                    Choice, CompletionUsage, EmbeddingData, EmbeddingsRequest, EmbeddingsResponse,
                                    EmbeddingsUsage, ResponseFormat, ResponseSajha, check_request,
                                    completion_to_chunks, encode_base64_floats, new_id, passthrough_used)
from sajha.ai.llm.errors import InvalidRequest, ModelFailed, UnsupportedFeature
from sajha.ai.llm.types import ChatRequest, ChatResponse, Done, StreamEvent, Usage

if TYPE_CHECKING:   # pragma: no cover
    from sajha.ai.llm.provider import ProviderBase as LLMProvider

CAPABILITY_FLAGS = ("chat", "tools", "structured_output", "vision", "streaming", "embedding")

# Feature flags added with the canonical format. None on a declaration means "the provider's
# default" (LLMProvider.feature_defaults); resolve() fills them in.
FEATURE_FLAGS = ("json_mode", "strict_tools", "named_tool_choice", "parallel_tool_control", "seed",
                 "stop_sequences", "reasoning_effort", "native_n", "variable_dimensions")


@dataclass(frozen=True)
class ModelCapabilities:
    chat: bool = True
    tools: bool = False
    structured_output: bool = False         # native json_schema output
    vision: bool = False
    streaming: bool = True
    embedding: bool = False
    context_window: int = 0
    max_output_tokens: int = 4096
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    dimensions: int = 0                     # embedding models
    temperature: bool = True                # accepts sampling controls (temperature, top_p)
    forced_tool_choice: bool = True         # accepts tool_choice "required"
    tags: FrozenSet[str] = frozenset()      # "fast", "reasoning", "cheap", "local", "deterministic"
    # canonical-format features (None = the provider's default)
    json_mode: Optional[bool] = None             # response_format json_object (default: = structured_output)
    strict_tools: Optional[bool] = None          # tools[].function.strict
    named_tool_choice: Optional[bool] = None     # tool_choice {function: {name}} (default: = forced_tool_choice)
    parallel_tool_control: Optional[bool] = None # parallel_tool_calls: false
    seed: Optional[bool] = None
    stop_sequences: Optional[bool] = None        # default True
    reasoning_effort: Optional[bool] = None
    native_n: Optional[bool] = None              # n > 1 in one call (else the model makes n calls)
    variable_dimensions: Optional[bool] = None   # embeddings: a requested output size

    def satisfies(self, needs: "Needs") -> bool:
        for flag in needs.flags:
            if not getattr(self, flag, False):
                return False
        if needs.min_context and self.context_window and self.context_window < needs.min_context:
            return False
        return not (needs.tags - self.tags)

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_cost_per_mtok + output_tokens * self.output_cost_per_mtok) / 1_000_000

    def to_dict(self) -> Dict[str, Any]:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["tags"] = sorted(self.tags)
        return d

    def merged(self, **overrides) -> "ModelCapabilities":
        clean = {k: v for k, v in overrides.items() if v is not None and k in self.__dataclass_fields__}
        if "tags" in clean:
            clean["tags"] = frozenset(clean["tags"])
        return replace(self, **clean)

    def resolved(self, defaults: Optional[Dict[str, Any]] = None) -> "ModelCapabilities":
        """Fill the unset feature flags from the provider's defaults, then the global ones."""
        defaults = defaults or {}
        upd: Dict[str, Any] = {}
        for f in FEATURE_FLAGS:
            if getattr(self, f) is not None:
                continue
            v = defaults.get(f)
            if v == "tagged":                       # declared by the model's "reasoning" tag
                v = "reasoning" in self.tags
            if v is None:
                v = {"json_mode": self.structured_output, "named_tool_choice": self.forced_tool_choice,
                     "stop_sequences": True}.get(f, False)
            upd[f] = bool(v)
        return replace(self, **upd) if upd else self


@dataclass(frozen=True)
class Needs:
    """What a caller requires of a model: capability flags, tags, a minimum context."""
    flags: FrozenSet[str] = frozenset()
    tags: FrozenSet[str] = frozenset()
    min_context: int = 0

    @classmethod
    def parse(cls, needs: Any) -> "Needs":
        if needs is None:
            return cls()
        if isinstance(needs, Needs):
            return needs
        if isinstance(needs, ModelCapabilities):
            flags = {f for f in CAPABILITY_FLAGS if f != "chat" and getattr(needs, f)
                     and f != "streaming"}
            return cls(frozenset(flags), frozenset(needs.tags), needs.context_window)
        if isinstance(needs, str):
            needs = [p.strip() for p in needs.replace(",", "+").split("+") if p.strip()]
        flags, tags = set(), set()
        for item in needs:
            (flags if item in CAPABILITY_FLAGS else tags).add(item)
        return cls(frozenset(flags), frozenset(tags))

    def __bool__(self):
        return bool(self.flags or self.tags or self.min_context)


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    display_name: str = ""
    kind: str = "chat"              # "chat" | "embedding"
    source: str = "catalog"         # catalog | config | live | db | registered
    deployment: str = ""            # Azure: the deployment serving this model

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "display_name": self.display_name or self.id, "kind": self.kind,
                "source": self.source, "capabilities": self.capabilities.to_dict()}


@dataclass(frozen=True)
class ModelInfo:
    """One model as ``GET /v1/models`` would list it, with SAJHA's declared capabilities."""
    id: str
    provider: str
    kind: str = "chat"
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    display_name: str = ""
    source: str = "catalog"

    @property
    def qualified_id(self) -> str:
        return f"{self.provider}/{self.id}"

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.qualified_id, "object": "model", "created": 0, "owned_by": self.provider,
                "sajha": {"model": self.id, "kind": self.kind, "display_name": self.display_name or self.id,
                          "source": self.source, "capabilities": self.capabilities.to_dict()}}


@dataclass
class HealthStatus:
    status: str = "ok"              # ok | degraded | down
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "degraded")

    def to_dict(self):
        return {"status": self.status, "detail": self.detail}


def estimate_tokens(text: str) -> int:
    """~4 characters per token; never 0 for non-empty text."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass
class Prepared:
    """A request after the capability check: what is sent, and what SAJHA did on the caller's behalf."""
    request: ChatCompletionRequest
    ignored: List[str] = field(default_factory=list)
    structured: Optional[str] = None            # native | emulated
    schema: Optional[Dict[str, Any]] = None     # emulated: the schema the reply is validated against


def _emulation_note(schema: Dict[str, Any]) -> str:
    return ("Reply with only one JSON object, no prose and no code fences. It must validate against this "
            "JSON Schema:\n" + json.dumps(schema, ensure_ascii=False))


def _schema_error(text: str, schema: Dict[str, Any]) -> Optional[str]:
    from sajha.ai.llm.types import parse_json_text
    try:
        value = parse_json_text(text)
    except Exception as e:
        return f"not valid JSON ({e.__class__.__name__})"
    try:
        import jsonschema
        jsonschema.validate(value, schema)
    except ImportError:                          # pragma: no cover - jsonschema is a dependency
        return None
    except Exception as e:
        return getattr(e, "message", str(e))[:300]
    return None


class ChatModel(LLMModel):
    """One chat model of one provider (the shared implementation of LLMModel for chat)."""

    id: str
    provider: "LLMProvider"
    capabilities: ModelCapabilities = ModelCapabilities()

    def __init__(self, provider: "LLMProvider", model_id: str,
                 capabilities: Optional[ModelCapabilities] = None, **options):
        self.provider = provider
        self.id = model_id
        caps = capabilities if capabilities is not None else self.capabilities
        resolve = getattr(provider, "resolve_capabilities", None)
        self.capabilities = resolve(caps) if resolve else caps.resolved()
        self.options = options

    @property
    def qualified_id(self) -> str:
        return f"{self.provider.name}/{self.id}"

    def info(self) -> ModelInfo:
        return ModelInfo(self.id, self.provider.name, "chat", self.capabilities)

    # ── which interface the subclass implements ───────────────────
    @classmethod
    def _is_canonical(cls) -> bool:
        return cls._create is not ChatModel._create

    @classmethod
    def _has_legacy_generate(cls) -> bool:
        return cls.generate is not ChatModel.generate

    @classmethod
    def _has_legacy_stream(cls) -> bool:
        return cls.stream is not ChatModel.stream

    # ── the canonical interface ───────────────────────────────────
    def chat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        req = ChatCompletionRequest.coerce(request, **fields)
        t0 = time.time()
        prep = self.prepare(req)
        comp = self._run(prep)
        return self._finalize(comp, prep, t0)

    async def achat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        req = ChatCompletionRequest.coerce(request, **fields)
        t0 = time.time()
        prep = self.prepare(req)
        comp = await self._arun(prep)
        return self._finalize(comp, prep, t0)

    def chat_completions_stream(self, request: Any = None, /, **fields) -> Iterator[ChatCompletionChunk]:
        req = ChatCompletionRequest.coerce(request, **fields)
        t0 = time.time()
        prep = self.prepare(req, stream=True)
        if prep.structured == "emulated" or (req.n or 1) > 1 or not self.capabilities.streaming:
            # one answer, replayed as chunks (validation of emulated output needs the whole reply)
            comp = self._finalize(self._run(prep), prep, t0)
            yield from completion_to_chunks(comp)
            return
        yield from self._normalize_stream(self._stream(prep.request), prep, t0)

    async def achat_completions_stream(self, request: Any = None, /, **fields) -> AsyncIterator[ChatCompletionChunk]:
        req = ChatCompletionRequest.coerce(request, **fields)
        t0 = time.time()
        prep = self.prepare(req, stream=True)
        if prep.structured == "emulated" or (req.n or 1) > 1 or not self.capabilities.streaming:
            comp = self._finalize(await self._arun(prep), prep, t0)
            for c in completion_to_chunks(comp):
                yield c
            return
        norm = _StreamNormalizer(self, prep, t0)
        async for c in self._astream(prep.request):
            for out in norm.feed(c):
                yield out
        for out in norm.close():
            yield out

    def embeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        raise self._unsupported("embeddings (it is a chat model)")

    async def aembeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        raise self._unsupported("embeddings (it is a chat model)")

    # ── hooks a provider adapter implements ───────────────────────
    def _create(self, request: ChatCompletionRequest) -> ChatCompletion:
        """One call, one choice. Default: an original-interface model's ``generate``, converted."""
        if not self._has_legacy_generate():
            raise NotImplementedError(f"{type(self).__name__} implements neither _create nor generate")
        from sajha.ai.llm.convert import from_canonical_request, to_canonical_response
        return to_canonical_response(self.generate(from_canonical_request(request)))

    def _stream(self, request: ChatCompletionRequest) -> Iterator[ChatCompletionChunk]:
        """Default: an original-interface model's ``stream`` converted, or one answer replayed as chunks."""
        if self._has_legacy_stream():
            from sajha.ai.llm.convert import chunks_from_events, from_canonical_request
            yield from chunks_from_events(self.stream(from_canonical_request(request)))
            return
        yield from completion_to_chunks(self._create(request))

    async def _acreate(self, request: ChatCompletionRequest) -> ChatCompletion:
        import anyio
        return await anyio.to_thread.run_sync(self._create, request)

    async def _astream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        import anyio
        it = iter(self._stream(request))
        sentinel = object()
        while True:
            c = await anyio.to_thread.run_sync(next, it, sentinel)
            if c is sentinel:
                return
            yield c

    # ── capability check ──────────────────────────────────────────
    def _unsupported(self, what: str) -> UnsupportedFeature:
        return UnsupportedFeature(f"{self.qualified_id} does not support {what}",
                                  provider=self.provider.name, model=self.id)

    def prepare(self, req: ChatCompletionRequest, stream: bool = False) -> Prepared:
        """Refuse what this model cannot honour; record what SAJHA does on the caller's behalf."""
        check_request(req)
        caps = self.capabilities
        if not getattr(self.provider, "openai_compatible", False):
            used = passthrough_used(req)
            if used:
                raise self._unsupported(f"{', '.join(used)} (passed through to OpenAI-compatible servers only)")
        if req.wants_tools:
            if not caps.tools:
                raise self._unsupported("tools")
            mode = req.tool_choice_mode
            if mode == "required" and not caps.forced_tool_choice:
                raise self._unsupported('tool_choice "required"')
            if mode == "named" and not caps.named_tool_choice:
                only = [t.name for t in req.tools or []] == [req.tool_choice_name]
                if not (only and caps.forced_tool_choice):
                    hint = ' (offer only that tool, with tool_choice "required")' if caps.forced_tool_choice else ""
                    raise self._unsupported("a named tool_choice" + hint)
            if req.parallel_tool_calls is False and not caps.parallel_tool_control:
                raise self._unsupported("parallel_tool_calls: false")
            if any(t.function and t.function.strict for t in req.tools or []) and not caps.strict_tools:
                raise self._unsupported("strict tools")
        if req.has_images and not caps.vision:
            raise self._unsupported("images")
        if req.stop_list and not caps.stop_sequences:
            raise self._unsupported("stop sequences")
        if req.seed is not None and not caps.seed:
            raise self._unsupported("seed")
        if req.reasoning_effort is not None and not caps.reasoning_effort:
            raise self._unsupported("reasoning_effort")
        out, ignored, structured, schema = req, [], None, None
        if not caps.temperature:
            dropped = [f for f in ("temperature", "top_p") if getattr(req, f) is not None]
            if dropped:
                ignored = dropped
                out = out.model_copy(update={f: None for f in dropped})
        kind = req.output_kind
        if kind == "json_object" and not (caps.structured_output or caps.json_mode):
            raise self._unsupported("JSON output (response_format json_object)")
        if kind == "json_schema":
            if caps.structured_output:
                structured = "native"
            elif caps.json_mode:
                structured, schema = "emulated", req.output_schema
                note = ChatMessage.system(_emulation_note(schema))
                out = out.model_copy(update={"messages": list(out.messages) + [note],
                                             "response_format": ResponseFormat(type="json_object")})
            else:
                raise self._unsupported("structured output (response_format json_schema)")
        return Prepared(out, ignored, structured, schema)

    # ── orchestration: n samples, emulated structured output ──────
    def _samples(self, prep: Prepared) -> int:
        n = prep.request.n or 1
        return 1 if n <= 1 or self.capabilities.native_n else n

    def _single_request(self, prep: Prepared) -> ChatCompletionRequest:
        return prep.request.model_copy(update={"n": None}) if self._samples(prep) > 1 else prep.request

    def _check_emulated(self, prep: Prepared, comp: ChatCompletion, retried: bool) -> Optional[ChatCompletionRequest]:
        """None when the reply validates; otherwise the retry request (once)."""
        if prep.structured != "emulated" or comp.finish_reason != "stop":
            return None
        err = _schema_error(comp.text, prep.schema or {})
        if err is None:
            return None
        if retried:
            raise ModelFailed(f"{self.qualified_id}: emulated structured output did not match the schema "
                              f"after one retry: {err}", provider=self.provider.name, model=self.id)
        req = self._single_request(prep)
        return req.model_copy(update={"messages": list(req.messages) + [
            ChatMessage.assistant(comp.text),
            ChatMessage.user(f"That reply does not match the schema: {err}. Reply again with only the JSON object.")]})

    def _run(self, prep: Prepared) -> ChatCompletion:
        out = []
        for _ in range(self._samples(prep)):
            req = self._single_request(prep)
            comp = self._create(req)
            retry = self._check_emulated(prep, comp, False)
            if retry is not None:
                usage = comp.usage
                comp = self._create(retry)
                self._check_emulated(prep, comp, True)
                comp.usage = _add_usage(usage, comp.usage)
            out.append(comp)
        return _merge_samples(out)

    async def _arun(self, prep: Prepared) -> ChatCompletion:
        out = []
        for _ in range(self._samples(prep)):
            req = self._single_request(prep)
            comp = await self._acreate(req)
            retry = self._check_emulated(prep, comp, False)
            if retry is not None:
                usage = comp.usage
                comp = await self._acreate(retry)
                self._check_emulated(prep, comp, True)
                comp.usage = _add_usage(usage, comp.usage)
            out.append(comp)
        return _merge_samples(out)

    def _finalize(self, comp: ChatCompletion, prep: Prepared, t0: float) -> ChatCompletion:
        sj = comp.ensure_sajha()
        sj.provider = sj.provider or self.provider.name
        sj.qualified_model = f"{self.provider.name}/{self.id}"
        if comp.usage is None:
            comp.usage = self.estimate_usage(prep.request, comp.text)
            sj.usage_estimated = True
        if not sj.cost_usd:
            sj.cost_usd = self.capabilities.cost(comp.usage.prompt_tokens, comp.usage.completion_tokens)
        sj.latency_ms = sj.latency_ms or int((time.time() - t0) * 1000)
        sj.ignored = sorted(set(sj.ignored) | set(prep.ignored))
        sj.structured_output = sj.structured_output or prep.structured
        comp.model = comp.model or self.id
        for ch in comp.choices:
            if ch.finish_reason not in ("stop", "length", "tool_calls", "content_filter"):
                ch.finish_reason = "tool_calls" if ch.message.tool_calls else "stop"
        return comp

    def _normalize_stream(self, chunks, prep: Prepared, t0: float) -> Iterator[ChatCompletionChunk]:
        norm = _StreamNormalizer(self, prep, t0)
        for c in chunks:
            yield from norm.feed(c)
        yield from norm.close()

    # ── the original interface, kept as shims ──────────────────────
    def generate(self, request: ChatRequest) -> ChatResponse:
        if not self._is_canonical():
            raise NotImplementedError(f"{type(self).__name__} implements neither _create nor generate")
        from sajha.ai.llm.convert import from_canonical_response, to_canonical_request
        return from_canonical_response(self.chat_completions_create(to_canonical_request(request, self.id)))

    def stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        if not self._is_canonical():
            yield Done(self.generate(request))           # a non-streaming original-interface model
            return
        from sajha.ai.llm.convert import events_from_chunks, to_canonical_request
        creq = to_canonical_request(request, self.id)
        yield from events_from_chunks(self.chat_completions_stream(creq))

    async def agenerate(self, request: ChatRequest) -> ChatResponse:
        if self._is_canonical():
            from sajha.ai.llm.convert import from_canonical_response, to_canonical_request
            return from_canonical_response(await self.achat_completions_create(to_canonical_request(request, self.id)))
        import anyio
        return await anyio.to_thread.run_sync(self.generate, request)

    def count_tokens(self, request: Union[ChatRequest, ChatCompletionRequest]) -> int:
        if isinstance(request, ChatCompletionRequest):
            text = "".join(m.text + (m.refusal or "") + "".join(c.function.name + c.function.arguments
                                                                 for c in m.tool_calls or [])
                           for m in request.messages)
            for t in request.tools or []:
                text += t.name + json.dumps(t.function.to_dict() if t.function else {})
            return estimate_tokens(text)
        text = request.system + "".join(m.text for m in request.messages)
        for m in request.messages:
            for r in m.tool_results:
                text += r.content_text()
        for t in request.tools:
            text += t.name + t.description + json.dumps(t.input_schema)
        return estimate_tokens(text)

    def estimate_usage(self, request: ChatCompletionRequest, output_text: str = "",
                       output_chars: Optional[int] = None) -> CompletionUsage:
        out = estimate_tokens(output_text) if output_chars is None else (output_chars + 3) // 4
        return CompletionUsage.of(self.count_tokens(request), out)

    def validate(self, request: ChatRequest) -> None:
        """The original capability check on a legacy ChatRequest (kept for models that call it)."""
        caps = self.capabilities
        if request.tools and request.tool_choice != "none" and not caps.tools:
            raise UnsupportedFeature(f"{self.qualified_id} does not support tools",
                                     provider=self.provider.name, model=self.id)
        if request.response_schema and not caps.structured_output:
            raise UnsupportedFeature(f"{self.qualified_id} does not support structured output",
                                     provider=self.provider.name, model=self.id)
        if any(p.__class__.__name__ == "ImagePart" for m in request.messages for p in m.parts) \
                and not caps.vision:
            raise UnsupportedFeature(f"{self.qualified_id} does not accept images",
                                     provider=self.provider.name, model=self.id)

    # helpers for subclasses
    def make_usage(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> Usage:
        input_tokens, output_tokens = int(input_tokens or 0), int(output_tokens or 0)
        return Usage(input_tokens, output_tokens, int(cached_tokens or 0),
                     self.capabilities.cost(input_tokens, output_tokens))

    def effective_max_tokens(self, request) -> int:
        return int(request.max_output_tokens or self.provider.config.default_max_output_tokens
                   or self.capabilities.max_output_tokens or 1024)

    def effective_temperature(self, request) -> Optional[float]:
        if not self.capabilities.temperature:
            return None
        t = request.temperature
        return t if t is not None else self.provider.config.default_temperature


class _StreamNormalizer:
    """Gives a model's chunk stream one id/created/model, a usage chunk last, and SAJHA's markers."""

    def __init__(self, model: ChatModel, prep: Prepared, t0: float):
        self.model, self.prep, self.t0 = model, prep, t0
        self.id, self.created, self.name = "", 0, ""
        self.chars = 0
        self.usage_seen = False

    def _stamp(self, c: ChatCompletionChunk) -> ChatCompletionChunk:
        self.id = self.id or c.id or new_id()
        self.created = self.created or c.created or int(time.time())
        self.name = self.name or c.model or self.model.id          # one model name for the whole stream
        c.id, c.created, c.model = self.id, self.created, self.name
        return c

    def _sajha(self, sj: Optional[ResponseSajha], usage: CompletionUsage) -> ResponseSajha:
        sj = sj or ResponseSajha()
        m = self.model
        sj.provider = sj.provider or m.provider.name
        sj.qualified_model = m.qualified_id
        if not sj.cost_usd:
            sj.cost_usd = m.capabilities.cost(usage.prompt_tokens, usage.completion_tokens)
        sj.latency_ms = int((time.time() - self.t0) * 1000)
        sj.ignored = sorted(set(sj.ignored) | set(self.prep.ignored))
        sj.structured_output = sj.structured_output or self.prep.structured
        return sj

    def feed(self, c: ChatCompletionChunk) -> List[ChatCompletionChunk]:
        c = self._stamp(c)
        for ch in c.choices:
            self.chars += len(ch.delta.content or "") + sum(len((t.function.arguments or "") if t.function else "")
                                                            for t in ch.delta.tool_calls or [])
        if c.usage is not None and not c.choices:
            self.usage_seen = True
            c.sajha = self._sajha(c.sajha, c.usage)
        return [c]

    def close(self) -> List[ChatCompletionChunk]:
        if self.usage_seen:
            return []
        usage = self.model.estimate_usage(self.prep.request, output_chars=self.chars)
        sj = self._sajha(None, usage)
        sj.usage_estimated = True
        return [self._stamp(ChatCompletionChunk(choices=[], usage=usage, sajha=sj))]


def _add_usage(a: Optional[CompletionUsage], b: Optional[CompletionUsage]) -> Optional[CompletionUsage]:
    if a is None or b is None:
        return a or b
    return a + b


def _merge_samples(comps: List[ChatCompletion]) -> ChatCompletion:
    """n separate calls -> one completion with n choices; usage and cost summed."""
    if len(comps) == 1:
        return comps[0]
    first = comps[0]
    choices, usage, cost = [], None, 0.0
    for i, c in enumerate(comps):
        for ch in c.choices:
            choices.append(Choice(index=len(choices), message=ch.message, finish_reason=ch.finish_reason,
                                  logprobs=ch.logprobs))
        usage = _add_usage(usage, c.usage)
        cost += (c.sajha.cost_usd if c.sajha else 0.0)
    out = first.model_copy(update={"choices": choices, "usage": usage})
    if cost:
        out.ensure_sajha().cost_usd = cost
    return out


class EmbeddingModel(LLMModel):
    """One embedding model (the shared implementation of LLMModel for embeddings). Implement ``_embed(texts, purpose, dimensions)`` (or the original
    ``embed(texts)``); callers use ``embeddings_create``."""

    id: str
    provider: "LLMProvider"
    dimensions: int = 0

    def __init__(self, provider: "LLMProvider", model_id: str, dimensions: int = 0,
                 capabilities: Optional[ModelCapabilities] = None):
        self.provider = provider
        self.id = model_id
        self.dimensions = dimensions
        caps = capabilities or ModelCapabilities(chat=False, embedding=True, dimensions=dimensions)
        resolve = getattr(provider, "resolve_capabilities", None)
        self.capabilities = resolve(caps) if resolve else caps.resolved()

    @property
    def qualified_id(self) -> str:
        return f"{self.provider.name}/{self.id}"

    def info(self) -> ModelInfo:
        return ModelInfo(self.id, self.provider.name, "embedding", self.capabilities)

    # ── chat is refused: this is an embedding model ──────────────
    def _no_chat(self) -> UnsupportedFeature:
        return UnsupportedFeature(f"{self.qualified_id} is an embedding model; chat is not supported",
                                  provider=self.provider.name, model=self.id)

    def chat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        raise self._no_chat()

    async def achat_completions_create(self, request: Any = None, /, **fields) -> ChatCompletion:
        raise self._no_chat()

    def chat_completions_stream(self, request: Any = None, /, **fields) -> Iterator[ChatCompletionChunk]:
        raise self._no_chat()

    async def achat_completions_stream(self, request: Any = None, /, **fields) -> AsyncIterator[ChatCompletionChunk]:
        raise self._no_chat()
        yield  # pragma: no cover  (an async generator, like the chat twin)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """The original interface: vectors for ``texts`` (document purpose, configured size)."""
        if type(self)._embed is EmbeddingModel._embed:
            raise NotImplementedError(f"{type(self).__name__} implements neither _embed nor embed")
        out = self._embed(list(texts))
        return out[0] if isinstance(out, tuple) else out

    def _embed(self, texts: List[str], purpose: Optional[str] = None,
               dimensions: Optional[int] = None) -> Union[List[List[float]], Tuple[List[List[float]], int]]:
        """Vectors (optionally with the vendor-reported token count). Default: ``embed``."""
        return self.embed(texts)

    def embeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        req = EmbeddingsRequest.coerce(request, **fields)
        t0 = time.time()
        if req.encoding_format not in (None, "float", "base64"):
            raise InvalidRequest(f"encoding_format: unknown value '{req.encoding_format}'")
        if req.is_tokens and not getattr(self.provider, "openai_compatible", False):
            raise UnsupportedFeature(f"{self.qualified_id} does not take token arrays (OpenAI-compatible only)",
                                     provider=self.provider.name, model=self.id)
        if req.dimensions and not self.capabilities.variable_dimensions and req.dimensions != self.dimensions:
            raise UnsupportedFeature(f"{self.qualified_id} has a fixed size; 'dimensions' is not supported",
                                     provider=self.provider.name, model=self.id)
        texts = req.input if req.is_tokens else req.texts
        if type(self)._embed is EmbeddingModel._embed:
            out: Any = self.embed(texts)
        else:
            out = self._embed(texts, req.purpose, req.dimensions)
        vectors, tokens = (out if isinstance(out, tuple) else (out, None))
        estimated = tokens is None
        if estimated:
            tokens = sum(estimate_tokens(t if isinstance(t, str) else " " * (len(t) * 4)) for t in texts)
        data = [EmbeddingData(embedding=encode_base64_floats(v) if req.encoding_format == "base64" else list(v),
                              index=i) for i, v in enumerate(vectors)]
        cost = tokens * self.capabilities.input_cost_per_mtok / 1_000_000
        return EmbeddingsResponse(data=data, model=self.id, usage=EmbeddingsUsage(prompt_tokens=tokens,
                                                                                  total_tokens=tokens),
                                  sajha=ResponseSajha(provider=self.provider.name, qualified_model=self.qualified_id,
                                                      cost_usd=cost, usage_estimated=estimated,
                                                      latency_ms=int((time.time() - t0) * 1000)))

    async def aembeddings_create(self, request: Any = None, /, **fields) -> EmbeddingsResponse:
        import anyio
        return await anyio.to_thread.run_sync(lambda: self.embeddings_create(request, **fields))
