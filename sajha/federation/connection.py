"""
SAJHA MCP Server — one upstream MCP server, through the official ``mcp`` SDK v2 ``Client``.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

An ``UpstreamConnection`` lives on the federation manager's event loop. Its runner task
opens the SDK client (Streamable HTTP on either protocol era, legacy SSE or stdio, a stdio upstream in
its own container unless ``isolation: none``: sajha/federation/container.py), keeps
it open, and reconnects with backoff when it fails. While connected it

* runs discovery when asked (start, periodic refresh, list_changed, admin Refresh), and
* listens for list changes: ``subscriptions/listen`` on a 2026-07-28 upstream,
  ``notifications/*/list_changed`` on a 2025-11-25 session.

It also keeps the upstream subscribed to the resources SAJHA's clients watch (``set_watched``:
``resources/subscribe`` on a session, ``resourceSubscriptions`` on the listen stream) and passes
resource updates on. Calls are made from other tasks on the same loop (``call_tool``,
``call_tool_relayed``, ``get_prompt``, ``read_resource``, ``complete``); a task answer is followed
to its end (sajha/federation/tasks.py), and a session-based upstream's requests to its client go to
the relay of the call, if any (sajha/federation/relay.py). A transport failure marks the connection
lost so the runner reopens it.
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


class UpstreamNotConnected(UpstreamUnavailable):
    """The connection was not open when the call came: nothing was sent, so another pool member
    or replica may take the call whatever the tool does."""


class UpstreamTimeout(TimeoutError):
    """The upstream did not answer within the timeout."""


class UpstreamUnauthorized(RuntimeError):
    """The upstream refused a per-user credential (HTTP 401, or 403 for a personal token).
    ``vendor``: the start of the vendor's own answer, already redacted."""

    def __init__(self, message: str, status: int = 401, vendor: str = ''):
        super().__init__(message)
        self.status = status
        self.vendor = vendor


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
        self.needs_sign_in = False          # HTTP 401 with no credential configured: it wants auth.type oauth_user
        self.waiting_for_user = False       # token_user without a discovery credential and nobody connected yet
        self.user_session = False           # a per-user session (token_user): a refused token ends it for good
        self.refused: Optional[UpstreamUnauthorized] = None
        self._last_status: Optional[int] = None
        self._last_refusal = ''             # the start of the vendor's 401/403 body (redacted)
        self._client = None
        self._secret_values: List[str] = []
        self._ready = asyncio.Event()
        self._lost = asyncio.Event()
        self._stop = asyncio.Event()
        self._refresh = asyncio.Event()
        self._refresh_done: List[asyncio.Future] = []
        self._task: Optional[asyncio.Task] = None
        self._fatal = asyncio.Event()       # user sessions: the vendor refused the token
        self._wake = asyncio.Event()        # kick(): try again now instead of after the backoff
        self._down = asyncio.Event()        # the last connection attempt (or session) ended: waiting for the backoff
        # resources/subscribe carried through (Federation.md section 4): the upstream URIs SAJHA's
        # clients watch, and what to call when the upstream says one changed
        self.watched: set = set()
        self._subscribed: set = set()       # what a session-based upstream was sent resources/subscribe for
        self._watch_changed = asyncio.Event()
        self.on_resource_updated: Optional[Callable[[str], None]] = None
        self.relay = None                   # a ClientRelay (sajha/federation/relay.py): this call's caller
        # gateway scale (sajha/federation/scale.py): 'primary' runs discovery and change listening;
        # 'pool' members (more connections, other replicas) only carry calls
        self.role = 'primary'
        self.replica = 0                    # index in the upstream's replica_urls
        self.slot = 0                       # index in that replica's pool
        self.in_flight = 0
        self.ewma_ms: Optional[float] = None
        self.fail_streak = 0
        # stdio (sajha/federation/container.py): 'container' or 'none' once launched, and this connection's container
        self.isolation: Optional[str] = None
        self.container_name: Optional[str] = None

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

    def kick(self) -> None:
        """Reconnect now (a user just connected: discovery can use their token)."""
        self._wake.set()
        self._lost.set()

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
            self._down.clear()
            self._last_status = None
            try:
                # The connect deadline is a cancel scope around the whole session (the SDK's task
                # groups must be entered and exited inside one scope); lifted once connected.
                with anyio.CancelScope(deadline=anyio.current_time() + self._connect_timeout()) as scope:
                    async with AsyncExitStack() as stack:
                        client = await self._open(stack)
                        scope.deadline = math.inf
                        self._client = client
                        self.state = 'connected'
                        if self.needs_sign_in:
                            self.needs_sign_in = False
                            try:
                                from sajha import notices
                                notices.clear_notice(f'federation.sign_in:{self.config.id}')
                            except Exception:
                                pass
                        self.connected_at = time.time()
                        self.waiting_for_user = False
                        self._wake.clear()
                        self.last_error = None
                        backoff = 1.0
                        self._lost.clear()
                        self._ready.set()
                        logger.info(f'federation: upstream {self.config.id} connected '
                                    f'(MCP {self.protocol_version})')
                        tasks = []
                        self._subscribed = set()
                        if self.role == 'primary':                   # pool members only carry calls
                            tasks.append(asyncio.ensure_future(self._refresher()))
                            if self._is_modern():
                                tasks.append(asyncio.ensure_future(self._listener(client)))
                            else:
                                tasks.append(asyncio.ensure_future(self._subscriber(client)))
                            self._refresh.set()                      # discover now
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
                status = self._last_status if self._last_status in (401, 403) else (401 if is_unauthorized(e) else None)
                if self.user_session and status:
                    from sajha.federation.security import redact
                    self.refused = UpstreamUnauthorized(f'upstream {self.config.id} refused the user token '
                                                        f'(HTTP {status})', status,
                                                        redact(self._last_refusal, self._secret_values))
                    self._fatal.set()
                    self._fail_waiters()
                    break
                if status == 401 and self._per_user_mode() and not self._secret_values:
                    self.waiting_for_user = True
                    self.last_error = ('waiting for the first user to connect: this server signs each user in with '
                                       'their own token, and has no discovery credential (auth.discovery); tools '
                                       'appear once a user connects')
                    backoff = BACKOFF_MAX_SECONDS
                elif (is_unauthorized(e) or self._last_status == 401) and not self._has_credential():
                    if not self.needs_sign_in:
                        self._sign_in_notice()
                    self.needs_sign_in = True
                    self.last_error = ('needs sign-in: the server answered HTTP 401 and asks for per-user OAuth '
                                       'sign-in (MCP authorization); set "auth": "oauth_user" on it so each user '
                                       'signs in on Server connections, or give it a static credential (a header)')
                    backoff = BACKOFF_MAX_SECONDS
                logger.warning(f'federation: upstream {self.config.id}: {self.last_error}')
            finally:
                self._fail_waiters()
            if self._stop.is_set():
                break
            self.state = ('needs_sign_in' if self.needs_sign_in
                          else 'waiting_for_user' if self.waiting_for_user else 'error')
            self._down.set()                 # callers waiting for this attempt fail now, not after their wait
            try:
                await asyncio.wait_for(_first(self._stop.wait(), self._wake.wait()), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            if self._wake.is_set():
                self._wake.clear()
                backoff = 1.0
                continue
            backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)
        self.state = 'disabled'

    def _per_user_mode(self) -> bool:
        return (self.config.auth or {}).get('type') in ('token_user', 'oauth_user')

    def _has_credential(self) -> bool:
        a = (self.config.auth or {}).get('type', 'none') or 'none'
        if a in ('token_user', 'oauth_user'):
            return bool(self._secret_values)
        return a not in ('none', 'static') or any(k.lower() in ('authorization', 'x-api-key', 'api-key')
                                  for k in (self.config.headers or {}))

    def _sign_in_notice(self) -> None:
        try:
            from sajha import notices
            notices.raise_notice(f'federation.sign_in:{self.config.id}', severity='warning', source='federation',
                                 title=f'Upstream {self.config.id} needs sign-in',
                                 detail=f'{self.config.url} answered HTTP 401: it uses per-user OAuth sign-in '
                                        f'(MCP authorization with discovery). Set auth.type oauth_user on it so '
                                        f'each user signs in on Server connections, give it a static credential '
                                        f'header, or remove it.', ttl_minutes=0)
        except Exception as e:
            logger.debug(f'federation: sign-in notice for {self.config.id}: {e}')

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
            # its own container unless isolation: none (sajha/federation/container.py); docker is asked off the loop
            target = await asyncio.to_thread(self._stdio_params)
            if self.container_name:
                from sajha.federation.container import aremove
                stack.push_async_callback(aremove, self.container_name)    # after the client closes
        else:
            from sajha.federation.security import check_url
            check_url(cfg.url, self.settings)
            target = await self._http_transport(stack, timeout, connect_timeout)
            if cfg.transport == 'sse':
                mode = 'legacy'
        # requests from a session-based upstream to its client: relayed to SAJHA's caller when a relay is
        # bound for this call (sajha/federation/relay.py), else answered with a clear error
        extra: Dict[str, Any] = {}
        if self.relay is not None:
            from sajha.federation.relay import ROOTS, SAMPLING
            if self.relay.supports(SAMPLING):
                extra['sampling_callback'] = self._on_sampling
            if self.relay.supports(ROOTS):
                extra['list_roots_callback'] = self._on_roots
        if not self.user_session:          # upstream tasks on the shared connection (sajha/federation/tasks.py)
            from sajha.federation.tasks import TasksExtension
            extra['extensions'] = [TasksExtension()]
        client = Client(
            target, mode=mode, read_timeout_seconds=timeout, cache=None,
            client_info=Implementation(name='sajha-federation', version=str(get_settings().app_version)),
            message_handler=self._on_message, elicitation_callback=self._on_elicitation, **extra,
        )
        await stack.enter_async_context(client)
        if self.container_name:                     # a container that ends ends the connection at once
            from sajha.federation.container import watch
            watcher = asyncio.ensure_future(watch(self, self.container_name))
            stack.callback(watcher.cancel)
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
        async def seen(response):              # the SDK hides an HTTP 401 behind a generic MCP error
            self._last_status = response.status_code
            if response.status_code in (401, 403):
                try:                           # the vendor's own answer, for the user (redacted later)
                    await response.aread()
                    self._last_refusal = (response.text or '')[:300]
                except Exception:
                    self._last_refusal = ''
        http = httpx2.AsyncClient(headers=headers, auth=auth, follow_redirects=False, trust_env=False,
                                  timeout=httpx2.Timeout(connect_timeout, read=max(timeout, 300.0)),
                                  event_hooks={'response': [seen]})
        stack.push_async_callback(http.aclose)
        return streamable_http_client(cfg.url, http_client=http)

    def _stdio_params(self):
        from sajha.federation.container import stdio_target
        from sajha.federation.security import resolve_ref
        cfg = self.config
        env = dict(cfg.env or {})
        for name, ref in (cfg.env_refs or {}).items():
            env[name] = resolve_ref(ref, f'upstream {cfg.id} env_refs.{name}')
            self._secret_values.append(env[name])
        return stdio_target(self, env)       # a container launch, or the plain command with isolation: none

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
                if self.waiting_for_user:
                    self.waiting_for_user = False
                    self.state = 'connected'
            except asyncio.CancelledError:
                raise
            except Exception as e:
                why = describe(e)
                if self._per_user_mode() and not self._secret_values and self._last_status in (401, 403):
                    # a stateless upstream opens without a request: the first refusal comes here
                    self.waiting_for_user = True
                    self.state = 'waiting_for_user'
                    self.last_error = ('waiting for the first user to connect: this server signs each user in with '
                                       'their own token, and has no discovery credential (auth.discovery); tools '
                                       'appear once a user connects')
                    for f in waiters:
                        if not f.done():
                            f.set_exception(UpstreamUnavailable(self.last_error))
                    continue
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
        """A 2026-07-28 upstream's ``subscriptions/listen`` stream: list changes trigger a refresh;
        ``resourceSubscriptions`` carry the URIs SAJHA's clients watch, and the stream is reopened
        when that set changes."""
        from mcp.client.subscriptions import ResourceUpdated
        caps = self.capabilities or {}
        want = dict(tools_list_changed=bool((caps.get('tools') or {}).get('listChanged')),
                    prompts_list_changed=bool(self.config.expose_prompts and (caps.get('prompts') or {}).get('listChanged')),
                    resources_list_changed=bool(self.config.expose_resources and (caps.get('resources') or {}).get('listChanged')))
        delay = 1.0
        while True:
            self._watch_changed.clear()
            uris = sorted(self.watched)
            if not any(want.values()) and not uris:
                await self._watch_changed.wait()
                continue
            restart = False
            try:
                async with client.listen(**want, resource_subscriptions=uris) as sub:
                    self.listening = True
                    delay = 1.0
                    it = sub.__aiter__()
                    while True:
                        nxt = asyncio.ensure_future(it.__anext__())
                        changed = asyncio.ensure_future(self._watch_changed.wait())
                        try:
                            await asyncio.wait({nxt, changed}, return_when=asyncio.FIRST_COMPLETED)
                        finally:
                            changed.cancel()
                            if not nxt.done():
                                nxt.cancel()
                                await asyncio.gather(nxt, return_exceptions=True)
                        if not nxt.done() or nxt.cancelled():
                            restart = True              # the watched set changed: reopen with it
                            break
                        try:
                            event = nxt.result()
                        except StopAsyncIteration:
                            break
                        if isinstance(event, ResourceUpdated):
                            self._resource_updated(event.uri)
                        else:
                            self._refresh.set()
                self.listening = False
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.listening = False
                logger.debug(f'federation: listen stream on {self.config.id} ended: {describe(e)}')
            if restart:
                continue
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX_SECONDS)
            self._refresh.set()                 # no replay on a new stream: refetch

    async def _subscriber(self, client) -> None:
        """A session-based upstream: keep ``resources/subscribe`` in step with the watched set."""
        while True:
            self._watch_changed.clear()
            want, have = set(self.watched), set(self._subscribed)
            for uri in sorted(want - have):
                try:
                    await client.subscribe_resource(uri)
                    self._subscribed.add(uri)
                except Exception as e:
                    logger.warning(f'federation: resources/subscribe {uri} on {self.config.id}: {describe(e)}')
            for uri in sorted(have - want):
                self._subscribed.discard(uri)
                try:
                    await client.unsubscribe_resource(uri)
                except Exception as e:
                    logger.debug(f'federation: resources/unsubscribe {uri} on {self.config.id}: {describe(e)}')
            await self._watch_changed.wait()

    def set_watched(self, uris) -> None:
        """The upstream URIs SAJHA's clients subscribe to now (called on the federation loop)."""
        uris = set(uris or ())
        if uris != self.watched:
            self.watched = uris
            self._watch_changed.set()

    def _resource_updated(self, uri: Any) -> None:
        cb = self.on_resource_updated
        if cb is not None and isinstance(uri, str) and uri:
            try:
                cb(uri)
            except Exception as e:
                logger.debug(f'federation: resource update {uri} from {self.config.id}: {e}')

    async def _on_message(self, message) -> None:
        """Legacy-era notifications on the session: a list change triggers a refresh; a resource
        update is passed to SAJHA's subscribed clients."""
        root = getattr(message, 'root', message)
        method = getattr(root, 'method', '') or ''
        if isinstance(method, str) and method.endswith('/list_changed'):
            self._refresh.set()
        elif method == 'notifications/resources/updated':
            params = getattr(root, 'params', None)
            self._resource_updated(getattr(params, 'uri', None) if params is not None else None)

    # ── requests from the upstream to its client (sajha/federation/relay.py) ──
    async def _relay(self, method: str, params: Any):
        """Send a 2025-11-25 upstream's request on to SAJHA's caller, or refuse it with a clear error."""
        from mcp_types import ErrorData
        from sajha.federation.relay import refusal
        body = params.model_dump(mode='json', by_alias=True, exclude_none=True) if params is not None else {}
        body.pop('_meta', None)
        relay = self.relay
        if relay is None or not relay.supports(method, body):
            logger.info(f'federation: {self.config.id} asked for {method}; not relayed')
            return ErrorData(code=-32600, message=refusal(self.config.id, method, relay is not None))
        try:
            return await relay.request(method, body)
        except Exception as e:
            return ErrorData(code=-32603, message=f'SAJHA\'s caller did not answer {method}: {e}'[:500])

    async def _on_elicitation(self, context, params):
        from mcp_types import ElicitResult
        out = await self._relay('elicitation/create', params)
        return out if not isinstance(out, dict) else ElicitResult.model_validate(out)

    async def _on_sampling(self, context, params):
        from mcp_types import CreateMessageResult, CreateMessageResultWithTools
        out = await self._relay('sampling/createMessage', params)
        if not isinstance(out, dict):
            return out
        try:
            return CreateMessageResult.model_validate(out)
        except Exception:
            return CreateMessageResultWithTools.model_validate(out)

    async def _on_roots(self, context):
        from mcp_types import ListRootsResult
        out = await self._relay('roots/list', None)
        return out if not isinstance(out, dict) else ListRootsResult.model_validate(out)

    # ── operations (called on the loop from other tasks) ───────────
    async def ready_client(self, wait: float):
        """The connected client. While a connection attempt is in progress, wait for it (at most ``wait``
        seconds); when the last attempt failed and the next one waits for its backoff, fail at once: a
        call to an upstream that is down fails fast (Federation.md section 8), and enough of them open
        the breaker promptly."""
        if self._client is not None and self._ready.is_set():
            return self._client
        if self.refused is not None:
            raise self.refused
        if self._stop.is_set():
            raise UpstreamUnavailable(f'upstream {self.config.id} is stopped')
        if self._down.is_set():
            raise UpstreamNotConnected(f'upstream {self.config.id} is not connected'
                                       + (f' ({self.last_error})' if self.last_error else ''))
        try:
            await asyncio.wait_for(_first(self._ready.wait(), self._fatal.wait(), self._down.wait()),
                                   timeout=max(0.0, wait))
            if self.refused is not None:
                raise self.refused
            if not self._ready.is_set():
                raise asyncio.TimeoutError()
        except asyncio.TimeoutError:
            raise UpstreamNotConnected(f'upstream {self.config.id} is not connected'
                                      + (f' ({self.last_error})' if self.last_error else ''))
        if self._client is None:
            raise UpstreamNotConnected(f'upstream {self.config.id} is not connected')
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
        """Every page of tools/list, prompts/list, resources/list or resources/templates/list
        (``kind`` ``resource_templates``)."""
        client = await self.ready_client(min(timeout, 5.0))
        fn = {'tools': client.list_tools, 'prompts': client.list_prompts, 'resources': client.list_resources,
              'resource_templates': client.list_resource_templates}[kind]
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
                        request_state: Optional[str] = None, meta: Optional[Dict[str, Any]] = None):
        """``meta``: request ``_meta`` (the caller's W3C ``traceparent``, captured on the calling
        thread because this coroutine runs on the federation loop)."""
        client = await self.ready_client(min(timeout, 5.0))
        responses = _input_responses(input_responses) if input_responses else None

        async def call():
            return await _call_following_tasks(client.session, name, arguments, timeout, progress, responses,
                                               request_state, meta)
        return await self._guarded(call, timeout, f'tools/call {name}')

    async def call_tool_relayed(self, relay, name: str, arguments: Dict[str, Any], timeout: float,
                                progress: Optional[Callable] = None, meta: Optional[Dict[str, Any]] = None):
        """One tools/call on a session-based upstream, on a connection opened for this call (with
        the shared credentials) whose server-to-client requests go to ``relay``, the calling
        client: the only way to know which caller such a request is for."""
        async def _no_discovery(_conn):
            return None
        eph = UpstreamConnection(self.config, self.settings, _no_discovery, refresh_seconds=0)
        eph.relay = relay

        async def call():
            try:
                async with AsyncExitStack() as stack:
                    client = await eph._open(stack)
                    return await _call_following_tasks(client.session, name, arguments, timeout, progress, None,
                                                       None, meta)
            except BaseExceptionGroup as group:         # the connection's task group wraps the upstream's answer
                leaves = [e for e in _leaves(group) if not isinstance(e, asyncio.CancelledError)]
                if len(leaves) == 1 and isinstance(leaves[0], Exception) and not is_transport_error(leaves[0]):
                    raise leaves[0] from None
                raise
        return await eph._guarded(call, timeout, f'tools/call {name}')

    async def complete(self, ref: Dict[str, Any], argument: Dict[str, str], context_arguments: Optional[Dict],
                       timeout: float):
        """completion/complete for one of the upstream's prompts or resource templates."""
        from mcp_types import PromptReference, ResourceTemplateReference
        client = await self.ready_client(min(timeout, 5.0))
        r = (PromptReference(type='ref/prompt', name=ref['name']) if ref.get('type') == 'ref/prompt'
             else ResourceTemplateReference(type='ref/resource', uri=ref['uri']))
        return await self._guarded(lambda: client.complete(r, argument, context_arguments or None), timeout,
                                   'completion/complete')

    async def call_tool_as(self, bearer: str, name: str, arguments: Dict[str, Any], timeout: float,
                           progress: Optional[Callable] = None, input_responses: Optional[Dict] = None,
                           request_state: Optional[str] = None, meta: Optional[Dict[str, Any]] = None):
        """One tools/call presenting ``bearer`` (the calling user's connected-account token) on a
        connection opened for this call and closed after it, so no user's token is ever on the
        shared connection or reused for another user. Raises UpstreamUnauthorized on HTTP 401."""
        return await self.call_tool_with_header('Authorization', f'Bearer {bearer}', name, arguments, timeout,
                                                progress, input_responses, request_state, meta, refuse_403=False)

    async def call_tool_with_header(self, header: str, value: str, name: str, arguments: Dict[str, Any],
                                    timeout: float, progress: Optional[Callable] = None,
                                    input_responses: Optional[Dict] = None, request_state: Optional[str] = None,
                                    meta: Optional[Dict[str, Any]] = None, refuse_403: bool = True,
                                    inner=None):
        """One tools/call carrying ``header: value`` (one user's credential) on a connection opened
        for this call and closed after it: on a 2026-07-28 upstream that is the credential riding on
        the request, with no per-user state kept. Raises UpstreamUnauthorized on HTTP 401 (and 403
        when ``refuse_403``). ``inner``: the shared service credential sent with the header
        (auth.type service_with_user)."""
        eph = self.user_connection(header, value, inner)
        responses = _input_responses(input_responses) if input_responses else None

        async def call():
            try:
                async with AsyncExitStack() as stack:
                    client = await eph._open(stack)
                    return await client.session.call_tool(
                        name, arguments, read_timeout_seconds=timeout, progress_callback=progress,
                        input_responses=responses, request_state=request_state, allow_input_required=True,
                        meta=meta or None)
            except Exception as e:
                refused = eph.refusal(e, refuse_403)
                if refused is not None:
                    raise refused from None
                raise
        return await eph._guarded(call, timeout, f'tools/call {name}')

    async def list_tools_with_header(self, header: str, value: str, timeout: float) -> List[Any]:
        """tools/list (every page) as one user, on a connection of its own (the connect page's test
        call and the per-user part of discovery). Raises UpstreamUnauthorized on 401/403."""
        eph = self.user_connection(header, value)

        async def listing():
            try:
                async with AsyncExitStack() as stack:
                    client = await eph._open(stack)
                    items: List[Any] = []
                    cursor = None
                    for _ in range(100):
                        page = await client.list_tools(cursor=cursor)
                        items.extend(page.tools or [])
                        cursor = page.next_cursor
                        if not cursor:
                            break
                    return items
            except Exception as e:
                refused = eph.refusal(e, True)
                if refused is not None:
                    raise refused from None
                raise
        return await eph._guarded(listing, timeout, 'tools/list')

    def user_connection(self, header: str, value: str, inner=None) -> 'UpstreamConnection':
        """An unstarted connection to this upstream presenting one user's credential (or, with
        ``inner``, the shared service credential plus the header naming the user)."""
        from sajha.federation.auth import OnBehalfAuth, StaticHeaderAuth

        async def _no_discovery(_conn):
            return None
        c = UpstreamConnection(self.config, self.settings, _no_discovery, refresh_seconds=0)
        c._auth_override = OnBehalfAuth(inner, header, value) if inner is not None else StaticHeaderAuth(header, value)
        c.user_session = True
        return c

    def refusal(self, exc: BaseException, refuse_403: bool = True) -> Optional[UpstreamUnauthorized]:
        """UpstreamUnauthorized when ``exc`` (or the last HTTP status seen) is the vendor refusing the
        credential, else None."""
        from sajha.federation.security import redact
        status = self._last_status if self._last_status in ((401, 403) if refuse_403 else (401,)) else None
        if status is None and is_unauthorized(exc):
            status = 401
        if status is None:
            return None
        return UpstreamUnauthorized(f'upstream {self.config.id} refused the user token (HTTP {status})', status,
                                    redact(self._last_refusal, self._secret_values))

    async def get_prompt(self, name: str, arguments: Dict[str, str], timeout: float):
        client = await self.ready_client(min(timeout, 5.0))
        return await self._guarded(lambda: client.get_prompt(name, arguments), timeout, f'prompts/get {name}')

    async def read_resource(self, uri: str, timeout: float):
        client = await self.ready_client(min(timeout, 5.0))
        return await self._guarded(lambda: client.read_resource(uri), timeout, 'resources/read')

    def secret_values(self) -> List[str]:
        return list(self._secret_values)


async def _call_following_tasks(session, name, arguments, timeout, progress, responses, request_state, meta):
    """tools/call; a task answer (the upstream supports the tasks extension) is followed to its end."""
    from sajha.federation.tasks import CreateTaskResult, follow
    result = await session.call_tool(
        name, arguments, read_timeout_seconds=timeout, progress_callback=progress,
        input_responses=responses, request_state=request_state, allow_input_required=True,
        allow_claimed=True, meta=meta or None)
    if isinstance(result, CreateTaskResult):
        return await follow(session, result, timeout)
    return result


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
