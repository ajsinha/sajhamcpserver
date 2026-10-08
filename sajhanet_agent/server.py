"""
The agent's HTTP listener: the standard library's threading HTTP server in front of
:meth:`sajhanet_agent.agent.Agent.handle` (``/sajhanet/v1/...`` and the signed MCP endpoint), plus
``GET /healthz``. TLS when a certificate and key are given; behind a TLS proxy, ``trust_proxy_tls``
counts requests as secure (forwarded API keys are accepted only over HTTPS, protocol §15.3).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import urlsplit

logger = logging.getLogger('sajhanet_agent')

MAX_BODY = 8 * 1024 * 1024 + 1


def make_server(agent, host: str = '0.0.0.0', port: int = 8790, tls_cert: str = '', tls_key: str = '',
                trust_proxy_tls: bool = False) -> ThreadingHTTPServer:
    secure = bool(tls_cert) or trust_proxy_tls

    class Handler(BaseHTTPRequestHandler):
        server_version = 'sajhanet-agent'
        sys_version = ''

        def log_message(self, fmt, *args):            # requests are logged at debug level only
            logger.debug('%s %s', self.address_string(), fmt % args)

        def _serve(self, method: str) -> None:
            u = urlsplit(self.path)
            if method == 'GET' and u.path == '/healthz':
                st = agent.status()
                return self._send(200, {'content-type': 'application/json'},
                                  json.dumps({'ok': True, 'net': st['net'], 'instance': st['instance'],
                                              'joined': st['joined']}).encode())
            n = int(self.headers.get('content-length') or 0)
            if n > MAX_BODY:
                return self._send(413, {}, b'')
            body = self.rfile.read(n) if n else b''
            headers = {k.lower(): v for k, v in self.headers.items()}
            try:
                r = agent.handle(method, u.path, u.query, headers, body, secure=secure, source=self.client_address[0])
            except Exception as e:                    # never leak a trace to a peer
                logger.warning(f'request {method} {u.path} failed: {e}', exc_info=True)
                return self._send(500, {}, b'')
            self._send(r.status, r.headers, r.body)

        def _send(self, status, headers, body) -> None:
            self.send_response(status)
            for k, v in (headers or {}).items():
                if k.lower() not in ('content-length', 'connection', 'transfer-encoding'):
                    self.send_header(k, v)
            self.send_header('content-length', str(len(body or b'')))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            self._serve('GET')

        def do_POST(self):
            self._serve('POST')

        def do_DELETE(self):
            self._serve('DELETE')

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    if tls_cert:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(tls_cert, tls_key or None)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    return httpd
