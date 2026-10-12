"""
SAJHA MCP Server — HTTP cassettes for the other transports tools use.

:mod:`sajha.quality.cassette` intercepts ``urllib.request``, ``requests`` and ``httpx``. This
module adds the transports found under ``sajha/tools/impl/`` and in the SDKs those tools call:

* ``urllib3`` (``HTTPConnectionPool.urlopen``): the transport under ``requests`` and under
  botocore, the AWS SDK's HTTP layer (``URLLib3Session``), so boto3 clients are recorded and
  replayed at the wire without a botocore-specific stub. A call made from inside another
  intercepted client (``requests`` sits on urllib3) is left to that client: one exchange is
  recorded once;
* ``aiohttp`` (``ClientSession._request``): what the OpenBB providers use;
* ``curl_cffi`` (``requests.Session.request`` and ``requests.AsyncSession.request``): what
  yfinance uses.

Each patch is installed only when its package imports, and behaves like the others: ``record``
performs the request and stores it, ``replay`` answers from the cassette and raises
``CassetteMiss`` for anything it does not hold (no network), ``live`` does nothing. Matching is on
method + URL (secret query parameters redacted) + SHA-256 of the body the caller gave, so a
request is matched the same way whichever client sent it.

Docs: docs/architecture/Tool Quality.md §2.3.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextlib
import io
import json as _json
import threading
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlencode

_DECODED_DROP = ('content-encoding', 'content-length', 'transfer-encoding')
_local = threading.local()


@contextlib.contextmanager
def outer() -> Iterator[None]:
    """Mark this thread as inside an intercepted client: nested transports pass through."""
    _local.depth = getattr(_local, 'depth', 0) + 1
    try:
        yield
    finally:
        _local.depth -= 1


def _nested() -> bool:
    return getattr(_local, 'depth', 0) > 0


def _decoded_headers(headers) -> Dict[str, str]:
    return {k: v for k, v in dict(headers).items() if k.lower() not in _DECODED_DROP}


def _form(data: Any) -> Any:
    """A body as the bytes a client would send for it (forms urlencoded, text UTF-8)."""
    if data is None or isinstance(data, (bytes, bytearray, str)):
        return data
    if isinstance(data, dict) or (isinstance(data, (list, tuple)) and all(isinstance(x, tuple) for x in data)):
        return urlencode(list(data.items()) if isinstance(data, dict) else list(data), doseq=True)
    return data


# ── urllib3 (requests, botocore) ────────────────────────────────────

def _pool_url(pool, url: str) -> str:
    if url.startswith(('http://', 'https://')):
        return url
    host = pool.host or ''
    if ':' in host and not host.startswith('['):
        host = f'[{host}]'
    default = 443 if pool.scheme == 'https' else 80
    port = f':{pool.port}' if pool.port and pool.port != default else ''
    return f'{pool.scheme}://{host}{port}{url}'


@contextlib.contextmanager
def _patch_urllib3(cassette):
    try:
        import urllib3
        from urllib3.connectionpool import HTTPConnectionPool
        from urllib3.response import HTTPResponse
    except ImportError:
        yield
        return
    from sajha.quality.cassette import _decode_body
    original = HTTPConnectionPool.urlopen

    def build(method, url, status, reason, headers, data, preload):
        return HTTPResponse(body=io.BytesIO(data), headers=urllib3.HTTPHeaderDict(headers), status=int(status),
                            reason=reason, preload_content=preload, decode_content=False,
                            request_method=method, request_url=url)

    def urlopen(self, method, url, body=None, headers=None, *args, **kwargs):
        if _nested():
            return original(self, method, url, body, headers, *args, **kwargs)
        full = _pool_url(self, url)
        preload = kwargs.get('preload_content', True)
        decode = kwargs.get('decode_content', True)
        if cassette.mode == 'replay':
            r = cassette._find(method, full, body)
            return build(method, full, r['status'], r.get('reason', ''), r['headers'], _decode_body(r['body']),
                         preload)
        with outer():
            resp = original(self, method, url, body, headers, *args, **kwargs)
        if preload:
            data = resp.data or b''
        else:
            data = resp.read(decode_content=decode)
            resp.release_conn()
        hdrs = _decoded_headers(resp.headers) if decode else dict(resp.headers)
        cassette._record(method, full, body, resp.status, resp.reason or '', hdrs, data)
        return build(method, full, resp.status, resp.reason or '', hdrs, data, preload)

    HTTPConnectionPool.urlopen = urlopen
    try:
        yield
    finally:
        HTTPConnectionPool.urlopen = original


# ── aiohttp (OpenBB providers) ──────────────────────────────────────

class _AioContent:
    """Enough of aiohttp's StreamReader for code that reads ``resp.content``."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    async def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    async def readany(self) -> bytes:
        return self._buf.read()

    async def readline(self) -> bytes:
        return self._buf.readline()

    async def iter_chunked(self, n: int):
        while True:
            chunk = self._buf.read(n)
            if not chunk:
                return
            yield chunk

    async def iter_any(self):
        data = self._buf.read()
        if data:
            yield data

    def at_eof(self) -> bool:
        return self._buf.tell() >= len(self._buf.getvalue())


