"""
SAJHA MCP Server — connected accounts: the provider registry.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A *provider* is a third-party service a user links once with OAuth 2.0 (authorization
code, with PKCE where the service supports it): GitHub, Slack, Google, Microsoft 365,
Atlassian, Notion, or any OAuth 2.0 service an administrator describes.

Providers are configuration, not code.  SAJHA ships *templates* for the built-in ones
(endpoints, default scopes, PKCE support, the hosts its API lives on, quirks such as
Slack's ``user_scope``); ``accounts.providers.<id>`` in application.yml switches one on by
giving it a client id and a client-secret *reference*, and may override any field.  An id
that is not a template is a custom provider and must give every endpoint itself.

Field resolution, per provider and field: ``SAJHA_ACCOUNTS_PROVIDERS_<ID>_<FIELD>`` →
``accounts.providers.<id>.<field>`` (YAML, ``${ENV:default}`` allowed) → the template.
``SAJHA_ACCOUNTS_PROVIDERS`` (a JSON object ``{id: {field: value}}``) replaces the YAML
block when set.  Secrets are never values here: ``client_secret_ref`` is ``env:NAME``,
``file:/path`` or ``db:...`` and is resolved only when a token request is made.

Design: docs/architecture/Connected Accounts.md
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROVIDER_ID = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
TOKEN_AUTH_METHODS = ('client_secret_post', 'client_secret_basic', 'none')
TOKEN_FORMATS = ('form', 'json')
REVOKE_STYLES = ('none', 'rfc7009', 'github', 'slack', 'google')

#: Built-in provider templates.  URLs and scopes are each service's documented OAuth 2.0
#: endpoints; ``api_hosts`` lists the only hosts a linked token is ever sent to.
TEMPLATES: Dict[str, Dict[str, Any]] = {
    'github': {
        'title': 'GitHub', 'icon': 'github',
        'description': 'Repositories, issues and pull requests as you.',
        'authorize_url': 'https://github.com/login/oauth/authorize',
        'token_url': 'https://github.com/login/oauth/access_token',
        'revoke_url': 'https://api.github.com/applications/{client_id}/grant', 'revoke_style': 'github',
        'userinfo_url': 'https://api.github.com/user', 'login_field': 'login', 'id_field': 'id',
        'scopes': ['read:user', 'repo'], 'scope_separator': ' ', 'pkce': True,
        'scope_implies': {'repo': ['public_repo', 'repo:status', 'repo_deployment', 'repo:invite'],
                          'user': ['read:user', 'user:email', 'user:follow']},
        'api_hosts': ['api.github.com', 'uploads.github.com'],
        'api_headers': {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'},
        'docs_url': 'https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps',
    },
    'slack': {
        'title': 'Slack', 'icon': 'slack',
        'description': 'Post and read messages in your workspace as you (a user token).',
        'authorize_url': 'https://slack.com/oauth/v2/authorize',
        'token_url': 'https://slack.com/api/oauth.v2.access',
        'revoke_url': 'https://slack.com/api/auth.revoke', 'revoke_style': 'slack',
        'userinfo_url': 'https://slack.com/api/auth.test', 'login_field': 'user', 'id_field': 'user_id',
        # Slack issues user tokens for "user_scope" and returns them under "authed_user"
        'scopes': ['chat:write', 'channels:read'], 'scope_separator': ',', 'scope_param': 'user_scope',
        'token_response_path': 'authed_user', 'pkce': False,
        'api_hosts': ['slack.com'],
        'docs_url': 'https://api.slack.com/authentication/oauth-v2',
    },
    'google': {
        'title': 'Google Workspace', 'icon': 'google',
        'description': 'Drive, Calendar and Gmail as you.',
        'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token_url': 'https://oauth2.googleapis.com/token',
        'revoke_url': 'https://oauth2.googleapis.com/revoke', 'revoke_style': 'google',
        'userinfo_url': 'https://openidconnect.googleapis.com/v1/userinfo', 'login_field': 'email', 'id_field': 'sub',
        'scopes': ['openid', 'email', 'https://www.googleapis.com/auth/drive.readonly'],
        'scope_separator': ' ', 'pkce': True,
        'scope_implies': {'https://www.googleapis.com/auth/drive': ['https://www.googleapis.com/auth/drive.readonly']},
        # offline access + consent: Google returns a refresh token only then
        'authorize_params': {'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true'},
        'api_hosts': ['www.googleapis.com', '*.googleapis.com'],
        'docs_url': 'https://developers.google.com/identity/protocols/oauth2/web-server',
    },
    'microsoft': {
        'title': 'Microsoft 365', 'icon': 'microsoft',
        'description': 'Outlook calendar and mail, OneDrive and Teams through Microsoft Graph, as you.',
        'authorize_url': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize',
        'token_url': 'https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token',
        'revoke_style': 'none',
        'userinfo_url': 'https://graph.microsoft.com/v1.0/me', 'login_field': 'userPrincipalName', 'id_field': 'id',
        'scopes': ['offline_access', 'User.Read', 'Calendars.Read'], 'scope_separator': ' ', 'pkce': True,
        'scope_strip_prefixes': ['https://graph.microsoft.com/'], 'scope_case_insensitive': True,
        'scope_implies': {'Calendars.ReadWrite': ['Calendars.Read']},
        'tenant': 'common',
        'api_hosts': ['graph.microsoft.com'],
        'docs_url': 'https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow',
    },
    'atlassian': {
        'title': 'Atlassian (Jira, Confluence)', 'icon': 'kanban',
        'description': 'Jira issues and Confluence pages as you.',
        'authorize_url': 'https://auth.atlassian.com/authorize',
        'token_url': 'https://auth.atlassian.com/oauth/token', 'token_request_format': 'json',
        'revoke_style': 'none',
        'userinfo_url': 'https://api.atlassian.com/me', 'login_field': 'email', 'id_field': 'account_id',
        'scopes': ['read:jira-work', 'read:jira-user', 'read:me', 'offline_access'], 'scope_separator': ' ',
        'pkce': False,
        'authorize_params': {'audience': 'api.atlassian.com', 'prompt': 'consent'},
        'api_hosts': ['api.atlassian.com'],
        'docs_url': 'https://developer.atlassian.com/cloud/jira/platform/oauth-2-3lo-apps/',
    },
    'notion': {
        'title': 'Notion', 'icon': 'journal-richtext',
        'description': 'Pages and databases you share with the integration.',
        'authorize_url': 'https://api.notion.com/v1/oauth/authorize',
        'token_url': 'https://api.notion.com/v1/oauth/token', 'token_request_format': 'json',
        'token_auth_method': 'client_secret_basic', 'revoke_style': 'none',
        'userinfo_url': '', 'login_field': 'workspace_name', 'id_field': 'bot_id',
        'scopes': [], 'pkce': False,
        'authorize_params': {'owner': 'user'},
        'api_hosts': ['api.notion.com'],
        'api_headers': {'Notion-Version': '2022-06-28'},
        'docs_url': 'https://developers.notion.com/docs/authorization',
    },
}

_FIELDS = ('title', 'icon', 'description', 'authorize_url', 'token_url', 'revoke_url', 'revoke_style',
           'userinfo_url', 'login_field', 'id_field', 'scopes', 'scope_separator', 'scope_param',
           'scope_implies', 'scope_strip_prefixes', 'scope_case_insensitive', 'pkce', 'token_auth_method',
           'token_request_format', 'token_response_path', 'authorize_params', 'token_params', 'api_hosts',
           'api_headers', 'client_id', 'client_secret_ref', 'redirect_uri', 'enabled', 'tenant', 'docs_url',
           'template')


class ProviderConfigError(ValueError):
    """A provider definition is invalid."""


@dataclass
class Provider:
    id: str
    title: str = ''
    icon: str = 'link-45deg'
    description: str = ''
    authorize_url: str = ''
    token_url: str = ''
    revoke_url: str = ''
    revoke_style: str = 'rfc7009'
    userinfo_url: str = ''
    login_field: str = ''
    id_field: str = ''
    scopes: List[str] = field(default_factory=list)
    scope_separator: str = ' '
    scope_param: str = 'scope'
    scope_implies: Dict[str, List[str]] = field(default_factory=dict)
    scope_strip_prefixes: List[str] = field(default_factory=list)
    scope_case_insensitive: bool = False
    pkce: bool = True
    token_auth_method: str = 'client_secret_post'
    token_request_format: str = 'form'
    token_response_path: str = ''
    authorize_params: Dict[str, str] = field(default_factory=dict)
    token_params: Dict[str, str] = field(default_factory=dict)
    api_hosts: List[str] = field(default_factory=list)
    api_headers: Dict[str, str] = field(default_factory=dict)
    client_id: str = ''
    client_secret_ref: str = ''
    redirect_uri: str = ''
    enabled: bool = True
    tenant: str = ''
    docs_url: str = ''
    template: str = ''

    # ── derived ────────────────────────────────────────────────────
    @property
    def configured(self) -> bool:
        """Enabled and has a client id: users can link it."""
        return bool(self.enabled and self.client_id and self.authorize_url and self.token_url)

    def url(self, which: str) -> str:
        raw = getattr(self, which) or ''
        return raw.replace('{tenant}', self.tenant or 'common').replace('{client_id}', self.client_id or '')

    def normalize_scope(self, scope: str) -> str:
        s = (scope or '').strip()
        for prefix in self.scope_strip_prefixes:
            if s.startswith(prefix):
                s = s[len(prefix):]
        return s.lower() if self.scope_case_insensitive else s

    def split_scopes(self, raw: Any) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, (list, tuple)):
            items = [str(x) for x in raw]
        else:
            items = re.split(r'[\s,]+', str(raw))
        out: List[str] = []
        for s in items:
            s = s.strip()
            if s and s not in out:
                out.append(s)
        return out

    def expand(self, scopes: List[str]) -> set:
        """Normalised scopes plus everything they imply."""
        have = set()
        implies = {self.normalize_scope(k): [self.normalize_scope(x) for x in v]
                   for k, v in (self.scope_implies or {}).items()}
        for s in scopes:
            n = self.normalize_scope(s)
            have.add(n)
            have.update(implies.get(n, []))
        return have

    def missing_scopes(self, granted: List[str], required: List[str]) -> List[str]:
        have = self.expand(granted)
        return [s for s in required if self.normalize_scope(s) not in have]

    def public_dict(self) -> Dict[str, Any]:
        """What the account page and the admin view show: never the secret reference's value."""
        return {'id': self.id, 'title': self.title or self.id, 'icon': self.icon, 'description': self.description,
                'scopes': list(self.scopes), 'pkce': self.pkce, 'configured': self.configured,
                'enabled': self.enabled, 'refresh': True, 'docs_url': self.docs_url,
                'template': self.template, 'api_hosts': list(self.api_hosts)}

    def validate(self) -> None:
        if not PROVIDER_ID.match(self.id):
            raise ProviderConfigError(f'provider id {self.id!r}: a lower-case letter, then letters, digits, - or _')
        if self.token_auth_method not in TOKEN_AUTH_METHODS:
            raise ProviderConfigError(f'{self.id}: token_auth_method must be one of {", ".join(TOKEN_AUTH_METHODS)}')
        if self.token_request_format not in TOKEN_FORMATS:
            raise ProviderConfigError(f'{self.id}: token_request_format must be form or json')
        if self.revoke_style not in REVOKE_STYLES:
            raise ProviderConfigError(f'{self.id}: revoke_style must be one of {", ".join(REVOKE_STYLES)}')
        if self.client_secret_ref and not _is_ref(self.client_secret_ref):
            raise ProviderConfigError(f'{self.id}: client_secret_ref must be a reference (env:NAME, file:/path '
                                      f'or db:table/key), never the secret itself')
        if self.enabled and self.client_id:
            for key in ('authorize_url', 'token_url'):
                url = self.url(key)
                if not url.startswith('https://') and not _loopback(url):
                    raise ProviderConfigError(f'{self.id}: {key} must be an https:// URL')
            if not self.api_hosts:
                raise ProviderConfigError(f'{self.id}: api_hosts must list the hosts its API lives on '
                                          f'(a linked token is sent nowhere else)')
            if self.token_auth_method != 'none' and not self.client_secret_ref and not self.pkce:
                raise ProviderConfigError(f'{self.id}: a public client (no client_secret_ref) needs pkce: true')


