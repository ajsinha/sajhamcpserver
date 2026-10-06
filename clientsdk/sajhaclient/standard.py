"""
SAJHA MCP Server — Standard MCP Client (official MCP Python SDK under the hood)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``SajhaMCPClient`` is a thin wrapper over the official MCP Python SDK
(``mcp`` package, v2.x) ``mcp.Client``, speaking the standard **Streamable
HTTP** transport to ``<base_url>/mcp``. The SDK negotiates the protocol era
automatically (``mode="auto"``): it probes ``server/discover`` (MCP
2026-07-28) and falls back to the ``initialize`` handshake (2025-11-25 and
earlier) on older servers. The version that was agreed is exposed as
``negotiated_protocol_version``.

On top of the standard MCP operations, the same object gives access to the
SAJHA-specific features via the existing zero-dependency clients:
``.rest`` (``SajhaClient``: health, tool schemas, usage reports, admin),
``.a2a`` (``A2AClient``) and ``.websocket()`` (``MCPWebSocketClient``).

Install the optional dependency first::

    pip install sajhaclient[mcp]

Async usage::

    from sajhaclient import SajhaMCPClient

    async with SajhaMCPClient("http://localhost:3002", api_key="sja_xxx") as client:
        print(client.negotiated_protocol_version)
        tools = await client.list_tools()
        result = await client.call_tool("calc_percentage_change",
                                        {"old_value": 100, "new_value": 125})

Sync usage (runs the async client on a background event loop)::

    from sajhaclient import SajhaMCPSyncClient

    with SajhaMCPSyncClient("http://localhost:3002", jwt_token="eyJ...") as client:
        tools = client.list_tools()

Importing this module does NOT import ``mcp``; the SDK is imported lazily the
first time a client is constructed.
"""

from __future__ import annotations

import builtins
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from sajhaclient.auth import AuthProvider, ApiKeyAuth, JWTAuth, NoAuth
from sajhaclient.config import SajhaConfig
from sajhaclient.exceptions import SajhaConnectionError, SajhaMCPError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp import Client as _SDKClient
    from sajhaclient.a2a_client import A2AClient
    from sajhaclient.client import SajhaClient
    from sajhaclient.mcp_client import MCPWebSocketClient

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "SajhaMCPClient requires the official MCP Python SDK. "
    "Install it with:  pip install 'sajhaclient[mcp]'   (or: pip install 'mcp>=2.3,<3')"
)

__all__ = ["SajhaMCPClient", "SajhaMCPSyncClient", "require_mcp"]


def require_mcp():
    """Import and return the ``mcp`` package, or raise a helpful ImportError."""
    try:
        import mcp  # noqa: F401
        from mcp import Client  # noqa: F401  (v2 API — fails on mcp 1.x)
    except ImportError as e:
        raise ImportError(_INSTALL_HINT) from e
    return mcp


def resolve_auth(config: SajhaConfig, auth: Optional[AuthProvider] = None) -> AuthProvider:
    """Same precedence as SajhaClient / MCPClient: explicit auth, api_key, jwt_token, username+password."""
    if auth is not None:
        return auth
    if config.api_key:
        return ApiKeyAuth(config.api_key)
    if config.jwt_token:
        return JWTAuth.from_token(config.jwt_token)
    if config.username and config.password:
        return JWTAuth(config.base_url, config.username, config.password, timeout=config.timeout)
    return NoAuth()


def _make_httpx_auth(provider: AuthProvider):
    """Build an ``httpx2.Auth`` that stamps the SAJHA auth headers on every request.

    Evaluated per request, so JWT/OAuth refresh (``refresh_if_needed``) is honoured
    over long-lived sessions.
    """
    import httpx2

    class _SajhaHttpxAuth(httpx2.Auth):
        def auth_flow(self, request):
            try:
                provider.refresh_if_needed()
            except Exception:  # never block a request on a failed refresh; server will 401
                logger.warning("SAJHA auth refresh failed", exc_info=True)
            for k, v in provider.get_headers().items():
                request.headers[k] = v
            yield request

    return _SajhaHttpxAuth()


_BaseExceptionGroup = getattr(builtins, "BaseExceptionGroup", None)
if _BaseExceptionGroup is None:  # Python 3.10: anyio depends on the backport
    try:
        from exceptiongroup import BaseExceptionGroup as _BaseExceptionGroup
    except ImportError:
        _BaseExceptionGroup = None


