"""
SAJHA Intelligence Layer — AWS Bedrock (Converse / ConverseStream / InvokeModel for embeddings).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Bedrock needs SigV4 request signing, so this provider uses boto3 — an optional dependency
(``pip install boto3``); without it the provider reports a clear error and stays down.
Credentials come from the config/env fields below or boto3's default chain (profile, SSO,
instance role). Tools map to toolSpec / toolUse / toolResult; Converse has no JSON-schema
output mode, so structured_output is false for Bedrock models. Embeddings: Titan Text v2
and Cohere Embed through InvokeModel.
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar, Dict, Iterator, List, Optional

from pydantic import SecretStr

from sajha.ai.llm.errors import (AuthenticationFailed, ConfigurationError, ContentFiltered, ContextTooLong,
                                 InvalidRequest, LLMError, ProviderUnavailable, RateLimited, UnsupportedFeature)
from sajha.ai.llm.http import CONTEXT_MARKERS, safe_json_loads
from sajha.ai.llm.model import ChatModel, EmbeddingModel, HealthStatus, ModelCapabilities
from sajha.ai.llm.provider import LLMProvider
from sajha.ai.llm.registry import register_provider
from sajha.ai.llm.settings import ProviderConfig
from sajha.ai.llm.types import (ChatRequest, ChatResponse, Done, ImagePart, Message, TextDelta, TextPart,
                                ToolCallDelta, ToolCallPart, UsageEvent)

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


class BedrockChatModel(ChatModel):
    def request_kwargs(self, request: ChatRequest) -> Dict[str, Any]:
        cfg = self.provider.config
        msgs: List[Dict[str, Any]] = []
        system = [request.system] if request.system else []
        for m in request.messages:
            if m.role == "system":
                system.append(m.text)
                continue
            role = "assistant" if m.role == "assistant" else "user"
            content: List[Dict[str, Any]] = []
            for p in m.parts:
                if isinstance(p, TextPart) and p.text:
                    content.append({"text": p.text})
                elif isinstance(p, ImagePart):
                    content.append({"image": {"format": _image_format(p.mime_type), "source": {"bytes": p.data}}})
                elif isinstance(p, ToolCallPart):
                    content.append({"toolUse": {"toolUseId": p.id, "name": p.name, "input": p.arguments}})
            for r in m.tool_results:
                body = [{"json": r.content}] if isinstance(r.content, dict) else [{"text": r.content_text()}]
                content.append({"toolResult": {"toolUseId": r.call_id, "content": body,
                                               "status": "error" if r.is_error else "success"}})
            if not content:
                continue
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"].extend(content)
            else:
                msgs.append({"role": role, "content": content})
        kw: Dict[str, Any] = {"modelId": self.id, "messages": msgs}
        if system:
            kw["system"] = [{"text": "\n\n".join(system)}]
        inf: Dict[str, Any] = {"maxTokens": self.effective_max_tokens(request)}
        t = self.effective_temperature(request)
        if t is not None:
            inf["temperature"] = t
        if request.stop:
            inf["stopSequences"] = list(request.stop)
        kw["inferenceConfig"] = inf
        if request.tools and request.tool_choice != "none":
            tc = request.tool_choice
            forced = self.capabilities.forced_tool_choice
            choice = {"auto": {}}
            if tc == "required" and forced:
                choice = {"any": {}}
            elif tc not in ("auto", "required", "none") and forced:
                choice = {"tool": {"name": tc}}
            kw["toolConfig"] = {"tools": [{"toolSpec": {"name": s.name, "description": s.description or s.name,
                                                        "inputSchema": {"json": s.input_schema or {"type": "object"}}}}
                                          for s in request.tools], "toolChoice": choice}
        if cfg.guardrail_identifier:
            kw["guardrailConfig"] = {"guardrailIdentifier": cfg.guardrail_identifier,
                                     "guardrailVersion": cfg.guardrail_version or "DRAFT"}
        if cfg.additional_model_request_fields:
            kw["additionalModelRequestFields"] = cfg.additional_model_request_fields
        return kw

    def _message(self, content: List[Dict[str, Any]]) -> Message:
        parts: List[Any] = []
        for b in content or []:
            if b.get("text"):
                parts.append(TextPart(b["text"]))
            elif "toolUse" in b:
                tu = b["toolUse"]
                parts.append(ToolCallPart(tu.get("toolUseId", ""), tu.get("name", ""), tu.get("input") or {}))
        return Message("assistant", parts)

    def _usage(self, u: Dict[str, Any]):
        return self.make_usage(u.get("inputTokens") or 0, u.get("outputTokens") or 0,
                               u.get("cacheReadInputTokens") or 0)

    def generate(self, request: ChatRequest) -> ChatResponse:
        self.validate(request)
        t0 = time.time()
        client = self.provider.client()
        try:
            with self.provider.slot():
                data = client.converse(**self.request_kwargs(request))
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        msg = self._message(((data.get("output") or {}).get("message") or {}).get("content") or [])
        finish = STOP.get(data.get("stopReason") or "end_turn", "stop")
        return ChatResponse(msg, finish, self._usage(data.get("usage") or {}), self.id, self.provider.name,
                            int((time.time() - t0) * 1000), raw=data)

    def stream(self, request: ChatRequest) -> Iterator:
        if not self.capabilities.streaming:
            yield from super().stream(request)
            return
        self.validate(request)
        t0 = time.time()
        client = self.provider.client()
        blocks: Dict[int, Dict[str, Any]] = {}
        finish, usage_raw = "stop", {}
        try:
            with self.provider.slot():
                resp = client.converse_stream(**self.request_kwargs(request))
                for ev in resp.get("stream") or []:
                    for k in ev:
                        if k.endswith("Exception"):
                            raise map_bedrock_error(type(k, (Exception,), {"response": {"Error": {
                                "Code": k, "Message": str(ev[k])}}})(), self.provider.name, self.id)
                    if "contentBlockStart" in ev:
                        cs = ev["contentBlockStart"]
                        idx = cs.get("contentBlockIndex", 0)
                        tu = (cs.get("start") or {}).get("toolUse")
                        if tu:
                            blocks[idx] = {"toolUse": {"toolUseId": tu.get("toolUseId", ""),
                                                       "name": tu.get("name", ""), "_json": ""}}
                            yield ToolCallDelta(tu.get("toolUseId", ""), tu.get("name", ""), "", idx)
                    elif "contentBlockDelta" in ev:
                        cd = ev["contentBlockDelta"]
                        idx = cd.get("contentBlockIndex", 0)
                        d = cd.get("delta") or {}
                        if "text" in d:
                            b = blocks.setdefault(idx, {"text": ""})
                            b["text"] = b.get("text", "") + d["text"]
                            yield TextDelta(d["text"])
                        elif "toolUse" in d:
                            frag = d["toolUse"].get("input", "")
                            b = blocks.setdefault(idx, {"toolUse": {"toolUseId": "", "name": "", "_json": ""}})
                            b["toolUse"]["_json"] += frag
                            yield ToolCallDelta(b["toolUse"]["toolUseId"], "", frag, idx)
                    elif "messageStop" in ev:
                        finish = STOP.get(ev["messageStop"].get("stopReason") or "end_turn", "stop")
                    elif "metadata" in ev:
                        usage_raw = ev["metadata"].get("usage") or usage_raw
        except LLMError:
            raise
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        content = []
        for idx in sorted(blocks):
            b = blocks[idx]
            if "toolUse" in b:
                b["toolUse"]["input"] = safe_json_loads(b["toolUse"].pop("_json", ""))
            content.append(b)
        usage = self._usage(usage_raw)
        yield UsageEvent(usage)
        yield Done(ChatResponse(self._message(content), finish, usage, self.id, self.provider.name,
                                int((time.time() - t0) * 1000)))


class BedrockEmbeddingModel(EmbeddingModel):
    def embed(self, texts: List[str]) -> List[List[float]]:
        client = self.provider.client()
        cfg = self.provider.config
        out: List[List[float]] = []
        try:
            if self.id.startswith("cohere."):
                body = {"texts": list(texts), "input_type": cfg.embedding_input_type}
                data = self._invoke(client, body)
                emb = data.get("embeddings")
                return emb.get("float") if isinstance(emb, dict) else emb
            for t in texts:
                body: Dict[str, Any] = {"inputText": t}
                if cfg.embedding_dimensions:
                    body["dimensions"] = cfg.embedding_dimensions
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
class BedrockProvider(LLMProvider):
    name = "bedrock"
    config_model = BedrockConfig
    requires_key = False            # boto3's credential chain
    catalog_key = "bedrock"
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
