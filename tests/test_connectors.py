# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Data Connectors (sajha/connectors/; docs/architecture/Data Connectors.md): the connection
record, the statement guard (sqlglot and the fallback scanner), parameter binding, SQLite and
DuckDB end to end (catalog, describe, query, limits, timeouts, masking, curated views and
injection into them, the read-only walls below the guard), the generated tools under the
policy engine, audit and metrics, mocked DB-API drivers for the kinds not run here (driver
missing, connect arguments, session set-up, per-user tokens), the vector and search adapters,
and the admin page and API.

PostgreSQL 16 and MySQL 8 run in tests/test_connectors_live.py when their containers are up.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import types
from pathlib import Path

import pytest

from sajha.connectors import catalog, engine, guard, model, pool, service, sqltext, store, vector
from sajha.connectors.drivers import ConnectorError, DriverMissing, QueryTimeout, get_driver
from sajha.connectors.guard import GuardError


# ── fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    import sajha.core.storage as storage
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    store.forget()
    catalog.invalidate()
    pool.clear()
    yield tmp_path
    store.forget()
    catalog.invalidate()
    pool.clear()


@pytest.fixture
def records():
    """Audit records written during the test."""
    from sajha import audit
    from sajha.audit.chain import ChainWriter
    got = []
    old = (audit._writer, audit._exporter)
    audit.set_writer(ChainWriter(store=False, anchor_interval=0, anchor_every=10 ** 9, on_record=got.append))
    audit._exporter = None
    yield got
    audit._writer, audit._exporter = old


class FakeRegistry:
    """The registry surface the service uses (load, unregister, configs, errors)."""

    def __init__(self):
        self.tools, self.tool_configs, self.tool_errors, self._file_timestamps = {}, {}, {}, {}
        self._tools_lock = threading.RLock()

    def _config_rel(self, ref):
        return f'config/tools/{Path(str(ref)).stem}.json'

    def load_tool_from_config(self, ref):
        from sajha.connectors.tools import ConnectorTool
        from sajha.core.storage import get_storage
        cfg = get_storage().read_json(self._config_rel(ref))
        self.tool_configs[cfg['name']] = cfg
        self.tools[cfg['name']] = ConnectorTool(cfg)

    def unregister_tool(self, name):
        self.tools.pop(name, None)


def _shop_sqlite(path: Path) -> str:
    db = str(path / 'shop.db')
    c = sqlite3.connect(db)
    c.executescript("""
        CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, email TEXT, ssn TEXT, card TEXT);
        CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT, total REAL, created_at TEXT);
        CREATE TABLE secrets(id INTEGER PRIMARY KEY, value TEXT);
        CREATE VIEW paid AS SELECT * FROM orders WHERE status = 'paid';
        INSERT INTO customers VALUES (1, 'Ann', 'ann@example.com', '123-45-6789', '4111 1111 1111 1111'),
                                     (2, 'Bob', 'bob@example.com', '987-65-4320', '5500 0000 0000 0004');
        INSERT INTO secrets VALUES (1, 'top secret');
    """)
    c.executemany('INSERT INTO orders VALUES (?, ?, ?, ?, ?)',
                  [(i, 1 + i % 2, ['new', 'paid', 'shipped'][i % 3], i * 1.5, f'2026-01-{1 + i % 28:02d}')
                   for i in range(1, 61)])
    c.commit()
    c.close()
    return db


SHOP = {
    'id': 'shop', 'kind': 'sqlite', 'title': 'Shop', 'description': 'Orders and customers.',
    'limits': {'max_rows': 25},
    'allow': {'tables': ['*'], 'deny_tables': ['secrets']},
    'masking': [{'column': 'email', 'mode': 'partial'}, {'column': 'customers.ssn', 'mode': 'hide'},
                {'column': 'card', 'mode': 'pii'}],
    'views': [{'name': 'orders_by_status', 'table': 'orders', 'title': 'Orders by status',
               'description': 'Orders, newest first.', 'columns': ['id', 'status', 'total', 'created_at'],
               'filters': [{'column': 'status', 'operators': ['eq', 'in'], 'enum': ['new', 'paid', 'shipped']},
                           {'column': 'total', 'operators': ['gte', 'lte']},
                           {'column': 'customer_id', 'operators': ['eq'], 'required': True},
                           {'column': 'created_at', 'operators': ['contains']}],
               'order_by': [{'column': 'id', 'direction': 'desc'}], 'max_rows': 10}],
}


@pytest.fixture
def shop(storage_dir):
    db = _shop_sqlite(storage_dir)
    reg = FakeRegistry()
    out = service.save(dict(SHOP, options={'path': db}), reg, 'admin')
    assert out['success'], out
    conn, err = store.get('shop')
    assert conn is not None, err
    return conn, reg


def _run(reg, name, args):
    return reg.tools[name].execute_with_tracking(args)


# ── the connection record ───────────────────────────────────────────────

@pytest.mark.parametrize('bad, why', [
    ({'id': 'Shop', 'kind': 'sqlite', 'options': {'path': 'x'}}, 'id'),
    ({'id': 'a__b', 'kind': 'sqlite', 'options': {'path': 'x'}}, 'id'),
    ({'id': 'x', 'kind': 'mongo'}, 'kind'),
    ({'id': 'x', 'kind': 'postgresql', 'options': {'password': 'hunter2'}}, 'secrets'),
    ({'id': 'x', 'kind': 'postgresql', 'options': {'api_key': 'k'}}, 'secrets'),
    ({'id': 'x', 'kind': 'postgresql', 'secrets': {'password': 'hunter2'}}, 'secret reference'),
    ({'id': 'x', 'kind': 'sqlite'}, 'options.path'),
    ({'id': 'x', 'kind': 'postgresql', 'masking': [{'column': 'email', 'mode': 'blur'}]}, 'mode'),
    ({'id': 'x', 'kind': 'postgresql', 'views': [{'name': 'query', 'table': 't'}]}, 'reserved'),
    ({'id': 'x', 'kind': 'postgresql', 'views': [{'name': 'v', 'table': 't',
                                                  'filters': [{'column': 'a', 'operators': ['regex']}]}]},
     'operators'),
    ({'id': 'x', 'kind': 'postgresql', 'auth': {'type': 'connected_account', 'provider': 'github'}}, 'per-user'),
    ({'id': 'x', 'kind': 'pgvector'}, 'vector'),
    ({'id': 'x', 'kind': 'qdrant', 'views': [{'name': 'v', 'table': 't'}]}, 'views'),
    ({'id': 'x', 'kind': 'postgresql', 'bogus': 1}, 'unknown'),
])
def test_invalid_records_are_refused_with_the_field(bad, why):
    with pytest.raises(model.ConnectorConfigError, match=why):
        model.parse(bad)


