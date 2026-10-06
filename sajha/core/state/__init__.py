"""
Process-shared state for SAJHA (``state.*`` in application.yml).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One :class:`~sajha.core.state.base.StateStore` per process, chosen by
``state.backend``:

    memory    (default) this process only; behaviour of a single worker is unchanged
    redis     shared by every worker and host (``state.redis.url`` /
              env SAJHA_STATE_REDIS_URL); pub/sub carries the change bus
    database  SAJHA's SQL database (or ``state.database.url``); shared by every
              worker that uses the same database; pub/sub is a polled table

A second store holds MCP task records (:func:`get_task_record_store`): the
database whenever ``state.tasks.durable`` is on (default ``auto``: on for the
redis and database backends), so tasks survive a restart.

The design, the inventory of process state and what stays local are in
``docs/architecture/Scaling and State.md``.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import uuid
from typing import Any, Dict, Optional

from sajha.core.state.base import StateStore
from sajha.core.state.memory import MemoryStateStore

logger = logging.getLogger(__name__)

BACKENDS = ("memory", "redis", "database")

#: identifies this process in task records and worker heartbeats
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"

HEARTBEAT_TTL = 30.0
_HEARTBEAT_EVERY = 10.0

_lock = threading.Lock()
_store: Optional[StateStore] = None
_task_store: Optional[StateStore] = None
_heartbeat: Optional[threading.Thread] = None
_heartbeat_stop = threading.Event()


# ── configuration ───────────────────────────────────────────────────

def _cfg(key: str, default: str = "") -> str:
    from sajha.core.config import _get
    return _get(key, default)


def configured_backend() -> str:
    backend = (_cfg("state.backend", "memory") or "memory").strip().lower()
    if backend not in BACKENDS:
        raise ValueError(f"state.backend must be one of {', '.join(BACKENDS)}; got {backend!r}")
    return backend


def key_prefix() -> str:
    return _cfg("state.key_prefix", "sajha:")


def tasks_durable(backend: Optional[str] = None) -> bool:
    raw = (_cfg("state.tasks.durable", "auto") or "auto").strip().lower()
    if raw == "auto":
        return (backend or configured_backend()) != "memory"
    from sajha.core.config import parse_bool
    return parse_bool(raw)


def build_store(backend: Optional[str] = None) -> StateStore:
    backend = backend or configured_backend()
    prefix = key_prefix()
    if backend == "memory":
        return MemoryStateStore(prefix)
    if backend == "redis":
        from sajha.core.state.redis_store import RedisStateStore
        url = _cfg("state.redis.url", "redis://localhost:6379/0") or "redis://localhost:6379/0"
        return RedisStateStore(url, prefix)
    from sajha.core.state.database import DatabaseStateStore
    from sajha.core.config import _int
    return DatabaseStateStore(prefix=prefix, url=_cfg("state.database.url", ""),
                              poll_interval=max(50, _int("state.database.poll_interval_ms", 500)) / 1000.0)


def get_state_store() -> StateStore:
    """The process's state store (built from config on first use)."""
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = build_store()
                if _store.shared:
                    _start_heartbeat()
    return _store


def get_task_record_store() -> StateStore:
    """Where MCP task records live: the database when tasks are durable, else the state store."""
    global _task_store
    if _task_store is None:
        main = get_state_store()
        with _lock:
            if _task_store is None:
                if tasks_durable(main.backend) and main.backend != "database":
                    from sajha.core.state.database import DatabaseStateStore
                    _task_store = DatabaseStateStore(prefix=main.prefix, url=_cfg("state.database.url", ""))
                else:
                    _task_store = main
    return _task_store


def set_state_store(store: Optional[StateStore], task_store: Optional[StateStore] = None) -> None:
    """Install stores (tests, embedding).  None resets to "build from config on next use"."""
    global _store, _task_store
    with _lock:
        _store = store
        _task_store = task_store


def reset_state_for_tests() -> None:
    set_state_store(None)


# ── worker liveness (orphaned tasks) ───────────────────────────────

