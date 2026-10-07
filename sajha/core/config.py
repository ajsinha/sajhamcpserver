"""
SAJHA MCP Server — Configuration (YAML)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Single config source: config/application.yml

Resolution priority (highest wins):
  1. Environment variables (SAJHA_ prefix)
  2. ${VAR:default} substitution in YAML values
  3. YAML file values
  4. Built-in defaults
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional
from functools import lru_cache

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

logger = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r'\$\{([^}:]+)(?::([^}]*))?\}')
_CONFIG_FILE = os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml')


def _substitute_vars(value: str) -> str:
    """Replace ${VAR:default} with environment variable or default."""
    def _replace(m):
        return os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else '')
    return _VAR_PATTERN.sub(_replace, value)


def _flatten(data: dict, prefix: str = '') -> dict:
    """
    Flatten nested YAML dict to dot-notation keys.

    Rules:
      - Nested dicts are recursed: {a: {b: 1}} → {'a.b': '1'}
      - None values are EXCLUDED (key not in dict → default kicks in)
      - Empty string '' IS a valid value (key defined, value intentionally empty)
      - All non-None values are stringified and ${VAR:default} substituted
    """
    flat: dict[str, str] = {}
    for key, value in data.items():
        full_key = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, full_key))
        elif value is not None:
            flat[full_key] = _substitute_vars(str(value))
        # value is None → key is NOT added to flat dict → default kicks in
    return flat


def load_yaml_config(filepath: str = _CONFIG_FILE) -> dict[str, str]:
    """Load and flatten a YAML config file. Returns empty dict if file missing."""
    path = Path(filepath)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        logger.warning(f'Config file not found: {path}')
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return _flatten(data)


def _load_dotenv(filepath: str = '.env') -> None:
    """Load .env file into os.environ (won't override existing vars)."""
    path = Path(filepath)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


# ── Load at import time ──────────────────────────────────────────
_load_dotenv()
_CFG = load_yaml_config()


def _get(key: str, default: str = '') -> str:
    """
    Get config value. Resolution order: SAJHA_ env var → YAML → default.

    Default kicks in if and only if the key is NOT defined anywhere.
    An empty string IS a valid value (key defined, intentionally empty).

    Examples:
      YAML has 'db.port: 5432'     → _get('db.port', '3306')    → '5432'
      YAML has 'db.port: '         → _get('db.port', '3306')    → ''  (intentionally empty)
      YAML has no 'db.port'        → _get('db.port', '3306')    → '3306'  (default)
      ENV has SAJHA_DB_PORT=9999   → _get('db.port', '3306')    → '9999'  (env wins)
    """
    # 1. Environment variable (highest priority)
    env_key = 'SAJHA_' + key.replace('.', '_').upper()
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val

    # 2. YAML config (key must exist — None values are excluded by _flatten)
    if key in _CFG:
        return _CFG[key]

    # 3. Default (key not defined anywhere)
    return default


def resolve_placeholders(text: str) -> str:
    """
    Resolve ``${key}`` and ``${key:default}`` in ``text`` the way tool configs are resolved:
    the environment variable named ``key`` → ``SAJHA_<KEY>`` → YAML → the inline default.
    A reference with no value and no default is left as written.

    For values that may reach a tool without passing through the tools registry (a config
    read straight from disk): a path such as ``${data.duckdb.dir:./data/duckdb}`` must never
    be used literally, or a directory of that name appears in the working directory.
    """
    if not isinstance(text, str) or '${' not in text:
        return text

    def _replace(m):
        key, default = m.group(1), m.group(2)
        value = os.environ.get(key)
        if value is None:
            value = _get(key, None)
        if value is None:
            value = default
        return m.group(0) if value is None else str(value)
    return _VAR_PATTERN.sub(_replace, text)


def _bool(key: str, default: bool = False) -> bool:
    val = _get(key, str(default))
    return parse_bool(val, default) if val else default


def _int(key: str, default: int = 0) -> int:
    val = _get(key, str(default))
    try:
        return int(val) if val != '' else default
    except (ValueError, TypeError):
        return default


def parse_bool(value, default: bool = False) -> bool:
    """A config value as a bool: true/1/yes/on are True, false/0/no/off/'' are False."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ('true', '1', 'yes', 'on'):
        return True
    if text in ('false', '0', 'no', 'off', 'none', ''):
        return False
    return default


def cfg_bool(cfg: dict, key: str, default: bool = False) -> bool:
    """A bool from a flattened config dict (the raw YAML ``_CFG``), where every value is a string."""
    return parse_bool(cfg.get(key), default) if key in cfg else default


def parse_list(raw) -> list[str]:
    """A list value: a YAML list (flattened to its repr), a JSON list or a comma-separated string."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    raw = str(raw).strip()
    if not raw:
        return []
    if raw.startswith('['):
        import ast
        try:
            return [str(x).strip() for x in ast.literal_eval(raw) if str(x).strip()]
        except (ValueError, SyntaxError):
            raw = raw.strip('[]')
    return [x.strip().strip('\'"') for x in raw.split(',') if x.strip().strip('\'"')]


def _list(key: str, default: Optional[list] = None) -> list[str]:
    """Live list lookup (SAJHA_ env, comma-separated or JSON → YAML list → default)."""
    raw = _get(key, None)
    if raw is None:
        return list(default or [])
    return parse_list(raw)


# ── Settings Model ───────────────────────────────────────────────

class Settings(BaseSettings):
    """Central configuration. All values: env → YAML → default."""

    # Application
    app_name: str = Field(default_factory=lambda: _get('app.name', 'SAJHA MCP Server'))
    app_version: str = Field(default_factory=lambda: _get('app.version', '7.0.0'))
    app_description: str = Field(default_factory=lambda: _get('app.description', 'Model Context Protocol Server'))
    app_author: str = Field(default_factory=lambda: _get('app.author', 'Ashutosh Sinha'))
    app_email: str = Field(default_factory=lambda: _get('app.email', 'ajsinha@gmail.com'))
    app_copyright_years: str = Field(default_factory=lambda: _get('app.copyright_years', '2025-2030'))
    app_github_repo: str = Field(default_factory=lambda: _get('app.github.repo', 'https://github.com/ajsinha/sajhamcpserver'))
    app_github_repo_name: str = Field(default_factory=lambda: _get('app.github.repo_name', 'ajsinha/sajhamcpserver'))

    # Server
    server_host: str = Field(default_factory=lambda: _get('server.host', '0.0.0.0'))
    server_port: int = Field(default_factory=lambda: _int('server.port', 3002))
    server_debug: bool = Field(default_factory=lambda: _bool('server.debug', False))
    # Empty -> generated once and persisted in the secrets file (sajha/core/server_secrets.py)
    secret_key: str = Field(default_factory=lambda: _get('auth.session.secret_key', ''))

    # Database
    db_type: str = Field(default_factory=lambda: _get('db.type', 'sqlite'))
    db_url: Optional[str] = Field(default_factory=lambda: _get('db.url', '') or None)
    db_path: str = Field(default_factory=lambda: _get('db.path', 'data/sajha.db'))
    db_host: str = Field(default_factory=lambda: _get('db.host', 'localhost'))
    db_port: int = Field(default_factory=lambda: _int('db.port', 5432))
    db_name: str = Field(default_factory=lambda: _get('db.name', 'sajha_mcp'))
    db_user: str = Field(default_factory=lambda: _get('db.user', 'sajha'))
    db_password: str = Field(default_factory=lambda: _get('db.password', 'sajha'))
    db_driver: str = Field(default_factory=lambda: _get('db.driver', 'psycopg2'))
    db_pool_size: int = Field(default_factory=lambda: _int('db.pool.size', 10))
    db_echo: bool = Field(default_factory=lambda: _bool('db.echo', False))
    db_scripts_dir: str = Field(default_factory=lambda: _get('db.scripts_dir', 'db/scripts'))
    db_schema_check: str = Field(default_factory=lambda: _get('db.schema_check', 'strict'))

    # JWT
    jwt_secret: str = Field(default_factory=lambda: _get('auth.jwt.secret', ''))
    jwt_algorithm: str = Field(default_factory=lambda: _get('auth.jwt.algorithm', 'HS256'))
    jwt_expiry_minutes: int = Field(default_factory=lambda: _int('auth.jwt.expiry_minutes', 60))

    # Config paths
    config_tools_dir: str = Field(default_factory=lambda: _get('config.tools.dir', 'config/tools'))
    config_prompts_dir: str = Field(default_factory=lambda: _get('config.prompts.dir', 'config/prompts'))
    config_users_path: str = Field(default_factory=lambda: _get('config.users.path', 'config/users.json'))
    config_apikeys_path: str = Field(default_factory=lambda: _get('config.apikeys.path', 'config/apikeys.json'))
    config_ir_dir: str = Field(default_factory=lambda: _get('config.ir.dir', 'config/ir'))

    # Hot reload
    hot_reload_interval: int = Field(default_factory=lambda: _int('hot_reload.interval_seconds', 300))
    hot_reload_enabled: bool = Field(default_factory=lambda: _bool('hot_reload.enabled', True))

    # Features
    features_websocket: bool = Field(default_factory=lambda: _bool('features.websocket.enabled', True))
    features_monitoring: bool = Field(default_factory=lambda: _bool('features.monitoring.enabled', True))
    features_admin_panel: bool = Field(default_factory=lambda: _bool('features.admin.panel.enabled', True))

    # Logging
    logging_level: str = Field(default_factory=lambda: _get('logging.level', 'INFO'))

    # Data directories
    data_duckdb_dir: str = Field(default_factory=lambda: _get('data.duckdb.dir', './data/duckdb'))
    data_sqlselect_dir: str = Field(default_factory=lambda: _get('data.sqlselect.dir', './data/sqlselect'))
    data_dir: str = Field(default_factory=lambda: _get('data.dir', './data'))

    # Cache settings
    cache_enabled: bool = Field(default_factory=lambda: _bool('cache.enabled', True))
    cache_dir: str = Field(default_factory=lambda: _get('cache.dir', 'data/cache'))
    cache_max_files: int = Field(default_factory=lambda: _int('cache.max_files', 50000))
    cache_max_file_size_kb: int = Field(default_factory=lambda: _int('cache.max_file_size_kb', 512))
    cache_cleanup_interval: int = Field(default_factory=lambda: _int('cache.cleanup_interval_seconds', 300))
    config_plugins_dir: str = Field(default_factory=lambda: _get('config.plugins.dir', 'config/plugins'))
    log_level: str = Field(default_factory=lambda: _get('logging.level', 'INFO'))
    log_dir: str = Field(default_factory=lambda: _get('logging.dir', './logs'))
    log_file: str = Field(default_factory=lambda: _get('logging.file', ''))

    # External API keys
    google_api_key: str = Field(default_factory=lambda: _get('google.api.key', ''))
    google_search_engine_id: str = Field(default_factory=lambda: _get('google.search.engine.id', ''))
    fred_api_key: str = Field(default_factory=lambda: _get('fred.api.key', ''))
    tavily_api_key: str = Field(default_factory=lambda: _get('tavily.api.key', ''))
    alpha_vantage_api_key: str = Field(default_factory=lambda: _get('alpha_vantage.api.key', ''))

    # Async execution settings
    async_enabled: bool = Field(default_factory=lambda: _bool('async.enabled', True))
    async_workers: int = Field(default_factory=lambda: _int('async.workers', 8))
    async_queue_size: int = Field(default_factory=lambda: _int('async.queue_size', 1000))
    async_task_ttl_hours: int = Field(default_factory=lambda: _int('async.task_ttl_hours', 24))
    async_webhook_timeout: int = Field(default_factory=lambda: _int('async.delivery.webhook.timeout', 10))
    async_webhook_max_retries: int = Field(default_factory=lambda: _int('async.delivery.webhook.max_retries', 3))
    async_webhook_allow_private_networks: bool = Field(
        default_factory=lambda: _bool('async.delivery.webhook.allow_private_networks', False))
    async_kafka_bootstrap_servers: str = Field(
        default_factory=lambda: _get('async.delivery.kafka.bootstrap_servers', 'localhost:9092'))
    async_file_base_dir: str = Field(default_factory=lambda: _get('async.delivery.file.base_dir', 'data/async_results'))
    async_file_max_size_mb: int = Field(default_factory=lambda: _int('async.delivery.file.max_size_mb', 50))

    # Shell execution settings
    shell_enabled: bool = Field(default_factory=lambda: _bool('shell.enabled', False))
    shell_mode: str = Field(default_factory=lambda: _get('shell.mode', 'sandbox'))
    shell_scratch_dir: str = Field(default_factory=lambda: _get('shell.scratch_dir', 'data/shell_scratch'))
    shell_python_enabled: bool = Field(default_factory=lambda: _bool('shell.python.enabled', True))
    shell_python_timeout: int = Field(default_factory=lambda: _int('shell.python.timeout_seconds', 30))
    shell_python_memory_mb: int = Field(default_factory=lambda: _int('shell.python.memory_limit_mb', 256))
    shell_bash_enabled: bool = Field(default_factory=lambda: _bool('shell.bash.enabled', False))
    shell_bash_timeout: int = Field(default_factory=lambda: _int('shell.bash.timeout_seconds', 15))
    shell_bash_max_output_bytes: int = Field(default_factory=lambda: _int('shell.bash.max_output_bytes', 1048576))

    # Config source (for startup banner)
    config_source: str = Field(default_factory=lambda: _CONFIG_FILE if _CFG else 'defaults')
    @property
    def database_url(self) -> str:
        if self.db_url:
            return self.db_url
        if self.db_type == 'postgresql':
            from urllib.parse import quote_plus
            pw = quote_plus(self.db_password)
            drv = self.db_driver or 'psycopg2'
            return f'postgresql+{drv}://{self.db_user}:{pw}@{self.db_host}:{self.db_port}/{self.db_name}'
        db_path = Path(self.db_path)
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f'sqlite:///{db_path}'

    # extra='ignore': a .env name that is not a Settings field (FMP_API_KEY=...,
    # SAJHA_MCP_AUTH_MODE=...) must not stop start-up; _warn_unknown_dotenv_names()
    # reports SAJHA_* names that nothing reads.
    model_config = SettingsConfigDict(env_file='.env', env_prefix='SAJHA_', case_sensitive=False,
                                      extra='ignore')


#: SAJHA_* environment names read directly (not Settings fields, not dotted config keys)
_KNOWN_ENV_ONLY = frozenset({
    'SAJHA_CONFIG_FILE', 'SAJHA_CORS_ORIGINS', 'SAJHA_TEST_PASSWORD', 'SAJHA_STORAGE_BACKEND',
    'SAJHA_BASE_DIR', 'SAJHA_S3_BUCKET', 'SAJHA_S3_PREFIX', 'SAJHA_S3_CACHE_DIR',
    'SAJHA_S3_ENDPOINT_URL', 'SAJHA_AZURE_CONTAINER', 'SAJHA_AZURE_ACCOUNT_URL', 'SAJHA_AZURE_PREFIX',
    'SAJHA_AZURE_CACHE_DIR', 'SAJHA_GCS_BUCKET', 'SAJHA_GCS_PREFIX', 'SAJHA_GCS_CACHE_DIR',
    'SAJHA_RELOAD_INTERVAL', 'SAJHA_MCP_AUTH_BUILTIN_CLIENTS',
    # observability secrets and the alert-rule list (sajha/observability/settings.py)
    'SAJHA_OBSERVABILITY_METRICS_TOKEN', 'SAJHA_OBSERVABILITY_ALERTS_EMAIL_PASSWORD', 'SAJHA_OBSERVABILITY_ALERTS',
    # the SIEM sink list (sajha/audit/sinks.py)
    'SAJHA_AUDIT_EXPORT_SINKS',
})


def _dotenv_names(filepath: str = '.env') -> list[str]:
    path = Path(filepath)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return []
    names = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                names.append(line.partition('=')[0].strip().removeprefix('export ').strip())
    return names


def unknown_sajha_env_names(names) -> list[str]:
    """SAJHA_* names that match no Settings field, no config key and no known env-only name."""
    known = {('SAJHA_' + f).upper() for f in Settings.model_fields}
    known |= {'SAJHA_' + k.replace('.', '_').upper() for k in _CFG}
    known |= _KNOWN_ENV_ONLY
    out = []
    for name in names:
        upper = name.upper()
        if not upper.startswith('SAJHA_') or upper in known:
            continue
        # a dotted key the code reads with a default but the YAML leaves out (SAJHA_MCP_APPS_DIR, ...)
        # SAJHA_ACCOUNTS_PROVIDERS[_<ID>_<FIELD>]: connected-account providers (sajha/accounts/providers.py)
        if upper.startswith(('SAJHA_MCP_', 'SAJHA_AUTH_', 'SAJHA_STORAGE_', 'SAJHA_ASYNC_', 'SAJHA_SHELL_',
                             'SAJHA_ACCOUNTS_')):
            continue
        out.append(name)
    return out


def _warn_unknown_dotenv_names() -> None:
    try:
        unknown = unknown_sajha_env_names(_dotenv_names())
    except OSError:
        return
    for name in unknown:
        logger.warning(f'.env: {name} is not a SAJHA setting; ignored')


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    # Secrets: refuse shipped placeholders; generate + persist missing ones (never logged)
    from sajha.core.server_secrets import resolve_settings_secrets
    resolve_settings_secrets(settings)
    return settings


_warn_unknown_dotenv_names()

