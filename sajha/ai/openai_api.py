"""
SAJHA MCP Server — SAJHA as an OpenAI-compatible endpoint (opt-in: ``ai.openai_api.enabled``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

``POST /v1/chat/completions`` (JSON or SSE chunks), ``GET /v1/models`` (and ``/v1/models/{id}``)
and ``POST /v1/embeddings`` in the OpenAI wire format, so an OpenAI SDK reaches SAJHA's gateway
by changing only its base URL and key. Routes: sajha/routes/openai_routes.py. Design and as-built:
docs/architecture/LLM Tools.md §13.4.

* **Who.** The caller is the AuthContext of a SAJHA API key sent as the bearer token (an owned key
  signs in as its owner), a SAJHA JWT, or, with ``ai.openai_api.cookie_auth``, the console's
  session cookie. Every model call carries the caller's RequestContext, so model policy per role
  (``ai.policy``), budgets, the response cache, fallback, the usage ledger and cost apply as for
  any gateway call; the request's own ``sajha`` field never sets the identity.
* **Policy.** Each request is also checked by the policy engine as the pseudo-tool
  ``openai_api.chat_completions`` or ``openai_api.embeddings`` (arguments ``{"model": ...}``)
  with source ``openai_api``, so a rule can deny or rate-limit the surface.
* **LLM tools as models.** With ``ai.openai_api.llm_tools`` each enabled LLM tool the caller may
  execute is the model ``sajha:<tool>``; a completion addressed to it runs the tool as the caller
  (``execute_with_tracking``: policy, its planner, limits, memory, audit) and returns its answer as
  the assistant message, with the run's details (``conversation_id``, ``stopped_by``, ...) in the
  response's ``sajha`` field. The request's ``sajha.conversation_id`` continues a conversation and
  ``sajha.arguments`` gives the tool's arguments explicitly.
* **Errors** are OpenAI-shaped: ``{"error": {"message", "type", "param", "code"}}`` with the
  matching HTTP status (:func:`error_for`).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

TOOL_PREFIX = "sajha:"
CHAT_PSEUDO_TOOL = "openai_api.chat_completions"
EMBEDDINGS_PSEUDO_TOOL = "openai_api.embeddings"
# OpenAI request fields an LLM tool model takes no notice of (they are listed in sajha.ignored)
_TOOL_IGNORED = ("temperature", "top_p", "max_completion_tokens", "max_tokens", "stop", "seed", "presence_penalty",
                 "frequency_penalty", "logit_bias", "logprobs", "top_logprobs", "user", "metadata", "store",
                 "service_tier", "reasoning_effort", "parallel_tool_calls", "modalities", "prediction")


class APIError(Exception):
    """An OpenAI-shaped error: HTTP status, type, code, message (and Retry-After)."""

    def __init__(self, status: int, message: str, *, type: str = "invalid_request_error", code: Optional[str] = None,
                 param: Optional[str] = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status, self.message, self.type, self.code, self.param = status, message, type, code, param
        self.retry_after = retry_after

    def body(self) -> Dict[str, Any]:
        return {"error": {"message": self.message, "type": self.type, "param": self.param, "code": self.code}}

    def headers(self) -> Optional[Dict[str, str]]:
        return {"Retry-After": str(int(self.retry_after))} if self.retry_after else None


def not_found(model: str) -> APIError:
    return APIError(404, f"The model '{model}' does not exist or you do not have access to it.",
                    type="not_found_error", code="model_not_found", param="model")


def error_for(e: Exception, model: str = "") -> APIError:
    """Map a gateway, policy or tool exception to an OpenAI-shaped error."""
    if isinstance(e, APIError):
        return e
    from sajha.ai.llm import errors as E
    from sajha.policy.errors import PolicyError, RateLimited as PolicyRateLimited
    if isinstance(e, PolicyRateLimited):
        return APIError(429, str(e), type="rate_limit_error", code="rate_limit_exceeded",
                        retry_after=int(getattr(e, "retry_after", 0) or 1))
    if isinstance(e, PolicyError):
        return APIError(403, str(e), type="permission_error", code=getattr(e, "kind", None) or "policy_denied")
    if isinstance(e, E.BudgetExceeded):
        return APIError(429, str(e), type="insufficient_quota", code="insufficient_quota")
    if isinstance(e, E.RateLimited):
        return APIError(429, str(e), type="rate_limit_error", code="rate_limit_exceeded",
                        retry_after=int(getattr(e, "retry_after", None) or 1))
    if isinstance(e, E.PolicyDenied):
        return APIError(403, str(e), type="permission_error", code="model_not_allowed")
    if isinstance(e, (E.InvalidRequest, E.UnsupportedFeature)):
        return APIError(400, str(e), code=e.code)
    if isinstance(e, E.ContextTooLong):
        return APIError(400, str(e), code="context_length_exceeded")
    if isinstance(e, E.NoModelAvailable):
        if "not allowed" in str(e) or "no such provider" in str(e):    # never say which
            return not_found(model)
        return APIError(503, str(e), type="server_error", code="no_model_available")
    if isinstance(e, E.LLMError):
        return APIError(502, str(e), type="server_error", code=e.code)
    if isinstance(e, PermissionError):
        return APIError(403, str(e), type="permission_error", code="permission_denied")
    if isinstance(e, ValueError):
        return APIError(400, str(e), code="invalid_request")
    logger.error(f"openai_api: {e.__class__.__name__}: {e}", exc_info=True)
    return APIError(500, f"internal error: {e.__class__.__name__}", type="server_error", code="internal_error")


# ── settings, identity ────────────────────────────────────────────────

def gateway():
    """The process-wide LLM factory (sajha.ai.llm), or None before the intelligence layer starts."""
    from sajha.ai.llm import llm_factory
    return llm_factory()


def settings():
    """``ai.openai_api.*`` from the running gateway (None when the gateway is not built)."""
    gw = gateway()
    return getattr(getattr(gw, "settings", None), "openai_api", None)


def enabled() -> bool:
    s = settings()
    return bool(s is not None and s.enabled)


def authenticate(request: Any, db: Any) -> Optional[Any]:
    """The AuthContext of the request, or None. A SAJHA API key as ``Authorization: Bearer sja_...``
    (or X-API-Key), a SAJHA JWT as the bearer, or the session cookie when cookie_auth is on."""
    from sajha.auth import AuthManager
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    auth = None
    if token.startswith("sja_"):
        auth = AuthManager.authenticate_apikey(db, token)
    elif token:
        auth = AuthManager.authenticate_jwt(db, token)
    elif request.headers.get("X-API-Key"):
        auth = AuthManager.authenticate_apikey(db, request.headers["X-API-Key"])
    else:
        s = settings()
        cookie = request.cookies.get("sajha_token", "")
        if cookie and s is not None and s.cookie_auth:
            auth = AuthManager.authenticate_jwt(db, cookie)
            if auth is not None:
                auth.auth_type = "session"
    return auth if auth is not None and auth.authenticated else None


def request_context(auth: Any):
    from sajha.ai.llm import RequestContext
    return RequestContext(user_id=auth.user_id or "", roles=list(auth.roles or []), is_admin=bool(auth.is_admin),
                          trace_id=uuid.uuid4().hex, can_use_tool=lambda name: bool(auth.has_tool_access(name)))


def bind_caller(auth: Any) -> None:
    """The caller and the policy source for this request's context (usage ledger, inner calls, policy)."""
    from sajha.observability.caller import from_auth, set_caller
    from sajha.policy.context import set_source
    set_caller(from_auth(auth))
    set_source("openai_api")


