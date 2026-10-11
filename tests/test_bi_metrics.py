# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Business Intelligence metrics layer and analysis tools (sajha/bi/, sajha/tools/impl/bi_metric_tools.py;
docs/architecture/Business Intelligence.md §2 to §4): periods, the definition checks and loader
notices, compilation that never writes a caller's value into SQL, governance (roles hide a metric,
a connection's deny rules and masking hold), the three source kinds, and golden results of
compare, top N, crosstab and explain_change on the shipped DuckDB sample data and metrics.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from sajha.bi import compiler as C
from sajha.bi import metrics as M
from sajha.bi import periods as P
from sajha.observability.caller import Caller, reset as reset_caller, set_caller
from tests.test_connectors import SHOP, FakeRegistry, _shop_sqlite, storage_dir  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ['bi_list_metrics', 'bi_describe_metric', 'bi_query_metric', 'bi_compare', 'bi_top_n', 'bi_crosstab',
         'bi_explain_change']


def _tool(name):
    from sajha.tools.impl import bi_metric_tools as T
    cfg = json.loads((ROOT / f'config/tools/bi/{name}.json').read_text())
    return getattr(T, cfg['implementation'].rsplit('.', 1)[1])(cfg)


def _registry_at(monkeypatch, base: Path, rel: str = 'config/bi/metrics') -> M.Registry:
    """Read metrics from ``base/rel`` through a local storage backend rooted at ``base``."""
    import sajha.core.storage as storage
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(base)))
    reg = M.Registry(rel)
    monkeypatch.setattr(M, '_registry', reg)
    reg.ensure(force=True)
    return reg


@pytest.fixture
def shipped(monkeypatch):
    """The shipped metrics (config/bi/metrics) over the shipped DuckDB sample data."""
    return _registry_at(monkeypatch, ROOT)


def _as(roles=(), user='u', admin=False, allowed=None):
    access = None if allowed is None else (lambda n: n in allowed)
    return set_caller(Caller(user, '', tuple(roles), 'session', access, admin))


# ── periods ─────────────────────────────────────────────────────────────

def test_periods():
    today = date(2026, 10, 11)
    q = P.parse('2025-Q3')
    assert (q.start, q.end, q.label) == (date(2025, 7, 1), date(2025, 10, 1), '2025-Q3')
    assert (q.previous().start, q.last_year().start) == (date(2025, 4, 1), date(2024, 7, 1))
    assert P.parse('2025-07').end == date(2025, 8, 1) and P.parse('2025').end == date(2026, 1, 1)
    fy = P.parse('FY2025', fiscal_year_start=4)
    assert (fy.start, fy.end) == (date(2024, 4, 1), date(2025, 4, 1))
    assert P.parse('FY2025').start == date(2025, 1, 1)
    ytd = P.parse('YTD', today=today)
    assert (ytd.start, ytd.end) == (date(2026, 1, 1), date(2026, 10, 12))
    assert P.parse('ytd', fiscal_year_start=4, today=today).start == date(2026, 4, 1)
    assert P.parse('QTD', today=today).start == date(2026, 10, 1)
    l12 = P.parse('last 12 months', today=today)
    assert (l12.start, l12.end) == (date(2025, 10, 1), date(2026, 10, 1))
    assert P.parse('last 8 quarters', today=today).start == date(2024, 10, 1)
    r = P.parse({'from': '2025-01-10', 'to': '2025-01-19'})
    assert r.end == date(2025, 1, 20) and r.previous().start == date(2024, 12, 31)
    assert P.against(q, 'same_period_last_year').label.startswith('2024-07-01')
    for bad in ('Q3', '2025-13', 'last 0 months', '', {'from': '2025-02-01', 'to': '2025-01-01'}, 7):
        with pytest.raises(P.PeriodError):
            P.parse(bad)
    assert P.bucket_label('2024-04-01', 'quarter') == '2024-Q2' and P.bucket_label(date(2024, 4, 1), 'month') == '2024-04'


# ── definitions ─────────────────────────────────────────────────────────

BASE = {'name': 'm', 'source': {'duckdb_table': 'orders'}, 'measure': {'sql': 'sum(quantity)', 'type': 'sum'},
        'time': {'column': 'order_date'}, 'dimensions': [{'name': 'region'}]}


