# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Cassettes for the other transports (sajha/quality/cassette_transports.py): urllib3 (and the call
pattern botocore's URLLib3Session uses), aiohttp and curl_cffi are recorded against a local server
and replayed with the server unreachable; a request the cassette does not hold raises CassetteMiss;
requests (which sits on urllib3) is recorded once, not twice; secret query values are redacted.

Docs: docs/architecture/Tool Quality.md §2.3
"""

import asyncio
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sajha.quality.cassette import Cassette, CassetteMiss


class Server:
    def __init__(self):
        self.hits = []


def _handler(srv):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _handle(self):
            n = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(n) if n else b''
            srv.hits.append((self.command, self.path, body))
            if self.path.startswith('/missing'):
                raw, status, extra = b'{"error":"nope"}', 404, {}
            elif self.path.startswith('/gz'):
                raw, status, extra = gzip.compress(b'{"zipped":true}'), 200, {'Content-Encoding': 'gzip'}
            else:
                raw = json.dumps({'path': self.path, 'method': self.command, 'echo': body.decode()}).encode()
                status, extra = 200, {}
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)
        do_GET = do_POST = do_PUT = _handle
    return H


@pytest.fixture
def server():
    srv = Server()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), _handler(srv))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    srv.url = f'http://127.0.0.1:{httpd.server_address[1]}'
    yield srv
    httpd.shutdown()


def _record_then_replay(tmp_path, server, call):
    """Run ``call()`` while recording, then again replaying with the server's hits frozen."""
    path = tmp_path / 'c.json'
    with Cassette(str(path), 'record').use():
        live = call()
    hits = len(server.hits)
    with Cassette(str(path), 'replay').use() as c:
        replayed = call()
    assert len(server.hits) == hits, 'replay reached the network'
    return live, replayed, json.loads(path.read_text()), c


# ── urllib3 and botocore's call pattern ──────────────────────────────

def test_urllib3_pool_manager_records_and_replays(tmp_path, server):
    import urllib3

    def call():
        r = urllib3.PoolManager().request('GET', f'{server.url}/a?apikey=s3cr3t&q=1')
        return r.status, json.loads(r.data)
    live, replayed, doc, _ = _record_then_replay(tmp_path, server, call)
    assert live == replayed and live[0] == 200 and live[1]['path'] == '/a?apikey=s3cr3t&q=1'
    assert len(doc['interactions']) == 1
    url = doc['interactions'][0]['request']['url']
    assert 's3cr3t' not in url and 'apikey=REDACTED' in url


def test_botocore_style_streaming_call_without_decoding(tmp_path, server):
    """URLLib3Session.send: conn.urlopen(..., retries=False, preload_content=False, decode_content=False)
    and the body read from the raw stream; gzip bytes stay as sent."""
    import urllib3

    def call():
        conn = urllib3.PoolManager().connection_from_url(server.url)
        r = conn.urlopen('PUT', '/gz/bucket/key', body=b'payload', headers={'x-amz-date': '20261011T000000Z'},
                         retries=False, assert_same_host=False, preload_content=False, decode_content=False)
        raw = b''.join(r.stream(1024))
        return r.status, r.headers.get('Content-Encoding'), gzip.decompress(raw)
    live, replayed, doc, _ = _record_then_replay(tmp_path, server, call)
    assert live == replayed == (200, 'gzip', b'{"zipped":true}')
    assert 'base64' in doc['interactions'][0]['response']['body']        # encoded bytes kept exactly


def test_urllib3_replay_miss_raises(tmp_path, server):
    import urllib3
    path = tmp_path / 'c.json'
    with Cassette(str(path), 'record').use():
        urllib3.PoolManager().request('GET', f'{server.url}/one')
    with Cassette(str(path), 'replay').use():
        with pytest.raises(CassetteMiss, match='/two'):
            urllib3.PoolManager().request('GET', f'{server.url}/two')


