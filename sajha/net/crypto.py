"""
Keys, certificates and signatures (protocol §8.1, §8.2, §8.10).

* Ed25519 (``ed25519``) and ECDSA P-256 with SHA-256 (``ecdsa-p256-sha256``, raw ``r || s``,
  not DER) are the only algorithms; both verify, both sign.
* A certificate's ``keyid`` is ``base64url(SHA-256(DER))`` (the ``x5t#S256`` thumbprint).
* Participant certificates: subject ``O=<net>, CN=<instance>``, subjectAltName naming the host of
  the participant's URL, keyUsage digitalSignature (critical), basicConstraints cA=false (critical).
* CA certificates: ``O=<net>``, basicConstraints cA=true, pathLen=0, keyUsage keyCertSign, cRLSign.
* Record signatures: ``sajha-net-v1:<type>:`` + JCS of the record without ``signature``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import ipaddress
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.x509.oid import NameOID

from sajha.net import jcs

#: The non-critical extension a renewed certificate carries: the previous certificate's serial
#: (lowercase hex, DER UTF8String), so members can follow a name's lineage (protocol §5.2, §8.1).
#: A UUID-derived OID (ITU-T X.667: 2.25.<uuid as integer>) needs no registration.
RENEWS_OID = x509.ObjectIdentifier('2.25.190758061232497851004893727469883845651')

ED25519 = 'ed25519'
P256 = 'ecdsa-p256-sha256'
ALGORITHMS = (ED25519, P256)


class CryptoError(ValueError):
    """A key, certificate or signature that is unusable; ``reason`` is a protocol reason."""

    def __init__(self, reason: str, detail: str = ''):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason


# ── encodings ───────────────────────────────────────────────────────

def b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def unb64(text: str) -> bytes:
    return base64.b64decode(text + '=' * (-len(text) % 4), validate=True)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('ascii').rstrip('=')


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def utc(ts: Optional[float] = None) -> _dt.datetime:
    return _dt.datetime.fromtimestamp(ts if ts is not None else _dt.datetime.now(_dt.timezone.utc).timestamp(),
                                      _dt.timezone.utc)


def rfc3339(ts: Optional[float] = None) -> str:
    return utc(ts).strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_rfc3339(text: str) -> float:
    return _dt.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=_dt.timezone.utc).timestamp()


# ── keys ────────────────────────────────────────────────────────────

def generate_key(alg: str = ED25519):
    if alg == ED25519:
        return ed25519.Ed25519PrivateKey.generate()
    if alg == P256:
        return ec.generate_private_key(ec.SECP256R1())
    raise CryptoError('signature_invalid', f'unsupported algorithm {alg}')


def ed25519_from_seed(seed: bytes) -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.from_private_bytes(seed)


def alg_of(key) -> str:
    """The protocol algorithm of a private or public key; raises for any other key type."""
    if isinstance(key, (ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey)):
        return ED25519
    if isinstance(key, (ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey)) and \
            isinstance(key.curve, ec.SECP256R1):
        return P256
    raise CryptoError('signature_invalid', f'unsupported key type {type(key).__name__}')


def key_to_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def key_from_pem(data: bytes):
    k = serialization.load_pem_private_key(data, password=None)
    alg_of(k)
    return k


def sign_raw(key, data: bytes) -> bytes:
    alg = alg_of(key)
    if alg == ED25519:
        return key.sign(data)
    r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


def verify_raw(public_key, alg: str, data: bytes, sig: bytes) -> bool:
    """True when ``sig`` (raw encoding of §8.2) verifies; False for any mismatch, including an
    ``alg`` that does not match the key or a DER-encoded ECDSA signature."""
    try:
        if alg not in ALGORITHMS or alg_of(public_key) != alg:
            return False
        if alg == ED25519:
            if len(sig) != 64:
                return False
            public_key.verify(sig, data)
            return True
        if len(sig) != 64:
            return False
        der = encode_dss_signature(int.from_bytes(sig[:32], 'big'), int.from_bytes(sig[32:], 'big'))
        public_key.verify(der, data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, CryptoError, ValueError):
        return False


# ── certificates ────────────────────────────────────────────────────

def thumbprint(der: bytes) -> str:
    return b64url(hashlib.sha256(der).digest())


def cert_der(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)


def load_cert(data: bytes) -> x509.Certificate:
    if data.lstrip().startswith(b'-----BEGIN'):
        return x509.load_pem_x509_certificate(data.strip())
    return x509.load_der_x509_certificate(data)


def cert_pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _name_attr(name: x509.Name, oid) -> Optional[str]:
    v = name.get_attributes_for_oid(oid)
    return str(v[0].value) if v else None


def subject_of(cert: x509.Certificate) -> Tuple[Optional[str], Optional[str]]:
    """``(O, CN)`` of the certificate's subject."""
    return _name_attr(cert.subject, NameOID.ORGANIZATION_NAME), _name_attr(cert.subject, NameOID.COMMON_NAME)


