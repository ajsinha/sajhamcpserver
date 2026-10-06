"""
The tamper-evident audit (sajha/audit/; docs/architecture/Policy and Audit.md, sections 7-8):
the hash chain and its signed anchors, detection of every kind of tampering, several writers
on one database, retry after a failed write, the verify command, and each SIEM sink against
a local fake receiver (syslog over TCP and TLS, Splunk HEC, Datadog, generic HTTP with
retries, the JSONL file with rotation) in JSON, CEF and OCSF.
"""

from __future__ import annotations

import base64
import datetime as dt
import http.server
import json
import os
import socket
import socketserver
import ssl
import threading
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine, text

from sajha.audit import formats, sinks
from sajha.audit.chain import ChainWriter, Signer, canonical, digest
from sajha.audit.verify import verify


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem(k):
    return k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())


@pytest.fixture(scope='module')
def signer():
    return Signer(_pem(_key()), 'test-kid')


@pytest.fixture
def db(tmp_path):
    return create_engine(f'sqlite:///{tmp_path}/audit.db')


def write(engine, signer, n=12, anchor_every=5, close=True, chain_id=None):
    w = ChainWriter(engine=engine, chain_id=chain_id, anchor_every=anchor_every, anchor_interval=0,
                    signer=signer, store=True)
    for i in range(n):
        w.append('policy.deny' if i % 3 == 0 else 'login_success', actor={'user': f'u{i}', 'roles': ['user']},
                 resource={'type': 'tool', 'id': f't{i}'}, outcome='deny' if i % 3 == 0 else 'ok',
                 details={'i': i})
    if close:
        w.close()
    return w


def check(engine, signer):
    return verify(engine, keys={signer.kid: signer.public_key()})


def problems(engine, signer):
    r = check(engine, signer)
    return r['ok'], ' '.join(p for c in r['chains'] for p in c['problems'])


# ── the chain ───────────────────────────────────────────────────────

def test_records_are_hash_chained_and_anchored(db, signer):
    w = write(db, signer)
    r = check(db, signer)
    assert r['ok'] and len(r['chains']) == 1
    c = r['chains'][0]
    assert c['closed'] and c['unanchored'] == 0 and c['anchors'] >= 3 and not c['warnings']
    with db.connect() as conn:
        rows = conn.execute(text('SELECT seq, record_json, prev_hash, hash, event FROM audit_chain '
                                 'ORDER BY seq')).fetchall()
    assert rows[0][4] == 'chain.open' and rows[0][2] == '0' * 64
    prev = '0' * 64
    for seq, rec_json, prev_hash, h, _ev in rows:
        rec = json.loads(rec_json)
        assert rec['seq'] == seq and rec['prev'] == prev == prev_hash
        assert h == digest(canonical(rec)) == digest(rec_json)
        prev = h
    assert rows[-1][4] == 'audit.anchor' and rows[-2][4] == 'chain.close'
    assert w.status()['pending'] == 0


@pytest.mark.parametrize('tamper,expect', [
    ("UPDATE audit_chain SET record_json = replace(record_json, '\"u4\"', '\"zz\"') WHERE seq = 5",
     'hash does not match'),
    ("UPDATE audit_chain SET actor = 'mallory' WHERE seq = 5", 'column actor was changed'),
    ("UPDATE audit_chain SET outcome = 'ok' WHERE seq = 1", 'column outcome was changed'),
    ("DELETE FROM audit_chain WHERE seq = 4", 'missing'),
    ("UPDATE audit_chain SET seq = 1000 WHERE seq = 3", 'missing'),
    ("UPDATE audit_anchors SET signature = 'AAAA' WHERE id = 1", 'signature is not valid'),
])
def test_tampering_is_detected(db, signer, tamper, expect):
    write(db, signer)
    with db.begin() as conn:
        conn.execute(text(tamper))
    ok, msg = problems(db, signer)
    assert not ok and expect in msg, msg


