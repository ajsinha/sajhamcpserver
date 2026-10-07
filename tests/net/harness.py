"""
A SAJHA Net test net in one process: one CA, participants as :class:`sajha.net.node.NetNode`s
with their own stores, keys and peer caches, wired together by the in-process connector, on a
fake clock. Used by the conformance tests (tests/net/test_*.py).
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from sajha.net import crypto, httpsig
from sajha.net.ca import CertificateAuthority, init_ca
from sajha.net.membership import PeerCache
from sajha.net.models import GossipSettings, MemoryKV, NetConfig, PeerCacheSettings, CASettings
from sajha.net.node import NetNode, Participant
from sajha.net.plugins import InProcessConnector, StaticMembership
from sajha.net.trust import CATrust, PinnedTrust

T0 = 1791374400.0          # 2026-10-07T12:00:00Z, the time of the spec's examples


class Clock:
    def __init__(self, t: float = T0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def fast_gossip() -> GossipSettings:
    return GossipSettings(gossip_interval_ms=100, ping_timeout_ms=100, indirect_probes=2, suspect_timeout_seconds=10,
                          full_sync_interval_seconds=30, dead_retention_minutes=60, dead_probe_interval_seconds=30)


class TestNet:
    __test__ = False

    def __init__(self, tmpdir, net: str = 'acme-net', clock: Optional[Clock] = None,
                 connector: Optional[InProcessConnector] = None):
        self.tmp = str(tmpdir)
        self.net = net
        self.clock = clock or Clock()
        self.connector = connector or InProcessConnector()
        self.ca_key, self.ca_cert = init_ca(net, now=self.clock() - 86400)
        self.ca = CertificateAuthority(net, self.ca_key, self.ca_cert, MemoryKV(self.clock), self.clock)
        self.nodes: Dict[str, NetNode] = {}
        self.participants: Dict[str, Participant] = {}
        self.events: List[tuple] = []

    def url(self, name: str) -> str:
        return f'https://{name}.test'

    def issue(self, name: str, host: Optional[str] = None, key=None, alg: str = crypto.ED25519):
        key = key or crypto.generate_key(alg)
        cert = self.ca._issue(key.public_key(), name, host or f'{name}.test')
        return key, cert

    def config(self, name: str, **kw) -> NetConfig:
        cfg = NetConfig(name=self.net, instance_name=name, base_url=kw.pop('base_url', self.url(name)),
                        gossip=fast_gossip(),
                        peer_cache=PeerCacheSettings(path=os.path.join(self.tmp, f'{name}-{self.net}-peers.json')))
        for k, v in kw.items():
            setattr(cfg, k, v)
        return cfg

    def add(self, name: str, *, founder: bool = False, seeds=(), ca_node: bool = False, key=None, cert=None,
            kv=None, start: bool = True, manual_pins=None, static: bool = False, route_as: Optional[str] = None,
            **cfg_kw) -> NetNode:
        cfg = self.config(name, founder=founder, seeds=list(seeds), **cfg_kw)
        if ca_node:
            cfg.ca = CASettings(enabled=True)
        kv = kv or MemoryKV(self.clock)
        if manual_pins is not None:
            key = key or crypto.generate_key()
            cert = cert or crypto.self_signed_certificate(key, self.net, name, f'{name}.test', now=self.clock() - 60)
            trust = PinnedTrust(self.net, lambda: manual_pins)
            cfg.admission = 'manual'
        else:
            if cert is None:
                key, cert = self.issue(name, key=key)
            trust = CATrust(self.net, self.ca_cert, lambda kv=kv: kv.get('rl'))
        node = NetNode(cfg, name, httpsig.Signer(key, [cert]), trust, kv, self.connector, clock=self.clock,
                       events=lambda kind, data, n=name: self.events.append((n, kind, data)),
                       ca=self.ca if ca_node else None, ca_certificate=self.ca_cert,
                       peer_cache=PeerCache(cfg.peer_cache.path), manual=manual_pins is not None,
                       membership=StaticMembership() if static else None)
        participant = self.participants.get(route_as or name) or Participant()
        participant.nodes[self.net] = node
        self.participants[route_as or name] = participant
        self.nodes[name] = node
        self.connector.routes[self.url(route_as or name)] = (
            lambda method, path, query, headers, body, secure, p=participant:
            p.handle(method, path, query, headers, body, secure=secure, source='127.0.0.1'))
        if start:
            node.start()
        return node

    def kill(self, name: str) -> None:
        self.connector.down.add(self.url(name))

    def revive(self, name: str) -> None:
        self.connector.down.discard(self.url(name))

    def rounds(self, n: int = 1, step: float = 1.0, only=None) -> None:
        for _ in range(n):
            for nm, node in list(self.nodes.items()):
                if only is not None and nm not in only:
                    continue
                if self.url(nm) in self.connector.down:
                    continue
                node.tick()
            self.clock.advance(step)

    def view(self, observer: str) -> Dict[str, str]:
        return {m['name']: m['state'] for m in self.nodes[observer].members()}

    def kinds(self, who: str) -> List[str]:
        return [k for n, k, _ in self.events if n == who]
