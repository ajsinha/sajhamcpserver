"""
SAJHA Intelligence Layer — model abstractions.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A provider is a factory for models; a model does the work. One ChatModel / EmbeddingModel
object per configured model, carrying its declared capabilities.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, Iterable, Iterator, List, Optional

from sajha.ai.llm.errors import UnsupportedFeature
from sajha.ai.llm.types import ChatRequest, ChatResponse, Done, StreamEvent, Usage

if TYPE_CHECKING:   # pragma: no cover
    from sajha.ai.llm.provider import LLMProvider

CAPABILITY_FLAGS = ("chat", "tools", "structured_output", "vision", "streaming", "embedding")


@dataclass(frozen=True)
class ModelCapabilities:
    chat: bool = True
    tools: bool = False
    structured_output: bool = False
    vision: bool = False
    streaming: bool = True
    embedding: bool = False
    context_window: int = 0
    max_output_tokens: int = 4096
    input_cost_per_mtok: float = 0.0
    output_cost_per_mtok: float = 0.0
    dimensions: int = 0                     # embedding models
    temperature: bool = True                # accepts a sampling temperature
    forced_tool_choice: bool = True         # accepts tool_choice "required" / a named tool
    tags: FrozenSet[str] = frozenset()      # "fast", "reasoning", "cheap", "local", "deterministic"

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


class ChatModel(ABC):
    """One chat model of one provider."""

    id: str
    provider: "LLMProvider"
    capabilities: ModelCapabilities = ModelCapabilities()

    def __init__(self, provider: "LLMProvider", model_id: str,
                 capabilities: Optional[ModelCapabilities] = None, **options):
        self.provider = provider
        self.id = model_id
        if capabilities is not None:
            self.capabilities = capabilities
        self.options = options

    @property
    def qualified_id(self) -> str:
        return f"{self.provider.name}/{self.id}"

    @abstractmethod
    def generate(self, request: ChatRequest) -> ChatResponse: ...

    def stream(self, request: ChatRequest) -> Iterator[StreamEvent]:
        """Default: a non-streaming fallback that yields one Done event."""
        yield Done(self.generate(request))

    async def agenerate(self, request: ChatRequest) -> ChatResponse:
        import anyio
        return await anyio.to_thread.run_sync(self.generate, request)

    def count_tokens(self, request: ChatRequest) -> int:
        text = request.system + "".join(m.text for m in request.messages)
        for m in request.messages:
            for r in m.tool_results:
                text += r.content_text()
        for t in request.tools:
            text += t.name + t.description + json.dumps(t.input_schema)
        return estimate_tokens(text)

    def validate(self, request: ChatRequest) -> None:
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

    def effective_max_tokens(self, request: ChatRequest) -> int:
        return int(request.max_output_tokens or self.provider.config.default_max_output_tokens
                   or self.capabilities.max_output_tokens or 1024)

    def effective_temperature(self, request: ChatRequest) -> Optional[float]:
        if not self.capabilities.temperature:
            return None
        t = request.temperature
        return t if t is not None else self.provider.config.default_temperature


class EmbeddingModel(ABC):
    id: str
    provider: "LLMProvider"
    dimensions: int = 0

    def __init__(self, provider: "LLMProvider", model_id: str, dimensions: int = 0,
                 capabilities: Optional[ModelCapabilities] = None):
        self.provider = provider
        self.id = model_id
        self.dimensions = dimensions
        self.capabilities = capabilities or ModelCapabilities(chat=False, embedding=True,
                                                              dimensions=dimensions)

    @property
    def qualified_id(self) -> str:
        return f"{self.provider.name}/{self.id}"

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]: ...
