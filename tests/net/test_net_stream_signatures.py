# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Signed event streams (protocol §8.9, §21.4; conformance SIG-14): an independent reference
implementation of the event chain, the §21.4 vectors it produces, and every mutation a home must
refuse.

The reference below is written from the specification alone, with its own canonical JSON and
direct Ed25519 calls, so it does not share code with ``sajha.net.httpsig``:

    c0    = SHA-256("sajha-net-v1:stream:" || request signature bytes)
    c_i   = SHA-256(c_(i-1) || uint32_be(i) || JCS(event_i without event_signature))
    sig_i = Ed25519(host key, "sajha-net-v1:event:" || c_i)

and the final message (seq n) carries ``stream: {seq: n, chain: hex(c_(n-1))}`` inside its signed
object, with the §8.9 ``response_signature`` over it. The transcript digest is
``c_n`` over the final message without ``response_signature``.

The cross-checks against the library's ``httpsig.EventChain`` skip, with a reason, while that class
does not exist.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import struct

import pytest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519

from sajha.net.conformance import vectors as V

EXT = 'io.sajha/net'


# ── the reference implementation (from the specification only) ─────────

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b'=').decode('ascii')


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def _key(label: str) -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.from_private_bytes(hashlib.sha256(f'sajha-net example: {label}'.encode()).digest())


def _thumb(der: bytes) -> str:
    return _b64url(hashlib.sha256(der).digest())


def ref_jcs(v) -> bytes:
    """RFC 8785 for the values the vectors use: strings, booleans, null, integers, finite doubles."""
    def num(x):
        if isinstance(x, int):
            return str(x)
        if not math.isfinite(x):
            raise ValueError('not I-JSON')
        if x == int(x) and abs(x) < 1e21:
            return str(int(x))
        r = repr(x)
        if 'e' in r or 'E' in r:
            raise ValueError('exponent form is outside what this reference needs')
        return r

    def s(x):
        return json.dumps(x, ensure_ascii=False)

    def enc(x):
        if x is None:
            return 'null'
        if x is True:
            return 'true'
        if x is False:
            return 'false'
        if isinstance(x, (int, float)):
            return num(x)
        if isinstance(x, str):
            return s(x)
        if isinstance(x, list):
            return '[' + ','.join(enc(i) for i in x) + ']'
        if isinstance(x, dict):
            keys = sorted(x, key=lambda k: k.encode('utf-16-be'))
            return '{' + ','.join(s(k) + ':' + enc(x[k]) for k in keys) + '}'
        raise TypeError(type(x))
    return enc(v).encode('utf-8')


def _event_ext(ev: dict) -> dict:
    return ev['params']['_meta'][EXT]


def _final_ext(msg: dict) -> dict:
    return msg['error']['data'][EXT] if 'error' in msg else msg['result']['_meta'][EXT]


def without(msg: dict, member: str, final: bool) -> dict:
    """The object that is hashed and signed: ``member`` removed, the objects that held it kept."""
    m = copy.deepcopy(msg)
    try:
        (_final_ext(m) if final else _event_ext(m)).pop(member, None)
    except (KeyError, TypeError):
        pass
    return m


def c0(request_signature: bytes) -> bytes:
    return hashlib.sha256(b'sajha-net-v1:stream:' + request_signature).digest()


def link(prev: bytes, seq: int, obj: dict) -> bytes:
    return hashlib.sha256(prev + struct.pack('>I', seq) + ref_jcs(obj)).digest()


def ref_sign_event(key, keyid: str, prev: bytes, seq: int, event: dict):
    """(the signed event, c_seq)."""
    out = copy.deepcopy(event)
    slot = out.setdefault('params', {}).setdefault('_meta', {}).setdefault(EXT, {})   # stays, even empty
    c = link(prev, seq, without(out, 'event_signature', False))
    slot['event_signature'] = {'alg': 'ed25519', 'keyid': keyid, 'seq': seq,
                               'sig': _b64url(key.sign(b'sajha-net-v1:event:' + c))}
    return out, c


