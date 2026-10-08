"""
SAJHA MCP Server v5.3.0 — Security Module
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Centralized security: password hashing, API key hashing, rate limiting,
security headers, input validation helpers.
"""
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Optional

import bcrypt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, JSONResponse

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# PASSWORD HASHING (bcrypt)
# ═══════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash a password with bcrypt (12 rounds)."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception as e:
        logger.warning(f"Password verification error: {e}", exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════
# API KEY HASHING (SHA-256)
# ═══════════════════════════════════════════════════════════════════

def hash_api_key(key: str) -> str:
    """Hash an API key with SHA-256 for storage."""
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def generate_api_key(prefix: str = 'sja_') -> tuple:
    """Generate a new API key. Returns (raw_key, hash, display_prefix)."""
    raw = prefix + secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw)
    display_prefix = raw[:12] + '...'
    return raw, key_hash, display_prefix


# ═══════════════════════════════════════════════════════════════════
# SESSION TOKEN HASHING (SHA-256)
# ═══════════════════════════════════════════════════════════════════

def generate_session_token() -> tuple:
    """Generate a session token. Returns (raw_token, hash)."""
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return raw, token_hash


def hash_token(token: str) -> str:
    """Hash a session token for DB lookup."""
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


# ═══════════════════════════════════════════════════════════════════
# RATE LIMITING (per IP / user / key, in the state store)
# ═══════════════════════════════════════════════════════════════════

def _state():
    from sajha.core.state import get_state_store
    return get_state_store()


class RateLimiter:
    """
    Sliding-window rate limiter.  The windows live in the state store
    (``state.backend``): per process with the memory backend, shared by every
    worker with redis or database, so N workers do not allow N times the limit.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60, name: str = 'rl'):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name

    def _key(self, key: str) -> str:
        return f'ratelimit:{self.name}:{key}'

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed under the rate limit (and count it if so)."""
        allowed, _ = _state().window_add(self._key(key), self.window_seconds, self.max_requests)
        return allowed

    def remaining(self, key: str) -> int:
        """Get remaining requests in the current window."""
        return max(0, self.max_requests - _state().window_count(self._key(key), self.window_seconds))

    def reset(self, key: Optional[str] = None) -> None:
        st = _state()
        if key is None:
            st.delete_prefix(f'ratelimit:{self.name}:')
        else:
            st.delete(self._key(key))


# Global rate limiters
_auth_limiter = RateLimiter(max_requests=5, window_seconds=60, name='auth')  # 5 login attempts per minute
_api_limiter = RateLimiter(max_requests=100, window_seconds=60, name='api')  # 100 API calls per minute


def check_auth_rate_limit(request: Request) -> bool:
    """Check if auth request is within rate limit."""
    ip = request.client.host if request.client else 'unknown'
    return _auth_limiter.is_allowed(f"auth:{ip}")


class FailureThrottle:
    """
    Counts *failed* sign-ins per key (client IP) in a sliding window; successful
    sign-ins cost nothing, so a busy office behind one NAT is not locked out by its own
    users.  Limits are read live from ``auth.login.ip_max_failures`` /
    ``auth.login.ip_window_seconds``.  Counts live in the state store (shared
    between workers with the redis or database backend).
    """

    _PREFIX = 'loginfail:'

    @staticmethod
    def _limits() -> tuple:
        from sajha.core.config import _int
        return max(1, _int('auth.login.ip_max_failures', 20)), max(1, _int('auth.login.ip_window_seconds', 300))

    def blocked(self, key: str) -> bool:
        limit, window = self._limits()
        return _state().window_count(self._PREFIX + key, window) >= limit

    def record_failure(self, key: str) -> None:
        _, window = self._limits()
        _state().window_add(self._PREFIX + key, window)

    def reset(self, key: Optional[str] = None) -> None:
        st = _state()
        if key is None:
            st.delete_prefix(self._PREFIX)
        else:
            st.delete(self._PREFIX + key)


_login_throttle = FailureThrottle()


def _client_key(request: Request) -> str:
    return f"login:{request.client.host if request.client else 'unknown'}"


def login_blocked(request: Request) -> bool:
    """True when this client IP has too many recent failed sign-ins (answer 429)."""
    return _login_throttle.blocked(_client_key(request))


def record_login_failure(request: Request) -> None:
    _login_throttle.record_failure(_client_key(request))


def check_api_rate_limit(request: Request) -> bool:
    """Check if API request is within rate limit."""
    ip = request.client.host if request.client else 'unknown'
    return _api_limiter.is_allowed(f"api:{ip}")


# ═══════════════════════════════════════════════════════════════════
# SECURITY HEADERS AND CONTENT SECURITY POLICY (per-request nonces)
# ═══════════════════════════════════════════════════════════════════
#
# Every response gets a fresh CSP nonce.  Templates mark their inline <script> elements with
# ``nonce="{{ csp_nonce() }}"`` (a Jinja global, sajha/app.py); scripts without it, and every
# inline event handler attribute (onclick=...), are refused by the browser.  The console's
# handlers are data-on* attributes run by /static/js/csp-actions.js instead.

