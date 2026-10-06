"""
MCP 2026-07-28 ("modern", stateless) request handling.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

SAJHA is a *dual-era* server (spec: basic/versioning, "Backward Compatibility
with Initialization-Based Versions"):

* an ``initialize`` request, or any request without the modern per-request
  ``_meta`` envelope, is served by the legacy (2025-11-25 and earlier) path in
  ``mcp_handler`` / ``mcp_routes`` — sessions, GET stream, DELETE, unchanged;
* a request whose ``params._meta`` carries ``io.modelcontextprotocol/protocolVersion``
  (or whose ``MCP-Protocol-Version`` header names a non-handshake version) is
  served here, statelessly: no ``initialize``, no ``Mcp-Session-Id``, every
  request self-describing.

This module owns only the 2026-07-28 envelope: era detection, the validation
ladder (``_meta`` fields -> routing headers -> protocol version ->
``Mcp-Param-*`` headers), ``server/discover``, the method surface, result
stamping (``resultType``, ``_meta`` serverInfo, ``ttlMs``/``cacheScope``) and
error-code/HTTP-status mapping.  The tools/prompts/resources logic itself is
reused from ``MCPHandler``.

Beyond the envelope:

* streamed ``tools/call`` responses (SSE) carrying ``notifications/progress``
  and ``notifications/message`` (only at the request's ``logLevel``); closing
  the stream cancels the call.  No resumability.
* ``subscriptions/listen`` fed by the change bus (sajha.core.change_bus);
* MRTR ``InputRequiredResult`` with an HMAC-signed ``requestState``
  (sajha.core.mcp_mrtr), incl. an optional confirmation for destructive tools;
* the tasks extension ``io.modelcontextprotocol/tasks`` (sajha.core.mcp_tasks).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple, Union

from starlette.concurrency import run_in_threadpool

from sajha.core.change_bus import PROMPTS, RESOURCE_UPDATED, RESOURCES, TOOLS, get_change_bus
from sajha.core.mcp_2025_11_25 import MCPError, SUPPORTED_PROTOCOL_VERSIONS as HANDSHAKE_PROTOCOL_VERSIONS
from sajha.core.mcp_mrtr import (MRTR_METHODS, InputRequired, RequestStateError, accepted_content,
                                 elicitation_form_supported, elicitation_request, missing_capabilities_for,
                                 sign_state, validate_input_responses, verify_state)
from sajha.core.mcp_tasks import (TASKS_EXTENSION, TaskNotFound, client_declares_tasks, get_task_store,
                                  required_capability)
from sajha.core.mcp_tool_context import ModernToolContext

logger = logging.getLogger(__name__)

# ── Versions ─────────────────────────────────────────────────────

MODERN_PROTOCOL_VERSIONS: List[str] = ["2026-07-28"]
LATEST_MODERN_VERSION: str = MODERN_PROTOCOL_VERSIONS[0]
# Every version this server speaks, newest first (server/discover, -32022 data)
ALL_SUPPORTED_VERSIONS: List[str] = MODERN_PROTOCOL_VERSIONS + list(HANDSHAKE_PROTOCOL_VERSIONS)

# ── Reserved _meta keys ──────────────────────────────────────────

PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
LOG_LEVEL_META_KEY = "io.modelcontextprotocol/logLevel"
SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
SUBSCRIPTION_ID_META_KEY = "io.modelcontextprotocol/subscriptionId"

# ── HTTP headers (lowercase; Starlette header lookups are case-insensitive) ──

PROTOCOL_VERSION_HEADER = "mcp-protocol-version"
METHOD_HEADER = "mcp-method"
NAME_HEADER = "mcp-name"
PARAM_HEADER_PREFIX = "mcp-param-"
X_MCP_HEADER_KEY = "x-mcp-header"
_ROUTING_HEADERS = (PROTOCOL_VERSION_HEADER, METHOD_HEADER, NAME_HEADER)

# Method -> params key mirrored into the Mcp-Name header
NAME_BEARING_METHODS: Dict[str, str] = {
    "tools/call": "name",
    "prompts/get": "name",
    "resources/read": "uri",
    # tasks extension (SEP-2663, "Streamable HTTP: Routing Headers")
    "tasks/get": "taskId",
    "tasks/update": "taskId",
    "tasks/cancel": "taskId",
}

# ── Error codes ──────────────────────────────────────────────────

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
HEADER_MISMATCH = -32020
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
UNSUPPORTED_PROTOCOL_VERSION = -32022
_SPEC_RESERVED_CODES = {HEADER_MISMATCH, MISSING_REQUIRED_CLIENT_CAPABILITY, UNSUPPORTED_PROTOCOL_VERSION}

# SAJHA implementation-defined codes on the modern path.  2026-07-28 reserves
# -32020..-32099 for the spec and forbids emitting -32002 (old "resource not
# found"), so SAJHA's own codes stay in -32000..-32019 and avoid -32002.
SAJHA_UNAUTHORIZED = -32001
SAJHA_FORBIDDEN = -32010  # implementation-defined range -32000..-32019

# JSON-RPC error code -> HTTP status (streamable-http "Server Validation" and
# "Protocol Version Header"); unmapped codes are sent with 200.
ERROR_HTTP_STATUS: Dict[int, int] = {
    PARSE_ERROR: 400,
    INVALID_REQUEST: 400,
    INVALID_PARAMS: 400,
    HEADER_MISMATCH: 400,
    MISSING_REQUIRED_CLIENT_CAPABILITY: 400,
    UNSUPPORTED_PROTOCOL_VERSION: 400,
    METHOD_NOT_FOUND: 404,
}

# Methods that return CacheableResult in 2026-07-28 -> config key of their TTL
_CACHEABLE: Dict[str, Tuple[str, int]] = {
    "server/discover": ("mcp.cache.discover_ttl_ms", 300000),
    "tools/list": ("mcp.cache.list_ttl_ms", 60000),
    "prompts/list": ("mcp.cache.list_ttl_ms", 60000),
    "resources/list": ("mcp.cache.list_ttl_ms", 60000),
    "resources/templates/list": ("mcp.cache.list_ttl_ms", 60000),
    "resources/read": ("mcp.cache.read_ttl_ms", 30000),
}

# MCP logging levels (RFC 5424), for validating the per-request logLevel
LOG_LEVELS = ("debug", "info", "notice", "warning", "error", "critical", "alert", "emergency")


# ── Era detection ────────────────────────────────────────────────

def _meta_of(body: Any) -> Optional[Mapping]:
    if not isinstance(body, dict):
        return None
    params = body.get("params")
    if not isinstance(params, dict):
        return None
    meta = params.get("_meta")
    return meta if isinstance(meta, dict) else None


def is_modern_request(body: Any, headers: Mapping[str, str]) -> bool:
    """
    Decide whether a POST /mcp message belongs to the 2026-07-28 era.

    * A body carrying ``_meta["io.modelcontextprotocol/protocolVersion"]`` is
      modern (even ``initialize``: a modern client sending it gets 404/-32601).
    * Otherwise ``initialize`` is legacy (the handshake selects legacy
      semantics for the session).
    * Otherwise an ``MCP-Protocol-Version`` header naming a version that is
      not a handshake-era version (2026-07-28, or an unknown one) routes to the
      modern ladder, which answers a structured -32602/-32020/-32022 instead of
      a legacy error, as the SDK's era router does.
    * Everything else is legacy.
    """
    meta = _meta_of(body)
    if meta is not None and PROTOCOL_VERSION_META_KEY in meta:
        return True
    if isinstance(body, dict) and body.get("method") == "initialize":
        return False
    version = (headers.get(PROTOCOL_VERSION_HEADER) or "").strip()
    return bool(version) and version not in HANDSHAKE_PROTOCOL_VERSIONS


def is_modern_header(headers: Mapping[str, str]) -> bool:
    """GET/DELETE heuristic: the client announced a modern protocol version."""
    version = (headers.get(PROTOCOL_VERSION_HEADER) or "").strip()
    return bool(version) and version not in HANDSHAKE_PROTOCOL_VERSIONS


# ── Request context ──────────────────────────────────────────────

@dataclass
class ModernRequestContext:
    """Everything the server knows about a modern request — taken from the request alone."""

    protocol_version: str
    client_capabilities: Dict[str, Any]
    client_info: Optional[Dict[str, Any]] = None
    log_level: Optional[str] = None          # None -> MUST NOT send notifications/message
    progress_token: Any = None
    traceparent: Optional[str] = None
    tracestate: Optional[str] = None
    baggage: Optional[str] = None
    extra_meta: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "ModernRequestContext":
        caps = meta.get(CLIENT_CAPABILITIES_META_KEY)
        info = meta.get(CLIENT_INFO_META_KEY)
        level = meta.get(LOG_LEVEL_META_KEY)
        return cls(
            protocol_version=meta.get(PROTOCOL_VERSION_META_KEY),
            client_capabilities=caps if isinstance(caps, dict) else {},
            client_info=info if isinstance(info, dict) else None,
            log_level=level if isinstance(level, str) and level in LOG_LEVELS else None,
            progress_token=meta.get("progressToken"),
            traceparent=meta.get("traceparent") if isinstance(meta.get("traceparent"), str) else None,
            tracestate=meta.get("tracestate") if isinstance(meta.get("tracestate"), str) else None,
            baggage=meta.get("baggage") if isinstance(meta.get("baggage"), str) else None,
            extra_meta={k: v for k, v in meta.items() if not k.startswith("io.modelcontextprotocol/")},
        )

    def missing_capabilities(self, required: Mapping[str, Any]) -> Dict[str, Any]:
        """The subset of ``required`` (a ClientCapabilities object) the client did not declare."""
        return {k: v for k, v in (required or {}).items() if k not in self.client_capabilities}


class ModernError(Exception):
    """A modern-path JSON-RPC error with its HTTP status."""

    def __init__(self, code: int, message: str, data: Any = None, status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        self.status = status if status is not None else ERROR_HTTP_STATUS.get(code, 200)


# ── Header codec / validation ────────────────────────────────────

_B64_SENTINEL = re.compile(r"^=\?base64\?(?P<payload>.*)\?=$")
_HEADER_SAFE = re.compile(r"^[\x20-\x7E\t]*$")
_RFC9110_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_CANONICAL_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")


def decode_header_value(value: Optional[str]) -> Optional[str]:
    """Decode the ``=?base64?...?=`` sentinel; ``None`` for a malformed sentinel."""
    if value is None:
        return None
    m = _B64_SENTINEL.fullmatch(value)
    if m is None:
        return value
    payload = m.group("payload")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None
    if base64.b64encode(decoded).decode("ascii") != payload:   # non-canonical
        return None
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    value = headers.get(name)
    return value.strip() if isinstance(value, str) else None


def find_duplicated_routing_header(raw_headers: List[Tuple[str, str]]) -> Optional[str]:
    seen = set()
    for name, _ in raw_headers:
        key = name.lower()
        if key in _ROUTING_HEADERS:
            if key in seen:
                return key
            seen.add(key)
    return None


def _render_scalar(value: Any) -> Optional[str]:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _annotated_properties(schema: Any, path: Tuple[str, ...] = ()):
    """Yield (path, token, property_schema) for x-mcp-header annotations reachable via `properties` only."""
    if not isinstance(schema, dict):
        return
    props = schema.get("properties")
    if not isinstance(props, dict):
        return
    for name, sub in props.items():
        if not isinstance(sub, dict):
            continue
        sub_path = path + (name,)
        token = sub.get(X_MCP_HEADER_KEY)
        if isinstance(token, str) and _RFC9110_TOKEN.fullmatch(token) \
                and sub.get("type") in ("string", "integer", "boolean"):
            yield sub_path, token, sub
        yield from _annotated_properties(sub, sub_path)


def _value_at(arguments: Mapping[str, Any], path: Tuple[str, ...]) -> Any:
    node: Any = arguments
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def validate_param_headers(input_schema: Any, arguments: Mapping[str, Any],
                           raw_headers: List[Tuple[str, str]]) -> Optional[str]:
    """
    Check ``Mcp-Param-{Name}`` headers against the tools/call arguments
    (streamable-http "Custom Headers from Tool Parameters").  Returns an error
    message for a HeaderMismatch, else None.
    """
    folded: Dict[str, str] = {}
    duplicated = set()
    for name, value in raw_headers:
        key = name.lower()
        if not key.startswith(PARAM_HEADER_PREFIX):
            continue
        if key in folded:
            duplicated.add(key)
        folded[key] = value.strip()
    for path, token, prop in _annotated_properties(input_schema):
        header_name = f"Mcp-Param-{token}"
        key = header_name.lower()
        raw = folded.get(key)
        value = _value_at(arguments, path)
        argument = ".".join(path)
        if raw is not None and key in duplicated:
            return f"{header_name} header appears more than once"
        rendered = _render_scalar(value) if value is not None else None
        if value is None or rendered is None:
            if raw is not None:
                return f"{header_name} header is present but the body's {argument!r} argument is absent"
            continue
        if raw is None:
            return f"{header_name} header is missing but the body's {argument!r} argument is present"
        if not _HEADER_SAFE.fullmatch(raw):
            return f"{header_name} header contains invalid characters"
        decoded = decode_header_value(raw)
        if decoded is None:
            return f"{header_name} header carries a malformed base64 value"
        if prop.get("type") == "integer" and not isinstance(value, bool) and isinstance(value, (int, float)) \
                and _CANONICAL_DECIMAL.fullmatch(decoded):
            whole, _, frac = decoded.partition(".")
            if (frac and set(frac) != {"0"}) or int(whole) != int(value):
                return f"{header_name} header does not match the body's {argument!r} argument"
            continue
        if decoded != rendered:
            return f"{header_name} header does not match the body's {argument!r} argument"
    return None


def classify(body: Dict[str, Any], headers: Mapping[str, str]) -> ModernRequestContext:
    """
    The 2026-07-28 validation ladder; first failure wins.

    1. ``params._meta`` carries protocolVersion and clientCapabilities -> else -32602
    2. ``MCP-Protocol-Version`` / ``Mcp-Method`` / ``Mcp-Name`` match the body -> else -32020
    3. the protocol version is one this server serves -> else -32022
    """
    meta = _meta_of(body)
    if meta is None:
        raise ModernError(INVALID_PARAMS, "params._meta must be an object carrying the required "
                                          f"'{PROTOCOL_VERSION_META_KEY}' and "
                                          f"'{CLIENT_CAPABILITIES_META_KEY}' keys")
    missing = [k for k in (PROTOCOL_VERSION_META_KEY, CLIENT_CAPABILITIES_META_KEY) if k not in meta]
    if missing:
        raise ModernError(INVALID_PARAMS, f"params._meta is missing required key(s): {', '.join(missing)}")
    version = meta[PROTOCOL_VERSION_META_KEY]

    version_header = _header(headers, PROTOCOL_VERSION_HEADER)
    if version_header is None:
        raise ModernError(HEADER_MISMATCH, "Header mismatch: MCP-Protocol-Version header is missing")
    if version_header != version:
        raise ModernError(HEADER_MISMATCH, f"Header mismatch: MCP-Protocol-Version header value "
                                           f"{version_header!r} does not match body value {version!r}")
    method = body.get("method")
    method_header = _header(headers, METHOD_HEADER)
    if method_header != method:
        raise ModernError(HEADER_MISMATCH, f"Header mismatch: Mcp-Method header value {method_header!r} "
                                           f"does not match body value {method!r}")
    name_key = NAME_BEARING_METHODS.get(method)
    if name_key is not None:
        body_value = body["params"].get(name_key)
        if body_value is not None:
            raw = _header(headers, NAME_HEADER)
            if raw is None:
                raise ModernError(HEADER_MISMATCH, "Header mismatch: Mcp-Name header is missing")
            if decode_header_value(raw) != body_value:
                raise ModernError(HEADER_MISMATCH, f"Header mismatch: Mcp-Name header value {raw!r} "
                                                   f"does not match body value {body_value!r}")

    if not isinstance(version, str):
        raise ModernError(INVALID_PARAMS, "the protocol-version _meta value must be a string")
    if version not in MODERN_PROTOCOL_VERSIONS:
        raise unsupported_version_error(version)
    return ModernRequestContext.from_meta(meta)


def unsupported_version_error(requested: Any) -> ModernError:
    return ModernError(UNSUPPORTED_PROTOCOL_VERSION, "Unsupported protocol version",
                       {"supported": list(ALL_SUPPORTED_VERSIONS), "requested": requested})


# ── Response streams (SSE) ───────────────────────────────────────

class ModernStream:
    """
    An SSE response body on the modern path: notifications, then (for a
    request) the final JSON-RPC response.  No event ids, no priming event and
    no resumption: 2026-07-28 has no resumability, a dropped stream is a
    cancelled request.  Only notifications are ever written — never a
    JSON-RPC *request* (server -> client input goes through MRTR).

    ``producer(emit)`` runs as its own task; when the client closes the stream
    the generator is closed, the producer task is cancelled and every
    ``on_close`` hook runs (e.g. to flag a thread-pool tool as cancelled).
    """

    def __init__(self, producer: Callable[[Callable[[Dict[str, Any]], None]], Awaitable[Optional[Dict[str, Any]]]]):
        self._producer = producer
        self.on_close: List[Callable[[], None]] = []

    async def events(self):
        queue: asyncio.Queue = asyncio.Queue()
        job = asyncio.ensure_future(self._producer(queue.put_nowait))
        getter: Optional[asyncio.Future] = None
        completed = False
        try:
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, job}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield {"data": json.dumps(getter.result())}
                    continue
                getter.cancel()
                while not queue.empty():
                    yield {"data": json.dumps(queue.get_nowait())}
                final = job.result()
                completed = True
                if final is not None:
                    yield {"data": json.dumps(final)}
                return
        finally:
            if getter is not None and not getter.done():
                getter.cancel()
            if not job.done():
                job.cancel()
            if not completed:
                for hook in self.on_close:
                    try:
                        hook()
                    except Exception:
                        pass
                logger.info("Modern response stream closed before completion; request cancelled")


@dataclass
class _CallScope:
    """Per-request plumbing: where notifications go and what to do on cancel."""
    emit: Optional[Callable[[Dict[str, Any]], None]] = None
    cancel_hooks: List[Callable[[], None]] = field(default_factory=list)

    def cancel(self) -> None:
        for hook in self.cancel_hooks:
            try:
                hook()
            except Exception:
                pass


async def _run_in_thread(fn, *args):
    """Run blocking work in the thread pool; on cancellation stop waiting (the thread is abandoned)."""
    import anyio.to_thread
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args), abandon_on_cancel=True)
    except TypeError:   # anyio < 4.1
        return await anyio.to_thread.run_sync(lambda: fn(*args), cancellable=True)


# ── The modern server ────────────────────────────────────────────

class ModernMCPServer:
    """Serves 2026-07-28 requests by reusing an ``MCPHandler``'s feature logic."""

    # Methods served on the modern path.  Everything else — including the
    # methods 2026-07-28 removed (initialize, ping, logging/setLevel,
    # resources/subscribe, resources/unsubscribe), tasks/list and tasks/result
    # (not part of the tasks extension) and SAJHA's legacy aliases — is
    # -32601 / HTTP 404.
    METHODS = (
        "server/discover",
        "tools/list", "tools/call",
        "prompts/list", "prompts/get",
        "resources/list", "resources/read", "resources/templates/list",
        "completion/complete",
        "subscriptions/listen",
        "tasks/get", "tasks/update", "tasks/cancel",
    )
    TASK_METHODS = ("tasks/get", "tasks/update", "tasks/cancel")
    DESTRUCTIVE_CONFIRM_KEY = "sajha_confirm_destructive"

    def __init__(self, handler):
        self.handler = handler

    # -- identity / capabilities ----------------------------------

    @property
    def server_info(self) -> Dict[str, Any]:
        return copy.deepcopy(self.handler.implementation)

    @staticmethod
    def tasks_enabled() -> bool:
        from sajha.core.config import _bool
        return _bool("mcp.tasks.enabled", True)

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Server capabilities on the 2026-07-28 wire."""
        legacy = self.handler.capabilities
        caps = {
            # Delivered on subscriptions/listen streams via the change bus
            # (tool registry / prompt registry changes).  resources: the tool
            # and prompt catalogs (sajha://tools/catalog, sajha://prompts/catalog)
            # change with them -> resources/list_changed + resources/updated.
            "tools": {"listChanged": True},
            "prompts": {"listChanged": True},
            "resources": {"subscribe": True, "listChanged": True},
            "completions": {},
            # notifications/message is sent on streamed tools/call responses,
            # only at the request's _meta logLevel.
            "logging": {},
            "extensions": {},
        }
        if self.tasks_enabled():
            caps["extensions"][TASKS_EXTENSION] = {}
        sajha = copy.deepcopy((legacy.get("experimental") or {}).get("sajha") or {})
        sajha.pop("websocket", None)   # the WebSocket transport is legacy-era only
        if sajha:
            caps["experimental"] = {"sajha": sajha}
        return caps

    # -- caching ---------------------------------------------------

    def _cache_fields(self, method: str, session: Optional[Dict]) -> Dict[str, Any]:
        from sajha.core.config import _get, _int
        key, default = _CACHEABLE[method]
        ttl = max(0, _int(key, default))
        scope = (_get("mcp.cache.scope", "auto") or "auto").strip().lower()
        if scope not in ("public", "private"):
            scope = "private" if self._caller_scoped(method, session) else "public"
        return {"ttlMs": ttl, "cacheScope": scope}

    def _caller_scoped(self, method: str, session: Optional[Dict]) -> bool:
        if method == "tools/list":
            return self.handler.tools_list_is_caller_scoped(session)
        return False

    # -- entry point -----------------------------------------------

    async def handle(self, body: Any, headers: Mapping[str, str], raw_headers: List[Tuple[str, str]],
                     session: Optional[Dict], receive: Optional[Callable[[], Awaitable[Dict[str, Any]]]] = None
                     ) -> Union[Tuple[int, Optional[Dict[str, Any]]], ModernStream]:
        """
        Serve one modern POST body.  Returns (http_status, json_body) — a
        ``None`` body means "202 Accepted, empty" (an accepted notification) —
        or a :class:`ModernStream` to send as ``text/event-stream``.

        Streams are used for ``subscriptions/listen`` and for a ``tools/call``
        whose client accepts SSE and asked for notifications (a progressToken
        or a logLevel in ``_meta``); everything else is plain JSON.  A JSON
        ``tools/call`` is still cancelled when the client disconnects (pass the
        ASGI ``receive`` channel to enable that).
        """
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" \
                or not isinstance(body.get("method"), str):
            return self._error_response(None, ModernError(
                INVALID_REQUEST, "Body must be a single JSON-RPC request or notification object"))

        # Notification: 202 when the version is served (no core client->server
        # notifications exist on this wire; they are acknowledged and dropped).
        if "id" not in body:
            version = _header(headers, PROTOCOL_VERSION_HEADER) or ""
            if version not in MODERN_PROTOCOL_VERSIONS:
                return self._error_response(None, unsupported_version_error(version))
            logger.debug(f"Acknowledged and dropped modern notification {body['method']}")
            return 202, None

        rid = body.get("id")
        if rid is None or isinstance(rid, bool) or not isinstance(rid, (str, int)):
            return self._error_response(None, ModernError(INVALID_REQUEST, "Request id must be a string or integer"))
        if body.get("params") is not None and not isinstance(body.get("params"), dict):
            return self._error_response(rid, ModernError(INVALID_PARAMS, "params must be an object"))

        method = body["method"]
        params = dict(body.get("params") or {})
        try:
            dup = find_duplicated_routing_header(raw_headers)
            if dup is not None:
                raise ModernError(HEADER_MISMATCH, f"Header mismatch: {dup} header appears more than once")
            ctx = classify(body, headers)
            if method not in self.METHODS:
                raise ModernError(METHOD_NOT_FOUND, f"Method not found: {method}", method)
            accepts_sse = "text/event-stream" in (headers.get("accept") or "")
            if method == "subscriptions/listen":
                return self._listen(rid, params, ctx, accepts_sse)
        except ModernError as e:
            return self._error_response(rid, e)

        if method == "tools/call" and accepts_sse and (ctx.progress_token is not None or ctx.log_level):
            scope = _CallScope()

            async def produce(emit):
                scope.emit = emit
                _, payload = await self._respond(rid, method, params, ctx, raw_headers, session, scope)
                return payload

            stream = ModernStream(produce)
            stream.on_close.append(scope.cancel)
            return stream

        scope = _CallScope()
        coro = self._respond(rid, method, params, ctx, raw_headers, session, scope)
        if method == "tools/call" and receive is not None:
            return await self._until_disconnect(coro, receive, scope, rid)
        return await coro

    async def _until_disconnect(self, coro, receive, scope: _CallScope, rid):
        """
        Await ``coro`` but cancel it (and the tool) if the client goes away.

        ``receive`` is the ASGI receive channel: once the body has been read,
        the next message it yields is ``http.disconnect``.  (Polling
        ``Request.is_disconnected()`` does not work behind BaseHTTPMiddleware,
        whose wrapped receive is cancelled before the server resumes reading.)
        """
        async def watch():
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    return

        job = asyncio.ensure_future(coro)
        watcher = asyncio.ensure_future(watch())
        try:
            await asyncio.wait({job, watcher}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if not watcher.done():
                watcher.cancel()
        if job.done():
            return job.result()
        job.cancel()
        scope.cancel()
        logger.info("Client disconnected; modern tools/call cancelled")
        return 499, {"jsonrpc": "2.0", "id": rid,
                     "error": {"code": INTERNAL_ERROR, "message": "Request cancelled: client disconnected"}}

    async def _respond(self, rid, method: str, params: Dict[str, Any], ctx: ModernRequestContext,
                       raw_headers: List[Tuple[str, str]], session: Optional[Dict],
                       scope: _CallScope) -> Tuple[int, Dict[str, Any]]:
        try:
            result = await self._dispatch(method, params, ctx, raw_headers, session, scope)
        except ModernError as e:
            return self._error_response(rid, e)
        except MCPError as e:
            return self._error_response(rid, self._map_mcp_error(e))
        except RequestStateError as e:
            return self._error_response(rid, ModernError(INVALID_PARAMS, str(e)))
        except PermissionError as e:
            return self._error_response(rid, ModernError(SAJHA_FORBIDDEN, str(e)))
        except ValueError as e:
            return self._error_response(rid, ModernError(INVALID_PARAMS, str(e)))
        except Exception as e:  # never leak handler internals
            logger.error(f"Modern MCP request {method} failed: {e}", exc_info=True)
            return self._error_response(rid, ModernError(INTERNAL_ERROR, "Internal server error"))
        return 200, {"jsonrpc": "2.0", "id": rid, "result": result}

    # -- dispatch --------------------------------------------------

    async def _dispatch(self, method: str, params: Dict[str, Any], ctx: ModernRequestContext,
                        raw_headers: List[Tuple[str, str]], session: Optional[Dict],
                        scope: _CallScope) -> Dict[str, Any]:
        if ctx.traceparent:
            logger.debug(f"{method}: traceparent={ctx.traceparent}")

        h = self.handler
        params.pop("_meta", None)
        if method == "server/discover":
            result = {
                "supportedVersions": list(ALL_SUPPORTED_VERSIONS),
                "capabilities": self.capabilities,
                "instructions": h.instructions,
            }
        elif method == "tools/list":
            result = await run_in_threadpool(h._handle_tools_list, params, session, "modern")
        elif method in MRTR_METHODS:
            result = await self._with_mrtr(method, params, ctx, raw_headers, session, scope)
        elif method == "prompts/list":
            result = await run_in_threadpool(h.handle_prompts_list, params, "modern")
        elif method == "resources/list":
            result = await run_in_threadpool(h._handle_resources_list, params)
        elif method == "resources/templates/list":
            result = await run_in_threadpool(h._handle_resources_templates_list, params)
        elif method in self.TASK_METHODS:
            result = self._task_method(method, params, ctx, session)
        else:  # completion/complete
            result = await run_in_threadpool(h._handle_completion_complete, params)
        return self._finish(method, dict(result or {}), session)

    def _finish(self, method: str, result: Dict[str, Any], session: Optional[Dict]) -> Dict[str, Any]:
        """Stamp resultType, caching hints and the serverInfo _meta on a result."""
        result.setdefault("resultType", "complete")
        if method in _CACHEABLE and result["resultType"] == "complete":
            for k, v in self._cache_fields(method, session).items():
                result.setdefault(k, v)
        meta = result.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        if meta.get(SERVER_INFO_META_KEY) is None:
            result["_meta"] = {**meta, SERVER_INFO_META_KEY: self.server_info}
        return result

    # -- MRTR (SEP-2322) ---------------------------------------------

    async def _with_mrtr(self, method: str, params: Dict[str, Any], ctx: ModernRequestContext,
                         raw_headers: List[Tuple[str, str]], session: Optional[Dict],
                         scope: _CallScope) -> Dict[str, Any]:
        """
        Run tools/call, prompts/get or resources/read with MRTR: merge the
        client's ``inputResponses`` with those carried in a verified
        ``requestState``, and turn an ``InputRequired`` from the handler into
        an ``InputRequiredResult`` with a freshly signed ``requestState``.
        """
        if "inputResponses" in params:
            input_responses = validate_input_responses(params.get("inputResponses"))
            if params.get("inputResponses") is None:
                raise ModernError(INVALID_PARAMS, "inputResponses must be an object, not null")
        else:
            input_responses = {}
        target = params.get("uri") if method == "resources/read" else params.get("name")
        arguments = params.get("arguments")
        user = (session or {}).get("user_id")
        prior: Dict[str, Any] = {}
        state: Dict[str, Any] = {}
        round_no = 0
        verified = False
        token = params.get("requestState")
        if token is not None:
            payload = verify_state(token, method=method, target=str(target), arguments=arguments, user=user)
            prior, state, round_no, verified = payload.get("r") or {}, payload.get("s") or {}, payload.get("n", 0), True
        responses = {**prior, **input_responses}
        tool_ctx = ModernToolContext(client_capabilities=ctx.client_capabilities,
                                     progress_token=ctx.progress_token, log_level=ctx.log_level,
                                     emit=scope.emit, input_responses=responses, state=state,
                                     state_verified=verified).bind_loop()
        scope.cancel_hooks.append(tool_ctx.cancel)
        try:
            if method == "tools/call":
                return await self._tools_call(params, ctx, raw_headers, session, tool_ctx)
            if method == "prompts/get":
                return await self._prompts_get(params, tool_ctx)
            return await run_in_threadpool(self.handler._handle_resources_read, params)
        except InputRequired as ir:
            missing = missing_capabilities_for(ir.requests, ctx.client_capabilities)
            if missing:
                raise ModernError(MISSING_REQUIRED_CLIENT_CAPABILITY,
                                  f"{method} needs client input the client cannot provide: "
                                  f"{', '.join(missing)}", {"requiredCapabilities": missing})
            carried = {k: v for k, v in responses.items() if k not in ir.requests}
            return {
                "resultType": "input_required",
                "inputRequests": ir.requests,
                "requestState": sign_state(method=method, target=str(target), arguments=arguments, user=user,
                                           responses=carried, state={**state, **ir.state},
                                           round_no=int(round_no) + 1),
            }

    async def _prompts_get(self, params: Dict[str, Any], tool_ctx: ModernToolContext) -> Dict[str, Any]:
        fixtures = self.handler._fixtures()
        name = params.get("name")
        if fixtures and isinstance(name, str) and fixtures.has_prompt(name, "modern"):
            try:
                return await run_in_threadpool(fixtures.get_prompt_mrtr, name, params.get("arguments") or {},
                                               tool_ctx)
            except ValueError as e:
                raise MCPError(INVALID_PARAMS, str(e))
        return await run_in_threadpool(self.handler.handle_prompts_get, params)

    # -- tools/call ------------------------------------------------------

    def _tool_input_schema(self, name: str) -> Optional[Dict]:
        fixtures = self.handler._fixtures()
        if fixtures and fixtures.has_tool(name, "modern"):
            return fixtures.tool_input_schema(name)
        registry = self.handler.tools_registry
        tool = registry.get_tool(name) if registry and isinstance(name, str) else None
        if tool is None:
            return None
        try:
            return tool.input_schema
        except Exception:
            return None

    def _task_support(self, name: Any) -> Optional[str]:
        if not isinstance(name, str) or not self.tasks_enabled():
            return None
        fixtures = self.handler._fixtures()
        if fixtures and fixtures.has_tool(name, "modern"):
            return fixtures.task_support(name)
        return self.handler.tool_task_support(name)

    async def _tools_call(self, params: Dict[str, Any], ctx: ModernRequestContext,
                          raw_headers: List[Tuple[str, str]], session: Optional[Dict],
                          tool_ctx: ModernToolContext) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments")
        if isinstance(name, str) and (arguments is None or isinstance(arguments, dict)):
            schema = self._tool_input_schema(name)
            if schema is not None:
                problem = validate_param_headers(schema, arguments or {}, raw_headers)
                if problem:
                    raise ModernError(HEADER_MISMATCH, f"Header mismatch: {problem}")

        fixtures = self.handler._fixtures()
        if fixtures and isinstance(name, str) and fixtures.has_tool(name, "modern"):
            missing = ctx.missing_capabilities(fixtures.required_client_capabilities(name))
            if missing:
                raise ModernError(MISSING_REQUIRED_CLIENT_CAPABILITY,
                                  f"Tool {name} requires client capabilities: {', '.join(missing)}",
                                  {"requiredCapabilities": missing})

        # Tasks extension (SEP-2663): the server decides; a client opts in per request
        support = self._task_support(name)
        if support:
            declared = client_declares_tasks(ctx.client_capabilities)
            if support == "required" and not declared:
                raise ModernError(MISSING_REQUIRED_CLIENT_CAPABILITY,
                                  f"Tool {name} runs only as a task: declare the {TASKS_EXTENSION} extension",
                                  {"requiredCapabilities": required_capability()})
            after_input = bool(fixtures and fixtures.has_tool(name, "modern") and fixtures.task_after_input(name))
            if declared and (not after_input or tool_ctx.input_responses):
                return self._create_task(name, params, ctx, session, tool_ctx)

        return await self._invoke_tool(name, params, session, tool_ctx)

    async def _invoke_tool(self, name: Any, params: Dict[str, Any], session: Optional[Dict],
                           tool_ctx: ModernToolContext) -> Dict[str, Any]:
        """Run one tool: async fixture, sync fixture or a registry tool (thread pool, cancellable)."""
        arguments = params.get("arguments") or {}
        fixtures = self.handler._fixtures()
        if fixtures and isinstance(name, str) and fixtures.has_tool(name, "modern"):
            if fixtures.is_async_tool(name):
                return await fixtures.call_tool_async(name, arguments, tool_ctx)
            return await _run_in_thread(fixtures.call_tool, name, arguments)

        refusal = self._confirm_destructive(name, tool_ctx)
        if refusal is not None:
            return refusal

        def work():
            token = tool_ctx.activate()
            try:
                return self.handler._handle_tools_call(params, session, "modern")
            finally:
                tool_ctx.deactivate(token)

        return await _run_in_thread(work)

    def _confirm_destructive(self, name: Any, tool_ctx: ModernToolContext) -> Optional[Dict[str, Any]]:
        """
        Optional confirmation for tools whose config marks them
        ``annotations.destructiveHint: true`` (``mcp.confirm_destructive_tools``,
        off by default).  Only asked when the client declared form-mode
        elicitation; otherwise the call proceeds as before.  Returns a
        CallToolResult when the user declined, None to proceed; raises
        InputRequired to ask.
        """
        from sajha.core.config import _bool
        if not _bool("mcp.confirm_destructive_tools", False) or not isinstance(name, str):
            return None
        registry = self.handler.tools_registry
        tool = registry.get_tool(name) if registry else None
        annotations = ((getattr(tool, "config", None) or {}).get("annotations") or {}) if tool else {}
        if not (isinstance(annotations, dict) and annotations.get("destructiveHint") is True):
            return None
        if not elicitation_form_supported(tool_ctx.client_capabilities):
            return None
        key = self.DESTRUCTIVE_CONFIRM_KEY
        response = tool_ctx.input_responses.get(key)
        if response is None:
            title = annotations.get("title") or name
            tool_ctx.require_input({key: elicitation_request(
                f"'{title}' can modify or delete data. Run it?",
                {"type": "object",
                 "properties": {"confirm": {"type": "boolean", "title": "Run this tool",
                                            "description": f"Confirm running {name}", "default": False}},
                 "required": ["confirm"]})})
        content = accepted_content(response)
        if content is not None and content.get("confirm") is True:
            return None
        return {"content": [{"type": "text", "text": f"Tool {name} was not run: the user did not confirm."}],
                "isError": True}

    # -- tasks extension (SEP-2663) -----------------------------------------

    def _create_task(self, name: str, params: Dict[str, Any], ctx: ModernRequestContext,
                     session: Optional[Dict], tool_ctx: ModernToolContext) -> Dict[str, Any]:
        owner = (session or {}).get("user_id")
        call_params = {k: v for k, v in params.items() if k not in ("inputResponses", "requestState", "task")}

        async def runner(task) -> Dict[str, Any]:
            run_ctx = ModernToolContext(client_capabilities=ctx.client_capabilities,
                                        input_responses=task.responses, state=task.state,
                                        state_verified=True).bind_loop()
            task.context = run_ctx
            try:
                return await self._invoke_tool(name, call_params, session, run_ctx)
            except InputRequired as ir:
                missing = missing_capabilities_for(ir.requests, ctx.client_capabilities)
                if missing:
                    raise MCPError(MISSING_REQUIRED_CLIENT_CAPABILITY,
                                   f"Tool {name} needs client input the client cannot provide",
                                   {"requiredCapabilities": missing})
                raise

        try:
            task = get_task_store().create(owner, runner, responses=tool_ctx.input_responses, state=tool_ctx.state)
        except OverflowError as e:
            raise ModernError(INTERNAL_ERROR, str(e))
        return {"resultType": "task", **task.envelope()}

    def _task_method(self, method: str, params: Dict[str, Any], ctx: ModernRequestContext,
                     session: Optional[Dict]) -> Dict[str, Any]:
        if not self.tasks_enabled():
            raise ModernError(METHOD_NOT_FOUND, f"Method not found: {method}", method)
        if not client_declares_tasks(ctx.client_capabilities):
            raise ModernError(MISSING_REQUIRED_CLIENT_CAPABILITY,
                              f"{method} requires the {TASKS_EXTENSION} extension",
                              {"requiredCapabilities": required_capability()})
        task_id = params.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise ModernError(INVALID_PARAMS, "taskId must be a non-empty string")
        store = get_task_store()
        owner = (session or {}).get("user_id")
        try:
            if method == "tasks/get":
                return {"resultType": "complete", **store.get(task_id, owner).detailed()}
            if method == "tasks/update":
                responses = validate_input_responses(params.get("inputResponses"))
                store.update(task_id, owner, responses)
                return {}
            store.cancel(task_id, owner)
            return {}
        except TaskNotFound:
            raise ModernError(INVALID_PARAMS, f"Unknown taskId: {task_id}")

    # -- subscriptions/listen ---------------------------------------------

    _FILTER_KINDS = (("toolsListChanged", TOOLS), ("promptsListChanged", PROMPTS),
                     ("resourcesListChanged", RESOURCES))

    def _listen(self, rid, params: Dict[str, Any], ctx: ModernRequestContext, accepts_sse: bool) -> ModernStream:
        """
        ``subscriptions/listen``: a long-lived POST answered with SSE.  First
        ``notifications/subscriptions/acknowledged`` (the honored subset of the
        filter), then only the opted-in notification types, every one tagged
        with ``_meta["io.modelcontextprotocol/subscriptionId"]`` (= the request
        id).  The stream ends with a SubscriptionsListenResult when the server
        shuts down, or when the client goes away.
        """
        from sajha.core.config import _int
        requested = params.get("notifications")
        if not isinstance(requested, dict):
            raise ModernError(INVALID_PARAMS, "subscriptions/listen requires a 'notifications' filter object")
        if not accepts_sse:
            raise ModernError(INVALID_REQUEST, "subscriptions/listen is answered with an SSE stream: "
                                               "the request must Accept text/event-stream", status=406)
        bus = get_change_bus()
        if bus.subscriber_count >= max(1, _int("mcp.subscriptions.max_streams", 1000)):
            raise ModernError(INTERNAL_ERROR, "Too many open subscription streams; retry later")
        honored: Dict[str, Any] = {}
        kinds = set()
        for field_name, kind in self._FILTER_KINDS:
            if requested.get(field_name) is True:
                honored[field_name] = True
                kinds.add(kind)
        uris = requested.get("resourceSubscriptions")
        if isinstance(uris, list) and uris:
            uris = [u for u in uris if isinstance(u, str)]
            if uris:
                honored["resourceSubscriptions"] = uris
                kinds.add(RESOURCE_UPDATED)
        else:
            uris = []

        server_info = self.server_info

        def tag(message: Dict[str, Any]) -> Dict[str, Any]:
            p = dict(message.get("params") or {})
            p["_meta"] = {**(p.get("_meta") or {}), SUBSCRIPTION_ID_META_KEY: rid}
            return {**message, "params": p}

        async def produce(emit):
            sub = bus.subscribe(kinds, uris)
            try:
                emit(tag({"jsonrpc": "2.0", "method": "notifications/subscriptions/acknowledged",
                          "params": {"notifications": honored}}))
                while True:
                    event = await sub.get()
                    if event is None:      # server shutting down: graceful end of the subscription
                        return {"jsonrpc": "2.0", "id": rid, "result": {
                            "resultType": "complete",
                            "_meta": {SUBSCRIPTION_ID_META_KEY: rid, SERVER_INFO_META_KEY: server_info}}}
                    emit(tag(event.notification()))
            finally:
                sub.close()

        return ModernStream(produce)

    # -- errors ------------------------------------------------------

    @staticmethod
    def _map_mcp_error(e: MCPError) -> ModernError:
        code, data = e.code, e.data
        if code == -32002:
            # Resource not found: -32602 in 2026-07-28 (SEP-2164); -32002 MUST NOT be emitted.
            return ModernError(INVALID_PARAMS, e.message, data)
        if -32099 <= code <= -32020 and code not in _SPEC_RESERVED_CODES:
            return ModernError(INTERNAL_ERROR, e.message, data)
        return ModernError(code, e.message, data)

    @staticmethod
    def _error_response(rid: Any, e: ModernError) -> Tuple[int, Dict[str, Any]]:
        error = {"code": e.code, "message": e.message}
        if e.data is not None:
            error["data"] = e.data
        return e.status, {"jsonrpc": "2.0", "id": rid, "error": error}


def parse_error_response() -> Tuple[int, Dict[str, Any]]:
    return 400, {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Parse error"}}