def _is_ref(value: Any) -> bool:
    return isinstance(value, str) and ':' in value and value.split(':', 1)[0].lower() in ('env', 'file', 'db')


def _loopback(url: str) -> bool:
    return url.startswith(('http://127.0.0.1', 'http://localhost', 'http://[::1]'))


# ── loading ─────────────────────────────────────────────────────────

def _raw_provider_config() -> Dict[str, Dict[str, Any]]:
    raw = os.environ.get('SAJHA_ACCOUNTS_PROVIDERS')
    if raw is not None:
        try:
            value = json.loads(raw or '{}')
        except ValueError:
            logger.warning('SAJHA_ACCOUNTS_PROVIDERS is not a JSON object; ignored')
            return {}
        return {str(k): v for k, v in value.items() if isinstance(v, dict)} if isinstance(value, dict) else {}
    path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as e:
        logger.warning(f'accounts: cannot read {path}: {e}')
        return {}
    block = ((data.get('accounts') or {}).get('providers')) or {}
    if not isinstance(block, dict):
        return {}
    return {str(k): _substitute(v) for k, v in block.items() if isinstance(v, dict)}


def _substitute(value):
    from sajha.core.config import _substitute_vars
    if isinstance(value, str):
        return _substitute_vars(value)
    if isinstance(value, dict):
        return {k: _substitute(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v) for v in value]
    return value


