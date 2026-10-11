# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The live tool check (sajha/quality/check.py; Tool Quality §12.4): argument derivation, skips,
outcomes, one call at a time per folder, folder notices, the schedule on the probe scheduler,
the CLI's JSON report and the missing-example lint. Fake tools only: no test touches the network."""

import json
import threading
import time

import pytest

from sajha import notices as N
from sajha.core.state import set_state_store
from sajha.core.state.memory import MemoryStateStore
from sajha.quality import check as K
from sajha.quality.cases import ProbeSpec, Suite, TestCase
from tests.ai.conftest import FakeTool

RO = {'readOnlyHint': True}


def tool(name, output=None, schema=None, annotations=RO, **cfg):
    t = FakeTool(name, f'{name}: a fake tool for the live check tests, returning canned data.',
                 schema=schema, output=output if output is not None else {'rows': [1]})
    if annotations is not None:
        t.config['annotations'] = dict(annotations)
    t.config.update(cfg)
    return t


class Box:
    def __init__(self, folders):
        self.tools, self.folders = {}, {}
        for folder, tools in folders.items():
            for t in tools:
                self.tools[t.name] = t
                self.folders[t.name] = folder

    def tool_folder(self, name):
        return self.folders.get(name)

    def get_tool(self, name):
        return self.tools.get(name)


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setattr('sajha.core.audit.get_audit_logger', lambda: type('A', (), {'log': lambda *a, **k: None})())
    s = N.NoticeService(MemoryStateStore('chk:'), forward=[])
    saved = N._service
    N.set_service(s)
    set_state_store(MemoryStateStore('chkstate:'))
    yield s
    N.set_service(saved)
    set_state_store(None)


def run(box, suite=None, **kw):
    kw.setdefault('pause_ms', 0)
    return {r.tool: r for r in K.run_check(box, suite=suite or Suite(), **kw)}


# ── arguments ───────────────────────────────────────────────────────────────

def test_arguments_come_from_structured_data_in_order():
    schema = {'type': 'object', 'examples': [{'q': 'from-examples'}],
              'properties': {'q': {'type': 'string', 'examples': ['from-property']}}, 'required': ['q']}
    cases = [TestCase(tool='t', name='bad', arguments={'q': 'x'}, error=True),
             TestCase(tool='t', name='first', arguments={'q': 'from-test'}),
             TestCase(tool='t', name='probe', arguments={'q': 'from-probe'})]
    assert K.derive_arguments(schema, cases, 'probe') == ({'q': 'from-probe'}, 'probe')
    assert K.derive_arguments(schema, cases) == ({'q': 'from-test'}, 'test')
    assert K.derive_arguments(schema, []) == ({'q': 'from-examples'}, 'examples')
    del schema['examples']
    assert K.derive_arguments(schema, []) == ({'q': 'from-property'}, 'properties')
    assert K.derive_arguments({'type': 'object', 'properties': {'q': {'type': 'string'}}, 'required': ['q']},
                              []) == (None, '')
    assert K.derive_arguments({'type': 'object', 'properties': {}}, []) == ({}, 'properties')


def test_description_prose_is_never_parsed():
    schema = {'type': 'object', 'properties': {'q': {'type': 'string', 'description': 'Example: {"q": "x"}'}},
              'required': ['q']}
    assert K.derive_arguments(schema, []) == (None, '')


# ── skips and outcomes ──────────────────────────────────────────────────────

def test_skips_name_their_reasons(monkeypatch):
    monkeypatch.setenv('SAJHA_QUALITY_CHECK_EXCLUDE', 'ex_*')
    llm = tool('llm_t')
    llm.config['llm'] = {'mode': 'complete'}
    acct = tool('acct_t', auth={'connected_account': 'github'})
    off = tool('off_t')
    off.disable()
    box = Box({'f': [tool('writes', annotations={}), tool('drops', annotations={'destructiveHint': True}),
                     llm, acct, off, tool('ex_one')]})
    out = run(box, notify=False)
    reasons = {n: r.message for n, r in out.items()}
    assert all(r.outcome == 'skipped' for r in out.values())
    assert 'read-only' in reasons['writes'] and reasons['drops'] == 'destructive'
    assert 'LLM' in reasons['llm_t'] and 'connected account' in reasons['acct_t']
    assert reasons['off_t'] == 'disabled' and 'exclude' in reasons['ex_one']
    assert all(not box.tools[n].calls for n in out)


