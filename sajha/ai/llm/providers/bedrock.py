"""
SAJHA Intelligence Layer — AWS Bedrock (Converse / ConverseStream / InvokeModel for embeddings).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Bedrock needs SigV4 request signing, so this provider uses boto3 — an optional dependency
(``pip install boto3``); without it the provider reports a clear error and stays down.
Credentials come from the config/env fields below or boto3's default chain (profile, SSO,
instance role). The adapter translates the canonical Chat Completions format to Converse:
system/developer -> ``system``; tools -> ``toolSpec``, tool_choice auto | any | {tool: {name}};
tool calls/results -> ``toolUse`` / ``toolResult`` (``status: error`` for error results);
images (data: URLs) -> bytes; temperature, top_p, stop -> ``inferenceConfig``; ``extra_body``
-> ``additionalModelRequestFields``. Converse has no JSON output mode, so ``response_format``
is refused (structured_output and json_mode are false), as are seed, reasoning_effort and
``parallel_tool_calls: false``. ``stopReason: guardrail_intervened`` becomes
``finish_reason: content_filter`` with ``message.refusal``. Async runs in a worker thread
(boto3 is synchronous). Embeddings: Titan Text v2 (``dimensions``) and Cohere Embed
(``input_type`` from the request's purpose) through InvokeModel.
"""

from __future__ import annotations

import base64
import json
from typing import Any, ClassVar, Dict, Iterator, List, Optional

from pydantic import SecretStr

from sajha.ai.llm.errors import (AuthenticationFailed, ConfigurationError, ContentFiltered, ContextTooLong,
                                 InvalidRequest, LLMError, ProviderUnavailable, RateLimited, UnsupportedFeature)
from sajha.ai.llm.http import CONTEXT_MARKERS
from sajha.ai.llm.model import ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities
from sajha.ai.llm.provider import ProviderBase
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.adapter import StreamTranslator, assistant_text, system_text
from sajha.ai.llm.canonical import (ChatCompletion, ChatCompletionRequest, ChatMessage, Choice, CompletionUsage,
                                    FunctionCall, ToolCall, split_data_url)

STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
        "guardrail_intervened": "content_filter", "content_filtered": "content_filter",
        "model_context_window_exceeded": "length"}
_RATE = {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException",
         "throttlingException", "serviceQuotaExceededException"}
_AUTH = {"AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException",
         "InvalidSignatureException", "IncompleteSignature", "accessDeniedException"}
_DOWN = {"ServiceUnavailableException", "InternalServerException", "ModelTimeoutException", "ModelErrorException",
         "ModelNotReadyException", "internalServerException", "serviceUnavailableException",
         "modelStreamErrorException", "modelTimeoutException"}


class BedrockConfig(ProviderConfig):
    region: Optional[str] = "us-east-1"
    profile: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[SecretStr] = None
    aws_session_token: Optional[SecretStr] = None
    embedding_input_type: str = "search_document"           # Cohere embed models
    guardrail_identifier: Optional[str] = None
    guardrail_version: Optional[str] = None
    additional_model_request_fields: Dict[str, Any] = {}

    vendor_env: ClassVar[Dict[str, List[str]]] = {
        "region": ["AWS_REGION", "AWS_DEFAULT_REGION"], "profile": ["AWS_PROFILE"],
        "aws_access_key_id": ["AWS_ACCESS_KEY_ID"], "aws_secret_access_key": ["AWS_SECRET_ACCESS_KEY"],
        "aws_session_token": ["AWS_SESSION_TOKEN"], "base_url": ["AWS_ENDPOINT_URL_BEDROCK_RUNTIME"]}


