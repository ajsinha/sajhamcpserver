"""
SAJHA MCP Server v5.1.0 — Security Module
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
from collections import defaultdict
from threading import Lock
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
# RATE LIMITING (in-memory, per-IP)
# ═══════════════════════════════════════════════════════════════════

class RateLimiter:
    """
    Simple in-memory rate limiter.
    Tracks requests per key (IP + endpoint) with sliding window.
    """

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        """Check if a request is allowed under the rate limit."""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            # Prune old entries
            self._hits[key] = [t for t in self._hits[key] if t > cutoff]
            if len(self._hits[key]) >= self.max_requests:
                return False
            self._hits[key].append(now)
            return True

    def remaining(self, key: str) -> int:
        """Get remaining requests in the current window."""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            self._hits[key] = [t for t in self._hits[key] if t > cutoff]
            return max(0, self.max_requests - len(self._hits[key]))


# Global rate limiters
_auth_limiter = RateLimiter(max_requests=5, window_seconds=60)  # 5 login attempts per minute
_api_limiter = RateLimiter(max_requests=100, window_seconds=60)  # 100 API calls per minute


def check_auth_rate_limit(request: Request) -> bool:
    """Check if auth request is within rate limit."""
    ip = request.client.host if request.client else 'unknown'
    return _auth_limiter.is_allowed(f"auth:{ip}")


def check_api_rate_limit(request: Request) -> bool:
    """Check if API request is within rate limit."""
    ip = request.client.host if request.client else 'unknown'
    return _api_limiter.is_allowed(f"api:{ip}")


# ═══════════════════════════════════════════════════════════════════
# SECURITY HEADERS MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # CSP: allow self, inline styles (Bootstrap), CDN scripts
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        # HSTS only if request came over HTTPS
        if request.url.scheme == 'https':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response


# ═══════════════════════════════════════════════════════════════════
# REQUEST SIZE LIMITING MIDDLEWARE
# ═══════════════════════════════════════════════════════════════════

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests larger than max_body_size bytes."""

    def __init__(self, app, max_body_size: int = 10 * 1024 * 1024):  # 10 MB default
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > self.max_body_size:
            return JSONResponse(
                {'error': f'Request body too large. Maximum: {self.max_body_size} bytes'},
                status_code=413
            )
        return await call_next(request)


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


# ═══════════════════════════════════════════════════════════════════
# PER-USER / PER-KEY API RATE LIMITING
# ═══════════════════════════════════════════════════════════════════

_user_limiter = RateLimiter(max_requests=100, window_seconds=60)  # 100 API calls/min per user
_key_limiter = RateLimiter(max_requests=200, window_seconds=60)   # 200 API calls/min per key


def check_user_rate_limit(user_id: str) -> bool:
    """Check if a user is within their API rate limit."""
    return _user_limiter.is_allowed(f"user:{user_id}")


def check_key_rate_limit(key_name: str) -> bool:
    """Check if an API key is within its rate limit."""
    return _key_limiter.is_allowed(f"key:{key_name}")


def get_user_rate_remaining(user_id: str) -> int:
    """Get remaining API calls for a user in the current window."""
    return _user_limiter.remaining(f"user:{user_id}")
