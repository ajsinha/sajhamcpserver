"""
SAJHA MCP Server — the outbound fetch guard for tools that fetch a URL someone else chose.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The web crawler tools fetch the URL their caller names, and a Studio REST tool calls the
endpoint its author typed. Both go through :func:`request`, which refuses a destination
whose host resolves to:

* a cloud metadata or link-local address (169.254.169.254, fd00:ec2::254, 100.100.100.200,
  ``metadata.google.internal``, 169.254.0.0/16, fe80::/10): always;
* loopback or the unspecified address (127.0.0.0/8, ::1, ``localhost``, 0.0.0.0/8, ::): always;
* multicast and reserved addresses: always;
* private ranges (10/8, 172.16/12, 192.168/16, fc00::/7 and CGNAT 100.64/10): only when
  ``tools.outbound.block_private_networks`` is true (off by default: intranet hosts are the
  usual targets of a deployment on an intranet).

``tools.outbound.exempt_hosts`` lists host patterns (fnmatch) and CIDRs that are never refused,
for an operator who really wants, say, a service on localhost. Every address a host name
resolves to is checked (an IP literal in any form inet_aton accepts, decimal or octal or hex,
and IPv6 forms that embed an IPv4 target, are normalised by ``ipaddress`` first), the
connection is pinned to the checked address, and each redirect hop is checked again. The
per-address rule is ``address_allowed`` (sajha/auth/oauth/clients.py), shared with federation,
API Import, OAuth CIMD and webhooks; the pinned client is API Import's (sajha/api_import/fetch.py).

``tools.outbound.proxy`` (explicit; HTTP_PROXY / HTTPS_PROXY are never read) sends these fetches
through an HTTP proxy, except hosts matching ``tools.outbound.no_proxy``. The same names and
addresses are refused through it; a host that does not resolve locally is left to the proxy;
the connection is not pinned (the proxy connects). The proxy URL may carry credentials and is
shown only masked.
"""

from __future__ import annotations

import fnmatch
import ipaddress
import json as _json
import logging
import re
import socket
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

BLOCK_PRIVATE_KEY = 'tools.outbound.block_private_networks'
EXEMPT_KEY = 'tools.outbound.exempt_hosts'
PROXY_KEY = 'tools.outbound.proxy'
NO_PROXY_KEY = 'tools.outbound.no_proxy'

METADATA_ADDRESSES = frozenset(ipaddress.ip_address(a) for a in (
    '169.254.169.254',      # AWS, Azure, GCP, OpenStack, Oracle
    'fd00:ec2::254',        # AWS IPv6
    '100.100.100.200',      # Alibaba Cloud (inside CGNAT, which is otherwise allowed by default)
))
METADATA_HOSTS = ('metadata.google.internal',)
_CGNAT = ipaddress.ip_network('100.64.0.0/10')
_THIS_NETWORK = ipaddress.ip_network('0.0.0.0/8')
_NUMERIC_HOST = re.compile(r'^[0-9a-fA-FxX.]+$')


class Refused(ValueError):
    """The destination is not allowed. A tool error for its caller, not a server fault."""
    caller_specific = True          # a caller's bad URL does not open the tool's circuit breaker
    quiet_failure = True            # logged at warning, without a stack trace


class FetchError(ValueError):
    """The request could not be made or its answer could not be read."""


class FetchTimeout(FetchError):
    pass


# ── settings (read live, so SAJHA_TOOLS_OUTBOUND_* overrides apply without a restart) ──

def block_private_networks() -> bool:
    from sajha.core.config import _bool
    return _bool(BLOCK_PRIVATE_KEY, False)


def exempt_entries() -> Tuple[List[str], List[Any]]:
    """``tools.outbound.exempt_hosts`` split into (host patterns, networks)."""
    return _patterns_and_networks(EXEMPT_KEY)


def _patterns_and_networks(key: str) -> Tuple[List[str], List[Any]]:
    from sajha.core.config import _list
    patterns, networks = [], []
    for raw in _list(key, []):
        entry = str(raw).strip().lower()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry.strip('[]'), strict=False))
        except ValueError:
            patterns.append(entry.rstrip('.'))
    return patterns, networks


def proxy_url() -> str:
    """``tools.outbound.proxy``: the proxy for guarded fetches ('' = direct). Explicit only:
    HTTP_PROXY / HTTPS_PROXY are never read. May carry credentials: never log it, use mask_proxy."""
    from sajha.core.config import _get
    return (_get(PROXY_KEY, '') or '').strip()


def no_proxy_entries() -> Tuple[List[str], List[Any]]:
    """``tools.outbound.no_proxy`` split into (host patterns, networks)."""
    return _patterns_and_networks(NO_PROXY_KEY)


