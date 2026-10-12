# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The Planner routing page and its API on the live app: admin only, CSRF, learn -> proposal,
approve the reviewed hash -> active version, rollback, the bandit's kill switch
(docs/architecture/LLM Tools.md §9.13)."""

import re

import pytest
from sqlalchemy import create_engine

from sajha.ai.planners_engine import learning as L
from sajha.quality.store import RunStore, set_run_store


@pytest.fixture
def routing(tmp_path, monkeypatch):
    set_run_store(RunStore(create_engine(f'sqlite:///{tmp_path / "q.db"}')))
    store = L.RoutingStore(str(tmp_path / 'routing'), reload_interval_s=0)
    L.set_store(store)
    monkeypatch.setattr(L, 'policy_gate', lambda pid, user: None)
    yield store
    L.set_store(None)
    L.set_bandit(None)
    set_run_store(None)


def _csrf(html):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def test_page_renders_for_admins_only(web, routing):
    c, admin = web
    r = c.get('/admin/planner-routing', cookies=admin)
    assert r.status_code == 200 and 'About this page' in r.text and 'Planner Routing' in r.text
    assert c.get('/admin/planner-routing', follow_redirects=False).status_code in (302, 303, 401, 403)
    assert c.get('/api/ai/planner-routing', follow_redirects=False).status_code in (302, 303, 401, 403)


def test_learn_approve_rollback_and_kill_switch(web, routing):
    c, admin = web
    page = c.get('/admin/planner-routing', cookies=admin).text
    tok = _csrf(page)
    r = c.post('/admin/planner-routing/learn', cookies=admin, data={'csrf': tok}, follow_redirects=False)
    assert r.status_code == 303 and 'notice=' in r.headers['location'] and len(routing.proposals()) == 1
    assert 'error=' in c.post('/admin/planner-routing/learn', cookies=admin, data={'csrf': 'x'},
                              follow_redirects=False).headers['location']
    doc = routing.propose({'llm_t': {'*': {'order': ['react', 'reflect'], 'scores': {}}}}, evidence={
        'eval_outcomes': 0, 'run_outcomes': 12}, settings={})
    page = c.get(f'/admin/planner-routing?proposal={doc["id"]}', cookies=admin).text
    assert doc['hash'] in page and 'react → reflect' in page
    r = c.post(f'/admin/planner-routing/{doc["id"]}/approve', cookies=admin,
               data={'csrf': tok, 'hash': doc['hash']}, follow_redirects=False)
    assert 'error=' in r.headers['location'] and routing.active()[0] == 0          # approve not ticked
    r = c.post(f'/admin/planner-routing/{doc["id"]}/approve', cookies=admin,
               data={'csrf': tok, 'hash': 'f' * 64, 'approve': '1'}, follow_redirects=False)
    assert 'error=' in r.headers['location'] and routing.active()[0] == 0          # not the reviewed hash
    r = c.post(f'/admin/planner-routing/{doc["id"]}/approve', cookies=admin,
               data={'csrf': tok, 'hash': doc['hash'], 'approve': '1'}, follow_redirects=False)
    assert 'notice=' in r.headers['location'] and routing.active()[0] == 1
    st = c.get('/api/ai/planner-routing', cookies=admin).json()
    assert st['active'] == 1 and st['rules']['llm_t']['*']['order'] == ['react', 'reflect']
    assert c.post('/api/ai/planner-routing/activate', cookies=admin, json={'version': 0}).status_code == 403
    r = c.post('/admin/planner-routing/activate', cookies=admin, data={'csrf': tok, 'version': '0'},
               follow_redirects=False)
    assert 'notice=' in r.headers['location'] and routing.active()[0] == 0
    assert c.get(f'/api/ai/planner-routing/proposals/{doc["id"]}', cookies=admin).json()['status'] == 'approved'
    assert c.get('/api/ai/planner-routing/proposals/nope', cookies=admin).status_code == 404
    r = c.post('/admin/planner-routing/bandit', cookies=admin, data={'csrf': tok, 'action': 'stop'},
               follow_redirects=False)
    assert 'notice=' in r.headers['location'] and L.get_bandit().killed()['reason']
    c.post('/admin/planner-routing/bandit', cookies=admin, data={'csrf': tok, 'action': 'resume'})
    assert L.get_bandit().killed() is None


def test_the_proposal_records_where_the_request_came_from(routing, monkeypatch):
    # the console (session cookie) is "console"; the HTTP API with an API key or a JWT is "api"
    from sajha.auth import AuthContext
    from sajha.routes.planner_routing_routes import _do
    seen = []
    monkeypatch.setattr(L, 'learn', lambda **kw: seen.append(kw['source']) or {'id': 'p1', 'diff': []})
    for auth_type in ('session', 'apikey', 'jwt'):
        _do('learn', AuthContext(authenticated=True, user_id='admin', is_admin=True, auth_type=auth_type), {})
    assert seen == ['console', 'api', 'api']
