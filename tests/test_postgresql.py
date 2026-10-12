# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""SAJHA's repositories on a real PostgreSQL server (they run on SQLite everywhere else in the suite).

Runs when SAJHA_TEST_PG_URL names a disposable PostgreSQL database; skips otherwise. The schema is built
from db/scripts/postgresql/schema.sql and seed.sql in a private PostgreSQL schema (tests/pg_support.py),
the way an operator builds it, and SAJHA's start-up check must find it complete. Covered: the DAOs of
sajha/db/dao (users, roles, permissions, API keys with time zones, tool usage reports including the
heatmap's date parts, audit log, A2A tasks, prompts with tags and ILIKE search, LLM providers and models,
composite tools), the workflow store, the connected-accounts vault, conversation memory, the audit chain
and the start-up schema check. The state store's database backend runs its whole contract on PostgreSQL
as the ``database_pg`` backend of tests/test_state_store.py. Guide: docs/getting-started/Database Setup.md.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from tests.pg_support import PG_URL, pg_engine

pytestmark = pytest.mark.skipif(not PG_URL, reason='set SAJHA_TEST_PG_URL to a disposable PostgreSQL database')


@pytest.fixture
def engine():
    return pg_engine()


@pytest.fixture
def db(engine):
    from sqlalchemy.orm import sessionmaker
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.rollback()
    s.close()


def _u(prefix='t'):
    return f'{prefix}_{uuid.uuid4().hex[:10]}'


# ── schema ────────────────────────────────────────────────────────────

def test_the_operator_built_schema_passes_the_start_up_check(engine):
    from sajha.db import schema
    assert engine.dialect.name == 'postgresql'
    assert schema.missing(engine) == {}
    assert schema.check(engine, 'strict') == {}


# ── sajha/db/dao ──────────────────────────────────────────────────────

def test_users_roles_and_permissions(db):
    from sajha.auth.password import hash_password
    from sajha.db.dao import PermissionDAO, RoleDAO, UserDAO
    from sajha.db.models import User
    users, roles = UserDAO(db), RoleDAO(db)
    admin = users.get_by_user_id('admin')
    assert admin is not None and admin.is_admin is True and admin.must_change_password is True
    assert sorted(r.name for r in roles.get_all()) == ['admin', 'developer', 'llm_author', 'user', 'viewer']
    uid = _u('user')
    u = User(user_id=uid, user_name='PG User', email=f'{uid}@example.com', password_hash=hash_password('pw'))
    u.roles.append(roles.get_by_name('user'))
    users.create(u)
    got = users.get_by_user_id(uid)
    assert got.role_names == ['user'] and got.is_admin is False and got.enabled is True
    assert users.get_by_email(f'{uid}@example.com').user_id == uid
    assert uid in [x.user_id for x in users.get_enabled_users()]
    users.update_last_login(uid)
    assert users.get_by_user_id(uid).last_login.tzinfo is not None      # TIMESTAMPTZ
    r1 = roles.get_or_create(_u('role'), 'x')
    assert roles.get_or_create(r1.name, 'y').id == r1.id
    perm = PermissionDAO(db)
    assert perm.check_access(admin.roles, 'tool', 'anything', 'execute') is True
    assert perm.check_access(got.roles, 'tool', 'calc_npv', 'execute') is True
    assert perm.check_access([], 'tool', 'anything', 'execute') is False


