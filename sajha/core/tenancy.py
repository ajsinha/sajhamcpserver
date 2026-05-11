"""
SAJHA MCP Server v4.0.0 — Multi-Tenancy
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Tenant-isolated tool configs, per-tenant API key pools,
usage quotas, and data isolation.
"""

import logging
import threading
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TenantQuota:
    """Usage quota for a tenant."""
    max_tool_calls_per_day: int = 0       # 0 = unlimited
    max_tool_calls_per_month: int = 0
    max_concurrent_sessions: int = 0
    max_api_keys: int = 50
    max_llm_tokens_per_day: int = 0       # 0 = unlimited
    allowed_providers: List[str] = field(default_factory=list)  # empty = all


@dataclass
class TenantUsage:
    """Current usage counters for a tenant."""
    tool_calls_today: int = 0
    tool_calls_this_month: int = 0
    active_sessions: int = 0
    llm_tokens_today: int = 0
    last_reset_day: str = ''
    last_reset_month: str = ''


@dataclass
class Tenant:
    """A tenant (organization, team, or business unit)."""
    id: str
    name: str
    enabled: bool = True
    tool_patterns: List[str] = field(default_factory=lambda: ['*'])
    blocked_tools: List[str] = field(default_factory=list)
    quota: TenantQuota = field(default_factory=TenantQuota)
    usage: TenantUsage = field(default_factory=TenantUsage)
    data_prefix: str = ''          # isolated data directory: data/{tenant_id}/
    config_overrides: Dict = field(default_factory=dict)
    created_at: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            'id': self.id, 'name': self.name, 'enabled': self.enabled,
            'tool_patterns': self.tool_patterns, 'blocked_tools': self.blocked_tools,
            'quota': self.quota.__dict__, 'usage': self.usage.__dict__,
            'data_prefix': self.data_prefix, 'created_at': self.created_at,
        }


class TenantManager:
    """
    Manages multi-tenant isolation.

    Each tenant has:
    - Tool access patterns (which tools they can use)
    - Blocked tools list (explicit deny)
    - Usage quotas (daily/monthly call limits, token limits)
    - Data isolation (per-tenant data directory prefix)
    - Config overrides (per-tenant LLM provider, default model, etc.)
    - API key pool (keys belong to a tenant, inherit tenant permissions)
    """

    def __init__(self):
        self._tenants: Dict[str, Tenant] = {}
        self._lock = threading.Lock()
        # Default tenant for backward compatibility
        self._tenants['default'] = Tenant(
            id='default', name='Default',
            tool_patterns=['*'], created_at=datetime.utcnow().isoformat())

    def create_tenant(self, tenant_id: str, name: str, **kwargs) -> Tenant:
        with self._lock:
            if tenant_id in self._tenants:
                raise ValueError(f"Tenant already exists: {tenant_id}")
            t = Tenant(id=tenant_id, name=name,
                       data_prefix=f"data/{tenant_id}/",
                       created_at=datetime.utcnow().isoformat(), **kwargs)
            self._tenants[tenant_id] = t
            logger.info(f"Tenant created: {tenant_id} ({name})")
            return t

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)

    def list_tenants(self) -> List[Dict]:
        return [t.to_dict() for t in self._tenants.values()]

    def update_tenant(self, tenant_id: str, **kwargs) -> Optional[Tenant]:
        t = self._tenants.get(tenant_id)
        if not t:
            return None
        for k, v in kwargs.items():
            if hasattr(t, k):
                setattr(t, k, v)
        return t

    def delete_tenant(self, tenant_id: str) -> bool:
        if tenant_id == 'default':
            return False
        return self._tenants.pop(tenant_id, None) is not None

    def has_tool_access(self, tenant_id: str, tool_name: str) -> bool:
        """Check if tenant can access a specific tool."""
        t = self._tenants.get(tenant_id)
        if not t or not t.enabled:
            return False
        # Check blocked list first
        if tool_name in t.blocked_tools:
            return False
        # Check allowed patterns
        import fnmatch
        for pattern in t.tool_patterns:
            if fnmatch.fnmatch(tool_name, pattern):
                return True
        return False

    def check_quota(self, tenant_id: str) -> tuple:
        """Check if tenant is within quota. Returns (allowed, reason)."""
        t = self._tenants.get(tenant_id)
        if not t:
            return False, 'Tenant not found'
        if not t.enabled:
            return False, 'Tenant disabled'

        today = datetime.utcnow().strftime('%Y-%m-%d')
        month = datetime.utcnow().strftime('%Y-%m')

        # Reset counters if day/month changed
        if t.usage.last_reset_day != today:
            t.usage.tool_calls_today = 0
            t.usage.llm_tokens_today = 0
            t.usage.last_reset_day = today
        if t.usage.last_reset_month != month:
            t.usage.tool_calls_this_month = 0
            t.usage.last_reset_month = month

        if t.quota.max_tool_calls_per_day > 0 and t.usage.tool_calls_today >= t.quota.max_tool_calls_per_day:
            return False, f'Daily quota exceeded ({t.quota.max_tool_calls_per_day} calls/day)'
        if t.quota.max_tool_calls_per_month > 0 and t.usage.tool_calls_this_month >= t.quota.max_tool_calls_per_month:
            return False, f'Monthly quota exceeded ({t.quota.max_tool_calls_per_month} calls/month)'
        return True, 'ok'

    def record_usage(self, tenant_id: str, tool_calls: int = 1, llm_tokens: int = 0):
        t = self._tenants.get(tenant_id)
        if not t:
            return
        t.usage.tool_calls_today += tool_calls
        t.usage.tool_calls_this_month += tool_calls
        t.usage.llm_tokens_today += llm_tokens

    def get_data_prefix(self, tenant_id: str) -> str:
        """Isolated data directory for this tenant."""
        t = self._tenants.get(tenant_id)
        return t.data_prefix if t else ''

    def load_from_db(self, db_session) -> int:
        """Load tenants from database."""
        try:
            from sajha.db.models import TenantRecord
            records = db_session.query(TenantRecord).all()
            count = 0
            for rec in records:
                import json
                t = Tenant(
                    id=rec.id, name=rec.name, enabled=rec.enabled,
                    tool_patterns=json.loads(rec.tool_patterns) if rec.tool_patterns else ['*'],
                    blocked_tools=json.loads(rec.blocked_tools) if rec.blocked_tools else [],
                    data_prefix=rec.data_prefix or f"data/{rec.id}/",
                    created_at=rec.created_at.isoformat() if rec.created_at else None,
                )
                if rec.quota_json:
                    q = json.loads(rec.quota_json)
                    t.quota = TenantQuota(**q)
                self._tenants[rec.id] = t
                count += 1
            logger.info(f"Loaded {count} tenants from database")
            return count
        except Exception as e:
            logger.warning(f"Failed to load tenants from DB: {e}")
            return 0


# ── Singleton ────────────────────────────────────────────────

_manager: Optional[TenantManager] = None

def init_tenant_manager() -> TenantManager:
    global _manager
    _manager = TenantManager()
    return _manager

def get_tenant_manager() -> Optional[TenantManager]:
    return _manager