import contextvars

_CSP_NONCE: contextvars.ContextVar[str] = contextvars.ContextVar('sajha_csp_nonce', default='')


def csp_nonce() -> str:
    """The current response's CSP nonce (one is created when none is set, e.g. outside a request)."""
    n = _CSP_NONCE.get()
    if not n:
        n = secrets.token_urlsafe(18)
        _CSP_NONCE.set(n)
    return n


def console_csp(nonce: Optional[str] = None, *, frame_ancestors: str = "'self'",
                img_src: str = "'self' data:", extra: str = '') -> str:
    """
    The console's Content-Security-Policy.  Scripts: this origin plus inline scripts carrying the
    response's nonce; no inline event handlers.  Styles keep 'unsafe-inline' (style attributes are
    used throughout the templates and by the vendored libraries; CSS cannot run script).
    """
    nonce = nonce or csp_nonce()
    policy = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "script-src-attr 'none'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        f"img-src {img_src}; "
        "connect-src 'self' ws: wss:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        f"frame-ancestors {frame_ancestors}"
    )
    return policy + (f'; {extra}' if extra else '')


def _hsts_value() -> Optional[str]:
    from sajha.core.config import _bool, _int
    age = _int('security.hsts.max_age', 31536000)
    if age <= 0:
        return None
    return f'max-age={age}' + ('; includeSubDomains' if _bool('security.hsts.include_subdomains', True) else '')


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers (and a per-request CSP nonce) to all responses."""

    async def dispatch(self, request: Request, call_next):
        nonce = secrets.token_urlsafe(18)
        _CSP_NONCE.set(nonce)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Routes may set a stricter policy (e.g. the OAuth consent page: DENY,
        # frame-ancestors 'none'); keep theirs.
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        # The legacy XSS auditor is off in every current browser and could be abused where it
        # remains; the CSP is the protection.  OWASP: send 0.
        response.headers['X-XSS-Protection'] = '0'
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy',
                                    'camera=(), microphone=(), geolocation=(), payment=(), usb=()')
        # All JS/CSS/fonts are vendored under /static/vendor: self-only, plus this response's nonce.
        response.headers.setdefault('Content-Security-Policy', console_csp(nonce))
        # HSTS only if the request came over HTTPS (behind a proxy: server.trusted_proxies)
        if request.url.scheme == 'https':
            hsts = _hsts_value()
            if hsts:
                response.headers['Strict-Transport-Security'] = hsts
        return response


# ═══════════════════════════════════════════════════════════════════
# CROSS-SITE REQUEST CHECK (CSRF for cookie sessions)
# ═══════════════════════════════════════════════════════════════════

_UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
#: Paths that check Origin themselves (the MCP DNS-rebinding allow-list, mcp.allowed_origins).
CSRF_EXEMPT_PREFIXES = ('/mcp', '/api/mcp')


def _origin_of(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url)
    except ValueError:
        return ''
    if not u.scheme or not u.netloc:
        return ''
    return f'{u.scheme.lower()}://{u.netloc.lower()}'


def trusted_origins() -> set:
    """Origins besides this server's own that may send cookie-authenticated state changes:
    ``security.csrf.trusted_origins`` and the CORS origins (``SAJHA_CORS_ORIGINS``)."""
    from sajha.core.config import _list
    out = {o.rstrip('/').lower() for o in _list('security.csrf.trusted_origins', []) if o}
    cors = os.environ.get('SAJHA_CORS_ORIGINS', '')
    out.update(o.strip().rstrip('/').lower() for o in cors.split(',') if o.strip())
    return out


def cross_site_refusal(method: str, path: str, headers: dict) -> Optional[str]:
    """
    Why a request must be refused as cross-site, or None.  It applies to state-changing methods
    that carry the console session cookie: the browser's ``Origin`` (or, without one,
    ``Referer``) must be this server (the ``Host`` it was sent to) or a trusted origin.  A request
    without either header is not from a browser page and passes (browsers always send ``Origin``
    on a cross-site POST); one with ``Origin: null`` is refused.  Pages' own CSRF tokens still
    apply on top.
    """
    if method not in _UNSAFE_METHODS or path.startswith(CSRF_EXEMPT_PREFIXES):
        return None
    cookie = headers.get('cookie', '')
    if 'sajha_token=' not in cookie:
        return None
    origin = headers.get('origin')
    if origin is None:
        ref = headers.get('referer')
        if not ref:
            return None
        origin = _origin_of(ref) or 'null'
    origin = origin.strip().rstrip('/').lower()
    if origin == 'null' or not origin:
        return 'Origin null'
    host = (headers.get('host') or '').strip().lower()
    if host and origin.split('://', 1)[-1] == host:
        return None
    if origin in trusted_origins():
        return None
    from sajha.core.config import _get
    public = _origin_of((_get('mcp.auth.public_url', '') or '').strip())
    if public and origin == public:
        return None
    return f'Origin {origin} is not this server'


class CrossSiteRequestMiddleware:
    """Refuse cookie-authenticated state changes sent from another site (403); pure ASGI."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode('latin-1').lower(): v.decode('latin-1') for k, v in scope.get('headers') or []}
        why = cross_site_refusal(scope.get('method', 'GET'), scope.get('path', ''), headers)
        if why:
            logger.warning(f"Cross-site request refused: {scope.get('method')} {scope.get('path')} ({why})")
            resp = JSONResponse({'error': 'cross-site request refused', 'detail': why}, status_code=403)
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