def map_bedrock_error(e: Exception, provider: str, model: str = "") -> LLMError:
    if isinstance(e, LLMError):
        return e
    resp = getattr(e, "response", None) or {}
    code = ((resp.get("Error") or {}).get("Code")) or e.__class__.__name__
    msg = f"bedrock {code}: {((resp.get('Error') or {}).get('Message')) or e}"
    kw = dict(provider=provider, model=model)
    name = e.__class__.__name__
    if code in _RATE:
        return RateLimited(msg, **kw)
    if code in _AUTH or name in ("NoCredentialsError", "PartialCredentialsError", "NoRegionError"):
        return AuthenticationFailed(msg, **kw)
    if code in ("ResourceNotFoundException",):
        return UnsupportedFeature(msg, **kw)
    if code in ("ValidationException", "validationException"):
        low = msg.lower()
        if any(m in low for m in CONTEXT_MARKERS):
            return ContextTooLong(msg, **kw)
        if "guardrail" in low or "blocked" in low or "content filter" in low:
            return ContentFiltered(msg, **kw)
        if "doesn't support tool" in low or "does not support tool" in low:
            return UnsupportedFeature(msg, **kw)
        return InvalidRequest(msg, **kw)
    if code in _DOWN or name in ("EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError",
                                 "ConnectionClosedError"):
        return ProviderUnavailable(msg, **kw)
    return ProviderUnavailable(msg, **kw)


def _image_format(mime: str) -> str:
    return {"image/jpeg": "jpeg", "image/jpg": "jpeg", "image/gif": "gif", "image/webp": "webp"}.get(mime, "png")


GUARDRAIL_REFUSAL = "Blocked by the Bedrock guardrail (stopReason: {reason})."


# ── wire mapping (pure; golden-tested) ─────────────────────────────

def _tool_result_content(m: ChatMessage) -> List[Dict[str, Any]]:
    if m.sajha and m.sajha.structured:
        try:
            v = json.loads(m.text)
            if isinstance(v, dict):
                return [{"json": v}]
        except Exception:
            pass
    return [{"text": m.text}]


def to_bedrock_kwargs(request: ChatCompletionRequest, *, model: str, cfg: "BedrockConfig", max_tokens: int,
                      temperature: Optional[float]) -> Dict[str, Any]:
    msgs: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("system", "developer"):
            continue
        content: List[Dict[str, Any]] = []
        if m.role == "assistant":
            if assistant_text(m):
                content.append({"text": assistant_text(m)})
            content += [{"toolUse": {"toolUseId": c.id, "name": c.function.name, "input": c.function.args()}}
                        for c in m.tool_calls or []]
            role = "assistant"
        elif m.role == "tool":
            content.append({"toolResult": {"toolUseId": m.tool_call_id, "content": _tool_result_content(m),
                                           "status": "error" if m.is_error else "success"}})
            role = "user"
        else:
            role = "user"
            for p in m.parts:
                if p.type == "text" and p.text:
                    content.append({"text": p.text})
                elif p.type == "image_url":
                    mime, data = split_data_url(p.image_url.url)
                    content.append({"image": {"format": _image_format(mime), "source": {"bytes": base64.b64decode(data)}}})
        if not content:
            continue
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"].extend(content)
        else:
            msgs.append({"role": role, "content": content})
    kw: Dict[str, Any] = {"modelId": model, "messages": msgs}
    system = system_text(request)
    if system:
        kw["system"] = [{"text": system}]
    inf: Dict[str, Any] = {"maxTokens": max_tokens}
    if temperature is not None:
        inf["temperature"] = temperature
    if request.top_p is not None:
        inf["topP"] = request.top_p
    if request.stop_list:
        inf["stopSequences"] = request.stop_list
    kw["inferenceConfig"] = inf
    if request.wants_tools:
        mode = request.tool_choice_mode
        choice: Dict[str, Any] = {"auto": {}}
        if mode == "required":
            choice = {"any": {}}
        elif mode == "named":
            choice = {"tool": {"name": request.tool_choice_name}}
        kw["toolConfig"] = {"tools": [{"toolSpec": {
            "name": t.name, "description": ((t.function.description if t.function else "") or t.name),
            "inputSchema": {"json": t.parameters_or_default}}} for t in request.tools or []], "toolChoice": choice}
    if cfg.guardrail_identifier:
        kw["guardrailConfig"] = {"guardrailIdentifier": cfg.guardrail_identifier,
                                 "guardrailVersion": cfg.guardrail_version or "DRAFT"}
    extra = {**(cfg.additional_model_request_fields or {}), **(request.extra_body or {})}
    if extra:
        kw["additionalModelRequestFields"] = extra
    return kw


