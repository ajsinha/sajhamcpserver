"""
Admission (design §5.3, §6.4, §6.5; protocol §8.1, §8.11, §13): what a receiver checks a
certificate against in one net, and the two shipped admission plug-ins.

* ``builtin_ca``: the chain must lead to the net's CA certificate and must not be on the net's
  CA-signed revocation list.
* ``manual``: a self-signed certificate whose thumbprint an administrator pinned for the net;
  removing the pin is the revocation.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from sajha.net import crypto, schemas
from sajha.net.httpsig import Trust
from sajha.net.plugins import AdmissionProvider, register


class CATrust(Trust):
    def __init__(self, net: str, ca_certificate, revocations: Callable[[], Optional[Dict[str, Any]]]):
        self.net = net
        self.ca = ca_certificate
        self._revocations = revocations

    def check_chain(self, chain, now):
        if self.ca is None:
            raise crypto.CryptoError('certificate_invalid', 'no CA certificate is configured for this net')
        crypto.verify_chain(chain, self.ca, now)

    def revocation(self, serial: str, instance: str) -> Optional[str]:
        return revocation_reason(self._revocations(), serial, instance)


class PinnedTrust(Trust):
    def __init__(self, net: str, pins: Callable[[], List[str]]):
        self.net = net
        self._pins = pins

    def check_chain(self, chain, now):
        if len(chain) != 1:
            raise crypto.CryptoError('certificate_invalid', 'manual mode expects one self-signed certificate')
        crypto.verify_self_signed(chain[0], now)
        if crypto.thumbprint(crypto.cert_der(chain[0])) not in set(self._pins() or []):
            raise crypto.CryptoError('certificate_invalid', 'the certificate thumbprint is not pinned for this net')

    def revocation(self, serial, instance):
        return None


def revocation_reason(rl: Optional[Dict[str, Any]], serial: str, instance: str) -> Optional[str]:
    if not rl:
        return None
    for e in rl.get('revoked') or []:
        if e.get('serial') and e['serial'] == serial:
            return 'certificate_revoked'
    for e in rl.get('revoked') or []:
        if e.get('instance') and e['instance'] == instance:
            return 'instance_revoked'
    return None


def verify_revocation_list(doc: Any, ca_certificate, net: str) -> bool:
    """§13: CA-signed (``keyid`` the CA thumbprint), for this net, valid against its schema."""
    if not isinstance(doc, dict) or ca_certificate is None or doc.get('net') != net:
        return False
    if not schemas.is_valid('revocation_list', doc):
        return False
    sig = doc.get('signature') or {}
    if sig.get('keyid') != crypto.thumbprint(crypto.cert_der(ca_certificate)):
        return False
    return crypto.verify_record('revocations', doc, sig, ca_certificate.public_key())


@register('admission')
class BuiltinCA(AdmissionProvider):
    name = 'builtin_ca'
    manual = False

    def trust(self, net, cfg, ca_certificate, revocations, pins):
        return CATrust(net, ca_certificate, revocations)


@register('admission')
class ManualAdmission(AdmissionProvider):
    name = 'manual'
    manual = True

    def trust(self, net, cfg, ca_certificate, revocations, pins):
        return PinnedTrust(net, pins)
