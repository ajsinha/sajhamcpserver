"""
Database state store (``state.backend: database``, and the durable task store).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Uses SAJHA's SQLAlchemy engine (``db.*``: SQLite or PostgreSQL) unless
``state.database.url`` names another database.  Two tables, created on first
use (they are not part of ``db/scripts``):

    sajha_state         k (PK), v (JSON text), ver (optimistic version), expires_at
    sajha_state_events  id (autoincrement), channel, payload, created_at

Atomic updates are optimistic: read (v, ver), compute, ``UPDATE ... WHERE
ver = :ver``; a lost race retries.  This is portable across SQLite (one host,
several processes) and PostgreSQL (several hosts) without table locks.

Pub/sub is a polled event table: ``publish`` inserts a row; one thread per
process reads rows newer than the last one it saw every
``state.database.poll_interval_ms`` and dispatches them; rows older than a
minute are deleted.  Latency is therefore one poll interval - fine for
list-changed notifications and task cancels, not a message bus.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text, and_, delete, func, insert,
                        or_, select, update)
from sqlalchemy.exc import IntegrityError

from sajha.core.state.base import MessageHandler, StateStore, dumps, loads

logger = logging.getLogger(__name__)

_meta = MetaData()
STATE_TABLE = Table(
    "sajha_state", _meta,
    Column("k", String(512), primary_key=True),
    Column("v", Text, nullable=False),
    Column("ver", Integer, nullable=False, default=0),
    Column("expires_at", Float, nullable=True, index=True),
)
EVENTS_TABLE = Table(
    "sajha_state_events", _meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("channel", String(200), nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", Float, nullable=False),
)

_EVENT_RETENTION_SECONDS = 60
_RETRIES = 200


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DatabaseStateStore(StateStore):
    backend = "database"
    shared = True

    def __init__(self, engine=None, prefix: str = "sajha:", poll_interval: float = 0.5, url: str = ""):
        super().__init__(prefix)
        self._engine = engine
        self._url = url
        self.poll_interval = max(0.05, poll_interval)
        self._ready = False
        self._init_lock = threading.Lock()
        self._handlers: Dict[str, List[MessageHandler]] = {}
        self._hlock = threading.Lock()
        self._poller: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_sweep = 0.0

    # -- engine ------------------------------------------------------------

    @property
    def engine(self):
        if self._engine is None:
            if self._url:
                from sqlalchemy import create_engine
                kwargs = {"connect_args": {"check_same_thread": False}} if self._url.startswith("sqlite") else \
                    {"pool_pre_ping": True}
                self._engine = create_engine(self._url, **kwargs)
            else:
                from sajha.db.engine import get_engine
                self._engine = get_engine()
        if not self._ready:
            with self._init_lock:
                if not self._ready:
                    _meta.create_all(self._engine, checkfirst=True)
                    self._ready = True
        return self._engine

    def _sweep(self) -> None:
        now = time.time()
        if now - self._last_sweep < 30:
            return
        self._last_sweep = now
        try:
            with self.engine.begin() as c:
                c.execute(delete(STATE_TABLE).where(and_(STATE_TABLE.c.expires_at.is_not(None),
                                                         STATE_TABLE.c.expires_at <= now)))
        except Exception as e:
            logger.debug(f"state sweep skipped: {e}")

    @staticmethod
    def _exp(ttl: Optional[float]) -> Optional[float]:
        return time.time() + ttl if ttl is not None else None

    def _row(self, conn, full: str):
        row = conn.execute(select(STATE_TABLE.c.v, STATE_TABLE.c.ver, STATE_TABLE.c.expires_at)
                           .where(STATE_TABLE.c.k == full)).first()
        if row is not None and row.expires_at is not None and row.expires_at <= time.time():
            return row, True
        return row, False

    # -- key/value -----------------------------------------------------------

    def get(self, key: str) -> Any:
        with self.engine.connect() as c:
            row, expired = self._row(c, self.k(key))
        return None if row is None or expired else loads(row.v)

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self.update(key, lambda _cur: value, ttl=ttl if ttl is not None else -1)

    def add(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        stored = []

        def fn(cur):
            if cur is not None:
                stored.clear()
                return cur
            stored.append(True)
            return value
        self.update(key, fn, ttl=None, _ttl_if_created=ttl)
        return bool(stored)

    def pop(self, key: str) -> Any:
        box = []

        def fn(cur):
            box[:] = [cur]
            return None
        self.update(key, fn)
        return box[0] if box else None

    def delete(self, key: str) -> bool:
        with self.engine.begin() as c:
            row, expired = self._row(c, self.k(key))
            res = c.execute(delete(STATE_TABLE).where(STATE_TABLE.c.k == self.k(key)))
        return bool(res.rowcount) and not expired

    def update(self, key: str, fn: Callable[[Any], Any], ttl: Optional[float] = None,
               _ttl_if_created: Optional[float] = None) -> Any:
        """``ttl=-1`` (internal) means "no expiry" for set()."""
        full = self.k(key)
        self._sweep()
        for attempt in range(_RETRIES):
            with self.engine.begin() as c:
                row, expired = self._row(c, full)
                current = None if row is None or expired else loads(row.v)
                new = fn(current)
                if ttl == -1:
                    expires = None
                elif ttl is not None:
                    expires = self._exp(ttl)
                elif current is None:
                    expires = self._exp(_ttl_if_created)
                else:
                    expires = row.expires_at
                if row is None:
                    if new is None:
                        return None
                    created = True
                else:
                    created = False
                    if new is None:
                        res = c.execute(delete(STATE_TABLE).where(and_(STATE_TABLE.c.k == full,
                                                                       STATE_TABLE.c.ver == row.ver)))
                    else:
                        res = c.execute(update(STATE_TABLE)
                                        .where(and_(STATE_TABLE.c.k == full, STATE_TABLE.c.ver == row.ver))
                                        .values(v=dumps(new), ver=row.ver + 1, expires_at=expires))
                    if res.rowcount == 1:
                        return loads(dumps(new)) if new is not None else None
            if created:
                try:
                    with self.engine.begin() as c:
                        c.execute(insert(STATE_TABLE).values(k=full, v=dumps(new), ver=1, expires_at=expires))
                    return loads(dumps(new))
                except IntegrityError:
                    pass                               # someone inserted first: retry
            time.sleep(min(0.001 * (attempt + 1), 0.02))
        raise RuntimeError(f"state update of {key!r} kept conflicting; gave up")

    def incr(self, key: str, amount: float = 1, ttl: Optional[float] = None) -> float:
        return self.update(key, lambda cur: (cur or 0) + amount, _ttl_if_created=ttl)

    def scan(self, prefix: str) -> Iterator[Tuple[str, Any]]:
        full = _escape_like(self.k(prefix)) + "%"
        now = time.time()
        with self.engine.connect() as c:
            rows = c.execute(select(STATE_TABLE.c.k, STATE_TABLE.c.v)
                             .where(and_(STATE_TABLE.c.k.like(full, escape="\\"),
                                         or_(STATE_TABLE.c.expires_at.is_(None),
                                             STATE_TABLE.c.expires_at > now)))).all()
        cut = len(self.prefix)
        for k, v in rows:
            yield k[cut:], loads(v)

    def delete_prefix(self, prefix: str) -> int:
        full = _escape_like(self.k(prefix)) + "%"
        with self.engine.begin() as c:
            return c.execute(delete(STATE_TABLE).where(STATE_TABLE.c.k.like(full, escape="\\"))).rowcount or 0

    def count(self, prefix: str) -> Optional[int]:
        full = _escape_like(self.k(prefix)) + "%"
        now = time.time()
        with self.engine.connect() as c:
            return int(c.execute(select(func.count()).select_from(STATE_TABLE)
                                 .where(and_(STATE_TABLE.c.k.like(full, escape="\\"),
                                             or_(STATE_TABLE.c.expires_at.is_(None),
                                                 STATE_TABLE.c.expires_at > now)))).scalar() or 0)

    # -- windows (a JSON list of timestamps under the key) --------------------

    def window_add(self, key: str, window: float, limit: Optional[int] = None) -> Tuple[bool, int]:
        out = [False, 0]

        def fn(cur):
            now = time.time()
            hits = [t for t in (cur or []) if t > now - window]
            if limit is not None and len(hits) >= limit:
                out[:] = [False, len(hits)]
                return hits or None
            hits.append(now)
            out[:] = [True, len(hits)]
            return hits
        self.update(key, fn, ttl=window)
        return out[0], out[1]

    def window_count(self, key: str, window: float) -> int:
        now = time.time()
        return len([t for t in (self.get(key) or []) if t > now - window])

    # -- pub/sub -------------------------------------------------------------

    def publish(self, channel: str, message: Dict[str, Any]) -> None:
        with self.engine.begin() as c:
            c.execute(insert(EVENTS_TABLE).values(channel=self.prefix + channel, payload=dumps(message),
                                                  created_at=time.time()))

    def subscribe(self, channel: str, handler: MessageHandler) -> Callable[[], None]:
        with self._hlock:
            self._handlers.setdefault(channel, []).append(handler)
            if self._poller is None:
                with self.engine.connect() as c:
                    last = c.execute(select(func.max(EVENTS_TABLE.c.id))).scalar() or 0
                self._poller = threading.Thread(target=self._poll, args=(last,),
                                                name="sajha-state-db-events", daemon=True)
                self._poller.start()

        def unsubscribe() -> None:
            with self._hlock:
                lst = self._handlers.get(channel, [])
                if handler in lst:
                    lst.remove(handler)
        return unsubscribe

    def _poll(self, last_id: int) -> None:
        cut = len(self.prefix)
        last_clean = 0.0
        while not self._stop.wait(self.poll_interval):
            try:
                with self.engine.connect() as c:
                    rows = c.execute(select(EVENTS_TABLE.c.id, EVENTS_TABLE.c.channel, EVENTS_TABLE.c.payload)
                                     .where(EVENTS_TABLE.c.id > last_id).order_by(EVENTS_TABLE.c.id)).all()
                for rid, chan, payload in rows:
                    last_id = max(last_id, rid)
                    if not chan.startswith(self.prefix):
                        continue
                    with self._hlock:
                        handlers = list(self._handlers.get(chan[cut:], ()))
                    for h in handlers:
                        try:
                            h(loads(payload))
                        except Exception as e:
                            logger.warning(f"state handler on {chan} failed: {e}")
                now = time.time()
                if now - last_clean > 30:
                    last_clean = now
                    with self.engine.begin() as c:
                        c.execute(delete(EVENTS_TABLE).where(
                            EVENTS_TABLE.c.created_at < now - _EVENT_RETENTION_SECONDS))
            except Exception as e:
                logger.warning(f"state event poll failed: {e}")

    # -- lifecycle -----------------------------------------------------------

    def ping(self) -> bool:
        try:
            with self.engine.connect() as c:
                c.execute(select(1))
            return True
        except Exception:
            return False

    def describe(self) -> Dict[str, Any]:
        d = super().describe()
        try:
            d["dialect"] = self.engine.dialect.name
        except Exception as e:
            d["dialect"] = f"unavailable: {e}"
        d["poll_interval_ms"] = int(self.poll_interval * 1000)
        return d

    def close(self) -> None:
        self._stop.set()
