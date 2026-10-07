"""
SAJHA Net membership (protocol §5.2, §9) with participants in one process: GOS-01 to GOS-14,
NAME-06, NAME-07, NAME-09, NAME-11, REV-01 and the clean-leave, crash and restart paths.
"""

import json
import os

import pytest

from sajha.net import crypto, httpsig
from sajha.net.membership import KEEP, RECORD, REPLACE, STATE, PeerCache, decide_merge, dissemination_limit
from sajha.net.models import MemoryKV
from tests.net.harness import TestNet


@pytest.fixture
def net(tmp_path):
    return TestNet(tmp_path)


def three(n):
    a = n.add('risk-eu', founder=True, ca_node=True)
    b = n.add('cust-na', seeds=[n.url('risk-eu')])
    c = n.add('treasury-na', seeds=[n.url('risk-eu')])
    n.rounds(4)
    return a, b, c


def _sig(node, to, path, body):
    raw = json.dumps(body, separators=(',', ':')).encode()
    return httpsig.sign_request(node.signer, 'POST', path, '', {}, raw, node.net, node.name, to, now=node.clock()), raw


# ── GOS-01 / GOS-08: ping, sync, join through one seed ─────────────────

def test_gos_01_ping_gets_a_signed_ack_and_updates_merge(net):
    a = net.add('risk-eu', founder=True)
    b = net.add('cust-na', founder=True)
    c = net.add('treasury-na', founder=True)
    h, raw = _sig(a, 'cust-na', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 5, 'updates': [a.own_entry(),
                                                                                                c.own_entry()]})
    r = net.participants['cust-na'].handle('POST', '/sajhanet/v1/gossip/ping', '', h, raw)
    assert r.status == 200
    v = httpsig.verify_response(a.trust, 'risk-eu', 'cust-na', 200, r.headers, r.body,
                                httpsig.request_signature_bytes(h), now=net.clock())
    ack = json.loads(r.body)
    assert v.sender == 'cust-na' and ack['type'] == 'ack' and ack['seq'] == 5
    assert ack['updates'][0]['record']['name'] == 'cust-na'
    assert {m['name'] for m in b.members()} == {'risk-eu', 'treasury-na'}


def test_gos_08_join_returns_the_full_list_with_retained_dead_and_left(net):
    a, b, c = three(net)
    assert net.view('cust-na') == {'risk-eu': 'alive', 'treasury-na': 'alive'}
    assert net.view('treasury-na') == {'risk-eu': 'alive', 'cust-na': 'alive'}
    c.leave()
    net.kill('cust-na')
    net.rounds(20, only=['risk-eu', 'treasury-na'])
    assert net.view('risk-eu')['cust-na'] == 'dead' and net.view('risk-eu')['treasury-na'] == 'left'
    d = net.add('eq-asia', seeds=[net.url('risk-eu')])
    assert d.try_join()
    assert net.view('eq-asia') == {'risk-eu': 'alive', 'cust-na': 'dead', 'treasury-na': 'left'}


# ── GOS-02: ping-req ───────────────────────────────────────────────────

def test_gos_02_ping_req(net):
    a, b, c = three(net)
    p = net.participants['cust-na']
    h, raw = _sig(a, 'cust-na', '/sajhanet/v1/gossip/ping-req',
                  {'type': 'ping-req', 'seq': 1, 'target': 'treasury-na', 'updates': [], 'url': 'https://evil.test'})
    r = p.handle('POST', '/sajhanet/v1/gossip/ping-req', '', h, raw)
    assert r.status == 200 and json.loads(r.body)['reachable'] is True
    net.kill('treasury-na')
    h, raw = _sig(a, 'cust-na', '/sajhanet/v1/gossip/ping-req', {'type': 'ping-req', 'seq': 2, 'target': 'treasury-na',
                                                                 'updates': []})
    assert json.loads(p.handle('POST', '/sajhanet/v1/gossip/ping-req', '', h, raw).body)['reachable'] is False
    h, raw = _sig(a, 'cust-na', '/sajhanet/v1/gossip/ping-req', {'type': 'ping-req', 'seq': 3, 'target': 'nobody-here',
                                                                 'updates': []})
    r = p.handle('POST', '/sajhanet/v1/gossip/ping-req', '', h, raw)
    assert r.status == 400 and json.loads(r.body)['reason'] == 'unknown_member'


