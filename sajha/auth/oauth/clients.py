"""
SAJHA MCP Server — OAuth clients of the built-in authorization server.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Three registration mechanisms, in the MCP order of preference:

* Client ID Metadata Documents (CIMD, draft-ietf-oauth-client-id-metadata-document):
  the client_id is an https URL; its JSON metadata is fetched (SSRF-guarded),
  validated and cached.  CIMD clients are public (token_endpoint_auth_method "none").
* Pre-registered clients: ``mcp.auth.builtin.clients`` in application.yml.
* Dynamic Client Registration (RFC 7591) — deprecated in MCP 2026-07-28 and off
  unless ``mcp.auth.builtin.dynamic_client_registration: true``; registrations
  live in memory.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

from sajha.auth.oauth import settings

logger = logging.getLogger(__name__)

AUTH_METHODS = ('none', 'client_secret_basic', 'client_secret_post')
_LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1', '[::1]')
_FORBIDDEN_SCHEMES = ('javascript', 'data', 'file', 'vbscript', 'about', 'blob', 'filesystem', 'ftp', 'ws', 'wss')
_MAX_DCR_CLIENTS = 1000
_MAX_CIMD_CACHE = 1000


class ClientError(Exception):
    """The client_id cannot be used (unknown, unreachable or invalid metadata)."""


@dataclass
class OAuthClient:
    client_id: str
    redirect_uris: List[str]
    auth_method: str = 'none'
    source: str = 'static'               # static | cimd | dcr
    name: Optional[str] = None
    client_uri: Optional[str] = None
    secret_sha256: Optional[str] = field(default=None, repr=False)

    @property
    def is_public(self) -> bool:
        return self.auth_method == 'none'

    def check_secret(self, secret: Optional[str]) -> bool:
        if self.is_public or not self.secret_sha256 or not secret:
            return False
        return hmac.compare_digest(hashlib.sha256(secret.encode()).hexdigest(), self.secret_sha256)

    def display_host(self) -> str:
        if self.source == 'cimd':
            return urlsplit(self.client_id).netloc
        return ''


def validate_redirect_uri(uri: str) -> Optional[str]:
    """A reason the redirect URI is unacceptable, else None."""
    if not isinstance(uri, str) or not uri or len(uri) > 2000:
        return 'redirect_uri must be a non-empty string'
    try:
        p = urlsplit(uri)
    except ValueError:
        return 'redirect_uri is not a valid URI'
    scheme = p.scheme.lower()
    if not scheme:
        return 'redirect_uri must be absolute'
    if p.fragment or '#' in uri:
        return 'redirect_uri must not contain a fragment'
    if scheme in _FORBIDDEN_SCHEMES:
        return f'redirect_uri scheme {scheme!r} is not allowed'
    if scheme == 'https':
        return None if p.hostname else 'redirect_uri has no host'
    if scheme == 'http':
        # OAuth 2.1 / RFC 8252: plain http only for loopback redirects
        return None if (p.hostname or '').lower() in _LOOPBACK_HOSTS else \
            'http redirect_uri is only allowed for localhost / loopback'
    # Private-use URI scheme for native apps (RFC 8252 7.1): reverse-domain name
    if '.' not in scheme:
        return 'custom redirect_uri schemes must be reverse-domain names (e.g. com.example.app)'
    return None


def is_url_client_id(client_id: str) -> bool:
    return isinstance(client_id, str) and client_id.lower().startswith(('https://', 'http://'))


def _static_clients() -> Dict[str, OAuthClient]:
    out: Dict[str, OAuthClient] = {}
    for entry in settings.static_clients():
        redirect_uris = [u for u in (entry.get('redirect_uris') or []) if isinstance(u, str)]
        bad = [u for u in redirect_uris if validate_redirect_uri(u)]
        if bad or not redirect_uris:
            logger.warning(f"OAuth client {entry['client_id']!r}: invalid or missing redirect_uris {bad}; ignored")
            continue
        secret = entry.get('client_secret') or None
        secret_hash = entry.get('client_secret_sha256') or (hashlib.sha256(secret.encode()).hexdigest()
                                                            if secret else None)
        method = entry.get('token_endpoint_auth_method') or ('client_secret_basic' if secret_hash else 'none')
        if method not in AUTH_METHODS or (method != 'none' and not secret_hash):
            logger.warning(f"OAuth client {entry['client_id']!r}: unsupported auth method {method!r}; ignored")
            continue
        out[entry['client_id']] = OAuthClient(
            client_id=entry['client_id'], redirect_uris=redirect_uris, auth_method=method, source='static',
            name=entry.get('client_name'), client_uri=entry.get('client_uri'), secret_sha256=secret_hash)
    return out


# ── CIMD fetch (SSRF-guarded) ──────────────────────────────────────

def check_cimd_url(url: str) -> Optional[str]:
    """Syntactic checks on a URL client_id; a reason string when unacceptable."""
    try:
        p = urlsplit(url)
    except ValueError:
        return 'client_id is not a valid URL'
    host = (p.hostname or '').lower()
    if p.username or p.password or '@' in p.netloc:
        return 'client_id URL must not contain credentials'
    if p.fragment or '#' in url:
        return 'client_id URL must not contain a fragment'
    if p.scheme == 'https':
        pass
    elif p.scheme == 'http' and settings.cimd_allow_localhost() and host in _LOOPBACK_HOSTS:
        pass
    else:
        return 'client_id URL must use https'
    if not host:
        return 'client_id URL has no host'
    if not p.path or p.path == '/':
        return 'client_id URL must have a path component'
    segments = p.path.split('/')
    if '.' in segments or '..' in segments:
        return 'client_id URL must not contain dot segments'
    try:
        p.port
    except ValueError:
        return 'client_id URL has an invalid port'
    return None


_NAT64 = ipaddress.ip_network('64:ff9b::/96')


def _ip_allowed(ip, host: str) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        # Addresses that embed an IPv4 target are judged by that target
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is None and ip in _NAT64:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if embedded is not None:
            ip = embedded
    if ip.is_loopback:
        return settings.cimd_allow_localhost() and host in _LOOPBACK_HOSTS
    if ip.is_global and not ip.is_multicast and not ip.is_reserved:
        return True
    return settings.cimd_allow_private_networks() and ip.is_private and not ip.is_link_local \
        and not ip.is_unspecified and not ip.is_multicast


async def _resolve_pinned(host: str, port: int) -> str:
    """Resolve once and vet every address (no DNS-rebinding window): returns the IP to connect to."""
    try:
        literal = ipaddress.ip_address(host.strip('[]'))
        infos = [str(literal)]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            res = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
                                         timeout=settings.cimd_timeout_seconds())
        except (OSError, asyncio.TimeoutError) as e:
            raise ClientError(f'client_id host does not resolve: {e}')
        infos = [r[4][0] for r in res]
    if not infos:
        raise ClientError('client_id host does not resolve')
    for addr in infos:
        if not _ip_allowed(ipaddress.ip_address(addr.split('%')[0]), host):
            raise ClientError('client_id host resolves to a non-public address')
    return infos[0]


async def fetch_cimd(url: str) -> Dict:
    """GET the metadata document: pinned IP, no redirects, no proxies, total timeout and size cap."""
    try:
        return await asyncio.wait_for(_fetch_cimd(url), timeout=settings.cimd_timeout_seconds() * 2)
    except asyncio.TimeoutError:
        raise ClientError('client metadata fetch timed out')


async def _fetch_cimd(url: str) -> Dict:
    import httpx
    reason = check_cimd_url(url)
    if reason:
        raise ClientError(reason)
    p = urlsplit(url)
    host = p.hostname.lower()
    port = p.port or (443 if p.scheme == 'https' else 80)
    ip = await _resolve_pinned(host, port)
    ip_host = f'[{ip}]' if ':' in ip else ip
    pinned = urlunsplit((p.scheme, f'{ip_host}:{port}', p.path, p.query, ''))
    host_header = p.netloc.rsplit('@', 1)[-1]
    limit = settings.cimd_max_bytes()
    timeout = settings.cimd_timeout_seconds()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', pinned, headers={'Host': host_header, 'Accept': 'application/json'},
                                     extensions={'sni_hostname': host}) as resp:
                if resp.status_code != 200:
                    raise ClientError(f'client metadata fetch returned HTTP {resp.status_code}')
                ctype = resp.headers.get('content-type', '').split(';')[0].strip().lower()
                if ctype != 'application/json' and not ctype.endswith('+json'):
                    raise ClientError('client metadata must be served as application/json')
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise ClientError(f'client metadata document exceeds {limit} bytes')
                cache_control = resp.headers.get('cache-control', '')
    except httpx.HTTPError as e:
        raise ClientError(f'client metadata fetch failed: {type(e).__name__}')
    try:
        doc = json.loads(bytes(body))
    except ValueError:
        raise ClientError('client metadata is not valid JSON')
    if not isinstance(doc, dict):
        raise ClientError('client metadata must be a JSON object')
    doc['_max_age'] = _max_age(cache_control)
    return doc


def _max_age(cache_control: str) -> int:
    m = re.search(r'max-age=(\d+)', cache_control or '')
    if 'no-store' in (cache_control or '') or 'no-cache' in (cache_control or ''):
        return 60
    return min(86400, max(60, int(m.group(1)))) if m else 300


def client_from_cimd(url: str, doc: Dict) -> OAuthClient:
    if doc.get('client_id') != url:
        raise ClientError('client metadata client_id does not match the client_id URL')
    redirect_uris = doc.get('redirect_uris')
    if not isinstance(redirect_uris, list) or not redirect_uris or \
            not all(isinstance(u, str) for u in redirect_uris):
        raise ClientError('client metadata must list redirect_uris')
    for u in redirect_uris:
        reason = validate_redirect_uri(u)
        if reason:
            raise ClientError(f'client metadata: {reason}')
    method = doc.get('token_endpoint_auth_method', 'none')
    if method != 'none':
        raise ClientError(f'token_endpoint_auth_method {method!r} is not supported for URL client_ids '
                          '(shared secrets cannot be used with Client ID Metadata Documents)')
    if 'client_secret' in doc or 'client_secret_expires_at' in doc:
        raise ClientError('client metadata must not contain a client_secret')
    grant_types = doc.get('grant_types')
    if grant_types is not None and (not isinstance(grant_types, list) or 'authorization_code' not in grant_types):
        raise ClientError('client metadata grant_types must include authorization_code')
    name = doc.get('client_name') if isinstance(doc.get('client_name'), str) else None
    client_uri = doc.get('client_uri') if isinstance(doc.get('client_uri'), str) else None
    return OAuthClient(client_id=url, redirect_uris=list(redirect_uris), auth_method='none', source='cimd',
                       name=(name or '')[:100] or None, client_uri=client_uri)


class ClientRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._dcr: Dict[str, OAuthClient] = {}
        self._cimd: Dict[str, tuple] = {}     # url -> (client, expires_at)

    def local_client(self, client_id: str) -> Optional[OAuthClient]:
        """A pre-registered or dynamically registered client (no network)."""
        static = _static_clients().get(client_id)
        if static:
            return static
        with self._lock:
            return self._dcr.get(client_id)

    async def resolve(self, client_id: str) -> OAuthClient:
        if not isinstance(client_id, str) or not client_id or len(client_id) > 2000:
            raise ClientError('client_id is required')
        local = self.local_client(client_id)
        if local:
            return local
        if not is_url_client_id(client_id):
            raise ClientError('unknown client_id')
        if not settings.cimd_enabled():
            raise ClientError('URL client_ids (Client ID Metadata Documents) are disabled')
        now = time.time()
        with self._lock:
            cached = self._cimd.get(client_id)
        if cached and cached[1] > now:
            return cached[0]
        doc = await fetch_cimd(client_id)
        client = client_from_cimd(client_id, doc)
        with self._lock:
            if len(self._cimd) >= _MAX_CIMD_CACHE:
                self._cimd = {k: v for k, v in self._cimd.items() if v[1] > now}
                if len(self._cimd) >= _MAX_CIMD_CACHE:
                    self._cimd.pop(next(iter(self._cimd)))
            self._cimd[client_id] = (client, now + doc.get('_max_age', 300))
        return client

    def register(self, metadata: Dict) -> Dict:
        """RFC 7591 registration; returns the client information response (raises ClientError)."""
        if not isinstance(metadata, dict):
            raise ClientError('registration body must be a JSON object')
        redirect_uris = metadata.get('redirect_uris')
        if not isinstance(redirect_uris, list) or not redirect_uris or \
                not all(isinstance(u, str) for u in redirect_uris):
            raise ClientError('redirect_uris is required')
        for u in redirect_uris:
            reason = validate_redirect_uri(u)
            if reason:
                raise ClientError(reason)
        method = metadata.get('token_endpoint_auth_method', 'client_secret_basic')
        if method not in AUTH_METHODS:
            raise ClientError(f'unsupported token_endpoint_auth_method {method!r}')
        grant_types = metadata.get('grant_types') or ['authorization_code']
        if not isinstance(grant_types, list) or \
                any(g not in ('authorization_code', 'refresh_token') for g in grant_types):
            raise ClientError('grant_types may contain only authorization_code and refresh_token')
        response_types = metadata.get('response_types') or ['code']
        if response_types != ['code']:
            raise ClientError('response_types must be ["code"]')
        client_id = 'dcr_' + secrets.token_urlsafe(18)
        secret = None if method == 'none' else secrets.token_urlsafe(32)
        name = metadata.get('client_name') if isinstance(metadata.get('client_name'), str) else None
        client = OAuthClient(client_id=client_id, redirect_uris=list(redirect_uris), auth_method=method,
                             source='dcr', name=(name or '')[:100] or None,
                             secret_sha256=hashlib.sha256(secret.encode()).hexdigest() if secret else None)
        with self._lock:
            if len(self._dcr) >= _MAX_DCR_CLIENTS:
                raise ClientError('too many registered clients')
            self._dcr[client_id] = client
        info = {
            'client_id': client_id,
            'client_id_issued_at': int(time.time()),
            'redirect_uris': client.redirect_uris,
            'token_endpoint_auth_method': method,
            'grant_types': grant_types,
            'response_types': ['code'],
        }
        if name:
            info['client_name'] = client.name
        if isinstance(metadata.get('scope'), str):
            info['scope'] = metadata['scope']
        if secret:
            info['client_secret'] = secret
            info['client_secret_expires_at'] = 0
        return info


_registry: Optional[ClientRegistry] = None
_registry_lock = threading.Lock()


def get_client_registry() -> ClientRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ClientRegistry()
        return _registry
