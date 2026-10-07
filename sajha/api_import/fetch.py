"""
SAJHA MCP Server — API Import: the SSRF-guarded HTTP client.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Every request API Import makes goes through :func:`request`: the spec URL, remote
``$ref`` documents, GraphQL introspection, OAuth token URLs and every call an imported
tool makes. The URL must be http(s) without credentials, its host must match
``api_import.allowed_hosts`` when that is set, and every address it resolves to must pass
``address_allowed`` (sajha/auth/oauth/clients.py, the guard shared with CIMD fetches,
webhooks and federation). The connection is pinned to the vetted address, TLS verifies
the real host name (SNI), environment proxies are not used, and a redirect is followed
only for GET/HEAD after the new URL passes the guard again.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from sajha.api_import import settings

MAX_REDIRECTS = 3


class UnsafeURLError(ValueError):
    """The URL is not an allowed API Import destination."""


class FetchError(ValueError):
    """The request could not be made or its answer could not be read."""


class FetchTimeout(FetchError):
    pass


@dataclass
class Response:
    status: int
    reason: str
    headers: Dict[str, str]
    content: bytes
    url: str
    links: Dict[str, str] = field(default_factory=dict)

    @property
    def content_type(self) -> str:
        return (self.headers.get('content-type') or '').split(';')[0].strip().lower()

    def text(self) -> str:
        return self.content.decode('utf-8', errors='replace')


def check_url(url: str) -> Tuple[str, int]:
    """Syntactic and host-list checks; returns (host, port). Raises UnsafeURLError."""
    try:
        p = urlsplit(url or '')
        port = p.port
    except ValueError:
        raise UnsafeURLError('the URL cannot be parsed')
    if p.scheme not in ('http', 'https'):
        raise UnsafeURLError(f'the URL must use http or https: {url!r}')
    if p.username or p.password or '@' in p.netloc:
        raise UnsafeURLError('the URL must not contain credentials; configure authentication instead')
    host = (p.hostname or '').lower().rstrip('.')
    if not host:
        raise UnsafeURLError('the URL has no host')
    allowed = [h.strip().lower() for h in settings.allowed_hosts() if h.strip()]
    if allowed and not any(fnmatch.fnmatchcase(host, pat) for pat in allowed):
        raise UnsafeURLError(f'host {host} is not in api_import.allowed_hosts')
    return host, port or (443 if p.scheme == 'https' else 80)


def resolve_pinned(host: str, port: int) -> str:
    """Resolve once and vet every address; returns the address to connect to."""
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
        if not address_allowed(ip, host, allow_localhost=settings.allow_localhost(),
                               allow_private=settings.allow_private_networks()):
            raise UnsafeURLError(
                f'host {host} resolves to a non-public address ({addr}); allow it with '
                f'api_import.allow_localhost or api_import.allow_private_networks')
    return addrs[0]


def guard(url: str) -> str:
    """Check ``url`` fully (syntax, host list, resolved addresses); returns the pinned IP."""
    host, port = check_url(url)
    return resolve_pinned(host, port)


def _parse_links(value: str) -> Dict[str, str]:
    out = {}
    for part in (value or '').split(','):
        if ';' not in part:
            continue
        target, _, params = part.partition(';')
        target = target.strip()
        if not (target.startswith('<') and target.endswith('>')):
            continue
        for param in params.split(';'):
            k, _, v = param.strip().partition('=')
            if k.strip().lower() == 'rel':
                for rel in v.strip().strip('"').split():
                    out.setdefault(rel.lower(), target[1:-1])
    return out


def request(method: str, url: str, *, params: Optional[Sequence[Tuple[str, str]]] = None,
            headers: Optional[Dict[str, str]] = None, content: Optional[bytes] = None,
            timeout: float = 30.0, max_bytes: int = 5 * 1024 * 1024,
            follow_redirects: bool = True) -> Response:
    """One guarded request. Raises UnsafeURLError, FetchTimeout or FetchError."""
    method = method.upper()
    target = httpx.URL(url)
    if params:
        target = target.copy_merge_params(list(params))
    hops = 0
    while True:
        current = str(target)
        host, port = check_url(current)
        ip = resolve_pinned(host, port)
        pinned = target.copy_with(host=ip, port=port)
        send_headers = dict(headers or {})
        send_headers['Host'] = target.netloc.decode('ascii')
        from sajha.observability.tracing import inject as _inject_trace
        _inject_trace(send_headers)                 # W3C traceparent of the current call
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
                with client.stream(method, pinned, headers=send_headers, content=content,
                                   extensions={'sni_hostname': host}) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308) and follow_redirects \
                            and method in ('GET', 'HEAD') and resp.headers.get('location'):
                        hops += 1
                        if hops > MAX_REDIRECTS:
                            raise FetchError(f'more than {MAX_REDIRECTS} redirects')
                        target = httpx.URL(urljoin(current, resp.headers['location']))
                        continue
                    body = bytearray()
                    for chunk in resp.iter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise FetchError(f'the response exceeds {max_bytes} bytes')
                    hdrs = {k.lower(): v for k, v in resp.headers.items()}
                    return Response(resp.status_code, resp.reason_phrase or '', hdrs, bytes(body),
                                    current, _parse_links(hdrs.get('link', '')))
        except httpx.TimeoutException:
            raise FetchTimeout(f'timed out after {timeout:g}s')
        except httpx.HTTPError as e:
            raise FetchError(f'request failed: {e.__class__.__name__}: {e}')


def fetch_document(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """GET a spec (or a referenced document); returns (text, final URL)."""
    resp = request('GET', url, headers={'Accept': 'application/json, application/yaml, text/yaml, */*',
                                        **(headers or {})},
                   timeout=float(settings.timeout_seconds()), max_bytes=settings.max_spec_bytes())
    if resp.status < 200 or resp.status >= 300:
        raise FetchError(f'GET {url} answered HTTP {resp.status} {resp.reason}'.rstrip())
    return resp.text(), resp.url


def as_header_items(headers: Dict[str, Any]) -> List[Tuple[str, str]]:
    return [(str(k), str(v)) for k, v in (headers or {}).items()]
