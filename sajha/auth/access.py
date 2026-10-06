"""
SAJHA MCP Server — tool access policy.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One answer to "may this caller see / run this tool?" for every surface that runs tools:
REST (``/api/tools/execute``, async execution), MCP (both protocol eras, Streamable HTTP,
the legacy SSE transport and WebSocket) and A2A.

Who gets what:

* **admin** role: every tool.
* **Users** (SAJHA login JWT, session cookie, OAuth token for a SAJHA user): the tool
  permissions of their roles (``permissions`` rows with resource_type ``tool`` or ``*``).
  ``execute`` (or ``*``) lets them call a tool; ``read`` alone lets them see it listed.
* **API keys**: the key's ``tool_access_mode``: ``all``, ``allowlist`` (only the listed
  fnmatch patterns), ``denylist`` (everything except them) or ``regex`` (tool names that
  fully match one of the listed regular expressions).
* **Other identities** without a SAJHA account (external OAuth users mapped to the
  ``api_consumer`` role): the permissions of a SAJHA role of that name, if an operator
  created one; otherwise none.
* **Anonymous** callers (no credentials, possible while ``mcp.auth.mode`` is ``off`` or
  ``optional``): ``mcp.anonymous.tools`` (fnmatch allowlist, default empty) plus the tool
  permissions of ``mcp.anonymous.role``; refused entirely when ``mcp.anonymous.enabled``
  is false.

The policy travels inside the MCP "session" dict (``mcp_session_for``), so the MCP handler
needs no database access to apply it.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

ANONYMOUS_USER_ID = 'anonymous'


# ── configuration ───────────────────────────────────────────────────

def anonymous_enabled() -> bool:
    from sajha.core.config import _bool
    return _bool('mcp.anonymous.enabled', True)


def anonymous_tool_patterns() -> List[str]:
    from sajha.core.config import _list
    return _list('mcp.anonymous.tools', [])


def anonymous_role() -> str:
    from sajha.core.config import _get
    return (_get('mcp.anonymous.role', '') or '').strip()


# ── pattern helpers ─────────────────────────────────────────────────

def matches(name: str, patterns: Iterable[str]) -> bool:
    """fnmatch globs (case-sensitive); ``re:<regex>`` entries are full-match regular expressions."""
    if not isinstance(name, str) or not name:
        return False
    for pattern in patterns or ():
        if not isinstance(pattern, str):
            continue
        if pattern.startswith('re:'):
            try:
                if re.fullmatch(pattern[3:], name):
                    return True
            except re.error:
                continue
        elif pattern == '*' or fnmatch.fnmatchcase(name, pattern):
            return True
    return False


def _actions(perm) -> set:
    return {a.strip() for a in (perm.actions or '').split(',') if a.strip()}


def _patterns_from_permissions(permissions) -> Tuple[List[str], List[str]]:
    """(execute patterns, visible patterns) from Permission rows."""
    execute: List[str] = []
    visible: List[str] = []
    for perm in permissions:
        if perm.resource_type not in ('*', 'tool'):
            continue
        name = perm.resource_name or '*'
        actions = _actions(perm)
        if '*' in actions or 'execute' in actions:
            execute.append(name)
            visible.append(name)
        elif 'read' in actions:
            visible.append(name)
    return execute, visible


def _role_permissions(roles) -> list:
    out = []
    for role in roles or ():
        out.extend(getattr(role, 'permissions', None) or ())
    return out


def _roles_by_name(db, names: Iterable[str]) -> list:
    names = [n for n in names if n]
    if db is None or not names:
        return []
    try:
        from sajha.db.models import Role
        return db.query(Role).filter(Role.name.in_(names)).all()
    except Exception as e:      # a policy lookup must never take a request down
        logger.warning(f'Role lookup failed ({type(e).__name__}); granting no tool access')
        return []


# ── the policy object ───────────────────────────────────────────────

class ToolPolicy:
    """Execute / visible allow-patterns and deny-patterns for one caller."""

    __slots__ = ('execute', 'visible', 'deny')

    def __init__(self, execute=(), visible=(), deny=()):
        self.execute = list(execute)
        self.visible = list(dict.fromkeys(list(visible) + list(execute)))
        self.deny = list(deny)

    # Patterns are fnmatch globs; an entry 're:<regex>' is a full-match regular expression
    # (API keys in tool access mode 'regex').

    @classmethod
    def everything(cls) -> 'ToolPolicy':
        return cls(['*'], ['*'])

    def can_execute(self, tool_name: str) -> bool:
        return matches(tool_name, self.execute) and not matches(tool_name, self.deny)

    def can_see(self, tool_name: str) -> bool:
        return matches(tool_name, self.visible) and not matches(tool_name, self.deny)

    def unrestricted(self) -> bool:
        return '*' in self.visible and '*' in self.execute and not self.deny

    def to_session(self) -> Dict[str, list]:
        return {'tools': list(self.execute), 'visible_tools': list(self.visible),
                'denied_tools': list(self.deny)}

    @classmethod
    def from_session(cls, session: Optional[Dict]) -> 'ToolPolicy':
        if not isinstance(session, dict):
            return anonymous_policy()
        return cls(session.get('tools') or [], session.get('visible_tools') or [],
                   session.get('denied_tools') or [])


def apikey_policy(mode: Optional[str], access_list) -> ToolPolicy:
    if isinstance(access_list, str):
        try:
            access_list = json.loads(access_list or '[]')
        except ValueError:
            access_list = []
    patterns = [str(p) for p in (access_list or []) if str(p).strip()]
    mode = (mode or 'all').lower()
    if mode == 'all':
        return ToolPolicy.everything()
    if mode == 'allowlist':
        return ToolPolicy(patterns, patterns)
    if mode == 'denylist':
        return ToolPolicy(['*'], ['*'], patterns)
    if mode == 'regex':
        regexes = [p if p.startswith('re:') else 're:' + p for p in patterns]
        return ToolPolicy(regexes, regexes)
    return ToolPolicy()     # unknown mode: nothing


def anonymous_policy(db=None) -> ToolPolicy:
    if not anonymous_enabled():
        return ToolPolicy()
    execute = list(anonymous_tool_patterns())
    visible = list(execute)
    role = anonymous_role()
    if role:
        if db is None:
            from sajha.db.engine import get_db_session
            try:
                db = get_db_session()
            except Exception:
                db = None
            close = db is not None
        else:
            close = False
        try:
            e, v = _patterns_from_permissions(_role_permissions(_roles_by_name(db, [role])))
        finally:
            if close:
                db.close()
        execute += e
        visible += v
    return ToolPolicy(execute, visible)


def policy_for(auth) -> ToolPolicy:
    """The ToolPolicy of an AuthContext (unauthenticated -> the anonymous policy)."""
    if auth is None or not getattr(auth, 'authenticated', False):
        return anonymous_policy(getattr(auth, '_db', None))
    if auth.is_admin:
        return ToolPolicy.everything()
    if auth.auth_type == 'apikey':
        return apikey_policy(getattr(auth, 'api_key_mode', None), getattr(auth, 'api_key_tools', None))
    user = getattr(auth, '_user', None)
    roles = user.roles if user is not None else _roles_by_name(getattr(auth, '_db', None), auth.roles)
    execute, visible = _patterns_from_permissions(_role_permissions(roles))
    return ToolPolicy(execute, visible)


def mcp_session_for(auth) -> Dict:
    """
    The session dict MCPHandler receives: identity plus the caller's ToolPolicy.
    Anonymous callers get one too (user_id ``anonymous``), so the handler always filters.
    """
    policy = policy_for(auth)
    if auth is not None and getattr(auth, 'authenticated', False):
        session = {
            'user_id': auth.user_id or ANONYMOUS_USER_ID,
            'user_name': auth.user_name or auth.user_id,
            'roles': list(auth.roles or []),
            'is_admin': bool(auth.is_admin),
            'auth_type': auth.auth_type,
            'api_key_name': getattr(auth, 'api_key_name', None),
            'authenticated': True,
        }
    else:
        session = {'user_id': ANONYMOUS_USER_ID, 'user_name': 'Anonymous', 'roles': [],
                   'is_admin': False, 'auth_type': None, 'authenticated': False}
    session.update(policy.to_session())
    return session


class SessionToolAccess:
    """
    The ``auth_manager`` MCPHandler is constructed with: answers from the policy carried
    in the session dict (see :func:`mcp_session_for`).  A missing session is anonymous.
    """

    def get_user_accessible_tools(self, session: Optional[Dict]) -> List[str]:
        policy = ToolPolicy.from_session(session)
        return ['*'] if policy.unrestricted() else list(policy.visible)

    def can_see(self, session: Optional[Dict], tool_name: str) -> bool:
        return ToolPolicy.from_session(session).can_see(tool_name)

    def has_tool_access(self, session: Optional[Dict], tool_name: str) -> bool:
        return ToolPolicy.from_session(session).can_execute(tool_name)

    def is_unrestricted(self, session: Optional[Dict]) -> bool:
        return ToolPolicy.from_session(session).unrestricted()

    def is_admin(self, session: Optional[Dict]) -> bool:
        return bool(isinstance(session, dict) and session.get('is_admin'))
