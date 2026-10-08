# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Wave 3 phase 3.2 authoring: the Studio LLM tool creator, the planner editor, Describe-a-tool
LLM proposals, the Conversations page, and Studio permissions per creator with ownership
(Roadmap X2). Pages: sajha/routes/studio_llm_routes.py, planner_editor_routes.py,
conversations_routes.py; logic: sajha/studio/llm_tool_builder.py, planner_editor.py, ownership.py.
"""
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

PASSWORD = 'Studio-Llm-Pass-1'
PREFIX = 'zz_llmc_'


def _make_user(role: str, extra_perm=None) -> str:
    from sajha.auth.password import hash_password
    from sajha.db.dao import RoleDAO, UserDAO
    from sajha.db.engine import get_db_session
    from sajha.db.models import Permission, User
    uid = f'llmc_{role}_{uuid.uuid4().hex[:8]}'
    db = get_db_session()
    try:
        r = RoleDAO(db).get_or_create(role)
        if extra_perm and not db.query(Permission).filter(Permission.role_id == r.id,
                                                          Permission.resource_type == extra_perm[0]).first():
            db.add(Permission(id=f'p-{uuid.uuid4().hex[:8]}', role_id=r.id, resource_type=extra_perm[0],
                              resource_name=extra_perm[1], actions=extra_perm[2]))
            db.commit()
        user = User(user_id=uid, user_name=uid, email='', password_hash=hash_password(PASSWORD), enabled=True)
        user.roles.append(r)
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


def _cookies(c, uid, password=PASSWORD):
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = c.post('/login', data={'user_id': uid, 'password': password}, follow_redirects=False)
    cookies = dict(r.cookies)
    c.cookies.clear()
    return cookies


@pytest.fixture(scope='module')
def env():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        users = {'dev': _make_user('developer'), 'dev2': _make_user('developer'),
                 'llm': _make_user('llm_author', ('studio', 'llm', 'use')), 'user': _make_user('user')}
        heads = {k: _headers(c, uid) for k, uid in users.items()}
        heads['admin'] = _headers(c, 'admin', 'admin123')
        yield c, heads, users
        from sajha.app import tools_registry
        for f in (ROOT / 'config' / 'tools').glob(f'{PREFIX}*.json'):
            c.post('/admin/studio/delete', json={'tool_name': f.stem}, headers=heads['admin'])
            if f.exists():
                f.unlink()
            if tools_registry and f.stem in tools_registry.tools:
                tools_registry.unregister_tool(f.stem)
        for uid in users.values():
            _drop_user(uid)


def _form(name, **kw):
    f = {'name': name, 'description': 'Classifies a support message into a queue.', 'mode': 'classify',
         'instructions': 'system_prompt', 'system_prompt': 'billing: money. technical: bugs.',
         'template': 'Classify this message:\n\n{{input.message}}', 'labels': ['billing', 'technical', 'other']}
    f.update(kw)
    return f


# ── the builder (no app) ─────────────────────────────────────────────

@pytest.mark.parametrize('mode,extra,ins,outs', [
    ('answer', {'memory': {'mode': 'conversation'}, 'tools_allow': ['calc_*']},
     {'question', 'conversation_id', 'confirm'}, {'answer', 'conversation_id', 'stopped_by'}),
    ('grounded', {}, {'question'}, {'answer', 'citations', 'stopped_by'}),
    ('complete', {'template': 'Summarise {{input.text}}'}, {'text'}, {'text', 'stopped_by'}),
    ('classify', {'template': '{{input.message}}', 'labels': ['a', 'b']}, {'message'}, {'label', 'stopped_by'}),
    ('extract', {'template': '{{input.text}}', 'fields': [{'name': 'amount', 'type': 'number'}]}, {'text'},
     {'amount', 'stopped_by'}),
    ('judge', {'template': '{{input.answer}}'}, {'answer'}, {'scores', 'verdict', 'stopped_by'}),
])
def test_generated_schemas_per_mode(mode, extra, ins, outs):
    from sajha.studio.llm_tool_builder import generated_schemas
    i, o = generated_schemas({'mode': mode, **extra})
    assert ins <= set(i['properties']) and outs <= set(o['properties'])
    if mode == 'classify':
        assert o['properties']['label']['enum'] == ['a', 'b']


def test_form_round_trips_a_shipped_tool():
    from sajha.studio.llm_tool_builder import build_config, form_from_config
    cfg = json.loads((ROOT / 'config/tools/llm_markets_assistant.json').read_text())
    again = build_config(form_from_config(cfg))
    assert again['llm']['mode'] == 'answer' and again['llm']['tools'] == cfg['llm']['tools']
    assert again['llm']['limits'] == cfg['llm']['limits'] and again['llm']['memory']['mode'] == 'conversation'
    assert again['inputSchema'] == cfg['inputSchema'] and again['outputSchema'] == cfg['outputSchema']


def test_graph_marks_bounded_and_back_edges():
    import yaml
    from sajha.studio.planner_editor import graph
    g = graph(yaml.safe_load((ROOT / 'config/planners/reflect.yaml').read_text()))
    loop = [e for e in g['edges'] if e['from'] == 'act' and e['to'] == 'act']
    assert loop and loop[0]['bounded'] and loop[0]['max_visits'] == 6 and loop[0]['back']
    assert any(e['kind'] == 'exhausted' and e['to'] == 'draft' for e in g['edges'])
    assert next(n for n in g['nodes'] if n['id'] == 'act')['start']


# ── the LLM tool creator ─────────────────────────────────────────────

def test_build_check_reports_the_loaders_messages(env):
    c, heads, _ = env
    r = c.post('/admin/studio/llm/build', json={'form': _form(PREFIX + 'bad', labels=[])}, headers=heads['admin'])
    chk = r.json()['check']
    assert not chk['valid'] and any('label property with an enum' in e for e in chk['errors'])
    r = c.post('/admin/studio/llm/build', json={'form': _form(PREFIX + 'ok', limits={'max_steps': 999})},
               headers=heads['admin'])
    chk = r.json()['check']
    assert chk['valid'] and chk['limits']['effective']['max_steps'] < 999 and chk['limits']['clamped'] == ['max_steps']
    r = c.post('/admin/studio/llm/check', json={'config': {'name': PREFIX + 'x', 'description': 'x', 'llm': {'mode': 'chat'}}},
               headers=heads['admin'])
    assert any('llm.mode must be one of' in e for e in r.json()['check']['errors'])


def test_live_matching_preview(env):
    c, heads, _ = env
    r = c.post('/admin/studio/llm/match', json={'allow': ['calc_*', 'nothing_here_*'], 'deny': ['calc_percentage*']},
               headers=heads['admin'])
    m = r.json()['matching']
    assert m['count'] > 0 and all(n.startswith('calc_') and not n.startswith('calc_percentage') for n in m['allowed'])
    pats = {p['pattern']: p for p in m['patterns']}
    assert pats['nothing_here_*']['matches'] == 0 and pats['calc_percentage*']['kind'] == 'deny'
    assert any(e['why'] == 'denied' for e in m['excluded'])


def test_test_run_on_the_mock(env):
    c, heads, _ = env
    r = c.post('/admin/studio/llm/test', json={'form': _form(PREFIX + 'try'), 'arguments': {'message': 'my billing is wrong'}},
               headers=heads['admin'])
    run = r.json()['run']
    assert run['ok'] and run['result']['label'] == 'billing' and run['model'].startswith('mock/')
    r = c.post('/admin/studio/llm/test', json={'form': _form(PREFIX + 'try'), 'arguments': {'nope': 1}},
               headers=heads['admin'])
    assert r.status_code == 400 and 'input schema' in r.json()['error']
    ans = {'name': PREFIX + 'ans', 'description': 'Answers with calculators.', 'mode': 'answer', 'tools_allow': ['calc_*']}
    r = c.post('/admin/studio/llm/test', json={'form': ans, 'arguments': {'question': 'What is the percentage change from 80 to 100?'},
                                               'run_all': True}, headers=heads['admin'])
    run = r.json()['run']
    assert run['ok'] and [s['name'] for s in run['steps']] == ['calc_percentage_change'] and '25' in run['result']['answer']


def test_deploy_edit_and_ownership(env):
    c, heads, users = env
    from sajha.app import tools_registry
    name = PREFIX + 'triage'
    r = c.post('/admin/studio/llm/deploy', json={'form': _form(name)}, headers=heads['dev'])
    assert r.status_code == 200, r.text
    cfg = json.loads((ROOT / 'config/tools' / f'{name}.json').read_text())
    assert cfg['metadata']['created_by'] == users['dev'] and cfg['metadata']['studio_creator'] == 'llm'
    assert name in tools_registry.tools
    r = c.post('/admin/studio/llm/deploy', json={'form': _form(name)}, headers=heads['dev'])
    assert r.status_code == 400 and 'exists already' in json.dumps(r.json())
    # another developer may read it, not change or delete it
    got = c.get(f'/api/studio/llm/tools/{name}', headers=heads['dev2']).json()
    assert got['editable'] is False and got['form']['labels'] == ['billing', 'technical', 'other']
    r = c.post('/admin/studio/llm/deploy', json={'form': _form(name, labels=['x', 'y']), 'edit': True}, headers=heads['dev2'])
    assert r.status_code == 403
    assert c.post('/admin/studio/delete', json={'tool_name': name}, headers=heads['dev2']).status_code == 403
    # the creator changes it; the creator is kept
    r = c.post('/admin/studio/llm/deploy', json={'form': _form(name, labels=['sales', 'support']), 'edit': True},
               headers=heads['dev'])
    assert r.status_code == 200, r.text
    cfg = json.loads((ROOT / 'config/tools' / f'{name}.json').read_text())
    assert cfg['outputSchema']['properties']['label']['enum'] == ['sales', 'support']
    assert cfg['metadata']['created_by'] == users['dev']
    # shipped LLM tools record no creator: only administrators may change them
    assert c.get('/api/studio/llm/tools/llm_triage_ticket', headers=heads['dev']).json()['editable'] is False
    assert c.get('/api/studio/llm/tools/llm_triage_ticket', headers=heads['admin']).json()['editable'] is True
    r = c.post('/admin/studio/delete', json={'tool_name': name}, headers=heads['dev'])
    assert r.status_code == 200 and name not in tools_registry.tools


# ── Studio permissions per creator (X2) ──────────────────────────────

def test_a_creator_permission_opens_only_that_creator(env):
    c, heads, users = env
    llm = heads['llm']
    assert c.get('/studio/llm', headers=llm).status_code == 200
    assert c.get('/studio', headers=llm).status_code == 200
    for path in ('/studio/rest', '/studio/dbquery', '/studio/script', '/studio/describe', '/studio/api-import',
                 '/studio/planners'):
        assert c.get(path, headers=llm, follow_redirects=False).status_code == 403, path
    assert c.post('/admin/studio/rest/preview', json={}, headers=llm).status_code == 403
    assert c.post('/api/composite-tools', json={'name': 'zz', 'master_tool': 'x'}, headers=llm).status_code == 403
    nav = c.get('/dashboard', cookies=_cookies(c, users['llm'])).text
    assert 'href="/studio/llm"' in nav and 'href="/studio/rest"' not in nav and 'href="/studio/planners"' not in nav
    # studio:* (the developer role) opens every creator but the planner editor
    assert c.get('/studio/rest', headers=heads['dev']).status_code == 200
    assert c.get('/studio/planners', headers=heads['dev']).status_code == 403
    assert c.get('/studio/llm', headers=heads['user']).status_code == 403


def test_permission_helpers():
    from types import SimpleNamespace
    from sajha.auth import AuthContext, STUDIO_CREATORS, can_use_creator, studio_creators
    admin = AuthContext(authenticated=True, is_admin=True)
    assert studio_creators(admin) == list(STUDIO_CREATORS) and can_use_creator(admin, 'planner')
    ctx = AuthContext(authenticated=True, auth_type='jwt')
    ctx._studio_grants_cache = [('llm', {'use'}), ('re*', {'read'})]
    assert can_use_creator(ctx, 'llm') and not can_use_creator(ctx, 'rest') and not can_use_creator(ctx, 'planner')
    ctx._studio_grants_cache = [('*', {'*'})]
    assert set(studio_creators(ctx)) == set(STUDIO_CREATORS) - {'planner'}
    assert not studio_creators(AuthContext(authenticated=True, auth_type='apikey', _db=SimpleNamespace()))


# ── Describe a tool: LLM proposals ───────────────────────────────────

def test_describe_proposes_tests_and_deploys_an_llm_tool(env):
    c, heads, users = env
    from sajha.app import tools_registry
    r = c.post('/admin/studio/describe/propose', json={'description': f'Classify a support message into billing, '
                                                                       f'technical or other', 'kind': 'llm'},
               headers=heads['dev'])
    d = r.json()
    assert d['success'] and d['proposal']['kind'] == 'llm' and not d['errors'], d
    assert d['proposal']['implementation']['mode'] == 'classify'
    assert [f['path'] for f in d['files']] == [f"config/tools/{d['proposal']['name']}.json"]
    p = dict(d['proposal'], name=PREFIX + 'described')
    d = c.post('/admin/studio/describe/revise', json={'draft_id': d['id'], 'proposal': p}, headers=heads['dev']).json()
    assert not d['errors'], d['errors']
    d = c.post('/admin/studio/describe/test', json={'draft_id': d['id']}, headers=heads['dev']).json()
    assert d['tests_run']['counts']['passed'] == 2 and not d['tests_run']['counts']['failed']
    r = c.post('/admin/studio/describe/deploy', json={'draft_id': d['id'], 'hash': d['hash'], 'approve': True},
               headers=heads['dev'])
    assert r.status_code == 200, r.text
    cfg = json.loads((ROOT / 'config/tools' / f'{PREFIX}described.json').read_text())
    assert cfg['implementation'] == 'sajha.ai.llm_tools.LLMTool' and cfg['metadata']['created_by'] == users['dev']
    assert PREFIX + 'described' in tools_registry.tools
    assert c.post('/admin/studio/delete', json={'tool_name': PREFIX + 'described'}, headers=heads['dev']).status_code == 200


def test_describe_rejects_a_bad_llm_block():
    from sajha.studio.describe import validate
    chk = validate({'kind': 'llm', 'name': 'zz_bad_llm', 'description': 'x', 'implementation': {'mode': 'classify'},
                    'output_schema': {'type': 'object', 'properties': {}}, 'tests': [{'name': 't', 'arguments': {}}]})
    assert any(e.startswith('llm: ') for e in chk.errors)


# ── the planner editor ───────────────────────────────────────────────

@pytest.fixture
def temp_planners(tmp_path):
    from sajha.ai.planners_engine.registry import PlannerRegistry, peek_registry, set_registry
    from sajha.ai.planners_engine.settings import PlannerSettings
    from sajha.core.storage import LocalStorageBackend
    shutil.copytree(ROOT / 'config/planners', tmp_path / 'planners')
    old = peek_registry()
    reg = PlannerRegistry(storage=LocalStorageBackend(str(tmp_path)), settings=PlannerSettings(dir='planners',
                                                                                               reload_interval_s=0))
    set_registry(reg)
    yield tmp_path / 'planners'
    set_registry(old)


def test_planner_editor_is_for_admins(env):
    c, heads, _ = env
    assert c.get('/studio/planners', headers=heads['admin']).status_code == 200
    for who in ('dev', 'llm', 'user'):
        assert c.get('/api/studio/planners', headers=heads[who]).status_code == 403
        assert c.post('/admin/studio/planners/save', json={'text': 'x'}, headers=heads[who]).status_code == 403


def test_planner_check_and_versioned_save(env, temp_planners):
    c, heads, _ = env
    a = heads['admin']
    bad = 'name: mine\nversion: 1.0.0\nstart: nowhere\nstages:\n  act: { type: act, outcomes: { called: { next: act, max_visits: 2 } } }\n'
    chk = c.post('/admin/studio/planners/check', json={'text': bad}, headers=a).json()
    codes = {e['code'] for e in chk['errors']}
    assert not chk['valid'] and 'P012' in codes and all(e['message'] for e in chk['errors'])
    assert c.post('/admin/studio/planners/save', json={'text': bad}, headers=a).status_code == 400
    assert not (temp_planners / 'mine.yaml').exists()
    good = ('name: mine\nversion: 1.0.0\ndescription: d\nuse_when: u\nstart: act\nstages:\n'
            '  act: { type: act, outcomes: { called: { next: act, max_visits: 2, on_exhausted: answer }, answered: { next: answer } } }\n'
            '  answer: { type: answer }\n')
    r = c.post('/admin/studio/planners/save', json={'text': good}, headers=a)
    assert r.status_code == 200 and (temp_planners / 'mine.yaml').exists(), r.text
    assert c.post('/admin/studio/planners/save', json={'text': good.replace('description: d', 'description: e')},
                  headers=a).status_code == 409
    r = c.post('/admin/studio/planners/save', json={'text': good.replace('1.0.0', '1.1.0')}, headers=a)
    assert r.json()['kept'] == 'mine@1.0.0.yaml' and (temp_planners / 'mine@1.0.0.yaml').exists()
    src = c.get('/api/studio/planners/mine', headers=a).json()
    assert src['version'] == '1.1.0' and src['versions'] == ['1.0.0', '1.1.0'] and src['valid']
    assert c.get('/api/studio/planners/mine@1.0.0', headers=a).json()['version'] == '1.0.0'
    dry = c.post('/api/ai/planners/dry-run', json={'planner': src['doc'], 'question': 'What is 2 plus 2?'}, headers=a).json()
    assert dry['path'][0] == 'act' and dry['path'][-1] == 'answer'
    # an edit made outside the editor that does not validate: the registry keeps the last good version
    (temp_planners / 'mine.yaml').write_text(good.replace('1.0.0', '1.1.0').replace('start: act', 'start: gone'))
    lst = c.get('/api/studio/planners', headers=a).json()
    refused = {x['file']: x for x in lst['refused']}
    assert refused['mine.yaml']['in_use'] and '1.1.0' in refused['mine.yaml']['last_good']


# ── the Conversations page ───────────────────────────────────────────

def test_conversations_page_and_admin_counts(env):
    c, heads, users = env
    page = c.get('/conversations', cookies=_cookies(c, users['user']))
    assert page.status_code == 200 and 'Delete all my conversations' in page.text and 'Stored on this server' not in page.text
    assert c.get('/api/ai/conversation-counts', headers=heads['user']).status_code == 403
    r = c.post('/api/ai/ask', json={'question': 'What is the percentage change from 80 to 100?', 'conversation_id': 'new'},
               headers=heads['user'])
    conv = r.json().get('conversation_id')
    assert conv
    mine = c.get('/api/ai/conversations', headers=heads['user']).json()['conversations']
    assert conv in [x['id'] for x in mine]
    assert conv not in [x['id'] for x in c.get('/api/ai/conversations', headers=heads['dev']).json()['conversations']]
    counts = c.get('/api/ai/conversation-counts', headers=heads['admin']).json()
    assert counts['counts'].get('ask', 0) >= 1 and 'conversations' not in counts
    admin_page = c.get('/conversations', cookies=_cookies(c, 'admin', 'admin123')).text
    assert 'Stored on this server' in admin_page
    assert c.delete(f'/api/ai/conversations/{conv}', headers=heads['user']).json() == {'deleted': 1}
