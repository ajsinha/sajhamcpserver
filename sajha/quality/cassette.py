"""
SAJHA MCP Server — HTTP cassettes: record a tool's HTTP exchanges once, replay them offline.

A small VCR. While a :class:`Cassette` is active (``with cassette.use():``) it intercepts

* ``urllib.request.urlopen`` (what nearly every built-in tool calls),
* ``requests.Session.send`` (when ``requests`` is installed),
* ``httpx.HTTPTransport.handle_request`` and ``httpx.AsyncHTTPTransport.handle_async_request``
  (when ``httpx`` is installed),

and, by mode:

* ``record``: performs the request, stores it, returns an equivalent response;
* ``replay``: answers from the stored interactions; a request it does not hold raises
  :class:`CassetteMiss` (no network, ever);
* ``live``: does nothing (the cassette is a no-op).

Matching is on method + URL (secret query parameters redacted) + SHA-256 of the body.
Identical requests are answered in recorded order. Request headers are never stored;
``Set-Cookie`` response headers are dropped. Docs: docs/architecture/Tool Quality.md §2.3.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MODES = ('record', 'replay', 'live')
SECRET_PARAMS = {'apikey', 'api_key', 'api-key', 'token', 'key', 'access_token', 'client_secret', 'password',
                 'secret', 'sig', 'signature', 'auth', 'apitoken', 'api_token', 'subscription-key'}
_DROP_RESPONSE_HEADERS = {'set-cookie', 'set-cookie2'}
_FORMAT = 1
_patch_lock = threading.RLock()


class CassetteMiss(RuntimeError):
    """Replay mode met a request the cassette does not hold."""


def redact_url(url: str) -> str:
    """``url`` with the values of secret-looking query parameters replaced by REDACTED."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    q = [(k, 'REDACTED' if k.lower() in SECRET_PARAMS else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def _body_hash(body: Any) -> str:
    if body is None or body == b'' or body == '':
        return ''
    if isinstance(body, str):
        body = body.encode('utf-8')
    if not isinstance(body, (bytes, bytearray)):
        try:
            body = bytes(body)
        except Exception:
            return 'stream'
    return hashlib.sha256(bytes(body)).hexdigest()


