"""
SAJHA MCP Server — server secrets (JWT signing key, session secret).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``auth.jwt.secret`` signs every SAJHA login JWT and ``auth.session.secret_key`` keys the
OAuth consent CSRF tokens and seeds the MRTR ``requestState`` key.  Earlier releases
shipped public placeholder values for both, so anyone could mint an admin JWT.

Resolution, per secret:

1. A value supplied through the environment or the config file is used as is, unless
   it is one of the placeholder strings that SAJHA (or its deployment recipes) ever
   shipped: then start-up stops with :class:`InsecureSecretError`.
2. Otherwise a 256-bit random value is generated once and persisted to
   ``auth.secrets_file`` (default ``<data.dir>/secrets/server_secrets.json``, mode 0600,
   git-ignored), so it is stable across restarts and shared by every worker process
   that sees the same data directory.

Secret values are never logged.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

#: Every placeholder secret that has appeared in SAJHA's config, code defaults, docs or
#: deployment recipes.  A deployment still using one of them is trivially forgeable.
KNOWN_SHIPPED_SECRETS = frozenset({
    'sajha-jwt-secret-change-in-production',
    'sajha-jwt-secret-change-me',
    'sajha-session-secret-change-in-production',
    'dev-secret-change-in-production',
    'change-me-in-production',
    'change-me-to-random-64-chars',
    'your-jwt-secret-here',
    'change-me',
    'changeme',
    'secret',
})

#: (Settings field, key in the secrets file, dotted config key, env vars that set it)
SECRET_SPECS = (
    ('jwt_secret', 'jwt_secret', 'auth.jwt.secret',
     'JWT_SECRET, SAJHA_JWT_SECRET or SAJHA_AUTH_JWT_SECRET'),
    ('secret_key', 'session_secret', 'auth.session.secret_key',
     'SESSION_SECRET, SAJHA_SECRET_KEY or SAJHA_AUTH_SESSION_SECRET_KEY'),
)

_lock = threading.Lock()


class InsecureSecretError(RuntimeError):
    """A secret is set to a publicly known placeholder value; the server must not start."""


def is_shipped_default(value: Optional[str]) -> bool:
    return (value or '').strip().lower() in KNOWN_SHIPPED_SECRETS


def check_not_shipped(config_key: str, value: Optional[str], how_to_set: str) -> None:
    if is_shipped_default(value):
        raise InsecureSecretError(
            f'{config_key} is set to a publicly known placeholder value, so anyone could forge '
            f'credentials signed with it. Set {how_to_set} to a long random value '
            f'(for example: python -c "import secrets; print(secrets.token_urlsafe(48))"), '
            f'or leave it empty and SAJHA generates one and stores it in the secrets file.')


def secrets_file_path() -> Path:
    from sajha.core.config import _get
    configured = (_get('auth.secrets_file', '') or '').strip()
    if configured:
        path = Path(configured)
    else:
        path = Path(_get('data.dir', './data') or './data') / 'secrets' / 'server_secrets.json'
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _read(path: Path) -> Dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise InsecureSecretError(f'Cannot read the secrets file {path}: {type(e).__name__}. '
                                  f'Fix or delete it (deleting it signs every user out).')
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str) and v} \
        if isinstance(data, dict) else {}


def _write(path: Path, data: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def persisted_secret(name: str, path: Optional[Path] = None) -> str:
    """The persisted secret ``name``, generated (and stored, mode 0600) on first use."""
    path = path or secrets_file_path()
    with _lock:
        data = _read(path)
        value = data.get(name)
        if value and not is_shipped_default(value):
            return value
        data[name] = secrets.token_urlsafe(48)
        _write(path, data)
        # Another worker may have written at the same moment: the file wins.
        value = _read(path).get(name) or data[name]
        logger.info(f'Generated server secret "{name}" in {path} (mode 0600)')
        return value


def resolve_settings_secrets(settings) -> None:
    """Fill empty secrets from the secrets file; refuse publicly known placeholder values."""
    for field, file_key, config_key, how in SECRET_SPECS:
        value = (getattr(settings, field, '') or '').strip()
        if value:
            check_not_shipped(config_key, value, how)
            if len(value) < 32:
                logger.warning(f'{config_key} is shorter than 32 characters; use a long random value')
            continue
        setattr(settings, field, persisted_secret(file_key))
    from sajha.core.config import _get
    check_not_shipped('mcp.mrtr.state_secret', _get('mcp.mrtr.state_secret', ''),
                      'SAJHA_MCP_MRTR_STATE_SECRET')