@pytest.mark.parametrize('change, why', [
    ({'name': 'Bad-Name'}, 'name'), ({'name': 'a__b'}, 'name'),
    ({'measure': {'sql': 'quantity', 'type': 'sum'}}, 'aggregate'),
    ({'measure': {'sql': '(select sum(x) from secrets)', 'type': 'sum'}}, 'SELECT'),
    ({'measure': {'sql': 'sum(quantity); drop table orders', 'type': 'sum'}}, "';'"),
    ({'measure': {'sql': 'sum(quantity) -- x', 'type': 'sum'}}, 'comments'),
    ({'measure': {'sql': 'sum(o.quantity)', 'type': 'sum'}}, "'.'"),
    ({'measure': {'sql': "sum(length(pg_read_file('/etc/passwd')))", 'type': 'sum'}}, 'pg_read_file'),
    ({'measure': {'sql': 'sum(quantity) over ()', 'type': 'sum'}}, 'OVER'),
    ({'measure': {'sql': 'sum(:x)', 'type': 'sum'}}, 'parameters'),
    ({'measure': {'sql': 'sum(quantity)', 'type': 'median'}}, 'measure.type'),
    ({'source': {'duckdb_table': 'orders', 'connector': 'shop', 'table': 't'}}, 'exactly one'),
    ({'source': {'loaded': True}}, 'not built'),
    ({'time': None}, 'time is required'),
    ({'filters': ['sum(quantity) > 1']}, 'may not aggregate'),
    ({'dimensions': [{'name': 'bi_value'}]}, 'reserved'),
    ({'dimensions': [{'name': 'region', 'column': 'region; drop'}]}, 'column name'),
    ({'surprise': 1}, 'unknown key'),
])
def test_definition_checks_refuse(change, why):
    doc = {**BASE, **change}
    doc = {k: v for k, v in doc.items() if v is not None}
    with pytest.raises(M.MetricError, match=why):
        m = M.parse(doc)
        M._finish(m, {m.name: m})


def test_loader_refuses_bad_files_with_a_notice_and_ratios_need_matching_filters(tmp_path, monkeypatch):
    raised, cleared = [], []
    from sajha import notices
    monkeypatch.setattr(notices, 'raise_notice', lambda nid, **kw: raised.append(nid))
    monkeypatch.setattr(notices, 'list_notices', lambda **kw: [{'id': n} for n in raised])
    monkeypatch.setattr(notices, 'clear_notice', lambda nid, **kw: cleared.append(nid))
    d = tmp_path / 'metrics'
    d.mkdir()
    import yaml
    (d / 'a.yaml').write_text(yaml.safe_dump([BASE, {**BASE, 'name': 'cnt', 'measure': {'sql': 'count(*)',
                                                                                         'type': 'count'},
                                                    'filters': ["order_status = 'Completed'"]}]))
    (d / 'r.yaml').write_text(yaml.safe_dump({'name': 'r', 'measure': {'type': 'ratio', 'ratio': {
        'numerator': 'm', 'denominator': 'cnt'}}}))
    (d / 'broken.yaml').write_text('name: [unclosed')
    reg = _registry_at(monkeypatch, tmp_path, 'metrics')
    assert sorted(reg.metrics) == ['cnt', 'm']
    assert 'same fixed filters' in reg.refused['metrics/r.yaml'] and 'metrics/broken.yaml' in reg.refused
    assert {M.NOTICE_PREFIX + 'metrics/r.yaml', M.NOTICE_PREFIX + 'metrics/broken.yaml'} <= set(raised)
    (d / 'broken.yaml').unlink()
    (d / 'r.yaml').unlink()
    reg.ensure(force=True)
    assert not reg.refused and M.NOTICE_PREFIX + 'metrics/r.yaml' in cleared


# ── compilation never interpolates a caller value ───────────────────────

EVIL = ["x' OR '1'='1", "'; DROP TABLE orders; --", 'Robert"); DELETE FROM orders; --', '%_!']


