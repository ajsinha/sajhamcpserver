"""
Tests for HTTP endpoints — API, MCP, A2A, Web UI.
Uses FastAPI TestClient (no real server needed).

These tests load the full app (157 tools) so they're slower.
Run separately: pytest tests/test_endpoints.py -v
"""

import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient


@pytest.fixture(scope='module')
def client():
    """TestClient with full app — shared across all tests in this module."""
    from sajha.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope='module')
def auth_headers(client):
    """Admin JWT token as Authorization header."""
    r = client.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
    assert r.status_code == 200
    token = r.json()['token']
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture(scope='module')
def auth_cookies(client):
    """Admin session cookie from form login."""
    r = client.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    assert r.status_code == 302
    return dict(r.cookies)


# ── Health ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get('/health')
        assert r.status_code == 200

    def test_health_has_status(self, client):
        data = client.get('/health').json()
        assert data['status'] == 'healthy'

    def test_health_has_tools_count(self, client):
        data = client.get('/health').json()
        assert data['tools_count'] > 0

    def test_health_has_version(self, client):
        data = client.get('/health').json()
        assert 'version' in data


# ── Auth API ─────────────────────────────────────────────────────────────

class TestAuthAPI:
    def test_login_success(self, client):
        r = client.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        assert r.status_code == 200
        data = r.json()
        assert 'token' in data
        assert data['user']['user_id'] == 'admin'
        assert 'admin' in data['user']['roles']

    def test_login_wrong_password(self, client):
        r = client.post('/api/auth/login', json={'user_id': 'admin', 'password': 'wrong'})
        assert r.status_code == 401

    def test_login_missing_fields(self, client):
        r = client.post('/api/auth/login', json={'user_id': 'admin'})
        assert r.status_code == 400

    def test_login_nonexistent_user(self, client):
        r = client.post('/api/auth/login', json={'user_id': 'ghost', 'password': 'pass'})
        assert r.status_code == 401

    def test_form_login_redirects(self, client):
        r = client.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
        assert r.status_code == 302
        assert 'sajha_token' in dict(r.cookies)

    def test_form_login_bad_password(self, client):
        r = client.post('/login', data={'user_id': 'admin', 'password': 'wrong'}, follow_redirects=False)
        assert r.status_code == 200  # Re-renders login page with error

    def test_logout_clears_cookie(self, client, auth_cookies):
        r = client.get('/logout', follow_redirects=False)
        assert r.status_code == 302


# ── Tools API ────────────────────────────────────────────────────────────

class TestToolsAPI:
    def test_list_tools(self, client):
        r = client.get('/api/tools/list')
        assert r.status_code == 200
        tools = r.json()['tools']
        assert len(tools) > 0

    def test_tool_schema(self, client):
        # Get first tool name
        tools = client.get('/api/tools/list').json()['tools']
        if tools:
            name = tools[0]['name'] if isinstance(tools[0], dict) else tools[0]
            r = client.get(f'/api/tools/{name}/schema')
            assert r.status_code == 200

    def test_tool_not_found(self, client):
        r = client.get('/api/tools/nonexistent_tool_xyz/schema')
        assert r.status_code == 404


# ── Reports API ──────────────────────────────────────────────────────────

class TestReportsAPI:
    def test_overview(self, client, auth_headers):
        r = client.get('/api/reports/overview?period=24h', headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert 'total_calls' in data
        assert 'error_rate' in data

    def test_tools_usage(self, client, auth_headers):
        r = client.get('/api/reports/tools/usage?period=7d', headers=auth_headers)
        assert r.status_code == 200
        assert 'tools' in r.json()

    def test_users_activity(self, client, auth_headers):
        r = client.get('/api/reports/users/activity?period=30d', headers=auth_headers)
        assert r.status_code == 200
        assert 'users' in r.json()

    def test_heatmap(self, client, auth_headers):
        r = client.get('/api/reports/heatmap?days=7', headers=auth_headers)
        assert r.status_code == 200
        assert 'heatmap' in r.json()

    def test_audit(self, client, auth_headers):
        r = client.get('/api/reports/audit?limit=10', headers=auth_headers)
        assert r.status_code == 200
        assert 'audit' in r.json()

    def test_requires_auth(self, client):
        r = client.get('/api/reports/overview')
        assert r.status_code == 401


# ── Admin API ────────────────────────────────────────────────────────────

class TestAdminAPI:
    def test_list_users(self, client, auth_headers):
        r = client.get('/api/admin/users', headers=auth_headers)
        assert r.status_code == 200
        users = r.json()['users']
        assert any(u['user_id'] == 'admin' for u in users)

    def test_create_user(self, client, auth_headers):
        import uuid
        uid = f'testcreate_{uuid.uuid4().hex[:8]}'
        r = client.post('/api/admin/users/create', headers=auth_headers, json={
            'user_id': uid, 'user_name': 'Test', 'password': 'pass123', 'roles': ['user']
        })
        assert r.status_code == 200
        assert r.json()['success'] is True

    def test_create_duplicate_user(self, client, auth_headers):
        r = client.post('/api/admin/users/create', headers=auth_headers, json={
            'user_id': 'admin', 'password': 'pass'
        })
        assert r.status_code == 409

    def test_requires_admin(self, client):
        r = client.get('/api/admin/users')
        assert r.status_code == 401


# ── MCP Protocol ─────────────────────────────────────────────────────────

class TestMCPProtocol:
    def _mcp(self, client, method, params=None, headers=None):
        return client.post('/mcp', json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}
        }, headers=headers)

    def test_initialize(self, client, auth_headers):
        r = self._mcp(client, 'initialize', {'clientInfo': {'name': 'test', 'version': '1'}}, auth_headers)
        assert r.status_code == 200
        caps = r.json()['result']['capabilities']
        assert 'tools' in caps

    def test_tools_list(self, client, auth_headers):
        r = self._mcp(client, 'tools/list', {}, auth_headers)
        assert r.status_code == 200
        tools = r.json()['result']['tools']
        assert len(tools) > 0

    def test_prompts_list(self, client, auth_headers):
        r = self._mcp(client, 'prompts/list', {}, auth_headers)
        assert r.status_code == 200

    def test_ping(self, client):
        r = self._mcp(client, 'ping')
        assert r.status_code == 200
        assert r.json()['result']['status'] == 'ok'

    def test_invalid_method(self, client):
        r = self._mcp(client, 'nonexistent/method')
        assert r.status_code == 200
        assert 'error' in r.json()

    def test_parse_error(self, client):
        r = client.post('/mcp', content=b'not json', headers={'Content-Type': 'application/json'})
        assert r.status_code == 400


