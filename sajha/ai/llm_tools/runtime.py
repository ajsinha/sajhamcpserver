"""
SAJHA MCP Server — LLM tools: resource safety (LLM Tools §10.3–10.4, build step 7).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

No amount of traffic, conversation length or tool output may take the process down: under
pressure LLM-tool work slows down or is refused, it does not crash. The pieces, all per process:

* **Admission** (:class:`Admission`): at most ``ai.llm_tools.runtime.max_concurrent_runs`` runs
  execute; up to ``max_queued`` more wait at most ``queue_timeout_s``; beyond that a call ends
  with ``stopped_by: busy`` (REST answers 503 with ``Retry-After``).
* **Working set** (:class:`Run`): every tool result a run holds is measured when added. One larger
  than ``ai.llm_tools.memory.spill_threshold_kb`` is written to the run's spool folder at once and
  the run keeps a reference and a clipped preview; when the run's total passes
  ``working_set_max_kb`` the oldest items spill next.
* **Spool** (:class:`Spool`): one folder per run under ``ai.llm_tools.memory.spool.dir``
  (``data/spool/llm_tools/<run>/``), deleted when the run ends; a janitor deletes folders older
  than ``orphan_minutes`` (crashed runs) at start-up and on each guard tick. The total is capped by
  ``max_mb`` and each run by ``per_run_mb``; past a cap a payload is truncated with a marker instead.
* **Memory guard** (:class:`MemoryGuard`): samples resident memory (``/proc/self/statm`` on Linux,
  ``psutil`` when installed) every ``runtime.memory_guard.interval_s``. Limits are percentages of the
  container's cgroup memory limit when one is set, else of physical memory, or absolute MB.
  *soft*: shed the caches, spill every spillable item, admit no queued run. *hard*: refuse new runs
  (``busy``) and end running ones at their next step (``stopped_by: memory_pressure``).
* **Caches**: the result cache of deterministic modes (``cache: true``) and the optional
  conversation hot cache (``ai.llm_tools.memory.cache``, off by default) are bounded by entries or
  measured bytes, have a TTL, and are the first thing given up under pressure.

Conditions are raised as System Notices (``llm_tools.memory``, ``llm_tools.busy``,
``llm_tools.spool_full``) and exported as the ``sajha_llm_tool_*`` metrics
(docs/architecture/Observability.md).
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.ai.llm_tools.config import LLMToolSettings, settings as _settings

logger = logging.getLogger(__name__)

STATES = ("ok", "soft", "hard")
TRUNCATED = "[truncated: the spool is full]"
NOTICE_MEMORY = "llm_tools.memory"
NOTICE_BUSY = "llm_tools.busy"
NOTICE_SPOOL = "llm_tools.spool_full"


def _m():
    try:
        from sajha.observability import metrics
        return metrics
    except Exception:
        return None


def _notices():
    try:
        from sajha import notices
        return notices
    except Exception:
        return None


def _worker() -> Optional[str]:
    try:
        from sajha.core.state import WORKER_ID
        return WORKER_ID
    except Exception:
        return None


def measure(value: Any) -> int:
    """Approximate bytes of a value as the model would see it (its JSON text)."""
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8", "ignore"))
    try:
        return len(json.dumps(value, default=str).encode("utf-8", "ignore"))
    except Exception:
        return len(str(value))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)


# ── resident memory and the container limit ───────────────────────────────

def read_rss_bytes() -> int:
    """Resident memory of this process: /proc on Linux, psutil when installed, else peak RSS."""
    try:
        with open("/proc/self/statm", "r") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except Exception:
        pass
    try:
        import psutil
        return int(psutil.Process().memory_info().rss)
    except Exception:
        pass
    try:
        import resource
        import sys
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(r if sys.platform == "darwin" else r * 1024)
    except Exception:
        return 0


def read_limit_bytes() -> int:
    """The memory this process may use: the cgroup limit (v2, then v1) when set, else physical memory."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = Path(path).read_text().strip()
            if raw and raw != "max":
                v = int(raw)
                if 0 < v < (1 << 60):
                    return v
        except Exception:
            continue
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except Exception:
        pass
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except Exception:
        return 0


