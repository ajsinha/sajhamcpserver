"""
The SAJHA Net CA (design §6.4; protocol §5.2 "Prevention at the CA", §13, §14).

One CA per net, run by the participant whose net entry has ``ca.enabled``. It keeps, in a
:class:`~sajha.net.models.KV`, the enrollment tokens (hashed), every certificate it issued (with
``renews`` naming the previous serial of a renewal) and the signed revocation list.

* A token is single use, short-lived, bound to one net and one instance name, and refused for a
  name held by a certificate that is not revoked (the refusal names the holder).
* Enrollment checks the token, the CSR's self-signature, key type and subject, and the one
  requested host; every failure is ``403 enrollment_refused`` (the detail is for the CA's log only).
* Renewal is signed with the current certificate; the new certificate carries the previous serial
  in its renews extension, so members follow the lineage (:func:`sajha.net.crypto.renews_of`).
* Revocation by instance name (removal from the net) or by serial (a lost key) gives a new
  revocation list version, signed with the CA key.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from sajha.net import crypto, names
from sajha.net.errors import NetError
from sajha.net.models import KV

logger = logging.getLogger(__name__)


class NameHeld(Exception):
    """A token was asked for a name another certificate holds."""

    def __init__(self, instance: str, holder: Dict[str, Any]):
        super().__init__(f'{instance} is held by certificate {holder.get("serial")} '
                         f'(thumbprint {holder.get("thumbprint")}); revoke it first')
        self.instance = instance
        self.holder = holder


def init_ca(net: str, alg: str = crypto.ED25519, days: int = 3650, now: Optional[float] = None):
    """A new CA key and self-signed CA certificate for ``net``."""
    key = crypto.generate_key(alg)
    return key, crypto.make_ca_certificate(key, net, days=days, now=now)


def _th(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


class CertificateAuthority:
    def __init__(self, net: str, ca_key, ca_cert, kv: KV, clock: Callable[[], float] = time.time,
                 validity_days: float = 30, token_minutes: float = 30, enrollments_per_minute: int = 10):
        self.net = net
        self.key = ca_key
        self.cert = ca_cert
        self.kv = kv
        self.clock = clock
        self.validity_days = float(validity_days)
        self.token_minutes = float(token_minutes)
        self.rate = max(1, int(enrollments_per_minute))
        if self.kv.get('ca:revocations') is None:
            self._write_list([], 1)

    # ── state ──────────────────────────────────────────────────────

    @property
    def thumbprint(self) -> str:
        return crypto.thumbprint(crypto.cert_der(self.cert))

    def issued(self) -> List[Dict[str, Any]]:
        return sorted((v for _, v in self.kv.scan('ca:issued:')), key=lambda r: r.get('issued_at', ''))

    def revocation_list(self) -> Dict[str, Any]:
        return self.kv.get('ca:revocations')

    def _revoked_serials(self) -> set:
        return {e['serial'] for e in (self.revocation_list() or {}).get('revoked', []) if e.get('serial')}

    def _revoked_instances(self) -> set:
        return {e['instance'] for e in (self.revocation_list() or {}).get('revoked', []) if e.get('instance')}

    def holder(self, instance: str) -> Optional[Dict[str, Any]]:
        """The newest issued certificate for ``instance`` that is not revoked (the name's holder)."""
        if instance in self._revoked_instances():
            return None
        revoked = self._revoked_serials()
        live = [r for r in self.issued() if r['instance'] == instance and r['serial'] not in revoked]
        return live[-1] if live else None

    def pending_tokens(self) -> List[Dict[str, Any]]:
        now = self.clock()
        return [dict(v, token_hash=k.split(':')[-1][:12]) for k, v in self.kv.scan('ca:token:')
                if v.get('expires', 0) > now and not v.get('used')]

    # ── tokens ─────────────────────────────────────────────────────

    def create_token(self, instance: str, host: str = '', by: str = '') -> Tuple[str, Dict[str, Any]]:
        if not names.is_instance_name(instance):
            raise ValueError(f'{instance!r} is not a valid instance name')
        if instance in self._revoked_instances():
            raise ValueError(f'{instance} is revoked in {self.net}; its name cannot be enrolled while revoked')
        h = self.holder(instance)
        if h is not None:
            raise NameHeld(instance, h)
        token = crypto.b64url(os.urandom(32))
        rec = {'net': self.net, 'instance': instance, 'host': host.strip().lower(), 'created_by': by,
               'created': self.clock(), 'expires': self.clock() + self.token_minutes * 60, 'used': False}
        self.kv.set('ca:token:' + _th(token), rec, ttl=self.token_minutes * 60 + 86400)
        return token, rec

    # ── issuing ────────────────────────────────────────────────────

    def _issue(self, public_key, instance: str, host: str, renews: Optional[str] = None):
        now = self.clock()
        cert = crypto.issue_certificate(self.key, self.cert, public_key, self.net, instance, host,
                                        days=self.validity_days, now=now, renews=renews)
        serial = crypto.serial_hex(cert)
        self.kv.set('ca:issued:' + serial, {
            'serial': serial, 'instance': instance, 'host': host,
            'thumbprint': crypto.thumbprint(crypto.cert_der(cert)), 'issued_at': crypto.rfc3339(now),
            'not_after': cert.not_valid_after_utc.strftime('%Y-%m-%dT%H:%M:%SZ'), 'renews': renews})
        return cert

    def issue_own(self, key, instance: str, host: str):
        """The CA participant's own certificate in the net (it holds the CA key)."""
        return self._issue(key.public_key(), instance, host)

    def _response(self, cert) -> Dict[str, Any]:
        return {'certificate': [crypto.b64(crypto.cert_der(cert))],
                'ca_certificate': crypto.b64(crypto.cert_der(self.cert)),
                'not_after': cert.not_valid_after_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}

    @staticmethod
    def _csr(text: str):
        try:
            csr = crypto.load_csr(crypto.unb64(text))
        except Exception:
            raise NetError('enrollment_refused', 'the CSR cannot be parsed')
        if not csr.is_signature_valid:
            raise NetError('enrollment_refused', 'the CSR self-signature does not verify')
        pk = csr.public_key()
        if not (isinstance(pk, ed25519.Ed25519PublicKey) or
                (isinstance(pk, ec.EllipticCurvePublicKey) and isinstance(pk.curve, ec.SECP256R1))):
            raise NetError('enrollment_refused', 'the CSR key is neither Ed25519 nor P-256')
        hosts = crypto.csr_hosts(csr)
        if len(hosts) != 1:
            raise NetError('enrollment_refused', 'the CSR must name exactly one host')
        return csr, hosts[0]

    def _rate_ok(self, source: str) -> bool:
        key = 'ca:rate:' + hashlib.sha256((source or '?').encode()).hexdigest()[:16]
        now = self.clock()

        def fn(cur):
            hits = [t for t in (cur or []) if t > now - 60]
            if len(hits) >= self.rate:
                raise _Limited()
            return hits + [now]
        try:
            self.kv.update(key, fn, ttl=120)
            return True
        except _Limited:
            return False

    def enroll(self, body: Dict[str, Any], header_net: str, source: str = '', secure: bool = True,
               allow_plain_http: bool = False) -> Tuple[Dict[str, Any], Any]:
        """§14.1. Returns ``(response body, certificate)``; raises :class:`NetError`."""
        if not self._rate_ok(source):
            raise NetError('rate_limited', 'too many enrollment requests from this address', retry_after=60)
        if not secure and not allow_plain_http:
            raise NetError('enrollment_refused', 'enrollment is refused over plain HTTP')
        net, instance, token = body.get('net'), body.get('instance'), str(body.get('token') or '')
        if net != header_net or net != self.net:
            raise NetError('enrollment_refused', 'Sajha-Net-Name does not match the request net')
        key = 'ca:token:' + _th(token)
        rec = self.kv.get(key)
        now = self.clock()
        if not rec or rec.get('used') or rec.get('expires', 0) <= now:
            raise NetError('enrollment_refused', 'the token is unknown, used or expired')
        if not (hmac.compare_digest(str(rec.get('net')), str(net)) and
                hmac.compare_digest(str(rec.get('instance')), str(instance))):
            raise NetError('enrollment_refused', 'the token was issued for another net or instance')
        csr, host = self._csr(str(body.get('csr') or ''))
        o, cn = crypto.subject_of(csr)
        if o != net or cn != instance:
            raise NetError('enrollment_refused', 'the CSR subject is not O=<net>, CN=<instance>')
        if rec.get('host') and rec['host'] != host:
            raise NetError('enrollment_refused', 'the CSR host is not the host bound to the token')
        if self.holder(instance) is not None:
            raise NetError('enrollment_refused', 'the name is held by another certificate')

        def spend(cur):
            if not cur or cur.get('used'):
                raise _Spent()
            return dict(cur, used=True, used_at=now)
        try:
            self.kv.update(key, spend)
        except _Spent:
            raise NetError('enrollment_refused', 'the token is already used')
        cert = self._issue(csr.public_key(), instance, host)
        logger.info(f'SAJHA Net CA {self.net}: enrolled {instance} ({crypto.serial_hex(cert)})')
        return self._response(cert), cert

    def renew(self, current_cert, body: Dict[str, Any]) -> Tuple[Dict[str, Any], Any]:
        """§14.2: ``current_cert`` is the verified signing certificate (not revoked: checked by §8.7)."""
        csr, host = self._csr(str(body.get('csr') or ''))
        if crypto.subject_of(csr) != crypto.subject_of(current_cert):
            raise NetError('enrollment_refused', 'the CSR subject differs from the signing certificate')
        old = crypto.serial_hex(current_cert)
        if old in self._revoked_serials():
            raise NetError('certificate_revoked', 'the signing certificate is revoked')
        _o, cn = crypto.subject_of(current_cert)
        cert = self._issue(csr.public_key(), cn, host, renews=old)
        logger.info(f'SAJHA Net CA {self.net}: renewed {cn} ({old} -> {crypto.serial_hex(cert)})')
        return self._response(cert), cert

    # ── revocation (§13) ───────────────────────────────────────────

    def _write_list(self, revoked: List[Dict[str, Any]], version: int) -> Dict[str, Any]:
        doc = {'type': 'revocations', 'net': self.net, 'version': int(version),
               'issued_at': crypto.rfc3339(self.clock()), 'revoked': revoked}
        doc['signature'] = crypto.sign_record('revocations', doc, self.key, self.thumbprint)
        self.kv.set('ca:revocations', doc)
        return doc

    def revoke(self, instance: Optional[str] = None, serial: Optional[str] = None, reason: str = '') -> Dict[str, Any]:
        if not instance and not serial:
            raise ValueError('name an instance or a serial to revoke')
        cur = self.revocation_list() or {'revoked': [], 'version': 0}
        entry: Dict[str, Any] = {'revoked_at': crypto.rfc3339(self.clock())}
        if instance:
            if not names.is_instance_name(instance):
                raise ValueError(f'{instance!r} is not an instance name')
            entry['instance'] = instance
        if serial:
            serial = serial.lower().lstrip('0') or '0'
            if not all(c in '0123456789abcdef' for c in serial):
                raise ValueError('a serial is lowercase hex')
            entry['serial'] = serial
        if reason:
            entry['reason'] = reason[:200]
        return self._write_list(list(cur.get('revoked') or []) + [entry], int(cur.get('version') or 0) + 1)


class _Limited(Exception):
    pass


class _Spent(Exception):
    pass