def check_policy(pseudo_tool: str, model: str) -> None:
    """The policy engine over the endpoint (deny, rate limit, quota); raises a PolicyError."""
    from sajha.policy import enforce
    enforce(SimpleNamespace(name=pseudo_tool, config={}), {"model": model})


def audit(auth: Any, endpoint: str, model: str, outcome: str, **details: Any) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().log("openai_api.request", user_id=getattr(auth, "user_id", None) or None, resource_type="model",
                          resource_id=model or "", details=json.dumps({"endpoint": endpoint, "outcome": outcome,
                                                                       "auth_type": getattr(auth, "auth_type", ""),
                                                                       **details}, default=str)[:4000])
    except Exception as e:
        logger.debug(f"openai_api audit failed: {e}")


# ── LLM tools as models ───────────────────────────────────────────────

def _registry():
    try:
        from sajha.tools.tools_registry import ToolsRegistry
        return ToolsRegistry._instance
    except Exception:
        return None


def llm_tool(name: str, auth: Any):
    """The enabled LLM tool ``name`` the caller may execute, else None (never says which it was)."""
    s = settings()
    if s is None or not s.llm_tools:
        return None
    reg = _registry()
    tool = reg.get_tool(name) if reg is not None else None
    from sajha.ai.llm_tools.config import is_llm_tool
    if tool is None or not is_llm_tool(tool) or not getattr(tool, "enabled", False):
        return None
    return tool if auth.has_tool_access(name) else None


