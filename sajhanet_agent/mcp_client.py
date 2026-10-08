"""
A small MCP client for the server the agent fronts: stdio (newline-delimited JSON-RPC to a child
process) or Streamable HTTP (JSON or SSE answers, ``Mcp-Session-Id``), on the 2025-11-25
``initialize`` handshake that every MCP server speaks. Only what the agent needs: ``tools/list``
(with pagination) and ``tools/call``; the server's own requests are answered (``ping``) or declined.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import shlex
import subprocess
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = '2025-11-25'
CLIENT_INFO = {'name': 'sajhanet-agent', 'version': '1'}


class MCPError(Exception):
    """The server answered with a JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.data = data


class MCPUnavailable(Exception):
    """The server could not be reached. ``sent``: the request may have reached it."""

    def __init__(self, message: str, sent: bool = False):
        super().__init__(message)
        self.sent = sent


class MCPClient:
    """The two calls the agent makes; subclasses provide :meth:`request`."""

    def __init__(self):
        self.on_tools_changed: Optional[Callable[[], None]] = None
        self._ids = itertools.count(1)
        self._initialized = False
        self._init_lock = threading.Lock()

    def request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Any:
        raise NotImplementedError

    def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def ensure_initialized(self, timeout: float = 30.0) -> None:
        with self._init_lock:
            if self._initialized:
                return
            self._raw_request('initialize', {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
                                             'clientInfo': CLIENT_INFO}, timeout)
            self.notify('notifications/initialized')
            self._initialized = True

    def _raw_request(self, method, params, timeout):
        return self.request(method, params, timeout)

    def list_tools(self, timeout: float = 30.0) -> List[Dict[str, Any]]:
        self.ensure_initialized(timeout)
        tools: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(100):
            res = self.request('tools/list', {'cursor': cursor} if cursor else {}, timeout) or {}
            tools.extend(t for t in res.get('tools') or [] if isinstance(t, dict) and t.get('name'))
            cursor = res.get('nextCursor')
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: Dict[str, Any], timeout: float = 60.0) -> Dict[str, Any]:
        self.ensure_initialized(timeout)
        res = self.request('tools/call', {'name': name, 'arguments': arguments or {}}, timeout)
        return res if isinstance(res, dict) else {'content': [{'type': 'text', 'text': json.dumps(res)}]}

    def _server_request(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Answer a request the server sends us: ``ping``; everything else is declined."""
        if msg.get('method') == 'ping':
            return {'jsonrpc': '2.0', 'id': msg.get('id'), 'result': {}}
        return {'jsonrpc': '2.0', 'id': msg.get('id'),
                'error': {'code': -32601, 'message': 'the SAJHA Net agent does not serve this request'}}

    def _notification(self, msg: Dict[str, Any]) -> None:
        if msg.get('method') == 'notifications/tools/list_changed' and self.on_tools_changed is not None:
            try:
                self.on_tools_changed()
            except Exception as e:
                logger.debug(f'tools changed callback: {e}')


def _result(msg: Dict[str, Any]) -> Any:
    if 'error' in msg and msg['error'] is not None:
        e = msg['error'] if isinstance(msg['error'], dict) else {}
        raise MCPError(int(e.get('code') or -32603), str(e.get('message') or 'error'), e.get('data'))
    return msg.get('result')


class StdioMCPClient(MCPClient):
    """A child process speaking MCP on stdin and stdout; restarted when it has exited."""

    def __init__(self, command: Any, env: Optional[Dict[str, str]] = None, cwd: Optional[str] = None):
        super().__init__()
        self.argv = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.argv:
            raise ValueError('an MCP command is needed')
        self.env = env
        self.cwd = cwd
        self.proc: Optional[subprocess.Popen] = None
        self._pending: Dict[Any, Dict[str, Any]] = {}
        self._cond = threading.Condition()
        self._write = threading.Lock()

    def _start(self) -> None:
        env = dict(os.environ)
        env.update(self.env or {})
        self.proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
                                     cwd=self.cwd, env=env, bufsize=0)
        self._initialized = False
        threading.Thread(target=self._reader, args=(self.proc,), name='mcp-stdio-reader', daemon=True).start()

    def _alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _reader(self, proc) -> None:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode('utf-8'))
            except ValueError:
                logger.debug(f'MCP stdio: not JSON: {line[:200]!r}')
                continue
            if not isinstance(msg, dict):
                continue
            if 'method' in msg and 'id' in msg:
                self._send(self._server_request(msg))
            elif 'method' in msg:
                self._notification(msg)
            else:
                with self._cond:
                    self._pending[msg.get('id')] = msg
                    self._cond.notify_all()
        with self._cond:
            self._cond.notify_all()

    def _send(self, msg: Dict[str, Any]) -> None:
        data = (json.dumps(msg, separators=(',', ':')) + '\n').encode('utf-8')
        with self._write:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    def notify(self, method, params=None):
        msg = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            msg['params'] = params
        try:
            self._send(msg)
        except (OSError, ValueError, AttributeError) as e:
            raise MCPUnavailable(f'the MCP server is not running: {e}')

    def request(self, method, params=None, timeout=30.0):
        if not self._alive():
            if method != 'initialize':
                self._start()
                self.ensure_initialized(timeout)
            else:
                self._start()
        rid = next(self._ids)
        msg = {'jsonrpc': '2.0', 'id': rid, 'method': method}
        if params is not None:
            msg['params'] = params
        try:
            self._send(msg)
        except (OSError, ValueError) as e:
            raise MCPUnavailable(f'the MCP server is not running: {e}')
        with self._cond:
            ok = self._cond.wait_for(lambda: rid in self._pending or not self._alive(), timeout)
            reply = self._pending.pop(rid, None)
        if reply is None:
            raise MCPUnavailable('the MCP server did not answer' if ok else 'the MCP server timed out', sent=True)
        return _result(reply)

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()


class HttpMCPClient(MCPClient):
    """Streamable HTTP: one POST per message; the answer is JSON or an SSE stream."""

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None, verify_tls: bool = True):
        super().__init__()
        import httpx
        self.url = url
        self.headers = dict(headers or {})
        self.session_id: Optional[str] = None
        self.client = httpx.Client(timeout=60.0, verify=verify_tls, follow_redirects=False)

    def _post(self, msg: Dict[str, Any], timeout: float):
        import httpx
        h = {'content-type': 'application/json', 'accept': 'application/json, text/event-stream', **self.headers}
        if self._initialized or msg.get('method') not in ('initialize',):
            h['mcp-protocol-version'] = PROTOCOL_VERSION
        if self.session_id:
            h['mcp-session-id'] = self.session_id
        try:
            r = self.client.post(self.url, content=json.dumps(msg).encode('utf-8'), headers=h, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise MCPUnavailable(f'the MCP server is unreachable: {e}', sent=False)
        except httpx.HTTPError as e:
            raise MCPUnavailable(f'the MCP server did not answer: {e}', sent=True)
        sid = r.headers.get('mcp-session-id')
        if sid:
            self.session_id = sid
        return r

    def _answer(self, r, rid) -> Optional[Dict[str, Any]]:
        ctype = r.headers.get('content-type', '').split(';')[0].strip().lower()
        if ctype == 'text/event-stream':
            for block in r.text.split('\n\n'):
                data = '\n'.join(line[5:].lstrip() for line in block.splitlines() if line.startswith('data:'))
                if not data:
                    continue
                try:
                    msg = json.loads(data)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get('id') == rid and 'method' not in msg:
                    return msg
                if isinstance(msg, dict) and 'method' in msg and 'id' not in msg:
                    self._notification(msg)
            return None
        try:
            msg = r.json()
        except ValueError:
            return None
        return msg if isinstance(msg, dict) else None

    def notify(self, method, params=None):
        msg = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            msg['params'] = params
        self._post(msg, 30.0)

    def request(self, method, params=None, timeout=30.0):
        for attempt in (1, 2):
            rid = next(self._ids)
            msg = {'jsonrpc': '2.0', 'id': rid, 'method': method}
            if params is not None:
                msg['params'] = params
            r = self._post(msg, timeout)
            if r.status_code == 404 and self.session_id and attempt == 1 and method != 'initialize':
                self.session_id = None                   # the session expired: start a new one
                self._initialized = False
                self.ensure_initialized(timeout)
                continue
            if r.status_code >= 400 and 'json' not in r.headers.get('content-type', ''):
                raise MCPUnavailable(f'the MCP server answered HTTP {r.status_code}', sent=r.status_code >= 500)
            reply = self._answer(r, rid)
            if reply is None:
                raise MCPUnavailable('the MCP server sent no answer to the request', sent=True)
            return _result(reply)
        raise MCPUnavailable('the MCP session could not be renewed', sent=False)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass


class CallableMCPClient(MCPClient):
    """An MCP server in this process: ``handler(message) -> answer`` (tests, embedding)."""

    def __init__(self, handler: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]):
        super().__init__()
        self.handler = handler

    def notify(self, method, params=None):
        self.handler({'jsonrpc': '2.0', 'method': method, **({'params': params} if params is not None else {})})

    def request(self, method, params=None, timeout=30.0):
        rid = next(self._ids)
        msg = {'jsonrpc': '2.0', 'id': rid, 'method': method}
        if params is not None:
            msg['params'] = params
        try:
            reply = self.handler(msg)
        except ConnectionError as e:
            raise MCPUnavailable(str(e), sent=False)
        if not isinstance(reply, dict):
            raise MCPUnavailable('no answer', sent=True)
        return _result(reply)
