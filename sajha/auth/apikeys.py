"""
SAJHA MCP Server — API keys owned by users: create, rotate, revoke, default keys.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* **Owned keys.** A key with an owner (``api_keys.owner_id``) signs in as that user, with the
  user's roles; the key's tool access mode and list are an extra ceiling
  (``sajha/auth/access.py``). A key without an owner keeps the older service identity
  ``apikey:<name>`` with the role ``api_consumer`` until an administrator assigns an owner.
* **Self-service.** Signed-in users create, rotate and revoke their own keys
  (``/account/apikeys``); administrators manage every key (``/admin/apikeys``).
* **Revocation record.** Revoking sets ``revoked_at`` / ``revoked_by`` and disables the key
  for good; the row stays, so the record survives.
* **Default key.** Every user has exactly one default key, created with the account (and at
  start-up for accounts that have none). It cannot be deleted or revoked, only rotated (by
  its owner or an administrator) or disabled (by an administrator). Its raw value is kept
  encrypted with the connected-accounts vault's AES-256-GCM data key
  (``sajha/accounts/vault.py``; bound to the owner and the key id), so the server can use
  it on the owner's behalf later; it is shown to the user once, after each rotation.
* **Persistent keys.** A key an administrator marks persistent is also kept, hashed, in the
  file at ``config.apikeys.path`` (``sajha/auth/persistent_keys.py``).

Every change is written to the audit log. Owner guide: docs/security/Security Model.md.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

PREFIX = 'sja_'
DEFAULT_KEY_NAME = 'default'
MODES = ('all', 'allowlist', 'denylist', 'regex')


class KeyError_(ValueError):
    """A key operation that is not allowed (the message says why)."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_raw() -> str:
    return f'{PREFIX}{secrets.token_hex(24)}'


def _hash(raw: str) -> str:
    """SHA-256 hex, as ``ApiKeyDAO.hash_key``."""
    import hashlib
    return hashlib.sha256(raw.encode()).hexdigest()


def max_per_user() -> int:
    from sajha.core.config import _int
    return max(1, _int('auth.api_keys.max_per_user', 25))


def _audit(db, action: str, by: str, key, details: Optional[dict] = None) -> None:
    try:
        from sajha.db.dao import AuditDAO
        d = {'key_id': key.id, 'prefix': key.key_prefix}
        d.update(details or {})
        AuditDAO(db).log(action, by, 'apikey', key.name, d)
    except Exception as e:
        logger.warning(f'audit of {action} failed: {e}')


def _vault():
    from sajha.accounts.vault import get_vault
    return get_vault()


def _provider_of(key) -> str:
    return f'apikey:{key.id}'


def _store_secret(key, owner, raw: str) -> None:
    """Default keys: keep the raw key encrypted (vault data key, bound to owner and key id)."""
    ct, kid = _vault().encrypt(owner.user_id, _provider_of(key), {'key': raw})
    key.secret_ciphertext, key.secret_key_id = ct, kid


def default_key_secret(db, user) -> Optional[str]:
    """The raw value of ``user``'s default key, decrypted; None when there is none or it is unusable."""
    key = default_key_of(db, user)
    if key is None or not key.secret_ciphertext or key.revoked_at is not None or not key.enabled:
        return None
    try:
        doc = _vault().decrypt(user.user_id, _provider_of(key), key.secret_ciphertext, key.secret_key_id or '')
    except Exception as e:
        logger.warning(f'default API key of {user.user_id} could not be decrypted: {e}')
        return None
    raw = doc.get('key') if isinstance(doc, dict) else None
    if not isinstance(raw, str) or _hash(raw) != key.key_hash:
        return None
    return raw


# ── persistent file ───────────────────────────────────────────────

def _sync_persistent(key, owner=None) -> None:
    from sajha.auth.persistent_keys import get_persistent_keys, record_for
    try:
        store = get_persistent_keys()
        if key.persistent:
            store.upsert(record_for(key, owner if owner is not None else key.owner))
        elif key.id in store.ids():
            store.remove(key.id)
    except Exception as e:
        logger.error(f'persistent API keys: could not update the file for key {key.key_prefix}: {e}')


def _drop_persistent(key_id: str) -> None:
    from sajha.auth.persistent_keys import get_persistent_keys
    try:
        get_persistent_keys().remove(key_id)
    except Exception as e:
        logger.error(f'persistent API keys: could not remove key {key_id} from the file: {e}')


# ── reads ─────────────────────────────────────────────────────────

