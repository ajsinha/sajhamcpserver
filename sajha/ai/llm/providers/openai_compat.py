"""
SAJHA Intelligence Layer — OpenAI Chat Completions wire format, and everything that speaks it.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

OpenAIProvider            api.openai.com (chat, tools, json_schema output, streaming, embeddings)
AzureOpenAIProvider       Azure OpenAI: the GA v1 path (default) or deployments + api-version;
                          auth by api-key, a fixed bearer token, or Microsoft Entra ID
                          (``auth: entra``: client secret, AKS workload identity or managed identity,
                          tokens acquired and refreshed by sajha/ai/llm/cloud_auth.py)
OpenAICompatibleProvider  any server with /chat/completions (vLLM, LM Studio, LiteLLM, ...)
  presets                 groq, together, fireworks, deepseek, xai, openrouter, perplexity,
                          vllm, lmstudio — each just a base URL, key variable and catalogue

The canonical format *is* this wire format, so the adapter is a pass-through. What differs per
server is authentication, base URL and path, and a few declared spellings kept as provider
settings: ``max_tokens_param`` (max_completion_tokens | max_tokens), ``tool_choice_required``
(Mistral's "any"), ``seed_param`` (Mistral's random_seed). ``strict_schema`` and
``parallel_tool_calls`` are defaults for requests that do not set them. Role "developer" is
sent unchanged to OpenAI and Azure OpenAI and as "system" elsewhere. The refusal field is kept.
Plain httpx; no vendor SDK; native async.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import Field, SecretStr

from sajha.ai.llm.adapter import HTTPChatModel, StreamTranslator, WireCall, finish_with_calls
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionRequest, ChatMessage, Choice, ChoiceDelta,
                                    CompletionUsage, FunctionCall, ToolCall)
from sajha.ai.llm.http import post_json, safe_json_loads
from sajha.ai.llm.model import EmbeddingModel, ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig

FINISH = {"stop": "stop", "length": "length", "tool_calls": "tool_calls", "function_call": "tool_calls",
          "content_filter": "content_filter", "end_turn": "stop", "eos": "stop"}

# OpenAI's own feature set; presets and compatible servers declare less
OPENAI_FEATURES = {"strict_tools": True, "parallel_tool_control": True, "seed": True, "native_n": True,
                   "reasoning_effort": "tagged", "variable_dimensions": True}
COMPAT_FEATURES = {"parallel_tool_control": True, "seed": True, "native_n": True, "reasoning_effort": "tagged"}


class OpenAIConfig(ProviderConfig):
    organization: Optional[str] = None
    project: Optional[str] = None
    max_tokens_param: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    strict_schema: bool = False                 # default for response_format.json_schema.strict
    stream_usage: bool = True                   # stream_options.include_usage
    parallel_tool_calls: Optional[bool] = None  # default for requests that do not set it
    tool_choice_required: str = "required"      # the vendor's word for "must call a tool"
    seed_param: str = "seed"                    # the vendor's name for the seed field
    chat_path: str = "/chat/completions"
    embeddings_path: str = "/embeddings"
    extra_body: Dict[str, Any] = Field(default_factory=dict)   # merged into every chat payload

    vendor_env: ClassVar[Dict[str, List[str]]] = {
        "api_key": ["OPENAI_API_KEY"], "base_url": ["OPENAI_BASE_URL"],
        "organization": ["OPENAI_ORG_ID"], "project": ["OPENAI_PROJECT_ID"]}


# ── wire mapping (pure; golden-tested) ─────────────────────────────

_PASS = ("top_p", "seed", "n", "presence_penalty", "frequency_penalty", "logit_bias", "logprobs",
         "top_logprobs", "service_tier", "reasoning_effort", "prediction")


def _message_out(m: ChatMessage, developer_role: bool, image_parts: bool) -> Dict[str, Any]:
    d = m.to_dict()
    d.pop("sajha", None)
    if m.role == "developer" and not developer_role:
        d["role"] = "system"
    if m.role == "tool":
        d.pop("name", None)
        if m.is_error:
            d["content"] = "ERROR: " + m.text
    if m.role == "assistant":
        if m.refusal and not m.text:
            d["content"] = m.refusal
        d.pop("refusal", None)
        d.pop("annotations", None)
        if "content" not in d:
            d["content"] = None
    if m.role == "user" and isinstance(m.content, list) and not image_parts:
        d["content"] = m.text
    return d


def to_openai_body(request: ChatCompletionRequest, *, model: str, cfg: OpenAIConfig, max_tokens: int,
                   temperature: Optional[float], developer_role: bool = False, vision: bool = True,
                   stream: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model,
                            "messages": [_message_out(m, developer_role, vision) for m in request.messages]}
    body[cfg.max_tokens_param] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    for f in _PASS:
        v = getattr(request, f)
        if v is not None and not (f == "n" and v == 1):
            body[cfg.seed_param if f == "seed" else f] = v
    if request.stop_list:
        body["stop"] = request.stop_list
    if request.wants_tools:
        tools = []
        for t in request.tools or []:
            fn = t.function.to_dict() if t.function else {}
            fn["description"] = (fn.get("description") or "")[:1024]
            fn["parameters"] = t.parameters_or_default
            tools.append({"type": "function", "function": fn})
        body["tools"] = tools
        mode = request.tool_choice_mode
        if mode == "required":
            body["tool_choice"] = cfg.tool_choice_required
        elif mode == "named":
            body["tool_choice"] = {"type": "function", "function": {"name": request.tool_choice_name}}
        else:
            body["tool_choice"] = "auto"
        ptc = request.parallel_tool_calls if request.parallel_tool_calls is not None else cfg.parallel_tool_calls
        if ptc is not None:
            body["parallel_tool_calls"] = ptc
    kind = request.output_kind
    if kind == "json_schema":
        js = request.response_format.json_schema
        fmt = {"name": js.name or "response", "schema": js.schema_,
               "strict": js.strict if js.strict is not None else cfg.strict_schema}
        if js.description:
            fmt["description"] = js.description
        body["response_format"] = {"type": "json_schema", "json_schema": fmt}
    elif kind == "json_object":
        body["response_format"] = {"type": "json_object"}
    if stream:
        body["stream"] = True
        if cfg.stream_usage:
            body["stream_options"] = {"include_usage": True}
    body.update(cfg.extra_body or {})
    body.update(request.extra_body or {})
    return body


def parse_openai_usage(u: Optional[Dict[str, Any]]) -> Optional[CompletionUsage]:
    if not u:
        return None
    usage = CompletionUsage.model_validate({k: v for k, v in u.items() if v is not None})
    usage.prompt_tokens = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
    usage.completion_tokens = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
    usage.total_tokens = int(u.get("total_tokens") or usage.prompt_tokens + usage.completion_tokens)
    return usage


def parse_openai_message(msg: Dict[str, Any]) -> ChatMessage:
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    calls = []
    for i, tc in enumerate(msg.get("tool_calls") or []):
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args or {})
        calls.append(ToolCall(id=tc.get("id") or f"call_{i}", function=FunctionCall(name=fn.get("name", ""),
                                                                                   arguments=args or "{}")))
    return ChatMessage(role="assistant", content=content or None, refusal=msg.get("refusal") or None,
                       tool_calls=calls or None, annotations=msg.get("annotations") or None)


def parse_openai_completion(data: Dict[str, Any], model: str) -> ChatCompletion:
    choices = []
    for i, ch in enumerate(data.get("choices") or [{}]):
        msg = parse_openai_message(ch.get("message") or {})
        finish = FINISH.get(ch.get("finish_reason") or "stop", "stop")
        if msg.refusal and finish == "stop":
            finish = "content_filter"
        choices.append(Choice(index=ch.get("index", i), message=msg,
                              finish_reason=finish_with_calls(finish, bool(msg.tool_calls)),
                              logprobs=ch.get("logprobs")))
    out = ChatCompletion(model=data.get("model") or model, choices=choices,
                         usage=parse_openai_usage(data.get("usage")),
                         system_fingerprint=data.get("system_fingerprint"), service_tier=data.get("service_tier"))
    if data.get("id"):
        out.id = data["id"]
    if data.get("created"):
        out.created = int(data["created"])
    return out


class OpenAIStreamTranslator(StreamTranslator):
    def feed(self, event: str, data: Any) -> List:
        if isinstance(data, str) and data.strip() == "[DONE]":
            return []
        chunk = safe_json_loads(data) if isinstance(data, str) else data
        out = []
        self.model_name = chunk.get("model") or self.model_name
        if chunk.get("usage"):
            self.usage = parse_openai_usage(chunk["usage"])
        for ch in chunk.get("choices") or []:
            if ch.get("index", 0) != 0:
                continue
            delta = ch.get("delta") or {}
            if delta.get("content"):
                out += self.text(delta["content"])
            if delta.get("refusal"):
                self.refusal = (self.refusal or "") + delta["refusal"]
                self.chars += len(delta["refusal"])
                out.append(self.chunk(ChoiceDelta(refusal=delta["refusal"])))
            for tc in delta.get("tool_calls") or []:
                key = tc.get("index", 0)
                fn = tc.get("function") or {}
                if tc.get("id") or key not in self._calls:
                    out += self.tool_start(key, tc.get("id") or f"call_{key}", fn.get("name") or "",
                                           fn.get("arguments") or "")
                else:
                    out += self.tool_args(key, fn.get("arguments") or "")
            if ch.get("logprobs") is not None:
                out.append(self.chunk(ChoiceDelta(), logprobs=ch["logprobs"]))
            if ch.get("finish_reason"):
                self.finish = FINISH.get(ch["finish_reason"], "stop")
        return out

    def close(self):
        if self.refusal and (self.finish or "stop") == "stop":
            self.finish = "content_filter"
        self.refusal = None            # already streamed as deltas
        return super().close()


class OpenAIChatModel(HTTPChatModel):
    """Chat Completions. Subclasses tweak url(), params(), wire_model() and the provider config."""

    def url(self) -> str:
        return self.provider.config.chat_path

    def params(self) -> Optional[Dict[str, str]]:
        return None

    def wire_model(self) -> str:
        return self.id

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        body = to_openai_body(request, model=self.wire_model(), cfg=self.provider.config,
                              max_tokens=self.effective_max_tokens(request),
                              temperature=self.effective_temperature(request),
                              developer_role=type(self.provider).developer_role, vision=self.capabilities.vision,
                              stream=stream)
        return WireCall(self.url(), body, self.params())

    def parse(self, data: Dict[str, Any], request: ChatCompletionRequest) -> ChatCompletion:
        return parse_openai_completion(data, self.id)

    def translator(self, request: ChatCompletionRequest) -> StreamTranslator:
        return OpenAIStreamTranslator(self, request)


class OpenAIEmbeddingModel(EmbeddingModel):
    def url(self) -> str:
        return self.provider.config.embeddings_path

    def params(self):
        return None

    def wire_model(self) -> str:
        return self.id

    def _embed(self, texts, purpose=None, dimensions=None):
        body: Dict[str, Any] = {"model": self.wire_model(), "input": list(texts)}
        dims = dimensions or self.provider.config.embedding_dimensions
        if dims:
            body["dimensions"] = dims
        with self.provider.slot():
            data = post_json(self.provider.http, self.url(), body, params=self.params(),
                             headers=self.provider.request_headers() or None,
                             provider=self.provider.name, model=self.id)
        rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
        vectors = [r.get("embedding") or [] for r in rows]
        tokens = (data.get("usage") or {}).get("prompt_tokens")
        return (vectors, int(tokens)) if tokens is not None else vectors


@register_provider
class OpenAIProvider(LLMProvider):
    name = "openai"
    config_model = OpenAIConfig
    default_base_url = "https://api.openai.com/v1"
    catalog_key = "openai"
    openai_compatible = True
    developer_role = True
    feature_defaults = OPENAI_FEATURES
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
    # api_key: the api-key header; bearer: a fixed token in api_key; entra: Microsoft Entra ID
    auth: Literal["api_key", "bearer", "entra"] = "api_key"
    max_tokens_param: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    # Entra ID (auth: entra). mode auto: client_secret if set, else workload identity if a
    # federated token file is present, else managed identity
    entra_mode: Literal["auto", "client_secret", "workload_identity", "managed_identity"] = "auto"
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[SecretStr] = None
    federated_token_file: Optional[str] = None
    entra_scope: str = "https://cognitiveservices.azure.com/.default"
    entra_authority: str = "https://login.microsoftonline.com"

    vendor_env: ClassVar[Dict[str, List[str]]] = {
        "api_key": ["AZURE_OPENAI_API_KEY"], "base_url": ["AZURE_OPENAI_ENDPOINT"],
        "api_version": ["OPENAI_API_VERSION", "AZURE_OPENAI_API_VERSION"],
        "tenant_id": ["AZURE_TENANT_ID"], "client_id": ["AZURE_CLIENT_ID"],
        "client_secret": ["AZURE_CLIENT_SECRET"], "federated_token_file": ["AZURE_FEDERATED_TOKEN_FILE"]}


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

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._tokens = None

    def auto_enabled(self) -> bool:
        if self.config.auth == "entra":
            return bool(self.base_url)
        return bool(self.api_key and self.base_url)

    @property
    def token_source(self):
        """The Entra ID token source (auth: entra), built on first use."""
        if self._tokens is None and self.config.auth == "entra":
            from sajha.ai.llm.cloud_auth import EntraTokenSource
            c = self.config
            self._tokens = EntraTokenSource(
                c.tenant_id or "", c.client_id or "", c.client_secret.get_secret_value() if c.client_secret else None,
                federated_token_file=c.federated_token_file, scope=c.entra_scope, authority=c.entra_authority,
                mode=c.entra_mode, transport=self._transport, environ={})
        return self._tokens

    def live_models(self):
        """Configured deployments are this resource's models (model id -> deployment name)."""
        from sajha.ai.llm.model import ModelDescriptor
        return [ModelDescriptor(mid, self.unknown_model_capabilities, kind="embedding" if "embed" in mid else "chat",
                                source="config", deployment=dep) for mid, dep in self.config.deployments.items()]

    def auth_headers(self) -> Dict[str, str]:
        if self.config.auth == "entra" or not self.api_key:
            return {}
        if self.config.auth == "bearer":
            return {"Authorization": f"Bearer {self.api_key}"}
        return {"api-key": self.api_key}

    def request_headers(self) -> Dict[str, str]:
        if self.config.auth != "entra":
            return {}
        return {"Authorization": f"Bearer {self.token_source.token()}"}

    async def arequest_headers(self) -> Dict[str, str]:
        if self.config.auth != "entra":
            return {}
        return {"Authorization": f"Bearer {await self.token_source.atoken()}"}

    def health(self):
        from sajha.ai.llm.model import HealthStatus
        if self.config.auth == "entra":
            if not self.active:
                return HealthStatus("down", "disabled" if self.config.enabled is False else "not configured")
            return HealthStatus("ok", f"entra ({self.token_source.effective_mode()})")
        return super().health()

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
    developer_role = False
    feature_defaults = COMPAT_FEATURES
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
            embeddings: bool = False, extra_env: Optional[Dict[str, List[str]]] = None,
            features: Optional[Dict[str, Any]] = None):
    """Declare an OpenAI-compatible vendor: its own name, config model, base URL, key variables."""
    env = {"api_key": key_vars}
    env.update(extra_env or {})
    cfg = type(f"{pname.title().replace('_', '')}Config", (CompatConfig,), {"__module__": __name__})
    cfg.vendor_env = env
    cls = type(f"{pname.title().replace('_', '')}Provider", (OpenAICompatibleProvider,), {
        "name": pname, "config_model": cfg, "default_base_url": base_url, "catalog_key": pname,
        "requires_key": requires_key, "unknown_model_capabilities": caps,
        "feature_defaults": {**COMPAT_FEATURES, **(features or {})},
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
                           caps=ModelCapabilities(tools=True, structured_output=False, context_window=128_000),
                           features={"json_mode": True})
XAIProvider = _preset("xai", "https://api.x.ai/v1", ["XAI_API_KEY"])
OpenRouterProvider = _preset("openrouter", "https://openrouter.ai/api/v1", ["OPENROUTER_API_KEY"])
PerplexityProvider = _preset("perplexity", "https://api.perplexity.ai", ["PERPLEXITY_API_KEY", "PPLX_API_KEY"],
                             caps=ModelCapabilities(tools=False, structured_output=True, context_window=127_000))
VLLMProvider = _preset("vllm", "http://localhost:8000/v1", ["VLLM_API_KEY"], requires_key=False,
                       caps=ModelCapabilities(tools=True, structured_output=True, context_window=32_000,
                                              tags=frozenset({"local"})), embeddings=True,
                       features={"variable_dimensions": True})
LMStudioProvider = _preset("lmstudio", "http://localhost:1234/v1", ["LMSTUDIO_API_KEY"], requires_key=False,
                           caps=ModelCapabilities(tools=True, structured_output=True, context_window=32_000,
                                                  tags=frozenset({"local"})), embeddings=True)