def mask_proxy(proxy: str) -> str:
    """The proxy URL without its credentials (``http://***@proxy:3128``)."""
    try:
        p = urlsplit(proxy or '')
        hostport = p.netloc.rsplit('@', 1)[-1]
        return urlunsplit((p.scheme, ('***@' if '@' in p.netloc else '') + hostport, '', '', ''))
    except ValueError:
        return '<proxy>'


def _scrub(message: str, proxy: str) -> str:
    """``message`` with any trace of the proxy's credentials replaced."""
    if not proxy:
        return message
    from urllib.parse import unquote
    out = message.replace(proxy, mask_proxy(proxy))
    try:
        p = urlsplit(proxy)
        secrets = [x for x in (p.netloc.rsplit('@', 1)[0] if '@' in p.netloc else '', p.password or '',
                               unquote(p.password or '')) if x]
    except ValueError:
        secrets = []
    for x in sorted(set(secrets), key=len, reverse=True):
        out = out.replace(x, '***')
    return out


def _checked_proxy() -> str:
    proxy = proxy_url()
    if not proxy:
        return ''
    try:
        p = urlsplit(proxy)
        ok = p.scheme in ('http', 'https') and bool(p.hostname)
        p.port
    except ValueError:
        ok = False
    if not ok:
        raise FetchError(f'{PROXY_KEY} is not an http:// or https:// proxy URL ({mask_proxy(proxy)})')
    return proxy


# ── the rule ──────────────────────────────────────────────────────────

def blocked_reason(ip, block_private: Optional[bool] = None) -> Optional[str]:
    """Why one address is refused ('cloud metadata', 'loopback', 'private', 'reserved'), or None."""
    from sajha.auth.oauth.clients import address_allowed, effective_address
    if block_private is None:
        block_private = block_private_networks()
    ip = effective_address(ipaddress.ip_address(ip) if isinstance(ip, str) else ip)
    if ip in METADATA_ADDRESSES or ip.is_link_local:
        return 'cloud metadata'
    if ip.is_loopback or ip.is_unspecified or (ip.version == 4 and ip in _THIS_NETWORK):
        return 'loopback'
    if not block_private and ip.version == 4 and ip in _CGNAT:
        return None
    if address_allowed(ip, '', allow_localhost=False, allow_private=not block_private):
        return None
    if block_private and (ip.is_private or (ip.version == 4 and ip in _CGNAT)) \
            and not ip.is_multicast and not ip.is_reserved:
        return 'private'
    return 'reserved'


def literal_address(host: str):
    """``host`` as an address when it is an IP literal in any form, else None."""
    h = host.strip('[]')
    try:
        return ipaddress.ip_address(h.split('%')[0])
    except ValueError:
        pass
    if _NUMERIC_HOST.match(h):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(h))   # decimal, octal, hex, short forms
        except OSError:
            return None
    return None


def resolve(host: str, port: int) -> List[str]:
    """Every address ``host`` resolves to."""
    lit = literal_address(host)
    if lit is not None:
        return [str(lit)]
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as e:
        raise FetchError(f'host {host} does not resolve ({e.__class__.__name__})')
    addrs = sorted({r[4][0].split('%')[0] for r in infos})
    if not addrs:
        raise FetchError(f'host {host} does not resolve')
    return addrs


def safe_url(url: str) -> str:
    """``url`` without credentials, query string or fragment (for messages and logs)."""
    try:
        p = urlsplit(url or '')
        netloc = p.netloc.rsplit('@', 1)[-1]
        return urlunsplit((p.scheme, netloc, p.path, '', ''))
    except ValueError:
        return '<unparseable URL>'


def _refuse(url: str, what: str) -> Refused:
    shown = safe_url(url)
    logger.warning(f'outbound fetch refused: {shown} ({what})')
    see = f'; see {BLOCK_PRIVATE_KEY} and {EXEMPT_KEY}' if 'blocked address' in what else ''
    return Refused(f'refused: {shown} {what}{see}')


