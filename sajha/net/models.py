"""
Configuration and data models of a participant, and the small key/value store the core keeps
its state in.

* :class:`NetConfig` is one entry of ``sajhanet.nets`` after shared defaults are applied (design §19).
* :class:`KV` is the store interface (get/set/add/update/delete/scan with TTLs): :class:`MemoryKV`
  here, SAJHA's state store through :mod:`sajha.net.integration` (so every worker sees one net).
* :func:`member_record` builds a participant's own member record (protocol §9.1).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from sajha.net import SUPPORTED_VERSIONS
from sajha.net.crypto import rfc3339

STATES = ('alive', 'suspect', 'dead', 'left')
PRECEDENCE = {s: i for i, s in enumerate(STATES)}


@dataclass
class GossipSettings:
    gossip_interval_ms: int = 1000
    ping_timeout_ms: int = 500
    indirect_probes: int = 3
    suspect_timeout_seconds: float = 10
    full_sync_interval_seconds: float = 30
    dead_retention_minutes: float = 60
    dead_probe_interval_seconds: float = 30
    dissemination_factor: int = 3


@dataclass
class PeerCacheSettings:
    path: str = ''
    interval_minutes: float = 10
    max_age_days: float = 7


@dataclass
class CASettings:
    enabled: bool = False
    key_ref: str = ''
    cert_ref: str = ''
    cert_validity_days: float = 30
    enrollment_token_minutes: float = 30
    enrollments_per_minute: int = 10
    # a net of one creates its CA at first start (owner decision); default: sajhanet.ca_auto_init
    auto_init: Optional[bool] = None


@dataclass
class IdentitySettings:
    cert_ref: str = ''
    key_ref: str = ''
    ca_ref: str = ''
    revocation_list_ref: str = ''
    pins: List[str] = field(default_factory=list)          # manual mode: pinned peer thumbprints


@dataclass
class NetConfig:
    name: str = 'default'
    instance_name: str = ''
    advertise_address: str = ''
    founder: bool = False
    seeds: List[str] = field(default_factory=list)
    identity: IdentitySettings = field(default_factory=IdentitySettings)
    ca: CASettings = field(default_factory=CASettings)
    peer_cache: PeerCacheSettings = field(default_factory=PeerCacheSettings)
    static_peers: List[str] = field(default_factory=list)
    base_url: str = ''
    mcp_path: str = '/mcp'
    region: str = ''
    labels: Dict[str, str] = field(default_factory=dict)
    signature_max_age_seconds: float = 30
    require_https: bool = True
    min_protocol_version: int = 1
    admission: str = 'builtin_ca'            # builtin_ca | manual | package.module:Class
    membership: str = 'gossip'               # gossip | static | package.module:Class
    gossip: GossipSettings = field(default_factory=GossipSettings)
    kind: str = 'sajha'
    user_identity: List[str] = field(default_factory=lambda: ['none'])
    max_injections_per_minute: int = 6

    def features(self) -> List[str]:
        out = ['gossip'] if self.membership == 'gossip' else []
        if self.ca.enabled and self.admission == 'builtin_ca':
            out.append('ca')
        return out


# ── member records (§9.1) ───────────────────────────────────────────

def member_record(cfg: NetConfig, name: str, incarnation: int, seq: int, revocations: int = 0,
                  leaving: bool = False, now: Optional[float] = None, catalog_digest: str = 'none',
                  keys: int = 0, blocks: int = 0) -> Dict[str, Any]:
    rec: Dict[str, Any] = {
        'type': 'member', 'net': cfg.name, 'name': name, 'url': cfg.base_url.rstrip('/'),
        'mcp_path': cfg.mcp_path or '/mcp', 'kind': cfg.kind, 'protocol_versions': list(SUPPORTED_VERSIONS),
        'features': cfg.features(), 'user_identity': list(cfg.user_identity),
        'incarnation': int(incarnation), 'seq': int(seq),
        'digests': {'catalog': catalog_digest, 'keys': int(keys), 'blocks': int(blocks),
                    'revocations': int(revocations)},
        'leaving': bool(leaving), 'issued_at': rfc3339(now),
    }
    if cfg.region:
        rec['region'] = cfg.region[:64]
    if cfg.labels:
        rec['labels'] = {str(k): str(v)[:128] for k, v in list(cfg.labels.items())[:32]}
    return rec


# ── the key/value store ─────────────────────────────────────────────

class KV:
    """The store interface the core keeps state in (SAJHA's state store has the same shape)."""

    def get(self, key: str) -> Any:                                         # pragma: no cover
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:  # pragma: no cover
        raise NotImplementedError

    def add(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:  # pragma: no cover
        raise NotImplementedError

    def update(self, key: str, fn: Callable[[Any], Any], ttl: Optional[float] = None) -> Any:  # pragma: no cover
        raise NotImplementedError

    def delete(self, key: str) -> bool:                                      # pragma: no cover
        raise NotImplementedError

    def scan(self, prefix: str) -> Iterator[Tuple[str, Any]]:                # pragma: no cover
        raise NotImplementedError


class MemoryKV(KV):
    """A process-local store with TTLs on an injectable clock (values are deep-copied, as JSON would be)."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._d: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = threading.RLock()
        self.clock = clock

    def _live(self, key: str):
        v = self._d.get(key)
        if v is None:
            return None
        if v[1] is not None and v[1] <= self.clock():
            del self._d[key]
            return None
        return v

    def get(self, key):
        with self._lock:
            v = self._live(key)
            return copy.deepcopy(v[0]) if v else None

    def set(self, key, value, ttl=None):
        with self._lock:
            self._d[key] = (copy.deepcopy(value), self.clock() + ttl if ttl else None)

    def add(self, key, value, ttl=None):
        with self._lock:
            if self._live(key):
                return False
            self.set(key, value, ttl)
            return True

    def update(self, key, fn, ttl=None):
        with self._lock:
            v = self._live(key)
            new = fn(copy.deepcopy(v[0]) if v else None)
            if new is None:
                self._d.pop(key, None)
                return None
            exp = (self.clock() + ttl) if ttl else (v[1] if v else None)
            self._d[key] = (copy.deepcopy(new), exp)
            return copy.deepcopy(new)

    def delete(self, key):
        with self._lock:
            return self._d.pop(key, None) is not None

    def scan(self, prefix):
        with self._lock:
            keys = [k for k in self._d if k.startswith(prefix)]
            out = []
            for k in keys:
                v = self._live(k)
                if v:
                    out.append((k, copy.deepcopy(v[0])))
        return iter(out)


class PrefixKV(KV):
    """A view of another store under a key prefix (one net's keys)."""

    def __init__(self, inner: KV, prefix: str):
        self.inner = inner
        self.prefix = prefix

    def get(self, key):
        return self.inner.get(self.prefix + key)

    def set(self, key, value, ttl=None):
        self.inner.set(self.prefix + key, value, ttl)

    def add(self, key, value, ttl=None):
        return self.inner.add(self.prefix + key, value, ttl)

    def update(self, key, fn, ttl=None):
        return self.inner.update(self.prefix + key, fn, ttl)

    def delete(self, key):
        return self.inner.delete(self.prefix + key)

    def scan(self, prefix):
        n = len(self.prefix)
        return iter([(k[n:], v) for k, v in self.inner.scan(self.prefix + prefix)])


class DocumentKV(KV):
    """A store kept as one JSON document (``{key: [value, expires_at or null]}``) that ``read`` and
    ``write`` load and save whole: the CA's tokens, issued certificates and revocation list, which
    must survive restarts (SAJHA: the storage backend). Every operation re-reads the document."""

    def __init__(self, read: Callable[[], Optional[Dict[str, Any]]], write: Callable[[Dict[str, Any]], None],
                 clock: Callable[[], float] = time.time):
        self._read, self._write, self.clock = read, write, clock
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Any]:
        doc = self._read() or {}
        now = self.clock()
        return {k: v for k, v in doc.items()
                if isinstance(v, list) and len(v) == 2 and (v[1] is None or v[1] > now)}

    def get(self, key):
        with self._lock:
            v = self._load().get(key)
            return copy.deepcopy(v[0]) if v else None

    def set(self, key, value, ttl=None):
        with self._lock:
            doc = self._load()
            doc[key] = [value, self.clock() + ttl if ttl else None]
            self._write(doc)

    def add(self, key, value, ttl=None):
        with self._lock:
            doc = self._load()
            if key in doc:
                return False
            doc[key] = [value, self.clock() + ttl if ttl else None]
            self._write(doc)
            return True

    def update(self, key, fn, ttl=None):
        with self._lock:
            doc = self._load()
            cur = doc.get(key)
            new = fn(copy.deepcopy(cur[0]) if cur else None)
            if new is None:
                doc.pop(key, None)
            else:
                doc[key] = [new, (self.clock() + ttl) if ttl else (cur[1] if cur else None)]
            self._write(doc)
            return copy.deepcopy(new)

    def delete(self, key):
        with self._lock:
            doc = self._load()
            if doc.pop(key, None) is None:
                return False
            self._write(doc)
            return True

    def scan(self, prefix):
        with self._lock:
            return iter([(k, copy.deepcopy(v[0])) for k, v in self._load().items() if k.startswith(prefix)])
