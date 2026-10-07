"""
SAJHA MCP Server — the tamper-evident audit chain.

Every audit record is a JSON object whose canonical form (sorted keys, no whitespace,
UTF-8) is hashed with SHA-256; the record carries the previous record's hash in ``prev``,
so each hash commits to the whole chain before it. Each process is the only writer of its
own chain (``chain_id`` = host, pid, start time): appends are ordered by an in-process
lock and need no cross-process coordination, and verification checks each chain on its
own. Every ``audit.chain.anchor_every`` records, every ``anchor_interval_seconds`` and at
close, the head of the chain is signed (RS256) with the server key (the built-in OAuth
signing key, whose public half is at /oauth/jwks) and stored in ``audit_anchors`` and in the
chain itself.

Tables (defined here; DDL in db/scripts/<dialect>/schema.sql; created here only on SQLite):
``audit_chain`` and ``audit_anchors``. Design: docs/architecture/Policy and Audit.md, section 7.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import socket
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, MetaData, String, Table, Text

logger = logging.getLogger(__name__)

GENESIS = '0' * 64
VERSION = 1

metadata = MetaData()

audit_chain = Table(
    'audit_chain', metadata,
    Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True),
    Column('chain_id', String(100), nullable=False),
    Column('seq', BigInteger, nullable=False),
    Column('ts', DateTime, nullable=False),
    Column('event', String(100), nullable=False),
    Column('actor', String(200)),
    Column('resource', String(300)),
    Column('outcome', String(40)),
    Column('record_json', Text, nullable=False),
    Column('prev_hash', String(64), nullable=False),
    Column('hash', String(64), nullable=False),
    Index('ux_audit_chain_chain_seq', 'chain_id', 'seq', unique=True),
    Index('ix_audit_chain_ts', 'ts'),
    Index('ix_audit_chain_event', 'event'),
)

audit_anchors = Table(
    'audit_anchors', metadata,
    Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True),
    Column('chain_id', String(100), nullable=False),
    Column('seq', BigInteger, nullable=False),
    Column('hash', String(64), nullable=False),
    Column('ts', DateTime, nullable=False),
    Column('kid', String(100)),
    Column('alg', String(20), nullable=False),
    Column('payload_json', Text, nullable=False),
    Column('signature', Text, nullable=False),
    Index('ix_audit_anchors_chain_seq', 'chain_id', 'seq'),
)

RECORDS = None   # the metric families, set on first use (avoids importing metrics at import time)


def _metrics():
    global RECORDS
    if RECORDS is None:
        from sajha.observability import metrics as m
        try:
            RECORDS = m.Counter(m.REGISTRY, 'sajha_audit_records_total', 'Audit records appended to the hash chain.')
        except Exception:      # registered already (module reloaded)
            RECORDS = m.REGISTRY._families.get('sajha_audit_records_total')
    return RECORDS


# ── canonical form and hashing ──────────────────────────────────────

def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _ts(dt: Optional[datetime] = None) -> str:
    dt = (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def parse_ts(s: str) -> datetime:
    return datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)


def _clip(v: Any, n: int) -> Optional[str]:
    if v is None or v == '':
        return None
    s = str(v)
    return s[:n]


def row_for(record: Dict[str, Any], h: str) -> Dict[str, Any]:
    """The audit_chain row for a record (the query columns are copies of the record)."""
    actor = record.get('actor') or {}
    res = record.get('resource') or {}
    resource = None
    if res.get('type') or res.get('id'):
        resource = f"{res.get('type') or ''}:{res.get('id') or ''}"
    return {'chain_id': record['chain'], 'seq': record['seq'], 'ts': parse_ts(record['ts']),
            'event': str(record['event'])[:100], 'actor': _clip(actor.get('user'), 200),
            'resource': _clip(resource, 300), 'outcome': _clip(record.get('outcome'), 40),
            'record_json': canonical(record), 'prev_hash': record['prev'], 'hash': h}


# ── signing ─────────────────────────────────────────────────────────

class Signer:
    """RS256 with the built-in OAuth signing key (sajha/auth/oauth/keys.py)."""

    alg = 'RS256'

    def __init__(self, private_pem: Optional[bytes] = None, kid: Optional[str] = None):
        if private_pem is None:
            from sajha.auth.oauth.keys import get_signing_key
            sk = get_signing_key()
            private_pem, kid = sk.private_pem, sk.kid
        from cryptography.hazmat.primitives import serialization
        self._key = serialization.load_pem_private_key(private_pem, password=None)
        self.kid = kid or ''

    def sign(self, data: bytes) -> str:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        sig = self._key.sign(data, padding.PKCS1v15(), hashes.SHA256())
        return base64.urlsafe_b64encode(sig).rstrip(b'=').decode('ascii')

    def public_key(self):
        return self._key.public_key()


def verify_signature(public_key, data: bytes, signature: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    try:
        raw = base64.urlsafe_b64decode(signature + '=' * (-len(signature) % 4))
        public_key.verify(raw, data, padding.PKCS1v15(), hashes.SHA256())
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ── settings ────────────────────────────────────────────────────────

def _cfg(key: str, default: str = '') -> str:
    from sajha.core.config import _get
    return _get(key, default)


def chain_enabled() -> bool:
    from sajha.core.config import _bool
    return _bool('audit.chain.enabled', True)


def _cfg_int(key: str, default: int) -> int:
    try:
        return int(float(_cfg(key, '') or default))
    except (TypeError, ValueError):
        return default


def new_chain_id() -> str:
    host = (socket.gethostname() or 'host').split('.')[0][:40]
    return f'{host}-{os.getpid()}-{int(time.time() * 1000):x}'


# ── the writer ──────────────────────────────────────────────────────

class ChainWriter:
    """The single writer of one chain.

    ``append`` hashes the record under a lock (so ``seq`` and ``prev`` are always
    consistent), then inserts every row not yet stored; a failed insert keeps the rows and
    retries on the next append, so a transient database error does not leave a gap.
    ``engine`` None means SAJHA's database (sajha.db.engine.get_engine), resolved per flush.
    """

    def __init__(self, engine=None, chain_id: Optional[str] = None, anchor_every: Optional[int] = None,
                 anchor_interval: Optional[float] = None, signer: Optional[Signer] = None,
                 store: Optional[bool] = None, on_record=None, max_pending: int = 50000):
        self._engine = engine
        self.chain_id = chain_id or new_chain_id()
        self.anchor_every = max(1, anchor_every if anchor_every is not None else _cfg_int('audit.chain.anchor_every', 100))
        self.anchor_interval = (anchor_interval if anchor_interval is not None
                                else float(_cfg_int('audit.chain.anchor_interval_seconds', 300)))
        self._signer = signer
        self.store = chain_enabled() if store is None else store
        self.on_record = on_record                 # callback(exported record) -> SIEM sinks
        self._lock = threading.RLock()
        self._flush_lock = threading.Lock()
        self._seq = -1
        self._head = GENESIS
        self._pending: Deque[Dict[str, Any]] = deque()
        self._pending_anchors: Deque[Dict[str, Any]] = deque()
        self._max_pending = max_pending
        self.dropped = 0
        self.last_anchor_seq = -1
        self._last_news_seq = -1
        self.last_error = ''
        self.closed = False
        self._table_ready_for = None
        self._timer: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # deferred appends (tool calls): hashed now, stored by a background flusher every
        # flush_interval seconds or as soon as flush_batch rows are pending
        self.flush_interval = max(0.01, _cfg_int('audit.chain.flush_interval_ms', 200) / 1000.0)
        self.flush_batch = max(1, _cfg_int('audit.chain.flush_batch', 200))
        self._flusher: Optional[threading.Thread] = None
        self._wake = threading.Event()

    # -- state ------------------------------------------------------

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def head(self) -> str:
        return self._head

    def status(self) -> Dict[str, Any]:
        return {'chain_id': self.chain_id, 'seq': self._seq, 'head': self._head, 'pending': len(self._pending),
                'last_anchor_seq': self.last_anchor_seq, 'stored': self.store, 'dropped': self.dropped,
                'last_error': self.last_error, 'closed': self.closed}

    def engine(self):
        if self._engine is not None:
            return self._engine
        from sajha.db.engine import get_engine
        return get_engine()

    # -- append -----------------------------------------------------

    def _build(self, event: str, actor=None, resource=None, outcome=None, details=None) -> Dict[str, Any]:
        """Hash the next record (the caller holds ``_lock``); queue its row; return the exported form."""
        rec = {'v': VERSION, 'chain': self.chain_id, 'seq': self._seq + 1, 'ts': _ts(),
               'prev': self._head, 'event': str(event)[:100],
               'actor': _clean_actor(actor), 'resource': _clean_resource(resource),
               'outcome': None if outcome is None else str(outcome)[:40],
               'details': details if details not in ('', None) else None}
        text = canonical(rec)
        h = digest(text)
        self._seq, self._head = rec['seq'], h
        if event != 'audit.anchor':
            self._last_news_seq = rec['seq']
        if self.store:
            if len(self._pending) >= self._max_pending:
                self._pending.popleft()
                self.dropped += 1
            self._pending.append(row_for(rec, h))
        return dict(json.loads(text), hash=h)

    def _open_details(self) -> Dict[str, Any]:
        try:
            from sajha.core.config import get_settings
            version = get_settings().app_version
        except Exception:
            version = ''
        return {'host': socket.gethostname(), 'pid': os.getpid(), 'version': version}

    def _after(self, outs: List[Dict[str, Any]], defer: bool = False) -> None:
        """Outside ``_lock``: count, store (now, or by the flusher when ``defer``), export."""
        try:
            _metrics().inc((), len(outs))
        except Exception:
            pass
        if self.store:
            if defer:
                self._ensure_flusher()
                if len(self._pending) >= self.flush_batch:
                    self._wake.set()
            else:
                self.flush()
        if self.on_record is not None:
            for out in outs:
                try:
                    self.on_record(out)
                except Exception as e:
                    logger.debug(f'audit export: {e}')

    def append(self, event: str, actor: Optional[Dict[str, Any]] = None, resource: Optional[Dict[str, Any]] = None,
               outcome: Optional[str] = None, details: Any = None, defer: bool = False) -> Dict[str, Any]:
        """Hash and store one record; returns it with its ``hash`` (the exported form).

        ``defer``: the record is hashed into the chain now (its place and hash are final) but
        stored by the background flusher, so the caller does not wait for the database
        (tool-call records, docs/architecture/Policy and Audit.md section 13)."""
        outs = []
        with self._lock:
            if self._seq < 0:
                outs.append(self._build('chain.open', actor={'user': 'system'}, details=self._open_details()))
            outs.append(self._build(event, actor, resource, outcome, details))
        self._after(outs, defer)
        if self._seq - max(self.last_anchor_seq, 0) >= self.anchor_every:
            self.anchor(defer=defer)
        self._ensure_timer()
        return outs[-1]

    # -- storage ----------------------------------------------------

    def _ensure_tables(self, engine) -> bool:
        if self._table_ready_for is engine:
            return True
        if engine.dialect.name == 'sqlite':
            metadata.create_all(engine, checkfirst=True)
        else:
            from sqlalchemy import inspect
            insp = inspect(engine)
            if not (insp.has_table('audit_chain') and insp.has_table('audit_anchors')):
                if self.last_error != 'tables missing':
                    from sajha.db.schema import apply_command
                    logger.warning('Audit chain not stored: tables audit_chain/audit_anchors are missing; create '
                                   f'them from the schema file:  {apply_command(engine)}')
                self.last_error = 'tables missing'
                return False
        self._table_ready_for = engine
        return True

    def flush(self) -> bool:
        """Insert every pending row and anchor; True when nothing is left pending. Never call with ``_lock`` held."""
        if not self.store:
            return True
        with self._flush_lock:
            with self._lock:
                rows = list(self._pending)
                anchors = list(self._pending_anchors)
            if not rows and not anchors:
                return True
            try:
                engine = self.engine()
                if not self._ensure_tables(engine):
                    return False
            except Exception as e:
                self.last_error = f'no database: {e}'
                return False
            try:
                with engine.begin() as conn:
                    if rows:
                        conn.execute(audit_chain.insert(), rows)
                    if anchors:
                        conn.execute(audit_anchors.insert(), anchors)
            except Exception as e:
                if self.last_error != str(e):
                    logger.warning(f'Audit chain write failed (kept {len(rows)} record(s) to retry): {e}')
                self.last_error = str(e)
                return False
            with self._lock:
                for _ in rows:
                    self._pending.popleft()
                for _ in anchors:
                    self._pending_anchors.popleft()
            self.last_error = ''
            return True

    # -- anchors ----------------------------------------------------

    def signer(self) -> Signer:
        if self._signer is None:
            self._signer = Signer()
        return self._signer

    def anchor(self, defer: bool = False) -> Optional[Dict[str, Any]]:
        """Sign the current head; None when nothing but anchors was appended since the last anchor."""
        with self._lock:
            if self._seq < 0 or self._last_news_seq <= self.last_anchor_seq:
                return None
            try:
                signer = self.signer()
            except Exception as e:
                self.last_error = f'cannot sign anchors: {e}'
                logger.warning(f'Audit anchor skipped: {e}')
                return None
            payload = {'chain': self.chain_id, 'seq': self._seq, 'hash': self._head, 'ts': _ts(),
                       'kid': signer.kid, 'alg': signer.alg}
            text = canonical(payload)
            sig = signer.sign(text.encode('utf-8'))
            self.last_anchor_seq = self._seq
            if self.store:
                self._pending_anchors.append({'chain_id': self.chain_id, 'seq': payload['seq'],
                                              'hash': payload['hash'], 'ts': parse_ts(payload['ts']),
                                              'kid': signer.kid, 'alg': signer.alg, 'payload_json': text,
                                              'signature': sig})
            out = self._build('audit.anchor', actor={'user': 'system'},
                              details={'anchored_seq': payload['seq'], 'anchored_hash': payload['hash'],
                                       'payload': text, 'signature': sig, 'kid': signer.kid, 'alg': signer.alg})
        self._after([out], defer)
        return {'payload': payload, 'signature': sig}

    def _ensure_timer(self) -> None:
        if self.anchor_interval <= 0 or self.closed or (self._timer is not None and self._timer.is_alive()):
            return
        with self._lock:
            if self._timer is not None and self._timer.is_alive():
                return

            def loop():
                while not self._stop.wait(self.anchor_interval):
                    try:
                        if self.store:
                            self.flush()
                        self.anchor()
                    except Exception as e:
                        logger.debug(f'audit anchor timer: {e}')

            self._timer = threading.Thread(target=loop, name='sajha-audit-anchor', daemon=True)
            self._timer.start()

    def _ensure_flusher(self) -> None:
        if self.closed or (self._flusher is not None and self._flusher.is_alive()):
            return
        with self._lock:
            if self._flusher is not None and self._flusher.is_alive():
                return

            def loop():
                while not self._stop.is_set():
                    self._wake.wait(self.flush_interval)
                    self._wake.clear()
                    try:
                        self.flush()
                    except Exception as e:
                        logger.debug(f'audit flusher: {e}')

            self._flusher = threading.Thread(target=loop, name='sajha-audit-flush', daemon=True)
            self._flusher.start()

    def close(self) -> None:
        """Append ``chain.close``, anchor it and flush (a clean shutdown)."""
        if self.closed:
            return
        self._stop.set()
        self._wake.set()
        if self._seq >= 0:
            with self._lock:
                out = self._build('chain.close', actor={'user': 'system'}, details={'records': self._seq + 1})
            self._after([out])
            self.anchor()
        self.closed = True
        self.flush()


def _clean_actor(actor: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not actor:
        return None
    out = {}
    for k in ('user', 'api_key', 'roles', 'auth', 'ip'):
        v = actor.get(k)
        if v not in (None, '', [], ()):
            out[k] = list(v) if isinstance(v, (list, tuple)) else str(v)[:200]
    return out or None


def _clean_resource(resource: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not resource:
        return None
    out = {k: str(resource[k])[:255] for k in ('type', 'id') if resource.get(k) not in (None, '')}
    return out or None


# ── reading ─────────────────────────────────────────────────────────

def recent(engine, limit: int = 100, event: Optional[str] = None, actor: Optional[str] = None,
           chain_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The newest records across every chain (merged by time), as exported dicts."""
    from sqlalchemy import select
    q = select(audit_chain.c.record_json, audit_chain.c.hash).order_by(audit_chain.c.ts.desc(),
                                                                       audit_chain.c.seq.desc())
    if event:
        q = q.where(audit_chain.c.event.like(event.replace('*', '%')))
    if actor:
        q = q.where(audit_chain.c.actor == actor)
    if chain_id:
        q = q.where(audit_chain.c.chain_id == chain_id)
    with engine.connect() as conn:
        rows = conn.execute(q.limit(max(1, min(int(limit), 5000)))).fetchall()
    out = []
    for text, h in rows:
        try:
            out.append(dict(json.loads(text), hash=h))
        except ValueError:
            out.append({'hash': h, 'error': 'record_json is not JSON'})
    return out
