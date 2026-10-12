# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Visibility (protocol §6.2 ``visibility``, §10.5; CAT-05; design §11.3).

Host: ``POST /sajhanet/v1/catalog/visibility`` lists, per key id of the requester's own records, the tools
exported to it that the key's user (mapped as for a call) may call; keys of another home or unknown ids get
``not_home``; a user without an account gets ``no_account``; a blocked user ``blocked``; export rules and tool
blocks narrow the list. Home: ``tools/list`` hides a host's proxies the host says the caller may not call,
and hides nothing when the host does not know the key as this server's or cannot be asked.
"""

from __future__ import annotations

from sajha.net import EXTENSION_ID
from sajha.net.integration import authz as az
from tests.net.test_net_identity import NET, fab, sync  # noqa: F401
from tests.net.test_net_routing_integration import net3, node, settle  # noqa: F401


class Book:
    """The catalog surface the visibility answer reads: the tools exported to a peer."""

    def __init__(self, tools):
        self.tools = tools

    def exports(self, peer):
        return [{'name': t} for t in self.tools]

    def tool_names(self, tool):
        return [tool]


def ask(frm, to, key_ids):
    x = frm.node.request(f'https://{to.name}.test', '/sajhanet/v1/catalog/visibility', {'key_ids': key_ids},
                         to.name)
    return x.body['visibility']


def test_cat_05_visibility_per_key(fab, monkeypatch):
    monkeypatch.setattr('sajha.auth.access.policy_for', lambda auth: type('P', (), {
        'can_execute': lambda self, tool: not (tool == 'admin_tool' and 'admin' not in auth.roles)})())
    a, b, c = fab.a, fab.b, fab.c
    assert 'visibility' in b.node.features
    assert 'visibility' in a.node.member('cust-na')['record']['features']
    b.node.catalog = Book(['var_calc', 'lookup', 'wire_send', 'admin_tool'])
    a.user('alice')
    b.user('alice')
    a.user('carol')                                       # no account at cust-na
    a.user('dave')
    b.user('dave')
    c.user('erin')
    alice, _ = a.key('alice')
    carol, _ = a.key('carol')
    dave, _ = a.key('dave')
    erin, _ = c.key('erin')
    sync(fab)
    b.authz.add_block(NET, 'tool', '*', 'secret', tool='wire_*', by='admin')
    b.authz.add_block(NET, 'user', '', 'abuse', user='dave@risk-eu', by='admin')
    v = ask(a, b, [alice, carol, dave, erin, 'no-such-key'])
    assert v[alice] == {'tools': ['var_calc', 'lookup']}             # wire_* blocked, admin_tool not allowed
    assert v[carol] == {'tools': [], 'reason': 'no_account'}
    assert v[dave] == {'tools': [], 'reason': 'blocked'}
    assert v[erin] == {'tools': [], 'reason': 'not_home'}             # a key of treasury-na, asked by risk-eu
    assert v['no-such-key'] == {'tools': [], 'reason': 'not_home'}
    # treasury-na may ask about its own key
    assert ask(c, b, [erin])[erin]['reason'] == 'no_account'


def test_cat_05_export_rules_narrow_the_list(fab):
    a, b = fab.a, fab.b
    b.st.settings.export = [{'tools': ['lookup']}]
    b.node.catalog = Book(['var_calc', 'lookup'])
    a.user('alice')
    b.user('alice')
    alice, _ = a.key('alice')
    sync(fab)
    assert ask(a, b, [alice])[alice] == {'tools': ['lookup']}


def test_visibility_off_is_404(fab):
    b = fab.b
    b.node.extra_features.remove('visibility')
    r = fab.n.connector                                   # CAP-05: a feature not listed answers 404
    from sajha.net import httpsig
    import json
    body = json.dumps({'key_ids': ['x']}).encode()
    h = httpsig.sign_request(fab.a.node.signer, 'POST', '/sajhanet/v1/catalog/visibility', '',
                             {'content-type': 'application/json'}, body, NET, 'risk-eu', 'cust-na',
                             now=fab.a.node.clock())
    resp = r.send('POST', 'https://cust-na.test/sajhanet/v1/catalog/visibility', h, body, 5)
    assert resp.status == 404 and resp.body == b''


def test_settings_default_on():
    assert az.NetAuthSettings().visibility is True


def test_home_hides_what_the_host_says_the_caller_may_not_call(net3, monkeypatch):
    from sajha.net.integration import get_service, set_service
    from sajha.net.integration import catalogs as cat_mod
    a, b, conn = net3['risk-eu'], net3['cust-na'], net3['conn']
    node(b).extra_features.append('visibility')
    node(b).refresh_record()
    settle([a, b, net3['treasury-na']], 4)
    assert 'visibility' in node(a).member('cust-na')['record']['features']
    monkeypatch.setattr(cat_mod, '_caller_user', lambda net_hint='': {'user_id': 'alice', 'roles': ['user'],
                                                                      'authenticated': True, 'net': ''})
    a.authz.key_for = lambda user: ('raw-key', 'kid-alice')
    answers = {'cust-na': {'tools': ['lookup']}}
    monkeypatch.setattr(a.catalogs, '_visibility', lambda book, m, kid: answers.get(m['name']))
    old = get_service()
    set_service(a)
    try:
        names = {t['name'] for t in cat_mod.listed(a.tools_registry.get_all_tools())}
        assert 'acme-net__cust-na__lookup' in names
        assert 'acme-net__cust-na__var_calc' not in names                 # not callable there for alice
        assert 'acme-net__treasury-na__var_calc' in names                 # treasury-na does not list visibility
        assert 'lookup' in names                                          # an alias: visible through any host
        answers['cust-na'] = {'tools': [], 'reason': 'no_account'}
        names = {t['name'] for t in cat_mod.listed(a.tools_registry.get_all_tools())}
        assert not any(n.startswith('acme-net__cust-na__') for n in names)
        answers['cust-na'] = {'tools': [], 'reason': 'not_home'}          # advice that does not apply: fail open
        names = {t['name'] for t in cat_mod.listed(a.tools_registry.get_all_tools())}
        assert 'acme-net__cust-na__var_calc' in names
        answers['cust-na'] = None                                         # the host could not be asked
        names = {t['name'] for t in cat_mod.listed(a.tools_registry.get_all_tools())}
        assert 'acme-net__cust-na__var_calc' in names
    finally:
        set_service(old)
    assert all(t['_meta'][EXTENSION_ID]['locality'] == 'remote' for t in a.tools_registry.get_all_tools()
               if t['name'].startswith('acme-net__'))
