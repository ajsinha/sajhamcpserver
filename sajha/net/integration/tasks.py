# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net tasks held at the host (design §9 "Tasks"; protocol §15.6).

* **At the host**, :class:`NetHostTasks` keeps the task of a task-augmented forwarded call: a
  :class:`~sajha.core.mcp_tasks.TaskStore` of its own (records in the task record store, under
  ``net:task:<net>/<instance>:``, so they are shared by every worker and, with a durable record store,
  survive a restart), owned by ``<net>/<sending participant>/<user>`` (the user the host resolved), running
  steps 10-12 of §15.4 (:meth:`~sajha.net.routing.HostServer.run_task`) on a worker thread. The task is not
  bounded by the hop's deadline; it ends with the tool, or by ``tasks/cancel``, or by its TTL
  (``mcp.tasks.ttl_ms``). An input request parks it as ``input_required`` until ``tasks/update``.
* **At the home**, a task-augmented call to a proxy whose host lists ``tasks`` is forwarded task-augmented;
  the home's own task (``sajha.core.mcp_tasks``) then follows the host's task through
  :class:`NetRemoteTasks`: ``tasks/get`` at the home relays a signed ``tasks/get`` to the host (the caller's
  identity again) and records what it says, the result screened and checked for residency as a call's
  result is; ``tasks/update`` and ``tasks/cancel`` are relayed. The home's record names the host's task,
  so it survives a restart of the home. A host that does not list ``tasks`` runs the call as before, inside
  the home's task (polling and cancellation still work; the hop's deadline bounds it).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import threading
from typing import Any, Dict, Optional

from sajha.net import EXTENSION_ID
from sajha.net.routing import CODES, RPC_AUTHORIZATION, CallContext, HostRefusal, HostTasks, refusal

logger = logging.getLogger(__name__)

KIND = 'sajhanet'
PREFIX = 'net:task:'


class TaskRefused(Exception):
    """A host task that ended with a net refusal (steps 10 or 12 of §15.4): the task fails with this error."""

    def __init__(self, error: Dict[str, Any]):
        super().__init__(str(error.get('message') or 'refused'))
        self.code = int(error.get('code') or RPC_AUTHORIZATION)
        self.message = str(error.get('message') or 'refused')
        self.data = error.get('data')


def enabled() -> bool:
    """Host-side tasks are on when ``sajhanet.tasks.enabled`` and the MCP tasks extension (``mcp.tasks.enabled``)
    both are."""
    from sajha.core.config import _bool, parse_bool
    from sajha.net.integration.config import _g
    return parse_bool(_g('tasks.enabled', 'true'), True) and _bool('mcp.tasks.enabled', True)


def _ctx_dict(ctx: CallContext) -> Dict[str, Any]:
    d = dataclasses.asdict(ctx)
    for k in ('input_responses', 'mrtr_state', 'mrtr_round', 'state_verified'):
        d.pop(k, None)
    try:
        return json.loads(json.dumps(d, default=str))
    except (TypeError, ValueError):
        return d


