"""
SAJHA MCP Server — tool quality: the test harness (cases, assertions, HTTP cassettes, JUnit),
the schema linter, health probes, evals for Ask SAJHA, and tool versions with canary routing,
automatic rollback and deprecation.

Design and operation: docs/architecture/Tool Quality.md

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from sajha.core.config import _get


def setting(key: str, default: str = '') -> str:
    """``quality.<key>`` through the usual resolution (SAJHA_QUALITY_* env, YAML, default)."""
    return _get(f'quality.{key}', default)


def setting_int(key: str, default: int) -> int:
    try:
        return int(float(setting(key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def setting_bool(key: str, default: bool = False) -> bool:
    from sajha.core.config import parse_bool
    return parse_bool(setting(key, 'true' if default else 'false'), default)


def tests_dir() -> str:
    return setting('tests_dir', 'config/tool_tests') or 'config/tool_tests'


def cassettes_dir() -> str:
    return setting('cassettes_dir', 'config/tool_tests/cassettes') or 'config/tool_tests/cassettes'


def evals_dir() -> str:
    return setting('evals_dir', 'config/evals') or 'config/evals'


def versions_dir() -> str:
    return setting('versions_dir', 'config/tool_versions') or 'config/tool_versions'