class MemoryGuard:
    """The watchdog. ``rss_reader`` and ``limit_reader`` can be replaced (tests simulate pressure)."""

    def __init__(self, cfg=None, rss_reader: Callable[[], int] = read_rss_bytes,
                 limit_reader: Callable[[], int] = read_limit_bytes):
        self.cfg = cfg
        self.rss_reader = rss_reader
        self.limit_reader = limit_reader
        self.state = "ok"
        self.rss = 0
        self.last = 0.0
        self.listeners: List[Callable[[str, str], None]] = []
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def settings(self):
        return self.cfg or _settings().guard

    def thresholds(self) -> Tuple[int, int]:
        g = self.settings
        mb = 1024 * 1024
        limit = 0
        if not (g.soft_mb > 0 and g.hard_mb > 0):
            limit = self.limit_reader() or 0
        soft = int(g.soft_mb * mb) if g.soft_mb > 0 else int(limit * g.soft_pct / 100.0)
        hard = int(g.hard_mb * mb) if g.hard_mb > 0 else int(limit * g.hard_pct / 100.0)
        return soft, hard

    def sample(self) -> str:
        """Measure now and move to the state the measurement calls for (listeners hear the change)."""
        if not self.settings.enabled:
            return "ok"
        try:
            rss = int(self.rss_reader() or 0)
        except Exception as e:
            logger.debug(f"memory guard: cannot read resident memory ({e})")
            return self.state
        soft, hard = self.thresholds()
        new = "ok"
        if hard > 0 and rss >= hard:
            new = "hard"
        elif soft > 0 and rss >= soft:
            new = "soft"
        with self._lock:
            old, self.state, self.rss, self.last = self.state, new, rss, time.time()
        m = _m()
        if m is not None:
            m.LLM_TOOL_GUARD.set((), STATES.index(new))
            m.LLM_TOOL_RSS.set((), rss)
        if new != old:
            logger.warning(f"LLM tools: memory guard {old} -> {new} (resident {rss // (1 << 20)} MB, "
                           f"soft {soft // (1 << 20)} MB, hard {hard // (1 << 20)} MB)") \
                if new != "ok" else logger.info("LLM tools: memory guard back to ok")
            self._notice(new, rss, soft, hard)
            for fn in list(self.listeners):
                try:
                    fn(old, new)
                except Exception as e:
                    logger.warning(f"memory guard listener failed: {e}")
        return new

    def maybe_sample(self) -> str:
        """Sample when the last measurement is older than the interval (cheap to call per admission)."""
        if time.time() - self.last >= max(0.05, float(self.settings.interval_s)):
            return self.sample()
        return self.state

    def _notice(self, state: str, rss: int, soft: int, hard: int) -> None:
        N = _notices()
        if N is None:
            return
        if state == "ok":
            N.clear_notice(NOTICE_MEMORY, holder=_worker())
            return
        mb = 1 << 20
        if state == "soft":
            title = "LLM tools: memory is high (soft limit)"
            detail = (f"Resident memory {rss // mb} MB passed the soft limit ({soft // mb} MB). LLM-tool caches were "
                      f"emptied, large results spill to disk and queued runs wait. If it reaches the hard limit "
                      f"({hard // mb} MB) new runs are refused. Lower ai.llm_tools.runtime.max_concurrent_runs or "
                      f"give the process more memory.")
        else:
            title = "LLM tools: memory is critical (hard limit)"
            detail = (f"Resident memory {rss // mb} MB passed the hard limit ({hard // mb} MB). New LLM-tool runs are "
                      f"refused (busy) and running ones end at their next step with stopped_by memory_pressure.")
        N.raise_notice(NOTICE_MEMORY, severity="warning" if state == "soft" else "error", source="llm_tools",
                       title=title, detail=detail, link="/help/guides/LLM%20Tools.md", ttl_minutes=10,
                       holder=_worker())

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(max(0.2, float(self.settings.interval_s))):
                try:
                    self.sample()
                    get_runtime().tick()
                except Exception as e:
                    logger.debug(f"memory guard tick failed: {e}")
        self._thread = threading.Thread(target=loop, name="llm-tools-memory-guard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout=2)
        self._thread = None


# ── admission ─────────────────────────────────────────────────────────────

class Busy(RuntimeError):
    """The process refused the run to protect itself."""

    def __init__(self, reason: str, message: str, stopped_by: str = "busy"):
        super().__init__(message)
        self.reason = reason
        self.stopped_by = stopped_by


class Admission:
    def __init__(self, guard: MemoryGuard, cfg=None):
        self.guard = guard
        self.cfg = cfg
        self.running = 0
        self.queued = 0
        self._cond = threading.Condition()

    @property
    def settings(self):
        return self.cfg or _settings().runtime

    def _gauges(self):
        m = _m()
        if m is not None:
            m.LLM_TOOL_RUNS.set(("running",), self.running)
            m.LLM_TOOL_RUNS.set(("queued",), self.queued)

    def _refuse(self, reason: str, message: str) -> Busy:
        m = _m()
        if m is not None:
            m.LLM_TOOL_REFUSED.inc((reason,))
        N = _notices()
        if N is not None:
            N.raise_notice(NOTICE_BUSY, severity="warning", source="llm_tools",
                           title="LLM tools are refusing runs (busy)",
                           detail=f"{message}. Callers get stopped_by busy (REST: 503 with Retry-After). Raise "
                                  f"ai.llm_tools.runtime.max_concurrent_runs / max_queued if the host has room.",
                           link="/help/guides/LLM%20Tools.md", ttl_minutes=10, holder=_worker())
        return Busy(reason, message)

    def acquire(self) -> None:
        s = self.settings
        state = self.guard.maybe_sample()
        if state == "hard":
            raise self._refuse("memory", "the process is at its hard memory limit")
        deadline = time.time() + max(0.0, float(s.queue_timeout_s))
        with self._cond:
            if self.running < max(1, s.max_concurrent_runs) and state == "ok" and self.queued == 0:
                self.running += 1
                self._gauges()
                return
            if self.queued >= max(0, s.max_queued):
                raise self._refuse("queue_full", f"{self.running} runs executing and {self.queued} waiting "
                                                 f"(max_concurrent_runs {s.max_concurrent_runs}, max_queued "
                                                 f"{s.max_queued})")
            self.queued += 1
            self._gauges()
            try:
                while True:
                    state = self.guard.state
                    if state == "hard":
                        raise self._refuse("memory", "the process reached its hard memory limit while the run waited")
                    if self.running < max(1, s.max_concurrent_runs) and state == "ok":
                        self.running += 1
                        return
                    left = deadline - time.time()
                    if left <= 0:
                        raise self._refuse("queue_timeout", f"the run waited {s.queue_timeout_s:g}s for a free slot")
                    self._cond.wait(min(left, 0.25))
                    if self.guard.state != "ok":
                        self.guard.maybe_sample()
            finally:
                self.queued -= 1
                self._gauges()

    def release(self) -> None:
        with self._cond:
            self.running = max(0, self.running - 1)
            self._gauges()
            self._cond.notify_all()


# ── spool ─────────────────────────────────────────────────────────────────

@dataclass
class SpoolRef:
    path: str
    size: int
    truncated: bool = False

    def read(self) -> str:
        try:
            return Path(self.path).read_text(encoding="utf-8")
        except Exception:
            return ""


class Spool:
    def __init__(self, cfg=None):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._bytes = 0
        self._per_run: Dict[str, int] = {}
        self._full = False

    @property
    def settings(self):
        return self.cfg or _settings().spool

    @property
    def root(self) -> Path:
        p = Path(self.settings.dir)
        if not p.is_absolute():
            p = Path.cwd() / p
        return p

    @property
    def bytes_in_use(self) -> int:
        return self._bytes

    def _gauge(self):
        m = _m()
        if m is not None:
            m.LLM_TOOL_SPOOL_BYTES.set((), self._bytes)

    def write(self, run_id: str, key: str, text: str) -> SpoolRef:
        """Write a payload for the run; past a cap the payload is truncated with a marker (not spooled)."""
        data = text.encode("utf-8", "ignore")
        mb = 1 << 20
        s = self.settings
        with self._lock:
            run_total = self._per_run.get(run_id, 0)
            fits = (self._bytes + len(data) <= s.max_mb * mb) and (run_total + len(data) <= s.per_run_mb * mb)
            if fits:
                self._bytes += len(data)
                self._per_run[run_id] = run_total + len(data)
        if not fits:
            self._set_full(True)
            return SpoolRef("", len(data), truncated=True)
        folder = self.root / run_id
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:80] or "item"
        path = folder / f"{safe}-{uuid.uuid4().hex[:8]}.json"
        path.write_bytes(data)
        self._gauge()
        if self._full:
            self._set_full(False)
        return SpoolRef(str(path), len(data))

    def _set_full(self, full: bool) -> None:
        if full == self._full:
            return
        self._full = full
        N = _notices()
        if N is None:
            return
        if full:
            N.raise_notice(NOTICE_SPOOL, severity="warning", source="llm_tools", title="LLM-tool spool is full",
                           detail=f"Large in-flight results are being truncated instead of written to "
                                  f"{self.settings.dir} (max_mb {self.settings.max_mb:g}, per_run_mb "
                                  f"{self.settings.per_run_mb:g}). Raise ai.llm_tools.memory.spool.max_mb or free "
                                  f"disk space.", link="/help/guides/LLM%20Tools.md", ttl_minutes=30, holder=_worker())
        else:
            N.clear_notice(NOTICE_SPOOL, holder=_worker())

    def remove_run(self, run_id: str) -> None:
        with self._lock:
            self._bytes = max(0, self._bytes - self._per_run.pop(run_id, 0))
        shutil.rmtree(self.root / run_id, ignore_errors=True)
        self._gauge()

    def sweep_orphans(self, active: Optional[set] = None, now: Optional[float] = None) -> int:
        """Delete run folders older than ``orphan_minutes`` that no live run owns (crashed runs)."""
        now = now or time.time()
        cutoff = now - max(0.0, float(self.settings.orphan_minutes)) * 60
        active = active or set()
        removed = 0
        root = self.root
        if not root.is_dir():
            return 0
        for p in root.iterdir():
            try:
                if p.is_dir() and p.name not in active and p.stat().st_mtime < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 1
            except Exception:
                continue
        if removed:
            logger.info(f"LLM tools: spool janitor removed {removed} orphaned run folder(s)")
        return removed


