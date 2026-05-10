"""
SAJHA MCP Server v3 — Password Hashing (bcrypt)
"""

import hashlib
import secrets
import bcrypt as _bcrypt


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
    except Exception:
        return False