def test_limits_default_and_are_capped(monkeypatch):
    monkeypatch.setenv('SAJHA_CONNECTORS_MAX_ROWS_LIMIT', '100')
    c = model.parse({'id': 'x', 'kind': 'postgresql', 'limits': {'max_rows': 5000, 'timeout_seconds': 5}})
    assert c.max_rows == 100 and c.timeout_seconds == 5 and c.max_bytes > 0
    assert model.parse({'id': 'y', 'kind': 'postgresql'}).max_rows == 100   # default 500, capped


def test_allowlist_and_masking_rules():
    c = model.parse({'id': 'x', 'kind': 'postgresql', 'allow': {'schemas': ['public', 'sales'],
                                                                'tables': ['*'], 'deny_tables': ['sales.audit_*']},
                     'masking': [{'column': 'crm.customers.email', 'mode': 'hash'}, {'column': '*ssn', 'mode': 'hide'}]})
    assert c.table_allowed('public', 'orders') and c.table_allowed('SALES', 'orders')
    assert not c.table_allowed('sales', 'audit_log') and not c.table_allowed('hr', 'people')
    assert c.mask_rules_for('email', [('crm', 'customers')]).mode == 'hash'
    assert c.mask_rules_for('email', [('public', 'orders')]) is None
    assert c.mask_rules_for('tax_ssn', [('public', 'orders')]).mode == 'hide'


def test_record_round_trips():
    c = model.parse(dict(SHOP, options={'path': '/x.db'}))
    again = model.parse(model.to_record(c))
    assert model.to_record(again) == model.to_record(c)


# ── tokenizer and parameters ────────────────────────────────────────────

def test_tokenizer_tells_code_from_strings_comments_and_casts():
    toks = sqltext.code(sqltext.tokenize("SELECT 'a;b' AS \"x;y\", c::int -- ; DROP\n FROM t /* ; */", 'postgres'))
    assert [t.kind for t in toks if t.kind in ('string', 'qident')] == ['string', 'qident']
    assert sqltext.count_statements(sqltext.tokenize("SELECT ';' -- ;\n", 'postgres')) == 1
    assert sqltext.count_statements(sqltext.tokenize('SELECT 1; SELECT 2', 'postgres')) == 2
    for bad in ("SELECT 'open", 'SELECT "open', 'SELECT 1 /* open'):
        with pytest.raises(sqltext.SQLTextError):
            sqltext.tokenize(bad, 'postgres')
    # a backslash ends nothing in standard SQL, so the statement after it is seen
    assert sqltext.count_statements(sqltext.tokenize("SELECT 'a\\'; DROP TABLE t; --'", 'postgres')) >= 2
    # MySQL escapes with a backslash, so the same text is one string there
    assert sqltext.count_statements(sqltext.tokenize("SELECT 'a\\'; DROP TABLE t; --'", 'mysql')) == 1
    assert sqltext.count_statements(sqltext.tokenize('SELECT $$a;b$$', 'postgres')) == 1


@pytest.mark.parametrize('style, expect_sql, expect_params', [
    ('pyformat', "SELECT * FROM t WHERE a = %(a)s AND b LIKE '50%%' AND c::int = %(c)s", {'a': 1, 'c': 2}),
    ('named', "SELECT * FROM t WHERE a = :a AND b LIKE '50%' AND c::int = :c", {'a': 1, 'c': 2}),
    ('qmark', "SELECT * FROM t WHERE a = ? AND b LIKE '50%' AND c::int = ?", [1, 2]),
    ('dollar', "SELECT * FROM t WHERE a = $a AND b LIKE '50%' AND c::int = $c", {'a': 1, 'c': 2}),
])
def test_parameters_are_rewritten_for_the_driver_outside_strings_and_casts(style, expect_sql, expect_params):
    sql = "SELECT * FROM t WHERE a = :a AND b LIKE '50%' AND c::int = :c"
    assert sqltext.bind_params(sql, {'a': 1, 'c': 2}, style, 'postgres') == (expect_sql, expect_params)


def test_parameters_missing_or_unused_are_errors():
    with pytest.raises(ValueError, match='no value'):
        sqltext.bind_params('SELECT :a', {}, 'named')
    with pytest.raises(ValueError, match='not used'):
        sqltext.bind_params('SELECT 1', {'a': 1}, 'named')
    assert sqltext.bind_params("SELECT ':a'", {}, 'named') == ("SELECT ':a'", None)


# ── the guard, both ways ────────────────────────────────────────────────

GUARD_CONN = model.parse({'id': 'g', 'kind': 'postgresql',
                          'masking': [{'column': 'email', 'mode': 'redact'}, {'column': 'ssn', 'mode': 'hide'}]})
_TABLES = [{'schema': 'public', 'name': 'orders'}, {'schema': 'public', 'name': 'customers'},
           {'schema': 'sales', 'name': 'orders'}]


def _resolve(cat, schema, name):
    return catalog.resolve_in(GUARD_CONN, _TABLES, 'public', ['shop'], cat, schema, name)


@pytest.fixture(params=['sqlglot', 'scanner'])
def parser(request, monkeypatch):
    if request.param == 'sqlglot' and not guard.sqlglot_available():
        pytest.skip('sqlglot is not installed')
    guard.use_scanner(request.param == 'scanner')
    yield request.param
    guard.use_scanner(False)


REFUSED = [
    'DELETE FROM orders', 'UPDATE orders SET total = 0', "INSERT INTO orders VALUES (1)", 'DROP TABLE orders',
    'TRUNCATE orders', 'ALTER TABLE orders ADD x int', 'CREATE TABLE x (a int)', 'GRANT ALL ON orders TO public',
    "COPY orders TO '/tmp/x'", "COPY (SELECT 1) TO PROGRAM 'id'", 'CALL p()', 'SET search_path = evil',
    'SELECT 1; DROP TABLE orders', 'SELECT 1; SELECT 2', 'SELECT * INTO x FROM orders',
    'SELECT * FROM orders FOR UPDATE', 'SELECT * FROM orders FOR SHARE',
    'WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d',
    'EXPLAIN ANALYZE DELETE FROM orders', 'BEGIN', 'VACUUM', 'LISTEN x',
    "SELECT pg_read_file('/etc/passwd')", "SELECT pg_ls_dir('.')", "SELECT lo_import('/etc/passwd')",
    "SELECT * FROM dblink('host=x', 'select 1') AS t(a int)", "SELECT query_to_xml('delete from orders', true, true, '')",
    "SELECT set_config('default_transaction_read_only', 'off', false)", "SELECT nextval('s')",
    "SELECT pg_terminate_backend(1)", "SELECT load_file('/etc/passwd')", "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM openrowset('x', 'y')", "SELECT utl_http.request('http://x') FROM orders",
    "SELECT dbms_pipe.receive_message('x') FROM orders", "SELECT system$cancel_all_queries('x')",
    'SELECT * FROM pg_shadow', 'SELECT * FROM pg_catalog.pg_authid', 'SELECT * FROM information_schema.tables',
    'SELECT * FROM other_db.public.orders', 'SELECT * FROM hr.people',
    'SELECT ssn FROM public.customers', 'SELECT upper(email) FROM public.customers',
    'SELECT email AS e FROM public.customers', "SELECT id FROM public.customers WHERE email LIKE 'a%'",
    'SELECT id FROM public.customers ORDER BY email', "SELECT 'x' UNION SELECT email FROM public.customers",
    'SELECT * FROM (SELECT * FROM public.customers) s', 'SELECT row_to_json(c) FROM public.customers c',
    "SELECT 'unterminated", 'SELECT 1 /* open',
]