def serial_hex(cert: x509.Certificate) -> str:
    return format(cert.serial_number, 'x')


def san_hosts(cert: x509.Certificate) -> List[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return [h.lower() for h in ext.get_values_for_type(x509.DNSName)] + \
        [str(a) for a in ext.get_values_for_type(x509.IPAddress)]


def host_in_san(cert: x509.Certificate, host: str) -> bool:
    host = (host or '').strip('[]').lower().rstrip('.')
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        pass
    return host in san_hosts(cert)


def _san_entry(host: str):
    host = host.strip('[]')
    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host.lower())


def _subject(net: str, cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, net),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _sig_hash(key):
    return None if alg_of(key) == ED25519 else hashes.SHA256()


def _serial() -> int:
    return int.from_bytes(os.urandom(16), 'big') >> 1


def make_ca_certificate(ca_key, net: str, days: int = 3650, now: Optional[float] = None,
                        common_name: Optional[str] = None) -> x509.Certificate:
    start = utc(now) - _dt.timedelta(minutes=5)
    name = _subject(net, common_name or f'{net} CA')
    b = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
         .serial_number(_serial()).not_valid_before(start).not_valid_after(start + _dt.timedelta(days=days))
         .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
         .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False, key_encipherment=False,
                                      data_encipherment=False, key_agreement=False, key_cert_sign=True,
                                      crl_sign=True, encipher_only=False, decipher_only=False), critical=True))
    return b.sign(ca_key, _sig_hash(ca_key))


def _leaf_builder(public_key, net: str, instance: str, host: str, start: _dt.datetime, days: float, serial: int):
    return (x509.CertificateBuilder().subject_name(_subject(net, instance)).public_key(public_key)
            .serial_number(serial).not_valid_before(start).not_valid_after(start + _dt.timedelta(days=days))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectAlternativeName([_san_entry(host)]), critical=False))


def issue_certificate(ca_key, ca_cert: x509.Certificate, public_key, net: str, instance: str, host: str,
                      days: float = 30, now: Optional[float] = None, serial: Optional[int] = None,
                      renews: Optional[str] = None) -> x509.Certificate:
    start = utc(now) - _dt.timedelta(minutes=1)
    b = _leaf_builder(public_key, net, instance, host, start, days, serial or _serial())
    if renews:
        raw = renews.encode('ascii')
        b = b.add_extension(x509.UnrecognizedExtension(RENEWS_OID, b'\x0c' + bytes([len(raw)]) + raw), critical=False)
    return b.issuer_name(ca_cert.subject).sign(ca_key, _sig_hash(ca_key))


def renews_of(cert: x509.Certificate) -> Optional[str]:
    """The serial (lowercase hex) of the certificate this one renews, if the CA marked it."""
    try:
        v = cert.extensions.get_extension_for_oid(RENEWS_OID).value.value
    except x509.ExtensionNotFound:
        return None
    if len(v) < 2 or v[0] != 0x0c or v[1] != len(v) - 2:
        return None
    try:
        text = v[2:].decode('ascii')
    except UnicodeDecodeError:
        return None
    return text if text and all(c in '0123456789abcdef' for c in text) else None