def _coerce(name: str, value: Any, default: Any) -> Any:
    from sajha.core.config import parse_bool, parse_list
    if isinstance(default, bool):
        return parse_bool(value, default)
    if isinstance(default, list):
        return parse_list(value) if not isinstance(value, list) else [str(x) for x in value]
    if isinstance(default, dict):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                raise ProviderConfigError(f'{name} must be an object')
        if not isinstance(value, dict):
            raise ProviderConfigError(f'{name} must be an object')
        return dict(value)
    return '' if value is None else str(value)


def build_provider(pid: str, overrides: Optional[Dict[str, Any]] = None, use_env: bool = True) -> Provider:
    """A Provider from its template (when ``pid`` or ``template`` names one) plus overrides."""
    overrides = dict(overrides or {})
    if 'client_secret' in overrides:
        raise ProviderConfigError(f'{pid}: put the secret in client_secret_ref (env:NAME), not in the config')
    unknown = set(overrides) - set(_FIELDS)
    if unknown:
        raise ProviderConfigError(f'{pid}: unknown field(s) {", ".join(sorted(unknown))}')
    template = str(overrides.get('template') or (pid if pid in TEMPLATES else ''))
    if template and template not in TEMPLATES:
        raise ProviderConfigError(f'{pid}: unknown template {template!r}')
    base = copy.deepcopy(TEMPLATES.get(template, {}))
    p = Provider(id=pid, template=template)
    for f in _FIELDS:
        if f in ('template',):
            continue
        default = getattr(p, f)
        value = base.get(f, default)
        if f in overrides:
            value = overrides[f]
        if use_env:
            env = os.environ.get(f'SAJHA_ACCOUNTS_PROVIDERS_{pid.upper().replace("-", "_")}_{f.upper()}')
            if env is not None:
                value = env
        setattr(p, f, _coerce(f'{pid}.{f}', value, default))
    if not p.title:
        p.title = pid
    p.validate()
    return p


