"""
SAJHA MCP Server — federation security: the URL guard, untrusted-text screening, secrets.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* ``check_url``: an upstream (or OAuth token) URL must be http(s) without credentials, its
  host must match ``federation.allowed_hosts`` when set, and every address it resolves to
  must pass ``address_allowed`` (the SSRF guard shared with CIMD fetches and webhooks).
* ``screen_text`` / ``screen_schema``: upstream names, titles and descriptions are what an
  LLM reads when it picks a tool, so they are treated as untrusted input: control
  characters stripped, length capped, injection markers replaced and flagged.
* ``secrets()`` / ``redact``: credentials are references resolved by the intelligence
  layer's SecretStore; nothing resolved is ever logged or shown.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import re
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit


class UnsafeURLError(ValueError):
    """The URL is not an allowed federation destination."""


# ── URL guard ───────────────────────────────────────────────────────

def check_url(url: str, settings, resolve: bool = True) -> Tuple[str, int]:
    """Validate ``url`` for federation; returns (host, port). Raises UnsafeURLError."""
    try:
        p = urlsplit(url or '')
    except ValueError:
        raise UnsafeURLError('the URL cannot be parsed')
    if p.scheme not in ('http', 'https'):
        raise UnsafeURLError('the URL must use http or https')
    if p.username or p.password or '@' in p.netloc:
        raise UnsafeURLError('the URL must not contain credentials; use auth with a secret reference')
    host = (p.hostname or '').lower().rstrip('.')
    if not host:
        raise UnsafeURLError('the URL has no host')
    try:
        port = p.port or (443 if p.scheme == 'https' else 80)
    except ValueError:
        raise UnsafeURLError('the URL has an invalid port')
    allowed = [h.strip().lower() for h in (settings.allowed_hosts or []) if h.strip()]
    if allowed and not any(fnmatch.fnmatchcase(host, pat) for pat in allowed):
        raise UnsafeURLError(f'host {host} is not in federation.allowed_hosts')
    if resolve:
        _check_addresses(host, port, settings)
    return host, port


def _check_addresses(host: str, port: int, settings) -> None:
    from sajha.auth.oauth.clients import address_allowed
    try:
        addrs = [str(ipaddress.ip_address(host.strip('[]')))]
    except ValueError:
        try:
            addrs = sorted({r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        except OSError as e:
            raise UnsafeURLError(f'host {host} does not resolve ({e.__class__.__name__})')
    if not addrs:
        raise UnsafeURLError(f'host {host} does not resolve')
    for addr in addrs:
        ip = ipaddress.ip_address(addr.split('%')[0])
        if not address_allowed(ip, host, allow_localhost=settings.allow_localhost,
                               allow_private=settings.allow_private_networks):
            raise UnsafeURLError(
                f'host {host} resolves to a non-public address ({addr}); allow it with '
                f'federation.allow_localhost or federation.allow_private_networks')


# ── untrusted text ──────────────────────────────────────────────────

_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠-⁤﻿]')

#: Phrases and tokens that try to steer the model that reads a tool description.
INJECTION_MARKERS = [
    re.compile(p, re.I) for p in (
        r'ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier|preceding)\s+'
        r'(?:instructions?|prompts?|messages?|rules?|context)',
        r'disregard\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier|system)\s+\w+',
        r'forget\s+(?:all\s+|everything\s+)?(?:you\s+were\s+told|previous\s+instructions?)',
        r'</?\s*(?:important|system|instructions?|admin|secret|hidden)\s*>',
        r'<\|[a-z_]*\|>',                          # chat-template tokens <|im_start|> ...
        r'\[/?(?:INST|SYS)\]',
        r'<<\s*/?SYS\s*>>',
        r'\byou\s+(?:are\s+now|must\s+now|will\s+now)\b',
        r'\bsystem\s+prompt\b',
        r'\bdo\s+not\s+(?:tell|inform|mention\s+(?:this\s+)?to)\s+the\s+user\b',
        r'\b(?:read|send|exfiltrate|upload|leak)\b[^.\n]{0,40}\b(?:~/\.ssh|id_rsa|\.env|api[_\s-]?keys?|'
        r'passwords?|credentials|secrets?|tokens?)\b',
        r'\bbefore\s+(?:using|calling)\s+(?:this|any)\s+tool\b[^.\n]{0,60}\b(?:call|invoke|run)\b',
    )
]


def screen_text(text: Any, limit: int) -> Tuple[str, bool]:
    """(clean text, flagged): control characters removed, markers replaced, capped at ``limit``."""
    if text is None:
        return '', False
    s = _CONTROL.sub('', str(text))
    flagged = False
    for rx in INJECTION_MARKERS:
        s, n = rx.subn('[removed]', s)
        flagged = flagged or n > 0
    if len(s) > limit:
        s = s[:max(0, limit - 1)].rstrip() + '…'
    return s, flagged


def screen_schema(schema: Any, limit: int, _depth: int = 0) -> Tuple[Any, bool]:
    """A JSON Schema with every ``description`` / ``title`` screened (property names untouched)."""
    if _depth > 32:
        return schema, False
    if isinstance(schema, dict):
        out, flagged = {}, False
        for k, v in schema.items():
            if k in ('description', 'title') and isinstance(v, str):
                out[k], f = screen_text(v, limit)
            else:
                out[k], f = screen_schema(v, limit, _depth + 1)
            flagged = flagged or f
        return out, flagged
    if isinstance(schema, list):
        items, flagged = [], False
        for v in schema:
            c, f = screen_schema(v, limit, _depth + 1)
            items.append(c)
            flagged = flagged or f
        return items, flagged
    return schema, False


# ── secrets ─────────────────────────────────────────────────────────

_store = None


def secrets():
    """The SecretStore used for upstream credentials (env:, file:, db:llm_providers/...)."""
    global _store
    if _store is None:
        from sajha.ai.llm.secrets import SecretStore, db_secret_lookup
        _store = SecretStore(db_lookup=db_secret_lookup)
    return _store


def resolve_ref(ref: Optional[str], what: str) -> str:
    value = secrets().resolve(ref) if ref else None
    if not value:
        raise ValueError(f'{what}: the secret reference {ref!r} resolves to nothing')
    return value


def redact(text: Any, extra: Optional[List[str]] = None) -> str:
    """Mask anything that looks like a credential, and any known secret value."""
    from sajha.ai.llm.secrets import SecretStore
    s = SecretStore.redact(str(text or ''))
    for value in extra or ():
        if value and len(value) >= 4:
            s = s.replace(value, '********')
    return s
