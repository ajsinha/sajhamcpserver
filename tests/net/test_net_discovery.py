# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Discovery sources (protocol §9.7; design §6.6 step 3; sajha/net/discovery.py).

Covers: the DNS SRV client (a query answered by a local UDP server, name compression, another query's
answer ignored); ``dns_srv`` ordering and default ports; ``kubernetes`` through SRV and its A-record
fallback; ``registry`` documents; only http(s) URLs, at most 64, cached for ``ttl_seconds``, a failing
source skipped; configuration problems; and a participant whose seeds are down joining through a
discovered address, as an ordinary signed sync (GOS-14's rules apply unchanged).
"""

from __future__ import annotations

import socket
import struct
import threading

import pytest

from sajha.net import discovery as dz
from tests.net.harness import TestNet


def srv_answer(qid, qname_wire, records):
    """A DNS response with SRV answers; the answers' names point back at the question (compression)."""
    msg = struct.pack('>HHHHHH', qid, 0x8180, 1, len(records), 0, 0) + qname_wire + struct.pack('>HH', 33, 1)
    for prio, weight, port, target in records:
        rdata = struct.pack('>HHH', prio, weight, port) + dz._qname(target)
        msg += b'\xc0\x0c' + struct.pack('>HHIH', 33, 1, 60, len(rdata)) + rdata
    return msg


def test_parse_srv_with_compression():
    qid, q = dz.query('_sajhanet._tcp.acme.example')
    msg = srv_answer(qid, q[12:-4], [(10, 5, 443, 'a.acme.example'), (5, 1, 8443, 'b.acme.example')])
    assert sorted(dz.parse_srv(msg, qid)) == [(5, 1, 8443, 'b.acme.example'), (10, 5, 443, 'a.acme.example')]
    with pytest.raises(ValueError):
        dz.parse_srv(msg, qid ^ 1)
    with pytest.raises(ValueError):
        dz.parse_srv(b'\x00' * 5)


def test_resolve_srv_over_udp():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(('127.0.0.1', 0))
    port = srv.getsockname()[1]

    def serve():
        data, addr = srv.recvfrom(4096)
        qid = struct.unpack('>H', data[:2])[0]
        srv.sendto(srv_answer(qid ^ 0xFFFF, data[12:-4], [(1, 1, 1, 'wrong.example')]), addr)  # another query
        srv.sendto(srv_answer(qid, data[12:-4], [(0, 0, 443, 'risk-eu.acme.example')]), addr)
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        assert dz.resolve_srv('_sajhanet._tcp.acme.example', f'127.0.0.1:{port}', timeout=3) == \
            [(0, 0, 443, 'risk-eu.acme.example')]
    finally:
        t.join(3)
        srv.close()


def test_sources():
    srv_calls = []

    def srv(name, ns=''):
        srv_calls.append(name)
        if name == '_sajhanet._tcp.acme.example':
            return [(10, 1, 443, 'c.acme.example'), (0, 1, 8443, 'a.acme.example'), (0, 9, 443, 'b.acme.example')]
        if name.startswith('_https._tcp.sajha.risk.svc'):
            return [(0, 0, 8443, 'sajha-0.sajha.risk.svc.cluster.local')]
        raise OSError('NXDOMAIN')
    now = [0.0]
    fetched = []

    def fetch(url):
        fetched.append(url)
        return {'members': ['https://r1.example/', 'ftp://nope', 'https://r2.example']}
    d = dz.Discovery([{'type': 'dns_srv', 'name': '_sajhanet._tcp.acme.example'},
                      {'type': 'kubernetes', 'service': 'sajha', 'namespace': 'risk', 'port_name': 'https'},
                      {'type': 'kubernetes', 'service': 'other', 'namespace': 'risk', 'port': 9443},
                      {'type': 'registry', 'url': 'https://reg.example/acme-net.json', 'ttl_seconds': 10},
                      {'type': 'dns_srv', 'name': '_broken._tcp.example'}],
                     srv=srv, host=lambda name, port: ['10.0.0.7', '[fd00::7]'], fetch=fetch, clock=lambda: now[0])
    assert d.addresses() == [
        'https://b.acme.example', 'https://a.acme.example:8443', 'https://c.acme.example',   # priority, then weight
        'https://sajha-0.sajha.risk.svc.cluster.local:8443',                                # kubernetes via SRV
        'https://10.0.0.7:9443', 'https://[fd00::7]:9443',                                  # A/AAAA fallback
        'https://r1.example', 'https://r2.example']                                         # registry, http(s) only
    d.addresses()
    assert fetched == ['https://reg.example/acme-net.json']                                 # cached
    now[0] = 61
    d.addresses()
    assert len(fetched) == 2
    many = dz.Discovery([{'type': 'registry', 'url': 'https://x'}],
                        fetch=lambda u: [f'https://h{i}.example' for i in range(100)])
    assert len(many.addresses()) == dz.MAX_ADDRESSES


def test_problems():
    assert dz.problems([{'type': 'dns_srv', 'name': 'x'}, {'type': 'registry', 'url': 'https://r'},
                        {'type': 'kubernetes', 'service': 's'}]) == []
    assert len(dz.problems([{'type': 'dns'}, {'type': 'dns_srv'}, {'type': 'registry', 'url': 'file:///x'},
                            {'type': 'kubernetes'}, 'x'])) == 5


def test_a_participant_joins_through_a_discovered_address(tmp_path, monkeypatch):
    n = TestNet(tmp_path)
    a = n.add('risk-eu', founder=True, ca_node=True)
    b = n.add('cust-na', seeds=['https://seed-down.test'], start=False,
              discovery=[{'type': 'registry', 'url': 'https://registry.test/acme-net.json'}])
    monkeypatch.setattr(dz, '_fetch_json', lambda url: [n.url('risk-eu')])
    b.start()
    assert ('discovery', n.url('risk-eu')) in [(k, u) for k, u, _nm in b.join_sources()]
    assert b.try_join()
    n.rounds(3)
    assert b.member('risk-eu') is not None and a.member('cust-na') is not None
