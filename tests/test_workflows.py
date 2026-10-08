# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Workflows (sajha/workflows; docs/architecture/Workflows.md): the definition model, parameter
mapping, DAG execution order and parallelism, branches, loops, retries, timeouts, cancel,
resume after a simulated crash, re-run from a failed step, concurrency limits, idempotency
keys, cron schedules (timezones, and one fire across two workers sharing a state store),
signed webhooks with replay protection, file triggers, change-bus events, run-as RBAC,
approval steps, delivery, and a workflow published as a tool over MCP in both eras.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine

from sajha.core.state.memory import MemoryStateStore
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.workflows import identity
from sajha.workflows.cron import CronError, CronSchedule
from sajha.workflows.model import WorkflowError, normalize, parse_text, topo_order
from sajha.workflows.service import WorkflowService
from sajha.workflows.store import WorkflowStore


class Fn(BaseMCPTool):
    def __init__(self, name, fn, annotations=None):
        cfg = {'name': name, 'description': 'workflow test tool', 'inputSchema': {'type': 'object'}}
        if annotations:
            cfg['annotations'] = annotations
        super().__init__(cfg)
        self.fn = fn
        self.calls = []

    def get_input_schema(self):
        return {'type': 'object'}

    def get_output_schema(self):
        return {}

    def execute(self, arguments):
        from sajha.observability.caller import current
        from sajha.policy.context import source
        self.calls.append({'args': dict(arguments), 'user': current().user_id, 'source': source(),
                           't': time.time()})
        return self.fn(arguments)


class Reg:
    def __init__(self, *tools):
        self.tools = {t.name: t for t in tools}

    def get_tool(self, n):
        return self.tools.get(n)

    def register_tool(self, t):
        self.tools[t.name] = t

    def unregister_tool(self, n):
        self.tools.pop(n, None)

    def add(self, *tools):
        for t in tools:
            self.tools[t.name] = t
        return tools[0] if len(tools) == 1 else tools


def everyone(owner):
    return identity.RunIdentity(owner, ['admin'], True, can_execute=lambda n: True)


@pytest.fixture(autouse=True)
def _isolate():
    from sajha import audit
    from sajha.audit.chain import ChainWriter
    from sajha.core.state import set_state_store
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.loader import PolicySet
    old = (audit._writer, audit._exporter)
    audit.set_writer(ChainWriter(store=False, anchor_interval=0, anchor_every=10 ** 9))
    audit._exporter = None
    set_engine(PolicyEngine(PolicySet()))
    st = MemoryStateStore()
    set_state_store(st)
    identity.set_resolver(everyone)
    yield st
    identity.set_resolver(None)
    set_engine(None)
    set_state_store(None)
    audit._writer, audit._exporter = old


@pytest.fixture
def env(tmp_path, _isolate):
    """(service, registry, store) on a scratch SQLite database and the shared memory state store."""
    engine = create_engine(f'sqlite:///{tmp_path / "wf.db"}', connect_args={'check_same_thread': False})
    reg = Reg()
    services = []

    def make(worker='w1', storage=None, store=None):
        svc = WorkflowService(reg, store or WorkflowStore(engine), _isolate, worker_id=worker, storage=storage)
        svc.heartbeat_seconds = 0.2
        svc.stale_seconds = 1.0
        svc.inline_wait_seconds = 1.0
        services.append(svc)
        return svc

    svc = make()
    yield svc, reg, make
    for s in services:
        s.stop(timeout=1)


def run_and_wait(svc, name, inp=None, timeout=15, **kw):
    run = svc.start_run(name, inp or {}, **kw)
    return svc.wait_for(run['id'], timeout)


def steps_of(svc, run_id):
    return {s['step_id']: s for s in svc.run_detail(run_id)['steps']}


# ── the model ────────────────────────────────────────────────────