def vet(url: str) -> Tuple[str, int, Optional[str]]:
    """Check one destination; returns (host, port, address to connect to), the address None when
    the request goes through ``tools.outbound.proxy``. Raises Refused or FetchError.

    Through the proxy the same names and addresses are refused; a host that does not resolve
    here is left to the proxy to resolve (an intranet resolver often cannot answer internet
    names), and the connection cannot be pinned (the proxy connects)."""
    try:
        p = urlsplit(url or '')
        port = p.port
    except ValueError:
        raise _refuse(url, 'cannot be parsed')
    if p.scheme not in ('http', 'https'):
        raise _refuse(url, 'is not an http or https URL')
    if p.username or p.password or '@' in p.netloc:
        raise _refuse(url, 'carries credentials in the URL')
    host = (p.hostname or '').lower().rstrip('.')
    if not host:
        raise _refuse(url, 'has no host')
    port = port or (443 if p.scheme == 'https' else 80)
    patterns, networks = exempt_entries()
    exempt_host = any(fnmatch.fnmatchcase(host, pat) for pat in patterns)
    if not exempt_host:
        if host in METADATA_HOSTS:
            raise _refuse(url, 'resolves to a blocked address (cloud metadata)')
        if host == 'localhost' or host.endswith('.localhost'):
            raise _refuse(url, 'resolves to a blocked address (loopback)')
    proxy = _checked_proxy()
    if proxy:
        np_patterns, np_networks = no_proxy_entries()
        if any(fnmatch.fnmatchcase(host, pat) for pat in np_patterns):
            proxy = ''
    try:
        addrs = resolve(host, port)
    except FetchError:
        if proxy:
            return host, port, None         # the proxy resolves it
        raise
    if not exempt_host:
        block_private = block_private_networks()
        for addr in addrs:
            ip = ipaddress.ip_address(addr)
            if any(ip.version == n.version and ip in n for n in networks):
                continue
            reason = blocked_reason(ip, block_private)
            if reason:
                raise _refuse(url, f'resolves to a blocked address ({reason})')
    if proxy and np_networks and all(
            any(ipaddress.ip_address(a).version == n.version and ipaddress.ip_address(a) in n
                for n in np_networks) for a in addrs):
        proxy = ''
    return host, port, (None if proxy else addrs[0])


# ── the request ───────────────────────────────────────────────────────

class _Headers(dict):
    """Response headers, looked up case-insensitively."""

    def __init__(self, items: Dict[str, str]):
        super().__init__({str(k).lower(): v for k, v in (items or {}).items()})

    def __getitem__(self, key):
        return super().__getitem__(str(key).lower())

    def __contains__(self, key):
        return super().__contains__(str(key).lower())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class Response:
    """What :func:`request` returns: the parts of a ``requests.Response`` the tools use."""

    def __init__(self, status_code: int, reason: str, headers: Dict[str, str], content: bytes, url: str):
        self.status_code, self.reason, self.headers, self.content, self.url = \
            status_code, reason, _Headers(headers), content, url

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode('utf-8', errors='replace')

    def json(self) -> Any:
        return _json.loads(self.content.decode('utf-8'))

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPStatusError(f'HTTP {self.status_code} {self.reason}'.rstrip(), self)


class HTTPStatusError(FetchError):
    def __init__(self, message: str, response: Response):
        super().__init__(message)
        self.response = response


def _param_items(params) -> List[Tuple[str, str]]:
    if not params:
        return []
    items = params.items() if isinstance(params, dict) else params
    out = []
    for k, v in items:
        for one in (v if isinstance(v, (list, tuple)) else [v]):
            if one is not None:
                out.append((str(k), str(one)))
    return out


def request(method: str, url: str, *, params=None, headers: Optional[Dict[str, str]] = None,
            json: Any = None, data: Optional[bytes] = None, auth: Optional[Tuple[str, str]] = None,
            timeout: float = 30.0, max_bytes: int = 10 * 1024 * 1024) -> Response:
    """One guarded request (redirects followed for GET/HEAD, each hop checked).
    Raises Refused, FetchTimeout or FetchError."""
    from sajha.api_import import fetch
    vet(url)                                # refuse before anything else touches the URL
    proxy = proxy_url()
    send = dict(headers or {})
    if auth:
        import base64
        token = base64.b64encode(f'{auth[0]}:{auth[1]}'.encode('utf-8')).decode('ascii')
        send['Authorization'] = f'Basic {token}'
    content = data
    if json is not None:
        content = _json.dumps(json).encode('utf-8')
        if not any(k.lower() == 'content-type' for k in send):
            send['Content-Type'] = 'application/json'
    try:
        r = fetch.request(method, url, params=_param_items(params), headers=send, content=content,
                          timeout=float(timeout), max_bytes=max_bytes, vet=vet, proxy=proxy or None)
    except fetch.FetchTimeout as e:
        raise FetchTimeout(_scrub(str(e), proxy))
    except fetch.FetchError as e:
        raise FetchError(_scrub(str(e), proxy))
    except Refused:
        raise
    except Exception as e:                  # an httpx URL error and the like: a message, not a trace
        raise FetchError(_scrub(f'request failed: {e.__class__.__name__}: {e}', proxy))
    return Response(r.status, r.reason, r.headers, r.content, r.url)
