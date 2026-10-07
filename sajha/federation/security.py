"""
SAJHA MCP Server — federation security: the URL guard, untrusted-text screening, secrets.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* ``check_url``: an upstream (or OAuth token) URL must be http(s) without credentials, its
  host must match ``federation.allowed_hosts`` when set, and every address it resolves to
  must pass ``address_allowed`` (the SSRF guard shared with CIMD fetches and webhooks).
* ``screen_text`` / ``screen_schema``: upstream names, titles and descriptions are what an
  LLM reads when it picks a tool, so they are treated as untrusted input: control
  characters stripped, length capped, injection markers replaced and flagged.
* ``check_peer_url``: a SAJHA Net peer's URL. Peers usually sit on private networks, so
  private addresses are allowed when inside ``sajhanet.allowed_networks`` (CIDRs), a list of
  its own, separate from ``federation.allow_private_networks``; loopback, link-local,
  unspecified and multicast addresses are refused whatever the list says.
* ``correct_annotations``: an imported tool's annotations, corrected and never widened: only
  the MCP hints with boolean values are kept, and ``openWorldHint`` is always true (the tool
  runs on another server).
* ``schema_problem``: an imported input or output schema that is not a valid JSON Schema
  (2020-12) object schema is refused with the reason.
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


# ── SAJHA Net peer URLs ─────────────────────────────────────────────

def net_allowed_networks() -> List[Any]:
    """``sajhanet.allowed_networks`` as ip_network objects (an invalid entry is skipped and logged)."""
    import logging
    from sajha.core.config import _list
    out = []
    for raw in _list('sajhanet.allowed_networks', []):
        try:
            out.append(ipaddress.ip_network(raw.strip(), strict=False))
        except ValueError:
            logging.getLogger(__name__).warning(f'sajhanet.allowed_networks: {raw!r} is not a CIDR; ignored')
    return out


def net_address_allowed(ip, networks) -> bool:
    """One resolved address of a peer: never loopback, link-local, unspecified, multicast or
    reserved; a public address always; any other (private, CGNAT, ULA) only inside ``networks``."""
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is not None:
            ip = embedded
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return False
    if ip.is_global:
        return True
    return any(ip.version == n.version and ip in n for n in networks or ())


def check_peer_url(url: str, networks=None, resolve: bool = True, require_https: bool = False) -> Tuple[str, int]:
    """Validate a SAJHA Net peer's base URL; returns (host, port). Raises UnsafeURLError.
    ``networks``: the allowlist (default ``sajhanet.allowed_networks``)."""
    try:
        p = urlsplit(url or '')
    except ValueError:
        raise UnsafeURLError('the URL cannot be parsed')
    if p.scheme not in (('https',) if require_https else ('http', 'https')):
        raise UnsafeURLError('the peer URL must use https' if require_https else 'the URL must use http or https')
    if p.username or p.password or '@' in p.netloc:
        raise UnsafeURLError('the URL must not contain credentials')
    host = (p.hostname or '').lower().rstrip('.')
    if not host:
        raise UnsafeURLError('the URL has no host')
    try:
        port = p.port or (443 if p.scheme == 'https' else 80)
    except ValueError:
        raise UnsafeURLError('the URL has an invalid port')
    if not resolve:
        return host, port
    nets = net_allowed_networks() if networks is None else [
        n if isinstance(n, (ipaddress.IPv4Network, ipaddress.IPv6Network)) else ipaddress.ip_network(n, strict=False)
        for n in networks]
    for addr in _resolve(host, port):
        ip = ipaddress.ip_address(addr.split('%')[0])
        if not net_address_allowed(ip, nets):
            raise UnsafeURLError(
                f'host {host} resolves to {addr}, which is not a public address and not in '
                f'sajhanet.allowed_networks (loopback and link-local are never allowed)')
    return host, port


def _resolve(host: str, port: int) -> List[str]:
    try:
        return [str(ipaddress.ip_address(host.strip('[]')))]
    except ValueError:
        pass
    try:
        addrs = sorted({r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    except OSError as e:
        raise UnsafeURLError(f'host {host} does not resolve ({e.__class__.__name__})')
    if not addrs:
        raise UnsafeURLError(f'host {host} does not resolve')
    return addrs


# ── annotations and schemas of imported tools ───────────────────────

_HINTS = ('readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint')


def correct_annotations(raw: Any) -> Dict[str, Any]:
    """Annotations for an imported tool, corrected and never widened: a hint is kept only when
    it is a boolean (anything else falls back to the MCP default, which is the cautious one),
    ``destructiveHint`` is dropped when the tool claims to be read-only (it is meaningless
    then), unknown keys are dropped, and ``openWorldHint`` is always true. ``title`` is kept
    as text; the caller screens it."""
    src = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {}
    if isinstance(src.get('title'), str) and src['title']:
        out['title'] = src['title']
    for hint in _HINTS:
        if isinstance(src.get(hint), bool):
            out[hint] = src[hint]
    if out.get('readOnlyHint') is True:
        out.pop('destructiveHint', None)
    out['openWorldHint'] = True
    return out


def schema_problem(schema: Any, what: str = 'inputSchema', required: bool = True) -> Optional[str]:
    """Why ``schema`` cannot be an imported tool's ``what``, or None when it can: it must be a
    valid JSON Schema (2020-12 unless it names another dialect in ``$schema``) whose type is
    ``object``. ``required=False``: an absent schema (None or ``{}``) is fine."""
    if schema is None or schema == {}:
        return None if not required else f'{what} is missing'
    if not isinstance(schema, dict):
        return f'{what} is not a JSON object'
    if schema.get('type') != 'object':
        return f'{what} must have "type": "object"'
    try:
        import jsonschema
        cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
        cls.check_schema(schema)
    except ImportError:          # jsonschema is a declared dependency; never skip silently
        return f'{what} cannot be checked (jsonschema is not installed)'
    except Exception as e:       # SchemaError, or a $schema naming an unknown dialect
        msg = getattr(e, 'message', None) or str(e)
        path = '/'.join(str(p) for p in getattr(e, 'path', ()) or ())
        return f'{what} is not a valid JSON Schema' + (f' at {path}' if path else '') + f': {msg}'[:300]
    return None


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