def test_model_validation_and_implicit_dependencies():
    d = normalize({'name': 'm', 'steps': [
        {'id': 'a', 'tool': 't'},
        {'id': 'b', 'tool': 't', 'params': {'x': '$steps.a.v', 'y': 'hi {{$steps.c.z}}'}},
        {'id': 'c', 'kind': 'condition', 'if': '$steps.a.v > 1', 'then': ['d']},
        {'id': 'd', 'kind': 'wait', 'seconds': 1}]})
    by = {s['id']: s for s in d['steps']}
    assert set(by['b']['depends_on']) == {'a', 'c'} and by['d']['depends_on'] == ['c']
    assert topo_order(d['steps']).index('a') < topo_order(d['steps']).index('b')
    bad = [
        ({'name': 'x', 'steps': [{'id': 'a', 'tool': 't', 'depends_on': ['b']},
                                 {'id': 'b', 'tool': 't', 'depends_on': ['a']}]}, 'cycle'),
        ({'name': 'x', 'steps': [{'id': 'a', 'tool': 't', 'depends_on': ['zz']}]}, 'not a step'),
        ({'name': 'runs', 'steps': [{'id': 'a', 'tool': 't'}]}, 'reserved'),
        ({'name': 'x', 'steps': [{'id': 'a', 'tool': 't'}], 'triggers': [{'type': 'cron', 'cron': '61 * * * *'}]},
         'outside'),
        ({'name': 'x', 'steps': [{'id': 'a', 'kind': 'condition', 'if': {'left': 1, 'op': 'like'}}]}, 'operator'),
        ({'name': 'x', 'steps': [{'id': 'a', 'tool': 't'}],
          'triggers': [{'type': 'file', 'prefix': '../etc'}]}, 'relative'),
    ]
    for defn, msg in bad:
        with pytest.raises(WorkflowError, match=msg):
            normalize(defn)
    assert parse_text('name: y\nsteps:\n  - {id: a, tool: t}\n')['name'] == 'y'


# ── execution ────────────────────────────────────────────────────

def test_dag_order_parallelism_and_mapping(env):
    svc, reg, _ = env

    def slow(a):
        time.sleep(0.4)
        return {'v': a['v']}
    reg.add(Fn('src', lambda a: {'n': a['n'], 'rows': [{'t': 'A'}, {'t': 'B'}]}), Fn('slow', slow),
            Fn('join', lambda a: dict(a)))
    svc.save({'name': 'dag', 'max_parallel': 4, 'steps': [
        {'id': 'a', 'tool': 'src', 'params': {'n': '$input.n'}},
        {'id': 'b', 'tool': 'slow', 'params': {'v': 1}, 'depends_on': ['a']},
        {'id': 'c', 'tool': 'slow', 'params': {'v': 2}, 'depends_on': ['a']},
        {'id': 'd', 'tool': 'join', 'params': {'b': '$steps.b.v', 'c': '$steps.c.v', 'n': '$steps.a.n',
                                              'first': '$steps.a.rows.0.t', 'msg': 'n={{$input.n}}',
                                              'lit': 'plain', 'nested': {'x': ['$input.n']}}}],
        'output': {'sum': '$steps.d'}}, 'alice', True)
    t0 = time.time()
    run = run_and_wait(svc, 'dag', {'n': 7})
    assert run['status'] == 'succeeded', run['error']
    assert time.time() - t0 < 1.2                     # b and c ran side by side
    slow_calls = reg.get_tool('slow').calls
    assert abs(slow_calls[0]['t'] - slow_calls[1]['t']) < 0.3
    assert reg.get_tool('join').calls[0]['t'] >= max(c['t'] for c in slow_calls) + 0.35
    assert run['output']['sum'] == {'b': 1, 'c': 2, 'n': 7, 'first': 'A', 'msg': 'n=7', 'lit': 'plain',
                                    'nested': {'x': [7]}}


def test_branches_join_and_when(env):
    svc, reg, _ = env
    reg.add(Fn('echo', lambda a: dict(a)))
    svc.save({'name': 'br', 'steps': [
        {'id': 'a', 'tool': 'echo', 'params': {'v': '$input.v'}},
        {'id': 'c', 'kind': 'condition', 'if': '$steps.a.v >= 10', 'then': ['big'], 'else': ['small']},
        {'id': 'big', 'tool': 'echo', 'params': {'size': 'big'}},
        {'id': 'small', 'tool': 'echo', 'params': {'size': 'small'}},
        {'id': 'merge', 'tool': 'echo', 'params': {'from': 'merge'}, 'depends_on': ['big', 'small'],
         'join': 'any_success'},
        {'id': 'strict', 'tool': 'echo', 'params': {}, 'depends_on': ['big', 'small']},
        {'id': 'gated', 'tool': 'echo', 'params': {}, 'depends_on': ['a'],
         'when': {'left': '$input.flag', 'op': '==', 'right': True}}]}, 'alice', True)
    r = run_and_wait(svc, 'br', {'v': 12})
    s = steps_of(svc, r['id'])
    assert r['status'] == 'succeeded'
    assert (s['big']['status'], s['small']['status'], s['merge']['status'], s['strict']['status'],
            s['gated']['status']) == ('succeeded', 'skipped', 'succeeded', 'skipped', 'skipped')
    assert 'branch not taken' in s['small']['error']
    r = run_and_wait(svc, 'br', {'v': 3, 'flag': True})
    s = steps_of(svc, r['id'])
    assert (s['big']['status'], s['small']['status'], s['gated']['status']) == ('skipped', 'succeeded', 'succeeded')


