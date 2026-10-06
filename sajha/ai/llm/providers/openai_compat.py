"""
SAJHA Intelligence Layer — OpenAI Chat Completions wire format, and everything that speaks it.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

OpenAIProvider            api.openai.com (chat, tools, json_schema output, streaming, embeddings)
AzureOpenAIProvider       Azure OpenAI: the GA v1 path (default) or deployments + api-version
OpenAICompatibleProvider  any server with /chat/completions (vLLM, LM Studio, LiteLLM, ...)
  presets                 groq, together, fireworks, deepseek, xai, openrouter, perplexity,
                          vllm, lmstudio — each just a base URL, key variable and catalogue

Plain httpx; no vendor SDK.
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar, Dict, Iterator, List, Literal, Optional

from pydantic import Field

from sajha.ai.llm.errors import UnsupportedFeature
from sajha.ai.llm.http import iter_sse, post_json, safe_json_loads, stream_post
from sajha.ai.llm.model import ChatModel, EmbeddingModel, ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, TextDelta, TextPart,
                                ToolCallDelta, ToolCallPart, ToolResultPart, UsageEvent)

FINISH = {"stop": "stop", "length": "length", "tool_calls": "tool_calls", "function_call": "tool_calls",
          "content_filter": "content_filter", "end_turn": "stop", "eos": "stop"}


class OpenAIConfig(ProviderConfig):
    organization: Optional[str] = None
    project: Optional[str] = None
    max_tokens_param: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    strict_schema: bool = False                 # response_format.json_schema.strict
    stream_usage: bool = True                   # stream_options.include_usage
    parallel_tool_calls: Optional[bool] = None
    tool_choice_required: str = "required"      # the vendor's word for "must call a tool"
    chat_path: str = "/chat/completions"
    embeddings_path: str = "/embeddings"
    extra_body: Dict[str, Any] = Field(default_factory=dict)   # merged into every chat payload

    vendor_env: ClassVar[Dict[str, List[str]]] = {
        "api_key": ["OPENAI_API_KEY"], "base_url": ["OPENAI_BASE_URL"],
        "organization": ["OPENAI_ORG_ID"], "project": ["OPENAI_PROJECT_ID"]}


# ── wire mapping ──────────────────────────────────────────────────

def to_openai_messages(request: ChatRequest, image_parts: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if request.system:
        out.append({"role": "system", "content": request.system})
    for m in request.messages:
        if m.role == "system":
            out.append({"role": "system", "content": m.text})
        elif m.role == "user":
            imgs = [p for p in m.parts if isinstance(p, ImagePart)]
            if imgs and image_parts:
                content = [{"type": "text", "text": p.text} for p in m.parts if isinstance(p, TextPart)]
                content += [{"type": "image_url", "image_url": {"url": f"data:{p.mime_type};base64,{p.b64}"}}
                            for p in imgs]
                out.append({"role": "user", "content": content})
            else:
                out.append({"role": "user", "content": m.text})
            for r in m.tool_results:       # tolerate results placed on a user message
                out.append(_tool_msg(r))
        elif m.role == "assistant":
            msg: Dict[str, Any] = {"role": "assistant", "content": m.text or None}
            if m.tool_calls:
                msg["tool_calls"] = [{"id": c.id, "type": "function",
                                      "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                     for c in m.tool_calls]
            out.append(msg)
        elif m.role == "tool":
            for r in m.tool_results:
                out.append(_tool_msg(r))
    return out


def _tool_msg(r: ToolResultPart) -> Dict[str, Any]:
    text = r.content_text()
    return {"role": "tool", "tool_call_id": r.call_id, "content": ("ERROR: " + text) if r.is_error else text}


def to_openai_tools(request: ChatRequest) -> List[Dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description[:1024],
                                              "parameters": t.input_schema or {"type": "object", "properties": {}}}}
            for t in request.tools]


def parse_openai_message(msg: Dict[str, Any]) -> Message:
    parts: List[Any] = []
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    if content:
        parts.append(TextPart(content))
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            args = safe_json_loads(args)
        parts.append(ToolCallPart(tc.get("id") or f"call_{i}", fn.get("name", ""), args or {}))
    return Message("assistant", parts)


class OpenAIChatModel(ChatModel):
    """Chat Completions. Subclasses tweak url(), payload() and the provider config."""

    def url(self) -> str:
        return self.provider.config.chat_path

    def params(self) -> Optional[Dict[str, str]]:
        return None

    def wire_model(self) -> str:
        return self.id

    def payload(self, request: ChatRequest, stream: bool = False) -> Dict[str, Any]:
        cfg = self.provider.config
        body: Dict[str, Any] = {"model": self.wire_model(),
                                "messages": to_openai_messages(request, self.capabilities.vision)}
        body[cfg.max_tokens_param] = self.effective_max_tokens(request)
        t = self.effective_temperature(request)
        if t is not None:
            body["temperature"] = t
        if request.stop:
            body["stop"] = list(request.stop)
        if request.tools and request.tool_choice != "none":
            body["tools"] = to_openai_tools(request)
            tc = request.tool_choice
            if tc == "required":
                body["tool_choice"] = cfg.tool_choice_required if self.capabilities.forced_tool_choice else "auto"
            elif tc not in ("auto", "none"):
                body["tool_choice"] = ({"type": "function", "function": {"name": tc}}
                                       if self.capabilities.forced_tool_choice else "auto")
            else:
                body["tool_choice"] = tc
            if cfg.parallel_tool_calls is not None:
                body["parallel_tool_calls"] = cfg.parallel_tool_calls
        if request.response_schema:
            body["response_format"] = {"type": "json_schema",
                                       "json_schema": {"name": "response", "schema": request.response_schema,
                                                       "strict": cfg.strict_schema}}
        if stream:
            body["stream"] = True
            if cfg.stream_usage:
                body["stream_options"] = {"include_usage": True}
        body.update(cfg.extra_body or {})
        return body

    def _usage(self, u: Optional[Dict[str, Any]]):
        u = u or {}
        cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        return self.make_usage(u.get("prompt_tokens") or u.get("input_tokens") or 0,
                               u.get("completion_tokens") or u.get("output_tokens") or 0, cached)

    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        with self.provider.slot():
            data = post_json(self.provider.http, self.url(), self.payload(request), params=self.params(),
                             provider=self.provider.name, model=self.id)
        choice = (data.get("choices") or [{}])[0]
        msg = parse_openai_message(choice.get("message") or {})
        finish = FINISH.get(choice.get("finish_reason") or "stop", "stop")
        if msg.tool_calls and finish == "stop":
            finish = "tool_calls"
        return ChatResponse(msg, finish, self._usage(data.get("usage")), data.get("model") or self.id,
                            self.provider.name, int((time.time() - t0) * 1000), raw=data)

    def stream(self, request: ChatRequest) -> Iterator:
        if not self.capabilities.streaming:
            yield from super().stream(request)
            return
        self.validate(request)
        t0 = time.time()
        text: List[str] = []
        calls: Dict[int, Dict[str, Any]] = {}
        finish, usage, model = "stop", None, self.id
        with self.provider.slot():
            with stream_post(self.provider.http, self.url(), self.payload(request, stream=True),
                             params=self.params(), provider=self.provider.name, model=self.id) as resp:
                for _event, data in iter_sse(resp):
                    if data.strip() == "[DONE]":
                        break
                    chunk = safe_json_loads(data)
                    model = chunk.get("model") or model
                    if chunk.get("usage"):
                        usage = self._usage(chunk["usage"])
                    for ch in chunk.get("choices") or []:
                        delta = ch.get("delta") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                            yield TextDelta(delta["content"])
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            slot = calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                            fn = tc.get("function") or {}
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            frag = fn.get("arguments") or ""
                            slot["args"] += frag
                            yield ToolCallDelta(slot["id"], fn.get("name") or "", frag, idx)
                        if ch.get("finish_reason"):
                            finish = FINISH.get(ch["finish_reason"], "stop")
        parts: List[Any] = [TextPart("".join(text))] if text else []
        for idx in sorted(calls):
            c = calls[idx]
            parts.append(ToolCallPart(c["id"] or f"call_{idx}", c["name"], safe_json_loads(c["args"])))
        if any(isinstance(p, ToolCallPart) for p in parts) and finish == "stop":
            finish = "tool_calls"
        if usage is None:
            usage = self.make_usage(self.count_tokens(request), sum(len(t) for t in text) // 4)
        resp_obj = ChatResponse(Message("assistant", parts), finish, usage, model, self.provider.name,
                                int((time.time() - t0) * 1000))
        yield UsageEvent(usage)
        yield Done(resp_obj)


class OpenAIEmbeddingModel(EmbeddingModel):
    def url(self) -> str:
        return self.provider.config.embeddings_path

    def params(self):
        return None

    def wire_model(self) -> str:
        return self.id

    def embed(self, texts: List[str]) -> List[List[float]]:
        body: Dict[str, Any] = {"model": self.wire_model(), "input": list(texts)}
        if self.provider.config.embedding_dimensions:
            body["dimensions"] = self.provider.config.embedding_dimensions
        with self.provider.slot():
            data = post_json(self.provider.http, self.url(), body, params=self.params(),
                             provider=self.provider.name, model=self.id)
        rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
        return [r.get("embedding") or [] for r in rows]


@register_provider
class OpenAIProvider(LLMProvider):
    name = "openai"
    config_model = OpenAIConfig
    default_base_url = "https://api.openai.com/v1"
    catalog_key = "openai"
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, vision=True,
                                                   context_window=128_000)
    chat_model_class = OpenAIChatModel
    embedding_model_class = OpenAIEmbeddingModel

    def auth_headers(self) -> Dict[str, str]:
        h = {}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if getattr(self.config, "organization", None):
            h["OpenAI-Organization"] = self.config.organization
        if getattr(self.config, "project", None):
            h["OpenAI-Project"] = self.config.project
        return h


# ── Azure OpenAI ─────────────────────────────────────────────────

class AzureOpenAIConfig(OpenAIConfig):
    api_style: Literal["v1", "deployments"] = "v1"
    api_version: str = "2024-10-21"             # used by api_style=deployments
    deployments: Dict[str, str] = Field(default_factory=dict)   # model id -> deployment name
    auth: Literal["api_key", "bearer"] = "api_key"               # bearer: Entra ID token in api_key
    max_tokens_param: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"

    vendor_env: ClassVar[Dict[str, List[str]]] = {
        "api_key": ["AZURE_OPENAI_API_KEY"], "base_url": ["AZURE_OPENAI_ENDPOINT"],
        "api_version": ["OPENAI_API_VERSION", "AZURE_OPENAI_API_VERSION"]}


class AzureChatModel(OpenAIChatModel):
    def deployment(self) -> str:
        return (self.options.get("deployment") or self.provider.config.deployments.get(self.id) or self.id)

    def url(self) -> str:
        if self.provider.config.api_style == "v1":
            return "/openai/v1/chat/completions"
        return f"/openai/deployments/{self.deployment()}/chat/completions"

    def params(self):
        return None if self.provider.config.api_style == "v1" else {"api-version": self.provider.config.api_version}

    def wire_model(self) -> str:
        return self.deployment()


class AzureEmbeddingModel(OpenAIEmbeddingModel):
    def deployment(self) -> str:
        return self.provider.config.deployments.get(self.id) or self.id

    def url(self) -> str:
        if self.provider.config.api_style == "v1":
            return "/openai/v1/embeddings"
        return f"/openai/deployments/{self.deployment()}/embeddings"

    def params(self):
        return None if self.provider.config.api_style == "v1" else {"api-version": self.provider.config.api_version}

    def wire_model(self) -> str:
        return self.deployment()


@register_provider
class AzureOpenAIProvider(OpenAIProvider):
    name = "azure_openai"
    config_model = AzureOpenAIConfig
    default_base_url = ""
    catalog_key = "azure_openai"
    chat_model_class = AzureChatModel
    embedding_model_class = AzureEmbeddingModel

    def auto_enabled(self) -> bool:
        return bool(self.api_key and self.base_url)

    def live_models(self):
        """Configured deployments are this resource's models (model id -> deployment name)."""
        from sajha.ai.llm.model import ModelDescriptor
        return [ModelDescriptor(mid, self.unknown_model_capabilities, kind="embedding" if "embed" in mid else "chat",
                                source="config", deployment=dep) for mid, dep in self.config.deployments.items()]

    def auth_headers(self) -> Dict[str, str]:
        if not self.api_key:
            return {}
        if self.config.auth == "bearer":
            return {"Authorization": f"Bearer {self.api_key}"}
        return {"api-key": self.api_key}

    def default_chat_model_id(self) -> str:
        if self.config.default_model:
            return self.config.default_model
        chats = [m.id for m in self.list_models() if m.kind == "chat"]
        return chats[0] if chats else next(iter(self.config.deployments), "")


