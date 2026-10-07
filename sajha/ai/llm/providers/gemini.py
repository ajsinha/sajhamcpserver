"""
SAJHA Intelligence Layer — Google Gemini (generateContent API, plain httpx): AI Studio or Vertex AI.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Translates the canonical Chat Completions format to generateContent and back:

  system / developer messages   ``systemInstruction``
  tools                         ``functionDeclarations`` (``parametersJsonSchema``, or the OpenAPI
                                subset with ``schema_mode: openapi``); tool_choice auto -> AUTO,
                                required -> ANY, named -> ANY + allowedFunctionNames
  tool calls / results          ``functionCall`` / ``functionResponse`` (the tool's name looked up
                                from the call; an error result as ``{"error": ...}``)
  images                        data: URLs -> ``inlineData``
  response_format               ``responseMimeType: application/json`` + ``responseJsonSchema``
                                (``responseSchema`` in openapi mode); json_object without a schema
  temperature, top_p, stop,     ``temperature``, ``topP``, ``stopSequences``, ``seed``,
  seed, n, max tokens           ``candidateCount``, ``maxOutputTokens``
  reasoning_effort              ``thinkingConfig.thinkingLevel``
  finishReason                  STOP/OTHER -> stop, MAX_TOKENS -> length, safety finishes (SAFETY,
                                PROHIBITED_CONTENT, BLOCKLIST, SPII, RECITATION, IMAGE_SAFETY) ->
                                content_filter with ``message.refusal``; MALFORMED_FUNCTION_CALL
                                -> ModelFailed (the gateway tries the next candidate)
  promptFeedback.blockReason    ContentFiltered (not retried, never cached)
  usage                         completion includes thought tokens, reported as reasoning_tokens

Model content parts (thought signatures included) ride on the assistant message as private
provider state and are echoed verbatim on the next turn. Streaming: ``:streamGenerateContent?alt=sse``.
Embeddings: ``:batchEmbedContents`` with ``taskType`` from the request's purpose (query ->
RETRIEVAL_QUERY, document -> RETRIEVAL_DOCUMENT) and ``outputDimensionality``.

``platform: vertex`` serves the same models from Vertex AI: ``/v1/projects/{p}/locations/{l}/
publishers/google/models/{model}:generateContent`` with a Google access token from a
service-account file or workload identity (cloud_auth.GoogleTokenSource); embeddings use
``:predict``.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Dict, List, Literal, Optional

import httpx
from pydantic import Field

from sajha.ai.llm.adapter import HTTPChatModel, StreamTranslator, WireCall, assistant_text, system_text, tool_names
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionRequest, ChatMessage, Choice, CompletionUsage,
                                    FunctionCall, MessageSajha, ToolCall, split_data_url)
from sajha.ai.llm.errors import AuthenticationFailed, ContentFiltered, ModelFailed
from sajha.ai.llm.http import post_json
from sajha.ai.llm.model import EmbeddingModel, ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig

SAFETY = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY")
FINISH = {"STOP": "stop", "MAX_TOKENS": "length", "OTHER": "stop", "FINISH_REASON_UNSPECIFIED": "stop",
          **{k: "content_filter" for k in SAFETY}}
FAILED = ("MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS")
_OPENAPI_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable",
                 "minimum", "maximum", "minItems", "maxItems", "anyOf", "propertyOrdering"}
TASK_TYPE = {"query": "RETRIEVAL_QUERY", "document": "RETRIEVAL_DOCUMENT"}


class GeminiConfig(ProviderConfig):
    api_version: str = "v1beta"
    schema_mode: Literal["json_schema", "openapi"] = "json_schema"
    safety_settings: List[Dict[str, Any]] = Field(default_factory=list)
    generation_config: Dict[str, Any] = Field(default_factory=dict)   # merged into generationConfig
    embedding_task_type: Optional[str] = "RETRIEVAL_DOCUMENT"         # when a request names no purpose
    # Vertex AI (platform: vertex): project, location and Google credentials
    platform: Literal["ai_studio", "vertex"] = "ai_studio"
    vertex_project: Optional[str] = None
    vertex_location: str = "global"
    vertex_api_version: str = "v1"
    credentials_file: Optional[str] = None      # a service-account JSON; empty = workload identity

    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                                                  "base_url": ["GEMINI_BASE_URL"],
                                                  "vertex_project": ["GOOGLE_CLOUD_PROJECT"],
                                                  "vertex_location": ["GOOGLE_CLOUD_LOCATION"],
                                                  "credentials_file": ["GOOGLE_APPLICATION_CREDENTIALS"]}


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
        return AuthenticationFailed("gemini HTTP 400: API key not valid", provider="gemini", status=400)
    return None


# ── wire mapping (pure; golden-tested) ─────────────────────────────

def _tool_response(m: ChatMessage) -> Dict[str, Any]:
    if m.is_error:
        return {"error": m.text}
    try:
        v = json.loads(m.text)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    return {"result": m.text}


def to_gemini_body(request: ChatCompletionRequest, *, provider: str, cfg: GeminiConfig, max_tokens: int,
                   temperature: Optional[float]) -> Dict[str, Any]:
    def schema(s: dict) -> dict:
        return s if cfg.schema_mode == "json_schema" else openapi_schema(s)

    names = tool_names(request)
    contents: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("system", "developer"):
            continue
        role = "model" if m.role == "assistant" else "user"
        state = m.state_for(provider) if m.role == "assistant" else None
        if state and state.get("gemini_parts"):
            parts = list(state["gemini_parts"])
        elif m.role == "assistant":
            parts = [{"text": assistant_text(m)}] if assistant_text(m) else []
            for c in m.tool_calls or []:
                fc: Dict[str, Any] = {"name": c.function.name, "args": c.function.args()}
                if not c.id.startswith("gcall_"):
                    fc["id"] = c.id
                parts.append({"functionCall": fc})
        elif m.role == "tool":
            fr: Dict[str, Any] = {"name": (m.sajha.tool_name if m.sajha and m.sajha.tool_name else "")
                                  or names.get(m.tool_call_id or "", ""), "response": _tool_response(m)}
            if not (m.tool_call_id or "").startswith("gcall_"):
                fr["id"] = m.tool_call_id
            parts = [{"functionResponse": fr}]
        else:
            parts = []
            for p in m.parts:
                if p.type == "text" and p.text:
                    parts.append({"text": p.text})
                elif p.type == "image_url":
                    mime, data = split_data_url(p.image_url.url)
                    parts.append({"inlineData": {"mimeType": mime, "data": data}})
        if not parts:
            continue
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})
    body: Dict[str, Any] = {"contents": contents}
    system = system_text(request)
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    gen: Dict[str, Any] = {"maxOutputTokens": max_tokens}
    if temperature is not None:
        gen["temperature"] = temperature
    if request.top_p is not None:
        gen["topP"] = request.top_p
    if request.stop_list:
        gen["stopSequences"] = request.stop_list
    if request.seed is not None:
        gen["seed"] = request.seed
    if request.n and request.n > 1:
        gen["candidateCount"] = request.n
    if request.reasoning_effort is not None:
        gen["thinkingConfig"] = {"thinkingLevel": request.reasoning_effort}
    kind = request.output_kind
    if kind:
        gen["responseMimeType"] = "application/json"
        if kind == "json_schema":
            key = "responseJsonSchema" if cfg.schema_mode == "json_schema" else "responseSchema"
            gen[key] = schema(request.output_schema)
    gen.update(cfg.generation_config or {})
    body["generationConfig"] = gen
    if request.wants_tools:
        pkey = "parametersJsonSchema" if cfg.schema_mode == "json_schema" else "parameters"
        body["tools"] = [{"functionDeclarations": [
            {"name": t.name, "description": (t.function.description or "") if t.function else "",
             pkey: schema(t.parameters_or_default)} for t in request.tools or []]}]
        mode = request.tool_choice_mode
        if mode == "required":
            fcc: Dict[str, Any] = {"mode": "ANY"}
        elif mode == "named":
            fcc = {"mode": "ANY", "allowedFunctionNames": [request.tool_choice_name]}
        else:
            fcc = {"mode": "AUTO"}
        body["toolConfig"] = {"functionCallingConfig": fcc}
    if cfg.safety_settings:
        body["safetySettings"] = cfg.safety_settings
    body.update(request.extra_body or {})
    return body


def gemini_usage(u: Dict[str, Any]) -> Optional[CompletionUsage]:
    if not u:
        return None
    thoughts = u.get("thoughtsTokenCount")
    return CompletionUsage.of(u.get("promptTokenCount") or 0, (u.get("candidatesTokenCount") or 0) + (thoughts or 0),
                              u.get("cachedContentTokenCount"), thoughts)


def check_prompt_feedback(data: Dict[str, Any], provider: str, model: str) -> None:
    fb = data.get("promptFeedback") or {}
    if fb.get("blockReason"):
        raise ContentFiltered(f"gemini blocked the prompt: {fb['blockReason']}", provider=provider, model=model)


def candidate_parts(cand: Dict[str, Any], counter: List[int]) -> tuple:
    raw_parts = (cand.get("content") or {}).get("parts") or []
    text, calls = [], []
    for p in raw_parts:
        if p.get("thought"):
            continue
        if p.get("text"):
            text.append(p["text"])
        elif "functionCall" in p:
            fc = p["functionCall"]
            cid = fc.get("id") or f"gcall_{counter[0]}_{fc.get('name', '')}"
            counter[0] += 1
            calls.append(ToolCall(id=cid, function=FunctionCall(name=fc.get("name", ""),
                                                                arguments=json.dumps(fc.get("args") or {}))))
    return raw_parts, "".join(text), calls


def gemini_finish(reason: Optional[str], has_calls: bool, provider: str, model: str) -> str:
    if reason in FAILED:
        raise ModelFailed(f"gemini finished with {reason}", provider=provider, model=model)
    f = FINISH.get(reason or "STOP", "stop")
    return "tool_calls" if has_calls and f == "stop" else f


def refusal_text(reason: str) -> str:
    return f"Blocked by the Gemini safety filter (finishReason: {reason})."


def parse_gemini(data: Dict[str, Any], model: str, provider: str) -> ChatCompletion:
    check_prompt_feedback(data, provider, model)
    choices = []
    counter = [0]
    for i, cand in enumerate(data.get("candidates") or [{}]):
        raw, text, calls = candidate_parts(cand, counter)
        reason = cand.get("finishReason")
        finish = gemini_finish(reason, bool(calls), provider, model)
        msg = ChatMessage(role="assistant", content=text or None, tool_calls=calls or None,
                          sajha=MessageSajha(provider=provider, provider_state={"gemini_parts": raw}))
        if finish == "content_filter":
            msg.refusal, msg.content = refusal_text(reason), None
        choices.append(Choice(index=cand.get("index", i), message=msg, finish_reason=finish))
    out = ChatCompletion(model=data.get("modelVersion") or model, choices=choices,
                         usage=gemini_usage(data.get("usageMetadata") or {}))
    if data.get("responseId"):
        out.id = data["responseId"]
    return out


class GeminiStreamTranslator(StreamTranslator):
    def __init__(self, model, request):
        super().__init__(model, request)
        self.raw: List[Dict[str, Any]] = []
        self.counter = [0]
        self.reason: Optional[str] = None

    def feed(self, event: str, data: Any) -> List:
        try:
            chunk = json.loads(data) if isinstance(data, str) else data
        except Exception:
            return []
        check_prompt_feedback(chunk, self.model.provider.name, self.model.id)
        if chunk.get("usageMetadata"):
            self.usage = gemini_usage(chunk["usageMetadata"])
        self.model_name = chunk.get("modelVersion") or self.model_name
        out: List = []
        cands = chunk.get("candidates") or []
        if not cands:
            return out
        cand = cands[0]
        raw, text, calls = candidate_parts(cand, self.counter)
        self.raw.extend(raw)
        out += self.text(text)
        for c in calls:
            out += self.tool_start(c.id, c.id, c.function.name, c.function.arguments)
        if cand.get("finishReason"):
            self.reason = cand["finishReason"]
        return out

    def close(self) -> List:
        finish = gemini_finish(self.reason, self.has_calls, self.model.provider.name, self.model.id)
        self.finish = finish
        if finish == "content_filter":
            self.refusal = refusal_text(self.reason or "SAFETY")
        merged: List[Dict[str, Any]] = []
        for rp in self.raw:          # merge streamed text fragments, keep signatures
            if merged and "text" in rp and "text" in merged[-1] and not rp.get("thought") \
                    and not merged[-1].get("thought") and "thoughtSignature" not in rp:
                merged[-1] = {**merged[-1], "text": merged[-1]["text"] + rp["text"]}
            else:
                merged.append(dict(rp))
        self.state = {"gemini_parts": merged}
        return super().close()


class GeminiChatModel(HTTPChatModel):
    def _path(self, stream: bool = False) -> str:
        verb = "streamGenerateContent" if stream else "generateContent"
        return f"{self.provider.model_prefix(self.id)}:{verb}"

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        body = to_gemini_body(request, provider=self.provider.name, cfg=self.provider.config,
                              max_tokens=self.effective_max_tokens(request),
                              temperature=self.effective_temperature(request))
        return WireCall(self._path(stream), body, {"alt": "sse"} if stream else None)

    def classify(self, resp):
        return _classify(resp)

    def parse(self, data: Dict[str, Any], request: ChatCompletionRequest) -> ChatCompletion:
        return parse_gemini(data, self.id, self.provider.name)

    def translator(self, request: ChatCompletionRequest) -> StreamTranslator:
        return GeminiStreamTranslator(self, request)


class GeminiEmbeddingModel(EmbeddingModel):
    def _embed(self, texts, purpose=None, dimensions=None):
        cfg = self.provider.config
        task = TASK_TYPE.get(purpose or "") or cfg.embedding_task_type
        dims = dimensions or cfg.embedding_dimensions
        headers = self.provider.request_headers() or None
        prefix = self.provider.model_prefix(self.id)
        if self.provider.vertex:
            instances = [{"content": t, **({"task_type": task} if task else {})} for t in texts]
            body: Dict[str, Any] = {"instances": instances}
            if dims:
                body["parameters"] = {"outputDimensionality": dims}
            with self.provider.slot():
                data = post_json(self.provider.http, f"{prefix}:predict", body, headers=headers,
                                 provider=self.provider.name, model=self.id, classify=_classify)
            return [((p.get("embeddings") or {}).get("values") or []) for p in data.get("predictions") or []]
        reqs = []
        for t in texts:
            r: Dict[str, Any] = {"model": f"models/{self.id}", "content": {"parts": [{"text": t}]}}
            if task:
                r["taskType"] = task
            if dims:
                r["outputDimensionality"] = dims
            reqs.append(r)
        with self.provider.slot():
            data = post_json(self.provider.http, f"{prefix}:batchEmbedContents", {"requests": reqs},
                             headers=headers, provider=self.provider.name, model=self.id, classify=_classify)
        return [e.get("values") or [] for e in data.get("embeddings") or []]


@register_provider
class GeminiProvider(LLMProvider):
    name = "gemini"
    config_model = GeminiConfig
    default_base_url = "https://generativelanguage.googleapis.com"
    catalog_key = "gemini"
    feature_defaults = {"seed": True, "native_n": True, "reasoning_effort": "tagged", "json_mode": True,
                        "variable_dimensions": True}
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=True, vision=True,
                                                   context_window=1_000_000)
    chat_model_class = GeminiChatModel
    embedding_model_class = GeminiEmbeddingModel

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._tokens = None

    @property
    def vertex(self) -> bool:
        return self.config.platform == "vertex"

    @property
    def base_url(self) -> str:
        if self.vertex and not self.config.base_url:
            from sajha.ai.llm.providers.anthropic import vertex_base_url
            return vertex_base_url(self.config.vertex_location)
        return super().base_url

    def model_prefix(self, model_id: str) -> str:
        c = self.config
        if self.vertex:
            if not c.vertex_project:
                from sajha.ai.llm.errors import ConfigurationError
                raise ConfigurationError("gemini on vertex needs vertex_project", provider=self.name)
            return (f"/{c.vertex_api_version}/projects/{c.vertex_project}/locations/{c.vertex_location}"
                    f"/publishers/google/models/{model_id}")
        return f"/{c.api_version}/models/{model_id}"

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
        return {"x-goog-api-key": self.api_key} if self.api_key else {}

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
