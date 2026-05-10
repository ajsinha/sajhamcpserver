"""
SAJHA MCP Server v3 — Data Access Objects (DAO)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

All database queries live here. No raw SQL anywhere else in the codebase.
"""

import json
import hashlib
import fnmatch
import logging
from datetime import datetime, timezone, timedelta
from typing import TypeVar, Generic, Type, Optional

from sqlalchemy import func, case, extract, desc
from sqlalchemy.orm import Session

from sajha.db.models import (
    User, Role, Permission, ApiKey, UserSession,
    ToolUsageEvent, AuditLog, A2ATask, user_roles,
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


# ── Base DAO ─────────────────────────────────────────────────────

class BaseDAO(Generic[T]):
    """Generic CRUD operations for any SQLAlchemy model."""

    def __init__(self, model: Type[T], db: Session):
        self.model = model
        self.db = db

    def get_by_id(self, id: str) -> Optional[T]:
        return self.db.query(self.model).filter(self.model.id == id).first()

    def get_all(self, skip: int = 0, limit: int = 100) -> list[T]:
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def create(self, obj: T) -> T:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def update(self, obj: T) -> T:
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: T) -> None:
        self.db.delete(obj)
        self.db.commit()

    def count(self) -> int:
        return self.db.query(self.model).count()


# ── User DAO ─────────────────────────────────────────────────────

class UserDAO(BaseDAO[User]):
    def __init__(self, db: Session):
        super().__init__(User, db)

    def get_by_user_id(self, user_id: str) -> Optional[User]:
        return self.db.query(User).filter(User.user_id == user_id).first()

    def get_by_email(self, email: str) -> Optional[User]:
        return self.db.query(User).filter(User.email == email).first()

    def get_by_oauth(self, provider: str, subject: str) -> Optional[User]:
        return self.db.query(User).filter(
            User.oauth_provider == provider,
            User.oauth_subject == subject,
        ).first()

    def get_enabled_users(self) -> list[User]:
        return self.db.query(User).filter(User.enabled == True).all()  # noqa: E712

    def get_all_users(self) -> list[User]:
        return self.db.query(User).all()

    def update_last_login(self, user_id: str) -> None:
        user = self.get_by_user_id(user_id)
        if user:
            user.last_login = datetime.now(timezone.utc)
            self.db.commit()

    def user_exists(self, user_id: str) -> bool:
        return self.db.query(User).filter(User.user_id == user_id).count() > 0


# ── Role DAO ─────────────────────────────────────────────────────

class RoleDAO(BaseDAO[Role]):
    def __init__(self, db: Session):
        super().__init__(Role, db)

    def get_by_name(self, name: str) -> Optional[Role]:
        return self.db.query(Role).filter(Role.name == name).first()

    def get_or_create(self, name: str, description: str = '', is_system: bool = False) -> Role:
        role = self.get_by_name(name)
        if role:
            return role
        role = Role(name=name, description=description, is_system=is_system)
        return self.create(role)

    def get_permissions_for_role(self, role_name: str) -> list[Permission]:
        role = self.get_by_name(role_name)
        if not role:
            return []
        return role.permissions


# ── Permission DAO ───────────────────────────────────────────────

class PermissionDAO(BaseDAO[Permission]):
    def __init__(self, db: Session):
        super().__init__(Permission, db)

    def check_access(self, roles: list[Role], resource_type: str, resource_name: str, action: str) -> bool:
        """
        Check if any of the given roles grant access to the specified resource+action.
        Supports wildcard matching: '*' matches everything, 'duckdb_*' matches duckdb_query, etc.
        """
        role_ids = [r.id for r in roles]
        if not role_ids:
            return False

        permissions = self.db.query(Permission).filter(
            Permission.role_id.in_(role_ids)
        ).all()

        for perm in permissions:
            # Check resource_type match
            if perm.resource_type != '*' and perm.resource_type != resource_type:
                continue

            # Check resource_name match (supports fnmatch wildcards)
            if perm.resource_name != '*' and not fnmatch.fnmatch(resource_name, perm.resource_name):
                continue

            # Check action match
            perm_actions = {a.strip() for a in perm.actions.split(',')}
            if '*' in perm_actions or action in perm_actions:
                return True

        return False

    def get_accessible_tools(self, roles: list[Role]) -> list[str]:
        """
        Return list of tool name patterns accessible to the given roles.
        Returns ['*'] if the user has wildcard access.
        """
        role_ids = [r.id for r in roles]
        if not role_ids:
            return []

        permissions = self.db.query(Permission).filter(
            Permission.role_id.in_(role_ids),
            Permission.resource_type.in_(['*', 'tool']),
        ).all()

        patterns = []
        for perm in permissions:
            if perm.resource_type == '*' or perm.resource_name == '*':
                return ['*']
            perm_actions = {a.strip() for a in perm.actions.split(',')}
            if '*' in perm_actions or 'execute' in perm_actions:
                patterns.append(perm.resource_name)

        return patterns


