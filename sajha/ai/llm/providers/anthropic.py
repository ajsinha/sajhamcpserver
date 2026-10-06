"""
SAJHA Intelligence Layer — Anthropic Messages API (plain httpx).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

POST {base_url}/v1/messages with x-api-key + anthropic-version. Tools map to ``tools`` /
``tool_use`` / ``tool_result`` blocks; structured output uses ``output_config.format``
(type json_schema); streaming parses the SSE events message_start, content_block_start,
content_block_delta (text_delta, input_json_delta), message_delta and message_stop.
Assistant content blocks (thinking included) are kept in Message.meta and echoed verbatim on
the next turn, as tool loops on thinking models require.
"""

from __future__ import annotations

import base64
import time
from typing import Any, ClassVar, Dict, Iterator, List, Literal, Optional

from pydantic import Field

from sajha.ai.llm.errors import ContentFiltered, ProviderUnavailable, RateLimited, InvalidRequest
from sajha.ai.llm.http import iter_sse, post_json, safe_json_loads, stream_post
from sajha.ai.llm.model import ChatModel, ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, TextDelta, TextPart,
                                ToolCallDelta, ToolCallPart, UsageEvent)

STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
        "refusal": "content_filter", "pause_turn": "stop", "model_context_window_exceeded": "length"}


class AnthropicConfig(ProviderConfig):
    api_version: str = "2023-06-01"
    beta_headers: List[str] = Field(default_factory=list)       # sent as anthropic-beta
    auth: Literal["api_key", "bearer"] = "api_key"
    structured_output_param: Literal["output_config", "output_format"] = "output_config"
    messages_path: str = "/v1/messages"
    extra_body: Dict[str, Any] = Field(default_factory=dict)    # e.g. {"output_config": {"effort": "low"}}

    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["ANTHROPIC_API_KEY"],
                                                  "base_url": ["ANTHROPIC_BASE_URL"]}


def _blocks(m: Message, provider: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for p in m.parts:
        if isinstance(p, TextPart):
            if p.text:
                blocks.append({"type": "text", "text": p.text})
        elif isinstance(p, ImagePart):
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": p.mime_type,
                                                       "data": base64.b64encode(p.data).decode()}})
        elif isinstance(p, ToolCallPart):
            blocks.append({"type": "tool_use", "id": p.id, "name": p.name, "input": p.arguments})
    for r in m.tool_results:
        blocks.append({"type": "tool_result", "tool_use_id": r.call_id, "content": r.content_text(),
                       "is_error": bool(r.is_error)})
    return blocks


def to_anthropic(request: ChatRequest, provider: str):
    system = [request.system] if request.system else []
    out: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role == "system":
            system.append(m.text)
            continue
        role = "assistant" if m.role == "assistant" else "user"
        if role == "assistant" and m.meta.get("anthropic_content") and m.meta.get("provider") == provider:
            blocks = list(m.meta["anthropic_content"])
        else:
            blocks = _blocks(m, provider)
        if not blocks:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})
    return "\n\n".join(s for s in system if s), out