def test_requests_is_recorded_once_not_again_by_urllib3(tmp_path, server):
    import requests

    def call():
        r = requests.post(f'{server.url}/r', data=b'abc', timeout=5)
        return r.status_code, r.json()
    live, replayed, doc, _ = _record_then_replay(tmp_path, server, call)
    assert live == replayed and live[1]['echo'] == 'abc'
    assert len(doc['interactions']) == 1


# ── aiohttp ─────────────────────────────────────────────────────────

def test_aiohttp_records_and_replays_get_post_and_errors(tmp_path, server):
    import aiohttp

    async def run():
        async with aiohttp.ClientSession() as s:
            async with s.get(f'{server.url}/x', params={'token': 'tk', 'n': '2'}) as r:
                a = (r.status, await r.json(), r.headers['Content-Type'])
            r = await s.post(f'{server.url}/y', json={'k': 1})
            b = (r.status, (await r.json())['echo'])
            async with s.get(f'{server.url}/missing') as r:
                try:
                    r.raise_for_status()
                    c = 'no error'
                except aiohttp.ClientResponseError as e:
                    c = e.status
            async with s.get(f'{server.url}/gz') as r:
                d = await r.text()
        return a, b, c, d

    live, replayed, doc, _ = _record_then_replay(tmp_path, server, lambda: asyncio.run(run()))
    assert live == replayed
    a, b, c, d = live
    assert a[0] == 200 and a[1]['path'].startswith('/x?') and b == (200, '{"k": 1}') and c == 404
    assert d == '{"zipped":true}'
    assert 'token=REDACTED' in doc['interactions'][0]['request']['url']


def test_aiohttp_replay_miss_raises(tmp_path, server):
    import aiohttp
    path = tmp_path / 'c.json'

    async def get(p):
        async with aiohttp.ClientSession() as s:
            async with s.get(f'{server.url}{p}') as r:
                return await r.read()
    with Cassette(str(path), 'record').use():
        asyncio.run(get('/one'))
    with Cassette(str(path), 'replay').use():
        with pytest.raises(CassetteMiss):
            asyncio.run(get('/other'))


# ── curl_cffi ───────────────────────────────────────────────────────

def test_curl_cffi_session_records_and_replays(tmp_path, server):
    from curl_cffi import requests as creq

    def call():
        with creq.Session() as s:
            r1 = s.get(f'{server.url}/q', params={'crumb': 'c1', 'symbols': 'AAPL'})
            r2 = s.post(f'{server.url}/p', json={'a': [1, 2]})
            r3 = s.get(f'{server.url}/missing')
            return (r1.status_code, r1.json()['path'], r2.json()['echo'], r3.status_code, r3.ok)
    live, replayed, doc, _ = _record_then_replay(tmp_path, server, call)
    assert live == replayed
    assert live[0] == 200 and live[1] == '/q?crumb=c1&symbols=AAPL' and live[3] == 404 and live[4] is False


def test_curl_cffi_async_session(tmp_path, server):
    from curl_cffi import requests as creq

    async def run():
        async with creq.AsyncSession() as s:
            r = await s.get(f'{server.url}/async')
            return r.status_code, r.json()['path']
    live, replayed, _, _ = _record_then_replay(tmp_path, server, lambda: asyncio.run(run()))
    assert live == replayed == (200, '/async')


def test_live_mode_patches_nothing(tmp_path, server):
    import aiohttp
    import urllib3
    before = (urllib3.connectionpool.HTTPConnectionPool.urlopen, aiohttp.ClientSession._request)
    with Cassette(None, 'live').use():
        assert (urllib3.connectionpool.HTTPConnectionPool.urlopen, aiohttp.ClientSession._request) == before
    with Cassette(str(tmp_path / 'c.json'), 'record').use():
        assert urllib3.connectionpool.HTTPConnectionPool.urlopen is not before[0]
    assert (urllib3.connectionpool.HTTPConnectionPool.urlopen, aiohttp.ClientSession._request) == before
