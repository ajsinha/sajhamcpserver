# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""bi_load_tool_result (sajha/tools/impl/bi_chart_tools.py; docs/architecture/Business Intelligence.md §6):
the inner call runs as the caller (a tool they may not call is refused; the policy engine still applies, so
sanctions_* results are not loaded for a model), the rows land in the caller's own scratch database with
provenance, other users cannot read them, and they expire."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from sajha.analytics import scratch
from sajha.analytics.scratch import ScratchDB, ScratchSettings
from sajha.core.inner_calls import InnerCallRefused
from sajha.observability.caller import Caller, reset as reset_caller, set_caller
from sajha.policy import context
from sajha.policy.engine import PolicyEngine, set_engine
from sajha.policy.errors import PolicyDenied
from sajha.policy.loader import PolicySet
from sajha.policy.model import parse_text
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.impl.bi_chart_tools import BIChartTool, BILoadToolResultTool, ChartError

ROOT = Path(__file__).resolve().parent.parent


class _Src(BaseMCPTool):
    def __init__(self, name, output):
        super().__init__({'name': name, 'description': 'rows', 'version': '2.1.0',
                          'inputSchema': {'type': 'object', 'properties': {'n': {'type': 'integer'}}}})
        self.output, self.calls = output, []

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {}

    def execute(self, arguments):
        from sajha.observability.caller import current
        self.calls.append((current().user_id, context.source(), dict(arguments)))
        return self.output


class _Reg:
    def __init__(self, *tools):
        self.tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self.tools.get(name)


