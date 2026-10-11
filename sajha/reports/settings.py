"""
SAJHA MCP Server — Reports settings (``reports.*``), read live so an environment override
(``SAJHA_REPORTS_<KEY>``) applies without a restart.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every key: docs/getting-started/Configuration Reference.md (Reports) and
docs/architecture/Reports.md §11.
"""

from __future__ import annotations

from sajha.core.config import _bool, _get, _int


def enabled() -> bool:
    return _bool('reports.enabled', True)


def reports_dir() -> str:
    return (_get('reports.dir', 'config/reports') or 'config/reports').rstrip('/')


def output_dir() -> str:
    return (_get('reports.output_dir', 'data/reports') or 'data/reports').rstrip('/')


def history_days() -> int:
    return max(0, _int('reports.history_days', 90))


def max_sections() -> int:
    return max(1, _int('reports.max_sections', 50))


def max_run_seconds() -> int:
    return max(1, _int('reports.max_run_seconds', 300))


def max_table_rows() -> int:
    return max(1, _int('reports.max_table_rows', 1000))


def reload_seconds() -> int:
    return max(0, _int('reports.reload_seconds', 5))


def narrate_model() -> str:
    return _get('reports.narrate_model', '') or ''