def bedrock_usage(u: Dict[str, Any]) -> Optional[CompletionUsage]:
    if not u:
        return None
    return CompletionUsage.of(u.get("inputTokens") or 0, u.get("outputTokens") or 0, u.get("cacheReadInputTokens"))


def bedrock_message(content: List[Dict[str, Any]], stop: str) -> tuple:
    text = "".join(b["text"] for b in content or [] if b.get("text"))
    calls = [ToolCall(id=b["toolUse"].get("toolUseId", ""), function=FunctionCall(
        name=b["toolUse"].get("name", ""), arguments=json.dumps(b["toolUse"].get("input") or {})))
        for b in content or [] if "toolUse" in b]
    finish = STOP.get(stop or "end_turn", "stop")
    msg = ChatMessage(role="assistant", content=text or None, tool_calls=calls or None)
    if finish == "content_filter":
        msg.refusal, msg.content = text or GUARDRAIL_REFUSAL.format(reason=stop), None   # the guardrail's message
    elif calls and finish == "stop":
        finish = "tool_calls"
    return msg, finish


def parse_bedrock(data: Dict[str, Any], model: str) -> ChatCompletion:
    msg, finish = bedrock_message(((data.get("output") or {}).get("message") or {}).get("content") or [],
                                  data.get("stopReason") or "end_turn")
    return ChatCompletion(model=model, choices=[Choice(message=msg, finish_reason=finish)],
                          usage=bedrock_usage(data.get("usage") or {}))


class BedrockStreamTranslator(StreamTranslator):
    def __init__(self, model, request):
        super().__init__(model, request)
        self.stop = ""

    def feed(self, event: str, ev: Any) -> List:
        out: List = []
        for k in ev:
            if k.endswith("Exception"):
                raise map_bedrock_error(type(k, (Exception,), {"response": {"Error": {
                    "Code": k, "Message": str(ev[k])}}})(), self.model.provider.name, self.model.id)
        if "contentBlockStart" in ev:
            cs = ev["contentBlockStart"]
            tu = (cs.get("start") or {}).get("toolUse")
            if tu:
                out += self.tool_start(cs.get("contentBlockIndex", 0), tu.get("toolUseId", ""), tu.get("name", ""))
        elif "contentBlockDelta" in ev:
            cd = ev["contentBlockDelta"]
            d = cd.get("delta") or {}
            if "text" in d:
                out += self.text(d["text"])
            elif "toolUse" in d:
                out += self.tool_args(cd.get("contentBlockIndex", 0), d["toolUse"].get("input", ""))
        elif "messageStop" in ev:
            self.stop = ev["messageStop"].get("stopReason") or "end_turn"
            self.finish = STOP.get(self.stop, "stop")
        elif "metadata" in ev:
            self.usage = bedrock_usage(ev["metadata"].get("usage") or {}) or self.usage
        return out

    def close(self) -> List:
        if self.finish == "content_filter":
            self.refusal = GUARDRAIL_REFUSAL.format(reason=self.stop)
        return super().close()


