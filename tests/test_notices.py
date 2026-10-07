"""System notices (docs/architecture/System Notices.md, section 6): the service, its sources,
the admin API, the live stream and the console banner, panel and badge."""
import json
import time
import uuid
from types import SimpleNamespace

import pytest

from sajha import notices as N
from sajha.core.state.memory import MemoryStateStore


@pytest.fixture
def svc(monkeypatch):
    """A service on its own memory store, installed as the process's service; audit captured."""
    events = []

    class _Audit:
        def log(self, action, **kw):
            events.append((action, kw.get('resource_id'), kw.get('user_id')))

    monkeypatch.setattr('sajha.core.audit.get_audit_logger', lambda: _Audit())
    s = N.NoticeService(MemoryStateStore('t:'), forward=[])
    s.events = events
    saved = N._service
    N.set_service(s)
    yield s
    N.set_service(saved)


# ── the service ──────────────────────────────────────────────────────

def test_raise_refresh_clear_one_entry_per_id(svc):
    a = N.raise_notice('x.cond:1', severity='warning', source='x', title='One', detail='d')
    assert a['state'] == 'active' and a['since'] == a['last_seen']
    time.sleep(0.01)
    b = N.raise_notice('x.cond:1', severity='warning', source='x', title='One', detail='d')
    assert b['since'] == a['since'] and b['last_seen'] > a['last_seen']
    assert len([n for n in svc.all() if n['id'] == 'x.cond:1']) == 1
    assert [e[0] for e in svc.events] == ['notice.raised']          # a refresh is not a transition
    assert N.clear_notice('x.cond:1') is True
    assert svc.get('x.cond:1')['state'] == 'cleared'
    assert N.clear_notice('x.cond:1') is False                        # already cleared
    assert [e[0] for e in svc.events] == ['notice.raised', 'notice.cleared']
    assert svc.list('open') == [] and [n['id'] for n in svc.list('cleared')] == ['x.cond:1']
    # raised again after clearing: a new occurrence
    c = N.raise_notice('x.cond:1', severity='error', title='One again')
    assert c['state'] == 'active' and c['since'] > a['since']


def test_ttl_clears_a_notice_nobody_refreshes(svc):
    N.raise_notice('x.ttl', ttl_minutes=1, title='t')
    N.raise_notice('x.forever', ttl_minutes=0, title='f')
    assert svc.sweep(now=time.time() + 30) == 0
    assert svc.sweep(now=time.time() + 120) == 1
    assert svc.get('x.ttl')['state'] == 'cleared' and svc.get('x.ttl')['cleared_reason'] == 'ttl'
    assert svc.get('x.forever')['state'] == 'active'


def test_escalation_reopens_an_acknowledged_notice(svc):
    N.raise_notice('x.esc', severity='warning', title='e')
    svc.acknowledge('x.esc', 'alice')
    assert svc.get('x.esc')['state'] == 'acknowledged'
    N.raise_notice('x.esc', severity='warning', title='e')            # same severity: stays acknowledged
    assert svc.get('x.esc')['state'] == 'acknowledged'
    N.raise_notice('x.esc', severity='error', title='e')              # worse: shouts again
    n = svc.get('x.esc')
    assert n['state'] == 'active' and n['acknowledged_by'] is None
    assert ('notice.acknowledged', 'x.esc', 'alice') in svc.events and ('notice.escalated', 'x.esc', 'system') in svc.events


def test_holders_one_worker_cannot_clear_another_workers_condition(svc):
    N.raise_notice('x.brk', holder='w1', title='b')
    N.raise_notice('x.brk', holder='w2', title='b')
    assert N.clear_notice('x.brk', holder='w1') is False
    assert svc.get('x.brk')['state'] == 'active' and list(svc.get('x.brk')['holders']) == ['w2']
    assert N.clear_notice('x.brk', holder='w2') is True


def test_max_active_drops_the_oldest_lowest_severity(svc, monkeypatch):
    monkeypatch.setenv('SAJHA_NOTICES_MAX_ACTIVE', '3')
    N.raise_notice('x.i1', severity='info', title='i1')
    N.raise_notice('x.i2', severity='info', title='i2')
    N.raise_notice('x.e1', severity='error', title='e1')
    N.raise_notice('x.w1', severity='warning', title='w1')             # evicts i1 (oldest info)
    assert {n['id'] for n in svc.list('open')} == {'x.i2', 'x.e1', 'x.w1'}
    assert svc.get('x.i1')['cleared_reason'] == 'evicted'
    assert N.raise_notice('x.i3', severity='info', title='i3') is not None   # evicts i2 (an equal info)
    N.raise_notice('x.c1', severity='critical', title='c1')
    N.raise_notice('x.e2', severity='error', title='e2')
    assert len(svc.list('open')) == 3
    assert N.raise_notice('x.i4', severity='info', title='i4') is None       # everything open is worse


