# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The SAJHA Net CA (protocol §5.2, §13, §14): CA-01 to CA-03 and NAME-08."""

import json

import pytest

from sajha.net import crypto, httpsig, schemas
from sajha.net.ca import NameHeld
from sajha.net.trust import CATrust
from tests.net.harness import TestNet


@pytest.fixture
def net(tmp_path):
    n = TestNet(tmp_path)
    n.ca_node = n.add('risk-eu', founder=True, ca_node=True)
    return n


def _enroll(n, instance, token, key=None, host=None, secure=True, net_header=None, subject=None, csr=None):
    key = key or crypto.generate_key()
    csr = csr or crypto.make_csr(key, *(subject or ('acme-net', instance)), host or f'{instance}.test')
    body = json.dumps({'net': 'acme-net', 'instance': instance, 'token': token, 'csr': crypto.b64(csr)}).encode()
    h = {'content-type': 'application/json', 'sajha-net-version': '1', 'sajha-net-name': net_header or 'acme-net'}
    r = n.participants['risk-eu'].handle('POST', '/sajhanet/v1/ca/enroll', '', h, body, secure=secure,
                                         source='10.0.0.9')
    return r, key


def test_ca_01_enrollment_issues_and_spends_the_token(net):
    token, _ = net.ca.create_token('cust-na')
    r, key = _enroll(net, 'cust-na', token)
    assert r.status == 200
    data = json.loads(r.body)
    assert schemas.is_valid('enroll_response', data)
    cert = crypto.chain_from_b64(data['certificate'])[0]
    assert crypto.subject_of(cert) == ('acme-net', 'cust-na')
    assert crypto.cert_der(crypto.load_cert(crypto.unb64(data['ca_certificate']))) == crypto.cert_der(net.ca_cert)
    from cryptography.hazmat.primitives import serialization as S
    raw = (S.Encoding.Raw, S.PublicFormat.Raw)
    assert cert.public_key().public_bytes(*raw) == key.public_key().public_bytes(*raw)
    # the answer is signed by the CA participant, addressed to the requested name (not bound: no request signature)
    httpsig.verify_response(CATrust('acme-net', net.ca_cert, lambda: None), 'cust-na', 'risk-eu', 200, r.headers,
                            r.body, None, now=net.clock())
    r2, _ = _enroll(net, 'cust-na', token)
    assert r2.status == 403 and json.loads(r2.body)['reason'] == 'enrollment_refused'


def test_ca_02_refusals_are_one_reason(net):
    t_exp, _ = net.ca.create_token('a-one')
    net.clock.advance(31 * 60)
    cases = []
    cases.append(_enroll(net, 'a-one', t_exp)[0])                             # expired
    t, _ = net.ca.create_token('b-two')
    cases.append(_enroll(net, 'c-three', t)[0])                               # issued for another name
    t, _ = net.ca.create_token('d-four')
    cases.append(_enroll(net, 'd-four', t, subject=('acme-net', 'e-five'))[0])   # wrong subject
    t, _ = net.ca.create_token('f-six')
    cases.append(_enroll(net, 'f-six', t, subject=('other-net', 'f-six'))[0])    # wrong O
    t, _ = net.ca.create_token('g-seven')
    good = crypto.make_csr(crypto.generate_key(), 'acme-net', 'g-seven', 'g-seven.test')
    cases.append(_enroll(net, 'g-seven', t, csr=good[:-3] + bytes(3))[0])      # bad self-signature
    cases.append(_enroll(net, 'h-eight', 'x' * 43)[0])                          # unknown token
    t, _ = net.ca.create_token('i-nine')
    cases.append(_enroll(net, 'i-nine', t, secure=False)[0])                    # plain HTTP
    for r in cases:
        doc = json.loads(r.body)
        assert r.status == 403 and doc['reason'] == 'enrollment_refused' and doc.get('detail') == 'refused', doc
    t, _ = net.ca.create_token('j-ten')
    r, _ = _enroll(net, 'j-ten', t, net_header='other-net')
    assert r.status == 404, 'a net the CA participant is not in'


def test_ca_02_rate_limited_per_source(net):
    statuses = [_enroll(net, 'k-x', 'y' * 43)[0].status for _ in range(12)]
    assert statuses[:10] == [403] * 10 and statuses[-1] == 429


def test_ca_03_renewal(net):
    n = net
    b = n.add('cust-na', seeds=[n.url('risk-eu')])
    assert b.try_join()
    old_serial = crypto.serial_hex(b.signer.chain[0])
    cert = b.renew()                                              # finds the CA participant by feature 'ca'
    assert crypto.subject_of(cert) == ('acme-net', 'cust-na') and crypto.renews_of(cert) == old_serial
    # another subject is refused
    key = crypto.generate_key()
    csr = crypto.make_csr(key, 'acme-net', 'treasury-na', 'cust-na.test')
    with pytest.raises(Exception) as e:
        b.request(n.url('risk-eu'), '/sajhanet/v1/ca/renew', {'csr': crypto.b64(csr)}, 'risk-eu')
    assert getattr(e.value, 'reason', '') == 'enrollment_refused'
    # a revoked certificate is refused before the CA looks at it
    n.ca_node.accept_revocations(n.ca.revoke(serial=crypto.serial_hex(cert)))
    with pytest.raises(Exception) as e:
        b.renew(ca_url=n.url('risk-eu'), ca_name='risk-eu')
    assert getattr(e.value, 'reason', '') == 'certificate_revoked'


def test_name_08_token_for_held_name_refused_until_revoked(net):
    token, _ = net.ca.create_token('cust-na')
    r, _ = _enroll(net, 'cust-na', token)
    assert r.status == 200
    cert = crypto.chain_from_b64(json.loads(r.body)['certificate'])[0]
    with pytest.raises(NameHeld) as e:
        net.ca.create_token('cust-na')
    assert e.value.holder['serial'] == crypto.serial_hex(cert) and e.value.holder['thumbprint']
    net.ca.revoke(serial=crypto.serial_hex(cert))
    token2, _ = net.ca.create_token('cust-na')
    assert _enroll(net, 'cust-na', token2)[0].status == 200
