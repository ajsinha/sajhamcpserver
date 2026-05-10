"""
Tests for sajha.core.config — YAML config loader.
"""

import os
import sys
import pytest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))


class TestYamlFlattening:
    """Test the YAML → flat dict conversion."""

    def test_flat_keys(self):
        from sajha.core.config import _flatten
        data = {'server': {'host': 'localhost', 'port': 3002}}
        flat = _flatten(data)
        assert flat['server.host'] == 'localhost'
        assert flat['server.port'] == '3002'

    def test_deeply_nested(self):
        from sajha.core.config import _flatten
        data = {'a': {'b': {'c': {'d': 'deep'}}}}
        flat = _flatten(data)
        assert flat['a.b.c.d'] == 'deep'

    def test_mixed_types(self):
        from sajha.core.config import _flatten
        data = {'x': {'flag': True, 'count': 42, 'name': 'test', 'empty': None}}
        flat = _flatten(data)
        assert flat['x.flag'] == 'True'
        assert flat['x.count'] == '42'
        assert flat['x.name'] == 'test'
        assert flat['x.empty'] == ''

    def test_empty_dict(self):
        from sajha.core.config import _flatten
        assert _flatten({}) == {}

    def test_top_level_keys(self):
        from sajha.core.config import _flatten
        data = {'simple': 'value'}
        flat = _flatten(data)
        assert flat['simple'] == 'value'


class TestEnvSubstitution:
    """Test ${VAR:default} substitution."""

    def test_default_when_no_env(self):
        from sajha.core.config import _substitute_vars
        assert _substitute_vars('${MISSING_VAR:fallback}') == 'fallback'

    def test_env_overrides_default(self):
        from sajha.core.config import _substitute_vars
        os.environ['TEST_SUB_VAR'] = 'from_env'
        try:
            assert _substitute_vars('${TEST_SUB_VAR:fallback}') == 'from_env'
        finally:
            del os.environ['TEST_SUB_VAR']

    def test_no_default(self):
        from sajha.core.config import _substitute_vars
        assert _substitute_vars('${NONEXISTENT_VAR}') == ''

    def test_multiple_substitutions(self):
        from sajha.core.config import _substitute_vars
        os.environ['A1'] = 'hello'
        try:
            result = _substitute_vars('${A1:x}-${MISSING:world}')
            assert result == 'hello-world'
        finally:
            del os.environ['A1']

    def test_no_substitution_needed(self):
        from sajha.core.config import _substitute_vars
        assert _substitute_vars('plain text') == 'plain text'


class TestYamlFileLoading:
    """Test loading actual YAML files."""

    def test_load_missing_file(self):
        from sajha.core.config import load_yaml_config
        result = load_yaml_config('/nonexistent/path.yml')
        assert result == {}

    def test_load_real_config(self):
        from sajha.core.config import load_yaml_config
        cfg = load_yaml_config('config/application.yml')
        assert len(cfg) > 0
        assert 'app.name' in cfg
        assert cfg['app.name'] == 'SAJHA MCP Server'

    def test_load_custom_yaml(self):
        from sajha.core.config import load_yaml_config
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write('test:\n  key: value123\n  nested:\n    deep: found\n')
            f.flush()
            cfg = load_yaml_config(f.name)
        os.unlink(f.name)
        assert cfg['test.key'] == 'value123'
        assert cfg['test.nested.deep'] == 'found'


class TestConfigGet:
    """Test the _get function with SAJHA_ prefix override."""

    def test_yaml_value(self):
        from sajha.core.config import _get
        assert _get('app.name', 'default') == 'SAJHA MCP Server'

    def test_default_fallback(self):
        from sajha.core.config import _get
        assert _get('nonexistent.key', 'mydefault') == 'mydefault'

    def test_sajha_env_override(self):
        from sajha.core.config import _get
        os.environ['SAJHA_APP_NAME'] = 'Override Name'
        try:
            assert _get('app.name', 'default') == 'Override Name'
        finally:
            del os.environ['SAJHA_APP_NAME']

    def test_bool_parsing(self):
        from sajha.core.config import _bool
        assert _bool('hot_reload.enabled') is True
        assert _bool('nonexistent', False) is False

    def test_int_parsing(self):
        from sajha.core.config import _int
        assert _int('server.port', 9999) == 3002
        assert _int('nonexistent', 8080) == 8080
        assert _int('app.name', 0) == 0  # non-numeric string → default


class TestSettingsModel:
    """Test the Pydantic Settings model."""

    def test_settings_creation(self):
        from sajha.core.config import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.app_name == 'SAJHA MCP Server'
        assert s.server_port == 3002
        assert s.db_type == 'sqlite'

    def test_database_url_sqlite(self):
        from sajha.core.config import get_settings
        get_settings.cache_clear()
        s = get_settings()
        assert s.database_url.startswith('sqlite:///')

    def test_database_url_postgresql(self):
        from sajha.core.config import get_settings
        os.environ['SAJHA_DB_TYPE'] = 'postgresql'
        os.environ['SAJHA_DB_HOST'] = 'myhost'
        os.environ['SAJHA_DB_PASSWORD'] = 'p@ss!'
        get_settings.cache_clear()
        try:
            s = get_settings()
            url = s.database_url
            assert url.startswith('postgresql+psycopg2://')
            assert 'myhost' in url
            assert 'p%40ss' in url  # URL-encoded
        finally:
            del os.environ['SAJHA_DB_TYPE']
            del os.environ['SAJHA_DB_HOST']
            del os.environ['SAJHA_DB_PASSWORD']
            get_settings.cache_clear()

    def test_database_url_explicit(self):
        from sajha.core.config import get_settings
        os.environ['SAJHA_DB_URL'] = 'postgresql://user:pass@host/db'
        get_settings.cache_clear()
        try:
            s = get_settings()
            assert s.database_url == 'postgresql://user:pass@host/db'
        finally:
            del os.environ['SAJHA_DB_URL']
            get_settings.cache_clear()