# ── A2A Protocol ─────────────────────────────────────────────────────────

class TestA2AProtocol:
    def test_agent_card(self, client):
        r = client.get('/.well-known/agent.json')
        assert r.status_code == 200
        card = r.json()
        assert card['name'] == 'SAJHA MCP Server'
        assert 'skills' in card
        assert 'capabilities' in card
        assert len(card['skills']) > 0

    def test_task_send(self, client):
        r = client.post('/a2a', json={
            'jsonrpc': '2.0', 'id': 1,
            'method': 'tasks/send',
            'params': {'message': {'parts': [{'type': 'text', 'text': 'hello'}]}}
        })
        assert r.status_code == 200
        result = r.json()['result']
        assert 'id' in result
        assert result['status']['state'] in ('completed', 'working')

    def test_task_get(self, client):
        # Create a task first
        r = client.post('/a2a', json={
            'jsonrpc': '2.0', 'id': 1,
            'method': 'tasks/send',
            'params': {'message': {'parts': [{'type': 'text', 'text': 'test'}]}}
        })
        task_id = r.json()['result']['id']

        # Get it
        r = client.post('/a2a', json={
            'jsonrpc': '2.0', 'id': 2,
            'method': 'tasks/get',
            'params': {'id': task_id}
        })
        assert r.status_code == 200
        assert r.json()['result']['id'] == task_id

    def test_task_get_nonexistent(self, client):
        r = client.post('/a2a', json={
            'jsonrpc': '2.0', 'id': 1,
            'method': 'tasks/get',
            'params': {'id': 'nonexistent-id'}
        })
        assert 'error' in r.json()

    def test_unknown_method(self, client):
        r = client.post('/a2a', json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'tasks/unknown', 'params': {}
        })
        assert 'error' in r.json()


# ── Web UI Pages ─────────────────────────────────────────────────────────

class TestWebPages:
    """All web UI pages should render (200) for authenticated users."""

    def test_login_page(self, client):
        r = client.get('/login')
        assert r.status_code == 200
        assert 'login' in r.text.lower() or 'sign in' in r.text.lower()

    @pytest.mark.parametrize('path', [
        '/dashboard', '/tools', '/prompts', '/help', '/about', '/docs',
        '/admin/users', '/admin/tools', '/admin/apikeys',
        '/reports',
        '/studio', '/studio/rest', '/studio/dbquery',
        '/monitoring/tools', '/monitoring/users',
    ])
    def test_authenticated_page(self, client, auth_cookies, path):
        r = client.get(path, cookies=auth_cookies)
        assert r.status_code == 200, f'{path} returned {r.status_code}'
        assert len(r.text) > 100, f'{path} response too short'

    def test_unauthenticated_redirect(self, client):
        r = client.get('/dashboard', follow_redirects=False)
        assert r.status_code in (302, 401, 403)

    def test_root_redirect(self, client):
        r = client.get('/', follow_redirects=False)
        assert r.status_code == 302

    def test_swagger_docs(self, client):
        r = client.get('/api/docs')
        assert r.status_code == 200

    def test_redoc(self, client):
        r = client.get('/api/redoc')
        assert r.status_code == 200


# ── Prompts API ──────────────────────────────────────────────────────────

class TestPromptsAPI:
    def test_list_prompts(self, client):
        r = client.get('/api/prompts/list')
        assert r.status_code == 200
        assert 'prompts' in r.json()

    def test_prompt_not_found(self, client):
        r = client.get('/api/prompts/nonexistent_prompt')
        assert r.status_code == 404
