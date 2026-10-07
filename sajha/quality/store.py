"""
SAJHA MCP Server — the ``quality_runs`` table: saved test-harness and eval runs.

One row per run (``kind`` test | eval); times are epoch seconds. SQLite creates the table on
first use; PostgreSQL gets it from ``db/scripts/postgresql/schema.sql`` (SAJHA runs no DDL
there). Docs: docs/architecture/Tool Quality.md §7.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, Float, Index, MetaData, String, Table, Text, delete, insert, select, update

logger = logging.getLogger(__name__)

metadata = MetaData()

quality_runs = Table(
    'quality_runs', metadata,
    Column('id', String(36), primary_key=True),
    Column('kind', String(10), nullable=False),            # test | eval
    Column('name', String(255), nullable=False),
    Column('status', String(16), nullable=False),          # running | done | failed
    Column('started_at', Float, nullable=False),
    Column('finished_at', Float),
    Column('created_by', String(200)),
    Column('summary_json', Text),
    Column('detail_json', Text),
    Index('ix_quality_runs_kind_started', 'kind', 'started_at'),
)


class StoreUnavailable(RuntimeError):
    """No database, or the table is missing on PostgreSQL."""


class RunStore:
    def __init__(self, engine=None):
        self._engine = engine
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
                if not inspect(eng).has_table('quality_runs'):
                    from sajha.db.schema import apply_command
                    raise StoreUnavailable('table quality_runs is missing; create it from the schema file: '
                                           f'{apply_command(eng)}')
            self._ready_for = eng
        return eng

    def start(self, kind: str, name: str, created_by: str = '', summary: Optional[Dict[str, Any]] = None) -> str:
        rid = str(uuid.uuid4())
        with self.ensure().begin() as c:
            c.execute(insert(quality_runs).values(id=rid, kind=kind, name=name[:255], status='running',
                                                  started_at=time.time(), created_by=(created_by or '')[:200],
                                                  summary_json=json.dumps(summary or {}, default=str)))
        return rid

    def finish(self, rid: str, summary: Dict[str, Any], detail: Any, status: str = 'done') -> None:
        with self.ensure().begin() as c:
            c.execute(update(quality_runs).where(quality_runs.c.id == rid).values(
                status=status, finished_at=time.time(), summary_json=json.dumps(summary, default=str),
                detail_json=json.dumps(detail, default=str)))

    def save(self, kind: str, name: str, summary: Dict[str, Any], detail: Any, created_by: str = '',
             started_at: Optional[float] = None, status: str = 'done') -> str:
        rid = str(uuid.uuid4())
        now = time.time()
        with self.ensure().begin() as c:
            c.execute(insert(quality_runs).values(
                id=rid, kind=kind, name=name[:255], status=status, started_at=started_at or now, finished_at=now,
                created_by=(created_by or '')[:200], summary_json=json.dumps(summary, default=str),
                detail_json=json.dumps(detail, default=str)))
        return rid

    @staticmethod
    def _row(r, with_detail: bool) -> Dict[str, Any]:
        m = r._mapping
        out = {'id': m['id'], 'kind': m['kind'], 'name': m['name'], 'status': m['status'],
               'started_at': m['started_at'], 'finished_at': m['finished_at'], 'created_by': m['created_by'],
               'summary': json.loads(m['summary_json'] or '{}')}
        if with_detail:
            out['detail'] = json.loads(m['detail_json'] or 'null')
        return out

    def list(self, kind: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        q = select(quality_runs.c.id, quality_runs.c.kind, quality_runs.c.name, quality_runs.c.status,
                   quality_runs.c.started_at, quality_runs.c.finished_at, quality_runs.c.created_by,
                   quality_runs.c.summary_json).order_by(quality_runs.c.started_at.desc()).limit(max(1, min(limit, 500)))
        if kind:
            q = q.where(quality_runs.c.kind == kind)
        with self.ensure().connect() as c:
            return [self._row(r, False) for r in c.execute(q)]

    def get(self, rid: str) -> Optional[Dict[str, Any]]:
        with self.ensure().connect() as c:
            r = c.execute(select(quality_runs).where(quality_runs.c.id == rid)).first()
        return self._row(r, True) if r else None

    def delete(self, rid: str) -> bool:
        with self.ensure().begin() as c:
            return c.execute(delete(quality_runs).where(quality_runs.c.id == rid)).rowcount > 0


_store: Optional[RunStore] = None


def get_run_store() -> RunStore:
    global _store
    if _store is None:
        _store = RunStore()
    return _store


def set_run_store(s: Optional[RunStore]) -> None:
    global _store
    _store = s
