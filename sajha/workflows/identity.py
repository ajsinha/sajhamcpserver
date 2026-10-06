"""
SAJHA MCP Server — "run as": the identity a workflow's steps run under.

Every run executes as the workflow's owner, resolved fresh at the start of each run (and
each resume) from the database: a user's current roles (admins may run every tool), or an
API key's allow/deny lists for an owner ``apikey:<name>``. A disabled or deleted owner
stops the workflow. The resolved identity is set as the caller (policy rules and the usage
ledger see the owner) and its tool policy is checked before every tool, composite and
foreach call; Ask SAJHA steps get the same check as their ``can_use_tool``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


class OwnerUnavailable(PermissionError):
    """The workflow's owner no longer exists or is disabled."""


@dataclass
class RunIdentity:
    user_id: str
    roles: List[str] = field(default_factory=list)
    is_admin: bool = False
    auth_type: str = 'workflow'
    api_key: str = ''
    can_execute: Callable[[str], bool] = lambda name: False

    def caller(self):
        from sajha.observability.caller import Caller
        return Caller(self.user_id, self.api_key, tuple(self.roles), self.auth_type)


#: tests and embedders may replace the resolver: owner -> RunIdentity
_resolver: Optional[Callable[[str], RunIdentity]] = None


def set_resolver(fn: Optional[Callable[[str], RunIdentity]]) -> None:
    global _resolver
    _resolver = fn


def resolve(owner: str) -> RunIdentity:
    if _resolver is not None:
        return _resolver(owner)
    return _from_db(owner)


def _from_db(owner: str) -> RunIdentity:
    from sajha.auth.access import ToolPolicy, _patterns_from_permissions, _role_permissions, apikey_policy
    from sajha.db.dao import UserDAO
    from sajha.db.engine import get_db_session
    db = get_db_session()
    try:
        user = UserDAO(db).get_by_user_id(owner)
        if user is not None:
            if not user.enabled:
                raise OwnerUnavailable(f'the workflow owner {owner!r} is disabled')
            roles = list(user.role_names)
            if user.is_admin:
                policy = ToolPolicy.everything()
            else:
                execute, visible = _patterns_from_permissions(_role_permissions(user.roles))
                policy = ToolPolicy(execute, visible)
            return RunIdentity(owner, roles, bool(user.is_admin), 'workflow', '', policy.can_execute)
        if owner.startswith('apikey:'):
            from sajha.db.models import ApiKey
            key = db.query(ApiKey).filter(ApiKey.name == owner[len('apikey:'):]).first()
            if key is None or not getattr(key, 'enabled', True):
                raise OwnerUnavailable(f'the workflow owner {owner!r} (an API key) no longer exists or is disabled')
            policy = apikey_policy(key.tool_access_mode, key.tool_access_list)
            return RunIdentity(owner, ['api_consumer'], False, 'workflow', key.name, policy.can_execute)
        raise OwnerUnavailable(f'the workflow owner {owner!r} no longer exists')
    finally:
        db.close()
