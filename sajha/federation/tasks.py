"""
SAJHA MCP Server — upstream tasks: a proxied tool that answers with a task.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

SAJHA's shared connection to a 2026-07-28 upstream declares the tasks extension
(``io.modelcontextprotocol/tasks``, SEP-2663). A tool that then answers ``tools/call`` with a
task (``resultType: "task"``) is followed here: SAJHA polls ``tasks/get`` at the upstream's
``pollIntervalMs`` until the task ends and returns its result as the call's own. When SAJHA's
call is cancelled (its caller cancelled, closed the stream, or cancelled SAJHA's own task),
``tasks/cancel`` goes to the upstream. To SAJHA's caller the call is an ordinary call, or,
when the caller asked for a task, a SAJHA task (polled and cancelled through SAJHA).
Design: docs/architecture/Federation.md (section 7, "Tasks").
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Literal, Optional

import anyio
from pydantic import ConfigDict, TypeAdapter
from pydantic.alias_generators import to_camel

from mcp.client.extension import ClientExtension, ResultClaim
from mcp_types import CallToolResult, Request, RequestParams, Result, TextContent

logger = logging.getLogger(__name__)

TASKS_EXTENSION = 'io.modelcontextprotocol/tasks'
_MIN_POLL, _MAX_POLL = 0.05, 5.0


class CreateTaskResult(Result):
    """The upstream's answer to a task-augmented tools/call (a flat CreateTaskResult)."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra='allow')
    result_type: Literal['task'] = 'task'
    task_id: str
    status: str = 'working'
    poll_interval_ms: Optional[int] = None
    status_message: Optional[str] = None


class _TaskIdParams(RequestParams):
    task_id: str


class _GetTask(Request[_TaskIdParams, Literal['tasks/get']]):
    name_param = 'taskId'


class _CancelTask(Request[_TaskIdParams, Literal['tasks/cancel']]):
    name_param = 'taskId'


_ANY = TypeAdapter(Dict[str, Any])


async def _unexpected(created: CreateTaskResult, ctx) -> CallToolResult:     # never used: SAJHA resolves itself
    return await follow(ctx.session, created, ctx.read_timeout_seconds)


class TasksExtension(ClientExtension):
    identifier = TASKS_EXTENSION

    def claims(self):
        return (ResultClaim(result_type='task', model=CreateTaskResult, resolve=_unexpected),)


def _interval(ms: Any) -> float:
    try:
        return max(_MIN_POLL, min(float(ms) / 1000.0, _MAX_POLL))
    except (TypeError, ValueError):
        return 0.5


def _error(text: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type='text', text=text)], is_error=True)


async def cancel(session, task_id: str) -> None:
    """tasks/cancel, best effort and shielded (the caller is already being cancelled)."""
    with anyio.CancelScope(shield=True):
        with anyio.move_on_after(5.0):
            try:
                await session.send_request(_CancelTask(method='tasks/cancel', params=_TaskIdParams(task_id=task_id)),
                                           _ANY, 5.0)
            except Exception as e:
                logger.debug(f'federation: tasks/cancel {task_id}: {e}')


async def follow(session, created: CreateTaskResult, request_timeout: Optional[float] = None) -> CallToolResult:
    """Poll the upstream's task to its end; cancel it upstream when this coroutine is cancelled."""
    task_id = created.task_id
    interval = _interval(created.poll_interval_ms or 500)
    try:
        while True:
            raw = await session.send_request(_GetTask(method='tasks/get', params=_TaskIdParams(task_id=task_id)),
                                             _ANY, request_timeout)
            status = raw.get('status')
            if status == 'completed':
                result = dict(raw.get('result') or {})
                result.pop('resultType', None)
                return CallToolResult.model_validate(result)
            if status == 'failed':
                err = raw.get('error') or {}
                return _error(f'the upstream task failed: {err.get("message") if isinstance(err, dict) else err}')
            if status == 'cancelled':
                return _error('the upstream cancelled the task')
            if status == 'input_required':
                await cancel(session, task_id)
                return _error('the upstream task asked for client input, which SAJHA does not relay into a '
                              'proxied task; the task was cancelled')
            interval = _interval(raw.get('pollIntervalMs') or interval * 1000)
            await asyncio.sleep(interval)
    except BaseException:
        await cancel(session, task_id)
        raise
