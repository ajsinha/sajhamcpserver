# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The SAJHA Net console of phase 5.2 (design §17.5): the Net overview (admin), Your net access (every
signed-in user), the pins view behind the admission panel, and the pages with SAJHA Net off and with a
running open-mode net of three.
"""

from tests.net.test_net_three_instances import NET, Instance, Who, _open, isolate, settle  # noqa: F401
from tests.net.test_net_integration import ClientConnector


# ── SAJHA Net off: a net of one ─────────────────────────────────────

def test_overview_and_access_pages_with_sajha_net_off(web):
    c, admin = web
    page = c.get('/admin/sajhanet/overview', cookies=admin)
    assert page.status_code == 200 and 'Net overview' in page.text and 'net of one' in page.text
    assert 'class="page-help"' in page.text
    j = c.get('/api/sajhanet/overview', cookies=admin).json()
    assert j['enabled'] is False and j['net'] is None and j['nets']
    page = c.get('/net/access', cookies=admin)
    assert page.status_code == 200 and 'Your net access' in page.text and 'no remote tools' in page.text
    j = c.get('/api/sajhanet/access', cookies=admin).json()
    assert j['enabled'] is False and j['local_usable'] >= 1 and j['nets'][0]['tools'] == []
    assert c.get('/api/sajhanet/nets/default/pins', cookies=admin).status_code == 503


def test_overview_is_admin_only_and_access_needs_sign_in(web):
    c, admin = web
    for url in ('/admin/sajhanet/overview', '/net/access'):
        assert c.get(url, follow_redirects=False).status_code in (302, 303, 401, 403)
    for url in ('/api/sajhanet/overview', '/api/sajhanet/access'):
        assert c.get(url).status_code in (401, 403)


def test_menu_lists_the_new_pages(web):
    c, admin = web
    page = c.get('/dashboard', cookies=admin).text
    assert '/net/access' in page and '/admin/sajhanet/overview' in page


# ── a running net ───────────────────────────────────────────────────

class _User:
    """A signed-in user whom this server lets use every tool (``_may_use``'s rule)."""
    authenticated = True
    auth_type = 'session'
    is_admin = True
    roles = ['user']
    user_id = 'alice'

    def has_tool_access(self, name):
        return True


def _records():
    """Audit records as the chain exports them: a home call, a host call, a chain refusal, residency."""
    return [
        {'event': 'net.call_attempt', 'ts': '2026-10-07T10:00:03Z', 'actor': {'user': 'alice'},
         'details': {'net': NET, 'name': 'lookup', 'trace_id': 't1', 'attempt': 2, 'host': 'open-ap',
                     'qualified_name': f'{NET}__open-ap__lookup', 'outcome': 'answered', 'executed': True}},
        {'event': 'net.host_refused', 'ts': '2026-10-07T10:00:02Z', 'actor': {'user': 'bob'},
         'details': {'net': NET, 'peer': 'open-na', 'tool': 'var_calc', 'trace_id': 't2', 'outcome': 'loop',
                     'executed': False, 'home': 'open-na'}},
        {'event': 'net.residency', 'ts': '2026-10-07T10:00:01Z', 'actor': {'user': 'alice'},
         'details': {'net': NET, 'instance': 'open-na', 'tool': 'lookup', 'flow': 'arguments',
                     'data_classes': ['eu-personal'], 'outcome': 'refused', 'rule': 'eu-stays', 'side': 'home',
                     'trace_id': 't3'}},
        {'event': 'net.call_attempt', 'ts': '2026-10-07T10:00:00Z',
         'details': {'net': 'other-net', 'name': 'x', 'outcome': 'answered'}},
    ]


def test_overview_and_access_of_an_open_net(tmp_path, isolate, web):
    from sajha.net.integration import set_service
    from sajha.net.integration.overview import access_view, overview_view
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
        v = overview_view(NET, records=_records())
        n = v['net']
        assert v['enabled'] and v['nets'] == [NET] and n['instance'] == 'open-eu'
        assert {m['name']: m['state'] for m in n['members']} == {'open-na': 'alive', 'open-ap': 'alive'}
        assert n['counts']['alive'] == 2 and n['gossip']['level'] == 'ok'
        assert n['admission'] == 'open'
        assert {k['instance'] for k in n['admission_detail']['first_use']} >= {'open-na', 'open-ap'}
        assert n['remote_tools'].get('active', 0) >= 2 and n['quarantined'] == [] and n['held'] == []
        assert [x['name'] for x in n['fallback_topology']['nodes']][0] == 'open-eu'
        act = n['activity']
        assert [c['trace_id'] for c in act['calls']] == ['t1', 't2']             # the other net's record is left out
        assert act['calls'][0]['side'] == 'home' and act['calls'][1]['side'] == 'host'
        assert [c['outcome'] for c in act['chain_refusals']] == ['loop']
        assert act['residency']['by_flow'] == {'arguments': {'refused': 1}}
        assert act['residency']['recent'][0]['rule'] == 'eu-stays'

        acc = access_view(_User())
        tools = {t['name']: t for t in acc['nets'][0]['tools']}
        assert set(tools['lookup']['hosts'][i]['instance'] for i in range(2)) == {'open-na', 'open-ap'}
        assert tools['lookup']['usable_hosts'] == 2 and all(h['usable'] for h in tools['lookup']['hosts'])
        assert tools['lookup']['alias'] == 'lookup'
        assert [h['order'] for h in tools['lookup']['hosts']] == [0, 1]
        assert access_view(None)['nets'][0]['usable'] == 0                       # nobody signed in: nothing

        # the pages and the pins view on the running net
        c, admin = web
        page = c.get(f'/admin/sajhanet/overview?net={NET}', cookies=admin)
        assert page.status_code == 200 and 'open-na' in page.text and 'data-sn-topology' in page.text
        assert 'data-mode="open"' in page.text and 'Recent forwarded calls' in page.text
        assert c.get('/admin/sajhanet', cookies=admin).text.count('data-sn-admission') == 1
        pins = c.get(f'/api/sajhanet/nets/{NET}/pins', cookies=admin).json()
        assert pins == {'net': NET, 'admission': 'open', 'configured': [], 'runtime': []}
        assert c.get('/api/sajhanet/nets/nowhere/pins', cookies=admin).status_code == 404
        assert c.get('/net/access', cookies=admin).status_code == 200
    finally:
        for i in (a, b, d):
            i.svc.stop()