def test_a_rewritten_tail_is_caught_by_the_signed_anchor(db, signer):
    """Edit record 3, then re-hash every later record so the links are consistent again:
    only the anchors (signed with a key the attacker lacks) still disagree."""
    write(db, signer, n=12, anchor_every=5)
    with db.begin() as conn:
        rows = conn.execute(text('SELECT id, seq, record_json FROM audit_chain ORDER BY seq')).fetchall()
        prev = None
        for rid, seq, rec_json in rows:
            rec = json.loads(rec_json)
            if seq == 3:
                rec['actor']['user'] = 'forged'
            if prev is not None and seq > 3:
                rec['prev'] = prev
            if seq >= 3:
                t = canonical(rec)
                h = digest(t)
                conn.execute(text('UPDATE audit_chain SET record_json=:t, hash=:h, prev_hash=:p, actor=:a '
                                  'WHERE id=:i'), {'t': t, 'h': h, 'p': rec['prev'], 'i': rid,
                                                   'a': (rec.get('actor') or {}).get('user')})
                prev = h
            else:
                prev = digest(rec_json)
    ok, msg = problems(db, signer)
    assert not ok and 'chain rewritten' in msg, msg
    assert 'hash does not match' not in msg and 'does not link' not in msg   # the forgery is self-consistent


def test_truncation_after_an_anchor_is_detected(db, signer):
    write(db, signer, n=12, anchor_every=5)
    with db.begin() as conn:
        conn.execute(text('DELETE FROM audit_chain WHERE seq >= 10'))
    ok, msg = problems(db, signer)
    assert not ok and 'truncated' in msg, msg


def test_unanchored_tail_and_open_chain_are_warnings(db, signer):
    w = write(db, signer, n=7, anchor_every=5, close=False)
    c = check(db, signer)['chains'][0]
    assert c['ok'] and not c['closed'] and c['unanchored'] > 0
    assert any('not yet anchored' in x for x in c['warnings']) and any('chain.close' in x for x in c['warnings'])
    w.close()
    assert check(db, signer)['chains'][0]['unanchored'] == 0


def test_an_unknown_signing_key_is_a_warning_and_a_jwks_file_fixes_it(db, signer, tmp_path):
    write(db, signer)
    r = verify(db, keys={})
    assert r['ok'] and any('pass --public-key' in w for w in r['chains'][0]['warnings'])
    nums = signer.public_key().public_numbers()

    def b64(n):
        return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, 'big')).rstrip(b'=').decode()
    jwks = tmp_path / 'jwks.json'
    jwks.write_text(json.dumps({'keys': [{'kty': 'RSA', 'kid': signer.kid, 'n': b64(nums.n), 'e': b64(nums.e)}]}))
    r = verify(db, public_key_file=str(jwks), keys=None)
    assert r['ok'] and r['chains'][0]['anchors'] >= 1 and not r['chains'][0]['warnings']
    other = Signer(_pem(_key()), signer.kid)                 # same kid, wrong key: invalid
    assert not verify(db, keys={signer.kid: other.public_key()})['ok']


def test_several_writers_one_database(db, signer):
    """Per-process chains: interleaved writers never contend for a chain head."""
    ws = [ChainWriter(engine=db, anchor_every=4, anchor_interval=0, signer=signer, store=True,
                      chain_id=f'w{i}') for i in range(3)]

    def run(w):
        for i in range(20):
            w.append('tool.call', actor={'user': w.chain_id}, details={'i': i})
    threads = [threading.Thread(target=run, args=(w,)) for w in ws]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for w in ws:
        w.close()
    r = check(db, signer)
    assert r['ok'] and sorted(c['chain_id'] for c in r['chains']) == ['w0', 'w1', 'w2']
    from sajha.audit.chain import recent
    merged = recent(db, limit=500)
    assert {m['chain'] for m in merged} == {'w0', 'w1', 'w2'}
    assert [m['ts'] for m in merged] == sorted((m['ts'] for m in merged), reverse=True)


def test_a_failed_write_is_retried_without_a_gap(tmp_path, signer):
    good = create_engine(f'sqlite:///{tmp_path}/ok.db')
    w = ChainWriter(engine=create_engine('sqlite:////nonexistent-dir/x.db'), anchor_every=1000, anchor_interval=0,
                    signer=signer, store=True)
    for i in range(3):
        w.append('e', details={'i': i})
    assert w.status()['pending'] == 4 and w.last_error                # chain.open + 3, all kept
    w._engine = good
    w.append('e', details={'i': 3})
    w.close()
    r = check(good, signer)
    assert r['ok'] and r['chains'][0]['records'] >= 7