def _tool_models(auth: Any) -> List[Dict[str, Any]]:
    s = settings()
    reg = _registry()
    if s is None or not s.llm_tools or reg is None:
        return []
    from sajha.ai.llm_tools.config import is_llm_tool
    with reg._tools_lock:
        tools = list(reg.tools.values())
    out = []
    for t in tools:
        if is_llm_tool(t) and getattr(t, "enabled", False) and auth.has_tool_access(t.name):
            spec = getattr(t, "spec", None)
            out.append({"id": f"{TOOL_PREFIX}{t.name}", "object": "model", "created": 0, "owned_by": "sajha",
                        "sajha": {"kind": "llm_tool", "tool": t.name, "mode": getattr(spec, "mode", ""),
                                  "description": (t.description or "")[:300]}})
    return out


def _alias_models(gw, ctx) -> List[Dict[str, Any]]:
    """The gateway's aliases the caller's role may use at least one candidate of."""
    import fnmatch
    policy = gw.effective_policy(ctx)
    out = []
    for alias, entries in gw.settings.aliases.items():
        def allowed(entry: str) -> bool:
            if policy is None:
                return True
            q = entry if "/" in entry else f"{entry}/*"
            return any(p == "*" or fnmatch.fnmatchcase(q, p) or (q.endswith("/*") and p.startswith(q[:-1]))
                       for p in policy.allowed)
        if any(allowed(e) for e in entries):
            out.append({"id": alias, "object": "model", "created": 0, "owned_by": "sajha",
                        "sajha": {"kind": "alias", "candidates": list(entries)}})
    return out


def list_models(auth: Any) -> Dict[str, Any]:
    gw = gateway()
    ctx = request_context(auth)
    data = _alias_models(gw, ctx) + [m.to_dict() for m in gw.models(ctx)] + _tool_models(auth)
    return {"object": "list", "data": data}