@pytest.mark.parametrize('sql', REFUSED)
def test_the_guard_refuses(parser, sql):
    with pytest.raises(GuardError):
        guard.check(sql, GUARD_CONN, _resolve, limit=10)


ALLOWED = [
    'SELECT 1', 'select * from public.orders', 'SELECT o.id, c.name FROM public.orders o JOIN customers c ON c.id = o.customer_id',
    'WITH x AS (SELECT id FROM sales.orders) SELECT * FROM x', 'SELECT * FROM public.orders WHERE id = :id',
    "SELECT id FROM customers WHERE name = 'DROP TABLE x; --'", 'SELECT count(*) FROM public.customers',
    'SELECT * FROM public.customers', 'SELECT * FROM shop.public.orders', 'SELECT * FROM orders',
    'SELECT id FROM public.orders ORDER BY id LIMIT 5', 'SELECT 1;', 'SELECT g FROM generate_series(1, 3) g',
]


@pytest.mark.parametrize('sql', ALLOWED)
def test_the_guard_allows(parser, sql):
    out = guard.check(sql, GUARD_CONN, _resolve, limit=10)
    assert out.sql.rstrip().endswith(('LIMIT 10', 'LIMIT 5'))


def test_unqualified_names_resolve_to_the_default_schema_and_masked_columns_by_parser(parser):
    assert guard.check('SELECT * FROM orders', GUARD_CONN, _resolve).tables == [('public', 'orders')]
    if parser == 'sqlglot':        # a masked column may be selected as itself
        assert guard.check('SELECT email FROM public.customers', GUARD_CONN, _resolve).tables
    else:                          # the scanner refuses any mention of it
        with pytest.raises(GuardError, match='masked'):
            guard.check('SELECT email FROM public.customers', GUARD_CONN, _resolve)


def test_the_guard_reports_tables_and_appends_the_limit_on_its_own_line(parser):
    out = guard.check('SELECT * FROM public.orders -- note', GUARD_CONN, _resolve, limit=11)
    assert out.tables == [('public', 'orders')] and out.sql.endswith('\nLIMIT 11') and out.limited
    assert guard.check('SELECT * FROM public.orders LIMIT 3', GUARD_CONN, _resolve, limit=11).sql.endswith('LIMIT 3')


def test_require_sqlglot_refuses_the_scanner(monkeypatch):
    guard.use_scanner(True)
    try:
        with pytest.raises(GuardError, match='sqlglot'):
            guard.check('SELECT 1', GUARD_CONN, _resolve, require_parser=True)
    finally:
        guard.use_scanner(False)


# ── SQLite end to end through the generated tools ───────────────────────

def test_saving_generates_planner_friendly_read_only_tools(shop, storage_dir):
    conn, reg = shop
    assert sorted(reg.tools) == ['shop__describe_table', 'shop__list_tables', 'shop__orders_by_status', 'shop__query']
    cfg = reg.tool_configs['shop__query']
    assert cfg['implementation'] == 'sajha.connectors.tools.ConnectorTool'
    assert cfg['annotations']['readOnlyHint'] is True and cfg['annotations']['destructiveHint'] is False
    assert 'shop__list_tables' in cfg['description'] and 'shop__describe_table' in cfg['description']
    assert ':name' in cfg['description'] and 'Orders and customers.' in cfg['description']
    assert 'shop__describe_table' in reg.tool_configs['shop__list_tables']['description']
    assert (storage_dir / 'config' / 'connectors' / 'shop.json').exists()
    assert (storage_dir / 'config' / 'tools' / 'shop__query.json').exists()
    # the record holds no secret values and the tool configs hold no connection settings
    assert 'path' not in json.dumps(cfg) and cfg['connector'] == {'connection': 'shop', 'op': 'query'}


def test_list_and_describe_respect_the_allowlist_and_masking(shop):
    conn, reg = shop
    out = _run(reg, 'shop__list_tables', {})
    names = [t['name'] for t in out['tables']]
    assert names == ['customers', 'orders', 'paid'] and 'secrets' not in names
    assert _run(reg, 'shop__list_tables', {'pattern': 'ord'})['tables'][0]['name'] == 'orders'
    d = _run(reg, 'shop__describe_table', {'table': 'customers'})
    cols = {c['name']: c for c in d['columns']}
    assert cols['ssn'] == {'name': 'ssn', 'masked': 'hide'} and cols['email']['masked'] == 'partial'
    assert d['primary_key'] == ['id'] and len(d['sample_rows']) == 2
    row = d['sample_rows'][0]
    assert 'ssn' not in row and row['email'].endswith('.com') and 'ann@' not in row['email']
    assert '4111 1111 1111 1111' not in json.dumps(d) and row['card'].endswith('1111')
    with pytest.raises(ConnectorError, match='not available'):
        _run(reg, 'shop__describe_table', {'table': 'secrets'})


def test_query_binds_parameters_caps_rows_and_masks(shop, records):
    conn, reg = shop
    out = _run(reg, 'shop__query', {'sql': 'SELECT id, status FROM orders WHERE status = :s ORDER BY id',
                                    'params': {'s': 'paid'}})
    assert out['row_count'] == 20 and not out['truncated'] and out['rows'][0] == {'id': 1, 'status': 'paid'}
    many = _run(reg, 'shop__query', {'sql': 'SELECT * FROM orders'})
    assert many['row_count'] == 25 and many['truncated'] and many['truncated_reason'] == 'rows'
    assert _run(reg, 'shop__query', {'sql': 'SELECT * FROM orders', 'max_rows': 3})['row_count'] == 3
    star = _run(reg, 'shop__query', {'sql': 'SELECT * FROM customers'})
    assert all('ssn' not in r for r in star['rows']) and 'ssn' not in [c['name'] for c in star['columns']]
    assert star['rows'][0]['email'] != 'ann@example.com'
    # an injection attempt in a parameter is only ever a value
    out = _run(reg, 'shop__query', {'sql': 'SELECT count(*) AS n FROM orders WHERE status = :s',
                                    'params': {'s': "paid' OR '1'='1"}})
    assert out['rows'] == [{'n': 0}]
    ok = [r for r in records if r['event'] == 'connector.query' and r['details'].get('op') == 'query']
    assert ok and ok[-1]['resource'] == {'type': 'data_connection', 'id': 'shop'}
    assert 'sql_sha256' in ok[-1]['details'] and 'sql' not in ok[-1]['details']


