# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Changes to existing code that SAJHA Net builds on (docs/archive/SAJHA Net Design Note.md, "new code this design needs",
items 2, 5, 6, 9 and 12): the provider-safe tool part, the peer URL guard with its network
allowlist, the io.sajha/net extension on both MCP eras, cancellation of 2025-11-25 requests,
and the Helm values. Federation's share of these is in tests/test_federation.py.
"""

import ipaddress
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
import yaml

from sajha.core import mcp_cancellation, net_extension
from sajha.federation.names import tool_part
from sajha.federation.security import UnsafeURLError, check_peer_url, net_address_allowed

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / 'charts' / 'sajha'


# ── the provider-safe tool part (qualified names: sajha/net/names.py) ──

def test_tool_part_replaces_dots_for_llm_providers():
    from sajha.federation.config import namespaced
    assert tool_part('a.b-c_d!') == 'a_b-c_d_'
    assert namespaced('wx', 'v1.get.forecast') == 'wx__v1_get_forecast'


# ── the peer URL guard (sajhanet.allowed_networks) ─────────────────

def test_peer_addresses_need_the_allowlist_for_private_ranges():
    nets = [ipaddress.ip_network('10.20.0.0/16'), ipaddress.ip_network('fd00:1::/32')]
    ok = lambda a: net_address_allowed(ipaddress.ip_address(a), nets)   # noqa: E731
    assert ok('8.8.8.8') and ok('10.20.4.17') and ok('fd00:1::5') and ok('::ffff:10.20.0.9')
    assert not ok('10.21.0.1') and not ok('192.168.1.1') and not ok('100.64.0.1')
    # never, whatever the list says
    every = [ipaddress.ip_network('0.0.0.0/0'), ipaddress.ip_network('::/0')]
    for a in ('127.0.0.1', '::1', '169.254.169.254', 'fe80::1', '0.0.0.0', '224.0.0.1'):
        assert not net_address_allowed(ipaddress.ip_address(a), every), a


def test_check_peer_url(monkeypatch):
    assert check_peer_url('https://10.20.4.17:3002', ['10.20.0.0/16']) == ('10.20.4.17', 3002)
    with pytest.raises(UnsafeURLError, match='allowed_networks'):
        check_peer_url('https://10.20.4.17:3002', [])
    with pytest.raises(UnsafeURLError, match='allowed_networks'):
        check_peer_url('http://127.0.0.1:3002', ['127.0.0.0/8'])
    with pytest.raises(UnsafeURLError, match='credentials'):
        check_peer_url('https://u:p@10.20.4.17', ['10.20.0.0/16'])
    with pytest.raises(UnsafeURLError, match='https'):
        check_peer_url('http://10.20.4.17', ['10.20.0.0/16'], require_https=True)
    # separate from federation.allow_private_networks: read from sajhanet.allowed_networks
    monkeypatch.setenv('SAJHA_SAJHANET_ALLOWED_NETWORKS', '10.20.0.0/16, not-a-cidr')
    monkeypatch.setenv('SAJHA_FEDERATION_ALLOW_PRIVATE_NETWORKS', 'false')
    assert check_peer_url('https://10.20.4.17') == ('10.20.4.17', 443)


# ── io.sajha/net on both eras ───────────────────────────────────────

@pytest.fixture
def net_on(monkeypatch):
    monkeypatch.setenv('SAJHA_SAJHANET_ENABLED', 'true')
    monkeypatch.setenv('SAJHA_SAJHANET_NETS', json.dumps([
        {'name': 'acme-net', 'instance_name': 'cust-na'}, {'name': 'partner-net', 'instance_name': 'cust-p'}]))
    net_extension.reset_advertised()
    yield
    net_extension.reset_advertised()


def test_nothing_is_advertised_when_sajha_net_is_off(monkeypatch):
    monkeypatch.setenv('SAJHA_SAJHANET_ENABLED', 'false')
    assert net_extension.extension_object() is None
    caps = {'tools': {}}
    assert net_extension.with_legacy_capabilities(caps) is caps


def test_extension_object(net_on):
    reduced = {'protocol_versions': [1], 'endpoint': '/sajhanet/v1/'}
    assert net_extension.extension_object() == reduced                 # unsigned: no net, no features
    net_extension.advertise(features=['gossip', 'catalog'], user_identity=['api_key'],
                            signature_algorithms=['ed25519', 'ecdsa-p256-sha256'])
    with net_extension.signed_for('partner-net'):
        full = net_extension.extension_object()
    assert full == {'protocol_versions': [1], 'net': 'partner-net', 'instance': 'cust-p', 'kind': 'sajha',
                    'endpoint': '/sajhanet/v1/', 'features': ['gossip', 'catalog'], 'user_identity': ['api_key'],
                    'signature_algorithms': ['ed25519', 'ecdsa-p256-sha256']}
    assert 'acme-net' not in json.dumps(full)                          # other nets are never named
    assert net_extension.extension_object('unknown-net') == reduced


def test_extension_on_both_eras(net_on):
    from types import SimpleNamespace
    from sajha.core.mcp_handler import MCPHandler
    from sajha.core.mcp_modern import ModernMCPServer
    handler = MCPHandler(tools_registry=SimpleNamespace(tools={}), prompts_registry=None)
    init = handler._handle_initialize({'protocolVersion': '2025-11-25', 'capabilities': {}}, None)
    assert init['capabilities']['experimental']['io.sajha/net'] == \
        {'protocol_versions': [1], 'endpoint': '/sajhanet/v1/'}
    assert 'sajha' in init['capabilities']['experimental']             # SAJHA's own entry stays
    assert 'io.sajha/net' not in handler.capabilities.get('experimental', {})   # not stored
    modern = ModernMCPServer(handler).capabilities
    assert modern['extensions']['io.sajha/net'] == {'protocol_versions': [1], 'endpoint': '/sajhanet/v1/'}
    assert 'io.sajha/net' not in (modern.get('experimental') or {})


def test_client_declaration_from_either_era():
    modern = {'extensions': {'io.sajha/net': {'protocol_version': 1}}}
    legacy = {'experimental': {'io.sajha/net': {'protocol_version': 1}}}
    assert net_extension.client_declaration(modern) == {'protocol_version': 1}
    assert net_extension.declared_protocol_version(legacy) == 1
    assert net_extension.declared_protocol_version({'experimental': {'io.sajha/net': {'protocol_version': True}}}) is None
    assert net_extension.client_declaration({'experimental': {'io.sajha/net': 'yes'}}) is None
    assert net_extension.client_declaration(None) is None


# ── 2025-11-25 cancellation ─────────────────────────────────────────

def test_cancellation_flags_only_the_named_request():
    from sajha.core.mcp_tool_context import is_cancelled
    seen = {}
    with mcp_cancellation.track('s1', 1):
        with mcp_cancellation.track('s1', '1'):                        # "1" and 1 are different ids
            assert mcp_cancellation.cancel('s1', '1', 'gave up')
            assert mcp_cancellation.is_cancelled() and is_cancelled()
        assert not mcp_cancellation.is_cancelled()
        assert mcp_cancellation.cancel('s1', 1)
        import contextvars
        ctx = contextvars.copy_context()
        t = threading.Thread(target=lambda: seen.setdefault('worker', ctx.run(is_cancelled)))
        t.start()
        t.join()
    assert seen['worker'] is True
    assert not mcp_cancellation.cancel('s1', 1)                        # finished: ignored
    assert not mcp_cancellation.cancel('s2', 1) and not mcp_cancellation.cancel(None, 1)


# ── Helm values ─────────────────────────────────────────────────────

_NET_VALUES = {'sajhanet': {'enabled': True, 'allowedNetworks': ['10.20.0.0/16'], 'nets': [
    {'name': 'acme-net', 'instanceName': 'risk-eu', 'advertiseAddress': '10.20.4.17:443', 'founder': True,
     'identitySecret': 'acme-id', 'revocationList': True, 'caKeySecret': 'acme-ca',
     'settings': {'default_trust': 'review'}}]}}


def test_chart_schema_accepts_and_refuses_net_values():
    jsonschema = pytest.importorskip('jsonschema')
    schema = json.loads((CHART / 'values.schema.json').read_text())
    jsonschema.validate(_NET_VALUES, schema)
    for bad in ({'name': 'Acme'}, {'name': 'a__b'}, {'name': 'a_'}, {'name': 'a', 'instanceName': 'a--b'},
                {'name': 'a', 'seeds': ['ftp://x']}, {'name': 'a', 'secret': 'x'}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({'sajhanet': {'nets': [bad]}}, schema)


@pytest.mark.skipif(not shutil.which('helm'), reason='helm not installed')
def test_chart_renders_the_net_configuration(tmp_path):
    values = tmp_path / 'v.yaml'
    values.write_text(yaml.safe_dump({**_NET_VALUES, 'networkPolicy': {'enabled': True}}))
    r = subprocess.run(['helm', 'template', 't', str(CHART), '-f', str(values)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    cm = next(d for d in docs if d['kind'] == 'ConfigMap' and 'overrides.yaml' in d.get('data', {}))
    net = yaml.safe_load(cm['data']['overrides.yaml'])['sajhanet']
    assert net['enabled'] is True and net['allowed_networks'] == ['10.20.0.0/16']
    entry = net['nets'][0]
    assert entry['instance_name'] == 'risk-eu' and entry['advertise_address'] == '10.20.4.17:443'
    assert entry['identity'] == {'cert_ref': 'file:/etc/sajhanet/acme-net/instance.crt',
                                 'key_ref': 'file:/etc/sajhanet/acme-net/instance.key',
                                 'ca_ref': 'file:/etc/sajhanet/acme-net/ca.pem',
                                 'revocation_list_ref': 'file:/etc/sajhanet/acme-net/revoked.json'}
    assert entry['ca'] == {'enabled': True, 'key_ref': 'file:/etc/sajhanet-ca/acme-net/ca.key'}
    assert entry['default_trust'] == 'review' and entry['founder'] is True
    dep = next(d for d in docs if d['kind'] == 'Deployment')
    pod = dep['spec']['template']['spec']
    secrets = {v['secret']['secretName'] for v in pod['volumes'] if 'secret' in v}
    assert {'acme-id', 'acme-ca'} <= secrets
    mounts = {m['mountPath']: m for m in pod['containers'][0]['volumeMounts']}
    assert mounts['/etc/sajhanet/acme-net']['readOnly'] and mounts['/etc/sajhanet-ca/acme-net']['readOnly']
    np = next(d for d in docs if d['kind'] == 'NetworkPolicy')
    assert {'ipBlock': {'cidr': '10.20.0.0/16'}} in np['spec']['ingress'][0]['from']
    # several pods: every net needs a configured name and an advertised address
    multi = dict(_NET_VALUES['sajhanet'], nets=[{'name': 'acme-net', 'founder': True}])
    values.write_text(yaml.safe_dump({'sajhanet': multi, 'replicaCount': 2, 'database': {
        'type': 'postgresql', 'postgresql': {'host': 'pg'}}, 'state': {'backend': 'database'},
        'persistence': {'data': {'enabled': False}}}))
    r = subprocess.run(['helm', 'template', 't', str(CHART), '-f', str(values)], capture_output=True, text=True)
    assert r.returncode != 0 and 'instanceName and advertiseAddress' in r.stderr
