"""
SAJHA MCP Server — background work for the credential files.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* Applies ``config/users.json`` (sajha/auth/users_file.py) to the users table at start-up and
  whenever the file changes on disk.
* Every ``auth.api_keys.db_dump_interval_minutes`` (default 10) writes the database's API keys
  to ``config/apikeys_db.json`` (sajha/auth/persistent_keys.py ``write_dump``), from one worker
  per interval (a claim in the state store).
* Raises the standing System Notices for the credential settings: plain-text storage
  (``auth.credential_storage: plain``) and an active test admin key.

Owner guide: docs/security/Security Model.md ("Credential storage and files").
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def dump_interval_seconds() -> float:
    from sajha.core.config import _get
    try:
        return max(60.0, float(_get('auth.api_keys.db_dump_interval_minutes', 10)) * 60.0)
    except (TypeError, ValueError):
        return 600.0


def _session():
    from sajha.db.engine import get_db_session
    return get_db_session()


def sync_users_file() -> int:
    from sajha.auth.users_file import get_users_file, sync_to_database
    from sajha.notices import clear_notice, raise_notice
    db = _session()
    try:
        n, problems = sync_to_database(db, get_users_file())
    finally:
        db.close()
    if problems:
        raise_notice('auth.users_file', 'error', 'auth', 'Some users in config/users.json were not applied',
                     '; '.join(problems)[:900], link='/admin/users/file', ttl_minutes=0)
    else:
        clear_notice('auth.users_file')
    return n


def dump_keys() -> int:
    from sajha.auth.persistent_keys import write_dump
    from sajha.notices import clear_notice, raise_notice
    db = _session()
    try:
        n = write_dump(db)
    except Exception as e:
        raise_notice('auth.apikeys_dump', 'warning', 'auth', 'API keys dump failed',
                     f'config/apikeys_db.json was not written: {e}', ttl_minutes=0)
        raise
    finally:
        db.close()
    clear_notice('auth.apikeys_dump')
    return n


def standing_notices() -> None:
    """The notices that say how credentials are configured."""
    from sajha.auth.password import credential_storage
    from sajha.auth.persistent_keys import get_persistent_keys, record_usable
    from sajha.notices import clear_notice, raise_notice
    if credential_storage() == 'plain':
        raise_notice('auth.plain_credentials', 'warning', 'auth', 'Credentials are stored in plain text',
                     'auth.credential_storage is plain: passwords and API keys are stored as given (an intranet or '
                     'development setting). Set it to hashed and run "python -m sajha.auth rehash" to change.',
                     ttl_minutes=0)
    else:
        clear_notice('auth.plain_credentials')
    try:
        active = any(r.get('test_admin') and record_usable(r) for r in get_persistent_keys().records())
    except Exception:
        active = False
    if active:
        raise_notice('auth.test_admin_key', 'critical', 'auth', 'Test admin key is enabled',
                     'A test admin key in config/apikeys.json signs in as an administrator here and across SAJHA Net. '
                     'Disable it before production (sajhanet.test_admin_key.enabled: false).',
                     link='/admin/apikeys/file', audience='admin', ttl_minutes=0)
    else:
        clear_notice('auth.test_admin_key')


def _claim(slot: int) -> bool:
    try:
        from sajha.core.state import WORKER_ID, get_state_store
        return bool(get_state_store().add(f'auth:apikeys_dump:{slot}', WORKER_ID, ttl=dump_interval_seconds() * 2))
    except Exception:
        return True


def _loop() -> None:
    from sajha.auth.users_file import get_users_file
    iv = dump_interval_seconds()
    last_slot = None
    while not _stop.wait(2.0):
        try:
            if get_users_file().changed():
                logger.info('users file changed on disk; applying it')
                sync_users_file()
                standing_notices()
        except Exception as e:
            logger.warning(f'users file not applied: {e}')
        slot = int(time.time() // iv)
        if slot != last_slot:
            last_slot = slot
            if _claim(slot):
                try:
                    n = dump_keys()
                    logger.debug(f'API keys dump: {n} key(s) written to config/apikeys_db.json')
                except Exception as e:
                    logger.warning(f'API keys dump failed: {e}')


def start() -> None:
    """Start-up: apply the users file, raise the standing notices, start the watcher."""
    global _thread
    try:
        sync_users_file()
    except Exception as e:
        logger.warning(f'users file not applied at start-up: {e}')
    try:
        standing_notices()
    except Exception as e:
        logger.debug(f'credential notices: {e}')
    if _thread is None or not _thread.is_alive():
        _stop.clear()
        _thread = threading.Thread(target=_loop, name='sajha-credential-files', daemon=True)
        _thread.start()


def stop() -> None:
    _stop.set()