def get_model(model_id: str, auth: Any) -> Dict[str, Any]:
    for m in list_models(auth)["data"]:
        if m["id"] == model_id:
            return m
    raise not_found(model_id)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def tool_arguments(tool: Any, body: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """The tool's arguments from a chat request: ``sajha.arguments`` if given, else the last user
    message (as the question; or a JSON object of arguments; or the one text input)."""
    spec = tool.spec
    if isinstance(extra.get("arguments"), dict):
        args = dict(extra["arguments"])
    else:
        msgs = [m for m in body.get("messages") or [] if isinstance(m, dict)]
        users = [m for m in msgs if m.get("role") == "user"]
        if not users:
            raise APIError(400, "messages must contain a user message", param="messages")
        text = _text_of(users[-1].get("content")).strip()
        props = (tool.input_schema or {}).get("properties") or {}
        args = None
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict) and parsed and set(parsed) <= set(props):
                args = parsed
        if args is None:
            if "question" in props:
                args = {"question": text}
            else:
                required = list((tool.input_schema or {}).get("required") or [])
                strings = [k for k, v in props.items() if isinstance(v, dict) and v.get("type") == "string"]
                target = required[0] if len(required) == 1 else (strings[0] if len(strings) == 1 else None)
                if target is None:
                    raise APIError(400, f"{TOOL_PREFIX}{tool.name} takes the arguments {sorted(props)}: send them as a "
                                        f"JSON object in the user message or in sajha.arguments", param="messages")
                args = {target: text}
        if spec.memory_mode == "client" and "messages" in props:
            history = [{"role": m.get("role"), "content": _text_of(m.get("content"))}
                       for m in msgs[:-1] if m.get("role") in ("user", "assistant")]
            if history:
                args["messages"] = history
    cid = extra.get("conversation_id")
    if cid is not None:
        if not isinstance(cid, str):
            raise APIError(400, "sajha.conversation_id must be a string", param="sajha.conversation_id")
        if spec.memory_mode != "conversation":
            raise APIError(400, f"{TOOL_PREFIX}{tool.name} keeps no conversation (llm.memory.mode "
                                f"{spec.memory_mode})", param="sajha.conversation_id")
        args["conversation_id"] = cid
    return args


_ERROR_STATUS = {"busy": (503, "server_error"), "memory_pressure": (503, "server_error"),
                 "budget": (429, "insufficient_quota"), "cancelled": (499, "server_error"),
                 "invalid_output": (502, "server_error"), "failed": (502, "server_error"),
                 "error": (500, "server_error")}


def run_tool(tool: Any, args: Dict[str, Any], auth: Any, model_id: str, ignored: List[str]):
    """Run the LLM tool as the caller (in a worker thread with the caller bound); a ChatCompletion."""
    from sajha.ai.llm.canonical import ChatCompletion, ChatMessage, Choice, CompletionUsage, ResponseSajha
    from sajha.ai.llm_tools.tool import LAST_RUN
    LAST_RUN.set(None)
    t0 = time.time()
    result = tool.execute_with_tracking(args)
    info = LAST_RUN.get()
    res = result if isinstance(result, dict) else {"answer": str(result)}
    stopped = res.get("stopped_by") or (info.stopped_by if info is not None else "answer")
    if getattr(result, "is_error", False):
        status, etype = _ERROR_STATUS.get(stopped, (500, "server_error"))
        if res.get("code") == "conversation_not_found":
            status, etype = 404, "not_found_error"
        raise APIError(status, str(res.get("error") or stopped), type=etype, code=res.get("code") or stopped,
                       retry_after=getattr(result, "retry_after", None))
    text = ""
    for k in ("answer", "text", "label"):
        if isinstance(res.get(k), str) and res.get(k):
            text = res[k]
            break
    if not text:
        text = json.dumps({k: v for k, v in res.items() if k not in ("stopped_by", "conversation_id")},
                          default=str, ensure_ascii=False)
    u = info.usage if info is not None else None
    usage = CompletionUsage.of(getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0))
    sj = ResponseSajha(provider="sajha", qualified_model=model_id,
                       cost_usd=round(float(getattr(u, "cost_usd", 0.0) or 0.0), 6),
                       latency_ms=int((time.time() - t0) * 1000), ignored=ignored)
    extra = info.to_sajha() if info is not None else {"stopped_by": stopped}
    for k in ("conversation_id",):
        if res.get(k):
            extra[k] = res[k]
    if isinstance(extra.get("citations"), list):          # ResponseSajha.citations is a list of objects
        extra["citations"] = [c if isinstance(c, dict) else {"text": str(c)} for c in extra["citations"]]
    for k, v in extra.items():
        setattr(sj, k, v)
    finish = "length" if stopped == "token_limit" else "stop"
    return ChatCompletion(model=model_id, choices=[Choice(index=0, message=ChatMessage.assistant(text),
                                                          finish_reason=finish)], usage=usage, sajha=sj)