SERIES = {'series_id': 'X', 'observations': [{'date': '2025-01-01', 'value': '1.5'},
                                             {'date': '2025-02-01', 'value': '2.0'},
                                             {'date': '2025-03-01', 'value': '.'}]}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A scratch directory of its own, an audit writer that only records, a memory state store."""
    from sajha import audit
    from sajha.audit.chain import ChainWriter
    from sajha.core.state import set_state_store
    from sajha.core.state.memory import MemoryStateStore
    cfg = ScratchSettings(dir=str(tmp_path / 'scratch'), max_rows=1000, max_mb=50, max_minutes=120)
    monkeypatch.setattr(scratch, 'settings', lambda: cfg)
    old = (audit._writer, audit._exporter)
    audit.set_writer(ChainWriter(store=False, anchor_interval=0, anchor_every=10 ** 9, on_record=lambda r: None))
    audit._exporter = None
    set_state_store(MemoryStateStore())
    src = _Src('fred_like_series', SERIES)
    sanc = _Src('sanctions_screen', {'matches': [{'name': 'ACME', 'score': 0.9}]})
    loader = BILoadToolResultTool(json.loads((ROOT / 'config/tools/bi/bi_load_tool_result.json').read_text()))
    chart = BIChartTool(json.loads((ROOT / 'config/tools/bi/bi_chart.json').read_text()))
    loader.registry = chart.registry = _Reg(src, sanc)
    yield {'cfg': cfg, 'src': src, 'sanc': sanc, 'loader': loader, 'chart': chart}
    set_engine(None)
    set_state_store(None)
    audit._writer, audit._exporter = old


class as_user:
    def __init__(self, user, allowed=None):
        access = None if allowed is None else (lambda n: n in allowed)
        self.caller = Caller(user, '', ('user',), 'session', access)

    def __enter__(self):
        self.t = set_caller(self.caller)

    def __exit__(self, *exc):
        reset_caller(self.t)


ALL = {'bi_load_tool_result', 'bi_chart', 'fred_like_series', 'sanctions_screen'}


def test_load_returns_provenance_and_the_rows_are_typed(env):
    with as_user('alice', ALL):
        meta = env['loader'].execute_with_tracking({'tool': 'fred_like_series', 'arguments': {'n': 3},
                                                    'rows_path': '$.observations', 'table': 'Unrate',
                                                    'ttl_minutes': 30})
    assert meta['table'] == 'unrate' and meta['rows'] == 3 and meta['tool'] == 'fred_like_series'
    assert meta['tool_version'] == '2.1.0' and meta['arguments'] == {'n': 3} and meta['rows_path'] == '$.observations'
    assert meta['call_id'].startswith('call_') and meta['loaded_at'] and meta['expires_at']
    assert {c['name']: c['type'] for c in meta['columns']} == {'date': 'DATE', 'value': 'DOUBLE'}
    assert meta['sample'][0] == {'date': '2025-01-01', 'value': 1.5}
    assert env['src'].calls == [('alice', 'other', {'n': 3})]
    # and bi_chart can draw it from the caller's own table
    with as_user('alice', ALL):
        out = env['chart'].execute({'kind': 'line', 'x': 'date', 'y': 'value',
                                    'data': {'sql': 'SELECT date, value FROM unrate ORDER BY date'}})
    assert out['rows'] == 2 and out['skipped'] == 1 and out['source']['tables'] == ['unrate']


def test_scratch_tables_are_per_user(env):
    with as_user('alice', ALL):
        env['loader'].execute({'tool': 'fred_like_series', 'rows_path': 'observations', 'table': 'mine'})
    with as_user('bob', ALL):
        env['loader'].execute({'tool': 'fred_like_series', 'rows_path': 'observations', 'table': 'bobs'})
        with pytest.raises(ChartError, match='unknown table mine'):
            env['chart'].execute({'kind': 'line', 'x': 'date', 'y': 'value', 'data': {'sql': 'SELECT * FROM mine'}})
    assert [t['table'] for t in ScratchDB('alice', env['cfg']).tables()] == ['mine']
    assert [t['table'] for t in ScratchDB('bob', env['cfg']).tables()] == ['bobs']
    assert ScratchDB('alice', env['cfg']).path != ScratchDB('bob', env['cfg']).path


def test_a_tool_the_caller_may_not_call_is_refused_and_never_runs(env):
    with as_user('carol', {'bi_load_tool_result'}):
        with pytest.raises(InnerCallRefused, match='no such tool, or you may not call it'):
            env['loader'].execute({'tool': 'fred_like_series'})
        with pytest.raises(InnerCallRefused, match='no such tool, or you may not call it'):
            env['loader'].execute({'tool': 'no_such_tool'})
    assert env['src'].calls == []
    assert ScratchDB('carol', env['cfg']).tables() == []
    with as_user('carol', ALL), pytest.raises(ValueError, match='cannot be loaded'):
        env['loader'].execute({'tool': 'bi_load_tool_result'})


def test_anonymous_callers_have_no_scratch_database(env):
    with as_user('anonymous', ALL), pytest.raises(PermissionError, match='sign in'):
        env['loader'].execute({'tool': 'fred_like_series'})
    assert env['src'].calls == []


def test_sanctions_results_are_not_loaded_where_the_policy_denies_them(env):
    doc = (ROOT / 'config/policies/10-sanctions.yaml').read_text()
    ps = PolicySet()
    ps.set_policies([parse_text(textwrap.dedent(doc), 'sanctions', '10-sanctions.yaml')])
    set_engine(PolicyEngine(ps))
    with as_user('dave', ALL):
        with context.using_source('ask', override=True):          # a model chose the call
            with pytest.raises(PolicyDenied):
                env['loader'].execute_with_tracking({'tool': 'sanctions_screen'})
        assert env['sanc'].calls == [] and ScratchDB('dave', env['cfg']).tables() == []
        with context.using_source('rest', override=True):         # a person calling directly
            meta = env['loader'].execute_with_tracking({'tool': 'sanctions_screen'})
    assert meta['rows'] == 1 and env['sanc'].calls[0][1] == 'rest'


def test_tables_expire_after_their_ttl_capped_by_the_setting(env, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(scratch, '_now', lambda: now[0])
    with as_user('erin', ALL):
        short = env['loader'].execute({'tool': 'fred_like_series', 'rows_path': 'observations', 'table': 'short',
                                       'ttl_minutes': 5})
        long_ = env['loader'].execute({'tool': 'fred_like_series', 'rows_path': 'observations', 'table': 'long',
                                       'ttl_minutes': 1440})
    db = ScratchDB('erin', env['cfg'])
    from datetime import datetime
    span = (datetime.fromisoformat(long_['expires_at']) - datetime.fromisoformat(long_['loaded_at'])).total_seconds()
    assert span == 120 * 60                                        # capped by bi.scratch_max_minutes
    assert {t['table'] for t in db.tables()} == {'short', 'long'}
    now[0] += 6 * 60
    assert [t['table'] for t in db.tables()] == ['long']
    with as_user('erin', ALL), pytest.raises(ChartError, match='unknown table short'):
        env['chart'].execute({'kind': 'bar', 'x': 'date', 'y': 'value', 'data': {'sql': 'SELECT * FROM short'}})
    now[0] += 120 * 60
    assert db.tables() == [] and short['table'] == 'short'


def test_config_annotations_and_description_fit():
    cfg = json.loads((ROOT / 'config/tools/bi/bi_load_tool_result.json').read_text())
    assert cfg['annotations']['readOnlyHint'] is True
    from sajha.quality.lint import lint_tool
    for name in ('bi_load_tool_result', 'bi_chart'):
        c = json.loads((ROOT / f'config/tools/bi/{name}.json').read_text())
        assert lint_tool(name, c) == [], name
        assert len(c['description']) <= 1024 - 600 - 2, name     # room for a full domain description
