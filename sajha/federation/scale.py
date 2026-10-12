"""
SAJHA MCP Server — federation at gateway scale: admission (load shedding), connection pools,
replica selection and the cluster-wide view of upstream health.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* :class:`Admission` bounds the calls in flight to one upstream (``max_in_flight``) and the
  calls waiting for a slot (``max_queue``, first come first served, at most
  ``queue_timeout_seconds``); over the bound a call is refused at once with
  :class:`UpstreamOverloaded`, a retryable error that does not count against the breaker.
* :func:`pick_member` chooses the pool connection (of any replica) for a call: a connected one,
  on a replica no worker reports failing, with the fewest calls in flight, then the lowest
  latency, then round robin.
* :class:`HealthBoard` publishes this worker's view of each upstream to the state store
  (``fed:health:<upstream>:<worker>``, with a TTL) and reads every live worker's view back:
  the admin page, ``/metrics`` and routing (peer breakers, replica choice) use that view.

Design: docs/architecture/Federation.md, section 8 "Health, status and failure isolation" and
"Gateway scale".
"""

from __future__ import annotations

import collections
import itertools
import logging
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

HEALTH_PREFIX = 'fed:health:'


class UpstreamOverloaded(RuntimeError):
    """An upstream has ``max_in_flight`` calls running and its queue is full (or the wait for a
    slot timed out): refused before anything is sent, so it is always safe to retry."""

    retryable = True
    caller_specific = True      # the load, not the upstream, failed it: the breaker does not count it
    quiet_failure = True        # an expected refusal: logged without a stack trace

    def __init__(self, message: str, retry_after: float = 1.0):
        super().__init__(message)
        self.retry_after = retry_after


# ── admission ───────────────────────────────────────────────────────

class Admission:
    """Calls in flight to one upstream (``limit``, 0 = no limit) and a bounded FIFO queue."""

    def __init__(self, upstream_id: str, limit: int = 0, queue: int = 0, queue_timeout: float = 5.0):
        self.upstream_id = upstream_id
        self.limit = max(0, int(limit or 0))
        self.queue = max(0, int(queue or 0))
        self.queue_timeout = max(0.0, float(queue_timeout or 0.0))
        self.in_flight = 0
        self.admitted = 0
        self.shed = 0
        self.queued_total = 0
        self.peak_in_flight = 0
        self._waiters: collections.deque = collections.deque()
        self._lock = threading.Lock()

    @property
    def waiting(self) -> int:
        return len(self._waiters)

    def acquire(self) -> None:
        """Take a slot, waiting in line when the queue has room; raises UpstreamOverloaded."""
        with self._lock:
            if self.limit <= 0 or (self.in_flight < self.limit and not self._waiters):
                self._enter()
                return
            if len(self._waiters) >= self.queue or self.queue_timeout <= 0:
                self.shed += 1
                raise self._refusal('its queue is full' if self.queue else 'no queue is configured')
            ev = threading.Event()
            self._waiters.append(ev)
            self.queued_total += 1
        if ev.wait(self.queue_timeout):
            return                              # release() handed this caller its slot
        with self._lock:
            if ev.is_set():                     # handed over just as the wait ended
                return
            try:
                self._waiters.remove(ev)
            except ValueError:
                pass
            self.shed += 1
        raise self._refusal(f'no slot freed within {self.queue_timeout:g}s')

    def release(self) -> None:
        with self._lock:
            if self._waiters and (self.limit <= 0 or self.in_flight <= self.limit):
                self.admitted += 1              # the slot passes straight to the next in line
                self._waiters.popleft().set()
                return
            self.in_flight = max(0, self.in_flight - 1)

    def _enter(self) -> None:
        self.in_flight += 1
        self.admitted += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)

    def _refusal(self, why: str) -> UpstreamOverloaded:
        return UpstreamOverloaded(
            f'upstream {self.upstream_id} is at capacity ({self.in_flight} calls in flight, limit {self.limit}; '
            f'{len(self._waiters)} waiting, queue {self.queue}): {why}. Nothing was sent; retry in a moment.',
            retry_after=1.0)

    def reconfigure(self, limit: int, queue: int, queue_timeout: float) -> None:
        with self._lock:
            self.limit, self.queue = max(0, int(limit or 0)), max(0, int(queue or 0))
            self.queue_timeout = max(0.0, float(queue_timeout or 0.0))
            while self._waiters and (self.limit <= 0 or self.in_flight < self.limit):
                self._enter()                   # a raised limit admits those already in line
                self._waiters.popleft().set()

    def snapshot(self) -> Dict[str, Any]:
        return {'limit': self.limit, 'queue': self.queue, 'queue_timeout_seconds': self.queue_timeout,
                'in_flight': self.in_flight, 'waiting': len(self._waiters), 'admitted': self.admitted,
                'queued_total': self.queued_total, 'shed': self.shed, 'peak_in_flight': self.peak_in_flight}


# ── pool members and replicas ───────────────────────────────────────

_rr = itertools.count()


