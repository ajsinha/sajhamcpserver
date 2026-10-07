"""
SAJHA Net catalogs and routing inside SAJHA: three SajhaNetService instances in one process, each with
its own tools registry, state store and key files, talking over HTTP (TestClient) through
``/sajhanet/v1/`` and the MCP endpoint's net path. Covers proxies in the registry (qualified names and
bare aliases, ``_meta["io.sajha/net"]``), a call forwarded through ``execute_with_tracking``, a host
going down with fallback, a contract conflict quarantined (the local copy too) and re-activated, a
restart that lists nothing remote until peers answer, the admin views, and NET-04.

Identity and authorization (stream D) are replaced by the shipped ``none`` resolver and ``allow_all``
rules, so this file tests catalogs and routing only.
"""

import json
import threading

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from sajha.core.state.memory import MemoryStateStore
from sajha.core.storage import LocalStorageBackend
from sajha.net import EXTENSION_ID, httpsig, plugins
from sajha.net.integration import SajhaNetService
from sajha.net.integration.config import Shared
from sajha.net.models import CASettings, GossipSettings, IdentitySettings, NetConfig, PeerCacheSettings
from sajha.tools.base_mcp_tool import BaseMCPTool
from tests.net.test_net_integration import ClientConnector

NET = 'acme-net'


class Registry:
    """The registry surface the net uses (one per instance; SAJHA's is a process singleton)."""

    def __init__(self):
        self.tools = {}
        self._tools_lock = threading.RLock()

    def get_tool(self, name):
        return self.tools.get(name)

    def register_tool(self, tool):
        self.tools[tool.name] = tool

    def unregister_tool(self, name):
        self.tools.pop(name, None)

    def get_all_tools(self):
        return [t.to_mcp_format() for t in self.tools.values() if t.enabled]


class Echo(BaseMCPTool):
    def __init__(self, name, props=None, annotations=None, owner=''):
        super().__init__({'name': name, 'description': f'{name} on {owner}', 'version': '1.2.0', 'enabled': True,
                          'inputSchema': {'type': 'object', 'properties': props or {'x': {'type': 'integer'}}},
                          'annotations': annotations or {'readOnlyHint': True}})
        self.owner = owner
        self.calls = 0

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {}

    def execute(self, arguments):
        self.calls += 1
        return f'{self.owner}:{self.name}:{arguments.get("x")}'


class Authz:
    """Stream D's NetAuthz replaced by the shipped plug-ins."""

    def __init__(self):
        self.identity = plugins.NoIdentity()
        self.rules = plugins.AllowAll()
        self.nets = {}

    def attach(self, cfg, node):
        return None


def app_for(svc):
    app = FastAPI()

    @app.api_route('/sajhanet/{path:path}', methods=['GET', 'POST'])
    async def ep(request: Request, path: str):
        from sajha.routes.sajhanet_routes import serve
        return await serve(svc, request)

    @app.post('/mcp')
    async def mcp(request: Request):
        from fastapi.responses import Response
        raw = await request.body()
        r = svc.participant.handle_mcp('POST', '/mcp', '', dict(request.headers), raw, True, '')
        if r is None:
            return Response(status_code=404)
        return Response(content=r.body, status_code=r.status,
                        headers={k: v for k, v in r.headers.items() if k != 'content-length'})
    return app


def gossip():
    return GossipSettings(gossip_interval_ms=3600000, ping_timeout_ms=500, indirect_probes=1,
                          suspect_timeout_seconds=1, full_sync_interval_seconds=3600, dead_retention_minutes=60,
                          dead_probe_interval_seconds=3600)


def make(tmp, name, conn, tools, founder=False, store=None):
    d = tmp / name
    s = Shared(enabled=True, data_dir=str(d), gossip=gossip())
    cfg = NetConfig(name=NET, instance_name=name, founder=founder, seeds=[] if founder else ['https://risk-eu.test'],
                    base_url=f'https://{name}.test', gossip=gossip(),
                    identity=IdentitySettings(cert_ref=f'file:{d}/instance.crt', key_ref=f'file:{d}/instance.key',
                                              ca_ref=f'file:{d}/ca.pem', revocation_list_ref=f'file:{d}/revoked.json'),
                    ca=CASettings(enabled=founder, key_ref=f'file:{d}/ca.key', cert_ref=f'file:{d}/ca.pem'),
                    peer_cache=PeerCacheSettings(path=str(d / 'peers.json')))
    svc = SajhaNetService(s, [cfg], {}, store=store or MemoryStateStore(), connector=conn,
                          documents=LocalStorageBackend(str(d)))
    svc.tools_registry = Registry()
    for t in tools:
        svc.tools_registry.register_tool(t)
    svc.authz = Authz()
    conn.clients[f'https://{name}.test'] = TestClient(app_for(svc), base_url=f'https://{name}.test')
    return svc


