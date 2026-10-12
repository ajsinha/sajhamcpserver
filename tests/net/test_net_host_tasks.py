# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Tasks held at the host (Roadmap L19; protocol §6.2 ``tasks``, §15.6; design §9 "Tasks").

Covers: the ``tasks`` feature listed and a proxy offered as a task; a task-augmented call at the home creates
the task at the host (the hop carries ``_meta["io.sajha/net"].task`` and the tasks extension) and the home's
task follows it through signed ``tasks/get``; the task outlives the hop's deadline; a home "restart" (a new
task store over the same records, its worker gone) still reads the task from the host; ``tasks/cancel``
reaches the running tool at the host; another member cannot read the task; an input request inside the host
task is answered through ``tasks/update`` at the home; a refusal inside the task fails it with the net
refusal; and a host that does not list ``tasks`` falls back to today's home-held task.
"""

from __future__ import annotations

import json
import time

import pytest

from sajha.core.mcp_tasks import TaskStore
from sajha.core.state.memory import MemoryStateStore
from sajha.net import EXTENSION_ID
from sajha.net.routing import HostRefusal
from tests.net.test_net_mrtr import ASK, Ask, answer
from tests.net import test_net_routing_integration as tri
from tests.net.test_net_routing_integration import Echo, make, node, settle
from tests.net.test_net_streaming import Slow, StreamConnector, quick, stream_app_for, tool_of

NET = 'acme-net'
SLOW = 'acme-net__cust-na__slow'


@pytest.fixture
def net3(tmp_path, monkeypatch):
    """risk-eu (home, founder), cust-na (hosts ``ask`` and ``slow``) and treasury-na."""
    monkeypatch.setattr(tri, 'app_for', stream_app_for)
    conn = StreamConnector()
    a = make(tmp_path, 'risk-eu', conn, [Echo('var_calc', owner='risk-eu')], founder=True)
    a.start(run_agents=False)
    a.ca_init(NET)
    assert node(a).try_join()
    out = {'a': a, 'conn': conn}
    for key, name, tools in (('b', 'cust-na', [Ask('cust-na'), Slow('slow', owner='cust-na', steps=1)]),
                             ('c', 'treasury-na', [Echo('rates', owner='treasury-na')])):
        s = make(tmp_path, name, conn, tools)
        s.start(run_agents=False)
        tok = a.ca_token(NET, name)
        s.enroll(NET, 'https://risk-eu.test', tok['token'], by='test')
        assert node(s).try_join()
        out[key] = s
    settle([out['a'], out['b'], out['c']], 5)
    audits = []
    out['b'].catalogs.hosts[NET].audit = lambda what, d: audits.append((what, d))
    out['host_audits'] = audits
    for s in (out['a'], out['b'], out['c']):
        quick(s, progress_min_interval_ms=0)
    yield out
    for s in (out['a'], out['b'], out['c']):
        s.stop()


class Handler:
    """The part of MCPHandler the 2026-07-28 task runner uses: the home's registry tool, run as a call."""

    def __init__(self, svc):
        self.svc = svc

    def _fixtures(self):
        return None

    def _handle_tools_call(self, params, session, era):
        return self.svc.tools_registry.get_tool(params['name']).execute_with_tracking(params.get('arguments') or {})


def home_task(svc, name, args, store):
    """A task-augmented call at the home, as ModernMCPServer starts one."""
    from sajha.core.mcp_modern import ModernMCPServer
    srv = ModernMCPServer.__new__(ModernMCPServer)
    srv.handler = Handler(svc)
    runner = srv._task_runner(name, {'name': name, 'arguments': args}, {}, None)
    return store.create(None, runner)


