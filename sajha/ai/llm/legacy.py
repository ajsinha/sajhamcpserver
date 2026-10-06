"""
SAJHA Intelligence Layer — LegacyProviderAdapter.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Wraps a provider written against the old ``sajha.ai.providers.LLMProvider`` ABC (registered
with ``register_provider_class``) as a new-style provider, so it is served through the
gateway's types, aliases, policy and budgets. The old interface has no tool-call parsing, so
wrapped models declare ``tools=False`` and the gateway routes tool requests elsewhere.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import Field

from sajha.ai.llm.errors import ProviderUnavailable, UnsupportedFeature
from sajha.ai.llm.model import ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities, ModelDescriptor
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import ChatRequest, ChatResponse, Message, TextPart


class LegacyConfig(ProviderConfig):
    legacy_type: str = ""
    region: Optional[str] = None
    legacy_kwargs: Dict[str, Any] = Field(default_factory=dict)


def _legacy_messages(request: ChatRequest) -> List[Dict[str, str]]:
    out = []
    for m in request.messages:
        if m.role == "system":
            continue
        text = m.text
        for r in m.tool_results:
            text += f"\n[tool result {r.call_id}]\n{r.content_text()}"
        for c in m.tool_calls:
            text += f"\n[called {c.name}({c.arguments})]"
        out.append({"role": "assistant" if m.role == "assistant" else "user", "content": text})
    return out


class LegacyChatModel(ChatModel):
    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        legacy = self.provider.legacy()
        system = "\n\n".join([request.system] + [m.text for m in request.messages if m.role == "system"]).strip()
        try:
            with self.provider.slot():
                r = legacy.complete(_legacy_messages(request), self.id,
                                    temperature=request.temperature if request.temperature is not None else 0.7,
                                    max_tokens=self.effective_max_tokens(request), system=system)
        except Exception as e:
            raise ProviderUnavailable(f"{self.provider.name}: {e}", provider=self.provider.name, model=self.id)
        usage = self.make_usage(r.input_tokens, r.output_tokens)
        if r.cost_usd:
            usage.cost_usd = r.cost_usd
        finish = {"length": "length", "max_tokens": "length"}.get(r.finish_reason, "stop")
        return ChatResponse(Message("assistant", [TextPart(r.content)] if r.content else []), finish, usage,
                            r.model or self.id, self.provider.name, int((time.time() - t0) * 1000), raw=r.raw)


class LegacyEmbeddingModel(EmbeddingModel):
    def embed(self, texts: List[str]) -> List[List[float]]:
        try:
            with self.provider.slot():
                return self.provider.legacy().embed(list(texts), model=self.id).embeddings
        except NotImplementedError:
            raise UnsupportedFeature(f"{self.provider.name} has no embeddings", provider=self.provider.name)


class LegacyProviderAdapter(LLMProvider):
    name = "legacy"
    config_model = LegacyConfig
    requires_key = False
    unknown_model_capabilities = ModelCapabilities(tools=False, structured_output=False, streaming=False)
    chat_model_class = LegacyChatModel
    embedding_model_class = LegacyEmbeddingModel

    def __init__(self, *a, legacy_instance=None, **kw):
        super().__init__(*a, **kw)
        self._legacy = legacy_instance

    def legacy(self):
        if self._legacy is None:
            from sajha.ai.providers import create_provider
            kwargs = dict(self.config.legacy_kwargs or {})
            if self.api_key:
                kwargs.setdefault("api_key", self.api_key)
            if self.config.base_url:
                kwargs.setdefault("base_url", self.config.base_url)
            if self.config.region:
                kwargs.setdefault("region", self.config.region)
            self._legacy = create_provider(self.config.legacy_type or self.name, **kwargs)
        return self._legacy

    def live_models(self) -> List[ModelDescriptor]:
        out = []
        for mi in self.legacy().list_models():
            caps = ModelCapabilities(tools=False, structured_output=False, streaming=False,
                                     vision=bool(mi.supports_vision), context_window=mi.context_window,
                                     max_output_tokens=mi.max_output_tokens,
                                     input_cost_per_mtok=mi.input_cost_per_1k * 1000,
                                     output_cost_per_mtok=mi.output_cost_per_1k * 1000,
                                     tags=frozenset(mi.tags or []))
            out.append(ModelDescriptor(mi.id, caps, mi.name, source="live"))
        return out

    def default_chat_model_id(self) -> str:
        if self.config.default_model:
            return self.config.default_model
        try:
            return self.legacy().get_default_model()
        except Exception:
            return ""

    def default_embedding_model_id(self) -> str:
        return self.config.default_embedding_model or (self.legacy().get_default_embedding_model() or "")

    def health(self) -> HealthStatus:
        if not self.active:
            return HealthStatus("down", "disabled")
        try:
            return HealthStatus("ok" if self.legacy().health_check() else "down", "legacy health_check")
        except Exception as e:
            return HealthStatus("down", str(e)[:200])
