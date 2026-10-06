"""
SAJHA Intelligence Layer — Google Gemini (AI Studio generateContent API, plain httpx).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

POST {base}/{api_version}/models/{model}:generateContent with x-goog-api-key. Tools map to
functionDeclarations / functionCall / functionResponse; structured output uses
responseMimeType=application/json with responseJsonSchema (schema_mode=json_schema, default)
or the OpenAPI-subset responseSchema (schema_mode=openapi). Streaming uses
:streamGenerateContent?alt=sse. Model content parts (thought signatures included) are kept in
Message.meta and echoed back verbatim on the next turn. Embeddings: :batchEmbedContents.
Vertex AI is not wired yet (use base_url + extra_headers with a bearer token to experiment).
"""

from __future__ import annotations

import base64
import time
from typing import Any, ClassVar, Dict, Iterator, List, Literal, Optional

import httpx
from pydantic import Field

from sajha.ai.llm.errors import AuthenticationFailed, ContentFiltered
from sajha.ai.llm.http import iter_sse, post_json, stream_post
from sajha.ai.llm.model import ChatModel, EmbeddingModel, ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, TextDelta, TextPart,
                                ToolCallDelta, ToolCallPart, UsageEvent)

FINISH = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter",
          "PROHIBITED_CONTENT": "content_filter", "BLOCKLIST": "content_filter", "SPII": "content_filter",
          "IMAGE_SAFETY": "content_filter", "MALFORMED_FUNCTION_CALL": "error", "OTHER": "stop"}
_OPENAPI_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable",
                 "minimum", "maximum", "minItems", "maxItems", "anyOf", "propertyOrdering"}


class GeminiConfig(ProviderConfig):
    api_version: str = "v1beta"
    schema_mode: Literal["json_schema", "openapi"] = "json_schema"
    safety_settings: List[Dict[str, Any]] = Field(default_factory=list)
    generation_config: Dict[str, Any] = Field(default_factory=dict)   # merged into generationConfig
    embedding_task_type: Optional[str] = "RETRIEVAL_DOCUMENT"

    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                                                  "base_url": ["GEMINI_BASE_URL"]}


def openapi_schema(schema: Any) -> Any:
    """Reduce a JSON Schema to Gemini's OpenAPI subset (schema_mode=openapi)."""
    if isinstance(schema, list):
        return [openapi_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: Dict[str, Any] = {}
    for k, v in schema.items():
        if k not in _OPENAPI_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: openapi_schema(pv) for pk, pv in v.items()}
        elif k in ("items",):
            out[k] = openapi_schema(v)
        elif k == "anyOf":
            out[k] = [openapi_schema(x) for x in v]
        elif k == "type" and isinstance(v, list):
            types = [t for t in v if t != "null"]
            out["type"] = (types[0] if types else "string").upper()
            if "null" in v:
                out["nullable"] = True
        elif k == "type":
            out[k] = str(v).upper()
        else:
            out[k] = v
    return out


def _classify(resp: httpx.Response):
    text = resp.text.lower()
    if resp.status_code == 400 and ("api key not valid" in text or "api_key_invalid" in text):
        return AuthenticationFailed(f"gemini HTTP 400: API key not valid", provider="gemini", status=400)
    return None


