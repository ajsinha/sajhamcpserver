"""
SAJHA MCP Server v3 — Unified Authentication Manager
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Supports: JWT Bearer, API Key (sja_), Session Cookie, OAuth.
All methods produce the same AuthContext for downstream code.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.db.dao import UserDAO, ApiKeyDAO, PermissionDAO, AuditDAO
from sajha.db.models import User
from sajha.auth.password import verify_password
from sajha.auth.jwt_handler import create_access_token, decode_access_token

logger = logging.getLogger(__name__)

# FastAPI security schemes (optional — won't fail if absent)
_bearer_scheme = HTTPBearer(auto_error=False)
_apikey_header = APIKeyHeader(name='X-API-Key', auto_error=False)


@dataclass
class AuthContext:
    """
    Unified auth result. Every auth method produces one of these.
    Downstream code never needs to know which method was used.
    """
    authenticated: bool = False
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    roles: list[str] = field(default_factory=list)
    auth_type: Optional[str] = None     # 'jwt', 'apikey', 'session', 'oauth'
    is_admin: bool = False
    api_key_name: Optional[str] = None  # For apikey auth

    # Internal references (not serialized)
    _user: Optional[User] = field(default=None, repr=False)
    _db: Optional[Session] = field(default=None, repr=False)

    def has_tool_access(self, tool_name: str) -> bool:
        """Check if this auth context grants access to execute a tool."""
        if not self.authenticated:
            return False
        if self.is_admin:
            return True
        if self._user and self._db:
            perm_dao = PermissionDAO(self._db)
            return perm_dao.check_access(self._user.roles, 'tool', tool_name, 'execute')
        return False

    def has_permission(self, resource_type: str, resource_name: str, action: str) -> bool:
        """General permission check."""
        if not self.authenticated:
            return False
        if self.is_admin:
            return True
        if self._user and self._db:
            perm_dao = PermissionDAO(self._db)
            return perm_dao.check_access(self._user.roles, resource_type, resource_name, action)
        return False

    def to_legacy_session(self) -> dict:
        """
        Convert to a dict compatible with the legacy MCPHandler session format.
        Ensures backward compatibility with existing code.
        """
        return {
            'user_id': self.user_id or 'anonymous',
            'user_name': self.user_name or 'Anonymous',
            'roles': self.roles,
            'tools': ['*'] if self.is_admin else [],
        }


class AuthManager:
    """
    Centralized authentication — used by FastAPI dependencies and routes.
    """

    # ── Local Auth ───────────────────────────────────────────────

    @staticmethod
    def authenticate_local(db: Session, login_id: str, password: str) -> Optional[str]:
        """
        Authenticate with username + password.
        Returns a JWT token on success, None on failure.
        """
        user_dao = UserDAO(db)
        user = user_dao.get_by_user_id(login_id)

        if not user or not user.enabled:
            logger.warning(f'Login failed: user not found or disabled — {login_id}')
            return None

        if not verify_password(password, user.password_hash):
            logger.warning(f'Login failed: bad password — {login_id}')
            return None

        # Success
        user_dao.update_last_login(login_id)
        token = create_access_token(user.user_id, user.role_names)

        # Audit
        AuditDAO(db).log(
            action='user.login',
            actor_id=user.user_id,
            resource_type='user',
            resource_id=user.user_id,
        )

        logger.info(f'User authenticated: {login_id}')
        return token

    # ── JWT Auth ─────────────────────────────────────────────────

    @staticmethod
    def authenticate_jwt(db: Session, token: str) -> Optional[AuthContext]:
        """Validate a JWT token and return an AuthContext."""
        payload = decode_access_token(token)
        if not payload:
            return None

        user_id = payload.get('sub')
        if not user_id:
            return None

        user_dao = UserDAO(db)
        user = user_dao.get_by_user_id(user_id)
        if not user or not user.enabled:
            return None

        return AuthContext(
            authenticated=True,
            user_id=user.user_id,
            user_name=user.user_name,
            roles=user.role_names,
            auth_type='jwt',
            is_admin=user.is_admin,
            _user=user,
            _db=db,
        )

    # ── API Key Auth ─────────────────────────────────────────────

    @staticmethod
    def authenticate_apikey(db: Session, raw_key: str) -> Optional[AuthContext]:
        """Validate an API key and return an AuthContext."""
        apikey_dao = ApiKeyDAO(db)
        valid, api_key, msg = apikey_dao.validate_key(raw_key)

        if not valid or not api_key:
            logger.debug(f'API key auth failed: {msg}')
            return None

        apikey_dao.record_usage(api_key)

        return AuthContext(
            authenticated=True,
            user_id=f'apikey:{api_key.name}',
            user_name=api_key.name,
            roles=['api_consumer'],
            auth_type='apikey',
            is_admin=False,
            api_key_name=api_key.name,
            _db=db,
        )

    # ── Request Auth (unified) ───────────────────────────────────

    @staticmethod
    def authenticate_request(
        request: Request,
        db: Session,
    ) -> AuthContext:
        """
        Try all auth methods in order:
        1. Authorization: Bearer <jwt>
        2. X-API-Key: sja_xxx
        3. Authorization: sja_xxx (API key in auth header)
        4. Session cookie (for web UI)

        Returns an AuthContext (may be unauthenticated).
        """
        # 1. Bearer token (JWT)
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            ctx = AuthManager.authenticate_jwt(db, token)
            if ctx:
                return ctx

        # 2. X-API-Key header
        api_key = request.headers.get('X-API-Key', '')
        if api_key:
            ctx = AuthManager.authenticate_apikey(db, api_key)
            if ctx:
                return ctx

        # 3. API key directly in Authorization header
        if auth_header and auth_header.startswith('sja_'):
            ctx = AuthManager.authenticate_apikey(db, auth_header)
            if ctx:
                return ctx

        # 4. Session cookie (JWT stored in cookie for web UI)
        session_token = request.cookies.get('sajha_token', '')
        if session_token:
            ctx = AuthManager.authenticate_jwt(db, session_token)
            if ctx:
                ctx.auth_type = 'session'
                return ctx

        return AuthContext(authenticated=False)


# ── FastAPI Dependencies ─────────────────────────────────────────

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthContext:
    """
    FastAPI dependency: returns AuthContext for the current request.
    Does NOT raise — returns unauthenticated context if no creds.
    Use `require_auth` or `require_admin` for protected routes.
    """
    return AuthManager.authenticate_request(request, db)


def require_auth(
    auth: AuthContext = Depends(get_current_user),
) -> AuthContext:
    """FastAPI dependency: require any valid authentication."""
    if not auth.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Authentication required',
            headers={'WWW-Authenticate': 'Bearer realm="sajha", scope="tools:read tools:execute"'},
        )
    return auth


def require_admin(
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """FastAPI dependency: require admin role."""
    if not auth.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Admin privileges required',
        )
    return auth
