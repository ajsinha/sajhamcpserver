"""
API Import (sajha/api_import/): OpenAPI 3.0, Swagger 2.0, a GitHub-like subset with local,
relative and recursive $refs, and a GraphQL introspection result → tools, schemas and
annotations; the executor against a local fake server (path/query/header/body, every
auth kind, error mapping, timeouts, pagination); the SSRF guard on spec, $ref, server and
redirect URLs; deploy, re-import diff, name collisions, the max-tools cap; and the Studio
endpoints end to end over MCP.

Design: docs/architecture/API Import.md.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / 'tests' / 'fixtures' / 'api_import'
PETSTORE = (FIX / 'petstore_openapi_3_0.yaml').read_text()
SWAGGER = (FIX / 'petstore_swagger_2_0.json').read_text()
GRAPHQL = (FIX / 'library_graphql_introspection.json').read_text()


# ── a local fake API server ─────────────────────────────────────────────

class FakeAPI:
    def __init__(self):
        self.requests = []
        self.tokens_issued = 0
        self.reject_next_token = False
        self.pets = {1: {'id': 1, 'name': 'Rex', 'tag': 'dog'}, 2: {'id': 2, 'name': 'Tom', 'tag': None}}


def _handler(api: FakeAPI):
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
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b''
            api.requests.append({'method': self.command, 'path': u.path, 'query': parse_qs(u.query),
                                 'raw_query': u.query, 'headers': dict(self.headers), 'body': body})
            p = u.path
            if p.startswith('/specs/'):
                f = FIX / p[len('/specs/'):]
                if not f.exists():
                    return self._send(404, {'message': 'no spec'})
                return self._send(200, f.read_bytes(), 'application/yaml' if f.suffix == '.yaml' else 'application/json')
            if p == '/slow':
                time.sleep(2.5)
                return self._send(200, {'ok': True})
            if p == '/redirect-to-metadata':
                return self._send(302, b'', headers={'Location': 'http://169.254.169.254/latest/meta-data/'})
            if p == '/oauth/token':
                api.tokens_issued += 1
                return self._send(200, {'access_token': f'tok{api.tokens_issued}', 'token_type': 'bearer',
                                        'expires_in': 3600})
            if p == '/graphql':
                q = json.loads(body or b'{}')
                op = q.get('operationName')
                if op == 'Book':
                    return self._send(200, {'data': {'book': {'id': q['variables']['id'], 'title': 'Dune'}}})
                if op == 'Search':
                    return self._send(200, {'errors': [{'message': 'term too short'}], 'data': None})
                if 'IntrospectionQuery' in q.get('query', ''):
                    return self._send(200, json.loads(GRAPHQL))
                return self._send(200, {'data': {}})
            if p.startswith('/v1/'):
                auth = self.headers.get('Authorization', '')
                if p == '/v1/secure' and auth != 'Bearer tok2' and auth.startswith('Bearer tok'):
                    return self._send(401, {'message': 'expired'})
                if p == '/v1/limited':
                    return self._send(429, {'message': 'slow down'}, headers={'Retry-After': '7'})
                if p == '/v1/pets' and self.command == 'GET':
                    return self._send(200, list(api.pets.values()),
                                      headers={'Link': '<http://127.0.0.1/v1/pets?page=2>; rel="next"'})
                if p == '/v1/pets' and self.command == 'POST':
                    pet = json.loads(body)
                    pet['id'] = 3
                    return self._send(201, pet)
                if p.startswith('/v1/pets/'):
                    pid = p.rsplit('/', 1)[-1]
                    if self.command == 'DELETE':
                        return self._send(204)
                    if not pid.isdigit() or int(pid) not in api.pets:
                        return self._send(404, {'code': 404, 'message': f'pet {pid} not found'})
                    if self.command == 'PUT':
                        return self._send(200, {**json.loads(body), 'id': int(pid)})
                    return self._send(200, api.pets[int(pid)])
                return self._send(200, {'echo': p})
            if p.startswith('/api/v3/'):
                return self._send(200, {'login': 'octocat', 'id': 1})
            return self._send(404, {'message': 'not found'})

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle

    return H


@pytest.fixture(scope='module')
def fake():
    api = FakeAPI()
    class Quiet(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            pass                                   # a client that timed out closed the socket
    server = Quiet(('127.0.0.1', 0), _handler(api))
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    api.url = f'http://127.0.0.1:{server.server_address[1]}'
    yield api
    server.shutdown()


@pytest.fixture
def local(monkeypatch):
    """Loopback allowed (the fake server), everything else at its default."""
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOW_LOCALHOST', 'true')
    monkeypatch.delenv('SAJHA_API_IMPORT_ALLOWED_HOSTS', raising=False)
    monkeypatch.delenv('SAJHA_API_IMPORT_MAX_TOOLS', raising=False)


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """A temporary storage backend: tool configs and import records land in tmp_path."""
    import sajha.core.storage as storage
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    return tmp_path


class FakeRegistry:
    """The registry surface API Import uses (load, unregister, configs, errors)."""

    def __init__(self):
        self.tools, self.tool_configs, self.tool_errors, self._file_timestamps = {}, {}, {}, {}
        self._tools_lock = threading.RLock()

    def _config_rel(self, ref):
        return f'config/tools/{Path(str(ref)).stem}.json'

    def load_tool_from_config(self, ref):
        from sajha.api_import.executor import ImportedAPITool
        from sajha.core.storage import get_storage
        cfg = get_storage().read_json(self._config_rel(ref))
        self.tool_configs[cfg['name']] = cfg
        self.tools[cfg['name']] = ImportedAPITool(cfg)

    def unregister_tool(self, name):
        self.tools.pop(name, None)


def _plan(**kw):
    from sajha.api_import import service
    return service.plan(kw, kw.pop('_registry', None))


def _ops(plan):
    return {o['key']: o for o in plan['operations']}


def _config(text, key, auth=None, base_url='', kind='openapi', **extra):
    from sajha.api_import import service
    req = service.ImportRequest.from_dict({'kind': kind, 'text': text, 'base_url': base_url, 'auth': auth or {},
                                           **extra})
    p = service.build_plan(req)
    op = p.op(key)
    return service.tool_config(op, op['name'], p.ctx())


def _tool(config):
    from sajha.api_import.executor import ImportedAPITool
    return ImportedAPITool(config)


# ── parsing: OpenAPI 3.0 ────────────────────────────────────────────────

def test_petstore_operations_become_tools_with_schemas_and_annotations():
    plan = _plan(kind='openapi', text=PETSTORE)
    assert plan['api']['title'] == 'Swagger Petstore' and plan['api']['prefix'] == 'swagger_petstore'
    assert plan['api']['base_url'] == 'http://petstore.swagger.io/v1'           # server variable default
    ops = _ops(plan)
    assert set(ops) == {'GET /pets', 'POST /pets', 'GET /pets/{petId}', 'PUT /pets/{petId}',
                        'DELETE /pets/{petId}', 'POST /pets/{petId}/image'}
    assert ops['GET /pets']['name'] == 'swagger_petstore_list_pets'
    assert ops['GET /pets/{petId}']['name'] == 'swagger_petstore_show_pet_by_id'
    assert ops['GET /pets']['annotations']['readOnlyHint'] is True
    assert ops['DELETE /pets/{petId}']['annotations']['destructiveHint'] is True
    assert ops['PUT /pets/{petId}']['annotations']['idempotentHint'] is True
    assert ops['POST /pets']['annotations']['destructiveHint'] is False
    assert all(o['annotations']['openWorldHint'] for o in ops.values())
    assert 'multipart/form-data' in ops['POST /pets/{petId}/image']['unsupported']
    assert ops['POST /pets/{petId}/image']['selectable'] is False
    assert ops['GET /pets']['pagination'] == ['limit']

    schema = ops['GET /pets/{petId}']['input_schema']
    assert schema['required'] == ['petId'] and schema['additionalProperties'] is False
    assert schema['properties']['petId'] == {'type': 'integer', 'format': 'int64', 'description': 'The id of the pet'}
    assert 'X-Request-ID' in schema['properties']
    status = ops['GET /pets']['input_schema']['properties']['status']
    assert status['items']['enum'] == ['available', 'pending', 'sold']
    body = ops['POST /pets']['input_schema']['properties']['body']
    assert body['required'] == ['name'] and body['properties']['tag']['type'] == ['string', 'null']


def test_petstore_output_schema_envelope_keeps_read_only_fields():
    cfg = _config(PETSTORE, 'GET /pets/{petId}')
    out = cfg['outputSchema']
    assert out['type'] == 'object' and out['required'] == ['status', 'body']
    pet = out['properties']['body']
    assert pet['allOf'][1]['properties']['id']['readOnly'] is True
    assert cfg['implementation'] == 'sajha.api_import.executor.ImportedAPITool'
    assert cfg['api_import']['security'] == [['api_key']]
    assert cfg['title'] == 'Info for a specific pet'
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(cfg['inputSchema'])
    jsonschema.Draft202012Validator.check_schema(out)


def test_server_variables_are_checked_against_their_enum():
    plan = _plan(kind='openapi', text=PETSTORE, server_variables={'basePath': 'v2'})
    assert plan['api']['base_url'] == 'http://petstore.swagger.io/v2'
    plan = _plan(kind='openapi', text=PETSTORE, server_variables={'basePath': 'v9'})
    assert plan['api']['base_url'] == '' and any('must be one of' in w for w in plan['warnings'])


def test_filters_by_tag_method_path_and_the_name_override():
    assert set(_ops(_plan(kind='openapi', text=PETSTORE, filters={'tags': ['media']}))) == {'POST /pets/{petId}/image'}
    assert set(_ops(_plan(kind='openapi', text=PETSTORE, filters={'methods': ['delete']}))) == {'DELETE /pets/{petId}'}
    assert set(_ops(_plan(kind='openapi', text=PETSTORE, filters={'path': '/pets/*/image'}))) == {'POST /pets/{petId}/image'}
    plan = _plan(kind='openapi', text=PETSTORE, prefix='pets', names={'GET /pets': 'pets_all'})
    assert _ops(plan)['GET /pets']['name'] == 'pets_all'
    assert _ops(plan)['POST /pets']['name'] == 'pets_create_pets'


def test_bad_documents_are_refused_with_a_reason():
    from sajha.api_import.service import APIImportError
    with pytest.raises(APIImportError, match='not an OpenAPI 3.x or Swagger 2.0'):
        _plan(kind='openapi', text='{"openapi": "4.0"}')
    with pytest.raises(APIImportError, match='introspection'):
        _plan(kind='openapi', text=GRAPHQL)
    with pytest.raises(APIImportError, match='prefix'):
        _plan(kind='openapi', text=PETSTORE, prefix='Bad-Prefix')


# ── parsing: Swagger 2.0 ────────────────────────────────────────────────

def test_swagger_2_is_converted():
    plan = _plan(kind='openapi', text=SWAGGER, prefix='pet2')
    api = plan['api']
    assert api['base_url'] == 'https://petstore.swagger.io/v2' and api['spec_version'] == 'swagger 2.0'
    schemes = api['security_schemes']
    assert schemes['api_key'] == {'type': 'apiKey', 'description': '', 'in': 'header', 'name': 'api_key'}
    assert schemes['service_auth']['token_url'] == 'https://petstore.swagger.io/oauth/token'
    assert schemes['basic']['scheme'] == 'basic'
    ops = _ops(plan)
    assert len(ops) == 8
    assert 'multipart' in ops['POST /pet/{petId}/uploadImage']['unsupported']
    assert ops['POST /pet/{petId}']['body'] == 'application/x-www-form-urlencoded'
    find = _config(SWAGGER, 'GET /pet/findByStatus', prefix='pet2')
    status = find['api_import']['params'][0]
    assert (status['style'], status['explode']) == ('form', True)                # collectionFormat multi
    assert find['inputSchema']['properties']['status']['items']['enum'] == ['available', 'pending', 'sold']
    get = _config(SWAGGER, 'GET /pet/{petId}', prefix='pet2')
    assert get['inputSchema']['properties']['petId']['minimum'] == 1              # shared #/parameters
    pet = get['outputSchema']['properties']['body']
    assert pet['properties']['status']['type'] == ['string', 'null']              # x-nullable
    assert None in pet['properties']['status']['enum']
    assert pet['properties']['name']['examples'] == ['doggie']
    parent = pet['properties']['category']['properties']['parent']
    assert 'recursive reference' in parent['$comment']                            # cycle cut
    login = _config(SWAGGER, 'GET /user/login', prefix='pet2')
    assert login['inputSchema']['properties']['password']['format'] == 'password'


# ── parsing: GitHub-like subset with remote/relative $refs ──────────────

def test_github_subset_resolves_relative_documents_through_the_guard(fake, local):
    plan = _plan(kind='openapi', url=f'{fake.url}/specs/github_subset_openapi.yaml', prefix='gh')
    assert plan['api']['base_url'] == f'{fake.url}/api/v3'                       # relative server
    ops = _ops(plan)
    assert ops['GET /repos/{owner}/{repo}']['name'] == 'gh_repos_get'
    assert ops['GET /repos/{owner}/{repo}/issues']['name'] == 'gh_issues_list_for_repo'
    assert ops['GET /repos/{owner}/{repo}/issues']['pagination'] == ['per_page', 'page']
    assert not any(o['unsupported'] for o in ops.values())
    cfg = _config('', 'GET /user', url=f'{fake.url}/specs/github_subset_openapi.yaml', prefix='gh')
    user = cfg['outputSchema']['properties']['body']
    assert user['required'] == ['login', 'id'] and user['properties']['email']['type'] == ['string', 'null']
    repo = _config('', 'GET /repos/{owner}/{repo}', url=f'{fake.url}/specs/github_subset_openapi.yaml', prefix='gh')
    body = repo['outputSchema']['properties']['body']
    assert body['properties']['owner']['properties']['login'] == {'type': 'string'}
    assert 'recursive' in body['properties']['parent']['$comment']
    assert repo['inputSchema']['required'] == ['owner', 'repo']
    assert repo['api_import']['security'] == [['bearerAuth']]
    meta = _config('', 'GET /meta', url=f'{fake.url}/specs/github_subset_openapi.yaml', prefix='gh')
    assert meta['api_import']['security'] == []


def test_uploaded_spec_with_relative_refs_flags_the_operations():
    text = (FIX / 'github_subset_openapi.yaml').read_text()
    plan = _plan(kind='openapi', text=text, prefix='gh', base_url='https://api.github.com')
    ops = _ops(plan)
    assert 'relative' in ops['GET /user']['unsupported']
    assert not ops['GET /meta']['unsupported']


# ── parsing: GraphQL ────────────────────────────────────────────────────

def test_graphql_introspection_becomes_query_and_mutation_tools():
    plan = _plan(kind='graphql', text=GRAPHQL, base_url='https://library.example/graphql')
    ops = _ops(plan)
    assert set(ops) == {'query book', 'query books', 'query search', 'mutation addBook', 'mutation deleteBook'}
    assert ops['query book']['name'] == 'graphql_book'
    assert ops['query book']['annotations']['readOnlyHint'] is True
    assert ops['mutation deleteBook']['annotations']['destructiveHint'] is True
    add = _config(GRAPHQL, 'mutation addBook', kind='graphql', base_url='https://library.example/graphql')
    inp = add['inputSchema']['properties']['input']
    assert inp['required'] == ['title'] and inp['properties']['genre']['enum'] == ['FICTION', 'HISTORY', 'SCIENCE']
    assert add['inputSchema']['required'] == ['input']
    doc = add['api_import']['graphql']['document']
    assert doc.startswith('mutation AddBook($input: BookInput!)') and 'addBook(input: $input)' in doc
    books = _config(GRAPHQL, 'query books', kind='graphql', base_url='https://library.example/graphql')
    assert books['inputSchema'].get('required') is None                          # defaults / nullable
    doc = books['api_import']['graphql']['document']
    assert 'author { id name }' in doc and 'reviews' not in doc                  # depth 2; required args skipped
    search = _config(GRAPHQL, 'query search', kind='graphql', base_url='https://library.example/graphql')
    assert '... on Book' in search['api_import']['graphql']['document']


# ── executor against the fake server ───────────────────────────────────

def test_executor_builds_path_query_header_and_body(fake, local, monkeypatch):
    monkeypatch.setenv('PETS_KEY', 'k-123')
    auth = {'api_key': {'type': 'apiKey', 'value_ref': 'env:PETS_KEY'}}
    t = _tool(_config(PETSTORE, 'GET /pets', auth=auth, base_url=f'{fake.url}/v1'))
    out = t.execute({'limit': 5, 'status': ['available', 'sold']})
    assert out['status'] == 200 and out['body'][0]['name'] == 'Rex'
    assert out['next_page'] == 'http://127.0.0.1/v1/pets?page=2'
    req = fake.requests[-1]
    assert req['query'] == {'limit': ['5'], 'status': ['available', 'sold']}
    assert req['headers']['X-API-Key'] == 'k-123'
    t = _tool(_config(PETSTORE, 'GET /pets/{petId}', auth=auth, base_url=f'{fake.url}/v1'))
    assert t.execute({'petId': 2, 'X-Request-ID': 'r1'})['body']['name'] == 'Tom'
    assert fake.requests[-1]['path'] == '/v1/pets/2' and fake.requests[-1]['headers']['X-Request-ID'] == 'r1'
    t = _tool(_config(PETSTORE, 'POST /pets', auth=auth, base_url=f'{fake.url}/v1'))
    out = t.execute({'body': {'name': 'Kit', 'tag': 'cat'}})
    assert out == {'status': 201, 'body': {'name': 'Kit', 'tag': 'cat', 'id': 3}}
    assert fake.requests[-1]['headers']['Content-Type'] == 'application/json'
    t = _tool(_config(PETSTORE, 'DELETE /pets/{petId}', auth=auth, base_url=f'{fake.url}/v1'))
    assert t.execute({'petId': 1}) == {'status': 204, 'body': None}


def test_executor_form_bodies_and_path_encoding(fake, local):
    t = _tool(_config(SWAGGER, 'POST /pet/{petId}', base_url=f'{fake.url}/v1', prefix='pet2'))
    t.execute({'petId': 7, 'body': {'name': 'a b', 'status': 'sold'}})
    req = fake.requests[-1]
    assert req['path'] == '/v1/pet/7' and req['body'] == b'name=a+b&status=sold'
    assert req['headers']['Content-Type'] == 'application/x-www-form-urlencoded'
    cfg = _config(SWAGGER, 'GET /pet/{petId}', base_url=f'{fake.url}/v1', prefix='pet2')
    cfg['inputSchema']['properties']['petId'] = {'type': 'string'}
    _tool(cfg).execute({'petId': '../admin?x=1'})
    assert fake.requests[-1]['path'] == '/v1/pet/..%2Fadmin%3Fx%3D1'


@pytest.mark.parametrize('kind,cfg,check', [
    ('query key', {'type': 'apiKey', 'in': 'query', 'name': 'key', 'value_ref': 'env:T_SECRET'},
     lambda r: r['query']['key'] == ['s3cret']),
    ('cookie key', {'type': 'apiKey', 'in': 'cookie', 'name': 'sid', 'value_ref': 'env:T_SECRET'},
     lambda r: r['headers']['Cookie'] == 'sid=s3cret'),
    ('bearer', {'type': 'bearer', 'token_ref': 'env:T_SECRET'},
     lambda r: r['headers']['Authorization'] == 'Bearer s3cret'),
    ('basic', {'type': 'basic', 'username': 'ann', 'password_ref': 'env:T_SECRET'},
     lambda r: r['headers']['Authorization'] == 'Basic YW5uOnMzY3JldA=='),
])
def test_executor_injects_each_credential_kind(fake, local, monkeypatch, kind, cfg, check):
    monkeypatch.setenv('T_SECRET', 's3cret')
    config = _config(PETSTORE, 'GET /pets', auth={'custom': cfg}, base_url=f'{fake.url}/v1')
    assert config['api_import']['auth']['custom']['global'] is True       # not declared by the spec
    assert 's3cret' not in json.dumps(config)                              # references only
    _tool(config).execute({})
    assert check(fake.requests[-1]), fake.requests[-1]


def test_oauth_client_credentials_caches_and_retries_once_on_401(fake, local, monkeypatch):
    from sajha.api_import import executor
    executor._TOKENS.clear()
    monkeypatch.setenv('CC_SECRET', 'cs')
    auth = {'svc': {'type': 'oauth2_client_credentials', 'token_url': f'{fake.url}/oauth/token',
                    'client_id': 'sajha', 'client_secret_ref': 'env:CC_SECRET', 'scopes': 'pets'}}
    cfg = _config(PETSTORE, 'GET /pets', auth=auth, base_url=f'{fake.url}/v1')
    cfg['api_import']['path'] = '/secure'
    before = fake.tokens_issued
    out = _tool(cfg).execute({})            # tok1 is refused (401), tok2 is accepted
    assert out['status'] == 200 and fake.tokens_issued == before + 2
    token_req = [r for r in fake.requests if r['path'] == '/oauth/token'][-1]
    assert b'grant_type=client_credentials' in token_req['body'] and b'scope=pets' in token_req['body']
    _tool(cfg).execute({})                   # cached
    assert fake.tokens_issued == before + 2


def test_errors_are_mapped_and_secrets_masked(fake, local, monkeypatch):
    from sajha.api_import.executor import APICallError
    monkeypatch.setenv('PETS_KEY', 'k-123456789')
    auth = {'api_key': {'type': 'apiKey', 'value_ref': 'env:PETS_KEY'}}
    t = _tool(_config(PETSTORE, 'GET /pets/{petId}', auth=auth, base_url=f'{fake.url}/v1'))
    with pytest.raises(APICallError) as e:
        t.execute({'petId': 99})
    assert e.value.status == 404 and 'HTTP 404' in str(e.value) and 'pet 99 not found' in str(e.value)
    cfg = _config(PETSTORE, 'GET /pets', base_url=f'{fake.url}/v1')
    cfg['api_import']['path'] = '/limited'
    with pytest.raises(APICallError, match=r'retry after 7s'):
        _tool(cfg).execute({})
    cfg = _config(PETSTORE, 'GET /pets', base_url=fake.url, timeout_seconds=1)
    cfg['api_import']['path'] = '/slow'
    started = time.monotonic()
    with pytest.raises(APICallError, match='timed out after 1s'):
        _tool(cfg).execute({})
    assert time.monotonic() - started < 2.4
    cfg = _config(PETSTORE, 'GET /pets', auth={'api_key': {'type': 'apiKey', 'value_ref': 'env:NOPE_UNSET'}},
                  base_url=f'{fake.url}/v1')
    with pytest.raises(APICallError, match='resolves to nothing'):
        _tool(cfg).execute({})


def test_rate_limit_per_api(fake, local):
    from sajha.api_import import executor
    from sajha.api_import.executor import APICallError
    executor._CALLS.clear()
    cfg = _config(PETSTORE, 'GET /pets', base_url=f'{fake.url}/v1', rate_limit_per_minute=2, prefix='ratelim')
    t = _tool(cfg)
    t.execute({})
    t.execute({})
    with pytest.raises(APICallError, match='rate limit for API ratelim'):
        t.execute({})


def test_graphql_executor(fake, local):
    from sajha.api_import.executor import APICallError
    t = _tool(_config(GRAPHQL, 'query book', kind='graphql', base_url=f'{fake.url}/graphql'))
    assert t.execute({'id': '42'}) == {'status': 200, 'body': {'id': '42', 'title': 'Dune'}}
    sent = json.loads(fake.requests[-1]['body'])
    assert sent['variables'] == {'id': '42'} and sent['operationName'] == 'Book'
    t = _tool(_config(GRAPHQL, 'query search', kind='graphql', base_url=f'{fake.url}/graphql'))
    with pytest.raises(APICallError, match='term too short'):
        t.execute({'term': 'x'})


def test_graphql_endpoint_introspection(fake, local):
    plan = _plan(kind='graphql', url=f'{fake.url}/graphql', prefix='lib')
    assert len(plan['operations']) == 5 and plan['api']['base_url'] == f'{fake.url}/graphql'


def test_input_validation_is_the_base_tool_json_schema(fake, local):
    from sajha.tools.base_mcp_tool import ToolArgumentError
    t = _tool(_config(PETSTORE, 'GET /pets/{petId}', base_url=f'{fake.url}/v1'))
    for bad, why in (({}, 'petId'), ({'petId': 'one'}, 'integer'), ({'petId': 1, 'extra': 1}, 'extra')):
        with pytest.raises(ToolArgumentError, match=why):
            t.validate_arguments(bad)
    t = _tool(_config(PETSTORE, 'GET /pets', base_url=f'{fake.url}/v1'))
    with pytest.raises(ToolArgumentError):
        t.validate_arguments({'status': ['lost']})
    with pytest.raises(ToolArgumentError):
        t.validate_arguments({'limit': 500})
    assert t.validate_arguments({'limit': 10, 'status': ['sold']})


# ── SSRF guard ──────────────────────────────────────────────────────────

def test_ssrf_guard_on_spec_urls(fake, monkeypatch):
    from sajha.api_import.service import APIImportError
    monkeypatch.delenv('SAJHA_API_IMPORT_ALLOW_LOCALHOST', raising=False)
    with pytest.raises(APIImportError, match='non-public address'):
        _plan(kind='openapi', url=f'{fake.url}/specs/petstore_openapi_3_0.yaml')
    for bad, why in (('http://169.254.169.254/latest/meta-data/', 'non-public'),
                     ('file:///etc/passwd', 'http or https'), ('http://user:pw@example.com/x', 'credentials'),
                     ('http://10.0.0.5/spec.json', 'non-public')):
        with pytest.raises(APIImportError, match=why):
            _plan(kind='openapi', url=bad)
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOW_PRIVATE_NETWORKS', 'true')
    with pytest.raises(APIImportError, match='non-public'):              # never link-local
        _plan(kind='openapi', url='http://169.254.169.254/latest/meta-data/')
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOWED_HOSTS', 'api.example.com,*.corp.example')
    with pytest.raises(APIImportError, match='allowed_hosts'):
        _plan(kind='openapi', url='https://evil.example.net/spec.json')


def test_ssrf_guard_on_server_urls_redirects_and_refs(fake, local, store_dir):
    from sajha.api_import import service
    from sajha.api_import.executor import APICallError
    from sajha.api_import.service import APIImportError
    cfg = _config(PETSTORE, 'GET /pets', base_url='http://169.254.169.254/v1')
    with pytest.raises(APICallError, match='SSRF guard'):
        _tool(cfg).execute({})
    with pytest.raises(APIImportError, match='base URL refused'):
        service.deploy({'kind': 'openapi', 'text': PETSTORE, 'prefix': 'ssrf', 'base_url': 'http://192.168.1.10/v1',
                        'selected': ['GET /pets']}, FakeRegistry())
    cfg = _config(PETSTORE, 'GET /pets', base_url=fake.url)
    cfg['api_import']['path'] = '/redirect-to-metadata'
    with pytest.raises(APICallError, match='SSRF guard'):
        _tool(cfg).execute({})
    spec = PETSTORE.replace("$ref: '#/components/schemas/NewPet'", "$ref: 'http://10.1.2.3/evil.yaml#/X'", 1)
    plan = _plan(kind='openapi', text=spec, base_url=f'{fake.url}/v1')
    assert 'refused' in _ops(plan)['POST /pets']['unsupported']


def test_literal_secrets_are_refused():
    from sajha.api_import.service import APIImportError
    with pytest.raises(APIImportError, match='secret reference'):
        _plan(kind='openapi', text=PETSTORE, auth={'api_key': {'type': 'apiKey', 'value_ref': 'plain-key'}})


# ── deploy, re-import diff, collisions, cap ─────────────────────────────

def test_deploy_reimport_diff_and_remove(fake, local, store_dir):
    from sajha.api_import import service, store
    reg = FakeRegistry()
    base = {'kind': 'openapi', 'text': PETSTORE, 'prefix': 'pets', 'base_url': f'{fake.url}/v1'}
    keys = ['GET /pets', 'GET /pets/{petId}', 'DELETE /pets/{petId}']
    out = service.deploy({**base, 'selected': keys}, reg, 'admin')
    assert out['success'] and sorted(out['deployed']) == ['pets_delete_pet', 'pets_list_pets', 'pets_show_pet_by_id']
    assert (store_dir / 'config' / 'tools' / 'pets_list_pets.json').exists()
    assert reg.tools['pets_show_pet_by_id'].execute({'petId': 1})['body']['name'] == 'Rex'
    record = store.load('pets')
    assert set(record['operations']) == set(keys) and record['updated_by'] == 'admin'

    plan = service.plan(base, reg)
    assert plan['reimport'] and {o['key']: o['status'] for o in plan['operations'] if o['status'] != 'new'} == \
        {k: 'unchanged' for k in keys}
    assert all(o['selected'] == (o['key'] in keys) for o in plan['operations'])

    # version 2: listPets gains a parameter, deletePet disappears, a new operation appears
    v2 = PETSTORE.replace("        - name: status\n          in: query\n",
                          "        - name: owner\n          in: query\n          schema:\n            type: string\n"
                          "        - name: status\n          in: query\n", 1)
    v2 = v2.replace("    delete:\n      summary: Delete a pet\n      operationId: deletePet\n      tags: [pets]\n"
                    "      responses:\n        '204':\n          description: Deleted\n", '')
    v2 = v2.replace('  /pets/{petId}/image:', "  /health:\n    get:\n      operationId: health\n      responses:\n"
                                              "        '200':\n          description: OK\n  /pets/{petId}/image:")
    plan = service.plan({**base, 'text': v2}, reg)
    status = {o['key']: o['status'] for o in plan['operations']}
    assert status['GET /pets'] == 'changed' and status['GET /pets/{petId}'] == 'unchanged'
    assert status['GET /health'] == 'new'
    assert plan['removed'] == [{'key': 'DELETE /pets/{petId}', 'name': 'pets_delete_pet', 'status': 'removed'}]

    out = service.deploy({**base, 'text': v2, 'selected': ['GET /pets', 'GET /health'],
                          'remove': ['DELETE /pets/{petId}']}, reg)
    assert out['updated'] == ['pets_list_pets'] and out['deployed'] == ['pets_health']
    assert out['removed'] == ['pets_delete_pet'] and 'pets_delete_pet' not in reg.tools
    assert not (store_dir / 'config' / 'tools' / 'pets_delete_pet.json').exists()
    assert 'owner' in reg.tools['pets_list_pets'].input_schema['properties']
    assert set(store.load('pets')['operations']) == {'GET /pets', 'GET /pets/{petId}', 'GET /health'}

    out = service.delete_api('pets', reg)
    assert sorted(out['removed']) == ['pets_health', 'pets_list_pets', 'pets_show_pet_by_id']
    assert not reg.tools and store.load('pets') is None


def test_name_collisions_are_flagged_and_never_overwritten(fake, local, store_dir):
    from sajha.api_import import service
    from sajha.api_import.service import APIImportError
    reg = FakeRegistry()
    reg.tools['pets_list_pets'] = object()          # a tool that is not this import's
    base = {'kind': 'openapi', 'text': PETSTORE, 'prefix': 'pets', 'base_url': f'{fake.url}/v1'}
    op = _ops(service.plan(base, reg))['GET /pets']
    assert op['conflict'] == 'another tool' and not op['selectable'] and not op['selected']
    with pytest.raises(APIImportError, match='already used'):
        service.deploy({**base, 'selected': ['GET /pets']}, reg)
    out = service.deploy({**base, 'selected': ['GET /pets'], 'names': {'GET /pets': 'pets_list_all'}}, reg)
    assert out['deployed'] == ['pets_list_all'] and reg.tools['pets_list_pets'] is not None
    # two operations proposing one name are told apart
    plan = service.plan({**base, 'prefix': 'dup', 'names': {'GET /pets': 'dup_same', 'POST /pets': 'dup_same'}}, reg)
    assert sorted(o['name'] for o in plan['operations'] if o['name'].startswith('dup_same')) == ['dup_same', 'dup_same_2']
    with pytest.raises(APIImportError, match='tool name'):
        service.plan({**base, 'names': {'GET /pets': 'Bad Name'}}, reg)


def test_max_tools_cap(fake, local, store_dir, monkeypatch):
    from sajha.api_import import service
    from sajha.api_import.service import APIImportError
    monkeypatch.setenv('SAJHA_API_IMPORT_MAX_TOOLS', '2')
    base = {'kind': 'openapi', 'text': PETSTORE, 'prefix': 'capped', 'base_url': f'{fake.url}/v1'}
    plan = service.plan(base, FakeRegistry())
    assert plan['max_tools'] == 2 and sum(o['selected'] for o in plan['operations']) == 2
    assert any('at most 2' in w for w in plan['warnings'])
    with pytest.raises(APIImportError, match='at most 2'):
        service.deploy({**base, 'selected': ['GET /pets', 'POST /pets', 'GET /pets/{petId}']}, FakeRegistry())


def test_unsupported_operations_cannot_be_deployed(fake, local, store_dir):
    from sajha.api_import import service
    from sajha.api_import.service import APIImportError
    with pytest.raises(APIImportError, match='cannot be imported'):
        service.deploy({'kind': 'openapi', 'text': PETSTORE, 'prefix': 'pets', 'base_url': f'{fake.url}/v1',
                        'selected': ['POST /pets/{petId}/image']}, FakeRegistry())


def test_test_call_without_deploying(fake, local, store_dir):
    from sajha.api_import import service
    base = {'kind': 'openapi', 'text': PETSTORE, 'prefix': 'pets', 'base_url': f'{fake.url}/v1'}
    out = service.test_call({**base, 'operation': 'GET /pets/{petId}', 'arguments': {'petId': 1}})
    assert out['success'] and out['result']['body']['name'] == 'Rex'
    out = service.test_call({**base, 'operation': 'GET /pets/{petId}', 'arguments': {}})
    assert not out['success'] and 'petId' in out['error']
    out = service.test_call({**base, 'operation': 'GET /pets/{petId}', 'arguments': {'petId': 404}})
    assert not out['success'] and out['status'] == 404
    assert not (store_dir / 'config' / 'tools').exists()


# ── Studio endpoints, end to end over MCP ───────────────────────────────

@pytest.fixture(scope='module')
def app_client():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        assert r.status_code == 200
        yield c, {'Authorization': f"Bearer {r.json()['token']}"}
        for f in list((ROOT / 'config' / 'tools').glob('zz_test_pets_*.json')):
            f.unlink()
        rec = ROOT / 'config' / 'api_imports' / 'zz_test_pets.json'
        if rec.exists():
            rec.unlink()
        if rec.parent.exists() and not any(rec.parent.iterdir()):
            rec.parent.rmdir()


def test_studio_import_deploy_call_over_mcp_and_delete(app_client, fake, local):
    c, headers = app_client
    base = {'kind': 'openapi', 'url': f'{fake.url}/specs/petstore_openapi_3_0.yaml', 'prefix': 'zz_test_pets',
            'base_url': f'{fake.url}/v1'}
    r = c.post('/admin/studio/api-import/parse', json=base, headers=headers)
    assert r.status_code == 200 and r.json()['success'], r.text
    assert len(r.json()['operations']) == 6
    r = c.post('/admin/studio/api-import/test', json={**base, 'operation': 'GET /pets/{petId}',
                                                      'arguments': {'petId': 2}}, headers=headers)
    assert r.json()['result']['body']['name'] == 'Tom', r.text
    keys = ['GET /pets', 'GET /pets/{petId}', 'DELETE /pets/{petId}']
    r = c.post('/admin/studio/api-import/deploy', json={**base, 'selected': keys}, headers=headers)
    assert r.status_code == 200 and r.json()['success'], r.text
    from sajha.app import tools_registry
    assert 'zz_test_pets_show_pet_by_id' in tools_registry.tools

    listed, cursor = {}, None
    while True:
        r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list',
                                 'params': {'cursor': cursor} if cursor else {}}, headers=headers)
        listed.update({t['name']: t for t in r.json()['result']['tools']})
        cursor = r.json()['result'].get('nextCursor')
        if not cursor:
            break
    assert listed['zz_test_pets_delete_pet']['annotations']['destructiveHint'] is True
    assert listed['zz_test_pets_list_pets']['annotations']['readOnlyHint'] is True
    r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
        'name': 'zz_test_pets_show_pet_by_id', 'arguments': {'petId': 1}}}, headers=headers)
    res = r.json()['result']
    assert res['structuredContent'] == {'status': 200, 'body': {'id': 1, 'name': 'Rex', 'tag': 'dog'}}
    r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
        'name': 'zz_test_pets_show_pet_by_id', 'arguments': {'petId': 'x'}}}, headers=headers)
    assert r.json()['result']['isError'] is True

    apis = c.get('/api/studio/api-import/apis', headers=headers).json()['apis']
    assert any(a['api_id'] == 'zz_test_pets' and a['loaded'] == 3 for a in apis)
    r = c.post('/admin/studio/api-import/deploy', json={**base, 'selected': keys}, headers=headers)
    assert sorted(r.json()['updated']) == sorted(['zz_test_pets_list_pets', 'zz_test_pets_show_pet_by_id',
                                                  'zz_test_pets_delete_pet'])
    # Studio's own delete knows imported tools
    r = c.post('/admin/studio/delete', json={'tool_name': 'zz_test_pets_delete_pet'}, headers=headers)
    assert r.status_code == 200 and r.json()['success'], r.text
    r = c.post('/admin/studio/api-import/delete', json={'api_id': 'zz_test_pets'}, headers=headers)
    assert r.json()['success'] and sorted(r.json()['removed']) == ['zz_test_pets_list_pets',
                                                                   'zz_test_pets_show_pet_by_id']
    assert 'zz_test_pets_list_pets' not in tools_registry.tools
    assert not list((ROOT / 'config' / 'tools').glob('zz_test_pets_*.json'))


def test_studio_page_and_admin_only(app_client):
    c, headers = app_client
    page = c.get('/studio/api-import', headers=headers)
    assert page.status_code == 200 and 'Import an API' in page.text and '/admin/studio/api-import' in page.text
    assert 'href="/studio/api-import"' in c.get('/studio', headers=headers).text
    r = c.post('/admin/studio/api-import/parse', json={'kind': 'openapi', 'text': PETSTORE}, follow_redirects=False)
    assert r.status_code in (302, 401, 403)
    r = c.post('/admin/studio/api-import/parse', json={'kind': 'openapi', 'text': '{}'}, headers=headers)
    assert r.status_code == 400 and not r.json()['success']


# ── CLI: sajha studio import-openapi ────────────────────────────────────

def test_cli_import_openapi(monkeypatch, capsys, tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / 'clientsdk'))
    from sajha.api_import import service
    import importlib
    cli = importlib.import_module('sajhaclient.cli.main')
    monkeypatch.setenv('SAJHA_CONFIG_DIR', str(tmp_path / 'cfg'))
    calls = []

    def fake_request(self, method, path, body=None, params=None):
        calls.append((method, path, body))
        if path.endswith('/parse'):
            return service.plan(body)
        return {'success': True, 'message': f"{body['prefix']}: {len(body['selected'])} added", 'failed': []}
    monkeypatch.setattr(cli.Context, 'request', fake_request)
    spec = tmp_path / 'petstore.yaml'
    spec.write_text(PETSTORE)
    code = cli.main(['studio', 'import-openapi', str(spec), '--dry-run', '--prefix', 'pets', '--tag', 'pets'])
    out = capsys.readouterr().out
    assert code == 0 and 'pets_list_pets' in out and 'GET /pets' in out and 'pets_upload_pet_image' not in out
    assert calls[-1][2]['text'] == PETSTORE and calls[-1][2]['filters']['tags'] == ['pets']
    code = cli.main(['studio', 'import-openapi', str(spec), '--prefix', 'pets', '--select', 'GET /pets',
                     '--select', 'DELETE /pets/{petId}'])
    assert code == 0 and 'pets: 2 added' in capsys.readouterr().out
    assert calls[-1][1] == '/admin/studio/api-import/deploy'
    assert calls[-1][2]['selected'] == ['GET /pets', 'DELETE /pets/{petId}']
    assert cli.main(['studio', 'import-openapi', str(spec), '--select', 'GET /nope']) == 2


def test_connected_account_binding(fake, local):
    from types import SimpleNamespace
    from sajha.api_import import service
    from sajha.api_import.executor import APICallError
    if not service.connected_accounts_available():
        pytest.skip('connected accounts are not installed')
    from sajha.accounts import injection
    cfg = _config(PETSTORE, 'GET /pets', auth={'me': {'type': 'connected_account', 'provider': 'github',
                                                      'scopes': 'repo'}}, base_url=f'{fake.url}/v1')
    assert cfg['auth'] == {'connected_account': 'github', 'scopes': ['repo']}
    tool = _tool(cfg)
    with pytest.raises(APICallError, match='github'):
        tool.execute({})
    reset = injection._tokens.set({'github': SimpleNamespace(authorization=lambda: 'Bearer user-tok')})
    try:
        tool.execute({})
    finally:
        injection._tokens.reset(reset)
    assert fake.requests[-1]['headers']['Authorization'] == 'Bearer user-tok'
    from sajha.api_import.service import APIImportError
    with pytest.raises(APIImportError, match='not a connected-accounts provider'):
        _plan(kind='openapi', text=PETSTORE, auth={'me': {'type': 'connected_account', 'provider': 'nope_x'}})
