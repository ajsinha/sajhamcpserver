# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Who may use MCP Studio: an admin, or a role with the ``studio`` permission (the seeded
``developer`` role). ``user`` and ``viewer`` may not. Some things stay admin only.
"""
import os
import sys
import uuid
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

PASSWORD = 'Studio-Access-Pass-1'
CODE = '''from sajha.studio import sajhamcptool

@sajhamcptool(description="Add two integers", category="Math")
def add(a: int, b: int = 2) -> dict:
    return {"sum": a + b}
'''


def _make_user(role: str) -> str:
    from sajha.auth.password import hash_password
    from sajha.db.dao import RoleDAO, UserDAO
    from sajha.db.engine import get_db_session
    from sajha.db.models import User
    uid = f'studio_{role}_{uuid.uuid4().hex[:8]}'
    db = get_db_session()
    try:
        user = User(user_id=uid, user_name=uid, email='', password_hash=hash_password(PASSWORD), enabled=True)
        user.roles.append(RoleDAO(db).get_or_create(role))
        UserDAO(db).create(user)
    finally:
        db.close()
    return uid


def _drop_user(uid: str) -> None:
    from sajha.db.dao import UserDAO
    from sajha.db.engine import get_db_session
    db = get_db_session()
    try:
        user = UserDAO(db).get_by_user_id(uid)
        if user:
            UserDAO(db).delete(user)
    finally:
        db.close()


def _headers(c, uid, password=PASSWORD):
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = c.post('/api/auth/login', json={'user_id': uid, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.json()['token']}"}


def _nav(c, uid, password=PASSWORD) -> str:
    """The dashboard as a browser sees it (the menu needs the session cookie)."""
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = c.post('/login', data={'user_id': uid, 'password': password}, follow_redirects=False)
    cookies = dict(r.cookies)
    c.cookies.clear()
    assert cookies, r.status_code
    return c.get('/dashboard', cookies=cookies).text


@pytest.fixture(scope='module')
def env():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        users = {role: _make_user(role) for role in ('developer', 'user', 'viewer')}
        heads = {role: _headers(c, uid) for role, uid in users.items()}
        heads['admin'] = _headers(c, 'admin', 'admin123')
        yield c, heads, users
        for name in ('zz_test_dev_add', 'zz_test_dev_script', 'zz_test_dev_rest', 'zz_describe_dev_stats'):
            c.post('/admin/studio/delete', json={'tool_name': name}, headers=heads['admin'])
        for uid in users.values():
            _drop_user(uid)
        for pattern in ('config/tools/zz_test_dev_*', 'sajha/tools/impl/*zz_test_dev_*',
                        'config/scripts/zz_test_dev_*'):
            for f in ROOT.glob(pattern):
                f.unlink()


def test_the_permission_check():
    from types import SimpleNamespace
    from sajha.auth import AuthContext, can_use_studio
    assert not can_use_studio(None)
    assert not can_use_studio(AuthContext(authenticated=False))
    assert can_use_studio(AuthContext(authenticated=True, is_admin=True))
    # an API key has no user, so no role permissions: never Studio
    assert not can_use_studio(AuthContext(authenticated=True, auth_type='apikey', _db=SimpleNamespace()))


STUDIO_PAGES = ('/studio', '/studio/rest', '/studio/dbquery', '/studio/script', '/studio/olap',
                '/studio/examples', '/studio/describe', '/studio/api-import')


@pytest.mark.parametrize('role', ['admin', 'developer'])
def test_studio_roles_open_every_page_and_see_the_menu(env, role):
    c, heads, users = env
    for path in STUDIO_PAGES:
        r = c.get(path, headers=heads[role], follow_redirects=False)
        assert r.status_code == 200, (path, r.status_code)
    nav = _nav(c, users.get(role, 'admin'), PASSWORD if role != 'admin' else 'admin123')
    assert "Studio home" in nav and 'href="/studio"' in nav
    assert ('/admin/federation' in nav) is (role == 'admin')     # the Admin menu stays admin only
    assert c.get('/api/studio/api-import/apis', headers=heads[role]).status_code == 200


@pytest.mark.parametrize('role', ['user', 'viewer'])
def test_other_roles_are_refused(env, role):
    c, heads, users = env
    for path in STUDIO_PAGES:
        assert c.get(path, headers=heads[role], follow_redirects=False).status_code == 403, path
    for path, body in (('/admin/studio/analyze', {'code': CODE, 'tool_name': 'zz_test_dev_add'}),
                       ('/admin/studio/deploy', {'code': CODE, 'tool_name': 'zz_test_dev_add'}),
                       ('/admin/studio/delete', {'tool_name': 'zz_test_dev_add'}),
                       ('/admin/studio/describe/propose', {'description': 'mean of numbers'}),
                       ('/admin/studio/api-import/parse', {'kind': 'openapi', 'text': '{}'})):
        assert c.post(path, json=body, headers=heads[role]).status_code == 403, path
    assert c.get('/api/studio/api-import/apis', headers=heads[role]).status_code == 403
    assert c.post('/api/composite-tools', json={'name': 'zz_c', 'master_tool': 'x'},
                  headers=heads[role]).status_code == 403
    nav = _nav(c, users[role])
    assert 'Studio home' not in nav and 'href="/studio"' not in nav


def test_developer_deploys_and_deletes_studio_tools(env):
    c, heads, _ = env
    dev = heads['developer']
    from sajha.app import tools_registry
    r = c.post('/admin/studio/deploy', json={'code': CODE, 'tool_name': 'zz_test_dev_add'}, headers=dev)
    assert r.status_code == 200 and r.json()['success'], r.text
    assert 'zz_test_dev_add' in tools_registry.tools
    r = c.post('/admin/studio/rest/deploy', headers=dev, json={
        'name': 'zz_test_dev_rest', 'endpoint': 'http://127.0.0.1:9/x', 'method': 'GET', 'description': 'd',
        'request_schema': {'type': 'object', 'properties': {}}, 'response_format': 'json', 'timeout': 2})
    assert r.status_code == 200 and r.json()['success'], r.text
    for name in ('zz_test_dev_add', 'zz_test_dev_rest'):
        r = c.post('/admin/studio/delete', json={'tool_name': name}, headers=dev)
        assert r.status_code == 200 and r.json()['deleted_files'], r.text
        assert name not in tools_registry.tools


def test_admin_only_items_refuse_developers(env):
    c, heads, _ = env
    dev, admin = heads['developer'], heads['admin']
    from sajha.app import tools_registry
    # tools Studio did not create: refused for everyone
    builtin = next(n for n in tools_registry.tools if (ROOT / 'config' / 'tools' / f'{n}.json').exists())
    assert c.post('/admin/studio/delete', json={'tool_name': builtin}, headers=dev).status_code == 403
    assert builtin in tools_registry.tools
    # code that would run in-process (sandbox not enforced): admin only
    from sajha.sandbox import settings as sb
    import dataclasses
    off = dataclasses.replace(sb.load_settings(), enforce_for_generated_tools=False)
    with mock.patch.object(sb, 'load_settings', return_value=off):
        r = c.post('/admin/studio/deploy', json={'code': CODE, 'tool_name': 'zz_test_dev_add'}, headers=dev)
        assert r.status_code == 403 and 'administrator' in r.json()['error']
        r = c.post('/admin/studio/script/deploy', headers=dev, json={
            'tool_name': 'zz_test_dev_script', 'description': 'Echo', 'script_type': 'bash',
            'script_content': 'echo hi'})
        assert r.status_code == 403
        # analysing (nothing written) is still fine
        r = c.post('/admin/studio/analyze', json={'code': CODE, 'tool_name': 'zz_test_dev_add'}, headers=dev)
        assert r.status_code == 200
    assert 'zz_test_dev_add' not in tools_registry.tools
    # outside Studio stays admin only
    for path in ('/admin/federation', '/admin/connectors', '/admin/policies', '/admin/audit', '/admin/users'):
        assert c.get(path, headers=dev, follow_redirects=False).status_code == 403, path
        assert c.get(path, headers=admin, follow_redirects=False).status_code == 200, path
    assert c.get('/api/sandbox/status', headers=dev).status_code == 403


def test_describe_drafts_are_per_user_for_developers(env):
    c, heads, _ = env
    dev, admin = heads['developer'], heads['admin']
    a = c.post('/admin/studio/describe/propose', headers=admin,
               json={'description': 'mean, median and standard deviation of a list of numbers'}).json()
    assert a['success']
    assert c.get(f"/api/studio/describe/drafts/{a['id']}", headers=dev).status_code == 404
    assert c.post('/admin/studio/describe/test', headers=dev, json={'draft_id': a['id']}).status_code == 404
    d = c.post('/admin/studio/describe/propose', headers=dev,
               json={'description': 'mean, median and standard deviation of a list of numbers'}).json()
    assert d['success']
    assert c.get(f"/api/studio/describe/drafts/{d['id']}", headers=admin).status_code == 200
    name = 'zz_describe_dev_stats'
    d = c.post('/admin/studio/describe/revise', headers=dev,
               json={'draft_id': d['id'], 'proposal': dict(d['proposal'], name=name)}).json()
    t = c.post('/admin/studio/describe/test', headers=dev, json={'draft_id': d['id']}).json()
    assert t['tests_run']['counts']['passed'] >= 1, t
    r = c.post('/admin/studio/describe/deploy', headers=dev,
               json={'draft_id': d['id'], 'hash': d['hash'], 'approve': True})
    assert r.status_code == 200, r.text
    from sajha.app import tools_registry
    assert type(tools_registry.get_tool(name)).__name__ == 'SandboxedPythonTool'
    assert c.post('/admin/studio/delete', json={'tool_name': name}, headers=dev).status_code == 200


def test_composites_developers_change_only_their_own(env):
    c, heads, _ = env
    dev, admin = heads['developer'], heads['admin']
    from sajha.app import tools_registry
    master = next(iter(tools_registry.tools))
    names = ('zz_comp_admin_' + uuid.uuid4().hex[:6], 'zz_comp_dev_' + uuid.uuid4().hex[:6])
    try:
        assert c.post('/api/composite-tools', headers=admin,
                      json={'name': names[0], 'master_tool': master}).status_code == 200
        assert c.post('/api/composite-tools', headers=dev,
                      json={'name': names[1], 'master_tool': master}).status_code == 200
        assert c.put(f'/api/composite-tools/{names[0]}', headers=dev,
                     json={'description': 'x'}).status_code == 403
        assert c.delete(f'/api/composite-tools/{names[0]}', headers=dev).status_code == 403
        assert c.put(f'/api/composite-tools/{names[1]}', headers=dev,
                     json={'description': 'mine', 'created_by': 'admin'}).status_code == 200
        assert c.delete(f'/api/composite-tools/{names[1]}', headers=dev).status_code == 200
    finally:
        for n in names:
            c.delete(f'/api/composite-tools/{n}', headers=admin)