# ═══════════════════════════════════════════════════════════════════
# ALLOWED HOSTS (Host header allow-list; off unless configured)
# ═══════════════════════════════════════════════════════════════════

_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '[::1]', '::1')


def allowed_hosts() -> list:
    from sajha.core.config import _list
    return [h.strip().lower() for h in _list('security.allowed_hosts', []) if h.strip()]


def host_allowed(host_header: str, allowed: list) -> bool:
    """``security.allowed_hosts`` entries: exact names or ``*.example.com``; ``*`` allows any.
    Loopback names always pass, so local tools and health checks keep working."""
    if not allowed or '*' in allowed:
        return True
    host = (host_header or '').strip().lower()
    if host.startswith('['):
        name = host.split(']', 1)[0] + ']'
    else:
        name = host.rsplit(':', 1)[0] if host.count(':') == 1 else host
    if name in _LOOPBACK_HOSTS:
        return True
    for a in allowed:
        if a.startswith('*.') and (name.endswith(a[1:]) and name != a[2:]):
            return True
        if name == a:
            return True
    return False


class AllowedHostsMiddleware:
    """400 for a Host header not in ``security.allowed_hosts`` (DNS rebinding, host-header
    poisoning).  Pure ASGI; read once at start-up."""

    def __init__(self, app, hosts: Optional[list] = None):
        self.app = app
        self.hosts = allowed_hosts() if hosts is None else hosts

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket') or not self.hosts:
            return await self.app(scope, receive, send)
        host = ''
        for k, v in scope.get('headers') or []:
            if k == b'host':
                host = v.decode('latin-1')
                break
        if host_allowed(host, self.hosts):
            return await self.app(scope, receive, send)
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1008})
        resp = JSONResponse({'error': 'Invalid host header'}, status_code=400)
        return await resp(scope, receive, send)


# ═══════════════════════════════════════════════════════════════════
# REQUEST SIZE LIMITING MIDDLEWARE (Content-Length and streamed bodies)
# ═══════════════════════════════════════════════════════════════════

def max_request_bytes() -> int:
    from sajha.core.config import _int
    return max(1024, _int('server.max_request_bytes', 10 * 1024 * 1024))


from starlette.exceptions import HTTPException as _StarletteHTTPException


class _BodyTooLarge(_StarletteHTTPException):
    """Raised while reading a body past the limit; an HTTPException, so the app answers 413."""

    def __init__(self, limit: int):
        super().__init__(status_code=413, detail=f'Request body too large. Maximum: {limit} bytes')


class RequestSizeLimitMiddleware:
    """
    Reject request bodies larger than ``max_body_size`` bytes with 413: at once when the
    ``Content-Length`` says so, and while reading when a body sent without one (chunked) passes
    the limit.  Pure ASGI, so streaming responses pass through untouched.
    """

    def __init__(self, app, max_body_size: Optional[int] = None):
        self.app = app
        self.max_body_size = max_body_size or max_request_bytes()

    def _too_large(self):
        return JSONResponse({'error': f'Request body too large. Maximum: {self.max_body_size} bytes'},
                            status_code=413)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        limit = self.max_body_size
        for k, v in scope.get('headers') or []:
            if k == b'content-length':
                try:
                    if int(v) > limit:
                        return await self._too_large()(scope, receive, send)
                except ValueError:
                    return await JSONResponse({'error': 'Invalid Content-Length'}, status_code=400)(
                        scope, receive, send)
        seen = 0
        started = False

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message['type'] == 'http.request':
                seen += len(message.get('body', b''))
                if seen > limit:
                    raise _BodyTooLarge(limit)
            return message

        async def tracking_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await self._too_large()(scope, receive, send)
        except Exception as e:  # an app wrapping the body read in its own handler re-raises ours
            if isinstance(e.__cause__, _BodyTooLarge) or isinstance(e.__context__, _BodyTooLarge):
                if not started:
                    await self._too_large()(scope, receive, send)
                return
            raise


# ═══════════════════════════════════════════════════════════════════
# ACCOUNT LOCKOUT
# ═══════════════════════════════════════════════════════════════════

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900  # 15 minutes


def check_account_locked(failed_attempts: int, locked_until: Optional[float]) -> bool:
    """Check if an account is locked due to failed attempts."""
    if failed_attempts >= MAX_FAILED_ATTEMPTS:
        if locked_until and time.time() < locked_until:
            return True
    return False


def get_lockout_time() -> float:
    """Get the lockout expiry timestamp."""
    return time.time() + LOCKOUT_DURATION_SECONDS


# Per-user and per-key limits on tool calls are policy rate_limit rules (one mechanism;
# config/policies/00-default.yaml carries a commented example). docs/security/Security Model.md