def pick_member(members: List[Any], exclude: Iterable[Any] = (), down_replicas: Iterable[int] = ()):
    """The connection for the next call, or None when no member is connected.

    Connected members only; members on a replica this worker or a peer sees failing come last;
    then the fewest calls in flight (fair use of the pool), the lowest latency, round robin."""
    skip = {id(m) for m in exclude}
    down = set(down_replicas)
    live = [m for m in members if id(m) not in skip and getattr(m, 'state', '') == 'connected']
    if not live:
        return None
    turn = next(_rr)
    n = len(live)

    def key(im):
        i, m = im
        bad = 1 if (getattr(m, 'replica', 0) in down or getattr(m, 'fail_streak', 0) > 0) else 0
        lat = getattr(m, 'ewma_ms', None)
        return (bad, getattr(m, 'in_flight', 0), round(lat / 25.0) if lat else 0, (i - turn) % n)
    return min(enumerate(live), key=key)[1]


def record_outcome(member: Any, ok: bool, elapsed_ms: float) -> None:
    """A call on ``member`` ended: latency (exponentially weighted) and the run of failures."""
    if ok:
        prev = getattr(member, 'ewma_ms', None)
        member.ewma_ms = elapsed_ms if prev is None else 0.8 * prev + 0.2 * elapsed_ms
        member.fail_streak = 0
    else:
        member.fail_streak = getattr(member, 'fail_streak', 0) + 1


# ── the cluster-wide view ───────────────────────────────────────────

class HealthBoard:
    """This worker's view of each upstream, published to the state store with a TTL, and every
    live worker's view read back. With the memory backend the view is this process only."""

    def __init__(self, worker_id: str, ttl: float = 30.0, store=None):
        self.worker_id = worker_id
        self.ttl = max(1.0, float(ttl))
        self._store = store
        self._views: Dict[str, List[Dict[str, Any]]] = {}
        self.last_read: Optional[float] = None

    def store(self):
        if self._store is None:
            from sajha.core.state import get_state_store
            return get_state_store()
        return self._store

    def publish(self, upstream_id: str, snapshot: Dict[str, Any]) -> None:
        doc = dict(snapshot, worker=self.worker_id, updated=time.time())
        self.store().set(f'{HEALTH_PREFIX}{upstream_id}:{self.worker_id}', doc, ttl=self.ttl)

    def forget(self, upstream_id: str) -> None:
        try:
            self.store().delete(f'{HEALTH_PREFIX}{upstream_id}:{self.worker_id}')
        except Exception:
            pass

    def read(self) -> Dict[str, List[Dict[str, Any]]]:
        """Every live report, by upstream id (newest first per worker); cached for :meth:`views`."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        for key, doc in self.store().scan(HEALTH_PREFIX):
            if not isinstance(doc, dict):
                continue
            # worker ids contain ':' (host:pid:nonce); an upstream id never does
            uid = key[len(HEALTH_PREFIX):].split(':', 1)[0]
            if not uid:
                continue
            out.setdefault(uid, []).append(doc)
        for docs in out.values():
            docs.sort(key=lambda d: str(d.get('worker', '')))
        self._views = out
        self.last_read = time.time()
        return out

    def views(self, upstream_id: str) -> List[Dict[str, Any]]:
        return list(self._views.get(upstream_id) or [])

    def peers(self, upstream_id: str) -> List[Dict[str, Any]]:
        return [d for d in self.views(upstream_id) if d.get('worker') != self.worker_id]

    def summary(self, upstream_id: str) -> Dict[str, Any]:
        """The cluster-wide view of one upstream, as status shows it."""
        docs = self.views(upstream_id)
        workers = []
        for d in docs:
            b = d.get('breaker') or {}
            workers.append({'worker': d.get('worker'), 'self': d.get('worker') == self.worker_id,
                            'state': d.get('state'), 'connected': d.get('connected'),
                            'pool': d.get('pool'), 'breaker': b.get('state'),
                            'breaker_source': b.get('source'), 'in_flight': d.get('in_flight'),
                            'waiting': d.get('waiting'), 'shed': d.get('shed'),
                            'latency_ms': d.get('latency_ms'), 'failures': d.get('failures'),
                            'last_error': d.get('last_error'), 'updated': d.get('updated')})
        return {
            'reporting': len(workers),
            'connected': sum(1 for w in workers if w['state'] == 'connected'),
            'breaker_open': [w['worker'] for w in workers if w['breaker'] in ('open', 'half_open')],
            'in_flight': sum(int(w['in_flight'] or 0) for w in workers),
            'shed': sum(int(w['shed'] or 0) for w in workers),
            'workers': workers,
            'read_at': self.last_read,
        }

    def down_replicas(self, upstream_id: str) -> List[int]:
        """Replicas a peer reports with no connected member (this worker judges its own members)."""
        down = set()
        for d in self.peers(upstream_id):
            for r in d.get('replicas') or []:
                if isinstance(r, dict) and r.get('members') and not r.get('connected'):
                    down.add(int(r.get('replica', 0)))
        return sorted(down)

    def open_breaker_from_peer(self, upstream_id: str) -> Optional[Dict[str, Any]]:
        """A peer's breaker for this upstream opened by that peer's own failures (not one it
        followed from another worker), the most recently opened; None when there is none."""
        best = None
        for d in self.peers(upstream_id):
            b = d.get('breaker') or {}
            if b.get('state') == 'open' and b.get('source') == 'local':
                if best is None or float(b.get('since') or 0) > float(best.get('since') or 0):
                    best = dict(b, worker=d.get('worker'))
        return best
