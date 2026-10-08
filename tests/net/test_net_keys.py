# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net key directory and block publication in one process (protocol §11, §12): KEY-01 to KEY-05,
REC-01 for the records SAJHA signs, NET-03 and NET-06 for key records and blocks documents, BLK-01,
and the usability checks of §15.3 (CALL-02, CALL-03 at the record level).
"""

import json

import pytest

from sajha.net import blocks as nblocks
from sajha.net import crypto, httpsig, keydir
from sajha.net.plugins import MemoryKeyDirectory
from tests.net.harness import TestNet

RAW = {'alice': 'sja_' + 'a1' * 24, 'bob': 'sja_' + 'b2' * 24}


def key(kid, user, raw, **kw):
    out = {'key_id': kid, 'key_prefix': raw[:8], 'name': f'{user} laptop', 'key_hash': keydir.key_hash(raw),
           'owner': {'user_id': f'id-{user}', 'user_name': user, 'display_name': user.title(), 'roles': ['analyst']},
           'enabled': True, 'expires_at': None, 'revoked_at': None, 'tool_access_mode': 'all',
           'tool_access_list': [], 'persistent': False}
    out.update(kw)
    return out


class Fabric:
    def __init__(self, tmp_path):
        self.n = TestNet(tmp_path)
        self.keys = {'risk-eu': {}, 'cust-na': {}, 'treasury-na': {}}
        self.dirs, self.blocks, self.pubs = {}, {}, {}
        for name, kw in (('risk-eu', dict(founder=True, ca_node=True)), ('cust-na', dict(seeds=[self.n.url('risk-eu')])),
                         ('treasury-na', dict(seeds=[self.n.url('risk-eu')]))):
            node = self.n.add(name, start=False, **kw)
            self.blocks[name] = [0, []]
            self.dirs[name] = keydir.KeyDirectory(node, MemoryKeyDirectory(),
                                                  lambda nm=name: list(self.keys[nm].values()),
                                                  skip=lambda peer, nm=name: nblocks.blocked_entirely(
                                                      self.blocks[nm][1], self.n.clock(), peer)).install()
            self.pubs[name] = nblocks.BlockPublication(node, lambda nm=name: tuple(self.blocks[nm]),
                                                       skip=lambda peer, nm=name: nblocks.blocked_entirely(
                                                           self.blocks[nm][1], self.n.clock(), peer)).install()
            node.start()
        self.n.rounds(4)

    def node(self, name):
        return self.n.nodes[name]

    def store(self, name):
        return self.dirs[name].store


@pytest.fixture
def f(tmp_path):
    return Fabric(tmp_path)


def test_key_04_publish_records_tombstones_and_versions(f):
    d = f.dirs['risk-eu']
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])
    assert d.publish() == 1
    rec = f.store('risk-eu').by_hash('acme-net', keydir.key_hash(RAW['alice']))
    assert rec['version'] == 1 and rec['home_instance'] == 'risk-eu' and rec['net'] == 'acme-net'
    assert RAW['alice'] not in json.dumps(rec)                                 # never the raw key
    assert rec['key_hash'] == __import__('hashlib').sha256(RAW['alice'].encode()).hexdigest()
    assert not keydir.acceptance_error(rec, 'acme-net', 'risk-eu', d.node.signer.chain[0])   # REC-01
    assert d.publish() == 0                                                   # nothing changed, no version
    f.keys['risk-eu']['k1']['enabled'] = False
    assert d.publish() == 1 and d.own_version() == 2
    del f.keys['risk-eu']['k1']                                               # deleted: a tombstone
    d.publish()
    rec = f.store('risk-eu').by_hash('acme-net', keydir.key_hash(RAW['alice']))
    assert rec['revoked_at'] and rec['version'] == 3
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])               # a tombstone never comes back
    d.publish()
    assert f.store('risk-eu').by_hash('acme-net', keydir.key_hash(RAW['alice']))['revoked_at']
    assert f.node('risk-eu').own_entry()['record']['digests']['keys'] == d.own_version()


def test_key_01_02_delta_pull_paging_and_acceptance(f):
    for i in range(7):
        f.keys['risk-eu'][f'k{i}'] = key(f'k{i}', 'alice', f'sja_{i:048d}')
    f.dirs['risk-eu'].page = 3
    f.dirs['risk-eu'].publish()
    f.n.rounds(6)
    b = f.store('cust-na')
    assert b.version('acme-net', 'risk-eu') == 7
    assert [r['version'] for r in b.since('acme-net', 'risk-eu', 0)] == list(range(1, 8))
    # KEY-01 directly: ascending, paged with more / next_since
    x = f.node('cust-na').request(f.n.url('risk-eu'), '/sajhanet/v1/keys', {'since': 2, 'limit': 3}, 'risk-eu')
    assert [r['version'] for r in x.body['records']] == [3, 4, 5] and x.body['more'] and x.body['next_since'] == 5
    assert x.body['version'] == 7
    # KEY-02: from someone other than the home, with a bad signature, or older: ignored
    rec = b.since('acme-net', 'risk-eu', 0)[0]
    cust_cert = f.node('cust-na').signer.chain[0]
    assert keydir.acceptance_error(rec, 'acme-net', 'cust-na', cust_cert) == 'not_home'
    forged = dict(rec, enabled=False)
    assert keydir.acceptance_error(forged, 'acme-net', 'risk-eu', f.node('risk-eu').signer.chain[0]) == \
        'signature_invalid'
    assert keydir.acceptance_error(rec, 'other-net', 'risk-eu', f.node('risk-eu').signer.chain[0]) == 'net_mismatch'
    assert b.put(dict(rec)) is False                                          # equal version: ignored


def test_forged_record_from_another_member_is_ignored(f):
    """A member serving records that name another home (§11.2): nothing is stored."""
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])
    f.dirs['risk-eu'].publish()
    t = f.node('treasury-na')
    evil = keydir.sign({'type': 'key', 'net': 'acme-net', 'key_id': 'k-evil', 'home_instance': 'risk-eu',
                        **{k: v for k, v in key('k-evil', 'admin', RAW['bob']).items() if k != 'key_id'},
                        'version': 99, 'updated_at': crypto.rfc3339(f.n.clock())}, t.signer.key, t.signer.keyid)
    f.store('treasury-na').put(evil, force=True)
    f.dirs['treasury-na'].serve_keys = lambda data, v: {'home_instance': 'treasury-na', 'version': 99,
                                                        'records': [evil], 'more': False}
    t.handlers['/sajhanet/v1/keys'] = f.dirs['treasury-na'].serve_keys
    m = f.node('cust-na').member('treasury-na')
    assert f.dirs['cust-na'].pull(m, since=0) == 0
    assert f.store('cust-na').by_hash('acme-net', keydir.key_hash(RAW['bob'])) is None


def test_key_03_digest_root_and_repair(f):
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])
    f.keys['risk-eu']['k2'] = key('k2', 'bob', RAW['bob'])
    f.dirs['risk-eu'].publish()
    f.n.rounds(4)
    recs = f.store('cust-na').since('acme-net', 'risk-eu', 0)
    pairs = sorted([[r['key_id'], r['version']] for r in recs])
    import hashlib
    from sajha.net import jcs
    assert keydir.digest_root(recs) == crypto.b64url(hashlib.sha256(jcs.canonicalize(pairs)).digest())
    m = f.node('cust-na').member('risk-eu')
    assert f.dirs['cust-na'].compare(m) is True
    # a record lost locally (missed update) is repaired by the digest comparison
    f.store('cust-na')._by.pop(('acme-net', 'k1'))
    assert f.dirs['cust-na'].compare(m) is False
    assert f.store('cust-na').by_hash('acme-net', keydir.key_hash(RAW['alice'])) is not None


def test_key_05_revoked_certificate_discards_and_repulls(f):
    f.keys['cust-na']['c1'] = key('c1', 'carol', RAW['bob'])
    f.dirs['cust-na'].publish()
    f.n.rounds(4)
    a = f.store('risk-eu')
    assert a.by_hash('acme-net', keydir.key_hash(RAW['bob']))
    # cust-na renews with a new key; its records are re-signed; then the old serial is revoked
    old_serial = crypto.serial_hex(f.node('cust-na').signer.chain[0])
    f.node('cust-na').renew(ca_url=f.n.url('risk-eu'), ca_name='risk-eu')
    f.dirs['cust-na'].publish()
    assert f.store('cust-na').by_hash('acme-net', keydir.key_hash(RAW['bob']))['signature']['keyid'] == \
        f.node('cust-na').signer.keyid
    doc = f.n.ca.revoke(serial=old_serial)
    assert f.node('risk-eu').accept_revocations(doc)
    assert a.by_hash('acme-net', keydir.key_hash(RAW['bob'])) is None          # discarded at once
    f.n.rounds(3)
    again = a.by_hash('acme-net', keydir.key_hash(RAW['bob']))                 # re-pulled from 0
    assert again and again['signature']['keyid'] == f.node('cust-na').signer.keyid


def test_usability_reasons_and_departed_homes(f):
    now = f.n.clock()
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])
    f.dirs['risk-eu'].publish()
    f.n.rounds(4)
    d = f.dirs['cust-na']
    rec = d.store.by_hash('acme-net', keydir.key_hash(RAW['alice']))
    assert keydir.check_usable(rec, 'risk-eu', now, d.home_usable) is None
    assert keydir.check_usable(None, 'risk-eu', now) == 'key_unknown'
    assert keydir.check_usable(dict(rec, enabled=False), 'risk-eu', now) == 'key_disabled'
    assert keydir.check_usable(dict(rec, expires_at=crypto.rfc3339(now - 1)), 'risk-eu', now) == 'key_expired'
    assert keydir.check_usable(dict(rec, revoked_at=crypto.rfc3339(now)), 'risk-eu', now) == 'key_revoked'
    assert keydir.check_usable(rec, 'treasury-na', now) == 'key_not_from_home'
    # the home leaves: its records are kept, marked, and refuse every forwarded key
    f.node('risk-eu').leave()
    f.n.rounds(2, only=['cust-na', 'treasury-na'])
    rec = d.store.by_hash('acme-net', keydir.key_hash(RAW['alice']))
    assert rec is not None and rec.get('unusable') == 'left'
    assert keydir.check_usable(rec, 'risk-eu', now, d.home_usable) == 'key_revoked'


def test_net_06_records_of_one_net_mean_nothing_in_another(f):
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])
    f.dirs['risk-eu'].publish()
    f.n.rounds(4)
    assert f.store('cust-na').by_hash('acme-net', keydir.key_hash(RAW['alice']))
    assert f.store('cust-na').by_hash('other-net', keydir.key_hash(RAW['alice'])) is None


def test_blk_01_blocks_document_signed_versioned_expired_omitted_and_pulled(f):
    now = f.n.clock()
    f.blocks['cust-na'] = [2, [
        {'id': 'b1', 'level': 'inbound', 'target_instance': 'risk-eu', 'reason': 'audit', 'set_at': crypto.rfc3339(now)},
        {'id': 'b2', 'level': 'user', 'target_instance': 'risk-eu', 'user': 'alice@risk-eu',
         'set_at': crypto.rfc3339(now), 'expires_at': crypto.rfc3339(now - 5)},
        {'id': 'b3', 'level': 'tool', 'direction': 'inbound', 'target_instance': '*', 'tool': 'wire_*',
         'set_at': crypto.rfc3339(now), 'reason': 'secret', 'withhold_reason': True}]]
    c = f.node('cust-na')
    c.refresh_record()
    assert c.own_entry()['record']['digests']['blocks'] == 2
    doc = f.pubs['cust-na'].serve({}, None)
    assert doc['version'] == 2 and [b['id'] for b in doc['blocks']] == ['b1', 'b3']
    assert 'reason' not in doc['blocks'][1] and 'direction' not in doc['blocks'][1]
    assert nblocks.acceptance_error(doc, 'acme-net', 'cust-na', c.signer.chain[0]) is None
    assert nblocks.acceptance_error(dict(doc, version=3), 'acme-net', 'cust-na', c.signer.chain[0]) == \
        'signature_invalid'
    assert nblocks.acceptance_error(doc, 'other-net', 'cust-na', c.signer.chain[0]) == 'net_mismatch'
    f.n.rounds(4)
    held = f.pubs['risk-eu'].peer_document('cust-na')
    assert held['version'] == 2
    seen = [d for n, k, d in f.n.events if n == 'risk-eu' and k == 'blocked_by_peer']
    assert seen and [b['id'] for b in seen[-1]['blocks']] == ['b1', 'b3']
    # matching helpers
    bl = f.blocks['cust-na'][1]
    assert nblocks.match_inbound(bl, now, 'risk-eu')['id'] == 'b1'
    assert nblocks.match_inbound(bl, now, 'treasury-na') is None
    assert nblocks.match_user(bl, now, 'alice@risk-eu') is None                # expired
    assert nblocks.match_tool(bl, now, 'treasury-na', 'wire_send')['id'] == 'b3'


def test_instance_block_ignores_key_updates(f):
    now = f.n.clock()
    f.blocks['cust-na'] = [1, [{'id': 'x', 'level': 'instance', 'target_instance': 'risk-eu',
                                'set_at': crypto.rfc3339(now)}]]
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])
    f.dirs['risk-eu'].publish()
    f.n.rounds(4)
    assert f.store('cust-na').by_hash('acme-net', keydir.key_hash(RAW['alice'])) is None
    assert f.store('treasury-na').by_hash('acme-net', keydir.key_hash(RAW['alice'])) is not None


def test_key_sync_failures_raise_an_event(f):
    f.keys['risk-eu']['k1'] = key('k1', 'alice', RAW['alice'])
    f.dirs['risk-eu'].publish()
    f.node('risk-eu').refresh_record()
    f.n.rounds(1, only=['risk-eu'])
    f.node('risk-eu').handlers['/sajhanet/v1/keys'] = lambda data, v: {'broken': True}
    f.node('cust-na').kv.set('kd:repull:risk-eu', True)              # pull now, whatever gossip has spread
    for _ in range(4):
        f.dirs['cust-na'].tick()
    assert any(k == 'key_sync_failed' and d['member'] == 'risk-eu' for n, k, d in f.n.events if n == 'cust-na')
    f.node('risk-eu').handlers['/sajhanet/v1/keys'] = f.dirs['risk-eu'].serve_keys
    f.dirs['cust-na'].tick()
    assert any(k == 'key_sync_ok' for n, k, d in f.n.events if n == 'cust-na')
