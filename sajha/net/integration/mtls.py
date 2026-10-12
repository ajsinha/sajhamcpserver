# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Mutual TLS between participants (design §19 ``sajhanet.mtls``; protocol §19).

Signatures authenticate every request and response whatever the transport (protocol §8); mutual TLS adds
the transport check some operators require. ``sajhanet.mtls``:

* ``off`` (default): nothing changes.
* ``client``: this server presents its instance certificate of the net concerned (the one it signs with,
  chosen by the request's ``Sajha-Net-Name``) as its TLS client certificate on every outbound request to
  a member. The private key is loaded into the TLS context from a temporary file that is deleted at once.
* ``require``: ``client``, and every signed request arriving under ``/sajhanet/`` or at the MCP endpoint
  must come over a TLS connection whose verified client certificate is the leaf of the request's
  ``Sajha-Net-Certificate``. TLS is terminated in front of SAJHA (uvicorn with ``--ssl-cert-reqs 2`` behind
  a proxy, nginx, Envoy, an ingress), which verifies the client certificate against the net's CA and passes
  it in the header ``sajhanet.mtls_client_cert_header`` (default ``x-ssl-client-cert``: URL-escaped PEM, as
  nginx's ``$ssl_client_escaped_cert``; base64 DER is accepted too). The terminator MUST strip that header
  from client requests. A request without it, or with another certificate, is refused with an unsigned
  ``401`` before the net sees it. Enrollment (``/sajhanet/v1/ca/enroll``), which a newcomer makes before it
  has a certificate, is exempt.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import logging
import os
import ssl
import tempfile
import threading
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import unquote, urlsplit

from sajha.net import crypto, sfv
from sajha.net.plugins import PeerConnector, PeerResponse

logger = logging.getLogger(__name__)

MODES = ('off', 'client', 'require')
DEFAULT_HEADER = 'x-ssl-client-cert'
EXEMPT = ('/sajhanet/v1/ca/enroll',)


def mode_of(value: Any) -> str:
    v = str(value or 'off').strip().lower()
    if v in ('false', 'no', '0', ''):
        return 'off'
    if v in ('true', 'yes', '1', 'on'):
        return 'require'
    if v not in MODES:
        logger.warning(f'sajhanet.mtls: {value!r} is not one of {MODES}; using off')
        return 'off'
    return v


def client_cert_header() -> str:
    from sajha.net.integration.config import _g
    return str(_g('mtls_client_cert_header', DEFAULT_HEADER)).strip().lower() or DEFAULT_HEADER


def _client_cert(value: str):
    """The certificate a TLS terminator passed: URL-escaped (or plain) PEM, or base64 DER."""
    text = unquote(value.strip()) if '%' in value else value.strip()
    if 'BEGIN CERTIFICATE' in text:
        from cryptography import x509
        return x509.load_pem_x509_certificate(text.replace('\t', '\n').encode('ascii'))
    return crypto.load_cert(base64.b64decode(text))


def inbound_problem(mode: str, path: str, headers: Dict[str, str], header: str = DEFAULT_HEADER) -> Optional[str]:
    """Why a request may not be served under ``require`` (None: it may). ``headers`` lower-cased."""
    if mode != 'require' or path in EXEMPT:
        return None
    if not any(k.startswith('sajha-net-') for k in headers):
        return None                                  # not a net request; the endpoint handles it as usual
    raw = headers.get(header)
    if not raw:
        return 'mutual TLS is required: the request did not come with a verified TLS client certificate'
    try:
        presented = _client_cert(raw)
    except Exception:
        return 'mutual TLS is required: the TLS client certificate cannot be read'
    try:
        items = sfv.parse_list(headers.get('sajha-net-certificate', ''))
        leaf = crypto.load_cert(items[0][0])
    except Exception:
        return 'mutual TLS is required: Sajha-Net-Certificate cannot be parsed'
    if crypto.cert_der(presented) != crypto.cert_der(leaf):
        return 'mutual TLS is required: the TLS client certificate is not the certificate the request is signed with'
    return None


def refusal_response(why: str):
    """The unsigned 401 a request refused by :func:`inbound_problem` gets."""
    import json
    from starlette.responses import Response
    body = {'type': 'urn:sajha:net:error:certificate_invalid', 'title': 'Certificate invalid', 'status': 401,
            'reason': 'certificate_invalid', 'detail': why}
    return Response(content=json.dumps(body), status_code=401, media_type='application/problem+json')


class MtlsConnector(PeerConnector):
    """An HTTP connector that presents this server's instance certificate of the request's net as its TLS
    client certificate (``client`` and ``require``). ``identity(net)`` returns ``(private key, certificate
    chain)`` of that net, or None (the request then goes without a client certificate)."""
    name = 'sajha_native_mtls'

    def __init__(self, identity: Callable[[str], Optional[Tuple[Any, list]]], verify_tls: bool = True,
                 max_connections_per_peer: int = 10):
        self.identity = identity
        self.verify_tls = verify_tls
        self.max_connections = max_connections_per_peer
        self._clients: Dict[Tuple[str, str, str], Any] = {}
        self._lock = threading.Lock()

    def _context(self, key, chain) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if not self.verify_tls:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        fd, path = tempfile.mkstemp(prefix='sajhanet-mtls-', suffix='.pem')
        try:
            os.chmod(path, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(crypto.key_to_pem(key))
                for c in chain:
                    f.write(crypto.cert_pem(c))
            ctx.load_cert_chain(path)
        finally:
            try:
                os.unlink(path)                      # the key lives only in the TLS context from here
            except OSError:
                pass
        return ctx

    def _client(self, url: str, net: str):
        import httpx
        p = urlsplit(url)
        base = f'{p.scheme}://{p.netloc}'
        ident = self.identity(net) if net else None
        serial = crypto.serial_hex(ident[1][0]) if ident else ''
        k = (base, net, serial)
        with self._lock:
            c = self._clients.get(k)
            if c is None:
                for old in [x for x in self._clients if x[0] == base and x[1] == net and x[2] != serial]:
                    try:
                        self._clients.pop(old).close()           # a renewed certificate: a new pool
                    except Exception:
                        pass
                verify: Any = self._context(*ident) if ident and p.scheme == 'https' else self.verify_tls
                c = httpx.Client(verify=verify, follow_redirects=False,
                                 limits=httpx.Limits(max_connections=self.max_connections,
                                                     max_keepalive_connections=self.max_connections))
                self._clients[k] = c
            return c

    def send(self, method, url, headers, body, timeout, stream=False):
        import httpx
        from sajha.net.plugins import PeerUnreachable
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        client = self._client(url, str(h.get('sajha-net-name') or ''))
        content = body if method.upper() != 'GET' else None
        try:
            if stream:
                req = client.build_request(method, url, headers=headers, content=content, timeout=timeout)
                r = client.send(req, stream=True)
            else:
                r = client.request(method, url, headers=headers, content=content, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol) as e:
            raise PeerUnreachable(f'{e.__class__.__name__}: {e}', sent=False) from e
        except httpx.HTTPError as e:
            raise PeerUnreachable(f'{e.__class__.__name__}: {e}', sent=True) from e
        headers_out = {k.lower(): v for k, v in r.headers.items()}
        if stream:
            return PeerResponse(r.status_code, headers_out, b'', stream=r.iter_raw(), close=r.close)
        return PeerResponse(r.status_code, headers_out, r.content)