def ref_sign_final(key, keyid: str, prev: bytes, seq: int, final: dict, nonce: str):
    """(the signed final message, transcript digest c_seq)."""
    m = copy.deepcopy(final)
    _final_ext(m)['stream'] = {'seq': seq, 'chain': prev.hex()}
    sig = key.sign(f'sajha-net-v1:response:{nonce}:'.encode('ascii') + ref_jcs(m))
    transcript = link(prev, seq, m)
    _final_ext(m)['response_signature'] = {'alg': 'ed25519', 'keyid': keyid, 'sig': _b64url(sig),
                                           'request_nonce': nonce}
    return m, transcript


class Refused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class RefHome:
    """What a home does with a stream after its headers verified (§8.9): one event at a time."""

    NOTIFICATIONS = ('notifications/progress', 'notifications/message')

    def __init__(self, request_signature: bytes, nonce: str, request_id, public_key, keyid: str):
        self.prev = c0(request_signature)
        self.seq = 0
        self.nonce = nonce
        self.id = request_id
        self.pub = public_key
        self.keyid = keyid
        self.relayed = []
        self.transcript = None

    def _sig_ok(self, sig_b64: str, data: bytes) -> bool:
        try:
            self.pub.verify(_unb64url(sig_b64), data)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def event(self, ev) -> None:
        if not isinstance(ev, dict) or ev.get('jsonrpc') != '2.0':
            raise Refused('event_invalid')
        if 'id' in ev:
            return self.final(ev)
        if ev.get('method') not in self.NOTIFICATIONS or not isinstance(ev.get('params'), dict):
            raise Refused('event_invalid')
        try:
            es = _event_ext(ev)['event_signature']
        except (KeyError, TypeError):
            raise Refused('event_invalid')
        if not isinstance(es, dict) or es.get('alg') != 'ed25519' or es.get('keyid') != self.keyid:
            raise Refused('event_invalid')
        if es.get('seq') != self.seq + 1:
            raise Refused('event_order')
        c = link(self.prev, self.seq + 1, without(ev, 'event_signature', False))
        if not self._sig_ok(str(es.get('sig') or ''), b'sajha-net-v1:event:' + c):
            raise Refused('event_invalid')
        self.prev, self.seq = c, self.seq + 1
        self.relayed.append(ev)

    def final(self, msg) -> dict:
        if msg.get('id') != self.id:
            raise Refused('event_invalid')
        try:
            ext = _final_ext(msg)
        except (KeyError, TypeError):
            raise Refused('stream_truncated')
        st = ext.get('stream')
        if not isinstance(st, dict) or st.get('seq') != self.seq + 1 or st.get('chain') != self.prev.hex():
            raise Refused('stream_truncated')
        rs = ext.get('response_signature')
        if not isinstance(rs, dict) or rs.get('request_nonce') != self.nonce or rs.get('keyid') != self.keyid:
            raise Refused('response_invalid')
        body = without(msg, 'response_signature', True)
        if not self._sig_ok(str(rs.get('sig') or ''), f'sajha-net-v1:response:{self.nonce}:'.encode() + ref_jcs(body)):
            raise Refused('response_invalid')
        self.transcript = link(self.prev, self.seq + 1, body)
        return msg

    def end(self) -> None:
        """The stream closed: without a verified final message it is truncated."""
        if self.transcript is None:
            raise Refused('stream_truncated')


# ── the §21.4 inputs ────────────────────────────────────────────────────

HOST_CERT = x509.load_der_x509_certificate(base64.b64decode(V.STREAM_HOST_CERT))
HOST_KEY = _key('cust-na')
HOST_KEYID = _thumb(base64.b64decode(V.STREAM_HOST_CERT))


