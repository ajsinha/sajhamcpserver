"""
SAJHA MCP Server v3 — Password Hashing (bcrypt)
"""

import logging

import bcrypt as _bcrypt

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    pwd_bytes = password.encode('utf-8')
    salt = _bcrypt.gensalt(rounds=12)
    return _bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    try:
        return _bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8'),
        )
    except Exception as e:
        logger.warning(f"Error handled: {e}", exc_info=True)
        return False


# ── Password policy ──────────────────────────────────────────────────

#: Passwords SAJHA has shipped or suggested (seed admin, old create-user default) plus the
#: most common guesses.  Signing in with one sets the "must change password" flag.
DEFAULT_PASSWORDS = frozenset({'admin123', 'changeme', 'admin', 'password', 'sajha', '12345678'})


def min_password_length() -> int:
    from sajha.core.config import _int
    return max(8, _int('auth.password.min_length', 8))


def password_problem(password: str, user_id: str = '') -> str | None:
    """Why a new password is unacceptable, or None."""
    if not isinstance(password, str) or not password:
        return 'a password is required'
    if len(password) < min_password_length():
        return f'must be at least {min_password_length()} characters'
    if len(password.encode('utf-8')) > 72:
        return 'must be at most 72 bytes (bcrypt limit)'
    if password.lower() in DEFAULT_PASSWORDS:
        return 'is a well-known default password'
    if user_id and password.lower() == user_id.lower():
        return 'must not equal the user ID'
    return None
