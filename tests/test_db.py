"""
Tests for sajha.db — SQL scripts, engine, models, DAOs, RBAC.
"""

import os
import sys
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))


def _make_db(tmp_dir: str):
    """Create a fresh test DB with SQL scripts executed."""
    from sqlalchemy import create_engine, text, inspect
    from sqlalchemy.orm import sessionmaker

    db_path = os.path.join(tmp_dir, 'test.db')
    url = f'sqlite:///{db_path}'
    engine = create_engine(url, connect_args={'check_same_thread': False})

    # Run schema script
    schema = Path('db/scripts/001_schema.sql').read_text()
    seed = Path('db/scripts/002_seed.sql').read_text()

    with engine.connect() as conn:
        for sql in [schema, seed]:
            for stmt in sql.split(';'):
                stmt = stmt.strip()
                lines = [l for l in stmt.split('\n') if l.strip() and not l.strip().startswith('--')]
                if lines:
                    try:
                        conn.execute(text(stmt))
                    except Exception:
                        pass
            conn.commit()

    Session = sessionmaker(bind=engine)
    return engine, Session()


class TestSQLScripts:
    """Test that SQL scripts create correct schema and seed data."""

    def test_schema_creates_all_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, db = _make_db(tmp)
            from sqlalchemy import inspect
            tables = inspect(engine).get_table_names()
            expected = ['a2a_tasks', 'api_keys', 'audit_log', 'permissions',
                        'roles', 'tool_usage_events', 'user_roles', 'user_sessions', 'users']
            for t in expected:
                assert t in tables, f'Missing table: {t}'
            db.close()

    def test_seed_creates_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, db = _make_db(tmp)
            from sqlalchemy import text
            roles = db.execute(text('SELECT name FROM roles ORDER BY name')).fetchall()
            role_names = [r[0] for r in roles]
            assert 'admin' in role_names
            assert 'user' in role_names
            assert 'analyst' in role_names
            assert 'viewer' in role_names
            assert 'tool_developer' in role_names
            assert 'api_consumer' in role_names
            assert len(role_names) == 6
            db.close()

    def test_seed_creates_admin_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, db = _make_db(tmp)
            from sqlalchemy import text
            admin = db.execute(text("SELECT user_id, user_name FROM users WHERE user_id='admin'")).fetchone()
            assert admin is not None
            assert admin[0] == 'admin'
            assert admin[1] == 'Administrator'
            db.close()

    def test_seed_creates_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, db = _make_db(tmp)
            from sqlalchemy import text
            perms = db.execute(text('SELECT COUNT(*) FROM permissions')).scalar()
            assert perms >= 10  # 11 permissions in seed
            db.close()

    def test_seed_assigns_admin_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine, db = _make_db(tmp)
            from sqlalchemy import text
            ur = db.execute(text(
                "SELECT r.name FROM user_roles ur "
                "JOIN roles r ON ur.role_id = r.id "
                "WHERE ur.user_id = 'user-admin-0001'"
            )).fetchall()
            assert any(r[0] == 'admin' for r in ur)
            db.close()

    def test_scripts_are_idempotent(self):
        """Running scripts twice should not duplicate data."""
        with tempfile.TemporaryDirectory() as tmp:
            engine, db = _make_db(tmp)
            # Run again
            from sqlalchemy import text
            schema = Path('db/scripts/001_schema.sql').read_text()
            seed = Path('db/scripts/002_seed.sql').read_text()
            with engine.connect() as conn:
                for sql in [schema, seed]:
                    for stmt in sql.split(';'):
                        stmt = stmt.strip()
                        lines = [l for l in stmt.split('\n') if l.strip() and not l.strip().startswith('--')]
                        if lines:
                            try:
                                conn.execute(text(stmt))
                            except Exception:
                                pass
                    conn.commit()
            roles = db.execute(text('SELECT COUNT(*) FROM roles')).scalar()
            assert roles == 6  # Not 12
            users = db.execute(text('SELECT COUNT(*) FROM users')).scalar()
            assert users == 1  # Not 2
            db.close()