# ── caches ────────────────────────────────────────────────────────────────

class BoundedCache:
    """LRU by measured bytes (``max_bytes``) or entries (``max_entries``), with a TTL; shed() empties it."""

    def __init__(self, label: str, max_bytes: int = 0, max_entries: int = 0, ttl_s: float = 300.0):
        self.label = label
        self.max_bytes, self.max_entries, self.ttl_s = max_bytes, max_entries, ttl_s
        self._d: "OrderedDict[str, Tuple[float, int, Any]]" = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self.enabled = True

    def __len__(self):
        return len(self._d)

    @property
    def bytes(self) -> int:
        return self._bytes

    def _evicted(self, n: int = 1):
        m = _m()
        if m is not None and n:
            m.LLM_TOOL_CACHE_EVICTIONS.inc((self.label,), n)

    def _gauge(self):
        m = _m()
        if m is not None:
            m.LLM_TOOL_CACHE_BYTES.set((self.label,), self._bytes)

    def get(self, key: str) -> Any:
        if not self.enabled:
            return None
        with self._lock:
            hit = self._d.get(key)
            if hit is None:
                return None
            ts, size, value = hit
            if self.ttl_s and time.time() - ts > self.ttl_s:
                del self._d[key]
                self._bytes -= size
                self._evicted()
                return None
            self._d.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        if not self.enabled or get_runtime().guard.state != "ok":
            return
        size = measure(value)
        if self.max_bytes and size > self.max_bytes:
            return
        n = 0
        with self._lock:
            old = self._d.pop(key, None)
            if old is not None:
                self._bytes -= old[1]
            self._d[key] = (time.time(), size, value)
            self._bytes += size
            while self._d and ((self.max_bytes and self._bytes > self.max_bytes)
                               or (self.max_entries and len(self._d) > self.max_entries)):
                _, (_, s, _) = self._d.popitem(last=False)
                self._bytes -= s
                n += 1
        self._evicted(n)
        self._gauge()

    def invalidate(self, prefix: str) -> None:
        with self._lock:
            for k in [k for k in self._d if k.startswith(prefix)]:
                self._bytes -= self._d.pop(k)[1]
        self._gauge()

    def shed(self) -> int:
        with self._lock:
            n = len(self._d)
            self._d.clear()
            self._bytes = 0
        self._evicted(n)
        self._gauge()
        return n