def test_indirect_probe_keeps_a_member_alive_across_one_broken_link(net):
    a, b, c = three(net)
    real = net.connector.routes[net.url('treasury-na')]

    def only_from_cust_na(method, path, query, headers, body, secure):
        if headers.get('sajha-net-from') == 'risk-eu':
            from sajha.net.plugins import PeerUnreachable
            raise PeerUnreachable('link down')
        return real(method, path, query, headers, body, secure)
    net.connector.routes[net.url('treasury-na')] = only_from_cust_na
    assert a.probe(a.member('treasury-na')) is True
    assert a.member('treasury-na')['state'] == 'alive'


# ── GOS-03 / GOS-04 / GOS-11: suspicion, refutation, dead probing ──────

def test_gos_03_suspect_then_dead(net):
    a, b, c = three(net)
    net.kill('treasury-na')
    a.probe(a.member('treasury-na'))
    assert a.member('treasury-na')['state'] == 'suspect'
    net.clock.advance(5)
    a.tick()
    assert a.member('treasury-na')['state'] == 'suspect'
    net.clock.advance(6)
    a.tick()
    assert a.member('treasury-na')['state'] == 'dead'
    assert ('risk-eu', 'member_state') in [(n, k) for n, k, _ in net.events]


def test_gos_04_false_suspicion_is_refuted(net):
    a, b, c = three(net)
    inc = c.incarnation()
    m = a.member('treasury-na')
    a._set_state('treasury-na', 'suspect')
    net.rounds(6)
    assert c.incarnation() > inc
    for who in ('risk-eu', 'cust-na'):
        assert net.view(who)['treasury-na'] == 'alive'
    assert m is not None


def test_gos_11_dead_member_probed_and_rejoins(net):
    a, b, c = three(net)
    net.kill('treasury-na')
    net.rounds(25, only=['risk-eu', 'cust-na'])
    assert net.view('risk-eu')['treasury-na'] == 'dead'
    net.revive('treasury-na')
    net.rounds(40, only=['risk-eu', 'cust-na'])          # treasury-na itself does nothing: peers find it
    assert net.view('risk-eu')['treasury-na'] == 'alive'
    assert net.view('cust-na')['treasury-na'] == 'alive'


# ── GOS-05: merge rules ──────────────────────────────────────────────

def _e(inc, seq, state, leaving=False, tag='x'):
    return {'record': {'incarnation': inc, 'seq': seq, 'leaving': leaving, 'tag': tag}, 'state': state}


@pytest.mark.parametrize('held, incoming, action, state', [
    (None, _e(5, 0, 'alive'), REPLACE, 'alive'),
    (_e(5, 0, 'alive'), _e(6, 0, 'alive'), REPLACE, 'alive'),
    (_e(5, 0, 'dead'), _e(6, 0, 'alive'), REPLACE, 'alive'),
    (_e(5, 0, 'alive'), _e(4, 9, 'dead'), KEEP, 'alive'),
    (_e(5, 0, 'alive'), _e(5, 0, 'suspect'), STATE, 'suspect'),
    (_e(5, 0, 'suspect'), _e(5, 0, 'alive'), KEEP, 'suspect'),
    (_e(5, 0, 'suspect'), _e(5, 0, 'dead'), STATE, 'dead'),
    (_e(5, 0, 'alive'), _e(5, 1, 'alive'), RECORD, 'alive'),
    (_e(5, 2, 'alive', tag='a'), _e(5, 2, 'alive', tag='b'), KEEP, 'alive'),
    (_e(5, 0, 'alive'), _e(5, 0, 'left'), KEEP, 'alive'),                 # left without leaving: ignored
    (_e(5, 0, 'alive'), _e(5, 1, 'left', leaving=True), RECORD, 'left'),
    (_e(5, 1, 'left', leaving=True), _e(5, 1, 'dead', leaving=True), KEEP, 'left'),
])
def test_gos_05_merge_rules(held, incoming, action, state):
    a, _rec, st = decide_merge(held, incoming)
    assert (a, st) == (action, state)


def test_dissemination_bound():
    assert dissemination_limit(1) == 3 and dissemination_limit(3) == 6 and dissemination_limit(10) == 12


# ── GOS-06 / GOS-07: records signed by their subjects; leave ───────────

