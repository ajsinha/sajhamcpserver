"""
Per-call context for tools on the MCP 2026-07-28 path.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A tool (an async conformance fixture, or a regular SAJHA tool running in the
thread pool) reaches the client only through this object:

* ``progress()`` -> ``notifications/progress`` when the request carried
  ``_meta.progressToken`` and the response is streamed (SSE);
* ``log()``      -> ``notifications/message``, only at or above the request's
  ``_meta["io.modelcontextprotocol/logLevel"]`` — never when it is absent;
* ``input_responses`` / ``state`` / ``require_input()`` -> MRTR (SEP-2322):
  the tool raises :class:`~sajha.core.mcp_mrtr.InputRequired` and is called
  again, from scratch, with the answers;
* ``cancelled`` -> set when the client closed the response stream (or a task
  was cancelled); long-running tools may poll it to stop early.

There are no server -> client JSON-RPC *requests* on this path (stateless
servers must use MRTR), so ``request()`` always fails.

Regular SAJHA tools have no ``ctx`` argument; they may still report progress
from their (thread-pool) ``execute`` via the module-level helpers::

    from sajha.core.mcp_tool_context import report_progress, report_log, is_cancelled
    report_progress(10, 100, "fetched page 1")
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from typing import Any, Callable, Dict, Mapping, Optional

from sajha.core.mcp_mrtr import InputRequired

LOG_LEVELS = ("debug", "info", "notice", "warning", "error", "critical", "alert", "emergency")
_LEVEL_RANK = {name: i for i, name in enumerate(LOG_LEVELS)}

_current: contextvars.ContextVar[Optional["ModernToolContext"]] = \
    contextvars.ContextVar("sajha_mcp_tool_context", default=None)


class ModernToolContext:
    def __init__(self, *, client_capabilities: Optional[Mapping[str, Any]] = None,
                 progress_token: Any = None, log_level: Optional[str] = None,
                 emit: Optional[Callable[[Dict[str, Any]], None]] = None,
                 input_responses: Optional[Dict[str, Any]] = None,
                 state: Optional[Dict[str, Any]] = None, state_verified: bool = False):
        self.client_capabilities = dict(client_capabilities or {})
        self.progress_token = progress_token
        self.log_level = log_level if log_level in _LEVEL_RANK else None
        self._emit = emit                       # None -> notifications are dropped
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.input_responses: Dict[str, Any] = dict(input_responses or {})
        self.state: Dict[str, Any] = dict(state or {})
        self.state_verified = state_verified    # the retry carried a valid requestState
        self.tool_name: Optional[str] = None    # the tools/call target (LLM-tool sampling asks only for it)
        self._cancelled = threading.Event()

    # -- binding ----------------------------------------------------

    def bind_loop(self) -> "ModernToolContext":
        """Remember the running loop so worker threads can emit safely."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        return self

    def activate(self) -> contextvars.Token:
        return _current.set(self)

    @staticmethod
    def deactivate(token: contextvars.Token) -> None:
        _current.reset(token)

    # -- notifications ------------------------------------------------

    def _send(self, method: str, params: Dict[str, Any]) -> None:
        if self._emit is None or self._cancelled.is_set():
            return
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        loop = self._loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if loop is not None and running is not loop:
            loop.call_soon_threadsafe(self._emit, message)   # from a worker thread
        else:
            self._emit(message)

    def should_log(self, level: str) -> bool:
        return self.log_level is not None and _LEVEL_RANK.get(level, 0) >= _LEVEL_RANK[self.log_level]

    def emit_progress(self, progress: float, total: Optional[float] = None, message: Optional[str] = None) -> None:
        if self.progress_token is None:
            return
        params: Dict[str, Any] = {"progressToken": self.progress_token, "progress": progress}
        if total is not None:
            params["total"] = total
        if message:
            params["message"] = message
        self._send("notifications/progress", params)

    def emit_log(self, level: str, data: Any, logger_name: Optional[str] = None) -> None:
        if not self.should_log(level):
            return
        params: Dict[str, Any] = {"level": level, "data": data}
        if logger_name:
            params["logger"] = logger_name
        self._send("notifications/message", params)

    # async API (same shape as the legacy ToolCallContext used by the fixtures)
    async def progress(self, progress: float, total: Optional[float] = None, message: Optional[str] = None):
        self.emit_progress(progress, total, message)

    async def log(self, level: str, data: Any, logger_name: Optional[str] = None):
        self.emit_log(level, data, logger_name)

    async def notify(self, method: str, params: Dict[str, Any]):
        if method == "notifications/message":
            self.emit_log(params.get("level", "info"), params.get("data"), params.get("logger"))
        elif method == "notifications/progress":
            self.emit_progress(params.get("progress", 0), params.get("total"), params.get("message"))

    # -- capabilities / MRTR ---------------------------------------------

    def client_supports(self, capability: str) -> bool:
        return capability in self.client_capabilities

    def require_input(self, requests: Mapping[str, Dict[str, Any]], state: Optional[Dict[str, Any]] = None):
        raise InputRequired(requests, state)

    async def request(self, method: str, params: Dict[str, Any], timeout: float = 120.0) -> Dict:
        raise RuntimeError(f"{method}: a stateless (2026-07-28) server cannot send requests to the "
                           f"client; use an InputRequiredResult (MRTR) instead")

    # -- cancellation ------------------------------------------------------

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


# ── helpers for regular (synchronous, thread-pool) SAJHA tools ──────

def current_context() -> Optional[ModernToolContext]:
    return _current.get()


def report_progress(progress: float, total: Optional[float] = None, message: Optional[str] = None) -> None:
    """Report progress from inside a tool; a no-op unless the caller asked for progress."""
    ctx = _current.get()
    if ctx is not None:
        ctx.emit_progress(progress, total, message)


def report_log(level: str, data: Any, logger_name: Optional[str] = None) -> None:
    """Send a log message to the client; a no-op unless the request set a logLevel <= level."""
    ctx = _current.get()
    if ctx is not None:
        ctx.emit_log(level, data, logger_name)


def is_cancelled() -> bool:
    """True once the client went away / the task was cancelled; tools may stop early."""
    ctx = _current.get()
    if ctx is not None and ctx.cancelled:
        return True
    from sajha.core import mcp_cancellation     # a 2025-11-25 notifications/cancelled
    return mcp_cancellation.is_cancelled()
