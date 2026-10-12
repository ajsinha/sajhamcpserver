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
* **API keys with an owner**: the owner's access (as for a user above, everything for an
  admin), with the key's ``tool_access_mode`` and list as an extra ceiling: a tool must pass
  both (``ToolPolicy.ceiling``).
* **API keys without an owner** (older keys, until an administrator assigns one): the key's
  ``tool_access_mode``: ``all``, ``allowlist`` (only the listed fnmatch patterns),
  ``denylist`` (everything except them) or ``regex`` (tool names that fully match one of
  the listed regular expressions).
* **Other identities** without a SAJHA account (external OAuth users mapped to the
  ``api_consumer`` role): the permissions of a SAJHA role of that name, if an operator
  created one; otherwise none.
* **Anonymous** callers (no credentials, possible while ``mcp.auth.mode`` is ``off`` or
  ``optional``): ``mcp.anonymous.tools`` (fnmatch allowlist, default empty) plus the tool
  permissions of ``mcp.anonymous.role``; refused entirely when ``mcp.anonymous.enabled``
  is false.

Prompts and data resources (:func:`can_see_prompt`, :func:`can_read_resource`; data
resources are ``sajha://data/<file>`` and federated ``sajha-federation://...`` URIs):

* **Anonymous** callers: ``mcp.anonymous.prompts`` / ``mcp.anonymous.resources`` (fnmatch,
  default empty).
* **Roles**: ``permissions`` rows with resource_type ``prompt`` (resource_name: a prompt name
  pattern) or ``resource`` (resource_name: a URI pattern), any action. A role with no such
  rows grants every prompt (resource), as before; a caller passes if any of their roles does.
* **API keys**: entries ``prompt:<pattern>`` and ``resource:<uri pattern>`` in the key's
  access list (``tool_access_list``) are the prompts and resources the key may reach (a
  ceiling, like the tool list). A key without such entries: no extra limit when its tool
  access mode is ``all`` or ``denylist``; **nothing** when it is ``allowlist`` or ``regex``
  (a key limited to a few tools reaches no prompt or data file it was not granted).
* **admin** role: everything (an admin's key: still capped by the key's entries).

The rules travel in the session dict as ``prompt_rules`` / ``resource_rules``: lists of
pattern lists, every one of which a name must match (absent: no limit).

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


def anonymous_prompt_patterns() -> List[str]:
    from sajha.core.config import _list
    return _list('mcp.anonymous.prompts', [])


def anonymous_resource_patterns() -> List[str]:
    from sajha.core.config import _list
    return _list('mcp.anonymous.resources', [])


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


PROMPT_PREFIX = 'prompt:'
RESOURCE_PREFIX = 'resource:'


def _access_entries(access_list) -> List[str]:
    if isinstance(access_list, str):
        try:
            access_list = json.loads(access_list or '[]')
        except ValueError:
            access_list = []
    if not isinstance(access_list, (list, tuple)):
        return []
    return [str(p).strip() for p in access_list if str(p).strip()]


def split_access_list(access_list) -> Tuple[List[str], List[str], List[str]]:
    """(tool patterns, prompt patterns, resource patterns) of an API key's access list:
    ``prompt:<pattern>`` and ``resource:<uri pattern>`` entries are not tool patterns."""
    tools: List[str] = []
    prompts: List[str] = []
    resources: List[str] = []
    for entry in _access_entries(access_list):
        if entry.startswith(PROMPT_PREFIX):
            if entry[len(PROMPT_PREFIX):].strip():
                prompts.append(entry[len(PROMPT_PREFIX):].strip())
        elif entry.startswith(RESOURCE_PREFIX):
            if entry[len(RESOURCE_PREFIX):].strip():
                resources.append(entry[len(RESOURCE_PREFIX):].strip())
        else:
            tools.append(entry)
    return tools, prompts, resources


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
        from sajha.db.engine import is_pool_exhausted
        if is_pool_exhausted(e):
            raise               # a dry pool: 503 + Retry-After, not a caller with no tools
        logger.warning(f'Role lookup failed ({type(e).__name__}); granting no tool access')
        return []


# ── the policy object ───────────────────────────────────────────────

class ToolPolicy:
    """Execute / visible allow-patterns and deny-patterns for one caller, optionally capped by
    a ``ceiling`` policy (an owned API key's own tool access): a tool must pass both."""

    __slots__ = ('execute', 'visible', 'deny', 'ceiling')

    def __init__(self, execute=(), visible=(), deny=(), ceiling: Optional['ToolPolicy'] = None):
        self.execute = list(execute)
        self.visible = list(dict.fromkeys(list(visible) + list(execute)))
        self.deny = list(deny)
        self.ceiling = ceiling if ceiling is not None and not ceiling.unrestricted() else None

    # Patterns are fnmatch globs; an entry 're:<regex>' is a full-match regular expression
    # (API keys in tool access mode 'regex').

    @classmethod
    def everything(cls) -> 'ToolPolicy':
        return cls(['*'], ['*'])

    # A tool that answers to several names (a SAJHA Net tool's qualified name and plain alias) gets one
    # decision under all of them: a pattern naming any of its names applies (Adversarial QA Plan 3.4).

    def can_execute(self, tool_name: str, aliases: Optional[List[str]] = None) -> bool:
        names = _names_of(tool_name, aliases)
        return (any(matches(n, self.execute) for n in names) and not any(matches(n, self.deny) for n in names)
                and (self.ceiling is None or self.ceiling.can_execute(tool_name, names[1:])))

    def can_see(self, tool_name: str, aliases: Optional[List[str]] = None) -> bool:
        names = _names_of(tool_name, aliases)
        return (any(matches(n, self.visible) for n in names) and not any(matches(n, self.deny) for n in names)
                and (self.ceiling is None or self.ceiling.can_see(tool_name, names[1:])))

    def unrestricted(self) -> bool:
        return ('*' in self.visible and '*' in self.execute and not self.deny
                and (self.ceiling is None or self.ceiling.unrestricted()))

    def capped_by(self, ceiling: Optional['ToolPolicy']) -> 'ToolPolicy':
        """This policy with ``ceiling`` as an extra limit (a ceiling already set stays)."""
        if ceiling is None or ceiling.unrestricted():
            return self
        if self.ceiling is not None:
            ceiling = self.ceiling.capped_by(ceiling)
        return ToolPolicy(self.execute, self.visible, self.deny, ceiling)

    def to_session(self) -> Dict[str, list]:
        out = {'tools': list(self.execute), 'visible_tools': list(self.visible),
               'denied_tools': list(self.deny)}
        if self.ceiling is not None:
            out['tool_ceiling'] = self.ceiling.to_session()
        return out

    @classmethod
    def from_session(cls, session: Optional[Dict]) -> 'ToolPolicy':
        if not isinstance(session, dict):
            return anonymous_policy()
        ceiling = session.get('tool_ceiling')
        return cls(session.get('tools') or [], session.get('visible_tools') or [],
                   session.get('denied_tools') or [],
                   cls.from_session(ceiling) if isinstance(ceiling, dict) else None)


def _names_of(tool_name: str, aliases: Optional[List[str]] = None) -> List[str]:
    """``tool_name`` and the other names of the same tool: ``aliases`` when given, else those of the tool
    of that name in the live registry (``sajha.policy.engine.tool_aliases``)."""
    if aliases is None:
        aliases = []
        try:
            from sajha.tools.tools_registry import ToolsRegistry
            reg = ToolsRegistry._instance
            tool = reg.get_tool(tool_name) if reg is not None else None
            if tool is not None:
                from sajha.policy.engine import tool_aliases
                aliases = tool_aliases(tool)
        except Exception:
            aliases = []
    return [tool_name] + [a for a in aliases if a and a != tool_name]


def apikey_policy(mode: Optional[str], access_list) -> ToolPolicy:
    patterns = split_access_list(access_list)[0]
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


def _caller_roles(auth) -> list:
    user = getattr(auth, '_user', None)
    if user is not None:
        return user.roles
    cached = getattr(auth, '_roles_by_name_cache', None)     # one lookup per request, not one per rule
    if cached is not None:
        return cached
    roles = _roles_by_name(getattr(auth, '_db', None), auth.roles)
    try:
        auth._roles_by_name_cache = roles
    except Exception:
        pass
    return roles


def policy_for(auth) -> ToolPolicy:
    """The ToolPolicy of an AuthContext (unauthenticated -> the anonymous policy)."""
    if auth is None or not getattr(auth, 'authenticated', False):
        return anonymous_policy(getattr(auth, '_db', None))
    is_key = auth.auth_type == 'apikey'
    key_policy = (apikey_policy(getattr(auth, 'api_key_mode', None), getattr(auth, 'api_key_tools', None))
                  if is_key else None)
    if is_key and not getattr(auth, 'api_key_owned', False):
        return key_policy           # an unowned key: its own lists only (the older behaviour)
    if auth.is_admin:
        return ToolPolicy.everything().capped_by(key_policy)
    execute, visible = _patterns_from_permissions(_role_permissions(_caller_roles(auth)))
    return ToolPolicy(execute, visible).capped_by(key_policy)


# ── prompts and data resources ──────────────────────────────────────

def apikey_catalog_rules(mode: Optional[str], access_list) -> Tuple[Optional[List[str]], Optional[List[str]]]:
    """(prompt patterns, resource patterns) an API key limits its caller to; None: no limit.
    Explicit ``prompt:`` / ``resource:`` entries win; without them a key whose tool access
    is ``allowlist`` or ``regex`` (or an unknown mode) reaches none, an ``all`` or
    ``denylist`` key is not limited."""
    _, prompts, resources = split_access_list(access_list)
    closed = (mode or 'all').lower() not in ('all', 'denylist')
    default = [] if closed else None
    return (prompts or default), (resources or default)


def _role_catalog_patterns(roles, kind: str) -> Optional[List[str]]:
    """The prompt (``kind='prompt'``) or resource patterns a caller's roles grant; None when
    they grant everything (some role has no rows of that kind, or a ``*`` pattern)."""
    granted: List[str] = []
    for role in roles or ():
        rows = [p for p in (getattr(role, 'permissions', None) or ()) if p.resource_type == kind]
        if not rows:
            return None
        granted.extend((p.resource_name or '*') for p in rows)
    if not granted or '*' in granted:
        return None
    return granted


def catalog_rules_for(auth) -> Dict[str, list]:
    """``{'prompt_rules': [...], 'resource_rules': [...]}`` for a signed-in AuthContext (keys
    only when limited); every pattern list in a rule must match. Anonymous callers: ``{}``
    (they follow ``mcp.anonymous.prompts`` / ``mcp.anonymous.resources``)."""
    if auth is None or not getattr(auth, 'authenticated', False):
        return {}
    prompt_rules: List[List[str]] = []
    resource_rules: List[List[str]] = []
    is_key = auth.auth_type == 'apikey'
    if is_key:
        kp, kr = apikey_catalog_rules(getattr(auth, 'api_key_mode', None), getattr(auth, 'api_key_tools', None))
        if kp is not None:
            prompt_rules.append(kp)
        if kr is not None:
            resource_rules.append(kr)
    if not auth.is_admin and not (is_key and not getattr(auth, 'api_key_owned', False)):
        roles = _caller_roles(auth)
        for kind, rules in (('prompt', prompt_rules), ('resource', resource_rules)):
            granted = _role_catalog_patterns(roles, kind)
            if granted is not None:
                rules.append(granted)
    out: Dict[str, list] = {}
    if prompt_rules:
        out['prompt_rules'] = prompt_rules
    if resource_rules:
        out['resource_rules'] = resource_rules
    return out


def _passes(rules, name: str) -> bool:
    if not isinstance(rules, list):
        return True
    return all(isinstance(r, list) and matches(name, r) for r in rules)


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
    session.update(catalog_rules_for(auth))
    return session


# ── prompts and other catalog surfaces ──────────────────────────────

def session_is_authenticated(session: Optional[Dict]) -> bool:
    """True for a session dict that belongs to a signed-in caller (see mcp_session_for)."""
    if not isinstance(session, dict):
        return False
    if session.get('authenticated') or session.get('is_admin'):
        return True
    user = session.get('user_id')
    return 'authenticated' not in session and bool(user) and user != ANONYMOUS_USER_ID


def can_see_prompt(session: Optional[Dict], prompt_name: str) -> bool:
    """
    May this caller see (list, get, complete) a prompt?  Signed-in callers: the session's
    ``prompt_rules`` (their roles' ``prompt`` permissions and their key's ``prompt:`` entries;
    see :func:`catalog_rules_for`); anonymous callers only those matching
    ``mcp.anonymous.prompts`` (fnmatch, default empty), and none when
    ``mcp.anonymous.enabled`` is false.  Federated prompts are matched by their namespaced name.  The same rule
    applies to prompts/list, prompts/get, completion/complete, the ``sajha://prompts/catalog``
    resource and the REST prompt endpoints.
    """
    if session_is_authenticated(session):
        return _passes(session.get('prompt_rules'), prompt_name)
    return anonymous_enabled() and matches(prompt_name, anonymous_prompt_patterns())


def can_read_resource(session: Optional[Dict], uri: str) -> bool:
    """
    May this caller see (list) and read a data resource (``sajha://data/<file>``, or a
    federated ``sajha-federation://<upstream>/<uri>``)?  Signed-in callers: the session's
    ``resource_rules`` (their roles' ``resource`` permissions and their key's ``resource:``
    entries; see :func:`catalog_rules_for`). Anonymous callers: only URIs matching
    ``mcp.anonymous.resources`` (fnmatch over the full URI, e.g. ``sajha://data/products.csv``
    or ``sajha://data/*``; default empty), and none when ``mcp.anonymous.enabled`` is false.
    Applies to resources/list and resources/read in both protocol eras and to
    ``/api/resources/*``. The tool and prompt catalog resources follow the tool and prompt
    rules instead.
    """
    if session_is_authenticated(session):
        return _passes(session.get('resource_rules'), uri)
    return anonymous_enabled() and matches(uri, anonymous_resource_patterns())


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

    def can_see_prompt(self, session: Optional[Dict], prompt_name: str) -> bool:
        return can_see_prompt(session, prompt_name)
