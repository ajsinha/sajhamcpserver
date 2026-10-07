"""The tool test harness: JSONPath, assertions, cases, cassettes (urllib, requests, httpx; record and
replay against a local HTTP server, strict replay, secret redaction), the runner, JUnit XML and the CLI."""

import json
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from sajha.quality import assertions as A, jsonpath
from sajha.quality.cases import CaseError, TestCase, load_suite, parse_case, select
from sajha.quality.cassette import Cassette, CassetteMiss, redact_url
from sajha.quality.runner import render_junit, run_case, run_cases, summarise
from sajha.tools.base_mcp_tool import BaseMCPTool


# ── JSONPath ────────────────────────────────────────────────────────

DOC = {'a': {'b': [{'c': 1, 'n': 'x'}, {'c': 2}], 'k-1': 'v'}, 'list': [1, 2, 3], 'deep': {'c': 9}}


@pytest.mark.parametrize('path,expected', [
    ('$', [DOC]), ('$.a.b[0].c', [1]), ('$.a.b[-1].c', [2]), ('$.a.b[*].c', [1, 2]),
    ("$['a']['k-1']", ['v']), ('$..c', [1, 2, 9]), ('$.list.*', [1, 2, 3]), ('a.b[1]', [{'c': 2}]),
    ('$.missing', []), ('$.list[7]', []),
])
def test_jsonpath(path, expected):
    assert sorted(map(json.dumps, jsonpath.find(DOC, path))) == sorted(map(json.dumps, expected))


def test_jsonpath_rejects_filters():
    with pytest.raises(jsonpath.JSONPathError):
        jsonpath.parse('$.a[?(@.c > 1)]')


# ── assertions ──────────────────────────────────────────────────────

RES = {'price': 101.004, 'symbol': 'AAPL', 'tags': ['x', 'y'], 'nested': {'a': 1, 'b': {'c': 2}}, 'items': [{'v': 1}, {'v': 5}]}
SCHEMA = {'type': 'object', 'properties': {'price': {'type': 'number'}}, 'required': ['price']}


@pytest.mark.parametrize('spec,ok', [
    ({'path': '$.price', 'equals': 101, 'tolerance': 0.01}, True),
    ({'path': '$.price', 'equals': 101}, False),
    ({'path': '$.symbol', 'regex': '^[A-Z]+$'}, True),
    ({'path': '$.tags', 'contains': 'y'}, True),
    ({'path': '$.nested', 'contains': {'b': {'c': 2}}}, True),
    ({'path': '$.nested', 'contains': {'a': 2}}, False),
    ({'path': '$.items[*].v', 'min': 1, 'max': 5}, True),
    ({'path': '$.items[*].v', 'max': 4}, False),
    ({'path': '$.tags', 'length': 2}, True),
    ({'path': '$.symbol', 'type': 'string'}, True),
    ({'path': '$.price', 'type': 'integer'}, False),
    ({'path': '$.nope', 'exists': False}, True),
    ({'path': '$.nope', 'equals': 1}, False),
    ({'path': '$.symbol', 'not_equals': 'MSFT'}, True),
    ({'schema': SCHEMA}, True),
    ({'schema': {'type': 'object', 'required': ['volume']}}, False),
    ({'schema': 'output'}, True),
    ({'latency_ms': 100}, True),
    ({'latency_ms': 10}, False),
])
def test_assertions(spec, ok):
    assert A.check(spec, RES, latency_ms=50, output_schema=SCHEMA).ok is ok


@pytest.mark.parametrize('spec', [{}, {'path': '$.a'}, {'path': '$.a', 'equal': 1}, {'schema': 3},
                                  {'path': '$.a', 'regex': '('}, {'latency_ms': 'fast'}])
def test_malformed_assertions_are_rejected(spec):
    with pytest.raises(Exception):
        A.validate_spec(spec)


def test_failure_messages_say_what_differs():
    o = A.check({'path': '$.price', 'equals': 5}, RES)
    assert not o.ok and '101.004' in o.message and '5' in o.message


def test_json_string_results_are_parsed():
    assert A.normalise_result('{"a": 1}') == {'a': 1}
    assert A.normalise_result('plain') == 'plain'


# ── cases ───────────────────────────────────────────────────────────

def test_case_parsing_and_validation():
    c = parse_case('t', {'name': 'n', 'arguments': {'x': 1}, 'expect': {'path': '$.x', 'equals': 1}, 'tags': 'smoke'})
    assert c.expect == [{'path': '$.x', 'equals': 1}] and c.tags == ['smoke']
    with pytest.raises(CaseError):
        parse_case('t', {'name': 'n', 'expect': [{'path': '$.x'}]})
    with pytest.raises(CaseError):
        parse_case('t', {'name': 'n', 'arguments': [1]})