def test_refused_sql_is_audited_and_counted(shop, records):
    from sajha.connectors.engine import _families
    conn, reg = shop
    before = _families()[0].value(('shop', 'query', 'rejected'))
    for sql in ('DELETE FROM orders', 'SELECT * FROM secrets', 'SELECT ssn FROM customers', "ATTACH 'x' AS y",
                'PRAGMA writable_schema = 1', "SELECT load_extension('evil')"):
        with pytest.raises(GuardError):
            _run(reg, 'shop__query', {'sql': sql})
    assert _families()[0].value(('shop', 'query', 'rejected')) == before + 6
    assert len([r for r in records if r['event'] == 'connector.rejected']) == 6


def test_byte_cap(shop, monkeypatch):
    conn, reg = shop
    raw = store.load_raw('shop')
    raw['limits']['max_bytes'] = 1024
    service.save(raw, reg)
    out = _run(reg, 'shop__query', {'sql': 'SELECT * FROM orders'})
    assert out['truncated'] and out['truncated_reason'] == 'bytes' and 0 < out['row_count'] < 25


def test_sqlite_is_opened_read_only_below_the_guard(shop):
    conn, _ = shop
    with engine.session(conn) as (drv, dbc, st):
        for sql in ('DELETE FROM orders', "INSERT INTO secrets VALUES (2, 'x')", 'DROP TABLE orders'):
            with pytest.raises(sqlite3.DatabaseError):
                dbc.execute(sql)
        st['broken'] = True


def test_long_query_times_out_and_the_connection_is_discarded(storage_dir):
    db = _shop_sqlite(storage_dir)
    reg = FakeRegistry()
    service.save({'id': 'slow', 'kind': 'sqlite', 'options': {'path': db}, 'limits': {'timeout_seconds': 1}}, reg)
    sql = ('WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) '
           'SELECT count(*) FROM r WHERE n < 0')
    with pytest.raises(QueryTimeout, match='timed out after 1s'):
        _run(reg, 'slow__query', {'sql': sql})
    assert pool.stats().get('slow', 0) == 0
    assert _run(reg, 'slow__query', {'sql': 'SELECT 1 AS one'})['rows'] == [{'one': 1}]


# ── curated views ───────────────────────────────────────────────────────

def test_view_tool_has_a_typed_closed_schema(shop):
    conn, reg = shop
    schema = reg.tool_configs['shop__orders_by_status']['inputSchema']
    p = schema['properties']
    assert schema['additionalProperties'] is False and schema['required'] == ['customer_id']
    assert p['status']['enum'] == ['new', 'paid', 'shipped'] and p['status_in']['type'] == 'array'
    assert p['total_from']['type'] == 'number' and p['customer_id']['type'] == 'integer'
    assert p['created_at_contains']['type'] == 'string' and p['limit']['maximum'] == 10


def test_view_runs_with_bound_values(shop):
    conn, reg = shop
    out = _run(reg, 'shop__orders_by_status', {'customer_id': 1, 'status_in': ['paid', 'new'], 'total_from': 30})
    assert out['row_count'] == 10 and out['truncated']                            # view max_rows 10
    assert [c['name'] for c in out['columns']] == ['id', 'status', 'total', 'created_at']
    assert all(r['total'] >= 30 and r['status'] in ('paid', 'new') for r in out['rows'])
    assert [r['id'] for r in out['rows']] == sorted((r['id'] for r in out['rows']), reverse=True)
    assert _run(reg, 'shop__orders_by_status', {'customer_id': 1, 'created_at_contains': '-01-1',
                                                'limit': 2})['row_count'] == 2


@pytest.mark.parametrize('args', [
    {'customer_id': 1, 'status': "paid' OR '1'='1"},
    {'customer_id': 1, 'created_at_contains': "%' OR 1=1 --"},
    {'customer_id': 1, 'created_at_contains': '%'},
    {'customer_id': 1, 'created_at_contains': '_'},
])
def test_view_values_cannot_inject(shop, args):
    conn, reg = shop
    if 'status' in args:
        with pytest.raises(Exception, match='enum|not one of'):
            _run(reg, 'shop__orders_by_status', args)              # the schema's enum
        out = engine.run_view(conn, 'orders_by_status', args)       # below the schema: still only a value
    else:
        out = _run(reg, 'shop__orders_by_status', args)
    assert out['row_count'] == 0


def test_view_refuses_unknown_arguments_and_bad_shapes(shop):
    conn, reg = shop
    with pytest.raises(Exception, match='(?i)additional|unknown'):
        _run(reg, 'shop__orders_by_status', {'customer_id': 1, 'id; DROP TABLE orders': 1})
    with pytest.raises(GuardError, match='unknown argument'):
        engine.run_view(conn, 'orders_by_status', {'customer_id': 1, 'evil': 1})
    with pytest.raises(GuardError, match='required'):
        engine.run_view(conn, 'orders_by_status', {})
    with pytest.raises(GuardError, match='list'):
        engine.run_view(conn, 'orders_by_status', {'customer_id': 1, 'status_in': 'paid'})


def test_view_on_a_missing_or_masked_column_is_refused_at_save(shop):
    conn, reg = shop
    raw = store.load_raw('shop')
    raw['views'] = [{'name': 'bad', 'table': 'orders', 'columns': ['nope']}]
    with pytest.raises(service.ConnectorServiceError, match='nope'):
        service.save(raw, reg)
    raw['views'] = [{'name': 'bad', 'table': 'customers', 'filters': [{'column': 'email', 'operators': ['eq']}]}]
    with pytest.raises(service.ConnectorServiceError, match='masked'):
        service.save(raw, reg)
    raw['views'] = [{'name': 'bad', 'table': 'customers', 'columns': ['ssn']}]
    with pytest.raises(service.ConnectorServiceError, match='hidden'):
        service.save(raw, reg)
    assert 'shop__orders_by_status' in reg.tools                    # nothing was saved


# ── tools: sync, edit, disable, delete, conflicts ───────────────────────