class _AioReplayResponse:
    """A replayed aiohttp ClientResponse: status, headers, read/text/json, raise_for_status, async with."""

    def __init__(self, method: str, url, status: int, reason: str, headers: Dict[str, str], data: bytes):
        from multidict import CIMultiDict, CIMultiDictProxy
        self.method, self.url, self.real_url = method, url, url
        self.status, self.reason = int(status), reason
        self.headers = CIMultiDictProxy(CIMultiDict(headers))
        self._body = data
        self.content = _AioContent(data)
        self.history = ()
        self.closed = False
        from aiohttp.client_reqrep import RequestInfo
        try:
            self.request_info = RequestInfo(url, method, CIMultiDictProxy(CIMultiDict()), url)
        except TypeError:                       # older RequestInfo without real_url
            self.request_info = RequestInfo(url, method, CIMultiDictProxy(CIMultiDict()))

    @property
    def ok(self) -> bool:
        return self.status < 400

    @property
    def content_type(self) -> str:
        return (self.headers.get('Content-Type') or 'application/octet-stream').split(';')[0].strip().lower()

    @property
    def charset(self) -> Optional[str]:
        ct = self.headers.get('Content-Type') or ''
        for part in ct.split(';')[1:]:
            k, _, v = part.strip().partition('=')
            if k.lower() == 'charset':
                return v.strip('"') or None
        return None

    async def read(self) -> bytes:
        return self._body

    async def text(self, encoding: Optional[str] = None, errors: str = 'strict') -> str:
        return self._body.decode(encoding or self.charset or 'utf-8', errors)

    async def json(self, *, encoding: Optional[str] = None, loads=_json.loads, content_type: Optional[str] = 'application/json'):
        if content_type and 'json' not in self.content_type:
            from aiohttp import ContentTypeError
            raise ContentTypeError(self.request_info, self.history, status=self.status,
                                   message=f'Attempt to decode JSON with unexpected mimetype: {self.content_type}')
        text = self._body.decode(encoding or self.charset or 'utf-8')
        return loads(text) if text.strip() else None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            from aiohttp import ClientResponseError
            raise ClientResponseError(self.request_info, self.history, status=self.status, message=self.reason,
                                      headers=self.headers)

    def release(self) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True

    async def wait_for_close(self) -> None:
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        self.release()


