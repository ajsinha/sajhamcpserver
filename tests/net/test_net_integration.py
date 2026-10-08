# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net inside SAJHA: three instances in one process, each with its own state store, key files
and storage, talking over HTTP through the ASGI stack. The first is a full SAJHA app (lifespan,
admin API, routes, notices); the other two are SAJHA Net services served by the same route code.

Covers: the CA run by SAJHA (init, tokens, enrollment, held names), joining through a seed, crash
detection, a restart with lost state, a clean leave, a name collision refused loudly, adding a peer
by address (SSRF rules, runtime seed), /sajhanet/ refused when off, to navigations and without CORS,
and the ``sajha net`` CLI.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from sajha.core.state.memory import MemoryStateStore
from sajha.core.storage import LocalStorageBackend
from sajha.net import crypto
from sajha.net.integration import SajhaNetService, ServiceError, get_service
from sajha.net.integration.config import Shared
from sajha.net.models import CASettings, GossipSettings, IdentitySettings, NetConfig, PeerCacheSettings
from sajha.net.plugins import PeerConnector, PeerResponse, PeerUnreachable

NET = 'acme-net'
A_URL = 'https://testserver'


class ClientConnector(PeerConnector):
    """Routes a request to the TestClient serving its base URL; a base URL in ``down`` is unreachable."""
    name = 'test_clients'

    def __init__(self):
        self.clients = {}
        self.down = set()

    def send(self, method, url, headers, body, timeout):
        from urllib.parse import urlsplit
        p = urlsplit(url)
        base = f'{p.scheme}://{p.netloc}'
        c = self.clients.get(base)
        if c is None or base in self.down:
            raise PeerUnreachable(f'connection refused: {base}')
        r = c.request(method, p.path + (('?' + p.query) if p.query else ''), headers=headers,
                      content=body if method != 'GET' else None)
        return PeerResponse(r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content)


def mini_app(svc):
    from sajha.routes.sajhanet_routes import serve
    app = FastAPI()

    @app.api_route('/sajhanet/{path:path}', methods=['GET', 'POST'])
    async def ep(request: Request, path: str):
        return await serve(svc, request)
    return app


def gossip():
    return GossipSettings(gossip_interval_ms=3600000, ping_timeout_ms=500, indirect_probes=1,
                          suspect_timeout_seconds=1, full_sync_interval_seconds=3600, dead_retention_minutes=60,
                          dead_probe_interval_seconds=3600)


def service(tmp: Path, name: str, conn, seeds=(A_URL,), host=None):
    d = tmp / name
    host = host or f'{name}.test'
    s = Shared(enabled=True, data_dir=str(d), gossip=gossip())
    cfg = NetConfig(name=NET, instance_name=name, seeds=list(seeds), base_url=f'https://{host}', gossip=gossip(),
                    identity=IdentitySettings(cert_ref=f'file:{d}/instance.crt', key_ref=f'file:{d}/instance.key',
                                              ca_ref=f'file:{d}/ca.pem', revocation_list_ref=f'file:{d}/revoked.json'),
                    ca=CASettings(), peer_cache=PeerCacheSettings(path=str(d / 'peers.json')))
    svc = SajhaNetService(s, [cfg], {}, store=MemoryStateStore(), connector=conn, documents=LocalStorageBackend(str(d)))
    conn.clients[f'https://{host}'] = TestClient(mini_app(svc), base_url=f'https://{host}')
    return svc