def test_caller_values_are_bound_never_written_into_sql(shipped):
    m = shipped.get('net_sales')
    src = C.open_source(m)
    for v in EVIL:
        for f in ({'dimension': 'sales_rep', 'op': 'eq', 'value': v},
                  {'dimension': 'sales_rep', 'op': 'in', 'value': [v, 'Alice Wang']},
                  {'dimension': 'sales_rep', 'op': 'not_in', 'value': [v]},
                  {'dimension': 'sales_rep', 'op': 'between', 'value': [v, v + 'z']},
                  {'dimension': 'payment_method', 'op': 'contains', 'value': v}):
            c = C.compile_query(m, src, ['region'], [f], 'month', P.parse({'from': '2024-01-01', 'to': '2024-12-31'}))
            assert v not in c.sql and "'1'='1" not in c.sql and 'DROP' not in c.sql.upper()
            if f['op'] != 'contains':                   # contains binds the value with LIKE escapes
                assert any(v in str(p) for p in c.params.values())
            C.run(m, ['region'], [f], 'month', P.parse('2024'), with_as_of=False)      # runs, binds, no error
    # identifiers: only declared dimensions and grains; never the caller's text
    for bad in (['region; DROP TABLE orders'], ['"region"'], ['order_status']):
        with pytest.raises(M.MetricError, match='no dimension'):
            C.compile_query(m, src, bad)
    with pytest.raises(M.MetricError, match='may be asked by'):
        C.compile_query(m, src, [], grain="month') --")
    with pytest.raises(M.MetricError, match='op must be'):
        C.compile_query(m, src, [], [{'dimension': 'region', 'op': '= 1 OR 1=1 --', 'value': 1}])
    with pytest.raises(M.MetricError, match='values are'):
        C.compile_query(m, src, [], [{'dimension': 'region', 'op': 'eq', 'value': "Nowhere' OR 1=1 --"}])
    with pytest.raises(M.MetricError, match='takes one value'):
        C.compile_query(m, src, [], [{'dimension': 'sales_rep', 'op': 'eq', 'value': {'sql': '1'}}])
    out = _tool('bi_query_metric').execute_with_tracking(
        {'metric': 'net_sales', 'filters': [{'dimension': 'sales_rep', 'value': EVIL[0]}], 'period': '2024'})
    assert out['rows'] in ([], [{'value': None}])


def test_tool_schemas_refuse_sql_shaped_arguments():
    from sajha.tools.base_mcp_tool import ToolArgumentError
    t = _tool('bi_query_metric')
    for args in ({'metric': 'net_sales', 'sql': 'select 1'}, {'metric': 'net_sales; drop'},
                 {'metric': 'net_sales', 'grain': 'decade'}, {'metric': 'net_sales', 'by': ['a b']}):
        with pytest.raises(ToolArgumentError):
            t.validate_arguments(args)


# ── governance ──────────────────────────────────────────────────────────

def test_roles_hide_a_metric(tmp_path, monkeypatch):
    import yaml
    d = tmp_path / 'm'
    d.mkdir()
    (d / 'x.yaml').write_text(yaml.safe_dump([{**BASE, 'name': 'open_metric'},
                                              {**BASE, 'name': 'finance_only', 'roles': ['finance'],
                                               'owner': 'finance', 'filters': ["order_status = 'Completed'"]}]))
    _registry_at(monkeypatch, tmp_path, 'm')
    if True:
        lst, desc = _tool('bi_list_metrics'), _tool('bi_describe_metric')
        for roles, admin, sees in ((('user',), False, False), (('finance',), False, True), ((), True, True)):
            t = _as(roles, admin=admin)
            try:
                names = [x['name'] for x in lst.execute({})['metrics']]
                assert ('finance_only' in names) is sees and 'open_metric' in names
                if sees:
                    out = desc.execute({'metric': 'finance_only'})
                    assert out['fixed_filters'] == ["order_status = 'Completed'"]   # the owner sees them
                    assert _tool('bi_query_metric').execute({'metric': 'finance_only', 'period': '2024'})['rows']
                else:
                    for name in ('bi_describe_metric', 'bi_query_metric'):
                        with pytest.raises(M.MetricError, match='unknown metric'):
                            _tool(name).execute({'metric': 'finance_only', 'period': '2024'})
                    assert 'fixed_filters' not in desc.execute({'metric': 'open_metric'})
            finally:
                reset_caller(t)


