"""
SAJHA MCP Server — the MCP stdio transport.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A desktop client (Claude Desktop, Claude Code, an IDE) launches SAJHA as a
subprocess and talks MCP over its stdin/stdout:

    sajha serve --stdio [--user admin | --api-key sja_...]
    python run_server.py --stdio [...]
    python -m sajha.cli.stdio [...]

Transport rules (MCP basic/transports, "stdio"):

* messages are newline-delimited JSON-RPC, UTF-8, one object per line, no
  embedded newlines;
* stdout carries nothing but MCP messages: at start-up file descriptor 1 is
  re-pointed at stderr, so a stray ``print`` (or a C extension writing to fd 1)
  can never corrupt the stream; the protocol writes to a private duplicate of
  the original stdout;
* logs go to stderr only;
* the server exits when stdin closes.

Both protocol eras are served with the same handlers as ``POST /mcp``:

* **2026-07-28** (stateless): a request whose ``params._meta`` carries
  ``io.modelcontextprotocol/protocolVersion`` goes to
  :class:`sajha.core.mcp_modern.ModernMCPServer`.  A client in ``auto`` mode
  probes with ``server/discover`` and stays modern when it succeeds.  stdio has
  no HTTP headers, so the routing headers that the HTTP validation ladder
  cross-checks (``MCP-Protocol-Version``, ``Mcp-Method``, ``Mcp-Name``,
  ``Mcp-Param-*``) are derived from the body itself: on stdio the body is the
  only source of truth.  Streamed responses (``subscriptions/listen``, a
  ``tools/call`` with a progressToken or logLevel) are written as consecutive
  lines: notifications first, then the response.
* **2025-11-25 and earlier**: ``initialize`` then requests, served by
  :class:`sajha.core.mcp_handler.MCPHandler`; the connection is the session.
  The initialize result advertises ``listChanged`` because stdio is a push
  channel: tool / prompt / resource list changes arrive as notifications.

``notifications/cancelled`` cancels the named in-flight request (both eras);
no response is sent for a cancelled request.

Identity: one caller per process, fixed at start-up and mapped through the same
access control as every other transport (``sajha/auth/access.py``):

* ``--api-key`` / ``SAJHA_API_KEY``: the API key's tool access list;
* ``--user`` / ``SAJHA_STDIO_USER``: a SAJHA user's roles (no password: whoever
  can start this process can already read the database it opens);
* neither: the anonymous policy (``mcp.anonymous.*``; by default no tools).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger('sajha.stdio')

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_ACCEPT = 'application/json, text/event-stream'


# ── stdout hygiene ───────────────────────────────────────────────

def claim_stdout():
    """
    Return a private binary writer on the original stdout and point fd 1 (and
    ``sys.stdout``) at stderr, so nothing but protocol messages reaches the client.
    """
    sys.stdout.flush()
    proto_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(proto_fd, 'wb', buffering=0)


def setup_logging(level: str = 'WARNING', log_file: Optional[str] = None):
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handlers = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    logging.basicConfig(
        level=getattr(logging, (level or 'WARNING').upper(), logging.WARNING),
        format='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
        handlers=handlers, force=True,
    )


# ── bootstrap: the subsystems MCP needs, nothing else ────────────

def bootstrap(with_ai: bool = False):
    """
    Initialise what serving MCP needs: database, storage, tool and prompt
    registries, composite tools and the MCP handler.  The web UI, templates,
    observability and (unless ``with_ai``) the LLM gateway are not loaded.
    Returns the :class:`MCPHandler`.
    """
    t0 = time.monotonic()
    from sajha.core.config import get_settings
    settings = get_settings()

    from sajha.db.engine import init_db, get_db_session
    init_db(settings)

    try:
        from sajha.core.properties_configurator import PropertiesConfigurator
        from sajha.core.storage import init_storage
        pc = PropertiesConfigurator(yaml_file=os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
        init_storage(pc)
    except Exception as e:
        logger.warning(f'storage init: {e}')

    from sajha.tools.tools_registry import get_tools_registry
    from sajha.core.prompts_registry import get_prompts_registry
    from sajha.core.mcp_handler import MCPHandler
    from sajha.auth.access import SessionToolAccess

    tools = get_tools_registry(tools_config_dir=settings.config_tools_dir, force_reinit=True)
    prompts = get_prompts_registry(prompts_config_dir=settings.config_prompts_dir, force_reinit=True)

    try:
        from sajha.tools.composite_tool import CompositeToolEngine
        db = get_db_session()
        try:
            CompositeToolEngine(tools).load_from_db(db)
        finally:
            db.close()
    except Exception as e:
        logger.info(f'composite tools: none loaded ({e})')

    if with_ai:
        try:
            from sajha.core.config import _CFG
            from sajha.ai.llm import init_llm_factory
            from sajha.ai.intelligence import init_intelligence
            from sajha.ai.ask_tool import register_if_enabled
            db = get_db_session()
            try:
                gw = init_llm_factory(_CFG, db_session=db)
            finally:
                db.close()
            if gw is not None:
                svc = init_intelligence(gw, tools)
                register_if_enabled(tools, svc.settings)
        except Exception as e:
            logger.warning(f'LLM factory unavailable on stdio: {e}')

    handler = MCPHandler(tools_registry=tools, auth_manager=SessionToolAccess(), prompts_registry=prompts)

    # Modules that look the registries up on sajha.app (async executor, help catalog)
    try:
        import sajha.app as app_module
        app_module.tools_registry, app_module.prompts_registry, app_module.mcp_handler = tools, prompts, handler
    except Exception as e:
        logger.debug(f'sajha.app globals not set: {e}')

    logger.info(f'stdio bootstrap: {len(tools.tools)} tools, {len(prompts.prompts)} prompts '
                f'in {time.monotonic() - t0:.2f}s')
    return handler


class IdentityError(Exception):
    pass


def resolve_identity(user: Optional[str] = None, api_key: Optional[str] = None) -> Dict[str, Any]:
    """The MCP session dict (identity + tool policy) for this stdio process."""
    from sajha.auth import AuthContext, AuthManager
    from sajha.auth.access import mcp_session_for, anonymous_enabled
    from sajha.db.engine import get_db_session

    if user and api_key:
        raise IdentityError('give --user or --api-key, not both')
    db = get_db_session()
    try:
        if api_key:
            auth = AuthManager.authenticate_apikey(db, api_key)
            if auth is None:
                raise IdentityError('API key is invalid, expired or disabled')
            return auth.to_legacy_session()
        if user:
            from sajha.db.dao import UserDAO
            u = UserDAO(db).get_by_user_id(user)
            if u is None or not u.enabled:
                raise IdentityError(f'no enabled SAJHA user {user!r}')
            auth = AuthContext(authenticated=True, user_id=u.user_id, user_name=u.user_name,
                               roles=u.role_names, auth_type='stdio', is_admin=u.is_admin, _user=u, _db=db)
            return auth.to_legacy_session()
        if not anonymous_enabled():
            raise IdentityError('no identity given and mcp.anonymous.enabled is false: '
                                'pass --user or --api-key')
        return mcp_session_for(None)
    finally:
        db.close()


# ── header synthesis for the modern path ─────────────────────────

def _b64(value: str) -> str:
    return '=?base64?' + base64.b64encode(value.encode('utf-8')).decode('ascii') + '?='


def synthesize_headers(body: Dict[str, Any], input_schema_for) -> list:
    """
    The routing headers an HTTP client would send for this body.  On stdio the
    body is authoritative, so these always agree with it and the HTTP-only
    header checks pass by construction; the body-level checks (``_meta``
    fields, protocol version, method surface) still apply.
    """
    from sajha.core import mcp_modern as mm
    params = body.get('params') if isinstance(body.get('params'), dict) else {}
    meta = params.get('_meta') if isinstance(params.get('_meta'), dict) else {}
    headers = [('accept', _ACCEPT), ('content-type', 'application/json')]
    version = meta.get(mm.PROTOCOL_VERSION_META_KEY)
    if isinstance(version, str):
        headers.append((mm.PROTOCOL_VERSION_HEADER, version))
    method = body.get('method')
    if isinstance(method, str):
        headers.append((mm.METHOD_HEADER, method))
        name_key = mm.NAME_BEARING_METHODS.get(method)
        if name_key is not None and isinstance(params.get(name_key), str):
            headers.append((mm.NAME_HEADER, _b64(params[name_key])))
        if method == 'tools/call' and isinstance(params.get('name'), str) \
                and isinstance(params.get('arguments') or {}, dict):
            schema = input_schema_for(params['name'])
            if schema is not None:
                args = params.get('arguments') or {}
                for path, token, _prop in mm._annotated_properties(schema):
                    value = mm._value_at(args, path)
                    rendered = mm._render_scalar(value) if value is not None else None
                    if rendered is not None:
                        headers.append((f'mcp-param-{token}'.lower(), _b64(rendered)))
    return headers


class _HeaderView(dict):
    """Case-insensitive ``headers.get`` over the synthesized list."""

    def __init__(self, pairs):
        super().__init__((k.lower(), v) for k, v in pairs)

    def get(self, key, default=None):
        return super().get(key.lower(), default)


# ── the transport ────────────────────────────────────────────────

class StdioServer:
    """One MCP connection over a pair of byte streams."""

    def __init__(self, handler, session_data: Dict[str, Any], out):
        from sajha.core.mcp_modern import ModernMCPServer
        self.handler = handler
        self.modern = ModernMCPServer(handler)
        self.session_data = session_data
        self.out = out
        self._write_lock = threading.Lock()
        self.inflight: Dict[Any, asyncio.Task] = {}
        self.cancelled: set = set()
        self.legacy_session = None
        self._forwarder: Optional[asyncio.Task] = None
        self._cancel_scope = f'stdio:{id(self)}'      # mcp_cancellation scope of this connection

    # -- output ----------------------------------------------------

    def send(self, message: Any):
        line = json.dumps(message, separators=(',', ':'), default=str, ensure_ascii=False)
        data = (line.replace('\n', '\\n') + '\n').encode('utf-8')
        with self._write_lock:
            try:
                self.out.write(data)
                self.out.flush()
            except (BrokenPipeError, ValueError, OSError):
                pass

    def _respond(self, rid, message):
        """Send a response unless its request was cancelled."""
        if rid in self.cancelled:
            self.cancelled.discard(rid)
            return
        if message is not None:
            self.send(message)

    # -- input -----------------------------------------------------

    async def serve(self, reader):
        """``reader`` yields raw lines (bytes); returns at EOF."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def pump():
            try:
                for raw in iter(reader.readline, b''):
                    loop.call_soon_threadsafe(queue.put_nowait, raw)
            except Exception as e:
                logger.debug(f'stdin reader stopped: {e}')
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=pump, name='stdio-reader', daemon=True).start()
        try:
            while True:
                raw = await queue.get()
                if raw is None:
                    break
                line = raw.strip()
                if not line:
                    continue
                self.dispatch(line)
        finally:
            await self.shutdown()

    async def shutdown(self, grace: float = 30.0):
        # stdin closed: let requests already read finish (bounded), then stop
        running = [t for t in self.inflight.values() if not t.done()]
        if running:
            await asyncio.wait(running, timeout=grace)
        for task in list(self.inflight.values()):
            task.cancel()
        if self._forwarder is not None:
            self._forwarder.cancel()
        pending = [t for t in list(self.inflight.values()) + [self._forwarder] if t is not None]
        if pending:
            await asyncio.wait(pending, timeout=2)

    def dispatch(self, line: bytes):
        try:
            body = json.loads(line)
        except (ValueError, RecursionError):
            self.send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}})
            return
        if isinstance(body, list):
            self.send({'jsonrpc': '2.0', 'id': None, 'error': {
                'code': -32600, 'message': 'Invalid Request: JSON-RPC batches are not supported'}})
            return
        if not isinstance(body, dict):
            self.send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid Request'}})
            return

        method = body.get('method')
        # A response from the client (to a server -> client request)
        if method is None and 'id' in body and ('result' in body or 'error' in body):
            from sajha.core.mcp_sessions import get_session_store
            if not get_session_store().resolve_response(self.legacy_session, body):
                logger.debug(f"unmatched client response id={body.get('id')!r}")
            return

        if method == 'notifications/cancelled':
            params = body.get('params') if isinstance(body.get('params'), dict) else {}
            self.cancel(params.get('requestId'), params.get('reason'))
            return

        from sajha.core.mcp_modern import is_modern_request
        if is_modern_request(body, {}):
            coro = self.handle_modern(body)
        else:
            coro = self.handle_legacy(body)
        rid = body.get('id') if 'id' in body else None
        task = asyncio.ensure_future(coro)
        if rid is not None and isinstance(rid, (str, int)) and not isinstance(rid, bool):
            self.inflight[rid] = task
            task.add_done_callback(lambda _t, r=rid: self.inflight.pop(r, None))

    def cancel(self, rid, reason=None):
        task = self.inflight.get(rid)
        if task is None or task.done():
            return            # unknown or finished: ignore (spec: MAY ignore)
        logger.info(f'request {rid!r} cancelled by client' + (f': {reason}' if reason else ''))
        self.cancelled.add(rid)
        from sajha.core import mcp_cancellation
        mcp_cancellation.cancel(self._cancel_scope, rid, reason)   # the worker thread sees it too
        task.cancel()

    # -- 2026-07-28 -----------------------------------------------

    async def handle_modern(self, body: Dict[str, Any]):
        from sajha.core.mcp_modern import ModernStream
        from sajha.policy.context import set_source
        set_source('stdio')          # this request's task context only (policy sources: [stdio])
        rid = body.get('id')
        pairs = synthesize_headers(body, self.modern._tool_input_schema)
        headers = _HeaderView(pairs)
        cancelled = asyncio.Event()

        async def receive():
            await cancelled.wait()
            return {'type': 'http.disconnect'}

        try:
            outcome = await self.modern.handle(body, headers, pairs, self.session_data, receive=receive)
            if isinstance(outcome, ModernStream):
                agen = outcome.events()
                try:
                    async for event in agen:
                        data = event.get('data')
                        if data:
                            message = json.loads(data)
                            if 'method' in message:
                                self.send(message)
                            else:
                                self._respond(rid, message)
                finally:
                    await agen.aclose()
                return
            _status, payload = outcome
            if payload is not None and 'id' in body:
                self._respond(rid, payload)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        except Exception as e:
            logger.error(f'stdio modern request failed: {e}', exc_info=True)
            if 'id' in body:
                self._respond(rid, {'jsonrpc': '2.0', 'id': rid,
                                    'error': {'code': -32603, 'message': 'Internal server error'}})

    # -- 2025-11-25 and earlier -----------------------------------

    async def handle_legacy(self, body: Dict[str, Any]):
        from sajha.core.mcp_modern import _run_in_thread
        from sajha.policy.context import set_source
        set_source('stdio')
        from sajha.routes.mcp_routes import with_push_capabilities
        method = body.get('method')
        params = body.get('params') if isinstance(body.get('params'), dict) else {}
        is_request = 'id' in body
        rid = body.get('id')
        try:
            if method == 'tools/call' and is_request:
                from sajha.core.mcp_conformance_fixtures import get_conformance_fixtures
                fixtures = get_conformance_fixtures()
                if fixtures and fixtures.is_async_tool(params.get('name', '')):
                    await self._fixture_call(rid, params, fixtures)
                    return

            if method == 'tools/call' and is_request:
                from sajha.core import mcp_cancellation
                with mcp_cancellation.track(self._cancel_scope, rid):
                    response = await _run_in_thread(self.handler.handle_request, body, self.session_data)
            else:
                response = await _run_in_thread(self.handler.handle_request, body, self.session_data)
            if not is_request:
                return
            if method == 'initialize' and isinstance(response, dict) and 'result' in response:
                from sajha.core.mcp_sessions import get_session_store
                self.legacy_session = get_session_store().create(
                    protocol_version=response['result'].get('protocolVersion'),
                    client_info=params.get('clientInfo') or {},
                    client_capabilities=params.get('capabilities') or {},
                    user_id=self.session_data.get('user_id'),
                )
                response = with_push_capabilities(response)
                # the WebSocket endpoint is an HTTP-server feature, not reachable from here
                sajha_caps = ((response['result'].get('capabilities') or {}).get('experimental') or {}).get('sajha')
                if isinstance(sajha_caps, dict):
                    sajha_caps.pop('websocket', None)
                self._start_forwarder()
            self._respond(rid, response)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f'stdio request {method} failed: {e}', exc_info=True)
            if is_request:
                self._respond(rid, {'jsonrpc': '2.0', 'id': rid,
                                    'error': {'code': -32603, 'message': 'Internal server error'}})

    async def _fixture_call(self, rid, params, fixtures):
        """A tool that talks to the client while it runs (progress, logging, sampling, elicitation)."""
        from sajha.core.mcp_sessions import ToolCallContext
        queue: asyncio.Queue = asyncio.Queue()
        meta = params.get('_meta') or {}
        ctx = ToolCallContext(self.legacy_session, queue, meta.get('progressToken'))
        task = asyncio.ensure_future(fixtures.call_tool_async(params.get('name', ''), params.get('arguments') or {}, ctx))
        try:
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    self.send(getter.result())
                    continue
                getter.cancel()
                while not queue.empty():
                    self.send(queue.get_nowait())
                self._respond(rid, {'jsonrpc': '2.0', 'id': rid, 'result': task.result()})
                return
        finally:
            if not task.done():
                task.cancel()

    def _start_forwarder(self):
        if self._forwarder is not None:
            return

        async def forward():
            from sajha.core.change_bus import get_change_bus, TOOLS, PROMPTS, RESOURCES
            sub = get_change_bus().subscribe({TOOLS, PROMPTS, RESOURCES})
            try:
                while True:
                    event = await sub.get()
                    if event is None:
                        return
                    self.send(event.notification())
            finally:
                sub.close()

        self._forwarder = asyncio.ensure_future(forward())


