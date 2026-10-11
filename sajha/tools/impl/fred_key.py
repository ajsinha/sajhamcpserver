"""
SAJHA MCP Server — the one FRED API key lookup for every FRED-backed tool.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

fred_*, fed_*, pboc_* and boj_* tools read FRED (api.stlouisfed.org), which needs a free key.
Resolution order: the tool config's ``api_key`` (configs carry ``"api_key": "${fred.api.key}"``,
which the registry resolves from application.yml ``fred.api.key`` / the FRED_API_KEY environment
variable), then FRED_API_KEY directly. An unresolved placeholder, an empty value, ``demo`` or
``DEMO_KEY`` means "not configured": the call fails with a message that says how to configure
the key. No FRED-backed tool ever returns invented values in place of data.
"""

import os
from typing import Any, Mapping, Optional

NOT_CONFIGURED = (
    "FRED API key not configured. Set the FRED_API_KEY environment variable "
    "(application.yml: fred.api.key). "
    "Get a free API key at https://fred.stlouisfed.org/docs/api/api_key.html"
)
_PLACEHOLDERS = {'demo', 'demo_key'}


def configured_key(config: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The configured FRED key, or None."""
    for candidate in ((config or {}).get('api_key'), os.environ.get('FRED_API_KEY')):
        if isinstance(candidate, str):
            value = candidate.strip()
            if value and not value.startswith('${') and value.lower() not in _PLACEHOLDERS:
                return value
    return None


def fred_api_key(config: Optional[Mapping[str, Any]]) -> str:
    """The configured FRED key; raises ValueError naming the setting when there is none."""
    key = configured_key(config)
    if not key:
        raise ValueError(NOT_CONFIGURED)
    return key