class NetHostTasks(HostTasks):
    """The tasks of one net's host (see the module docstring)."""

    def __init__(self, catalogs, net: str, instance: str, records=None):
        from sajha.core.mcp_tasks import TaskStore
        self.catalogs = catalogs
        self.net = net
        self.store = TaskStore(records, prefix=f'{PREFIX}{net}/{instance}:', channel=f'net.tasks.{net}.{instance}')
        self.store.set_resumer(self._runner)

    def create(self, owner: str, ctx: CallContext, arguments: Dict[str, Any]) -> Dict[str, Any]:
        spec = {'ctx': _ctx_dict(ctx), 'arguments': dict(arguments or {})}
        task = self.store.create(owner, self._runner(spec), responses=ctx.input_responses, state=ctx.mrtr_state,
                                 spec=spec)
        return task.envelope()

    def get(self, owner: str, task_id: str) -> Dict[str, Any]:
        from sajha.core.mcp_tasks import TaskNotFound
        try:
            return self.store.get(task_id, owner).detailed()
        except TaskNotFound:
            raise LookupError(task_id)

    def update(self, owner: str, task_id: str, responses: Dict[str, Any]) -> None:
        from sajha.core.mcp_tasks import TaskNotFound
        try:
            self.store.update(task_id, owner, responses)
        except TaskNotFound:
            raise LookupError(task_id)

    def cancel(self, owner: str, task_id: str) -> None:
        from sajha.core.mcp_tasks import TaskNotFound
        try:
            self.store.cancel(task_id, owner)
        except TaskNotFound:
            raise LookupError(task_id)

    def _runner(self, spec: Dict[str, Any]):
        if not isinstance(spec, dict) or not isinstance(spec.get('ctx'), dict):
            return None
        net = self.net

        async def runner(task) -> Dict[str, Any]:
            host = self.catalogs.hosts.get(net)
            if host is None:
                raise TaskRefused({'code': -32603, 'message': f'{net} is not running on this server'})
            fields = {f.name for f in dataclasses.fields(CallContext)}
            ctx = CallContext(**{k: v for k, v in spec['ctx'].items() if k in fields})
            ctx.input_responses = dict(task.responses or {})
            ctx.mrtr_state = dict(task.state or {})
            ctx.state_verified = True
            tctx = ctx.tool_context()
            task.context = tctx

            def work():
                token = tctx.activate()
                try:
                    return host.run_task(ctx, dict(spec.get('arguments') or {}))
                finally:
                    tctx.deactivate(token)
            try:
                return await asyncio.to_thread(work)
            except HostRefusal as e:
                code = RPC_AUTHORIZATION if e.reason == 'contract_conflict' else CODES.get(e.reason, RPC_AUTHORIZATION)
                raise TaskRefused(refusal(code, e.reason, 'host', net, host.node.name, ctx.tool, ctx.trace_id,
                                          executed=e.executed, **(getattr(e, 'extra', None) or {})))
        return runner


# ── the home ────────────────────────────────────────────────────────

#: ``<net>/<instance>`` -> the NetCatalogs of that home (one per process in SAJHA; several in tests)
_HOMES: Dict[str, Any] = {}
_homes_lock = threading.Lock()


def register_home(net: str, instance: str, catalogs) -> None:
    with _homes_lock:
        _HOMES[f'{net}/{instance}'] = catalogs
    from sajha.core.mcp_tasks import register_remote_handler
    register_remote_handler(KIND, _REMOTE)


def unregister_home(catalogs) -> None:
    with _homes_lock:
        for k in [k for k, v in _HOMES.items() if v is catalogs]:
            _HOMES.pop(k, None)


def remote_of(name: str, out: Dict[str, Any], home: str) -> Optional[Dict[str, Any]]:
    """The ``remote`` object of a home task that follows the host's task ``out`` (a CreateTaskResult from the
    host, with the home's ``_meta["io.sajha/net"]``), or None when ``out`` is no task."""
    if not isinstance(out, dict) or out.get('resultType') != 'task' or not isinstance(out.get('taskId'), str):
        return None
    meta = (out.get('_meta') or {}).get(EXTENSION_ID) or {}
    net, host = str(meta.get('net') or ''), str(meta.get('instance') or '')
    if not net or not host:
        return None
    from sajha.federation.security import screen_text
    msg = out.get('statusMessage')
    return {'kind': KIND, 'home': f'{net}/{home}', 'net': net, 'host': host,
            'qualified_name': str(meta.get('qualified_name') or ''), 'name': name, 'task_id': out['taskId'],
            'trace_id': str(meta.get('trace_id') or ''),
            'status': out.get('status') if out.get('status') in ('working', 'input_required') else 'working',
            'status_message': screen_text(msg, 500)[0] if isinstance(msg, str) and msg else None}


