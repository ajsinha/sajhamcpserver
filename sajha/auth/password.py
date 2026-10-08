# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA MCP Server v3 — Password Hashing (bcrypt)
"""

import logging

import bcrypt as _bcrypt

logger = logging.getLogger(__name__)


def credential_storage() -> str:
    """``auth.credential_storage``: ``plain`` (the owner's intranet setting: passwords and API
    keys stored as given) or ``hashed`` (bcrypt passwords, SHA-256 key hashes only)."""
    from sajha.core.config import _get
    v = str(_get('auth.credential_storage', 'plain') or 'plain').strip().lower()
    return v if v in ('plain', 'hashed') else 'plain'


def is_bcrypt(value: str) -> bool:
    return isinstance(value, str) and value.startswith(('$2a$', '$2b$', '$2y$')) and len(value) == 60


def bcrypt_hash(password: str) -> str:
    """Always bcrypt, whatever the storage setting (used by ``python -m sajha.auth rehash``)."""
    return _bcrypt.hashpw(password.encode('utf-8'), _bcrypt.gensalt(rounds=12)).decode('utf-8')


def hash_password(password: str) -> str:
    """The value to store for a new password: the password itself under
    ``auth.credential_storage: plain``, a bcrypt hash under ``hashed``."""
    return password if credential_storage() == 'plain' else bcrypt_hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a password against a stored value, bcrypt or plain, whatever the current setting:
    values stored before a switch keep working."""
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str) or not hashed_password:
        return False
    if is_bcrypt(hashed_password):
        try:
            return _bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
            return False
    import hmac
    return hmac.compare_digest(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


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
