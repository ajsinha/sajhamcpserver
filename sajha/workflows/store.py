"""
SAJHA MCP Server — durable workflow storage: definitions, runs and per-step records.

Three tables, defined here with SQLAlchemy Core and created by the schema files
(db/scripts/<dialect>/schema.sql). SQLite creates them at start-up (and here, for a
store pointed at a fresh SQLite database); on PostgreSQL SAJHA never runs DDL, it only
checks that they exist. Times are epoch seconds (DOUBLE PRECISION / REAL) so every
comparison (heartbeats, wake-up times) is the same arithmetic on both dialects.

Claiming a run (resume after a crash, start a queued run) is a conditional UPDATE: the
row changes only if it still has the status and worker the claimer saw, so exactly one
worker wins.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import (BigInteger, Boolean, Column, Float, ForeignKey, Index, Integer, MetaData, String, Table,
                        Text, and_, delete, func, insert, select, update)
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

metadata = MetaData()

workflows = Table(
    'workflows', metadata,
    Column('name', String(100), primary_key=True),
    Column('description', Text),
    Column('definition_json', Text, nullable=False),
    Column('owner', String(200), nullable=False),
    Column('enabled', Boolean, nullable=False, default=True),
    Column('published', Boolean, nullable=False, default=False),
    Column('version', Integer, nullable=False, default=1),
    Column('created_at', Float, nullable=False),
    Column('updated_at', Float, nullable=False),
    Column('updated_by', String(200)),
)

workflow_runs = Table(
    'workflow_runs', metadata,
    Column('id', String(36), primary_key=True),
    Column('workflow', String(100), nullable=False),
    Column('version', Integer, nullable=False),
    Column('status', String(20), nullable=False),
    Column('trigger_type', String(20), nullable=False),
    Column('trigger_id', String(100)),
    Column('trigger_detail', Text),
    Column('run_as', String(200), nullable=False),
    Column('started_by', String(200)),
    Column('input_json', Text),
    Column('output_json', Text),
    Column('error', Text),
    Column('idempotency_key', String(200)),
    Column('parent_run_id', String(36)),
    Column('from_step', String(100)),
    Column('worker_id', String(200)),
    Column('cancel_requested', Boolean, nullable=False, default=False),
    Column('delivery_status', String(200)),
    Column('definition_json', Text, nullable=False),
    Column('created_at', Float, nullable=False),
    Column('started_at', Float),
    Column('finished_at', Float),
    Column('heartbeat_at', Float),
    Index('ix_workflow_runs_workflow_created', 'workflow', 'created_at'),
    Index('ix_workflow_runs_status', 'status'),
    Index('ux_workflow_runs_idempotency', 'workflow', 'idempotency_key', unique=True),
)

workflow_run_steps = Table(
    'workflow_run_steps', metadata,
    Column('id', BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True),
    Column('run_id', String(36), ForeignKey('workflow_runs.id', ondelete='CASCADE'), nullable=False),
    Column('step_id', String(100), nullable=False),
    Column('kind', String(20), nullable=False),
    Column('status', String(20), nullable=False),
    Column('attempts', Integer, nullable=False, default=0),
    Column('input_json', Text),
    Column('output_json', Text),
    Column('error', Text),
    Column('idempotency_key', String(64)),
    Column('detail_json', Text),
    Column('started_at', Float),
    Column('finished_at', Float),
    Column('duration_ms', Float),
    Index('ux_workflow_run_steps_run_step', 'run_id', 'step_id', unique=True),
)

RUN_ACTIVE = ('queued', 'running', 'waiting')
RUN_DONE = ('succeeded', 'failed', 'cancelled')
STEP_DONE = ('succeeded', 'failed', 'skipped', 'cancelled')


class StoreUnavailable(RuntimeError):
    """The workflow tables are missing (PostgreSQL without the schema file applied)."""


def _dumps(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, default=str, ensure_ascii=False)


def _loads(v: Optional[str]) -> Any:
    if v is None or v == '':
        return None
    try:
        return json.loads(v)
    except ValueError:
        return v


def bounded(value: Any, limit: int) -> Any:
    """``value`` when its JSON fits ``limit`` characters, else a truncated preview marker."""
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) <= limit:
        return value
    return {'_truncated': True, 'chars': len(text), 'preview': text[:limit]}


class WorkflowStore:
    """Definitions, runs and steps, over SAJHA's database (or any SQLAlchemy engine)."""

    def __init__(self, engine=None):
        self._engine = engine
        self._ready_for = None

    @property
    def engine(self):
        if self._engine is None:
            from sajha.db.engine import get_engine
            return get_engine()
        return self._engine

    def ensure(self):
        eng = self.engine
        if self._ready_for is eng:
            return eng
        if eng.dialect.name == 'sqlite':
            metadata.create_all(eng, checkfirst=True)
        else:
            from sqlalchemy import inspect
            insp = inspect(eng)
            missing = [t for t in metadata.tables if not insp.has_table(t)]
            if missing:
                from sajha.db.schema import apply_command
                raise StoreUnavailable(f'workflow tables missing ({", ".join(missing)}); create them from the '
                                       f'schema file: {apply_command(eng)}')
        self._ready_for = eng
        return eng

    # ── definitions ───────────────────────────────────────────────

    @staticmethod
    def _wf(row) -> Dict[str, Any]:
        m = row._mapping
        return {'name': m['name'], 'description': m['description'] or '',
                'definition': _loads(m['definition_json']) or {}, 'owner': m['owner'],
                'enabled': bool(m['enabled']), 'published': bool(m['published']), 'version': m['version'],
                'created_at': m['created_at'], 'updated_at': m['updated_at'], 'updated_by': m['updated_by']}

    def list_workflows(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        q = select(workflows).order_by(workflows.c.name)
        if owner is not None:
            q = q.where(workflows.c.owner == owner)
        with self.ensure().connect() as c:
            return [self._wf(r) for r in c.execute(q)]

    def get_workflow(self, name: str) -> Optional[Dict[str, Any]]:
        with self.ensure().connect() as c:
            r = c.execute(select(workflows).where(workflows.c.name == name)).first()
        return self._wf(r) if r else None

    def save_workflow(self, defn: Dict[str, Any], owner: str, by: str, enabled: bool = True) -> Dict[str, Any]:
        now = time.time()
        name = defn['name']
        published = bool((defn.get('publish') or {}).get('enabled'))
        with self.ensure().begin() as c:
            cur = c.execute(select(workflows.c.version, workflows.c.owner, workflows.c.created_at)
                            .where(workflows.c.name == name)).first()
            if cur is None:
                c.execute(insert(workflows).values(
                    name=name, description=defn.get('description', ''), definition_json=_dumps(defn),
                    owner=owner, enabled=enabled, published=published, version=1, created_at=now, updated_at=now,
                    updated_by=by))
            else:
                c.execute(update(workflows).where(workflows.c.name == name).values(
                    description=defn.get('description', ''), definition_json=_dumps(defn), enabled=enabled,
                    published=published, version=cur.version + 1, updated_at=now, updated_by=by))
        return self.get_workflow(name)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        with self.ensure().begin() as c:
            return c.execute(update(workflows).where(workflows.c.name == name)
                             .values(enabled=enabled, updated_at=time.time())).rowcount == 1

    def delete_workflow(self, name: str) -> bool:
        with self.ensure().begin() as c:
            run_ids = [r.id for r in c.execute(select(workflow_runs.c.id).where(workflow_runs.c.workflow == name))]
            if run_ids:
                c.execute(delete(workflow_run_steps).where(workflow_run_steps.c.run_id.in_(run_ids)))
                c.execute(delete(workflow_runs).where(workflow_runs.c.workflow == name))
            return c.execute(delete(workflows).where(workflows.c.name == name)).rowcount == 1

    # ── runs ──────────────────────────────────────────────────────

    @staticmethod
    def _run(row) -> Dict[str, Any]:
        m = dict(row._mapping)
        for k in ('input_json', 'output_json', 'trigger_detail', 'definition_json'):
            m[k.replace('_json', '')] = _loads(m.pop(k))
        m['cancel_requested'] = bool(m['cancel_requested'])
        return m

    def create_run(self, *, workflow: str, version: int, definition: Dict[str, Any], run_as: str,
                   trigger_type: str, trigger_id: Optional[str] = None, trigger_detail: Any = None,
                   started_by: Optional[str] = None, input: Any = None, idempotency_key: Optional[str] = None,
                   parent_run_id: Optional[str] = None, from_step: Optional[str] = None,
                   status: str = 'queued') -> tuple:
        """``(run, created)``: a run with the same idempotency key is returned instead of a new one."""
        if idempotency_key:
            existing = self.get_run_by_key(workflow, idempotency_key)
            if existing:
                return existing, False
        rid = str(uuid.uuid4())
        try:
            with self.ensure().begin() as c:
                c.execute(insert(workflow_runs).values(
                    id=rid, workflow=workflow, version=version, status=status, trigger_type=trigger_type,
                    trigger_id=trigger_id, trigger_detail=_dumps(trigger_detail), run_as=run_as,
                    started_by=started_by, input_json=_dumps(input or {}), idempotency_key=idempotency_key or None,
                    parent_run_id=parent_run_id, from_step=from_step, cancel_requested=False,
                    definition_json=_dumps(definition), created_at=time.time()))
        except IntegrityError:
            existing = self.get_run_by_key(workflow, idempotency_key) if idempotency_key else None
            if existing:
                return existing, False
            raise
        return self.get_run(rid), True

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.ensure().connect() as c:
            r = c.execute(select(workflow_runs).where(workflow_runs.c.id == run_id)).first()
        return self._run(r) if r else None

    def get_run_by_key(self, workflow: str, key: str) -> Optional[Dict[str, Any]]:
        with self.ensure().connect() as c:
            r = c.execute(select(workflow_runs).where(and_(workflow_runs.c.workflow == workflow,
                                                           workflow_runs.c.idempotency_key == key))).first()
        return self._run(r) if r else None

    def list_runs(self, workflow: Optional[str] = None, status: Optional[str] = None, limit: int = 50,
                  workflows_in: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        q = select(workflow_runs).order_by(workflow_runs.c.created_at.desc()).limit(max(1, min(int(limit), 1000)))
        if workflow:
            q = q.where(workflow_runs.c.workflow == workflow)
        if workflows_in is not None:
            q = q.where(workflow_runs.c.workflow.in_(list(workflows_in)))
        if status:
            q = q.where(workflow_runs.c.status == status)
        with self.ensure().connect() as c:
            return [self._run(r) for r in c.execute(q)]

    def runs_with_status(self, statuses: Iterable[str]) -> List[Dict[str, Any]]:
        q = select(workflow_runs).where(workflow_runs.c.status.in_(list(statuses))) \
            .order_by(workflow_runs.c.created_at)
        with self.ensure().connect() as c:
            return [self._run(r) for r in c.execute(q)]

    def count_active(self, workflow: str, statuses=('running', 'waiting')) -> int:
        q = select(func.count()).select_from(workflow_runs).where(and_(
            workflow_runs.c.workflow == workflow, workflow_runs.c.status.in_(list(statuses))))
        with self.ensure().connect() as c:
            return int(c.execute(q).scalar() or 0)

    def update_run(self, run_id: str, **fields) -> None:
        vals = {}
        for k, v in fields.items():
            if k in ('input', 'output', 'trigger_detail'):
                vals[k + '_json' if k != 'trigger_detail' else k] = _dumps(v)
            else:
                vals[k] = v
        with self.ensure().begin() as c:
            c.execute(update(workflow_runs).where(workflow_runs.c.id == run_id).values(**vals))

    def claim_run(self, run_id: str, *, from_status: Iterable[str], to_status: str, worker_id: str,
                  expect_worker: Any = ..., expect_heartbeat: Any = ...) -> bool:
        """Atomically move a run to ``to_status`` owned by ``worker_id``; True for the one winner."""
        cond = [workflow_runs.c.id == run_id, workflow_runs.c.status.in_(list(from_status))]
        if expect_worker is not ...:
            cond.append(workflow_runs.c.worker_id.is_(None) if expect_worker is None
                        else workflow_runs.c.worker_id == expect_worker)
        if expect_heartbeat is not ...:
            cond.append(workflow_runs.c.heartbeat_at.is_(None) if expect_heartbeat is None
                        else workflow_runs.c.heartbeat_at == expect_heartbeat)
        now = time.time()
        vals = {'status': to_status, 'worker_id': worker_id, 'heartbeat_at': now}
        with self.ensure().begin() as c:
            return c.execute(update(workflow_runs).where(and_(*cond)).values(**vals)).rowcount == 1

    def finish_run(self, run_id: str, status: str, *, output: Any = None, error: Optional[str] = None) -> bool:
        """Set a terminal status unless the run is already terminal."""
        with self.ensure().begin() as c:
            return c.execute(update(workflow_runs).where(and_(
                workflow_runs.c.id == run_id, workflow_runs.c.status.in_(list(RUN_ACTIVE)))).values(
                status=status, output_json=_dumps(output), error=error, finished_at=time.time(),
                worker_id=None)).rowcount == 1

    def request_cancel(self, run_id: str) -> bool:
        with self.ensure().begin() as c:
            return c.execute(update(workflow_runs).where(and_(
                workflow_runs.c.id == run_id, workflow_runs.c.status.in_(list(RUN_ACTIVE))))
                .values(cancel_requested=True)).rowcount == 1

    def cancel_requested(self, run_id: str) -> bool:
        with self.ensure().connect() as c:
            v = c.execute(select(workflow_runs.c.cancel_requested, workflow_runs.c.status)
                          .where(workflow_runs.c.id == run_id)).first()
        return bool(v and (v.cancel_requested or v.status == 'cancelled'))

    def heartbeat(self, run_id: str, worker_id: str) -> bool:
        """Refresh the heartbeat; False when this worker no longer owns the run."""
        with self.ensure().begin() as c:
            return c.execute(update(workflow_runs).where(and_(
                workflow_runs.c.id == run_id, workflow_runs.c.worker_id == worker_id))
                .values(heartbeat_at=time.time())).rowcount == 1

    def prune_runs(self, older_than: float) -> int:
        with self.ensure().begin() as c:
            ids = [r.id for r in c.execute(select(workflow_runs.c.id).where(and_(
                workflow_runs.c.finished_at.is_not(None), workflow_runs.c.finished_at < older_than)))]
            if not ids:
                return 0
            c.execute(delete(workflow_run_steps).where(workflow_run_steps.c.run_id.in_(ids)))
            return c.execute(delete(workflow_runs).where(workflow_runs.c.id.in_(ids))).rowcount

    # ── steps ─────────────────────────────────────────────────────

    @staticmethod
    def _stp(row) -> Dict[str, Any]:
        m = dict(row._mapping)
        m.pop('id', None)
        for k in ('input_json', 'output_json', 'detail_json'):
            m[k.replace('_json', '')] = _loads(m.pop(k))
        return m

    def get_steps(self, run_id: str) -> List[Dict[str, Any]]:
        q = select(workflow_run_steps).where(workflow_run_steps.c.run_id == run_id) \
            .order_by(workflow_run_steps.c.id)
        with self.ensure().connect() as c:
            return [self._stp(r) for r in c.execute(q)]

    def put_step(self, run_id: str, step_id: str, kind: str, **fields) -> None:
        vals = {}
        for k, v in fields.items():
            vals[k + '_json' if k in ('input', 'output', 'detail') else k] = \
                _dumps(v) if k in ('input', 'output', 'detail') else v
        with self.ensure().begin() as c:
            n = c.execute(update(workflow_run_steps).where(and_(
                workflow_run_steps.c.run_id == run_id, workflow_run_steps.c.step_id == step_id))
                .values(**vals)).rowcount
            if n == 0:
                vals.setdefault('status', 'pending')
                vals.setdefault('attempts', 0)
                c.execute(insert(workflow_run_steps).values(run_id=run_id, step_id=step_id, kind=kind, **vals))
