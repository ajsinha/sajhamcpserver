"""
The ``database`` key directory store (design §10.3, §20.1): the ``sajhanet_api_keys`` table, one
row per key record of every home in every net this server is in (its own records included), kept
apart from the local ``api_keys`` table so local key administration is unchanged.

* The row holds the signed record as JSON (``record_json``) plus the columns lookups need: the key
  hash (indexed with the net), the home, the version, the signer's certificate thumbprint (to
  discard records of a revoked certificate, protocol §11.2) and ``unusable`` (``left``,
  ``revoked``: the home is gone; the record is kept and refuses every forwarded key).
* SQLite creates the table on first use; PostgreSQL gets it from
  ``db/scripts/postgresql/schema.sql`` (an operator runs what ``python -m sajha.db upgrade-sql``
  prints; SAJHA runs no DDL there).

Also here: :func:`own_keys`, the home's keys as record bodies for :class:`sajha.net.keydir.KeyDirectory`
(owned keys in ``api_keys`` plus persistent keys the database does not hold; keys without an owner
never cross the net).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import (Boolean, Column, Float, Index, Integer, MetaData, String, Table, Text, and_, delete, insert,
                        select, update)

from sajha.net import plugins

logger = logging.getLogger(__name__)

metadata = MetaData()

sajhanet_api_keys = Table(
    'sajhanet_api_keys', metadata,
    Column('net', String(16), primary_key=True),
    Column('key_id', String(64), primary_key=True),
    Column('home_instance', String(255), nullable=False),
    Column('key_hash', String(64), nullable=False),
    Column('version', Integer, nullable=False),
    Column('owner_user', String(255)),
    Column('enabled', Boolean, nullable=False),
    Column('expires_at', String(40)),
    Column('revoked_at', String(40)),
    Column('signer_keyid', String(64), nullable=False),
    Column('unusable', String(20)),
    Column('record_json', Text, nullable=False),
    Column('received_at', Float, nullable=False),
    Index('ix_sajhanet_api_keys_hash', 'net', 'key_hash'),
    Index('ix_sajhanet_api_keys_home', 'net', 'home_instance', 'version'),
)


class StoreUnavailable(RuntimeError):
    """No database, or the table is missing on PostgreSQL."""


@plugins.register('key_directory_store')
class DatabaseKeyDirectory(plugins.KeyDirectoryStore):
    """Key records in the ``sajhanet_api_keys`` table of ``engine``; ``sajha_db=True`` (what the
    service uses): SAJHA's own database; neither: a private in-memory SQLite database (contract
    checks, tools)."""
    name = 'database'

    def __init__(self, engine=None, sajha_db: bool = False):
        self._engine = engine if engine is not None or sajha_db else _scratch_engine()
        self._ready_for = None
        self._lock = threading.Lock()

    @property
    def engine(self):
        if self._engine is not None:
            return self._engine
        from sajha.db.engine import get_engine
        return get_engine()

    def ensure(self):
        eng = self.engine
        if eng is None:
            raise StoreUnavailable('no database engine')
        if self._ready_for is eng:
            return eng
        with self._lock:
            if eng.dialect.name == 'sqlite':
                metadata.create_all(eng, checkfirst=True)
            else:
                from sqlalchemy import inspect
                if not inspect(eng).has_table('sajhanet_api_keys'):
                    from sajha.db.schema import apply_command
                    raise StoreUnavailable('table sajhanet_api_keys is missing; create it from the schema file: '
                                           f'{apply_command(eng)}')
            self._ready_for = eng
        return eng

    @staticmethod
    def _row(m) -> Dict[str, Any]:
        rec = json.loads(m['record_json'])
        if m['unusable']:
            rec['unusable'] = m['unusable']
        return rec

    def put(self, record, force=False):
        eng = self.ensure()
        net, kid = record['net'], str(record['key_id'])
        values = dict(home_instance=record['home_instance'], key_hash=record['key_hash'],
                      version=int(record['version']), owner_user=str((record.get('owner') or {}).get('user_name') or '')[:255],
                      enabled=bool(record.get('enabled')), expires_at=record.get('expires_at'),
                      revoked_at=record.get('revoked_at'),
                      signer_keyid=str((record.get('signature') or {}).get('keyid') or '')[:64],
                      record_json=json.dumps({k: v for k, v in record.items() if k != 'unusable'},
                                             separators=(',', ':'), sort_keys=True),
                      received_at=time.time())
        with eng.begin() as c:
            held = c.execute(select(sajhanet_api_keys.c.home_instance, sajhanet_api_keys.c.version,
                                    sajhanet_api_keys.c.unusable).where(
                and_(sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.key_id == kid))).first()
            if held is None:
                c.execute(insert(sajhanet_api_keys).values(net=net, key_id=kid, unusable=None, **values))
                return True
            if held[0] != record['home_instance'] or (not force and int(held[1]) >= int(record['version'])):
                return False
            c.execute(update(sajhanet_api_keys).where(
                and_(sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.key_id == kid)).values(**values))
            return True

    def find(self, net, key_hash):
        with self.ensure().connect() as c:
            rows = c.execute(select(sajhanet_api_keys).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.key_hash == key_hash))
                .order_by(sajhanet_api_keys.c.key_id)).all()
        return [self._row(r._mapping) for r in rows]

    def by_hash(self, net, key_hash):
        found = self.find(net, key_hash)
        return found[0] if found else None

    def by_id(self, net, home, key_id):
        with self.ensure().connect() as c:
            r = c.execute(select(sajhanet_api_keys).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.key_id == str(key_id),
                sajhanet_api_keys.c.home_instance == home))).first()
        return self._row(r._mapping) if r is not None else None

    def since(self, net, home, version, limit=1000):
        with self.ensure().connect() as c:
            rows = c.execute(select(sajhanet_api_keys).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.home_instance == home,
                sajhanet_api_keys.c.version > int(version))).order_by(sajhanet_api_keys.c.version)
                .limit(int(limit))).all()
        return [self._row(r._mapping) for r in rows]

    def version(self, net, home):
        from sqlalchemy import func
        with self.ensure().connect() as c:
            v = c.execute(select(func.max(sajhanet_api_keys.c.version)).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.home_instance == home))).scalar()
        return int(v or 0)

    def discard_signed(self, net, keyid):
        with self.ensure().begin() as c:
            homes = sorted({r[0] for r in c.execute(select(sajhanet_api_keys.c.home_instance).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.signer_keyid == keyid))).all()})
            c.execute(delete(sajhanet_api_keys).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.signer_keyid == keyid)))
        return homes

    def mark(self, net, home, reason):
        with self.ensure().begin() as c:
            c.execute(update(sajhanet_api_keys).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.home_instance == home)).values(
                unusable=(reason or None)))

    def marked(self, net, home):
        with self.ensure().connect() as c:
            r = c.execute(select(sajhanet_api_keys.c.unusable).where(and_(
                sajhanet_api_keys.c.net == net, sajhanet_api_keys.c.home_instance == home,
                sajhanet_api_keys.c.unusable.isnot(None))).limit(1)).first()
        return r[0] if r else None

    # ── console views ──────────────────────────────────────────────

    def summary(self, net: str) -> List[Dict[str, Any]]:
        """Per home: record count, revoked, unusable mark, highest version, last received."""
        out: Dict[str, Dict[str, Any]] = {}
        with self.ensure().connect() as c:
            for r in c.execute(select(sajhanet_api_keys.c.home_instance, sajhanet_api_keys.c.version,
                                      sajhanet_api_keys.c.revoked_at, sajhanet_api_keys.c.enabled,
                                      sajhanet_api_keys.c.unusable, sajhanet_api_keys.c.received_at).where(
                    sajhanet_api_keys.c.net == net)).all():
                h = out.setdefault(r[0], {'home': r[0], 'records': 0, 'revoked': 0, 'disabled': 0, 'version': 0,
                                          'unusable': None, 'last_received': 0.0})
                h['records'] += 1
                h['revoked'] += 1 if r[2] else 0
                h['disabled'] += 0 if r[3] else 1
                h['version'] = max(h['version'], int(r[1]))
                h['unusable'] = h['unusable'] or r[4]
                h['last_received'] = max(h['last_received'], float(r[5] or 0))
        return sorted(out.values(), key=lambda h: h['home'])

    def records(self, net: str, home: str, limit: int = 500) -> List[Dict[str, Any]]:
        """Public view of a home's records (never the hash in full)."""
        out = []
        for rec in self.since(net, home, 0, limit=limit):
            out.append({'key_id': rec['key_id'], 'prefix': rec.get('key_prefix'), 'name': rec.get('name'),
                        'owner': (rec.get('owner') or {}).get('user_name'), 'enabled': rec.get('enabled'),
                        'expires_at': rec.get('expires_at'), 'revoked_at': rec.get('revoked_at'),
                        'tool_access_mode': rec.get('tool_access_mode'), 'persistent': rec.get('persistent'),
                        'version': rec.get('version'), 'updated_at': rec.get('updated_at'),
                        'unusable': rec.get('unusable')})
        return out