def test_gos_06_records_must_be_signed_by_their_subject(net):
    a = net.add('risk-eu', founder=True)
    b = net.add('cust-na', founder=True)
    forged = dict(b.own_entry())
    rec = dict(forged['record'], url='https://evil.test')
    forged = dict(forged, record=rec, signature=crypto.sign_record('member', rec, b.signer.key, b.signer.keyid))
    assert not a.merge(forged), 'url host not in the certificate'
    e = a.own_entry()
    other = dict(b.own_entry(), signature=crypto.sign_record('member', b.own_entry()['record'], a.signer.key,
                                                             a.signer.keyid), certificate=e['certificate'])
    assert not a.merge(other) and a.member('cust-na') is None, 'signed by someone else'
    assert a.merge(b.own_entry())


def test_gos_07_leave(net):
    a, b, c = three(net)
    bogus = dict(c.own_entry(), state='left')
    assert not b.merge(bogus) or b.member('treasury-na')['state'] != 'left'
    h, raw = _sig(a, 'cust-na', '/sajhanet/v1/membership/leave', {'type': 'leave', 'entry': dict(c.own_entry(),
                                                                                                state='left')})
    r = net.participants['cust-na'].handle('POST', '/sajhanet/v1/membership/leave', '', h, raw)
    assert r.status == 400, 'a leave about another member is refused'
    told = c.leave()
    assert told == 2
    assert b.member('treasury-na')['state'] == 'left' and a.member('treasury-na')['state'] == 'left'


# ── GOS-09: incarnations across restarts ─────────────────────────────

def test_gos_09_incarnation_after_restart(net):
    a = net.add('risk-eu', founder=True)
    first = a.incarnation()
    a2 = net.add('risk-eu', founder=True, key=a.signer.key, cert=a.signer.chain[0])
    assert a2.incarnation() > first
    os.unlink(a2.cfg.peer_cache.path)                       # persisted state lost
    net.clock.advance(1)
    a3 = net.add('risk-eu', founder=True, key=a.signer.key, cert=a.signer.chain[0])
    assert a3.incarnation() > a2.incarnation()
    net.clock.advance(-3600)                                # clock set back
    a4 = net.add('risk-eu', founder=True, key=a.signer.key, cert=a.signer.chain[0])
    assert a4.incarnation() == a3.incarnation() + 1


# ── GOS-10 / REV-01: revocation ──────────────────────────────────────

def test_gos_10_revoked_member_dropped_and_rev_01(net):
    a, b, c = three(net)
    doc = net.ca.revoke(instance='treasury-na')
    assert a.accept_revocations(doc)
    assert a.member('treasury-na') is None
    net.rounds(4, only=['risk-eu', 'cust-na'])
    assert b.revocation_list()['version'] == doc['version']
    assert b.member('treasury-na') is None
    # REV-01: bad signature, other net, lower version are ignored; any member serves the newest
    bad = dict(doc, version=doc['version'] + 5)
    assert not b.accept_revocations(bad)
    other = dict(doc, net='other-net')
    assert not b.accept_revocations(other)
    assert not b.accept_revocations(net.ca.revocation_list() if False else doc)
    h = httpsig.sign_request(b.signer, 'GET', '/sajhanet/v1/revocations', '', {}, b'', 'acme-net', 'cust-na',
                             'risk-eu', now=net.clock())
    r = net.participants['risk-eu'].handle('GET', '/sajhanet/v1/revocations', '', h, b'')
    assert r.status == 200 and json.loads(r.body)['version'] == doc['version']
    # a revoked participant cannot ping
    hh, raw = _sig(c, 'risk-eu', '/sajhanet/v1/gossip/ping', {'type': 'ping', 'seq': 1, 'updates': []})
    r = net.participants['risk-eu'].handle('POST', '/sajhanet/v1/gossip/ping', '', hh, raw)
    assert r.status == 403 and json.loads(r.body)['reason'] == 'instance_revoked'


# ── GOS-12 / GOS-13 / GOS-14: seeds, restarts, operator hints ──────────

def test_gos_12_no_seeds_is_a_net_of_one_that_grows_without_restart(tmp_path):
    n = TestNet(tmp_path)
    founder = n.add('risk-eu', founder=True)
    assert founder.try_join() and founder.joined()
    lonely = n.add('cust-na')                               # no seeds, not marked founder: a net of one
    assert lonely.try_join() and lonely.joined()
    st = lonely.status()
    assert st['single_member'] and not st.get('config_error') and not st.get('backoff')
    kinds = [k for w, k, _ in n.events if w == 'cust-na']
    assert 'config_error' not in kinds and 'not_joined' not in kinds
    sent, real = [], n.connector.send
    n.connector.send = lambda *a, **k: sent.append(a) or real(*a, **k)
    n.rounds(5, only={'cust-na'})                           # nobody to talk to: no join retries, no gossip
    n.connector.send = real
    assert lonely.joined() and lonely.members() == [] and sent == []
    # a peer contacts it later, through it as a seed: the net of one grows without a restart
    late = n.add('treasury-na', seeds=[n.url('cust-na')])
    assert late.try_join()
    n.rounds(3)
    assert n.view('cust-na').get('treasury-na') == 'alive' and n.view('treasury-na').get('cust-na') == 'alive'


