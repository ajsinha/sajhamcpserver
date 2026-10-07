"""
SAJHA Intelligence Layer — Cohere v2 Chat and Embed (plain httpx).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Translates the canonical Chat Completions format to POST {base}/v2/chat and back:

  messages        system/developer -> system; assistant tool_calls (+ ``tool_plan`` text); tool
                  results as role "tool" (text, or document parts with ``tool_result_format: document``)
  tools           function definitions, as in OpenAI
  tool_choice     required -> REQUIRED. Cohere has no named choice: a named tool_choice is accepted
                  only when that function is the only one offered (then REQUIRED) and refused
                  otherwise (model.prepare)
  sampling        temperature, ``p`` (top_p), ``seed``, ``stop_sequences``, ``max_tokens``
  response_format ``{type: json_object, json_schema?}``
  finish_reason   COMPLETE/STOP_SEQUENCE -> stop, MAX_TOKENS -> length, TOOL_CALL -> tool_calls;
                  ERROR and TIMEOUT -> ModelFailed (the gateway tries the next candidate)

Streaming SSE events: content-delta, tool-call-start, tool-call-delta, message-end.
Embeddings: POST /v2/embed with ``input_type`` from the request's purpose (query ->
search_query, document -> search_document; the configured value when none is named) and
``output_dimension``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Literal, Optional

from sajha.ai.llm.adapter import HTTPChatModel, StreamTranslator, WireCall, assistant_text, tool_result_text
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionRequest, ChatMessage, Choice, CompletionUsage,
                                    FunctionCall, ToolCall)
from sajha.ai.llm.errors import ModelFailed
from sajha.ai.llm.http import post_json, safe_json_loads
from sajha.ai.llm.model import EmbeddingModel, ModelCapabilities
from sajha.ai.llm.provider import ProviderBase
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig

FINISH = {"COMPLETE": "stop", "STOP_SEQUENCE": "stop", "MAX_TOKENS": "length", "TOOL_CALL": "tool_calls"}
FAILED = ("ERROR", "TIMEOUT")
INPUT_TYPE = {"query": "search_query", "document": "search_document"}


class CohereConfig(ProviderConfig):
    tool_result_format: Literal["text", "document"] = "text"
    embedding_input_type: str = "search_document"     # when a request names no purpose
    chat_path: str = "/v2/chat"
    embed_path: str = "/v2/embed"
    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["COHERE_API_KEY", "CO_API_KEY"],
                                                  "base_url": ["COHERE_BASE_URL"]}


# ── wire mapping (pure; golden-tested) ─────────────────────────────

def to_cohere_body(request: ChatCompletionRequest, *, model: str, cfg: CohereConfig, max_tokens: int,
                   temperature: Optional[float], stream: bool = False) -> Dict[str, Any]:
    msgs: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("system", "developer", "user"):
            if m.text:
                msgs.append({"role": "system" if m.role == "developer" else m.role, "content": m.text})
        elif m.role == "assistant":
            am: Dict[str, Any] = {"role": "assistant"}
            if m.tool_calls:
                am["tool_calls"] = [{"id": c.id, "type": "function",
                                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                    for c in m.tool_calls]
                if assistant_text(m):
                    am["tool_plan"] = assistant_text(m)
            elif assistant_text(m):
                am["content"] = assistant_text(m)
            msgs.append(am)
        elif m.role == "tool":
            text = tool_result_text(m)
            content: Any = text
            if cfg.tool_result_format == "document":
                content = [{"type": "document", "document": {"data": text}}]
            msgs.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": content})
    body: Dict[str, Any] = {"model": model, "messages": msgs, "max_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature
    if request.top_p is not None:
        body["p"] = request.top_p
    if request.seed is not None:
        body["seed"] = request.seed
    if request.stop_list:
        body["stop_sequences"] = request.stop_list
    if request.wants_tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t.name, "description": (t.function.description or "") if t.function else "",
            "parameters": t.parameters_or_default}} for t in request.tools or []]
        if request.tool_choice_mode in ("required", "named"):
            body["tool_choice"] = "REQUIRED"
    kind = request.output_kind
    if kind:
        rf: Dict[str, Any] = {"type": "json_object"}
        if kind == "json_schema":
            rf["json_schema"] = request.output_schema
        body["response_format"] = rf
    body.update(request.extra_body or {})
    if stream:
        body["stream"] = True
    return body


def cohere_usage(u: Dict[str, Any]) -> Optional[CompletionUsage]:
    tok = u.get("tokens") or u.get("billed_units") or {}
    if not tok:
        return None
    return CompletionUsage.of(tok.get("input_tokens") or 0, tok.get("output_tokens") or 0)


def cohere_finish(reason: Optional[str], has_calls: bool, provider: str, model: str) -> str:
    if reason in FAILED:
        raise ModelFailed(f"cohere finished with {reason}", provider=provider, model=model)
    f = FINISH.get(reason or "COMPLETE", "stop")
    return "tool_calls" if has_calls and f == "stop" else f


def parse_cohere(data: Dict[str, Any], model: str, provider: str) -> ChatCompletion:
    m = data.get("message") or {}
    text = "".join(c.get("text", "") for c in (m.get("content") or []) if c.get("type") == "text")
    if not text and m.get("tool_plan") and m.get("tool_calls"):
        text = m["tool_plan"]
    calls = [ToolCall(id=tc.get("id") or f"call_{i}", function=FunctionCall(
        name=(tc.get("function") or {}).get("name", ""), arguments=(tc.get("function") or {}).get("arguments") or "{}"))
        for i, tc in enumerate(m.get("tool_calls") or [])]
    finish = cohere_finish(data.get("finish_reason"), bool(calls), provider, model)
    out = ChatCompletion(model=model, choices=[Choice(message=ChatMessage(role="assistant", content=text or None,
                                                                          tool_calls=calls or None),
                                                      finish_reason=finish)],
                         usage=cohere_usage(data.get("usage") or {}))
    if data.get("id"):
        out.id = data["id"]
    return out


class CohereStreamTranslator(StreamTranslator):
    def __init__(self, model, request):
        super().__init__(model, request)
        self.reason: Optional[str] = None

    def feed(self, event: str, data: Any) -> List:
        ev = safe_json_loads(data) if isinstance(data, str) else data
        et = ev.get("type", "") or event
        delta = ev.get("delta") or {}
        msg = delta.get("message") or {}
        out: List = []
        if et == "content-delta":
            out += self.text(((msg.get("content") or {}).get("text")) or "")
        elif et == "tool-plan-delta":          # the plan before tool calls, as content (as in a reply)
            out += self.text(msg.get("tool_plan") or "")
        elif et == "tool-call-start":
            tc = msg.get("tool_calls") or {}
            idx = ev.get("index", len(self._calls))
            fn = tc.get("function") or {}
            out += self.tool_start(idx, tc.get("id") or f"call_{idx}", fn.get("name", ""), fn.get("arguments") or "")
        elif et == "tool-call-delta":
            idx = ev.get("index", max(self._calls) if self._calls else 0)
            out += self.tool_args(idx, (((msg.get("tool_calls") or {}).get("function") or {}).get("arguments")) or "")
        elif et == "message-end":
            self.reason = delta.get("finish_reason") or "COMPLETE"
            self.usage = cohere_usage(delta.get("usage") or {})
        return out

    def close(self) -> List:
        self.finish = cohere_finish(self.reason, self.has_calls, self.model.provider.name, self.model.id)
        return super().close()


class CohereChatModel(HTTPChatModel):
    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        return WireCall(self.provider.config.chat_path,
                        to_cohere_body(request, model=self.id, cfg=self.provider.config,
                                       max_tokens=self.effective_max_tokens(request),
                                       temperature=self.effective_temperature(request), stream=stream))

    def parse(self, data: Dict[str, Any], request: ChatCompletionRequest) -> ChatCompletion:
        return parse_cohere(data, self.id, self.provider.name)

    def translator(self, request: ChatCompletionRequest) -> StreamTranslator:
        return CohereStreamTranslator(self, request)


class CohereEmbeddingModel(EmbeddingModel):
    def _embed(self, texts, purpose=None, dimensions=None):
        cfg = self.provider.config
        body: Dict[str, Any] = {"model": self.id, "texts": list(texts),
                                "input_type": INPUT_TYPE.get(purpose or "") or cfg.embedding_input_type,
                                "embedding_types": ["float"]}
        dims = dimensions or cfg.embedding_dimensions
        if dims:
            body["output_dimension"] = dims
        with self.provider.slot():
            data = post_json(self.provider.http, cfg.embed_path, body, provider=self.provider.name, model=self.id)
        emb = data.get("embeddings") or {}
        vectors = emb.get("float") if isinstance(emb, dict) else emb
        tokens = ((data.get("meta") or {}).get("billed_units") or {}).get("input_tokens")
        return (vectors, int(tokens)) if tokens is not None else vectors


@register_provider
class CohereProvider(ProviderBase):
    name = "cohere"
    config_model = CohereConfig
    default_base_url = "https://api.cohere.com"
    catalog_key = "cohere"
    feature_defaults = {"seed": True, "named_tool_choice": False, "json_mode": True, "variable_dimensions": True}
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, context_window=128_000)
    chat_model_class = CohereChatModel
    embedding_model_class = CohereEmbeddingModel

    def auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}


