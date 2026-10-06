"""
Tasks extension ``io.modelcontextprotocol/tasks`` (SEP-2663) for the MCP 2026-07-28 path.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A task-supporting tool called by a client that declares the extension (in the
per-request ``_meta["io.modelcontextprotocol/clientCapabilities"].extensions``)
answers with a flat ``CreateTaskResult`` (``resultType: "task"`` + the task
fields) and keeps running here.  The client then uses

    tasks/get     -> DetailedTask: status (+ inlined result / error / inputRequests)
    tasks/update  -> deliver inputResponses to an ``input_required`` task (ack)
    tasks/cancel  -> cancel (ack; idempotent on terminal tasks)

There is no tasks/list or tasks/result on this surface (both -32601), and the
legacy 2025-11-25 core ``tasks/*`` (sajha.core.mcp_2025_11_25) are untouched.

Store: task *records* (status, result, error, pending input, answers, tool
state, owner, the worker running it) live in the task record store
(sajha.core.state.get_task_record_store): process memory with the default
``state.backend: memory``; the database when ``state.tasks.durable`` is on
(default with the redis and database backends), so records are visible to
every worker and survive a restart.  The running coroutine stays in the event
loop of the worker that started it.  Records are scoped to the caller (a task
is invisible to other users).

Across workers: ``tasks/get`` reads the record anywhere; ``tasks/cancel`` marks
the record and relays the cancel to the running worker over pub/sub;
``tasks/update`` may be answered on any worker, which rebuilds the runner from
the stored call spec (tool, arguments, caller) and runs the next round itself.
A ``working`` task whose worker stopped heart-beating is failed on read
("orphaned"): tools are not assumed idempotent, so it is never re-run.

It is *not* the /admin/async-tasks executor (sajha.core.async_executor): that
one is a fire-and-forget worker pool that delivers results to
webhooks/Kafka/files, cannot pause for client input and cannot cancel a
running job — the opposite of what SEP-2663 needs.

Input during a task (MRTR on tasks): when the tool raises ``InputRequired`` the
task parks as ``input_required`` with the pending ``inputRequests``;
``tasks/update`` may answer them one at a time, and once every pending key is
answered the tool is run again with all answers gathered so far.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sajha.core.mcp_mrtr import InputRequired

logger = logging.getLogger(__name__)

TASKS_EXTENSION = "io.modelcontextprotocol/tasks"
TERMINAL_STATUSES = ("completed", "failed", "cancelled")

# Tool-level declaration (tools/list ``execution.taskSupport``)
TASK_SUPPORT_VALUES = ("forbidden", "optional", "required")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def client_declares_tasks(client_capabilities: Dict[str, Any]) -> bool:
    ext = (client_capabilities or {}).get("extensions")
    return isinstance(ext, dict) and TASKS_EXTENSION in ext


def required_capability() -> Dict[str, Any]:
    return {"extensions": {TASKS_EXTENSION: {}}}


_KEY = "mcp:task:"
_CHANNEL = "mcp.tasks"
ORPHANED_MESSAGE = "The worker running this task stopped before it finished"

# record fields persisted in the task record store
_RECORD_FIELDS = ("task_id", "owner", "ttl_ms", "poll_interval_ms", "status", "status_message",
                  "created_at", "updated_at", "result", "error", "pending", "responses", "state",
                  "worker", "spec")


@dataclass
class McpTask:
    task_id: str
    owner: Optional[str]
    runner: Optional[Callable[["McpTask"], Awaitable[Dict[str, Any]]]]
    ttl_ms: int
    poll_interval_ms: int
    status: str = "working"
    status_message: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    pending: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # inputRequests still unanswered
    responses: Dict[str, Any] = field(default_factory=dict)            # every answer gathered so far
    state: Dict[str, Any] = field(default_factory=dict)                # tool state across input rounds
    worker: Optional[str] = None                                       # worker running / that ran it
    spec: Optional[Dict[str, Any]] = None                              # how to rebuild the runner elsewhere
    context: Any = None                                                # the running ModernToolContext
    _job: Optional[asyncio.Task] = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def touch(self, status: Optional[str] = None, message: Optional[str] = None) -> None:
        if status:
            self.status = status
        self.status_message = message
        self.updated_at = time.time()

    def record(self) -> Dict[str, Any]:
        return {f: getattr(self, f) for f in _RECORD_FIELDS}

    def absorb(self, rec: Dict[str, Any]) -> "McpTask":
        for f in _RECORD_FIELDS:
            if f in rec:
                setattr(self, f, rec[f])
        return self

    @classmethod
    def from_record(cls, rec: Dict[str, Any]) -> "McpTask":
        return cls(task_id=rec["task_id"], owner=rec.get("owner"), runner=None,
                   ttl_ms=rec["ttl_ms"], poll_interval_ms=rec["poll_interval_ms"]).absorb(rec)

    def envelope(self) -> Dict[str, Any]:
        """The Task fields shared by CreateTaskResult and DetailedTask."""
        out = {
            "taskId": self.task_id,
            "status": self.status,
            "createdAt": _iso(self.created_at),
            "lastUpdatedAt": _iso(self.updated_at),
            "ttlMs": self.ttl_ms,
            "pollIntervalMs": self.poll_interval_ms,
        }
        if self.status_message:
            out["statusMessage"] = self.status_message
        return out

    def detailed(self) -> Dict[str, Any]:
        """DetailedTask for tasks/get: result / error / inputRequests inlined by status."""
        out = self.envelope()
        if self.status == "completed" and self.result is not None:
            out["result"] = self.result
        elif self.status == "failed" and self.error is not None:
            out["error"] = self.error
        elif self.status == "input_required":
            out["inputRequests"] = dict(self.pending)
        return out


class TaskNotFound(LookupError):
    pass


#: rebuilds a runner from a stored spec (registered by the 2026-07-28 server); None = cannot
Resumer = Callable[[Dict[str, Any]], Optional[Callable[[McpTask], Awaitable[Dict[str, Any]]]]]


class TaskStore:
    def __init__(self, records=None):
        self._records = records                    # StateStore; None = sajha.core.state's task store
        self._live: Dict[str, McpTask] = {}        # tasks whose runner lives in this process
        self._lock = threading.Lock()
        self._resumer: Optional[Resumer] = None
        self._relay = None                         # shared StateStore carrying cancels
        self._unsubscribe = None

    @property
    def records(self):
        if self._records is not None:
            return self._records
        from sajha.core.state import get_task_record_store
        return get_task_record_store()

    # -- config ---------------------------------------------------------

    @staticmethod
    def _cfg():
        from sajha.core.config import _int
        return (max(1000, _int("mcp.tasks.ttl_ms", 3600000)),
                max(1, _int("mcp.tasks.poll_interval_ms", 500)),
                max(1, _int("mcp.tasks.max_tasks", 1000)))

    def set_resumer(self, resumer: Optional[Resumer]) -> None:
        self._resumer = resumer

    def attach(self) -> None:
        """Listen for cancels relayed from other workers (shared state store only)."""
        from sajha.core.state import get_state_store
        relay = get_state_store()
        if not relay.shared or self._relay is relay:
            return
        if self._unsubscribe:
            self._unsubscribe()
        self._relay = relay
        self._unsubscribe = relay.subscribe(_CHANNEL, self._on_message)

    def _on_message(self, message: Dict[str, Any]) -> None:
        if message.get("op") != "cancel":
            return
        with self._lock:
            task = self._live.get(message.get("task_id"))
        if task is not None:
            self._cancel_local(task, threadsafe=True)

    # -- records ----------------------------------------------------------

    def _save(self, task: McpTask) -> None:
        self.records.set(_KEY + task.task_id, task.record(), ttl=task.ttl_ms / 1000.0)

    def _write(self, task_id: str, fn: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]],
               ttl_ms: int) -> Optional[Dict[str, Any]]:
        """Atomic change of a record; ``fn`` returns the changed record or None to leave it."""
        def apply(cur):
            if cur is None:
                return None
            new = fn(dict(cur))
            return cur if new is None else new
        return self.records.update(_KEY + task_id, apply, ttl=ttl_ms / 1000.0)

    # -- lifecycle ------------------------------------------------------

    def create(self, owner: Optional[str], runner: Callable[[McpTask], Awaitable[Dict[str, Any]]],
               *, responses: Optional[Dict[str, Any]] = None, state: Optional[Dict[str, Any]] = None,
               spec: Optional[Dict[str, Any]] = None) -> McpTask:
        """Register the task (so tasks/get resolves at once), then start it."""
        from sajha.core.state import WORKER_ID
        ttl_ms, poll_ms, max_tasks = self._cfg()
        self._purge(max_tasks - 1)
        task = McpTask(task_id=uuid.uuid4().hex, owner=owner, runner=runner,
                       ttl_ms=ttl_ms, poll_interval_ms=poll_ms,
                       responses=dict(responses or {}), state=dict(state or {}),
                       worker=WORKER_ID, spec=_jsonable(spec))
        with self._lock:
            if self._size_locked() >= max_tasks:
                raise OverflowError("too many active tasks; retry later")
            self._live[task.task_id] = task
        self._save(task)
        if self.records.shared:
            self.attach()
        self._start(task)
        return task

    def _start(self, task: McpTask) -> None:
        task._job = asyncio.get_running_loop().create_task(self._drive(task))

    async def _drive(self, task: McpTask) -> None:
        from sajha.core.mcp_2025_11_25 import MCPError
        try:
            result = await task.runner(task)
        except InputRequired as ir:
            pending = {k: v for k, v in ir.requests.items() if k not in task.responses}
            self._settle(task, "input_required", "Waiting for client input (tasks/update)",
                         pending=pending, state={**task.state, **ir.state})
            return
        except asyncio.CancelledError:
            self._settle(task, "cancelled", "Cancelled")
            return
        except MCPError as e:
            self._settle(task, "failed", e.message, error=_error_object(e.code, e.message, e.data))
            return
        except Exception as e:
            code = getattr(e, "code", None)
            if isinstance(code, int):
                error = _error_object(code, getattr(e, "message", str(e)), getattr(e, "data", None))
            else:
                logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
                error = _error_object(-32603, "Internal error")
            self._settle(task, "failed", error["message"], error=error)
            return
        self._settle(task, "completed", None, result=result)

    def _settle(self, task: McpTask, status: str, message: Optional[str], **fields) -> None:
        """Record the outcome of a run, unless the task was cancelled meanwhile (the cancel wins)."""
        def fn(rec):
            if rec.get("status") in TERMINAL_STATUSES:
                return None
            rec.update(fields, status=status, status_message=message, updated_at=time.time())
            return rec
        try:
            rec = self._write(task.task_id, fn, task.ttl_ms)
        except Exception as e:
            logger.error(f"Task {task.task_id}: could not record {status}: {e}")
            rec = None
        if rec is None:                      # cancelled meanwhile, or the record expired
            try:
                rec = self.records.get(_KEY + task.task_id)
            except Exception:
                rec = None
        if rec is not None:
            task.absorb(rec)
        else:
            for k, v in fields.items():
                setattr(task, k, v)
            task.touch(status, message)
        if task.terminal:
            with self._lock:
                self._live.pop(task.task_id, None)

    def get(self, task_id: Any, owner: Optional[str]) -> McpTask:
        self._purge()
        rec = self.records.get(_KEY + task_id) if isinstance(task_id, str) else None
        if rec is None or rec.get("owner") != owner:
            raise TaskNotFound(task_id)
        rec = self._reap_orphan(rec)
        with self._lock:
            live = self._live.get(task_id)
        if live is not None:
            return live.absorb(rec)
        return McpTask.from_record(rec)

    def _reap_orphan(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        """A working task whose worker is gone will never finish: fail it."""
        from sajha.core.state import worker_alive
        if rec.get("status") != "working" or worker_alive(rec.get("worker"), self.records):
            return rec
        worker = rec.get("worker")

        def fn(cur):
            if cur.get("status") != "working" or cur.get("worker") != worker:
                return None
            cur.update(status="failed", status_message=ORPHANED_MESSAGE, updated_at=time.time(),
                       error=_error_object(-32603, ORPHANED_MESSAGE))
            return cur
        logger.warning(f"Task {rec['task_id']}: worker {worker} is gone; marking it failed")
        return self._write(rec["task_id"], fn, rec["ttl_ms"]) or rec

    def update(self, task_id: Any, owner: Optional[str], input_responses: Dict[str, Any]) -> None:
        from sajha.core.state import WORKER_ID
        task = self.get(task_id, owner)
        if task.status != "input_required":
            return                                       # nothing pending: ack, ignore
        answered = [k for k in input_responses if k in task.pending]
        if not answered:
            return
        claimed: List[bool] = []

        def fn(rec):
            claimed.clear()
            if rec.get("status") != "input_required":
                return None
            pending = dict(rec.get("pending") or {})
            responses = dict(rec.get("responses") or {})
            for key in input_responses:
                if key in pending:
                    responses[key] = input_responses[key]
                    pending.pop(key, None)
            rec.update(pending=pending, responses=responses, updated_at=time.time())
            if pending:
                rec.update(status="input_required", status_message="Waiting for client input (tasks/update)")
            else:
                rec.update(status="working", status_message=None, worker=WORKER_ID)
                claimed.append(True)
            return rec

        rec = self._write(task.task_id, fn, task.ttl_ms)
        if not claimed or rec is None:
            return
        with self._lock:
            live = self._live.get(task.task_id)
        if live is None:
            runner = self._resumer(rec["spec"]) if (self._resumer and rec.get("spec")) else None
            if runner is None:
                self._settle(McpTask.from_record(rec), "failed", "This task cannot be resumed on this worker",
                             error=_error_object(-32603, "This task cannot be resumed on this worker"))
                return
            live = McpTask.from_record(rec)
            live.runner = runner
            with self._lock:
                self._live[live.task_id] = live
        live.absorb(rec)
        self._start(live)

    def cancel(self, task_id: Any, owner: Optional[str]) -> None:
        task = self.get(task_id, owner)
        if task.terminal:
            return                                       # idempotent

        def fn(rec):
            if rec.get("status") in TERMINAL_STATUSES:
                return None
            rec.update(status="cancelled", status_message="Cancelled by client", updated_at=time.time())
            return rec
        rec = self._write(task.task_id, fn, task.ttl_ms)
        with self._lock:
            live = self._live.get(task.task_id)
        if live is not None:
            if rec is not None:
                live.absorb(rec)
            self._cancel_local(live)
        elif self._relay is not None:
            self._relay.publish(_CHANNEL, {"op": "cancel", "task_id": task.task_id})

    def _cancel_local(self, task: McpTask, threadsafe: bool = False) -> None:
        if task.context is not None:
            try:
                task.context.cancel()
            except Exception:
                pass
        job = task._job
        if job is not None and not job.done():
            if threadsafe:
                try:
                    job.get_loop().call_soon_threadsafe(job.cancel)
                except RuntimeError:
                    pass
            else:
                job.cancel()
        if not (job is not None and not job.done()):
            with self._lock:
                self._live.pop(task.task_id, None)

    # -- housekeeping ---------------------------------------------------

    def _size_locked(self) -> int:
        n = self.records.count(_KEY)
        return n if n is not None else len(self._live)

    def _purge(self, keep: Optional[int] = None) -> None:
        """Drop expired records (the store's TTL does that) and, over ``keep``, the oldest finished ones."""
        store = self.records
        if keep is not None and store.count(_KEY) is not None and store.count(_KEY) > keep:
            done = sorted((rec for _, rec in store.scan(_KEY) if rec.get("status") in TERMINAL_STATUSES),
                          key=lambda r: r.get("updated_at", 0))
            for rec in done[:store.count(_KEY) - keep]:
                store.delete(_KEY + rec["task_id"])
        if keep is None:
            return
        # forget (and stop) local runners whose record has expired
        with self._lock:
            live = list(self._live.values())
        gone = [t for t in live if store.get(_KEY + t.task_id) is None]
        with self._lock:
            for t in gone:
                self._live.pop(t.task_id, None)
        for t in gone:
            if t._job is not None and not t._job.done():
                t._job.cancel()

    def __len__(self) -> int:
        with self._lock:
            return self._size_locked()


def _jsonable(spec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if spec is None:
        return None
    try:
        return json.loads(json.dumps(spec))
    except (TypeError, ValueError):
        return None          # cannot be stored: the task only resumes on the worker that created it


def _error_object(code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


_store = TaskStore()


def get_task_store() -> TaskStore:
    return _store