def _encode_body(data: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
    encoded = {k.lower(): v for k, v in headers.items()}.get('content-encoding', '')
    if not encoded:
        try:
            return {'text': data.decode('utf-8')}
        except UnicodeDecodeError:
            pass
    return {'base64': base64.b64encode(data).decode('ascii')}


def _decode_body(body: Dict[str, Any]) -> bytes:
    if 'base64' in body:
        return base64.b64decode(body['base64'])
    return str(body.get('text', '')).encode('utf-8')


class Cassette:
    def __init__(self, path: Optional[str], mode: str = 'replay'):
        if mode not in MODES:
            raise ValueError(f'cassette mode must be one of {MODES}, got {mode!r}')
        self.path = Path(path) if path else None
        self.mode = mode
        self.interactions: List[Dict[str, Any]] = []
        self._played: Dict[int, bool] = {}
        self._lock = threading.Lock()
        self.misses: List[str] = []
        if mode == 'replay':
            if not self.path or not self.path.is_file():
                raise FileNotFoundError(f'no cassette at {self.path}')
            self.interactions = list(json.loads(self.path.read_text(encoding='utf-8')).get('interactions', []))

    # -- store ------------------------------------------------------------

    @property
    def requests_seen(self) -> int:
        return len(self.interactions) if self.mode == 'record' else sum(1 for v in self._played.values() if v)

    def save(self) -> Optional[Path]:
        if self.mode != 'record' or not self.path:
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + '.tmp')
        tmp.write_text(json.dumps({'format': _FORMAT, 'interactions': self.interactions}, indent=1,
                                  ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, self.path)
        return self.path

    def _record(self, method: str, url: str, body: Any, status: int, reason: str,
                headers: Dict[str, str], data: bytes) -> None:
        headers = {k: v for k, v in headers.items() if k.lower() not in _DROP_RESPONSE_HEADERS}
        with self._lock:
            self.interactions.append({
                'request': {'method': method.upper(), 'url': redact_url(url), 'body_sha256': _body_hash(body)},
                'response': {'status': int(status), 'reason': reason or '', 'headers': headers,
                             'body': _encode_body(data, headers)}})

    def _find(self, method: str, url: str, body: Any) -> Dict[str, Any]:
        want = (method.upper(), redact_url(url), _body_hash(body))
        with self._lock:
            for i, it in enumerate(self.interactions):
                r = it['request']
                if not self._played.get(i) and (r['method'], r['url'], r.get('body_sha256', '')) == want:
                    self._played[i] = True
                    return it['response']
        msg = f'{want[0]} {want[1]}'
        self.misses.append(msg)
        raise CassetteMiss(f'cassette {self.path.name if self.path else ""} has no (unplayed) recording of {msg}; '
                           f're-record with --record')

    # -- activation -------------------------------------------------------

    @contextlib.contextmanager
    def use(self) -> Iterator['Cassette']:
        if self.mode == 'live':
            yield self
            return
        with _patch_lock:          # one cassette at a time per process (the harness runs cases serially)
            stack = contextlib.ExitStack()
            with stack:
                stack.enter_context(_patch_urllib(self))
                stack.enter_context(_patch_requests(self))
                stack.enter_context(_patch_httpx(self))
                yield self
        self.save()


# ── urllib ──────────────────────────────────────────────────────────

class _UrllibResponse(io.BytesIO):
    """Enough of http.client.HTTPResponse for tools: read, headers, status, info(), getheader, with."""

    def __init__(self, url: str, status: int, reason: str, headers: Dict[str, str], data: bytes):
        super().__init__(data)
        import email.message
        self.url = url
        self.status = self.code = int(status)
        self.reason = self.msg = reason
        msg = email.message.Message()
        for k, v in headers.items():
            msg[k] = v
        self.headers = msg

    def info(self):
        return self.headers

    def geturl(self):
        return self.url

    def getcode(self):
        return self.status

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def getheaders(self):
        return list(self.headers.items())


def _urllib_request_parts(req, data) -> Tuple[str, str, Any]:
    import urllib.request
    if isinstance(req, urllib.request.Request):
        return req.get_method(), req.full_url, req.data if data is None else data
    return ('POST' if data is not None else 'GET'), str(req), data


@contextlib.contextmanager
def _patch_urllib(cassette: Cassette):
    import urllib.error
    import urllib.request
    original = urllib.request.urlopen

    def urlopen(req, data=None, *args, **kwargs):
        method, url, body = _urllib_request_parts(req, data)
        if cassette.mode == 'replay':
            r = cassette._find(method, url, body)
            payload = _decode_body(r['body'])
            if r['status'] >= 400:
                raise urllib.error.HTTPError(url, r['status'], r.get('reason', ''),
                                             _UrllibResponse(url, r['status'], r.get('reason', ''), r['headers'], b'').headers,
                                             io.BytesIO(payload))
            return _UrllibResponse(url, r['status'], r.get('reason', ''), r['headers'], payload)
        try:
            resp = original(req, data, *args, **kwargs)
        except urllib.error.HTTPError as e:
            payload = e.read() if e.fp is not None else b''
            hdrs = dict(e.headers.items()) if e.headers else {}
            cassette._record(method, url, body, e.code, str(e.reason or ''), hdrs, payload)
            raise urllib.error.HTTPError(url, e.code, e.reason, e.headers, io.BytesIO(payload)) from None
        with resp:
            payload = resp.read()
            status = getattr(resp, 'status', None) or resp.getcode()
            hdrs = dict(resp.headers.items()) if getattr(resp, 'headers', None) else {}
            reason = getattr(resp, 'reason', '') or ''
            final = resp.geturl() if hasattr(resp, 'geturl') else url
        cassette._record(method, url, body, status, reason, hdrs, payload)
        return _UrllibResponse(final, status, reason, hdrs, payload)

    urllib.request.urlopen = urlopen
    try:
        yield
    finally:
        urllib.request.urlopen = original


# ── requests ────────────────────────────────────────────────────────

@contextlib.contextmanager
def _patch_requests(cassette: Cassette):
    try:
        import requests
        from requests.structures import CaseInsensitiveDict
    except ImportError:
        yield
        return
    original = requests.Session.send

    def build(prepared, r: Dict[str, Any], payload: bytes):
        resp = requests.Response()
        resp.status_code = r['status']
        resp.reason = r.get('reason', '')
        resp.headers = CaseInsensitiveDict(r['headers'])
        resp._content = payload
        resp._content_consumed = True
        resp.url = prepared.url
        resp.request = prepared
        resp.encoding = requests.utils.get_encoding_from_headers(resp.headers)
        return resp

    def send(self, prepared, **kwargs):
        if cassette.mode == 'replay':
            r = cassette._find(prepared.method or 'GET', prepared.url, prepared.body)
            return build(prepared, r, _decode_body(r['body']))
        resp = original(self, prepared, **kwargs)
        payload = resp.content
        cassette._record(prepared.method or 'GET', prepared.url, prepared.body, resp.status_code, resp.reason or '',
                         dict(resp.headers), payload)
        return resp

    requests.Session.send = send
    try:
        yield
    finally:
        requests.Session.send = original


# ── httpx ───────────────────────────────────────────────────────────

@contextlib.contextmanager
def _patch_httpx(cassette: Cassette):
    try:
        import httpx
    except ImportError:
        yield
        return
    sync_orig = httpx.HTTPTransport.handle_request
    async_orig = httpx.AsyncHTTPTransport.handle_async_request

    def _headers(resp_headers) -> Dict[str, str]:
        # content-encoding is dropped on replay because the stored body is the decoded body
        return {k: v for k, v in resp_headers.items() if k.lower() not in ('content-encoding', 'content-length',
                                                                           'transfer-encoding')}

    def handle_request(self, request):
        body = request.read() if hasattr(request, 'read') else request.content
        if cassette.mode == 'replay':
            r = cassette._find(request.method, str(request.url), body)
            return httpx.Response(r['status'], headers=r['headers'], content=_decode_body(r['body']), request=request)
        resp = sync_orig(self, request)
        payload = resp.read()
        hdrs = _headers(resp.headers)
        cassette._record(request.method, str(request.url), body, resp.status_code, resp.reason_phrase, hdrs, payload)
        return httpx.Response(resp.status_code, headers=hdrs, content=payload, request=request)

    async def handle_async_request(self, request):
        body = await request.aread() if hasattr(request, 'aread') else request.content
        if cassette.mode == 'replay':
            r = cassette._find(request.method, str(request.url), body)
            return httpx.Response(r['status'], headers=r['headers'], content=_decode_body(r['body']), request=request)
        resp = await async_orig(self, request)
        payload = await resp.aread()
        hdrs = _headers(resp.headers)
        cassette._record(request.method, str(request.url), body, resp.status_code, resp.reason_phrase, hdrs, payload)
        return httpx.Response(resp.status_code, headers=hdrs, content=payload, request=request)

    httpx.HTTPTransport.handle_request = handle_request
    httpx.AsyncHTTPTransport.handle_async_request = handle_async_request
    try:
        yield
    finally:
        httpx.HTTPTransport.handle_request = sync_orig
        httpx.AsyncHTTPTransport.handle_async_request = async_orig


def cassette_path(tool: str, case: str, root: Optional[str] = None) -> Path:
    """``<cassettes_dir>/<tool>/<case slug>.json``."""
    import re
    from sajha.quality import cassettes_dir
    slug = re.sub(r'[^A-Za-z0-9_.-]+', '_', case).strip('_') or 'case'
    tool_slug = re.sub(r'[^A-Za-z0-9_.-]+', '_', tool) or 'tool'
    return Path(root or cassettes_dir()) / tool_slug / f'{slug}.json'
