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


# (port) of the socket this process serves HTTP on, learnt from the first request (note_listening)
_listening_port: Optional[int] = None


def note_listening(scope) -> None:
    """Record the port this process actually listens on, from an HTTP request's ASGI ``server``
    (the local socket; not the Host header). Called for every request; only the first one counts.
    Starlette's TestClient reports a made-up ``testserver``, which is ignored."""
    global _listening_port
    if _listening_port is not None:
        return
    server = scope.get('server') if isinstance(scope, dict) else None
    if server and len(server) > 1 and server[1] and server[0] != 'testserver':
        _listening_port = int(server[1])


def local_base_url() -> str:
    """This server's own origin where no request is at hand (a link built inside a tool call, a CLI):
    ``http(s)://<server.host, or localhost for a wildcard bind>:<the listening port>``. The port is the
    one requests arrive on once one has; before that ``server.port``, which ``run_sajha_web.py --port``
    sets to the port it listens on. https when ``server.tls.certfile`` is set."""
    from sajha.core.config import _get, get_settings
    st = get_settings()
    host = st.server_host if st.server_host not in ('0.0.0.0', '::', '') else 'localhost'
    if ':' in host and not host.startswith('['):
        host = f'[{host}]'
    port = _listening_port or st.server_port
    scheme = 'https' if str(_get('server.tls.certfile', '') or '').strip() else 'http'
    return f'{scheme}://{host}:{port}'


def harden_ssl_context(ctx: Optional[ssl.SSLContext]) -> None:
    """Raise a server context's floor to ``server.tls.min_version`` (never below TLS 1.2)."""
    if ctx is None:
        return
    ctx.minimum_version = max(tls_min_version(), ssl.TLSVersion.TLSv1_2)
    ctx.options |= ssl.OP_NO_COMPRESSION
