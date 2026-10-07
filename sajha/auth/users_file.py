"""
SAJHA MCP Server — the administrators' users file (``config/users.json``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Administrators may define users by hand in a JSON file (default ``config/users.json``,
``auth.users_file.path``). The file always wins: at start-up and whenever it changes on disk,
each user in it is written to the users table (created if missing; user name, email,
password, roles and enabled flag overwritten), so every sign-in path (form, JWT, OAuth, API
keys, SAJHA Net) sees the file's values. Users the file defines are marked as managed by it
(``users.managed_by``) and are edited only through the file (Admin > Users > Users file);
the database copy is overwritten on the next sync.

Format::

    {"format": "sajha-users/1",
     "users": [{"user_id": "alice", "user_name": "Alice", "email": "a@example.com",
                "password": "…", "roles": ["user"], "enabled": true}]}

The file is standalone: SAJHA never writes database users into it. It ships with a test
administrator account (``"test_admin": true``), applied as enabled only while
``sajhanet.test_admin_key.enabled`` is on. ``password`` is stored as written under ``auth.credential_storage: plain`` (a bcrypt value is
also accepted). Roles must exist; a user naming an unknown role is skipped with an error.
Removing a user from the file does not delete it from the database: it simply stops being
managed (disable or delete it in the console). The file is written atomically with owner-only
permissions and is git-ignored. Owner guide: docs/security/Security Model.md ("Users file").
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FORMAT = 'sajha-users/1'
NOTE = ('SAJHA users file, maintained by administrators (Admin > Users > Users file). Users here win over the '
        'database: they are written to it at start-up and whenever this file changes. Keep it private: '
        'git-ignored, owner-only. docs/security/Security Model.md')
FIELDS = ('user_id', 'user_name', 'email', 'password', 'roles', 'enabled', 'test_admin')


def configured_path() -> Path:
    from sajha.core.config import _get
    p = Path(str(_get('auth.users_file.path', 'config/users.json') or 'config/users.json'))
    return p if p.is_absolute() else Path.cwd() / p


def problem(rec: Dict[str, Any], known_roles: Optional[set] = None) -> Optional[str]:
    """Why a record is unusable, or None."""
    uid = rec.get('user_id')
    if not isinstance(uid, str) or not uid.strip():
        return 'user_id is required'
    if len(uid) > 100:
        return 'user_id is longer than 100 characters'
    if not isinstance(rec.get('password'), str) or not rec.get('password'):
        return f'{uid}: a password is required'
    roles = rec.get('roles') or []
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        return f'{uid}: roles must be a list of role names'
    if known_roles is not None:
        unknown = [r for r in roles if r not in known_roles]
        if unknown:
            return f'{uid}: unknown role(s) {", ".join(unknown)}'
    return None


class UsersFile:
    """The records in the file; re-read when it changes; atomic, owner-only writes."""

    @property
    def CHECK_EVERY(self) -> float:      # noqa: N802
        from sajha.auth.persistent_keys import reload_check_seconds
        return reload_check_seconds()

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._users: List[Dict[str, Any]] = []
        self._sig: Optional[tuple] = None
        self._checked = 0.0
        self.reload()

    def _signature(self) -> Optional[tuple]:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def reload(self) -> int:
        with self._lock:
            sig = self._signature()
            users: List[Dict[str, Any]] = []
            if sig is not None:
                try:
                    data = json.loads(self.path.read_text(encoding='utf-8') or '{}')
                except (OSError, ValueError) as e:
                    logger.error(f'users file: cannot read {self.path}: {e}; keeping the last good copy')
                    self._sig, self._checked = sig, time.time()
                    return len(self._users)
                if isinstance(data, dict):
                    users = [u for u in (data.get('users') or []) if isinstance(u, dict)]
            self._users, self._sig, self._checked = users, sig, time.time()
            return len(users)

    def changed(self) -> bool:
        """True (and re-read) when the file changed on disk since the last read."""
        with self._lock:
            now = time.time()
            if now - self._checked < self.CHECK_EVERY:
                return False
            self._checked = now
            if self._signature() != self._sig:
                self.reload()
                return True
            return False

    def users(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(u) for u in self._users]

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        return next((u for u in self.users() if u.get('user_id') == user_id), None)

    def write(self, users: List[Dict[str, Any]]) -> None:
        doc = {'format': FORMAT, 'note': NOTE,
               'users': [{k: u[k] for k in FIELDS if k in u} for u in users]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.users-', suffix='.json', dir=str(self.path.parent))
        try:
            if os.name == 'posix':
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.reload()

    def upsert(self, rec: Dict[str, Any]) -> None:
        with self._lock:
            rest = [u for u in self._users if u.get('user_id') != rec.get('user_id')]
            self.write(rest + [rec])

    def remove(self, user_id: str) -> bool:
        with self._lock:
            rest = [u for u in self._users if u.get('user_id') != user_id]
            if len(rest) == len(self._users):
                return False
            self.write(rest)
            return True


def sync_to_database(db, store: Optional['UsersFile'] = None) -> Tuple[int, List[str]]:
    """Write every usable user in the file to the users table. Returns (synced, problems)."""
    from sajha.db.models import Role, User
    store = store or get_users_file()
    roles = {r.name: r for r in db.query(Role).all()}
    synced, problems = 0, []
    from sajha.auth.persistent_keys import test_admin_enabled
    test_on = test_admin_enabled()
    for rec in store.users():
        why = problem(rec, set(roles))
        if why:
            problems.append(why)
            logger.error(f'users file: {why}; this user is not applied')
            continue
        user = db.query(User).filter(User.user_id == rec['user_id']).first()
        if user is None:
            user = User(user_id=rec['user_id'], user_name=rec.get('user_name') or rec['user_id'])
            db.add(user)
        user.user_name = rec.get('user_name') or rec['user_id']
        if 'email' in rec:
            user.email = rec.get('email') or None
        if user.password_hash != rec['password']:
            user.password_hash = rec['password']
        # a test admin account (``"test_admin": true``) counts only while sajhanet.test_admin_key.enabled
        user.enabled = bool(rec.get('enabled', True)) and (test_on or not rec.get('test_admin'))
        user.must_change_password = False
        user.roles = [roles[r] for r in rec.get('roles') or []]
        if hasattr(user, 'managed_by'):
            user.managed_by = 'users_file'
        synced += 1
    db.commit()
    if synced:
        try:
            from sajha.auth.apikeys import ensure_default_key
            for rec in store.users():
                if problem(rec, set(roles)) is None:
                    u = db.query(User).filter(User.user_id == rec['user_id']).first()
                    if u is not None:
                        ensure_default_key(db, u)
        except Exception as e:                       # default keys are best effort here
            logger.debug(f'users file: default keys not ensured: {e}')
    return synced, problems


_store: Optional[UsersFile] = None
_lock = threading.Lock()


def get_users_file() -> UsersFile:
    global _store
    with _lock:
        if _store is None:
            _store = UsersFile(configured_path())
        return _store


def set_users_file(store: Optional[UsersFile]) -> None:
    global _store
    with _lock:
        _store = store