def _req_sig() -> bytes:
    from sajha.net import sfv
    return sfv.parse_dict(V.STREAM_HEADERS['Signature'])['sajhanet'][0]


def _events():
    """The three unsigned events and the unsigned final message of §21.4."""
    tok = V.STREAM_PROGRESS_TOKEN
    evs = [
        {'jsonrpc': '2.0', 'method': 'notifications/progress',
         'params': {'progressToken': tok, 'progress': 1, 'total': 3, 'message': 'loading positions'}},
        {'jsonrpc': '2.0', 'method': 'notifications/message',
         'params': {'level': 'info', 'logger': 'var_calc', 'data': '1240 positions loaded'}},
        {'jsonrpc': '2.0', 'method': 'notifications/progress',
         'params': {'progressToken': tok, 'progress': 2, 'total': 3, 'message': 'simulating'}},
    ]
    final = json.loads(V.RESP_BODY)
    final['id'] = 8
    return evs, final


def reference_stream():
    """(signed events, signed final, [c0..c3], transcript) computed by the reference."""
    evs, final = _events()
    prev = c0(_req_sig())
    chain = [prev]
    signed = []
    for i, ev in enumerate(evs, start=1):
        s, prev = ref_sign_event(HOST_KEY, HOST_KEYID, prev, i, ev)
        signed.append(s)
        chain.append(prev)
    fin, transcript = ref_sign_final(HOST_KEY, HOST_KEYID, prev, len(evs) + 1, final, V.STREAM_NONCE)
    return signed, fin, chain, transcript


def _home():
    return RefHome(_req_sig(), V.STREAM_NONCE, 8, HOST_KEY.public_key(), HOST_KEYID)


def _run(events, final, *, end=True):
    h = _home()
    for ev in events:
        h.event(ev)
    if final is not None:
        h.event(final)
    if end:
        h.end()
    return h


# ── the vectors ─────────────────────────────────────────────────────────

def test_the_host_certificate_is_the_example_cas_cust_na():
    from sajha.net import crypto
    ca = crypto.load_cert(base64.b64decode(V.CA_B64))
    crypto.verify_chain([HOST_CERT], ca, V.T0)
    assert crypto.subject_of(HOST_CERT) == ('acme-net', 'cust-na')
    assert HOST_KEYID == V.RESPONSE_KEYID          # the responder of §21.1 is this certificate
    pub = HOST_CERT.public_key()
    assert pub.public_bytes_raw() == HOST_KEY.public_key().public_bytes_raw()


def test_the_request_verifies_and_asks_for_a_stream():
    from sajha.net import httpsig
    from sajha.net.conformance import _ExampleTrust
    v = httpsig.verify_request(_ExampleTrust(), 'cust-na', 'POST', '/mcp', '', V.STREAM_HEADERS, V.STREAM_BODY,
                               mcp=True, now=V.T0)
    assert v.sender == 'risk-eu'
    body = json.loads(V.STREAM_BODY)
    meta = body['params']['_meta']
    assert meta[EXT]['stream'] == 1 and meta['progressToken'] == V.STREAM_PROGRESS_TOKEN
    assert meta['io.modelcontextprotocol/logLevel'] == 'info'
    assert 'text/event-stream' in V.STREAM_HEADERS['Accept']
    assert httpsig.request_nonce(V.STREAM_HEADERS) == V.STREAM_NONCE


def test_reference_jcs_agrees_with_the_library():
    from sajha.net import jcs
    evs, final = _events()
    for obj in evs + [final, json.loads(V.STREAM_BODY), {'b': [1.5, 0.99, 1843200.0, -0.0, 10], 'a': 'é\n'}]:
        assert ref_jcs(obj) == jcs.canonicalize(obj)


