"""
SAJHA MCP Server — revocable sign-in.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Two mechanisms, both checked on every request that presents a SAJHA JWT (the console
cookie, ``Authorization: Bearer``) or a built-in OAuth access token:

* **Token version (every session of a user).** ``users.token_version`` is copied into each
  token as the claim ``tv`` (a token without ``tv`` counts as version 0). The user row is
  reloaded on every request anyway, so a token whose ``tv`` differs from the row is refused.
  :func:`end_all_sessions` bumps the version: "sign out everywhere", a password change (the
  session that changed it gets a fresh token), an administrator's password reset or
  "revoke sessions". Built-in OAuth refresh tokens remember the version they were issued
  under and stop refreshing once it changes.
* **One token (sign out).** Every SAJHA JWT carries a ``jti``. Signing out records the
  ``jti`` in the state store (``auth:revoked:<jti>``) until the token would have expired,
  so the same token presented again is refused on every worker that shares the store
  (``state.backend: redis`` or ``database``; with ``memory`` only this process knows).

Design and limits: docs/security/Security Model.md, "Revocable sign-in".
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_REVOKED = 'auth:revoked:'


def _store():
    from sajha.core.state import get_state_store
    return get_state_store()


def revoke_token(payload: Optional[Dict[str, Any]]) -> bool:
    """Refuse this one token from now until it expires. False when it carries no ``jti``."""
    if not isinstance(payload, dict):
        return False
    jti = payload.get('jti')
    if not isinstance(jti, str) or not jti:
        return False
    try:
        exp = float(payload.get('exp') or 0)
    except (TypeError, ValueError):
        exp = 0.0
    ttl = max(60.0, exp - time.time() + 60.0) if exp else 86400.0
    try:
        _store().set(_REVOKED + jti, True, ttl=ttl)
        return True
    except Exception as e:
        logger.warning(f'could not record a signed-out token in the state store: {e}')
        return False


def is_revoked(payload: Optional[Dict[str, Any]]) -> bool:
    jti = payload.get('jti') if isinstance(payload, dict) else None
    if not isinstance(jti, str) or not jti:
        return False
    try:
        return _store().get(_REVOKED + jti) is not None
    except Exception as e:      # a state store outage must not sign everyone out
        logger.warning(f'revocation check skipped (state store unavailable): {e}')
        return False


def token_version_of(user) -> int:
    try:
        return int(getattr(user, 'token_version', 0) or 0)
    except (TypeError, ValueError):
        return 0


def version_matches(payload: Optional[Dict[str, Any]], user) -> bool:
    """Does the token's ``tv`` (default 0) equal the user's current token version?"""
    try:
        tv = int((payload or {}).get('tv', 0) or 0)
    except (TypeError, ValueError):
        return False
    return tv == token_version_of(user)


def end_all_sessions(db, user, by: str, reason: str) -> int:
    """Bump the user's token version: every JWT and OAuth token issued before stops working.
    Returns the new version. Audited as ``user.sessions_revoked``."""
    user.token_version = token_version_of(user) + 1
    db.commit()
    try:
        from sajha.db.dao import AuditDAO
        AuditDAO(db).log('user.sessions_revoked', by, 'user', user.user_id, {'reason': reason})
    except Exception as e:
        logger.warning(f'audit of sessions_revoked failed: {e}')
    return user.token_version
