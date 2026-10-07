"""
Data Connectors against real databases: PostgreSQL 16 and MySQL 8 (docs/architecture/Data Connectors.md).

Skipped unless a database URL is given (and reachable)::

    docker run -d --rm --name pg16 -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=shop -p 55432:5432 postgres:16
    docker run -d --rm --name my8 -e MYSQL_ROOT_PASSWORD=pw -e MYSQL_DATABASE=shop -p 53306:3306 mysql:8.0
    SAJHA_TEST_CONNECTORS_POSTGRES_URL=postgresql://postgres:pw@127.0.0.1:55432/shop \\
    SAJHA_TEST_CONNECTORS_MYSQL_URL=mysql://root:pw@127.0.0.1:53306/shop pytest tests/test_connectors_live.py

The connection signs in as the superuser on purpose: the read-only session has to hold even
for an account that could write, so a write that slips past the statement guard still fails.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

import pytest

from sajha.connectors import catalog, engine, pool, service, store
from sajha.connectors.drivers import QueryTimeout
from sajha.connectors.guard import GuardError


def _url(name):
    raw = os.environ.get(name)
    if not raw:
        pytest.skip(f'{name} is not set (see the module docstring)')
    u = urlsplit(raw)
    return {'host': u.hostname, 'port': u.port, 'user': unquote(u.username or ''),
            'password': unquote(u.password or ''), 'database': (u.path or '/').lstrip('/')}


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    import sajha.core.storage as storage
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    store.forget()
    catalog.invalidate()
    pool.clear()
    yield tmp_path
    pool.clear()
    store.forget()
    catalog.invalidate()


# ── PostgreSQL ──────────────────────────────────────────────────────────

@pytest.fixture
def pg(storage_dir, monkeypatch):
    psycopg2 = pytest.importorskip('psycopg2')
    u = _url('SAJHA_TEST_CONNECTORS_POSTGRES_URL')
    try:
        admin = psycopg2.connect(host=u['host'], port=u['port'], user=u['user'], password=u['password'],
                                 dbname=u['database'], connect_timeout=3)
    except Exception as e:
        pytest.skip(f'PostgreSQL is not reachable: {e}')
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute("""
        DROP SCHEMA IF EXISTS zz_sales CASCADE; DROP SCHEMA IF EXISTS zz_hr CASCADE;
        CREATE SCHEMA zz_sales; CREATE SCHEMA zz_hr;
        CREATE TABLE zz_sales.customers (id int PRIMARY KEY, name text, email text);
        COMMENT ON TABLE zz_sales.customers IS 'People who buy';
        COMMENT ON COLUMN zz_sales.customers.email IS 'Contact address';
        INSERT INTO zz_sales.customers VALUES (1, 'Ann', 'ann@example.com'), (2, 'Bob', 'bob@example.com');
        CREATE TABLE zz_sales.orders (id int PRIMARY KEY, customer_id int, status text, total numeric(10,2),
                                      created_at date);
        INSERT INTO zz_sales.orders SELECT g, 1 + g % 2, (ARRAY['new','paid','shipped'])[1 + g % 3], g * 1.5,
                                           date '2026-01-01' + g FROM generate_series(1, 50) g;
        CREATE VIEW zz_sales.paid AS SELECT * FROM zz_sales.orders WHERE status = 'paid';
        CREATE TABLE zz_hr.salaries (id int, amount int);
        CREATE SEQUENCE zz_sales.s;
    """)
    monkeypatch.setenv('ZZ_PG_PASSWORD', u['password'])
    reg = None
    out = service.save({
        'id': 'pgshop', 'kind': 'postgresql', 'description': 'Web-shop orders and customers.',
        'options': {'host': u['host'], 'port': u['port'], 'database': u['database'], 'user': u['user']},
        'secrets': {'password': 'env:ZZ_PG_PASSWORD'},
        'limits': {'max_rows': 20, 'timeout_seconds': 2},
        'allow': {'schemas': ['zz_sales']},
        'masking': [{'column': 'email', 'mode': 'pii'}],
        'views': [{'name': 'orders', 'table': 'zz_sales.orders', 'columns': ['id', 'status', 'total', 'created_at'],
                   'filters': [{'column': 'status', 'operators': ['eq', 'in']},
                               {'column': 'created_at', 'operators': ['gte', 'lte']},
                               {'column': 'total', 'operators': ['gt']}],
                   'order_by': [{'column': 'id', 'direction': 'asc'}]}],
    }, reg, 'admin')
    assert out['success'], out
    yield store.get('pgshop')[0], admin
    pool.clear()
    cur.execute('DROP SCHEMA IF EXISTS zz_sales CASCADE; DROP SCHEMA IF EXISTS zz_hr CASCADE')
    admin.close()


def test_pg_catalog_describe_and_comments(pg):
    conn, _ = pg
    t = engine.list_tables(conn)['tables']
    assert {(x['schema'], x['name'], x['type']) for x in t} == {('zz_sales', 'customers', 'table'),
                                                                 ('zz_sales', 'orders', 'table'),
                                                                 ('zz_sales', 'paid', 'view')}
    assert next(x for x in t if x['name'] == 'customers')['comment'] == 'People who buy'
    d = engine.describe_table(conn, 'customers')
    email = next(c for c in d['columns'] if c['name'] == 'email')
    assert email['comment'] == 'Contact address' and email['masked'] == 'pii' and d['primary_key'] == ['id']
    assert all('@example.com' in r['email'] and not r['email'].startswith(('ann@', 'bob@')) for r in d['sample_rows'])
    assert engine.test(conn)['server_version'].startswith('PostgreSQL 16')


def test_pg_query_parameters_limits_and_typed_values(pg):
    conn, _ = pg
    out = engine.query(conn, 'SELECT status, count(*) AS n, sum(total) AS s FROM orders '
                             'WHERE created_at >= :d GROUP BY status ORDER BY status', {'d': '2026-01-20'})
    assert [r['status'] for r in out['rows']] == ['new', 'paid', 'shipped'] and isinstance(out['rows'][0]['s'], str)
    many = engine.query(conn, 'SELECT * FROM zz_sales.orders')
    assert many['row_count'] == 20 and many['truncated'] and many['truncated_reason'] == 'rows'
    # search_path is the allowed schemas: an unqualified name means zz_sales
    assert engine.query(conn, "SELECT 'a%b' LIKE :p AS ok, 1::int AS one FROM paid LIMIT 1",
                        {'p': 'a%'})['rows'] == [{'ok': True, 'one': 1}]


@pytest.mark.parametrize('sql', [
    "SELECT pg_read_file('/etc/passwd')", "SELECT pg_ls_dir('.')", "COPY (SELECT 1) TO '/tmp/zz'",
    "COPY zz_sales.orders TO PROGRAM 'id'", 'SELECT * FROM pg_shadow', 'SELECT * FROM zz_hr.salaries',
    'SELECT * FROM orders FOR UPDATE', 'WITH d AS (DELETE FROM zz_sales.orders RETURNING *) SELECT * FROM d',
    'SELECT * INTO zz_sales.copy FROM zz_sales.orders', 'DELETE FROM zz_sales.orders', 'SELECT 1; DROP TABLE x',
    "SELECT set_config('default_transaction_read_only', 'off', false)", "SELECT nextval('zz_sales.s')",
    "SELECT lo_import('/etc/passwd')", "SELECT query_to_xml('select 1', true, true, '')",
    'SET default_transaction_read_only = off', 'SELECT upper(email) FROM customers',
])
def test_pg_guard_refuses(pg, sql):
    conn, _ = pg
    with pytest.raises(GuardError):
        engine.query(conn, sql)


def test_pg_read_only_session_holds_below_the_guard(pg):
    conn, admin = pg
    with engine.session(conn) as (drv, dbc, st):
        cur = dbc.cursor()
        for sql in ("INSERT INTO zz_sales.orders VALUES (999, 1, 'x', 1, NULL)", 'DROP TABLE zz_sales.orders',
                    "SELECT nextval('zz_sales.s')"):
            with pytest.raises(Exception, match='read-only transaction'):
                cur.execute(sql)
            dbc.rollback()
        st['broken'] = True
    c = admin.cursor()
    c.execute('SELECT count(*) FROM zz_sales.orders')
    assert c.fetchone()[0] == 50


def test_pg_long_query_is_cancelled(pg):
    conn, _ = pg
    with pytest.raises(QueryTimeout, match='timed out after 2s'):
        engine.query(conn, 'SELECT count(*) FROM generate_series(1, 10000000000)')
    assert engine.query(conn, 'SELECT 1 AS one')['rows'] == [{'one': 1}]       # a fresh connection


def test_pg_view_and_injection(pg):
    conn, _ = pg
    out = engine.run_view(conn, 'orders', {'status_in': ['paid'], 'created_at_from': '2026-01-10',
                                           'total_after': 10})
    assert out['rows'] and all(r['status'] == 'paid' and float(r['total']) > 10 for r in out['rows'])
    for evil in ("paid' OR '1'='1", "paid'; DROP TABLE zz_sales.orders; --"):
        assert engine.run_view(conn, 'orders', {'status': evil})['row_count'] == 0
    with pytest.raises(Exception):
        engine.run_view(conn, 'orders', {'created_at_from': 'not a date'})
    assert engine.query(conn, 'SELECT count(*) AS n FROM orders')['rows'] == [{'n': 50}]


# ── MySQL ───────────────────────────────────────────────────────────────

@pytest.fixture
def my(storage_dir, monkeypatch):
    pymysql = pytest.importorskip('pymysql')
    u = _url('SAJHA_TEST_CONNECTORS_MYSQL_URL')
    try:
        admin = pymysql.connect(host=u['host'], port=u['port'], user=u['user'], password=u['password'],
                                database=u['database'], autocommit=True, connect_timeout=3)
    except Exception as e:
        pytest.skip(f'MySQL is not reachable: {e}')
    cur = admin.cursor()
    for st in ('DROP TABLE IF EXISTS zz_orders', 'DROP TABLE IF EXISTS zz_secret',
               "CREATE TABLE zz_orders (id int PRIMARY KEY, status varchar(20) COMMENT 'Order state', note text) "
               "COMMENT='All orders'",
               "INSERT INTO zz_orders VALUES (1, 'paid', 'it''s ok'), (2, 'new', NULL), (3, 'paid', '100%')",
               'CREATE TABLE zz_secret (v text)'):
        cur.execute(st)
    monkeypatch.setenv('ZZ_MY_PASSWORD', u['password'])
    out = service.save({'id': 'myshop', 'kind': 'mysql', 'options': {'host': u['host'], 'port': u['port'],
                                                                      'database': u['database'], 'user': u['user']},
                        'secrets': {'password': 'env:ZZ_MY_PASSWORD'}, 'limits': {'timeout_seconds': 2},
                        'allow': {'tables': ['zz_orders']}}, None)
    assert out['success'], out
    yield store.get('myshop')[0], admin
    pool.clear()
    cur.execute('DROP TABLE IF EXISTS zz_orders')
    cur.execute('DROP TABLE IF EXISTS zz_secret')
    admin.close()


def test_mysql_catalog_query_and_guard(my):
    conn, _ = my
    assert [t['name'] for t in engine.list_tables(conn)['tables']] == ['zz_orders']
    cols = engine.describe_table(conn, 'zz_orders')['columns']
    assert cols[1]['comment'] == 'Order state'
    out = engine.query(conn, "SELECT id, note FROM zz_orders WHERE status = :s AND note LIKE '%' ORDER BY id",
                       {'s': 'paid'})
    assert out['rows'] == [{'id': 1, 'note': "it's ok"}, {'id': 3, 'note': '100%'}]
    for sql in ("SELECT load_file('/etc/passwd')", "SELECT * FROM zz_orders INTO OUTFILE '/tmp/zz'",
                'SELECT * FROM zz_secret', 'SELECT * FROM mysql.user', "SELECT benchmark(10000000, md5('a'))",
                'DELETE FROM zz_orders', 'SELECT 1; DROP TABLE zz_orders'):
        with pytest.raises(GuardError):
            engine.query(conn, sql)
    # a backslash-escaped quote is part of the string on MySQL: no second statement hides behind it
    assert engine.query(conn, "SELECT 'a\\' ; DROP TABLE zz_orders; -- ' AS s")['row_count'] == 1


def test_mysql_read_only_transaction_holds_below_the_guard(my):
    conn, admin = my
    with engine.session(conn) as (drv, dbc, st):
        drv.begin(dbc, conn)
        cur = dbc.cursor()
        with pytest.raises(Exception, match='READ ONLY'):
            cur.execute("INSERT INTO zz_orders VALUES (9, 'x', NULL)")
        dbc.rollback()
        st['broken'] = True
    c = admin.cursor()
    c.execute('SELECT count(*) FROM zz_orders')
    assert c.fetchone()[0] == 3


def test_mysql_long_query_is_stopped(my):
    """MAX_EXECUTION_TIME interrupts the statement at the connection's limit (SLEEP then returns 1)."""
    import time
    conn, _ = my
    t0 = time.monotonic()
    try:
        out = engine.query(conn, 'SELECT SLEEP(10) AS s')
        assert out['rows'] == [{'s': 1}]
    except QueryTimeout:
        pass
    assert time.monotonic() - t0 < 6
