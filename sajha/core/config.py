"""
SAJHA MCP Server v3 — Configuration (YAML)
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
from pydantic_settings import BaseSettings
from pydantic import Field

logger = logging.getLogger(__name__)

_VAR_PATTERN = re.compile(r'\$\{([^}:]+)(?::([^}]*))?\}')
_CONFIG_FILE = 'config/application.yml'


def _substitute_vars(value: str) -> str:
    """Replace ${VAR:default} with environment variable or default."""
    def _replace(m):
        return os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else '')
    return _VAR_PATTERN.sub(_replace, value)


def _flatten(data: dict, prefix: str = '') -> dict[str, str]:
    """Flatten nested dict to dot-notation keys with env var substitution."""
    flat: dict[str, str] = {}
    for key, value in data.items():
        full_key = f'{prefix}.{key}' if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, full_key))
        else:
            s = str(value) if value is not None else ''
            flat[full_key] = _substitute_vars(s)
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
    """Get config value: SAJHA_ env var → YAML → default."""
    env_key = 'SAJHA_' + key.replace('.', '_').upper()
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val
    return _CFG.get(key, default)


def _bool(key: str, default: bool = False) -> bool:
    return _get(key, str(default)).lower() in ('true', '1', 'yes')


def _int(key: str, default: int = 0) -> int:
    try:
        return int(_get(key, str(default)))
    except (ValueError, TypeError):
        return default


# ── Settings Model ───────────────────────────────────────────────

class Settings(BaseSettings):
    """Central configuration. All values: env → YAML → default."""

    # Application
    app_name: str = Field(default_factory=lambda: _get('app.name', 'SAJHA MCP Server'))
    app_version: str = Field(default_factory=lambda: _get('app.version', '4.5.0'))
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
    secret_key: str = Field(default_factory=lambda: _get('auth.session.secret_key', os.urandom(24).hex()))

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

    # JWT
    jwt_secret: str = Field(default_factory=lambda: _get('auth.jwt.secret', 'sajha-jwt-secret-change-me'))
    jwt_algorithm: str = Field(default_factory=lambda: _get('auth.jwt.algorithm', 'HS256'))
    jwt_expiry_minutes: int = Field(default_factory=lambda: _int('auth.jwt.expiry_minutes', 60))

    # OAuth
    oauth_mode: str = Field(default_factory=lambda: _get('oauth.mode', 'none'))
    oauth_provider: str = Field(default_factory=lambda: _get('oauth.provider', ''))
    oauth_azure_tenant_id: str = Field(default_factory=lambda: _get('oauth.azure.tenant_id', ''))
    oauth_azure_client_id: str = Field(default_factory=lambda: _get('oauth.azure.client_id', ''))
    oauth_azure_client_secret: str = Field(default_factory=lambda: _get('oauth.azure.client_secret', ''))

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
    config_plugins_dir: str = Field(default_factory=lambda: _get('config.plugins.dir', 'config/plugins'))
    log_level: str = Field(default_factory=lambda: _get('logging.level', 'INFO'))
    log_dir: str = Field(default_factory=lambda: _get('logging.dir', './logs'))
    log_file: str = Field(default_factory=lambda: _get('logging.file', ''))

    # External API keys
    google_api_key: str = Field(default_factory=lambda: _get('google.api.key', ''))
    google_search_engine_id: str = Field(default_factory=lambda: _get('google.search.engine.id', ''))
    fred_api_key: str = Field(default_factory=lambda: _get('fred.api.key', ''))
    tavily_api_key: str = Field(default_factory=lambda: _get('tavily.api.key', ''))

    # Config source (for startup banner)
    config_source: str = Field(default_factory=lambda: 'application.yml' if _CFG else 'defaults')
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

    class Config:
        env_file = '.env'
        env_prefix = 'SAJHA_'
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