def node(svc):
    return svc.runtimes[NET].node


def settle(svcs, rounds=4):
    for _ in range(rounds):
        for s in svcs:
            if node(s) is not None and f'https://{node(s).name}.test' not in s.connector.down:
                node(s).tick()
        for s in svcs:
            s.catalogs.maybe_sync()


@pytest.fixture
def net3(tmp_path):
    conn = ClientConnector()
    a = make(tmp_path, 'risk-eu', conn, [Echo('var_calc', owner='risk-eu')], founder=True)
    a.start(run_agents=False)
    a.ca_init(NET)
    assert node(a).try_join()
    out = {'risk-eu': a, 'conn': conn, 'tmp': tmp_path}
    for name, tools in (('cust-na', [Echo('var_calc', owner='cust-na'), Echo('lookup', owner='cust-na')]),
                        ('treasury-na', [Echo('var_calc', owner='treasury-na'), Echo('lookup', owner='treasury-na'),
                                         Echo('wipe', owner='treasury-na', annotations={'destructiveHint': True})])):
        s = make(tmp_path, name, conn, tools)
        s.start(run_agents=False)
        tok = a.ca_token(NET, name)
        s.enroll(NET, 'https://risk-eu.test', tok['token'], by='test')
        s.authz = s.authz if hasattr(s, 'authz') else Authz()
        assert node(s).try_join()
        out[name] = s
    settle([out['risk-eu'], out['cust-na'], out['treasury-na']], 5)
    yield out
    for s in (out['risk-eu'], out['cust-na'], out['treasury-na']):
        s.stop()


def test_proxies_calls_fallback_conflict_and_restart(net3):
    a, b, c, conn = net3['risk-eu'], net3['cust-na'], net3['treasury-na'], net3['conn']
    svcs = [a, b, c]
    reg = a.tools_registry
    # proxies: every remote tool under its qualified name; plain aliases only where no local tool exists
    names = set(reg.tools)
    assert {'acme-net__cust-na__lookup', 'acme-net__treasury-na__lookup', 'acme-net__cust-na__var_calc',
            'acme-net__treasury-na__var_calc', 'acme-net__treasury-na__wipe', 'lookup', 'wipe', 'var_calc'} <= names
    assert type(reg.tools['var_calc']).__name__ == 'Echo'                     # local wins the plain name
    listed = {t['name']: t for t in reg.get_all_tools()}
    meta = listed['acme-net__cust-na__lookup']['_meta'][EXTENSION_ID]
    assert meta['locality'] == 'remote' and meta['instance'] == 'cust-na' and meta['net'] == NET
    assert meta['qualified_name'] == 'acme-net__cust-na__lookup' and meta['alias'] == 'lookup'
    assert meta['version'] == '1.2.0' and meta['contract_hash'].startswith('sha-256:')
    assert listed['acme-net__cust-na__lookup']['annotations']['openWorldHint'] is True
    assert listed['lookup']['_meta'][EXTENSION_ID]['resolution'] == ['acme-net__cust-na__lookup',
                                                                       'acme-net__treasury-na__lookup']

    # a forwarded call through the registry tool (execute_with_tracking at the home, the real tool at the host)
    r = reg.get_tool('lookup').execute_with_tracking({'x': 7})
    assert r['content'][0]['text'] == 'cust-na:lookup:7'
    assert r['_meta'][EXTENSION_ID]['instance'] == 'cust-na'
    assert b.tools_registry.get_tool('lookup').calls == 1
    r = reg.get_tool('acme-net__treasury-na__lookup').execute_with_tracking({'x': 1})
    assert r['content'][0]['text'] == 'treasury-na:lookup:1'

    # the host goes down: the plain name falls back; the qualified name fails fast
    conn.down.add('https://cust-na.test')
    r = reg.get_tool('lookup').execute_with_tracking({'x': 2})
    assert r['content'][0]['text'] == 'treasury-na:lookup:2'
    assert [x['host'] for x in r['_meta'][EXTENSION_ID]['attempts']] == ['cust-na', 'treasury-na']
    r = reg.get_tool('acme-net__cust-na__lookup').execute_with_tracking({'x': 2})
    assert r['isError'] and r['_meta'][EXTENSION_ID]['refusal']['reason'] == 'unreachable'
    conn.down.discard('https://cust-na.test')

    # a contract conflict: cust-na's var_calc changes; everyone quarantines, risk-eu's own copy included
    b.tools_registry.register_tool(Echo('var_calc', props={'x': {'type': 'string'}}, owner='cust-na'))
    b.catalogs.books[NET].invalidate()
    settle(svcs, 4)
    for s in svcs:
        q = s.catalogs.books[NET].quarantined()
        assert set(q) == {'var_calc'} and q['var_calc']['differing'] == ['cust-na'], node(s).name
    assert 'acme-net__treasury-na__var_calc' not in reg.tools
    assert a.catalogs.local_quarantine('var_calc')['differing'] == ['cust-na']
    from sajha.net.integration import set_service, get_service
    old = get_service()
    set_service(a)
    try:
        from sajha.net.integration.catalogs import LocalQuarantined, listed as net_listed
        with pytest.raises(LocalQuarantined):
            reg.get_tool('var_calc').execute_with_tracking({'x': 1})
        assert 'var_calc' not in {t['name'] for t in net_listed(reg.get_all_tools())}
    finally:
        set_service(old)
    from sajha import notices
    assert any(n['id'] == f'sajhanet.conflict:{NET}:var_calc' for n in notices.list_notices())
    # cust-na withdraws it: re-activated everywhere, the notice clears
    b.tools_registry.unregister_tool('var_calc')
    b.catalogs.books[NET].invalidate()
    settle(svcs, 4)
    for s in svcs:
        assert s.catalogs.books[NET].quarantined() == {}
    assert 'acme-net__treasury-na__var_calc' in reg.tools
    assert not any(n['id'] == f'sajhanet.conflict:{NET}:var_calc' for n in notices.list_notices())

    # views
    t = a.catalogs.table()
    row = next(r for r in t['rows'] if r['qualified_name'] == 'acme-net__treasury-na__lookup')
    assert row['state'] == 'active' and row['resolution'].startswith('2: net order') and row['alias'] == 'lookup'
    assert t['resolution']['var_calc']['kind'] == 'local'
    assert a.catalogs.metrics()[0][0] == 'sajha_net_contract_conflicts'

    # a restart of risk-eu with its state store kept: nothing remote until the peers answer in this run
    store = a.store
    a.stop()
    store.delete(f'sajhanet:{NET}:run')
    a2 = make(net3['tmp'], 'risk-eu-2', conn, [Echo('var_calc', owner='risk-eu')], founder=True, store=store)
    a2.shared.data_dir = a.shared.data_dir
    a2.runtimes[NET].cfg = a.runtimes[NET].cfg
    a2.documents = a.documents
    conn.clients['https://risk-eu.test'] = conn.clients.pop('https://risk-eu-2.test')
    conn.clients['https://risk-eu.test'].app = app_for(a2)
    a2.start(run_agents=False)
    a2.catalogs.maybe_sync()
    assert not any(n.startswith('acme-net__') for n in a2.tools_registry.tools)
    assert a2.catalogs.books[NET]._held('cust-na').get('tools')             # the stored copy is there
    node(a2).try_join()
    settle([a2, b, c], 3)
    assert 'acme-net__cust-na__lookup' in a2.tools_registry.tools


