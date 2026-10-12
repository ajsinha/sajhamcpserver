"""
Change bus — fan-out of "something the client may have cached changed" events.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Producers (any thread):
    * ToolsRegistry      register / unregister / enable / disable / reload  -> TOOLS
    * PromptsRegistry    create / update / delete / reload                   -> PROMPTS
    Both also change a catalog resource (sajha://tools/catalog,
    sajha://prompts/catalog), so they publish RESOURCES and a
    RESOURCE_UPDATED event for that URI as well.
    * TaskStore (sajha.core.mcp_tasks)  a task record changed           -> TASK {task id}
      (to subscriptions only: synchronous listeners never see TASK events)

Consumers (asyncio):
    * MCP 2026-07-28 ``subscriptions/listen`` streams (sajha.core.mcp_modern)
    * the legacy 2024-11-05 HTTP+SSE stream (GET /mcp/sse)
    * the WebSocket transport (/mcp/ws)

Across workers: when a shared state store is configured (``state.backend``
redis or database) :meth:`ChangeBus.attach_store` makes every publish also go
to the store's ``changes`` channel, and events from other workers are fanned
out to this worker's subscriptions and to the synchronous listeners registered
with ``remote=True`` (the workflow service's event triggers); other listeners
stay local.  Every event carries an ``id`` (equal on every worker that sees it)
so such a listener can claim it once cluster-wide.  See
docs/architecture/Scaling and State.md.

Each consumer holds a :class:`Subscription` bound to its event loop.  Publishing
is thread-safe (``loop.call_soon_threadsafe``) and coalescing: while an event is
queued but not yet delivered to a subscriber, an identical event is dropped, so
a bulk reload of 200 tools produces one ``tools/list_changed`` per subscriber,
not 200.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, FrozenSet, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

TOOLS = "tools"                         # notifications/tools/list_changed
PROMPTS = "prompts"                     # notifications/prompts/list_changed
RESOURCES = "resources"                 # notifications/resources/list_changed
RESOURCE_UPDATED = "resource_updated"   # notifications/resources/updated {uri}
TASK = "task"                           # notifications/tasks {DetailedTask}; ``uri`` holds the task id

TOOL_CATALOG_URI = "sajha://tools/catalog"
PROMPT_CATALOG_URI = "sajha://prompts/catalog"

_NOTIFICATION_METHODS = {
    TOOLS: "notifications/tools/list_changed",
    PROMPTS: "notifications/prompts/list_changed",
    RESOURCES: "notifications/resources/list_changed",
    RESOURCE_UPDATED: "notifications/resources/updated",
    TASK: "notifications/tasks",
}

#: kinds whose events are keyed (``ChangeEvent.uri``): a resource URI, a task id
_KEYED = (RESOURCE_UPDATED, TASK)

_CLOSED = object()   # sentinel: the bus is shutting down

CHANGES_CHANNEL = "changes"   # state-store channel carrying events between workers


@dataclass(frozen=True)
class ChangeEvent:
    kind: str
    uri: Optional[str] = None      # RESOURCE_UPDATED: the resource URI; TASK: the task id
    #: one publish's id, the same on every worker that sees it (not part of equality: coalescing
    #: treats two publishes of the same change as one)
    id: Optional[str] = field(default=None, compare=False, hash=False)

    def notification(self) -> dict:
        """The JSON-RPC notification for this event (without any _meta tagging).  A TASK event
        carries only the id here: a listen stream reads the record and sends the DetailedTask."""
        msg = {"jsonrpc": "2.0", "method": _NOTIFICATION_METHODS[self.kind]}
        if self.kind == RESOURCE_UPDATED:
            msg["params"] = {"uri": self.uri}
        elif self.kind == TASK:
            msg["params"] = {"taskId": self.uri}
        return msg


class Subscription:
    """One consumer's view of the bus: a filtered, coalescing asyncio queue."""

    def __init__(self, bus: "ChangeBus", loop: asyncio.AbstractEventLoop,
                 kinds: Iterable[str], resource_uris: Iterable[str] = (), task_ids: Iterable[str] = ()):
        self._bus = bus
        self._loop = loop
        self.kinds: FrozenSet[str] = frozenset(kinds)
        self.resource_uris: FrozenSet[str] = frozenset(resource_uris)
        self.task_ids: FrozenSet[str] = frozenset(task_ids)
        self.queue: asyncio.Queue = asyncio.Queue()
        self._pending: Set[ChangeEvent] = set()
        self.closed = False

    def wants(self, event: ChangeEvent) -> bool:
        if event.kind == RESOURCE_UPDATED:
            return RESOURCE_UPDATED in self.kinds and event.uri in self.resource_uris
        if event.kind == TASK:
            return TASK in self.kinds and event.uri in self.task_ids
        return event.kind in self.kinds

    # called from any thread
    def _offer(self, item) -> None:
        try:
            self._loop.call_soon_threadsafe(self._put, item)
        except RuntimeError:        # loop closed
            self._bus.unsubscribe(self)

    # runs on the subscriber's loop
    def _put(self, item) -> None:
        if item is _CLOSED:
            self.queue.put_nowait(_CLOSED)
            return
        if item in self._pending:
            return
        self._pending.add(item)
        self.queue.put_nowait(item)

    async def get(self) -> Optional[ChangeEvent]:
        """Next event, or None once the bus shut down."""
        item = await self.queue.get()
        if item is _CLOSED:
            return None
        self._pending.discard(item)
        return item

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._bus.unsubscribe(self)


class ChangeBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._subs: List[Subscription] = []
        self._listeners: List[Callable[[ChangeEvent], None]] = []
        self._remote_listeners: Set[Callable[[ChangeEvent], None]] = set()   # also hear other workers
        self._store = None
        self._unsubscribe_store: Optional[Callable[[], None]] = None
        self.origin = uuid.uuid4().hex          # tags this bus's relayed events (skip our own echo)
        self._relay_window: dict = {}           # event -> its latest repeat in the open relay window (or None)
        self.relayed = 0                        # events written to the store (observability, tests)

    # -- cross-worker ---------------------------------------------------

    def attach_store(self, store) -> None:
        """Relay events through ``store`` pub/sub (shared backends).  Idempotent."""
        if self._store is store:
            return
        self.detach_store()

        def on_remote(message: dict) -> None:
            if message.get("origin") == self.origin:
                return
            kind = message.get("kind")
            if kind in _NOTIFICATION_METHODS:
                self._fan_out(ChangeEvent(kind, message.get("uri") if kind in _KEYED else None,
                                          id=message.get("id")),
                              listeners=False, remote=kind != TASK)

        self._unsubscribe_store = store.subscribe(CHANGES_CHANNEL, on_remote)
        self._store = store

    def detach_store(self) -> None:
        if self._unsubscribe_store is not None:
            try:
                self._unsubscribe_store()
            except Exception:
                pass
        self._store, self._unsubscribe_store = None, None

    def subscribe(self, kinds: Iterable[str], resource_uris: Iterable[str] = (),
                  loop: Optional[asyncio.AbstractEventLoop] = None, task_ids: Iterable[str] = ()) -> Subscription:
        """Create a subscription bound to ``loop`` (default: the running loop)."""
        sub = Subscription(self, loop or asyncio.get_running_loop(), kinds, resource_uris, task_ids)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    def add_listener(self, fn: Callable[[ChangeEvent], None], remote: bool = False) -> None:
        """Synchronous listener, called on the publishing thread (keep it cheap).  With ``remote``
        it is also called (on the store's delivery thread) for events relayed from other workers;
        ``event.id`` then lets it act on each publish once across workers."""
        with self._lock:
            self._listeners.append(fn)
            if remote:
                self._remote_listeners.add(fn)

    def remove_listener(self, fn: Callable[[ChangeEvent], None]) -> None:
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)
            self._remote_listeners.discard(fn)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def publish(self, kind: str, uri: Optional[str] = None) -> None:
        """Publish an event; safe from any thread, never raises."""
        if kind not in _NOTIFICATION_METHODS:
            raise ValueError(f"unknown change kind: {kind}")
        event = ChangeEvent(kind, uri if kind in _KEYED else None, id=uuid.uuid4().hex)
        self._fan_out(event, listeners=kind != TASK)
        if self._store is not None:
            self._relay(event)

    #: Identical events relayed to other workers within this window are coalesced: the first
    #: goes out at once, any repeats become one trailing relay when the window ends.  A burst
    #: (a bulk reload) is then O(distinct events) store writes, not one per tool.
    RELAY_WINDOW_SECONDS = 0.5

    def _relay(self, event: ChangeEvent) -> None:
        with self._lock:
            if event in self._relay_window:
                self._relay_window[event] = event       # repeat: one trailing relay (the latest id)
                return
            self._relay_window[event] = None
        self._send(event)
        timer = threading.Timer(self.RELAY_WINDOW_SECONDS, self._close_window, (event,))
        timer.daemon = True
        timer.start()

    def _close_window(self, event: ChangeEvent) -> None:
        with self._lock:
            repeated = self._relay_window.pop(event, None)
        if repeated is not None:
            self._relay(repeated)

    def _send(self, event: ChangeEvent) -> None:
        store = self._store
        if store is None:
            return
        self.relayed += 1
        try:
            store.publish(CHANGES_CHANNEL, {"kind": event.kind, "uri": event.uri, "id": event.id,
                                            "origin": self.origin})
        except Exception as e:   # other workers miss this event; this one is unaffected
            logger.warning(f"change-bus relay to other workers failed: {e}")

    def _fan_out(self, event: ChangeEvent, listeners: bool, remote: bool = False) -> None:
        with self._lock:
            subs = [s for s in self._subs if s.wants(event)]
            if listeners:
                listeners = list(self._listeners)
            elif remote:
                listeners = [fn for fn in self._listeners if fn in self._remote_listeners]
            else:
                listeners = []
        for sub in subs:
            sub._offer(event)
        for fn in listeners:
            try:
                fn(event)
            except Exception as e:  # a broken listener must not break the producer
                logger.warning(f"change-bus listener failed: {e}")

    def tools_changed(self) -> None:
        """The tool list (and therefore the tool catalog resource) changed."""
        self.publish(TOOLS)
        self.publish(RESOURCES)
        self.publish(RESOURCE_UPDATED, TOOL_CATALOG_URI)

    def task_changed(self, task_id: str) -> None:
        """A task record changed (status, result, pending input): listen streams that asked for
        this task id read the record and send ``notifications/tasks``."""
        self.publish(TASK, task_id)

    def prompts_changed(self) -> None:
        """The prompt list (and therefore the prompt catalog resource) changed."""
        self.publish(PROMPTS)
        self.publish(RESOURCES)
        self.publish(RESOURCE_UPDATED, PROMPT_CATALOG_URI)

    def shutdown(self) -> None:
        """End every subscription (listen streams then send their final result)."""
        with self._lock:
            subs, self._subs = list(self._subs), []
        for sub in subs:
            sub._offer(_CLOSED)


_bus = ChangeBus()


def get_change_bus() -> ChangeBus:
    return _bus