def keys_of(db, user, include_revoked: bool = True) -> List:
    from sajha.db.models import ApiKey
    q = db.query(ApiKey).filter(ApiKey.owner_id == user.id)
    if not include_revoked:
        q = q.filter(ApiKey.revoked_at.is_(None))
    return q.order_by(ApiKey.is_default.desc(), ApiKey.created_at.desc()).all()


def default_key_of(db, user):
    from sajha.db.models import ApiKey
    return (db.query(ApiKey).filter(ApiKey.owner_id == user.id, ApiKey.is_default.is_(True))
            .order_by(ApiKey.created_at).first())


def get_key(db, key_id: str):
    from sajha.db.models import ApiKey
    return db.query(ApiKey).filter(ApiKey.id == key_id).first()


def _iso(d: Optional[datetime]) -> Optional[str]:
    if d is None:
        return None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d.replace(microsecond=0).isoformat() + 'Z'


def status_of(key) -> str:
    if key.revoked_at is not None:
        return 'revoked'
    if not key.enabled:
        return 'disabled'
    exp = key.expires_at
    if exp is not None:
        exp = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            return 'expired'
    return 'active'


def public(key) -> Dict[str, Any]:
    """For pages and APIs: never the key, its hash or its ciphertext."""
    try:
        tools = json.loads(key.tool_access_list or '[]')
    except ValueError:
        tools = []
    owner = key.owner
    return {
        'id': key.id, 'name': key.name, 'description': key.description or '', 'prefix': key.key_prefix,
        'owner': owner.user_id if owner is not None else None,
        'owner_name': owner.user_name if owner is not None else None,
        'is_default': bool(key.is_default), 'persistent': bool(key.persistent),
        'enabled': bool(key.enabled), 'status': status_of(key),
        'tool_access_mode': key.tool_access_mode or 'all', 'tool_access_list': tools if isinstance(tools, list) else [],
        'created_at': _iso(key.created_at), 'created_by': key.created_by,
        'expires_at': _iso(key.expires_at), 'last_used': _iso(key.last_used), 'usage_count': key.usage_count or 0,
        'rotated_at': _iso(key.rotated_at), 'revoked_at': _iso(key.revoked_at), 'revoked_by': key.revoked_by,
    }


# ── changes ───────────────────────────────────────────────────────

def _access(mode: Optional[str], tools: Optional[Iterable[str]]) -> Tuple[str, Optional[str]]:
    mode = (mode or 'all').strip().lower()
    if mode not in MODES:
        raise KeyError_(f'tool_access_mode must be one of {", ".join(MODES)}')
    patterns = [str(t).strip() for t in (tools or []) if str(t).strip()]
    if mode in ('allowlist', 'regex') and not patterns:
        raise KeyError_(f'tool_access_mode {mode} needs at least one pattern in tool_list')
    return mode, (json.dumps(patterns) if patterns else None)


def _expiry(days: Any) -> Optional[datetime]:
    if days in (None, '', 0, '0'):
        return None
    try:
        n = int(days)
    except (TypeError, ValueError):
        raise KeyError_('expires_in_days must be a whole number of days')
    if n < 1 or n > 3650:
        raise KeyError_('expires_in_days must be between 1 and 3650')
    return _now() + timedelta(days=n)


def create_key(db, *, name: str, created_by: str, owner=None, description: str = '',
               mode: str = 'all', tool_list: Optional[Iterable[str]] = None, expires_in_days: Any = None,
               persistent: bool = False, is_default: bool = False) -> Tuple[Any, str]:
    """A new key; returns ``(row, raw key)``. The raw key is not stored (default keys: encrypted)."""
    from sajha.db.models import ApiKey
    name = (name or '').strip()[:255] or 'Unnamed key'
    mode, tools = _access(mode, tool_list)
    if owner is not None and not is_default and len(keys_of(db, owner, include_revoked=False)) >= max_per_user() + 1:
        raise KeyError_(f'{owner.user_id} already has the most keys allowed (auth.api_keys.max_per_user: '
                        f'{max_per_user()}); revoke one first')
    raw = generate_raw()
    key = ApiKey(key_hash=_hash(raw), key_prefix=raw[:8], name=name, description=(description or '')[:500] or None,
                 owner_id=owner.id if owner is not None else None, tool_access_mode=mode, tool_access_list=tools,
                 expires_at=_expiry(expires_in_days), persistent=bool(persistent), is_default=bool(is_default),
                 created_by=created_by, enabled=True, usage_count=0)
    from sajha.db.models import _uuid
    key.id = _uuid()
    if is_default:
        if owner is None:
            raise KeyError_('a default key needs an owner')
        _store_secret(key, owner, raw)
    db.add(key)
    db.commit()
    db.refresh(key)
    _audit(db, 'apikey.create', created_by, key, {'owner': owner.user_id if owner is not None else None,
                                                  'default': bool(is_default), 'persistent': bool(persistent),
                                                  'mode': mode})
    if key.persistent:
        _sync_persistent(key, owner)
    return key, raw