def test_net_04_signed_discover_and_unknown_net_is_404(net3, monkeypatch):
    a, b, conn = net3['risk-eu'], net3['cust-na'], net3['conn']
    monkeypatch.setenv('SAJHA_SAJHANET_ENABLED', 'true')
    monkeypatch.setenv('SAJHA_SAJHANET_NETS', json.dumps([{'name': NET, 'instance_name': 'cust-na'},
                                                          {'name': 'other-net', 'instance_name': 'cust-x'}]))
    na = node(a)
    body = json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'server/discover', 'params': {}}).encode()
    h = httpsig.sign_request(na.signer, 'POST', '/mcp', '', {'content-type': 'application/json',
                                                             'mcp-method': 'server/discover'},
                             body, NET, na.name, 'cust-na', mcp=True, now=na.clock())
    r = conn.send('POST', 'https://cust-na.test/mcp', h, body, 5)
    assert r.status == 200
    ext = json.loads(r.body)['result']['capabilities']['extensions'][EXTENSION_ID]
    assert ext['net'] == NET and ext['instance'] == 'cust-na' and 'other-net' not in json.dumps(ext)
    h2 = dict(h, **{'sajha-net-name': 'no-such-net'})
    r = conn.send('POST', 'https://cust-na.test/mcp', h2, body, 5)
    assert r.status == 404 and r.body == b''
    # a signed tools/list returns what the catalog endpoint returns (CAT-03)
    body = json.dumps({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/list', 'params': {}}).encode()
    h = httpsig.sign_request(na.signer, 'POST', '/mcp', '', {'content-type': 'application/json'}, body, NET,
                             na.name, 'cust-na', mcp=True, now=na.clock())
    listed = json.loads(conn.send('POST', 'https://cust-na.test/mcp', h, body, 5).body)['result']['tools']
    cat = na.request('https://cust-na.test', '/sajhanet/v1/catalog', {}, 'cust-na').body['tools']
    assert listed == cat
