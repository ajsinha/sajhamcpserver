"""SAJHA Net is off by default: every /sajhanet/ path is a bare 404 (protocol §7.3, SIG-15)."""


def test_disabled_by_default(web):
    c, admin = web
    for method in ('GET', 'POST'):
        r = c.request(method, '/sajhanet/v1/gossip/ping', headers={'Sajha-Net-Name': 'default'})
        assert r.status_code == 404 and r.content == b''
    st = c.get('/api/sajhanet/status', cookies=admin).json()
    assert st['enabled'] is False and st['nets'] == []
    page = c.get('/admin/sajhanet', cookies=admin)
    assert page.status_code == 200 and 'sajhanet.enabled' in page.text
