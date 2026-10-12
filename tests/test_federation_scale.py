# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Federation at gateway scale (sajha/federation/scale.py): connection pools per upstream, the bound
on calls in flight with a queue and load shedding, replicas with health-based selection and
failover, and the cluster-wide view of upstream health in the state store (two managers standing
for two workers, on each state-store backend the state-store tests use).
Design: docs/architecture/Federation.md, "Gateway scale".
"""

import concurrent.futures
import tempfile
import threading
import time

import pytest

pytest.importorskip('mcp.server.mcpserver')

from sajha.federation.config import ConfigError, FederationSettings, UpstreamConfig  # noqa: E402
from sajha.federation.manager import FederationManager  # noqa: E402
from sajha.federation.scale import Admission, UpstreamOverloaded, pick_member  # noqa: E402
from sajha.federation.store import FederationStore  # noqa: E402
from tests.test_federation import Registry, Upstream, wait_for  # noqa: E402
from tests.test_state_store import _make  # noqa: E402


@pytest.fixture(autouse=True)
def _no_policy_engine(monkeypatch):
    monkeypatch.setenv('SAJHA_POLICY_ENABLED', 'false')


@pytest.fixture(scope='module')
def upstream():
    u = Upstream()
    yield u
    u.stop()


@pytest.fixture
def make(tmp_path):
    made = []

    def _make_manager(upstreams, worker=None, store=None, **kw):
        settings = FederationSettings(**{'enabled': True, 'allow_localhost': True, 'require_approval': False,
                                         'startup_wait_seconds': 10, 'default_timeout_seconds': 10,
                                         'health_publish_seconds': 3600, 'upstreams': upstreams, **kw})
        reg = Registry()
        m = FederationManager(reg, settings, FederationStore(str(tmp_path / f'fed{len(made)}.json')))
        if worker:
            m.worker_id = m.health.worker_id = worker
        if store is not None:
            m.health._store = store
        m.start()
        made.append(m)
        return m, reg
    yield _make_manager
    for m in made:
        m.stop()


def c2f(m, reg, prefix='units', value=100):
    tool = reg.tools[f'{prefix}__celsius_to_fahrenheit']
    return m.call_tool(tool, {'celsius': value})


# ── configuration ───────────────────────────────────────────────────

def test_replica_and_pool_fields_are_validated():
    cfg = UpstreamConfig.from_dict({'id': 'w', 'url': 'http://a/mcp', 'urls': ['http://b/mcp', 'http://c/mcp'],
                                    'pool_size': 3, 'max_in_flight': 8, 'max_queue': 4})
    assert cfg.replica_urls == ['http://a/mcp', 'http://b/mcp', 'http://c/mcp']
    assert (cfg.pool_size, cfg.max_in_flight, cfg.max_queue) == (3, 8, 4)
    assert UpstreamConfig.from_dict({'id': 'w', 'url': 'http://a/mcp'}).pool_size is None   # the global default
    for bad, why in [({'urls': ['http://a/mcp']}, 'differ'), ({'urls': ['ftp://b']}, 'http'),
                     ({'pool_size': 0}, 'pool_size'), ({'pool_size': 999}, 'pool_size'),
                     ({'max_in_flight': -1}, 'max_in_flight')]:
        with pytest.raises(ConfigError, match=why):
            UpstreamConfig.from_dict({'id': 'w', 'url': 'http://a/mcp', **bad})
    with pytest.raises(ConfigError, match='HTTP transport'):
        UpstreamConfig.from_dict({'id': 'w', 'transport': 'stdio', 'command': 'x', 'urls': ['http://b/mcp']})


# ── admission ───────────────────────────────────────────────────────

def test_admission_queues_in_order_and_sheds_over_the_bound():
    a = Admission('u', limit=2, queue=2, queue_timeout=5)
    a.acquire()
    a.acquire()
    order = []

    def wait(tag):
        a.acquire()
        order.append(tag)

    t1 = threading.Thread(target=wait, args=('first',))
    t1.start()
    assert wait_for(lambda: a.waiting == 1, 2)
    t2 = threading.Thread(target=wait, args=('second',))
    t2.start()
    assert wait_for(lambda: a.waiting == 2, 2)
    t0 = time.time()
    with pytest.raises(UpstreamOverloaded, match='queue is full') as e:   # refused at once, not after a wait
        a.acquire()
    assert time.time() - t0 < 0.5 and e.value.retryable and e.value.caller_specific
    assert 'Nothing was sent' in str(e.value)
    a.release()
    t1.join(2)
    a.release()
    t2.join(2)
    assert order == ['first', 'second']                       # first come, first served
    assert a.in_flight == 2 and a.shed == 1
    a.release()
    a.release()
    assert a.in_flight == 0


def test_admission_queue_timeout_and_no_limit():
    a = Admission('u', limit=1, queue=1, queue_timeout=0.2)
    a.acquire()
    with pytest.raises(UpstreamOverloaded, match='no slot freed'):
        a.acquire()
    assert a.waiting == 0 and a.shed == 1
    free = Admission('u', limit=0)
    for _ in range(100):
        free.acquire()                                        # 0: no limit (the default)
    assert free.in_flight == 100 and free.shed == 0


def test_pick_member_prefers_connected_healthy_and_idle():
    class M:
        def __init__(self, state='connected', replica=0, in_flight=0, fail=0, lat=None):
            self.state, self.replica, self.in_flight, self.fail_streak, self.ewma_ms = state, replica, in_flight, fail, lat
    down, busy, idle, sick = M('error'), M(in_flight=3), M(in_flight=0, replica=1), M(fail=2)
    assert pick_member([down, busy, idle, sick]) is idle
    assert pick_member([down, busy, sick]) is busy                       # a failing replica comes last
    assert pick_member([busy, M(replica=2)], down_replicas=[2]) is busy  # a peer reports replica 2 down
    assert pick_member([down]) is None
    a, b = M(), M()
    assert {id(pick_member([a, b])) for _ in range(6)} == {id(a), id(b)}  # ties: round robin


# ── pools ───────────────────────────────────────────────────────────

def test_pool_opens_n_connections_and_spreads_calls(upstream, make):
    m, reg = make([{'id': 'units', 'url': upstream.url, 'pool_size': 3}])
    up = m._upstreams['units']
    assert wait_for(lambda: all(c.state == 'connected' for c in up.pool), 10)
    assert len(up.pool) == 3 and up.pool[0] is up.conn
    assert [c.role for c in up.pool] == ['primary', 'pool', 'pool']       # one discovery, not three
    tool = reg.tools['units__sleepy']
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda _: m.call_tool(tool, {'seconds': 0.3}), range(6)))
    used = [c for c in up.pool if c.ewma_ms is not None]
    assert len(used) == 3                                                  # every connection carried calls
    st = m.status('units')
    assert st['pool'] == {'size': 3, 'connections': 3, 'connected': 3}
    assert st['admission']['limit'] == 0 and st['admission']['peak_in_flight'] >= 3


def test_default_is_one_connection_and_no_limit(upstream, make):
    m, reg = make([{'id': 'units', 'url': upstream.url}])
    up = m._upstreams['units']
    assert len(up.pool) == 1 and up.pool[0] is up.conn
    assert c2f(m, reg)['structuredContent']['result'] == 212.0
    st = m.status('units')
    assert st['pool']['connections'] == 1 and st['admission']['limit'] == 0 and len(st['replicas']) == 1


# ── load shedding ───────────────────────────────────────────────────

def test_over_the_bound_calls_are_refused_fast_and_spare_the_breaker(upstream, make):
    m, reg = make([{'id': 'units', 'url': upstream.url, 'prefix': 'shed', 'max_in_flight': 1, 'max_queue': 0,
                    'breaker': {'failure_threshold': 2, 'recovery_timeout': 60}}])
    sleepy, c2f_tool = reg.tools['shed__sleepy'], reg.tools['shed__celsius_to_fahrenheit']
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        slow = ex.submit(sleepy.execute_with_tracking, {'seconds': 1.0})
        assert wait_for(lambda: m._upstreams['units'].admission.in_flight == 1, 5)
        for _ in range(4):
            t0 = time.time()
            with pytest.raises(UpstreamOverloaded, match='at capacity'):
                c2f_tool.execute_with_tracking({'celsius': 1})
            assert time.time() - t0 < 0.5
        slow.result(10)
    from sajha.core.circuit_breaker import get_circuit_registry
    assert get_circuit_registry().get_breaker('shed__x').state.value == 'closed'   # load is not a failure
    st = m.status('units')
    assert st['admission']['shed'] == 4 and st['calls'] == 1 and st['failures'] == 0
    assert c2f_tool.execute_with_tracking({'celsius': 0})['structuredContent']['result'] == 32.0
    from sajha.observability import metrics
    from sajha.federation import manager as manager_mod
    old = manager_mod._manager
    manager_mod._manager = m
    try:
        text = metrics.render(metrics.REGISTRY.collect())
    finally:
        manager_mod._manager = old
    assert 'sajha_federation_upstream_shed_total{upstream="units"} 4' in text
    assert 'sajha_federation_upstream_in_flight{upstream="units"} 0' in text


def test_queued_calls_wait_for_a_slot(upstream, make):
    m, reg = make([{'id': 'units', 'url': upstream.url, 'max_in_flight': 1, 'max_queue': 4}],
                  queue_timeout_seconds=10)
    tool = reg.tools['units__sleepy']
    with concurrent.futures.ThreadPoolExecutor(3) as ex:
        results = list(ex.map(lambda _: m.call_tool(tool, {'seconds': 0.2}), range(3)))
    assert len(results) == 3
    adm = m.status('units')['admission']
    assert adm['shed'] == 0 and adm['queued_total'] >= 1 and adm['peak_in_flight'] == 1


# ── replicas ────────────────────────────────────────────────────────

def test_replica_failover_and_promotion(make):
    a, b = Upstream(), Upstream()
    try:
        m, reg = make([{'id': 'units', 'url': a.url, 'urls': [b.url], 'retries': 1}])
        up = m._upstreams['units']
        assert wait_for(lambda: all(c.state == 'connected' for c in up.pool), 10)
        assert [(c.replica, c.role) for c in up.pool] == [(0, 'primary'), (1, 'pool')]
        assert [r['url'] for r in m.status('units')['replicas']] == [a.url, b.url]
        a.stop()                                                   # the primary replica goes away
        for i in range(6):                                         # every call is answered (by b)
            assert c2f(m, reg, value=i)['structuredContent']['result'] == i * 9 / 5 + 32
        assert wait_for(lambda: up.pool[0].state != 'connected', 10)
        m.health_tick()                                            # b's connection becomes the primary
        assert wait_for(lambda: up.conn is up.pool[1] and up.conn.state == 'connected', 10)
        assert up.conn.role == 'primary' and up.pool[0].role == 'pool'
        st = m.status('units')
        assert st['state'] == 'connected' and [r['primary'] for r in st['replicas']] == [False, True]
        assert m.refresh('units')['state'] == 'connected'          # discovery runs on the new primary
        assert c2f(m, reg)['structuredContent']['result'] == 212.0
    finally:
        b.stop()


def test_not_connected_member_is_skipped_for_any_tool(make):
    a, b = Upstream(), Upstream()
    try:
        m, reg = make([{'id': 'units', 'url': a.url, 'urls': [b.url], 'retries': 0}])
        up = m._upstreams['units']
        assert wait_for(lambda: all(c.state == 'connected' for c in up.pool), 10)
        a.stop()
        up.pool[0].mark_lost('test: gone')                         # known down before the call
        assert wait_for(lambda: up.pool[0].state != 'connected', 10)
        assert up.pool[1].ewma_ms is None
        m.call_tool(reg.tools['units__sleepy'], {'seconds': 0})   # not read-only, retries 0: still answered
        assert up.pool[1].ewma_ms is not None
    finally:
        b.stop()


# ── the cluster-wide view (two workers sharing a state store) ───────

@pytest.fixture(params=['memory', 'fakeredis', 'database'])
def shared(request):
    from sajha.core.circuit_breaker import get_circuit_registry
    reg = get_circuit_registry()
    for p in ('wa__', 'wb__', 'na__', 'nb__'):                  # fresh breakers for each backend
        reg._breakers.pop(p, None)
    with tempfile.TemporaryDirectory() as tmp:
        s = _make(request.param, tmp)
        yield s
        try:
            s.delete_prefix('')
        finally:
            s.close()


def test_health_is_shared_and_a_peer_breaker_is_followed(upstream, make, shared):
    brk = {'failure_threshold': 2, 'recovery_timeout': 1}
    wa, _ra = make([{'id': 'units', 'url': upstream.url, 'prefix': 'wa', 'breaker': brk}],
                   worker='host:1:a', store=shared, health_ttl_seconds=2)
    wb, rb = make([{'id': 'units', 'url': upstream.url, 'prefix': 'wb', 'breaker': brk}],
                  worker='host:2:b', store=shared, health_ttl_seconds=2)
    wa.health_tick()
    wb.health_tick()
    wa.health_tick()
    cl = wb.status('units')['cluster']
    assert cl['reporting'] == 2 and cl['connected'] == 2 and cl['breaker_open'] == []
    assert {w['worker'] for w in cl['workers']} == {'host:1:a', 'host:2:b'}
    assert [w['self'] for w in cl['workers'] if w['worker'] == 'host:2:b'] == [True]

    from sajha.core.circuit_breaker import get_circuit_registry
    ba, bb = get_circuit_registry().get_breaker('wa__x'), get_circuit_registry().get_breaker('wb__x')
    ba.record_failure()
    ba.record_failure()                                         # worker A opens its breaker
    assert ba.state.value == 'open' and bb.state.value == 'closed'
    wa.health_tick()
    wb.health_tick()
    assert bb.state.value == 'open'                             # B follows A
    assert wb.status('units')['cluster']['breaker_open'] == ['host:1:a']
    wb.health_tick()
    wa.health_tick()
    peer_b = [w for w in wa.status('units')['cluster']['workers'] if w['worker'] == 'host:2:b'][0]
    assert peer_b['breaker'] == 'open' and peer_b['breaker_source'] == 'peer'   # followed, never passed on
    with pytest.raises(RuntimeError, match='circuit breaker open'):
        rb.tools['wb__celsius_to_fahrenheit'].execute_with_tracking({'celsius': 1})
    time.sleep(1.2)                                             # B probes on its own after its recovery timeout
    out = rb.tools['wb__celsius_to_fahrenheit'].execute_with_tracking({'celsius': 100})
    assert out['structuredContent']['result'] == 212.0 and bb.state.value == 'closed'
    wb.health_tick()
    assert bb.state.value == 'closed'                           # the same opening is followed once
    time.sleep(2.2)                                             # A stops publishing: its view expires
    wb.health_tick()
    assert wb.status('units')['cluster']['reporting'] == 1


def test_following_peer_breakers_can_be_switched_off(upstream, make, shared):
    brk = {'failure_threshold': 1, 'recovery_timeout': 60}
    wa, _ = make([{'id': 'units', 'url': upstream.url, 'prefix': 'na', 'breaker': brk}],
                 worker='host:1:a', store=shared)
    wb, _ = make([{'id': 'units', 'url': upstream.url, 'prefix': 'nb', 'breaker': brk}],
                 worker='host:2:b', store=shared, follow_peer_breakers=False)
    from sajha.core.circuit_breaker import get_circuit_registry
    get_circuit_registry().get_breaker('na__x').record_failure()
    wa.health_tick()
    wb.health_tick()
    assert get_circuit_registry().get_breaker('nb__x').state.value == 'closed'
    assert wb.status('units')['cluster']['breaker_open'] == ['host:1:a']        # still visible
