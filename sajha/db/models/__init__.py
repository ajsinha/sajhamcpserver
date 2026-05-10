"""
SAJHA MCP Server v3 — SQLAlchemy ORM Models
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

All persistent state lives here. No loose SQL anywhere else.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Boolean, DateTime, Integer, Text,
    Float, Table, ForeignKey, Index
)
from sqlalchemy.orm import relationship

from sajha.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Association Tables ───────────────────────────────────────────

user_roles = Table(
    'user_roles', Base.metadata,
    Column('user_id', String(36), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', String(36), ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
)


# ── User ─────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = 'users'

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(100), unique=True, nullable=False, index=True)
    user_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    password_hash = Column(String(255), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    last_login = Column(DateTime, nullable=True)

    # OAuth federation
    oauth_provider = Column(String(50), nullable=True)
    oauth_subject = Column(String(255), nullable=True)

    # Relationships
    roles = relationship('Role', secondary=user_roles, back_populates='users', lazy='joined')
    api_keys = relationship('ApiKey', back_populates='owner', cascade='all, delete-orphan')
    sessions = relationship('UserSession', back_populates='user', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.user_id}>'

    @property
    def role_names(self) -> list[str]:
        return [r.name for r in self.roles]

    @property
    def is_admin(self) -> bool:
        return 'admin' in self.role_names


# ── Role ─────────────────────────────────────────────────────────

class Role(Base):
    __tablename__ = 'roles'

    id = Column(String(36), primary_key=True, default=_uuid)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500), nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    # Relationships
    users = relationship('User', secondary=user_roles, back_populates='roles')
    permissions = relationship('Permission', back_populates='role', cascade='all, delete-orphan', lazy='joined')

    def __repr__(self):
        return f'<Role {self.name}>'


# ── Permission ───────────────────────────────────────────────────

class Permission(Base):
    """
    Fine-grained permission: (role, resource_type, resource_name, actions).

    Examples:
        role=admin, resource_type='*', resource_name='*', actions='*'
        role=analyst, resource_type='tool', resource_name='duckdb_*', actions='execute,read'
        role=viewer, resource_type='tool', resource_name='*', actions='read'
        role=studio_dev, resource_type='studio', resource_name='*', actions='*'
    """
    __tablename__ = 'permissions'

    id = Column(String(36), primary_key=True, default=_uuid)
    role_id = Column(String(36), ForeignKey('roles.id', ondelete='CASCADE'), nullable=False)
    resource_type = Column(String(50), nullable=False)
    resource_name = Column(String(255), nullable=False, default='*')
    actions = Column(String(255), nullable=False, default='*')

    role = relationship('Role', back_populates='permissions')

    __table_args__ = (
        Index('ix_perm_role_resource', 'role_id', 'resource_type', 'resource_name'),
    )

    def __repr__(self):
        return f'<Permission {self.resource_type}:{self.resource_name}:{self.actions}>'


# ── API Key ──────────────────────────────────────────────────────

class ApiKey(Base):
    __tablename__ = 'api_keys'

    id = Column(String(36), primary_key=True, default=_uuid)
    key_hash = Column(String(255), nullable=False, unique=True, index=True)
    key_prefix = Column(String(12), nullable=False)  # 'sja_xxxx' for display
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    owner_id = Column(String(36), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    last_used = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0, nullable=False)

    # Tool access control
    tool_access_mode = Column(String(20), default='all', nullable=False)  # all, allowlist, denylist
    tool_access_list = Column(Text, nullable=True)  # JSON array of tool names/patterns

    # Relationships
    owner = relationship('User', back_populates='api_keys')

    def __repr__(self):
        return f'<ApiKey {self.key_prefix}... ({self.name})>'


# ── User Session ─────────────────────────────────────────────────

class UserSession(Base):
    """DB-backed sessions (replaces in-memory dict)."""
    __tablename__ = 'user_sessions'

    id = Column(String(36), primary_key=True, default=_uuid)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    user_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    last_activity = Column(DateTime, default=_utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    user = relationship('User', back_populates='sessions')

    __table_args__ = (
        Index('ix_session_expires', 'expires_at'),
    )

    def __repr__(self):
        return f'<UserSession user={self.user_id}>'


# ── Tool Usage Event ─────────────────────────────────────────────

class ToolUsageEvent(Base):
    """Every tool execution is logged here. Foundation for all reporting."""
    __tablename__ = 'tool_usage_events'

    id = Column(String(36), primary_key=True, default=_uuid)
    tool_name = Column(String(255), nullable=False, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    auth_type = Column(String(20), nullable=True)   # session, apikey, oauth, anonymous
    timestamp = Column(DateTime, nullable=False, default=_utcnow, index=True)
    duration_ms = Column(Integer, nullable=True)
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)
    arguments_hash = Column(String(64), nullable=True)
    result_size_bytes = Column(Integer, nullable=True)
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)

    __table_args__ = (
        Index('ix_tool_usage_tool_time', 'tool_name', 'timestamp'),
        Index('ix_tool_usage_user_time', 'user_id', 'timestamp'),
    )

    def __repr__(self):
        return f'<ToolUsageEvent {self.tool_name} by {self.user_id}>'


# ── Audit Log ────────────────────────────────────────────────────

class AuditLog(Base):
    """Tracks admin actions: user create/delete, tool enable/disable, config changes."""
    __tablename__ = 'audit_log'

    id = Column(String(36), primary_key=True, default=_uuid)
    timestamp = Column(DateTime, nullable=False, default=_utcnow, index=True)
    actor_id = Column(String(100), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(String(255), nullable=True)
    details = Column(Text, nullable=True)   # JSON with before/after
    ip_address = Column(String(45), nullable=True)

    def __repr__(self):
        return f'<AuditLog {self.action} by {self.actor_id}>'


# ── A2A Task ─────────────────────────────────────────────────────

class A2ATask(Base):
    """Agent-to-Agent task with lifecycle state management."""
    __tablename__ = 'a2a_tasks'

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(100), nullable=True, index=True)
    state = Column(String(20), default='submitted', nullable=False)
    input_message = Column(Text, nullable=True)       # JSON
    output_artifacts = Column(Text, nullable=True)     # JSON array
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    caller_agent = Column(String(255), nullable=True)
    metadata_json = Column(Text, nullable=True)        # JSON

    # Valid states: submitted, working, input-required, completed, failed, cancelled

    def __repr__(self):
        return f'<A2ATask {self.id[:8]} state={self.state}>'