def test_gos_12_other_nets_join_normally(tmp_path):
    m = TestNet(tmp_path / 'm', net='net-m')
    nn = TestNet(tmp_path / 'n', net='net-n', clock=m.clock, connector=m.connector)
    os.makedirs(tmp_path / 'm', exist_ok=True)
    os.makedirs(tmp_path / 'n', exist_ok=True)
    m.add('hub-m', founder=True)
    nn.add('hub-n', founder=True)
    bad = m.add('server', seeds=[m.url('nowhere')], route_as='server')   # net-m's only seed is down
    m.kill('nowhere')
    good = nn.add('server', seeds=[nn.url('hub-n')], route_as='server')
    assert not bad.try_join() and good.try_join()
    assert ('server', 'not_joined') in [(w, k) for w, k, _ in m.events]


def test_gos_13_restart_seeds_then_saved_peers_then_backoff(net):
    a, b, c = three(net)
    c.save_peers(force=True)
    net.kill('risk-eu')                                     # the only seed is down
    c2 = net.add('treasury-na', seeds=[net.url('risk-eu')], key=c.signer.key, cert=c.signer.chain[0])
    assert c2.try_join(), 'joined through the saved peer list'
    assert c2.status()['joined_via'] == net.url('cust-na')
    # entries older than max_age_days are skipped
    doc = PeerCache(c2.cfg.peer_cache.path).load()
    for m in doc['members']:
        m['last_seen'] = net.clock() - 8 * 86400
    PeerCache(c2.cfg.peer_cache.path).save(doc)
    c3 = net.add('treasury-na', seeds=[net.url('risk-eu')], key=c.signer.key, cert=c.signer.chain[0])
    assert not c3.try_join()
    st = c3.status()
    assert st['backoff'] >= 5 and st['next_join_at'] > net.clock()
    assert ('treasury-na', 'not_joined') in [(w, k) for w, k, _ in net.events]


def test_gos_13_saved_member_whose_certificate_no_longer_verifies_is_refused(net):
    a, b, c = three(net)
    c.save_peers(force=True)
    net.kill('risk-eu')
    other_ca = TestNet(net.tmp, clock=net.clock)
    key, cert = other_ca.issue('cust-na')                   # cust-na re-keyed under another CA
    impostor = net.add('cust-na', founder=True, key=key, cert=cert, start=False)
    impostor.trust = other_ca.add('x', founder=True).trust
    impostor.start()
    c2 = net.add('treasury-na', seeds=[net.url('risk-eu')], key=c.signer.key, cert=c.signer.chain[0])
    assert not c2.try_join()


def test_gos_14_operator_hint_is_an_ordinary_signed_sync(net):
    a = net.add('risk-eu', founder=True)
    b = net.add('cust-na', founder=True)
    x = b.sync(net.url('risk-eu'), httpsig.ANY, reason='join')
    assert x.sender == 'risk-eu' and b.member('risk-eu') is not None
    foreign = TestNet(net.tmp, clock=net.clock, connector=net.connector)
    stranger = foreign.add('stranger', founder=True)
    from sajha.net.node import ResponseInvalid
    with pytest.raises(ResponseInvalid) as e:
        b.sync(foreign.url('stranger'), httpsig.ANY, reason='join')
    assert e.value.reason == 'certificate_invalid'
    assert b.member('stranger') is None and stranger is not None


# ── NAME-06 / NAME-07 / NAME-09 / NAME-11: name ownership ──────────────

