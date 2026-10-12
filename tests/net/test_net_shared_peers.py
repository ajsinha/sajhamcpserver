# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Per-peer breakers and rate limits shared across workers, and cached results of read-only remote tools
(SAJHA Net §15; ``sajhanet.peer.shared``, ``sajhanet.cache.ttl_seconds``).

Covers: a breaker opened by one worker is open for another (one state-store entry per peer), and closes for
both on success; a per-peer rate limit counts every worker's calls; the router and the host use the shared
forms when the state store is shared (``auto``) or when told to; a read-only remote tool's result is served
from the cache to the same caller only, never for a destructive tool or another user.
"""

from __future__ import annotations

import pytest

from sajha.net import EXTENSION_ID
from sajha.net.models import MemoryKV
from sajha.net.routing import PeerBreaker, PeerWindow, SharedPeerBreaker, SharedPeerWindow
from tests.net.test_net_routing_integration import NET, net3, node  # noqa: F401


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_shared_breaker_across_workers():
    clock = Clock()
    kv = MemoryKV(clock)
    w1, w2 = (SharedPeerBreaker(kv, 'brk:cust-na', threshold=2, reset_seconds=30, clock=clock) for _ in range(2))
    assert w1.allow() and w2.allow() and w1.state == 'closed'
    w1.failure()
    w2.failure()                                     # two workers' failures count together
    assert w1.state == 'open' and not w2.allow()
    clock.t += 31
    assert w2.state == 'half_open' and w1.allow()
    w2.success()
    assert w1.state == 'closed' and w1.failures == 0 and kv.get('brk:cust-na') is None


def test_shared_rate_limit_across_workers():
    clock = Clock()
    kv = MemoryKV(clock)
    w1, w2 = (SharedPeerWindow(kv, 'rlout:cust-na', 3, clock) for _ in range(2))
    assert [w1.take(), w2.take(), w1.take(), w2.take()] == [True, True, True, False]
    clock.t += 60                                    # the next minute
    assert w2.take()


def test_router_and_host_use_the_shared_forms(net3):
    a, b = net3['risk-eu'], net3['cust-na']
    r = a.catalogs.router
    assert type(r.breaker(NET, 'cust-na')) is PeerBreaker                  # memory state store: per process
    a.catalogs.settings.peer_shared = 'true'
    a.catalogs._build_router()
    r = a.catalogs.router
    assert r.peer.shared and isinstance(r.breaker(NET, 'cust-na'), SharedPeerBreaker)
    assert isinstance(r.window(NET, 'cust-na'), SharedPeerWindow)
    assert a.catalogs.settings.peer.shared is False                         # the settings are not changed
    host = b.catalogs.hosts[NET]
    assert type(host._window('risk-eu')) is PeerWindow
    host.shared_limits, host._windows = True, {}
    assert isinstance(host._window('risk-eu'), SharedPeerWindow)
    # auto follows the state store
    a.catalogs.settings.peer_shared = 'auto'
    real = a._store
    a._store = type('SharedStore', (), {'shared': True})()
    try:
        assert a.catalogs.shared_peers() is True
    finally:
        a._store = real
    assert a.catalogs.shared_peers() is False
    # a call still works with shared breakers and limits
    a.catalogs.settings.peer_shared = 'true'
    a.catalogs._build_router()
    out = a.tools_registry.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 3})
    assert out['content'][0]['text'] == 'cust-na:lookup:3'


@pytest.fixture
def alice(monkeypatch):
    import sajha.net.integration.catalogs as cat
    who = {'user': 'alice'}
    monkeypatch.setattr(cat, '_caller_user', lambda net_hint='': {
        'user_id': who['user'], 'roles': ['user'], 'authenticated': True, 'auth_type': 'apikey', 'net': ''})
    return who


def test_read_only_results_cached_per_caller(net3, alice):
    a, b, c = net3['risk-eu'], net3['cust-na'], net3['treasury-na']
    a.catalogs.settings.cache_seconds = 60
    reg = a.tools_registry
    lookup = b.tools_registry.get_tool('lookup')
    r1 = reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 1})
    r2 = reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 1})
    assert r1['content'] == r2['content'] and lookup.calls == 1
    assert r2['_meta'][EXTENSION_ID]['cached'] is True and 'cached' not in r1['_meta'][EXTENSION_ID]
    reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 2})      # other arguments
    assert lookup.calls == 2
    alice['user'] = 'bob'                                                          # another caller
    reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 1})
    assert lookup.calls == 3
    wipe = c.tools_registry.get_tool('wipe')                                       # destructive: never cached
    for _ in range(2):
        reg.get_tool('acme-net__treasury-na__wipe').execute_with_tracking({'x': 1})
    assert wipe.calls == 2
    a.catalogs.settings.cache_seconds = 0                                          # off (the default)
    reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 1})
    assert lookup.calls == 4
