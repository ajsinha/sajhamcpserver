"""
SAJHA MCP Server — observability settings (``observability.*`` in application.yml).

Scalar keys resolve through ``sajha.core.config._get`` (``SAJHA_OBSERVABILITY_*`` env →
YAML → default), read live so tests and a restart pick changes up. The alert rule list
is nested data: it is read from the raw YAML, or from ``SAJHA_OBSERVABILITY_ALERTS`` (a
JSON list), which replaces it. Every key: docs/getting-started/Configuration Reference.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _get(key: str, default: str = '') -> str:
    from sajha.core.config import _get as cfg_get
    return cfg_get(key, default)


def get_bool(key: str, default: bool) -> bool:
    from sajha.core.config import parse_bool
    v = _get(key, '')
    return parse_bool(v, default) if v != '' else default


def get_int(key: str, default: int) -> int:
    try:
        v = _get(key, '')
        return int(float(v)) if v != '' else default
    except (TypeError, ValueError):
        return default


def get_float(key: str, default: float) -> float:
    try:
        v = _get(key, '')
        return float(v) if v != '' else default
    except (TypeError, ValueError):
        return default


def get_str(key: str, default: str = '') -> str:
    v = _get(key, None)
    return default if v is None else str(v)


def get_list(key: str) -> List[str]:
    from sajha.core.config import _list
    return _list(key, [])


# ── metrics ─────────────────────────────────────────────────────────

def metrics_enabled() -> bool:
    return get_bool('observability.metrics.enabled', True)


def metrics_auth() -> str:
    mode = get_str('observability.metrics.auth', 'admin').strip().lower()
    return mode if mode in ('none', 'token', 'admin') else 'admin'


def metrics_token() -> str:
    # A secret: environment only (SAJHA_OBSERVABILITY_METRICS_TOKEN), never the YAML.
    return os.environ.get('SAJHA_OBSERVABILITY_METRICS_TOKEN', '')


def tool_label_mode() -> str:
    mode = get_str('observability.metrics.tool_label', 'name').strip().lower()
    return mode if mode in ('name', 'group', 'none') else 'name'


def max_series() -> int:
    return max(10, get_int('observability.metrics.max_series', 2000))


# ── alerts ──────────────────────────────────────────────────────────

def _raw_section() -> Dict[str, Any]:
    path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as e:
        logger.warning(f'observability: cannot read {path}: {e}')
        return {}
    return data.get('observability') or {}


def alert_rules_raw() -> List[Dict[str, Any]]:
    env = os.environ.get('SAJHA_OBSERVABILITY_ALERTS')
    if env:
        try:
            rules = json.loads(env)
            return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []
        except ValueError as e:
            logger.warning(f'SAJHA_OBSERVABILITY_ALERTS is not a JSON list: {e}')
            return []
    rules = _raw_section().get('alerts') or []
    return [r for r in rules if isinstance(r, dict)] if isinstance(rules, list) else []


def describe() -> Dict[str, Any]:
    """The effective settings (no secrets), for the dashboard and the docs test."""
    return {
        'metrics': {'enabled': metrics_enabled(), 'auth': metrics_auth(),
                    'token_set': bool(metrics_token()),
                    'port': get_int('observability.metrics.port', 0),
                    'host': get_str('observability.metrics.host', '0.0.0.0'),
                    'tool_label': tool_label_mode(), 'max_series': max_series(),
                    'multiworker': get_str('observability.metrics.multiworker', 'auto')},
        'otel': {'enabled': get_bool('observability.otel.enabled', False)},
        'usage': {'enabled': get_bool('observability.usage.enabled', True),
                  'retention_days': get_int('observability.usage.retention_days', 90)},
        'alerts': len(alert_rules_raw()),
    }