def test_outcomes(svc):
    def boom(a):
        raise RuntimeError('HTTP 503 from upstream')

    def nokey(a):
        raise ValueError('FRED API key is not configured')
    strict = tool('strict_t', output={'rows': 'not-a-list'})
    strict.config['outputSchema'] = {'type': 'object', 'properties': {'rows': {'type': 'array'}}}
    strict._output_schema = strict.config['outputSchema']
    box = Box({'p': [tool('ok_t'), tool('empty_t', output={'rows': []}), tool('err_t', output=boom),
                     tool('errdict_t', output={'error': 'upstream said 418'}), tool('nokey_t', output=nokey),
                     strict, tool('cfgkey_t', api_key='${missing.key}'),
                     tool('noex_t', schema={'type': 'object', 'properties': {'q': {'type': 'string'}},
                                            'required': ['q']})]})
    out = run(box)
    got = {n: r.outcome for n, r in out.items()}
    assert got == {'ok_t': 'ok', 'empty_t': 'empty', 'err_t': 'error', 'errdict_t': 'error',
                   'nokey_t': 'not_configured', 'strict_t': 'schema_mismatch', 'cfgkey_t': 'not_configured',
                   'noex_t': 'not_checked'}
    assert out['err_t'].error_class == 'RuntimeError'
    assert not box.tools['cfgkey_t'].calls and not box.tools['noex_t'].calls


def test_the_call_gets_schema_defaults_and_a_timeout(svc):
    schema = {'type': 'object', 'properties': {'limit': {'type': 'integer', 'default': 3}}}
    slow = tool('slow_t', output=lambda a: time.sleep(2) or {'rows': [1]})
    box = Box({'f': [tool('d_t', schema=schema), slow]})
    out = run(box, timeout=0.2)
    assert box.tools['d_t'].calls == [{'limit': 3}]
    assert out['slow_t'].outcome == 'error' and out['slow_t'].error_class == 'TimeoutError'


def test_one_call_at_a_time_per_folder(svc):
    active, peak, lock = {}, {}, threading.Lock()

    def make(folder):
        def out(a):
            with lock:
                active[folder] = active.get(folder, 0) + 1
                peak[folder] = max(peak.get(folder, 0), active[folder])
            time.sleep(0.05)
            with lock:
                active[folder] -= 1
            return {'rows': [1]}
        return out
    box = Box({f: [tool(f'{f}_{i}', output=make(f)) for i in range(4)] for f in ('a', 'b', 'c')})
    t0 = time.monotonic()
    run(box, concurrency=3)
    assert peak == {'a': 1, 'b': 1, 'c': 1}
    assert time.monotonic() - t0 < 0.6                           # folders ran side by side


def test_the_budget_skips_what_is_left(svc):
    box = Box({'f': [tool('b1'), tool('b2')]})
    out = run(box, budget_seconds=-1)
    assert {r.outcome for r in out.values()} == {'skipped'} and 'budget' in out['b1'].message


# ── notices, state, schedule ────────────────────────────────────────────────

def test_one_notice_per_folder_with_broken_tools_and_it_clears(svc):
    state = {'broken': True}

    def flaky(a):
        if state['broken']:
            raise RuntimeError('HTTP 500')
        return {'rows': [1]}
    box = Box({'fred': [tool('fred_a', output=flaky), tool('fred_b', output=flaky)], 'calc': [tool('calc_a')]})
    run(box)
    open_ids = {n['id'] for n in svc.list()}
    assert open_ids == {'quality.check:fred'}
    n = svc.get('quality.check:fred')
    assert n['severity'] == 'warning' and n['source'] == 'quality' and 'fred_a' in n['detail'] and '2 broken' in n['title']
    state['broken'] = False
    run(box, folder='calc')                                      # another folder's run leaves it alone
    assert {n['id'] for n in svc.list()} == {'quality.check:fred'}
    run(box, folder='fred')
    assert svc.list() == []
    last = K.last_results()
    assert last['fred_a']['outcome'] == 'ok' and last['calc_a']['outcome'] == 'ok'