def test_foreach_cap_parallel_and_overflow(env):
    svc, reg, _ = env
    seen = []

    def sq(a):
        seen.append(a['x'])
        time.sleep(0.05)
        return {'sq': a['x'] ** 2, 'i': a['i']}
    reg.add(Fn('list', lambda a: {'rows': [{'x': i} for i in range(10)]}), Fn('sq', sq))
    svc.save({'name': 'loop', 'steps': [
        {'id': 'l', 'tool': 'list'},
        {'id': 'each', 'kind': 'foreach', 'items': '$steps.l.rows', 'max_items': 4, 'parallel': 4,
         'do': {'tool': 'sq', 'params': {'x': '$item.x', 'i': '$index'}}}]}, 'alice', True)
    r = run_and_wait(svc, 'loop')
    out = r['output']['each']
    assert r['status'] == 'succeeded' and out['truncated'] is True and out['count'] == 4
    assert [o['sq'] for o in out['items']] == [0, 1, 4, 9] and [o['i'] for o in out['items']] == [0, 1, 2, 3]
    assert sorted(seen) == [0, 1, 2, 3]
    wf = svc.store.get_workflow('loop')['definition']
    wf['steps'][1]['on_overflow'] = 'fail'
    svc.save(wf, 'alice', True)
    r = run_and_wait(svc, 'loop')
    assert r['status'] == 'failed' and 'exceed max_items 4' in r['error']


def test_retries_with_backoff_and_timeouts(env):
    svc, reg, _ = env
    n = {'c': 0}

    def flaky(a):
        n['c'] += 1
        if n['c'] < 3:
            raise RuntimeError(f'boom {n["c"]}')
        return {'ok': n['c']}
    reg.add(Fn('flaky', flaky), Fn('sleepy', lambda a: time.sleep(1.5) or {'late': True}))
    svc.save({'name': 'retry', 'steps': [
        {'id': 'f', 'tool': 'flaky', 'retry': {'max_attempts': 3, 'backoff_seconds': 0.05}}]}, 'alice', True)
    r = run_and_wait(svc, 'retry')
    assert r['status'] == 'succeeded' and steps_of(svc, r['id'])['f']['attempts'] == 3
    n['c'] = -10
    r = run_and_wait(svc, 'retry')
    assert r['status'] == 'failed' and 'after 3 attempts' in r['error']

    svc.save({'name': 'slow', 'steps': [
        {'id': 's', 'tool': 'sleepy', 'timeout_seconds': 0.2,
         'retry': {'max_attempts': 3, 'backoff_seconds': 0, 'on_timeout': False}}]}, 'alice', True)
    t0 = time.time()
    r = run_and_wait(svc, 'slow')
    assert r['status'] == 'failed' and 'timed out after 0.2s' in r['error']
    assert time.time() - t0 < 1.2 and steps_of(svc, r['id'])['s']['attempts'] == 1


def test_run_timeout_cancel_and_waits(env):
    svc, reg, _ = env
    reg.add(Fn('echo', lambda a: dict(a)))
    svc.save({'name': 'pause', 'steps': [{'id': 'w', 'kind': 'wait', 'seconds': '$input.s'},
                                         {'id': 'after', 'tool': 'echo', 'depends_on': ['w']}]}, 'alice', True)
    r = run_and_wait(svc, 'pause', {'s': 0.3})
    assert r['status'] == 'succeeded'
    # a long wait parks the run, cancel finishes it, every open step is cancelled
    run = svc.start_run('pause', {'s': 3600})
    run = svc.wait_for(run['id'], 3)
    assert run['status'] == 'waiting'
    assert steps_of(svc, run['id'])['w']['detail']['wake_at'] > time.time() + 3000
    svc.cancel(run['id'], 'alice', is_admin=True)
    s = steps_of(svc, run['id'])
    assert svc.store.get_run(run['id'])['status'] == 'cancelled'
    assert s['w']['status'] == 'cancelled' and s['after']['status'] == 'cancelled'
    # cancel while a step runs
    reg.add(Fn('block', lambda a: time.sleep(0.6) or {}))
    svc.save({'name': 'busy', 'steps': [{'id': 'b', 'tool': 'block'}, {'id': 'next', 'tool': 'echo',
                                                                       'depends_on': ['b']}]}, 'alice', True)
    run = svc.start_run('busy', {})
    time.sleep(0.2)
    svc.cancel(run['id'], 'alice', is_admin=True)
    run = svc.wait_for(run['id'], 5)
    assert run['status'] == 'cancelled' and reg.get_tool('echo').calls == [{'args': {}, 'user': 'alice',
                                                                             'source': 'workflow',
                                                                             't': reg.get_tool('echo').calls[0]['t']}]
    # a parked wait wakes through the scheduler
    run = svc.start_run('pause', {'s': 1.5})
    run = svc.wait_for(run['id'], 1)
    assert run['status'] == 'waiting'
    time.sleep(1.6)
    assert svc.tick_runs()['woken'] == 1
    assert svc.wait_for(run['id'], 5)['status'] == 'succeeded'