class GeminiChatModel(ChatModel):
    def _schema(self, s: dict) -> dict:
        return s if self.provider.config.schema_mode == "json_schema" else openapi_schema(s)

    def payload(self, request: ChatRequest) -> Dict[str, Any]:
        cfg = self.provider.config
        names: Dict[str, str] = {}
        contents: List[Dict[str, Any]] = []
        system = [request.system] if request.system else []
        for m in request.messages:
            if m.role == "system":
                system.append(m.text)
                continue
            for c in m.tool_calls:
                names[c.id] = c.name
            role = "model" if m.role == "assistant" else "user"
            if role == "model" and m.meta.get("gemini_parts") and m.meta.get("provider") == self.provider.name:
                parts = list(m.meta["gemini_parts"])
            else:
                parts = []
                for p in m.parts:
                    if isinstance(p, TextPart) and p.text:
                        parts.append({"text": p.text})
                    elif isinstance(p, ImagePart):
                        parts.append({"inlineData": {"mimeType": p.mime_type,
                                                     "data": base64.b64encode(p.data).decode()}})
                    elif isinstance(p, ToolCallPart):
                        fc = {"name": p.name, "args": p.arguments}
                        if not p.id.startswith("gcall_"):
                            fc["id"] = p.id
                        parts.append({"functionCall": fc})
                for r in m.tool_results:
                    content = r.content if isinstance(r.content, dict) else {"result": r.content_text()}
                    if r.is_error:
                        content = {"error": r.content_text()}
                    fr = {"name": r.name or names.get(r.call_id, ""), "response": content}
                    if not r.call_id.startswith("gcall_"):
                        fr["id"] = r.call_id
                    parts.append({"functionResponse": fr})
            if not parts:
                continue
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})
        body: Dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        gen: Dict[str, Any] = {"maxOutputTokens": self.effective_max_tokens(request)}
        t = self.effective_temperature(request)
        if t is not None:
            gen["temperature"] = t
        if request.stop:
            gen["stopSequences"] = list(request.stop)
        if request.response_schema:
            gen["responseMimeType"] = "application/json"
            key = "responseJsonSchema" if cfg.schema_mode == "json_schema" else "responseSchema"
            gen[key] = self._schema(request.response_schema)
        gen.update(cfg.generation_config or {})
        body["generationConfig"] = gen
        if request.tools and request.tool_choice != "none":
            pkey = "parametersJsonSchema" if cfg.schema_mode == "json_schema" else "parameters"
            body["tools"] = [{"functionDeclarations": [
                {"name": s.name, "description": s.description,
                 pkey: self._schema(s.input_schema or {"type": "object", "properties": {}})}
                for s in request.tools]}]
            tc = request.tool_choice
            if tc == "required":
                body["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
            elif tc not in ("auto", "none"):
                body["toolConfig"] = {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [tc]}}
            else:
                body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        if cfg.safety_settings:
            body["safetySettings"] = cfg.safety_settings
        return body

    def _path(self, stream: bool = False) -> str:
        v = self.provider.config.api_version
        return f"/{v}/models/{self.id}:" + ("streamGenerateContent" if stream else "generateContent")

    def _parse(self, data: Dict[str, Any], counter: List[int]):
        fb = data.get("promptFeedback") or {}
        if fb.get("blockReason"):
            raise ContentFiltered(f"gemini blocked the prompt: {fb['blockReason']}", provider=self.provider.name,
                                  model=self.id)
        cand = (data.get("candidates") or [{}])[0]
        raw_parts = (cand.get("content") or {}).get("parts") or []
        parts: List[Any] = []
        for p in raw_parts:
            if p.get("thought"):
                continue
            if "text" in p and p["text"]:
                parts.append(TextPart(p["text"]))
            elif "functionCall" in p:
                fc = p["functionCall"]
                cid = fc.get("id") or f"gcall_{counter[0]}_{fc.get('name', '')}"
                counter[0] += 1
                parts.append(ToolCallPart(cid, fc.get("name", ""), fc.get("args") or {}))
        return raw_parts, parts, cand.get("finishReason")

    def _usage(self, u: Dict[str, Any]):
        return self.make_usage(u.get("promptTokenCount") or 0,
                               (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0),
                               u.get("cachedContentTokenCount") or 0)

    def _finish(self, reason: Optional[str], parts) -> str:
        f = FINISH.get(reason or "STOP", "stop")
        if any(isinstance(p, ToolCallPart) for p in parts) and f == "stop":
            f = "tool_calls"
        return f

    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        with self.provider.slot():
            data = post_json(self.provider.http, self._path(), self.payload(request), provider=self.provider.name,
                             model=self.id, classify=_classify)
        raw_parts, parts, reason = self._parse(data, [0])
        msg = Message("assistant", parts, meta={"gemini_parts": raw_parts, "provider": self.provider.name})
        return ChatResponse(msg, self._finish(reason, parts), self._usage(data.get("usageMetadata") or {}),
                            data.get("modelVersion") or self.id, self.provider.name,
                            int((time.time() - t0) * 1000), raw=data)

    def stream(self, request: ChatRequest) -> Iterator:
        if not self.capabilities.streaming:
            yield from super().stream(request)
            return
        self.validate(request)
        t0 = time.time()
        all_raw: List[Dict[str, Any]] = []
        all_parts: List[Any] = []
        reason, usage_meta, counter = None, {}, [0]
        with self.provider.slot():
            with stream_post(self.provider.http, self._path(True), self.payload(request), params={"alt": "sse"},
                             provider=self.provider.name, model=self.id, classify=_classify) as resp:
                import json as _json
                for _ev, data in iter_sse(resp):
                    try:
                        chunk = _json.loads(data)
                    except Exception:
                        continue
                    raw_parts, parts, r = self._parse(chunk, counter)
                    reason = r or reason
                    usage_meta = chunk.get("usageMetadata") or usage_meta
                    all_raw.extend(raw_parts)
                    for i, p in enumerate(parts):
                        if isinstance(p, TextPart):
                            if all_parts and isinstance(all_parts[-1], TextPart):
                                all_parts[-1] = TextPart(all_parts[-1].text + p.text)
                            else:
                                all_parts.append(p)
                            yield TextDelta(p.text)
                        else:
                            all_parts.append(p)
                            yield ToolCallDelta(p.id, p.name, _json.dumps(p.arguments),
                                                sum(isinstance(x, ToolCallPart) for x in all_parts) - 1)
        merged_raw: List[Dict[str, Any]] = []
        for rp in all_raw:          # merge streamed text fragments, keep signatures
            if merged_raw and "text" in rp and "text" in merged_raw[-1] and not rp.get("thought") \
                    and not merged_raw[-1].get("thought") and "thoughtSignature" not in rp:
                merged_raw[-1] = {**merged_raw[-1], "text": merged_raw[-1]["text"] + rp["text"]}
            else:
                merged_raw.append(dict(rp))
        usage = self._usage(usage_meta)
        msg = Message("assistant", all_parts, meta={"gemini_parts": merged_raw, "provider": self.provider.name})
        yield UsageEvent(usage)
        yield Done(ChatResponse(msg, self._finish(reason, all_parts), usage, self.id, self.provider.name,
                                int((time.time() - t0) * 1000)))