class CachedConversationStore:
    """Write-through hot cache (T1) in front of the conversation store: reads of a conversation row
    and its window of turns are served from memory; every write goes to the database first and
    drops the cached entries, so eviction never loses data."""

    def __init__(self, store, cache: BoundedCache):
        self._store = store
        self.cache = cache

    def __getattr__(self, item):
        return getattr(self._store, item)

    def _key(self, *parts) -> str:
        return "|".join(str(p) for p in parts)

    def get(self, conversation_id, user_id, tool_name=None, *a, **kw):
        if a or kw:
            return self._store.get(conversation_id, user_id, tool_name, *a, **kw)
        k = self._key(conversation_id, user_id, "row", tool_name)
        v = self.cache.get(k)
        if v is None:
            v = self._store.get(conversation_id, user_id, tool_name)
            if v is not None:
                self.cache.put(k, v)
        return v

    def turns(self, conversation_id, user_id, after=0, through=None):
        k = self._key(conversation_id, user_id, "turns", after, through)
        v = self.cache.get(k)
        if v is None:
            v = self._store.turns(conversation_id, user_id, after=after, through=through)
            self.cache.put(k, v)
        return v

    def _write(self, name, conversation_id, user_id, *a, **kw):
        try:
            return getattr(self._store, name)(conversation_id, user_id, *a, **kw)
        finally:
            self.cache.invalidate(f"{conversation_id}|")

    def add_turn(self, conversation_id, user_id, **kw):
        return self._write("add_turn", conversation_id, user_id, **kw)

    def set_summary(self, conversation_id, user_id, *a, **kw):
        return self._write("set_summary", conversation_id, user_id, *a, **kw)

    def fold(self, conversation_id, user_id, *a, **kw):
        return self._write("fold", conversation_id, user_id, *a, **kw)

    def delete(self, conversation_id, user_id):
        return self._write("delete", conversation_id, user_id)

    def delete_all(self, user_id):
        try:
            return self._store.delete_all(user_id)
        finally:
            self.cache.shed()

    def purge(self, *a, **kw):
        try:
            return self._store.purge(*a, **kw)
        finally:
            self.cache.shed()


