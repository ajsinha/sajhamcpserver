"""
SAJHA MCP Server — connected accounts: settings (the ``accounts.*`` keys).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every key, its default and its environment variable are in
docs/getting-started/Configuration Reference.md#connected-accounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class AccountsSettings:
    enabled: bool = True
    public_url: str = ''
    flow_ttl_seconds: int = 600
    refresh_skew_seconds: int = 120
    http_timeout_seconds: float = 20.0
    max_response_bytes: int = 2_000_000
    vault_key: str = ''
    vault_previous_keys: List[str] = None
    vault_key_provider: str = ''

    @classmethod
    def load(cls) -> 'AccountsSettings':
        from sajha.core.config import _bool, _get, _int, _list
        try:
            timeout = float(_get('accounts.http_timeout_seconds', '20') or 20)
        except (TypeError, ValueError):
            timeout = 20.0
        return cls(
            enabled=_bool('accounts.enabled', True),
            public_url=(_get('accounts.public_url', '') or _get('mcp.auth.public_url', '') or '').strip().rstrip('/'),
            flow_ttl_seconds=max(60, _int('accounts.flow_ttl_seconds', 600)),
            refresh_skew_seconds=max(0, _int('accounts.refresh_skew_seconds', 120)),
            http_timeout_seconds=max(1.0, timeout),
            max_response_bytes=max(10_000, _int('accounts.max_response_bytes', 2_000_000)),
            vault_key=(_get('accounts.vault.key', '') or '').strip(),
            vault_previous_keys=_list('accounts.vault.previous_keys', []),
            vault_key_provider=(_get('accounts.vault.key_provider', '') or '').strip(),
        )


_settings: Optional[AccountsSettings] = None


def get_accounts_settings() -> AccountsSettings:
    global _settings
    if _settings is None:
        _settings = AccountsSettings.load()
    return _settings


def set_accounts_settings(settings: Optional[AccountsSettings]) -> None:
    """Install settings (tests); None reloads from configuration on next use."""
    global _settings
    _settings = settings


def base_url(request=None) -> str:
    """The externally visible origin: accounts.public_url, mcp.auth.public_url, the request, or the bind address."""
    s = get_accounts_settings()
    if s.public_url:
        return s.public_url
    if request is not None:
        return str(request.base_url).rstrip('/')
    from sajha.core.config import get_settings
    st = get_settings()
    host = st.server_host if st.server_host not in ('0.0.0.0', '::', '') else 'localhost'
    return f'http://{host}:{st.server_port}'
