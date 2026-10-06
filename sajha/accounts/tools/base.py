"""
SAJHA MCP Server — ConnectedAccountTool: a tool that calls a third-party API as the caller.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Subclasses implement ``run(arguments)`` and call the provider with :meth:`api`, which

* takes the caller's token bound for this call (sajha/accounts/injection.py),
* refuses any URL whose host is not in the provider's ``api_hosts`` (the token never
  leaves its own service), and adds the provider's API headers,
* on HTTP 401 refreshes the token once and retries; a second 401 marks the link
  ``reauth_required`` and raises ConnectedAccountRequired (the caller is asked to
  reconnect),
* caps the response size and turns provider errors into readable messages without
  echoing the token.

The tool is listed only while its provider is configured (``enabled`` is false
otherwise), so a server without a GitHub OAuth app does not offer GitHub tools.
Results are per user: the tool cache never applies (sajha/core/cache.py).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sajha.accounts import http as ahttp
from sajha.accounts.injection import auth_spec, current_token, replace_token
from sajha.tools.base_mcp_tool import BaseMCPTool


class ProviderAPIError(RuntimeError):
    """The provider answered with an error."""

    def __init__(self, provider: str, status: int, message: str):
        super().__init__(f'{provider} API error (HTTP {status}): {message}')
        self.status = status


class ConnectedAccountTool(BaseMCPTool):
    #: the provider when the config does not say (subclasses for one service set it)
    default_provider: str = ''
    #: scopes the tool needs when the config does not say
    default_scopes: tuple = ()

    def __init__(self, config: Optional[Dict] = None):
        cfg = dict(config or {})
        auth = dict(cfg.get('auth') or {})
        auth.setdefault('connected_account', self.default_provider)
        if 'scopes' not in auth and self.default_scopes:
            auth['scopes'] = list(self.default_scopes)
        cfg['auth'] = auth
        super().__init__(cfg)

    # ── listing ────────────────────────────────────────────────────
    @property
    def provider_id(self) -> str:
        spec = auth_spec(self.config)
        return spec[0] if spec else ''

    @property
    def enabled(self) -> bool:
        if not self._enabled:
            return False
        try:
            from sajha.accounts.providers import get_registry
            from sajha.accounts.settings import get_accounts_settings
            if not get_accounts_settings().enabled:
                return False
            p = get_registry().get(self.provider_id)
            return bool(p and p.configured)
        except Exception:
            return False

    def get_input_schema(self) -> Dict:
        return self._input_schema or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self._output_schema or {}

    def get_description(self) -> str:
        return self.description

    # ── execution ──────────────────────────────────────────────────
    def execute(self, arguments: Dict[str, Any]) -> Any:
        return self.run(dict(arguments or {}))

    def run(self, arguments: Dict[str, Any]) -> Any:     # pragma: no cover - abstract
        raise NotImplementedError

    def token(self):
        return current_token(self.provider_id)

    def is_auth_failure(self, response) -> bool:
        """True when the provider says the token is no longer good (HTTP 401 by default)."""
        return response.status_code == 401

    def api(self, method: str, url: str, *, params: Optional[Dict[str, Any]] = None,
            json_body: Any = None, data: Any = None, headers: Optional[Dict[str, str]] = None):
        """One provider API request as the caller; returns the httpx.Response (2xx/3xx/4xx except auth)."""
        from sajha.accounts.service import get_service
        from sajha.accounts.settings import get_accounts_settings
        token = self.token()
        p = token.provider
        ahttp.check_api_url(p, url)
        limit = get_accounts_settings().max_response_bytes
        for attempt in range(2):
            hdrs = {'Accept': 'application/json', **(p.api_headers or {}), **(headers or {}),
                    'Authorization': token.authorization()}
            with ahttp.client() as c:
                resp = c.request(method, url, params=_clean(params), json=json_body, data=data, headers=hdrs)
            if len(resp.content or b'') > limit:
                raise ProviderAPIError(p.title, resp.status_code, f'response larger than {limit} bytes')
            if not self.is_auth_failure(resp):
                return resp
            svc = get_service()
            if attempt == 0:
                token = svc.refresh_after_rejection(token, tool=self.name)
                replace_token(token)
                continue
            svc.mark_rejected(token)
            raise svc.required(p.id, 'reauth_required', token.user_id, tool=self.name)
        raise AssertionError('unreachable')

    def api_json(self, method: str, url: str, **kw) -> Any:
        resp = self.api(method, url, **kw)
        if resp.status_code >= 400:
            raise ProviderAPIError(self.token().provider.title, resp.status_code, _error_text(resp))
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            raise ProviderAPIError(self.token().provider.title, resp.status_code, 'the response is not JSON')


def _clean(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not params:
        return None
    return {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items() if v not in (None, '')}


def _error_text(resp) -> str:
    try:
        body = resp.json()
    except ValueError:
        return (resp.text or '')[:300]
    if isinstance(body, dict):
        err = body.get('error')
        if isinstance(err, dict):
            return str(err.get('message') or err.get('code') or err)[:300]
        msg = body.get('message') or err or body.get('error_description')
        if msg:
            return str(msg)[:300]
    return json.dumps(body)[:300]