# ── OpenAI-compatible servers and presets ───────────────────────

class CompatConfig(OpenAIConfig):
    max_tokens_param: Literal["max_completion_tokens", "max_tokens"] = "max_tokens"
    live_models: Optional[bool] = None          # GET /models; None = only for keyless (local) servers
    models_path: str = "/models"
    vendor_env: ClassVar[Dict[str, List[str]]] = {}


@register_provider
class OpenAICompatibleProvider(OpenAIProvider):
    """Any /chat/completions server. Configure base_url (and api_key if it needs one)."""
    name = "openai_compatible"
    config_model = CompatConfig
    default_base_url = ""
    catalog_key = "openai_compatible"
    requires_key = False
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=False, context_window=32_000)
    embedding_model_class = OpenAIEmbeddingModel

    def live_models(self):
        from sajha.ai.llm.http import get_json
        from sajha.ai.llm.model import ModelDescriptor
        live = self.config.live_models
        if live is False or (live is None and self.requires_key) or not self.active or not self.base_url:
            return []
        data = get_json(self.http, self.config.models_path, provider=self.name, timeout=self.config.health_timeout_s)
        return [ModelDescriptor(m["id"], self.unknown_model_capabilities,
                                kind="embedding" if "embed" in m["id"] else "chat", source="live")
                for m in (data.get("data") or []) if m.get("id")]

    def auto_enabled(self) -> bool:
        if self.requires_key:
            return bool(self.api_key)
        # keyless local servers are used only when someone pointed us at them
        return bool(self.config.base_url) and self.sources.get("base_url", "default") != "default"


