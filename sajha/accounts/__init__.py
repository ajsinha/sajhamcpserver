"""
SAJHA MCP Server — connected accounts (per-user OAuth links to third-party services).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A user links an account at GitHub, Slack, Google, Microsoft 365, Atlassian, Notion or any
configured OAuth 2.0 service once, on /account/connections.  SAJHA keeps the tokens
encrypted (``vault``), refreshes them (``service``), and tools that declare
``"auth": {"connected_account": "<provider>"}`` call the service as that user
(``injection``).  Federated upstreams can receive the caller's token the same way
(``auth.type: connected_account``).

    providers.py   the provider registry (templates + accounts.providers.*)
    vault.py       AES-256-GCM token vault over the connected_accounts table
    service.py     authorization-code flow with PKCE, refresh, revocation, audit
    injection.py   binding the caller's token to a tool call
    respond.py     "connect your account" on MCP (both eras), REST
    tools/         ConnectedAccountTool and the GitHub, Slack, Google, Microsoft tools

Design: docs/architecture/Connected Accounts.md
"""

from sajha.accounts.errors import (AccountsError, ConnectedAccountRequired, OAuthFlowError,  # noqa: F401
                                   ProviderNotConfigured, VaultError)
from sajha.accounts.injection import auth_spec, bind, current_token  # noqa: F401


def get_service():
    from sajha.accounts.service import get_service as _g
    return _g()
