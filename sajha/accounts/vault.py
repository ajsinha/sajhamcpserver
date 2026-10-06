"""
SAJHA MCP Server — connected accounts: the token vault.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One row per (SAJHA user, provider) in ``connected_accounts`` (defined in
``db/scripts/<dialect>/schema.sql`` with the rest of the schema; SQLite creates it, PostgreSQL is
set up by the operator from the schema file).  The tokens (access token, refresh token, token type) are one
JSON document encrypted with AES-256-GCM; everything else on the row is metadata the
account page and the admin view show: the provider-side login, the granted scopes, the
expiry, the status.  The database never holds a token in clear.

* The data key: ``accounts.vault.key`` (env ``SAJHA_ACCOUNTS_VAULT_KEY``; 32 bytes as
  base64url, or any passphrase, stretched with HKDF-SHA256), else a key generated once
  and kept in the server secrets file (``<data.dir>/secrets/server_secrets.json``, mode
  0600), which every worker that shares the data directory reads.  Several hosts must
  share ``SAJHA_ACCOUNTS_VAULT_KEY`` instead.
* Rotation: put the old key in ``accounts.vault.previous_keys`` and the new one in
  ``accounts.vault.key``; rows still decrypt (each row records its ``key_id``) and are
  re-encrypted with the current key when used, or all at once with :meth:`TokenVault.rotate`
  (the admin page's "Re-encrypt" button).  Remove the old key once nothing uses it.
* KMS hook: ``accounts.vault.key_provider: package.module:factory`` names a callable
  returning an object with ``current() -> (key_id, 32 bytes)`` and
  ``lookup(key_id) -> bytes | None`` (for example one that unwraps a data key with AWS KMS
  or Vault Transit at start-up).
* Each ciphertext is bound to its row's user and provider (GCM associated data), so a
  ciphertext copied onto another user's row does not decrypt.

No token, key or ciphertext is ever logged.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (Boolean, Column, DateTime, Index, MetaData, String, Table, Text, and_, delete, insert,
                        select, update)

from sajha.accounts.errors import VaultError

logger = logging.getLogger(__name__)

metadata = MetaData()

connected_accounts = Table(
    'connected_accounts', metadata,
    Column('id', String(36), primary_key=True),
    Column('user_id', String(200), nullable=False),
    Column('provider', String(64), nullable=False),
    Column('account_login', String(255)),
    Column('account_id', String(255)),
    Column('scopes', String(4000)),
    Column('token_ciphertext', Text, nullable=False),
    Column('key_id', String(64), nullable=False),
    Column('has_refresh_token', Boolean, nullable=False, default=False),
    Column('expires_at', DateTime),
    Column('status', String(20), nullable=False),
    Column('last_error', String(500)),
    Column('created_at', DateTime, nullable=False),
    Column('updated_at', DateTime, nullable=False),
    Column('last_used_at', DateTime),
    Column('last_refreshed_at', DateTime),
    Index('ux_connected_accounts_user_provider', 'user_id', 'provider', unique=True),
    Index('ix_connected_accounts_provider', 'provider'),
)

STATUSES = ('active', 'reauth_required')
_CT_PREFIX = 'v1:'


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── keys ────────────────────────────────────────────────────────────

def derive_key(secret: str) -> bytes:
    """32 bytes from a configured secret: base64url of 32 bytes as is, anything else via HKDF-SHA256."""
    s = (secret or '').strip()
    if not s:
        raise VaultError('empty vault key')
    try:
        raw = base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))
        if len(raw) == 32 and len(s) >= 43:
            return raw
    except (ValueError, TypeError):
        pass
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b'sajha-accounts-vault',
                info=b'sajha/accounts/vault/v1').derive(s.encode('utf-8'))


def key_id_of(key: bytes) -> str:
    return 'k' + hashlib.sha256(b'sajha-vault-kid|' + key).hexdigest()[:12]


class LocalKeyProvider:
    """Keys from configuration (current + previous), or one generated into the secrets file."""

    def __init__(self, key: str = '', previous: Optional[List[str]] = None):
        if not key:
            from sajha.core.server_secrets import persisted_secret
            key = persisted_secret('accounts_vault_key')
        cur = derive_key(key)
        self._current = key_id_of(cur)
        self._keys: Dict[str, bytes] = {self._current: cur}
        for p in previous or []:
            try:
                k = derive_key(p)
            except VaultError:
                continue
            self._keys.setdefault(key_id_of(k), k)

    def current(self) -> Tuple[str, bytes]:
        return self._current, self._keys[self._current]

    def lookup(self, key_id: str) -> Optional[bytes]:
        return self._keys.get(key_id)


def build_key_provider(settings=None):
    from sajha.accounts.settings import get_accounts_settings
    s = settings or get_accounts_settings()
    if s.vault_key_provider:
        mod, _, attr = s.vault_key_provider.partition(':')
        if not attr:
            raise VaultError('accounts.vault.key_provider must be "package.module:factory"')
        factory = getattr(importlib.import_module(mod), attr)
        kp = factory()
        if not (callable(getattr(kp, 'current', None)) and callable(getattr(kp, 'lookup', None))):
            raise VaultError('the vault key provider must have current() and lookup(key_id)')
        return kp
    return LocalKeyProvider(s.vault_key, s.vault_previous_keys or [])


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _aad(user_id: str, provider: str) -> bytes:
    return f'sajha/accounts/v1|{user_id}|{provider}'.encode('utf-8')


# ── rows ────────────────────────────────────────────────────────────

@dataclass
class Connection:
    """One linked account: metadata in clear, tokens only through :meth:`TokenVault.tokens`."""
    id: str
    user_id: str
    provider: str
    account_login: str = ''
    account_id: str = ''
    scopes: List[str] = field(default_factory=list)
    has_refresh_token: bool = False
    expires_at: Optional[datetime] = None
    status: str = 'active'
    last_error: str = ''
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    last_refreshed_at: Optional[datetime] = None
    key_id: str = ''
    _ciphertext: str = field(default='', repr=False)

    def expires_within(self, seconds: float) -> bool:
        return self.expires_at is not None and self.expires_at <= utcnow() + timedelta(seconds=seconds)

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= utcnow()

    def to_public(self) -> Dict[str, Any]:
        """For pages and APIs: never a token, a ciphertext or a key."""
        def iso(d):
            return d.replace(microsecond=0).isoformat() + 'Z' if d else None
        return {'provider': self.provider, 'user_id': self.user_id, 'account_login': self.account_login,
                'account_id': self.account_id, 'scopes': list(self.scopes), 'status': self.status,
                'last_error': self.last_error, 'expires_at': iso(self.expires_at),
                'refreshable': self.has_refresh_token, 'created_at': iso(self.created_at),
                'updated_at': iso(self.updated_at), 'last_used_at': iso(self.last_used_at),
                'last_refreshed_at': iso(self.last_refreshed_at)}


def _row_to_connection(r) -> Connection:
    m = r._mapping
    return Connection(id=m['id'], user_id=m['user_id'], provider=m['provider'],
                      account_login=m['account_login'] or '', account_id=m['account_id'] or '',
                      scopes=[s for s in (m['scopes'] or '').split(' ') if s],
                      has_refresh_token=bool(m['has_refresh_token']), expires_at=m['expires_at'],
                      status=m['status'], last_error=m['last_error'] or '', created_at=m['created_at'],
                      updated_at=m['updated_at'], last_used_at=m['last_used_at'],
                      last_refreshed_at=m['last_refreshed_at'], key_id=m['key_id'],
                      _ciphertext=m['token_ciphertext'])


class VaultSchemaMissing(VaultError):
    """PostgreSQL without the connected_accounts table (apply the schema file)."""


class TokenVault:
    def __init__(self, engine=None, key_provider=None):
        self._engine = engine
        self._kp = key_provider
        self._ready_for = None
        self._lock = threading.Lock()

    # ── plumbing ─────────────────────────────────────────────────
    @property
    def engine(self):
        if self._engine is not None:
            return self._engine
        from sajha.db.engine import get_engine
        return get_engine()

    @property
    def keys(self):
        if self._kp is None:
            with self._lock:
                if self._kp is None:
                    self._kp = build_key_provider()
        return self._kp

    def ensure_table(self) -> None:
        engine = self.engine
        if self._ready_for is engine:
            return
        with self._lock:
            if self._ready_for is engine:
                return
            if engine.dialect.name == 'sqlite':
                metadata.create_all(engine, tables=[connected_accounts], checkfirst=True)
            else:
                from sqlalchemy import inspect
                if not inspect(engine).has_table('connected_accounts'):
                    # SAJHA runs no DDL on PostgreSQL: the table comes from the schema file
                    from sajha.db.schema import apply_command
                    raise VaultSchemaMissing('table connected_accounts is missing; create it from the '
                                             f'schema file:  {apply_command(engine)}  '
                                             '(docs/getting-started/Database Setup.md)')
            self._ready_for = engine

    # ── crypto ───────────────────────────────────────────────────
    def encrypt(self, user_id: str, provider: str, tokens: Dict[str, Any]) -> Tuple[str, str]:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        kid, key = self.keys.current()
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, json.dumps(tokens, separators=(',', ':')).encode('utf-8'),
                                 _aad(user_id, provider))
        return _CT_PREFIX + _b64e(nonce + ct), kid

    def decrypt(self, user_id: str, provider: str, ciphertext: str, key_id: str) -> Dict[str, Any]:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = self.keys.lookup(key_id)
        if key is None:
            raise VaultError(f'no vault key {key_id} (was the key changed without listing the old one '
                             f'in accounts.vault.previous_keys?)')
        if not (ciphertext or '').startswith(_CT_PREFIX):
            raise VaultError('stored token is not in a known format')
        try:
            raw = _b64d(ciphertext[len(_CT_PREFIX):])
            plain = AESGCM(key).decrypt(raw[:12], raw[12:], _aad(user_id, provider))
            return json.loads(plain)
        except (InvalidTag, ValueError, TypeError):
            raise VaultError('stored token failed to decrypt (wrong key or tampered row)') from None

    # ── reads ────────────────────────────────────────────────────
    def get(self, user_id: str, provider: str) -> Optional[Connection]:
        self.ensure_table()
        with self.engine.connect() as c:
            r = c.execute(select(connected_accounts).where(and_(connected_accounts.c.user_id == user_id,
                                                                connected_accounts.c.provider == provider))).first()
        return _row_to_connection(r) if r is not None else None

    def tokens(self, conn: Connection) -> Dict[str, Any]:
        """The decrypted token document; re-encrypts the row when it used an old key."""
        doc = self.decrypt(conn.user_id, conn.provider, conn._ciphertext, conn.key_id)
        if conn.key_id != self.keys.current()[0]:
            try:
                self._reencrypt(conn, doc)
            except Exception as e:      # the read already succeeded; rotation retries next time
                logger.warning(f'accounts: re-encrypting {conn.provider} for {conn.user_id} failed: '
                               f'{type(e).__name__}')
        return doc

    def list_for_user(self, user_id: str) -> List[Connection]:
        self.ensure_table()
        with self.engine.connect() as c:
            rows = c.execute(select(connected_accounts).where(connected_accounts.c.user_id == user_id)
                             .order_by(connected_accounts.c.provider)).all()
        return [_row_to_connection(r) for r in rows]

    def list_all(self, provider: Optional[str] = None, user_id: Optional[str] = None,
                 limit: int = 1000) -> List[Connection]:
        self.ensure_table()
        q = select(connected_accounts)
        if provider:
            q = q.where(connected_accounts.c.provider == provider)
        if user_id:
            q = q.where(connected_accounts.c.user_id == user_id)
        q = q.order_by(connected_accounts.c.user_id, connected_accounts.c.provider).limit(max(1, limit))
        with self.engine.connect() as c:
            return [_row_to_connection(r) for r in c.execute(q).all()]

    # ── writes ───────────────────────────────────────────────────
    def save(self, user_id: str, provider: str, tokens: Dict[str, Any], *, scopes: List[str],
             expires_at: Optional[datetime], account_login: str = '', account_id: str = '',
             refreshed: bool = False) -> Connection:
        """Insert or replace the user's link to ``provider`` (status active)."""
        self.ensure_table()
        ct, kid = self.encrypt(user_id, provider, tokens)
        now = utcnow()
        values = dict(account_login=(account_login or '')[:255], account_id=str(account_id or '')[:255],
                      scopes=' '.join(scopes)[:4000], token_ciphertext=ct, key_id=kid,
                      has_refresh_token=bool(tokens.get('refresh_token')), expires_at=expires_at,
                      status='active', last_error=None, updated_at=now)
        if refreshed:
            values['last_refreshed_at'] = now
        from sqlalchemy.exc import IntegrityError
        where = and_(connected_accounts.c.user_id == user_id, connected_accounts.c.provider == provider)
        for _ in range(2):
            with self.engine.begin() as c:
                n = c.execute(update(connected_accounts).where(where).values(**values)).rowcount
                if n:
                    break
                try:
                    c.execute(insert(connected_accounts).values(id=str(uuid.uuid4()), user_id=user_id,
                                                                provider=provider, created_at=now, **values))
                    break
                except IntegrityError:      # another worker inserted it first: update instead
                    continue
        return self.get(user_id, provider)

    def update_tokens(self, conn: Connection, tokens: Dict[str, Any], *, expires_at: Optional[datetime],
                      scopes: Optional[List[str]] = None) -> Connection:
        """After a refresh: new ciphertext, expiry and (when the provider says) scopes."""
        return self.save(conn.user_id, conn.provider, tokens, scopes=scopes if scopes else conn.scopes,
                         expires_at=expires_at, account_login=conn.account_login,
                         account_id=conn.account_id, refreshed=True)

    def set_status(self, user_id: str, provider: str, status: str, error: str = '') -> None:
        if status not in STATUSES:
            raise ValueError(status)
        self.ensure_table()
        with self.engine.begin() as c:
            c.execute(update(connected_accounts)
                      .where(and_(connected_accounts.c.user_id == user_id, connected_accounts.c.provider == provider))
                      .values(status=status, last_error=(error or None) and error[:500], updated_at=utcnow()))

    def touch(self, conn: Connection, min_interval: float = 60.0) -> None:
        """Record use (at most once a minute per link, to keep writes off the hot path)."""
        now = utcnow()
        if conn.last_used_at and (now - conn.last_used_at).total_seconds() < min_interval:
            return
        try:
            with self.engine.begin() as c:
                c.execute(update(connected_accounts).where(connected_accounts.c.id == conn.id)
                          .values(last_used_at=now))
        except Exception as e:
            logger.debug(f'accounts: touch failed: {type(e).__name__}')

    def delete(self, user_id: str, provider: str) -> bool:
        self.ensure_table()
        with self.engine.begin() as c:
            n = c.execute(delete(connected_accounts).where(and_(connected_accounts.c.user_id == user_id,
                                                                connected_accounts.c.provider == provider))).rowcount
        return bool(n)

    def _reencrypt(self, conn: Connection, doc: Dict[str, Any]) -> None:
        ct, kid = self.encrypt(conn.user_id, conn.provider, doc)
        with self.engine.begin() as c:
            c.execute(update(connected_accounts).where(and_(connected_accounts.c.id == conn.id,
                                                            connected_accounts.c.key_id == conn.key_id))
                      .values(token_ciphertext=ct, key_id=kid))

    def rotate(self) -> Dict[str, int]:
        """Re-encrypt every row not under the current key. {'rotated', 'failed', 'current'}"""
        current = self.keys.current()[0]
        out = {'rotated': 0, 'failed': 0, 'current': 0}
        for conn in self.list_all(limit=1_000_000):
            if conn.key_id == current:
                out['current'] += 1
                continue
            try:
                doc = self.decrypt(conn.user_id, conn.provider, conn._ciphertext, conn.key_id)
                self._reencrypt(conn, doc)
                out['rotated'] += 1
            except VaultError:
                out['failed'] += 1
        return out

    def key_usage(self) -> Dict[str, int]:
        """Rows per key id (the admin view: is an old key still needed?)."""
        out: Dict[str, int] = {}
        for conn in self.list_all(limit=1_000_000):
            out[conn.key_id] = out.get(conn.key_id, 0) + 1
        return out


_vault: Optional[TokenVault] = None


def get_vault() -> TokenVault:
    global _vault
    if _vault is None:
        _vault = TokenVault()
    return _vault


def set_vault(vault: Optional[TokenVault]) -> None:
    global _vault
    _vault = vault
