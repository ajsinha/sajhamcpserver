# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Plug-in points of SAJHA Net (design §5.3): one interface per moving part, each with registered
implementations chosen by name or by ``package.module:Class``. Third parties add their own through
the Python entry-point group ``sajha.net.plugins`` (entry-point name ``<kind>.<name>``, or a class
with ``kind`` and ``name`` attributes). Every implementation must pass its contract suite
(:mod:`sajha.net.contract`) before it can be selected; :func:`create` runs a cheap shape check.

=====================  ======================  ===========================================
kind                   interface               shipped here
=====================  ======================  ===========================================
membership             MembershipProvider      gossip, static
admission              AdmissionProvider       open, builtin_ca, manual
connector              PeerConnector           sajha_native (HTTP), in_process (tests, agents)
identity               IdentityResolver        none (api_key, assertion, token_exchange in SAJHA)
catalog_source         CatalogSource           static
key_directory_store    KeyDirectoryStore       memory
rules                  RuleEvaluator           allow_all, deny_all
snapshot_sink          SnapshotSink            local_files
routing                RoutingStrategy         local_first, lowest_latency, pinned
=====================  ======================  ===========================================

The SAJHA implementations that need the rest of SAJHA (the ``api_key``, ``assertion`` and
``token_exchange`` resolvers, the ``native``
catalog source, the ``database`` key directory store, the policy-engine rules) register from
:mod:`sajha.net.integration` as they are built.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import importlib
import logging
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Type

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = 'sajha.net.plugins'


class Plugin:
    kind: str = ''
    name: str = ''


# ── interfaces ──────────────────────────────────────────────────────

class MembershipProvider(Plugin):
    """How participants find each other (design §5.3). ``gossip`` True: the node runs SWIM (§9);
    False: members are the configured static peers, synced every full-sync interval."""
    kind = 'membership'
    gossip: bool = True

    def peers(self, cfg) -> List[str]:
        """Addresses this provider always contacts (static membership)."""
        return []

    def discover(self, cfg) -> List[str]:
        """Addresses to try after the seeds and the saved peers (design §6.6 step 3)."""
        return []


class AdmissionProvider(Plugin):
    """Who may join and how they prove it: builds the net's :class:`~sajha.net.httpsig.Trust` and
    loads (or, in manual mode, creates) this participant's signer."""
    kind = 'admission'
    manual: bool = False

    def trust(self, net: str, cfg, ca_certificate, revocations: Callable[[], Any], pins: Callable[[], List[str]]):
        raise NotImplementedError


@dataclass
class PeerResponse:
    """A peer's answer. A streamed answer (protocol §8.9, an SSE body) has ``stream``, an iterator of
    raw byte chunks, and ``close``, which ends it early (at a host: cancels the call); ``body`` is then
    empty. A connector asked for a stream may still return a whole ``body`` (the peer answered JSON)."""
    status: int
    headers: Dict[str, str]
    body: bytes
    stream: Optional[Iterator[bytes]] = None
    close: Optional[Callable[[], None]] = None


class PeerUnreachable(Exception):
    """The peer could not be reached (connection refused, timeout, TLS). ``sent`` is True when the
    request may have reached the peer (a timeout or a dropped connection after sending), False when
    it certainly did not (connection refused, connect timeout, TLS handshake): protocol §15.8."""

    def __init__(self, message: str = '', sent: bool = False):
        super().__init__(message)
        self.sent = sent


class PeerConnector(Plugin):
    """How requests travel to a participant."""
    kind = 'connector'

    def send(self, method: str, url: str, headers: Dict[str, str], body: bytes, timeout: float,
             stream: bool = False) -> PeerResponse:
        """``stream`` True: return as soon as the response headers arrive, the body as
        :attr:`PeerResponse.stream` (a connector without streaming may ignore it and buffer; a caller
        never passes it to a connector whose ``send`` lacks the parameter)."""
        raise NotImplementedError


class IdentityResolver(Plugin):
    """How the user travels with a forwarded call and is verified (design §10.2)."""
    kind = 'identity'

    def outbound_headers(self, user: Optional[Dict[str, Any]]) -> Dict[str, str]:
        """Headers a home adds to a forwarded call for ``user``."""
        raise NotImplementedError

    def resolve(self, headers: Dict[str, str], sender: str) -> Optional[Dict[str, Any]]:
        """The user a host runs a forwarded call as, or None for the service identity."""
        raise NotImplementedError


class CatalogSource(Plugin):
    """Where a participant's tools come from."""
    kind = 'catalog_source'

    def tools(self, net: str, peer: Optional[str] = None) -> List[Dict[str, Any]]:
        raise NotImplementedError