@pytest.fixture
def shop_metrics(storage_dir, monkeypatch):             # noqa: F811
    """The test_connectors 'shop' SQLite connection (secrets denied, email/ssn/card masked) and metrics on it."""
    import yaml
    from sajha.connectors import service
    db = _shop_sqlite(storage_dir)
    assert service.save(dict(SHOP, options={'path': db}), FakeRegistry(), 'admin')['success']
    d = storage_dir / 'config/bi/metrics'
    d.mkdir(parents=True)
    src = {'connector': 'shop', 'table': 'orders'}
    docs = [
        {'name': 'shop_orders', 'source': src, 'measure': {'sql': 'count(*)', 'type': 'count'},
         'time': {'column': 'created_at'}, 'dimensions': [{'name': 'status'}]},
        {'name': 'shop_revenue', 'source': src, 'measure': {'sql': 'sum(total)', 'type': 'sum'},
         'time': {'column': 'created_at'}, 'dimensions': [{'name': 'status'}], 'filters': ["status <> 'new'"]},
        {'name': 'leak_secrets', 'source': {'connector': 'shop', 'table': 'secrets'},
         'measure': {'sql': 'count(value)', 'type': 'count'}, 'time': {'column': 'id'}},
        {'name': 'by_email', 'source': {'connector': 'shop', 'table': 'customers'},
         'measure': {'sql': 'count(*)', 'type': 'count'}, 'time': {'column': 'id'},
         'dimensions': [{'name': 'email'}]},
        {'name': 'ssn_count', 'source': {'connector': 'shop', 'table': 'customers'},
         'measure': {'sql': 'count(distinct ssn)', 'type': 'count_distinct'}, 'time': {'column': 'id'}},
    ]
    (d / 'shop.yaml').write_text(yaml.safe_dump(docs))
    reg = M.Registry('config/bi/metrics')
    monkeypatch.setattr(M, '_registry', reg)
    reg.ensure(force=True)
    return reg


@pytest.fixture(params=['sqlglot', 'scanner'])
def parser(request):
    from sajha.connectors import guard
    if request.param == 'sqlglot' and not guard.sqlglot_available():
        pytest.skip('sqlglot is not installed')
    guard.use_scanner(request.param == 'scanner')
    yield request.param
    guard.use_scanner(False)


def test_connector_metric_runs_through_the_connection_with_audit(shop_metrics, parser):
    from sajha import audit
    from sajha.audit.chain import ChainWriter
    got = []
    old = (audit._writer, audit._exporter)
    audit.set_writer(ChainWriter(store=False, anchor_interval=0, anchor_every=10 ** 9, on_record=got.append))
    audit._exporter = None
    try:
        out = _tool('bi_query_metric').execute({'metric': 'shop_orders', 'by': ['status'], 'grain': 'month',
                                                'period': '2026-01'})
    finally:
        audit._writer, audit._exporter = old
    assert {(r['status'], r['value']) for r in out['rows']} == {('new', 20), ('paid', 20), ('shipped', 20)}
    assert {r['period'] for r in out['rows']} == {'2026-01'} and out['as_of'] == '2026-01-28'
    rec = [r for r in got if r.get('event') == 'connector.query']
    assert rec and rec[0]['details']['op'] == 'bi_query' and 'sql_sha256' in rec[0]['details']
    rev = _tool('bi_compare').execute({'metric': 'shop_revenue', 'period': '2026-01', 'by': ['status']})
    expected = sum(i * 1.5 for i in range(1, 61) if i % 3 != 0)          # paid and shipped
    assert rev['total']['value'] == pytest.approx(expected)
    weekly = _tool('bi_query_metric').execute({'metric': 'shop_orders', 'grain': 'week', 'period': '2026-01'})
    assert sum(r['value'] for r in weekly['rows']) == 60 and weekly['rows'][0]['period'] == '2025-12-29'


def test_a_metric_cannot_read_a_table_its_connection_denies(shop_metrics, parser):
    from sajha.connectors.drivers import ConnectorError
    with pytest.raises(ConnectorError, match='not available on connection shop'):
        _tool('bi_query_metric').execute({'metric': 'leak_secrets'})


