"""
SAJHA MCP Server — scheduled health probes: one test case per tool, run live on a schedule.

Opt-in twice: ``quality.probes.enabled`` starts the scheduler (a daemon thread per worker) and
only tools whose test file (or config) has a ``probe:`` block are probed. A slot fires once
across workers: the worker that wins ``state_store.add('quality:probe:fire:<tool>:<slot>')``
runs it. Interval slots are aligned to the epoch; cron slots use the workflows cron parser.
The latest result and a short history per tool live in the state store; outcomes feed
``sajha_tool_probe_*`` metrics. Docs: docs/architecture/Tool Quality.md §4.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sajha.quality.cases import ProbeSpec, Suite, load_suite

logger = logging.getLogger(__name__)

_families: Dict[str, Any] = {}


def _fam(name: str):
    if not _families:
        try:
            from sajha.observability import metrics as M
            _families['runs'] = M.Counter(M.REGISTRY, 'sajha_tool_probe_runs_total',
                                          'Health probe runs by tool and outcome (pass, fail, error).', ('tool', 'outcome'))
            _families['up'] = M.Gauge(M.REGISTRY, 'sajha_tool_probe_up',
                                      '1 when the tool\'s last health probe passed, else 0.', ('tool',))
            _families['duration'] = M.Gauge(M.REGISTRY, 'sajha_tool_probe_duration_seconds',
                                            'Duration of the tool\'s last health probe.', ('tool',))
        except Exception:
            return None
    return _families.get(name)


def _store():
    from sajha.core.state import get_state_store
    return get_state_store()


def _history_len() -> int:
    from sajha.quality import setting_int
    return max(1, setting_int('probes.history', 20))


def next_slot(spec: ProbeSpec, after: float) -> float:
    """The first scheduled time strictly after ``after`` (epoch seconds)."""
    if spec.cron:
        from sajha.workflows.cron import CronSchedule
        dt = CronSchedule(spec.cron, spec.timezone or None).next_after(datetime.fromtimestamp(after, timezone.utc))
        return dt.timestamp()
    every = float(spec.every or 300)
    return (math.floor(after / every) + 1) * every


def state(tool: str) -> Dict[str, Any]:
    try:
        return _store().get(f'quality:probe:state:{tool}') or {}
    except Exception:
        return {}


def run_probe(registry: Any, spec: ProbeSpec, suite: Suite, trigger: str = 'schedule') -> Dict[str, Any]:
    """Run one probe now (live, never a cassette); store the result and update metrics."""
    from sajha.quality.runner import run_case
    case = next((c for c in suite.for_tool(spec.tool) if c.name == spec.case), None)
    tool = registry.get_tool(spec.tool) if registry else None
    if case is None:
        outcome = {'status': 'error', 'message': f'case {spec.case!r} not found', 'duration_ms': 0.0}
    else:
        r = run_case(tool, case, mode='live')
        outcome = {'status': r.status, 'message': r.message, 'duration_ms': round(r.duration_ms, 2),
                   'failures': r.failures[:5]}
    status = {'pass': 'pass', 'skip': 'pass', 'fail': 'fail'}.get(outcome['status'], 'error')
    entry = {'at': time.time(), 'status': status, 'message': outcome['message'][:500],
             'duration_ms': outcome['duration_ms'], 'trigger': trigger, 'worker': _worker()}

    def upd(cur):
        cur = dict(cur or {})
        hist = list(cur.get('history') or [])
        hist.append(entry)
        cur['history'] = hist[-_history_len():]
        cur['last'] = entry
        cur['consecutive_failures'] = 0 if status == 'pass' else int(cur.get('consecutive_failures', 0)) + 1
        cur['tool'] = spec.tool
        return cur
    try:
        _store().update(f'quality:probe:state:{spec.tool}', upd)
    except Exception as e:
        logger.warning(f'probe {spec.tool}: could not store the result: {e}')
    try:
        _fam('runs').inc((spec.tool, status))
        _fam('up').set((spec.tool,), 1.0 if status == 'pass' else 0.0)
        _fam('duration').set((spec.tool,), outcome['duration_ms'] / 1000.0)
    except Exception:
        pass
    if status != 'pass':
        logger.warning(f'health probe {spec.tool}/{spec.case}: {status}: {outcome["message"][:200]}')
    return entry


def _worker() -> str:
    try:
        from sajha.observability.metrics import _worker_id
        return _worker_id()
    except Exception:
        return str(os.getpid())


class ProbeScheduler:
    """Wakes every ``tick`` seconds; runs each probe whose slot has come, if this worker claims it."""

    def __init__(self, registry: Any, tick: Optional[float] = None, suite_loader=None):
        from sajha.quality import setting_int
        self.registry = registry
        self.tick = float(tick if tick is not None else setting_int('probes.tick_seconds', 15))
        self._suite_loader = suite_loader or (lambda: load_suite(registry=registry))
        self._suite: Optional[Suite] = None
        self._suite_at = 0.0
        self._due: Dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def suite(self) -> Suite:
        if self._suite is None or time.monotonic() - self._suite_at > 60:
            self._suite = self._suite_loader()
            self._suite_at = time.monotonic()
        return self._suite

    def probes(self) -> Dict[str, ProbeSpec]:
        return dict(self.suite().probes)

    def due(self, now: float) -> List[ProbeSpec]:
        out = []
        for tool, spec in self.probes().items():
            key = f'{tool}:{spec.schedule_text()}'
            when = self._due.get(key)
            if when is None:
                self._due[key] = next_slot(spec, now)
                continue
            if now >= when:
                self._due[key] = next_slot(spec, now)
                out.append((spec, when))
        return out

    def run_once(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = time.time() if now is None else now
        ran = []
        suite = self.suite()
        for spec, slot in self.due(now):
            try:
                ttl = max(60.0, float(spec.every or 3600) * 2)
                if not _store().add(f'quality:probe:fire:{spec.tool}:{int(slot)}', _worker(), ttl=ttl):
                    continue          # another worker runs this slot
            except Exception as e:
                logger.debug(f'probe claim failed for {spec.tool}: {e}')
                continue
            ran.append(run_probe(self.registry, spec, suite))
        return ran

    def _loop(self) -> None:
        while not self._stop.wait(self.tick):
            try:
                self.run_once()
            except Exception as e:
                logger.warning(f'probe scheduler: {e}', exc_info=True)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='sajha-probes', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


_scheduler: Optional[ProbeScheduler] = None


def enabled() -> bool:
    from sajha.quality import setting_bool
    return setting_bool('probes.enabled', False)


def start(registry: Any) -> bool:
    """Start-up: start the scheduler when ``quality.probes.enabled``."""
    global _scheduler
    if not enabled():
        return False
    _scheduler = ProbeScheduler(registry)
    _scheduler.start()
    return True


def stop() -> None:
    if _scheduler is not None:
        _scheduler.stop()


def overview(registry: Any, suite: Optional[Suite] = None) -> List[Dict[str, Any]]:
    """Every probe with its schedule, last result and history (for the Tool Health page)."""
    suite = suite or load_suite(registry=registry)
    now = time.time()
    out = []
    for tool, spec in sorted(suite.probes.items()):
        st = state(tool)
        try:
            nxt = next_slot(spec, now)
        except Exception:
            nxt = None
        out.append({**spec.to_dict(), 'last': st.get('last'), 'history': st.get('history') or [],
                    'consecutive_failures': st.get('consecutive_failures', 0), 'next': nxt,
                    'registered': bool(registry and registry.get_tool(tool))})
    return out