def self_signed_certificate(key, net: str, instance: str, host: str, days: float = 365,
                            now: Optional[float] = None) -> x509.Certificate:
    """Manual mode (§8.11): a self-signed participant certificate with the §8.1 profile."""
    start = utc(now) - _dt.timedelta(minutes=1)
    b = _leaf_builder(key.public_key(), net, instance, host, start, days, _serial())
    return b.issuer_name(_subject(net, instance)).sign(key, _sig_hash(key))


def make_csr(key, net: str, instance: str, host: str) -> bytes:
    csr = (x509.CertificateSigningRequestBuilder().subject_name(_subject(net, instance))
           .add_extension(x509.SubjectAlternativeName([_san_entry(host)]), critical=False)
           .sign(key, _sig_hash(key)))
    return csr.public_bytes(serialization.Encoding.DER)


def load_csr(der: bytes) -> x509.CertificateSigningRequest:
    return x509.load_der_x509_csr(der)


def csr_hosts(csr: x509.CertificateSigningRequest) -> List[str]:
    try:
        ext = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return [h.lower() for h in ext.get_values_for_type(x509.DNSName)] + \
        [str(a) for a in ext.get_values_for_type(x509.IPAddress)]


def _verify_issued_by(cert: x509.Certificate, issuer: x509.Certificate) -> bool:
    pub = issuer.public_key()
    try:
        if isinstance(pub, ed25519.Ed25519PublicKey):
            pub.verify(cert.signature, cert.tbs_certificate_bytes)
        elif isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        else:
            return False
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _within(cert: x509.Certificate, now: float) -> bool:
    t = utc(now)
    return cert.not_valid_before_utc <= t <= cert.not_valid_after_utc


def _is_ca(cert: x509.Certificate) -> bool:
    try:
        return bool(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
    except x509.ExtensionNotFound:
        return False


def verify_chain(chain: List[x509.Certificate], ca: x509.Certificate, now: float) -> None:
    """Raise :class:`CryptoError` ``certificate_invalid`` unless ``chain`` (leaf first, without the
    root) chains to ``ca`` and every certificate is within its validity period."""
    if not chain:
        raise CryptoError('certificate_invalid', 'no certificate')
    if _is_ca(chain[0]):
        raise CryptoError('certificate_invalid', 'the leaf is a CA certificate')
    path = list(chain) + [ca]
    for cert, issuer in zip(path, path[1:]):
        if cert.issuer != issuer.subject or not _verify_issued_by(cert, issuer):
            raise CryptoError('certificate_invalid', 'the certificate does not chain to the net CA')
        if issuer is not ca and not _is_ca(issuer):
            raise CryptoError('certificate_invalid', 'an intermediate is not a CA')
    for c in path:
        if not _within(c, now):
            raise CryptoError('certificate_invalid', 'a certificate in the chain is outside its validity period')


def verify_self_signed(cert: x509.Certificate, now: float) -> None:
    if not _verify_issued_by(cert, cert) or not _within(cert, now):
        raise CryptoError('certificate_invalid', 'the self-signed certificate does not verify or is not valid now')


# ── record signatures (§8.10) ───────────────────────────────────────

def record_signing_input(rtype: str, record: Dict[str, Any]) -> bytes:
    body = {k: v for k, v in record.items() if k != 'signature'}
    return f'sajha-net-v1:{rtype}:'.encode('ascii') + jcs.canonicalize(body)


def sign_record(rtype: str, record: Dict[str, Any], key, keyid: str) -> Dict[str, str]:
    """The ``signature`` object for ``record`` (which is not modified)."""
    sig = sign_raw(key, record_signing_input(rtype, record))
    return {'alg': alg_of(key), 'keyid': keyid, 'sig': b64url(sig)}


def verify_record(rtype: str, record: Dict[str, Any], signature: Dict[str, Any], public_key) -> bool:
    if not isinstance(signature, dict):
        return False
    try:
        sig = unb64url(str(signature.get('sig') or ''))
    except Exception:
        return False
    return verify_raw(public_key, str(signature.get('alg') or ''), record_signing_input(rtype, record), sig)


def chain_from_b64(items: Iterable[str]) -> List[x509.Certificate]:
    try:
        return [load_cert(unb64(s)) for s in items]
    except Exception:
        raise CryptoError('certificate_invalid', 'a certificate cannot be parsed')