def test_audit_logger_events_join_the_chain(signer):
    from sajha import audit
    from sajha.core.audit import AuditLogger
    got = []
    old = (audit._writer, audit._exporter)
    audit.set_writer(ChainWriter(store=False, anchor_interval=0, anchor_every=10 ** 6, signer=signer,
                                 on_record=got.append))
    try:
        AuditLogger().login_failed('eve', ip='203.0.113.9', reason='bad password')
    finally:
        audit._writer, audit._exporter = old
    rec = [r for r in got if r['event'] == 'login_failed'][0]
    assert rec['actor'] == {'user': 'eve', 'ip': '203.0.113.9'} and rec['details'] == 'bad password'
    assert rec['hash'] == digest(canonical({k: v for k, v in rec.items() if k != 'hash'}))


def test_verify_command(tmp_path, capsys):
    from sajha.audit.__main__ import main
    url = f'sqlite:///{tmp_path}/cli.db'
    eng = create_engine(url)
    write(eng, Signer())                                       # the server key: the CLI verifies with it
    assert main(['verify', '--db-url', url]) == 0
    assert 'INTACT' in capsys.readouterr().out
    assert main(['show', '--db-url', url, '--limit', '3', '--format', 'cef']) == 0
    assert capsys.readouterr().out.count('CEF:0|SAJHA|') == 3
    with eng.begin() as conn:
        conn.execute(text("UPDATE audit_chain SET record_json = replace(record_json, 'u1', 'u7') WHERE seq = 2"))
    assert main(['verify', '--db-url', url, '--json']) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['ok'] is False and 'seq 2' in report['chains'][0]['problems'][0]
    assert main(['verify', '--db-url', 'postgresql://nobody@127.0.0.1:1/none']) == 2


# ── formats ─────────────────────────────────────────────────────────

REC = {'v': 1, 'chain': 'h-1-a', 'seq': 7, 'ts': '2026-10-06T09:15:02.123456Z', 'prev': 'p' * 64,
       'event': 'policy.deny', 'actor': {'user': 'ali=ce', 'roles': ['user'], 'ip': '10.0.0.1'},
       'resource': {'type': 'tool', 'id': 'pay|ments'}, 'outcome': 'deny',
       'details': {'rule': 'p/r', 'why': 'line1\nline2'}, 'hash': 'h' * 64}


def test_cef_rendering_escapes_and_carries_the_chain():
    line = formats.to_cef(REC)
    assert line.startswith('CEF:0|SAJHA|SAJHA MCP Server|')
    head = line.split('|')
    assert head[4] == 'policy.deny' and head[6] == '6'
    assert 'suser=ali\\=ce' in line and 'cs1=h-1-a' in line and 'cn1=7' in line and f'cs2={"h" * 64}' in line
    assert '\n' not in line and 'rt=1791278102123' in line


def test_ocsf_rendering():
    o = formats.to_ocsf(REC)
    assert o['class_uid'] == 6003 and o['status'] == 'Failure' and o['metadata']['uid'] == 'h' * 64
    assert o['metadata']['sequence'] == 7 and o['actor']['user']['name'] == 'ali=ce'
    assert formats.to_ocsf(dict(REC, event='login_success', outcome=None))['class_uid'] == 3002
    assert formats.to_ocsf(dict(REC, event='apikey_create', outcome=None))['class_uid'] == 3001


# ── sinks against local fake receivers ──────────────────────────────

def _read_frames(data: bytes):
    out = []
    while data:
        n, _, rest = data.partition(b' ')
        n = int(n)
        out.append(rest[:n])
        data = rest[n:]
    return out


