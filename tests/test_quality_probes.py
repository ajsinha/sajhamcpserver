"""Health probes: schedule slots (interval and cron), single fire across workers through a shared
state store, stored state and history, metrics, and the scheduler's opt-in."""

import pytest

from sajha.core.state import set_state_store
from sajha.core.state.memory import MemoryStateStore
from sajha.quality import probes as P
from sajha.quality.cases import ProbeSpec, Suite, TestCase
from tests.ai.conftest import FakeTool, ToolBox


@pytest.fixture
def store():
    s = MemoryStateStore('test:')
    set_state_store(s)
    yield s
    set_state_store(None)


def _setup(output=None):
    tb = ToolBox(with_calc=False)
    tb.add(FakeTool('svc_ping', 'Ping the service', output=output if output is not None else {'ok': True}))
    suite = Suite(cases=[TestCase(tool='svc_ping', name='ping', expect=[{'path': '$.ok', 'equals': True}])],
                  probes={'svc_ping': ProbeSpec(tool='svc_ping', case='ping', every=60)})
    return tb, suite


def test_interval_slots_are_aligned_to_the_epoch():
    spec = ProbeSpec(tool='t', case='c', every=60)
    assert P.next_slot(spec, 1000.0) == 1020.0 and P.next_slot(spec, 1020.0) == 1080.0


def test_cron_slots():
    spec = ProbeSpec(tool='t', case='c', cron='*/30 * * * *')
    assert P.next_slot(spec, 0.0) == 1800.0


def test_run_probe_stores_state_history_and_metrics(store):
    tb, suite = _setup()
    e = P.run_probe(tb, suite.probes['svc_ping'], suite, trigger='test')
    assert e['status'] == 'pass' and e['trigger'] == 'test'
    tb.tools['svc_ping'].output = {'ok': False}
    P.run_probe(tb, suite.probes['svc_ping'], suite)
    st = P.state('svc_ping')
    assert st['last']['status'] == 'fail' and st['consecutive_failures'] == 1 and len(st['history']) == 2
    from sajha.observability.metrics import REGISTRY
    up = REGISTRY.family('sajha_tool_probe_up')
    assert any(lbl == {'tool': 'svc_ping'} and v == 0.0 for _, lbl, v in up.samples())
    runs = REGISTRY.family('sajha_tool_probe_runs_total')
    assert runs.value(('svc_ping', 'pass')) >= 1 and runs.value(('svc_ping', 'fail')) >= 1


def test_a_slot_fires_once_across_workers(store):
    """Two schedulers (two workers) sharing one store: each slot runs once."""
    tb, suite = _setup()
    a = P.ProbeScheduler(tb, tick=1, suite_loader=lambda: suite)
    b = P.ProbeScheduler(tb, tick=1, suite_loader=lambda: suite)
    assert a.run_once(now=1000.0) == [] and b.run_once(now=1000.0) == []     # first look: learn the next slot (1020)
    ran = a.run_once(now=1021.0) + b.run_once(now=1021.0)
    assert len(ran) == 1
    assert a.run_once(now=1030.0) == [] and b.run_once(now=1030.0) == []     # not due yet (1080)
    ran = b.run_once(now=1081.0) + a.run_once(now=1081.0)
    assert len(ran) == 1 and len(P.state('svc_ping')['history']) == 2


def test_overview_lists_probes(store):
    tb, suite = _setup()
    P.run_probe(tb, suite.probes['svc_ping'], suite)
    o = P.overview(tb, suite)
    assert o[0]['tool'] == 'svc_ping' and o[0]['last']['status'] == 'pass' and o[0]['registered'] and o[0]['next']


def test_scheduler_is_opt_in(monkeypatch):
    monkeypatch.delenv('SAJHA_QUALITY_PROBES_ENABLED', raising=False)
    assert P.start(object()) is False
    monkeypatch.setenv('SAJHA_QUALITY_PROBES_ENABLED', 'true')
    tb, suite = _setup()
    assert P.start(tb) is True
    P.stop()


def test_missing_case_is_an_error(store):
    tb, suite = _setup()
    spec = ProbeSpec(tool='svc_ping', case='nope', every=60)
    assert P.run_probe(tb, spec, suite)['status'] == 'error'
