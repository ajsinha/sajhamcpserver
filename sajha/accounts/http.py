"""
SAJHA MCP Server — connected accounts: outbound HTTP.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every request SAJHA makes for connected accounts (token exchange, refresh, revocation,
user info, and the provider API calls tools make) goes through :func:`client`, so a
test can install an in-process transport (:func:`set_transport`) and a deployment can
see one place where tokens leave the server.

:func:`check_api_url` is the rule that keeps a linked token on its own service: a token
for provider P is only ever sent over https to a host listed in P's ``api_hosts``.
"""

from __future__ import annotations

import fnmatch
import json
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlsplit

import httpx

_transport: Optional[httpx.BaseTransport] = None


def set_transport(transport: Optional[httpx.BaseTransport]) -> None:
    """Route every connected-accounts request through ``transport`` (tests); None restores the network."""
    global _transport
    _transport = transport


def client(timeout: Optional[float] = None) -> httpx.Client:
    from sajha.accounts.settings import get_accounts_settings
    t = timeout or get_accounts_settings().http_timeout_seconds
    from sajha.core.config import get_settings
    headers = {'User-Agent': f'sajha-connected-accounts/{get_settings().app_version}'}
    from sajha.observability.tracing import httpx_hooks
    if _transport is not None:
        return httpx.Client(transport=_transport, timeout=t, follow_redirects=False, headers=headers,
                            event_hooks=httpx_hooks())
    return httpx.Client(timeout=t, follow_redirects=False, headers=headers, trust_env=False,
                        event_hooks=httpx_hooks())


class TokenHostError(PermissionError):
    """A request would send a linked token to a host outside the provider's api_hosts."""


def host_matches(host: str, patterns) -> bool:
    host = (host or '').lower().rstrip('.')
    return any(fnmatch.fnmatchcase(host, p.lower()) for p in patterns or [])


def check_api_url(provider, url: str) -> str:
    """``url`` when it is https and on one of ``provider.api_hosts``; raises TokenHostError otherwise."""
    p = urlsplit(url or '')
    host = (p.hostname or '').lower()
    if p.username or p.password:
        raise TokenHostError('the URL must not carry credentials')
    loopback = host in ('127.0.0.1', 'localhost', '::1')
    if p.scheme != 'https' and not (p.scheme == 'http' and loopback and host_matches(host, provider.api_hosts)):
        raise TokenHostError('linked tokens are only sent over https')
    if not host_matches(host, provider.api_hosts):
        raise TokenHostError(f'{host} is not one of the hosts a {provider.title} token may be sent to '
                             f'({", ".join(provider.api_hosts)})')
    return url


def parse_token_response(resp: httpx.Response) -> Dict[str, Any]:
    """A token endpoint's answer as a dict: JSON, or form-encoded (older GitHub style)."""
    ctype = resp.headers.get('content-type', '')
    text = resp.text or ''
    if 'json' in ctype or text.lstrip().startswith('{'):
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    return dict(parse_qsl(text))
