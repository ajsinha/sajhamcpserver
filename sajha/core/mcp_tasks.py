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

Store: in memory, in the server's event loop, scoped to the caller (a task is
invisible to other users).  It is *not* the /admin/async-tasks executor
(sajha.core.async_executor): that one is a fire-and-forget worker pool that
delivers results to webhooks/Kafka/files, cannot pause for client input and
cannot cancel a running job — the opposite of what SEP-2663 needs.  Because
the store is per process, run a single worker (or sticky routing) when tasks
are used.

Input during a task (MRTR on tasks): when the tool raises ``InputRequired`` the
task parks as ``input_required`` with the pending ``inputRequests``;
``tasks/update`` may answer them one at a time, and once every pending key is
answered the tool is run again with all answers gathered so far.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

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


@dataclass
class McpTask:
    task_id: str
    owner: Optional[str]
    runner: Callable[["McpTask"], Awaitable[Dict[str, Any]]]
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


class TaskStore:
    def __init__(self):
        self._tasks: Dict[str, McpTask] = {}
        self._lock = threading.Lock()

    # -- config ---------------------------------------------------------

    @staticmethod
    def _cfg():
        from sajha.core.config import _int
        return (max(1000, _int("mcp.tasks.ttl_ms", 3600000)),
                max(1, _int("mcp.tasks.poll_interval_ms", 500)),
                max(1, _int("mcp.tasks.max_tasks", 1000)))

    # -- lifecycle ------------------------------------------------------

    def create(self, owner: Optional[str], runner: Callable[[McpTask], Awaitable[Dict[str, Any]]],
               *, responses: Optional[Dict[str, Any]] = None, state: Optional[Dict[str, Any]] = None) -> McpTask:
        """Register the task (so tasks/get resolves at once), then start it."""
        ttl_ms, poll_ms, max_tasks = self._cfg()
        self._purge(max_tasks - 1)
        task = McpTask(task_id=uuid.uuid4().hex, owner=owner, runner=runner,
                       ttl_ms=ttl_ms, poll_interval_ms=poll_ms,
                       responses=dict(responses or {}), state=dict(state or {}))
        with self._lock:
            if len(self._tasks) >= max_tasks:
                raise OverflowError("too many active tasks; retry later")
            self._tasks[task.task_id] = task
        self._start(task)
        return task

    def _start(self, task: McpTask) -> None:
        task._job = asyncio.get_running_loop().create_task(self._drive(task))

    async def _drive(self, task: McpTask) -> None:
        from sajha.core.mcp_2025_11_25 import MCPError
        try:
            result = await task.runner(task)
        except InputRequired as ir:
            task.pending = {k: v for k, v in ir.requests.items() if k not in task.responses}
            task.state.update(ir.state)
            task.touch("input_required", "Waiting for client input (tasks/update)")
            return
        except asyncio.CancelledError:
            if not task.terminal:
                task.touch("cancelled", "Cancelled")
            return
        except MCPError as e:
            task.error = _error_object(e.code, e.message, e.data)
            task.touch("failed", e.message)
            return
        except Exception as e:
            code = getattr(e, "code", None)
            if isinstance(code, int):
                task.error = _error_object(code, getattr(e, "message", str(e)), getattr(e, "data", None))
            else:
                logger.error(f"Task {task.task_id} failed: {e}", exc_info=True)
                task.error = _error_object(-32603, "Internal error")
            task.touch("failed", task.error["message"])
            return
        if task.status == "cancelled":       # cancelled while finishing: keep the cancel
            return
        task.result = result
        task.touch("completed")

    def get(self, task_id: Any, owner: Optional[str]) -> McpTask:
        self._purge()
        with self._lock:
            task = self._tasks.get(task_id) if isinstance(task_id, str) else None
        if task is None or task.owner != owner:
            raise TaskNotFound(task_id)
        return task

    def update(self, task_id: Any, owner: Optional[str], input_responses: Dict[str, Any]) -> None:
        task = self.get(task_id, owner)
        if task.status != "input_required":
            return                                       # nothing pending: ack, ignore
        answered = [k for k in input_responses if k in task.pending]
        if not answered:
            return
        for key in answered:
            task.responses[key] = input_responses[key]
            task.pending.pop(key, None)
        if task.pending:
            task.touch("input_required", "Waiting for client input (tasks/update)")
            return
        task.touch("working")
        self._start(task)

    def cancel(self, task_id: Any, owner: Optional[str]) -> None:
        task = self.get(task_id, owner)
        if task.terminal:
            return                                       # idempotent
        task.touch("cancelled", "Cancelled by client")
        if task.context is not None:
            try:
                task.context.cancel()
            except Exception:
                pass
        if task._job is not None and not task._job.done():
            task._job.cancel()

    # -- housekeeping ---------------------------------------------------

    def _purge(self, keep: Optional[int] = None) -> None:
        now = time.time()
        with self._lock:
            expired = [t for t in self._tasks.values()
                       if now > max(t.created_at, t.updated_at) + t.ttl_ms / 1000.0]
            for t in expired:
                self._tasks.pop(t.task_id, None)
            if keep is not None and len(self._tasks) > keep:
                done = sorted((t for t in self._tasks.values() if t.terminal), key=lambda t: t.updated_at)
                for t in done[:len(self._tasks) - keep]:
                    self._tasks.pop(t.task_id, None)
        for t in expired:
            if t._job is not None and not t._job.done():
                t._job.cancel()

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)


def _error_object(code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return err


_store = TaskStore()


def get_task_store() -> TaskStore:
    return _store