def _scratch_engine():
    """A private in-memory SQLite database when SAJHA has none (tools, tests without a database)."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    return create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)


# ── the home's own keys ─────────────────────────────────────────────

def _iso(d: Optional[datetime]) -> Optional[str]:
    if d is None:
        return None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d.replace(microsecond=0).isoformat() + 'Z'


def _tools(text: Any) -> List[str]:
    if isinstance(text, list):
        return [str(t) for t in text]
    try:
        v = json.loads(text or '[]')
    except (TypeError, ValueError):
        return []
    return [str(t) for t in v] if isinstance(v, list) else []


def body_of_key(key, owner) -> Dict[str, Any]:
    """The record body of an owned ``ApiKey`` row (protocol §11.1; ``owner`` its ``User``)."""
    return {
        'key_id': key.id, 'key_prefix': (key.key_prefix or '')[:16], 'name': (key.name or '')[:255],
        'key_hash': key.key_hash,
        'owner': {'user_id': owner.id, 'user_name': owner.user_id, 'display_name': owner.user_name or owner.user_id,
                  'roles': sorted(owner.role_names)},
        'enabled': bool(key.enabled) and bool(owner.enabled) and key.revoked_at is None,
        'expires_at': _iso(key.expires_at), 'revoked_at': _iso(key.revoked_at),
        'tool_access_mode': key.tool_access_mode or 'all', 'tool_access_list': _tools(key.tool_access_list),
        'persistent': bool(key.persistent),
    }


def body_of_file_record(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The record body of a persistent-file record (sajha/auth/persistent_keys.py) with an owner. A record
    may hold the raw ``key`` (plain credential storage, the administrators' file) or its ``sha256``; only
    the hash is published. Test admin records are never published: a host honours the test admin key only
    from its OWN keys file while its own switch is on, so publishing it would bypass that switch."""
    if not rec.get('owner') or not rec.get('id') or rec.get('test_admin'):
        return None
    from sajha.auth.persistent_keys import record_hash
    kh = record_hash(rec)
    if not kh:
        return None
    return {
        'key_id': str(rec['id']), 'key_prefix': str(rec.get('prefix') or '')[:16], 'name': str(rec.get('name') or '')[:255],
        'key_hash': str(kh).lower(),
        'owner': {'user_id': str(rec['owner']), 'user_name': str(rec['owner']),
                  'display_name': str(rec.get('owner_name') or rec['owner']),
                  'roles': sorted(str(r) for r in rec.get('roles') or [])},
        'enabled': bool(rec.get('enabled')) and not rec.get('revoked_at'),
        'expires_at': rec.get('expires_at') or None, 'revoked_at': rec.get('revoked_at') or None,
        'tool_access_mode': str(rec.get('tool_access_mode') or 'all'),
        'tool_access_list': _tools(rec.get('tool_access_list') or []), 'persistent': True,
    }