class KeyDirectoryStore(Plugin):
    """Where synced key records live (protocol §11)."""
    kind = 'key_directory_store'

    def put(self, record: Dict[str, Any], force: bool = False) -> bool:
        """Store a record if it is newer than the held one (``force``: also at an equal or lower
        version, for the home's own re-signed records); a record held for another home is never
        replaced. True when stored."""
        raise NotImplementedError

    def by_hash(self, net: str, key_hash: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def since(self, net: str, home: str, version: int, limit: int = 1000) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def version(self, net: str, home: str) -> int:
        raise NotImplementedError

    # optional: the shipped stores implement these; the defaults keep older third-party stores working

    def find(self, net: str, key_hash: str) -> List[Dict[str, Any]]:
        """Every record of ``net`` with this hash (several homes could publish one hash)."""
        r = self.by_hash(net, key_hash)
        return [r] if r else []

    def by_id(self, net: str, home: str, key_id: str) -> Optional[Dict[str, Any]]:
        """The record ``key_id`` of ``home`` (a user assertion names a key by id, protocol §15.5)."""
        return next((r for r in self.since(net, home, 0, limit=10 ** 6) if r.get('key_id') == key_id), None)

    def discard_signed(self, net: str, keyid: str) -> List[str]:
        """Drop the records whose signature ``keyid`` is this certificate thumbprint (§11.2, a
        revoked certificate); returns the homes concerned."""
        return []

    def mark(self, net: str, home: str, reason: Optional[str]) -> None:
        """Mark a home's records unusable (``left``, ``revoked``) or usable again (None)."""

    def marked(self, net: str, home: str) -> Optional[str]:
        return None


@dataclass
class Decision:
    allow: bool
    reason: str = ''
    value: Any = None          # residency: the arguments or result to send instead (redacted), or None


class RuleEvaluator(Plugin):
    """Export, import, residency and blocking decisions."""
    kind = 'rules'

    def decide(self, rule: str, subject: Dict[str, Any]) -> Decision:
        raise NotImplementedError


class SnapshotSink(Plugin):
    """Where snapshots go."""
    kind = 'snapshot_sink'

    def write(self, name: str, data: bytes) -> str:
        raise NotImplementedError

    def list(self) -> List[str]:
        raise NotImplementedError

    def delete(self, name: str) -> bool:
        raise NotImplementedError


@dataclass
class HostOption:
    """One host offering a tool in one net, for routing."""
    instance: str
    local: bool = False
    latency_ms: Optional[float] = None
    attrs: Dict[str, Any] = field(default_factory=dict)


class RoutingStrategy(Plugin):
    """The order of the hosts within one net that offer a tool, after its preferences (design §8.2)."""
    kind = 'routing'

    def order(self, tool: str, hosts: List[HostOption], preferred: Optional[List[str]] = None) -> List[HostOption]:
        raise NotImplementedError


INTERFACES: Dict[str, Type[Plugin]] = {c.kind: c for c in (
    MembershipProvider, AdmissionProvider, PeerConnector, IdentityResolver, CatalogSource, KeyDirectoryStore,
    RuleEvaluator, SnapshotSink, RoutingStrategy)}


# ── registry ────────────────────────────────────────────────────────

_REGISTRY: Dict[str, Dict[str, Type[Plugin]]] = {k: {} for k in INTERFACES}
_entry_points_loaded = False
#: third-party plug-ins that failed to load or to pass their contract check: {source, kind, name, error}
LOAD_ERRORS: List[Dict[str, str]] = []


def register(kind: str, name: Optional[str] = None):
    """Class decorator: ``@register('routing')`` (uses ``cls.name``) or ``@register('routing', 'mine')``."""
    def deco(cls):
        base = INTERFACES.get(kind)
        if base is None:
            raise ValueError(f'unknown SAJHA Net plug-in kind {kind!r}; kinds: {", ".join(sorted(INTERFACES))}')
        if not (isinstance(cls, type) and issubclass(cls, base)):
            raise TypeError(f'{cls!r} does not implement {base.__name__}')
        n = name or cls.name
        if not n:
            raise ValueError(f'{cls.__name__} has no name')
        cls.name = n
        _REGISTRY[kind][n] = cls
        return cls
    return deco


def _load_entry_points() -> None:
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                cls = ep.load()
                kind, _, nm = ep.name.partition('.')
                kind = getattr(cls, 'kind', '') or kind
                register(kind, getattr(cls, 'name', '') or nm or ep.name)(cls)
            except Exception as e:
                logger.warning(f'SAJHA Net plug-in entry point {ep.name}: {e}')
                _record_error(f'entry point {ep.name}', ep.name.partition('.')[0], ep.name, str(e))
    except Exception as e:                      # pragma: no cover
        logger.debug(f'SAJHA Net plug-in entry points: {e}')


def _record_error(source: str, kind: str, name: str, error: str) -> None:
    item = {'source': source, 'kind': kind, 'name': name, 'error': error[:500]}
    if item not in LOAD_ERRORS:
        LOAD_ERRORS.append(item)


def _snapshot() -> Dict[str, Dict[str, Type[Plugin]]]:
    return {k: dict(v) for k, v in _REGISTRY.items()}


def _new_since(before: Dict[str, Dict[str, Type[Plugin]]]) -> List[tuple]:
    return [(k, n) for k, v in _REGISTRY.items() for n, c in v.items() if before.get(k, {}).get(n) is not c]


def _check_new(before, source: str) -> List[Dict[str, str]]:
    """Run the contract check of every plug-in registered since ``before``; one that fails is
    unregistered (it cannot be selected) and reported."""
    from sajha.net import contract
    out = []
    for kind, name in _new_since(before):
        try:
            contract.check(kind, lambda k=kind, n=name: create(k, n))
            out.append({'source': source, 'kind': kind, 'name': name, 'error': ''})
        except Exception as e:
            _REGISTRY[kind].pop(name, None)
            if before.get(kind, {}).get(name) is not None:
                _REGISTRY[kind][name] = before[kind][name]
            msg = f'fails its contract check: {e}' if isinstance(e, AssertionError) else f'cannot be built: {e}'
            logger.warning(f'SAJHA Net plug-in {kind}.{name} from {source} {msg}; it is not available')
            _record_error(source, kind, name, msg)
            out.append({'source': source, 'kind': kind, 'name': name, 'error': msg})
    return out


def load_plugins(modules: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """Load third-party plug-ins at start (design §5.3): the entry-point group ``sajha.net.plugins``
    and every module in ``modules`` (``sajhanet.plugins.modules``; a module registers its classes
    with :func:`register` when imported). Each new plug-in must pass its contract check. Returns one
    row per plug-in found or module that failed (``error`` empty when it loaded); failures are also
    kept in :data:`LOAD_ERRORS`."""
    out: List[Dict[str, str]] = []
    before = _snapshot()
    _load_entry_points()
    out += _check_new(before, 'entry points')
    out += [dict(e) for e in LOAD_ERRORS if e['source'].startswith('entry point ')]
    for mod in modules or []:
        mod = str(mod).strip()
        if not mod:
            continue
        before = _snapshot()
        import sys
        if mod in sys.modules:                       # loaded before (a second start): nothing new to check
            out.append({'source': f'module {mod}', 'kind': '', 'name': mod, 'error': ''})
            continue
        try:
            importlib.import_module(mod)
        except Exception as e:
            logger.warning(f'SAJHA Net plug-in module {mod}: {e}')
            _record_error(f'module {mod}', '', mod, f'cannot be imported: {e}')
            out.append({'source': f'module {mod}', 'kind': '', 'name': mod, 'error': f'cannot be imported: {e}'})
            continue
        found = _check_new(before, f'module {mod}')
        if not found:
            out.append({'source': f'module {mod}', 'kind': '', 'name': mod,
                        'error': 'registers no SAJHA Net plug-in (use sajha.net.plugins.register)'})
        out += found
    return out


def registered(kind: str) -> Dict[str, Type[Plugin]]:
    _load_entry_points()
    return dict(_REGISTRY[kind])


def plugin_class(kind: str, spec: str) -> Type[Plugin]:
    """A registered name, or ``package.module:Class`` implementing the kind's interface."""
    if kind not in INTERFACES:
        raise ValueError(f'unknown SAJHA Net plug-in kind {kind!r}')
    key = (spec or '').strip()
    if key in _REGISTRY[kind]:
        return _REGISTRY[kind][key]
    if ':' in key:
        mod, _, attr = key.partition(':')
        cls = getattr(importlib.import_module(mod), attr)
        if not (isinstance(cls, type) and issubclass(cls, INTERFACES[kind])):
            raise ValueError(f'{spec!r} does not implement {INTERFACES[kind].__name__}')
        if not cls.name:
            cls.name = key
        return cls
    _load_entry_points()
    if key in _REGISTRY[kind]:
        return _REGISTRY[kind][key]
    raise ValueError(f'unknown {kind} plug-in {spec!r}; registered: {", ".join(sorted(_REGISTRY[kind]))} '
                     f'(or give package.module:Class)')


def create(kind: str, spec: str, **kwargs) -> Plugin:
    cls = plugin_class(kind, spec)
    obj = cls(**kwargs) if kwargs else cls()
    for attr, val in vars(INTERFACES[kind]).items():
        if callable(val) and not attr.startswith('_') and not callable(getattr(obj, attr, None)):
            raise TypeError(f'{cls.__name__} lacks {attr}()')
    return obj


# ── shipped implementations ─────────────────────────────────────────

@register('membership')
class GossipMembership(MembershipProvider):
    name = 'gossip'
    gossip = True


@register('membership')
class StaticMembership(MembershipProvider):
    name = 'static'
    gossip = False

    def peers(self, cfg) -> List[str]:
        return list(getattr(cfg, 'static_peers', None) or [])


@register('connector')
class HttpConnector(PeerConnector):
    """Signed requests over HTTP(S) on the peer's normal port (httpx), one connection pool per peer
    base URL (design §15: per-peer isolation)."""
    name = 'sajha_native'

    def __init__(self, verify_tls: bool = True, max_connections_per_peer: int = 10):
        self.verify_tls = verify_tls
        self.max_connections = max_connections_per_peer
        self._clients: Dict[str, Any] = {}
        self._lock = __import__('threading').Lock()

    def _client(self, url: str):
        import httpx
        from urllib.parse import urlsplit
        p = urlsplit(url)
        base = f'{p.scheme}://{p.netloc}'
        with self._lock:
            c = self._clients.get(base)
            if c is None:
                c = httpx.Client(verify=self.verify_tls, follow_redirects=False,
                                 limits=httpx.Limits(max_connections=self.max_connections,
                                                     max_keepalive_connections=self.max_connections))
                self._clients[base] = c
            return c

    def send(self, method, url, headers, body, timeout, stream=False):
        import httpx
        client = self._client(url)
        content = body if method.upper() != 'GET' else None
        try:
            if stream:
                req = client.build_request(method, url, headers=headers, content=content, timeout=timeout)
                r = client.send(req, stream=True)
            else:
                r = client.request(method, url, headers=headers, content=content, timeout=timeout)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol) as e:
            raise PeerUnreachable(f'{e.__class__.__name__}: {e}', sent=False) from e
        except httpx.HTTPError as e:
            raise PeerUnreachable(f'{e.__class__.__name__}: {e}', sent=True) from e
        headers_out = {k.lower(): v for k, v in r.headers.items()}
        if stream:
            return PeerResponse(r.status_code, headers_out, b'', stream=r.iter_raw(), close=r.close)
        return PeerResponse(r.status_code, headers_out, r.content)


@register('connector')
class InProcessConnector(PeerConnector):
    """Routes requests to handlers in this process by base URL (tests, the agent's self-checks).
    ``routes`` maps a base URL (``https://risk-eu.test``) to ``handler(method, path, query, headers,
    body, secure) -> PeerResponse``; an address with no handler is unreachable."""
    name = 'in_process'

    def __init__(self, routes: Optional[Dict[str, Callable[..., PeerResponse]]] = None):
        self.routes = routes if routes is not None else {}
        self.down: set = set()
        self.hang: set = set()          # base URLs that accept a request and never answer (tests)

    def send(self, method, url, headers, body, timeout, stream=False):
        """A handler's streamed answer (``PeerResponse.stream``) passes through as it is."""
        from urllib.parse import urlsplit
        p = urlsplit(url)
        base = f'{p.scheme}://{p.netloc}'
        h = self.routes.get(base)
        if h is None or base in self.down:
            raise PeerUnreachable(f'connection refused: {base}')
        if base in self.hang:
            raise PeerUnreachable(f'read timeout: {base}', sent=True)
        return h(method, p.path, p.query, dict(headers), body or b'', p.scheme == 'https')


@register('identity')
class NoIdentity(IdentityResolver):
    """Service identity only: no user travels with a call (sponsored servers without users)."""
    name = 'none'

    def outbound_headers(self, user):
        return {}

    def resolve(self, headers, sender):
        return None


@register('catalog_source')
class StaticCatalog(CatalogSource):
    name = 'static'

    def __init__(self, tools: Optional[List[Dict[str, Any]]] = None):
        self._tools = list(tools or [])

    def tools(self, net, peer=None):
        return [dict(t) for t in self._tools]


@register('key_directory_store')
class MemoryKeyDirectory(KeyDirectoryStore):
    name = 'memory'

    def __init__(self):
        self._by: Dict[tuple, Dict[str, Any]] = {}
        self._marks: Dict[tuple, str] = {}

    def put(self, record, force=False):
        k = (record['net'], record['key_id'])
        held = self._by.get(k)
        if held is not None and (held['home_instance'] != record['home_instance']
                                 or (not force and int(held['version']) >= int(record['version']))):
            return False
        self._by[k] = dict(record)
        return True

    def _out(self, r):
        out = dict(r)
        m = self._marks.get((r['net'], r['home_instance']))
        if m:
            out['unusable'] = m
        return out

    def by_hash(self, net, key_hash):
        found = self.find(net, key_hash)
        return found[0] if found else None

    def find(self, net, key_hash):
        return [self._out(r) for (n, _), r in sorted(self._by.items()) if n == net and r.get('key_hash') == key_hash]

    def discard_signed(self, net, keyid):
        gone = [k for k, r in self._by.items() if k[0] == net and (r.get('signature') or {}).get('keyid') == keyid]
        homes = sorted({self._by[k]['home_instance'] for k in gone})
        for k in gone:
            del self._by[k]
        return homes

    def mark(self, net, home, reason):
        if reason:
            self._marks[(net, home)] = reason
        else:
            self._marks.pop((net, home), None)

    def marked(self, net, home):
        return self._marks.get((net, home))

    def since(self, net, home, version, limit=1000):
        rs = [r for (n, _), r in self._by.items()
              if n == net and r['home_instance'] == home and int(r['version']) > int(version)]
        return [self._out(r) for r in sorted(rs, key=lambda r: int(r['version']))[:limit]]

    def version(self, net, home):
        vs = [int(r['version']) for (n, _), r in self._by.items() if n == net and r['home_instance'] == home]
        return max(vs) if vs else 0


@register('rules')
class AllowAll(RuleEvaluator):
    name = 'allow_all'

    def decide(self, rule, subject):
        return Decision(True, 'allow_all')


@register('rules')
class DenyAll(RuleEvaluator):
    name = 'deny_all'

    def decide(self, rule, subject):
        return Decision(False, 'deny_all')


@register('snapshot_sink')
class LocalFilesSink(SnapshotSink):
    """Snapshots as files in a directory, owner-only, written atomically."""
    name = 'local_files'

    def __init__(self, directory: str = 'data/sajhanet/snapshots'):
        self.directory = directory

    def _path(self, name: str) -> str:
        if not name or '/' in name or '\\' in name or name.startswith('.'):
            raise ValueError(f'invalid snapshot name {name!r}')
        return os.path.join(self.directory, name)

    def write(self, name, data):
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        path = self._path(name)
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix='.tmp-')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return path

    def list(self):
        try:
            return sorted(n for n in os.listdir(self.directory) if not n.startswith('.'))
        except FileNotFoundError:
            return []

    def delete(self, name):
        try:
            os.unlink(self._path(name))
            return True
        except FileNotFoundError:
            return False


