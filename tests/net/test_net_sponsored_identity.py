# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Sponsored members with the ``assertion`` and ``token_exchange`` identities (SAJHA Net §5.1; protocol §15.5,
§15.9).

A sponsored participant takes its sponsor's resolvers for the net, with itself as the receiver: an assertion
must name it as the audience (one for the sponsor is refused), a token is exchanged at its own token endpoint
and is valid only for it, and a custom resolver of the sponsor is not offered.
"""

from __future__ import annotations

import pytest

from sajha.federation.tool import FederatedTool
from sajha.net import EXTENSION_ID
from tests.net.test_net_mixed_conformance import FakeFederation
from tests.net.test_net_reexport_identity import M, PERMS, Capture, Peer, Who, decode, join, settle, start
from tests.net.test_net_three_instances import as_user, isolate  # noqa: F401

SEARCH = 'acme-net__vendor-search__search'


def sponsored_pair(tmp_path, ids):
    conn = Capture()
    fed = FakeFederation()
    search = FederatedTool(fed, 'vendor', 'search', {
        'name': 'vendor__search', 'description': 'Search the vendor index',
        'inputSchema': {'type': 'object', 'properties': {'q': {'type': 'string'}}},
        'annotations': {'readOnlyHint': True}})
    b = Peer(tmp_path, 'cust-na', conn, [Who('lookup', owner='cust-na'), search], [(M, True, [])],
             auth={M: {'user_identity': ids}})
    b.svc.sponsored_config = [{'net': M, 'instance_name': 'vendor-search', 'upstream': 'vendor',
                               'vendor': 'vendorco'}]
    a = Peer(tmp_path, 'risk-eu', conn, [Who('var_calc', owner='risk-eu')], [(M, False, ['https://cust-na.test'])],
             auth={M: {'user_identity': ids}})
    start(b, a)
    join(b, [a])
    tools = PERMS + ',vendor__search,search,' + SEARCH
    for p in (a, b):
        p.user('alice', roles=('analyst',), tools=tools)
    kid, raw = a.key('alice')
    settle([a, b], 8)
    from sajha.net.integration import set_service
    set_service(a.svc)
    sp = a.n().member('vendor-search')
    assert sp is not None and sp['record'].get('kind') == 'sponsored'
    return conn, a, b, fed, kid, raw


def sent_to_sponsored(conn):
    return [h for _u, h in conn.sent if h.get('sajha-net-to') == 'vendor-search']


def test_sponsored_member_accepts_an_assertion_for_itself(tmp_path, isolate):
    conn, a, b, fed, kid, raw = sponsored_pair(tmp_path, 'assertion')
    assert a.n().member('vendor-search')['record']['user_identity'] == ['assertion']
    r = as_user('alice', raw, kid, lambda: a.reg.get_tool(SEARCH).execute_with_tracking({'q': 'bonds'}))
    assert r['content'][0]['text'] == 'vendor:search:bonds', r
    h = sent_to_sponsored(conn)[-1]
    doc = decode(h['sajha-net-user-assertion'])
    assert doc['aud'] == 'vendor-search' and doc['key_id'] == kid and 'sajha-net-api-key' not in h
    # an assertion for the sponsor is not accepted by the sponsored member
    from sajha.net.integration.identity import make_assertion
    from sajha.net.errors import NetError
    from sajha.net.integration.sponsored import _Identity
    wrong = make_assertion(a.svc.authz, M, {'user_id': 'alice', 'key_id': kid, 'authenticated': True}, 'cust-na', None)
    with pytest.raises(NetError) as e:
        _Identity(b.svc.authz.identity, 'vendor-search').resolve(
            {'sajha-net-name': M, 'sajha-net-user-assertion': wrong}, 'risk-eu', hop=1, visited=[f'{M}/risk-eu'])
    assert e.value.reason == 'assertion_invalid' and 'not vendor-search' in e.value.detail, e.value.detail
    for p in (a, b):
        p.svc.stop()


def test_sponsored_member_serves_token_exchange(tmp_path, isolate):
    conn, a, b, fed, kid, raw = sponsored_pair(tmp_path, 'token_exchange')
    rec = a.n().member('vendor-search')['record']
    assert 'token_exchange' in rec['features'] and rec['user_identity'] == ['token_exchange']
    tx = a.svc.authz.identity.resolvers['token_exchange']
    call = lambda: as_user('alice', raw, kid, lambda: a.reg.get_tool(SEARCH).execute_with_tracking({'q': 'x'}))  # noqa
    assert call()['content'][0]['text'] == 'vendor:search:x'
    assert call()['content'][0]['text'] == 'vendor:search:x'
    assert tx.exchanges == 1
    tok = sent_to_sponsored(conn)[-1]['sajha-net-user-token']
    # the token is for the sponsored member only: the sponsor itself does not take it
    from sajha.net.errors import NetError
    with pytest.raises(NetError) as e:
        b.svc.authz.identity.resolve({'sajha-net-name': M, 'sajha-net-user-token': tok}, 'risk-eu')
    assert e.value.reason == 'token_invalid'
    assert fed.calls == [('search', {'q': 'x'}), ('search', {'q': 'x'})]
    assert (call().get('_meta') or {}).get(EXTENSION_ID, {}).get('instance') == 'vendor-search'
    for p in (a, b):
        p.svc.stop()