def until(fn, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    return fn()


def record(store, task):
    return store.records.get(store._prefix + task.task_id)


def remote_of(store, task):
    return until(lambda: (record(store, task) or {}).get('remote'))


def test_tasks_listed_and_proxy_offered_as_a_task(net3):
    a, b = net3['a'], net3['b']
    assert 'tasks' in node(b).features
    assert 'tasks' in node(a).member('cust-na')['record']['features']
    proxy = a.tools_registry.get_tool(SLOW)
    assert proxy.config['execution'] == {'taskSupport': 'optional'}
    assert '_host_tasks' not in json.dumps(proxy.to_mcp_format())       # the marker is never listed


def test_task_held_at_the_host_outlives_the_hop_deadline(net3):
    a, b, conn = net3['a'], net3['b'], net3['conn']
    slow = tool_of(b, 'slow')
    slow.hold = 1.5
    a.catalogs.router.default_timeout = 0.5                            # the hop's deadline
    a.catalogs.router.peer.timeout_seconds = 0.5
    store = TaskStore(MemoryStateStore(), prefix='test:home:')
    task = home_task(a, SLOW, {'x': 4}, store)
    remote = remote_of(store, task)
    assert remote and remote['host'] == 'cust-na' and remote['kind'] == 'sajhanet', record(store, task)
    sent = json.loads(conn.mcp[-1][2]) if conn.mcp[-1][1].get('mcp-method') == 'tools/call' else \
        next(json.loads(x[2]) for x in reversed(conn.mcp) if x[1].get('mcp-method') == 'tools/call')
    assert sent['params']['_meta'][EXTENSION_ID]['task'] == 1
    assert 'io.modelcontextprotocol/tasks' in \
        sent['params']['_meta']['io.modelcontextprotocol/clientCapabilities']['extensions']
    # the host holds the task for <net>/<home>/<user>
    held = b.catalogs.hosts[NET].tasks.store
    assert held.records.get(held._prefix + remote['task_id'])['owner'] == f'{NET}/risk-eu/'
    assert store.get(task.task_id, None).status == 'working'           # a signed tasks/get to the host
    assert any(x[1].get('mcp-method') == 'tasks/get' for x in conn.mcp)
    done = until(lambda: store.get(task.task_id, None).status == 'completed', 6)
    assert done, record(store, task)
    t = store.get(task.task_id, None)
    assert t.result['content'][0]['text'] == 'cust-na:slow:4'
    m = t.result['_meta'][EXTENSION_ID]
    assert m['instance'] == 'cust-na' and m['task_id'] == remote['task_id'] and m['qualified_name'] == SLOW
    outcomes = [d['outcome'] for w, d in net3['host_audits'] if w == 'net.host_call']
    assert outcomes[:1] == ['task'] and 'ok' in outcomes


def test_a_home_restart_keeps_following_the_host_task(net3):
    a, b = net3['a'], net3['b']
    slow = tool_of(b, 'slow')
    slow.hold = 0.8
    records = MemoryStateStore()
    store = TaskStore(records, prefix='test:home:')
    task = home_task(a, SLOW, {'x': 5}, store)
    assert remote_of(store, task)
    # the home restarts: a new store over the same records, no runner here, the worker that started it gone
    records.update('test:home:' + task.task_id, lambda cur: dict(cur, worker='a-previous-run:1:dead'))
    again = TaskStore(records, prefix='test:home:')
    assert again.get(task.task_id, None).status == 'working'           # not reaped as orphaned
    assert until(lambda: again.get(task.task_id, None).status == 'completed', 6)
    assert again.get(task.task_id, None).result['content'][0]['text'] == 'cust-na:slow:5'


def test_cancel_reaches_the_tool_at_the_host(net3):
    a, b = net3['a'], net3['b']
    slow = tool_of(b, 'slow')
    slow.hold = 10
    store = TaskStore(MemoryStateStore(), prefix='test:home:')
    task = home_task(a, SLOW, {'x': 1}, store)
    remote = remote_of(store, task)
    assert until(lambda: slow.calls >= 1)
    store.cancel(task.task_id, None)
    assert store.get(task.task_id, None).status == 'cancelled'
    assert slow.cancelled.wait(3)                                      # the host tool stopped
    held = b.catalogs.hosts[NET].tasks.store
    owner = held.records.get(held._prefix + remote['task_id'])['owner']
    assert until(lambda: held.get(remote['task_id'], owner).status == 'cancelled')


def test_another_member_cannot_read_the_task(net3):
    a, b, c = net3['a'], net3['b'], net3['c']
    tool_of(b, 'slow').hold = 1.0
    store = TaskStore(MemoryStateStore(), prefix='test:home:')
    task = home_task(a, SLOW, {'x': 1}, store)
    remote = remote_of(store, task)
    for method in ('tasks/get', 'tasks/cancel'):
        out = c.catalogs.router.task_request(NET, 'cust-na', method, remote['task_id'])
        assert out.get('refusal', {}).get('reason') == 'unknown_task', out
    out = a.catalogs.router.task_request(NET, 'cust-na', 'tasks/get', remote['task_id'])
    assert out['result']['status'] in ('working', 'completed')


def test_input_requests_inside_a_host_task(net3):
    a, b = net3['a'], net3['b']
    store = TaskStore(MemoryStateStore(), prefix='test:home:')
    task = home_task(a, ASK, {'x': 1}, store)
    assert remote_of(store, task)
    t = until(lambda: (lambda x: x if x.status == 'input_required' else None)(store.get(task.task_id, None)))
    assert t and list(t.pending) == ['a'], record(store, task)
    store.update(task.task_id, None, {'a': answer('one')})
    t = until(lambda: (lambda x: x if x.status == 'input_required' and 'b' in x.pending else None)(
        store.get(task.task_id, None)))
    assert t and list(t.pending) == ['b'], record(store, task)
    store.update(task.task_id, None, {'b': answer('two')})
    t = until(lambda: (lambda x: x if x.status == 'completed' else None)(store.get(task.task_id, None)))
    assert t and t.result['content'][0]['text'] == 'one+two:b', record(store, task)


def test_a_refusal_inside_the_host_task_fails_it(net3, monkeypatch):
    a, b = net3['a'], net3['b']

    def refuse(ctx, arguments):
        raise HostRefusal('access')
    monkeypatch.setattr(b.catalogs.hosts[NET], 'execute', refuse)
    store = TaskStore(MemoryStateStore(), prefix='test:home:')
    task = home_task(a, SLOW, {'x': 1}, store)
    assert remote_of(store, task)
    t = until(lambda: (lambda x: x if x.status == 'failed' else None)(store.get(task.task_id, None)))
    assert t, record(store, task)
    rf = t.error['data'][EXTENSION_ID]
    assert rf['reason'] == 'access' and rf['side'] == 'host' and rf['executed'] is False


def test_a_host_without_tasks_falls_back_to_the_home_held_task(net3):
    a, b = net3['a'], net3['b']
    b.catalogs.hosts[NET].tasks = None
    node(b).extra_features.remove('tasks')
    rec = node(a).member('cust-na')['record']
    if 'tasks' in rec['features']:                                    # the home's view of the member, as gossiped
        a.catalogs.router.tasks = False
    store = TaskStore(MemoryStateStore(), prefix='test:home:')
    task = home_task(a, SLOW, {'x': 9}, store)
    t = until(lambda: (lambda x: x if x.status == 'completed' else None)(store.get(task.task_id, None)))
    assert t and t.result['content'][0]['text'] == 'cust-na:slow:9'
    assert not (record(store, task) or {}).get('remote')