class _TCP(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _syslog_server(tls_ctx=None):
    got = []

    class H(socketserver.BaseRequestHandler):
        def handle(self):
            conn = self.request
            if tls_ctx is not None:
                conn = tls_ctx.wrap_socket(conn, server_side=True)
            buf = b''
            try:
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            except OSError:
                pass
            got.extend(_read_frames(buf))

    srv = _TCP(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, got


def _wait(pred, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_syslog_over_tcp_rfc5424_octet_counted():
    srv, got = _syslog_server()
    s = sinks.SyslogSink({'name': 'sys', 'host': '127.0.0.1', 'port': srv.server_address[1], 'format': 'json',
                          'flush_seconds': 0.05})
    for i in range(3):
        s.submit(dict(REC, seq=i))
    assert s.flush(10)
    s.stop()
    assert _wait(lambda: len(got) == 3)
    srv.shutdown()
    msg = got[0].decode('utf-8')
    assert msg.startswith('<108>1 2026-10-06T09:15:02.123456Z ')     # facility 13 (log audit) * 8 + warning 4
    assert ' sajha ' in msg and ' policy.deny [sajha@32473 chain="h-1-a" seq="0" hash="' in msg
    body = got[0].split(b'\xef\xbb\xbf', 1)[1]
    assert json.loads(body)['event'] == 'policy.deny'
    assert s.status()['sent'] == 3


def _self_signed(tmp_path):
    k = _key()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
            .sign(k, hashes.SHA256()))
    cp, kp = tmp_path / 'c.pem', tmp_path / 'k.pem'
    cp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    kp.write_bytes(_pem(k))
    return str(cp), str(kp)


def test_syslog_over_tls_in_cef(tmp_path):
    cert, key = _self_signed(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    srv, got = _syslog_server(ctx)
    s = sinks.SyslogSink({'name': 'tls', 'host': 'localhost', 'port': srv.server_address[1], 'tls': True,
                          'ca_file': cert, 'format': 'cef', 'flush_seconds': 0.05})
    s.submit(REC)
    assert s.flush(10)
    s.stop()
    assert _wait(lambda: len(got) == 1)
    srv.shutdown()
    assert b'CEF:0|SAJHA|SAJHA MCP Server|' in got[0]


class _HTTP:
    """A local HTTP receiver; ``fail`` is how many requests answer 500 first."""

    def __init__(self, fail=0):
        self.requests = []
        self.fail = fail
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                outer.requests.append({'path': self.path, 'headers': {k.lower(): v for k, v in self.headers.items()},
                                       'body': body})
                code = 500 if outer.fail > 0 else 200
                outer.fail -= 1
                self.send_response(code)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.srv.server_address[1]}'

    def close(self):
        self.srv.shutdown()


@pytest.mark.parametrize('flavor', ['splunk_hec', 'datadog', 'generic'])
def test_http_sinks_batch_and_authenticate(flavor, monkeypatch):
    monkeypatch.setenv('TEST_SIEM_TOKEN', 's3cret')
    rx = _HTTP()
    s = sinks.HttpSink({'name': flavor, 'type': 'http', 'flavor': flavor, 'url': rx.url + '/ingest',
                        'token': 'env:TEST_SIEM_TOKEN', 'allow_private_networks': True, 'batch_size': 10,
                        'flush_seconds': 0.3, 'format': 'ocsf' if flavor == 'generic' else 'json'})
    for i in range(4):
        s.submit(dict(REC, seq=i))
    assert s.flush(10)
    s.stop()
    rx.close()
    assert s.status()['sent'] == 4 and rx.requests
    r = rx.requests[0]
    if flavor == 'splunk_hec':
        assert r['headers']['authorization'] == 'Splunk s3cret'
        events = [json.loads(line) for line in r['body'].decode().splitlines()]
        assert events[0]['sourcetype'] == 'sajha:audit' and events[0]['event']['event'] == 'policy.deny'
    elif flavor == 'datadog':
        assert r['headers']['dd-api-key'] == 's3cret'
        items = json.loads(r['body'])
        assert items[0]['ddsource'] == 'sajha' and items[0]['sajha']['seq'] == 0
    else:
        assert r['headers']['authorization'] == 'Bearer s3cret'
        assert json.loads(r['body'])[0]['class_uid'] == 6003
    total = sum(len(json.loads(x['body'])) if flavor != 'splunk_hec' else len(x['body'].splitlines())
                for x in rx.requests)
    assert total == 4


def test_http_sink_retries_then_drops():
    rx = _HTTP(fail=2)
    s = sinks.HttpSink({'name': 'retry', 'url': rx.url, 'allow_private_networks': True, 'flush_seconds': 0.05,
                        'max_retries': 3, 'retry_base_seconds': 0.01})
    s.submit(REC)
    assert s.flush(10)
    assert s.status()['sent'] == 1 and s.status()['failed'] == 2 and s.status()['dropped'] == 0
    rx.fail = 100
    s.submit(REC)
    assert s.flush(10)
    s.stop()
    rx.close()
    st = s.status()
    assert st['dropped'] == 1 and 'HTTP 500' in st['last_error']


def test_http_sink_ssrf_guard(monkeypatch):
    rx = _HTTP()
    with pytest.raises(sinks.ExportRefused, match='non-public'):
        sinks.check_destination(rx.url, allow_private=False)
    monkeypatch.setenv('SAJHA_AUDIT_EXPORT_ALLOWED_URLS', 'https://siem.example.com/')
    with pytest.raises(sinks.ExportRefused, match='allowed_urls'):
        sinks.check_destination(rx.url, allow_private=True)
    rx.close()
    with pytest.raises(sinks.SinkConfigError):
        sinks.HttpSink({'url': 'https://user:pw@siem.example.com/'})


def test_file_sink_rotates(tmp_path):
    s = sinks.FileSink({'name': 'f', 'path': str(tmp_path / 'a-{pid}.jsonl'), 'max_bytes': 2048, 'backups': 2,
                        'flush_seconds': 0.01})
    for i in range(30):
        s.submit(dict(REC, seq=i))
    assert s.flush(10)
    s.stop()
    base = tmp_path / f'a-{os.getpid()}.jsonl'
    files = sorted(p.name for p in tmp_path.iterdir())
    assert base.name in files and f'{base.name}.1' in files and f'{base.name}.2' in files
    assert f'{base.name}.3' not in files
    assert all(json.loads(line)['event'] == 'policy.deny' for line in base.read_text().splitlines())
    assert base.stat().st_size <= 2048


def test_sinks_from_config_and_a_full_queue_drops(monkeypatch, tmp_path):
    monkeypatch.setenv('SAJHA_AUDIT_EXPORT_SINKS', json.dumps([
        {'name': 'f', 'type': 'file', 'path': str(tmp_path / 'x.jsonl')},
        {'name': 'bad', 'type': 'carrier-pigeon'},
        {'name': 'off', 'type': 'file', 'enabled': False}]))
    m = sinks.ExportManager.from_config()
    assert [s.name for s in m.sinks] == ['f'] and 'type must be one of' in m.errors[0]
    m.stop()
    s = sinks.FileSink({'name': 'tiny', 'path': str(tmp_path / 'y.jsonl'), 'queue_size': 10})
    s.start = lambda: None                                 # no consumer: the queue fills
    for _ in range(15):
        s.submit(REC)
    assert s.dropped == 5


def test_writer_exports_every_record_including_anchors(db, signer, tmp_path):
    rx = _HTTP()
    sink = sinks.HttpSink({'name': 'g', 'url': rx.url, 'allow_private_networks': True, 'flush_seconds': 0.05})
    m = sinks.ExportManager([sink])
    w = ChainWriter(engine=db, anchor_every=3, anchor_interval=0, signer=signer, store=True, on_record=m.dispatch)
    for i in range(4):
        w.append('e', details={'i': i})
    w.close()
    assert m.flush(10)
    m.stop()
    rx.close()
    exported = [r for req in rx.requests for r in json.loads(req['body'])]
    events = [r['event'] for r in exported]
    assert events.count('audit.anchor') >= 2 and 'chain.open' in events and 'chain.close' in events
    with db.connect() as conn:
        n = conn.execute(text('SELECT COUNT(*) FROM audit_chain')).scalar()
    assert len(exported) == n and all(r['hash'] for r in exported)


def test_admin_verify_api(web):
    client, admin = web
    r = client.get('/api/audit/verify', cookies=admin)
    assert r.status_code == 200 and 'chains' in r.json()
    assert client.get('/api/audit/verify').status_code in (401, 403)
    r = client.get('/api/audit/records?limit=5', cookies=admin)
    assert r.status_code == 200 and isinstance(r.json()['records'], list)
