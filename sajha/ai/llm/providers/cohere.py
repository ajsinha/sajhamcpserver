"""
SAJHA Intelligence Layer — Cohere v2 Chat and Embed (plain httpx).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

POST {base}/v2/chat with a bearer key. Tools are function definitions; the reply carries
message.tool_calls; tool results go back as role "tool" messages. Structured output:
response_format {type: json_object, json_schema}. Streaming SSE events: content-delta,
tool-call-start, tool-call-delta, message-end. Embeddings: POST /v2/embed.
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar, Dict, Iterator, List, Literal, Optional

from sajha.ai.llm.http import iter_sse, post_json, safe_json_loads, stream_post
from sajha.ai.llm.model import ChatModel, EmbeddingModel, ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, Message, TextDelta, TextPart, ToolCallDelta,
                                ToolCallPart, UsageEvent)

FINISH = {"COMPLETE": "stop", "STOP_SEQUENCE": "stop", "MAX_TOKENS": "length", "TOOL_CALL": "tool_calls",
          "ERROR": "error", "TIMEOUT": "error"}


class CohereConfig(ProviderConfig):
    tool_result_format: Literal["text", "document"] = "text"
    embedding_input_type: str = "search_document"
    chat_path: str = "/v2/chat"
    embed_path: str = "/v2/embed"
    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["COHERE_API_KEY", "CO_API_KEY"],
                                                  "base_url": ["COHERE_BASE_URL"]}


class CohereChatModel(ChatModel):
    def payload(self, request: ChatRequest, stream: bool = False) -> Dict[str, Any]:
        cfg = self.provider.config
        msgs: List[Dict[str, Any]] = []
        if request.system:
            msgs.append({"role": "system", "content": request.system})
        for m in request.messages:
            if m.role in ("system", "user") and m.text:
                msgs.append({"role": m.role, "content": m.text})
            elif m.role == "assistant":
                am: Dict[str, Any] = {"role": "assistant"}
                if m.tool_calls:
                    am["tool_calls"] = [{"id": c.id, "type": "function",
                                         "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                        for c in m.tool_calls]
                    if m.text:
                        am["tool_plan"] = m.text
                elif m.text:
                    am["content"] = m.text
                msgs.append(am)
            for r in m.tool_results:
                text = ("ERROR: " if r.is_error else "") + r.content_text()
                content: Any = text
                if cfg.tool_result_format == "document":
                    content = [{"type": "document", "document": {"data": text}}]
                msgs.append({"role": "tool", "tool_call_id": r.call_id, "content": content})
        body: Dict[str, Any] = {"model": self.id, "messages": msgs,
                                "max_tokens": self.effective_max_tokens(request)}
        t = self.effective_temperature(request)
        if t is not None:
            body["temperature"] = t
        if request.stop:
            body["stop_sequences"] = list(request.stop)
        if request.tools and request.tool_choice != "none":
            body["tools"] = [{"type": "function", "function": {"name": s.name, "description": s.description,
                                                               "parameters": s.input_schema or {"type": "object"}}}
                             for s in request.tools]
            if request.tool_choice != "auto" and self.capabilities.forced_tool_choice:
                body["tool_choice"] = "REQUIRED"
        elif request.tools and request.tool_choice == "none":
            pass
        if request.response_schema:
            body["response_format"] = {"type": "json_object", "json_schema": request.response_schema}
        if stream:
            body["stream"] = True
        return body

    def _usage(self, u: Dict[str, Any]):
        tok = u.get("tokens") or u.get("billed_units") or {}
        return self.make_usage(tok.get("input_tokens") or 0, tok.get("output_tokens") or 0)

    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        with self.provider.slot():
            data = post_json(self.provider.http, self.provider.config.chat_path, self.payload(request),
                             provider=self.provider.name, model=self.id)
        m = data.get("message") or {}
        parts: List[Any] = []
        text = "".join(c.get("text", "") for c in (m.get("content") or []) if c.get("type") == "text")
        if text:
            parts.append(TextPart(text))
        elif m.get("tool_plan") and m.get("tool_calls"):
            parts.append(TextPart(m["tool_plan"]))
        for i, tc in enumerate(m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            parts.append(ToolCallPart(tc.get("id") or f"call_{i}", fn.get("name", ""),
                                      safe_json_loads(fn.get("arguments") or "")))
        finish = FINISH.get(data.get("finish_reason") or "COMPLETE", "stop")
        return ChatResponse(Message("assistant", parts), finish, self._usage(data.get("usage") or {}), self.id,
                            self.provider.name, int((time.time() - t0) * 1000), raw=data)

    def stream(self, request: ChatRequest) -> Iterator:
        if not self.capabilities.streaming:
            yield from super().stream(request)
            return
        self.validate(request)
        t0 = time.time()
        text: List[str] = []
        calls: Dict[int, Dict[str, str]] = {}
        finish, usage = "stop", None
        with self.provider.slot():
            with stream_post(self.provider.http, self.provider.config.chat_path, self.payload(request, True),
                             provider=self.provider.name, model=self.id) as resp:
                for _ev, data in iter_sse(resp):
                    ev = safe_json_loads(data)
                    et = ev.get("type", "")
                    delta = ev.get("delta") or {}
                    msg = delta.get("message") or {}
                    if et == "content-delta":
                        t = ((msg.get("content") or {}).get("text")) or ""
                        if t:
                            text.append(t)
                            yield TextDelta(t)
                    elif et == "tool-call-start":
                        tc = msg.get("tool_calls") or {}
                        idx = ev.get("index", len(calls))
                        fn = tc.get("function") or {}
                        calls[idx] = {"id": tc.get("id", ""), "name": fn.get("name", ""),
                                      "args": fn.get("arguments") or ""}
                        yield ToolCallDelta(calls[idx]["id"], calls[idx]["name"], calls[idx]["args"], idx)
                    elif et == "tool-call-delta":
                        idx = ev.get("index", max(calls) if calls else 0)
                        frag = (((msg.get("tool_calls") or {}).get("function") or {}).get("arguments")) or ""
                        slot = calls.setdefault(idx, {"id": "", "name": "", "args": ""})
                        slot["args"] += frag
                        yield ToolCallDelta(slot["id"], "", frag, idx)
                    elif et == "message-end":
                        finish = FINISH.get(delta.get("finish_reason") or "COMPLETE", "stop")
                        usage = self._usage(delta.get("usage") or {})
        parts: List[Any] = [TextPart("".join(text))] if text else []
        for idx in sorted(calls):
            c = calls[idx]
            parts.append(ToolCallPart(c["id"] or f"call_{idx}", c["name"], safe_json_loads(c["args"])))
        usage = usage or self.make_usage(self.count_tokens(request), sum(map(len, text)) // 4)
        yield UsageEvent(usage)
        yield Done(ChatResponse(Message("assistant", parts), finish, usage, self.id, self.provider.name,
                                int((time.time() - t0) * 1000)))


class CohereEmbeddingModel(EmbeddingModel):
    def embed(self, texts: List[str]) -> List[List[float]]:
        cfg = self.provider.config
        body: Dict[str, Any] = {"model": self.id, "texts": list(texts), "input_type": cfg.embedding_input_type,
                                "embedding_types": ["float"]}
        if cfg.embedding_dimensions:
            body["output_dimension"] = cfg.embedding_dimensions
        with self.provider.slot():
            data = post_json(self.provider.http, cfg.embed_path, body, provider=self.provider.name, model=self.id)
        emb = data.get("embeddings") or {}
        return emb.get("float") if isinstance(emb, dict) else emb


@register_provider
class CohereProvider(LLMProvider):
    name = "cohere"
    config_model = CohereConfig
    default_base_url = "https://api.cohere.com"
    catalog_key = "cohere"
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, context_window=128_000)
    chat_model_class = CohereChatModel
    embedding_model_class = CohereEmbeddingModel

    def auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