def rotate_key(db, key, by: str) -> str:
    """A new secret for the same key (same id, owner, access); the old one stops working at once."""
    if key.revoked_at is not None:
        raise KeyError_('a revoked key cannot be rotated')
    raw = generate_raw()
    key.key_hash, key.key_prefix, key.rotated_at = _hash(raw), raw[:8], _now()
    if key.is_default and key.owner is not None:
        _store_secret(key, key.owner, raw)
    db.commit()
    _audit(db, 'apikey.rotate', by, key)
    if key.persistent:
        _sync_persistent(key)
    return raw


def revoke_key(db, key, by: str) -> None:
    """Revoke for good: disabled, with ``revoked_at`` / ``revoked_by``. A default key cannot be revoked."""
    if key.is_default:
        raise KeyError_('a default key cannot be revoked or deleted; rotate it, or an administrator disables it')
    if key.revoked_at is not None:
        return
    key.revoked_at, key.revoked_by, key.enabled = _now(), by, False
    key.secret_ciphertext = key.secret_key_id = None
    db.commit()
    _audit(db, 'apikey.revoke', by, key)
    if key.persistent:
        _sync_persistent(key)


def set_enabled(db, key, enabled: bool, by: str) -> None:
    if key.revoked_at is not None and enabled:
        raise KeyError_('a revoked key cannot be enabled again; create a new key')
    key.enabled = bool(enabled)
    db.commit()
    _audit(db, 'apikey.enable' if enabled else 'apikey.disable', by, key)
    if key.persistent:
        _sync_persistent(key)


def set_access(db, key, mode: str, tool_list: Optional[Iterable[str]], by: str) -> None:
    key.tool_access_mode, key.tool_access_list = _access(mode, tool_list)
    db.commit()
    _audit(db, 'apikey.access', by, key, {'mode': key.tool_access_mode})
    if key.persistent:
        _sync_persistent(key)


def set_persistent(db, key, on: bool, by: str) -> None:
    if on and key.revoked_at is not None:
        raise KeyError_('a revoked key cannot be made persistent')
    key.persistent = bool(on)
    db.commit()
    _audit(db, 'apikey.persistent', by, key, {'persistent': key.persistent})
    _sync_persistent(key)


def assign_owner(db, key, user, by: str) -> None:
    """Give an unowned (older) key an owner: from now on it signs in as that user."""
    if key.owner_id is not None:
        raise KeyError_('this key already has an owner')
    if key.revoked_at is not None:
        raise KeyError_('a revoked key cannot be given an owner')
    key.owner_id = user.id
    db.commit()
    db.refresh(key)
    _audit(db, 'apikey.assign_owner', by, key, {'owner': user.user_id})
    if key.persistent:
        _sync_persistent(key, user)


def delete_key(db, key, by: str) -> None:
    """Administrators: remove the row (and its file record). A default key cannot be deleted."""
    if key.is_default:
        raise KeyError_('a default key cannot be deleted; rotate or disable it')
    key_id = key.id
    _audit(db, 'apikey.delete', by, key)
    db.delete(key)
    db.commit()
    _drop_persistent(key_id)


def ensure_default_key(db, user, by: str = 'system') -> Optional[Any]:
    """Create ``user``'s default key when it has none. Returns the new row, or None."""
    if default_key_of(db, user) is not None:
        return None
    key, _ = create_key(db, name=DEFAULT_KEY_NAME, created_by=by, owner=user,
                        description=f'Default API key of {user.user_id}', is_default=True)
    return key


def ensure_default_keys(db) -> int:
    """Start-up: a default key for every account that has none. Returns how many were created."""
    from sajha.db.models import User
    made = 0
    for user in db.query(User).all():
        try:
            if ensure_default_key(db, user) is not None:
                made += 1
        except Exception as e:
            db.rollback()
            logger.warning(f'default API key for {user.user_id} not created: {e}')
    return made


def forget_user(db, user) -> None:
    """Before a user is deleted: drop the file records of their persistent keys (the rows go with the user)."""
    for key in keys_of(db, user):
        if key.persistent:
            _drop_persistent(key.id)