class AnthropicChatModel(ChatModel):
    def payload(self, request: ChatRequest, stream: bool = False) -> Dict[str, Any]:
        cfg = self.provider.config
        system, messages = to_anthropic(request, self.provider.name)
        body: Dict[str, Any] = {"model": self.id, "max_tokens": self.effective_max_tokens(request),
                                "messages": messages}
        if system:
            body["system"] = system
        t = self.effective_temperature(request)
        if t is not None:
            body["temperature"] = t
        if request.stop:
            body["stop_sequences"] = list(request.stop)
        if request.tools and request.tool_choice != "none":
            body["tools"] = [{"name": s.name, "description": s.description,
                              "input_schema": s.input_schema or {"type": "object", "properties": {}}}
                             for s in request.tools]
            tc = request.tool_choice
            forced = self.capabilities.forced_tool_choice
            if tc == "required":
                body["tool_choice"] = {"type": "any"} if forced else {"type": "auto"}
            elif tc not in ("auto", "none"):
                body["tool_choice"] = {"type": "tool", "name": tc} if forced else {"type": "auto"}
            else:
                body["tool_choice"] = {"type": "auto"}
        if request.response_schema:
            fmt = {"type": "json_schema", "schema": request.response_schema}
            if cfg.structured_output_param == "output_config":
                body["output_config"] = {"format": fmt}
            else:
                body["output_format"] = fmt
        for k, v in (cfg.extra_body or {}).items():
            if isinstance(v, dict) and isinstance(body.get(k), dict):
                body[k] = {**v, **body[k]}
            else:
                body[k] = v
        if stream:
            body["stream"] = True
        return body

    def _usage(self, u: Dict[str, Any]):
        return self.make_usage((u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                               + (u.get("cache_creation_input_tokens") or 0),
                               u.get("output_tokens") or 0, u.get("cache_read_input_tokens") or 0)

    def _message(self, content: List[Dict[str, Any]]) -> Message:
        parts: List[Any] = []
        for b in content:
            if b.get("type") == "text" and b.get("text"):
                parts.append(TextPart(b["text"]))
            elif b.get("type") == "tool_use":
                parts.append(ToolCallPart(b.get("id", ""), b.get("name", ""), b.get("input") or {}))
        return Message("assistant", parts, meta={"anthropic_content": content, "provider": self.provider.name})

    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        with self.provider.slot():
            data = post_json(self.provider.http, self.provider.config.messages_path, self.payload(request),
                             provider=self.provider.name, model=self.id)
        msg = self._message(data.get("content") or [])
        finish = STOP.get(data.get("stop_reason") or "end_turn", "stop")
        return ChatResponse(msg, finish, self._usage(data.get("usage") or {}), data.get("model") or self.id,
                            self.provider.name, int((time.time() - t0) * 1000), raw=data)

    def stream(self, request: ChatRequest) -> Iterator:
        if not self.capabilities.streaming:
            yield from super().stream(request)
            return
        self.validate(request)
        t0 = time.time()
        blocks: Dict[int, Dict[str, Any]] = {}
        usage_in: Dict[str, Any] = {}
        out_tokens = 0
        finish = "stop"
        model = self.id
        with self.provider.slot():
            with stream_post(self.provider.http, self.provider.config.messages_path,
                             self.payload(request, stream=True), provider=self.provider.name,
                             model=self.id) as resp:
                for event, data in iter_sse(resp):
                    ev = safe_json_loads(data)
                    et = ev.get("type") or event
                    if et == "message_start":
                        m = ev.get("message") or {}
                        model = m.get("model") or model
                        usage_in = m.get("usage") or {}
                    elif et == "content_block_start":
                        cb = dict(ev.get("content_block") or {})
                        if cb.get("type") == "tool_use":
                            cb["_json"] = ""
                            cb["input"] = {}
                            yield ToolCallDelta(cb.get("id", ""), cb.get("name", ""), "", ev.get("index", 0))
                        blocks[ev.get("index", 0)] = cb
                    elif et == "content_block_delta":
                        idx = ev.get("index", 0)
                        d = ev.get("delta") or {}
                        cb = blocks.setdefault(idx, {"type": "text", "text": ""})
                        if d.get("type") == "text_delta":
                            cb["text"] = cb.get("text", "") + d.get("text", "")
                            yield TextDelta(d.get("text", ""))
                        elif d.get("type") == "input_json_delta":
                            frag = d.get("partial_json", "")
                            cb["_json"] = cb.get("_json", "") + frag
                            yield ToolCallDelta(cb.get("id", ""), "", frag, idx)
                        elif d.get("type") == "thinking_delta":
                            cb["thinking"] = cb.get("thinking", "") + d.get("thinking", "")
                        elif d.get("type") == "signature_delta":
                            cb["signature"] = d.get("signature", "")
                    elif et == "message_delta":
                        finish = STOP.get((ev.get("delta") or {}).get("stop_reason") or "end_turn", "stop")
                        out_tokens = (ev.get("usage") or {}).get("output_tokens", out_tokens)
                    elif et == "error":
                        err = ev.get("error") or {}
                        typ, msg = err.get("type", ""), err.get("message", "stream error")
                        kw = dict(provider=self.provider.name, model=self.id)
                        if typ == "rate_limit_error":
                            raise RateLimited(msg, **kw)
                        if typ in ("overloaded_error", "api_error"):
                            raise ProviderUnavailable(msg, **kw)
                        raise InvalidRequest(f"{typ}: {msg}", **kw)
        content = []
        for idx in sorted(blocks):
            cb = blocks[idx]
            if cb.get("type") == "tool_use":
                cb["input"] = safe_json_loads(cb.pop("_json", ""))
            content.append(cb)
        usage = self._usage({**usage_in, "output_tokens": out_tokens})
        resp_obj = ChatResponse(self._message(content), finish, usage, model, self.provider.name,
                                int((time.time() - t0) * 1000))
        yield UsageEvent(usage)
        yield Done(resp_obj)


@register_provider
class AnthropicProvider(LLMProvider):
    name = "anthropic"
    config_model = AnthropicConfig
    default_base_url = "https://api.anthropic.com"
    catalog_key = "anthropic"
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, vision=True,
                                                   context_window=200_000)
    chat_model_class = AnthropicChatModel

    def auth_headers(self) -> Dict[str, str]:
        h = {"anthropic-version": self.config.api_version}
        if self.config.beta_headers:
            h["anthropic-beta"] = ",".join(self.config.beta_headers)
        if self.api_key:
            if self.config.auth == "bearer":
                h["Authorization"] = f"Bearer {self.api_key}"
            else:
                h["x-api-key"] = self.api_key
        return h