def test_edits_apply_without_regenerating_and_tools_follow_switches(shop, monkeypatch):
    conn, reg = shop
    monkeypatch.setenv('SAJHA_CONNECTORS_RECORD_REFRESH_SECONDS', '0')
    raw = store.load_raw('shop')
    raw['tools'] = {'query': False}
    raw['views'] = []
    out = service.save(raw, reg)
    assert sorted(out['removed']) == ['shop__orders_by_status', 'shop__query']
    assert sorted(reg.tools) == ['shop__describe_table', 'shop__list_tables']
    raw['enabled'] = False
    service.save(raw, reg)
    assert reg.tools == {}
    raw['enabled'] = True
    raw['tools'] = {}
    service.save(raw, reg)
    assert 'shop__query' in reg.tools
    # a limit change reaches a running tool through the record alone
    raw = store.load_raw('shop')
    raw['limits']['max_rows'] = 2
    store.save(raw)
    assert _run(reg, 'shop__query', {'sql': 'SELECT * FROM orders'})['row_count'] == 2
    assert service.delete('shop', reg)['removed'] and reg.tools == {}
    with pytest.raises(ConnectorError, match='does not exist'):
        from sajha.connectors.tools import ConnectorTool
        ConnectorTool({'name': 'shop__query', 'connector': {'connection': 'shop', 'op': 'query'},
                       'inputSchema': {'type': 'object'}}).execute({'sql': 'SELECT 1'})


def test_name_conflicts_and_orphans(storage_dir):
    db = _shop_sqlite(storage_dir)
    reg = FakeRegistry()
    reg.tools['dup__query'] = object()
    reg.tool_configs['dup__query'] = {'name': 'dup__query'}
    out = service.save({'id': 'dup', 'kind': 'sqlite', 'options': {'path': db}}, reg)
    assert not out['success'] and out['failed'][0]['name'] == 'dup__query'
    # tools whose connection record vanished are removed by sync_all
    service.save({'id': 'gone', 'kind': 'sqlite', 'options': {'path': db}}, reg)
    store.delete('gone')
    res = service.sync_all(reg)
    assert set(res['orphans_removed']) == {'gone__list_tables', 'gone__describe_table', 'gone__query'}


def test_connectors_switch_off(shop, monkeypatch):
    conn, reg = shop
    monkeypatch.setenv('SAJHA_CONNECTORS_ENABLED', 'false')
    with pytest.raises(ConnectorError, match='turned off'):
        _run(reg, 'shop__list_tables', {})


def test_generated_tools_are_governed_by_the_policy_engine(shop):
    import textwrap
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.errors import PolicyDenied
    from sajha.policy.loader import PolicySet
    from sajha.policy.model import parse_text
    conn, reg = shop
    ps = PolicySet()
    ps.set_policies([parse_text(textwrap.dedent('''
        rules:
          - id: no-free-sql
            match: {tools: ["shop__query"]}
            effect: deny
            reason: use the curated views
    '''), 'p', 'p.yaml')])
    set_engine(PolicyEngine(ps))
    try:
        with pytest.raises(PolicyDenied, match='curated views'):
            _run(reg, 'shop__query', {'sql': 'SELECT 1'})
        assert _run(reg, 'shop__list_tables', {})['row_count'] == 3
    finally:
        set_engine(None)


def test_cache_ttl_is_copied_to_tools(storage_dir):
    db = _shop_sqlite(storage_dir)
    reg = FakeRegistry()
    service.save({'id': 'c', 'kind': 'sqlite', 'options': {'path': db}, 'cache_ttl': 60}, reg)
    assert reg.tool_configs['c__query']['cache_ttl'] == 60


def test_test_and_list_and_kinds(shop):
    conn, reg = shop
    out = service.test(store.load_raw('shop'))
    assert out['success'] and out['server_version'].startswith('SQLite') and out['tables'] == 3
    assert service.test({'id': 'x', 'kind': 'sqlite', 'options': {'path': '/no/such.db'}})['success'] is False
    listed = service.list_connections(reg)[0]
    assert listed['id'] == 'shop' and listed['valid'] and {t['name'] for t in listed['tools']} == set(reg.tools)
    kinds = {k['kind']: k for k in service.kinds()}
    assert kinds['sqlite']['installed'] and kinds['snowflake']['pip'] == 'snowflake-connector-python'
    assert kinds['snowflake']['per_user'] and not kinds['postgresql']['per_user']


# ── DuckDB ──────────────────────────────────────────────────────────────

@pytest.fixture
def duck(storage_dir):
    duckdb = pytest.importorskip('duckdb')
    p = str(storage_dir / 'a.duckdb')
    c = duckdb.connect(p)
    c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v VARCHAR); INSERT INTO t VALUES (1, 'a'), (2, 'b');"
              "COMMENT ON TABLE t IS 'the t table'; COMMENT ON COLUMN t.v IS 'a value'")
    c.close()
    (storage_dir / 'secret.csv').write_text('x\n1\n')
    reg = FakeRegistry()
    service.save({'id': 'dk', 'kind': 'duckdb', 'options': {'path': p}, 'limits': {'timeout_seconds': 1}}, reg)
    return store.get('dk')[0], reg, storage_dir


def test_duckdb_catalog_query_and_walls(duck):
    conn, reg, d = duck
    assert _run(reg, 'dk__list_tables', {})['tables'] == [{'schema': 'main', 'name': 't', 'type': 'table',
                                                           'comment': 'the t table'}]
    cols = _run(reg, 'dk__describe_table', {'table': 't'})['columns']
    assert cols[1]['comment'] == 'a value'
    assert _run(reg, 'dk__query', {'sql': 'SELECT v FROM t WHERE id = :i', 'params': {'i': 2}})['rows'] == [{'v': 'b'}]
    secret = str(d / 'secret.csv')
    for sql in (f"SELECT * FROM read_csv('{secret}')", f"SELECT * FROM '{secret}'", "SELECT * FROM glob('/*')",
                "INSTALL httpfs", "ATTACH 'x.db'", 'SET enable_external_access = true'):
        with pytest.raises(GuardError):
            _run(reg, 'dk__query', {'sql': sql})
    # below the guard: no file access and no writes
    with engine.session(conn) as (drv, dbc, st):
        with pytest.raises(Exception, match='(?i)external|permission|disabled'):
            dbc.execute(f"SELECT * FROM read_csv('{secret}')").fetchall()
        with pytest.raises(Exception, match='(?i)read-only|read only'):
            dbc.execute('INSERT INTO t VALUES (3, \'c\')')
        st['broken'] = True
    with pytest.raises(QueryTimeout):
        _run(reg, 'dk__query', {'sql': 'SELECT count(*) FROM range(100000000) a, range(100000000) b'})


# ── mocked DB-API drivers ───────────────────────────────────────────────

