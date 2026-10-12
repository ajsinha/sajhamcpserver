# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
API Import coverage (Roadmap L4): multipart and binary request bodies (file values given
inline or as a storage path under api_import.file_roots, the upload size cap), opt-in
pagination following (link, next URL field, cursor, page, offset; page and row caps; a next
link the SSRF guard refuses or on another origin is never followed), and Swagger 2.0
remote $ref bundling through the guard. Everything runs against a local fake server.

Design: docs/architecture/API Import.md.
"""

import base64
import json
import threading
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / 'tests' / 'fixtures' / 'api_import'
ROWS = [{'id': i} for i in range(1, 26)]                  # 25 rows, 10 per page


class Fake:
    def __init__(self):
        self.requests = []


def _handler(api: Fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, body=None, ctype='application/json', headers=None):
            raw = b'' if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self):
            u = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b''
            api.requests.append({'method': self.command, 'path': u.path, 'query': q,
                                 'headers': dict(self.headers), 'body': body})
            p = u.path
            if p.startswith('/specs/'):
                f = FIX / p[len('/specs/'):]
                if not f.exists():
                    return self._send(404, {'message': 'no spec'})
                return self._send(200, f.read_bytes(), 'application/yaml')
            if p in ('/v1/upload', '/v1/raw', '/v1/image'):
                return self._send(200, {'content_type': self.headers.get('Content-Type', ''),
                                        'size': len(body), 'b64': base64.b64encode(body).decode()})
            page = int(q.get('page') or 1)
            if p == '/v1/linked':
                rows = ROWS[(page - 1) * 10: page * 10]
                hdr = {'Link': f'<{api.url}/v1/linked?page={page + 1}>; rel="next"'} if page * 10 < len(ROWS) else {}
                return self._send(200, rows, headers=hdr)
            if p == '/v1/nexturl':
                rows = ROWS[(page - 1) * 10: page * 10]
                nxt = f'/v1/nexturl?page={page + 1}' if page * 10 < len(ROWS) else None
                return self._send(200, {'data': rows, 'links': {'next': nxt}})
            if p == '/v1/cursor':
                start = int(q.get('cursor') or 0)
                nxt = str(start + 10) if start + 10 < len(ROWS) else None
                return self._send(200, {'items': ROWS[start:start + 10], 'meta': {'next_cursor': nxt}})
            if p == '/v1/paged':
                return self._send(200, {'results': ROWS[(page - 1) * 10: page * 10], 'total': len(ROWS)})
            if p == '/v1/offset':
                off, lim = int(q.get('offset') or 0), int(q.get('limit') or 10)
                return self._send(200, ROWS[off:off + lim])
            if p == '/v1/evil':                   # the next page points at a private address
                return self._send(200, ROWS[:10], headers={'Link': '<http://10.1.2.3/v1/evil?page=2>; rel="next"'})
            if p == '/v1/elsewhere':              # the next page is on another origin the guard allows
                port = urlsplit(api.url).port
                return self._send(200, ROWS[:10], headers={'Link': f'<http://localhost:{port}/v1/linked?page=2>; rel="next"'})
            return self._send(404, {'message': 'not found'})

        do_GET = do_POST = do_PUT = _handle

    return H


@pytest.fixture(scope='module')
def fake():
    api = Fake()
    server = ThreadingHTTPServer(('127.0.0.1', 0), _handler(api))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api.url = f'http://127.0.0.1:{server.server_address[1]}'
    yield api
    server.shutdown()


@pytest.fixture
def local(monkeypatch, fake):
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOW_LOCALHOST', 'true')
    for k in ('ALLOWED_HOSTS', 'FILE_ROOTS', 'MAX_UPLOAD_BYTES', 'PAGINATION_MAX_PAGES', 'PAGINATION_MAX_ITEMS',
              'ALLOW_PRIVATE_NETWORKS'):
        monkeypatch.delenv(f'SAJHA_API_IMPORT_{k}', raising=False)
    fake.requests.clear()
    return fake


def _spec(paths):
    return json.dumps({'openapi': '3.0.3', 'info': {'title': 'T', 'version': '1'}, 'paths': paths})


UPLOAD_SPEC = _spec({
    '/upload': {'post': {'operationId': 'upload', 'requestBody': {'required': True, 'content': {
        'multipart/form-data': {
            'schema': {'type': 'object', 'required': ['file'], 'properties': {
                'file': {'type': 'string', 'format': 'binary', 'description': 'The document'},
                'attachments': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                'meta': {'type': 'object', 'properties': {'kind': {'type': 'string'}}},
                'note': {'type': 'string'}}},
            'encoding': {'meta': {'contentType': 'application/json'}}}}},
        'responses': {'200': {'description': 'ok'}}}},
    '/raw': {'put': {'operationId': 'raw', 'requestBody': {'content': {
        'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}},
        'responses': {'200': {'description': 'ok'}}}},
    '/image': {'put': {'operationId': 'image', 'requestBody': {'content': {
        'image/png': {'schema': {'type': 'string', 'format': 'binary'}}}},
        'responses': {'200': {'description': 'ok'}}}},
})


def _tool(text, key, base_url, **extra):
    from sajha.api_import import service
    from sajha.api_import.executor import ImportedAPITool
    req = service.ImportRequest.from_dict({'kind': 'openapi', 'text': text, 'base_url': base_url, **extra})
    p = service.build_plan(req)
    op = p.op(key)
    return ImportedAPITool(service.tool_config(op, op['name'], p.ctx()))


def _parts(resp_body):
    raw = base64.b64decode(resp_body['b64'])
    msg = BytesParser(policy=HTTP).parsebytes(b'Content-Type: ' + resp_body['content_type'].encode() + b'\r\n\r\n' + raw)
    return {(part.get_param('name', header='content-disposition'), i): part for i, part in enumerate(msg.iter_parts())}


# ── multipart and binary bodies ─────────────────────────────────────────

def test_multipart_operation_becomes_a_tool_with_file_values(local):
    from sajha.api_import import service
    plan = service.plan({'kind': 'openapi', 'text': UPLOAD_SPEC, 'base_url': f'{local.url}/v1'})
    ops = {o['key']: o for o in plan['operations']}
    assert all(not o['unsupported'] and o['files'] for o in ops.values())
    body = ops['POST /upload']['input_schema']['properties']['body']
    assert body['required'] == ['file']
    assert body['properties']['file']['type'] == 'object' and 'The document' in body['properties']['file']['description']
    assert body['properties']['attachments']['items']['properties']['content_base64']['contentEncoding'] == 'base64'
    assert body['properties']['meta']['type'] == 'object' and body['properties']['note'] == {'type': 'string'}
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(ops['POST /upload']['input_schema'])
    cfg = _tool(UPLOAD_SPEC, 'POST /upload', f'{local.url}/v1').config['api_import']['body']
    assert cfg['fields'] == {'file': 'file', 'attachments': 'files', 'meta': 'json', 'note': 'value'}
    assert cfg['part_types'] == {'meta': 'application/json'}


def test_multipart_call_sends_every_part_through_the_guard(local):
    tool = _tool(UPLOAD_SPEC, 'POST /upload', f'{local.url}/v1')
    out = tool.execute({'body': {
        'file': {'content_base64': base64.b64encode(b'\x00\x01PDF').decode(), 'filename': 'a.pdf'},
        'attachments': [{'text': 'one', 'filename': 'one.txt'}, {'text': 'two'}],
        'meta': {'kind': 'invoice'}, 'note': 'hello'}})
    assert out['status'] == 200 and out['body']['content_type'].startswith('multipart/form-data; boundary=')
    parts = _parts(out['body'])
    by_name = {}
    for (name, _), part in parts.items():
        by_name.setdefault(name, []).append(part)
    f = by_name['file'][0]
    assert f.get_filename() == 'a.pdf' and f.get_content_type() == 'application/pdf'
    assert f.get_payload(decode=True) == b'\x00\x01PDF'
    assert [p.get_payload(decode=True) for p in by_name['attachments']] == [b'one', b'two']
    assert by_name['attachments'][1].get_filename() == 'attachments'
    assert json.loads(by_name['meta'][0].get_payload(decode=True)) == {'kind': 'invoice'}
    assert by_name['meta'][0].get_content_type() == 'application/json'
    assert by_name['note'][0].get_payload(decode=True) == b'hello'


def test_binary_bodies_use_the_declared_or_given_type(local):
    raw = _tool(UPLOAD_SPEC, 'PUT /raw', f'{local.url}/v1')
    assert raw.config['inputSchema']['properties']['body']['properties']['content_base64']
    out = raw.execute({'body': {'content_base64': base64.b64encode(b'\xffbytes').decode()}})
    assert base64.b64decode(out['body']['b64']) == b'\xffbytes'
    assert out['body']['content_type'] == 'application/octet-stream'
    img = _tool(UPLOAD_SPEC, 'PUT /image', f'{local.url}/v1')
    out = img.execute({'body': {'text': 'PNG?'}})
    assert out['body']['content_type'] == 'image/png'


def test_upload_size_cap_refuses_before_any_request(local, monkeypatch):
    from sajha.api_import.executor import APICallError
    monkeypatch.setenv('SAJHA_API_IMPORT_MAX_UPLOAD_BYTES', '2048')
    raw = _tool(UPLOAD_SPEC, 'PUT /raw', f'{local.url}/v1')
    big = base64.b64encode(b'x' * 4096).decode()
    with pytest.raises(APICallError, match='max_upload_bytes'):
        raw.execute({'body': {'content_base64': big}})
    up = _tool(UPLOAD_SPEC, 'POST /upload', f'{local.url}/v1')
    with pytest.raises(APICallError, match='max_upload_bytes'):          # several parts add up
        up.execute({'body': {'file': {'text': 'a' * 1200}, 'attachments': [{'text': 'b' * 1200}]}})
    assert not [r for r in local.requests if r['path'] in ('/v1/raw', '/v1/upload')]


def test_file_values_must_name_exactly_one_source(local):
    from sajha.api_import.executor import APICallError
    raw = _tool(UPLOAD_SPEC, 'PUT /raw', f'{local.url}/v1')
    with pytest.raises(APICallError, match='exactly one'):
        raw.execute({'body': {'text': 'a', 'content_base64': 'YQ=='}})
    with pytest.raises(APICallError, match='not valid base64'):
        raw.execute({'body': {'content_base64': '***'}})


def test_file_paths_only_under_the_file_roots(local, monkeypatch, tmp_path):
    import sajha.core.storage as storage
    from sajha.api_import.executor import APICallError
    from sajha.observability import caller
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    (tmp_path / 'uploads' / 'alice').mkdir(parents=True)
    (tmp_path / 'uploads' / 'alice' / 'report.csv').write_bytes(b'a,b\n1,2\n')
    (tmp_path / 'uploads' / 'bob').mkdir(parents=True)
    (tmp_path / 'uploads' / 'bob' / 'secret.txt').write_bytes(b'bob only')
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'application.yml').write_text('secret: 1')
    raw = _tool(UPLOAD_SPEC, 'PUT /raw', f'{local.url}/v1')
    with pytest.raises(APICallError, match='file_roots is empty'):
        raw.execute({'body': {'path': 'uploads/alice/report.csv'}})
    monkeypatch.setenv('SAJHA_API_IMPORT_FILE_ROOTS', 'uploads/{user}')
    token = caller._current.set(caller.Caller(user_id='alice'))
    try:
        out = raw.execute({'body': {'path': 'uploads/alice/report.csv'}})
        assert base64.b64decode(out['body']['b64']) == b'a,b\n1,2\n'
        for bad in ('uploads/bob/secret.txt', 'config/application.yml', '../etc/passwd', '/etc/passwd',
                    'uploads/alice/../bob/secret.txt'):
            with pytest.raises(APICallError):
                raw.execute({'body': {'path': bad}})
        (tmp_path / 'uploads' / 'alice' / 'link').symlink_to(tmp_path / 'uploads' / 'bob' / 'secret.txt')
        with pytest.raises(APICallError, match='outside'):
            raw.execute({'body': {'path': 'uploads/alice/link'}})
    finally:
        caller._current.reset(token)
    with pytest.raises(APICallError, match='not under'):                 # anonymous: no per-user root
        raw.execute({'body': {'path': 'uploads/alice/report.csv'}})


# ── pagination following ────────────────────────────────────────────────

def _list_spec(path, params=()):
    return _spec({path: {'get': {'operationId': 'list', 'parameters': [
        {'name': n, 'in': 'query', 'schema': {'type': 'integer' if n in ('page', 'offset', 'limit') else 'string'}}
        for n in params], 'responses': {'200': {'description': 'ok'}}}}})


def _paged(local, path, params, follow, **args):
    tool = _tool(_list_spec(path, params), f'GET {path}', f'{local.url}/v1', pagination={f'GET {path}': follow})
    return tool, tool.execute(args)


def test_pagination_is_off_by_default(local):
    tool = _tool(_list_spec('/linked', ['page']), 'GET /linked', f'{local.url}/v1')
    out = tool.execute({})
    assert len(out['body']) == 10 and out['next_page'].endswith('page=2') and 'pages' not in out
    assert 'paginate' not in tool.config['api_import']


@pytest.mark.parametrize('path,params,follow,body_rows', [
    ('/linked', ['page'], {'mode': 'link'}, lambda b: b),
    ('/nexturl', ['page'], {'mode': 'next_url', 'next_field': 'links.next'}, lambda b: b['data']),
    ('/cursor', ['cursor'], {'mode': 'cursor', 'next_field': 'meta.next_cursor'}, lambda b: b['items']),
    ('/paged', ['page'], {'mode': 'page', 'items': 'results'}, lambda b: b['results']),
    ('/offset', ['offset', 'limit'], {'mode': 'offset'}, lambda b: b),
])
def test_every_mode_collects_all_pages(local, path, params, follow, body_rows):
    tool, out = _paged(local, path, params, follow)
    assert body_rows(out['body']) == ROWS and out['items'] == 25 and out['truncated'] is False
    assert out['pages'] in (3, 4)                    # page/offset need one empty page to know they ended
    assert 'pages' in tool.config['outputSchema']['properties']


def test_page_cap_and_row_cap(local, monkeypatch):
    _, out = _paged(local, '/linked', ['page'], {'mode': 'link', 'max_pages': 2})
    assert out['pages'] == 2 and len(out['body']) == 20 and out['truncated'] is True
    assert out['next_page'].endswith('/v1/linked?page=3')
    _, out = _paged(local, '/cursor', ['cursor'], {'mode': 'cursor', 'next_field': 'meta.next_cursor', 'max_items': 15})
    assert out['items'] == 15 and out['truncated'] and out['next_arguments'] == {'cursor': '20'}
    monkeypatch.setenv('SAJHA_API_IMPORT_PAGINATION_MAX_PAGES', '1')    # the server cap wins
    local.requests.clear()
    _, out = _paged(local, '/paged', ['page'], {'mode': 'page', 'max_pages': 50})
    assert out['pages'] == 1 and out['truncated'] and out['next_arguments'] == {'page': 2}
    assert len([r for r in local.requests if r['path'] == '/v1/paged']) == 1


def test_a_next_link_the_guard_refuses_is_never_followed(local, monkeypatch):
    seen = []
    from sajha.api_import import fetch
    real = fetch.request

    def spy(method, url, **kw):
        seen.append(url)
        return real(method, url, **kw)
    monkeypatch.setattr(fetch, 'request', spy)
    _, out = _paged(local, '/evil', [], {'mode': 'link'})
    assert out['pages'] == 1 and out['truncated'] and 'SSRF guard' in out['stopped']
    assert 'next_page' not in out and not any('10.1.2.3' in u for u in seen)
    # another origin the guard would allow (localhost vs 127.0.0.1): not followed either
    seen.clear()
    _, out = _paged(local, '/elsewhere', [], {'mode': 'link'})
    assert out['pages'] == 1 and 'another origin' in out['stopped']
    assert not any('localhost' in u for u in seen)


def test_pagination_config_is_checked(local):
    from sajha.api_import import service
    from sajha.api_import.service import APIImportError
    base = {'kind': 'openapi', 'text': _list_spec('/cursor', ['cursor']), 'base_url': f'{local.url}/v1'}
    with pytest.raises(APIImportError, match='mode must be one of'):
        service.plan({**base, 'pagination': {'GET /cursor': {'mode': 'sideways'}}})
    with pytest.raises(APIImportError, match='next_field'):
        service.plan({**base, 'pagination': {'GET /cursor': {'mode': 'cursor'}}})
    with pytest.raises(APIImportError, match='not a query parameter'):
        service.plan({**base, 'pagination': {'GET /cursor': {'mode': 'page', 'page_param': 'p'}}})
    with pytest.raises(APIImportError, match='only for GET'):
        service.plan({'kind': 'openapi', 'text': UPLOAD_SPEC, 'base_url': f'{local.url}/v1',
                      'pagination': {'POST /upload': {'mode': 'link'}}})
    plan = service.plan({**base, 'pagination': {'GET /cursor': {'mode': 'cursor', 'next_field': 'meta.next_cursor'}}})
    assert plan['operations'][0]['paginate'] == {'mode': 'cursor', 'items': '', 'next_field': 'meta.next_cursor',
                                                 'cursor_param': 'cursor'}


def test_pagination_is_recorded_and_kept_on_reimport(local, tmp_path, monkeypatch):
    import sajha.core.storage as storage
    from sajha.api_import import service
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    base = {'kind': 'openapi', 'text': _list_spec('/linked', ['page']), 'base_url': f'{local.url}/v1', 'prefix': 'pg'}
    out = service.deploy({**base, 'selected': ['GET /linked'], 'pagination': {'GET /linked': {'mode': 'link'}}})
    assert out['success'], out
    assert service.reimport_request('pg')['pagination'] == {'GET /linked': {'mode': 'link', 'items': ''}}
    plan = service.plan(base)                                            # no pagination given: as recorded
    assert plan['operations'][0]['paginate']['mode'] == 'link'
    plan = service.plan({**base, 'pagination': {}})                      # given empty: off
    assert plan['operations'][0]['paginate'] is None


# ── Swagger 2.0 remote $ref ─────────────────────────────────────────────

def test_swagger_2_remote_refs_are_bundled_through_the_guard(local):
    from sajha.api_import import service
    url = f'{local.url}/specs/swagger_remote_2_0.yaml'
    plan = service.plan({'kind': 'openapi', 'url': url, 'prefix': 'orders'})
    fetched = [r['path'] for r in local.requests if r['path'].startswith('/specs/')]
    assert fetched.count('/specs/swagger_remote_common.yaml') == 1                  # fetched once, bundled
    ops = {o['key']: o for o in plan['operations']}
    assert not ops['GET /orders']['unsupported'] and not ops['POST /orders']['unsupported']
    limit = ops['GET /orders']['input_schema']['properties']['limit']                # remote #/parameters
    assert limit['minimum'] == 1 and limit['maximum'] == 100
    new = ops['POST /orders']['input_schema']['properties']['body']                  # remote #/definitions
    customer = new['properties']['customer']
    assert customer['properties']['name']['type'] == ['string', 'null']             # x-nullable converted
    assert customer['properties']['address']['properties']['city'] == {'type': 'string'}
    assert 'recursive' in customer['properties']['referredBy']['$comment']           # cycle cut
    req = service.ImportRequest.from_dict({'kind': 'openapi', 'url': url, 'prefix': 'orders'})
    p = service.build_plan(req)
    out = service.tool_config(p.op('GET /orders'), 'orders_list', p.ctx())['outputSchema']['properties']['body']
    assert out['items']['properties']['customer']['properties']['address']['properties']['city'] == {'type': 'string'}
    assert ops['GET /broken']['unsupported']                                          # a missing document


def test_swagger_2_remote_ref_to_a_refused_address_is_flagged(local):
    from sajha.api_import import service
    text = json.dumps({'swagger': '2.0', 'info': {'title': 'S', 'version': '1'}, 'host': 'api.example', 'paths': {
        '/a': {'get': {'operationId': 'a', 'responses': {'200': {'description': 'ok', 'schema': {
            '$ref': 'http://169.254.169.254/latest/defs.json#/definitions/X'}}}}}}})
    plan = service.plan({'kind': 'openapi', 'text': text, 'prefix': 'sref'})
    op = plan['operations'][0]
    assert op['unsupported'] and ('refused' in op['unsupported'] or 'non-public' in op['unsupported'])
