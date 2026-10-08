# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The SAJHA Net console pages (design §17.1, §17.2) on a SAJHA with SAJHA Net off: this server is always
listed as a net of one, the navbar badge names it, the Instances pages are for every signed-in user and
read-only, the Remote tools page is for administrators. The pages with a running net are exercised in
tests/net/test_net_three_instances.py.
"""

from urllib.parse import quote


def test_instances_page_lists_this_server_as_a_net_of_one(web):
    c, admin = web
    r = c.get('/net/instances', cookies=admin)
    assert r.status_code == 200
    assert 'a net of one' in r.text and 'this server' in r.text and 'class="page-help"' in r.text
    assert 'sajha-net-badge' in r.text and 'Net · ' in r.text                    # the navbar badge
    data = c.get('/api/sajhanet/instances', cookies=admin).json()
    assert data['enabled'] is False
    me = data['nets'][0]['instances'][0]
    assert me['self'] and me['state'] == 'alive' and me['kind'] == 'sajha' and me['tools_usable'] >= 1


def test_this_instance_page_shows_its_tools_with_try_it(web):
    c, admin = web
    page = c.get('/net/instances/this', cookies=admin)
    assert page.status_code == 200 and 'Try it' in page.text and '/execute' in page.text
    me = c.get('/api/sajhanet/instances', cookies=admin).json()['nets'][0]
    net, inst = me['net'], me['instances'][0]['name']
    assert c.get(f'/net/instances/{quote(net, safe="")}/{quote(inst, safe="")}', cookies=admin).status_code == 200
    j = c.get(f'/api/sajhanet/instances/{net}/{inst}', cookies=admin).json()
    assert j['instance']['self'] and j['tools'] and all(t['try_it'] for t in j['tools'])
    assert c.get('/net/instances/no-such-net/nobody', cookies=admin).status_code == 404


def test_pages_need_sign_in_and_remote_tools_is_admin_only(web):
    c, admin = web
    assert c.get('/api/sajhanet/instances').status_code in (401, 403)
    r = c.get('/net/instances', follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)
    page = c.get('/admin/sajhanet/tools', cookies=admin)
    assert page.status_code == 200 and 'Host and tool table' in page.text and 'No tool is quarantined' in page.text
    r = c.get('/admin/sajhanet/tools', follow_redirects=False)
    assert r.status_code in (302, 303, 401, 403)


def test_navigation_has_instances_for_every_signed_in_user(web):
    c, admin = web
    page = c.get('/dashboard', cookies=admin)
    assert '/net/instances' in page.text and '/admin/sajhanet/tools' in page.text
