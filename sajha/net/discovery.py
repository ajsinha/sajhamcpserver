# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Discovery sources (protocol §9.7, design §6.6 step 3): addresses a participant tries to join through after
its seeds and its saved peers. An address carries no trust: the join is an ordinary signed sync, and the
peer is admitted or refused by the same rules as any member (GOS-14).

A net's ``discovery`` is a list of sources (``sajhanet.discovery``, or a net entry's ``discovery``):

* ``{"type": "dns_srv", "name": "_sajhanet._tcp.example.com", "scheme": "https"}``: the SRV records of
  ``name``, by priority then weight, as ``<scheme>://<target>:<port>`` (the port left out when it is the
  scheme's default). A small DNS client over UDP (no third-party resolver); ``nameserver`` overrides the
  first ``nameserver`` of ``/etc/resolv.conf``.
* ``{"type": "kubernetes", "service": "sajha", "namespace": "risk", "port_name": "https", "port": 8443,
  "scheme": "https", "cluster_domain": "cluster.local"}``: a headless Service. Its SRV records
  ``_<port_name>._tcp.<service>.<namespace>.svc.<cluster_domain>`` give the pods' DNS names (a StatefulSet's
  stable names; the names the instance certificates carry); without SRV records, the Service's A/AAAA
  records with ``port`` give ``<scheme>://<address>:<port>`` (certificates must then name the addresses).
* ``{"type": "registry", "url": "https://registry.example/acme-net.json"}``: a JSON document fetched with
  GET, a list of URLs or an object with ``members`` (or ``urls``) holding one.

At most :data:`MAX_ADDRESSES` addresses come back in all, only ``http(s)`` URLs, and each source's answer is
kept for its ``ttl_seconds`` (default 60), so a participant retrying its join does not ask again at every
attempt. A source that fails is logged and skipped.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import secrets
import socket
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MAX_ADDRESSES = 64
TYPES = ('dns_srv', 'kubernetes', 'registry')
SRV = 33
DEFAULT_PORTS = {'https': 443, 'http': 80}

Srv = Tuple[int, int, int, str]                 # priority, weight, port, target


# ── a minimal DNS SRV client ────────────────────────────────────────

def _qname(name: str) -> bytes:
    out = b''
    for label in name.rstrip('.').split('.'):
        raw = label.encode('idna') if label else b''
        if not raw or len(raw) > 63:
            raise ValueError(f'invalid DNS name {name!r}')
        out += bytes([len(raw)]) + raw
    return out + b'\x00'


def _name_at(msg: bytes, off: int) -> Tuple[str, int]:
    """The (possibly compressed) name at ``off``, and the offset after it in the record."""
    labels: List[str] = []
    end = None
    seen = 0
    while True:
        if off >= len(msg):
            raise ValueError('truncated name')
        n = msg[off]
        if n & 0xC0 == 0xC0:
            if off + 1 >= len(msg):
                raise ValueError('truncated pointer')
            if end is None:
                end = off + 2
            off = ((n & 0x3F) << 8) | msg[off + 1]
            seen += 1
            if seen > 32:
                raise ValueError('a compression loop')
            continue
        if n == 0:
            return '.'.join(labels), (end if end is not None else off + 1)
        labels.append(msg[off + 1:off + 1 + n].decode('ascii', 'replace'))
        off += 1 + n


def query(name: str) -> Tuple[int, bytes]:
    """A DNS query for the SRV records of ``name``: ``(id, packet)``."""
    qid = secrets.randbelow(0x10000)
    return qid, struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0) + _qname(name) + struct.pack('>HH', SRV, 1)


def parse_srv(msg: bytes, qid: Optional[int] = None) -> List[Srv]:
    """The SRV answers of a DNS response (RFC 2782), unsorted."""
    if len(msg) < 12:
        raise ValueError('a short DNS response')
    rid, flags, qd, an, _ns, _ar = struct.unpack('>HHHHHH', msg[:12])
    if qid is not None and rid != qid:
        raise ValueError('a DNS response for another query')
    rcode = flags & 0x000F
    if rcode not in (0, 3):
        raise ValueError(f'DNS error {rcode}')
    off = 12
    for _ in range(qd):
        _n, off = _name_at(msg, off)
        off += 4
    out: List[Srv] = []
    for _ in range(an):
        _n, off = _name_at(msg, off)
        if off + 10 > len(msg):
            raise ValueError('a truncated record')
        typ, _cls, _ttl, rdlen = struct.unpack('>HHIH', msg[off:off + 10])
        off += 10
        if typ == SRV and rdlen >= 7:
            prio, weight, port = struct.unpack('>HHH', msg[off:off + 6])
            target, _ = _name_at(msg, off + 6)
            if target:
                out.append((prio, weight, port, target.rstrip('.')))
        off += rdlen
    return out


def _nameserver() -> str:
    try:
        with open('/etc/resolv.conf', encoding='utf-8') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == 'nameserver':
                    return parts[1]
    except OSError:
        pass
    return '127.0.0.1'


def _server(ns: str) -> Tuple[str, int]:
    """``host`` or ``host:port`` (``[v6]:port`` for IPv6 with a port)."""
    if ns.startswith('['):
        host, _, rest = ns[1:].partition(']')
        return host, int(rest[1:]) if rest.startswith(':') else 53
    if ns.count(':') == 1:
        host, port = ns.split(':')
        return host, int(port)
    return ns, 53