class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, None, []
        self.connection = conn

    def execute(self, sql, params=None, **kw):
        self.conn.executed.append((sql, params, kw))
        result = self.conn.answer(sql, params)
        if result is None:
            self.description, self._rows = None, []
        else:
            cols, rows = result
            self.description = [(c, None) for c in cols]
            self._rows = list(rows)

    def fetchmany(self, n):
        out, self._rows = self._rows[:n], self._rows[n:]
        return out

    def fetchall(self):
        out, self._rows = self._rows, []
        return out

    def close(self):
        pass


class FakeDBAPI:
    """A DB-API connection that records what it was asked and answers from a table."""

    def __init__(self, tables=None):
        self.executed, self.rolled_back, self.closed = [], 0, False
        self.tables = tables or {}

    def cursor(self):
        return FakeCursor(self)

    def answer(self, sql, params):
        s = sql.lower()
        if 'information_schema.tables' in s or 'all_tab_comments' in s or 'sys.objects' in s:
            return ['s', 'n', 't', 'c'], [('PUBLIC', 'ORDERS', 'BASE TABLE', 'All orders')]
        if 'information_schema.columns' in s or 'all_tab_columns' in s or 'sys.columns' in s:
            return ['n', 't', 'nl', 'c'], [('ID', 'NUMBER', 'NO', ''), ('STATUS', 'TEXT', 'YES', 'state')]
        if 'current_version' in s:
            return ['v'], [('8.1',)]
        if s.lstrip().startswith(('select', 'with')) and 'orders' in s:
            return ['ID', 'STATUS'], [(1, 'paid'), (2, 'new')]
        return None

    def rollback(self):
        self.rolled_back += 1

    def commit(self):
        pass

    def close(self):
        self.closed = True


def _fake_module(monkeypatch, name, connect):
    parts = name.split('.')
    for i in range(1, len(parts) + 1):
        mod_name = '.'.join(parts[:i])
        mod = sys.modules.get(mod_name) if mod_name in sys.modules and i < len(parts) else types.ModuleType(mod_name)
        monkeypatch.setitem(sys.modules, mod_name, mod)
        if i > 1:
            setattr(sys.modules['.'.join(parts[:i - 1])], parts[i - 1], mod)
    sys.modules[name].connect = connect
    return sys.modules[name]


def test_a_missing_driver_names_the_package(storage_dir, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_snowflake(name, *a, **kw):
        if name.startswith('snowflake'):
            raise ImportError(f'No module named {name!r}')
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, '__import__', no_snowflake)
    for k in [k for k in sys.modules if k.startswith('snowflake')]:
        monkeypatch.delitem(sys.modules, k)
    conn = model.parse({'id': 'sf', 'kind': 'snowflake', 'options': {'account': 'a', 'user': 'u'}})
    with pytest.raises(DriverMissing, match="pip install 'snowflake-connector-python'"):
        engine.list_tables(conn)
    out = service.test({'id': 'sf', 'kind': 'snowflake', 'options': {'account': 'a'}})
    assert not out['success'] and 'snowflake-connector-python' in out['error']


def test_snowflake_connect_arguments_session_and_query(storage_dir, monkeypatch):
    calls = []
    fake = FakeDBAPI()

    def connect(**kw):
        calls.append(kw)
        return fake
    _fake_module(monkeypatch, 'snowflake.connector', connect)
    monkeypatch.setenv('SF_PW', 's3cret-value')
    conn = model.parse({'id': 'sf', 'kind': 'snowflake', 'secrets': {'password': 'env:SF_PW'},
                        'options': {'account': 'acme-x1', 'user': 'svc', 'warehouse': 'WH', 'database': 'DB',
                                    'role': 'READER'}, 'limits': {'timeout_seconds': 7}})
    out = engine.query(conn, 'SELECT id, status FROM orders WHERE status = :s', {'s': 'paid'})
    kw = calls[0]
    assert kw['password'] == 's3cret-value' and kw['role'] == 'READER' and kw['autocommit'] is False
    assert kw['session_parameters']['STATEMENT_TIMEOUT_IN_SECONDS'] == 7
    sql, params, _ = fake.executed[-1]
    assert '%(s)s' in sql and params == {'s': 'paid'} and sql.rstrip().endswith('LIMIT 501')
    assert out['rows'] == [{'ID': 1, 'STATUS': 'paid'}, {'ID': 2, 'STATUS': 'new'}] and fake.rolled_back


def test_snowflake_per_user_token_comes_from_the_connected_account(storage_dir, monkeypatch):
    calls = []
    _fake_module(monkeypatch, 'snowflake.connector', lambda **kw: calls.append(kw) or FakeDBAPI())
    from sajha.accounts import injection
    tok = types.SimpleNamespace(access_token='user-oauth-token')
    monkeypatch.setattr(injection, 'current_token', lambda provider=None: tok)
    conn = model.parse({'id': 'sf', 'kind': 'snowflake', 'options': {'account': 'a', 'user': 'u'},
                        'auth': {'type': 'connected_account', 'provider': 'snowflake', 'scopes': ['session:role:R']}})
    engine.query(conn, 'SELECT * FROM orders')
    engine.query(conn, 'SELECT * FROM orders')
    assert calls[0]['authenticator'] == 'oauth' and calls[0]['token'] == 'user-oauth-token'
    assert 'password' not in calls[0] and len(calls) >= 3          # never pooled
    assert pool.stats().get('sf', 0) == 0
    cfg = service.tool_configs(conn)['sf__query']
    assert cfg['auth'] == {'connected_account': 'snowflake', 'scopes': ['session:role:R']}
    from sajha.core.cache import get_tool_ttl
    assert get_tool_ttl('sf__query', dict(cfg, cache_ttl=60)) == 0