# ── chat completions ────────────────────────────────────────────────

def split_body(body: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(the OpenAI request, the caller's ``sajha`` field). The ``sajha`` field never carries identity."""
    if not isinstance(body, dict):
        raise APIError(400, "the request body must be a JSON object")
    body = dict(body)
    extra = body.pop("sajha", None)
    if extra is not None and not isinstance(extra, dict):
        raise APIError(400, "sajha must be an object", param="sajha")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise APIError(400, "you must provide a model parameter", param="model", code="missing_model")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise APIError(400, "messages must be a non-empty array", param="messages")
    return body, dict(extra or {})


def prepare_chat(body: Dict[str, Any], auth: Any):
    """A ChatCompletionRequest carrying the caller's context (validated); the SAJHA-only field is dropped."""
    from sajha.ai.llm.canonical import ChatCompletionRequest, SajhaRequest
    try:
        req = ChatCompletionRequest.model_validate(body)
    except Exception as e:
        raise APIError(400, f"invalid request: {str(e)[:500]}")
    ctx = request_context(auth)
    req.sajha = SajhaRequest(context=ctx, trace_id=ctx.trace_id)
    return req


def chat_create(req) -> Any:
    return gateway().model(req.model or "default").chat_completions_create(req)


def chat_stream(req) -> Iterator[Any]:
    return gateway().model(req.model or "default").chat_completions_stream(req)


def tool_request(body: Dict[str, Any], extra: Dict[str, Any], auth: Any):
    """(tool, arguments, model id, ignored fields) for a completion addressed to ``sajha:<tool>``."""
    model_id = body["model"]
    tool = llm_tool(model_id[len(TOOL_PREFIX):], auth)
    if tool is None:
        raise not_found(model_id)
    if body.get("tools") or body.get("functions"):
        raise APIError(400, f"{model_id} is a SAJHA LLM tool: it uses its own tools, not the request's",
                       param="tools")
    if (body.get("n") or 1) != 1:
        raise APIError(400, f"{model_id} returns one choice (n must be 1)", param="n")
    if body.get("response_format") not in (None, {"type": "text"}):
        raise APIError(400, f"{model_id} answers in its own output format; leave response_format out",
                       param="response_format")
    ignored = [k for k in _TOOL_IGNORED if body.get(k) is not None]
    return tool, tool_arguments(tool, body, extra), model_id, ignored


# ── embeddings ────────────────────────────────────────────────────────

def embeddings(body: Any, auth: Any) -> Dict[str, Any]:
    from sajha.ai.llm.canonical import EmbeddingsRequest, SajhaRequest, encode_base64_floats
    if not isinstance(body, dict):
        raise APIError(400, "the request body must be a JSON object")
    body = dict(body)
    body.pop("sajha", None)
    if not isinstance(body.get("model"), str) or not body.get("model"):
        raise APIError(400, "you must provide a model parameter", param="model")
    if body.get("input") in (None, "", []):
        raise APIError(400, "input must be a string or an array of strings", param="input")
    fmt = body.get("encoding_format")
    if fmt not in (None, "float", "base64"):
        raise APIError(400, "encoding_format must be float or base64", param="encoding_format")
    try:
        req = EmbeddingsRequest.model_validate(body)
    except Exception as e:
        raise APIError(400, f"invalid request: {str(e)[:500]}")
    ctx = request_context(auth)
    req.sajha = SajhaRequest(context=ctx, trace_id=ctx.trace_id)
    gw = gateway()
    gw.check_budget(ctx)
    resp = gw.model(req.model or "embedding", kind="embedding").embeddings_create(req)
    out = resp.to_dict()
    if fmt == "base64":
        for d in out.get("data") or []:
            if isinstance(d.get("embedding"), list):
                d["embedding"] = encode_base64_floats(d["embedding"])
    elif fmt in (None, "float"):
        for d, src in zip(out.get("data") or [], resp.data):
            if isinstance(d.get("embedding"), str):
                d["embedding"] = src.vector
    return out
