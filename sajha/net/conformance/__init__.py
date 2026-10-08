"""
The SAJHA Net conformance suite (protocol §20), runnable against any target.

Every id of §20 is listed in :data:`CASES` with its targets (S a SAJHA instance, A the SAJHA Net
agent or any participant claiming that target, L the reference library) and the feature it needs.
A case is checked in one of three ways:

* **remote**: against a running participant over HTTP (or an in-process connector), as a
  participant of the net would see it: signed and tampered requests to ``/sajhanet/v1/`` and the
  signed MCP endpoint, and the refusals, problems and signed answers that come back;
* **library**: against the protocol core of this process (``sajha/net/``) with the §21 vectors,
  for target L;
* **in-process**: the case needs control of the target's insides (clocks, CA administration,
  several members failing): it is reported ``skip`` with the test file of SAJHA's own suite that
  covers it.

A case that does not apply to the target (its targets, or a feature the target does not advertise)
is ``skip`` with the reason. The runner is itself a participant: it needs an identity the target
trusts (self-signed under ``admission: open``, or a certificate from the net's CA, by enrollment
with a token or from files). It never joins the net: it sends no member entry of its own.

    python -m sajha.net.conformance --target https://risk-eu.example:3002 --net acme-net \\
        --ca-url https://risk-eu.example:3002 --token <token>
    python -m sajha.net.conformance --target library

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.net import EXTENSION_ID, SUPPORTED_VERSIONS, crypto, httpsig, jcs, keydir, names, schemas, sfv
from sajha.net.catalog import catalog_hash, contract_hash
from sajha.net.errors import NetError
from sajha.net.plugins import PeerConnector, PeerUnreachable

PASS, FAIL, SKIP = 'pass', 'fail', 'skip'
P = '/sajhanet/v1'
MODERN = '2026-07-28'


@dataclass
class Case:
    id: str
    targets: str                      # 'S A L' etc.
    feature: str = ''                 # the case applies only to a target that advertises it
    how: str = 'in_process'           # remote | library | in_process
    where: str = ''                   # in_process: the test file of SAJHA's suite that covers it


def _c(cid, targets, how='in_process', feature='', where=''):
    return Case(cid, targets, feature, how, where)


T = 'tests/net/'
#: every id of protocol §20, in the order of the table
CASES: List[Case] = [
    _c('NAME-01', 'S A L', 'library'), _c('NAME-02', 'S A L', 'library'), _c('NAME-03', 'S A L', 'library'),
    _c('NAME-04', 'S A', where=T + 'test_net_names.py'), _c('NAME-05', 'S A L', 'library'),
    _c('NAME-06', 'S A', 'remote'), _c('NAME-07', 'S A', where=T + 'test_net_membership.py'),
    _c('NAME-08', 'S', feature='ca', where=T + 'test_net_ca.py'),
    _c('NAME-09', 'S A', where=T + 'test_net_ca.py'), _c('NAME-10', 'S A L', 'library'),
    _c('NAME-11', 'S A', where=T + 'test_net_membership.py'),
    _c('NET-01', 'S A', 'remote'), _c('NET-02', 'S A', where=T + 'test_net_signatures.py'),
    _c('NET-03', 'S A L', 'library'), _c('NET-04', 'S A', 'remote'),
    _c('NET-05', 'S', where=T + 'test_net_reexport_identity.py'), _c('NET-06', 'S A', where=T + 'test_net_keys.py'),
    _c('CAP-01', 'S A', 'remote'), _c('CAP-02', 'S A', 'remote'), _c('CAP-03', 'S A', 'remote'),
    _c('CAP-04', 'S A L', 'remote'), _c('CAP-05', 'S A', 'remote'),
    _c('SIG-01', 'S A L', 'library'), _c('SIG-02', 'S A', 'remote'), _c('SIG-03', 'S A', 'remote'),
    _c('SIG-04', 'S A', 'remote'), _c('SIG-05', 'S A', 'remote'), _c('SIG-06', 'S A', 'remote'),
    _c('SIG-07', 'S A', 'remote'), _c('SIG-08', 'S A', where=T + 'test_net_signatures.py'),
    _c('SIG-09', 'S A L', 'remote'), _c('SIG-10', 'S A', 'remote'), _c('SIG-11', 'S A', 'remote'),
    _c('SIG-12', 'S A L', 'remote'), _c('SIG-13', 'S A L', 'library'),
    _c('SIG-14', 'S A', where='(streamed forwarded responses are not relayed yet)'),
    _c('SIG-15', 'S A', 'remote'),
    _c('REC-01', 'S A L', 'library'), _c('REC-02', 'S A L', 'library'),
    _c('GOS-01', 'S A', 'remote', 'gossip'), _c('GOS-02', 'S A', 'remote', 'gossip'),
    _c('GOS-03', 'S A', where=T + 'test_net_membership.py'), _c('GOS-04', 'S A', where=T + 'test_net_membership.py'),
    _c('GOS-05', 'S A L', 'library'), _c('GOS-06', 'S A L', 'remote', 'gossip'),
    _c('GOS-07', 'S A', where=T + 'test_net_membership.py'), _c('GOS-08', 'S A', 'remote', 'gossip'),
    _c('GOS-09', 'S A', where=T + 'test_net_membership.py'), _c('GOS-10', 'S A', where=T + 'test_net_membership.py'),
    _c('GOS-11', 'S A', where=T + 'test_net_membership.py'), _c('GOS-12', 'S A', where=T + 'test_net_membership.py'),
    _c('GOS-13', 'S A', where=T + 'test_net_membership.py'), _c('GOS-14', 'S A', where=T + 'test_net_integration.py'),
    _c('CAT-01', 'S A', 'remote', 'catalog'), _c('CAT-02', 'S A', 'remote', 'catalog'),
    _c('CAT-03', 'S A', 'remote', 'catalog'), _c('CAT-04', 'S', where=T + 'test_net_catalog.py'),
    _c('CAT-05', 'S A', 'remote', 'visibility'), _c('CAT-06', 'S A', 'remote', 'catalog'),
    _c('CAT-07', 'S', where=T + 'test_net_catalog.py'), _c('CAT-08', 'S', where=T + 'test_net_catalog.py'),
    _c('CON-06', 'S A', where=T + 'test_net_catalog.py'), _c('CON-01', 'S A', where=T + 'test_net_catalog.py'),
    _c('CON-02', 'S A', where=T + 'test_net_catalog.py'), _c('CON-03', 'S A', where=T + 'test_net_catalog.py'),
    _c('CON-04', 'S A', where=T + 'test_net_catalog.py'), _c('CON-05', 'S', where=T + 'test_net_catalog.py'),
    _c('KEY-01', 'S A', 'remote', 'key_directory'), _c('KEY-02', 'S A L', 'library'),
    _c('KEY-03', 'S A L', 'remote', 'key_directory'), _c('KEY-04', 'S A', 'remote', 'key_directory'),
    _c('KEY-05', 'S A', where=T + 'test_net_keys.py'),
    _c('BLK-01', 'S A', 'remote', 'blocks'), _c('REV-01', 'S A L', 'remote'),
    _c('CA-01', 'S', feature='ca', where=T + 'test_net_ca.py'), _c('CA-02', 'S', feature='ca', where=T + 'test_net_ca.py'),
    _c('CA-03', 'S', feature='ca', where=T + 'test_net_ca.py'),
    _c('CALL-01', 'S A', 'remote'), _c('CALL-02', 'S A', where=T + 'test_net_identity.py'),
    _c('CALL-03', 'S A', 'remote'), _c('CALL-04', 'S A', 'remote'), _c('CALL-05', 'S A', 'remote'),
    _c('CALL-06', 'S A', where=T + 'test_net_identity.py, test_net_routing_integration.py'),
    _c('CALL-07', 'S A', feature='residency', where=T + 'test_net_residency.py'), _c('CALL-08', 'S A', 'remote'),
    _c('CALL-09', 'S', where=T + 'test_net_routing_integration.py'), _c('CALL-10', 'S A', where=T + 'test_net_identity.py'),
    _c('CALL-11', 'S A', feature='progress', where='(progress and cancellation are not relayed yet)'),
    _c('CALL-12', 'S A', where='(forwarded calls use the 2026-07-28 era only)'),
    _c('CALL-13', 'S A', feature='reexport', where=T + 'test_net_reexport_identity.py'),
    _c('CALL-14', 'S A', where=T + 'test_net_reexport_identity.py'),
    _c('CALL-15', 'S A', feature='token_exchange', where=T + 'test_net_reexport_identity.py'),
    _c('FB-01', 'S A', 'remote'), _c('FB-02', 'S', where=T + 'test_net_catalog.py'),
    _c('FB-03', 'S', where=T + 'test_net_catalog.py'), _c('FB-04', 'S', where=T + 'test_net_catalog.py'),
    _c('FB-05', 'S', where=T + 'test_net_catalog.py'), _c('FB-06', 'S', where=T + 'test_net_catalog.py'),
    _c('FB-07', 'S', where='(progress, input requests and tasks are not relayed yet)'),
    _c('ERR-01', 'S A', 'remote'), _c('LIM-01', 'S A', 'remote'),
]
BY_ID = {c.id: c for c in CASES}


class CheckFailed(AssertionError):
    pass


class NotApplicable(Exception):
    pass


def check(cond: Any, msg: str) -> None:
    if not cond:
        raise CheckFailed(msg)


@dataclass
class Result:
    id: str
    status: str
    detail: str = ''


@dataclass
class Report:
    target: Dict[str, Any]
    results: List[Result] = field(default_factory=list)

    @property
    def summary(self) -> Dict[str, int]:
        out = {PASS: 0, FAIL: 0, SKIP: 0}
        for r in self.results:
            out[r.status] += 1
        return out

    def failed(self) -> List[Result]:
        return [r for r in self.results if r.status == FAIL]

    def status(self, cid: str) -> str:
        return next((r.status for r in self.results if r.id == cid), '')

    def to_dict(self) -> Dict[str, Any]:
        return {'target': self.target, 'summary': self.summary,
                'results': [{'id': r.id, 'status': r.status, 'detail': r.detail} for r in self.results]}

    def text(self) -> str:
        t = self.target
        lines = [f'SAJHA Net conformance: {t.get("instance") or t.get("url")} (target {t.get("code")}, '
                 f'kind {t.get("kind")}) in {t.get("net", "-")}']
        for r in self.results:
            lines.append(f'  {r.id:<8} {r.status.upper():<4}  {r.detail}')
        s = self.summary
        lines.append(f'{s[PASS]} passed, {s[FAIL]} failed, {s[SKIP]} skipped')
        return '\n'.join(lines)


# ── library cases (target L, and the shared rules every target must follow) ─────

def _seed_key(label):
    return crypto.ed25519_from_seed(hashlib.sha256(f'sajha-net example: {label}'.encode()).digest())


class _ExampleTrust(httpsig.Trust):
    net = 'acme-net'

    def __init__(self):
        from sajha.net.conformance import vectors as V
        self.ca = crypto.load_cert(base64.b64decode(V.CA_B64))

    def check_chain(self, chain, now):
        crypto.verify_chain(chain, self.ca, now)


def _example_verified(headers=None, body=None):
    from sajha.net.conformance import vectors as V
    return httpsig.verify_request(_ExampleTrust(), 'cust-na', 'POST', '/mcp', '', headers or V.HEADERS,
                                  V.BODY if body is None else body, mcp=True, now=V.T0)


def lib_name_01():
    for ok in ('risk-eu', 'ab', 'a1', 'x' * 32, 'cust-na'):
        check(names.is_configured_name(ok), f'{ok!r} is a valid name')
    for bad in ('risk_eu', 'a.b', 'a:b', 'Risk', 'a--b', '1abc', '-a', 'a-', 'x' * 33):
        check(not names.is_configured_name(bad), f'{bad!r} is refused')


def lib_name_02():
    check(names.safe_prefix('10.20.4.17:3002') == '10_20_4_17_3002', 'the prefix of 10.20.4.17:3002')


def lib_name_03():
    n = names.safe_prefix('[2001:db8::7]:3002')
    check(n == '2001_0db8_0000_0000_0000_0000_0000_0007_3002', f'the prefix of [2001:db8::7]:3002 ({n})')
    check('__' not in n, 'no __ in an IPv6 prefix')
    m = names.safe_prefix(names.format_address_name('::ffff:10.0.0.1', 80))
    check(len(m.split('_')) == 9, f'an IPv4-mapped address expands to eight groups ({m})')


def lib_name_05():
    check(names.split_qualified('acme-net__risk-eu__a__b') == ('acme-net', 'risk-eu', 'a__b'), 'split at the first two __')
    check(names.split_qualified('acme-net__10_20_4_17_3002__var_calc') == ('acme-net', '10_20_4_17_3002', 'var_calc'),
          'an address prefix')
    check(names.tool_part('a.b') == 'a_b', 'a dotted tool name gets the tool part a_b')
    check(names.qualified_name('acme-net', 'risk-eu', 'x')[0].isalpha(), 'a qualified name starts with a letter')


def lib_name_10():
    for ok in ('default', 'a', 'acme-net', 'risk_eu', 'x' * 16):
        check(names.is_net_name(ok), f'{ok!r} is a valid net name')
    for bad in ('Acme', '1net', '-net', '_net', 'a__b', 'net_', 'x' * 17):
        check(not names.is_net_name(bad), f'{bad!r} is refused')
    check(names.net_name_or_default(None) == 'default', 'no net configured: default')


def lib_net_03():
    from sajha.net.conformance import vectors as V
    rec = dict(V.KEY_RECORD, net='other-net')
    v = _example_verified()
    check(keydir.acceptance_error(rec, 'acme-net', 'risk-eu', v.certificate) == 'net_mismatch',
          'a key record of another net is dropped')


def lib_sig_01():
    v = _example_verified()
    check(v.sender == 'risk-eu' and v.keyid == '_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ', 'the §21.1 request verifies')


def lib_sig_12():
    from sajha.net.conformance import vectors as V
    req_sig = httpsig.request_signature_bytes(V.HEADERS)
    h = {'content-type': 'application/json', 'sajha-net-version': '1', 'sajha-net-name': 'acme-net',
         'sajha-net-from': 'cust-na', 'sajha-net-to': 'risk-eu', 'content-digest': httpsig.content_digest(V.RESP_BODY)}
    pv = ('("@status" "content-type" "content-digest" "sajha-net-version" "sajha-net-name" "sajha-net-from" '
          f'"sajha-net-to" "signature";req;key="sajhanet");created={V.RESPONSE_CREATED};'
          f'keyid="{V.RESPONSE_KEYID}";alg="ed25519";tag="sajha-net-v1"')
    comps, params = sfv.parse_dict('sajhanet=' + pv)['sajhanet']
    covered = [(n, dict(p)) for n, p in comps]
    base = httpsig.signature_base(covered, sfv.ser_inner(comps, params), status=200, headers=h, req_signature=req_sig)
    sig = base64.b64decode(V.RESPONSE_SIGNATURE)
    pub = _seed_key('cust-na').public_key()
    check(crypto.verify_raw(pub, 'ed25519', base, sig), 'the §21.1 response verifies against its request')
    other = bytes([req_sig[0] ^ 1]) + req_sig[1:]
    base2 = httpsig.signature_base(covered, sfv.ser_inner(comps, params), status=200, headers=h, req_signature=other)
    check(not crypto.verify_raw(pub, 'ed25519', base2, sig), 'bound to its request')


def lib_sig_09():
    from sajha.net.conformance import vectors as V
    for bad in ('ed25519";x="', 'hmac-sha256', 'rsa-pss-sha512', 'ecdsa-p256-sha256'):
        h = dict(V.HEADERS)
        h['Signature-Input'] = V.SIG_INPUT.replace('alg="ed25519"', f'alg="{bad}"')
        try:
            _example_verified(h)
        except NetError as e:
            check(e.reason in ('signature_invalid', 'signature_missing'), f'alg {bad}: {e.reason}')
            continue
        raise CheckFailed(f'alg {bad} was accepted')
    h = dict(V.HEADERS)
    h['Signature-Input'] = V.SIG_INPUT.replace('_9toR0iCB', '_9toR0iCC')
    try:
        _example_verified(h)
        raise CheckFailed('a keyid that is not the leaf thumbprint was accepted')
    except NetError as e:
        check(e.reason == 'signature_invalid', f'keyid: {e.reason}')


def lib_sig_13():
    for alg in (crypto.ED25519, crypto.P256):
        k = crypto.generate_key(alg)
        sig = crypto.sign_raw(k, b'sajha')
        check(crypto.verify_raw(k.public_key(), alg, b'sajha', sig), f'{alg} raw signature verifies')
    k = crypto.generate_key(crypto.P256)
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    der = k.sign(b'sajha', ec.ECDSA(hashes.SHA256()))
    check(not crypto.verify_raw(k.public_key(), crypto.P256, b'sajha', der), 'a DER ECDSA signature is refused')


def lib_rec_01():
    from sajha.net.conformance import vectors as V
    pub = _example_verified().certificate.public_key()
    rec = {k: v for k, v in V.KEY_RECORD.items() if k != 'signature'}
    check(schemas.is_valid('key_record', V.KEY_RECORD), 'the §21.3 record is valid')
    check(crypto.verify_record('key', rec, V.KEY_RECORD['signature'], pub), 'it verifies')
    check(crypto.verify_record('key', dict(reversed(list(rec.items()))), V.KEY_RECORD['signature'], pub),
          'reordered, it verifies')
    check(not crypto.verify_record('key', dict(rec, version=43), V.KEY_RECORD['signature'], pub), 'a change fails')


def lib_rec_02():
    from sajha.net.conformance import vectors as V
    pub = _example_verified().certificate.public_key()
    rec = {k: v for k, v in V.KEY_RECORD.items() if k != 'signature'}
    check(not crypto.verify_record('member', rec, V.KEY_RECORD['signature'], pub), 'domain separation')


def lib_gos_05():
    from sajha.net.membership import decide_merge

    def e(inc, seq, state, leaving=False):
        return {'record': {'incarnation': inc, 'seq': seq, 'leaving': leaving}, 'state': state}
    table = [  # (held, incoming) -> (record incarnation and seq, state)
        (None, e(1, 0, 'alive'), (1, 0, 'alive')),
        (e(1, 0, 'alive'), e(2, 0, 'alive'), (2, 0, 'alive')),
        (e(2, 0, 'alive'), e(1, 5, 'dead'), (2, 0, 'alive')),
        (e(1, 0, 'alive'), e(1, 0, 'suspect'), (1, 0, 'suspect')),
        (e(1, 0, 'suspect'), e(1, 0, 'alive'), (1, 0, 'suspect')),
        (e(1, 0, 'alive'), e(1, 1, 'alive'), (1, 1, 'alive')),
        (e(1, 0, 'alive'), e(1, 0, 'left'), (1, 0, 'alive')),
        (e(1, 0, 'alive'), e(1, 1, 'left', True), (1, 1, 'left')),
        (e(1, 0, 'suspect'), e(2, 0, 'alive'), (2, 0, 'alive')),
    ]
    for held, inc, want in table:
        _a, rec, state = decide_merge(held, inc)
        got = (rec['incarnation'], rec['seq'], state)
        check(got == want, f'merge {held and (held["record"]["incarnation"], held["state"])} + '
                           f'{(inc["record"]["incarnation"], inc["record"]["seq"], inc["state"])}: {got} != {want}')


def lib_key_02():
    from sajha.net.conformance import vectors as V
    v = _example_verified()
    check(keydir.acceptance_error(V.KEY_RECORD, 'acme-net', 'cust-na', v.certificate) == 'not_home',
          'a record whose home is not the responder is ignored')
    bad = dict(V.KEY_RECORD, name='changed')
    check(keydir.acceptance_error(bad, 'acme-net', 'risk-eu', v.certificate) == 'signature_invalid',
          'a record with a bad signature is ignored')
    check(keydir.acceptance_error(V.KEY_RECORD, 'acme-net', 'risk-eu', v.certificate) is None, 'the record is accepted')


def lib_key_03():
    recs = [{'key_id': 'b', 'version': 2}, {'key_id': 'a', 'version': 1}]
    want = crypto.b64url(hashlib.sha256(b'[["a",1],["b",2]]').digest())
    check(keydir.digest_root(recs) == want, 'the digest root of §11.4')


def lib_rev_01():
    from sajha.net.ca import init_ca, CertificateAuthority
    from sajha.net.models import MemoryKV
    from sajha.net.trust import verify_revocation_list
    k, c = init_ca('acme-net')
    ca = CertificateAuthority('acme-net', k, c, MemoryKV())
    doc = ca.revoke(instance='gone')
    check(verify_revocation_list(doc, c, 'acme-net'), 'a CA-signed list verifies')
    check(not verify_revocation_list(dict(doc, net='other'), c, 'acme-net'), 'another net is ignored')
    k2, c2 = init_ca('acme-net')
    check(not verify_revocation_list(doc, c2, 'acme-net'), 'another CA\'s list is ignored')


def lib_cap_04():
    try:
        httpsig._version({'sajha-net-version': '99'}, SUPPORTED_VERSIONS)
        raise CheckFailed('version 99 was accepted')
    except NetError as e:
        check(e.reason == 'unsupported_version', e.reason)


def lib_gos_06():
    key = crypto.generate_key()
    cert = crypto.self_signed_certificate(key, 'acme-net', 'alpha', 'alpha.test')
    check(crypto.host_in_san(cert, 'alpha.test') and not crypto.host_in_san(cert, 'beta.test'),
          'the url host must be in the subject certificate')


LIBRARY: Dict[str, Callable[[], None]] = {
    'NAME-01': lib_name_01, 'NAME-02': lib_name_02, 'NAME-03': lib_name_03, 'NAME-05': lib_name_05,
    'NAME-10': lib_name_10, 'NET-03': lib_net_03, 'CAP-04': lib_cap_04, 'SIG-01': lib_sig_01, 'SIG-09': lib_sig_09,
    'SIG-12': lib_sig_12, 'SIG-13': lib_sig_13, 'REC-01': lib_rec_01, 'REC-02': lib_rec_02, 'GOS-05': lib_gos_05,
    'GOS-06': lib_gos_06, 'KEY-02': lib_key_02, 'KEY-03': lib_key_03, 'REV-01': lib_rev_01,
}


def run_library(ids: Optional[List[str]] = None) -> Report:
    """Target L: every case whose targets include L, against this process's protocol core."""
    rep = Report({'code': 'L', 'kind': 'library', 'url': 'library', 'net': 'acme-net'})
    for c in CASES:
        if ids and c.id not in ids:
            continue
        if 'L' not in c.targets.split():
            rep.results.append(Result(c.id, SKIP, 'not a library case (targets ' + c.targets + ')'))
            continue
        fn = LIBRARY.get(c.id)
        if fn is None:
            rep.results.append(Result(c.id, SKIP, 'covered by ' + (c.where or 'the remote cases')))
            continue
        try:
            fn()
            rep.results.append(Result(c.id, PASS))
        except CheckFailed as e:
            rep.results.append(Result(c.id, FAIL, str(e)))
        except Exception as e:
            rep.results.append(Result(c.id, FAIL, f'{e.__class__.__name__}: {e}'))
    return rep