# ── API Key DAO ──────────────────────────────────────────────────

class ApiKeyDAO(BaseDAO[ApiKey]):
    def __init__(self, db: Session):
        super().__init__(ApiKey, db)

    def get_by_key_hash(self, key_hash: str) -> Optional[ApiKey]:
        return self.db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()

    def hash_key(self, raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()

    def validate_key(self, raw_key: str) -> tuple[bool, Optional[ApiKey], str]:
        key_hash = self.hash_key(raw_key)
        api_key = self.get_by_key_hash(key_hash)

        if not api_key:
            return False, None, 'Invalid API key'
        if not api_key.enabled:
            return False, None, 'API key is disabled'
        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            return False, None, 'API key has expired'

        return True, api_key, 'Valid'

    def record_usage(self, api_key: ApiKey) -> None:
        api_key.last_used = datetime.now(timezone.utc)
        api_key.usage_count += 1
        self.db.commit()

    def check_tool_access(self, api_key: ApiKey, tool_name: str) -> bool:
        if api_key.tool_access_mode == 'all':
            return True

        tool_list = json.loads(api_key.tool_access_list or '[]')

        if api_key.tool_access_mode == 'allowlist':
            return any(fnmatch.fnmatch(tool_name, pat) for pat in tool_list)
        elif api_key.tool_access_mode == 'denylist':
            return not any(fnmatch.fnmatch(tool_name, pat) for pat in tool_list)

        return False

    def get_all_keys(self, include_disabled: bool = False) -> list[ApiKey]:
        q = self.db.query(ApiKey)
        if not include_disabled:
            q = q.filter(ApiKey.enabled == True)  # noqa: E712
        return q.order_by(ApiKey.created_at.desc()).all()


# ── Tool Usage DAO ───────────────────────────────────────────────

class ToolUsageDAO(BaseDAO[ToolUsageEvent]):
    """All reporting queries live here."""

    def __init__(self, db: Session):
        super().__init__(ToolUsageEvent, db)

    def log_execution(
        self,
        tool_name: str,
        user_id: Optional[str] = None,
        auth_type: Optional[str] = None,
        duration_ms: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        arguments: Optional[dict] = None,
        result_size_bytes: Optional[int] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ToolUsageEvent:
        args_hash = None
        if arguments:
            args_hash = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()

        event = ToolUsageEvent(
            tool_name=tool_name,
            user_id=user_id,
            auth_type=auth_type,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            arguments_hash=args_hash,
            result_size_bytes=result_size_bytes,
            client_ip=client_ip,
            user_agent=user_agent,
        )
        return self.create(event)

    def get_usage_by_tool(self, since: datetime, until: datetime) -> list[dict]:
        rows = self.db.query(
            ToolUsageEvent.tool_name,
            func.count().label('total_calls'),
            func.avg(ToolUsageEvent.duration_ms).label('avg_duration_ms'),
            func.sum(case((ToolUsageEvent.success == True, 1), else_=0)).label('success_count'),  # noqa
            func.sum(case((ToolUsageEvent.success == False, 1), else_=0)).label('error_count'),  # noqa
        ).filter(
            ToolUsageEvent.timestamp.between(since, until)
        ).group_by(ToolUsageEvent.tool_name).order_by(desc('total_calls')).all()

        return [
            {
                'tool_name': r.tool_name,
                'total_calls': r.total_calls,
                'avg_duration_ms': round(float(r.avg_duration_ms or 0), 1),
                'success_count': r.success_count,
                'error_count': r.error_count,
            }
            for r in rows
        ]

    def get_usage_by_user(self, since: datetime, until: datetime) -> list[dict]:
        rows = self.db.query(
            ToolUsageEvent.user_id,
            func.count().label('total_calls'),
            func.count(func.distinct(ToolUsageEvent.tool_name)).label('tools_used'),
            func.max(ToolUsageEvent.timestamp).label('last_active'),
        ).filter(
            ToolUsageEvent.timestamp.between(since, until),
            ToolUsageEvent.user_id.isnot(None),
        ).group_by(ToolUsageEvent.user_id).order_by(desc('total_calls')).all()

        return [
            {
                'user_id': r.user_id,
                'total_calls': r.total_calls,
                'tools_used': r.tools_used,
                'last_active': r.last_active.isoformat() if r.last_active else None,
            }
            for r in rows
        ]

    def get_overview(self, period_hours: int = 24) -> dict:
        since = datetime.now(timezone.utc) - timedelta(hours=period_hours)
        total = self.db.query(func.count()).filter(
            ToolUsageEvent.timestamp >= since
        ).scalar() or 0
        errors = self.db.query(func.count()).filter(
            ToolUsageEvent.timestamp >= since,
            ToolUsageEvent.success == False,  # noqa
        ).scalar() or 0
        avg_dur = self.db.query(func.avg(ToolUsageEvent.duration_ms)).filter(
            ToolUsageEvent.timestamp >= since,
        ).scalar() or 0
        active_users = self.db.query(func.count(func.distinct(ToolUsageEvent.user_id))).filter(
            ToolUsageEvent.timestamp >= since,
        ).scalar() or 0

        return {
            'total_calls': total,
            'error_count': errors,
            'error_rate': round(errors / total * 100, 1) if total > 0 else 0,
            'avg_duration_ms': round(float(avg_dur), 1),
            'active_users': active_users,
            'period_hours': period_hours,
        }

    def get_tool_detail(self, tool_name: str, days: int = 30) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        events = self.db.query(ToolUsageEvent).filter(
            ToolUsageEvent.tool_name == tool_name,
            ToolUsageEvent.timestamp >= since,
        ).order_by(ToolUsageEvent.timestamp.desc()).limit(500).all()

        durations = [e.duration_ms for e in events if e.duration_ms is not None]
        durations.sort()
        p50 = durations[len(durations) // 2] if durations else 0
        p95 = durations[int(len(durations) * 0.95)] if durations else 0
        p99 = durations[int(len(durations) * 0.99)] if durations else 0

        return {
            'tool_name': tool_name,
            'total_calls': len(events),
            'success_count': sum(1 for e in events if e.success),
            'error_count': sum(1 for e in events if not e.success),
            'p50_ms': p50,
            'p95_ms': p95,
            'p99_ms': p99,
            'recent_errors': [
                {'timestamp': e.timestamp.isoformat(), 'message': e.error_message}
                for e in events if not e.success
            ][:10],
        }

    def get_hourly_heatmap(self, days: int = 30, tool_name: Optional[str] = None) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = self.db.query(
            extract('dow', ToolUsageEvent.timestamp).label('day_of_week'),
            extract('hour', ToolUsageEvent.timestamp).label('hour'),
            func.count().label('call_count'),
        ).filter(ToolUsageEvent.timestamp >= since)

        if tool_name:
            q = q.filter(ToolUsageEvent.tool_name == tool_name)

        rows = q.group_by('day_of_week', 'hour').all()
        return [
            {'day_of_week': int(r.day_of_week), 'hour': int(r.hour), 'count': r.call_count}
            for r in rows
        ]


# ── Audit DAO ────────────────────────────────────────────────────

class AuditDAO(BaseDAO[AuditLog]):
    def __init__(self, db: Session):
        super().__init__(AuditLog, db)

    def log(
        self,
        action: str,
        actor_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        entry = AuditLog(
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
        )
        return self.create(entry)

    def get_recent(self, limit: int = 100, action: Optional[str] = None) -> list[AuditLog]:
        q = self.db.query(AuditLog)
        if action:
            q = q.filter(AuditLog.action == action)
        return q.order_by(AuditLog.timestamp.desc()).limit(limit).all()


# ── A2A Task DAO ─────────────────────────────────────────────────

class A2ATaskDAO(BaseDAO[A2ATask]):
    def __init__(self, db: Session):
        super().__init__(A2ATask, db)

    def get_by_session(self, session_id: str) -> list[A2ATask]:
        return self.db.query(A2ATask).filter(A2ATask.session_id == session_id).all()

    def update_state(self, task_id: str, state: str, output: Optional[str] = None, error: Optional[str] = None):
        task = self.get_by_id(task_id)
        if task:
            task.state = state
            if output:
                task.output_artifacts = output
            if error:
                task.error_message = error
            task.updated_at = datetime.now(timezone.utc)
            self.db.commit()