# ── one run ───────────────────────────────────────────────────────────────

@dataclass
class Item:
    key: str
    size: int
    preview: Any
    value: Any = None
    ref: Optional[SpoolRef] = None


@dataclass
class Run:
    tool: str
    mode: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    started: float = field(default_factory=time.time)
    deadline: float = 0.0
    cost_cap: float = 0.0
    cost: float = 0.0                      # spent by nested LLM tools (the run's own model calls add theirs)
    parent: Optional["Run"] = None
    items: List[Item] = field(default_factory=list)
    bytes: int = 0
    peak: int = 0
    spilled: int = 0
    inner_calls: int = 0
    stop: Optional[str] = None             # set from outside: memory_pressure, cancelled

    def remaining_cost(self, own: float = 0.0) -> float:
        return self.cost_cap - self.cost - own

    # working set
    def add(self, key: str, value: Any) -> Any:
        """Hold a tool result; large ones go to the spool. Returns what the run keeps in memory."""
        rt = get_runtime()
        ws = rt.settings.working_set
        size = measure(value)
        preview_chars = _preview_chars()
        item = Item(key, size, value if size <= preview_chars else _clip(value, preview_chars), value)
        self.items.append(item)
        self.bytes += size
        self.peak = max(self.peak, self.bytes)
        if size > ws.spill_threshold_kb * 1024 or rt.guard.state != "ok":
            self._spill(item)
        while self.bytes > ws.working_set_max_kb * 1024:
            victim = next((i for i in self.items if i.value is not None), None)
            if victim is None:
                break
            self._spill(victim)
        return item.preview if item.value is None else item.value

    def _spill(self, item: Item) -> None:
        if item.value is None:
            return
        rt = get_runtime()
        item.ref = rt.spool.write(self.id, item.key, _text(item.value))
        item.value = None
        self.bytes -= item.size
        self.spilled += 1
        m = _m()
        if m is not None:
            m.LLM_TOOL_SPILLED.inc(())

    def spill_all(self) -> None:
        for i in list(self.items):
            self._spill(i)

    def full(self, key: str) -> Any:
        """The full value of an item (streamed back from the spool when it was spilled)."""
        for i in self.items:
            if i.key == key:
                if i.value is not None:
                    return i.value
                if i.ref is not None and not i.ref.truncated:
                    raw = i.ref.read()
                    try:
                        return json.loads(raw)
                    except Exception:
                        return raw
                return i.preview
        return None


def _preview_chars() -> int:
    try:
        from sajha.ai.intelligence import get_intelligence
        svc = get_intelligence()
        if svc is not None:
            return int(svc.settings.max_result_chars)
    except Exception:
        pass
    return 4000