class NetRemoteTasks:
    """Follows a host's task from the home's task record (registered as remote-task handler ``sajhanet``)."""

    @staticmethod
    def _home(rec: Dict[str, Any]):
        r = rec.get('remote') or {}
        with _homes_lock:
            cat = _HOMES.get(str(r.get('home') or ''))
        return r, cat

    @staticmethod
    def _user() -> Dict[str, Any]:
        from sajha.net.integration.catalogs import _caller_user
        return _caller_user()

    def refresh(self, rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from sajha.federation.security import screen_text
        r, cat = self._home(rec)
        if cat is None or cat.router is None:
            return None
        user = self._user()
        out = cat.router.task_request(r['net'], r['host'], 'tasks/get', r['task_id'], user=user,
                                      qualified_name=r.get('qualified_name') or '')
        rf = out.get('refusal')
        if rf is not None:
            reason = str(rf.get('reason') or 'error')
            if reason == 'unknown_task':
                text = f'{r["host"]} no longer holds this task (it expired, or the server restarted without it)'
                return {'status': 'failed', 'status_message': text, 'error': {'code': -32603, 'message': text}}
            # the host cannot be asked now: the last known status stands, with the reason
            return {'status_message': f'{r["host"]} could not be asked about the task now ({reason}); '
                                      f'this is its last known status'}
        d = out['result']
        status = d.get('status')
        msg = d.get('statusMessage')
        fields: Dict[str, Any] = {'status_message': screen_text(msg, 500)[0] if isinstance(msg, str) and msg else None}
        if isinstance(d.get('pollIntervalMs'), int) and not isinstance(d.get('pollIntervalMs'), bool):
            fields['poll_interval_ms'] = max(1, min(60000, d['pollIntervalMs']))
        if status == 'working':
            fields['status'] = 'working'
        elif status == 'completed':
            fields['status'] = 'completed'
            fields['result'] = cat.task_result(r, d.get('result') if isinstance(d.get('result'), dict) else {}, user)
        elif status == 'failed':
            err = d.get('error') if isinstance(d.get('error'), dict) else {}
            data = (err.get('data') or {}).get(EXTENSION_ID) if isinstance(err.get('data'), dict) else None
            text = screen_text(str(err.get('message') or 'the task failed at the host'), 500)[0]
            clean: Dict[str, Any] = {'code': err.get('code') if isinstance(err.get('code'), int) else -32603,
                                     'message': text}
            if isinstance(data, dict):
                clean['data'] = {EXTENSION_ID: {k: data[k] for k in ('reason', 'side', 'net', 'instance', 'tool',
                                                                     'trace_id', 'executed') if k in data}}
            fields.update(status='failed', error=clean, status_message=fields['status_message'] or text)
        elif status == 'cancelled':
            fields['status'] = 'cancelled'
        elif status == 'input_required':
            fields.update(status='input_required', pending=_screen_requests(d.get('inputRequests')))
        else:
            return None
        return fields

    def update(self, rec: Dict[str, Any], responses: Dict[str, Any]) -> None:
        r, cat = self._home(rec)
        if cat is None or cat.router is None:
            raise RuntimeError('SAJHA Net is not running here; the answer cannot reach the host')
        user = self._user()
        checked = cat.check_task_answers(r, responses, user)       # residency: answers leave like arguments
        out = cat.router.task_request(r['net'], r['host'], 'tasks/update', r['task_id'], user=user,
                                      input_responses=checked, qualified_name=r.get('qualified_name') or '')
        if out.get('refusal') is not None:
            raise RuntimeError(f'{r["host"]} did not take the answer ({out["refusal"].get("reason")})')

    def cancel(self, rec: Dict[str, Any]) -> None:
        r, cat = self._home(rec)
        if cat is None or cat.router is None:
            return
        out = cat.router.task_request(r['net'], r['host'], 'tasks/cancel', r['task_id'], user=self._user(),
                                      qualified_name=r.get('qualified_name') or '')
        if out.get('refusal') is not None:
            logger.warning(f'SAJHA Net: tasks/cancel did not reach {r["host"]}: {out["refusal"].get("reason")}')


def _screen_requests(requests: Any) -> Dict[str, Any]:
    """A host's input requests are untrusted text, like its results (as for a call's input requests)."""
    import copy
    from sajha.federation.security import screen_text
    out: Dict[str, Any] = {}
    for key, req in (requests.items() if isinstance(requests, dict) else []):
        req = copy.deepcopy(req) if isinstance(req, dict) else {}
        p = req.get('params') if isinstance(req.get('params'), dict) else None
        if p is not None and isinstance(p.get('message'), str):
            p['message'] = screen_text(p['message'], 4000)[0]
        out[str(key)] = req
    return out


_REMOTE = NetRemoteTasks()
