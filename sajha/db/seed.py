"""
SAJHA MCP Server v3 — Legacy Data Import
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Imports users and API keys from legacy JSON config files (v2 format)
into the database. Safe to run every startup — skips existing records.

Schema creation and default seed data (roles, permissions, admin user)
are handled by SQL scripts in db/scripts/.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from sajha.db.models import User, Role, ApiKey
from sajha.db.dao import UserDAO, RoleDAO, ApiKeyDAO
from sajha.auth.password import hash_password

logger = logging.getLogger(__name__)


def import_legacy_users(db: Session, json_path: str) -> int:
    """
    Import users from legacy users.json (v2 format).
    Hashes plain-text passwords with bcrypt.
    Skips users that already exist (by user_id).
    """
    path = Path(json_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        logger.info(f'  No legacy users file at {path}, skipping')
        return 0

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    user_dao = UserDAO(db)
    role_dao = RoleDAO(db)
    count = 0

    for u in data.get('users', []):
        uid = u.get('user_id')
        if not uid or uid == 'admin':  # admin is created by 002_seed.sql
            continue
        if user_dao.user_exists(uid):
            continue

        user = User(
            user_id=uid,
            user_name=u.get('user_name', uid),
            email=u.get('email', ''),
            password_hash=hash_password(u.get('password', 'changeme')),
            enabled=u.get('enabled', True),
        )

        # Map roles
        for role_name in u.get('roles', ['user']):
            role = role_dao.get_by_name(role_name)
            if role:
                user.roles.append(role)

        db.add(user)
        count += 1
        logger.info(f'  Imported user: {uid}')

    if count > 0:
        db.commit()
    return count


def import_legacy_apikeys(db: Session, json_path: str) -> int:
    """Import API keys from legacy apikeys.json (v2 format)."""
    path = Path(json_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        logger.info(f'  No legacy API keys file at {path}, skipping')
        return 0

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    apikey_dao = ApiKeyDAO(db)
    count = 0

    for key_data in data.get('apikeys', []):
        raw_key = key_data.get('key', '')
        if not raw_key:
            continue

        key_hash = apikey_dao.hash_key(raw_key)
        if apikey_dao.get_by_key_hash(key_hash):
            continue

        api_key = ApiKey(
            key_hash=key_hash,
            key_prefix=raw_key[:8] if len(raw_key) >= 8 else raw_key,
            name=key_data.get('name', 'Imported Key'),
            description=key_data.get('description', 'Imported from legacy apikeys.json'),
            enabled=key_data.get('enabled', True),
            tool_access_mode=key_data.get('tool_access', {}).get('mode', 'all'),
            tool_access_list=json.dumps(
                key_data.get('tool_access', {}).get('allowlist', []) or
                key_data.get('tool_access', {}).get('denylist', [])
            ),
        )
        db.add(api_key)
        count += 1
        logger.info(f'  Imported API key: {api_key.key_prefix}... ({api_key.name})')

    if count > 0:
        db.commit()
    return count


def run_legacy_import(db: Session, settings) -> dict:
    """
    Import legacy data from JSON config files.
    Called after SQL scripts have created schema and seed data.
    """
    logger.info('Importing legacy data from JSON configs...')

    users = import_legacy_users(db, settings.config_users_path)
    keys = import_legacy_apikeys(db, settings.config_apikeys_path)

    if users > 0 or keys > 0:
        logger.info(f'  Legacy import: {users} users, {keys} API keys')
    else:
        logger.info('  No legacy data to import')

    return {'users_imported': users, 'apikeys_imported': keys}