def test_api_keys_with_aware_expiry(db):
    from sajha.db.dao import ApiKeyDAO
    from sajha.db.models import ApiKey
    dao = ApiKeyDAO(db)
    raw, old = f'sja_{uuid.uuid4().hex}', f'sja_{uuid.uuid4().hex}'
    dao.create(ApiKey(key_hash=dao.hash_key(raw), key_prefix=raw[:8], name=_u('key'),
                      expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    dao.create(ApiKey(key_hash=dao.hash_key(old), key_prefix=old[:8], name=_u('key'),
                      expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    valid, key, _ = dao.validate_key(raw)
    assert valid is True and key.expires_at.tzinfo is not None
    dao.record_usage(key)
    assert dao.validate_key(raw)[1].usage_count == 1
    assert dao.validate_key(old)[0] is False and dao.validate_key(old)[2] == 'API key has expired'
    assert dao.validate_key('sja_nope')[0] is False
    key.enabled = False
    db.commit()
    assert dao.validate_key(raw)[2] == 'API key is disabled'
    assert key.id not in [k.id for k in dao.get_all_keys()]
    assert key.id in [k.id for k in dao.get_all_keys(include_disabled=True)]


def test_tool_usage_reports(db):
    from sajha.db.dao import ToolUsageDAO
    dao = ToolUsageDAO(db)
    tool, user = _u('tool'), _u('user')
    for i in range(10):
        dao.log_execution(tool, user, 'jwt', 100 + i * 10, True, arguments={'i': i})
    dao.log_execution(tool, user, 'jwt', 5000, False, error_message='crash')
    since, until = datetime.now(timezone.utc) - timedelta(hours=1), datetime.now(timezone.utc) + timedelta(hours=1)
    row = [r for r in dao.get_usage_by_tool(since, until) if r['tool_name'] == tool][0]
    assert (row['total_calls'], row['success_count'], row['error_count']) == (11, 10, 1)
    assert [r for r in dao.get_usage_by_user(since, until) if r['user_id'] == user][0]['total_calls'] == 11
    assert dao.get_overview(24)['total_calls'] >= 11
    detail = dao.get_tool_detail(tool, days=1)
    assert detail['total_calls'] == 11 and detail['error_count'] == 1 and detail['p95_ms'] >= detail['p50_ms'] > 0
    assert len(detail['recent_errors']) == 1
    cells = dao.get_hourly_heatmap(days=1, tool_name=tool)
    assert sum(c['count'] for c in cells) == 11
    now = datetime.now(timezone.utc)
    assert all(0 <= c['day_of_week'] <= 6 and 0 <= c['hour'] <= 23 for c in cells)
    assert any(c['hour'] in (now.hour, (now.hour - 1) % 24) for c in cells)


def test_audit_log_and_a2a_tasks(db):
    from sajha.db.dao import A2ATaskDAO, AuditDAO
    from sajha.db.models import A2ATask
    audit, action = AuditDAO(db), _u('act')
    audit.log(action, 'admin', 'tool', 'x', {'enabled': True}, '127.0.0.1')
    rows = audit.get_recent(10, action=action)
    assert len(rows) == 1 and rows[0].created_at.tzinfo is not None
    tasks, sess = A2ATaskDAO(db), _u('sess')
    t = tasks.create(A2ATask(session_id=sess, state='submitted', caller_agent='agent'))
    tasks.update_state(t.id, 'completed', output='{"ok": true}')
    assert tasks.get_by_id(t.id).state == 'completed'
    assert [x.id for x in tasks.get_by_session(sess)] == [t.id]


def test_prompts_tags_and_case_insensitive_search(db):
    from sajha.db.dao import PromptDAO
    dao, name = PromptDAO(db), _u('prompt')
    dao.create_prompt(name, 'Hello {{who}}', description='Greets SOMEONE', category='pgcat',
                      arguments=[{'name': 'who'}], tags=['pg', 'greeting'])
    assert dao.get_by_name(name).enabled is True
    assert name in [p.name for p in dao.search('someone')]          # ILIKE on PostgreSQL
    assert name in [p.name for p in dao.get_by_tag('pg')]
    assert 'pgcat' in dao.get_categories() and 'greeting' in dao.get_tags()
    dao.update_prompt(name, tags=['other'], description='changed')
    assert [t.tag for t in dao.get_by_name(name).tags] == ['other']
    assert dao.delete_prompt(name) is True and dao.get_by_name(name) is None


def test_llm_providers_and_models(db):
    from sajha.db.dao import LLMModelDAO, LLMProviderDAO
    from sajha.db.models import LLMProviderRecord
    providers, models = LLMProviderDAO(db), LLMModelDAO(db)
    ptype = _u('prov')
    providers.create(LLMProviderRecord(id=str(uuid.uuid4()), provider_type=ptype, display_name='PG provider',
                                       enabled=True))
    assert providers.set_default(ptype) is True and providers.get_default().provider_type == ptype
    m1, m2 = _u('model'), _u('model')
    models.create_model(ptype, m1, 'M1')
    models.create_model(ptype, m2, 'M2')
    assert models.set_default(ptype, m2) is True
    assert models.get_default_for_provider(ptype).model_id == m2
    assert {m.model_id for m in models.get_by_provider(ptype)} == {m1, m2}
    models.update_model(m1, display_name='M1b')
    assert models.get_by_model_id(m1).display_name == 'M1b'
    assert models.delete_model(m1) is True
    db.query(LLMProviderRecord).filter(LLMProviderRecord.provider_type == ptype).delete()
    db.commit()


def test_composite_tools(db):
    from sajha.db.dao import CompositeToolDAO
    dao, name = CompositeToolDAO(db), _u('comp')
    dao.create(name, 'calc_npv', description='pg', steps=[
        {'tool_name': 'calc_irr', 'output_key': 'irr', 'param_mapping': {'a': 'b'}}])
    rec = dao.get_by_name(name)
    assert rec.enabled is True and [s.tool_name for s in rec.steps] == ['calc_irr']
    dao.update(name, description='pg2', steps=[{'tool_name': 'calc_wacc', 'output_key': 'w'},
                                              {'tool_name': 'calc_capm', 'output_key': 'c'}])
    assert [s['tool_name'] for s in dao.to_dict(dao.get_by_name(name))['steps']] == ['calc_wacc', 'calc_capm']
    assert name in [r.name for r in dao.get_all()]
    assert dao.delete(name) is True


# ── stores that own their tables ──────────────────────────────────────

def test_workflow_store(engine):
    from sajha.workflows.store import WorkflowStore
    store, name = WorkflowStore(engine), _u('wf')
    defn = {'name': name, 'steps': [{'id': 'a', 'kind': 'tool', 'tool': 'calc_npv', 'params': {}}]}
    saved = store.save_workflow(defn, owner='admin', by='admin')
    assert saved['version'] == 1 and store.get_workflow(name)['enabled'] is True
    assert store.set_enabled(name, False) is True and store.get_workflow(name)['enabled'] is False
    run, created = store.create_run(workflow=name, version=1, definition=defn, run_as='admin',
                                    trigger_type='manual', idempotency_key='k1')
    assert created and store.create_run(workflow=name, version=1, definition=defn, run_as='admin',
                                        trigger_type='manual', idempotency_key='k1') == (run, False)
    assert store.claim_run(run['id'], from_status=['queued'], to_status='running', worker_id='w1') is True
    assert store.claim_run(run['id'], from_status=['queued'], to_status='running', worker_id='w2') is False
    assert store.count_active(name) == 1 and store.heartbeat(run['id'], 'w1') is True
    store.put_step(run['id'], 'a', 'tool', status='succeeded', output={'npv': 1})
    assert store.get_steps(run['id'])[0]['status'] == 'succeeded'
    assert store.request_cancel(run['id']) is True and store.cancel_requested(run['id']) is True
    assert store.finish_run(run['id'], 'succeeded', output={'ok': True}) is True
    assert store.get_run(run['id'])['status'] == 'succeeded'
    assert [r['id'] for r in store.list_runs(name)] == [run['id']]
    assert store.delete_workflow(name) is True and store.get_run(run['id']) is None


def test_connected_accounts_vault(engine):
    from sajha.accounts.vault import LocalKeyProvider, TokenVault
    vault, user = TokenVault(engine, LocalKeyProvider('pg-test-secret')), _u('user')
    exp = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)     # the vault works in naive UTC
    vault.save(user, 'github', {'access_token': 'a', 'refresh_token': 'r'}, scopes=['repo'], expires_at=exp,
               account_login='octo')
    conn = vault.get(user, 'github')
    assert conn.has_refresh_token is True and vault.tokens(conn)['access_token'] == 'a'
    assert not conn.expired and conn.expires_within(7200)
    vault.set_status(user, 'github', 'reauth_required', 'boom')
    assert vault.get(user, 'github').status == 'reauth_required'
    assert [c.provider for c in vault.list_for_user(user)] == ['github']


def test_conversation_memory(engine):
    from sajha.ai.memory import ConversationStore
    store, user, cid = ConversationStore(engine), _u('user'), str(uuid.uuid4())
    for q in ('first', 'second'):
        store.add_turn(cid, user, question=q, standalone=q, answer='a', tools=['calc_npv'],
                       stopped_by='answer', confidence=0.9, title='PG')
    assert store.get(cid, user)['title'] == 'PG'
    assert [t['question'] for t in store.turns(cid, user)] == ['first', 'second']
    assert [c['id'] for c in store.list(user)] == [cid]
    assert store.delete(cid, user) is True and store.get(cid, user) is None


def test_audit_chain(engine):
    from sajha.audit import chain
    w = chain.ChainWriter(engine, anchor_every=2, anchor_interval=3600, store=True)
    try:
        for i in range(3):
            w.append('pg.test', actor={'user_id': 'admin'}, resource={'type': 'tool', 'id': str(i)})
        assert w.flush() is True
        recs = chain.recent(engine, 10, event='pg.test', chain_id=w.chain_id)
        seqs = [r['seq'] for r in recs]
        assert len(seqs) == 3 and seqs == sorted(seqs, reverse=True)       # newest first
    finally:
        w.close()
    from sajha.audit.verify import verify
    res = verify(engine, w.chain_id)
    assert res['ok'] is True and res['records'] >= 3      # the three records and the chain's own entries


def test_concurrent_sessions_see_committed_rows(engine):
    """Two sessions (two pool connections): a commit in one is visible in the other, and a failed
    statement rolls back cleanly so the session stays usable (PostgreSQL aborts the transaction)."""
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker
    from sajha.db.dao import RoleDAO
    S = sessionmaker(bind=engine)
    a, b = S(), S()
    try:
        name = _u('role')
        RoleDAO(a).get_or_create(name)
        assert RoleDAO(b).get_by_name(name) is not None
        from sajha.db.models import Role
        a.add(Role(name=name))
        with pytest.raises(IntegrityError):
            a.commit()
        a.rollback()
        assert RoleDAO(a).get_by_name(name) is not None
    finally:
        a.close()
        b.close()