def test_resume_after_simulated_crash_and_rerun_from_failed_step(env):
    svc, reg, make = env
    counts = {'a': 0, 'b': 0, 'c': 0}

    def mk(k, ann=None):
        def f(a):
            counts[k] += 1
            return {k: counts[k]}
        return Fn(k, f, ann)
    reg.add(mk('a'), mk('b', {'idempotentHint': True}), mk('c'))
    svc.save({'name': 'crashy', 'steps': [
        {'id': 'a', 'tool': 'a'}, {'id': 'b', 'tool': 'b', 'depends_on': ['a']},
        {'id': 'c', 'tool': 'c', 'depends_on': ['b']}]}, 'alice', True)
    wf = svc.store.get_workflow('crashy')

    def crashed_run(b_idempotent_override=None):
        """A run another worker was executing when it died: a done, b in flight, c pending."""
        defn = json.loads(json.dumps(wf['definition']))
        if b_idempotent_override is not None:
            defn['steps'][1]['idempotent'] = b_idempotent_override
        run, _ = svc.store.create_run(workflow='crashy', version=1, definition=defn, run_as='alice',
                                      trigger_type='manual', status='running')
        svc.store.update_run(run['id'], worker_id='dead-host:1:abc', heartbeat_at=time.time() - 30,
                             started_at=time.time() - 31)
        svc.store.put_step(run['id'], 'a', 'tool', status='succeeded', output={'a': 'from-before'}, attempts=1)
        svc.store.put_step(run['id'], 'b', 'tool', status='running', attempts=1)
        svc.store.put_step(run['id'], 'c', 'tool', status='pending')
        return run['id']

    rid = crashed_run()
    other = make('w2')                          # a second worker picks it up
    assert other.tick_runs()['resumed'] == 1
    run = other.wait_for(rid, 5)
    assert run['status'] == 'succeeded'
    assert counts == {'a': 0, 'b': 1, 'c': 1}  # a's stored output reused; b (idempotent) and c ran
    assert run['output']['a'] == {'a': 'from-before'}
    assert svc.tick_runs()['resumed'] == 0      # nothing left to take over

    rid = crashed_run(b_idempotent_override=False)
    assert svc.tick_runs()['resumed'] == 1
    run = svc.wait_for(rid, 5)
    s = steps_of(svc, rid)
    assert run['status'] == 'failed' and 'not idempotent' in s['b']['error'] and s['c']['status'] == 'skipped'
    assert counts == {'a': 0, 'b': 1, 'c': 1}
    rerun = svc.rerun(rid, 'alice', is_admin=True)
    assert rerun['from_step'] == 'b' and rerun['parent_run_id'] == rid
    rerun = svc.wait_for(rerun['id'], 5)
    assert rerun['status'] == 'succeeded' and counts == {'a': 0, 'b': 2, 'c': 2}
    assert steps_of(svc, rerun['id'])['a']['detail'] == {'reused_from': rid}


def test_concurrency_limit_and_idempotency_key(env):
    svc, reg, _ = env
    reg.add(Fn('nap', lambda a: time.sleep(0.4) or {'ok': 1}))
    svc.save({'name': 'one_at_a_time', 'concurrency': 1, 'steps': [{'id': 'n', 'tool': 'nap'}]}, 'alice', True)
    r1 = svc.start_run('one_at_a_time', {})
    r2 = svc.start_run('one_at_a_time', {})
    assert r1['status'] == 'running' and r2['status'] == 'queued'
    assert svc.wait_for(r2['id'], 5)['status'] == 'succeeded'
    assert svc.wait_for(r1['id'], 1)['status'] == 'succeeded'
    a = svc.start_run('one_at_a_time', {}, idempotency_key='k-1')
    b = svc.start_run('one_at_a_time', {}, idempotency_key='k-1')
    assert a['id'] == b['id']


# ── triggers ─────────────────────────────────────────────────────

