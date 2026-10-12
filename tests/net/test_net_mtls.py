# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Mutual TLS between participants (``sajhanet.mtls``; sajha/net/integration/mtls.py).

Covers: ``require`` refuses a net request without a verified TLS client certificate, or with one that is not
the leaf of its ``Sajha-Net-Certificate``, with an unsigned 401 before the net sees it, at ``/sajhanet/`` and
at the MCP endpoint; enrollment and non-net requests are exempt; ``client`` and ``require`` present the
instance certificate of the request's net as the TLS client certificate on outbound requests, with the key
held only in the TLS context; the mode's spellings.
"""

from __future__ import annotations

import base64
import json
import ssl
from urllib.parse import quote

from fastapi.testclient import TestClient

from sajha.net import crypto, httpsig
from sajha.net.integration import mtls
from tests.net.test_net_routing_integration import NET, net3, node  # noqa: F401
from tests.net.test_net_streaming import stream_app_for


def ping_headers(svc, to, body):
    n = node(svc)
    return httpsig.sign_request(n.signer, 'POST', '/sajhanet/v1/gossip/ping', '', {'content-type': 'application/json'},
                                body, NET, n.name, to, now=n.clock())


def test_modes():
    assert [mtls.mode_of(v) for v in ('off', '', 'false', 'client', 'require', 'true', 'bogus')] == \
        ['off', 'off', 'off', 'client', 'require', 'require', 'off']


def test_inbound_check(net3):
    a, b = net3['risk-eu'], net3['cust-na']
    body = b'{"type":"ping","seq":1,"updates":[]}'
    h = httpsig.lower_headers(ping_headers(a, 'cust-na', body))
    leaf = node(a).signer.chain[0]
    path = '/sajhanet/v1/gossip/ping'
    assert mtls.inbound_problem('client', path, h) is None                       # only require checks
    assert 'did not come with' in mtls.inbound_problem('require', path, h)
    ok = dict(h, **{mtls.DEFAULT_HEADER: quote(crypto.cert_pem(leaf).decode())})  # nginx $ssl_client_escaped_cert
    assert mtls.inbound_problem('require', path, ok) is None
    der = dict(h, **{mtls.DEFAULT_HEADER: base64.b64encode(crypto.cert_der(leaf)).decode()})
    assert mtls.inbound_problem('require', path, der) is None
    other = dict(h, **{mtls.DEFAULT_HEADER: quote(crypto.cert_pem(node(b).signer.chain[0]).decode())})
    assert 'not the certificate' in mtls.inbound_problem('require', path, other)
    assert 'cannot be read' in mtls.inbound_problem('require', path, dict(h, **{mtls.DEFAULT_HEADER: 'junk'}))
    assert mtls.inbound_problem('require', '/sajhanet/v1/ca/enroll', h) is None   # a newcomer has no certificate
    assert mtls.inbound_problem('require', '/mcp', {'content-type': 'application/json'}) is None


def test_require_refuses_at_both_endpoints(net3):
    a, b = net3['risk-eu'], net3['cust-na']
    b.shared.mtls = 'require'
    client = TestClient(stream_app_for(b), base_url='https://cust-na.test')
    body = b'{"type":"ping","seq":1,"updates":[]}'
    h = ping_headers(a, 'cust-na', body)
    r = client.post('/sajhanet/v1/gossip/ping', content=body, headers=h)
    assert r.status_code == 401 and r.json()['reason'] == 'certificate_invalid'
    assert 'signature' not in {k.lower() for k in r.headers}                     # unsigned: refused before the net
    good = dict(h, **{mtls.DEFAULT_HEADER: quote(crypto.cert_pem(node(a).signer.chain[0]).decode())})
    assert TestClient(stream_app_for(b), base_url='https://cust-na.test').post(
        '/sajhanet/v1/gossip/ping', content=body, headers=good).status_code == 200
    raw = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}}).encode()
    n = node(a)
    mh = httpsig.sign_request(n.signer, 'POST', '/mcp', '', {'content-type': 'application/json'}, raw, NET, n.name,
                              'cust-na', mcp=True, now=n.clock())
    r = client.post('/mcp', content=raw, headers=mh)
    assert r.status_code == 401 and r.json()['reason'] == 'certificate_invalid'
    good = dict(mh, **{mtls.DEFAULT_HEADER: quote(crypto.cert_pem(n.signer.chain[0]).decode())})
    assert client.post('/mcp', content=raw, headers=good).status_code == 200


def test_outbound_presents_the_instance_certificate_of_the_net(net3, monkeypatch):
    a = net3['risk-eu']
    made = []

    class Resp:
        status_code, headers, content = 200, {'x': '1'}, b'{}'

    class Client:
        def __init__(self, **kw):
            made.append(kw)

        def request(self, *args, **kw):
            return Resp()

        def close(self):
            pass
    import httpx
    monkeypatch.setattr(httpx, 'Client', Client)
    loaded = []
    real = ssl.SSLContext.load_cert_chain

    def spy(self, path, *args, **kw):
        loaded.append(path)
        return real(self, path, *args, **kw)
    monkeypatch.setattr(ssl.SSLContext, 'load_cert_chain', spy)
    c = mtls.MtlsConnector(a._mtls_identity)
    r = c.send('POST', 'https://cust-na.test/sajhanet/v1/gossip/ping', {'Sajha-Net-Name': NET}, b'{}', 5)
    assert r.status == 200
    assert isinstance(made[-1]['verify'], ssl.SSLContext)
    import os
    assert loaded and not os.path.exists(loaded[-1])                          # the key file is gone at once
    c.send('POST', 'https://cust-na.test/x', {'sajha-net-name': NET}, b'{}', 5)
    assert len(made) == 1                                                      # one pool per peer and net
    c.send('POST', 'https://cust-na.test/x', {'sajha-net-name': 'no-such-net'}, b'{}', 5)
    assert made[-1]['verify'] is True                                          # no identity there: no client cert
    # the service builds it for client and require
    from sajha.net.integration import SajhaNetService
    from sajha.net.integration.config import Shared
    svc = SajhaNetService(Shared(enabled=True, mtls='client'), [], {})
    assert isinstance(svc.connector, mtls.MtlsConnector)
    assert not isinstance(SajhaNetService(Shared(enabled=True), [], {}).connector, mtls.MtlsConnector)
