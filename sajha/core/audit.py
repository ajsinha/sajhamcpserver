"""
SAJHA MCP Server v5.1.0 — Structured Audit Log
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Records security-sensitive events to the audit_log DB table.
Events: login, logout, login_failed, user_create, user_delete,
apikey_create, apikey_revoke, tool_enable, tool_disable,
permission_change, config_change.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class AuditLogger:
    """Writes structured audit events to the audit_log table."""

    def log(self, action: str, user_id: str = None, resource_type: str = None,
            resource_id: str = None, details: str = None, ip_address: str = None):
        """Record an audit event."""
        try:
            from sajha.db.engine import get_db_session
            from sajha.db.models import AuditLog
            db = get_db_session()
            entry = AuditLog(
                id=str(uuid.uuid4()),
                action=action,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                ip_address=ip_address,
                created_at=datetime.now(timezone.utc),
            )
            db.add(entry)
            db.commit()
            db.close()
            logger.info(f"Audit: {action} by {user_id or 'system'} on {resource_type}:{resource_id}")
        except Exception as e:
            # Audit logging must never crash the application
            logger.error(f"Audit log write failed: {e}", exc_info=True)

    # Convenience methods
    def login_success(self, user_id: str, ip: str = None):
        self.log('login_success', user_id=user_id, resource_type='session', ip_address=ip)

    def login_failed(self, user_id: str, ip: str = None, reason: str = None):
        self.log('login_failed', user_id=user_id, resource_type='session', details=reason, ip_address=ip)

    def logout(self, user_id: str):
        self.log('logout', user_id=user_id, resource_type='session')

    def user_created(self, user_id: str, by_user: str = None):
        self.log('user_create', user_id=by_user, resource_type='user', resource_id=user_id)

    def user_deleted(self, user_id: str, by_user: str = None):
        self.log('user_delete', user_id=by_user, resource_type='user', resource_id=user_id)

    def apikey_created(self, key_name: str, by_user: str = None):
        self.log('apikey_create', user_id=by_user, resource_type='apikey', resource_id=key_name)

    def apikey_revoked(self, key_name: str, by_user: str = None):
        self.log('apikey_revoke', user_id=by_user, resource_type='apikey', resource_id=key_name)

    def tool_execution(self, tool_name: str, user_id: str = None, success: bool = True):
        self.log('tool_execute' if success else 'tool_error', user_id=user_id,
                 resource_type='tool', resource_id=tool_name)

    def config_changed(self, setting: str, by_user: str = None, details: str = None):
        self.log('config_change', user_id=by_user, resource_type='config',
                 resource_id=setting, details=details)

    def permission_changed(self, user_id: str, by_user: str = None, details: str = None):
        self.log('permission_change', user_id=by_user, resource_type='permission',
                 resource_id=user_id, details=details)

    def account_locked(self, user_id: str, ip: str = None):
        self.log('account_locked', user_id=user_id, resource_type='session',
                 details='Account locked after max failed attempts', ip_address=ip)


# Module singleton
_audit: Optional[AuditLogger] = None

def get_audit_logger() -> AuditLogger:
    global _audit
    if _audit is None:
        _audit = AuditLogger()
    return _audit