def resolve_srv(name: str, nameserver: str = '', timeout: float = 2.0) -> List[Srv]:
    """The SRV records of ``name`` over UDP, from ``nameserver`` (``host[:port]``; default the first of
    ``/etc/resolv.conf``)."""
    host, port = _server(nameserver or _nameserver())
    qid, packet = query(name)
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    s = socket.socket(family, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.sendto(packet, (host, port))
        end = time.monotonic() + timeout
        while True:
            msg, _addr = s.recvfrom(65535)
            try:
                return parse_srv(msg, qid)
            except ValueError as e:
                if 'another query' not in str(e) or time.monotonic() >= end:
                    raise
    finally:
        s.close()


def resolve_host(name: str, port: int) -> List[str]:
    """The addresses of ``name`` (A and AAAA)."""
    out: List[str] = []
    for fam, _t, _p, _c, sa in socket.getaddrinfo(name, port, proto=socket.IPPROTO_TCP):
        a = sa[0]
        a = f'[{a}]' if fam == socket.AF_INET6 else a
        if a not in out:
            out.append(a)
    return out


def _fetch_json(url: str, timeout: float = 5.0) -> Any:
    import httpx
    r = httpx.get(url, timeout=timeout, follow_redirects=False)
    r.raise_for_status()
    return r.json()


# ── sources ─────────────────────────────────────────────────────────

def _url(scheme: str, host: str, port: int) -> str:
    return f'{scheme}://{host}' if DEFAULT_PORTS.get(scheme) == port else f'{scheme}://{host}:{port}'


def _ordered(records: List[Srv]) -> List[Srv]:
    """By priority; within one, heavier first (a stable order, so every attempt tries the same way)."""
    return sorted(records, key=lambda r: (r[0], -r[1], r[3], r[2]))


class Discovery:
    """The discovery sources of one net (see the module docstring). The resolvers may be replaced (tests,
    other environments)."""

    def __init__(self, sources: List[Dict[str, Any]], *, srv: Optional[Callable[..., List[Srv]]] = None,
                 host: Optional[Callable[[str, int], List[str]]] = None, fetch: Optional[Callable[[str], Any]] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.sources = [dict(s) for s in (sources or []) if isinstance(s, dict)]
        self.srv = srv or (lambda name, ns='': resolve_srv(name, ns))
        self.host = host or (lambda name, port: resolve_host(name, port))
        self.fetch = fetch or (lambda url: _fetch_json(url))
        self.clock = clock
        self._cache: Dict[int, Tuple[float, List[str]]] = {}
        self._lock = threading.Lock()

    def addresses(self) -> List[str]:
        out: List[str] = []
        for i, src in enumerate(self.sources):
            for u in self._cached(i, src):
                if u not in out and len(out) < MAX_ADDRESSES:
                    out.append(u)
        return out

    def _cached(self, i: int, src: Dict[str, Any]) -> List[str]:
        now = self.clock()
        with self._lock:
            hit = self._cache.get(i)
            if hit is not None and hit[0] > now:
                return hit[1]
        try:
            found = [u for u in self._one(src) if u.startswith(('https://', 'http://'))][:MAX_ADDRESSES]
        except Exception as e:
            logger.info(f'SAJHA Net discovery {src.get("type")}: {e}')
            found = []
        try:
            ttl = max(1.0, float(src.get('ttl_seconds', 60)))
        except (TypeError, ValueError):
            ttl = 60.0
        with self._lock:
            self._cache[i] = (now + ttl, found)
        return found

    def _one(self, src: Dict[str, Any]) -> List[str]:
        kind = str(src.get('type') or '')
        scheme = str(src.get('scheme') or 'https').lower()
        if kind == 'dns_srv':
            name = str(src.get('name') or '')
            return [_url(scheme, t, p) for _pr, _w, p, t in _ordered(self.srv(name, str(src.get('nameserver') or '')))]
        if kind == 'kubernetes':
            svc, ns = str(src.get('service') or ''), str(src.get('namespace') or 'default')
            domain = str(src.get('cluster_domain') or 'cluster.local')
            fqdn = f'{svc}.{ns}.svc.{domain}'
            port_name = str(src.get('port_name') or scheme)
            try:
                recs = self.srv(f'_{port_name}._tcp.{fqdn}', str(src.get('nameserver') or ''))
            except Exception as e:
                logger.debug(f'SAJHA Net discovery kubernetes SRV {fqdn}: {e}')
                recs = []
            if recs:
                return [_url(scheme, t, p) for _pr, _w, p, t in _ordered(recs)]
            port = int(src.get('port') or DEFAULT_PORTS.get(scheme, 443))
            return [_url(scheme, a, port) for a in self.host(fqdn, port)]
        if kind == 'registry':
            doc = self.fetch(str(src.get('url') or ''))
            items = doc.get('members') or doc.get('urls') if isinstance(doc, dict) else doc
            return [str(u).rstrip('/') for u in (items or []) if isinstance(u, str)]
        raise ValueError(f'unknown discovery type {kind!r} (one of {", ".join(TYPES)})')


def problems(sources: Any) -> List[str]:
    """What is wrong with a ``discovery`` setting (empty: nothing)."""
    out = []
    for i, s in enumerate(sources or []):
        if not isinstance(s, dict):
            out.append(f'discovery[{i}] is not an object')
            continue
        t = s.get('type')
        if t not in TYPES:
            out.append(f'discovery[{i}].type {t!r} is not one of {", ".join(TYPES)}')
        elif t == 'dns_srv' and not s.get('name'):
            out.append(f'discovery[{i}] (dns_srv) needs name')
        elif t == 'kubernetes' and not s.get('service'):
            out.append(f'discovery[{i}] (kubernetes) needs service')
        elif t == 'registry' and not str(s.get('url') or '').startswith(('https://', 'http://')):
            out.append(f'discovery[{i}] (registry) needs an http(s) url')
    return out