def _preset(pname: str, base_url: str, key_vars: List[str], *, requires_key: bool = True,
            caps: ModelCapabilities = ModelCapabilities(tools=True, structured_output=True, context_window=128_000),
            embeddings: bool = False, extra_env: Optional[Dict[str, List[str]]] = None):
    """Declare an OpenAI-compatible vendor: its own name, config model, base URL, key variables."""
    env = {"api_key": key_vars}
    env.update(extra_env or {})
    cfg = type(f"{pname.title().replace('_', '')}Config", (CompatConfig,), {"__module__": __name__})
    cfg.vendor_env = env
    cls = type(f"{pname.title().replace('_', '')}Provider", (OpenAICompatibleProvider,), {
        "name": pname, "config_model": cfg, "default_base_url": base_url, "catalog_key": pname,
        "requires_key": requires_key, "unknown_model_capabilities": caps,
        "embedding_model_class": OpenAIEmbeddingModel if embeddings else None,
        "__module__": __name__,
    })
    register_provider(cls)
    globals()[cls.__name__] = cls
    return cls


GroqProvider = _preset("groq", "https://api.groq.com/openai/v1", ["GROQ_API_KEY"],
                       extra_env={"base_url": ["GROQ_BASE_URL"]})
TogetherProvider = _preset("together", "https://api.together.xyz/v1", ["TOGETHER_API_KEY"], embeddings=True)
FireworksProvider = _preset("fireworks", "https://api.fireworks.ai/inference/v1", ["FIREWORKS_API_KEY"],
                            embeddings=True)
DeepSeekProvider = _preset("deepseek", "https://api.deepseek.com/v1", ["DEEPSEEK_API_KEY"],
                           caps=ModelCapabilities(tools=True, structured_output=False, context_window=128_000))
XAIProvider = _preset("xai", "https://api.x.ai/v1", ["XAI_API_KEY"])
OpenRouterProvider = _preset("openrouter", "https://openrouter.ai/api/v1", ["OPENROUTER_API_KEY"])
PerplexityProvider = _preset("perplexity", "https://api.perplexity.ai", ["PERPLEXITY_API_KEY", "PPLX_API_KEY"],
                             caps=ModelCapabilities(tools=False, structured_output=True, context_window=127_000))
VLLMProvider = _preset("vllm", "http://localhost:8000/v1", ["VLLM_API_KEY"], requires_key=False,
                       caps=ModelCapabilities(tools=True, structured_output=True, context_window=32_000,
                                              tags=frozenset({"local"})), embeddings=True)
LMStudioProvider = _preset("lmstudio", "http://localhost:1234/v1", ["LMSTUDIO_API_KEY"], requires_key=False,
                           caps=ModelCapabilities(tools=True, structured_output=True, context_window=32_000,
                                                  tags=frozenset({"local"})), embeddings=True)