def beat_once() -> None:
    """Announce this worker as alive (TTL ``HEARTBEAT_TTL``) in the shared stores."""
    store = _store
    if store is not None and store.shared:
        store.set(f"worker:{WORKER_ID}", {"since": _STARTED, "pid": os.getpid()}, ttl=HEARTBEAT_TTL)
    ts = _task_store
    if ts is not None and ts is not store and ts.shared:
        ts.set(f"worker:{WORKER_ID}", {"since": _STARTED, "pid": os.getpid()}, ttl=HEARTBEAT_TTL)


def _beat(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            beat_once()
        except Exception as e:
            logger.warning(f"state heartbeat failed: {e}")
        stop.wait(_HEARTBEAT_EVERY)


_STARTED = time.time()


def _start_heartbeat() -> None:
    global _heartbeat
    if _heartbeat is None:
        _heartbeat = threading.Thread(target=_beat, args=(_heartbeat_stop,), name="sajha-state-heartbeat",
                                      daemon=True)
        _heartbeat.start()


def worker_alive(worker_id: Optional[str], store: Optional[StateStore] = None) -> bool:
    """
    True for this process, or a worker whose heartbeat is in the shared state store.
    With the memory backend there is one process: a record naming any other
    worker came from a previous run of this server (durable task store) and is dead.
    """
    if not worker_id:
        return False
    if worker_id == WORKER_ID:
        return True
    main = get_state_store()
    if not main.shared:
        return False
    return main.get(f"worker:{worker_id}") is not None


# ── startup checks and /health ─────────────────────────────────────

def worker_count_hint() -> int:
    """Workers this deployment runs, as far as the environment says (WEB_CONCURRENCY, --workers)."""
    for name in ("SAJHA_WORKERS", "WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        try:
            n = int(os.environ.get(name, "") or 0)
        except ValueError:
            n = 0
        if n > 0:
            return n
    argv = sys.argv
    for i, a in enumerate(argv):
        val = None
        if a in ("--workers", "-w") and i + 1 < len(argv):
            val = argv[i + 1]
        elif a.startswith("--workers="):
            val = a.split("=", 1)[1]
        if val:
            try:
                return max(1, int(val))
            except ValueError:
                pass
    return 1


def startup_check() -> Dict[str, Any]:
    """Build the store, verify it answers, attach the change bus; warn on >1 worker with memory."""
    store = get_state_store()
    if store.shared and not store.ping():
        raise RuntimeError(f"state.backend={store.backend}: the store does not answer "
                           f"({store.describe()}); refusing to start")
    workers = worker_count_hint()
    if workers > 1 and not store.shared:
        logger.warning(
            f"Running {workers} workers with state.backend=memory: OAuth codes, MCP sessions, tasks, "
            "rate limits and change notifications are per worker and WILL break across workers. "
            "Set state.backend: redis (or database). See docs/architecture/Scaling and State.md")
    if store.shared:
        from sajha.core.change_bus import get_change_bus
        get_change_bus().attach_store(store)
        get_task_record_store()
        from sajha.core import mcp_sessions, mcp_sse_relay
        mcp_sessions.get_session_store().attach_store(store)
        mcp_sse_relay.attach_store(store)
    from sajha.core.mcp_tasks import get_task_store
    get_task_store().attach()
    beat_once()
    info = health_info()
    logger.info(f"State store: {info['backend']} (tasks: {info['tasks']}, worker {WORKER_ID})")
    return info


def health_info() -> Dict[str, Any]:
    store = get_state_store()
    out = store.describe()
    if "reachable" not in out:
        out["reachable"] = store.ping()
    ts = get_task_record_store()
    out["tasks"] = "durable (database)" if ts.backend == "database" else ts.backend
    out["worker_id"] = WORKER_ID
    out["workers_hint"] = worker_count_hint()
    return out


def shutdown() -> None:
    """Stop the heartbeat and close shared stores (the memory store is kept: nothing to release)."""
    global _store, _task_store, _heartbeat, _heartbeat_stop
    shared = [x for x in {id(x): x for x in (_store, _task_store) if x is not None}.values() if x.shared]
    if not shared:
        return
    _heartbeat_stop.set()
    try:
        if _store is not None and _store.shared:
            _store.delete(f"worker:{WORKER_ID}")
    except Exception:
        pass
    for s in shared:
        try:
            s.close()
        except Exception:
            pass
    with _lock:
        _store = _task_store = None
        _heartbeat, _heartbeat_stop = None, threading.Event()