def test_databricks_and_sqlserver_and_oracle_session_setup(storage_dir, monkeypatch):
    seen = {}
    fake = FakeDBAPI()
    _fake_module(monkeypatch, 'databricks.sql', lambda **kw: seen.setdefault('databricks', kw) and fake or fake)
    conn = model.parse({'id': 'db', 'kind': 'databricks', 'secrets': {'token': 'env:DBX'},
                        'options': {'host': 'x.cloud.databricks.com', 'http_path': '/sql/1', 'catalog': 'main'}})
    monkeypatch.setenv('DBX', 'dapi-123')
    engine.query(conn, 'SELECT * FROM orders WHERE id = :i', {'i': 1})
    assert seen['databricks']['access_token'] == 'dapi-123'
    assert seen['databricks']['session_configuration'] == {'STATEMENT_TIMEOUT': '30'}
    assert fake.executed[-1][0].count(':i') == 1 and fake.executed[-1][1] == {'i': 1}

    fake2 = FakeDBAPI()
    odbc = _fake_module(monkeypatch, 'pyodbc', lambda cs, **kw: seen.setdefault('odbc', (cs, kw)) and fake2 or fake2)
    monkeypatch.setenv('MSPW', 'p;w}d')
    conn = model.parse({'id': 'ms', 'kind': 'sqlserver', 'secrets': {'password': 'env:MSPW'},
                        'options': {'host': 'sql1', 'port': 1433, 'database': 'Shop', 'user': 'reader'}})
    engine.query(conn, 'SELECT * FROM orders WHERE id = :i', {'i': 1})
    cs = seen['odbc'][0]
    assert 'ApplicationIntent={ReadOnly}' in cs and 'PWD={p;w}}d}' in cs and odbc is sys.modules['pyodbc']
    assert fake2.timeout == 30
    assert fake2.executed[-1][0].endswith('WHERE id = ?') and fake2.executed[-1][1] == [1]   # no LIMIT in T-SQL

    fake3 = FakeDBAPI()
    _fake_module(monkeypatch, 'oracledb', lambda **kw: seen.setdefault('oracle', kw) and fake3 or fake3)
    conn = model.parse({'id': 'ora', 'kind': 'oracle', 'options': {'host': 'o1', 'service_name': 'ORCL',
                                                                    'user': 'scott'}})
    engine.query(conn, 'SELECT * FROM orders')
    assert seen['oracle']['dsn'] == 'o1:1521/ORCL' and fake3.call_timeout == 30000
    assert [e[0] for e in fake3.executed].count('SET TRANSACTION READ ONLY') >= 1


def test_bigquery_uses_the_byte_billing_cap(storage_dir, monkeypatch):
    fake = FakeDBAPI()
    jobs = []

    class QueryJobConfig:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            jobs.append(self)
    bq = _fake_module(monkeypatch, 'google.cloud.bigquery', None)
    bq.QueryJobConfig = QueryJobConfig
    bq.Client = lambda **kw: ('client', kw)
    dbapi = _fake_module(monkeypatch, 'google.cloud.bigquery.dbapi', lambda client: fake)
    assert dbapi
    conn = model.parse({'id': 'bq', 'kind': 'bigquery', 'options': {'project': 'p1'},
                        'allow': {'schemas': ['PUBLIC']}, 'limits': {'max_bytes_billed': 10 ** 9}})
    tables = engine.list_tables(conn)['tables']
    assert tables and '`PUBLIC`.INFORMATION_SCHEMA.TABLES' in fake.executed[0][0]
    engine.query(conn, 'SELECT * FROM orders')
    assert jobs[-1].maximum_bytes_billed == 10 ** 9 and jobs[-1].job_timeout_ms == 30000


def test_secret_values_never_reach_an_error(storage_dir, monkeypatch):
    monkeypatch.setenv('PW', 'very-secret-password')

    def connect(**kw):
        raise RuntimeError(f"auth failed for password={kw['password']}")
    _fake_module(monkeypatch, 'snowflake.connector', connect)
    conn = model.parse({'id': 'sf', 'kind': 'snowflake', 'secrets': {'password': 'env:PW'},
                        'options': {'account': 'a', 'user': 'u'}})
    with pytest.raises(ConnectorError) as e:
        engine.list_tables(conn)
    assert 'very-secret-password' not in str(e.value)


# ── vector and search adapters ──────────────────────────────────────────

@pytest.fixture
def http(monkeypatch):
    httpx = pytest.importorskip('httpx')
    seen = []

    def handler(request):
        seen.append(request)
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if path == '/collections':
            return httpx.Response(200, json={'result': {'collections': [{'name': 'docs'}, {'name': 'private'}]}})
        if path == '/collections/docs':
            return httpx.Response(200, json={'result': {'status': 'green', 'points_count': 2,
                                                        'config': {'params': {'vectors': {'size': 3}}},
                                                        'payload_schema': {'title': {}, 'email': {}}}})
        if path == '/collections/docs/points/search':
            return httpx.Response(200, json={'result': [
                {'id': 7, 'score': 0.9, 'payload': {'text': 'hello', 'title': 'Doc', 'email': 'ann@example.com'}}]})
        if path == '/_cat/indices':
            return httpx.Response(200, json=[{'index': 'kb'}, {'index': '.internal'}])
        if path == '/kb/_mapping':
            return httpx.Response(200, json={'kb': {'mappings': {'properties': {'text': {'type': 'text'}}}}})
        if path == '/kb/_search':
            return httpx.Response(200, json={'hits': {'hits': [{'_id': 'a1', '_score': 3.2,
                                                                '_source': {'text': 'found', 'lang': 'en'}}]}})
        return httpx.Response(404, text='no')
    vector.set_transport(httpx.MockTransport(handler))
    yield seen
    vector.set_transport(None)


def test_qdrant_lists_describes_and_searches_with_masking(storage_dir, http, monkeypatch):
    monkeypatch.setenv('QK', 'qdrant-key')
    reg = FakeRegistry()
    out = service.save({'id': 'kb', 'kind': 'qdrant', 'options': {'url': 'http://qdrant.local:6333'},
                        'secrets': {'api_key': 'env:QK'}, 'allow': {'deny_tables': ['private']},
                        'masking': [{'column': 'email', 'mode': 'redact'}]}, reg)
    assert sorted(out['tools']) == ['kb__describe_collection', 'kb__list_collections', 'kb__search']
    assert _run(reg, 'kb__list_collections', {})['collections'] == [{'name': 'docs', 'type': 'collection'}]
    assert _run(reg, 'kb__describe_collection', {})['points'] == 2
    res = _run(reg, 'kb__search', {'vector': [0.1, 0.2, 0.3], 'top_k': 3, 'filters': {'title': 'Doc'}})
    hit = res['results'][0]
    assert hit == {'id': 7, 'score': 0.9, 'text': 'hello', 'metadata': {'title': 'Doc', 'email': '[REDACTED]'}}
    req = http[-1]
    assert req.headers['api-key'] == 'qdrant-key'
    assert json.loads(req.content) == {'vector': [0.1, 0.2, 0.3], 'limit': 3, 'with_payload': True,
                                       'filter': {'must': [{'key': 'title', 'match': {'value': 'Doc'}}]}}
    with pytest.raises(ConnectorError, match='not available'):
        _run(reg, 'kb__search', {'vector': [1.0], 'collection': 'private'})
    with pytest.raises(Exception, match='(?i)filter|additional'):
        _run(reg, 'kb__search', {'vector': [1.0], 'filters': {'title': {'$ne': 1}}})