def _apply_preferred(hosts: List[HostOption], preferred: Optional[List[str]]) -> List[HostOption]:
    if not preferred:
        return list(hosts)
    rank = {p: i for i, p in enumerate(preferred)}
    first = sorted([h for h in hosts if h.instance in rank], key=lambda h: rank[h.instance])
    return first + [h for h in hosts if h.instance not in rank]


@register('routing')
class LocalFirst(RoutingStrategy):
    """The local tool first, then hosts in a stable order by instance name; preferences first of all."""
    name = 'local_first'

    def order(self, tool, hosts, preferred=None):
        base = sorted(hosts, key=lambda h: (not h.local, h.instance))
        return _apply_preferred(base, preferred)


@register('routing')
class LowestLatency(RoutingStrategy):
    """The local tool first, then by measured latency (unknown last), ties by instance name."""
    name = 'lowest_latency'

    def order(self, tool, hosts, preferred=None):
        base = sorted(hosts, key=lambda h: (not h.local, h.latency_ms is None,
                                            h.latency_ms if h.latency_ms is not None else 0, h.instance))
        return _apply_preferred(base, preferred)


@register('routing')
class Pinned(RoutingStrategy):
    """Only the hosts named in the preferences, in that order."""
    name = 'pinned'

    def order(self, tool, hosts, preferred=None):
        rank = {p: i for i, p in enumerate(preferred or [])}
        return sorted([h for h in hosts if h.instance in rank], key=lambda h: rank[h.instance])


# the admission plug-ins live next to the trust they build
from sajha.net import trust as _trust  # noqa: E402,F401