def test_masked_columns_are_never_grouped_filtered_or_aggregated(shop_metrics):
    for name in ('by_email', 'ssn_count'):
        with pytest.raises(M.MetricError, match='masked on connection shop'):
            _tool('bi_query_metric').execute({'metric': name})
    with pytest.raises(M.MetricError, match='masked'):
        _tool('bi_top_n').execute({'metric': 'by_email', 'dimension': 'email'})


def test_connector_metric_hidden_from_callers_without_the_connection(shop_metrics):
    t = _as(('user',), allowed={'bi_list_metrics'})
    try:
        assert 'shop_orders' not in [m['name'] for m in _tool('bi_list_metrics').execute({})['metrics']]
    finally:
        reset_caller(t)
    t = _as(('user',), allowed={'bi_list_metrics', 'shop__list_tables'})
    try:
        assert 'shop_orders' in [m['name'] for m in _tool('bi_list_metrics').execute({})['metrics']]
    finally:
        reset_caller(t)


def test_olap_dataset_source(tmp_path, monkeypatch):
    import yaml
    d = tmp_path / 'm'
    d.mkdir()
    (d / 'o.yaml').write_text(yaml.safe_dump({
        'name': 'olap_customers', 'source': {'olap_dataset': 'customer_olap'},
        'measure': {'sql': 'count(distinct customer_id)', 'type': 'count_distinct'},
        'time': {'column': 'signup_date'}, 'dimensions': [{'name': 'customer_segment'}]}))
    _registry_at(monkeypatch, tmp_path, 'm')
    out = _tool('bi_query_metric').execute({'metric': 'olap_customers', 'by': ['customer_segment']})
    assert sum(r['value'] for r in out['rows']) == 50 and out['as_of']
    top = _tool('bi_top_n').execute({'metric': 'olap_customers', 'dimension': 'customer_segment', 'pareto': True})
    assert top['members'][0]['share_pct'] is None and 'note' in top['pareto']


# ── golden results on the shipped sample metrics ────────────────────────

def test_shipped_metrics_load_and_list(shipped):
    assert sorted(shipped.metrics) == ['average_order_value', 'net_sales', 'order_count'] and not shipped.refused
    out = _tool('bi_list_metrics').execute({'tag': 'kpi'})
    assert out['count'] == 3
    d = _tool('bi_describe_metric').execute({'metric': 'average_order_value'})
    assert d['ratio'] == {'numerator': 'net_sales', 'denominator': 'order_count'} and d['as_of'] == '2024-11-15'
    assert d['status'] == 'ok'


def test_golden_query_cumulative_and_rolling(shipped):
    q = _tool('bi_query_metric').execute({'metric': 'order_count', 'grain': 'month', 'period': '2024-Q1',
                                          'cumulative': 'qtd'})
    assert [(r['period'], r['value'], r['cumulative']) for r in q['rows']] == [
        ('2024-01', 4, 4), ('2024-02', 4, 8), ('2024-03', 4, 12)]
    q = _tool('bi_query_metric').execute({'metric': 'net_sales', 'grain': 'quarter', 'period': '2024',
                                          'rolling': {'window': 2, 'fn': 'sum'}})
    assert [(r['period'], r['value'], r['rolling']) for r in q['rows']] == [
        ('2024-Q1', 19116.0235, 19116.0235), ('2024-Q2', 15731.807, 34847.8305),
        ('2024-Q3', 16842.783, 32574.59), ('2024-Q4', 11207.9825, 28050.7655)]
    with pytest.raises(M.MetricError, match='additive'):
        _tool('bi_query_metric').execute({'metric': 'average_order_value', 'grain': 'month', 'cumulative': 'ytd'})


def test_golden_compare(shipped):
    o = _tool('bi_compare').execute({'metric': 'net_sales', 'period': '2024-Q3', 'against': 'same_period_last_year',
                                     'by': ['region']})
    assert o['total'] == {'value': 16842.783, 'comparison': 8394.766, 'change': 8448.017, 'pct_change': 100.6343}
    assert o['against']['from'] == '2023-07-01'
    assert [(r['region'], r['value'], r['comparison']) for r in o['rows']] == [
        ('West', 7364.625, 809.991), ('South', 3809.688, 1981.037), ('Central', 2384.19, 1709.981),
        ('East', 1784.49, 1203.824), ('North', 1499.79, 2689.933)]
    o = _tool('bi_compare').execute({'metric': 'order_count', 'period': '2024-Q3'})
    assert o['total'] == {'value': 13, 'comparison': 12, 'change': 1, 'pct_change': 8.3333}
    assert o['against']['from'] == '2024-04-01'


