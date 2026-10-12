# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Forwarding on the 2025-11-25 era (protocol §6.4; CALL-12).

Covers: a signed ``initialize`` creates a session bound to the net and the participant that sent it; the
same participant's signed requests may use it; another participant's signed request presenting it, or an
unknown session id, gets ``404 session_invalid`` and the tool does not run (CALL-12); a host that does not
serve 2026-07-28 answers ``-32022`` and the home forwards on 2025-11-25 instead, on one session per
(net, home, host), without streaming; a session the host forgot is replaced once.
"""

from __future__ import annotations

import json

from sajha.net import EXTENSION_ID, httpsig, sfv
from sajha.net.routing import LEGACY, MODERN, SESSION_KEY
from tests.net.test_net_routing_integration import NET, net3, node  # noqa: F401


def signed(frm, to, body, conn, extra=None, version=None):
    n = node(frm)
    raw = json.dumps(body).encode()
    h = {'content-type': 'application/json', 'mcp-method': body['method'],
         'sajha-net-hop': '1', 'sajha-net-visited': sfv.ser_list([(f'{NET}/{n.name}', {})])}
    if version:
        h['mcp-protocol-version'] = version
    h.update(extra or {})
    s = httpsig.sign_request(n.signer, 'POST', '/mcp', '', h, raw, NET, n.name, to, mcp=True, now=n.clock())
    return conn.send('POST', f'https://{to}.test/mcp', s, raw, 5)


def initialize(frm, to, conn):
    r = signed(frm, to, {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                         'params': {'protocolVersion': LEGACY, 'capabilities': {}}}, conn, version=LEGACY)
    assert r.status == 200, r.body
    res = json.loads(r.body)['result']
    assert EXTENSION_ID in res['capabilities']['experimental']                  # CAP-02
    return httpsig.lower_headers(r.headers)['mcp-session-id']


def call(frm, to, conn, sid):
    return signed(frm, to, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                            'params': {'name': 'lookup', 'arguments': {'x': 3}}}, conn,
                  extra={'mcp-session-id': sid}, version=LEGACY)


def test_call_12_a_session_is_bound_to_the_participant_that_created_it(net3):
    a, b, c, conn = net3['risk-eu'], net3['cust-na'], net3['treasury-na'], net3['conn']
    sid = initialize(a, 'cust-na', conn)
    assert node(b).kv.get(SESSION_KEY + sid) == {'net': NET, 'peer': 'risk-eu', 'created': node(b).kv.get(
        SESSION_KEY + sid)['created']}
    lookup = b.tools_registry.get_tool('lookup')
    r = call(a, 'cust-na', conn, sid)                                          # its creator may use it
    assert r.status == 200 and json.loads(r.body)['result']['content'][0]['text'] == 'cust-na:lookup:3'
    assert lookup.calls == 1
    r = call(c, 'cust-na', conn, sid)                                          # another participant may not
    err = json.loads(r.body)['error']
    assert r.status == 404 and err['data'][EXTENSION_ID]['reason'] == 'session_invalid'
    assert err['data'][EXTENSION_ID]['executed'] is False
    r = call(a, 'cust-na', conn, 'no-such-session')
    assert r.status == 404 and json.loads(r.body)['error']['data'][EXTENSION_ID]['reason'] == 'session_invalid'
    assert lookup.calls == 1                                                    # nothing else ran


def test_a_host_without_2026_07_28_is_called_on_2025_11_25(net3):
    a, b, conn = net3['risk-eu'], net3['cust-na'], net3['conn']
    b.catalogs.hosts[NET].eras = (LEGACY,)
    sent = []
    real = conn.send

    def spy(method, url, headers, body, timeout):
        if url.endswith('/mcp'):
            sent.append((dict(headers), json.loads(body)))
        return real(method, url, headers, body, timeout)
    conn.send = spy
    r = a.tools_registry.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 8})
    assert r['content'][0]['text'] == 'cust-na:lookup:8', r
    eras = [(h.get('mcp-protocol-version'), body['method']) for h, body in sent]
    assert eras == [(MODERN, 'tools/call'), (LEGACY, 'initialize'), (LEGACY, 'tools/call')]
    assert 'stream' not in sent[-1][1]['params']['_meta'][EXTENSION_ID]        # no streaming on that era
    sid = sent[-1][0]['mcp-session-id']
    # the next call goes straight to 2025-11-25 on the same session
    a.tools_registry.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 9})
    assert [(h.get('mcp-protocol-version'), h.get('mcp-session-id')) for h, _ in sent[3:]] == [(LEGACY, sid)]
    # the host forgets the session: the home opens a new one, once
    node(b).kv.delete(SESSION_KEY + sid)
    r = a.tools_registry.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 10})
    assert r['content'][0]['text'] == 'cust-na:lookup:10', r
    assert [body['method'] for _h, body in sent[4:]] == ['tools/call', 'initialize', 'tools/call']
    assert sent[-1][0]['mcp-session-id'] != sid
