# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Tool versions: the versions file, routing (API-key pin > user > role > canary > stable), canary
stickiness, automatic rollback shared across workers, deprecation and sunset, MCP exposure (one
name, the version in _meta, hidden after the tool's sunset), REST, and the admin API."""

import textwrap
from datetime import date, timedelta

import pytest

from sajha.core.state import set_state_store
from sajha.core.state.memory import MemoryStateStore
from sajha.observability.caller import Caller, reset, set_caller
from sajha.quality import versions as V
from sajha.tools.base_mcp_tool import BaseMCPTool

HERE = 'tests.test_quality_versions'


class VersionedEcho(BaseMCPTool):
    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {'type': 'object'}

    def execute(self, a):
        return {'version': self.version, 'x': a.get('x')}


class AlwaysFails(VersionedEcho):
    def execute(self, a):
        raise RuntimeError('boom')


def make_tool(name='svc_echo', version='1.0.0'):
    return VersionedEcho({'name': name, 'version': version, 'description': 'Echo the argument back with the version.',
                          'implementation': f'{HERE}.VersionedEcho',
                          'inputSchema': {'type': 'object', 'properties': {'x': {'type': 'integer'}}}})


class Reg:
    def __init__(self, *tools):
        self.tools = {t.name: t for t in tools}

    def get_tool(self, n):
        return self.tools.get(n)

    def get_all_tools(self):
        return [t.to_mcp_format() for t in self.tools.values()]


@pytest.fixture
def env(tmp_path):
    store = MemoryStateStore('test:')
    set_state_store(store)
    d = tmp_path / 'versions'
    d.mkdir()

    def write(text, name='svc_echo'):
        (d / f'{name}.yaml').write_text(textwrap.dedent(text))
        m.reload(force=True)
    m = V.VersionManager(str(d), reload_seconds=0)
    V.set_manager(m)
    yield m, write, store
    V.set_manager(None)
    set_state_store(None)


def call(tool, caller=None, **args):
    tok = set_caller(caller or Caller())
    try:
        with V.collect_meta() as meta:
            out = tool.execute_with_tracking(args or {'x': 1})
        return out, meta
    finally:
        reset(tok)


BASIC = """
tool: svc_echo
versions:
  "2.0.0":
    changelog: v2
routing:
  roles: {beta: "2.0.0"}
  users: {alice: "2.0.0"}
  api_keys: {ci: "1.0.0", early: "2.0.0"}
"""


def test_unversioned_tools_are_untouched(env):
    out, meta = call(make_tool())
    assert out == {'version': '1.0.0', 'x': 1} and meta == {}


def test_routing_precedence(env):
    m, write, _ = env
    write(BASIC)
    t = make_tool()
    assert call(t)[0]['version'] == '1.0.0'
    out, meta = call(t, Caller('bob', roles=('beta',)))
    assert out['version'] == '2.0.0' and meta[V.META_VERSION] == {'version': '2.0.0', 'route': 'role'}
    assert call(t, Caller('alice'))[1][V.META_VERSION]['route'] == 'user'
    out, meta = call(t, Caller('alice', api_key='ci', roles=('beta',)))      # the API-key pin wins
    assert out['version'] == '1.0.0' and meta[V.META_VERSION]['route'] == 'api_key'


def test_canary_is_sticky_and_roughly_proportional(env):
    m, write, _ = env
    write("""
    tool: svc_echo
    versions: {"2.0.0": {}}
    routing: {canary: {version: "2.0.0", percent: 30}}
    """)
    t = make_tool()
    seen = {}
    for i in range(400):
        c = Caller(f'user{i}')
        v = call(t, c)[0]['version']
        assert call(t, c)[0]['version'] == v                                 # same caller, same version
        seen[v] = seen.get(v, 0) + 1
    assert 80 <= seen.get('2.0.0', 0) <= 160, seen


def test_overrides_and_whole_config_versions(env, tmp_path):
    m, write, _ = env
    (tmp_path / 'versions' / 'svc_echo-3.json').write_text(
        '{"name": "x", "implementation": "%s.VersionedEcho", "description": "three"}' % HERE)
    write("""
    tool: svc_echo
    versions:
      "2.0.0": {overrides: {description: "two"}}
      "3.0.0": {config: svc_echo-3.json}
    routing: {users: {u2: "2.0.0", u3: "3.0.0"}}
    """)
    t = make_tool()
    v2, v3 = m.instance_for(t, '2.0.0'), m.instance_for(t, '3.0.0')
    assert (v2.name, v2.version, v2.description) == ('svc_echo', '2.0.0', 'two')
    assert (v3.name, v3.version, v3.description) == ('svc_echo', '3.0.0', 'three')
    assert m.instance_for(t, '1.0.0') is t and m.instance_for(t, '9') is None
    assert call(t, Caller('u3'))[0]['version'] == '3.0.0'


def test_invalid_files_are_rejected(env):
    m, write, _ = env
    for bad in ({'tool': 'svc_echo', 'routing': {'canary': {'version': '2', 'percent': 150}}},
                {'tool': 'svc_echo', 'versions': {'2': {'overrides': {'name': 'other'}}}},
                {'tool': 'svc_echo', 'versions': {'2': {'config': '../../etc/passwd'}}},
                {'tool': 'svc_echo', 'versions': {'bad version!': {}}},
                {'tool': 'svc_echo', 'deprecation': {'sunset': 'soon'}},
                {'tool': 'svc_echo', 'surprise': 1}):
        with pytest.raises(V.VersionsError):
            V.parse(bad)
    with pytest.raises(V.VersionsError):
        V.check_references(V.parse({'tool': 'svc_echo', 'routing': {'roles': {'r': '7.0'}}}), '1.0.0')
    write('tool: svc_echo\nsurprise: 1\n')
    assert m.get('svc_echo') is None and m.errors()


def test_automatic_rollback_is_shared_by_workers(env):
    m, write, store = env
    write(f"""
    tool: svc_echo
    versions:
      "2.0.0": {{overrides: {{implementation: {HERE}.AlwaysFails}}}}
    routing: {{canary: {{version: "2.0.0", percent: 100}}}}
    rollback: {{max_error_rate: 0.5, min_calls: 4, window_seconds: 60}}
    """)
    t = make_tool()
    for i in range(4):
        with pytest.raises(RuntimeError):
            call(t, Caller(f'u{i}'))
    rb = m.rolled_back('svc_echo', '2.0.0')
    assert rb and 'error rate' in rb['reason']
    # another worker: its own manager over the same directory and the same (shared) store
    other = V.VersionManager(str(m.directory), reload_seconds=0)
    V.set_manager(other)
    out, meta = call(make_tool(), Caller('u9'))
    assert out['version'] == '1.0.0' and meta[V.META_VERSION]['route'] == 'stable'
    from sajha.observability.metrics import REGISTRY
    assert REGISTRY.family('sajha_tool_version_rollbacks_total').value(('svc_echo', '2.0.0')) >= 1
    assert other.clear_rollback('svc_echo', '2.0.0', 'admin') and not other.rolled_back('svc_echo', '2.0.0')


def test_latency_rollback(env):
    m, write, _ = env
    write("""
    tool: svc_echo
    versions: {"2.0.0": {}}
    routing: {canary: {version: "2.0.0", percent: 100}}
    rollback: {max_p95_ms: 1, min_calls: 3, window_seconds: 60}
    """)
    vf = m.get('svc_echo')
    for _ in range(3):
        m.record(vf, '2.0.0', True, 50.0, '1.0.0')
    assert 'p95' in m.rolled_back('svc_echo', '2.0.0')['reason']
    for _ in range(5):                                                        # the stable version never rolls back
        m.record(vf, '1.0.0', False, 50.0, '1.0.0')
    assert not m.rolled_back('svc_echo', '1.0.0')


def test_caller_errors_do_not_count(env):
    m, write, _ = env
    write("""
    tool: svc_echo
    versions: {"2.0.0": {}}
    routing: {canary: {version: "2.0.0", percent: 100}}
    rollback: {min_calls: 2, window_seconds: 60}
    """)
    t = make_tool()
    for i in range(3):
        with pytest.raises(ValueError):
            call(t, Caller(f'u{i}'), x='not an integer')                      # ToolArgumentError
    assert not m.rolled_back('svc_echo', '2.0.0')
    assert m.window_stats('svc_echo', '2.0.0', 60)['errors'] == 0


def test_version_deprecation_and_sunset(env):
    m, write, _ = env
    future = (date.today() + timedelta(days=30)).isoformat()
    past = (date.today() - timedelta(days=1)).isoformat()
    write(f"""
    tool: svc_echo
    versions:
      "1.0.0": {{sunset: {future}, successor: "2.0.0"}}
      "2.0.0": {{sunset: {past}}}
    routing: {{users: {{late: "2.0.0"}}}}
    """)
    t = make_tool()
    out, meta = call(t)
    assert out['version'] == '1.0.0' and meta[V.META_DEPRECATION]['sunset'] == future
    assert meta[V.META_DEPRECATION]['successor'] == '2.0.0'
    out, meta = call(t, Caller('late'))                                        # 2.0.0 is past its sunset
    assert out['version'] == '1.0.0'


def test_tool_sunset_hides_and_refuses(env):
    m, write, _ = env
    from sajha.core.mcp_handler import MCPHandler
    t, other = make_tool(), make_tool('svc_other')
    h = MCPHandler(tools_registry=Reg(t, other))
    future = (date.today() + timedelta(days=3)).isoformat()
    write(f'tool: svc_echo\ndeprecation: {{sunset: {future}, successor: svc_other}}\n')
    names = [x['name'] for x in h._handle_tools_list({}, None)['tools']]
    assert names.count('svc_echo') == 1 and 'svc_other' in names
    r = h._handle_tools_call({'name': 'svc_echo', 'arguments': {'x': 2}}, None)
    assert not r.get('isError') and r['_meta'][V.META_DEPRECATION]['successor'] == 'svc_other'
    assert r['_meta'][V.META_VERSION]['version'] == '1.0.0'
    write('tool: svc_echo\ndeprecation: {sunset: 2000-01-01, successor: svc_other}\n')
    assert 'svc_echo' not in [x['name'] for x in h._handle_tools_list({}, None)['tools']]
    r = h._handle_tools_call({'name': 'svc_echo', 'arguments': {'x': 2}}, None)
    assert r['isError'] and 'retired' in r['content'][0]['text']
    r = h._handle_tools_call({'name': 'svc_other', 'arguments': {'x': 2}}, None)
    assert '_meta' not in r                                                    # unversioned: no _meta


def test_mcp_lists_one_name_and_reports_the_version(env):
    m, write, _ = env
    from sajha.core.mcp_handler import MCPHandler
    write(BASIC)
    h = MCPHandler(tools_registry=Reg(make_tool()))
    assert [x['name'] for x in h._handle_tools_list({}, None)['tools']] == ['svc_echo']
    tok = set_caller(Caller('bob', roles=('beta',)))
    try:
        r = h._handle_tools_call({'name': 'svc_echo', 'arguments': {'x': 3}}, None)
    finally:
        reset(tok)
    assert r['structuredContent'] == {'version': '2.0.0', 'x': 3}
    assert r['_meta'][V.META_VERSION] == {'version': '2.0.0', 'route': 'role'}


def test_a_broken_version_falls_back(env):
    m, write, _ = env
    write("""
    tool: svc_echo
    versions: {"2.0.0": {overrides: {implementation: no.such.module.Tool}}}
    routing: {canary: {version: "2.0.0", percent: 100}}
    """)
    out, meta = call(make_tool(), Caller('u'))
    assert out['version'] == '1.0.0' and meta[V.META_VERSION]['route'] == 'fallback'


def test_writing_helpers(env):
    m, write, _ = env
    t = make_tool()
    with pytest.raises(V.VersionsError):
        m.save_text('svc_echo', 'tool: svc_echo\nrouting: {roles: {r: "9.9"}}\n', '1.0.0')
    m.save_text('svc_echo', 'tool: svc_echo\nversions: {"2.0.0": {}}\n', '1.0.0')
    m.set_canary('svc_echo', '2.0.0', 25, '1.0.0')
    assert m.get('svc_echo').canary_percent == 25
    m.promote('svc_echo', '2.0.0', '1.0.0')
    vf = m.get('svc_echo')
    assert vf.stable == '2.0.0' and vf.canary_percent == 0
    assert call(t)[0]['version'] == '2.0.0'
    d = m.describe(t)
    assert d['managed'] and d['stable'] == '2.0.0' and {v['version'] for v in d['versions']} == {'1.0.0', '2.0.0'}


def test_disabled_versioning(env, monkeypatch):
    m, write, _ = env
    write(BASIC)
    V.set_manager(None)
    monkeypatch.setenv('SAJHA_QUALITY_VERSIONS_ENABLED', 'false')
    assert call(make_tool(), Caller('bob', roles=('beta',)))[0]['version'] == '1.0.0'