class GeminiEmbeddingModel(EmbeddingModel):
    def embed(self, texts: List[str]) -> List[List[float]]:
        cfg = self.provider.config
        reqs = []
        for t in texts:
            r: Dict[str, Any] = {"model": f"models/{self.id}", "content": {"parts": [{"text": t}]}}
            if cfg.embedding_task_type:
                r["taskType"] = cfg.embedding_task_type
            if cfg.embedding_dimensions:
                r["outputDimensionality"] = cfg.embedding_dimensions
            reqs.append(r)
        with self.provider.slot():
            data = post_json(self.provider.http, f"/{cfg.api_version}/models/{self.id}:batchEmbedContents",
                             {"requests": reqs}, provider=self.provider.name, model=self.id, classify=_classify)
        return [e.get("values") or [] for e in data.get("embeddings") or []]


@register_provider
class GeminiProvider(LLMProvider):
    name = "gemini"
    config_model = GeminiConfig
    default_base_url = "https://generativelanguage.googleapis.com"
    catalog_key = "gemini"
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, vision=True,
                                                   context_window=1_000_000)
    chat_model_class = GeminiChatModel
    embedding_model_class = GeminiEmbeddingModel

    def auth_headers(self) -> Dict[str, str]:
        return {"x-goog-api-key": self.api_key} if self.api_key else {}