def test_switched_off(svc, monkeypatch):
    monkeypatch.setenv('SAJHA_NOTICES_ENABLED', 'false')
    assert N.raise_notice('x.off', title='o') is None
    v = N.view(True)
    assert v['enabled'] is False and v['banner'] is None


def test_view_banner_badge_and_audience(svc):
    N.raise_notice('x.w', severity='warning', title='w', audience='everyone')
    N.raise_notice('x.e', severity='error', title='e')                 # admin only
    N.raise_notice('x.i', severity='info', title='i', audience='everyone')
    admin, user = N.view(True), N.view(False)
    assert admin['banner']['id'] == 'x.e' and admin['badge'] == 2 and admin['others'] == 2
    assert {n['id'] for n in user['notices']} == {'x.w', 'x.i'}
    assert user['banner'] is None and user['badge'] == 1                 # a warning never takes the banner
    assert 'workers' not in user['notices'][0] and 'workers' in admin['notices'][0]
    assert N.view(True, authenticated=False)['notices'] == []
    # acknowledged: off the banner and the badge, still on the panel
    svc.acknowledge('x.e', 'admin')
    admin = N.view(True)
    assert admin['banner'] is None and admin['badge'] == 1 and len(admin['notices']) == 3


def test_critical_stays_on_the_banner_when_acknowledged(svc):
    N.raise_notice('x.c', severity='critical', title='c')
    svc.acknowledge('x.c', 'admin')
    v = N.view(True)
    assert v['banner']['id'] == 'x.c' and v['badge'] == 1


def test_banner_min_severity_critical(svc, monkeypatch):
    monkeypatch.setenv('SAJHA_NOTICES_BANNER_MIN_SEVERITY', 'critical')
    N.raise_notice('x.e', severity='error', title='e')
    assert N.view(True)['banner'] is None


def test_several_workers_share_notices(tmp_path, monkeypatch):
    """Two services (two workers) on one database state store see and change the same notices."""
    monkeypatch.setattr('sajha.core.audit.get_audit_logger', lambda: SimpleNamespace(log=lambda *a, **k: None))
    from sajha.core.state.database import DatabaseStateStore
    url = f'sqlite:///{tmp_path}/state.db'
    a = N.NoticeService(DatabaseStateStore(url=url, prefix='mw:', poll_interval=0.05), forward=[])
    b = N.NoticeService(DatabaseStateStore(url=url, prefix='mw:', poll_interval=0.05), forward=[])
    try:
        a.raise_notice('x.shared', severity='error', title='s', holder='A')
        assert b.get('x.shared')['state'] == 'active' and b.version() == a.version() >= 1
        b.raise_notice('x.shared', severity='error', title='s', holder='B')
        assert len(b.list('open')) == 1
        b.acknowledge('x.shared', 'admin')
        assert a.get('x.shared')['state'] == 'acknowledged'
        assert a.clear('x.shared', holder='A') is False
        assert b.clear('x.shared', holder='B') is True
        assert a.get('x.shared')['state'] == 'cleared'
    finally:
        a.store.close()
        b.store.close()


def test_forward_rules_and_delivery(svc, monkeypatch, caplog):
    rules, errors = N.parse_forward_rules([
        {'min_severity': 'error', 'channel': {'type': 'log'}},
        {'min_severity': 'nope', 'channel': 'log'},
        {'min_severity': 'critical', 'channel': {'type': 'notice'}},
        {'min_severity': 'critical', 'channel': {'type': 'webhook', 'url': 'https://not-allowed.example/x'}},
        {'min_severity': 'critical', 'channel': {'type': 'email'}},
    ])
    assert [r['min_severity'] for r in rules] == ['error'] and len(errors) == 4
    svc._forward = rules
    import logging
    with caplog.at_level(logging.WARNING, logger='sajha.observability.alerts'):
        N.raise_notice('x.fw:w', severity='warning', title='quiet')
        N.raise_notice('x.fw:e', severity='error', title='loud')
        N.raise_notice('x.fw:e', severity='error', title='loud')       # refresh: not forwarded again
    sent = [r.getMessage() for r in caplog.records if r.name == 'sajha.observability.alerts']
    assert sent == ['NOTICE [error] loud (x.fw:e)']