# ── remote cases ────────────────────────────────────────────────────

class Answer:
    def __init__(self, suite: 'Suite', req_headers: Dict[str, str], status: int, headers: Dict[str, str], body: bytes):
        self.suite = suite
        self.req = req_headers
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body = body or b''
        try:
            self.json = json.loads(self.body.decode('utf-8')) if self.body else None
        except ValueError:
            self.json = None

    @property
    def reason(self) -> str:
        return str((self.json or {}).get('reason') or '') if isinstance(self.json, dict) else ''

    def verify(self, expected_sender: Optional[str] = None) -> Optional[str]:
        """None when the response is signed and verifies against its request, else why not."""
        s = self.suite
        own = self.req.get('sajha-net-from') or httpsig.ANY
        try:
            req_sig = httpsig.request_signature_bytes(self.req) if 'signature' in self.req else None
        except Exception:
            req_sig = None
        try:
            httpsig.verify_response(s.trust, own, expected_sender or s.instance or httpsig.ANY, self.status, self.headers,
                                    self.body, req_sig, now=s.clock(), max_age=s.max_age)
        except NetError as e:
            return e.reason
        except Exception as e:
            return f'{e.__class__.__name__}: {e}'
        return None

    def rpc_error(self) -> Dict[str, Any]:
        e = (self.json or {}).get('error') if isinstance(self.json, dict) else None
        return e if isinstance(e, dict) else {}

    def refusal(self) -> Dict[str, Any]:
        return ((self.rpc_error().get('data') or {}).get(EXTENSION_ID)) or {}


