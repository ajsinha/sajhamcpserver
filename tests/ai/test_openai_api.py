# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""SAJHA as an OpenAI-compatible endpoint (sajha/ai/openai_api.py, sajha/routes/openai_routes.py;
docs/architecture/LLM Tools.md §13.4), proved with the official ``openai`` Python SDK where it is
installed: chat, streaming, models, embeddings and an LLM tool as a model; API-key auth as the
bearer; the caller sees only the models and LLM tools their role allows; OpenAI-shaped errors;
policy rate limits; the surface is off by default."""

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))


def _db():
    from sajha.db.engine import get_db_session
    return get_db_session()


def _make_user(role):
    from sajha.auth.password import hash_password
    from sajha.db.dao import RoleDAO, UserDAO
    from sajha.db.models import User
    uid = f'oai_{role}_{uuid.uuid4().hex[:8]}'
    db = _db()
    try:
        user = User(user_id=uid, user_name=uid, email='', password_hash=hash_password('Oai-Pass-12345'), enabled=True)
        user.roles.append(RoleDAO(db).get_or_create(role))
        UserDAO(db).create(user)
    finally:
        db.close()
    return uid


def _key(uid):
    from sajha.auth import apikeys as svc
    from sajha.db.dao import UserDAO
    db = _db()
    try:
        _, raw = svc.create_key(db, name='oai-' + uuid.uuid4().hex[:6], created_by='test',
                                owner=UserDAO(db).get_by_user_id(uid))
        return raw
    finally:
        db.close()


def _llm_tool(name, base, **llm):
    from sajha.ai.llm_tools import LLMTool
    with open(f'config/tools/{base}.json') as f:
        cfg = json.load(f)
    cfg.update(name=name, enabled=True)
    cfg['llm'] = {**cfg['llm'], **llm}
    return LLMTool(cfg)


@pytest.fixture(scope='module')
def env():
    from fastapi.testclient import TestClient
    os.environ['SAJHA_AI_OPENAI_API_ENABLED'] = 'true'
    from sajha.app import create_app
    try:
        with TestClient(create_app()) as c:
            from sajha.app import tools_registry
            for t in (_llm_tool('oai_summarise', 'llm_summarise'),
                      _llm_tool('oai_docs_qa', 'llm_docs_qa')):
                tools_registry.register_tool(t)
            users = {r: _make_user(r) for r in ('user', 'viewer')}
            keys = {r: _key(u) for r, u in users.items()}
            yield c, keys
            for n in ('oai_summarise', 'oai_docs_qa'):
                tools_registry.unregister_tool(n)
    finally:
        os.environ.pop('SAJHA_AI_OPENAI_API_ENABLED', None)


def H(key):
    return {'Authorization': f'Bearer {key}'}


# ── over HTTP ───────────────────────────────────────────────────────

def test_a_key_is_required_and_errors_are_openai_shaped(env):
    c, keys = env
    r = c.get('/v1/models')
    assert r.status_code == 401 and r.json()['error']['code'] == 'invalid_api_key'
    r = c.get('/v1/models', headers=H('sja_not_a_key'))
    assert r.status_code == 401
    r = c.post('/v1/chat/completions', headers=H(keys['user']), json={'model': 'default'})
    assert r.status_code == 400 and set(r.json()['error']) == {'message', 'type', 'param', 'code'}
    r = c.post('/v1/chat/completions', headers=H(keys['user']),
               json={'model': 'nobody/nothing', 'messages': [{'role': 'user', 'content': 'hi'}]})
    assert r.status_code == 404 and r.json()['error']['code'] == 'model_not_found'


def test_models_follow_the_callers_role(env):
    c, keys = env
    ids = {m['id'] for m in c.get('/v1/models', headers=H(keys['user'])).json()['data']}
    assert {'default', 'mock/mock-planner', 'sajha:oai_summarise', 'sajha:oai_docs_qa'} <= ids
    viewer = {m['id'] for m in c.get('/v1/models', headers=H(keys['viewer'])).json()['data']}
    assert 'mock/mock-planner' in viewer and not any(i.startswith('sajha:') for i in viewer)   # no execute
    r = c.post('/v1/chat/completions', headers=H(keys['viewer']),
               json={'model': 'sajha:oai_summarise', 'messages': [{'role': 'user', 'content': 'x'}]})
    assert r.status_code == 404
    assert c.get('/v1/models/sajha:oai_summarise', headers=H(keys['user'])).json()['sajha']['mode'] == 'complete'


def test_the_sajha_field_never_sets_the_identity(env):
    c, keys = env
    r = c.post('/v1/chat/completions', headers=H(keys['viewer']), json={
        'model': 'default', 'messages': [{'role': 'user', 'content': 'hello'}],
        'sajha': {'context': {'user_id': 'admin', 'roles': ['admin'], 'is_admin': True}}})
    assert r.status_code == 200
    from sajha.ai.llm import llm_factory
    usage = llm_factory().get_token_usage()
    assert 'admin' not in usage or all(k != 'admin' for k in usage if k.startswith('oai_'))


def test_a_policy_rule_rate_limits_the_surface(env):
    from sajha.policy.engine import PolicyEngine, get_engine, set_engine
    from sajha.policy.loader import PolicySet
    from sajha.policy.model import parse_text
    c, keys = env
    before = get_engine()
    ps = PolicySet()
    ps.set_policies([parse_text("rules:\n  - id: oai-rate\n    match: {tools: ['openai_api.*'], sources: [openai_api]}\n"
                                "    rate_limit: {limit: 1, window: 1m, per: [user]}\n", 'oai', 'oai.yaml')])
    set_engine(PolicyEngine(ps))
    try:
        body = {'model': 'default', 'messages': [{'role': 'user', 'content': 'hello'}]}
        assert c.post('/v1/chat/completions', headers=H(keys['user']), json=body).status_code == 200
        r = c.post('/v1/chat/completions', headers=H(keys['user']), json=body)
        assert r.status_code == 429 and r.json()['error']['type'] == 'rate_limit_error' and r.headers['Retry-After']
    finally:
        set_engine(before)


def test_off_by_default():
    from sajha.ai.llm.settings import AISettings
    assert AISettings({}, environ={}).openai_api.enabled is False


# ── with the official openai SDK ───────────────────────────────────

@pytest.fixture
def sdk(env):
    openai = pytest.importorskip('openai')
    c, keys = env
    return openai, openai.OpenAI(api_key=keys['user'], base_url='http://testserver/v1', http_client=c, max_retries=0)


def test_sdk_chat_streaming_models_and_embeddings(sdk):
    openai, client = sdk
    ids = [m.id for m in client.models.list()]
    assert 'default' in ids and 'sajha:oai_summarise' in ids
    comp = client.chat.completions.create(model='default', messages=[{'role': 'user', 'content': 'Say hello'}])
    assert comp.object == 'chat.completion' and comp.choices[0].message.role == 'assistant'
    assert comp.choices[0].message.content and comp.usage.total_tokens >= 0
    stream = client.chat.completions.create(model='default', messages=[{'role': 'user', 'content': 'Say hello'}],
                                            stream=True, stream_options={'include_usage': True})
    chunks = list(stream)
    text = ''.join(ch.choices[0].delta.content or '' for ch in chunks if ch.choices)
    assert text and chunks[-1].usage is not None
    emb = client.embeddings.create(model='embedding', input=['alpha', 'beta'])         # SDK default: base64
    assert len(emb.data) == 2 and len(emb.data[0].embedding) > 0
    emb = client.embeddings.create(model='embedding', input='alpha', encoding_format='float')
    assert isinstance(emb.data[0].embedding[0], float)
    with pytest.raises(openai.NotFoundError):
        client.chat.completions.create(model='nobody/nothing', messages=[{'role': 'user', 'content': 'x'}])


def test_sdk_llm_tool_as_a_model(sdk):
    openai, client = sdk
    comp = client.chat.completions.create(model='sajha:oai_summarise', messages=[
        {'role': 'user', 'content': 'Rates rose 25 basis points. Markets fell. Bonds rallied.'}])
    assert comp.choices[0].message.content.startswith('Rates rose 25 basis points.')
    assert comp.model == 'sajha:oai_summarise' and comp.model_extra['sajha']['stopped_by'] == 'answer'
    stream = client.chat.completions.create(model='sajha:oai_summarise', stream=True, messages=[
        {'role': 'user', 'content': json.dumps({'text': 'One. Two. Three.', 'max_sentences': 2})}])
    assert ''.join(ch.choices[0].delta.content or '' for ch in stream if ch.choices) == 'One. Two.'
    # a tool with conversation memory: the handle travels in the sajha field
    first = client.chat.completions.create(model='sajha:oai_docs_qa', messages=[
        {'role': 'user', 'content': 'How do I enable sampling?'}], extra_body={'sajha': {'conversation_id': 'new'}})
    cid = first.model_extra['sajha'].get('conversation_id')
    assert cid and first.choices[0].message.content
    again = client.chat.completions.create(model='sajha:oai_docs_qa', messages=[
        {'role': 'user', 'content': 'And on 2025-11-25?'}], extra_body={'sajha': {'conversation_id': cid}})
    assert again.model_extra['sajha'].get('conversation_id') == cid
    with pytest.raises(openai.BadRequestError):
        client.chat.completions.create(model='sajha:oai_summarise', messages=[{'role': 'user', 'content': 'x'}],
                                       tools=[{'type': 'function', 'function': {'name': 'f', 'parameters': {}}}])