def test_forward_rules_from_environment(monkeypatch):
    monkeypatch.setenv('SAJHA_NOTICES_FORWARD', json.dumps([{'min_severity': 'warning', 'channel': 'log'}]))
    assert N.NoticeService(MemoryStateStore('f:')).forward_rules == [
        {'min_severity': 'warning', 'channel': {'type': 'log'}}]


# ── sources ──────────────────────────────────────────────────────────

def test_breaker_source_and_listener(svc):
    from sajha.core import circuit_breaker as cb
    from sajha.notices import sources
    reg = cb.get_circuit_registry()
    name = f'zz_notices_{uuid.uuid4().hex[:6]}_'
    reg.register_prefix(name, f'Test upstream {name}', failure_threshold=2, recovery_timeout=60)
    b = reg.get_breaker(name + 'tool')
    nid = sources.BREAKER_PREFIX + b.name
    cb.add_listener(sources.on_breaker_change)
    try:
        b.record_failure()
        assert svc.get(nid) is None
        b.record_failure()                                                # CLOSED -> OPEN
        n = svc.get(nid)
        assert n['state'] == 'active' and n['source'] == 'resilience' and n['link'] == '/admin/federation'
        sources.check_breakers()                                          # the poll agrees
        assert svc.get(nid)['state'] == 'active'
        b.state, b.success_count = cb.CircuitState.HALF_OPEN, 0
        b.record_success()                                                # HALF_OPEN -> CLOSED
        assert svc.get(nid)['state'] == 'cleared'
        # the poll alone raises and clears too
        b.state = cb.CircuitState.OPEN
        sources.check_breakers()
        assert svc.get(nid)['state'] == 'active'
        b.state = cb.CircuitState.CLOSED
        sources.check_breakers()
        assert svc.get(nid)['state'] == 'cleared'
    finally:
        cb.remove_listener(sources.on_breaker_change)
        with reg._lock:
            reg._breakers.pop(name, None)
            reg._extra.pop(name, None)


def test_workflow_source(svc, monkeypatch):
    from sajha.notices import sources
    monkeypatch.setenv('SAJHA_NOTICES_WORKFLOW_FAILURES', '2')
    nid = sources.WORKFLOW_PREFIX + 'nightly'
    sources.workflow_run_finished('nightly', 'manual', 'failed', 'boom')     # not scheduled: ignored
    sources.workflow_run_finished('nightly', 'cron', 'failed', 'boom')
    assert svc.get(nid) is None
    sources.workflow_run_finished('nightly', 'cron', 'failed', 'boom twice')
    n = svc.get(nid)
    assert n['severity'] == 'error' and 'boom twice' in n['detail'] and n['ttl'] == 0
    sources.workflow_run_finished('nightly', 'cron', 'succeeded')
    assert svc.get(nid)['state'] == 'cleared'
    sources.workflow_run_finished('nightly', 'cron', 'failed', 'again')       # the count restarted
    assert svc.get(nid)['state'] == 'cleared'


def test_workflow_notice_cleared_when_the_workflow_is_gone(svc, monkeypatch):
    from sajha.notices import sources
    N.raise_notice(sources.WORKFLOW_PREFIX + 'gone', severity='error', title='g', ttl_minutes=0)
    fake = SimpleNamespace(store=SimpleNamespace(get_workflow=lambda name: None))
    monkeypatch.setattr('sajha.workflows.get_service', lambda: fake)
    sources.check_workflows()
    assert svc.get(sources.WORKFLOW_PREFIX + 'gone')['state'] == 'cleared'


