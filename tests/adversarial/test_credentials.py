# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Adversarial QA Plan 3.3 (credentials and sign-in), P0 items.

* Precedence matrix: one raw key in the keys file (config/apikeys.json), the database and the dump
  (config/apikeys_db.json) in every combination of states. The first store that knows the key decides:
  the file, then the database, then the dump; a store that refuses never falls through to a later one.
* The test admin key: refused from every store while ``sajhanet.test_admin_key.enabled`` is off, never in
  the records this instance publishes to a net's key directory (even while on).
* JWTs: ``alg: none``, a wrong key, a different HMAC algorithm, an expired token and a token revoked by
  signing out are all refused, over HTTP and by the decoder.
"""

import base64
import itertools
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_api_keys_identity import _auth_key, _bearer, _db, _login, _new_key, app  # noqa: F401
from tests.test_credential_files import files  # noqa: F401

FILE_STATES = ('absent', 'enabled', 'disabled', 'expired')
DB_STATES = ('absent', 'enabled', 'disabled')
DUMP_STATES = ('absent', 'enabled', 'disabled')


def _expected(file_s, db_s, dump_s):
    """(accepted, deciding store) under the documented precedence."""
    if file_s != 'absent':
        return file_s == 'enabled', 'file'
    if db_s != 'absent':
        return db_s == 'enabled', 'db'
    if dump_s != 'absent':
        return dump_s == 'enabled', 'dump'
    return False, None


def _record(raw, state, name):
    rec = {'id': f'adv-{name}-{uuid.uuid4().hex[:6]}', 'name': name, 'key': raw, 'roles': ['user'],
           'enabled': state != 'disabled'}
    if state == 'expired':
        rec['expires_at'] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return rec


@pytest.mark.parametrize('file_s,db_s,dump_s', list(itertools.product(FILE_STATES, DB_STATES, DUMP_STATES)))
def test_credential_precedence_matrix(app, files, file_s, db_s, dump_s):  # noqa: F811
    keys, _users, dump = files
    from sajha.auth import apikeys as svc
    from sajha.db.models import ApiKey
    kid, raw = _new_key(None, name=f'adv-{uuid.uuid4().hex[:6]}')      # unowned: the service identity
    db = _db()
    try:
        key = svc.get_key(db, kid)
        if db_s == 'disabled':
            svc.set_enabled(db, key, False, 'adversarial')
        elif db_s == 'absent':
            db.query(ApiKey).filter(ApiKey.id == kid).delete()
            db.commit()
    finally:
        db.close()
    if file_s != 'absent':
        keys.upsert(_record(raw, file_s, 'from-file'))
    if dump_s != 'absent':
        dump.upsert(_record(raw, dump_s, 'from-dump'))
    accepted, store = _expected(file_s, db_s, dump_s)
    auth = _auth_key(raw)
    assert (auth is not None) == accepted, (file_s, db_s, dump_s, auth)
    if accepted:
        label = {'file': 'from-file', 'dump': 'from-dump'}.get(store)
        if label:
            assert auth.api_key_name == label, (store, auth.api_key_name)
        else:
            assert auth.api_key_name not in ('from-file', 'from-dump')


@pytest.mark.parametrize('where', ['file', 'dump'])
def test_test_admin_key_refused_from_every_store_while_off(app, files, monkeypatch, where):  # noqa: F811
    keys, _users, dump = files
    raw = f'sja_adv_test_admin_{uuid.uuid4().hex[:8]}'
    rec = {'id': 'adv-ta', 'name': 'test admin', 'key': raw, 'roles': ['admin'], 'enabled': True, 'test_admin': True}
    (keys if where == 'file' else dump).upsert(rec)
    monkeypatch.setenv('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'false')
    assert _auth_key(raw) is None
    monkeypatch.setenv('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'true')
    auth = _auth_key(raw)
    assert auth is not None and auth.is_admin


def test_test_admin_key_never_reaches_the_published_key_directory(monkeypatch):
    from sajha.net.integration.keystore import own_keys
    monkeypatch.setenv('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'true')        # even while honoured locally
    recs = [{'id': 'ta', 'key': 'sja_adv_ta_publish', 'owner': 'admin', 'roles': ['admin'], 'enabled': True,
             'test_admin': True},
            {'id': 'ok', 'key': 'sja_adv_ok_publish', 'owner': 'alice', 'roles': ['user'], 'enabled': True}]
    published = own_keys(db_factory=lambda: None, persistent=lambda: recs)
    assert [b['key_id'] for b in published] == ['ok']
    assert 'sja_adv_ta_publish' not in json.dumps(published) and 'sja_adv_ok_publish' not in json.dumps(published)


# ── JWTs ──────────────────────────────────────────────────────────────

def _b64(obj) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b'=').decode()


def _claims(sub='admin', **over):
    now = datetime.now(timezone.utc)
    c = {'sub': sub, 'roles': ['admin'], 'iat': int(now.timestamp()),
         'exp': int((now + timedelta(minutes=30)).timestamp()), 'iss': 'sajha-mcp-server', 'jti': uuid.uuid4().hex}
    c.update(over)
    return c


def _forged_tokens():
    from jose import jwt
    from sajha.core.config import get_settings
    secret = get_settings().jwt_secret
    other_alg = 'HS512' if get_settings().jwt_algorithm != 'HS512' else 'HS384'
    past = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
    return {
        'alg none': f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(_claims())}.",
        'alg None, signature kept': f"{_b64({'alg': 'None', 'typ': 'JWT'})}.{_b64(_claims())}.c2ln",
        'wrong key': jwt.encode(_claims(), 'not-the-server-secret', algorithm='HS256'),
        'other algorithm': jwt.encode(_claims(), secret, algorithm=other_alg),
        'expired': jwt.encode(_claims(exp=past), secret, algorithm=get_settings().jwt_algorithm),
        'garbage': 'eyJhbGciOiJIUzI1NiJ9.not-json.sig',
    }


def test_forged_jwts_are_refused_by_the_decoder():
    from sajha.auth.jwt_handler import decode_access_token
    for label, token in _forged_tokens().items():
        assert decode_access_token(token) is None, label


def test_forged_jwts_are_refused_over_http(app):  # noqa: F811
    c, _users, _ = app
    for label, token in _forged_tokens().items():
        assert c.get('/api/account/apikeys', headers=_bearer(token)).status_code == 401, label
        r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
                   headers={**_bearer(token), 'Accept': 'application/json, text/event-stream'})
        assert r.status_code == 401, (label, r.status_code)


def test_a_signed_out_token_stays_refused_everywhere(app):  # noqa: F811
    c, users, _ = app
    token = _login(c, users['user'])
    assert c.post('/api/auth/logout', headers=_bearer(token)).status_code == 200
    assert c.get('/api/account/apikeys', headers=_bearer(token)).status_code == 401
    r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
               headers={**_bearer(token), 'Accept': 'application/json, text/event-stream'})
    assert r.status_code == 401
