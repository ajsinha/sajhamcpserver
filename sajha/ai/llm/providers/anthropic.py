"""
SAJHA Intelligence Layer — Anthropic Messages API (plain httpx), direct or on Vertex AI.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Translates the canonical Chat Completions format to the Messages API and back:

  system / developer messages   one top-level ``system`` text, joined with a blank line
  tools                         ``tools[].input_schema``; tool_choice auto | any | {type: tool, name};
                                ``parallel_tool_calls: false`` -> ``disable_parallel_tool_use``
  tool calls / results          ``tool_use`` / ``tool_result`` blocks (``is_error`` kept)
  images                        data: URLs -> base64 image source
  response_format               ``output_config.format`` (json_schema; json_object -> {"type": "object"})
  reasoning_effort              ``output_config.effort``
  top_p, stop                   ``top_p``, ``stop_sequences``
  stop_reason                   end_turn/stop_sequence/pause_turn -> stop, max_tokens and
                                model_context_window_exceeded -> length, tool_use -> tool_calls,
                                refusal -> content_filter with ``message.refusal``
  usage                         prompt = input + cache reads + cache writes; cached = cache reads

Assistant content blocks (thinking included) ride on the assistant message as private
provider state and are echoed verbatim on the next turn to the same provider, as tool loops on
thinking models require. Streaming parses message_start, content_block_start,
content_block_delta (text_delta, input_json_delta, thinking_delta, signature_delta),
message_delta and error events.

``platform: vertex`` serves Claude from Vertex AI: POST
``/v1/projects/{p}/locations/{l}/publishers/anthropic/models/{model}:rawPredict`` (and
``:streamRawPredict``) with ``anthropic_version: vertex-2023-10-16`` in the body and a Google
access token from a service-account file or workload identity (cloud_auth.GoogleTokenSource).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import Field

from sajha.ai.llm.adapter import (HTTPChatModel, StreamTranslator, WireCall, assistant_text, system_text)
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionRequest, ChatMessage, Choice, CompletionUsage,
                                    FunctionCall, MessageSajha, ToolCall, split_data_url)
from sajha.ai.llm.errors import InvalidRequest, ProviderUnavailable, RateLimited
from sajha.ai.llm.http import safe_json_loads
from sajha.ai.llm.model import ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig

STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
        "refusal": "content_filter", "pause_turn": "stop", "model_context_window_exceeded": "length"}
REFUSAL_TEXT = "The model declined to answer (Anthropic stop_reason: refusal)."
VERTEX_VERSION = "vertex-2023-10-16"


class AnthropicConfig(ProviderConfig):
    api_version: str = "2023-06-01"
    beta_headers: List[str] = Field(default_factory=list)       # sent as anthropic-beta
    auth: Literal["api_key", "bearer"] = "api_key"
    structured_output_param: Literal["output_config", "output_format"] = "output_config"
    messages_path: str = "/v1/messages"
    extra_body: Dict[str, Any] = Field(default_factory=dict)    # e.g. {"thinking": {...}}
    # Vertex AI (platform: vertex): project, location and Google credentials
    platform: Literal["anthropic", "vertex"] = "anthropic"
    vertex_project: Optional[str] = None
    vertex_location: str = "global"
    credentials_file: Optional[str] = None      # a service-account JSON; empty = workload identity

    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["ANTHROPIC_API_KEY"],
                                                  "base_url": ["ANTHROPIC_BASE_URL"],
                                                  "vertex_project": ["ANTHROPIC_VERTEX_PROJECT_ID"],
                                                  "vertex_location": ["CLOUD_ML_REGION"],
                                                  "credentials_file": ["GOOGLE_APPLICATION_CREDENTIALS"]}


def vertex_base_url(location: str) -> str:
    return "https://aiplatform.googleapis.com" if location in ("", "global") \
        else f"https://{location}-aiplatform.googleapis.com"


# ── wire mapping (pure; golden-tested) ─────────────────────────────

def _user_blocks(m: ChatMessage) -> List[Dict[str, Any]]:
    out = []
    for p in m.parts:
        if p.type == "text" and p.text:
            out.append({"type": "text", "text": p.text})
        elif p.type == "image_url":
            mime, data = split_data_url(p.image_url.url)
            out.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
    return out


def to_anthropic_messages(request: ChatCompletionRequest, provider: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("system", "developer"):
            continue
        if m.role == "assistant":
            state = m.state_for(provider)
            if state and state.get("anthropic_content"):
                blocks = list(state["anthropic_content"])
            else:
                blocks = [{"type": "text", "text": assistant_text(m)}] if assistant_text(m) else []
                blocks += [{"type": "tool_use", "id": c.id, "name": c.function.name, "input": c.function.args()}
                           for c in m.tool_calls or []]
            role = "assistant"
        elif m.role == "tool":
            blocks = [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.text,
                       "is_error": m.is_error}]
            role = "user"
        else:
            blocks, role = _user_blocks(m), "user"
        if not blocks:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    return out


def to_anthropic_body(request: ChatCompletionRequest, *, model: str, provider: str, cfg: AnthropicConfig,
                      max_tokens: int, temperature: Optional[float], stream: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                            "messages": to_anthropic_messages(request, provider)}
    system = system_text(request)
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = temperature
    if request.top_p is not None:
        body["top_p"] = request.top_p
    if request.stop_list:
        body["stop_sequences"] = request.stop_list
    if request.wants_tools:
        body["tools"] = [{"name": t.name, "description": (t.function.description or "") if t.function else "",
                          "input_schema": t.parameters_or_default} for t in request.tools or []]
        mode = request.tool_choice_mode
        tc: Dict[str, Any] = {"type": "auto"}
        if mode == "required":
            tc = {"type": "any"}
        elif mode == "named":
            tc = {"type": "tool", "name": request.tool_choice_name}
        if request.parallel_tool_calls is False:
            tc["disable_parallel_tool_use"] = True
        body["tool_choice"] = tc
    output_config: Dict[str, Any] = {}
    kind = request.output_kind
    if kind:
        schema = request.output_schema if kind == "json_schema" else {"type": "object"}
        fmt = {"type": "json_schema", "schema": schema}
        if cfg.structured_output_param == "output_config":
            output_config["format"] = fmt
        else:
            body["output_format"] = fmt
    if request.reasoning_effort is not None:
        output_config["effort"] = request.reasoning_effort
    if output_config:
        body["output_config"] = output_config
    for k, v in {**(cfg.extra_body or {}), **(request.extra_body or {})}.items():
        if isinstance(v, dict) and isinstance(body.get(k), dict):
            body[k] = {**v, **body[k]}
        else:
            body[k] = v
    if stream:
        body["stream"] = True
    if cfg.platform == "vertex":
        body.pop("model", None)
        body["anthropic_version"] = VERTEX_VERSION
    return body


def anthropic_usage(u: Dict[str, Any]) -> CompletionUsage:
    reads = u.get("cache_read_input_tokens")
    prompt = (u.get("input_tokens") or 0) + (reads or 0) + (u.get("cache_creation_input_tokens") or 0)
    return CompletionUsage.of(prompt, u.get("output_tokens") or 0, reads if reads is not None else None)


def anthropic_message(content: List[Dict[str, Any]], stop: str, provider: str) -> tuple:
    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    calls = [ToolCall(id=b.get("id", ""), function=FunctionCall(name=b.get("name", ""),
                                                                arguments=json.dumps(b.get("input") or {})))
             for b in content if b.get("type") == "tool_use"]
    finish = STOP.get(stop or "end_turn", "stop")
    msg = ChatMessage(role="assistant", content=text or None, tool_calls=calls or None,
                      sajha=MessageSajha(provider=provider, provider_state={"anthropic_content": content}))
    if finish == "content_filter":
        msg.refusal = text or REFUSAL_TEXT
        msg.content = None
    elif calls and finish == "stop":
        finish = "tool_calls"
    return msg, finish


def parse_anthropic(data: Dict[str, Any], model: str, provider: str) -> ChatCompletion:
    msg, finish = anthropic_message(data.get("content") or [], data.get("stop_reason") or "end_turn", provider)
    out = ChatCompletion(model=data.get("model") or model, choices=[Choice(message=msg, finish_reason=finish)],
                         usage=anthropic_usage(data.get("usage") or {}))
    if data.get("id"):
        out.id = data["id"]
    return out


class AnthropicStreamTranslator(StreamTranslator):
    def __init__(self, model, request):
        super().__init__(model, request)
        self.blocks: Dict[int, Dict[str, Any]] = {}
        self.usage_in: Dict[str, Any] = {}
        self.out_tokens = 0

    def feed(self, event: str, data: Any) -> List:
        ev = safe_json_loads(data) if isinstance(data, str) else data
        et = ev.get("type") or event
        out: List = []
        if et == "message_start":
            m = ev.get("message") or {}
            self.model_name = m.get("model") or self.model_name
            self.usage_in = m.get("usage") or {}
        elif et == "content_block_start":
            idx = ev.get("index", 0)
            cb = dict(ev.get("content_block") or {})
            if cb.get("type") == "tool_use":
                cb["_json"], cb["input"] = "", {}
                out += self.tool_start(idx, cb.get("id", ""), cb.get("name", ""))
            elif cb.get("type") == "text" and cb.get("text"):
                out += self.text(cb["text"])
            self.blocks[idx] = cb
        elif et == "content_block_delta":
            idx = ev.get("index", 0)
            d = ev.get("delta") or {}
            cb = self.blocks.setdefault(idx, {"type": "text", "text": ""})
            if d.get("type") == "text_delta":
                cb["text"] = cb.get("text", "") + d.get("text", "")
                out += self.text(d.get("text", ""))
            elif d.get("type") == "input_json_delta":
                frag = d.get("partial_json", "")
                cb["_json"] = cb.get("_json", "") + frag
                out += self.tool_args(idx, frag)
            elif d.get("type") == "thinking_delta":
                cb["thinking"] = cb.get("thinking", "") + d.get("thinking", "")
            elif d.get("type") == "signature_delta":
                cb["signature"] = d.get("signature", "")
        elif et == "message_delta":
            stop = (ev.get("delta") or {}).get("stop_reason")
            if stop:
                self.finish = STOP.get(stop, "stop")
            self.out_tokens = (ev.get("usage") or {}).get("output_tokens", self.out_tokens)
        elif et == "error":
            err = ev.get("error") or {}
            typ, msg = err.get("type", ""), err.get("message", "stream error")
            kw = dict(provider=self.model.provider.name, model=self.model.id)
            if typ == "rate_limit_error":
                raise RateLimited(msg, **kw)
            if typ in ("overloaded_error", "api_error"):
                raise ProviderUnavailable(msg, **kw)
            raise InvalidRequest(f"{typ}: {msg}", **kw)
        return out

    def close(self) -> List:
        content = []
        for idx in sorted(self.blocks):
            cb = dict(self.blocks[idx])
            if cb.get("type") == "tool_use":
                cb["input"] = safe_json_loads(cb.pop("_json", ""))
            content.append(cb)
        self.state = {"anthropic_content": content}
        if self.finish == "content_filter":
            self.refusal = REFUSAL_TEXT
        self.usage = anthropic_usage({**self.usage_in, "output_tokens": self.out_tokens})
        return super().close()


class AnthropicChatModel(HTTPChatModel):
    def _path(self, stream: bool) -> str:
        cfg = self.provider.config
        if cfg.platform == "vertex":
            if not cfg.vertex_project:
                from sajha.ai.llm.errors import ConfigurationError
                raise ConfigurationError("anthropic on vertex needs vertex_project", provider=self.provider.name)
            verb = "streamRawPredict" if stream else "rawPredict"
            return (f"/v1/projects/{cfg.vertex_project}/locations/{cfg.vertex_location}/publishers/anthropic/"
                    f"models/{self.id}:{verb}")
        return cfg.messages_path

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        body = to_anthropic_body(request, model=self.id, provider=self.provider.name, cfg=self.provider.config,
                                 max_tokens=self.effective_max_tokens(request),
                                 temperature=self.effective_temperature(request), stream=stream)
        return WireCall(self._path(stream), body)

    def parse(self, data: Dict[str, Any], request: ChatCompletionRequest) -> ChatCompletion:
        return parse_anthropic(data, self.id, self.provider.name)

    def translator(self, request: ChatCompletionRequest) -> StreamTranslator:
        return AnthropicStreamTranslator(self, request)


@register_provider
class AnthropicProvider(LLMProvider):
    name = "anthropic"
    config_model = AnthropicConfig
    default_base_url = "https://api.anthropic.com"
    catalog_key = "anthropic"
    feature_defaults = {"parallel_tool_control": True, "reasoning_effort": "tagged", "json_mode": True}
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, vision=True,
                                                   context_window=200_000)
    chat_model_class = AnthropicChatModel

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._tokens = None

    @property
    def vertex(self) -> bool:
        return self.config.platform == "vertex"

    @property
    def base_url(self) -> str:
        if self.vertex and not self.config.base_url:
            return vertex_base_url(self.config.vertex_location)
        return super().base_url

    @property
    def token_source(self):
        if self._tokens is None and self.vertex:
            from sajha.ai.llm.cloud_auth import GoogleTokenSource
            self._tokens = GoogleTokenSource(self.config.credentials_file, transport=self._transport, environ={})
        return self._tokens

    def auto_enabled(self) -> bool:
        return bool(self.config.vertex_project) if self.vertex else super().auto_enabled()

    def auth_headers(self) -> Dict[str, str]:
        if self.vertex:
            return {}
        h = {"anthropic-version": self.config.api_version}
        if self.config.beta_headers:
            h["anthropic-beta"] = ",".join(self.config.beta_headers)
        if self.api_key:
            if self.config.auth == "bearer":
                h["Authorization"] = f"Bearer {self.api_key}"
            else:
                h["x-api-key"] = self.api_key
        return h

    def request_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token_source.token()}"} if self.vertex else {}

    async def arequest_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {await self.token_source.atoken()}"} if self.vertex else {}

    def health(self):
        from sajha.ai.llm.model import HealthStatus
        if self.vertex:
            if not self.active:
                return HealthStatus("down", "disabled" if self.config.enabled is False else "no vertex_project")
            return HealthStatus("ok", f"vertex {self.config.vertex_location} ({self.token_source.describe()})")
        return super().health()
