"""
SAJHA MCP Server — who may read /metrics, and the optional separate metrics listener.

``observability.metrics.auth``: ``admin`` (a signed-in administrator), ``token``
(``Authorization: Bearer $SAJHA_OBSERVABILITY_METRICS_TOKEN``, or an administrator) or
``none``. ``observability.metrics.port`` > 0 also serves ``/metrics`` (same rule) on
``observability.metrics.host``, so scrapes can stay off the public interface.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hmac
import logging
import threading
from http.cookies import SimpleCookie
from typing import Mapping, Optional, Tuple

from sajha.observability import settings as S

logger = logging.getLogger(__name__)


def _is_admin_token(token: str) -> bool:
    if not token:
        return False
    try:
        from sajha.auth import AuthManager
        from sajha.db.engine import get_db_session
        db = get_db_session()
        try:
            ctx = AuthManager.authenticate_jwt(db, token)
            return bool(ctx and ctx.is_admin)
        finally:
            db.close()
    except Exception:
        return False


def authorize(headers: Mapping[str, str], cookies: Mapping[str, str]) -> Tuple[bool, int, str]:
    """(allowed, status when refused, reason)."""
    mode = S.metrics_auth()
    if mode == 'none':
        return True, 200, ''
    auth = headers.get('authorization') or headers.get('Authorization') or ''
    bearer = auth[7:].strip() if auth[:7].lower() == 'bearer ' else ''
    if mode == 'token':
        tok = S.metrics_token()
        if tok and bearer and hmac.compare_digest(bearer.encode(), tok.encode()):
            return True, 200, ''
    if _is_admin_token(bearer) or _is_admin_token(cookies.get('sajha_token', '')):
        return True, 200, ''
    if not bearer and not cookies.get('sajha_token'):
        return False, 401, 'authentication required'
    return False, 403, 'not allowed to read metrics'


# ── the separate listener ───────────────────────────────────────────

_server = None
_thread: Optional[threading.Thread] = None


def start_metrics_server() -> bool:
    global _server, _thread
    port = S.get_int('observability.metrics.port', 0)
    if port <= 0 or _server is not None or not S.metrics_enabled():
        return False
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from sajha.observability.metrics import CONTENT_TYPE, exposition

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.split('?')[0] != '/metrics':
                self.send_error(404)
                return
            jar = SimpleCookie()
            try:
                jar.load(self.headers.get('Cookie') or '')
            except Exception:
                pass
            ok, status, why = authorize({k.lower(): v for k, v in self.headers.items()},
                                        {k: m.value for k, m in jar.items()})
            if not ok:
                body = why.encode()
                self.send_response(status)
                if status == 401:
                    self.send_header('WWW-Authenticate', 'Bearer realm="sajha-metrics"')
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = exposition().encode()
            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            logger.debug('metrics listener: ' + fmt % args)

    host = S.get_str('observability.metrics.host', '127.0.0.1') or '127.0.0.1'
    try:
        _server = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        logger.warning(f'  Metrics listener: cannot bind {host}:{port} ({e})')
        return False
    _thread = threading.Thread(target=_server.serve_forever, name='sajha-metrics-listener', daemon=True)
    _thread.start()
    logger.info(f'  Metrics listener: http://{host}:{port}/metrics (auth {S.metrics_auth()})')
    return True


def stop_metrics_server() -> None:
    global _server, _thread
    if _server is not None:
        try:
            _server.shutdown()
            _server.server_close()
        except Exception:
            pass
    _server, _thread = None, None