@pytest.fixture(scope='module')
def fabric(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('sajhanet')
    nets = [{'name': NET, 'instance_name': 'risk-eu', 'founder': True, 'ca': {'enabled': True}}]
    env = {'SAJHA_SAJHANET_ENABLED': 'true', 'SAJHA_SAJHANET_BASE_URL': A_URL,
           'SAJHA_SAJHANET_DATA_DIR': str(tmp / 'a'), 'SAJHA_SAJHANET_NETS': json.dumps(nets),
           'SAJHA_SAJHANET_GOSSIP_GOSSIP_INTERVAL_MS': '3600000',
           'SAJHA_SAJHANET_GOSSIP_SUSPECT_TIMEOUT_SECONDS': '1',
           'SAJHA_SAJHANET_GOSSIP_FULL_SYNC_INTERVAL_SECONDS': '3600',
           'SAJHA_SAJHANET_GOSSIP_DEAD_PROBE_INTERVAL_SECONDS': '3600'}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    conn = ClientConnector()
    try:
        from sajha.app import create_app
        with TestClient(create_app(), base_url=A_URL) as c:
            r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
            admin = dict(r.cookies)
            c.cookies.clear()
            svc_a = get_service()
            svc_a.connector = conn
            conn.clients[A_URL] = c
            yield {'c': c, 'admin': admin, 'conn': conn, 'tmp': tmp, 'a': svc_a}
    finally:
        from sajha import notices                     # the notices service is process-wide: leave none behind
        for n in notices.list_notices(state='all'):
            if str(n.get('id', '')).startswith('sajhanet.'):
                notices.clear_notice(n['id'])
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _api(f, method, path, body=None):
    return f['c'].request(method, path, json=body, cookies=f['admin'])


def node(svc):
    return svc.runtimes[NET].node


def test_the_net_in_one_process(fabric, monkeypatch):
    f, conn, tmp = fabric, fabric['conn'], fabric['tmp']
    a = f['a']
    st = _api(f, 'GET', '/api/sajhanet/status').json()
    assert st['enabled'] and 'not initialised' in st['nets'][0]['error']

    # the CA run by SAJHA: init once, through the admin API
    r = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/ca/init')
    assert r.status_code == 200, r.text
    assert _api(f, 'POST', f'/api/sajhanet/nets/{NET}/ca/init').status_code == 409
    assert oct(os.stat(tmp / 'a' / NET / 'ca.key').st_mode & 0o777) == '0o600'
    na = node(a)
    assert na is not None and na.try_join() and 'ca' in na.features

    # two more instances enroll with tokens and join through the seed
    svcs = {}
    for name in ('cust-na', 'treasury-na'):
        tok = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/ca/tokens', {'instance': name}).json()
        svc = service(tmp, name, conn)
        svc.start(run_agents=False)
        assert svc.runtimes[NET].error.startswith('no certificate')
        out = svc.enroll(NET, A_URL, tok['token'], by='test')
        assert out['certificate']['instance'] == name
        assert node(svc).try_join(), node(svc).status()
        svcs[name] = svc
    b, c = svcs['cust-na'], svcs['treasury-na']
    for _ in range(4):
        for s in (a, b, c):
            node(s).tick()
    for s, others in ((a, {'cust-na', 'treasury-na'}), (b, {'risk-eu', 'treasury-na'}), (c, {'risk-eu', 'cust-na'})):
        assert {m['name']: m['state'] for m in node(s).members()} == {o: 'alive' for o in others}

    # a held name: the CA refuses a token; a rogue certificate for it is refused loudly by every member
    r = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/ca/tokens', {'instance': 'cust-na'})
    assert r.status_code == 409 and r.json()['holder']['serial']
    rogue = service(tmp, 'cust-na-rogue', conn, host='rogue.test')
    rogue.runtimes[NET].cfg.instance_name = 'cust-na'
    key = crypto.generate_key()
    cert = a.runtimes[NET].ca._issue(key.public_key(), 'cust-na', 'rogue.test')
    d = tmp / 'cust-na-rogue'
    d.mkdir(exist_ok=True)
    (d / 'instance.key').write_bytes(crypto.key_to_pem(key))
    (d / 'instance.crt').write_bytes(crypto.cert_pem(cert))
    (d / 'ca.pem').write_bytes(crypto.cert_pem(a.runtimes[NET].ca.cert))
    rogue.start(run_agents=False)
    rn = node(rogue)
    assert not rn.try_join()
    assert rn.refused()['holder_thumbprint'] == node(b).signer.keyid
    assert rogue.status()['nets'][0]['refused']
    from sajha import notices
    assert any(n['id'] == f'sajhanet.name_conflict:{NET}' for n in notices.list_notices())
    assert all(m['record']['url'] != 'https://rogue.test' for s in (a, b, c) for m in node(s).members())
    rn.tick()
    assert not rn.joined()

    # crash detection: treasury-na stops answering
    conn.down.add('https://treasury-na.test')
    node(a).probe(node(a).member('treasury-na'))
    assert node(a).member('treasury-na')['state'] == 'suspect'
    time.sleep(1.1)
    node(a).tick()
    assert node(a).member('treasury-na')['state'] == 'dead'

    # restart of cust-na with its state store lost: seeds first, higher incarnation
    inc = node(b).incarnation()
    b2 = service(tmp, 'cust-na', conn)
    b2.start(run_agents=False)
    assert node(b2).try_join() and node(b2).incarnation() > inc
    for _ in range(3):
        node(a).tick()
        node(b2).tick()
    assert node(a).member('cust-na')['record']['incarnation'] == node(b2).incarnation()

    # a clean leave
    assert node(b2).leave() >= 1
    assert node(a).member('cust-na')['state'] == 'left'

    # adding a peer by address: SSRF rules first, then an ordinary signed join
    r = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/peers', {'address': '127.0.0.1:9'})
    assert r.status_code == 400 and 'refused' in r.json()['error']
    tok = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/ca/tokens', {'instance': 'eq-asia'}).json()
    e = service(tmp, 'eq-asia', conn, seeds=())
    e.runtimes[NET].cfg.founder = True
    e.start(run_agents=False)
    e.enroll(NET, A_URL, tok['token'])
    import sajha.federation.security as fsec
    monkeypatch.setattr(fsec, 'check_peer_url', lambda url, **kw: ('eq-asia.test', 443))
    r = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/peers', {'address': 'https://eq-asia.test', 'keep_as_seed': True})
    assert r.status_code == 200 and r.json()['peer'] == 'eq-asia', r.text
    assert node(a).member('eq-asia')['state'] == 'alive'
    assert [s['url'] for s in a.runtime_seeds(NET)] == ['https://eq-asia.test']
    conn.down.add('https://nowhere.test')
    r = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/peers', {'address': 'https://nowhere.test'})
    assert r.status_code == 502 and node(a).member('nowhere') is None

    # the CA's revocation reaches members through gossip digests
    r = _api(f, 'POST', f'/api/sajhanet/nets/{NET}/ca/revoke', {'instance': 'eq-asia'})
    assert r.status_code == 200 and node(a).member('eq-asia') is None

    # the console page and the metrics
    page = f['c'].get('/admin/sajhanet', cookies=f['admin'])
    assert page.status_code == 200 and 'risk-eu' in page.text and 'class="page-help"' in page.text
    from sajha.observability.metrics import exposition
    text = exposition()
    assert 'sajha_net_joined{net="acme-net"} 1' in text and 'sajha_net_members' in text


def test_net_paths_refuse_browsers_and_cors(fabric):
    c = fabric['c']
    r = c.get('/sajhanet/v1/revocations', headers={'Origin': 'https://evil.example', 'Sajha-Net-Name': NET})
    assert not any(k.lower().startswith('access-control-') for k in r.headers)
    r = c.options('/sajhanet/v1/gossip/ping', headers={'Origin': 'https://evil.example',
                                                       'Access-Control-Request-Method': 'POST'})
    assert r.status_code == 404 and not any(k.lower().startswith('access-control-') for k in r.headers)
    r = c.get('/sajhanet/v1/revocations', headers={'Sec-Fetch-Mode': 'navigate', 'Sajha-Net-Name': NET})
    assert r.status_code == 404 and r.content == b''
    r = c.post('/sajhanet/v1/gossip/ping', headers={'Sajha-Net-Name': 'not-mine'}, json={})
    assert r.status_code == 404 and r.content == b''


def test_admin_api_is_admin_only(fabric):
    c = fabric['c']
    assert c.get('/api/sajhanet/status').status_code in (401, 403)
    assert c.post(f'/api/sajhanet/nets/{NET}/peers', json={'address': '10.0.0.1:3002'}).status_code in (401, 403)


def test_cli_net_commands(fabric, monkeypatch, capsys):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'clientsdk'))
    import importlib
    cli = importlib.import_module("sajhaclient.cli.main")
    f = fabric

    def request(self, method, path, body=None, params=None):
        r = _api(f, method, path, body)
        if r.status_code >= 400:
            from sajhaclient.exceptions import SajhaNotFoundError, SajhaError
            raise (SajhaNotFoundError if r.status_code == 404 else SajhaError)(r.text)
        return r.json()
    monkeypatch.setattr(cli.Context, 'request', request)
    monkeypatch.setenv('SAJHA_CONFIG_DIR', str(f['tmp'] / 'cli'))
    assert cli.main(['net', 'status']) == 0
    out = capsys.readouterr().out
    assert 'acme-net: risk-eu (joined) founder CA' in out
    assert cli.main(['net', 'ca', 'show', '--net', NET, '--json']) == 0
    data = json.loads(capsys.readouterr().out)
    assert any(i['instance'] == 'cust-na' for i in data['issued'])
    assert cli.main(['net', 'ca', 'enroll', 'cust-na', '--net', NET]) != 0      # a held name
    capsys.readouterr()
    assert cli.main(['net', 'ca', 'enroll', 'new-one', '--net', NET]) == 0
    cap = capsys.readouterr()
    assert 'sajha net enroll --net acme-net' in cap.out + cap.err


def test_service_errors_for_unknown_nets():
    s = SajhaNetService(Shared(enabled=True), [], {}, store=MemoryStateStore(), connector=ClientConnector())
    with pytest.raises(ServiceError) as e:
        s.inject('nope', '10.0.0.1:3002')
    assert e.value.status == 404