def test_name_06_07_held_name_refused_loudly_and_not_retried(net):
    a, b, c = three(net)
    for state_change in (None, 'dead', 'left'):
        if state_change == 'dead':
            net.kill('cust-na')
            net.rounds(25, only=['risk-eu', 'treasury-na'])
            assert net.view('risk-eu')['cust-na'] == 'dead'
        if state_change == 'left':
            b.leave()
            assert net.view('risk-eu')['cust-na'] == 'left'
        key, cert = net.issue('cust-na', host='cust-na-2.test')
        imp = net.add('cust-na', seeds=[net.url('risk-eu')], key=key, cert=cert, route_as=f'imp-{state_change}',
                      base_url=f'https://cust-na-2.test')
        assert not imp.try_join()
        r = imp.refused()
        assert r and r['holder_thumbprint'] == b.signer.keyid and r['holder_state'] == (state_change or 'alive')
        assert ('cust-na', 'name_conflict') in [(w, k) for w, k, _ in net.events]
        assert all(m['record']['url'] != 'https://cust-na-2.test' for m in a.members() + c.members())
        n_calls = len(net.events)
        imp.tick()
        imp.tick()
        assert not imp.joined() and len([e for e in net.events[n_calls:] if e[1] == 'not_joined']) == 0
        if state_change == 'left':
            net.revive('cust-na')


def test_name_07_refusal_persists_until_config_or_certificate_change(net):
    a, b, c = three(net)
    key, cert = net.issue('cust-na', host='cust-na-2.test')
    imp = net.add('cust-na', seeds=[net.url('risk-eu')], key=key, cert=cert, route_as='imp',
                  base_url='https://cust-na-2.test')
    assert not imp.try_join() and imp.refused()
    again = net.add('cust-na', seeds=[net.url('risk-eu')], key=key, cert=cert, route_as='imp',
                    base_url='https://cust-na-2.test')
    assert again.refused(), 'a restart with the same configuration and certificate stays refused'
    key2, cert2 = net.issue('cust-eu', host='cust-na-2.test')
    renamed = net.add('cust-eu', seeds=[net.url('risk-eu')], key=key2, cert=cert2, route_as='imp',
                      base_url='https://cust-na-2.test')
    assert not renamed.refused() and renamed.try_join()


def test_name_09_restart_and_renewal_are_not_conflicts(net):
    a, b, c = three(net)
    b2 = net.add('cust-na', seeds=[net.url('risk-eu')], key=b.signer.key, cert=b.signer.chain[0])
    assert b2.try_join()
    old = b2.signer.keyid
    b2.renew(ca_url=net.url('risk-eu'), ca_name='risk-eu')
    assert b2.signer.keyid != old and crypto.renews_of(b2.signer.chain[0]) == crypto.serial_hex(b.signer.chain[0])
    net.rounds(4)
    assert net.view('treasury-na')['cust-na'] == 'alive'
    assert a.lineage_conflict('cust-na', b2.signer.chain[0]) is None
    key, cert = net.issue('cust-na')                        # same CA, outside the lineage
    assert a.lineage_conflict('cust-na', cert) is not None
    net.ca.revoke(serial=crypto.serial_hex(b.signer.chain[0]))
    a.accept_revocations(net.ca.revocation_list())
    assert a.lineage_conflict('cust-na', cert) is not None, 'one lineage serial is still unrevoked'
    net.ca.revoke(serial=crypto.serial_hex(b2.signer.chain[0]))
    a.accept_revocations(net.ca.revocation_list())
    assert a.lineage_conflict('cust-na', cert) is None, 'every certificate of the lineage is revoked'


def test_name_11_two_nets_two_names(tmp_path):
    m = TestNet(tmp_path, net='net-m')
    nn = TestNet(tmp_path, net='net-n', clock=m.clock, connector=m.connector)
    m.add('hub', founder=True, route_as='hub-m')
    nn.add('hub', founder=True, route_as='hub-n')
    sm = m.add('risk-eu', seeds=['https://hub-m.test'], route_as='server')
    sn = nn.add('risk-eu-p', seeds=['https://hub-n.test'], route_as='server')
    assert sm.try_join() and sn.try_join()
    # a name held in M does not block the same name in N; a conflict in M leaves N alone
    key, cert = nn.issue('risk-eu', host='other.test')
    other = nn.add('risk-eu', seeds=['https://hub-n.test'], key=key, cert=cert, route_as='other',
                   base_url='https://other.test')
    assert other.try_join()
    key, cert = m.issue('risk-eu', host='other2.test')
    imp = m.add('risk-eu', seeds=['https://hub-m.test'], key=key, cert=cert, route_as='other2',
                base_url='https://other2.test')
    assert not imp.try_join() and imp.refused()
    assert sn.joined() and not sn.refused()


# ── static membership (plug-in) ──────────────────────────────────────

def test_static_membership_syncs_with_its_peers(net):
    a = net.add('risk-eu', founder=True)
    b = net.add('cust-na', founder=True, static=True, static_peers=[net.url('risk-eu')])
    b.tick()
    assert b.member('risk-eu') is not None and a.member('cust-na') is not None
