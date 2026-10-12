# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The SAJHA Net management pages (design §17.1): conflicts and reviews, users across the net, access and
blocks, the key directory, snapshots, live activity, certificates, net settings, sponsored servers, the
change history, and an instance's tabs; with blast radius, reasons and undo on every change, CSRF on
console changes, and administrators only. Off (a net of one) and on a running open-mode net of three.
"""

import pytest

from tests.net.test_net_integration import ClientConnector, csrf_header
from tests.net.test_net_three_instances import NET, Instance, Who, _open, isolate, settle  # noqa: F401

PAGES = ['/admin/sajhanet/reviews', '/admin/sajhanet/users', '/admin/sajhanet/blocks', '/admin/sajhanet/keys',
         '/admin/sajhanet/snapshots', '/admin/sajhanet/activity', '/admin/sajhanet/certificates',
         '/admin/sajhanet/settings', '/admin/sajhanet/sponsored', '/admin/sajhanet/changes']
APIS = ['/api/sajhanet/reviews', '/api/sajhanet/activity', '/api/sajhanet/certificates', '/api/sajhanet/settings',
        '/api/sajhanet/snapshots']


# ── SAJHA Net off ───────────────────────────────────────────────────

@pytest.mark.parametrize('url', PAGES)
def test_each_page_renders_off_with_page_help(web, url):
    c, admin = web
    r = c.get(url, cookies=admin)
    assert r.status_code == 200, r.text[:300]
    assert 'class="page-help"' in r.text and 'data-sn-csrf' in r.text or url == '/admin/sajhanet/activity'
    assert 'sn-subnav' in r.text


@pytest.mark.parametrize('url', PAGES)
def test_pages_are_admin_only(web, url):
    c, _admin = web
    assert c.get(url, follow_redirects=False).status_code in (302, 303, 401, 403)


@pytest.mark.parametrize('url', APIS)
def test_apis_need_an_administrator_and_answer_off(web, url):
    c, admin = web
    assert c.get(url).status_code in (401, 403)
    r = c.get(url, cookies=admin)
    assert r.status_code == 200 and isinstance(r.json(), dict)


def test_changes_need_sajha_net_and_csrf(web):
    c, admin = web
    assert c.get('/api/sajhanet/nets/default/changes', cookies=admin).status_code == 503
    # a console session without the page's token is refused before anything else
    assert c.post('/api/sajhanet/nets/default/changes/x/undo', cookies=admin, json={'reason': 'r'}).status_code == 403
    assert c.post('/api/sajhanet/nets/default/changes/x/undo', cookies=admin, json={'reason': 'r'},
                  headers=csrf_header(admin)).status_code == 503


def test_menu_lists_the_management_pages(web):
    c, admin = web
    page = c.get('/dashboard', cookies=admin).text
    for url in PAGES:
        assert url in page


# ── a running net of three ──────────────────────────────────────────

@pytest.fixture
def net3(tmp_path, isolate):
    from sajha.net.integration import set_service
    conn = ClientConnector()
    a = _open(Instance(tmp_path, 'open-eu', conn, [Who('var_calc', owner='open-eu')], seeds=[]))
    b = _open(Instance(tmp_path, 'open-na', conn, [Who('lookup', owner='open-na')], seeds=['https://open-eu.test']))
    d = _open(Instance(tmp_path, 'open-ap', conn, [Who('lookup', owner='open-ap')], seeds=['https://open-eu.test']))
    for i in (a, b, d):
        i.svc.start(run_agents=False)
    assert a.node.try_join() and b.node.try_join() and d.node.try_join()
    settle([a, b, d], 4)
    set_service(a.svc)
    try:
        yield a, b, d
    finally:
        for i in (a, b, d):
            i.svc.stop()


def _records():
    return [{'event': 'net.call_attempt', 'ts': '2026-10-07T10:00:03Z', 'actor': {'user': 'alice'},
             'details': {'net': NET, 'name': 'lookup', 'trace_id': 't1', 'attempt': 1, 'host': 'open-na',
                         'qualified_name': f'{NET}__open-na__lookup', 'outcome': 'answered', 'user': 'alice'}},
            {'event': 'net.host_refused', 'ts': '2026-10-07T10:00:02Z', 'actor': {'user': 'bob@open-na'},
             'details': {'net': NET, 'peer': 'open-na', 'tool': 'var_calc', 'trace_id': 't2', 'outcome': 'blocked',
                         'home': 'open-na', 'user': 'bob@open-na'}}]


def test_views_on_a_running_net(net3):
    from sajha.net.integration import pages
    a, b, d = net3
    m = pages.blocks_page(NET)
    assert m['available'] and m['instances'][0] == 'open-eu' and set(m['instances']) == {'open-eu', 'open-na', 'open-ap'}
    assert all(cell['state'] in ('allowed', 'self') for r in m['matrix'] for cell in r['cells'])
    rv = pages.reviews_view(NET)
    assert rv['net'] == NET and isinstance(rv['items'], list)
    act = pages.activity_view(NET, records=_records())
    assert [c['trace_id'] for c in act['calls']] == ['t1', 't2']
    assert act['calls'][0]['from'] == 'open-eu' and act['calls'][0]['to'] == 'open-na'
    assert act['calls'][1]['from'] == 'open-na' and not act['calls'][1]['ok']
    assert [c['trace_id'] for c in pages.activity_view(NET, outcome='refused', records=_records())['calls']] == ['t2']
    assert pages.activity_view(NET, since='2026-10-07T10:00:02Z', records=_records())['calls'][0]['trace_id'] == 't1'
    tr = pages.trace_view('t1', records=_records())
    assert len(tr['records']) == 1 and tr['others'][0]['instance'] == 'open-na'
    assert tr['others'][0]['url'].endswith('/admin/sajhanet/activity?trace=t1')
    det = pages.instance_admin(NET, 'open-na', records=_records())
    assert det['traffic']['to'] == 1 and det['traffic']['from'] == 1
    assert any(t['tool'] == 'lookup' for t in det['tools_in']) and 'var_calc' in det['tools_out']
    st = pages.settings_view()
    assert st['enabled'] and st['nets'][0]['net'] == NET and st['nets'][0]['gossip']['level'] in ('ok', 'warn')
    assert pages.certificates_view()['nets'][0]['admission'] == 'open'
    assert pages.keys_page(NET)['available']
    assert pages.users_page(NET)['available']


def test_block_with_blast_radius_history_and_undo(net3, web):
    from sajha.net.integration import changes
    a, b, d = net3
    br = changes.blast_radius(NET, 'block_add', {'level': 'outbound', 'target_instance': 'open-na'}, records=_records())
    assert br['local_tools'] >= 1 and br['local_users'] == 1 and 'open-na' in br['words']
    br = changes.blast_radius(NET, 'block_add', {'level': 'inbound', 'target_instance': 'open-na'}, records=_records())
    assert br['remote_tools'] >= 1 and 'open-na' in br['words']

    c, admin = web
    base = f'/api/sajhanet/nets/{NET}'
    body = {'level': 'instance', 'target_instance': 'open-ap', 'reason': 'maintenance'}
    assert c.post(f'{base}/blocks', cookies=admin, json=body).status_code == 403            # no CSRF token
    r = c.post(f'{base}/blocks', cookies=admin, json=body, headers=csrf_header(admin))
    assert r.status_code == 200, r.text
    bid = r.json()['id']
    assert c.get(f'{base}/blast-radius?kind=block_add&level=instance&target_instance=open-na',
                 cookies=admin).json()['kind'] == 'block_add'
    hist = c.get(f'{base}/changes', cookies=admin).json()['changes']
    assert hist[0]['kind'] == 'block_add' and hist[0]['reason'] == 'maintenance' and hist[0]['undo']['kind'] == 'block_remove'
    assert c.get(f'{base}/changes?instance=open-ap', cookies=admin).json()['changes'][0]['id'] == hist[0]['id']
    mx = c.get(f'{base}/access-matrix', cookies=admin).json()
    row = next(x for x in mx['matrix'] if x['caller'] == 'open-ap')
    assert next(cl for cl in row['cells'] if cl['host'] == 'open-eu')['state'] == 'blocked'
    # the pages show it
    page = c.get(f'/admin/sajhanet/blocks?net={NET}', cookies=admin).text
    assert 'maintenance' in page and 'blocked entirely' in page
    page = c.get(f'/admin/sajhanet/changes?net={NET}', cookies=admin).text
    assert 'maintenance' in page and '/undo' in page
    # undo: a reason is required; then the block is gone and the undo is itself recorded
    url = f'{base}/changes/{hist[0]["id"]}/undo'
    assert c.post(url, cookies=admin, json={}, headers=csrf_header(admin)).status_code == 400
    r = c.post(url, cookies=admin, json={'reason': 'done early'}, headers=csrf_header(admin))
    assert r.status_code == 200, r.text
    assert not [x for x in a.svc.authz.blocks_view(NET)['blocks'] if x['id'] == bid]
    hist = c.get(f'{base}/changes', cookies=admin).json()['changes']
    assert hist[0]['kind'] == 'block_remove' and hist[0]['undo_of'] == hist[1]['id'] and hist[1]['undone_at']
    assert c.post(url, cookies=admin, json={'reason': 'again'}, headers=csrf_header(admin)).status_code == 409
    # undoing the undo puts the block back (with a new id)
    r = c.post(f'{base}/changes/{hist[0]["id"]}/undo', cookies=admin, json={'reason': 'redo'}, headers=csrf_header(admin))
    assert r.status_code == 200
    assert [x for x in a.svc.authz.blocks_view(NET)['blocks'] if x['target_instance'] == 'open-ap' and x['level'] == 'instance']


def test_links_role_maps_name_matching_and_trust_undo(net3):
    from sajha.net.integration import changes
    a, b, d = net3
    a.user('carol')
    a.user('dave')
    changes.perform(NET, 'link', {'remote_user': 'carol@open-na', 'local_user': 'carol'}, 'admin', 'same person')
    changes.perform(NET, 'link', {'remote_user': 'carol@open-na', 'local_user': 'dave'}, 'admin', 'reassigned')
    h = changes.history(NET)
    assert h[0]['undo'] == {'kind': 'link', 'params': {'remote_user': 'carol@open-na', 'local_user': 'carol'}}
    changes.undo(NET, h[0]['id'], 'admin', 'wrong account')
    assert a.svc.authz.users_view(NET)['links']['carol@open-na']['local'] == 'carol'
    changes.perform(NET, 'role_map', {'instance': 'open-na', 'map': {'analyst': ['user']}}, 'admin', 'guests')
    changes.undo(NET, changes.history(NET)[0]['id'], 'admin', 'no guests')
    assert 'open-na' not in a.svc.authz.users_view(NET)['role_maps']
    changes.perform(NET, 'name_matching', {'instance': 'open-na', 'on': False}, 'admin', 'name clash')
    assert 'open-na' in a.svc.authz.users_view(NET)['no_name_match']
    changes.undo(NET, changes.history(NET)[0]['id'], 'admin', 'resolved')
    assert 'open-na' not in a.svc.authz.users_view(NET)['no_name_match']
    changes.perform(NET, 'trust', {'peer': 'open-na', 'trust': 'review'}, 'admin', 'audit their tools')
    assert a.svc.catalogs.trust_of(NET, 'open-na')[0] == 'review'
    changes.undo(NET, changes.history(NET)[0]['id'], 'admin', 'audited')
    assert a.svc.catalogs.trust_of(NET, 'open-na')[0] == 'auto'
    # a final change is recorded but cannot be undone
    changes.perform(NET, 'resync', {}, 'admin', 'after an incident')
    from sajha.net.integration import ServiceError
    with pytest.raises(ServiceError) as e:
        changes.undo(NET, changes.history(NET)[0]['id'], 'admin', 'no')
    assert e.value.status == 409
    # a caller that arrived through the net changes nothing
    with pytest.raises(ServiceError) as e:
        changes.perform(NET, 'unlink', {'remote_user': 'carol@open-na'}, 'admin@open-na', 'x', by_auth_type='sajhanet')
    assert e.value.status == 403


def test_pages_and_instance_tabs_on_a_running_net(net3, web):
    a, b, d = net3
    c, admin = web
    for url in PAGES:
        r = c.get(f'{url}?net={NET}', cookies=admin)
        assert r.status_code == 200, (url, r.text[:300])
    assert 'open-na' in c.get(f'/admin/sajhanet/blocks?net={NET}', cookies=admin).text
    assert 'open-eu' in c.get('/admin/sajhanet/settings', cookies=admin).text
    for tab in ('tools', 'traffic', 'users', 'keys', 'blocks', 'history'):
        r = c.get(f'/net/instances/{NET}/open-na?tab={tab}', cookies=admin)
        assert r.status_code == 200 and 'Instance tabs' in r.text and 'aria-current="page">' in r.text, tab
    assert 'Block entirely' in c.get(f'/net/instances/{NET}/open-na?tab=blocks', cookies=admin).text
    j = c.get(f'/api/sajhanet/nets/{NET}/instances/open-na/detail', cookies=admin).json()
    assert j['instance'] == 'open-na' and 'traffic' in j
    assert c.get(f'/api/sajhanet/nets/{NET}/users/by-instance', cookies=admin).json()['available']


def test_snapshot_pages_compare_download_and_restore_plan(web, tmp_path, monkeypatch):
    from sajha.snapshots import SnapshotService, SnapshotSettings
    import sajha.snapshots as S
    st = SnapshotSettings.from_config()
    st.dir = str(tmp_path / 'snaps')
    svc = SnapshotService(settings=st, registry_getter=lambda: None)
    svc.take(actor='test', reason='test')
    svc.take(actor='test', reason='test')
    monkeypatch.setattr(S, '_service', svc)
    c, admin = web
    j = c.get('/api/sajhanet/snapshots', cookies=admin).json()
    assert len(j['snapshots']) == 2 and j['ok'] is True and j['snapshots'][0]['chain'] == 'verified'
    names = [s['name'] for s in j['snapshots']]
    d = c.get(f'/api/sajhanet/snapshots/diff?a={names[0]}&b={names[1]}', cookies=admin).json()
    assert d['a'] == names[0] and isinstance(d['lines'], list)
    r = c.get(f'/api/sajhanet/snapshots/{names[1]}/download', cookies=admin)
    assert r.status_code == 200 and r.json()['snapshot']['seq'] == 2
    assert c.get('/api/sajhanet/snapshots/nope/download', cookies=admin).status_code == 404
    url = f'/api/sajhanet/snapshots/{names[1]}/restore'
    assert c.post(url, cookies=admin, json={'dry_run': True}).status_code == 403
    plan = c.post(url, cookies=admin, json={'dry_run': True}, headers=csrf_header(admin))
    assert plan.status_code == 200 and plan.json()['dry_run'] is True
    assert c.post(url, cookies=admin, json={'confirm': 'wrong', 'reason': 'x'}, headers=csrf_header(admin)).status_code == 400
    assert c.post(url, cookies=admin, json={'confirm': names[1]}, headers=csrf_header(admin)).status_code == 400
    page = c.get('/admin/sajhanet/snapshots', cookies=admin).text
    assert names[1] in page and 'verified' in page
