"""
SAJHA MCP Server — connected accounts: errors.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

:class:`ConnectedAccountRequired` is what a tool raises (through the injection layer)
when the caller has not linked the third-party account the tool acts with, the link
lacks a scope the tool needs, or the provider stopped accepting it.  It subclasses
:class:`~sajha.core.mcp_mrtr.InputRequired`, because that is what it is: the call cannot
finish until the user does something (opens the connect page).  Every path that already
lets ``InputRequired`` through untouched (the circuit breaker, the replay store, the
federation manager) therefore treats it as "input required", not as a tool failure; each
caller then answers in its own way (sajha/accounts/respond.py):

* MCP 2026-07-28: an MRTR ``InputRequiredResult`` with a URL-mode elicitation;
* MCP 2025-11-25: a ``URLElicitationRequiredError`` (-32042);
* either era, when the client cannot open URLs: a tool error naming the connect URL;
* REST: HTTP 428 with ``error_code: connected_account_required`` and ``connect_url``;
* Ask SAJHA: a ``needs_connection`` event and a "Connect <provider>" button.

Design: docs/architecture/Connected Accounts.md
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sajha.core.mcp_mrtr import InputRequired

#: why a connection is required
REASONS = ('not_connected', 'insufficient_scope', 'reauth_required', 'sign_in_required',
           'provider_unavailable')


class AccountsError(RuntimeError):
    """A connected-accounts operation failed (configuration, provider or vault)."""


class ProviderNotConfigured(AccountsError):
    """The provider is unknown, disabled or has no client id."""


class OAuthFlowError(AccountsError):
    """The authorization flow failed (bad state, provider error, token exchange)."""


class VaultError(AccountsError):
    """A token could not be encrypted or decrypted (wrong key, tampered row)."""


class ConnectedAccountRequired(InputRequired):
    """The caller must link (or re-link) ``provider`` before this call can run."""

    def __init__(self, provider: str, *, provider_title: str = '', connect_url: str = '',
                 reason: str = 'not_connected', scopes: Optional[List[str]] = None,
                 user_id: str = '', tool: str = ''):
        self.provider = provider
        self.provider_title = provider_title or provider
        self.connect_url = connect_url
        self.reason = reason if reason in REASONS else 'not_connected'
        self.scopes = list(scopes or [])
        self.user_id = user_id
        self.tool = tool
        self.elicitation_key = f'sajha.connect.{provider}'
        # InputRequired's own fields: filled in by the MCP 2026-07-28 responder
        super().__init__({}, {})
        self.args = (self.message,)

    @property
    def message(self) -> str:
        title = self.provider_title
        if self.reason == 'sign_in_required':
            return (f'{title} tools act as a signed-in SAJHA user with a linked {title} account; '
                    f'this caller is not a signed-in user, so it has no connected accounts.')
        if self.reason == 'insufficient_scope':
            need = ', '.join(self.scopes) or 'more access'
            return (f'Your linked {title} account does not grant {need}. Reconnect {title} at '
                    f'{self.connect_url} to grant it, then retry.')
        if self.reason == 'reauth_required':
            return (f'{title} no longer accepts your linked account (expired or revoked). '
                    f'Reconnect {title} at {self.connect_url}, then retry.')
        if self.reason == 'provider_unavailable':
            return f'{title} is not configured on this server; ask an administrator to enable it.'
        return f'Connect your {title} account at {self.connect_url}, then retry.'

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        return {'error': self.message, 'error_code': 'connected_account_required',
                'provider': self.provider, 'provider_title': self.provider_title,
                'reason': self.reason, 'scopes': self.scopes, 'connect_url': self.connect_url}
