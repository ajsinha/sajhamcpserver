"""
Transport settings for the HTTP server (uvicorn): trusted proxies and native TLS.

    server.trusted_proxies   proxies whose X-Forwarded-For / X-Forwarded-Proto uvicorn believes
                             (its forwarded_allow_ips); empty: uvicorn's default
    server.tls.certfile      serve https directly with this certificate chain ...
    server.tls.keyfile       ... and key (else terminate TLS at a proxy)
    server.tls.min_version   TLSv1.2 (default) or TLSv1.3

docs/security/Security Model.md section 3 (Transport protections)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
from __future__ import annotations

import ssl
from typing import Any, Dict, Optional

_VERSIONS = {'tlsv1.2': ssl.TLSVersion.TLSv1_2, '1.2': ssl.TLSVersion.TLSv1_2,
             'tlsv1.3': ssl.TLSVersion.TLSv1_3, '1.3': ssl.TLSVersion.TLSv1_3}


def tls_min_version() -> ssl.TLSVersion:
    from sajha.core.config import _get
    raw = str(_get('server.tls.min_version', 'TLSv1.2') or 'TLSv1.2').strip().lower()
    if raw not in _VERSIONS:
        raise ValueError(f'server.tls.min_version must be TLSv1.2 or TLSv1.3, not {raw!r}')
    return _VERSIONS[raw]


def uvicorn_kwargs() -> Dict[str, Any]:
    """Extra uvicorn.run / uvicorn.Config arguments from the configuration."""
    from sajha.core.config import _get
    out: Dict[str, Any] = {}
    proxies = str(_get('server.trusted_proxies', '') or '').strip()
    if proxies:
        out['forwarded_allow_ips'] = proxies
        out['proxy_headers'] = True
    cert = str(_get('server.tls.certfile', '') or '').strip()
    key = str(_get('server.tls.keyfile', '') or '').strip()
    if cert or key:
        if not (cert and key):
            raise ValueError('server.tls.certfile and server.tls.keyfile must be set together')
        out['ssl_certfile'], out['ssl_keyfile'] = cert, key
        out['ssl_version'] = ssl.PROTOCOL_TLS_SERVER
    return out


def harden_ssl_context(ctx: Optional[ssl.SSLContext]) -> None:
    """Raise a server context's floor to ``server.tls.min_version`` (never below TLS 1.2)."""
    if ctx is None:
        return
    ctx.minimum_version = max(tls_min_version(), ssl.TLSVersion.TLSv1_2)
    ctx.options |= ssl.OP_NO_COMPRESSION
