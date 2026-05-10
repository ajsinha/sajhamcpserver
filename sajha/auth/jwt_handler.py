"""
SAJHA MCP Server v3 — JWT Authentication
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError

from sajha.core.config import get_settings

logger = logging.getLogger(__name__)


def create_access_token(
    user_id: str,
    roles: list[str],
    expires_minutes: Optional[int] = None,
    extra_claims: Optional[dict] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        user_id: The user's login identifier
        roles: List of role names
        expires_minutes: Override expiry (defaults to settings)
        extra_claims: Additional claims to embed
    """
    settings = get_settings()
    exp_minutes = expires_minutes or settings.jwt_expiry_minutes
    now = datetime.now(timezone.utc)

    payload = {
        'sub': user_id,
        'roles': roles,
        'iat': now,
        'exp': now + timedelta(minutes=exp_minutes),
        'iss': 'sajha-mcp-server',
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.

    Returns:
        Decoded payload dict, or None if invalid/expired.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={'verify_exp': True},
        )
        return payload
    except JWTError as e:
        logger.debug(f'JWT decode failed: {e}')
        return None


def create_session_token(user_id: str, roles: list[str]) -> str:
    """Convenience: create a standard session JWT."""
    return create_access_token(user_id, roles)
