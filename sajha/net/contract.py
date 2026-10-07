"""
Contract checks for SAJHA Net plug-ins (design §5.4): every implementation of an interface,
shipped or third-party, must pass the check of its kind before it is selected in production.

``check(kind, factory)`` builds instances with ``factory()`` and raises ``AssertionError`` naming
the broken rule. tests/net/test_net_plugins.py runs it against every registered implementation.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import tempfile
from typing import Any, Callable, Dict

from sajha.net import crypto
from sajha.net.models import NetConfig
from sajha.net.plugins import (Decision, HostOption, INTERFACES, PeerResponse, PeerUnreachable)


def _membership(make):
    p = make()
    assert isinstance(p.gossip, bool), 'gossip must be a bool'
    cfg = NetConfig(name='acme-net', static_peers=['https://a.test'])
    for fn in (p.peers, p.discover):
        out = fn(cfg)
        assert isinstance(out, list) and all(isinstance(u, str) for u in out), f'{fn.__name__}() returns a list of URLs'
    if not p.gossip:
        assert p.peers(cfg), 'a non-gossip membership must name the peers it contacts'


def _admission(make):
    p = make()
    net = 'acme-net'
    ca_key, ca_cert = crypto.generate_key(), None
    ca_cert = crypto.make_ca_certificate(ca_key, net)
    key = crypto.generate_key()
    if getattr(p, 'manual', False):
        cert = crypto.self_signed_certificate(key, net, 'risk-eu', 'risk-eu.test')
        th = crypto.thumbprint(crypto.cert_der(cert))
        t = p.trust(net, NetConfig(name=net), None, lambda: None, lambda: [th])
        t.check_chain([cert], cert.not_valid_before_utc.timestamp() + 120)
        other = crypto.self_signed_certificate(crypto.generate_key(), net, 'risk-eu', 'risk-eu.test')
        try:
            t.check_chain([other], other.not_valid_before_utc.timestamp() + 120)
        except crypto.CryptoError:
            pass
        else:
            raise AssertionError('an unpinned certificate must be refused')
        return
    cert = crypto.issue_certificate(ca_key, ca_cert, key.public_key(), net, 'risk-eu', 'risk-eu.test')
    serial = crypto.serial_hex(cert)
    rl = {'revoked': [{'serial': serial, 'revoked_at': '2026-10-07T00:00:00Z'}]}
    t = p.trust(net, NetConfig(name=net), ca_cert, lambda: rl, lambda: [])
    assert t.net == net, 'the trust names its net'
    now = cert.not_valid_before_utc.timestamp() + 120
    t.check_chain([cert], now)
    assert t.revocation(serial, 'risk-eu') == 'certificate_revoked'
    foreign_key = crypto.generate_key()
    foreign = crypto.make_ca_certificate(foreign_key, net)
    bad = crypto.issue_certificate(foreign_key, foreign, key.public_key(), net, 'risk-eu', 'risk-eu.test')
    try:
        t.check_chain([bad], now)
    except crypto.CryptoError as e:
        assert e.reason == 'certificate_invalid'
    else:
        raise AssertionError('a certificate from another CA must be refused')


def _connector(make):
    p = make()
    try:
        r = p.send('POST', 'https://unreachable.invalid/sajhanet/v1/gossip/ping', {'content-type': 'application/json'},
                   b'{}', 0.2)
    except PeerUnreachable:
        return
    assert isinstance(r, PeerResponse) and isinstance(r.status, int) and isinstance(r.body, bytes), \
        'send() returns a PeerResponse or raises PeerUnreachable'


def _identity(make):
    p = make()
    h = p.outbound_headers(None)
    assert isinstance(h, dict)
    out = p.resolve({}, 'risk-eu')
    assert out is None or isinstance(out, dict)


def _catalog(make):
    p = make()
    tools = p.tools('acme-net')
    assert isinstance(tools, list) and all(isinstance(t, dict) for t in tools)


def _keys(make):
    p = make()
    rec = {'type': 'key', 'net': 'acme-net', 'key_id': 'k1', 'key_hash': 'a' * 64, 'home_instance': 'risk-eu',
           'version': 2}
    assert p.put(rec) is True
    assert p.put(dict(rec, version=1)) is False, 'an older version is ignored'
    assert p.put(dict(rec, home_instance='cust-na', version=9)) is False, 'another home cannot overwrite a record'
    assert p.by_hash('acme-net', 'a' * 64)['key_id'] == 'k1'
    assert p.by_hash('other-net', 'a' * 64) is None, 'records of one net are not found in another'
    assert p.version('acme-net', 'risk-eu') == 2
    assert [r['version'] for r in p.since('acme-net', 'risk-eu', 0)] == [2]
    assert p.since('acme-net', 'risk-eu', 2) == []
    assert p.put(dict(rec, version=2, name='re-signed'), force=True) is True, 'force replaces an equal version'
    assert p.put(dict(rec, home_instance='cust-na', version=9), force=True) is False, 'never another home'
    assert [r['key_id'] for r in p.find('acme-net', 'a' * 64)] == ['k1']
    p.mark('acme-net', 'risk-eu', 'left')
    assert p.marked('acme-net', 'risk-eu') == 'left'
    p.mark('acme-net', 'risk-eu', None)
    assert p.marked('acme-net', 'risk-eu') is None
    signed = dict(rec, key_id='k2', key_hash='b' * 64, version=3, signature={'alg': 'ed25519', 'keyid': 'T' * 43,
                                                                             'sig': 'x'})
    assert p.put(signed) is True
    assert p.discard_signed('acme-net', 'T' * 43) == ['risk-eu']
    assert p.by_hash('acme-net', 'b' * 64) is None, 'records of a revoked certificate are discarded'


def _rules(make):
    p = make()
    d = p.decide('export', {'tool': 'var_calc', 'peer': 'cust-na'})
    assert isinstance(d, Decision) and isinstance(d.allow, bool)


def _snapshots(make):
    p = make()
    with tempfile.TemporaryDirectory() as d:
        if hasattr(p, 'directory'):
            p.directory = d
        p.write('s1.json', b'{}')
        assert 's1.json' in p.list()
        assert p.delete('s1.json') is True and 's1.json' not in p.list()


def _routing(make):
    p = make()
    hosts = [HostOption('b-host'), HostOption('a-host', latency_ms=5), HostOption('local', local=True)]
    out = p.order('var_calc', hosts, ['a-host'])
    names = [h.instance for h in out]
    assert len(names) == len(set(names)), 'no host twice'
    assert set(names) <= {h.instance for h in hosts}, 'only offered hosts'
    assert p.order('var_calc', hosts, ['a-host']) == out, 'the order is stable'
    if names:
        assert names[0] == 'a-host', 'a preferred host comes first'


CHECKS: Dict[str, Callable[[Callable[[], Any]], None]] = {
    'membership': _membership, 'admission': _admission, 'connector': _connector, 'identity': _identity,
    'catalog_source': _catalog, 'key_directory_store': _keys, 'rules': _rules, 'snapshot_sink': _snapshots,
    'routing': _routing,
}
assert set(CHECKS) == set(INTERFACES), 'every plug-in kind has a contract check'


def check(kind: str, factory: Callable[[], Any]) -> None:
    CHECKS[kind](factory)