class TestDAOs:
    """Test DAO operations using ORM models."""

    def _setup_orm_db(self, tmp_dir):
        """Setup DB through engine.init_db (runs SQL scripts + ORM mapping)."""
        from sajha.core.config import get_settings
        from sajha.db import engine as eng

        eng._engine = None
        eng._SessionLocal = None

        s = get_settings()
        # Monkey-patch for test
        db_file = os.path.join(tmp_dir, 'test.db')
        orig = type(s).database_url.fget
        type(s).database_url = property(lambda self: f'sqlite:///{db_file}')

        from sajha.db.engine import init_db, get_db_session
        init_db(s)
        session = get_db_session()
        type(s).database_url = property(orig)
        return session, eng

    def test_user_dao_get_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import UserDAO
            dao = UserDAO(db)
            admin = dao.get_by_user_id('admin')
            assert admin is not None
            assert admin.user_id == 'admin'
            assert admin.is_admin is True
            assert 'admin' in admin.role_names
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_user_dao_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import UserDAO, RoleDAO
            from sajha.db.models import User
            from sajha.auth.password import hash_password

            user_dao = UserDAO(db)
            role_dao = RoleDAO(db)

            user = User(
                user_id='testuser',
                user_name='Test User',
                email='test@example.com',
                password_hash=hash_password('pass123'),
            )
            role = role_dao.get_by_name('user')
            user.roles.append(role)
            user_dao.create(user)

            fetched = user_dao.get_by_user_id('testuser')
            assert fetched is not None
            assert fetched.user_name == 'Test User'
            assert 'user' in fetched.role_names
            assert fetched.is_admin is False
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_user_dao_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import UserDAO
            assert UserDAO(db).count() == 1  # Just admin from seed
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_role_dao_get_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import RoleDAO
            roles = RoleDAO(db).get_all()
            assert len(roles) == 6
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_role_dao_get_or_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import RoleDAO
            dao = RoleDAO(db)
            r1 = dao.get_or_create('custom_role', 'A custom role')
            r2 = dao.get_or_create('custom_role', 'Different desc')
            assert r1.id == r2.id  # Same role returned
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_permission_dao_admin_wildcard(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import UserDAO, PermissionDAO
            admin = UserDAO(db).get_by_user_id('admin')
            perm = PermissionDAO(db)
            assert perm.check_access(admin.roles, 'tool', 'anything', 'execute') is True
            assert perm.check_access(admin.roles, 'admin', 'users', 'delete') is True
            assert perm.check_access(admin.roles, 'report', 'audit', 'read') is True
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_permission_dao_no_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import PermissionDAO
            perm = PermissionDAO(db)
            assert perm.check_access([], 'tool', 'anything', 'execute') is False
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_apikey_dao_create_and_validate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import ApiKeyDAO
            from sajha.db.models import ApiKey
            dao = ApiKeyDAO(db)
            raw = 'sja_test123456789'
            key = ApiKey(
                key_hash=dao.hash_key(raw),
                key_prefix=raw[:8],
                name='Test Key',
            )
            dao.create(key)
            valid, found, msg = dao.validate_key(raw)
            assert valid is True
            assert found.name == 'Test Key'
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_apikey_dao_invalid_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import ApiKeyDAO
            valid, _, msg = ApiKeyDAO(db).validate_key('sja_nonexistent')
            assert valid is False
            assert 'Invalid' in msg
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_tool_usage_dao_log_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import ToolUsageDAO
            dao = ToolUsageDAO(db)

            dao.log_execution('tool_a', 'admin', 'jwt', 100, True)
            dao.log_execution('tool_a', 'admin', 'jwt', 200, True)
            dao.log_execution('tool_b', 'admin', 'jwt', 50, False, error_message='timeout')

            overview = dao.get_overview(24)
            assert overview['total_calls'] == 3
            assert overview['error_count'] == 1
            assert overview['error_rate'] == pytest.approx(33.3, abs=0.1)
            assert overview['active_users'] == 1

            since = datetime.now(timezone.utc) - timedelta(hours=1)
            until = datetime.now(timezone.utc) + timedelta(hours=1)
            by_tool = dao.get_usage_by_tool(since, until)
            assert len(by_tool) == 2
            assert by_tool[0]['tool_name'] == 'tool_a'  # Most calls first
            assert by_tool[0]['total_calls'] == 2

            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_tool_usage_dao_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import ToolUsageDAO
            dao = ToolUsageDAO(db)

            for i in range(10):
                dao.log_execution('perf_tool', 'admin', 'jwt', 100 + i * 10, True)
            dao.log_execution('perf_tool', 'admin', 'jwt', 5000, False, error_message='crash')

            detail = dao.get_tool_detail('perf_tool', days=1)
            assert detail['total_calls'] == 11
            assert detail['error_count'] == 1
            assert detail['p50_ms'] > 0
            assert detail['p95_ms'] >= detail['p50_ms']
            assert len(detail['recent_errors']) == 1
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_audit_dao(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import AuditDAO
            dao = AuditDAO(db)

            dao.log('user.login', 'admin', 'user', 'admin')
            dao.log('tool.enable', 'admin', 'tool', 'duckdb_query', {'enabled': True})
            dao.log('user.create', 'admin', 'user', 'newuser')

            all_logs = dao.get_recent(10)
            assert len(all_logs) == 3

            login_only = dao.get_recent(10, action='user.login')
            assert len(login_only) == 1
            assert login_only[0].actor_id == 'admin'
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_a2a_task_dao(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup_orm_db(tmp)
            from sajha.db.dao import A2ATaskDAO
            from sajha.db.models import A2ATask
            dao = A2ATaskDAO(db)

            task = A2ATask(session_id='sess-1', state='submitted', caller_agent='test-agent')
            dao.create(task)

            fetched = dao.get_by_id(task.id)
            assert fetched.state == 'submitted'

            dao.update_state(task.id, 'completed', output='{"result": "ok"}')
            fetched = dao.get_by_id(task.id)
            assert fetched.state == 'completed'
            assert fetched.output_artifacts == '{"result": "ok"}'

            by_session = dao.get_by_session('sess-1')
            assert len(by_session) == 1
            db.close()
            eng._engine = None; eng._SessionLocal = None


class TestAuthManager:
    """Test unified AuthManager."""

    def _setup(self, tmp_dir):
        from sajha.core.config import get_settings
        from sajha.db import engine as eng
        eng._engine = None; eng._SessionLocal = None
        s = get_settings()
        db_file = os.path.join(tmp_dir, 'test.db')
        orig = type(s).database_url.fget
        type(s).database_url = property(lambda self: f'sqlite:///{db_file}')
        from sajha.db.engine import init_db, get_db_session
        init_db(s)
        db = get_db_session()
        type(s).database_url = property(orig)
        return db, eng

    def test_local_login_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup(tmp)
            from sajha.auth import AuthManager
            token = AuthManager.authenticate_local(db, 'admin', 'admin123')
            assert token is not None
            assert len(token) > 50
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_local_login_wrong_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup(tmp)
            from sajha.auth import AuthManager
            token = AuthManager.authenticate_local(db, 'admin', 'wrongpass')
            assert token is None
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_local_login_nonexistent_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup(tmp)
            from sajha.auth import AuthManager
            token = AuthManager.authenticate_local(db, 'nobody', 'pass')
            assert token is None
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_jwt_auth_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup(tmp)
            from sajha.auth import AuthManager
            token = AuthManager.authenticate_local(db, 'admin', 'admin123')
            ctx = AuthManager.authenticate_jwt(db, token)
            assert ctx is not None
            assert ctx.authenticated is True
            assert ctx.user_id == 'admin'
            assert ctx.is_admin is True
            assert 'admin' in ctx.roles
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_apikey_auth(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup(tmp)
            from sajha.auth import AuthManager
            from sajha.db.dao import ApiKeyDAO
            from sajha.db.models import ApiKey

            raw = 'sja_testapikey12345'
            dao = ApiKeyDAO(db)
            key = ApiKey(key_hash=dao.hash_key(raw), key_prefix=raw[:8], name='TestKey')
            dao.create(key)

            ctx = AuthManager.authenticate_apikey(db, raw)
            assert ctx is not None
            assert ctx.authenticated is True
            assert ctx.auth_type == 'apikey'
            assert ctx.api_key_name == 'TestKey'
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_auth_context_tool_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup(tmp)
            from sajha.auth import AuthManager
            token = AuthManager.authenticate_local(db, 'admin', 'admin123')
            ctx = AuthManager.authenticate_jwt(db, token)
            assert ctx.has_tool_access('any_tool') is True
            assert ctx.has_permission('admin', 'users', 'delete') is True
            db.close()
            eng._engine = None; eng._SessionLocal = None

    def test_auth_context_legacy_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, eng = self._setup(tmp)
            from sajha.auth import AuthManager
            token = AuthManager.authenticate_local(db, 'admin', 'admin123')
            ctx = AuthManager.authenticate_jwt(db, token)
            legacy = ctx.to_legacy_session()
            assert legacy['user_id'] == 'admin'
            assert 'admin' in legacy['roles']
            db.close()
            eng._engine = None; eng._SessionLocal = None
