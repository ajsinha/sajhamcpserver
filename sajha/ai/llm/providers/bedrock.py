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
is refused (structured_output and json_mode are false), as are seed and
``parallel_tool_calls: false``. ``reasoning_effort`` goes into ``additionalModelRequestFields``
per model family (``REASONING_FAMILIES``): Anthropic Claude -> ``output_config.effort``; Amazon
Nova 2 -> ``reasoningConfig`` (``maxReasoningEffort`` low | medium | high, ``none`` disables
it). Any other family refuses it with UnsupportedFeature naming the families that take it.
``stopReason: guardrail_intervened`` becomes ``finish_reason: content_filter`` with
``message.refusal``. Embeddings: Titan Text v2 (``dimensions``) and Cohere Embed
(``input_type`` from the request's purpose) through InvokeModel.

Async: with aiobotocore installed (``pip install aiobotocore``, or aioboto3 which brings it) the
async paths (chat, stream, embeddings) call Bedrock natively, one client per event loop;
without it they run the boto3 client in a worker thread. Neither library is needed to import
this module.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import weakref
from typing import Any, AsyncIterator, ClassVar, Dict, Iterator, List, Optional

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


# ── reasoning_effort per model family ───────────────────────────

_REGION_PREFIXES = ("us", "eu", "apac", "global", "us-gov", "jp", "au", "ca", "ap")
NOVA_EFFORT = {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "high"}


def model_family(model_id: str) -> str:
    """The vendor family of a Bedrock model id, inference-profile id or ARN
    ("anthropic", "amazon.nova-2", "amazon", "meta", ...)."""
    mid = (model_id or "").rsplit("/", 1)[-1].lower()
    parts = mid.split(".")
    if len(parts) > 2 and parts[0] in _REGION_PREFIXES:
        parts = parts[1:]
    vendor = parts[0]
    if vendor == "amazon" and len(parts) > 1 and parts[1].startswith("nova-2"):
        return "amazon.nova-2"
    return vendor


def _claude_effort(effort: str) -> Dict[str, Any]:
    return {"output_config": {"effort": effort}}


def _nova2_effort(effort: str) -> Dict[str, Any]:
    if effort == "none":
        return {"reasoningConfig": {"type": "disabled"}}
    return {"reasoningConfig": {"type": "enabled", "maxReasoningEffort": NOVA_EFFORT[effort]}}


REASONING_FAMILIES = {"anthropic": _claude_effort, "amazon.nova-2": _nova2_effort}


def reasoning_fields(model_id: str, effort: str, provider: str = "bedrock") -> Dict[str, Any]:
    """``additionalModelRequestFields`` for ``reasoning_effort`` on this model, or UnsupportedFeature."""
    fn = REASONING_FAMILIES.get(model_family(model_id))
    if fn is None:
        raise UnsupportedFeature(
            f"{provider}/{model_id} does not support reasoning_effort: on Bedrock it is sent for Anthropic "
            f"Claude (output_config.effort) and Amazon Nova 2 (reasoningConfig) models only; for another "
            f"model put its own field in additional_model_request_fields or extra_body",
            provider=provider, model=model_id)
    return fn(effort)


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = {**out[k], **v} if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


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
    extra: Dict[str, Any] = {}
    if request.reasoning_effort is not None:
        extra = reasoning_fields(model, request.reasoning_effort)
    extra = _merge(_merge(extra, cfg.additional_model_request_fields or {}), request.extra_body or {})
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

    def prepare(self, req: ChatCompletionRequest, stream: bool = False):
        if req.reasoning_effort is not None:
            reasoning_fields(self.id, req.reasoning_effort, self.provider.name)   # the family's refusal first
        return super().prepare(req, stream)

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

    async def _acreate(self, request: ChatCompletionRequest) -> ChatCompletion:
        if not self.provider.async_native():
            return await super()._acreate(request)
        try:
            kw = self.request_kwargs(request)
            client = await self.provider.aclient()
            async with self.provider.aslot():
                data = await client.converse(**kw)
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        comp = parse_bedrock(data, self.id)
        comp._raw = data
        return comp

    async def _astream(self, request: ChatCompletionRequest) -> AsyncIterator:
        if not self.provider.async_native():
            async for c in super()._astream(request):
                yield c
            return
        tr = BedrockStreamTranslator(self, request)
        try:
            kw = self.request_kwargs(request)
            client = await self.provider.aclient()
            async with self.provider.aslot():
                resp = await client.converse_stream(**kw)
                stream = resp.get("stream") or []
                if hasattr(stream, "__aiter__"):
                    async for ev in stream:
                        for c in tr.feed("", ev):
                            yield c
                else:
                    for ev in stream:
                        for c in tr.feed("", ev):
                            yield c
        except LLMError:
            raise
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        for c in tr.close():
            yield c


def _embed_body(model_id: str, cfg: "BedrockConfig", texts: List[str], purpose: Optional[str],
                dimensions: Optional[int]) -> List[Dict[str, Any]]:
    """InvokeModel bodies: one for a Cohere batch, one per text for Titan."""
    if model_id.startswith("cohere."):
        return [{"texts": list(texts), "input_type": {"query": "search_query", "document": "search_document"}.get(
            purpose or "") or cfg.embedding_input_type}]
    dims = dimensions or cfg.embedding_dimensions
    return [{"inputText": t, **({"dimensions": dims} if dims else {})} for t in texts]


def _embed_vectors(model_id: str, replies: List[Dict[str, Any]]) -> List[List[float]]:
    if model_id.startswith("cohere."):
        emb = replies[0].get("embeddings")
        return emb.get("float") if isinstance(emb, dict) else emb
    return [r.get("embedding") or [] for r in replies]


class BedrockEmbeddingModel(EmbeddingModel):
    def _embed(self, texts, purpose=None, dimensions=None):
        client = self.provider.client()
        try:
            replies = [self._invoke(client, body)
                       for body in _embed_body(self.id, self.provider.config, texts, purpose, dimensions)]
        except LLMError:
            raise
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        return _embed_vectors(self.id, replies)

    def _invoke(self, client, body):
        with self.provider.slot():
            resp = client.invoke_model(modelId=self.id, body=json.dumps(body), contentType="application/json",
                                       accept="application/json")
        raw = resp.get("body")
        raw = raw.read() if hasattr(raw, "read") else raw
        return json.loads(raw)

    async def _aembed(self, texts, purpose=None, dimensions=None):
        if not self.provider.async_native():
            return await super()._aembed(texts, purpose, dimensions)
        try:
            client = await self.provider.aclient()
            replies = [await self._ainvoke(client, body)
                       for body in _embed_body(self.id, self.provider.config, texts, purpose, dimensions)]
        except LLMError:
            raise
        except Exception as e:
            raise map_bedrock_error(e, self.provider.name, self.id) from None
        return _embed_vectors(self.id, replies)

    async def _ainvoke(self, client, body):
        async with self.provider.aslot():
            resp = await client.invoke_model(modelId=self.id, body=json.dumps(body),
                                             contentType="application/json", accept="application/json")
            raw = resp.get("body")
            if hasattr(raw, "read"):
                raw = raw.read()
                if inspect.isawaitable(raw):
                    raw = await raw
        return json.loads(raw)


@register_provider
class BedrockProvider(ProviderBase):
    name = "bedrock"
    config_model = BedrockConfig
    requires_key = False            # boto3's credential chain
    catalog_key = "bedrock"
    feature_defaults = {"json_mode": False, "reasoning_effort": "tagged"}
    unknown_model_capabilities = ModelCapabilities(tools=True, structured_output=False, context_window=128_000)
    chat_model_class = BedrockChatModel
    embedding_model_class = BedrockEmbeddingModel

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._boto = None
        self._aio: Optional[bool] = None
        self._aboto: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()   # event loop -> client

    def auto_enabled(self) -> bool:
        cfg = self.config
        return bool(cfg.aws_access_key_id or cfg.profile)

    def _injected(self):
        t = self._transport
        return t if t is not None and hasattr(t, "converse") else None

    def _session_kwargs(self) -> Dict[str, Any]:
        cfg = self.config
        return dict(region_name=cfg.region or None, aws_access_key_id=cfg.aws_access_key_id or None,
                    aws_secret_access_key=cfg.aws_secret_access_key.get_secret_value()
                    if cfg.aws_secret_access_key else None,
                    aws_session_token=cfg.aws_session_token.get_secret_value() if cfg.aws_session_token else None)

    def _client_kwargs(self, config_cls) -> Dict[str, Any]:
        cfg = self.config
        bc = config_cls(connect_timeout=cfg.connect_timeout_s, read_timeout=cfg.read_timeout_s,
                        retries={"max_attempts": 1, "mode": "standard"},
                        max_pool_connections=max(10, cfg.max_concurrency),
                        proxies={"https": cfg.proxy, "http": cfg.proxy} if cfg.proxy else None)
        verify: Any = cfg.ca_bundle if (cfg.verify_tls and cfg.ca_bundle) else cfg.verify_tls
        return dict(config=bc, endpoint_url=cfg.base_url or None, verify=verify)

    def client(self):
        """The bedrock-runtime client (an injected fake in tests)."""
        if self._injected() is not None:
            return self._injected()
        if self._boto is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                raise ConfigurationError("bedrock needs boto3: pip install boto3", provider=self.name) from None
            sk = self._session_kwargs()
            session = boto3.Session(profile_name=self.config.profile or None, **sk)
            self._boto = session.client("bedrock-runtime", **self._client_kwargs(Config))
        return self._boto

    def async_native(self) -> bool:
        """True when the async paths call Bedrock natively: aiobotocore is installed (or the injected
        test client is async). Otherwise they run the boto3 client in a worker thread."""
        t = self._injected()
        if t is not None:
            return inspect.iscoroutinefunction(t.converse)
        if self._aio is None:
            try:
                import aiobotocore.session  # noqa: F401
                self._aio = True
            except ImportError:
                self._aio = False
        return self._aio

    async def aclient(self):
        """The aiobotocore bedrock-runtime client for the running event loop (one per loop)."""
        t = self._injected()
        if t is not None:
            return t
        loop = asyncio.get_running_loop()
        c = self._aboto.get(loop)
        if c is None:
            from aiobotocore.config import AioConfig
            from aiobotocore.session import AioSession
            session = AioSession(profile=self.config.profile or None)
            c = await session.create_client("bedrock-runtime", **self._session_kwargs(),
                                            **self._client_kwargs(AioConfig)).__aenter__()
            self._aboto[loop] = c
        return c

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
        self._aboto = weakref.WeakKeyDictionary()