def _iter_leaf_exceptions(exc: BaseException):
    if _BaseExceptionGroup is not None and isinstance(exc, _BaseExceptionGroup):
        for sub in exc.exceptions:
            yield from _iter_leaf_exceptions(sub)
    else:
        yield exc


def _translate(exc: BaseException) -> Optional[BaseException]:
    """Map SDK / transport errors to SAJHA exceptions (None = leave as is)."""
    from mcp import MCPError
    import httpx2

    for leaf in _iter_leaf_exceptions(exc):
        if isinstance(leaf, MCPError):
            return SajhaMCPError(leaf.code, leaf.message, getattr(leaf.error, "data", None))
        if isinstance(leaf, (httpx2.TransportError, ConnectionError, OSError)):
            return SajhaConnectionError(f"MCP transport error: {leaf}")
    return None


class SajhaMCPClient:
    """
    Standard MCP client for SAJHA (async), backed by the official ``mcp`` SDK.

    Args:
        base_url: SAJHA server URL, e.g. ``"http://localhost:3002"``. Overrides ``config.base_url``.
        config: A :class:`SajhaConfig` (credentials, timeout, extra headers, verify_ssl).
        auth: Explicit :class:`AuthProvider` (``ApiKeyAuth`` -> ``X-API-Key``,
            ``JWTAuth`` / ``OAuthAuth`` -> ``Authorization: Bearer``).
        api_key / jwt_token / username / password: Shortcuts copied into ``config``.
        mode: SDK negotiation mode — ``"auto"`` (default: discover, fall back to
            initialize), ``"legacy"`` (force the initialize handshake) or a modern
            version string such as ``"2026-07-28"`` (adopt directly).
        mcp_path: Path of the MCP endpoint (default ``"/mcp"``).
        client_name / client_version: Sent as ``clientInfo``.
        **client_kwargs: Passed through to ``mcp.Client`` (e.g. ``sampling_callback``,
            ``elicitation_callback``, ``logging_callback``, ``read_timeout_seconds``,
            ``cache``).

    All MCP operations return the SDK's typed pydantic results
    (``ListToolsResult``, ``CallToolResult``, ...). Protocol errors are raised as
    :class:`SajhaMCPError`, transport failures as :class:`SajhaConnectionError`.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        config: Optional[SajhaConfig] = None,
        auth: Optional[AuthProvider] = None,
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        mode: str = "auto",
        mcp_path: str = "/mcp",
        client_name: str = "sajhaclient",
        client_version: Optional[str] = None,
        **client_kwargs: Any,
    ):
        require_mcp()
        self.config = config or SajhaConfig()
        if base_url:
            self.config.base_url = base_url.rstrip("/")
        for name, value in (("api_key", api_key), ("jwt_token", jwt_token),
                            ("username", username), ("password", password)):
            if value is not None:
                setattr(self.config, name, value)
        self._auth = resolve_auth(self.config, auth)
        self.mode = mode
        self.mcp_url = self.config.base_url + "/" + mcp_path.lstrip("/")
        self._client_name = client_name
        if client_version is None:
            from sajhaclient import __version__ as client_version
        self._client_version = client_version
        self._client_kwargs = client_kwargs

        self._sdk: Optional["_SDKClient"] = None
        self._http = None
        self._rest: Optional["SajhaClient"] = None
        self._a2a: Optional["A2AClient"] = None

    # ── Lifecycle ────────────────────────────────────────────────

    async def connect(self) -> "SajhaMCPClient":
        """Open the Streamable HTTP connection and negotiate the protocol version."""
        if self._sdk is not None:
            return self
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        from mcp_types import Implementation

        self._http = httpx2.AsyncClient(
            headers={"User-Agent": f"sajhaclient/{self._client_version}", **self.config.headers},
            auth=_make_httpx_auth(self._auth),
            timeout=httpx2.Timeout(float(self.config.timeout), read=300.0),
            verify=self.config.verify_ssl,
        )
        kwargs = dict(self._client_kwargs)
        kwargs.setdefault("client_info", Implementation(name=self._client_name, version=self._client_version))
        sdk = Client(streamable_http_client(self.mcp_url, http_client=self._http), mode=self.mode, **kwargs)
        try:
            await sdk.__aenter__()
        except BaseException as e:
            await self._http.aclose()
            self._http = None
            mapped = _translate(e) if isinstance(e, Exception) else None
            if mapped is not None:
                raise mapped from e
            raise
        self._sdk = sdk
        logger.info("Connected to %s (MCP %s)", self.mcp_url, sdk.protocol_version)
        return self

    async def close(self) -> None:
        """Close the MCP session (sends DELETE for stateful sessions) and the HTTP client."""
        sdk, http = self._sdk, self._http
        self._sdk = self._http = None
        try:
            if sdk is not None:
                await sdk.__aexit__(None, None, None)
        finally:
            if http is not None:
                await http.aclose()

    async def __aenter__(self) -> "SajhaMCPClient":
        return await self.connect()

    async def __aexit__(self, *exc) -> None:
        await self.close()

    @property
    def connected(self) -> bool:
        return self._sdk is not None

    @property
    def sdk(self) -> "_SDKClient":
        """The underlying ``mcp.Client`` (for anything not wrapped here)."""
        if self._sdk is None:
            raise RuntimeError("SajhaMCPClient is not connected; use 'async with' or await connect()")
        return self._sdk

    # ── Negotiated session info ──────────────────────────────────

    @property
    def negotiated_protocol_version(self) -> str:
        """Protocol version agreed with the server, e.g. ``"2025-11-25"`` or ``"2026-07-28"``."""
        return self.sdk.protocol_version

    @property
    def server_info(self):
        """``mcp_types.Implementation`` or None (2026-era servers may stay anonymous)."""
        return self.sdk.server_info

    @property
    def server_capabilities(self):
        return self.sdk.server_capabilities

    @property
    def instructions(self) -> Optional[str]:
        return self.sdk.instructions

    # ── Standard MCP operations (delegated to the SDK) ───────────

    async def _call(self, fn: Callable, *args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            mapped = _translate(e)
            if mapped is not None:
                raise mapped from e
            raise

    async def list_tools(self, cursor: Optional[str] = None, **kwargs):
        """One page of ``tools/list`` -> ``ListToolsResult``."""
        return await self._call(self.sdk.list_tools, cursor=cursor, **kwargs)

    async def list_all_tools(self) -> List[Any]:
        """All tools, following ``next_cursor`` pagination -> ``list[Tool]``."""
        return await self._collect(self.list_tools, "tools")

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None, **kwargs):
        """``tools/call`` -> ``CallToolResult`` (check ``.is_error``; tool failures are not raised)."""
        return await self._call(self.sdk.call_tool, name, arguments or {}, **kwargs)

    async def list_prompts(self, cursor: Optional[str] = None, **kwargs):
        return await self._call(self.sdk.list_prompts, cursor=cursor, **kwargs)

    async def list_all_prompts(self) -> List[Any]:
        return await self._collect(self.list_prompts, "prompts")

    async def get_prompt(self, name: str, arguments: Optional[Dict[str, str]] = None, **kwargs):
        """``prompts/get`` -> ``GetPromptResult``. Argument values must be strings per the MCP spec."""
        args = {k: v if isinstance(v, str) else str(v) for k, v in (arguments or {}).items()}
        return await self._call(self.sdk.get_prompt, name, args, **kwargs)

    async def list_resources(self, cursor: Optional[str] = None, **kwargs):
        return await self._call(self.sdk.list_resources, cursor=cursor, **kwargs)

    async def list_all_resources(self) -> List[Any]:
        return await self._collect(self.list_resources, "resources")

    async def list_resource_templates(self, cursor: Optional[str] = None, **kwargs):
        return await self._call(self.sdk.list_resource_templates, cursor=cursor, **kwargs)

    async def read_resource(self, uri: str, **kwargs):
        return await self._call(self.sdk.read_resource, uri, **kwargs)

    async def complete(self, ref, argument: Dict[str, str], **kwargs):
        return await self._call(self.sdk.complete, ref, argument, **kwargs)

    async def _collect(self, page_fn: Callable, attr: str, max_pages: int = 1000) -> List[Any]:
        items: List[Any] = []
        cursor = None
        for _ in range(max_pages):
            page = await page_fn(cursor=cursor)
            items.extend(getattr(page, attr))
            cursor = page.next_cursor
            if not cursor:
                break
        return items

    # ── SAJHA extras (zero-dependency clients, same config + auth) ──

    @property
    def auth(self) -> AuthProvider:
        return self._auth

    @property
    def rest(self) -> "SajhaClient":
        """SAJHA REST client: health, tool schemas, usage reports/metrics, admin. Blocking (urllib)."""
        if self._rest is None:
            from sajhaclient.client import SajhaClient
            self._rest = SajhaClient(self.config, auth=self._auth)
        return self._rest

    @property
    def a2a(self) -> "A2AClient":
        """SAJHA A2A (Agent-to-Agent) client. Blocking (urllib)."""
        if self._a2a is None:
            from sajhaclient.a2a_client import A2AClient
            self._a2a = A2AClient(self.config, auth=self._auth)
        return self._a2a

    def websocket(self) -> "MCPWebSocketClient":
        """A new (unconnected) SAJHA MCP-over-WebSocket client; call ``.connect()`` on it.

        Requires ``pip install websockets``. WebSocket is a SAJHA extension, not a
        standard MCP transport.
        """
        from sajhaclient.mcp_client import MCPWebSocketClient
        return MCPWebSocketClient(self.config, auth=self._auth)

    async def _rest_call(self, fn: Callable, *args, **kwargs):
        import anyio
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))

    async def health(self) -> Dict:
        """``GET /health`` (REST, run off the event loop)."""
        return await self._rest_call(self.rest.health)

    async def tool_schema(self, tool_name: str) -> Dict:
        """``GET /api/tools/{name}/schema`` (REST)."""
        return await self._rest_call(self.rest.get_tool_schema, tool_name)

    async def tool_metrics(self, tool_name: str, period: str = "30d") -> Dict:
        """``GET /api/reports/tools/{name}/detail`` — latency percentiles, errors (REST)."""
        return await self._rest_call(self.rest.report_tool_detail, tool_name, period)

    async def tools_usage(self, period: str = "7d") -> Dict:
        """``GET /api/reports/tools/usage`` (REST)."""
        return await self._rest_call(self.rest.report_tools_usage, period)

    def __repr__(self) -> str:
        state = f"MCP {self._sdk.protocol_version}" if self._sdk else "disconnected"
        return f"<SajhaMCPClient {self.mcp_url} auth={self._auth.auth_type} {state}>"


class SajhaMCPSyncClient:
    """
    Blocking facade over :class:`SajhaMCPClient`.

    Runs the async client on a private event loop in a background thread
    (``anyio.from_thread.start_blocking_portal``). Takes the same arguments
    as :class:`SajhaMCPClient` and exposes the same methods, synchronously::

        with SajhaMCPSyncClient("http://localhost:3002", api_key="sja_xxx") as c:
            print(c.negotiated_protocol_version)
            print([t.name for t in c.list_all_tools()])
    """

    _ASYNC_METHODS = (
        "list_tools", "list_all_tools", "call_tool",
        "list_prompts", "list_all_prompts", "get_prompt",
        "list_resources", "list_all_resources", "list_resource_templates", "read_resource",
        "complete", "health", "tool_schema", "tool_metrics", "tools_usage",
    )

    def __init__(self, base_url: Optional[str] = None, **kwargs: Any):
        self._async = SajhaMCPClient(base_url, **kwargs)
        self._portal_cm = None
        self._portal = None
        self._session_cm = None

    def connect(self) -> "SajhaMCPSyncClient":
        if self._portal is not None:
            return self
        from anyio.from_thread import start_blocking_portal
        self._portal_cm = start_blocking_portal()
        self._portal = self._portal_cm.__enter__()
        try:
            # The SDK's task group must be entered and exited in the same task, so
            # the async context is held open by a dedicated portal task.
            self._session_cm = self._portal.wrap_async_context_manager(self._async)
            self._session_cm.__enter__()
        except BaseException:
            self._session_cm = None
            self._stop_portal()
            raise
        return self

    def close(self) -> None:
        if self._portal is None:
            return
        try:
            if self._session_cm is not None:
                self._session_cm.__exit__(None, None, None)
        finally:
            self._session_cm = None
            self._stop_portal()

    def _stop_portal(self) -> None:
        cm, self._portal_cm, self._portal = self._portal_cm, None, None
        if cm is not None:
            cm.__exit__(None, None, None)

    def __enter__(self) -> "SajhaMCPSyncClient":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in SajhaMCPSyncClient._ASYNC_METHODS:
            coro_fn = getattr(self._async, name)

            def blocking(*args, **kwargs):
                if self._portal is None:
                    raise RuntimeError("SajhaMCPSyncClient is not connected; use 'with' or call connect()")
                return self._portal.call(lambda: coro_fn(*args, **kwargs))

            blocking.__name__ = name
            blocking.__doc__ = coro_fn.__doc__
            return blocking
        # Properties and sync extras (negotiated_protocol_version, server_info, rest, a2a, websocket, sdk, ...)
        return getattr(self._async, name)

    def __repr__(self) -> str:
        return repr(self._async).replace("SajhaMCPClient", "SajhaMCPSyncClient", 1)
