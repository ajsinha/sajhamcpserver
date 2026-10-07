"""SAJHA Net names (protocol §5): conformance cases NAME-01 to NAME-05 and NAME-10."""

import pytest

from sajha.net import names, schemas


@pytest.mark.parametrize('name', ['risk-eu', 'ab', 'a1', 'cust-na', 'x' * 32, 'a-b-c9'])
def test_name_01_configured_names_accepted(name):
    assert names.is_configured_name(name) and names.is_instance_name(name)
    assert not schemas.errors('member_record', None) == []


@pytest.mark.parametrize('name', ['risk_eu', 'risk.eu', 'risk:eu', 'Risk-eu', 'risk--eu', '1risk', '-risk',
                                  'risk-', 'x' * 33, 'a', ''])
def test_name_01_configured_names_rejected(name):
    assert not names.is_configured_name(name)
    assert not names.is_instance_name(name)


def test_name_02_ipv4_prefix():
    assert names.safe_prefix('10.20.4.17:3002') == '10_20_4_17_3002'
    assert names.is_address_name('10.20.4.17:3002')


def test_name_03_ipv6_prefix():
    p = names.safe_prefix('[2001:db8::7]:3002')
    assert p == '2001_0db8_0000_0000_0000_0000_0000_0007_3002'
    assert '__' not in p
    mapped = names.format_address_name('::ffff:10.0.0.1', 3002)
    pm = names.safe_prefix(mapped)
    assert pm == '0000_0000_0000_0000_0000_ffff_0a00_0001_3002' and len(pm.split('_')) == 9
    assert not names.is_address_name('[2001:0db8::7]:3002')        # only the RFC 5952 form


@pytest.mark.parametrize('addr', ['0.0.0.0', '::', '127.0.0.1', '127.9.9.9', '::1', '169.254.1.1', 'fe80::1',
                                  '::ffff:127.0.0.1'])
def test_name_04_unacceptable_addresses(addr):
    assert names.address_refusal(addr) is not None
    with pytest.raises(names.NameError_):
        names.format_address_name(addr, 3002)


def test_name_04_resolution_order_and_refusals():
    r = names.resolve_instance_name
    assert r('risk-eu', '10.0.0.5:9000', '10.0.0.6', 3002) == ('risk-eu', None)
    assert r('', '10.0.0.5:9000', '10.0.0.6', 3002) == ('10.0.0.5:9000', None)
    assert r('', '[2001:db8::7]', '0.0.0.0', 3002) == ('[2001:db8::7]:3002', None)
    assert r('', '', '10.0.0.6', 3002) == ('10.0.0.6:3002', None)
    assert r('', '', '0.0.0.0', 3002, route_address=lambda: '192.168.1.20') == ('192.168.1.20:3002', None)
    for args in (('', '', '127.0.0.1', 3002), ('', '', 'localhost', 3002), ('', 'localhost:3002', '0.0.0.0', 3002),
                 ('', '169.254.3.3:3002', '0.0.0.0', 3002)):
        name, why = r(*args, route_address=lambda: None)
        assert name is None and why
    name, why = r('', '', '0.0.0.0', 3002, route_address=lambda: None)
    assert name is None and 'default-route' in why
    name, why = r('', '', '0.0.0.0', 3002, route_address=lambda: '127.0.0.1')
    assert name is None and 'loopback' in why
    assert r('Bad_Name', '', '0.0.0.0', 3002)[0] is None


def test_name_05_qualified_names():
    assert names.split_qualified('acme-net__risk-eu__a__b') == ('acme-net', 'risk-eu', 'a__b')
    assert names.split_qualified('acme-net__10_20_4_17_3002__var_calc') == ('acme-net', '10_20_4_17_3002', 'var_calc')
    assert names.split_qualified('var_calc') is None
    assert names.split_qualified('risk_eu__x__y') == ('risk_eu', 'x', 'y')
    assert names.tool_part('a.b') == 'a_b'
    q = names.qualified_name('acme-net', '10.20.4.17:3002', 'a.b')
    assert q == 'acme-net__10_20_4_17_3002__a_b' and q[0].isalpha()
    assert names.qualified_name('n', '[2001:db8::7]:3002', 't')[0] == 'n'
    with pytest.raises(names.NameError_):
        names.qualified_name('acme-net', 'risk-eu', 'x' * 120)


@pytest.mark.parametrize('net', ['default', 'a', 'acme-net', 'risk_eu', 'abcdefghijklmnop'])
def test_name_10_net_names_accepted(net):
    assert names.is_net_name(net)
    assert schemas.is_valid('extension', {'protocol_versions': [1], 'endpoint': '/sajhanet/v1/', 'net': net})


@pytest.mark.parametrize('net', ['Acme', '1net', '-net', '_net', 'a__b', 'net_', 'abcdefghijklmnopq', ''])
def test_name_10_net_names_rejected(net):
    assert not names.is_net_name(net)
    assert not schemas.is_valid('extension', {'protocol_versions': [1], 'endpoint': '/sajhanet/v1/', 'net': net})


def test_name_10_unnamed_net_is_default():
    assert names.net_name_or_default(None) == 'default' and names.net_name_or_default('') == 'default'
    with pytest.raises(names.NameError_):
        names.net_name_or_default('Bad')


def test_net_user():
    assert names.net_user('alice', '10.20.4.17:3002') == 'alice@10.20.4.17:3002'