def test_qdrant_embeds_text_through_the_gateway(storage_dir, http, monkeypatch):
    from sajha.ai.llm import factory as fac
    calls = []

    def fake_model(name, kind=''):
        def embeddings_create(input=None, sajha=None):
            calls.append((input, name, sajha.input_purpose if sajha else None))
            return types.SimpleNamespace(vectors=[[0.5, 0.5, 0.5]])
        return types.SimpleNamespace(embeddings_create=embeddings_create)
    monkeypatch.setattr(fac, '_factory', types.SimpleNamespace(model=fake_model))
    conn = model.parse({'id': 'kb', 'kind': 'qdrant', 'options': {'url': 'http://q:6333', 'collection': 'docs'},
                        'vector': {'embedding_model': 'embedding'}})
    vector.search(conn, {'query': 'greeting'})
    assert calls == [(['greeting'], 'embedding', 'query')] and json.loads(http[-1].content)['vector'] == [0.5, 0.5, 0.5]


def test_elasticsearch_full_text_search_builds_the_query(storage_dir, http, monkeypatch):
    monkeypatch.setenv('ESPW', 'pw')
    conn = model.parse({'id': 'es', 'kind': 'elasticsearch', 'options': {'url': 'http://es:9200', 'user': 'elastic'},
                        'secrets': {'password': 'env:ESPW'}, 'vector': {'fields': ['text']}})
    assert [c['name'] for c in vector.list_collections(conn)['collections']] == ['kb']
    out = vector.search(conn, {'query': 'refund policy', 'filters': {'lang': 'en'}, 'top_k': 2})
    assert out['results'] == [{'id': 'a1', 'score': 3.2, 'text': 'found', 'metadata': {'lang': 'en'}}]
    body = json.loads(http[-1].content)
    assert body == {'size': 2, 'query': {'bool': {'must': [{'simple_query_string': {'query': 'refund policy',
                                                                                    'fields': ['text']}}],
                                                  'filter': [{'term': {'lang': 'en'}}]}}}
    assert http[-1].headers['authorization'].startswith('Basic ')


def test_pgvector_search_sql_is_parameterised(storage_dir, monkeypatch):
    fake = FakeDBAPI()

    def answer(sql, params):
        s = sql.lower()
        if 'pg_class c join' in s and 'relkind' in s:
            return ['s', 'n', 't', 'c'], [('public', 'docs', 'table', '')]
        if 'pg_attribute' in s:
            return ['n', 't', 'nl', 'c'], [('id', 'integer', False, ''), ('body', 'text', True, ''),
                                           ('embedding', 'vector(3)', True, ''), ('lang', 'text', True, '')]
        if 'pg_index' in s:
            return ['n'], []
        if '<=>' in sql:
            return ['_id', '_text', 'lang', '_distance'], [(1, 'hello', 'en', 0.25)]
        return None
    fake.answer = answer
    _fake_module(monkeypatch, 'psycopg2', lambda **kw: fake)
    conn = model.parse({'id': 'pv', 'kind': 'pgvector', 'options': {'host': 'h', 'database': 'd'},
                        'vector': {'table': 'docs', 'vector_column': 'embedding', 'text_column': 'body',
                                   'id_column': 'id', 'metadata_columns': ['lang']}})
    out = vector.search(conn, {'vector': [1, 0, 0], 'filters': {'lang': "en' OR 1=1"}})
    assert out['results'] == [{'id': 1, 'score': 0.75, 'text': 'hello', 'metadata': {'lang': 'en'}}]
    sql, params, _ = fake.executed[-1]
    assert 'CAST(%(qv)s AS vector)' in sql and '"lang" = %(f0)s' in sql and 'LIMIT 5' in sql
    assert params == {'qv': '[1,0,0]', 'f0': "en' OR 1=1"}
    with pytest.raises(ConnectorError, match='metadata'):
        vector.search(conn, {'vector': [1, 0, 0], 'filters': {'body': 'x'}})
    assert 'pv__search' in service.tool_configs(conn)


# ── the admin page and API ──────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent


def test_admin_page_and_api(web, tmp_path):
    """Through the real app, registry and storage (names prefixed zz_test_, removed afterwards)."""
    c, admin = web
    db = _shop_sqlite(tmp_path)
    store.forget()
    tok = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'}).json()['token']
    c.cookies.clear()
    bearer = {'Authorization': f'Bearer {tok}'}
    assert c.get('/api/connectors').status_code in (401, 403)
    assert c.post('/api/connectors', json={'id': 'x'}).status_code in (401, 403)
    r = c.get('/admin/connectors', cookies=admin)
    assert r.status_code == 200 and 'Data Connectors' in r.text and 'class="page-help"' in r.text
    kinds = c.get('/api/connectors/kinds', cookies=admin).json()
    assert any(k['kind'] == 'sqlite' and k['installed'] for k in kinds['kinds'])
    body = {'id': 'zz_test_conn', 'kind': 'sqlite', 'options': {'path': db}}
    t = c.post('/api/connectors/test', json=body, cookies=admin).json()
    assert t['success'] and t['tables'] == 4
    bad = c.post('/api/connectors', json={**body, 'options': {'path': db, 'password': 'x'}}, cookies=admin)
    assert bad.status_code == 400 and 'secrets' in bad.json()['error']
    s = c.post('/api/connectors', json=body, cookies=admin).json()
    try:
        assert s['success'] and 'zz_test_conn__query' in s['tools'], s
        listed = c.get('/api/connectors', cookies=admin).json()['connections']
        assert 'zz_test_conn' in [x['id'] for x in listed]
        assert c.get('/api/connectors/zz_test_conn', cookies=admin).json()['connection']['kind'] == 'sqlite'
        assert c.get('/api/connectors/zz_test_conn/tables', cookies=admin).json()['tables'][0]['name'] == 'customers'
        d = c.get('/api/connectors/zz_test_conn/describe', params={'table': 'orders'}, cookies=admin).json()
        assert d['success'] and d['table'] == 'orders'
        assert c.post('/api/connectors/zz_test_conn/refresh', cookies=admin).json()['tables'] == 4
        run = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
            'name': 'zz_test_conn__query', 'arguments': {'sql': 'SELECT count(*) AS n FROM orders'}}},
                     headers=bearer)
        assert run.status_code == 200 and run.json()['result']['structuredContent']['rows'] == [{'n': 60}], run.text
        run = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'zz_test_conn__query', 'arguments': {'sql': 'DELETE FROM orders'}}}, headers=bearer)
        assert run.json()['result']['isError'] is True and 'read-only' in run.text
    finally:
        out = c.delete('/api/connectors/zz_test_conn', cookies=admin).json()
        assert out['success'] and 'zz_test_conn__query' in out['removed']
        assert not list((ROOT / 'config' / 'tools').glob('zz_test_conn__*.json'))
        assert not (ROOT / 'config' / 'connectors' / 'zz_test_conn.json').exists()