@contextlib.contextmanager
def _patch_aiohttp(cassette):
    try:
        import aiohttp
    except ImportError:
        yield
        return
    from sajha.quality.cassette import _decode_body
    original = aiohttp.ClientSession._request

    def _target(session, str_or_url, params):
        build = getattr(session, '_build_url', None)
        url = build(str_or_url) if callable(build) else __import__('yarl').URL(str(str_or_url))
        return url.extend_query(params) if params else url

    def _body(session, kwargs) -> Any:
        if kwargs.get('json') is not None:
            ser = getattr(session, '_json_serialize', None) or _json.dumps
            return ser(kwargs['json'])
        return _form(kwargs.get('data'))

    async def _request(self, method, str_or_url, **kwargs):
        url = _target(self, str_or_url, kwargs.get('params'))
        body = _body(self, kwargs)
        if cassette.mode == 'replay':
            r = cassette._find(method, str(url), body)
            resp = _AioReplayResponse(method.upper(), url, r['status'], r.get('reason', ''), r['headers'],
                                      _decode_body(r['body']))
            if kwargs.get('raise_for_status') is True or (kwargs.get('raise_for_status') is None
                                                          and getattr(self, '_raise_for_status', False) is True):
                resp.raise_for_status()
            return resp
        resp = await original(self, method, str_or_url, **kwargs)
        data = await resp.read()               # aiohttp keeps the body: later read/text/json still work
        cassette._record(method, str(url), body, resp.status, resp.reason or '', _decoded_headers(resp.headers), data)
        return resp

    aiohttp.ClientSession._request = _request
    try:
        yield
    finally:
        aiohttp.ClientSession._request = original


# ── curl_cffi (yfinance) ────────────────────────────────────────────

def _curl_url(url: str, params: Any) -> str:
    if not params:
        return url
    items = list(params.items()) if isinstance(params, dict) else list(params)
    return url + ('&' if '?' in url else '?') + urlencode(items, doseq=True)


def _curl_body(kwargs) -> Any:
    if kwargs.get('json') is not None:
        return _json.dumps(kwargs['json'], separators=(',', ':'))
    if kwargs.get('content') is not None:
        return kwargs['content']
    return _form(kwargs.get('data'))


def _curl_response(method: str, url: str, status: int, reason: str, headers: Dict[str, str], data: bytes):
    from curl_cffi.requests import Headers, Response
    resp = Response()
    resp.url, resp.status_code, resp.reason = url, int(status), reason
    resp.ok = int(status) < 400
    resp.headers = Headers(headers)
    resp.content = data
    resp.encoding = None
    return resp


@contextlib.contextmanager
def _patch_curl_cffi(cassette):
    try:
        from curl_cffi import requests as creq
    except ImportError:
        yield
        return
    from sajha.quality.cassette import _decode_body
    sync_orig = creq.Session.request
    async_orig = creq.AsyncSession.request

    def _replay(method, url, body):
        r = cassette._find(method, url, body)
        return _curl_response(method, url, r['status'], r.get('reason', ''), r['headers'], _decode_body(r['body']))

    def _store(method, url, body, resp):
        data = resp.content if isinstance(resp.content, (bytes, bytearray)) else b''
        hdrs = _decoded_headers(resp.headers.items() if hasattr(resp.headers, 'items') else resp.headers)
        cassette._record(method, url, body, resp.status_code, resp.reason or '', hdrs, bytes(data))
        return _curl_response(method, resp.url or url, resp.status_code, resp.reason or '', hdrs, bytes(data))

    def request(self, method, url, *args, **kwargs):
        if args:                                 # params given positionally
            kwargs['params'] = args[0]
            args = args[1:]
        full, body = _curl_url(url, kwargs.get('params')), _curl_body(kwargs)
        if cassette.mode == 'replay':
            return _replay(method.upper(), full, body)
        resp = sync_orig(self, method, url, *args, **kwargs)
        return _store(method.upper(), full, body, resp)

    async def arequest(self, method, url, *args, **kwargs):
        if args:
            kwargs['params'] = args[0]
            args = args[1:]
        full, body = _curl_url(url, kwargs.get('params')), _curl_body(kwargs)
        if cassette.mode == 'replay':
            return _replay(method.upper(), full, body)
        resp = await async_orig(self, method, url, *args, **kwargs)
        return _store(method.upper(), full, body, resp)

    creq.Session.request = request
    creq.AsyncSession.request = arequest
    try:
        yield
    finally:
        creq.Session.request = sync_orig
        creq.AsyncSession.request = async_orig


@contextlib.contextmanager
def patch_all(cassette):
    """Every transport of this module, for ``Cassette.use()``."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(_patch_urllib3(cassette))
        stack.enter_context(_patch_aiohttp(cassette))
        stack.enter_context(_patch_curl_cffi(cassette))
        yield
