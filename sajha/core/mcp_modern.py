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

Wave 1 scope: no response streaming (``notifications/progress`` /
``notifications/message`` are never sent), no ``subscriptions/listen``
(Wave 2), no MRTR ``InputRequiredResult`` or tasks extension (Wave 3).
"""

from __future__ import annotations

import base64
import binascii
import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from starlette.concurrency import run_in_threadpool

from sajha.core.mcp_2025_11_25 import MCPError, SUPPORTED_PROTOCOL_VERSIONS as HANDSHAKE_PROTOCOL_VERSIONS

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


# ── The modern server ────────────────────────────────────────────

class ModernMCPServer:
    """Serves 2026-07-28 requests by reusing an ``MCPHandler``'s feature logic."""

    # Methods served on the modern path.  Everything else — including the
    # methods 2026-07-28 removed (initialize, ping, logging/setLevel,
    # resources/subscribe, resources/unsubscribe), core tasks/* (now the tasks
    # extension, Wave 3) and SAJHA's legacy aliases — is -32601 / HTTP 404.
    METHODS = (
        "server/discover",
        "tools/list", "tools/call",
        "prompts/list", "prompts/get",
        "resources/list", "resources/read", "resources/templates/list",
        "completion/complete",
    )

    def __init__(self, handler):
        self.handler = handler

    # -- identity / capabilities ----------------------------------

    @property
    def server_info(self) -> Dict[str, Any]:
        return copy.deepcopy(self.handler.implementation)

    @property
    def capabilities(self) -> Dict[str, Any]:
        """Server capabilities on the 2026-07-28 wire."""
        legacy = self.handler.capabilities
        caps = {
            "tools": {"listChanged": False},
            "prompts": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
            "completions": {},
            # Wave 1 never streams, so it never sends notifications/message:
            # the `logging` capability is not advertised on the modern path.
            "extensions": {},
        }
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
                     session: Optional[Dict]) -> Tuple[int, Optional[Dict[str, Any]]]:
        """
        Serve one modern POST body.  Returns (http_status, json_body); a
        ``None`` body means "202 Accepted, empty" (an accepted notification).
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

        try:
            dup = find_duplicated_routing_header(raw_headers)
            if dup is not None:
                raise ModernError(HEADER_MISMATCH, f"Header mismatch: {dup} header appears more than once")
            ctx = classify(body, headers)
            result = await self._dispatch(body["method"], dict(body.get("params") or {}), ctx,
                                          raw_headers, session)
        except ModernError as e:
            return self._error_response(rid, e)
        except MCPError as e:
            return self._error_response(rid, self._map_mcp_error(e))
        except PermissionError as e:
            return self._error_response(rid, ModernError(SAJHA_FORBIDDEN, str(e)))
        except ValueError as e:
            return self._error_response(rid, ModernError(INVALID_PARAMS, str(e)))
        except Exception as e:  # never leak handler internals
            logger.error(f"Modern MCP request {body.get('method')} failed: {e}", exc_info=True)
            return self._error_response(rid, ModernError(INTERNAL_ERROR, "Internal server error"))
        return 200, {"jsonrpc": "2.0", "id": rid, "result": result}

    # -- dispatch --------------------------------------------------

    async def _dispatch(self, method: str, params: Dict[str, Any], ctx: ModernRequestContext,
                        raw_headers: List[Tuple[str, str]], session: Optional[Dict]) -> Dict[str, Any]:
        if method not in self.METHODS:
            raise ModernError(METHOD_NOT_FOUND, f"Method not found: {method}", method)
        if ctx.log_level:
            logger.debug(f"{method}: client requested logLevel={ctx.log_level} "
                         f"(no response stream in this release; nothing is sent)")
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
        elif method == "tools/call":
            result = await self._tools_call(params, ctx, raw_headers, session)
        elif method == "prompts/list":
            result = await run_in_threadpool(h.handle_prompts_list, params)
        elif method == "prompts/get":
            result = await run_in_threadpool(h.handle_prompts_get, params)
        elif method == "resources/list":
            result = await run_in_threadpool(h._handle_resources_list, params)
        elif method == "resources/read":
            result = await run_in_threadpool(h._handle_resources_read, params)
        elif method == "resources/templates/list":
            result = await run_in_threadpool(h._handle_resources_templates_list, params)
        else:  # completion/complete
            result = await run_in_threadpool(h._handle_completion_complete, params)
        return self._finish(method, dict(result or {}), session)

    def _finish(self, method: str, result: Dict[str, Any], session: Optional[Dict]) -> Dict[str, Any]:
        """Stamp resultType, caching hints and the serverInfo _meta on a result."""
        result.setdefault("resultType", "complete")
        if method in _CACHEABLE:
            for k, v in self._cache_fields(method, session).items():
                result.setdefault(k, v)
        meta = result.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        if meta.get(SERVER_INFO_META_KEY) is None:
            result["_meta"] = {**meta, SERVER_INFO_META_KEY: self.server_info}
        return result

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

    async def _tools_call(self, params: Dict[str, Any], ctx: ModernRequestContext,
                          raw_headers: List[Tuple[str, str]], session: Optional[Dict]) -> Dict[str, Any]:
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
            if fixtures.is_async_tool(name):
                # No response stream in Wave 1: notifications are dropped and
                # the tool's result is returned as plain JSON.
                from sajha.core.mcp_sessions import ToolCallContext
                return await fixtures.call_tool_async(name, arguments or {}, ToolCallContext(None, None, None))
        return await run_in_threadpool(self.handler._handle_tools_call, params, session, "modern")

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