def test_cron_parsing_timezones_and_dst():
    ny = CronSchedule('0 9 * * 1-5', 'America/New_York')
    t = ny.next_after(datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc))      # Friday 08:00 EDT
    assert t == datetime(2026, 7, 3, 13, 0, tzinfo=timezone.utc)
    t = ny.next_after(t)                                                        # skips the weekend
    assert t == datetime(2026, 7, 6, 13, 0, tzinfo=timezone.utc)
    assert ny.next_after(datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 1, 6, 14, 0, tzinfo=timezone.utc)                       # EST in winter
    gap = CronSchedule('30 2 * * *', 'America/New_York')                        # 02:30 does not exist on 8 March
    assert gap.next_after(datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc)).day == 9
    assert CronSchedule('@hourly').latest_due(datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
                                              datetime(2026, 1, 1, 3, 10, tzinfo=timezone.utc)).hour == 3
    assert CronSchedule('*/15 * * * *').minutes == {0, 15, 30, 45}
    assert CronSchedule('0 0 * * sun,7').weekdays == {0}
    for bad in ('* * *', '0 25 * * *', '0 0 * * mon-xyz'):
        with pytest.raises(CronError):
            CronSchedule(bad)
    with pytest.raises(CronError):
        CronSchedule('0 0 * * *', 'Mars/Olympus')