def test_llm_source(svc, monkeypatch):
    from sajha.notices import sources
    from sajha.ai.llm.errors import NoModelAvailable
    from sajha.ai.llm.model import HealthStatus
    health = {'good': HealthStatus('ok'), 'bad': HealthStatus('down', 'HTTP 401')}

    def resolve(alias):
        if alias == 'reasoning':
            raise NoModelAvailable("no model available for 'reasoning'")
        return None

    providers = {'good': SimpleNamespace(active=True), 'bad': SimpleNamespace(active=True),
                 'off': SimpleNamespace(active=False)}
    gw = SimpleNamespace(
        provider_names=lambda: list(providers), provider=providers.get,
        provider_health=lambda n: health[n], settings=SimpleNamespace(aliases={'default': [], 'reasoning': []}),
        resolve=resolve, breaker_states=lambda: {})
    gw.model = lambda alias: SimpleNamespace(info=lambda: gw.resolve(alias))
    monkeypatch.setattr('sajha.ai.llm.llm_factory', lambda: gw)
    sources.check_llm()
    assert svc.get(sources.PROVIDER_PREFIX + 'bad')['state'] == 'active'
    assert svc.get(sources.PROVIDER_PREFIX + 'good') is None
    a = svc.get(sources.ALIAS_PREFIX + 'reasoning')
    assert a['state'] == 'active' and a['severity'] == 'warning'
    health['bad'] = HealthStatus('ok')
    gw.resolve = lambda alias: None
    sources.check_llm()
    assert svc.get(sources.PROVIDER_PREFIX + 'bad')['state'] == 'cleared'
    assert svc.get(sources.ALIAS_PREFIX + 'reasoning')['state'] == 'cleared'


def test_federation_source(svc, monkeypatch):
    from sajha.notices import sources
    status = [
        {'id': 'up1', 'title': 'Up one', 'enabled': True, 'state': 'error', 'last_error': 'refused',
         'counts': {'approved': 3}, 'items': [{'kind': 'tool', 'status': 'pending'},
                                             {'kind': 'tool', 'status': 'changed'},
                                             {'kind': 'prompt', 'status': 'pending'}]},
        {'id': 'up2', 'enabled': True, 'state': 'connected', 'counts': {}, 'items': []},
        {'id': 'up3', 'enabled': False, 'state': 'disabled', 'counts': {}, 'items': []},
    ]
    fed = SimpleNamespace(settings=SimpleNamespace(enabled=True), status=lambda: status)
    monkeypatch.setattr('sajha.federation.manager.get_federation', lambda: fed)
    sources.check_federation()
    down = svc.get(sources.UPSTREAM_PREFIX + 'up1')
    assert down['severity'] == 'error' and down['audience'] == 'everyone'
    held = svc.get(sources.APPROVAL_PREFIX + 'up1')
    assert held['title'].startswith('2 tools from Up one')
    assert svc.get(sources.UPSTREAM_PREFIX + 'up2') is None
    status[0].update(state='connected', items=[])
    sources.check_federation()
    assert svc.get(sources.UPSTREAM_PREFIX + 'up1')['state'] == 'cleared'
    assert svc.get(sources.APPROVAL_PREFIX + 'up1')['state'] == 'cleared'


def test_alert_rule_notice_channel(svc, monkeypatch):
    from sajha.observability import alerts
    from sajha.notices import sources
    rule = alerts.parse_rule({'name': 'breakers', 'metric': 'breaker_open', 'op': '>=', 'threshold': 1,
                              'channel': {'type': 'notice', 'severity': 'error', 'audience': 'everyone'}})
    assert not rule.error
    assert alerts.parse_rule({'name': 'b', 'metric': 'breaker_open', 'op': '>', 'threshold': 0,
                              'channel': {'type': 'notice', 'severity': 'loud'}}).error
    mgr = alerts.AlertManager([rule])
    monkeypatch.setattr(mgr, 'value', lambda r, now: (2.0, 1))
    monkeypatch.setattr('sajha.observability.metrics.record_alert', lambda name: None)
    mgr.evaluate()
    n = svc.get(sources.ALERT_PREFIX + 'breakers')
    assert n['state'] == 'active' and n['severity'] == 'error' and n['audience'] == 'everyone'
    monkeypatch.setattr(mgr, 'value', lambda r, now: (0.0, 1))
    mgr.evaluate()
    assert svc.get(sources.ALERT_PREFIX + 'breakers')['state'] == 'cleared'


# ── HTTP: API, stream and console ───────────────────────────────────

PASSWORD = 'Notices-Pass-1'


@pytest.fixture(scope='module')
def plain_user():
    from sajha.db.engine import get_db_session
    from sajha.db.dao import UserDAO, RoleDAO
    from sajha.db.models import User
    from sajha.auth.password import hash_password
    uid = f'notices_{uuid.uuid4().hex[:8]}'
    db = get_db_session()
    try:
        u = User(user_id=uid, user_name=uid, email='', password_hash=hash_password(PASSWORD), enabled=True)
        u.roles.append(RoleDAO(db).get_or_create('user'))
        UserDAO(db).create(u)
    finally:
        db.close()
    yield uid
    db = get_db_session()
    try:
        u = UserDAO(db).get_by_user_id(uid)
        if u:
            UserDAO(db).delete(u)
    finally:
        db.close()