def test_the_chain_values_are_the_published_ones():
    signed, fin, chain, transcript = reference_stream()
    assert [c.hex() for c in chain] == list(V.STREAM_CHAIN)
    assert [json.dumps(e, separators=(',', ':')) for e in signed] == [e.decode() for e in V.STREAM_EVENTS]
    assert json.dumps(fin, separators=(',', ':')).encode() == V.STREAM_FINAL
    assert transcript.hex() == V.STREAM_TRANSCRIPT


def test_the_published_stream_verifies_event_by_event_and_as_a_whole():
    evs = [json.loads(e) for e in V.STREAM_EVENTS]
    h = _run(evs, json.loads(V.STREAM_FINAL))
    assert h.relayed == evs and h.transcript.hex() == V.STREAM_TRANSCRIPT


def test_the_published_headers_verify_as_a_streamed_response():
    from sajha.net import httpsig

    class Trust(httpsig.Trust):
        net = 'acme-net'

        def check_chain(self, chain, now):
            from sajha.net import crypto
            crypto.verify_chain(chain, crypto.load_cert(base64.b64decode(V.CA_B64)), now)

    httpsig.verify_response(Trust(), 'risk-eu', 'cust-na', 200, V.STREAM_RESPONSE_HEADERS, b'', _req_sig(),
                            streamed=True, now=V.T0 + 1)
    assert V.STREAM_RESPONSE_HEADERS['Content-Type'] == 'text/event-stream'
    assert 'content-digest' not in {k.lower() for k in V.STREAM_RESPONSE_HEADERS}


def test_a_stream_with_no_events_closes_on_c0():
    _, final = _events()
    fin, transcript = ref_sign_final(HOST_KEY, HOST_KEYID, c0(_req_sig()), 1, final, V.STREAM_NONCE)
    assert _final_ext(fin)['stream'] == {'seq': 1, 'chain': V.STREAM_CHAIN[0]}
    assert _run([], fin).transcript == transcript


def test_an_error_final_message_carries_the_binding_in_error_data():
    signed, _, chain, _ = reference_stream()
    err = {'jsonrpc': '2.0', 'id': 8, 'error': {'code': -32011, 'message': 'needs approval on cust-na', 'data': {
        EXT: {'reason': 'approval_required', 'side': 'host', 'net': 'acme-net', 'instance': 'cust-na',
              'executed': False}}}}
    fin, _ = ref_sign_final(HOST_KEY, HOST_KEYID, chain[-1], 4, err, V.STREAM_NONCE)
    assert set(fin['error']['data'][EXT]) >= {'stream', 'response_signature'}
    _run(signed, fin)


# ── every mutation ──────────────────────────────────────────────────────

def _published():
    return [json.loads(e) for e in V.STREAM_EVENTS], json.loads(V.STREAM_FINAL)


def _refused(reason, events, final, **kw):
    with pytest.raises(Refused) as e:
        _run(events, final, **kw)
    assert e.value.reason == reason


@pytest.mark.parametrize('path, value', [
    (('params', 'progress'), 3),
    (('params', 'total'), 4),
    (('params', 'message'), 'loading positions!'),
    (('params', 'progressToken'), 'another-token'),
    (('method',), 'notifications/message'),
])
def test_changing_any_member_of_an_event_fails(path, value):
    evs, fin = _published()
    target = evs[0]
    for p in path[:-1]:
        target = target[p]
    target[path[-1]] = value
    _refused('event_invalid', evs, fin)


def test_adding_a_member_to_an_event_fails():
    evs, fin = _published()
    evs[1]['params']['extra'] = True
    _refused('event_invalid', evs, fin)


def test_changing_seq_fails():
    evs, fin = _published()
    _event_ext(evs[1])['event_signature']['seq'] = 3
    _refused('event_order', evs, fin)


def test_a_seq_that_matches_but_a_signature_made_for_another_seq_fails():
    evs, fin = _published()
    _, final = _events()
    # the second event signed as if it were the third
    raw, _ = _events()
    s, _ = ref_sign_event(HOST_KEY, HOST_KEYID, c0(_req_sig()), 3, raw[1])
    _event_ext(s)['event_signature']['seq'] = 2
    _refused('event_invalid', [evs[0], s, evs[2]], fin)