class ProviderRegistry:
    """Every built-in template plus the configured custom providers, by id."""

    def __init__(self, providers: Dict[str, Provider], errors: Optional[Dict[str, str]] = None):
        self._providers = providers
        self.errors = dict(errors or {})

    @classmethod
    def load(cls, raw: Optional[Dict[str, Dict[str, Any]]] = None, use_env: bool = True) -> 'ProviderRegistry':
        raw = _raw_provider_config() if raw is None else raw
        providers: Dict[str, Provider] = {}
        errors: Dict[str, str] = {}
        for pid in list(TEMPLATES) + [k for k in raw if k not in TEMPLATES]:
            try:
                providers[pid] = build_provider(pid, raw.get(pid), use_env=use_env)
            except ProviderConfigError as e:
                errors[pid] = str(e)
                logger.warning(f'accounts: provider {pid} not loaded: {e}')
        return cls(providers, errors)

    def get(self, pid: str) -> Optional[Provider]:
        return self._providers.get(pid)

    def all(self) -> List[Provider]:
        return list(self._providers.values())

    def configured(self) -> List[Provider]:
        return [p for p in self._providers.values() if p.configured]


_registry: Optional[ProviderRegistry] = None
_lock = threading.Lock()


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = ProviderRegistry.load()
    return _registry


def set_registry(registry: Optional[ProviderRegistry]) -> None:
    """Install a registry (tests); None reloads from configuration on next use."""
    global _registry
    with _lock:
        _registry = registry
