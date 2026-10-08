# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net signatures and records (protocol §7, §8): SIG-01 to SIG-14, REC-01, REC-02, NET-01 to
NET-03, CAP-04 (version refusal), ERR-01 and LIM-01. §21.1 and §21.3 are test vectors.
"""

import base64
import hashlib
import json

import pytest

from sajha.net import crypto, httpsig, jcs, schemas, sfv
from sajha.net.errors import NetError
from sajha.net.models import MemoryKV
from sajha.net.node import Participant
from sajha.net.trust import CATrust
from tests.net.harness import T0, TestNet

CA_B64 = ('MIIBJjCB2aADAgECAgEBMAUGAytlcDApMREwDwYDVQQKDAhhY21lLW5ldDEUMBIGA1UEAwwLYWNtZS1uZXQgQ0EwHhcNMjYxMDAxMDAw'
          'MDAwWhcNMzYxMDAxMDAwMDAwWjApMREwDwYDVQQKDAhhY21lLW5ldDEUMBIGA1UEAwwLYWNtZS1uZXQgQ0EwKjAFBgMrZXADIQAU74St'
          '0nczabbH0d6rF/LCbrZd+WHVAdsGiGlenT/aTqMmMCQwEgYDVR0TAQH/BAgwBgEB/wIBADAOBgNVHQ8BAf8EBAMCAQYwBQYDK2VwA0EA'
          'nDomu6qIswXIkXAgTBkvJISwwprAH5TvqXTB0DsUObmJfREpDIpmZAbddLzNY5aJEBpCUsVES9KW50koegP7Dg==')
LEAF = (':MIIBSTCB/KADAgECAgMaKzwwBQYDK2VwMCkxETAPBgNVBAoMCGFjbWUtbmV0MRQwEgYDVQQDDAthY21lLW5ldCBDQTAeFw0yNjEwMDEw'
        'MDAwMDBaFw0yNjEwMzEwMDAwMDBaMCUxETAPBgNVBAoMCGFjbWUtbmV0MRAwDgYDVQQDDAdyaXNrLWV1MCowBQYDK2VwAyEAIWvGipO7Yb'
        'WU0Mxtr+alRgL4QiXNgPhYTBG2IOEdxKSjSzBJMAwGA1UdEwEB/wQCMAAwDgYDVR0PAQH/BAQDAgeAMCkGA1UdEQQiMCCCHnNhamhhLXJp'
        'c2stZXUuZXhhbXBsZS5pbnRlcm5hbDAFBgMrZXADQQCdjQWn60f/a+Co25hWcYkVpEm5gaan+h8jRb85AvE2F4vda21cPZJrjjZW6KpIht'
        'e1uVKZReH6ir3hYl6Xm7sJ:')
BODY = (b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"var_calc","arguments":{"portfolio":'
        b'"EU-RATES","confidence":0.99,"horizon_days":10},"_meta":{"io.modelcontextprotocol/protocolVersion":'
        b'"2026-07-28","io.modelcontextprotocol/clientCapabilities":{"extensions":{"io.sajha/net":{"protocol_version"'
        b':1}}},"traceparent":"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01","io.sajha/net":{"home":'
        b'"risk-eu","qualified_name":"acme-net__cust-na__var_calc"}}}}')
COMPONENTS = ('("@method" "@path" "@query" "content-type" "content-digest" "mcp-protocol-version" "mcp-method" '
              '"mcp-name" "sajha-net-version" "sajha-net-name" "sajha-net-from" "sajha-net-to" "sajha-net-hop" '
              '"sajha-net-visited" "sajha-net-api-key" "traceparent")')
SIG_INPUT = (f'sajhanet={COMPONENTS};created=1791374400;nonce="q1QXbXk3WlNQ8n0Zr6dL4w";'
             'keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519";tag="sajha-net-v1"')
HEADERS = {
    'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
    'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': 'tools/call', 'Mcp-Name': 'var_calc',
    'Sajha-Net-Version': '1', 'Sajha-Net-Name': 'acme-net', 'Sajha-Net-From': 'risk-eu', 'Sajha-Net-To': 'cust-na',
    'Sajha-Net-Hop': '1', 'Sajha-Net-Visited': '"acme-net/risk-eu"',
    'Sajha-Net-Api-Key': 'sja_U7ctcH-MN6JrIdIlX_PfCVXKc79Rmt58aTub2E7N97E',
    'traceparent': '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',
    'Content-Digest': 'sha-256=:FH+YtinzXcDSV+F2IPdYvsdEmlqry1zKK1duKAzRDeI=:',
    'Sajha-Net-Certificate': LEAF, 'Signature-Input': SIG_INPUT,
    'Signature': 'sajhanet=:xHiAAzcYJVUZBiNqU+OYRIwVVv5I7DfVOTEws0KRlNbLHX9nyOmPPwEiojXWFOSS9su5gbZkm51gcf/nqPYPDQ==:'}
RESP_BODY = (b'{"jsonrpc":"2.0","id":7,"result":{"resultType":"complete","content":[{"type":"text","text":"{\\"var\\": '
             b'1843200.0, \\"currency\\": \\"EUR\\"}"}],"structuredContent":{"var":1843200.0,"currency":"EUR"},'
             b'"isError":false,"_meta":{"io.sajha/net":{"instance":"cust-na","data_classes":{"results":'
             b'["confidential"]}}}}}')
KEY_RECORD = {
    'type': 'key', 'net': 'acme-net', 'key_id': '0b6f3c1e-8a4d-4f7e-9c21-5d3e7a9b2f10', 'key_prefix': 'sja_U7ctcH-M...',
    'name': 'alice laptop', 'key_hash': '1db0e8728c95abfa10d2a7b40dabc56c240e72cc4c63d517815b22ac46f09ff4',
    'home_instance': 'risk-eu', 'owner': {'user_id': '7d2a9e44-1c3b-4b8e-a6f0-2e9d8c7b5a31', 'user_name': 'alice',
                                          'display_name': 'Alice Martin', 'roles': ['analyst']},
    'enabled': True, 'expires_at': '2027-04-01T00:00:00Z', 'revoked_at': None, 'tool_access_mode': 'allowlist',
    'tool_access_list': ['var_calc', 'stress_test'], 'persistent': False, 'version': 42,
    'updated_at': '2026-10-07T11:58:03Z',
    'signature': {'alg': 'ed25519', 'keyid': '_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ',
                  'sig': '0AFAefhoSn4sMYcjD95AcBYRf_Ik_GTQF2U1oKGlNtgaweBjdz9Ugjygjh5BenumgXzrW8NaHybd1ZXs6_hOBg'}}


def _seed_key(label):
    return crypto.ed25519_from_seed(hashlib.sha256(f'sajha-net example: {label}'.encode()).digest())


class ExampleTrust(httpsig.Trust):
    net = 'acme-net'

    def __init__(self):
        self.ca = crypto.load_cert(base64.b64decode(CA_B64))

    def check_chain(self, chain, now):
        crypto.verify_chain(chain, self.ca, now)


def _verify_example(headers=None, body=BODY, **kw):
    return httpsig.verify_request(ExampleTrust(), 'cust-na', 'POST', '/mcp', '', headers or HEADERS, body, mcp=True,
                                  now=T0, **kw)


# ── the published vectors ───────────────────────────────────────────

def test_sig_01_example_request_verifies():
    v = _verify_example()
    assert v.sender == 'risk-eu' and v.keyid == '_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ'
    assert v.certificate.public_key().public_bytes(*_raw()) == _seed_key('risk-eu').public_key().public_bytes(*_raw())


def _raw():
    from cryptography.hazmat.primitives import serialization as S
    return S.Encoding.Raw, S.PublicFormat.Raw


def test_sig_12_example_response_verifies_against_its_request():
    assert httpsig.content_digest(RESP_BODY) == 'sha-256=:3cc/4zkToj3LIns5PQjmKsHtH56yWZ+r6ASgmPUwZ+8=:'
    req_sig = httpsig.request_signature_bytes(HEADERS)
    h = {'content-type': 'application/json', 'sajha-net-version': '1', 'sajha-net-name': 'acme-net',
         'sajha-net-from': 'cust-na', 'sajha-net-to': 'risk-eu', 'content-digest': httpsig.content_digest(RESP_BODY)}
    pv = ('("@status" "content-type" "content-digest" "sajha-net-version" "sajha-net-name" "sajha-net-from" '
          '"sajha-net-to" "signature";req;key="sajhanet");created=1791374401;'
          'keyid="TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I";alg="ed25519";tag="sajha-net-v1"')
    comps, params = sfv.parse_dict('sajhanet=' + pv)['sajhanet']
    covered = [(n, dict(p)) for n, p in comps]
    base = httpsig.signature_base(covered, sfv.ser_inner(comps, params), status=200, headers=h, req_signature=req_sig)
    sig = base64.b64decode('VsjDNqwP39vYvKv6QK79JlSp+PSgnZOkvcPpeSRlMmC66VzbfNBVxjHu+zDVbF5i/ZlMT6fPwDLXBGLVKWOBBg==')
    pub = _seed_key('cust-na').public_key()
    assert crypto.verify_raw(pub, 'ed25519', base, sig)
    other = bytes([req_sig[0] ^ 1]) + req_sig[1:]
    base2 = httpsig.signature_base(covered, sfv.ser_inner(comps, params), status=200, headers=h, req_signature=other)
    assert not crypto.verify_raw(pub, 'ed25519', base2, sig)


def test_rec_01_example_key_record():
    pub = _verify_example().certificate.public_key()
    rec = {k: v for k, v in KEY_RECORD.items() if k != 'signature'}
    assert schemas.is_valid('key_record', KEY_RECORD)
    assert crypto.verify_record('key', rec, KEY_RECORD['signature'], pub)
    reordered = dict(reversed(list(rec.items())))
    assert crypto.verify_record('key', reordered, KEY_RECORD['signature'], pub)
    for k in ('name', 'version', 'enabled'):
        changed = dict(rec, **{k: (rec[k] + 'x') if isinstance(rec[k], str) else (not rec[k]) if isinstance(
            rec[k], bool) else rec[k] + 1})
        assert not crypto.verify_record('key', changed, KEY_RECORD['signature'], pub)
    assert hashlib.sha256(HEADERS['Sajha-Net-Api-Key'].encode()).hexdigest() == KEY_RECORD['key_hash']


def test_rec_02_domain_separation():
    pub = _verify_example().certificate.public_key()
    rec = {k: v for k, v in KEY_RECORD.items() if k != 'signature'}
    assert not crypto.verify_record('member', rec, KEY_RECORD['signature'], pub)


def test_jcs_numbers_and_order():
    assert jcs.canonicalize({'b': 1, 'a': [1.5, 1e-7, 1e21, 0.000001, 100.0, -0.0, 'é']}) == \
        '{"a":[1.5,1e-7,1e+21,0.000001,100,0,"é"],"b":1}'.encode()
    assert jcs.canonicalize({'€': 1, '\r': 2, '1': 3}) == '{"\\r":2,"1":3,"€":1}'.encode()


# ── verification failures, in the order of §8.7 ─────────────────────

def _refused(reason, headers=None, body=BODY, **kw):
    with pytest.raises(NetError) as e:
        _verify_example(headers, body, **kw)
    assert e.value.reason == reason, (e.value.reason, e.value.detail)
    return e.value


@pytest.mark.parametrize('drop', ['Signature', 'Signature-Input', 'Sajha-Net-Certificate'])
def test_sig_02_missing(drop):
    _refused('signature_missing', {k: v for k, v in HEADERS.items() if k != drop})


def test_sig_03_body_byte_changed():
    _refused('digest_mismatch', body=BODY.replace(b'0.99', b'0.98'))


@pytest.mark.parametrize('header', ['Content-Type', 'MCP-Protocol-Version', 'Mcp-Method', 'Mcp-Name', 'Sajha-Net-Hop',
                                    'Sajha-Net-Visited', 'Sajha-Net-Api-Key', 'traceparent'])
def test_sig_04_changed_covered_header(header):
    h = dict(HEADERS)
    h[header] = h[header] + 'x' if header != 'Sajha-Net-Hop' else '2'
    _refused('signature_invalid', h)


def test_sig_04_changed_routing_headers():
    for header in ('Sajha-Net-To', 'Sajha-Net-From', 'Sajha-Net-Name', 'Sajha-Net-Version'):
        h = dict(HEADERS, **{header: 'other-net' if header != 'Sajha-Net-Version' else '1 '})
        if header == 'Sajha-Net-Version':
            continue                                   # whitespace is trimmed (RFC 9421 §2.1): same value
        with pytest.raises(NetError) as e:
            _verify_example(h)
        assert e.value.reason in ('signature_invalid', 'net_mismatch'), header


def test_sig_05_expired_and_future():
    with pytest.raises(NetError) as e:
        httpsig.verify_request(ExampleTrust(), 'cust-na', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0 + 31)
    assert e.value.reason == 'signature_expired'
    with pytest.raises(NetError) as e:
        httpsig.verify_request(ExampleTrust(), 'cust-na', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0 - 6)
    assert e.value.reason == 'signature_expired'
    httpsig.verify_request(ExampleTrust(), 'cust-na', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0 - 5)
    httpsig.verify_request(ExampleTrust(), 'cust-na', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0 + 29,
                           max_age=30)


def test_sig_06_replay_and_failed_requests_do_not_spend_nonces():
    kv = MemoryKV(lambda: T0)
    seen = lambda k, n, ttl: not kv.add(f'{k}:{n}', 1, ttl)          # noqa: E731
    _refused('digest_mismatch', body=BODY + b' ', seen_nonce=seen)
    _verify_example(seen_nonce=seen)
    _refused('replay', seen_nonce=seen)


def test_sig_07_wrong_ca_and_wrong_net():
    class OtherCA(ExampleTrust):
        def __init__(self):
            self.ca = crypto.make_ca_certificate(crypto.generate_key(), 'acme-net', now=T0 - 86400)
    with pytest.raises(NetError) as e:
        httpsig.verify_request(OtherCA(), 'cust-na', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0)
    assert e.value.reason == 'certificate_invalid' and e.value.status == 401

    class OtherNet(ExampleTrust):
        net = 'other-net'
    with pytest.raises(NetError) as e:
        httpsig.verify_request(OtherNet(), 'cust-na', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0)
    assert e.value.reason == 'net_mismatch' and e.value.status == 403


def test_sig_08_revoked_serial_and_instance():
    leaf = _verify_example().certificate

    class Revoked(ExampleTrust):
        def __init__(self, entry):
            super().__init__()
            self.rl = {'revoked': [entry]}

        def revocation(self, serial, instance):
            from sajha.net.trust import revocation_reason
            return revocation_reason(self.rl, serial, instance)
    for entry, reason in (({'serial': crypto.serial_hex(leaf)}, 'certificate_revoked'),
                          ({'instance': 'risk-eu'}, 'instance_revoked')):
        with pytest.raises(NetError) as e:
            httpsig.verify_request(Revoked(entry), 'cust-na', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0)
        assert e.value.reason == reason and e.value.status == 403


@pytest.mark.parametrize('params, reason', [
    ('keyid="AAAAiCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519"', 'signature_invalid'),
    ('keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ecdsa-p256-sha256"', 'signature_invalid'),
    ('keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="hmac-sha256"', 'signature_invalid'),
    ('keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="rsa-pss-sha512"', 'signature_invalid')])
def test_sig_09_keyid_and_alg(params, reason):
    si = SIG_INPUT.replace('keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519"', params)
    _refused(reason, dict(HEADERS, **{'Signature-Input': si}))


def test_sig_10_from_to_and_own_name(ca):
    s = _signer(ca, 'risk-eu', crypto.ED25519)
    trust = CATrust('acme-net', ca[1], lambda: None)
    body = b'{}'
    for sender, to, own, reason, status in (('cust-eu', 'cust-na', 'cust-na', 'from_mismatch', 401),
                                            ('risk-eu', 'treasury-na', 'cust-na', 'recipient_mismatch', 421),
                                            ('risk-eu', 'risk-eu', 'risk-eu', 'name_conflict', 409)):
        h = httpsig.sign_request(s, 'POST', '/sajhanet/v1/gossip/ping', '', {}, body, 'acme-net', sender, to, now=T0)
        with pytest.raises(NetError) as e:
            httpsig.verify_request(trust, own, 'POST', '/sajhanet/v1/gossip/ping', '', h, body, now=T0)
        assert (e.value.reason, e.value.status) == (reason, status)
    with pytest.raises(NetError) as e:
        httpsig.verify_request(ExampleTrust(), 'risk-eu', 'POST', '/mcp', '', HEADERS, BODY, mcp=True, now=T0)
    assert e.value.reason == 'name_conflict'


@pytest.mark.parametrize('component', ['"@query" ', '"content-digest" ', '"sajha-net-name" ', '"traceparent"',
                                       '"mcp-name" '])
def test_sig_11_incomplete(component):
    si = SIG_INPUT.replace(component, '').replace(' )', ')')
    _refused('signature_incomplete', dict(HEADERS, **{'Signature-Input': si}))
    _refused('signature_incomplete', dict(HEADERS, **{'Signature-Input': SIG_INPUT.replace(';tag="sajha-net-v1"', '')}))
    _refused('signature_incomplete', dict(HEADERS, **{'Signature-Input': SIG_INPUT.replace(
        'nonce="q1QXbXk3WlNQ8n0Zr6dL4w";', '')}))


def test_cap_04_unsupported_version():
    e = _refused('unsupported_version', dict(HEADERS, **{'Sajha-Net-Version': '2'}))
    assert e.status == 400


# ── signing round trips, both algorithms (SIG-13) ───────────────────

@pytest.fixture
def ca():
    key = crypto.generate_key()
    return key, crypto.make_ca_certificate(key, 'acme-net', now=T0 - 86400)


def _signer(ca, name, alg):
    key = crypto.generate_key(alg)
    cert = crypto.issue_certificate(ca[0], ca[1], key.public_key(), 'acme-net', name, f'{name}.test', now=T0 - 3600)
    return httpsig.Signer(key, [cert])


@pytest.mark.parametrize('alg', [crypto.ED25519, crypto.P256])
def test_sig_13_both_algorithms_and_der_refused(ca, alg):
    s = _signer(ca, 'risk-eu', alg)
    body = b'{"type":"ping","seq":1,"updates":[]}'
    h = httpsig.sign_request(s, 'POST', '/sajhanet/v1/gossip/ping', '', {}, body, 'acme-net', 'risk-eu', 'cust-na',
                             now=T0)
    trust = CATrust('acme-net', ca[1], lambda: None)
    v = httpsig.verify_request(trust, 'cust-na', 'POST', '/sajhanet/v1/gossip/ping', '', h, body, now=T0)
    assert v.alg == alg
    if alg == crypto.P256:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        comps, params = sfv.parse_dict(h['signature-input'])['sajhanet']
        base = httpsig.signature_base([(n, dict(p)) for n, p in comps], sfv.ser_inner(comps, params),
                                      method='POST', path='/sajhanet/v1/gossip/ping', query='', headers=h)
        der = s.key.sign(base, ec.ECDSA(hashes.SHA256()))
        bad = dict(h, signature='sajhanet=' + sfv.ser_bare(der))
        with pytest.raises(NetError) as e:
            httpsig.verify_request(trust, 'cust-na', 'POST', '/sajhanet/v1/gossip/ping', '', bad, body, now=T0)
        assert e.value.reason == 'signature_invalid'


def test_sig_12_response_binding(ca):
    a, b = _signer(ca, 'risk-eu', crypto.ED25519), _signer(ca, 'cust-na', crypto.ED25519)
    trust = CATrust('acme-net', ca[1], lambda: None)
    rq = httpsig.sign_request(a, 'GET', '/sajhanet/v1/revocations', '', {}, b'', 'acme-net', 'risk-eu', 'cust-na', now=T0)
    rq2 = httpsig.sign_request(a, 'GET', '/sajhanet/v1/revocations', '', {}, b'', 'acme-net', 'risk-eu', 'cust-na', now=T0)
    body = b'{"x":1}'
    rs = httpsig.sign_response(b, 200, {}, body, httpsig.request_signature_bytes(rq), 'acme-net', 'cust-na', 'risk-eu',
                               now=T0)
    httpsig.verify_response(trust, 'risk-eu', 'cust-na', 200, rs, body, httpsig.request_signature_bytes(rq), now=T0)
    for bad in (lambda: httpsig.verify_response(trust, 'risk-eu', 'cust-na', 200, rs, body,
                                                httpsig.request_signature_bytes(rq2), now=T0),
                lambda: httpsig.verify_response(trust, 'risk-eu', 'cust-na', 200, {'content-type': 'application/json'},
                                                body, httpsig.request_signature_bytes(rq), now=T0),
                lambda: httpsig.verify_response(trust, 'risk-eu', 'cust-na', 201, rs, body,
                                                httpsig.request_signature_bytes(rq), now=T0),
                lambda: httpsig.verify_response(trust, 'risk-eu', 'treasury-na', 200, rs, body,
                                                httpsig.request_signature_bytes(rq), now=T0)):
        with pytest.raises(NetError):
            bad()


def test_sig_14_streamed_final_message(ca):
    b = _signer(ca, 'cust-na', crypto.ED25519)
    msg = {'jsonrpc': '2.0', 'id': 7, 'result': {'content': [{'type': 'text', 'text': 'ok'}], 'isError': False,
                                                  'structuredContent': {'var': 1843200.0}}}
    signed = httpsig.sign_message(b, msg, 'q1QXbXk3WlNQ8n0Zr6dL4w')
    assert 'response_signature' in signed['result']['_meta']['io.sajha/net']
    assert httpsig.verify_message(signed, 'q1QXbXk3WlNQ8n0Zr6dL4w', b.chain[0])
    assert not httpsig.verify_message(signed, 'another-nonce-0000000000', b.chain[0])
    changed = json.loads(json.dumps(signed))
    changed['result']['content'][0]['text'] = 'changed'
    assert not httpsig.verify_message(changed, 'q1QXbXk3WlNQ8n0Zr6dL4w', b.chain[0])
    err = httpsig.sign_message(b, {'jsonrpc': '2.0', 'id': 7, 'error': {'code': -32019, 'message': 'x'}}, 'n' * 22)
    assert httpsig.verify_message(err, 'n' * 22, b.chain[0]) and 'io.sajha/net' in err['error']['data']


# ── endpoints: one port, several nets (NET-01..03), errors and limits ─

def _signed(node, to, path, body, net=None, method='POST'):
    raw = json.dumps(body, separators=(',', ':')).encode() if body is not None else b''
    h = httpsig.sign_request(node.signer, method, path, '', {'content-type': 'application/json'} if raw else {}, raw,
                             net or node.net, node.name, to, now=node.clock())
    return h, raw


def test_net_01_unknown_net_and_missing_header_get_bare_404(tmp_path):
    n = TestNet(tmp_path)
    a = n.add('risk-eu', founder=True)
    b = n.add('cust-na', founder=True)
    p = n.participants['cust-na']
    h, raw = _signed(a, 'cust-na', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': []})
    ok = p.handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw)
    assert ok.status == 200 and ok.headers['sajha-net-name'] == 'acme-net'
    assert '"sajha-net-name"' in ok.headers['signature-input']
    for variant in ({k: v for k, v in h.items() if k != 'sajha-net-name'}, dict(h, **{'sajha-net-name': 'other-net'}),
                    dict(h, **{'sajha-net-name': 'Bad__Net'})):
        r = p.handle('POST', '/sajhanet/v1/gossip/ping', '', variant, raw)
        assert (r.status, r.body, r.headers) == (404, b'', {})
    off = Participant({'acme-net': b}, enabled=False).handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw)
    assert (off.status, off.body, off.headers) == (404, b'', {})


def test_net_02_nets_kept_apart(tmp_path):
    m, nn = TestNet(tmp_path, net='net-m'), TestNet(tmp_path, net='net-n')
    nn.clock = m.clock
    am = m.add('risk-eu', founder=True)
    an = nn.add('risk-eu-n', founder=True)
    bm = m.add('cust-na', founder=True)
    bn = nn.add('cust-na', founder=True, route_as='cust-na-n')
    both = Participant({'net-m': bm, 'net-n': bn})
    # a certificate from N's CA in a request naming M
    h, raw = _signed(an, 'cust-na', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': []}, net='net-m')
    r = both.handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw)
    assert r.status == 401 and json.loads(r.body)['reason'] == 'certificate_invalid'
    # a certificate with O=net-m presented for net-n (issued by N's CA for the test)
    key = crypto.generate_key()
    cert = crypto.issue_certificate(nn.ca_key, nn.ca_cert, key.public_key(), 'net-m', 'risk-eu', 'risk-eu.test',
                                    now=m.clock() - 60)
    s = httpsig.Signer(key, [cert])
    raw = b'{"type":"ping","seq":1,"updates":[]}'
    h = httpsig.sign_request(s, 'POST', '/sajhanet/v1/gossip/ping', '', {}, raw, 'net-n', 'risk-eu', 'cust-na',
                             now=m.clock())
    r = both.handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw)
    assert r.status == 403 and json.loads(r.body)['reason'] == 'net_mismatch'
    # the same nonce once in M and once in N is not a replay
    hm, raw = _signed(am, 'cust-na', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': []})
    nonce = sfv.parse_dict(hm['signature-input'])['sajhanet'][1]['nonce']
    hn = httpsig.sign_request(an.signer, 'POST', '/sajhanet/v1/gossip/ping', '', {}, raw, 'net-n', 'risk-eu-n',
                              'cust-na', now=m.clock(), nonce=nonce)
    assert both.handle('POST', '/sajhanet/v1/gossip/ping', '', hm, raw).status == 200
    assert both.handle('POST', '/sajhanet/v1/gossip/ping', '', hn, raw).status == 200
    assert both.handle('POST', '/sajhanet/v1/gossip/ping', '', hm, raw).status == 401


def test_net_03_member_record_of_another_net_dropped(tmp_path):
    m, nn = TestNet(tmp_path, net='net-m'), TestNet(tmp_path, net='net-n')
    am = m.add('risk-eu', founder=True)
    bm = m.add('cust-na', founder=True)
    entry = am.own_entry()
    assert bm.merge(entry, via_net='net-m')
    bm2 = m.add('treasury-na', founder=True)
    assert not bm2.merge(entry, via_net='net-n')
    assert bm2.member('risk-eu') is None


def test_err_01_problem_bodies_are_signed_and_valid(tmp_path):
    n = TestNet(tmp_path)
    a = n.add('risk-eu', founder=True)
    n.add('cust-na', founder=True)
    p = n.participants['cust-na']
    h, raw = _signed(a, 'cust-na', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': -1, 'updates': []})
    req_sig = httpsig.request_signature_bytes(h)
    h2, raw2 = _signed(a, 'nobody', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': []})
    for hh, body, status, reason in ((h, raw, 400, 'invalid_request'),
                                     (h2, raw2, 421, 'recipient_mismatch'),
                                     ({k: v for k, v in h.items() if k != 'signature'}, raw, 401, 'signature_missing')):
        r = p.handle('POST', '/sajhanet/v1/gossip/ping', '', hh, body)
        doc = json.loads(r.body)
        assert r.status == status and doc['reason'] == reason and schemas.is_valid('problem', doc)
        assert r.headers['content-type'] == 'application/problem+json' and 'signature' in r.headers
        if reason != 'signature_missing':
            httpsig.verify_response(a.trust, 'risk-eu', 'cust-na', r.status, r.headers, r.body,
                                    httpsig.request_signature_bytes(hh), now=n.clock())


def test_lim_01_limits(tmp_path):
    n = TestNet(tmp_path)
    a = n.add('risk-eu', founder=True)
    n.add('cust-na', founder=True)
    p = n.participants['cust-na']
    entry = a.own_entry()
    h, raw = _signed(a, 'cust-na', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': [entry] * 32})
    assert p.handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw).status == 200
    h, raw = _signed(a, 'cust-na', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': [entry] * 33})
    assert p.handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw).status == 400
    big = {'type': 'ping', 'seq': 1, 'updates': [], 'pad': 'x' * (65 * 1024)}
    h, raw = _signed(a, 'cust-na', '/sajhanet/v1/gossip/ping', big)
    r = p.handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw)
    assert r.status == 413 and json.loads(r.body)['reason'] == 'too_large'
    members = [entry] * 1024
    h, raw = _signed(a, 'cust-na', '/sajhanet/v1/membership/sync', {'type': 'sync', 'reason': 'join', 'members': members})
    assert len(raw) < 1024 * 1024
    assert p.handle('POST', '/sajhanet/v1/membership/sync', '', h, raw).status == 200


def test_cap_05_unlisted_feature_paths_are_404(tmp_path):
    n = TestNet(tmp_path)
    a = n.add('risk-eu', founder=True)
    n.add('cust-na', founder=True)
    p = n.participants['cust-na']
    for path in ('/sajhanet/v1/catalog', '/sajhanet/v1/keys', '/sajhanet/v1/blocks', '/sajhanet/v1/ca/renew',
                 '/sajhanet/v1/nothing'):
        h, raw = _signed(a, 'cust-na', path, {})
        assert p.handle('POST', path, '', h, raw).status == 404
    h, raw = _signed(a, 'cust-na', '/sajhanet/v1/gossip/ping', None, method='GET')
    assert p.handle('GET', '/sajhanet/v1/gossip/ping', '', h, raw).status == 405
