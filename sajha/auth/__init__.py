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
    api_key_mode: Optional[str] = None  # apikey: tool_access_mode (all | allowlist | denylist)
    api_key_tools: Optional[str] = None  # apikey: tool_access_list (JSON array of patterns)
    api_key_id: Optional[str] = None     # apikey: the key's id (never the key)
    api_key_owned: bool = False          # apikey: signs in as its owner (user_id/roles are the owner's)
    token_payload: Optional[dict] = field(default=None, repr=False)  # jwt/session: the verified claims
    password_change_required: bool = False  # user: must change the password (banner)

    # Internal references (not serialized)
    _user: Optional[User] = field(default=None, repr=False)
    _db: Optional[Session] = field(default=None, repr=False)

    def has_tool_access(self, tool_name: str) -> bool:
        """May this caller execute the tool?  (sajha/auth/access.py: roles, API key lists.)"""
        if not self.authenticated:
            return False
        from sajha.auth.access import policy_for
        return policy_for(self).can_execute(tool_name)

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
        The session dict MCPHandler receives: identity plus this caller's tool policy
        (``tools`` = execute patterns, ``visible_tools``, ``denied_tools``).  Works for an
        unauthenticated context too (the anonymous policy, ``mcp.anonymous.*``).
        """
        from sajha.auth.access import mcp_session_for
        return mcp_session_for(self)


def _observe_auth_failure(method: str, lockout: bool = False) -> None:
    """sajha_auth_failures_total / sajha_auth_lockouts_total (sajha/observability); never raises."""
    try:
        from sajha.observability.metrics import record_auth_failure, record_lockout
        record_auth_failure(method)
        if lockout:
            record_lockout()
    except Exception:
        pass


class AuthManager:
    """
    Centralized authentication — used by FastAPI dependencies and routes.
    """

    # ── Local Auth ───────────────────────────────────────────────

    @staticmethod
    def authenticate_local(db: Session, login_id: str, password: str) -> Optional[str]:
        """
        Authenticate with username + password.
        Returns a JWT token on success, None on failure (bad credentials or locked account).
        """
        token, _ = AuthManager.sign_in(db, login_id, password)
        return token

    @staticmethod
    def sign_in(db: Session, login_id: str, password: str) -> tuple[Optional[str], str]:
        """
        Password sign-in with account lockout.  Returns ``(jwt, outcome)``; outcome is
        ``ok``, ``invalid`` or ``locked``.  ``auth.login.max_failed_attempts`` consecutive
        failures lock the account for ``auth.login.lockout_minutes`` (users.failed_attempts /
        users.locked_until); a success resets the counter.  The JWT carries ``pwc: true``
        when the password must be changed (seed or admin-set password, or a well-known one).
        """
        from sajha.core.config import _int
        from sajha.auth.password import DEFAULT_PASSWORDS
        user_dao = UserDAO(db)
        user = user_dao.get_by_user_id(login_id)

        if not user or not user.enabled:
            logger.warning(f'Login failed: user not found or disabled — {login_id!r}')
            _observe_auth_failure('password')
            return None, 'invalid'

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        locked_until = user.locked_until.replace(tzinfo=None) if user.locked_until else None
        if locked_until and locked_until > now:
            logger.warning(f'Login refused: account locked until {locked_until.isoformat()}Z — {login_id!r}')
            _observe_auth_failure('password')
            return None, 'locked'

        if not verify_password(password, user.password_hash):
            max_failures = max(1, _int('auth.login.max_failed_attempts', 5))
            user.failed_attempts = (0 if locked_until else (user.failed_attempts or 0)) + 1
            outcome = 'invalid'
            if user.failed_attempts >= max_failures:
                user.locked_until = now + timedelta(minutes=max(1, _int('auth.login.lockout_minutes', 15)))
                user.failed_attempts = 0
                outcome = 'locked'
                logger.warning(f'Account locked after {max_failures} failed sign-ins — {login_id!r}')
            else:
                user.locked_until = None
            db.commit()
            AuditDAO(db).log(action='user.login_failed', user_id=user.user_id,
                             resource_type='user', resource_id=user.user_id)
            logger.warning(f'Login failed: bad password — {login_id!r}')
            _observe_auth_failure('password', lockout=outcome == 'locked')
            return None, outcome

        # Success
        user.failed_attempts = 0
        user.locked_until = None
        if (password or '').lower() in DEFAULT_PASSWORDS:
            user.must_change_password = True
        db.commit()
        user_dao.update_last_login(login_id)
        claims = {'pwc': True} if getattr(user, 'must_change_password', False) else None
        from sajha.auth.revocation import token_version_of
        token = create_access_token(user.user_id, user.role_names, extra_claims=claims,
                                    token_version=token_version_of(user))

        # Audit
        AuditDAO(db).log(
            action='user.login',
            user_id=user.user_id,
            resource_type='user',
            resource_id=user.user_id,
        )

        logger.info(f'User authenticated: {login_id}')
        return token, 'ok'

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

        # Revocable sign-in (sajha/auth/revocation.py): every session of the user ended since
        # this token was issued (token version), or this token signed out (jti)
        from sajha.auth import revocation
        if not revocation.version_matches(payload, user) or revocation.is_revoked(payload):
            logger.debug(f'JWT refused: signed out or sessions revoked — {user_id!r}')
            return None

        return AuthContext(
            authenticated=True,
            user_id=user.user_id,
            user_name=user.user_name,
            roles=user.role_names,
            auth_type='jwt',
            is_admin=user.is_admin,
            password_change_required=bool(getattr(user, 'must_change_password', False)),
            token_payload=payload,
            _user=user,
            _db=db,
        )

    # ── API Key Auth ─────────────────────────────────────────────

    @staticmethod
    def authenticate_apikey(db: Session, raw_key: str) -> Optional[AuthContext]:
        """
        Validate an API key and return an AuthContext.

        The database decides for every key it knows (unknown, disabled, revoked or expired:
        refused). A key with an owner signs in as that user, with the user's roles (refused
        when the owner is disabled); its tool access mode and list stay an extra ceiling. A
        key without an owner keeps the older service identity ``apikey:<name>`` with the
        role ``api_consumer``. A key the database does not know, or every key while the
        database does not answer, is looked up in the persistent key file
        (sajha/auth/persistent_keys.py).
        """
        apikey_dao = ApiKeyDAO(db)
        db_ok = True
        try:
            valid, api_key, msg = apikey_dao.validate_key(raw_key)
        except Exception as e:
            logger.warning(f'API key lookup in the database failed ({type(e).__name__}); trying the persistent key file')
            db_ok, valid, api_key, msg = False, False, None, 'database unavailable'
            try:
                db.rollback()
            except Exception:
                pass

        if api_key is not None:
            if not valid:
                logger.debug(f'API key auth failed: {msg}')
                return None
            owner = api_key.owner if api_key.owner_id else None
            if api_key.owner_id and (owner is None or not owner.enabled):
                logger.debug('API key auth failed: its owner is missing or disabled')
                return None
            try:
                apikey_dao.record_usage(api_key)
            except Exception as e:
                logger.debug(f'API key usage not recorded: {e}')
                db.rollback()
            if owner is not None:
                return AuthContext(
                    authenticated=True, user_id=owner.user_id, user_name=owner.user_name,
                    roles=owner.role_names, auth_type='apikey', is_admin=owner.is_admin,
                    api_key_name=api_key.name, api_key_mode=api_key.tool_access_mode,
                    api_key_tools=api_key.tool_access_list, api_key_id=api_key.id, api_key_owned=True,
                    _user=owner, _db=db,
                )
            return AuthContext(
                authenticated=True,
                user_id=f'apikey:{api_key.name}',
                user_name=api_key.name,
                roles=['api_consumer'],
                auth_type='apikey',
                is_admin=False,
                api_key_name=api_key.name,
                api_key_mode=api_key.tool_access_mode,
                api_key_tools=api_key.tool_access_list,
                api_key_id=api_key.id,
                _db=db,
            )
        return AuthManager._authenticate_persistent(db, raw_key, db_ok)

    @staticmethod
    def _authenticate_persistent(db: Session, raw_key: str, db_ok: bool) -> Optional[AuthContext]:
        """A key from the persistent key file (the database does not know it, or is down)."""
        import json as _json
        from sajha.auth.persistent_keys import get_persistent_keys, record_usable
        try:
            rec = get_persistent_keys().lookup(ApiKeyDAO.hash_key(None, raw_key))
        except Exception as e:
            logger.warning(f'persistent API key lookup failed: {e}')
            return None
        if rec is None or not record_usable(rec):
            return None
        tools = rec.get('tool_access_list')
        tools = _json.dumps(tools) if isinstance(tools, list) else None
        name = str(rec.get('name') or rec.get('prefix') or 'persistent key')
        owner_id = rec.get('owner')
        if owner_id:
            user = None
            if db_ok:
                try:
                    user = UserDAO(db).get_by_user_id(owner_id)
                except Exception:
                    db_ok = False
                    try:
                        db.rollback()
                    except Exception:
                        pass
            if db_ok and (user is None or not user.enabled):
                logger.info(f'persistent API key {rec.get("prefix")} refused: its owner {owner_id!r} '
                            'is not an enabled user in the database')
                return None
            if user is not None:
                return AuthContext(authenticated=True, user_id=user.user_id, user_name=user.user_name,
                                   roles=user.role_names, auth_type='apikey', is_admin=user.is_admin,
                                   api_key_name=name, api_key_mode=rec.get('tool_access_mode') or 'all',
                                   api_key_tools=tools, api_key_id=rec.get('id'), api_key_owned=True,
                                   _user=user, _db=db)
            roles = [str(r) for r in (rec.get('roles') or [])]
            return AuthContext(authenticated=True, user_id=str(owner_id),
                               user_name=str(rec.get('owner_name') or owner_id), roles=roles,
                               auth_type='apikey', is_admin='admin' in roles, api_key_name=name,
                               api_key_mode=rec.get('tool_access_mode') or 'all', api_key_tools=tools,
                               api_key_id=rec.get('id'), api_key_owned=True, _db=db if db_ok else None)
        return AuthContext(authenticated=True, user_id=f'apikey:{name}', user_name=name, roles=['api_consumer'],
                           auth_type='apikey', is_admin=False, api_key_name=name,
                           api_key_mode=rec.get('tool_access_mode') or 'all', api_key_tools=tools,
                           api_key_id=rec.get('id'), _db=db if db_ok else None)

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
        failed = []     # credentials presented that did not authenticate (sajha_auth_failures_total)

        # 1. Bearer token (JWT)
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            ctx = AuthManager.authenticate_jwt(db, token)
            if ctx:
                return ctx
            failed.append('bearer')

        # 2. X-API-Key header
        api_key = request.headers.get('X-API-Key', '')
        if api_key:
            ctx = AuthManager.authenticate_apikey(db, api_key)
            if ctx:
                return ctx
            failed.append('apikey')

        # 3. API key directly in Authorization header
        if auth_header and auth_header.startswith('sja_'):
            ctx = AuthManager.authenticate_apikey(db, auth_header)
            if ctx:
                return ctx
            failed.append('apikey')

        # 4. Session cookie (JWT stored in cookie for web UI)
        session_token = request.cookies.get('sajha_token', '')
        if session_token:
            ctx = AuthManager.authenticate_jwt(db, session_token)
            if ctx:
                ctx.auth_type = 'session'
                return ctx
            failed.append('session')

        for method in failed:
            _observe_auth_failure(method)
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
    auth = AuthManager.authenticate_request(request, db)
    try:
        request.state.auth = auth      # render() reads it for the navigation (can_use_studio)
    except Exception:
        pass
    return auth


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


#: The permission that opens MCP Studio to a non-admin: a row with resource_type ``studio``.
#: Its resource_name names the creator it opens (``studio:rest`` is resource_type ``studio``,
#: resource_name ``rest``); ``*`` (``studio:*``, the seeded ``developer`` role) opens every creator,
#: which is what the single ``studio`` permission always meant. Actions ``*`` or ``use``.
STUDIO_PERMISSION = 'studio'

#: Every Studio creator a permission can name (Roadmap X2; docs/security/Security Model.md §4).
STUDIO_CREATORS = ('python', 'rest', 'api_import', 'dbquery', 'script', 'powerbi', 'powerbidax', 'livelink',
                   'sharepoint', 'olap', 'composite', 'describe', 'llm', 'planner')

#: Creators no permission opens: administrators only (LLM Tools §9.10, decision 6).
ADMIN_ONLY_CREATORS = ('planner',)


def _studio_grants(auth: AuthContext) -> list:
    """(resource_name pattern, actions) of the caller's roles' ``studio`` (and ``*``) permission rows,
    read once per request context."""
    cached = getattr(auth, '_studio_grants_cache', None)
    if cached is not None:
        return cached
    grants = []
    user, db = getattr(auth, '_user', None), getattr(auth, '_db', None)
    if user is not None and db is not None:
        from sajha.db.models import Permission
        role_ids = [r.id for r in (user.roles or [])]
        if role_ids:
            for perm in db.query(Permission).filter(Permission.role_id.in_(role_ids),
                                                    Permission.resource_type.in_([STUDIO_PERMISSION, '*'])).all():
                grants.append((perm.resource_name or '', {a.strip() for a in (perm.actions or '').split(',')}))
    try:
        auth._studio_grants_cache = grants
    except Exception:
        pass
    return grants


def can_use_creator(auth: Optional[AuthContext], creator: str) -> bool:
    """May this caller use one Studio creator? An admin may use all; a non-admin needs ``studio:<creator>``
    or ``studio:*`` (planner: admins only)."""
    import fnmatch
    if auth is None or not auth.authenticated:
        return False
    if auth.is_admin:
        return True
    if creator in ADMIN_ONLY_CREATORS:
        return False
    try:
        return any((name == '*' or fnmatch.fnmatch(creator, name)) and ('*' in actions or 'use' in actions)
                   for name, actions in _studio_grants(auth))
    except Exception as e:
        logger.warning(f'studio permission check failed: {e}')
        return False


def studio_creators(auth: Optional[AuthContext]) -> list:
    """The creators this caller may use (empty: no Studio at all)."""
    return [c for c in STUDIO_CREATORS if can_use_creator(auth, c)]


def can_use_studio(auth: Optional[AuthContext]) -> bool:
    """MCP Studio access: an admin, or a signed-in user whose role grants at least one creator."""
    if auth is None or not auth.authenticated:
        return False
    if auth.is_admin:
        return True
    return bool(studio_creators(auth))


def is_owner(auth: Optional[AuthContext], created_by: Optional[str]) -> bool:
    """Ownership rule for Studio-made things: an admin may change anything; anyone else only what
    records them as its creator (a tool with no recorded creator is the admins')."""
    if auth is None or not auth.authenticated:
        return False
    if auth.is_admin:
        return True
    return bool(created_by) and str(created_by) == str(auth.user_id or '')


def require_studio(
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """FastAPI dependency: MCP Studio pages that every Studio user may open (any creator permission)."""
    if not can_use_studio(auth):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='MCP Studio requires the admin role or a role with a studio permission',
        )
    return auth


def require_creator(creator: str):
    """FastAPI dependency factory: one Studio creator (``studio:<creator>`` or ``studio:*``; admins always)."""
    if creator not in STUDIO_CREATORS:
        raise ValueError(f'unknown Studio creator {creator!r}')

    def dependency(auth: AuthContext = Depends(require_auth)) -> AuthContext:
        if not can_use_creator(auth, creator):
            detail = ('the planner editor is for administrators only' if creator in ADMIN_ONLY_CREATORS else
                      f'this Studio creator needs the admin role or a role with the studio:{creator} '
                      f'(or studio:*) permission')
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
        return auth

    dependency.__name__ = f'require_creator_{creator}'
    return dependency
