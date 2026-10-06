"""
SAJHA MCP Server — signing key of the built-in OAuth authorization server.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

An RSA-2048 key (RS256) generated on first use into
``mcp.auth.builtin.signing_key_path`` (default data/oauth/signing_key.pem,
file mode 0600, git-ignored).  The public half is served at /oauth/jwks with a
RFC 7638 thumbprint as ``kid``.  Rotate by deleting the file and restarting:
outstanding access tokens then fail validation (clients refresh/re-authorize).
"""

import base64
import hashlib
import json
import logging
import os
import threading
from typing import Dict, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sajha.auth.oauth import settings

logger = logging.getLogger(__name__)

ALGORITHM = 'RS256'


def _b64u_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big')
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


class SigningKey:
    def __init__(self, private_pem: bytes):
        self.private_pem = private_pem
        key = serialization.load_pem_private_key(private_pem, password=None)
        numbers = key.public_key().public_numbers()
        e, n = _b64u_uint(numbers.e), _b64u_uint(numbers.n)
        # RFC 7638 thumbprint: lexicographic members, no whitespace
        canonical = json.dumps({'e': e, 'kty': 'RSA', 'n': n}, separators=(',', ':'), sort_keys=True)
        self.kid = base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).rstrip(b'=').decode()
        self.public_jwk: Dict[str, str] = {'kty': 'RSA', 'use': 'sig', 'alg': ALGORITHM,
                                           'kid': self.kid, 'n': n, 'e': e}
        self.public_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def jwks(self) -> Dict:
        return {'keys': [dict(self.public_jwk)]}


_lock = threading.Lock()
_cached: Optional[SigningKey] = None
_cached_path: Optional[str] = None


def get_signing_key() -> SigningKey:
    """Load (or create once) the persisted signing key."""
    global _cached, _cached_path
    path = settings.signing_key_path()
    with _lock:
        if _cached is not None and _cached_path == str(path):
            return _cached
        if path.exists():
            pem = path.read_bytes()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
            try:
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:          # another worker won the race
                pem = path.read_bytes()
            else:
                with os.fdopen(fd, 'wb') as f:
                    f.write(pem)
                logger.info(f'Generated OAuth signing key at {path}')
        _cached, _cached_path = SigningKey(pem), str(path)
        return _cached
