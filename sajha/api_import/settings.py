"""
SAJHA MCP Server — API Import settings (``api_import.*``), read live so an environment
override (``SAJHA_API_IMPORT_<KEY>``) applies without a restart.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import List

from sajha.core.config import _bool, _get, _int, _list


def allow_localhost() -> bool:
    return _bool('api_import.allow_localhost', False)


def allow_private_networks() -> bool:
    return _bool('api_import.allow_private_networks', False)


def allowed_hosts() -> List[str]:
    return _list('api_import.allowed_hosts', [])


def max_tools() -> int:
    return max(1, _int('api_import.max_tools', 200))


def max_spec_bytes() -> int:
    return max(1024, _int('api_import.max_spec_bytes', 10 * 1024 * 1024))


def max_ref_documents() -> int:
    return max(0, _int('api_import.max_ref_documents', 20))


def timeout_seconds() -> int:
    return max(1, _int('api_import.timeout_seconds', 30))


def max_response_bytes() -> int:
    return max(1024, _int('api_import.max_response_bytes', 5 * 1024 * 1024))


def graphql_depth() -> int:
    return min(5, max(1, _int('api_import.graphql_depth', 2)))


def records_dir() -> str:
    return (_get('api_import.records_dir', 'config/api_imports') or 'config/api_imports').rstrip('/')