def test_cron_fires_once_across_two_workers(env):
    svc, reg, make = env
    reg.add(Fn('tick', lambda a: {'at': a.get('scheduled_for')}))
    svc.save({'name': 'nightly', 'steps': [{'id': 't', 'tool': 'tick', 'params': {'scheduled_for': '$input.scheduled_for'}}],
              'triggers': [{'id': 'every_min', 'type': 'cron', 'cron': '* * * * *', 'timezone': 'Europe/London'}]},
             'alice', True)
    w2 = make('w2')
    now = datetime.now(timezone.utc).replace(second=30, microsecond=0)
    fired = []
    barrier = threading.Barrier(2)

    def go(s):
        barrier.wait()
        fired.extend(s.tick_cron(now))
    ts = [threading.Thread(target=go, args=(s,)) for s in (svc, w2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(fired) == 1
    assert svc.tick_cron(now) == [] and w2.tick_cron(now) == []      # same slot: never again
    runs = svc.store.list_runs('nightly')
    assert len(runs) == 1 and runs[0]['trigger_type'] == 'cron'
    assert runs[0]['idempotency_key'] == f'cron:every_min:{now.strftime("%Y-%m-%dT%H:%MZ")}'
    assert svc.wait_for(runs[0]['id'], 5)['status'] == 'succeeded'


def _sign(secret, ts, body):
    return 'sha256=' + hmac.new(secret.encode(), f'{ts}.'.encode() + body, hashlib.sha256).hexdigest()


def test_webhook_signature_and_replay(env):
    svc, reg, _ = env
    reg.add(Fn('echo', lambda a: dict(a)))
    wf = svc.save({'name': 'hooked', 'steps': [{'id': 'e', 'tool': 'echo', 'params': {'order': '$input.order'}}],
                   'triggers': [{'id': 'inbound', 'type': 'webhook', 'tolerance_seconds': 60}]}, 'alice', True)
    secret = wf['definition']['triggers'][0]['secret']
    assert len(secret) >= 32
    body = json.dumps({'order': 42}).encode()
    ts = str(int(time.time()))
    h = {'X-Sajha-Timestamp': ts, 'X-Sajha-Signature': _sign(secret, ts, body), 'X-Sajha-Delivery': 'd-1'}
    code, out = svc.receive_webhook('hooked', 'inbound', body, h)
    assert code == 202
    assert svc.wait_for(out['run_id'], 5)['output']['e'] == {'order': 42}
    assert svc.receive_webhook('hooked', 'inbound', body, h)[0] == 409                     # replay
    assert svc.receive_webhook('hooked', 'inbound', body + b' ', h)[0] == 401              # body changed
    old = str(int(time.time()) - 600)
    assert svc.receive_webhook('hooked', 'inbound', body, {
        'X-Sajha-Timestamp': old, 'X-Sajha-Signature': _sign(secret, old, body)})[0] == 401
    assert svc.receive_webhook('hooked', 'nope', body, h)[0] == 404
    # saving the masked definition keeps the secret
    d = svc.store.get_workflow('hooked')['definition']
    d['triggers'][0]['secret'] = '********'
    assert svc.save(d, 'alice', True)['definition']['triggers'][0]['secret'] == secret


def test_file_trigger_on_the_storage_backend(env, tmp_path):
    from sajha.core.storage import LocalStorageBackend
    svc, reg, make = env
    root = tmp_path / 'store'
    (root / 'inbox').mkdir(parents=True)
    (root / 'inbox' / 'old.csv').write_text('a\n')
    backend = LocalStorageBackend(str(root))
    svc._storage = lambda: backend
    reg.add(Fn('echo', lambda a: dict(a)))
    svc.save({'name': 'onfile', 'steps': [{'id': 'e', 'tool': 'echo', 'params': {'p': '$input.path'}}],
              'triggers': [{'id': 'drop', 'type': 'file', 'prefix': 'inbox', 'pattern': '*.csv',
                            'interval_seconds': 1}]}, 'alice', True)
    assert svc.tick_files() == []                      # first poll: a baseline, existing files do not fire
    (root / 'inbox' / 'new.csv').write_text('b\n')
    (root / 'inbox' / 'skip.txt').write_text('c\n')
    w2 = make('w2', storage=lambda: backend)
    assert w2.tick_files() == []                       # the poll interval is shared: nobody polls yet
    time.sleep(1.1)
    fired = svc.tick_files() + w2.tick_files()
    assert len(fired) == 1 and fired[0]['input']['path'] == 'inbox/new.csv'
    time.sleep(1.1)
    assert svc.tick_files() == []                      # unchanged: no second run
    import os
    os.utime(root / 'inbox' / 'new.csv', (time.time() + 5, time.time() + 5))
    time.sleep(1.1)
    assert len(svc.tick_files()) == 1                  # modified: fires again


def test_change_bus_event_trigger(env):
    from sajha.core.change_bus import ChangeEvent
    svc, reg, _ = env
    reg.add(Fn('echo', lambda a: dict(a)))
    svc.save({'name': 'onchange', 'steps': [{'id': 'e', 'tool': 'echo', 'params': {'k': '$input.event.kind'}}],
              'triggers': [{'id': 'tools', 'type': 'event', 'kinds': ['tools'], 'debounce_seconds': 5}]},
             'alice', True)
    svc.on_change(ChangeEvent('tools'))
    svc.on_change(ChangeEvent('tools'))            # debounced
    svc.on_change(ChangeEvent('prompts'))          # not subscribed
    deadline = time.time() + 5
    while time.time() < deadline and not svc.store.list_runs('onchange'):
        time.sleep(0.05)
    time.sleep(0.3)
    runs = svc.store.list_runs('onchange')
    assert len(runs) == 1 and svc.wait_for(runs[0]['id'], 5)['output']['e'] == {'k': 'tools'}


# ── identity, approvals, delivery ────────────────────────────────

def test_run_as_owner_with_rbac(env):
    svc, reg, _ = env
    ok, secret = reg.add(Fn('public_tool', lambda a: {'ok': 1}), Fn('secret_tool', lambda a: {'s': 1}))
    identity.set_resolver(lambda owner: identity.RunIdentity(owner, ['user'], False,
                                                             can_execute=lambda n: n == 'public_tool'))
    svc.save({'name': 'mine', 'steps': [{'id': 'p', 'tool': 'public_tool'},
                                        {'id': 's', 'tool': 'secret_tool', 'depends_on': ['p']}]}, 'bob')
    r = run_and_wait(svc, 'mine', started_by='someone-else')
    assert r['status'] == 'failed' and "'bob' may not execute secret_tool" in r['error']
    assert ok.calls[0]['user'] == 'bob' and ok.calls[0]['source'] == 'workflow' and secret.calls == []
    with pytest.raises(PermissionError):
        svc.save({'name': 'mine', 'steps': [{'id': 'p', 'tool': 'public_tool'}]}, 'mallory')
    with pytest.raises(PermissionError):
        svc.save({'name': 'pub', 'steps': [{'id': 'p', 'tool': 'public_tool'}], 'publish': True}, 'bob')

    def gone(owner):
        raise identity.OwnerUnavailable(f'the workflow owner {owner!r} is disabled')
    identity.set_resolver(gone)
    assert run_and_wait(svc, 'mine')['error'] == "the workflow owner 'bob' is disabled"


def test_approval_step_waits_for_a_decision(env):
    from sajha.policy import approvals
    svc, reg, _ = env
    reg.add(Fn('ship', lambda a: {'shipped': True}))
    svc.save({'name': 'gated', 'steps': [{'id': 'ok', 'kind': 'approval', 'reason': 'ship it?'},
                                         {'id': 's', 'tool': 'ship', 'depends_on': ['ok']}]}, 'alice', True)
    run = svc.start_run('gated', {})
    run = svc.wait_for(run['id'], 3)
    assert run['status'] == 'waiting'
    aid = steps_of(svc, run['id'])['ok']['detail']['approval_id']
    rec = approvals.get(aid)
    assert rec['status'] == 'pending' and rec['tool'] == 'workflow:gated.ok' and rec['source'] == 'workflow'
    with pytest.raises(approvals.ApprovalError):
        approvals.decide(aid, True, 'alice')                 # the owner cannot approve their own gate
    approvals.decide(aid, True, 'boss', 'fine')
    assert svc.tick_runs()['woken'] == 1
    run = svc.wait_for(run['id'], 5)
    assert run['status'] == 'succeeded' and run['output']['ok']['decided_by'] == 'boss'
    # denied
    run = svc.start_run('gated', {})
    run = svc.wait_for(run['id'], 3)
    aid = steps_of(svc, run['id'])['ok']['detail']['approval_id']
    approvals.decide(aid, False, 'boss', 'no')
    svc.tick_runs()
    run = svc.wait_for(run['id'], 5)
    assert run['status'] == 'failed' and 'denied by boss: no' in run['error']


def test_policy_approval_on_a_tool_step_parks_and_resumes(env):
    import textwrap
    from sajha.policy import approvals
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.loader import PolicySet
    from sajha.policy.model import parse_text as parse_policy
    svc, reg, _ = env
    wire = reg.add(Fn('wf_wire', lambda a: {'sent': a['amount']}))
    ps = PolicySet()
    ps.set_policies([parse_policy(textwrap.dedent('''
        rules:
          - {id: hold, match: {tools: [wf_wire]}, effect: require_approval, reason: big money}
    '''), 'p0', 'p0.yaml')])
    set_engine(PolicyEngine(ps))
    svc.save({'name': 'pay', 'steps': [{'id': 'w', 'tool': 'wf_wire', 'params': {'amount': 5}}]}, 'alice', True)
    run = svc.wait_for(svc.start_run('pay', {})['id'], 3)
    assert run['status'] == 'waiting' and wire.calls == []
    detail = steps_of(svc, run['id'])['w']['detail']
    assert detail['policy'] is True
    approvals.decide(detail['approval_id'], True, 'boss')
    svc.tick_runs()
    run = svc.wait_for(run['id'], 5)
    assert run['status'] == 'succeeded' and wire.calls[0]['args'] == {'amount': 5}


def test_delivery_through_the_async_router(env, monkeypatch):
    svc, reg, _ = env
    got = []

    class Router:
        def validate(self, kind, dest):
            if dest.startswith('/'):
                raise ValueError('no absolute paths')

        def deliver(self, task):
            got.append((task.task_id, task.delivery_type, task.delivery_destination, task.result,
                        task.status.value))
            return True
    monkeypatch.setattr(WorkflowService, '_router', staticmethod(lambda: Router()))
    reg.add(Fn('echo', lambda a: {'v': 1}))
    with pytest.raises(WorkflowError, match='no absolute'):
        svc.save({'name': 'out', 'steps': [{'id': 'e', 'tool': 'echo'}],
                  'delivery': {'type': 'file', 'destination': '/etc/x'}}, 'alice', True)
    svc.save({'name': 'out', 'steps': [{'id': 'e', 'tool': 'echo'}],
              'delivery': {'type': 'file', 'destination': 'wf/out.json'}}, 'alice', True)
    r = run_and_wait(svc, 'out')
    deadline = time.time() + 3
    while time.time() < deadline and svc.store.get_run(r['id'])['delivery_status'] is None:
        time.sleep(0.05)
    assert got == [(r['id'], 'file', 'wf/out.json', {'e': {'v': 1}}, 'completed')]
    assert svc.store.get_run(r['id'])['delivery_status'] == 'delivered'


# ── the app: REST, the page, publish as a tool over MCP (both eras) ──

@pytest.fixture
def app_svc(web):
    """The live app's workflow service, with the real identity resolver and a test tool."""
    from sajha.app import tools_registry
    from sajha.workflows import get_service
    identity.set_resolver(None)
    svc = get_service()
    assert svc is not None, 'the app did not start the workflow service'
    t = Fn('wf_test_echo', lambda a: {'echo': a})
    tools_registry.register_tool(t)
    client, admin = web
    tok = client.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'}).json()['token']
    yield client, admin, {'Authorization': f'Bearer {tok}'}, svc
    for name in ('wf_app_test', 'wf_app_hook'):
        try:
            client.delete(f'/api/workflows/{name}', cookies=admin)
        except Exception:
            pass
    tools_registry.unregister_tool('wf_test_echo')


def test_rest_api_page_and_published_tool_over_mcp(app_svc):
    client, admin, h, svc = app_svc
    yaml_def = ('name: wf_app_test\ndescription: echo through a workflow\n'
                'input_schema: {type: object, properties: {word: {type: string}}}\n'
                'steps:\n  - {id: e, tool: wf_test_echo, params: {w: $input.word}}\n'
                'output: {said: $steps.e.echo.w}\npublish: {enabled: true, timeout_seconds: 20}\n')
    r = client.post('/api/workflows', json={'text': yaml_def}, headers=h)
    assert r.status_code == 200, r.text
    assert client.get('/workflows', cookies=admin).status_code == 200
    r = client.post('/api/workflows/wf_app_test/runs', json={'input': {'word': 'hi'}, 'wait': 10}, headers=h)
    assert r.status_code == 200 and r.json()['run']['output'] == {'said': 'hi'}, r.text
    rid = r.json()['run']['id']
    r = client.get(f'/api/workflows/runs/{rid}', headers=h)
    assert r.json()['run']['steps'][0]['status'] == 'succeeded' and 'definition' not in r.json()['run']
    assert client.get('/api/workflows/wf_app_test/runs', headers=h).json()['runs'][0]['id'] == rid
    assert 'steps:' in client.get('/api/workflows/wf_app_test?format=yaml', headers=h).text
    assert client.post('/api/workflows/validate', json={'name': 'x', 'steps': []}, headers=h).status_code == 400
    assert client.get('/api/workflows/wf_app_test', headers={'Accept': 'application/json'}).status_code == 401

    # MCP 2026-07-28 (stateless): the published workflow is an ordinary tool
    meta = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
            'io.modelcontextprotocol/clientCapabilities': {},
            'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}
    modern = {**h, 'MCP-Protocol-Version': '2026-07-28', 'Accept': 'application/json, text/event-stream'}
    names, cursor = [], None
    for _ in range(50):
        params = {'_meta': meta, **({'cursor': cursor} if cursor else {})}
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': params},
                        headers={**modern, 'Mcp-Method': 'tools/list'})
        page = r.json()['result']
        names += [t['name'] for t in page['tools']]
        cursor = page.get('nextCursor')
        if not cursor:
            break
    assert 'wf_app_test' in names
    r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                  'params': {'name': 'wf_app_test', 'arguments': {'word': 'modern'}, '_meta': meta}},
                    headers={**modern, 'Mcp-Method': 'tools/call', 'Mcp-Name': 'wf_app_test'})
    res = r.json()['result']
    assert res.get('isError') is not True and json.loads(res['content'][0]['text'])['output'] == {'said': 'modern'}

    # MCP 2025-11-25 (session)
    r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'pytest', 'version': '1'}}},
        headers=h)
    sid = r.headers['mcp-session-id']
    legacy = {**h, 'Mcp-Session-Id': sid, 'MCP-Protocol-Version': '2025-11-25', 'Accept': 'application/json'}
    client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}, headers=legacy)
    r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                  'params': {'name': 'wf_app_test', 'arguments': {'word': 'session'}}}, headers=legacy)
    res = r.json()['result']
    assert res.get('isError') is not True and json.loads(res['content'][0]['text'])['output'] == {'said': 'session'}
    runs = client.get('/api/workflows/wf_app_test/runs', headers=h).json()['runs']
    assert {r['trigger_type'] for r in runs} == {'manual', 'tool'}

    # disabling unpublishes
    client.post('/api/workflows/wf_app_test/disable', headers=h)
    from sajha.app import tools_registry
    assert tools_registry.get_tool('wf_app_test') is None
    assert client.delete('/api/workflows/wf_app_test', headers=h).json() == {'success': True}