def _clip(value: Any, n: int) -> str:
    t = _text(value)
    return t if len(t) <= n else t[:n] + f"… [{len(t) - n} more characters]"


CURRENT: contextvars.ContextVar[Optional[Run]] = contextvars.ContextVar("sajha_llm_tool_run", default=None)


def current_run() -> Optional[Run]:
    return CURRENT.get()


def observe_result(name: str, call_id: str, value: Any) -> Any:
    """Called by the planner loop for each inner tool result; a no-op outside an LLM-tool run."""
    run = CURRENT.get()
    if run is None:
        return value
    run.inner_calls += 1
    return run.add(f"{name}-{call_id}", value)


# ── the process-wide runtime ──────────────────────────────────────────────

class Runtime:
    def __init__(self, s: Optional[LLMToolSettings] = None, guard: Optional[MemoryGuard] = None):
        self._s = s
        self.guard = guard or MemoryGuard()
        self.admission = Admission(self.guard)
        self.spool = Spool()
        self.results = BoundedCache("result", max_entries=self.settings.result_cache.max_entries,
                                    ttl_s=self.settings.result_cache.ttl_s)
        c = self.settings.cache
        self.hot = BoundedCache("conversation", max_bytes=int(c.max_mb * (1 << 20)), ttl_s=c.ttl_s)
        self.hot.enabled = bool(c.enabled)
        self.runs: Dict[str, Run] = {}
        self._lock = threading.Lock()
        self._swept = False
        self._last_sweep = 0.0
        self.guard.listeners.append(self._on_state)

    @property
    def settings(self) -> LLMToolSettings:
        return self._s or _settings()

    def _on_state(self, old: str, new: str) -> None:
        if new in ("soft", "hard"):
            self.results.shed()
            self.hot.shed()
            with self._lock:
                runs = list(self.runs.values())
            for r in runs:
                try:
                    r.spill_all()
                except Exception as e:
                    logger.warning(f"LLM tools: could not spill run {r.id}: {e}")
        if new == "hard":
            with self._lock:
                for r in self.runs.values():
                    r.stop = r.stop or "memory_pressure"
        with self.admission._cond:
            self.admission._cond.notify_all()

    def tick(self) -> None:
        """Periodic work: the spool janitor (also runs once on first use)."""
        if time.time() - self._last_sweep >= 60:
            self._last_sweep = time.time()
            with self._lock:
                active = set(self.runs)
            try:
                self.spool.sweep_orphans(active)
            except Exception as e:
                logger.debug(f"spool janitor: {e}")

    def begin(self, tool: str, mode: str, timeout_s: float, cost_cap: float) -> Run:
        """Admit a run (raises Busy) and make it the current run; shares the outer run's budget."""
        if not self._swept:
            self._swept = True
            self.tick()
            self.guard.start()
        self.admission.acquire()
        parent = CURRENT.get()
        now = time.time()
        run = Run(tool=tool, mode=mode, deadline=now + timeout_s, cost_cap=cost_cap, parent=parent)
        if parent is not None:
            run.deadline = min(run.deadline, parent.deadline)
            run.cost_cap = min(run.cost_cap, max(0.0, parent.remaining_cost()))
        with self._lock:
            self.runs[run.id] = run
        return run

    def end(self, run: Run) -> None:
        with self._lock:
            self.runs.pop(run.id, None)
        try:
            self.spool.remove_run(run.id)
        finally:
            self.admission.release()
        if run.parent is not None:
            run.parent.cost += run.cost
        m = _m()
        if m is not None:
            m.LLM_TOOL_WORKING_SET.observe((), run.peak)

    def stats(self) -> Dict[str, Any]:
        return {"guard": self.guard.state, "resident_bytes": self.guard.rss, "running": self.admission.running,
                "queued": self.admission.queued, "spool_bytes": self.spool.bytes_in_use,
                "result_cache_entries": len(self.results), "hot_cache_bytes": self.hot.bytes}


_runtime: Optional[Runtime] = None
_rt_lock = threading.Lock()


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        with _rt_lock:
            if _runtime is None:
                _runtime = Runtime()
    return _runtime


def set_runtime(rt: Optional[Runtime]) -> None:
    """Install a runtime (tests); None builds a fresh one on next use."""
    global _runtime
    with _rt_lock:
        old, _runtime = _runtime, rt
    if old is not None and old is not rt:
        old.guard.stop()
