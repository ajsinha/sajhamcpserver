"""
HTTP Message Signatures (RFC 9421) and Content-Digest (RFC 9530) exactly as protocol §8.3-§8.9
profile them: the ``sajhanet`` label, the covered components of §8.5 and §8.8, the eleven
verification steps of §8.7 in order, response binding through ``"signature";req``, and the
JCS message signature that ends a streamed response (§8.9).

Framework-free: callers pass the method, path, raw query, a header mapping and the body bytes.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from cryptography import x509

from sajha.net import PROTOCOL_VERSION, SIGNATURE_LABEL, SIGNATURE_TAG, SUPPORTED_VERSIONS, EXTENSION_ID
from sajha.net import crypto, jcs, sfv
from sajha.net.errors import NetError

FUTURE_ALLOWANCE = 5            # seconds a `created` may be ahead of the receiver's clock
MAX_AGE_CAP = 300               # the configured maximum age is never more than this
_NONCE_RE = re.compile(r'^[A-Za-z0-9_-]{22,64}$')

ALWAYS = ('sajha-net-version', 'sajha-net-name', 'sajha-net-from', 'sajha-net-to')
MCP_HEADERS = ('mcp-protocol-version', 'mcp-method', 'mcp-name', 'mcp-session-id')
TAIL_HEADERS = ('sajha-net-hop', 'sajha-net-visited', 'sajha-net-api-key', 'sajha-net-user-assertion', 'traceparent')
REQ_SIG = ('signature', {'req': True, 'key': SIGNATURE_LABEL})
#: ``Sajha-Net-To: *`` on a join sync to an address whose instance name the sender does not know yet
#: (a seed URL or an operator-given address, protocol §9.7); accepted on no other request.
ANY = '*'


def lower_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    items = headers.items() if hasattr(headers, 'items') else headers
    for k, v in items:
        k = k.lower()
        out[k] = f'{out[k]}, {v}' if k in out else v
    return out


def content_digest(body: bytes) -> str:
    return 'sha-256=:' + base64.b64encode(hashlib.sha256(body).digest()).decode('ascii') + ':'


def digest_matches(header: Optional[str], body: bytes) -> bool:
    try:
        d = sfv.parse_dict(header or '')
    except sfv.SFVError:
        return False
    v = d.get('sha-256')
    return bool(v) and isinstance(v[0], bytes) and v[0] == hashlib.sha256(body).digest()


def new_nonce() -> str:
    return crypto.b64url(os.urandom(16))


@dataclass
class Signer:
    """What a participant signs with in one net: its key and its certificate chain (leaf first)."""
    key: Any
    chain: List[x509.Certificate]

    @property
    def keyid(self) -> str:
        return crypto.thumbprint(crypto.cert_der(self.chain[0]))

    @property
    def alg(self) -> str:
        return crypto.alg_of(self.key)

    def certificate_header(self) -> str:
        return sfv.ser_list([(crypto.cert_der(c), {}) for c in self.chain])


# ── components and signature bases ──────────────────────────────────

def request_components(method: str, has_body: bool, headers: Dict[str, str], mcp: bool) -> List[Tuple[str, dict]]:
    """The components §8.5 requires for this request, in the order it lists them."""
    comps: List[Tuple[str, dict]] = [('@method', {}), ('@path', {}), ('@query', {})]
    if has_body:
        comps += [('content-type', {}), ('content-digest', {})]
    if mcp:
        comps += [(h, {}) for h in MCP_HEADERS if h in headers]
        comps += [(h, {}) for h in sorted(headers) if h.startswith('mcp-param-')]
    comps += [(h, {}) for h in ALWAYS]
    comps += [(h, {}) for h in TAIL_HEADERS if h in headers]
    return comps


def response_components(has_body: bool, streamed: bool = False, bound: bool = True) -> List[Tuple[str, dict]]:
    """§8.8; ``bound`` False only for the answer to an unsigned enrollment (§14.1), which has no
    request signature to cover."""
    comps: List[Tuple[str, dict]] = [('@status', {})]
    if has_body:
        comps.append(('content-type', {}))
        if not streamed:
            comps.append(('content-digest', {}))
    comps += [(h, {}) for h in ALWAYS]
    if bound:
        comps.append(REQ_SIG)
    return comps


def _component_value(name: str, params: dict, *, method: str = '', path: str = '', query: str = '',
                     status: Optional[int] = None, headers: Dict[str, str], req_signature: Optional[bytes] = None) -> str:
    if name == '@method':
        return method.upper()
    if name == '@path':
        return path or '/'
    if name == '@query':
        return '?' + (query or '')
    if name == '@status':
        if status is None:
            raise NetError('signature_invalid', '@status on a request')
        return str(int(status))
    if name == 'signature' and params.get('req') and params.get('key') == SIGNATURE_LABEL:
        if req_signature is None:
            raise NetError('signature_invalid', 'the request signature is not available')
        return sfv.ser_bare(req_signature)
    if params:
        raise NetError('signature_invalid', f'unsupported component parameters on {name}')
    if name.startswith('@'):
        raise NetError('signature_invalid', f'unsupported derived component {name}')
    if name not in headers:
        raise NetError('signature_invalid', f'covered header {name} is absent')
    return headers[name].strip(' \t')


def signature_params(components: List[Tuple[str, dict]], params: Dict[str, Any]) -> str:
    return sfv.ser_inner([(n, p) for n, p in components], params)


def signature_base(components, params_value: str, **values) -> bytes:
    lines = []
    for name, p in components:
        ident = sfv.ser_item(name, p)
        lines.append(f'{ident}: {_component_value(name, p, **values)}')
    lines.append(f'"@signature-params": {params_value}')
    return '\n'.join(lines).encode('utf-8')


# ── signing ────────────────────────────────────────────────────────

def sign_request(signer: Signer, method: str, path: str, query: str, headers: Dict[str, str], body: bytes,
                 net: str, sender: str, recipient: str, *, mcp: bool = False, now: Optional[float] = None,
                 nonce: Optional[str] = None, version: int = PROTOCOL_VERSION) -> Dict[str, str]:
    """Return ``headers`` plus every header §8.5 needs, signed. ``headers`` keys may be any case."""
    h = lower_headers(headers)
    h['sajha-net-version'] = str(version)
    h['sajha-net-name'] = net
    h['sajha-net-from'] = sender
    h['sajha-net-to'] = recipient
    has_body = bool(body) or method.upper() != 'GET'
    if has_body:
        h.setdefault('content-type', 'application/json')
        h['content-digest'] = content_digest(body or b'')
    comps = request_components(method, has_body, h, mcp)
    params = {'created': int(now if now is not None else time.time()), 'nonce': nonce or new_nonce(),
              'keyid': signer.keyid, 'alg': signer.alg, 'tag': SIGNATURE_TAG}
    pv = signature_params(comps, params)
    base = signature_base(comps, pv, method=method, path=path, query=query, headers=h)
    sig = crypto.sign_raw(signer.key, base)
    h['sajha-net-certificate'] = signer.certificate_header()
    h['signature-input'] = f'{SIGNATURE_LABEL}={pv}'
    h['signature'] = f'{SIGNATURE_LABEL}={sfv.ser_bare(sig)}'
    return h


def sign_response(signer: Signer, status: int, headers: Dict[str, str], body: bytes, req_signature: Optional[bytes],
                  net: str, sender: str, recipient: str, *, streamed: bool = False, now: Optional[float] = None,
                  version: int = PROTOCOL_VERSION) -> Dict[str, str]:
    h = lower_headers(headers)
    h['sajha-net-version'] = str(version)
    h['sajha-net-name'] = net
    h['sajha-net-from'] = sender
    h['sajha-net-to'] = recipient
    has_body = bool(body) or streamed
    if has_body:
        h.setdefault('content-type', 'application/json')
        if not streamed:
            h['content-digest'] = content_digest(body)
    comps = response_components(has_body, streamed, bound=req_signature is not None)
    params = {'created': int(now if now is not None else time.time()), 'keyid': signer.keyid, 'alg': signer.alg,
              'tag': SIGNATURE_TAG}
    pv = signature_params(comps, params)
    base = signature_base(comps, pv, status=status, headers=h, req_signature=req_signature)
    h['sajha-net-certificate'] = signer.certificate_header()
    h['signature-input'] = f'{SIGNATURE_LABEL}={pv}'
    h['signature'] = f'{SIGNATURE_LABEL}={sfv.ser_bare(crypto.sign_raw(signer.key, base))}'
    return h


# ── verification ───────────────────────────────────────────────────

class Trust:
    """What a receiver checks a certificate against in one net (§8.1, §8.11, §13). Subclasses
    implement :meth:`check_chain` and :meth:`revocation`."""

    net: str = ''

    def check_chain(self, chain: List[x509.Certificate], now: float) -> None:      # pragma: no cover
        raise NotImplementedError

    def revocation(self, serial: str, instance: str) -> Optional[str]:
        """``certificate_revoked``, ``instance_revoked`` or None."""
        return None


@dataclass
class Verified:
    """A request or response that passed every check."""
    net: str
    sender: str
    recipient: str
    keyid: str
    alg: str
    nonce: Optional[str]
    created: int
    signature: bytes
    chain: List[x509.Certificate]
    version: int
    covered: List[str] = field(default_factory=list)

    @property
    def certificate(self) -> x509.Certificate:
        return self.chain[0]

    @property
    def serial(self) -> str:
        return crypto.serial_hex(self.chain[0])


def _parse_signature(h: Dict[str, str]):
    if 'signature-input' not in h or 'signature' not in h or 'sajha-net-certificate' not in h:
        raise NetError('signature_missing', 'Signature, Signature-Input or Sajha-Net-Certificate is missing')
    try:
        si = sfv.parse_dict(h['signature-input'])
        sg = sfv.parse_dict(h['signature'])
    except sfv.SFVError:
        raise NetError('signature_invalid', 'Signature or Signature-Input cannot be parsed')
    if SIGNATURE_LABEL not in si or SIGNATURE_LABEL not in sg:
        raise NetError('signature_missing', f'no "{SIGNATURE_LABEL}" signature')
    comps, params = si[SIGNATURE_LABEL]
    sig, _ = sg[SIGNATURE_LABEL]
    if not isinstance(comps, list) or not isinstance(sig, bytes):
        raise NetError('signature_invalid', 'malformed signature members')
    return comps, params, sig


def _check_params(params: dict, need_nonce: bool):
    if params.get('tag') != SIGNATURE_TAG:
        raise NetError('signature_incomplete', f'tag must be "{SIGNATURE_TAG}"')
    for p in ('created', 'keyid', 'alg') + (('nonce',) if need_nonce else ()):
        if p not in params:
            raise NetError('signature_incomplete', f'signature parameter {p} is missing')
    if not isinstance(params['created'], int) or isinstance(params['created'], bool):
        raise NetError('signature_incomplete', 'created must be an integer')
    if need_nonce and (not isinstance(params['nonce'], str) or not _NONCE_RE.match(params['nonce'])):
        raise NetError('signature_invalid', 'the nonce must be 22 to 64 base64url characters')


def _covered(comps) -> List[Tuple[str, dict]]:
    out = []
    for v, p in comps:
        if not isinstance(v, str):
            raise NetError('signature_invalid', 'component identifiers must be strings')
        out.append((v.lower(), dict(p)))
    return out


def _require(covered: List[Tuple[str, dict]], required: List[Tuple[str, dict]]):
    have = {sfv.ser_item(n, p) for n, p in covered}
    missing = [sfv.ser_item(n, p) for n, p in required if sfv.ser_item(n, p) not in have]
    if missing:
        raise NetError('signature_incomplete', f'not covered: {", ".join(missing)}')


def _version(h: Dict[str, str], supported) -> int:
    try:
        v = sfv.parse_item(h.get('sajha-net-version', ''))[0]
    except sfv.SFVError:
        v = None
    if not isinstance(v, int) or isinstance(v, bool) or v not in supported:
        raise NetError('unsupported_version', f'Sajha-Net-Version {h.get("sajha-net-version")!r} is not spoken here')
    return v


def _time_checks(params: dict, now: float, max_age: float):
    created = params['created']
    max_age = min(float(max_age), MAX_AGE_CAP)
    if created < now - max_age:
        raise NetError('signature_expired', f'created is {int(now - created)} s before receipt; the maximum age is '
                                            f'{int(max_age)} s')
    if created > now + FUTURE_ALLOWANCE:
        raise NetError('signature_expired', f'created is {int(created - now)} s in the future')
    exp = params.get('expires')
    if exp is not None and (not isinstance(exp, int) or exp < now):
        raise NetError('signature_expired', 'the signature has expired')


def _chain_checks(h: Dict[str, str], trust: Trust, net: str, now: float) -> List[x509.Certificate]:
    try:
        items = sfv.parse_list(h['sajha-net-certificate'])
        if not items or len(items) > 4 or any(not isinstance(v, bytes) for v, _ in items):
            raise ValueError()
        chain = [crypto.load_cert(v) for v, _ in items]
    except Exception:
        raise NetError('certificate_invalid', 'Sajha-Net-Certificate cannot be parsed')
    try:
        trust.check_chain(chain, now)
    except crypto.CryptoError as e:
        raise NetError('name_conflict' if e.reason == 'name_conflict' else 'certificate_invalid', e.detail)
    o, cn = crypto.subject_of(chain[0])
    if o != net:
        raise NetError('net_mismatch', 'the certificate names another net')
    why = trust.revocation(crypto.serial_hex(chain[0]), cn or '')
    if why:
        raise NetError(why, 'the certificate is revoked' if why == 'certificate_revoked' else 'the instance is revoked')
    return chain


def _sig_checks(chain, params, base: bytes, sig: bytes):
    leaf = chain[0]
    if params['keyid'] != crypto.thumbprint(crypto.cert_der(leaf)):
        raise NetError('signature_invalid', 'keyid is not the certificate thumbprint')
    try:
        key_alg = crypto.alg_of(leaf.public_key())
    except crypto.CryptoError:
        raise NetError('signature_invalid', 'unsupported certificate key')
    if params['alg'] != key_alg:
        raise NetError('signature_invalid', 'alg does not match the certificate key')
    if not crypto.verify_raw(leaf.public_key(), key_alg, base, sig):
        raise NetError('signature_invalid', 'the signature does not verify')


def verify_request(trust: Trust, own_name: str, method: str, path: str, query: str, headers: Mapping[str, str],
                   body: bytes, *, mcp: bool = False, now: Optional[float] = None, max_age: float = 30,
                   seen_nonce: Optional[Callable[[str, str, float], bool]] = None,
                   supported_versions=SUPPORTED_VERSIONS, allow_any_recipient: bool = False) -> Verified:
    """Run §8.7 steps 1-11 in order for the net ``trust.net`` (already selected by the caller from
    ``Sajha-Net-Name``, §7.7). ``seen_nonce(keyid, nonce, ttl)`` records a nonce and returns True when
    it was already recorded; it is called only after every other check passed. Raises :class:`NetError`."""
    now = time.time() if now is None else now
    h = lower_headers(headers)
    comps, params, sig = _parse_signature(h)                                     # 1
    _check_params(params, need_nonce=True)                                       # 2
    covered = _covered(comps)
    has_body = bool(body) or method.upper() != 'GET'
    _require(covered, request_components(method, has_body, h, mcp))
    version = _version(h, supported_versions)                                    # 3
    _time_checks(params, now, max_age)                                           # 4
    if has_body and not digest_matches(h.get('content-digest'), body or b''):    # 5
        raise NetError('digest_mismatch', 'Content-Digest does not match the body')
    chain = _chain_checks(h, trust, trust.net, now)                              # 6, 7
    try:
        base = signature_base(covered, sfv.ser_inner(comps, params), method=method, path=path, query=query,
                              headers=h)
    except NetError:
        raise
    _sig_checks(chain, params, base, sig)                                        # 8, 9
    _o, cn = crypto.subject_of(chain[0])
    if h.get('sajha-net-from', '').strip() != cn:                                # 10
        raise NetError('from_mismatch', 'Sajha-Net-From is not the certificate CN')
    if cn == own_name:
        raise NetError('name_conflict', 'the sender claims this participant\'s own name')
    to = h.get('sajha-net-to', '').strip()
    if to != own_name and not (allow_any_recipient and to == ANY):
        raise NetError('recipient_mismatch', 'Sajha-Net-To is not this participant')
    if seen_nonce is not None:                                                   # 11
        if seen_nonce(params['keyid'], params['nonce'], min(float(max_age), MAX_AGE_CAP) + FUTURE_ALLOWANCE):
            raise NetError('replay', 'this nonce was already used')
    return Verified(net=trust.net, sender=cn, recipient=own_name, keyid=params['keyid'], alg=params['alg'],
                    nonce=params['nonce'], created=params['created'], signature=sig, chain=chain, version=version,
                    covered=[sfv.ser_item(n, p) for n, p in covered])


def verify_response(trust: Trust, own_name: str, expected_sender: str, status: int, headers: Mapping[str, str],
                    body: bytes, req_signature: Optional[bytes], *, streamed: bool = False, now: Optional[float] = None,
                    max_age: float = 30, supported_versions=SUPPORTED_VERSIONS) -> Verified:
    """§8.8: a response to a signed request, checked as §8.7 steps 4-10 in the request's net."""
    now = time.time() if now is None else now
    h = lower_headers(headers)
    comps, params, sig = _parse_signature(h)
    _check_params(params, need_nonce=False)
    covered = _covered(comps)
    has_body = bool(body) or streamed
    _require(covered, response_components(has_body, streamed, bound=req_signature is not None))
    if h.get('sajha-net-name', '').strip() != trust.net:
        raise NetError('net_mismatch', 'the response names another net')
    version = _version(h, supported_versions)
    _time_checks(params, now, max_age)
    if has_body and not streamed and not digest_matches(h.get('content-digest'), body or b''):
        raise NetError('digest_mismatch', 'Content-Digest does not match the body')
    chain = _chain_checks(h, trust, trust.net, now)
    base = signature_base(covered, sfv.ser_inner(comps, params), status=status, headers=h,
                          req_signature=req_signature)
    _sig_checks(chain, params, base, sig)
    _o, cn = crypto.subject_of(chain[0])
    if h.get('sajha-net-from', '').strip() != cn or (expected_sender != ANY and cn != expected_sender):
        raise NetError('from_mismatch', 'the response is not from the participant asked')
    if h.get('sajha-net-to', '').strip() != own_name:
        raise NetError('recipient_mismatch', 'the response is addressed to another participant')
    return Verified(net=trust.net, sender=cn, recipient=own_name, keyid=params['keyid'], alg=params['alg'],
                    nonce=None, created=params['created'], signature=sig, chain=chain, version=version,
                    covered=[sfv.ser_item(n, p) for n, p in covered])