# ── entry point ──────────────────────────────────────────────────

def build_parser(parser: Optional[argparse.ArgumentParser] = None) -> argparse.ArgumentParser:
    p = parser or argparse.ArgumentParser(
        prog='sajha serve --stdio', description='Serve MCP over stdin/stdout (for desktop MCP clients).')
    p.add_argument('--user', default=None,
                   help='act as this SAJHA user (roles decide the tools); env SAJHA_STDIO_USER')
    p.add_argument('--api-key', dest='api_key', default=None,
                   help='act as this API key (its tool access list); env SAJHA_API_KEY')
    p.add_argument('--config', default=None, help='YAML config file (default config/application.yml)')
    p.add_argument('--root', default=None, help='SAJHA checkout to serve from (default: this one); env SAJHA_HOME')
    p.add_argument('--log-level', default=None, help='stderr log level (default WARNING); env SAJHA_STDIO_LOG_LEVEL')
    p.add_argument('--log-file', default=None, help='also log to this file')
    p.add_argument('--with-ai', action='store_true',
                   help='also start the LLM gateway (registers sajha_ask when ai.ask.mcp_tool_enabled is on)')
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return run(args)


def run(args) -> int:
    out = claim_stdout()
    setup_logging(args.log_level or os.environ.get('SAJHA_STDIO_LOG_LEVEL') or 'WARNING', args.log_file)

    root = Path(args.root or os.environ.get('SAJHA_HOME') or PROJECT_ROOT).resolve()
    if not (root / 'sajha').is_dir():
        print(f'sajha stdio: {root} is not a SAJHA checkout', file=sys.stderr)
        return 2
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)
    if args.config:
        os.environ['SAJHA_CONFIG_FILE'] = args.config
    for d in ('logs', 'data', 'temp'):
        os.makedirs(d, exist_ok=True)

    try:
        handler = bootstrap(with_ai=args.with_ai)
        session = resolve_identity(args.user or os.environ.get('SAJHA_STDIO_USER') or None,
                                   args.api_key or os.environ.get('SAJHA_API_KEY') or None)
    except IdentityError as e:
        print(f'sajha stdio: {e}', file=sys.stderr)
        return 2
    except Exception as e:
        logger.error(f'stdio start-up failed: {e}', exc_info=True)
        return 1

    logger.warning(f"SAJHA MCP over stdio ready (identity: {session.get('user_id')})")
    server = StdioServer(handler, session, out)
    try:
        asyncio.run(server.serve(sys.stdin.buffer))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            from sajha.core.change_bus import get_change_bus
            get_change_bus().shutdown()
        except Exception:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
