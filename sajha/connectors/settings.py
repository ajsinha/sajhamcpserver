"""
SAJHA MCP Server — Data Connectors settings (``connectors.*``), read live so an environment
override (``SAJHA_CONNECTORS_<KEY>``) applies without a restart.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every key: docs/getting-started/Configuration Reference.md#data-connectors.
"""

from __future__ import annotations

from sajha.core.config import _bool, _get, _int


def enabled() -> bool:
    return _bool('connectors.enabled', True)


def records_dir() -> str:
    return (_get('connectors.records_dir', 'config/connectors') or 'config/connectors').rstrip('/')


def default_max_rows() -> int:
    return max(1, _int('connectors.default_max_rows', 500))


def max_rows_limit() -> int:
    return max(1, _int('connectors.max_rows_limit', 10000))


def default_max_bytes() -> int:
    return max(1024, _int('connectors.default_max_bytes', 2 * 1024 * 1024))


def max_bytes_limit() -> int:
    return max(1024, _int('connectors.max_bytes_limit', 16 * 1024 * 1024))


def default_timeout_seconds() -> int:
    return max(1, _int('connectors.default_timeout_seconds', 30))


def max_timeout_seconds() -> int:
    return max(1, _int('connectors.max_timeout_seconds', 300))


def sample_rows() -> int:
    return min(20, max(0, _int('connectors.sample_rows', 3)))


def catalog_ttl_seconds() -> int:
    return max(0, _int('connectors.catalog_ttl_seconds', 600))


def catalog_max_tables() -> int:
    return max(1, _int('connectors.catalog_max_tables', 2000))


def pool_size() -> int:
    return max(0, _int('connectors.pool_size', 4))


def pool_max_age_seconds() -> int:
    return max(1, _int('connectors.pool_max_age_seconds', 300))


def record_refresh_seconds() -> int:
    return max(0, _int('connectors.record_refresh_seconds', 5))


def require_sqlglot() -> bool:
    return _bool('connectors.require_sqlglot', False)


def audit_sql() -> bool:
    return _bool('connectors.audit_sql', False)


def sync_on_startup() -> bool:
    return _bool('connectors.sync_on_startup', True)