def request_signature_bytes(headers: Mapping[str, str]) -> bytes:
    """The raw ``sajhanet`` signature of a (signed) request, which its response covers."""
    h = lower_headers(headers)
    return sfv.parse_dict(h['signature'])[SIGNATURE_LABEL][0]


def request_nonce(headers: Mapping[str, str]) -> str:
    h = lower_headers(headers)
    return sfv.parse_dict(h['signature-input'])[SIGNATURE_LABEL][1]['nonce']


# ── streamed responses (§8.9) ──────────────────────────────────────

def _slot(msg: Dict[str, Any], create: bool) -> Optional[Dict[str, Any]]:
    if 'error' in msg:
        parent = msg['error']
        key = 'data'
    else:
        parent = msg.setdefault('result', {}) if create else msg.get('result')
        key = '_meta'
    if not isinstance(parent, dict):
        return None
    if create:
        parent.setdefault(key, {})
        parent[key].setdefault(EXTENSION_ID, {})
    container = parent.get(key)
    if not isinstance(container, dict):
        return None
    ext = container.get(EXTENSION_ID)
    return ext if isinstance(ext, dict) else None


def _message_input(msg: Dict[str, Any], nonce: str) -> bytes:
    m = copy.deepcopy(msg)
    ext = _slot(m, create=False)
    if ext is not None:
        ext.pop('response_signature', None)
    return f'sajha-net-v1:response:{nonce}:'.encode('ascii') + jcs.canonicalize(m)


def sign_message(signer: Signer, msg: Dict[str, Any], request_nonce_value: str) -> Dict[str, Any]:
    """Return a copy of JSON-RPC response ``msg`` carrying ``response_signature``."""
    m = copy.deepcopy(msg)
    slot = _slot(m, create=True)          # the containers stay (even empty) when the member is removed
    sig = crypto.sign_raw(signer.key, _message_input(m, request_nonce_value))
    slot['response_signature'] = {'alg': signer.alg, 'keyid': signer.keyid,
                                                   'sig': crypto.b64url(sig), 'request_nonce': request_nonce_value}
    return m


def verify_message(msg: Dict[str, Any], request_nonce_value: str, certificate: x509.Certificate) -> bool:
    ext = _slot(msg, create=False)
    rs = (ext or {}).get('response_signature')
    if not isinstance(rs, dict) or rs.get('request_nonce') != request_nonce_value:
        return False
    if rs.get('keyid') != crypto.thumbprint(crypto.cert_der(certificate)):
        return False
    try:
        sig = crypto.unb64url(str(rs.get('sig') or ''))
    except Exception:
        return False
    return crypto.verify_raw(certificate.public_key(), str(rs.get('alg') or ''), _message_input(msg, request_nonce_value),
                             sig)
