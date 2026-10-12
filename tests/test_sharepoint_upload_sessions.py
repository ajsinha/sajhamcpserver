# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SharePoint large uploads and the delegated grant (sajha/tools/impl/sharepoint_upload.py) against a
fake Microsoft Graph: chunked upload sessions (Content-Range, 320 KiB multiples, no token on the
upload URL), retries that resume from nextExpectedRanges, an interrupted upload resumed by a later
call, cancellation on refusal, the size cap, files from the storage backend, upload-URL host checks,
and calls made with the caller's connected Microsoft account (refresh once, then "reconnect").

Docs: docs/tools/enterprise/SharePoint Tool Reference Guide.md
"""

import base64
import json
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from sajha.tools.impl import sharepoint_tool as sp
from sajha.tools.impl import sharepoint_upload as spu
from tests.tool_config_files import read_tool

GRAPH = 'https://graph.microsoft.com/v1.0'
SITE_ID = 'site,1,2'
UPLOAD = 'https://contoso.sharepoint.com/sites/team/_api/v2.0/drives/d1/items/i1/uploadSession?guid=abc'


class Resp:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code, self.payload = status, payload
        self.headers = headers or {'Content-Type': 'application/json'}
        self.content = b'' if payload is None else json.dumps(payload).encode()
        self.text = self.content.decode()

    def json(self):
        if self.payload is None:
            raise ValueError('no body')
        return self.payload

    def raise_for_status(self):
        pass


class FakeGraph:
    """Graph and one upload session, in memory. ``fail`` maps a chunk start offset to the statuses
    (or 'drop' for a connection error) its next PUTs answer before succeeding."""

    def __init__(self, total=0):
        self.calls, self.tokens = [], 0
        self.received = {}
        self.total = total
        self.fail = {}
        self.cancelled = False
        self.chunk_status = {}

    def post(self, url, data=None, timeout=None):
        self.tokens += 1
        return Resp(200, {'access_token': 'app-token', 'expires_in': 3600})

    def _expected(self):
        have, nxt = sorted(self.received), 0
        for start in have:
            if start == nxt:
                nxt = start + len(self.received[start])
        return [f'{nxt}-'] if nxt < self.total else []

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None):
        headers = headers or {}
        self.calls.append((method, url, params, json, headers, len(data) if isinstance(data, bytes) else None))
        path = urlsplit(url).path
        if url.startswith(UPLOAD.split('?')[0]):
            assert 'Authorization' not in headers, 'the token must not go to the upload URL'
            if method == 'GET':
                return Resp(404) if self.cancelled else Resp(200, {'nextExpectedRanges': self._expected()})
            if method == 'DELETE':
                self.cancelled = True
                return Resp(204)
            m = re.match(r'bytes (\d+)-(\d+)/(\d+)', headers['Content-Range'])
            start, end, total = map(int, m.groups())
            assert int(headers['Content-Length']) == len(data) == end - start + 1 and total == self.total
            queue = self.fail.get(start)
            if queue:
                what = queue.pop(0)
                if what == 'drop':
                    import requests
                    raise requests.ConnectionError('reset by peer')
                return Resp(what, {'error': {'message': f'status {what}'}})
            self.received[start] = data
            if not self._expected():
                return Resp(201, {'id': 'new-item', 'webUrl': 'https://contoso.sharepoint.com/x/big.bin',
                                  'size': self.total})
            return Resp(202, {'nextExpectedRanges': self._expected()})
        auth = headers.get('Authorization', '')
        if auth == 'Bearer expired-user-token':
            return Resp(401, {'error': {'message': 'token expired'}})
        if path == '/v1.0/sites/contoso.sharepoint.com:/sites/team':
            return Resp(200, {'id': SITE_ID})
        if path.endswith('/createUploadSession') and method == 'POST':
            return Resp(200, {'uploadUrl': UPLOAD, 'expirationDateTime': '2026-10-12T00:00:00Z'})
        if path.endswith('/content') and method == 'PUT':
            return Resp(201, {'id': 'small', 'webUrl': 'https://contoso.sharepoint.com/x/s.txt', 'size': len(data)})
        if path.endswith('/drive/root/children'):
            return Resp(200, {'value': []})
        return Resp(404, {'error': {'message': f'no route {method} {path}'}})

    def assembled(self):
        return b''.join(self.received[k] for k in sorted(self.received))


def _tool(**extra):
    cfg = read_tool('sharepoint_documents')
    cfg.update(site_url='https://contoso.sharepoint.com/sites/team',
               authentication={'type': 'client_credentials', 'tenant_id': 't', 'client_id': 'c', 'client_secret': 's'})
    cfg.update(extra)
    return sp.SharePointDocumentTool(cfg)


@pytest.fixture
def graph(monkeypatch):
    g = FakeGraph()
    monkeypatch.setattr(sp.requests, 'post', g.post)
    monkeypatch.setattr(sp.requests, 'request', g.request)
    monkeypatch.setattr(spu.time, 'sleep', lambda s: g.calls.append(('SLEEP', s)))
    return g


def _upload(tool, content, **args):
    return tool.execute({'operation': 'upload', 'file_name': 'big.bin', 'folder_path': '/Reports',
                         'content_base64': base64.b64encode(content).decode(), **args})


def _puts(g):
    return [c for c in g.calls if c[0] == 'PUT' and c[1].startswith(UPLOAD.split('?')[0])]


def test_small_files_keep_the_simple_upload(graph):
    out = _upload(_tool(), b'hello')
    assert out['success'] and out['method'] == 'simple'
    assert not any('createUploadSession' in str(c[1]) for c in graph.calls)


def test_large_file_goes_through_an_upload_session_in_aligned_chunks(graph):
    content = bytes(range(256)) * (4 * 4096) + b'tail'                # 4 MiB + 4 bytes
    graph.total = len(content)
    out = _upload(_tool(upload_chunk_bytes=1_000_000), content, overwrite=True)
    assert out['success'] and out['method'] == 'upload_session' and out['id'] == 'new-item', out
    create = next(c for c in graph.calls if str(c[1]).endswith('/createUploadSession'))
    assert create[3] == {'item': {'@microsoft.graph.conflictBehavior': 'replace', 'name': 'big.bin'}}
    assert '/drive/root:/Reports/big.bin:/createUploadSession' in create[1]
    sizes = [c[5] for c in _puts(graph)]
    assert all(s % spu.CHUNK_UNIT == 0 for s in sizes[:-1]) and sizes[0] == 3 * spu.CHUNK_UNIT   # 1e6 rounded down
    assert graph.assembled() == content


def test_failed_chunks_are_retried_from_the_sessions_expected_range(graph):
    content = b'a' * (spu.CHUNK_UNIT * 13 + 17)                 # over the 4 MiB simple-upload limit
    graph.total = len(content)
    graph.fail = {spu.CHUNK_UNIT * 2: [503, 'drop']}
    out = _upload(_tool(upload_chunk_bytes=spu.CHUNK_UNIT), content)
    assert out['success'], out
    assert graph.assembled() == content
    assert [c for c in graph.calls if c[0] == 'SLEEP']                     # backed off between attempts
    assert sum(1 for c in graph.calls if c[0] == 'GET' and c[1] == UPLOAD) == 2   # asked where to resume


def test_an_interrupted_upload_resumes_in_a_later_call(graph):
    content = b'b' * (spu.CHUNK_UNIT * 14)
    graph.total = len(content)
    graph.fail = {spu.CHUNK_UNIT * 3: [500, 500, 500, 500]}
    tool = _tool(upload_chunk_bytes=spu.CHUNK_UNIT)
    out = _upload(tool, content)
    assert out['success'] is False and out['resumable'] and out['upload_url'] == UPLOAD
    assert out['bytes_uploaded'] == spu.CHUNK_UNIT * 3 and out['size'] == len(content)
    assert not graph.cancelled
    before = len(_puts(graph))
    out = _upload(tool, content, resume_upload_url=out['upload_url'])
    assert out['success'], out
    assert len(_puts(graph)) - before == 11                              # only the missing chunks
    assert graph.assembled() == content


def test_a_refused_chunk_cancels_the_session(graph):
    content = b'c' * (spu.CHUNK_UNIT * 20)
    graph.total = len(content)
    graph.fail = {0: [409]}
    out = _upload(_tool(), content)
    assert out['success'] is False and 'HTTP 409' in out['error'] and graph.cancelled


def test_resume_urls_on_other_hosts_are_refused(graph):
    content = b'd' * (spu.CHUNK_UNIT * 20)
    for url in ('https://evil.example.com/upload?x', 'http://contoso.sharepoint.com/upload',
                'https://fabrikam.sharepoint.com/upload', 'https://user:pw@contoso.sharepoint.com/u'):
        out = _upload(_tool(), content, resume_upload_url=url)
        assert out['success'] is False and 'upload URL' in out['error'], url
    assert spu.check_upload_url('https://contoso-my.sharepoint.com/personal/u/_api/x', 'https://contoso.sharepoint.com/sites/t')


def test_the_size_cap(graph):
    out = _upload(_tool(max_upload_bytes=1000), b'e' * 1001)
    assert out['success'] is False and 'max_upload_bytes' in out['error']


def test_source_path_reads_from_upload_roots_only(graph, tmp_path, monkeypatch):
    import sajha.core.storage as storage
    from sajha.observability.caller import Caller, reset, set_caller
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    (tmp_path / 'uploads' / 'alice').mkdir(parents=True)
    (tmp_path / 'uploads' / 'alice' / 'r.txt').write_bytes(b'report')
    (tmp_path / 'secret.txt').write_bytes(b'nope')
    args = {'operation': 'upload', 'file_name': 'r.txt'}
    assert 'upload_roots' in _tool().execute({**args, 'source_path': 'uploads/alice/r.txt'})['error']
    tool = _tool(upload_roots=['uploads/{user}'])
    tok = set_caller(Caller('alice'))
    try:
        out = tool.execute({**args, 'source_path': 'uploads/alice/r.txt'})
        assert out['success'] and out['size'] == 6
        assert "'..'" in tool.execute({**args, 'source_path': 'uploads/alice/../../secret.txt'})['error']
        assert 'not under' in tool.execute({**args, 'source_path': 'secret.txt'})['error']
    finally:
        reset(tok)
    tok = set_caller(Caller('bob'))
    try:
        assert 'not under' in tool.execute({**args, 'source_path': 'uploads/alice/r.txt'})['error']
    finally:
        reset(tok)


# ── the delegated grant ─────────────────────────────────────────────

class FakeService:
    def __init__(self):
        self.refreshed, self.rejected = 0, 0

    def refresh_after_rejection(self, token, tool=''):
        self.refreshed += 1
        return SimpleNamespace(access_token=self.next_token, provider=SimpleNamespace(id='microsoft'), user_id='alice')

    def mark_rejected(self, token, why=''):
        self.rejected += 1

    def required(self, pid, reason, user_id='', scopes=None, tool=''):
        from sajha.accounts.errors import ConnectedAccountRequired
        return ConnectedAccountRequired(pid, reason=reason, connect_url='https://sajha.test/account/connections',
                                        provider_title='Microsoft 365')


def _delegated(**auth):
    return _tool(authentication={'type': 'delegated', **auth})


def _bound(token):
    from sajha.accounts import injection
    return injection._tokens.set({'microsoft': SimpleNamespace(access_token=token, user_id='alice',
                                                               provider=SimpleNamespace(id='microsoft'))})


def test_delegated_config_binds_the_callers_microsoft_account():
    tool = _delegated(scopes=['Sites.Read.All'])
    assert tool.config['auth'] == {'connected_account': 'microsoft', 'scopes': ['Sites.Read.All']}
    assert _delegated().config['auth']['scopes'] == ['Sites.ReadWrite.All']
    assert 'auth' not in _tool().config                                   # client credentials: no binding


def test_delegated_calls_use_the_callers_token_and_never_the_app_token(graph):
    from sajha.accounts import injection
    tok = _bound('user-token')
    try:
        out = _delegated().execute({'operation': 'list_files'})
    finally:
        injection._tokens.reset(tok)
    assert out['success'], out
    assert graph.tokens == 0
    assert {c[4].get('Authorization') for c in graph.calls if c[0] != 'SLEEP'} == {'Bearer user-token'}


def test_delegated_401_refreshes_once_then_asks_to_reconnect(graph, monkeypatch):
    from sajha.accounts import injection, service as svc_mod
    from sajha.accounts.errors import ConnectedAccountRequired
    fake = FakeService()
    monkeypatch.setattr(svc_mod, 'get_service', lambda: fake)
    fake.next_token = 'user-token-2'
    tok = _bound('expired-user-token')
    try:
        out = _delegated().execute({'operation': 'list_files'})
        assert out['success'] and fake.refreshed == 1                     # refreshed, retried, worked
    finally:
        injection._tokens.reset(tok)
    fake.next_token = 'expired-user-token'                                  # the refresh does not help
    tok = _bound('expired-user-token')
    try:
        with pytest.raises(ConnectedAccountRequired):                      # not swallowed into success: false
            _delegated().execute({'operation': 'list_files'})
    finally:
        injection._tokens.reset(tok)
    assert fake.rejected == 1


def test_delegated_tokens_never_leave_graph(graph):
    from sajha.accounts import injection
    tool = _delegated()
    tok = _bound('user-token')
    try:
        with pytest.raises(RuntimeError, match='only sent to graph.microsoft.com'):
            tool._graph('GET', 'https://evil.example.com/v1.0/me')
    finally:
        injection._tokens.reset(tok)