def own_keys(db_factory: Optional[Callable[[], Any]] = None, persistent: Optional[Callable[[], List[Dict[str, Any]]]] = None
             ) -> List[Dict[str, Any]]:
    """Every key this instance issued that may cross the net: owned keys in the database (revoked
    ones included, as tombstones), then persistent-file keys the database does not hold."""
    out: Dict[str, Dict[str, Any]] = {}
    db = None
    try:
        if db_factory is None:
            from sajha.db.engine import get_db_session
            db_factory = get_db_session
        db = db_factory()
        if db is not None:
            from sajha.db.models import ApiKey
            for key in db.query(ApiKey).filter(ApiKey.owner_id.isnot(None)).all():
                owner = key.owner
                if owner is None:
                    continue
                out[key.id] = body_of_key(key, owner)
    except Exception as e:
        logger.warning(f'SAJHA Net: own API keys not read from the database: {e}')
        raise
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    try:
        if persistent is None:
            from sajha.auth.persistent_keys import get_persistent_keys
            persistent = get_persistent_keys().records
        for rec in persistent() or []:
            b = body_of_file_record(rec)
            if b is not None and b['key_id'] not in out:
                out[b['key_id']] = b
    except Exception as e:
        logger.debug(f'SAJHA Net: persistent keys not read: {e}')
    return list(out.values())
