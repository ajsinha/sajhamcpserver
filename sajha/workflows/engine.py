"""
SAJHA MCP Server — the workflow run executor: one run of the DAG, durable step by step.

A run walks the DAG in dependency order and starts every step whose dependencies are
done (up to ``max_parallel`` at once). Each step's state is written to
``workflow_run_steps`` as it changes, so another worker can pick the run up after a crash:
a step that had succeeded is never run again (its stored output is reused); a step that
was running when the worker died runs again only if it is idempotent, otherwise it is
marked failed (and can be re-run from the UI, CLI or API).

Waits longer than ``workflows.inline_wait_seconds`` and approvals park the run
(status ``waiting``) and free the worker; the scheduler resumes it when the time has come
or the approval is decided.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import concurrent.futures as cf
import contextvars
import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sajha.workflows import expr
from sajha.workflows.identity import OwnerUnavailable, RunIdentity
from sajha.workflows.model import topo_order
from sajha.workflows.store import STEP_DONE, bounded

logger = logging.getLogger(__name__)

#: the timeout of a step that sets none (seconds)
DEFAULT_STEP_TIMEOUT = 300.0

# One shared pool runs the calls that have a timeout; a timed-out call cannot be killed
# (Python threads cannot be), it is abandoned and its result ignored.
_call_pool = cf.ThreadPoolExecutor(max_workers=64, thread_name_prefix='wf-call')


#: the workflows on the current call path (a published workflow may not call itself)
CHAIN: contextvars.ContextVar = contextvars.ContextVar('sajha_workflow_chain', default=())


class StepError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class Waiting(Exception):
    """The step cannot finish yet; ``detail`` says what it waits for (wake_at / approval_id)."""

    def __init__(self, detail: Dict[str, Any]):
        super().__init__('waiting')
        self.detail = detail


class Cancelled(Exception):
    pass


def _key(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _parse_until(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        dt = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return dt.timestamp()


class RunExecutor:
    """Executes (or resumes) one run on this worker."""

    def __init__(self, service, run: Dict[str, Any]):
        self.svc = service
        self.store = service.store
        self.run = run
        self.run_id = run['id']
        self.defn = run['definition'] or {}
        self.steps: Dict[str, Dict[str, Any]] = {s['id']: s for s in self.defn.get('steps', [])}
        self.order: List[str] = topo_order(self.defn.get('steps', []))
        self.records: Dict[str, Dict[str, Any]] = {}
        self.outputs: Dict[str, Any] = {}
        self.cancel_event = threading.Event()
        self.ident: Optional[RunIdentity] = None
        self._lock = threading.Lock()
        self._last_cancel_check = 0.0
        self._last_beat = 0.0
        self._lost = False

    # ── context ───────────────────────────────────────────────────

    def ctx(self, item: Any = None, index: Optional[int] = None, with_item: bool = False) -> Dict[str, Any]:
        c = {'input': self.run.get('input') or {}, 'steps': dict(self.outputs),
             'run': {'id': self.run_id, 'workflow': self.run['workflow'], 'trigger': self.run.get('trigger_type'),
                     'trigger_id': self.run.get('trigger_id')}}
        if with_item:
            c['item'] = item
            c['index'] = index
        return c

    def cancelled(self) -> bool:
        if self.cancel_event.is_set():
            return True
        now = time.time()
        if now - self._last_cancel_check >= 0.5:
            self._last_cancel_check = now
            try:
                if self.store.cancel_requested(self.run_id):
                    self.cancel_event.set()
            except Exception as e:
                logger.debug(f'workflow cancel check: {e}')
        return self.cancel_event.is_set()

    def sleep(self, seconds: float) -> None:
        end = time.time() + max(0.0, seconds)
        while True:
            if self.cancelled():
                raise Cancelled()
            left = end - time.time()
            if left <= 0:
                return
            time.sleep(min(left, 0.2))

    def _beat(self) -> None:
        now = time.time()
        if now - self._last_beat >= self.svc.heartbeat_seconds:
            self._last_beat = now
            try:
                if not self.store.heartbeat(self.run_id, self.svc.worker_id):
                    self._lost = True
            except Exception as e:
                logger.debug(f'workflow heartbeat: {e}')

    # ── step state ────────────────────────────────────────────────

    def _set(self, sid: str, **fields) -> None:
        with self._lock:
            rec = self.records.setdefault(sid, {'status': 'pending', 'attempts': 0, 'detail': None})
            rec.update({k: v for k, v in fields.items() if k in ('status', 'attempts', 'detail', 'error')})
        store_fields = dict(fields)
        if 'output' in store_fields:
            store_fields['output'] = bounded(store_fields['output'], self.svc.output_chars)
        if 'input' in store_fields:
            store_fields['input'] = bounded(store_fields['input'], self.svc.input_chars)
        self.store.put_step(self.run_id, sid, self.steps[sid]['kind'], **store_fields)

    def idempotent(self, step: Dict[str, Any]) -> bool:
        if 'idempotent' in step:
            return bool(step['idempotent'])
        kind = step['kind']
        if kind in ('condition', 'wait', 'approval'):
            return True
        if kind == 'foreach':
            return self.idempotent(dict(step['do']))
        if kind in ('tool', 'composite'):
            tool = self.svc.get_tool(step['tool'])
            ann = (getattr(tool, 'config', None) or {}).get('annotations') or {} if tool is not None else {}
            return bool(ann.get('readOnlyHint') or ann.get('idempotentHint'))
        return False

    # ── the run ───────────────────────────────────────────────────

    def execute(self) -> str:
        """Run to a terminal or parked state; returns the run status it left."""
        from sajha.observability.caller import reset as reset_caller, set_caller
        from sajha.policy.context import reset_source, set_source
        try:
            from sajha.workflows import identity
            self.ident = identity.resolve(self.run['run_as'])
        except OwnerUnavailable as e:
            return self._finish('failed', error=str(e))
        except Exception as e:
            return self._finish('failed', error=f'cannot resolve the run-as identity: {e}')
        t_caller, t_source = set_caller(self.ident.caller()), set_source('workflow')
        t_chain = CHAIN.set(tuple(CHAIN.get()) + (self.run['workflow'],))
        try:
            return self._execute()
        except Exception as e:
            logger.error(f'workflow run {self.run_id} crashed: {e}', exc_info=True)
            return self._finish('failed', error=f'internal error: {e}')
        finally:
            CHAIN.reset(t_chain)
            reset_caller(t_caller)
            reset_source(t_source)

    def _load(self) -> None:
        for rec in self.store.get_steps(self.run_id):
            sid = rec['step_id']
            if sid not in self.steps:
                continue
            self.records[sid] = {'status': rec['status'], 'attempts': rec['attempts'] or 0,
                                 'detail': rec.get('detail'), 'error': rec.get('error')}
            if rec['status'] == 'succeeded':
                self.outputs[sid] = rec.get('output')
        for sid in self.order:
            if sid not in self.records:
                self._set(sid, status='pending', attempts=0)
        # a step left running by a dead worker: run again only when that is safe
        for sid, rec in self.records.items():
            if rec['status'] == 'running':
                if self.idempotent(self.steps[sid]):
                    self._set(sid, status='pending')
                else:
                    self._set(sid, status='failed', finished_at=time.time(),
                              error='interrupted (the worker running it stopped) and the step is not idempotent: '
                                    're-run the workflow from this step once you have checked its effect')

    def _readiness(self, sid: str) -> str:
        """'wait' (dependencies not done), 'run' or 'skip:<reason>'."""
        step = self.steps[sid]
        deps = step['depends_on']
        states = [self.records[d]['status'] for d in deps]
        if any(s not in STEP_DONE for s in states):
            return 'wait'
        for cid, c in self.steps.items():
            if c['kind'] != 'condition' or self.records[cid]['status'] != 'succeeded':
                continue
            result = bool((self.outputs.get(cid) or {}).get('result'))
            if sid in c.get('then', []) and not result:
                return f'skip:branch not taken ({cid} was false)'
            if sid in c.get('else', []) and result:
                return f'skip:branch not taken ({cid} was true)'
        join = step.get('join', 'all_success')
        if deps:
            ok = [s == 'succeeded' for s in states]
            if join == 'all_success' and not all(ok):
                return 'skip:a dependency did not succeed'
            if join == 'any_success' and not any(ok):
                return 'skip:no dependency succeeded'
        if step.get('when') is not None:
            try:
                if not expr.evaluate(step['when'], self.ctx()):
                    return 'skip:"when" was false'
            except Exception as e:
                return f'skip:"when" could not be evaluated: {e}'
        return 'run'

    def _wait_satisfied(self, sid: str) -> bool:
        detail = self.records[sid].get('detail') or {}
        if detail.get('wake_at') is not None:
            return time.time() >= float(detail['wake_at'])
        if detail.get('approval_id'):
            try:
                from sajha.policy import approvals
                rec = approvals.get(detail['approval_id'])
            except Exception:
                return True                     # let the step itself report the problem
            return not rec or rec.get('status') != 'pending'
        return True

    def next_wake(self) -> Optional[float]:
        times = [float((r.get('detail') or {}).get('wake_at')) for r in self.records.values()
                 if r['status'] == 'waiting' and (r.get('detail') or {}).get('wake_at') is not None]
        return min(times) if times else None

    def _execute(self) -> str:
        self._load()
        started = self.run.get('started_at') or time.time()
        if not self.run.get('started_at'):
            self.store.update_run(self.run_id, started_at=started)
        deadline = started + float(self.defn['timeout_seconds']) if self.defn.get('timeout_seconds') else None
        max_parallel = int(self.defn.get('max_parallel') or self.svc.max_parallel)
        pool = cf.ThreadPoolExecutor(max_workers=max_parallel, thread_name_prefix=f'wf-{self.run_id[:8]}')
        inflight: Dict[cf.Future, str] = {}
        fatal: Optional[str] = None
        for sid, rec in self.records.items():
            if rec['status'] == 'failed' and self.steps[sid].get('on_error', 'fail') == 'fail':
                fatal = f'step {sid}: {rec.get("error") or "failed"}'
        try:
            while True:
                self._beat()
                if self._lost:
                    logger.warning(f'workflow run {self.run_id}: another worker took it over; stopping here')
                    return 'lost'
                if self.cancelled():
                    return self._cancel(inflight)
                if deadline and time.time() > deadline and fatal is None:
                    fatal = f'the run exceeded its timeout ({self.defn["timeout_seconds"]:g}s)'
                running = set(inflight.values())
                if fatal is None:
                    for sid in self.order:
                        if sid in running or len(inflight) >= max_parallel:
                            continue
                        rec = self.records[sid]
                        if rec['status'] == 'pending':
                            r = self._readiness(sid)
                            if r == 'run':
                                self._set(sid, status='running', started_at=time.time(), error=None)
                                inflight[pool.submit(contextvars.copy_context().run, self._run_step, sid)] = sid
                            elif r.startswith('skip:'):
                                self._set(sid, status='skipped', error=r[5:], finished_at=time.time())
                        elif rec['status'] == 'waiting' and self._wait_satisfied(sid):
                            self._set(sid, status='running')
                            inflight[pool.submit(contextvars.copy_context().run, self._run_step, sid)] = sid
                if not inflight:
                    pending = [s for s in self.order if self.records[s]['status'] == 'pending']
                    waiting = [s for s in self.order if self.records[s]['status'] == 'waiting']
                    if fatal is not None:
                        for s in pending + waiting:
                            self._set(s, status='skipped', error='not run: the run failed', finished_at=time.time())
                        return self._finish('failed', error=fatal)
                    if not pending and not waiting:
                        return self._finish('succeeded')
                    if waiting:
                        wake = self.next_wake()
                        if wake is not None and wake - time.time() <= self.svc.inline_wait_seconds:
                            self.sleep(min(0.2, max(0.0, wake - time.time())))
                            continue
                        return self._park()
                    # pending steps whose dependencies can never finish (should not happen in a DAG)
                    for s in pending:
                        self._set(s, status='skipped', error='dependencies never finished', finished_at=time.time())
                    continue
                done, _ = cf.wait(list(inflight), timeout=0.25, return_when=cf.FIRST_COMPLETED)
                for f in done:
                    sid = inflight.pop(f)
                    err = self._settle(sid, f)
                    if err and self.steps[sid].get('on_error', 'fail') == 'fail' and fatal is None:
                        fatal = f'step {sid}: {err}'
        finally:
            pool.shutdown(wait=False)

    def _settle(self, sid: str, f: cf.Future) -> Optional[str]:
        """Record a finished step; returns the error text of a failure."""
        now = time.time()
        try:
            output, used_input = f.result()
            self.outputs[sid] = output
            self._set(sid, status='succeeded', output=output, input=used_input, finished_at=now,
                      duration_ms=self._duration(sid, now), error=None)
            return None
        except Waiting as w:
            self._set(sid, status='waiting', detail=w.detail)
            return None
        except Cancelled:
            self._set(sid, status='cancelled', finished_at=now, error='cancelled')
            return None
        except StepError as e:
            self._set(sid, status='failed', error=str(e)[:4000], finished_at=now, duration_ms=self._duration(sid, now))
            return str(e)
        except Exception as e:  # noqa: BLE001
            logger.warning(f'workflow step {sid} raised: {e}', exc_info=True)
            self._set(sid, status='failed', error=str(e)[:4000], finished_at=now, duration_ms=self._duration(sid, now))
            return str(e) or e.__class__.__name__

    def _duration(self, sid: str, now: float) -> Optional[float]:
        started = self.records[sid].get('started_at')
        return round((now - started) * 1000, 1) if started else None

    def _set_started(self, sid: str) -> None:
        with self._lock:
            self.records[sid]['started_at'] = time.time()

    # ── one step ──────────────────────────────────────────────────

    def _run_step(self, sid: str):
        """(output, input as resolved) or raises Waiting / Cancelled / StepError."""
        self._set_started(sid)
        step = self.steps[sid]
        kind = step['kind']
        ctx = self.ctx()
        if kind == 'condition':
            return {'result': bool(expr.evaluate(step['if'], ctx))}, {'if': step['if']}
        if kind == 'wait':
            return self._wait(sid, step, ctx)
        if kind == 'approval':
            return self._approval(sid, step)
        if kind == 'foreach':
            return self._foreach(sid, step, ctx)
        # tool / composite / ask: a policy approval parks the step; the call runs again once decided
        detail = self.records[sid].get('detail') or {}
        if detail.get('approval_id') and detail.get('policy'):
            self._check_policy_approval(detail['approval_id'])
        return self._call(sid, step, ctx, top_level=True)

    def _check_policy_approval(self, aid: str) -> None:
        try:
            from sajha.policy import approvals
            rec = approvals.get(aid)
        except Exception:
            return
        if rec and rec.get('status') == 'denied':
            raise StepError(f'the policy approval was denied by {rec.get("decided_by")}'
                            + (f': {rec.get("note")}' if rec.get('note') else ''))
        if rec and rec.get('status') == 'expired':
            raise StepError('the policy approval expired before anyone decided it')

    def _wait(self, sid: str, step: Dict[str, Any], ctx: Dict[str, Any]):
        detail = self.records[sid].get('detail') or {}
        wake = detail.get('wake_at')
        if wake is None:
            if step.get('until') is not None:
                wake = _parse_until(expr.resolve(step['until'], ctx))
            else:
                secs = expr.resolve(step.get('seconds'), ctx)
                try:
                    secs = float(secs)
                except (TypeError, ValueError):
                    raise StepError(f'wait: seconds resolved to {secs!r}, not a number')
                wake = time.time() + max(0.0, secs)
            detail = {'wake_at': wake}
            self._set(sid, detail=detail)
        left = float(wake) - time.time()
        if left > self.svc.inline_wait_seconds:
            raise Waiting(detail)
        self.sleep(left)
        return {'woke_at': time.time(), 'wake_at': wake}, {'wake_at': wake}

    def _approval(self, sid: str, step: Dict[str, Any]):
        try:
            from sajha.policy import approvals
        except ImportError:
            raise StepError('approval steps need the policy engine (sajha/policy), which is not available')
        detail = self.records[sid].get('detail') or {}
        aid = detail.get('approval_id')
        if not aid:
            rec = approvals.request(
                tool=f'workflow:{self.run["workflow"]}.{sid}',
                arguments={'workflow': self.run['workflow'], 'run_id': self.run_id, 'step': sid,
                           'input': self.run.get('input') or {}},
                caller=self.ident.caller(), source='workflow', rule='workflow-approval-step',
                reason=step.get('reason') or f'Workflow step {sid} needs approval',
                ttl=step.get('ttl_seconds'))
            raise Waiting({'approval_id': rec['id']})
        rec = approvals.get(aid)
        if not rec:
            raise StepError('the approval record is gone (expired from the state store)')
        status = rec.get('status')
        if status in ('approved', 'used'):
            return {'approved': True, 'approval_id': aid, 'decided_by': rec.get('decided_by'),
                    'note': rec.get('note') or ''}, {'approval_id': aid}
        if status == 'denied':
            raise StepError(f'denied by {rec.get("decided_by")}' + (f': {rec.get("note")}' if rec.get('note') else ''))
        if status == 'expired':
            raise StepError('the approval expired before anyone decided it')
        raise Waiting({'approval_id': aid})

    def _foreach(self, sid: str, step: Dict[str, Any], ctx: Dict[str, Any]):
        items = expr.resolve(step['items'], ctx)
        if items is None or items == '':
            items = []
        if isinstance(items, dict):
            items = list(items.items())
        if not isinstance(items, list):
            raise StepError(f'foreach: items resolved to {type(items).__name__}, not a list')
        cap = min(int(step.get('max_items') or self.svc.loop_max_items), self.svc.loop_hard_max)
        truncated = len(items) > cap
        if truncated and step.get('on_overflow') == 'fail':
            raise StepError(f'foreach: {len(items)} items exceed max_items {cap}')
        items = items[:cap]
        body = step['do']
        results: List[Any] = [None] * len(items)
        errors: List[Optional[str]] = [None] * len(items)

        def one(i):
            c = self.ctx(items[i], i, with_item=True)
            out, _ = self._call(sid, body, c, top_level=False, salt=i)
            return out

        par = max(1, min(int(step.get('parallel') or 1), len(items) or 1))
        with cf.ThreadPoolExecutor(max_workers=par, thread_name_prefix=f'wf-each-{sid}') as p:
            futs = {p.submit(contextvars.copy_context().run, one, i): i for i in range(len(items))}
            for f in cf.as_completed(futs):
                i = futs[f]
                try:
                    results[i] = f.result()
                except (Waiting, Cancelled):
                    raise
                except Exception as e:
                    errors[i] = str(e)
                    if body.get('on_error', 'fail') == 'fail':
                        for g in futs:
                            g.cancel()
                        raise StepError(f'item {i}: {e}')
                    results[i] = {'error': str(e)}
        return ({'items': results, 'count': len(items), 'truncated': truncated,
                 'failed': sum(1 for e in errors if e)},
                {'items': bounded(items, 2000), 'max_items': cap})

    def _call(self, sid: str, spec: Dict[str, Any], ctx: Dict[str, Any], top_level: bool, salt: Any = None):
        """A tool / composite / ask call with retries, backoff and a timeout."""
        from sajha.policy.errors import ApprovalRequired, PolicyError, RateLimited
        kind = spec['kind']
        if kind == 'ask':
            used = {'question': expr.resolve(spec['question'], ctx)}
            if spec.get('model'):
                used['model'] = spec['model']
        else:
            params = expr.resolve(spec.get('params') or {}, ctx)
            if not isinstance(params, dict):
                raise StepError('params did not resolve to an object')
            if spec.get('idempotency_param'):
                params[spec['idempotency_param']] = _key(self.run_id, sid, salt)
            used = params
        idem = _key(self.run_id, sid, salt, used)
        if top_level:
            self._set(sid, idempotency_key=idem, input=used)
        retry = spec.get('retry') or {'max_attempts': 1, 'backoff_seconds': 1, 'backoff_factor': 2,
                                      'max_backoff_seconds': 300, 'on_timeout': True}
        timeout = float(spec.get('timeout_seconds') or self.svc.step_timeout)
        attempt = self.records[sid].get('attempts', 0) if top_level else 0
        tries = 0
        while True:
            if self.cancelled():
                raise Cancelled()
            attempt += 1
            tries += 1
            if top_level:
                self._set(sid, attempts=attempt)
            retryable, delay_floor = True, 0.0
            try:
                return self._timed(lambda: self._invoke(kind, spec, used), timeout), used
            except ApprovalRequired as e:
                if not top_level:
                    raise StepError(f'needs approval ({e}); approvals inside a foreach are not supported')
                raise Waiting({'approval_id': e.approval_id, 'policy': True, 'rule': e.rule})
            except RateLimited as e:
                err = str(e)
                delay_floor = float(e.retry_after or 0)
            except PolicyError as e:
                raise StepError(f'policy: {e}')
            except PermissionError as e:
                raise StepError(str(e))
            except (Waiting, Cancelled):
                raise
            except StepError as e:
                err, retryable = str(e), e.retryable
            except cf.TimeoutError:
                err = f'timed out after {timeout:g}s'
                retryable = bool(retry.get('on_timeout', True))
            except Exception as e:  # noqa: BLE001
                err = str(e) or e.__class__.__name__
            if not retryable or tries >= int(retry.get('max_attempts', 1)):
                suffix = f' (after {tries} attempts)' if tries > 1 else ''
                raise StepError(err + suffix)
            delay = min(float(retry.get('backoff_seconds', 1)) * float(retry.get('backoff_factor', 2)) ** (tries - 1),
                        float(retry.get('max_backoff_seconds', 300)))
            self.sleep(max(delay, delay_floor))

    def _timed(self, fn, timeout: float):
        fut = _call_pool.submit(contextvars.copy_context().run, fn)
        return fut.result(timeout=timeout)

    def _invoke(self, kind: str, spec: Dict[str, Any], used: Dict[str, Any]) -> Any:
        if kind == 'ask':
            from sajha.ai.intelligence import get_intelligence
            svc = get_intelligence()
            if svc is None:
                raise StepError('Ask SAJHA is not available on this server (no LLM provider configured)')
            from sajha.ai.llm.types import RequestContext
            rc = RequestContext(user_id=self.ident.user_id, roles=list(self.ident.roles), is_admin=self.ident.is_admin,
                                trace_id=uuid.uuid4().hex, can_use_tool=self.ident.can_execute)
            res = svc.ask(str(used['question']), rc, model=used.get('model'))
            if res is None:
                raise RuntimeError('Ask SAJHA returned nothing')
            if getattr(res, 'error', ''):
                raise RuntimeError(res.error)
            return res.to_dict()
        name = spec['tool']
        tool = self.svc.get_tool(name)
        if tool is None:
            raise StepError(f'no such tool: {name}', retryable=True)
        if not self.ident.can_execute(name):
            raise PermissionError(f'the run-as identity {self.ident.user_id!r} may not execute {name}')
        result = tool.execute_with_tracking(dict(used))
        if isinstance(result, dict):
            if set(result) == {'error'}:
                raise RuntimeError(str(result['error']))
            if result.get('isError') is True:
                content = result.get('content') or []
                text = ' '.join(c.get('text', '') for c in content if isinstance(c, dict))
                raise RuntimeError(text or 'the tool reported an error')
        return result

    # ── ends ──────────────────────────────────────────────────────

    def output(self) -> Any:
        spec = self.defn.get('output')
        if spec is None:
            return {sid: self.outputs[sid] for sid in self.order if sid in self.outputs}
        try:
            return expr.resolve(spec, self.ctx())
        except Exception as e:
            return {'error': f'output mapping failed: {e}'}

    def _finish(self, status: str, error: Optional[str] = None) -> str:
        out = self.output() if status == 'succeeded' or self.outputs else None
        out = bounded(out, self.svc.output_chars) if out is not None else None
        if self.store.finish_run(self.run_id, status, output=out, error=error):
            self.svc.after_finish(self.run_id, status, out, error)
        return status

    def _cancel(self, inflight) -> str:
        for sid in self.order:
            st = self.records[sid]['status']
            if st in ('pending', 'waiting') or (st == 'running' and sid not in inflight.values()):
                self._set(sid, status='cancelled', error='the run was cancelled', finished_at=time.time())
        for f, sid in list(inflight.items()):
            f.cancel()
            self._set(sid, status='cancelled', error='the run was cancelled while this step ran; its call '
                                                      'could not be interrupted', finished_at=time.time())
        return self._finish('cancelled', error='cancelled')

    def _park(self) -> str:
        """Nothing runnable until a wait ends or an approval is decided: free this worker."""
        if self.store.claim_run(self.run_id, from_status=('running',), to_status='waiting',
                                worker_id=None, expect_worker=self.svc.worker_id):
            return 'waiting'
        return 'lost'