class Suite:
    """The remote cases against one target (see the module docstring)."""

    def __init__(self, url: str, net: str, *, connector: PeerConnector, signer: httpsig.Signer, trust: httpsig.Trust,
                 instance: str = '', mcp_path: str = '', clock: Callable[[], float] = time.time,
                 api_key: str = '', tool: str = '', max_age: float = 30, timeout: float = 10.0,
                 ca_mode: Optional[bool] = None):
        self.url = url.rstrip('/')
        self.net = net
        self.connector = connector
        self.signer = signer
        self.trust = trust
        self.name = crypto.subject_of(signer.chain[0])[1]
        self.instance = instance
        self.mcp_path = mcp_path
        self.clock = clock
        self.api_key = api_key
        self.tool = tool
        self.max_age = max_age
        self.timeout = timeout
        self.ca_mode = (len(signer.chain) and not _self_signed(signer.chain[0])) if ca_mode is None else ca_mode
        self.record: Dict[str, Any] = {}
        self.ext: Dict[str, Any] = {}
        self.kind = ''
        self.problems: List[Tuple[str, Answer]] = []        # every /sajhanet/ error seen (ERR-01)
        self.refusals: List[Tuple[str, Dict[str, Any]]] = []   # every MCP refusal seen (FB-01)
        self._catalog: Optional[Dict[str, Any]] = None

    # ── sending ─────────────────────────────────────────────────────

    def send(self, method: str, path: str, body: Any = None, *, raw: Optional[bytes] = None, to: Optional[str] = None,
             sender: Optional[str] = None, sign: bool = True, mcp: bool = False, created: Optional[float] = None,
             nonce: Optional[str] = None, version: int = 1, signer: Optional[httpsig.Signer] = None,
             extra: Optional[Dict[str, str]] = None, mutate: Optional[Callable] = None,
             headers: Optional[Dict[str, str]] = None, net: Optional[str] = None, record: bool = True) -> Answer:
        if raw is None:
            raw = b'' if method == 'GET' else json.dumps(body if body is not None else {}, separators=(',', ':')).encode()
        h = dict(headers or ({} if method == 'GET' else {'content-type': 'application/json'}))
        if sign:
            h = httpsig.sign_request(signer or self.signer, method, path, '', h, raw, net or self.net,
                                     sender or self.name, to or self.instance or httpsig.ANY, mcp=mcp,
                                     now=created if created is not None else self.clock(), nonce=nonce, version=version)
        h.update(extra or {})
        if mutate is not None:
            h, raw = mutate(dict(h), raw)
        try:
            r = self.connector.send(method, self.url + path, h, raw, self.timeout)
        except PeerUnreachable as e:
            raise CheckFailed(f'{path}: the target is unreachable ({e})')
        a = Answer(self, httpsig.lower_headers(h), r.status, r.headers, r.body)
        if record and path.startswith('/sajhanet/') and a.status >= 400 and a.body:
            self.problems.append((path, a))
        return a

    def mcp(self, method: str, params: Optional[Dict[str, Any]] = None, *, tool: str = '', hop: int = 1,
            visited: Optional[List[str]] = None, depth: int = 0, extra: Optional[Dict[str, str]] = None,
            mutate: Optional[Callable] = None, sign: bool = True) -> Answer:
        params = dict(params or {})
        if depth:
            params.setdefault('_meta', {})[EXTENSION_ID] = {'home': self.name, 'depth': depth}
        msg = {'jsonrpc': '2.0', 'id': secrets.randbelow(10 ** 6), 'method': method, 'params': params}
        visited = visited if visited is not None else [f'{self.net}/{self.name}']
        h = {'content-type': 'application/json', 'accept': 'application/json, text/event-stream',
             'mcp-protocol-version': MODERN, 'mcp-method': method,
             'sajha-net-hop': str(hop), 'sajha-net-visited': sfv.ser_list([(v, {}) for v in visited])}
        if tool:
            h['mcp-name'] = tool
        if not sign:
            h = {'content-type': 'application/json', 'accept': 'application/json, text/event-stream'}
        h.update(extra or {})
        a = self.send('POST', self.mcp_path or '/mcp', raw=json.dumps(msg).encode(), headers=h, mcp=True, sign=sign,
                      mutate=mutate)
        if a.refusal():
            self.refusals.append((method, a.refusal()))
        return a

    # ── discovery ───────────────────────────────────────────────────

    def discover(self) -> Dict[str, Any]:
        """Learn the target: a signed sync (``Sajha-Net-To`` its name, or ``*``) answers with its own
        member entry first; then its signed ``server/discover``."""
        a = self.send('POST', P + '/membership/sync', {'type': 'sync', 'reason': 'anti_entropy', 'members': []},
                      record=False)
        if a.status == 200 and isinstance(a.json, dict):
            why = a.verify(expected_sender=self.instance or httpsig.ANY)
            if why is not None:
                raise CheckFailed(f'the target\'s sync answer does not verify ({why})')
            own = next((e for e in a.json.get('members') or [] if (e.get('record') or {}).get('name') ==
                        a.headers.get('sajha-net-from')), None)
            if own is None:
                raise CheckFailed('the target\'s sync answer lacks its own entry')
            self.record = own['record']
            self.instance = self.record['name']
            self.members = [e for e in a.json.get('members') or []]
        elif not self.instance:
            raise CheckFailed(f'the target answered the sync with {a.status} {a.reason}; give its instance name')
        self.mcp_path = self.mcp_path or self.record.get('mcp_path') or '/mcp'
        d = self.mcp('server/discover')
        res = (d.json or {}).get('result') if isinstance(d.json, dict) else None
        self.ext = (((res or {}).get('capabilities') or {}).get('extensions') or {}).get(EXTENSION_ID) or {}
        self.kind = str(self.ext.get('kind') or self.record.get('kind') or '')
        return {'url': self.url, 'net': self.net, 'instance': self.instance, 'kind': self.kind,
                'code': {'sajha': 'S', 'sponsored': 'S', 'agent': 'A'}.get(self.kind, 'A'),
                'features': self.features, 'user_identity': list(self.record.get('user_identity') or []),
                'sponsor': self.record.get('sponsor') or self.ext.get('sponsor') or ''}

    @property
    def features(self) -> List[str]:
        return list(self.record.get('features') or self.ext.get('features') or [])

    def catalog(self) -> Dict[str, Any]:
        if self._catalog is None:
            a = self.send('POST', P + '/catalog', {})
            check(a.status == 200, f'catalog: {a.status} {a.reason}')
            check(a.verify() is None, f'the catalog answer does not verify ({a.verify()})')
            self._catalog = a.json
        return self._catalog

    def some_tool(self) -> str:
        if self.tool:
            return self.tool
        if 'catalog' in self.features:
            tools = self.catalog().get('tools') or []
            if tools:
                return tools[0]['name']
        return 'conformance_probe'

    def _expect_problem(self, a: Answer, status: int, reason: str, what: str) -> None:
        check(a.status == status and a.reason == reason, f'{what}: expected {status} {reason}, got {a.status} '
                                                         f'{a.reason or a.body[:80]!r}')

    def _ping(self, **kw) -> Answer:
        return self.send('POST', P + '/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': []}, **kw)

    # ── the cases ──────────────────────────────────────────────────

    def c_NAME_06(self):
        if self.ca_mode:
            raise NotApplicable('the CA issues no certificate for a held name; covered by tests/net/test_net_ca.py')
        held = next((e['record']['name'] for e in getattr(self, 'members', []) if e['record']['name'] not in
                     (self.instance, self.name)), None)
        if held is None:
            raise NotApplicable('the target knows no other member whose name could be claimed')
        key = crypto.generate_key()
        cert = crypto.self_signed_certificate(key, self.net, held, 'conformance.invalid')
        a = self._ping(signer=httpsig.Signer(key, [cert]), sender=held)
        self._expect_problem(a, 409, 'name_conflict', f'a new key claiming {held}')

    def c_NET_01(self):
        def unsigned(extra):
            h = {'content-type': 'application/json', 'sajha-net-version': '1', **extra}
            return self.send('POST', P + '/gossip/ping', raw=b'{"type":"ping","seq":1,"updates":[]}', sign=False,
                             headers=h, record=False)
        for what, extra in (('no Sajha-Net-Name', {}), ('an invalid net name', {'sajha-net-name': 'Bad__Net'}),
                            ('a net the target is not in', {'sajha-net-name': 'zz-not-a-net'})):
            a = unsigned(extra)
            check(a.status == 404 and not a.body and 'signature' not in a.headers, f'{what}: expected an unsigned '
                                                                                 f'404 with no body, got {a.status}')
        a = self._ping()
        check(a.headers.get('sajha-net-name') == self.net, 'responses carry Sajha-Net-Name')
        covered = a.headers.get('signature-input', '')
        check('"sajha-net-name"' in covered, 'Sajha-Net-Name is covered by the response signature')

    def c_NET_04(self):
        check(self.ext.get('net') == self.net and self.ext.get('instance') == self.instance,
              f'a signed discover shows this net\'s net and instance ({self.ext.get("net")}, {self.ext.get("instance")})')

    def c_CAP_01(self):
        check(self.ext, 'server/discover carries capabilities.extensions["io.sajha/net"]')
        errs = schemas.errors('extension', self.ext)
        check(not errs, f'the extension object is valid ({errs[:1]})')

    def c_CAP_02(self):
        a = self.mcp('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                                    'clientInfo': {'name': 'sajhanet-conformance', 'version': '1'}})
        res = (a.json or {}).get('result') or {}
        ext = ((res.get('capabilities') or {}).get('experimental') or {}).get(EXTENSION_ID)
        check(isinstance(ext, dict), 'initialize carries capabilities.experimental["io.sajha/net"]')
        check(not schemas.errors('extension', ext) and ext.get('instance') == self.instance,
              'the same object as server/discover')

    def c_CAP_03(self):
        a = self.mcp('server/discover', sign=False)
        if a.status != 200 or not isinstance(a.json, dict) or 'result' not in a.json:
            raise NotApplicable(f'the MCP endpoint does not answer an unsigned discover here ({a.status})')
        ext = ((a.json['result'].get('capabilities') or {}).get('extensions') or {}).get(EXTENSION_ID)
        check(isinstance(ext, dict), 'an unsigned discover carries the extension')
        check(set(ext) <= {'protocol_versions', 'endpoint'}, f'an unsigned discover carries only protocol_versions and '
                                                             f'endpoint ({sorted(ext)})')

    def c_CAP_04(self):
        a = self._ping(version=99)
        self._expect_problem(a, 400, 'unsupported_version', 'Sajha-Net-Version 99')
        check(list((a.json or {}).get('supported_versions') or []), 'the supported versions are listed')
        m = self.mcp('tools/list', mutate=lambda h, b: (dict(h, **{'sajha-net-version': '99'}), b))
        # a changed covered header fails the signature first unless the version is checked before it (§8.7 step 3)
        code = m.rpc_error().get('code')
        check(code == -32017, f'version 99 on the MCP endpoint: -32017 (got {code})')

    def c_CAP_05(self):
        from sajha.net.node import ROUTES
        tried = 0
        for path, (method, feature, _schema, _limit, signed) in ROUTES.items():
            if feature is None or feature in self.features or not signed:
                continue
            body = None if method == 'GET' else {}
            a = self.send(method, path, body, record=False)
            check(a.status == 404 and not a.body, f'{path} (feature {feature} not listed): expected 404, got {a.status}')
            tried += 1
        check(tried, 'no unlisted feature to try')

    def c_SIG_02(self):
        def strip(name):
            def m(h, b):
                h.pop(name, None)
                return h, b
            return m
        for name in ('signature', 'signature-input', 'sajha-net-certificate'):
            a = self._ping(mutate=strip(name))
            self._expect_problem(a, 401, 'signature_missing', f'without {name}')

    def c_SIG_03(self):
        a = self._ping(mutate=lambda h, b: (h, b.replace(b'"seq":1', b'"seq":2')))
        self._expect_problem(a, 401, 'digest_mismatch', 'one changed body byte')

    def c_SIG_04(self):
        for name, value in (('sajha-net-from', 'someone-else'), ('sajha-net-to', 'someone-else'),
                            ('content-type', 'application/json; charset=utf-8')):
            a = self._ping(mutate=lambda h, b, n=name, v=value: (dict(h, **{n: v}), b))
            self._expect_problem(a, 401, 'signature_invalid', f'a changed {name}')

    def c_SIG_05(self):
        a = self._ping(created=self.clock() - 3600)
        self._expect_problem(a, 401, 'signature_expired', 'created an hour ago')
        a = self._ping(created=self.clock() + 60)
        self._expect_problem(a, 401, 'signature_expired', 'created a minute ahead')

    def c_SIG_06(self):
        nonce = httpsig.new_nonce()
        bad = self._ping(nonce=nonce, mutate=lambda h, b: (h, b.replace(b'"seq":1', b'"seq":3')))
        self._expect_problem(bad, 401, 'digest_mismatch', 'a failing request')
        ok = self._ping(nonce=nonce)
        check(ok.status == 200, f'a request that failed verification does not consume its nonce (got {ok.status})')
        again = self._ping(nonce=nonce)
        self._expect_problem(again, 401, 'replay', 'the same nonce twice')

    def c_SIG_07(self):
        if not self.ca_mode:
            raise NotApplicable('the target admits self-signed certificates (admission: open or manual)')
        key = crypto.generate_key()
        other_key, other_ca = _other_ca(self.net)
        cert = crypto.issue_certificate(other_key, other_ca, key.public_key(), self.net, self.name, 'conformance.invalid')
        a = self._ping(signer=httpsig.Signer(key, [cert]))
        self._expect_problem(a, 401, 'certificate_invalid', 'a certificate from another CA')

    def c_SIG_09(self):
        def keyid(h, b):
            h['signature-input'] = h['signature-input'].replace(f'keyid="{self.signer.keyid}"',
                                                                f'keyid="{"A" * 43}"')
            return h, b
        a = self._ping(mutate=keyid)
        self._expect_problem(a, 401, 'signature_invalid', 'a keyid that is not the leaf thumbprint')
        for alg in ('hmac-sha256', 'rsa-pss-sha512'):
            a = self._ping(mutate=lambda h, b, al=alg: (dict(h, **{'signature-input': h['signature-input'].replace(
                f'alg="{self.signer.alg}"', f'alg="{al}"')}), b))
            self._expect_problem(a, 401, 'signature_invalid', f'alg {alg}')

    def c_SIG_10(self):
        a = self._ping(sender='someone-else')
        self._expect_problem(a, 401, 'from_mismatch', 'Sajha-Net-From not the certificate CN')
        a = self._ping(to='someone-else')
        check(a.status == 421, f'Sajha-Net-To not the receiver: expected 421, got {a.status}')

    def c_SIG_11(self):
        raw = b'{"type":"ping","seq":1,"updates":[]}'
        h = {'content-type': 'application/json', 'content-digest': httpsig.content_digest(raw),
             'sajha-net-version': '1', 'sajha-net-name': self.net, 'sajha-net-from': self.name,
             'sajha-net-to': self.instance}
        comps = [('@method', {}), ('@path', {}), ('@query', {}), ('content-type', {}),
                 ('sajha-net-version', {}), ('sajha-net-name', {}), ('sajha-net-from', {}), ('sajha-net-to', {})]
        params = {'created': int(self.clock()), 'nonce': httpsig.new_nonce(), 'keyid': self.signer.keyid,
                  'alg': self.signer.alg, 'tag': 'sajha-net-v1'}
        pv = httpsig.signature_params(comps, params)
        base = httpsig.signature_base(comps, pv, method='POST', path=P + '/gossip/ping', query='', headers=h)
        sig = crypto.sign_raw(self.signer.key, base)
        h['sajha-net-certificate'] = self.signer.certificate_header()
        h['signature-input'] = f'sajhanet={pv}'
        h['signature'] = f'sajhanet={sfv.ser_bare(sig)}'
        a = self.send('POST', P + '/gossip/ping', raw=raw, headers=h, sign=False)
        self._expect_problem(a, 401, 'signature_incomplete', 'a signature not covering content-digest')

    def c_SIG_12(self):
        a = self._ping()
        check(a.status == 200, f'ping: {a.status} {a.reason}')
        check(a.verify() is None, f'the response verifies against its request ({a.verify()})')
        b = self._ping()
        req_b = b.req
        b.req = a.req                                        # the answer to another request must not verify
        check(b.verify() is not None, 'a response does not verify against another request')
        b.req = req_b

    def c_SIG_15(self):
        a = self._ping(extra={'sec-fetch-mode': 'navigate'}, record=False)
        check(a.status == 404 and not a.body, f'Sec-Fetch-Mode: navigate: expected 404, got {a.status}')
        a = self._ping(extra={'origin': 'https://evil.example'})
        check(not any(k.startswith('access-control-') for k in a.headers), 'no CORS headers')

    def c_GOS_01(self):
        a = self.send('POST', P + '/gossip/ping', {'type': 'ping', 'seq': 4242, 'updates': []})
        check(a.status == 200 and a.verify() is None, f'a ping gets a signed ack ({a.status}, {a.verify()})')
        check(schemas.is_valid('ack', a.json) and a.json.get('seq') == 4242, 'the ack is valid and echoes seq')

    def c_GOS_02(self):
        a = self.send('POST', P + '/gossip/ping-req', {'type': 'ping-req', 'seq': 1, 'target': 'no-such-member-x',
                                                       'updates': []})
        self._expect_problem(a, 400, 'unknown_member', 'ping-req for an unknown member')

    def c_GOS_06(self):
        key = crypto.generate_key()
        cert = crypto.self_signed_certificate(key, self.net, 'ghost-member', 'conformance.invalid')
        rec = {'type': 'member', 'net': self.net, 'name': 'ghost-member', 'url': 'https://conformance.invalid',
               'mcp_path': '/mcp', 'kind': 'agent', 'protocol_versions': [1], 'features': [], 'user_identity': ['none'],
               'incarnation': 1, 'seq': 0, 'digests': {'catalog': 'none', 'keys': 0, 'blocks': 0, 'revocations': 0},
               'leaving': False, 'issued_at': crypto.rfc3339(self.clock())}
        forged = {'record': rec, 'signature': crypto.sign_record('member', rec, self.signer.key, self.signer.keyid),
                  'certificate': [crypto.b64(crypto.cert_der(self.signer.chain[0]))], 'state': 'alive'}
        a = self.send('POST', P + '/membership/sync', {'type': 'sync', 'reason': 'anti_entropy', 'members': [forged]})
        check(a.status == 200, f'sync: {a.status} {a.reason}')
        names_ = [e['record']['name'] for e in (a.json or {}).get('members') or []]
        check('ghost-member' not in names_, 'a member record signed by anyone but its subject is dropped')
        del cert

    def c_GOS_08(self):
        a = self.send('POST', P + '/membership/sync', {'type': 'sync', 'reason': 'join', 'members': []})
        check(a.status == 200 and schemas.is_valid('sync', a.json), f'a join sync answers a valid list ({a.status})')
        states = {e['state'] for e in a.json['members']}
        check(a.json['members'][0]['record']['name'] == self.instance, 'the responder\'s own entry comes first')
        check(states <= {'alive', 'suspect', 'dead', 'left'}, 'every entry has a state')

    def c_CAT_01(self):
        cat = self.catalog()
        errs = schemas.errors('catalog_response', dict(cat, tools=cat.get('tools') or []))
        check(not errs, f'the catalog is valid ({errs[:1]})')
        for t in cat.get('tools') or []:
            meta = (t.get('_meta') or {}).get(EXTENSION_ID) or {}
            check(not schemas.errors('tool_net_meta', meta), f'{t.get("name")}: _meta["io.sajha/net"] is valid')
            check(meta.get('instance') == self.instance and meta.get('net') == self.net, f'{t.get("name")}: net and '
                                                                                         f'instance')

    def c_CAT_02(self):
        cat = self.catalog()
        tools = cat.get('tools') or []
        check(cat.get('hash') == catalog_hash(tools), 'the catalog hash is computed as §10.2 says')
        a = self.send('POST', P + '/catalog', {'if_none_match': cat['hash']})
        check(a.status == 200 and a.json.get('unchanged') is True and 'tools' not in a.json,
              'if_none_match equal to the hash: unchanged without tools')

    def c_CAT_03(self):
        cat = self.catalog()
        a = self.mcp('tools/list')
        res = (a.json or {}).get('result') or {}
        check(a.verify() is None, f'the signed tools/list answer verifies ({a.verify()})')
        mine = sorted(t['name'] for t in res.get('tools') or [])
        check(mine == sorted(t['name'] for t in cat.get('tools') or []), 'a signed tools/list returns the catalog\'s '
                                                                         'tools')

    def c_CAT_05(self):
        raise NotApplicable('visibility is not built')

    def c_CAT_06(self):
        for t in self.catalog().get('tools') or []:
            meta = (t.get('_meta') or {}).get(EXTENSION_ID) or {}
            plain = copy.deepcopy(t)
            check(meta.get('contract_hash') == contract_hash(plain), f'{t["name"]}: contract_hash as §10.2')
            check('inputSchema' in t and 'name' in t, f'{t["name"]}: a complete tool definition')
            if 'version' in meta:
                check(isinstance(meta['version'], str), f'{t["name"]}: version is informational text')

    def _keys(self, since=0, limit=1000) -> Answer:
        return self.send('POST', P + '/keys', {'since': since, 'limit': limit})

    def c_KEY_01(self):
        a = self._keys(0, 1)
        check(a.status == 200 and schemas.is_valid('keys_response', a.json), f'a delta pull answers ({a.status})')
        check(a.json['home_instance'] == self.instance, 'the responder\'s own records')
        recs, since, pages = [], 0, 0
        while pages < 1000:
            a = self._keys(since, 1)
            recs += a.json['records']
            pages += 1
            if not a.json['more']:
                break
            check('next_since' in a.json, 'more: true carries next_since')
            since = a.json['next_since']
        vs = [r['version'] for r in recs]
        check(vs == sorted(vs) and all(v > 0 for v in vs), 'ascending versions above since')

    def c_KEY_03(self):
        recs, since = [], 0
        for _ in range(1000):
            a = self._keys(since, 1000)
            check(a.status == 200, f'keys: {a.status}')
            recs += a.json['records']
            if not a.json['more']:
                break
            since = a.json['next_since']
        d = self.send('POST', P + '/keys/digest', {})
        check(d.status == 200 and schemas.is_valid('keys_digest_response', d.json), f'the digest answers ({d.status})')
        check(d.json['root'] == keydir.digest_root(recs) and d.json['count'] == len(recs),
              'the digest root is computed as §11.4')

    def c_KEY_04(self):
        a = self._keys(0, 1000)
        for r in a.json.get('records') or []:
            check(not ({'key', 'raw_key', 'api_key'} & set(r)), f'{r.get("key_id")}: no raw key')
            kh = str(r.get('key_hash') or '')
            check(len(kh) == 64 and kh == kh.lower() and all(c in '0123456789abcdef' for c in kh),
                  f'{r.get("key_id")}: key_hash is lowercase hex SHA-256')
            if r.get('revoked_at'):
                check(not r.get('enabled'), f'{r.get("key_id")}: a deleted key is disabled')

    def c_BLK_01(self):
        a = self.send('POST', P + '/blocks', {})
        check(a.status == 200 and schemas.is_valid('blocks_document', a.json), f'the blocks document ({a.status})')
        doc = a.json
        check(doc['instance'] == self.instance and doc['net'] == self.net, 'its publisher and net')
        sig = doc['signature']
        body = {k: v for k, v in doc.items() if k != 'signature'}
        cert = self._target_cert(a)
        check(crypto.verify_record('blocks', body, sig, cert.public_key()), 'signed by its publisher')
        want = int((self.record.get('digests') or {}).get('blocks') or 0)
        check(int(doc['version']) == want, f'version {doc["version"]} equals digests.blocks {want}')
        now = self.clock()
        for b in doc.get('blocks') or []:
            if b.get('expires_at'):
                check(crypto.parse_rfc3339(b['expires_at']) > now, 'expired blocks are omitted')

    def _target_cert(self, a: Answer):
        items = sfv.parse_list(a.headers.get('sajha-net-certificate', ''))
        return crypto.load_cert(items[0][0])

    def c_REV_01(self):
        a = self.send('GET', P + '/revocations', record=False)
        if a.status == 503 and a.reason == 'unavailable':
            raise NotApplicable('the target holds no revocation list (no CA in this net, or none issued yet)')
        check(a.status == 200 and schemas.is_valid('revocation_list', a.json), f'the revocation list ({a.status})')
        check(a.json['net'] == self.net, 'for this net')
        ca = getattr(self.trust, 'ca', None)
        if ca is not None:
            from sajha.net.trust import verify_revocation_list
            check(verify_revocation_list(a.json, ca, self.net), 'signed by the net\'s CA')

    def _call(self, **kw) -> Answer:
        tool = kw.pop('tool', None) or self.some_tool()
        return self.mcp('tools/call', {'name': tool, 'arguments': kw.pop('arguments', {})}, tool=tool, **kw)

    def _refused(self, a: Answer, code: int, reason: str, what: str) -> None:
        e = a.rpc_error()
        r = a.refusal()
        check(e.get('code') == code and r.get('reason') == reason,
              f'{what}: expected {code} {reason}, got {e.get("code")} {r.get("reason") or e.get("message")}')
        check(r.get('executed') is False, f'{what}: executed is false')
        check(a.verify() is None, f'{what}: the refusal is signed ({a.verify()})')

    def c_CALL_01(self):
        if not self.api_key:
            raise NotApplicable('give --api-key: a key of a user of the runner\'s home that the target accepts')
        a = self._call(extra={'sajha-net-api-key': self.api_key})
        check(a.verify() is None, 'the answer verifies')
        res = (a.json or {}).get('result')
        check(isinstance(res, dict), f'the call runs as the key\'s user ({a.rpc_error().get("message")})')

    def c_CALL_03(self):
        if 'api_key' not in (self.record.get('user_identity') or []):
            raise NotApplicable('the target does not list the api_key identity')
        a = self._call(extra={'sajha-net-api-key': 'sja_conformance_' + secrets.token_urlsafe(24)})
        self._refused(a, -32013, 'key_unknown', 'an unknown key')

    def c_CALL_04(self):
        if self.url.startswith('https://'):
            raise NotApplicable('the target is reached over HTTPS')
        if 'api_key' not in (self.record.get('user_identity') or []):
            raise NotApplicable('the target does not list the api_key identity')
        a = self._call(extra={'sajha-net-api-key': 'sja_conformance_' + secrets.token_urlsafe(24)})
        r = a.refusal()
        check(r.get('reason') in ('https_required', 'key_unknown'), f'a key over plain HTTP: {r.get("reason")}')

    def c_CALL_05(self):
        a = self._call(extra={'authorization': 'Bearer conformance'})
        self._refused(a, -32013, 'ambiguous_credentials', 'a signed call also carrying Authorization')
        a = self._call(extra={'x-api-key': 'sja_conformance'})
        self._refused(a, -32013, 'ambiguous_credentials', 'a signed call also carrying X-API-Key')
        a = self._call(mutate=lambda h, b: (h, b.replace(b'"tools/call"', b'"tools/call" ')))
        check('result' not in (a.json or {}), 'a request with Sajha-Net-* headers and a bad signature is never served')

    def c_CALL_08(self):
        me = f'{self.net}/{self.name}'
        a = self._call(hop=9, visited=[f'{self.net}/x{i}' for i in range(8)] + [me])
        self._refused(a, -32016, 'hop_limit', 'hop 9')
        a = self._call(hop=1, visited=[f'{self.net}/{self.instance}'])
        self._refused(a, -32016, 'loop', 'the receiver in the visited list')
        a = self._call(hop=1, visited=[f'{self.net}/someone-else'])
        self._refused(a, -32016, 'hop_inconsistent', 'a last visited entry other than the sender')
        a = self._call(depth=40)
        self._refused(a, -32016, 'chain_limit', 'hop plus depth over the maximum')

    def c_FB_01(self):
        if not self.refusals:
            self.c_CALL_05()
        for method, r in self.refusals:
            if r.get('reason') == 'residency_result':
                check(r.get('executed') is True, 'residency_result carries executed: true')
            else:
                check(r.get('executed') is False, f'{r.get("reason")}: a refusal before execution carries executed: '
                                                  f'false')

    def c_ERR_01(self):
        if not self.problems:
            self.c_SIG_03()
        for path, a in self.problems:
            check(a.headers.get('content-type', '').split(';')[0] == 'application/problem+json',
                  f'{path} {a.status}: application/problem+json')
            check(schemas.is_valid('problem', a.json), f'{path} {a.status}: valid against problem')
            # signed by a participant of the net (a request whose Sajha-Net-To was changed may be answered by
            # the participant that shares the address, e.g. a sponsored participant's sponsor)
            why = a.verify(expected_sender=httpsig.ANY)
            check(why is None, f'{path} {a.status} {a.reason}: signed ({why})')

    def c_LIM_01(self):
        big = json.dumps({'type': 'ping', 'seq': 1, 'updates': [], 'pad': 'x' * (65 * 1024)}).encode()
        a = self.send('POST', P + '/gossip/ping', raw=big)
        check(a.status == 413, f'a body over the limit: expected 413, got {a.status}')
        a = self._ping(extra={'x-pad': 'y' * (17 * 1024)})
        check(a.status == 413, f'headers over the limit: expected 413, got {a.status}')

    # ── running ────────────────────────────────────────────────────

    def run(self, ids: Optional[List[str]] = None, code: Optional[str] = None) -> Report:
        try:
            target = self.discover()
        except CheckFailed as e:
            rep = Report({'url': self.url, 'net': self.net, 'code': code or '?', 'kind': '?'})
            rep.results.append(Result('DISCOVER', FAIL, str(e)))
            return rep
        if code:
            target['code'] = code
        rep = Report(target)
        order = [c for c in CASES if not ids or c.id in ids]
        # ERR-01 and FB-01 look at what the other cases saw: run them last
        order = [c for c in order if c.id not in ('ERR-01', 'FB-01')] + [c for c in order if c.id in ('ERR-01', 'FB-01')]
        for c in order:
            rep.results.append(self._one(c, target))
        rep.results.sort(key=lambda r: CASES.index(BY_ID[r.id]) if r.id in BY_ID else -1)
        return rep

    def _one(self, c: Case, target: Dict[str, Any]) -> Result:
        code = target['code']
        if code not in c.targets.split():
            return Result(c.id, SKIP, f'not for target {code} (targets {c.targets})')
        if c.feature and c.feature not in self.features:
            return Result(c.id, SKIP, f'the target does not advertise {c.feature}')
        if c.how != 'remote':
            if c.how == 'library':
                return Result(c.id, SKIP, 'a library case: run with --target library')
            return Result(c.id, SKIP, f'in-process only: {c.where}')
        fn = getattr(self, 'c_' + c.id.replace('-', '_'), None)
        if fn is None:
            return Result(c.id, SKIP, 'no remote check')
        try:
            fn()
            return Result(c.id, PASS)
        except NotApplicable as e:
            return Result(c.id, SKIP, str(e))
        except CheckFailed as e:
            return Result(c.id, FAIL, str(e))
        except Exception as e:
            return Result(c.id, FAIL, f'{e.__class__.__name__}: {e}')


def _self_signed(cert) -> bool:
    try:
        return cert.issuer == cert.subject
    except Exception:
        return False


def _other_ca(net: str):
    from sajha.net.ca import init_ca
    return init_ca(net)


def run(url: str, net: str, **kw) -> Report:
    """Run the suite against the participant at ``url`` (``library``: target L)."""
    if url == 'library':
        return run_library(kw.get('ids'))
    ids = kw.pop('ids', None)
    code = kw.pop('code', None)
    return Suite(url, net, **kw).run(ids, code)
