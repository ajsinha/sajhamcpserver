"""
SAJHA MCP Server — the workflow service: definitions, runs, triggers and the scheduler.

One :class:`WorkflowService` per process. Its scheduler thread ticks every
``workflows.tick_seconds`` and, on every worker:

* fires due cron schedules: each slot is claimed with an atomic ``add`` in the state
  store (``wf:cron:<workflow>:<trigger>:<slot>``) and the run carries the slot as its
  idempotency key, so exactly one worker fires it even with many workers;
* polls file triggers (one worker per interval, through a state-store lock) on the
  storage backend (local disk, S3, Azure Blob or GCS listing);
* resumes runs whose worker died (status ``running`` with a stale heartbeat, taken over
  with a conditional UPDATE), wakes parked runs whose wait or approval is over, and
  starts queued runs when the workflow's concurrency limit allows.

Change-bus events fire ``event`` triggers on the worker that produced them; webhooks
arrive through ``POST /api/workflows/{name}/hooks/{trigger}`` (HMAC-signed).
Design: docs/architecture/Workflows.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.workflows import model
from sajha.workflows.model import WorkflowError
from sajha.workflows.store import RUN_ACTIVE, RUN_DONE, WorkflowStore

logger = logging.getLogger(__name__)


def _cfg(key: str, default):
    from sajha.core.config import _get
    raw = _get(key, '')
    if raw in ('', None):
        return default
    try:
        if isinstance(default, bool):
            return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


class WorkflowService:
    def __init__(self, tools_registry=None, store: Optional[WorkflowStore] = None, state=None,
                 worker_id: Optional[str] = None, storage: Optional[Callable[[], Any]] = None):
        from sajha.core.state import WORKER_ID
        self.registry = tools_registry
        self.store = store or WorkflowStore()
        self._state = state
        self.worker_id = worker_id or WORKER_ID
        self._storage = storage
        self.enabled = _cfg('workflows.enabled', True)
        self.tick_seconds = _cfg('workflows.tick_seconds', 5.0)
        self.max_runs = _cfg('workflows.max_concurrent_runs', 8)
        self.default_concurrency = _cfg('workflows.default_concurrency', 4)
        self.max_parallel = _cfg('workflows.max_parallel_steps', 4)
        self.loop_max_items = _cfg('workflows.loop_max_items', 100)
        self.loop_hard_max = _cfg('workflows.loop_hard_max_items', 10000)
        self.step_timeout = _cfg('workflows.step_timeout_seconds', 300.0)
        self.inline_wait_seconds = _cfg('workflows.inline_wait_seconds', 5.0)
        self.heartbeat_seconds = _cfg('workflows.heartbeat_seconds', 5.0)
        self.stale_seconds = _cfg('workflows.stale_seconds', 60.0)
        self.output_chars = _cfg('workflows.step_output_max_chars', 262144)
        self.input_chars = _cfg('workflows.step_input_max_chars', 16384)
        self.retention_days = _cfg('workflows.run_retention_days', 30.0)
        self._pool = cf.ThreadPoolExecutor(max_workers=max(1, self.max_runs), thread_name_prefix='wf-run')
        self._local: Dict[str, Any] = {}
        self._local_lock = threading.Lock()
        self._done = threading.Condition()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._listener = None
        self._published: Dict[str, str] = {}          # workflow -> tool name
        self._cron_seen: Dict[str, datetime] = {}      # trigger key -> last slot checked (this worker)
        self._last_prune = 0.0

    # ── plumbing ──────────────────────────────────────────────────

    @property
    def state(self):
        if self._state is not None:
            return self._state
        from sajha.core.state import get_state_store
        return get_state_store()

    def storage(self):
        if self._storage is not None:
            return self._storage()
        from sajha.core.storage import get_storage
        return get_storage()

    def get_tool(self, name: str):
        if self.registry is None:
            return None
        return self.registry.get_tool(name)

    def _audit(self, event: str, actor: str, wf: str, outcome: str = 'success', **details) -> None:
        try:
            from sajha import audit
            audit.record(event, actor={'user': actor}, resource={'type': 'workflow', 'name': wf},
                         outcome=outcome, details=details or None)
        except Exception as e:
            logger.debug(f'workflow audit: {e}')

    # ── definitions ───────────────────────────────────────────────

    def validate(self, raw: Any) -> Dict[str, Any]:
        if isinstance(raw, str):
            raw = model.parse_text(raw)
        return model.normalize(raw)

    def save(self, raw: Any, user_id: str, is_admin: bool = False, enabled: Optional[bool] = None) -> Dict[str, Any]:
        """Create or update a definition. The owner (run-as) is the creator; admins may edit any."""
        defn = self.validate(raw)
        existing = self.store.get_workflow(defn['name'])
        if existing and existing['owner'] != user_id and not is_admin:
            raise PermissionError('only the owner or an administrator may change this workflow')
        if (defn.get('publish') or {}).get('enabled') and not is_admin:
            raise PermissionError('only administrators may publish a workflow as a tool '
                                  '(callers would run its steps with the owner\'s rights)')
        old_triggers = {t['id']: t for t in (existing['definition'].get('triggers', []) if existing else [])}
        for t in defn['triggers']:
            if t['type'] != 'webhook' or t.get('secret_ref'):
                continue
            if t.get('secret') in (None, '********'):
                prev = old_triggers.get(t['id'], {}).get('secret')
                t['secret'] = prev or secrets.token_urlsafe(32)
        if defn.get('delivery'):
            self._validate_delivery(defn['delivery'])
        owner = existing['owner'] if existing else user_id
        wf = self.store.save_workflow(defn, owner=owner, by=user_id,
                                      enabled=existing['enabled'] if (existing and enabled is None)
                                      else (True if enabled is None else bool(enabled)))
        self._sync_published(wf)
        self._audit('workflow.save', user_id, defn['name'], version=wf['version'])
        return wf

    def _validate_delivery(self, d: Dict[str, Any]) -> None:
        router = self._router()
        if router is None:
            return
        try:
            router.validate(d['type'], d['destination'])
        except Exception as e:
            raise WorkflowError(f'delivery: {e}')

    def delete(self, name: str, user_id: str, is_admin: bool = False) -> bool:
        wf = self.store.get_workflow(name)
        if not wf:
            return False
        if wf['owner'] != user_id and not is_admin:
            raise PermissionError('only the owner or an administrator may delete this workflow')
        for r in self.store.runs_with_status(RUN_ACTIVE):
            if r['workflow'] == name:
                self.cancel(r['id'], user_id, is_admin=True)
        self._unpublish(name)
        ok = self.store.delete_workflow(name)
        self._audit('workflow.delete', user_id, name)
        return ok

    def set_enabled(self, name: str, enabled: bool, user_id: str, is_admin: bool = False) -> Dict[str, Any]:
        wf = self.store.get_workflow(name)
        if not wf:
            raise KeyError(name)
        if wf['owner'] != user_id and not is_admin:
            raise PermissionError('only the owner or an administrator may change this workflow')
        self.store.set_enabled(name, enabled)
        wf = self.store.get_workflow(name)
        self._sync_published(wf)
        return wf

    def visible(self, user_id: str, is_admin: bool) -> List[Dict[str, Any]]:
        return self.store.list_workflows(None if is_admin else user_id)

    def can_manage(self, wf: Dict[str, Any], user_id: str, is_admin: bool) -> bool:
        return is_admin or wf['owner'] == user_id

    # ── publish as tool ───────────────────────────────────────────

    def _sync_published(self, wf: Dict[str, Any]) -> None:
        name = wf['name']
        pub = wf['definition'].get('publish') or {}
        self._unpublish(name)
        if self.registry is None or not wf['enabled'] or not pub.get('enabled'):
            return
        from sajha.workflows.tool import WorkflowTool
        tool = WorkflowTool(self, wf)
        current = self.registry.get_tool(tool.name)
        if current is not None and not isinstance(current, WorkflowTool):
            logger.warning(f'workflow {name}: not published, a tool named {tool.name} already exists')
            return
        self.registry.register_tool(tool)
        self._published[name] = tool.name

    def _unpublish(self, name: str) -> None:
        tool_name = self._published.pop(name, None)
        if tool_name and self.registry is not None:
            from sajha.workflows.tool import WorkflowTool
            if isinstance(self.registry.get_tool(tool_name), WorkflowTool):
                self.registry.unregister_tool(tool_name)

    def publish_all(self) -> int:
        n = 0
        for wf in self.store.list_workflows():
            if (wf['definition'].get('publish') or {}).get('enabled') and wf['enabled']:
                self._sync_published(wf)
                n += wf['name'] in self._published
        return n

    def _on_registry_reload(self) -> None:
        self._published.clear()
        try:
            self.publish_all()
        except Exception as e:
            logger.warning(f'workflows: re-publishing after a reload failed: {e}')

    # ── runs ──────────────────────────────────────────────────────

    def start_run(self, name: str, input: Optional[Dict[str, Any]] = None, *, trigger_type: str = 'manual',
                  trigger_id: Optional[str] = None, trigger_detail: Any = None, started_by: Optional[str] = None,
                  idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        wf = self.store.get_workflow(name)
        if not wf:
            raise KeyError(name)
        if not wf['enabled'] and trigger_type not in ('manual', 'rerun'):
            raise WorkflowError(f'workflow {name} is disabled')
        if input is not None and not isinstance(input, dict):
            raise WorkflowError('the run input is an object')
        run, created = self.store.create_run(
            workflow=name, version=wf['version'], definition=wf['definition'], run_as=wf['owner'],
            trigger_type=trigger_type, trigger_id=trigger_id, trigger_detail=trigger_detail,
            started_by=started_by, input=input or {}, idempotency_key=idempotency_key)
        if created:
            self._audit('workflow.run', started_by or wf['owner'], name, run_id=run['id'], trigger=trigger_type,
                        trigger_id=trigger_id)
            self.dispatch(run)
            run = self.store.get_run(run['id'])
        return run

    def _concurrency(self, run: Dict[str, Any]) -> int:
        return int((run.get('definition') or {}).get('concurrency') or self.default_concurrency)

    def dispatch(self, run: Dict[str, Any]) -> bool:
        """Start a queued run here if its workflow's concurrency limit allows."""
        lock = f'wf:dispatch:{run["workflow"]}'
        st = self.state
        got = False
        for _ in range(40):
            if st.add(lock, self.worker_id, ttl=10):
                got = True
                break
            time.sleep(0.05)
        if not got:
            return False
        try:
            if self.store.count_active(run['workflow']) >= self._concurrency(run):
                return False
            if not self.store.claim_run(run['id'], from_status=('queued',), to_status='running',
                                        worker_id=self.worker_id):
                return False
        finally:
            st.delete(lock)
        self._submit(run['id'])
        return True

    def _submit(self, run_id: str) -> None:
        with self._local_lock:
            if run_id in self._local:
                return
            self._local[run_id] = None
            if self._pool is None:        # stopped (an app shut down) but still asked to run: a new pool
                self._pool = cf.ThreadPoolExecutor(max_workers=max(1, self.max_runs), thread_name_prefix='wf-run')
            pool = self._pool
        pool.submit(self._execute, run_id)

    def _execute(self, run_id: str) -> None:
        from sajha.workflows.engine import RunExecutor
        try:
            run = self.store.get_run(run_id)
            if not run or run['status'] != 'running' or run['worker_id'] != self.worker_id:
                return
            ex = RunExecutor(self, run)
            with self._local_lock:
                self._local[run_id] = ex
            ex.execute()
        except Exception as e:
            logger.error(f'workflow run {run_id}: {e}', exc_info=True)
            try:
                self.store.finish_run(run_id, 'failed', error=f'internal error: {e}')
            except Exception:
                pass
        finally:
            with self._local_lock:
                self._local.pop(run_id, None)
            with self._done:
                self._done.notify_all()
            self._dispatch_queued_for(run_id)

    def _dispatch_queued_for(self, run_id: str) -> None:
        try:
            run = self.store.get_run(run_id)
            if not run:
                return
            for q in self.store.list_runs(run['workflow'], status='queued', limit=20)[::-1]:
                if not self.dispatch(q):
                    break
        except Exception as e:
            logger.debug(f'workflow dispatch: {e}')

    def wait_for(self, run_id: str, timeout: float) -> Dict[str, Any]:
        end = time.time() + max(0.0, timeout)
        while True:
            run = self.store.get_run(run_id)
            if run is None or run['status'] in RUN_DONE or time.time() >= end:
                return run
            with self._done:
                self._done.wait(min(0.25, max(0.01, end - time.time())))

    def run_detail(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.store.get_run(run_id)
        if not run:
            return None
        run['steps'] = self.store.get_steps(run_id)
        order = {s['id']: i for i, s in enumerate((run.get('definition') or {}).get('steps', []))}
        run['steps'].sort(key=lambda s: order.get(s['step_id'], 10 ** 6))
        return run

    def cancel(self, run_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any]:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        wf = self.store.get_workflow(run['workflow'])
        if not is_admin and run['run_as'] != user_id and (not wf or wf['owner'] != user_id):
            raise PermissionError('only the owner or an administrator may cancel this run')
        if run['status'] in RUN_DONE:
            return run
        self.store.request_cancel(run_id)
        with self._local_lock:
            ex = self._local.get(run_id)
        if ex is not None:
            ex.cancel_event.set()
        elif run['status'] in ('queued', 'waiting'):
            # nobody is executing it: finish it here
            if self.store.finish_run(run_id, 'cancelled', error='cancelled'):
                for s in self.store.get_steps(run_id):
                    if s['status'] in ('pending', 'waiting', 'running'):
                        self.store.put_step(run_id, s['step_id'], s['kind'], status='cancelled',
                                            error='the run was cancelled', finished_at=time.time())
                self.after_finish(run_id, 'cancelled', None, 'cancelled')
        self._audit('workflow.cancel', user_id, run['workflow'], run_id=run_id)
        return self.store.get_run(run_id)

    def rerun(self, run_id: str, user_id: str, is_admin: bool = False, from_step: Optional[str] = None,
              latest_definition: bool = False) -> Dict[str, Any]:
        """A new run that reuses the outputs of the steps before ``from_step`` (default: the first failed)."""
        old = self.run_detail(run_id)
        if not old:
            raise KeyError(run_id)
        wf = self.store.get_workflow(old['workflow'])
        if not wf:
            raise WorkflowError('the workflow no longer exists')
        if not self.can_manage(wf, user_id, is_admin):
            raise PermissionError('only the owner or an administrator may re-run this workflow')
        if old['status'] not in RUN_DONE:
            raise WorkflowError(f'the run is still {old["status"]}')
        defn = wf['definition'] if latest_definition else old['definition']
        ids = [s['id'] for s in defn['steps']]
        if from_step is None:
            failed = [s['step_id'] for s in old['steps'] if s['status'] in ('failed', 'cancelled')]
            from_step = next((sid for sid in ids if sid in failed), None)
        if from_step is not None and from_step not in ids:
            raise WorkflowError(f'no step {from_step} in this workflow')
        redo = model.descendants(defn['steps'], from_step) if from_step else set(ids)
        run, _ = self.store.create_run(
            workflow=old['workflow'], version=wf['version'] if latest_definition else old['version'],
            definition=defn, run_as=wf['owner'], trigger_type='rerun', trigger_id=old['id'],
            trigger_detail={'rerun_of': old['id'], 'from_step': from_step}, started_by=user_id,
            input=old.get('input') or {}, parent_run_id=old['id'], from_step=from_step)
        for s in old['steps']:
            if s['step_id'] in ids and s['step_id'] not in redo and s['status'] in ('succeeded', 'skipped'):
                self.store.put_step(run['id'], s['step_id'], s['kind'], status=s['status'], attempts=s['attempts'],
                                    input=s.get('input'), output=s.get('output'), error=s.get('error'),
                                    detail={'reused_from': old['id']}, started_at=s.get('started_at'),
                                    finished_at=s.get('finished_at'), duration_ms=s.get('duration_ms'),
                                    idempotency_key=s.get('idempotency_key'))
        self._audit('workflow.rerun', user_id, old['workflow'], run_id=run['id'], rerun_of=old['id'],
                    from_step=from_step)
        self.dispatch(run)
        return self.store.get_run(run['id'])

    # ── delivery ──────────────────────────────────────────────────

    @staticmethod
    def _router():
        try:
            from sajha.core.async_executor import get_async_executor
            return get_async_executor()._router
        except Exception as e:
            logger.debug(f'workflow delivery router: {e}')
            return None

    def after_finish(self, run_id: str, status: str, output: Any, error: Optional[str]) -> None:
        run = self.store.get_run(run_id)
        if not run:
            return
        self._audit('workflow.finish', run['run_as'], run['workflow'], outcome=status, run_id=run_id,
                    error=(error or '')[:300] or None)
        try:
            from sajha.observability import metrics
            fn = getattr(metrics, 'record_workflow_run', None)
            if fn:
                fn(run['workflow'], status)
        except Exception:
            pass
        # System notice when scheduled runs keep failing (docs/architecture/System Notices.md)
        from sajha.notices.sources import workflow_run_finished
        workflow_run_finished(run['workflow'], run.get('trigger_type') or '', status, error)
        delivery = (run.get('definition') or {}).get('delivery')
        if not delivery or status not in delivery.get('on', ['succeeded', 'failed']):
            return
        threading.Thread(target=self._deliver, args=(run, status, output, error, delivery),
                         name=f'wf-deliver-{run_id[:8]}', daemon=True).start()

    def _deliver(self, run, status, output, error, delivery) -> None:
        from sajha.core.async_executor import AsyncTask, AsyncTaskStatus
        router = self._router()
        if router is None:
            self.store.update_run(run['id'], delivery_status='failed: no delivery router')
            return
        task = AsyncTask(task_id=run['id'], tool_name=f'workflow:{run["workflow"]}', arguments=run.get('input') or {},
                         delivery_type=delivery['type'], delivery_destination=delivery['destination'],
                         status=AsyncTaskStatus.COMPLETED if status == 'succeeded' else AsyncTaskStatus.FAILED,
                         result=output, error=error, user_id=run['run_as'],
                         duration_ms=round(((run.get('finished_at') or time.time()) - (run.get('started_at')
                                                                                         or run['created_at'])) * 1000, 1))
        try:
            ok = router.deliver(task)
        except Exception as e:
            ok = False
            task.error = str(e)
        self.store.update_run(run['id'], delivery_status=('delivered' if ok else
                                                          f'failed: {(task.error or "")[:150]}'))

    # ── triggers ──────────────────────────────────────────────────

    def webhook_secret(self, trigger: Dict[str, Any]) -> Optional[str]:
        ref = trigger.get('secret_ref')
        if ref:
            import os
            return os.environ.get(ref[len('env:'):]) or None
        return trigger.get('secret')

    @staticmethod
    def sign(secret: str, timestamp: str, body: bytes) -> str:
        mac = hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()
        return f'sha256={mac}'

    def receive_webhook(self, name: str, trigger_id: str, body: bytes, headers: Dict[str, str]) -> Tuple[int, Dict]:
        """Verify a signed delivery and start a run. Returns (HTTP status, JSON body)."""
        wf = self.store.get_workflow(name)
        trig = None
        if wf and wf['enabled']:
            trig = next((t for t in wf['definition'].get('triggers', [])
                         if t['id'] == trigger_id and t['type'] == 'webhook' and t.get('enabled', True)), None)
        if trig is None:
            return 404, {'error': 'no such webhook'}
        secret = self.webhook_secret(trig)
        if not secret:
            return 503, {'error': 'the webhook has no secret configured'}
        h = {k.lower(): v for k, v in headers.items()}
        ts, sig = h.get('x-sajha-timestamp', ''), h.get('x-sajha-signature', '')
        try:
            ts_f = float(ts)
        except ValueError:
            return 401, {'error': 'missing or bad X-Sajha-Timestamp'}
        tol = float(trig.get('tolerance_seconds', 300))
        if abs(time.time() - ts_f) > tol:
            return 401, {'error': f'timestamp outside the {tol:g}s tolerance (replay protection)'}
        if not sig or not hmac.compare_digest(self.sign(secret, ts, body), sig.strip()):
            return 401, {'error': 'bad signature'}
        delivery = h.get('x-sajha-delivery') or ''
        replay_key = f'wf:hook:{name}:{trigger_id}:{hashlib.sha256(sig.encode()).hexdigest()[:32]}'
        if not self.state.add(replay_key, ts, ttl=tol * 2 + 60):
            return 409, {'error': 'this delivery was already received (replay)'}
        import json
        try:
            payload = json.loads(body.decode('utf-8') or '{}') if body else {}
        except ValueError:
            payload = {'body': body.decode('utf-8', 'replace')}
        inp = dict(trig.get('input') or {})
        inp.update(payload if isinstance(payload, dict) else {'payload': payload})
        key = f'webhook:{trigger_id}:{delivery}' if delivery else None
        try:
            run = self.start_run(name, inp, trigger_type='webhook', trigger_id=trigger_id,
                                 trigger_detail={'delivery': delivery or None, 'timestamp': ts_f},
                                 started_by=f'webhook:{trigger_id}', idempotency_key=key)
        except WorkflowError as e:
            return 409, {'error': str(e)}
        return 202, {'run_id': run['id'], 'status': run['status']}

    def _fire(self, wf, trig, input_extra: Dict[str, Any], key: Optional[str], detail: Any) -> Optional[Dict]:
        inp = dict(trig.get('input') or {})
        inp.update(input_extra or {})
        try:
            return self.start_run(wf['name'], inp, trigger_type=trig['type'], trigger_id=trig['id'],
                                  trigger_detail=detail, started_by=f'{trig["type"]}:{trig["id"]}',
                                  idempotency_key=key)
        except Exception as e:
            logger.warning(f'workflow {wf["name"]}: trigger {trig["id"]} could not start a run: {e}')
            return None

    def _triggers(self, ttype: str):
        for wf in self.store.list_workflows():
            if not wf['enabled']:
                continue
            for t in wf['definition'].get('triggers', []):
                if t['type'] == ttype and t.get('enabled', True):
                    yield wf, t

    def tick_cron(self, now: Optional[datetime] = None) -> List[Dict]:
        from sajha.workflows.cron import CronSchedule
        now = now or datetime.now(timezone.utc)
        fired = []
        for wf, t in self._triggers('cron'):
            k = f'{wf["name"]}:{t["id"]}:{t["cron"]}:{t.get("timezone")}'
            since = self._cron_seen.get(k)
            if since is None:
                # first look on this worker: the slot due in the last tick window counts
                since = now - timedelta(seconds=max(self.tick_seconds * 2, 60))
            self._cron_seen[k] = now
            try:
                slot = CronSchedule(t['cron'], t.get('timezone')).latest_due(since, now)
            except Exception as e:
                logger.warning(f'workflow {wf["name"]}: cron {t["id"]}: {e}')
                continue
            if slot is None:
                continue
            iso = slot.strftime('%Y-%m-%dT%H:%MZ')
            if not self.state.add(f'wf:cron:{wf["name"]}:{t["id"]}:{iso}', self.worker_id, ttl=86400 * 2):
                continue        # another worker fired this slot
            run = self._fire(wf, t, {'scheduled_for': iso}, f'cron:{t["id"]}:{iso}',
                             {'slot': iso, 'timezone': t.get('timezone'), 'worker': self.worker_id})
            if run:
                fired.append(run)
        return fired

    def tick_files(self) -> List[Dict]:
        fired = []
        for wf, t in self._triggers('file'):
            base = f'{wf["name"]}:{t["id"]}'
            if not self.state.add(f'wf:filepoll:{base}', self.worker_id, ttl=float(t['interval_seconds'])):
                continue        # polled within the interval (here or on another worker)
            try:
                backend = self.storage()
                paths = backend.list_files(t['prefix'], t['pattern'])
            except Exception as e:
                logger.warning(f'workflow {wf["name"]}: file trigger {t["id"]}: {e}')
                continue
            first = self.state.add(f'wf:filebase:{base}', time.time())
            for path in paths[:1000]:
                try:
                    mtime = float(backend.get_modified_time(path))
                except Exception:
                    continue
                marker = f'wf:file:{base}:{hashlib.sha256(path.encode()).hexdigest()[:24]}'
                if self.state.get(marker) == mtime:
                    continue
                self.state.set(marker, mtime, ttl=86400 * 30)
                if first and not t.get('fire_existing'):
                    continue
                run = self._fire(wf, t, {'path': path, 'modified': mtime}, f'file:{t["id"]}:{path}:{mtime}',
                                 {'path': path, 'modified': mtime})
                if run:
                    fired.append(run)
        return fired

    def on_change(self, event) -> None:
        """Change-bus listener: fire matching ``event`` triggers (off the producer's thread)."""
        if self._stop.is_set():
            return

        def go():
            try:
                for wf, t in self._triggers('event'):
                    if event.kind not in t['kinds']:
                        continue
                    if t.get('uri') and t['uri'] != event.uri:
                        continue
                    deb = float(t.get('debounce_seconds', 5))
                    if deb > 0 and not self.state.add(f'wf:event:{wf["name"]}:{t["id"]}:{event.kind}:{event.uri}',
                                                      1, ttl=deb):
                        continue
                    self._fire(wf, t, {'event': {'kind': event.kind, 'uri': event.uri}}, None,
                               {'kind': event.kind, 'uri': event.uri})
            except Exception as e:
                logger.debug(f'workflow event trigger: {e}')
        threading.Thread(target=go, name='wf-event', daemon=True).start()

    # ── recovery and the scheduler ────────────────────────────────

    def tick_runs(self) -> Dict[str, int]:
        """Resume orphaned runs, wake parked ones, start queued ones."""
        from sajha.core.state import worker_alive
        from sajha.workflows.engine import RunExecutor
        n = {'resumed': 0, 'woken': 0, 'started': 0, 'timed_out': 0}
        now = time.time()
        for run in self.store.runs_with_status(('running',)):
            if run['worker_id'] == self.worker_id:
                with self._local_lock:
                    mine = run['id'] in self._local
                if mine:
                    continue
            elif run['worker_id'] and (now - (run['heartbeat_at'] or 0)) < self.stale_seconds:
                continue
            elif run['worker_id'] and worker_alive(run['worker_id'], self.state) \
                    and (now - (run['heartbeat_at'] or 0)) < self.stale_seconds * 3:
                continue
            if self.store.claim_run(run['id'], from_status=('running',), to_status='running',
                                    worker_id=self.worker_id, expect_worker=run['worker_id'],
                                    expect_heartbeat=run['heartbeat_at']):
                logger.info(f'workflow run {run["id"]} ({run["workflow"]}): resuming after worker '
                            f'{run["worker_id"]} stopped')
                self._audit('workflow.resume', run['run_as'], run['workflow'], run_id=run['id'],
                            previous_worker=run['worker_id'])
                self._submit(run['id'])
                n['resumed'] += 1
        for run in self.store.runs_with_status(('waiting',)):
            d = run.get('definition') or {}
            if d.get('timeout_seconds') and now > (run.get('started_at') or run['created_at']) + float(d['timeout_seconds']):
                if self.store.finish_run(run['id'], 'failed', error='the run exceeded its timeout while waiting'):
                    self.after_finish(run['id'], 'failed', None, 'timeout')
                    n['timed_out'] += 1
                continue
            if run['cancel_requested']:
                self.cancel(run['id'], 'system', is_admin=True)
                continue
            probe = RunExecutor(self, run)
            for s in self.store.get_steps(run['id']):
                probe.records[s['step_id']] = {'status': s['status'], 'detail': s.get('detail')}
            ready = any(r['status'] == 'waiting' and probe._wait_satisfied(sid) for sid, r in probe.records.items()
                        if sid in probe.steps)
            if ready and self.store.claim_run(run['id'], from_status=('waiting',), to_status='running',
                                              worker_id=self.worker_id, expect_worker=None):
                self._submit(run['id'])
                n['woken'] += 1
        for run in self.store.runs_with_status(('queued',)):
            if self.dispatch(run):
                n['started'] += 1
        return n

    def tick(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for name, fn in (('cron', lambda: len(self.tick_cron(now))), ('files', lambda: len(self.tick_files())),
                         ('runs', self.tick_runs)):
            try:
                out[name] = fn()
            except Exception as e:
                logger.warning(f'workflow scheduler ({name}): {e}', exc_info=True)
        if time.time() - self._last_prune > 3600 and self.retention_days > 0:
            self._last_prune = time.time()
            try:
                self.store.prune_runs(time.time() - self.retention_days * 86400)
            except Exception as e:
                logger.debug(f'workflow prune: {e}')
        return out

    def _loop(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            self.tick()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        try:
            from sajha.core.change_bus import get_change_bus
            self._listener = self.on_change
            get_change_bus().add_listener(self._listener)
        except Exception as e:
            logger.debug(f'workflows: change bus unavailable: {e}')
        if self.registry is not None and hasattr(self.registry, 'add_reload_listener'):
            self.registry.add_reload_listener(self._on_registry_reload)
        self._thread = threading.Thread(target=self._loop, name='wf-scheduler', daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                from sajha.core.change_bus import get_change_bus
                get_change_bus().remove_listener(self._listener)
            except Exception:
                pass
            self._listener = None
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        with self._local_lock:
            running = [e for e in self._local.values() if e is not None]
        # running runs keep their heartbeat; another worker resumes them once it is stale
        with self._local_lock:
            pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        for ex in running:
            logger.info(f'workflow run {ex.run_id} left running at shutdown; another worker (or this one after '
                        f'restart) resumes it')

    def status(self) -> Dict[str, Any]:
        with self._local_lock:
            local = len(self._local)
        return {'enabled': self.enabled, 'worker': self.worker_id, 'running_here': local,
                'tick_seconds': self.tick_seconds, 'published': dict(self._published),
                'state_shared': bool(getattr(self.state, 'shared', False))}


# ── the process singleton ───────────────────────────────────────

_service: Optional[WorkflowService] = None


def init_workflows(tools_registry) -> Optional[WorkflowService]:
    global _service
    svc = WorkflowService(tools_registry)
    if not svc.enabled:
        logger.info('  Workflows: off (workflows.enabled: false)')
        _service = svc
        return svc
    svc.store.ensure()
    n = svc.publish_all()
    svc.start()
    _service = svc
    logger.info(f'  Workflows: scheduler on (tick {svc.tick_seconds:g}s), {n} published as tools')
    return svc


def get_service() -> Optional[WorkflowService]:
    return _service


def set_service(svc: Optional[WorkflowService]) -> None:
    global _service
    _service = svc


def shutdown_workflows() -> None:
    global _service
    if _service is not None:
        _service.stop()
