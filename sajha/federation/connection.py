"""
SAJHA MCP Server — one upstream MCP server, through the official ``mcp`` SDK v2 ``Client``.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

An ``UpstreamConnection`` lives on the federation manager's event loop. Its runner task
opens the SDK client (Streamable HTTP on either protocol era, legacy SSE or stdio), keeps
it open, and reconnects with backoff when it fails. While connected it

* runs discovery when asked (start, periodic refresh, list_changed, admin Refresh), and
* listens for list changes: ``subscriptions/listen`` on a 2026-07-28 upstream,
  ``notifications/*/list_changed`` on a 2025-11-25 session.

Calls are made from other tasks on the same loop (``call_tool``, ``get_prompt``,
``read_resource``); a transport failure marks the connection lost so the runner reopens it.
Design: docs/architecture/Federation.md.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time

import anyio
from contextlib import AsyncExitStack
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

BACKOFF_MAX_SECONDS = 60.0


class UpstreamUnavailable(RuntimeError):
    """The upstream cannot be reached (not connected, connection lost, refused)."""


class UpstreamTimeout(TimeoutError):
    """The upstream did not answer within the timeout."""


class UpstreamUnauthorized(RuntimeError):
    """The upstream answered HTTP 401 to a per-user (connected-account) call."""


def is_unauthorized(exc: BaseException) -> bool:
    """An HTTP 401 from the upstream anywhere in the exception (group)."""
    for e in _leaves(exc):
        resp = getattr(e, 'response', None)
        if getattr(resp, 'status_code', None) == 401:
            return True
        if '401' in str(e) and 'nauthorized' in str(e):
            return True
    return False


def is_transport_error(exc: BaseException) -> bool:
    """A failure of the connection rather than an answer from the upstream."""
    import anyio
    import httpx2
    from mcp.shared.exceptions import MCPError
    from mcp_types.jsonrpc import CONNECTION_CLOSED
    leaves = list(_leaves(exc))
    for e in leaves:
        if isinstance(e, MCPError):
            if e.code == CONNECTION_CLOSED:
                return True
            continue
        if isinstance(e, (httpx2.TransportError, OSError, ConnectionError, UpstreamUnavailable,
                          anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream)):
            return True
    return False


def _leaves(exc: BaseException):
    subs = getattr(exc, 'exceptions', None)
    if subs:
        for s in subs:
            yield from _leaves(s)
    else:
        yield exc


def describe(exc: BaseException) -> str:
    """A short, redacted description of a failure (innermost exceptions of a group)."""
    from sajha.federation.security import redact
    parts = []
    for e in _leaves(exc):
        text = str(e) or e.__class__.__name__
        code = getattr(e, 'code', None)
        msg = f'{e.__class__.__name__}: {text}' if code is None else f'MCP error {code}: {getattr(e, "message", text)}'
        if msg not in parts:
            parts.append(msg)
    return redact('; '.join(parts))[:500]


class UpstreamConnection:
    def __init__(self, config, settings, on_discover: Callable[['UpstreamConnection'], Awaitable[None]],
                 refresh_seconds: Optional[float] = None):
        self.config = config
        self.settings = settings
        self._on_discover = on_discover
        self.refresh_seconds = refresh_seconds if refresh_seconds is not None else settings.refresh_interval_seconds
        self.state = 'connecting'
        self.protocol_version: Optional[str] = None
        self.server_info: Dict[str, Any] = {}
        self.capabilities: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self.connected_at: Optional[float] = None
        self.listening = False
        self._client = None
        self._secret_values: List[str] = []
        self._ready = asyncio.Event()
        self._lost = asyncio.Event()
        self._stop = asyncio.Event()
        self._refresh = asyncio.Event()
        self._refresh_done: List[asyncio.Future] = []
        self._task: Optional[asyncio.Task] = None

    # ── lifecycle ──────────────────────────────────────────────────
    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._lost.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()
        self.state = 'disabled'

    def mark_lost(self, why: str = '') -> None:
        if why:
            self.last_error = why
        self._lost.set()

    async def request_refresh(self, wait: bool = False, timeout: float = 30.0) -> None:
        """Ask the runner for a discovery now; optionally wait until it ran."""
        fut = asyncio.get_running_loop().create_future() if wait else None
        if fut is not None:
            self._refresh_done.append(fut)
        self._refresh.set()
        if fut is not None:
            await asyncio.wait_for(fut, timeout)

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self.state = 'connecting'
            try:
                # The connect deadline is a cancel scope around the whole session (the SDK's task
                # groups must be entered and exited inside one scope); lifted once connected.
                with anyio.CancelScope(deadline=anyio.current_time() + self._connect_timeout()) as scope:
                    async with AsyncExitStack() as stack:
                        client = await self._open(stack)
                        scope.deadline = math.inf
                        self._client = client
                        self.state = 'connected'
                        self.connected_at = time.time()
                        self.last_error = None
                        backoff = 1.0
                        self._lost.clear()
                        self._ready.set()
                        logger.info(f'federation: upstream {self.config.id} connected '
                                    f'(MCP {self.protocol_version})')
                        tasks = [asyncio.ensure_future(self._refresher())]
                        if self._is_modern():
                            tasks.append(asyncio.ensure_future(self._listener(client)))
                        self._refresh.set()                          # discover now
                        try:
                            await _first(self._stop.wait(), self._lost.wait())
                        finally:
                            self._ready.clear()
                            self._client = None
                            self.listening = False
                            for t in tasks:
                                t.cancel()
                            await asyncio.gather(*tasks, return_exceptions=True)
                if scope.cancelled_caught and not self._stop.is_set():
                    raise TimeoutError(f'no connection within {self._connect_timeout():g}s')
            except asyncio.CancelledError:
                if self._stop.is_set():
                    break
                raise
            except Exception as e:
                self.last_error = describe(e)
                logger.warning(f'federation: upstream {self.config.id}: {self.last_error}')
            finally:
                self._fail_waiters()
            if self._stop.is_set():
                break
            self.state = 'error'
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)
        self.state = 'disabled'

    def _connect_timeout(self) -> float:
        return min(float(self.config.timeout_seconds or self.settings.default_timeout_seconds), 30.0)

    def _fail_waiters(self) -> None:
        waiters, self._refresh_done = self._refresh_done, []
        for f in waiters:
            if not f.done():
                f.set_exception(UpstreamUnavailable(self.last_error or f'upstream {self.config.id} disconnected'))

    async def _open(self, stack: AsyncExitStack):
        """Build the transport and the SDK client, and complete the handshake / discovery."""
        from mcp import Client
        from mcp_types import Implementation
        from sajha.core.config import get_settings

        cfg = self.config
        timeout = float(cfg.timeout_seconds or self.settings.default_timeout_seconds)
        connect_timeout = min(timeout, 30.0)
        mode = {'auto': 'auto', 'legacy': 'legacy'}.get(cfg.protocol, cfg.protocol)
        if cfg.transport == 'stdio':
            if not self.settings.allow_stdio:
                raise PermissionError('stdio upstreams are disabled (federation.allow_stdio)')
            target = self._stdio_params()
        else:
            from sajha.federation.security import check_url
            check_url(cfg.url, self.settings)
            target = await self._http_transport(stack, timeout, connect_timeout)
            if cfg.transport == 'sse':
                mode = 'legacy'
        client = Client(
            target, mode=mode, read_timeout_seconds=timeout, cache=None,
            client_info=Implementation(name='sajha-federation', version=str(get_settings().app_version)),
            message_handler=self._on_message, elicitation_callback=self._decline_elicitation,
        )
        await stack.enter_async_context(client)
        self.protocol_version = client.protocol_version
        info = client.server_info
        self.server_info = info.model_dump(mode='json', exclude_none=True) if info is not None else {}
        caps = client.server_capabilities
        self.capabilities = caps.model_dump(mode='json', by_alias=True, exclude_none=True) if caps is not None else {}
        return client

    async def _http_transport(self, stack: AsyncExitStack, timeout: float, connect_timeout: float):
        import httpx2
        from sajha.core.config import get_settings
        from sajha.federation.auth import build_auth
        cfg = self.config
        override = getattr(self, '_auth_override', None)     # call_tool_as: the caller's own token
        auth = override if override is not None else build_auth(cfg, self.settings)
        self._secret_values = list(getattr(auth, 'secret_values', lambda: [])())
        headers = {'User-Agent': f'sajha-federation/{get_settings().app_version}', **(cfg.headers or {})}
        if cfg.transport == 'sse':
            from mcp.client.sse import sse_client
            return sse_client(cfg.url, headers=headers, timeout=connect_timeout,
                              sse_read_timeout=max(timeout, 300.0), auth=auth)
        from mcp.client.streamable_http import streamable_http_client
        http = httpx2.AsyncClient(headers=headers, auth=auth, follow_redirects=False, trust_env=False,
                                  timeout=httpx2.Timeout(connect_timeout, read=max(timeout, 300.0)))
        stack.push_async_callback(http.aclose)
        return streamable_http_client(cfg.url, http_client=http)

    def _stdio_params(self):
        from mcp.client.stdio import StdioServerParameters
        from sajha.federation.security import resolve_ref
        cfg = self.config
        env = dict(cfg.env or {})
        for name, ref in (cfg.env_refs or {}).items():
            env[name] = resolve_ref(ref, f'upstream {cfg.id} env_refs.{name}')
            self._secret_values.append(env[name])
        return StdioServerParameters(command=cfg.command, args=list(cfg.args or []), env=env or None,
                                     cwd=cfg.cwd or None)

    def _is_modern(self) -> bool:
        return bool(self.protocol_version) and self.protocol_version >= '2026-07-28'

    # ── change detection ───────────────────────────────────────────
    async def _refresher(self) -> None:
        interval = float(self.refresh_seconds or 0)
        while True:
            if interval > 0:
                try:
                    await asyncio.wait_for(self._refresh.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
            else:
                await self._refresh.wait()
            self._refresh.clear()
            waiters, self._refresh_done = self._refresh_done, []
            try:
                await self._on_discover(self)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                why = describe(e)
                logger.warning(f'federation: discovery on upstream {self.config.id} failed: {why}')
                for f in waiters:
                    if not f.done():
                        f.set_exception(UpstreamUnavailable(why))
                if is_transport_error(e):
                    self.mark_lost(why)
                    return
                continue
            for f in waiters:
                if not f.done():
                    f.set_result(None)

    async def _listener(self, client) -> None:
        caps = self.capabilities or {}
        want = dict(tools_list_changed=bool((caps.get('tools') or {}).get('listChanged')),
                    prompts_list_changed=bool(self.config.expose_prompts and (caps.get('prompts') or {}).get('listChanged')),
                    resources_list_changed=bool(self.config.expose_resources and (caps.get('resources') or {}).get('listChanged')))
        if not any(want.values()):
            return
        delay = 1.0
        while True:
            try:
                async with client.listen(**want) as sub:
                    self.listening = True
                    delay = 1.0
                    async for _event in sub:
                        self._refresh.set()
                self.listening = False
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.listening = False
                logger.debug(f'federation: listen stream on {self.config.id} ended: {describe(e)}')
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX_SECONDS)
            self._refresh.set()                 # no replay on a new stream: refetch

    async def _on_message(self, message) -> None:
        """Legacy-era notifications on the session: a list change triggers a refresh."""
        root = getattr(message, 'root', message)
        method = getattr(root, 'method', '') or ''
        if isinstance(method, str) and method.endswith('/list_changed'):
            self._refresh.set()

    @staticmethod
    async def _decline_elicitation(context, params):
        """A 2025-11-25 upstream asking SAJHA for input mid-call: SAJHA's caller is not on this
        connection to answer, so decline (2026-07-28 upstreams use MRTR, which is forwarded)."""
        from mcp_types import ElicitResult
        return ElicitResult(action='decline')

    # ── operations (called on the loop from other tasks) ───────────
    async def ready_client(self, wait: float):
        if self._client is not None and self._ready.is_set():
            return self._client
        if self._stop.is_set():
            raise UpstreamUnavailable(f'upstream {self.config.id} is stopped')
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=max(0.0, wait))
        except asyncio.TimeoutError:
            raise UpstreamUnavailable(f'upstream {self.config.id} is not connected'
                                      + (f' ({self.last_error})' if self.last_error else ''))
        if self._client is None:
            raise UpstreamUnavailable(f'upstream {self.config.id} is not connected')
        return self._client

    async def _guarded(self, coro_fn, timeout: float, what: str):
        # Not asyncio.wait_for: it waits for the cancelled request to wind down, which can take as
        # long as the upstream does; the caller is released at the deadline instead.
        task = asyncio.ensure_future(coro_fn())
        try:
            done, _ = await asyncio.wait({task}, timeout=timeout)
        except asyncio.CancelledError:
            task.cancel()
            raise
        if not done:
            task.cancel()
            task.add_done_callback(_consume)
            raise UpstreamTimeout(f'upstream {self.config.id} did not answer {what} within {timeout:g}s')
        try:
            return task.result()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if is_transport_error(e):
                why = describe(e)
                self.mark_lost(why)
                raise UpstreamUnavailable(f'upstream {self.config.id} connection failed: {why}') from None
            raise

    async def list_all(self, kind: str, timeout: float) -> List[Any]:
        """Every page of tools/list, prompts/list or resources/list."""
        client = await self.ready_client(min(timeout, 5.0))
        fn = {'tools': client.list_tools, 'prompts': client.list_prompts, 'resources': client.list_resources}[kind]
        items: List[Any] = []
        cursor = None
        for _ in range(100):
            page = await self._guarded(lambda: fn(cursor=cursor), timeout, f'{kind}/list')
            items.extend(getattr(page, kind) or [])
            cursor = page.next_cursor
            if not cursor:
                break
        return items

    async def call_tool(self, name: str, arguments: Dict[str, Any], timeout: float,
                        progress: Optional[Callable] = None, input_responses: Optional[Dict] = None,
                        request_state: Optional[str] = None):
        client = await self.ready_client(min(timeout, 5.0))
        responses = _input_responses(input_responses) if input_responses else None

        async def call():
            return await client.session.call_tool(
                name, arguments, read_timeout_seconds=timeout, progress_callback=progress,
                input_responses=responses, request_state=request_state, allow_input_required=True)
        return await self._guarded(call, timeout, f'tools/call {name}')

    async def call_tool_as(self, bearer: str, name: str, arguments: Dict[str, Any], timeout: float,
                           progress: Optional[Callable] = None, input_responses: Optional[Dict] = None,
                           request_state: Optional[str] = None):
        """One tools/call presenting ``bearer`` (the calling user's connected-account token) on a
        connection opened for this call and closed after it, so no user's token is ever on the
        shared connection or reused for another user. Raises UpstreamUnauthorized on HTTP 401."""
        from sajha.federation.auth import StaticHeaderAuth

        async def _no_discovery(_conn):
            return None
        eph = UpstreamConnection(self.config, self.settings, _no_discovery, refresh_seconds=0)
        eph._auth_override = StaticHeaderAuth('Authorization', f'Bearer {bearer}')
        responses = _input_responses(input_responses) if input_responses else None

        async def call():
            try:
                async with AsyncExitStack() as stack:
                    client = await eph._open(stack)
                    return await client.session.call_tool(
                        name, arguments, read_timeout_seconds=timeout, progress_callback=progress,
                        input_responses=responses, request_state=request_state, allow_input_required=True)
            except Exception as e:
                if is_unauthorized(e):
                    raise UpstreamUnauthorized(f'upstream {self.config.id} refused the user token (HTTP 401)') \
                        from None
                raise
        return await eph._guarded(call, timeout, f'tools/call {name}')

    async def get_prompt(self, name: str, arguments: Dict[str, str], timeout: float):
        client = await self.ready_client(min(timeout, 5.0))
        return await self._guarded(lambda: client.get_prompt(name, arguments), timeout, f'prompts/get {name}')

    async def read_resource(self, uri: str, timeout: float):
        client = await self.ready_client(min(timeout, 5.0))
        return await self._guarded(lambda: client.read_resource(uri), timeout, 'resources/read')

    def secret_values(self) -> List[str]:
        return list(self._secret_values)


def _consume(task: asyncio.Future) -> None:
    """Retrieve an abandoned task's outcome so asyncio does not log it as never retrieved."""
    if not task.cancelled():
        task.exception()


def _input_responses(raw: Dict[str, Any]) -> Dict[str, Any]:
    """MRTR inputResponses from SAJHA's caller (JSON) as the SDK's typed results."""
    from pydantic import TypeAdapter
    import mcp_types
    adapter = TypeAdapter(mcp_types.InputResponse)
    out = {}
    for key, value in (raw or {}).items():
        try:
            out[key] = adapter.validate_python(value)
        except Exception:
            out[key] = value
    return out


async def _first(*aws) -> None:
    tasks = [asyncio.ensure_future(a) for a in aws]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