@pytest.mark.parametrize('order', [(1, 0, 2), (0, 2, 1), (2, 1, 0)])
def test_reordering_fails(order):
    evs, fin = _published()
    _refused('event_order', [evs[i] for i in order], fin)


def test_a_duplicated_event_fails():
    evs, fin = _published()
    _refused('event_order', [evs[0], evs[0], evs[1], evs[2]], fin)


def test_a_dropped_event_fails():
    evs, fin = _published()
    _refused('event_order', [evs[0], evs[2]], fin)
    _refused('stream_truncated', evs[:2], fin)            # dropped last event: the final binding disagrees


def test_an_injected_unsigned_event_fails():
    evs, fin = _published()
    raw, _ = _events()
    _refused('event_invalid', [evs[0], raw[1], evs[1], evs[2]], fin)


def test_an_event_re_signed_by_another_key_fails():
    evs, fin = _published()
    raw, _ = _events()
    s, _ = ref_sign_event(_key('risk-eu'), HOST_KEYID, c0(_req_sig()), 1, raw[0])
    _refused('event_invalid', [s] + evs[1:], fin)
    s, _ = ref_sign_event(_key('risk-eu'), V.KEY_RECORD['signature']['keyid'], c0(_req_sig()), 1, raw[0])
    _refused('event_invalid', [s] + evs[1:], fin)          # its own keyid: not the response headers' certificate


def test_an_event_chain_from_another_request_fails():
    raw, final = _events()
    other = c0(b'\x00' * 64)
    s, _ = ref_sign_event(HOST_KEY, HOST_KEYID, other, 1, raw[0])
    evs, fin = _published()
    _refused('event_invalid', [s] + evs[1:], fin)
    # a whole stream signed for another request
    prev, out = other, []
    for i, ev in enumerate(raw, start=1):
        e, prev = ref_sign_event(HOST_KEY, HOST_KEYID, prev, i, ev)
        out.append(e)
    f, _ = ref_sign_final(HOST_KEY, HOST_KEYID, prev, 4, final, V.STREAM_NONCE)
    _refused('event_invalid', out, f)


def test_an_event_without_event_signature_or_of_another_shape_fails():
    evs, fin = _published()
    del _event_ext(evs[0])['event_signature']
    _refused('event_invalid', evs, fin)
    evs, fin = _published()
    _refused('event_invalid', [{'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': evs[0]['params']}],
             fin)
    _refused('event_invalid', ['not an object'], fin)
    evs, fin = _published()
    _event_ext(evs[0])['event_signature']['alg'] = 'hmac-sha256'
    _refused('event_invalid', evs, fin)


def test_a_stream_without_its_final_message_is_truncated():
    evs, _ = _published()
    _refused('stream_truncated', evs, None)
    _refused('stream_truncated', [], None)


@pytest.mark.parametrize('binding', [
    {'seq': 3, 'chain': V.STREAM_CHAIN[3]},
    {'seq': 4, 'chain': V.STREAM_CHAIN[2]},
    None,
])
def test_a_final_binding_that_disagrees_is_truncated(binding):
    evs, fin = _published()
    ext = _final_ext(fin)
    if binding is None:
        ext.pop('stream')
    else:
        ext['stream'] = binding
    _refused('stream_truncated', evs, fin)


def test_a_changed_final_result_fails():
    evs, fin = _published()
    fin['result']['structuredContent']['var'] = 1.0
    _refused('response_invalid', evs, fin)
    evs, fin = _published()
    _final_ext(fin)['response_signature']['request_nonce'] = 'q1QXbXk3WlNQ8n0Zr6dL4w'
    _refused('response_invalid', evs, fin)


def test_the_final_of_another_call_fails():
    evs, fin = _published()
    fin['id'] = 7
    _refused('event_invalid', evs, fin)