class BedrockChatModel(ChatModel):
    def request_kwargs(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        return to_bedrock_kwargs(request, model=self.id, cfg=self.provider.config,
                                 max_tokens=self.effective_max_tokens(request),
                                 temperature=self.effective_temperature(request))

    def _create(self, request: ChatCompletionRequest) -> ChatCompletion:
        client = self.provider.client()
        try:
            with self.provider.slot():
                data = client.converse(**self.request_kwargs(request))
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        comp = parse_bedrock(data, self.id)
        comp._raw = data
        return comp

    def _stream(self, request: ChatCompletionRequest) -> Iterator:
        client = self.provider.client()
        tr = BedrockStreamTranslator(self, request)
        try:
            with self.provider.slot():
                resp = client.converse_stream(**self.request_kwargs(request))
                for ev in resp.get("stream") or []:
                    yield from tr.feed("", ev)
        except LLMError:
            raise
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        yield from tr.close()


class BedrockEmbeddingModel(EmbeddingModel):
    def _embed(self, texts, purpose=None, dimensions=None):
        client = self.provider.client()
        cfg = self.provider.config
        out: List[List[float]] = []
        try:
            if self.id.startswith("cohere."):
                body = {"texts": list(texts),
                        "input_type": {"query": "search_query", "document": "search_document"}.get(
                            purpose or "") or cfg.embedding_input_type}
                data = self._invoke(client, body)
                emb = data.get("embeddings")
                return emb.get("float") if isinstance(emb, dict) else emb
            dims = dimensions or cfg.embedding_dimensions
            for t in texts:
                body: Dict[str, Any] = {"inputText": t}
                if dims:
                    body["dimensions"] = dims
                out.append(self._invoke(client, body).get("embedding") or [])
        except LLMError:
            raise
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        return out

    def _invoke(self, client, body):
        with self.provider.slot():
            resp = client.invoke_model(modelId=self.id, body=json.dumps(body), contentType="application/json",
                                       accept="application/json")
        raw = resp.get("body")
        raw = raw.read() if hasattr(raw, "read") else raw
        return json.loads(raw)


@register_provider
class BedrockProvider(ProviderBase):
    name = "bedrock"
    config_model = BedrockConfig
    requires_key = False            # boto3's credential chain
    catalog_key = "bedrock"
    feature_defaults = {"json_mode": False}
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=False, context_window=128_000)
    chat_model_class = BedrockChatModel
    embedding_model_class = BedrockEmbeddingModel

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._boto = None

    def auto_enabled(self) -> bool:
        cfg = self.config
        return bool(cfg.aws_access_key_id or cfg.profile)

    def client(self):
        """The bedrock-runtime client (an injected fake in tests)."""
        if self._transport is not None and hasattr(self._transport, "converse"):
            return self._transport
        if self._boto is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                raise ConfigurationError("bedrock needs boto3: pip install boto3", provider=self.name) from None
            cfg = self.config
            session = boto3.Session(
                profile_name=cfg.profile or None, region_name=cfg.region or None,
                aws_access_key_id=cfg.aws_access_key_id or None,
                aws_secret_access_key=cfg.aws_secret_access_key.get_secret_value()
                if cfg.aws_secret_access_key else None,
                aws_session_token=cfg.aws_session_token.get_secret_value() if cfg.aws_session_token else None)
            bc = Config(connect_timeout=cfg.connect_timeout_s, read_timeout=cfg.read_timeout_s,
                        retries={"max_attempts": 1, "mode": "standard"},
                        max_pool_connections=max(10, cfg.max_concurrency),
                        proxies={"https": cfg.proxy, "http": cfg.proxy} if cfg.proxy else None)
            verify: Any = cfg.ca_bundle if (cfg.verify_tls and cfg.ca_bundle) else cfg.verify_tls
            self._boto = session.client("bedrock-runtime", config=bc, endpoint_url=cfg.base_url or None,
                                        verify=verify)
        return self._boto

    def health(self) -> HealthStatus:
        if not self.active:
            return HealthStatus("down", "disabled" if self.config.enabled is False else "not configured")
        if self._transport is None:
            try:
                import boto3  # noqa: F401
            except ImportError:
                return HealthStatus("down", "boto3 not installed (pip install boto3)")
        return HealthStatus("ok", f"region {self.config.region}")

    def close(self) -> None:
        self._boto = None
