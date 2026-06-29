"""
SAJHA MCP Server v5.3.0 — Authentication Manager
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Database-backed authentication with bcrypt password hashing,
session token hashing, account lockout, and rate limiting.
"""
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from threading import RLock
from typing import Optional, Dict, List, Tuple

from sqlalchemy.orm import Session

from sajha.security import (
    hash_password, verify_password, generate_session_token,
    hash_token, check_account_locked, get_lockout_time,
    MAX_FAILED_ATTEMPTS,
)

logger = logging.getLogger(__name__)


class AuthManager:
    """
    Database-backed authentication manager.

    All credentials stored hashed:
      - Passwords: bcrypt (12 rounds)
      - Session tokens: SHA-256
      - API keys: SHA-256 (handled by ApiKeyManager)

    Features:
      - Account lockout after 5 failed attempts (15 min)
      - Session expiry (configurable, default 1 hour)
      - DB-persisted sessions (survive restarts)
    """

    def __init__(self, settings=None):
        self.settings = settings or {}
        self._lock = RLock()
        self.session_ttl = int(self.settings.get('session_ttl', 3600))
        self.logger = logging.getLogger(__name__)

    def _get_db(self) -> Session:
        """Get a DB session for imperative use."""
        from sajha.db.engine import get_db_session
        return get_db_session()

    # ── User Authentication ──────────────────────────────────────

    def authenticate(self, user_id: str, password: str, ip_address: str = None) -> Optional[str]:
        """
        Authenticate user with user_id and password.
        Returns raw session token on success, None on failure.
        """
        db = self._get_db()
        try:
            from sajha.db.models import User
            user = db.query(User).filter(User.user_id == user_id).first()

            if not user:
                self.logger.warning(f"Login attempt for unknown user: {user_id}")
                return None

            if not user.enabled:
                self.logger.warning(f"Login attempt for disabled user: {user_id}")
                return None

            # Check account lockout
            locked_until = user.locked_until.timestamp() if user.locked_until else None
            if check_account_locked(user.failed_attempts or 0, locked_until):
                self.logger.warning(f"Account locked: {user_id}")
                return None

            # Verify password (bcrypt)
            if not verify_password(password, user.password_hash):
                user.failed_attempts = (user.failed_attempts or 0) + 1
                if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
                    user.locked_until = datetime.fromtimestamp(get_lockout_time(), tz=timezone.utc)
                    self.logger.warning(f"Account locked after {MAX_FAILED_ATTEMPTS} failures: {user_id}")
                db.commit()
                self.logger.warning(f"Invalid password for user: {user_id}")
                return None

            # Success — reset failed attempts, update last_login
            user.failed_attempts = 0
            user.locked_until = None
            user.last_login = datetime.now(timezone.utc)
            db.commit()

            # Create DB-persisted session
            raw_token, token_hash = generate_session_token()
            from sajha.db.models import UserSession
            session = UserSession(
                id=str(uuid.uuid4()),
                token_hash=token_hash,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.session_ttl),
                ip_address=ip_address,
            )
            db.add(session)
            db.commit()

            self.logger.info(f"User authenticated: {user_id}")
            return raw_token

        except Exception as e:
            self.logger.error(f"Authentication error: {e}", exc_info=True)
            db.rollback()
            return None
        finally:
            db.close()

    def validate_session(self, token: str) -> Optional[Dict]:
        """Validate a session token. Returns user data dict or None."""
        if not token:
            return None
        token_h = hash_token(token)
        db = self._get_db()
        try:
            from sajha.db.models import UserSession, User
            session = db.query(UserSession).filter(UserSession.token_hash == token_h).first()
            if not session:
                return None
            if session.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
                db.delete(session)
                db.commit()
                return None
            # Update last activity
            session.last_activity = datetime.now(timezone.utc)
            db.commit()

            user = db.query(User).filter(User.id == session.user_id).first()
            if not user or not user.enabled:
                return None
            return {
                'user_id': user.user_id,
                'user_name': user.user_name,
                'roles': user.role_names,
                'is_admin': user.is_admin,
                'email': user.email,
            }
        except Exception as e:
            self.logger.error(f"Session validation error: {e}", exc_info=True)
            return None
        finally:
            db.close()

    def logout(self, token: str) -> bool:
        """Invalidate a session token."""
        if not token:
            return False
        token_h = hash_token(token)
        db = self._get_db()
        try:
            from sajha.db.models import UserSession
            session = db.query(UserSession).filter(UserSession.token_hash == token_h).first()
            if session:
                db.delete(session)
                db.commit()
                return True
            return False
        except Exception as e:
            self.logger.error(f"Logout error: {e}", exc_info=True)
            return False
        finally:
            db.close()

    # ── User CRUD ────────────────────────────────────────────────

    def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user by user_id (never returns password hash)."""
        db = self._get_db()
        try:
            from sajha.db.models import User
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                return None
            return {
                'id': user.id,
                'user_id': user.user_id,
                'user_name': user.user_name,
                'email': user.email,
                'enabled': user.enabled,
                'roles': user.role_names,
                'is_admin': user.is_admin,
                'created_at': str(user.created_at),
                'last_login': str(user.last_login) if user.last_login else None,
            }
        except Exception as e:
            self.logger.error(f"Get user error: {e}", exc_info=True)
            return None
        finally:
            db.close()

    def get_all_users(self) -> List[Dict]:
        """Get all users (NEVER returns password hashes)."""
        db = self._get_db()
        try:
            from sajha.db.models import User
            users = db.query(User).all()
            return [{
                'id': u.id,
                'user_id': u.user_id,
                'user_name': u.user_name,
                'email': u.email,
                'enabled': u.enabled,
                'roles': u.role_names,
                'is_admin': u.is_admin,
                'created_at': str(u.created_at),
                'last_login': str(u.last_login) if u.last_login else None,
            } for u in users]
        except Exception as e:
            self.logger.error(f"Get all users error: {e}", exc_info=True)
            return []
        finally:
            db.close()

    def create_user(self, user_data: Dict) -> bool:
        """Create a new user with bcrypt-hashed password."""
        db = self._get_db()
        try:
            from sajha.db.models import User, Role
            existing = db.query(User).filter(User.user_id == user_data['user_id']).first()
            if existing:
                return False
            user = User(
                id=str(uuid.uuid4()),
                user_id=user_data['user_id'],
                user_name=user_data.get('user_name', user_data['user_id']),
                email=user_data.get('email'),
                password_hash=hash_password(user_data['password']),
                enabled=user_data.get('enabled', True),
            )
            # Assign roles
            role_names = user_data.get('roles', ['user'])
            for rn in role_names:
                role = db.query(Role).filter(Role.name == rn).first()
                if role:
                    user.roles.append(role)
            db.add(user)
            db.commit()
            self.logger.info(f"User created: {user_data['user_id']}")
            return True
        except Exception as e:
            self.logger.error(f"Create user error: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()

    def update_user(self, user_id: str, user_data: Dict) -> bool:
        """Update user. If password provided, re-hash with bcrypt."""
        db = self._get_db()
        try:
            from sajha.db.models import User
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                return False
            if user_data.get('user_name'):
                user.user_name = user_data['user_name']
            if user_data.get('email'):
                user.email = user_data['email']
            if user_data.get('password'):
                user.password_hash = hash_password(user_data['password'])
            if 'enabled' in user_data:
                user.enabled = user_data['enabled']
            db.commit()
            self.logger.info(f"User updated: {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Update user error: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()

    def delete_user(self, user_id: str) -> bool:
        """Delete a user and all associated sessions/keys."""
        db = self._get_db()
        try:
            from sajha.db.models import User
            user = db.query(User).filter(User.user_id == user_id).first()
            if not user:
                return False
            db.delete(user)
            db.commit()
            self.logger.info(f"User deleted: {user_id}")
            return True
        except Exception as e:
            self.logger.error(f"Delete user error: {e}", exc_info=True)
            db.rollback()
            return False
        finally:
            db.close()

    # ── Request Authentication ───────────────────────────────────

    @staticmethod
    def authenticate_request(request, db=None):
        """
        Authenticate an incoming request. Checks (in order):
        1. Authorization: Bearer <token>
        2. X-API-Key header
        3. ?api_key= query param
        4. sajha_token cookie
        """
        from sajha.auth import AuthContext

        # 1. Bearer token
        auth_header = request.headers.get('authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            mgr = _get_auth_manager()
            user_data = mgr.validate_session(token)
            if user_data:
                return AuthContext(
                    authenticated=True,
                    method='bearer',
                    user_id=user_data['user_id'],
                    user_name=user_data['user_name'],
                    roles=user_data['roles'],
                )

        # 2. API Key
        api_key = request.headers.get('x-api-key', '') or request.query_params.get('api_key', '')
        if api_key:
            from sajha.core.apikey_manager import get_api_key_manager
            km = get_api_key_manager()
            valid, key_data, msg = km.validate_key(api_key)
            if valid and key_data:
                return AuthContext(
                    authenticated=True,
                    method='api_key',
                    user_id=key_data.get('owner_user_id', 'api_user'),
                    user_name=key_data.get('name', 'API Key User'),
                    roles=key_data.get('roles', ['user']),
                    api_key_name=key_data.get('name'),
                )

        # 3. Session cookie
        token = request.cookies.get('sajha_token', '')
        if token:
            mgr = _get_auth_manager()
            user_data = mgr.validate_session(token)
            if user_data:
                return AuthContext(
                    authenticated=True,
                    method='cookie',
                    user_id=user_data['user_id'],
                    user_name=user_data['user_name'],
                    roles=user_data['roles'],
                )

        return AuthContext(authenticated=False)

    # ── Cleanup ──────────────────────────────────────────────────

    def cleanup_expired_sessions(self):
        """Remove expired sessions from DB."""
        db = self._get_db()
        try:
            from sajha.db.models import UserSession
            expired = db.query(UserSession).filter(
                UserSession.expires_at < datetime.now(timezone.utc)
            ).all()
            for s in expired:
                db.delete(s)
            db.commit()
            if expired:
                self.logger.info(f"Cleaned up {len(expired)} expired sessions")
        except Exception as e:
            self.logger.error(f"Session cleanup error: {e}", exc_info=True)
        finally:
            db.close()


# Module-level singleton
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager


def init_auth_manager(settings=None) -> AuthManager:
    global _auth_manager
    _auth_manager = AuthManager(settings)
    return _auth_manager


def _get_auth_manager() -> AuthManager:
    return get_auth_manager()