@pytest.fixture
def http(web, plain_user):
    """(client, admin cookies, user cookies), and test notices cleaned up afterwards."""
    client, admin = web
    from sajha.security import _login_throttle
    try:
        _login_throttle.reset()
    except Exception:
        pass
    r = client.post('/login', data={'user_id': plain_user, 'password': PASSWORD}, follow_redirects=False)
    user = dict(r.cookies)
    client.cookies.clear()
    yield client, admin, user
    for n in N.get_service().all():
        if n['id'].startswith('test.'):
            N.get_service().store.delete(N.KEY + n['id'])


def test_api_view_and_admin_actions(http):
    client, admin, user = http
    N.raise_notice('test.api:e', severity='error', title='API error', audience='admin')
    N.raise_notice('test.api:w', severity='warning', title='API warning', audience='everyone')
    v = client.get('/api/notices', cookies=admin).json()
    assert v['banner']['id'] == 'test.api:e' and v['csrf']
    u = client.get('/api/notices', cookies=user).json()
    ids = {n['id'] for n in u['notices']}
    assert 'test.api:w' in ids and 'test.api:e' not in ids and 'csrf' not in u
    assert client.get('/api/notices').status_code == 401
    # admin list; non-admins refused
    lst = client.get('/api/admin/notices', cookies=admin).json()['notices']
    assert {'test.api:e', 'test.api:w'} <= {n['id'] for n in lst}
    assert client.get('/api/admin/notices', cookies=user).status_code == 403
    assert client.get('/api/admin/notices?state=bogus', cookies=admin).status_code == 400
    # acknowledge: CSRF for cookie callers; non-admins refused; unknown id 404
    url = '/api/admin/notices/test.api:e/acknowledge'
    assert client.post(url, cookies=admin).status_code == 403
    assert client.post(url, cookies=user, headers={'X-CSRF-Token': v['csrf']}).status_code == 403
    r = client.post(url, cookies=admin, headers={'X-CSRF-Token': v['csrf']})
    assert r.status_code == 200 and r.json()['notice']['state'] == 'acknowledged'
    assert client.post('/api/admin/notices/test.none/acknowledge', cookies=admin,
                       headers={'X-CSRF-Token': v['csrf']}).status_code == 404
    r = client.post('/api/admin/notices/test.api:w/clear', cookies=admin, headers={'X-CSRF-Token': v['csrf']})
    assert r.json()['notice']['state'] == 'cleared' and r.json()['notice']['cleared_reason'] == 'admin'
    cleared = client.get('/api/notices?cleared=1', cookies=admin).json()['cleared']
    assert 'test.api:w' in {n['id'] for n in cleared}


def test_stream_sends_the_view(http):
    client, admin, _ = http
    N.raise_notice('test.stream', severity='critical', title='Streamed')
    r = client.get('/api/notices/stream?once=1', cookies=admin)
    assert r.status_code == 200 and r.headers['content-type'].startswith('text/event-stream')
    data = [line[len('data: '):] for line in r.text.splitlines() if line.startswith('data: ')]
    view = json.loads(data[0])
    assert 'event: notices' in r.text and view['banner']['id'] == 'test.stream'


def test_console_banner_badge_and_panel(http):
    client, admin, user = http
    N.raise_notice('test.page:c', severity='critical', title='Database <down>', audience='admin')
    N.raise_notice('test.page:w', severity='warning', title='Shared warning', audience='everyone')
    page = client.get('/dashboard', cookies=admin).text
    assert 'id="sajha-notice-banner"' in page and 'role="alert"' in page
    assert 'Database &lt;down&gt;' in page and 'Critical:' in page            # severity in words
    assert 'id="sajha-notice-badge"' in page and 'id="system-status"' in page and 'ssp-initial' in page
    other = client.get('/tools', cookies=admin).text                         # the banner is on every page
    assert 'Database &lt;down&gt;' in other and 'id="system-status"' not in other
    upage = client.get('/dashboard', cookies=user).text
    assert 'Database &lt;down&gt;' not in upage and 'Shared warning' in upage
    # signed out: nothing
    assert 'sajha-notice-banner' not in client.get('/login').text


def test_every_route_answers_when_switched_off(http, monkeypatch):
    client, admin, _ = http
    monkeypatch.setenv('SAJHA_NOTICES_ENABLED', 'false')
    assert client.get('/api/notices', cookies=admin).json()['enabled'] is False
    assert 'id="sajha-notice-banner"' not in client.get('/dashboard', cookies=admin).text
