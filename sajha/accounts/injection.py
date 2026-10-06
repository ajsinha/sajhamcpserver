"""
SAJHA MCP Server — connected accounts: binding a tool call to the caller's token.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A tool declares the account it acts with in its configuration::

    "auth": {"connected_account": "github", "scopes": ["repo"]}

``BaseMCPTool.execute_with_tracking`` calls :func:`bind` around every run.  For a tool
without that block it does nothing.  For one with it, it validates the arguments first
(so a malformed call is reported as such, not as "connect your account"), then asks the
service for the *caller's* token (the caller comes from
``sajha.observability.caller``, set by MCP on both eras, REST and Ask SAJHA) and makes it
available to the tool for the duration of the call through :func:`current_token`.  The
token lives in a context variable: it never enters the tool's arguments, its result,
the tool cache (per-user tools are never cached), the replay store or a log line.

When the caller has no usable link, :class:`~sajha.accounts.errors.ConnectedAccountRequired`
propagates and each front end answers it (sajha/accounts/respond.py).
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Tuple

_tokens: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar('sajha_account_tokens',
                                                                                   default=None)


def auth_spec(config: Optional[Dict[str, Any]]) -> Optional[Tuple[str, List[str]]]:
    """(provider, scopes) from a tool config's ``auth`` block, or None."""
    auth = (config or {}).get('auth') if isinstance(config, dict) else None
    if not isinstance(auth, dict):
        return None
    provider = auth.get('connected_account')
    if not isinstance(provider, str) or not provider:
        return None
    scopes = auth.get('scopes') or []
    if isinstance(scopes, str):
        scopes = scopes.replace(',', ' ').split()
    return provider, [str(s) for s in scopes]


def caller_user_id() -> str:
    from sajha.observability.caller import current
    return current().user_id


@contextmanager
def bind(tool, arguments: Dict[str, Any]) -> Iterator[Optional[Any]]:
    spec = auth_spec(getattr(tool, 'config', None))
    if spec is None:
        yield None
        return
    provider, scopes = spec
    tool.validate_arguments(arguments)
    from sajha.accounts.service import get_service
    token = get_service().resolve(caller_user_id(), provider, scopes, tool=getattr(tool, 'name', ''))
    reset = _tokens.set({**(_tokens.get() or {}), provider: token})
    try:
        yield token
    finally:
        _tokens.reset(reset)


def current_token(provider: Optional[str] = None):
    """The AccessToken bound to this call (the only one, or the one for ``provider``)."""
    bound = _tokens.get() or {}
    if provider is None:
        if len(bound) != 1:
            raise RuntimeError('no connected account is bound to this call (does the tool config declare '
                               'auth.connected_account?)')
        return next(iter(bound.values()))
    token = bound.get(provider)
    if token is None:
        raise RuntimeError(f'no {provider} account is bound to this call (does the tool config declare '
                           f'"auth": {{"connected_account": "{provider}"}}?)')
    return token


def replace_token(token) -> None:
    """After a refresh inside a call: the new token for the rest of it."""
    bound = dict(_tokens.get() or {})
    bound[token.provider.id] = token
    _tokens.set(bound)