def test_load_suite_reads_files_and_tool_configs(tmp_path):
    (tmp_path / 'a.yaml').write_text('tool: t1\ncases:\n  - name: one\n    arguments: {}\nprobe: {case: one, every: 60}\n')
    (tmp_path / 'bad.yaml').write_text('tool: t2\ncases:\n  - name: x\n    expect: [{path: "$.a"}]\n')
    (tmp_path / 'dup.yaml').write_text('tool: t1\ncases:\n  - name: one\n')

    class Reg:
        tools = {'t3': type('T', (), {'config': {'tests': [{'name': 'cfg', 'arguments': {}}]}})()}
    s = load_suite(str(tmp_path), Reg())
    assert [(c.tool, c.name) for c in s.cases] == [('t1', 'one'), ('t3', 'cfg')]
    assert s.probes['t1'].every == 60
    assert any('duplicate' in e for e in s.errors) and any('t2' in e for e in s.errors)
    assert [c.name for c in select(s.cases, 't3')] == ['cfg']


def test_probe_needs_a_known_case_and_a_sane_schedule(tmp_path):
    (tmp_path / 'a.yaml').write_text('tool: t1\ncases: [{name: one}]\nprobe: {case: two}\n')
    (tmp_path / 'b.yaml').write_text('tool: t2\ncases: [{name: one}]\nprobe: {case: one, every: 1}\n')
    (tmp_path / 'c.yaml').write_text('tool: t3\ncases: [{name: one}]\nprobe: {case: one, cron: "not cron"}\n')
    s = load_suite(str(tmp_path))
    assert not s.probes and len(s.errors) == 3


# ── a local HTTP service and a tool that calls it ───────────────────

