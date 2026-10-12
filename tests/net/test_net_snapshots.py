# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The net view in snapshots (SAJHA Net §20.4; sajha/snapshots/core.py ``collect_net``).

Covers: a snapshot of a net member records the members it holds (itself included) with state, kind and
features, the proxies of the host and tool table with their contract hashes, and the key directory per home
(counts and versions only); a change in the net shows in ``diff``; nothing of the net view is restored; no
net, no net view.
"""

from __future__ import annotations

import json

from sajha.snapshots import core
from tests.net.test_net_routing_integration import NET, net3, node, settle  # noqa: F401


class KeyStore:
    def summary(self, net):
        return [{'home': 'cust-na', 'records': 3, 'revoked': 1, 'disabled': 0, 'version': 7, 'unusable': None,
                 'last_received': 1.0}]


def test_net_view_recorded_and_compared(net3):
    a, b, c, conn = net3['risk-eu'], net3['cust-na'], net3['treasury-na'], net3['conn']
    a.authz.nets = {NET: type('St', (), {'store': KeyStore()})()}
    v1 = core.collect_net(a)
    members = {m['id']: m for m in v1['net_members']}
    assert members[f'{NET}/risk-eu']['state'] == 'self'
    assert members[f'{NET}/cust-na']['state'] == 'alive' and 'catalog' in members[f'{NET}/cust-na']['features']
    quals = {p['qualified_name']: p for p in v1['net_proxies']}
    assert quals['acme-net__cust-na__lookup']['contract_hash'].startswith('sha-256:')
    assert quals['acme-net__cust-na__lookup']['host'] == 'cust-na'
    assert v1['net_keys'] == [{'id': f'{NET}/cust-na', 'net': NET, 'home': 'cust-na', 'records': 3, 'revoked': 1,
                               'disabled': 0, 'version': 7, 'unusable': None}]
    assert 'sja_' not in json.dumps(v1)
    # treasury-na goes down: it turns suspect, then dead, and its proxies are withdrawn
    conn.down.add('https://treasury-na.test')
    for _ in range(8):
        node(a).tick()
        a.catalogs.maybe_sync()
    v2 = core.collect_net(a)
    d = core.diff(dict(v1, users=[], roles=[], api_keys=[], tools=[]), dict(v2, users=[], roles=[], api_keys=[],
                                                                            tools=[]))
    changed = {x['id'] for x in d['net_members']['changed']}
    gone = set(d['net_proxies']['removed']) | {x['qualified_name'] for x in d['net_proxies']['changed']}
    assert f'{NET}/treasury-na' in changed or f'{NET}/treasury-na' in d['net_members']['removed']
    assert any(q.startswith('acme-net__treasury-na__') for q in gone), d['net_proxies']
    assert any(line.startswith(('~ net_members', '- net_members')) for line in core.diff_lines(d))


def test_no_net_no_net_view():
    assert core.collect_net(type('S', (), {'shared': type('X', (), {'enabled': False})()})()) == {
        'net_members': [], 'net_proxies': [], 'net_keys': []}


def test_restore_ignores_the_net_view():
    import inspect
    src = inspect.getsource(core.restore)
    assert 'net_' not in src                    # the net is learned again from peers, never restored
