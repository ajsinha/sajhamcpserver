# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
sajha: call this SAJHA server from the Python Playground.

This module runs inside Pyodide, in a Web Worker in your browser. It reaches the server
with ordinary same-origin HTTP requests carrying your signed-in session, so every call is
checked by the server exactly as if you had made it from the Tools page: the tools you
may not use are refused there, and the usual API limits apply.

    import sajha
    sajha.tools()                          # the tools you may call: [{name, description, ...}]
    sajha.schema("calc_future_value")      # one tool's input schema
    sajha.call("calc_future_value", present_value=1000, rate=5, years=10)
    sajha.ask("What is the percentage change from 80 to 100?")

Calls are synchronous (a blocking request is allowed in a worker), so no ``await``.
A refused or failed call raises ``sajha.ToolError``.

Served by the server at /api/playground/sajha.py (source: sajha/web/playground_assets/sajha_bridge.py).
"""

import json as _json
import sys as _sys
import types as _types

__all__ = ['tools', 'schema', 'call', 'ask', 'ToolError', 'server']

#: Per-request timeout (seconds) on the browser side; the server applies its own limits too.
TIMEOUT_S = 120


class ToolError(Exception):
    """A tool call the server refused or that failed. ``status`` is the HTTP status."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def _request(method, path, payload=None):
    from js import XMLHttpRequest  # the worker's global: same origin, session cookie included
    xhr = XMLHttpRequest.new()
    xhr.open(method, path, False)  # synchronous: allowed in a Web Worker
    xhr.timeout = TIMEOUT_S * 1000
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.setRequestHeader('X-SAJHA-Client', 'playground')  # policy rules can match sources: [playground]
    body = None
    if payload is not None:
        xhr.setRequestHeader('Content-Type', 'application/json')
        body = _json.dumps(payload)
    try:
        xhr.send(body)
    except Exception as e:  # network error, timeout
        raise ToolError(f'{method} {path}: request failed ({e})') from None
    text = str(xhr.responseText or '')
    try:
        data = _json.loads(text) if text else None
    except ValueError:
        data = None
    status = int(xhr.status)
    if status == 401:
        raise ToolError('not signed in (your session may have expired; reload the page)', status, data)
    if status >= 400 or status == 0:
        msg = (data or {}).get('error') if isinstance(data, dict) else None
        raise ToolError(msg or f'{method} {path}: HTTP {status}', status, data)
    return data


_tool_cache = None


def tools(refresh=False):
    """The tools you may call, as the server decides: a list of {name, description, category}."""
    global _tool_cache
    if _tool_cache is None or refresh:
        _tool_cache = _request('GET', '/api/playground/tools')['tools']
    return [dict(t) for t in _tool_cache]


def schema(name):
    """A tool's MCP description, including its inputSchema."""
    return _request('GET', f'/api/tools/{name}/schema')


def call(name, arguments=None, **kwargs):
    """Run a tool on the server with your permissions; returns its result (parsed JSON).

    ``sajha.call("calc_future_value", present_value=1000, rate=5, years=10)`` or, for an
    argument whose name is not a Python identifier, ``sajha.call(name, {"a-b": 1})``."""
    args = dict(arguments or {})
    args.update(kwargs)
    data = _request('POST', '/api/tools/execute', {'tool': name, 'arguments': args})
    if not isinstance(data, dict) or not data.get('success'):
        raise ToolError((data or {}).get('error') or f'{name} failed', None, data)
    return data.get('result')


def ask(question, model=None):
    """Ask SAJHA (POST /api/ai/ask): returns the answer dict (answer, steps, citations, confidence)."""
    payload = {'question': str(question)}
    if model:
        payload['model'] = model
    return _request('POST', '/api/ai/ask', payload)


def server():
    """Where these calls go: this page's origin."""
    from js import location
    return str(location.origin)


# ``from sajha.studio import sajhamcptool``: MCP Studio's decorator, so a Python code tool
# opened from Studio runs here unchanged. In the playground it only records its metadata.
_studio = _types.ModuleType('sajha.studio')


def _sajhamcptool(description='', category='General', tags=None, **meta):
    def wrap(fn):
        fn.__sajha_tool__ = dict(meta, description=description, category=category, tags=list(tags or []))
        return fn
    return wrap


_studio.sajhamcptool = _sajhamcptool
_studio.__doc__ = 'Playground stand-in for sajha.studio: @sajhamcptool records metadata only.'
studio = _studio
_sys.modules['sajha.studio'] = _studio