class _Handler(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        _Handler.hits.append(self.path)
        if self.path.startswith('/missing'):
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error": "nope"}')
            return
        body = json.dumps({'path': self.path, 'n': len(_Handler.hits)}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Set-Cookie', 'session=secret')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        data = self.rfile.read(n)
        _Handler.hits.append(('POST', self.path, data))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"posted": true}')

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _Handler.hits = []
    srv = HTTPServer(('127.0.0.1', 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


class HttpTool(BaseMCPTool):
    """Calls the local server with urllib (what built-in tools use)."""

    def __init__(self, base):
        super().__init__({'name': 'http_echo', 'description': 'echo', 'version': '1.0.0',
                          'inputSchema': {'type': 'object', 'properties': {'q': {'type': 'string'}}, 'required': ['q']},
                          'outputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}}}})
        self.base = base

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return self._output_schema

    def execute(self, a):
        with urllib.request.urlopen(f'{self.base}/echo?q={a["q"]}&apikey=SECRET123', timeout=5) as r:
            return json.loads(r.read())


def test_urllib_record_then_replay_offline(server, tmp_path):
    path = tmp_path / 'c.json'
    c = Cassette(str(path), 'record')
    with c.use():
        with urllib.request.urlopen(f'{server}/a?token=T0P&x=1') as r:
            first = json.loads(r.read())
            assert r.status == 200 and r.headers.get('Content-Type') == 'application/json'
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(f'{server}/missing')
        assert ei.value.code == 404 and json.loads(ei.value.read()) == {'error': 'nope'}
    saved = json.loads(path.read_text())
    url = saved['interactions'][0]['request']['url']
    assert 'T0P' not in url and 'token=REDACTED' in url      # (the echo body keeps it: bodies are stored as received)
    assert 'session=secret' not in path.read_text()                       # Set-Cookie dropped
    hits = len(_Handler.hits)
    with Cassette(str(path), 'replay').use():
        with urllib.request.urlopen(f'{server}/a?token=OTHER&x=1') as r:     # secrets do not take part in matching
            assert json.loads(r.read()) == first
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(urllib.request.Request(f'{server}/missing'))
        assert ei.value.code == 404
        with pytest.raises(CassetteMiss):
            urllib.request.urlopen(f'{server}/never-recorded')
    assert len(_Handler.hits) == hits                                     # replay made no request
    assert urllib.request.urlopen.__name__ == 'urlopen' and urllib.request.urlopen.__module__ == 'urllib.request'


def test_post_bodies_match_by_hash(server, tmp_path):
    path = tmp_path / 'p.json'
    with Cassette(str(path), 'record').use():
        urllib.request.urlopen(urllib.request.Request(f'{server}/p', data=b'{"a":1}', method='POST')).read()
    with Cassette(str(path), 'replay').use():
        assert json.loads(urllib.request.urlopen(urllib.request.Request(f'{server}/p', data=b'{"a":1}', method='POST')).read())
        with pytest.raises(CassetteMiss):
            urllib.request.urlopen(urllib.request.Request(f'{server}/p', data=b'{"a":2}', method='POST'))


def test_requests_record_and_replay(server, tmp_path):
    requests = pytest.importorskip('requests')
    path = tmp_path / 'r.json'
    with Cassette(str(path), 'record').use():
        live = requests.get(f'{server}/r', params={'api_key': 'K'}).json()
    hits = len(_Handler.hits)
    with Cassette(str(path), 'replay').use():
        r = requests.get(f'{server}/r', params={'api_key': 'other'})
        assert r.status_code == 200 and r.json() == live
    assert len(_Handler.hits) == hits


def test_httpx_record_and_replay(server, tmp_path):
    httpx = pytest.importorskip('httpx')
    path = tmp_path / 'h.json'
    with Cassette(str(path), 'record').use():
        live = httpx.get(f'{server}/h').json()
    hits = len(_Handler.hits)
    with Cassette(str(path), 'replay').use():
        assert httpx.get(f'{server}/h').json() == live

        async def go():
            async with httpx.AsyncClient() as c:
                return (await c.get(f'{server}/h')).json()
        import asyncio
        with pytest.raises(CassetteMiss):           # the one recording was played already
            asyncio.run(go())
    assert len(_Handler.hits) == hits


def test_redact_url():
    assert redact_url('https://x/y?apikey=1&q=a&Token=2') == 'https://x/y?apikey=REDACTED&q=a&Token=REDACTED'
    assert redact_url('https://x/y') == 'https://x/y'


# ── the runner ──────────────────────────────────────────────────────

def _case(**kw):
    base = {'tool': 'http_echo', 'name': 'echo', 'arguments': {'q': 'hi'},
            'expect': [{'schema': 'output'}, {'path': '$.path', 'regex': 'q=hi'}]}
    base.update(kw)
    return TestCase(**base)


def test_runner_record_replay_auto_and_strict(server, tmp_path):
    tool = HttpTool(server)
    root = str(tmp_path)
    r = run_case(tool, _case(), 'record', root)
    assert r.status == 'pass' and r.mode == 'record' and r.http_calls == 1
    assert (tmp_path / 'http_echo' / 'echo.json').is_file()
    hits = len(_Handler.hits)
    assert run_case(tool, _case(), 'auto', root).mode == 'replay'          # a cassette exists: replay
    assert run_case(tool, _case(), 'replay', root).status == 'pass'
    assert len(_Handler.hits) == hits
    miss = run_case(tool, _case(name='other'), 'replay', root)             # no cassette: strict replay fails
    assert miss.status == 'error' and 'cassette' in miss.message
    assert run_case(tool, _case(name='other'), 'auto', root).mode == 'live'


def test_runner_statuses(server, tmp_path):
    tool = HttpTool(server)
    root = str(tmp_path)
    assert run_case(tool, _case(expect=[{'path': '$.path', 'equals': 'x'}]), 'live', root).status == 'fail'
    bad_args = run_case(tool, _case(arguments={}, error='q'), 'live', root)
    assert bad_args.status == 'pass' and 'q' in bad_args.message           # expected failure
    assert run_case(tool, _case(arguments={}), 'live', root).status == 'error'
    assert run_case(tool, _case(error=True), 'live', root).status == 'fail'
    assert run_case(tool, _case(skip='flaky upstream'), 'live', root).status == 'skip'
    assert run_case(None, _case(), 'live', root).status == 'error'


def test_junit_xml_is_well_formed(server, tmp_path):
    tool = HttpTool(server)

    class Reg:
        def get_tool(self, n):
            return tool if n == 'http_echo' else None
    cases = [_case(), _case(name='bad', expect=[{'path': '$.path', 'equals': 'x'}]), _case(name='s', skip='later'),
             _case(tool='ghost', name='g')]
    res = run_cases(Reg(), cases, 'live', str(tmp_path))
    s = summarise(res)
    assert (s['pass'], s['fail'], s['skip'], s['error']) == (1, 1, 1, 1) and not s['ok']
    root = ET.fromstring(render_junit(res))
    assert root.tag == 'testsuites' and root.get('tests') == '4' and root.get('failures') == '1'
    suites = {s.get('name'): s for s in root}
    assert set(suites) == {'http_echo', 'ghost'}
    cases_ = {c.get('name'): c for c in suites['http_echo']}
    assert cases_['bad'].find('failure') is not None and cases_['s'].find('skipped') is not None
    assert suites['ghost'][0].find('error') is not None


def test_shipped_cases_pass_offline():
    """config/tool_tests/ replays offline (the wiki_search cassette is committed)."""
    from sajha.quality.__main__ import main
    assert main(['test', '--replay']) == 0


def test_cli_writes_junit_and_json(tmp_path):
    from sajha.quality.__main__ import main
    j, js = tmp_path / 'r.xml', tmp_path / 'r.json'
    assert main(['test', '--tool', 'calc_*', '--replay', '--junit', str(j), '--json', str(js)]) == 0
    assert ET.parse(j).getroot().get('failures') == '0'
    data = json.loads(js.read_text())
    assert data['summary']['ok'] and all(r['tool'].startswith('calc_') for r in data['results'])