def test_webhook_route(app_svc):
    client, admin, h, svc = app_svc
    r = client.post('/api/workflows', json={'name': 'wf_app_hook', 'steps': [
        {'id': 'e', 'tool': 'wf_test_echo', 'params': {'n': '$input.n'}}],
        'triggers': [{'id': 'in', 'type': 'webhook'}]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()['workflow']['definition']['triggers'][0]['secret'] == '********'
    secret = client.get('/api/workflows/wf_app_hook?reveal=1', headers=h).json()['definition']['triggers'][0]['secret']
    body = b'{"n": 3}'
    ts = str(int(time.time()))
    hh = {'X-Sajha-Timestamp': ts, 'X-Sajha-Signature': _sign(secret, ts, body), 'Content-Type': 'application/json'}
    r = client.post('/api/workflows/wf_app_hook/hooks/in', content=body, headers=hh)
    assert r.status_code == 202, r.text
    assert svc.wait_for(r.json()['run_id'], 10)['status'] == 'succeeded'
    assert client.post('/api/workflows/wf_app_hook/hooks/in', content=body, headers=hh).status_code == 409
    hh['X-Sajha-Signature'] = 'sha256=00'
    assert client.post('/api/workflows/wf_app_hook/hooks/in', content=body, headers=hh).status_code == 401
