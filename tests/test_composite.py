# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Composite tools: param-mapping forms, both arrangements, and registration of
DB-saved composites into the registry (they used to fail to register).
"""
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sajha.core.composition import ParamLens, resolve_source  # noqa: E402
from sajha.tools.base_mcp_tool import BaseMCPTool  # noqa: E402
from sajha.tools.composite_tool import CompositeTool, CompositeToolEngine, _map_params  # noqa: E402


class FnTool(BaseMCPTool):
    def __init__(self, name, fn, schema=None):
        super().__init__({'name': name, 'description': name})
        self._fn, self._schema = fn, schema or {'type': 'object', 'properties': {}}
        self.calls = []

    def get_input_schema(self):
        return self._schema

    def get_output_schema(self):
        return {'type': 'object'}

    def execute(self, arguments):
        self.calls.append(dict(arguments))
        return self._fn(arguments)


class StubRegistry:
    """The parts of ToolsRegistry the composite engine uses."""

    def __init__(self, *tools):
        self.tools = {t.name: t for t in tools}
        self._listeners = []

    def get_tool(self, name):
        return self.tools.get(name)

    def register_tool(self, tool):  # one argument, like ToolsRegistry.register_tool
        self.tools[tool.name] = tool

    def unregister_tool(self, name):
        self.tools.pop(name, None)

    def add_reload_listener(self, cb):
        self._listeners.append(cb)

    def reload_all_tools(self):  # what the real registry does: drop everything, reload files
        self.tools = {n: t for n, t in self.tools.items() if not isinstance(t, CompositeTool)}
        for cb in self._listeners:
            cb()


def _master(args):
    return {'ticker': 'AAPL', 'quote': {'price': 10}, 'rows': [{'sym': 'A'}, {'sym': 'B'}]}


def _echo(args):
    return {'got': dict(args)}


# ── resolver ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('expr,expected', [
    ('$input.symbol', 'MSFT'),
    ('$.input.symbol', 'MSFT'),
    ('$.ticker', 'AAPL'),
    ('$.quote.price', 10),
    ('$.rows.1.sym', 'B'),
    ('$.missing', ''),
    ('$input.missing', ''),
    ('literal', 'literal'),
    (5, 5),
])
def test_resolve_source_forms(expr, expected):
    assert resolve_source(expr, master_input={'symbol': 'MSFT'}, record=_master({})) == expected


def test_param_lens_and_legacy_map_params_agree():
    lens = ParamLens(mapping={'a': '$input.x', 'b': '$.input.x', 'c': '$.f'}, static_params={'s': 1})
    assert lens.view({}, master_input={'x': 'X'}, record={'f': 'F'}) == {'s': 1, 'a': 'X', 'b': 'X', 'c': 'F'}
    assert _map_params({'f': 'F'}, {'a': '$input.x', 'b': '$.input.x', 'c': '$.f'}, {'s': 1},
                       {'x': 'X'}) == {'s': 1, 'a': 'X', 'b': 'X', 'c': 'F'}


# ── arrangements ───────────────────────────────────────────────────────

def test_sibling_resolves_all_documented_forms():
    master, echo = FnTool('master', _master), FnTool('echo', _echo)
    reg = StubRegistry(master, echo)
    tool = CompositeTool({
        'name': 'combo', 'arrangement': 'sibling', 'master_tool': 'master',
        'master_output_key': 'm',
        'steps': [{'tool_name': 'echo', 'output_key': 'e',
                   'param_mapping': {'from_master': '$.ticker', 'nested': '$.quote.price',
                                     'plain_input': '$input.symbol', 'dotted_input': '$.input.symbol'},
                   'static_params': {'limit': 5}}],
    }, reg)
    # Both $input.x and $.input.x surface the field in the composite's input schema
    assert 'symbol' in tool.get_input_schema()['properties']
    out = tool.execute({'symbol': 'MSFT'})
    got = out['e']['got']
    assert got['from_master'] == 'AAPL' and got['nested'] == 10
    assert got['plain_input'] == 'MSFT' and got['dotted_input'] == 'MSFT'
    assert got['limit'] == 5 and got['symbol'] == 'MSFT'  # sibling steps also see the composite input
    assert out['m'] == _master({})
    assert out['_composition']['steps_succeeded'] == 2


def test_parent_child_fans_out_per_record():
    master, echo = FnTool('master', _master), FnTool('echo', _echo)
    tool = CompositeTool({
        'name': 'fan', 'arrangement': 'parent_child', 'master_tool': 'master', 'record_path': 'rows',
        'steps': [{'tool_name': 'echo', 'output_key': 'e',
                   'param_mapping': {'s': '$.sym', 'q': '$input.q', 'q2': '$.input.q'}}],
    }, StubRegistry(master, echo))
    out = tool.execute({'q': 'Z'})
    assert [c['e']['got'] for c in out['children']] == [
        {'s': 'A', 'q': 'Z', 'q2': 'Z'}, {'s': 'B', 'q': 'Z', 'q2': 'Z'}]


# ── engine: saved composites become callable tools ─────────────────────

@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sajha.db.base import Base
    import sajha.db.models  # noqa: F401  (register the tables)
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _save(db, name='saved_combo', enabled=True):
    from sajha.db.dao import CompositeToolDAO
    dao = CompositeToolDAO(db)
    dao.create(name=name, master_tool='master', arrangement='sibling',
               steps=[{'tool_name': 'echo', 'output_key': 'e', 'param_mapping': {'t': '$.ticker',
                                                                                  'x': '$input.x'}}])
    if not enabled:
        dao.update(name, enabled=False)


def test_engine_registers_saved_composite_and_it_runs(db_session):
    reg = StubRegistry(FnTool('master', _master), FnTool('echo', _echo))
    _save(db_session)
    engine = CompositeToolEngine(reg)
    assert engine.load_from_db(db_session) == 1
    tool = reg.get_tool('saved_combo')
    assert isinstance(tool, CompositeTool)
    assert tool.execute({'x': 1})['e']['got']['t'] == 'AAPL'


def test_engine_survives_registry_reload_and_reload_drops_disabled(db_session):
    from sajha.tools import composite_tool
    reg = StubRegistry(FnTool('master', _master), FnTool('echo', _echo))
    _save(db_session)
    engine = CompositeToolEngine(reg)
    engine.load_from_db(db_session)
    assert composite_tool.get_engine(reg) is engine
    reg.reload_all_tools()
    assert isinstance(reg.get_tool('saved_combo'), CompositeTool)
    from sajha.db.dao import CompositeToolDAO
    CompositeToolDAO(db_session).update('saved_combo', enabled=False)
    assert engine.reload(db_session) == 0
    assert reg.get_tool('saved_combo') is None
    engine.forget('saved_combo')
    assert reg.get_tool('saved_combo') is None


def test_composite_routes_register_and_call(tmp_path):
    """Through the API: a saved composite is immediately callable, and deleting it unregisters it."""
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        h = {'Authorization': f"Bearer {r.json()['token']}"}
        from sajha.app import tools_registry
        tools_registry.register_tool(FnTool('zz_comp_master', _master))
        tools_registry.register_tool(FnTool('zz_comp_echo', _echo))
        try:
            r = c.post('/api/composite-tools', headers=h, json={
                'name': 'zz_comp_test', 'master_tool': 'zz_comp_master', 'arrangement': 'sibling',
                'steps': [{'tool_name': 'zz_comp_echo', 'output_key': 'e',
                           'param_mapping': {'t': '$.ticker', 'x': '$input.x'}}]})
            assert r.status_code == 200, r.text
            assert isinstance(tools_registry.get_tool('zz_comp_test'), CompositeTool)
            r = c.post('/mcp', headers=h, json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                'params': {'name': 'zz_comp_test', 'arguments': {'x': 'y'}}})
            assert r.status_code == 200 and 'result' in r.json(), r.text
            assert '"AAPL"' in r.text
        finally:
            c.delete('/api/composite-tools/zz_comp_test', headers=h)
            tools_registry.unregister_tool('zz_comp_master')
            tools_registry.unregister_tool('zz_comp_echo')
        assert tools_registry.get_tool('zz_comp_test') is None