def test_events_are_relayed_only_until_the_first_failure():
    evs, fin = _published()
    h = _home()
    h.event(evs[0])
    with pytest.raises(Refused):
        h.event(evs[2])
    assert h.relayed == [evs[0]]


# ── cross-check with the library (stream A's EventChain) ────────────────

def _event_chain():
    from sajha.net import httpsig
    ec = getattr(httpsig, 'EventChain', None)
    if ec is None:
        pytest.skip('sajha.net.httpsig.EventChain is not built yet (phase 6.1 stream A); '
                    'the reference vectors above stand alone')
    return ec


class _HostSigner:
    """The §21.4 host as a ``httpsig.Signer``."""

    def __new__(cls):
        from sajha.net import httpsig
        return httpsig.Signer(HOST_KEY, [HOST_CERT])


def test_library_event_chain_signs_the_same_bytes():
    EventChain = _event_chain()
    raw, final = _events()
    chain = EventChain(_req_sig())
    signer = _HostSigner()
    got = [chain.sign_event(signer, copy.deepcopy(ev)) for ev in raw]
    assert [ref_jcs(e) for e in got] == [ref_jcs(json.loads(e)) for e in V.STREAM_EVENTS]


def test_library_event_chain_verifies_the_vectors_and_refuses_mutations():
    EventChain = _event_chain()
    evs, _ = _published()
    chain = EventChain(_req_sig())
    assert all(chain.verify_event(HOST_CERT, copy.deepcopy(e)) for e in evs)
    bad = copy.deepcopy(evs[0])
    bad['params']['progress'] = 3
    assert not EventChain(_req_sig()).verify_event(HOST_CERT, bad)
    reordered = EventChain(_req_sig())
    assert not reordered.verify_event(HOST_CERT, copy.deepcopy(evs[1]))
    other = EventChain(b'\x00' * 64)
    assert not other.verify_event(HOST_CERT, copy.deepcopy(evs[0]))


def test_library_event_chain_closes_with_the_published_binding_and_transcript():
    EventChain = _event_chain()
    from sajha.net import httpsig
    raw, final = _events()
    host = EventChain(_req_sig())
    for ev in raw:
        host.sign_event(_HostSigner(), ev)
    closed = httpsig.sign_message(_HostSigner(), host.close(final), V.STREAM_NONCE)
    assert ref_jcs(closed) == ref_jcs(json.loads(V.STREAM_FINAL))
    assert host.transcript == V.STREAM_TRANSCRIPT
    home = EventChain(_req_sig())
    for e in V.STREAM_EVENTS:
        assert home.verify_event(HOST_CERT, json.loads(e))
    fin = json.loads(V.STREAM_FINAL)
    assert home.verify_close(fin) and httpsig.verify_message(fin, V.STREAM_NONCE, HOST_CERT)
    assert home.transcript == V.STREAM_TRANSCRIPT


def test_library_event_chain_gives_the_reference_reasons():
    EventChain = _event_chain()
    evs, fin = _published()
    for events, reason in (([evs[1]], 'event_order'), ([evs[0], evs[0]], 'event_order'),
                           ([evs[0], evs[2]], 'event_order')):
        chain = EventChain(_req_sig())
        got = [chain.check_event(HOST_CERT, copy.deepcopy(e)) for e in events]
        assert got[-1] == reason and all(g is None for g in got[:-1])
    raw, _ = _events()
    s, _ = ref_sign_event(_key('risk-eu'), HOST_KEYID, c0(_req_sig()), 1, raw[0])
    assert EventChain(_req_sig()).check_event(HOST_CERT, s) == 'event_invalid'
    chain = EventChain(_req_sig())
    for e in evs[:2]:
        assert chain.verify_event(HOST_CERT, copy.deepcopy(e))
    assert not chain.verify_close(copy.deepcopy(fin))          # the third event was dropped