def test_golden_top_n_and_pareto(shipped):
    o = _tool('bi_top_n').execute({'metric': 'net_sales', 'dimension': 'sales_rep', 'n': 3, 'period': '2024',
                                   'pareto': True})
    assert o['total'] == 62898.596 and o['member_count'] == 5
    assert [(m['sales_rep'], m['share_pct'], m['cumulative_share_pct']) for m in o['members']] == [
        ('Carol Jones', 45.1187, 45.1187), ('David Chen', 17.5018, 62.6205), ('Eric Brown', 16.3893, 79.0098)]
    assert o['pareto']['members'] == ['Carol Jones', 'David Chen', 'Eric Brown', 'Alice Wang']


def test_golden_crosstab(shipped):
    o = _tool('bi_crosstab').execute({'metric': 'order_count', 'rows': 'region', 'columns': 'payment_method',
                                      'period': '2024'})
    assert o['row_headers'] == ['Central', 'East', 'North', 'South', 'West']
    assert o['column_headers'] == ['Bank Transfer', 'Credit Card', 'PayPal']
    assert o['cells'] == [[2, 5, 1], [6, 1, 2], [3, 2, 2], [None, 7, 3], [4, 8, None]]
    assert (o['row_totals'], o['column_totals'], o['grand_total']) == ([8, 9, 7, 10, 12], [15, 23, 8], 46)
    o = _tool('bi_crosstab').execute({'metric': 'average_order_value', 'rows': 'region',
                                      'columns': 'payment_method', 'period': '2024', 'normalize': 'row'})
    assert o['grand_total'] == pytest.approx(62898.596 / 46, abs=1e-5)   # a ratio's margin is computed, not summed
    assert o['cells'][0] == [102.670829, 101.308261, 88.117039]


def test_golden_explain_change_additive_and_ratio(shipped):
    o = _tool('bi_explain_change').execute({'metric': 'net_sales', 'period': '2024-Q3', 'against': '2024-Q2',
                                            'dimensions': ['region', 'product_category']})
    assert o['total']['change'] == 1110.976
    region = o['by_dimension'][0]
    assert [(m['member'], m['change']) for m in region['members']] == [
        ('West', 3022.4), ('East', -2470.4135), ('North', -2175.072), ('Central', 1934.28), ('South', 799.7815)]
    assert region['explains_most'] == ['West']
    for d in o['by_dimension']:                         # additive: member changes add up to the total change
        assert sum(m['change'] for m in d['members']) == pytest.approx(1110.976, abs=1e-3)
        assert sum(m['share_of_change_pct'] for m in d['members']) == pytest.approx(100, abs=1e-2)
    r = _tool('bi_explain_change').execute({'metric': 'average_order_value', 'period': '2024-Q3',
                                            'against': '2024-Q2', 'dimensions': ['region']})
    d = r['by_dimension'][0]
    assert r['total']['change'] == pytest.approx(-15.385224, abs=1e-6)
    assert d['rate_effect'] + d['mix_effect'] == pytest.approx(r['total']['change'], abs=1e-5)
    assert sum(m['contribution'] for m in d['members']) == pytest.approx(r['total']['change'], abs=1e-5)
    assert {m['member'] for m in d['members']} == {'Central', 'East', 'North', 'South', 'West'}


def test_tool_configs_are_read_only_with_examples_and_output_schemas():
    domain = (ROOT / 'config/tools/bi/domain.txt').read_text().strip()
    assert len(domain) <= 600
    for name in TOOLS:
        cfg = json.loads((ROOT / f'config/tools/bi/{name}.json').read_text())
        assert cfg['annotations']['readOnlyHint'] is True and cfg['annotations']['destructiveHint'] is False
        assert cfg['outputSchema']['type'] == 'object' and cfg['inputSchema']['examples']
        assert '\nExample: ' in cfg['description'] and 'cache_ttl' not in cfg
        assert len(cfg['description']) + 2 + len(domain) <= 1024