def test_the_schedule_rides_the_probe_scheduler_and_fires_once(svc, monkeypatch):
    from sajha.quality import probes as P
    monkeypatch.setenv('SAJHA_QUALITY_CHECK_CRON', '*/30 * * * *')
    runs = []
    monkeypatch.setattr(K, 'scheduled_run', lambda reg: runs.append(reg) or True)
    box = Box({'f': [tool('s1')]})
    a = P.ProbeScheduler(box, tick=1, suite_loader=lambda: Suite(), run_probes=False)
    b = P.ProbeScheduler(box, tick=1, suite_loader=lambda: Suite(), run_probes=False)
    assert a.run_once(now=0.0) == [] and b.run_once(now=0.0) == []    # learn the next slot (1800)
    a.run_once(now=1801.0)
    b.run_once(now=1801.0)
    assert len(runs) == 1


def test_the_scheduler_starts_for_the_check_alone(monkeypatch):
    from sajha.quality import probes as P
    monkeypatch.delenv('SAJHA_QUALITY_PROBES_ENABLED', raising=False)
    monkeypatch.delenv('SAJHA_QUALITY_CHECK_CRON', raising=False)
    started = []
    monkeypatch.setattr(P.ProbeScheduler, 'start', lambda self: started.append(self.run_probes))
    if P.enabled():
        pytest.skip('probes enabled in this configuration')
    assert P.start(Box({})) is False
    monkeypatch.setenv('SAJHA_QUALITY_CHECK_CRON', '0 3 * * *')
    assert P.start(Box({})) is True and started == [False]


# ── reports and the CLI ─────────────────────────────────────────────────────

def test_reports():
    rs = [K.CheckResult('a', 'f', 'ok'), K.CheckResult('b', 'f', 'error', 'boom'),
          K.CheckResult('c', 'g', 'skipped', 'destructive')]
    s = K.summarise(rs)
    assert s['broken'] == 1 and s['broken_folders'] == ['f'] and s['skipped'] == 1
    import xml.etree.ElementTree as ET
    root = ET.fromstring(K.render_junit(rs))
    assert root.get('failures') == '1'
    assert 'destructive' not in K.render_text(rs) and 'destructive' in K.render_text(rs, show_skipped=True)


def test_cli_writes_a_json_report(svc, tmp_path, monkeypatch):
    from sajha.quality import __main__ as M
    box = Box({'f': [tool('cli_ok'), tool('cli_bad', output={'error': 'HTTP 500'})]})
    monkeypatch.setattr(M, '_registry', lambda: box)
    monkeypatch.setattr('sajha.quality.cases.load_suite', lambda registry=None: Suite())
    monkeypatch.setenv('SAJHA_QUALITY_CHECK_PAUSE_MS', '0')
    out = tmp_path / 'check.json'
    assert M.main(['check', '--json', str(out)]) == 1
    data = json.loads(out.read_text())
    assert data['summary']['broken'] == 1
    assert {r['tool']: r['outcome'] for r in data['results']} == {'cli_ok': 'ok', 'cli_bad': 'error'}


def test_lint_missing_example():
    from sajha.quality.lint import lint_tool
    cfg = {'description': 'A tool with a required argument and nothing to call it with, for the test.',
           'inputSchema': {'type': 'object', 'properties': {'q': {'type': 'string', 'description': 'query'}},
                           'required': ['q']}}
    assert ('warning', 'missing-example') in {(f.level, f.rule) for f in lint_tool('t', cfg)}
    case = TestCase(tool='t', name='c', arguments={'q': 'x'})
    assert 'missing-example' not in {f.rule for f in lint_tool('t', cfg, cases=[case])}
