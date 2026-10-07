"""
SAJHA MCP Server v5.3.0 — Async Tool Executor
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Background execution engine for long-running tool calls.
Client gets task_id immediately; result delivered via webhook, Kafka, or file.

Architecture:
  API → AsyncTask(DB) → WorkQueue(bounded) → DaemonWorkerPool(N threads)
    → execute_with_tracking() → DeliveryRouter → webhook|kafka|file

Config: config/application.yml → async: section
"""
import json
import logging
import os
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# TASK MODEL
# ═══════════════════════════════════════════════════════════════════

class AsyncTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DELIVERED = "delivered"


def _run_as_submitter(task, fn):
    """Run ``fn`` as the task's submitter with source ``async`` (policy rules, usage ledger)."""
    from sajha.observability.caller import Caller, reset, set_caller
    from sajha.policy.context import reset_source, set_source
    who = getattr(task, '_caller', None) or Caller(user_id=task.user_id or 'anonymous')
    t_caller, t_source = set_caller(who), set_source('async')
    from sajha.observability import tracing as _tracing
    try:
        # the submitting request's trace continues in the worker (outbound calls, audit records)
        with _tracing.span(f'async {task.tool_name}', traceparent=getattr(task, '_traceparent', None),
                           ensure_trace=True):
            return fn()
    finally:
        reset(t_caller)
        reset_source(t_source)


@dataclass
class AsyncTask:
    """A background tool execution task."""
    task_id: str
    tool_name: str
    arguments: Dict
    delivery_type: str           # webhook | kafka | file
    delivery_destination: str    # URL, topic, or path
    delivery_config: Dict = field(default_factory=dict)  # headers, kafka_key, etc.
    status: AsyncTaskStatus = AsyncTaskStatus.QUEUED
    result: Optional[Any] = None
    error: Optional[str] = None
    user_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    delivered_at: Optional[float] = None
    duration_ms: Optional[float] = None
    delivery_status: Optional[str] = None  # success | failed | pending
    worker: Optional[str] = None           # the process whose queue holds / ran it

    def to_record(self) -> Dict:
        """What other workers see (shared state store).  Delivery headers stay in this process."""
        return {
            'task_id': self.task_id, 'tool_name': self.tool_name, 'arguments': self.arguments,
            'delivery_type': self.delivery_type, 'delivery_destination': self.delivery_destination,
            'delivery_config': {k: v for k, v in (self.delivery_config or {}).items() if k != 'headers'},
            'status': self.status.value, 'result': self.result, 'error': self.error, 'user_id': self.user_id,
            'created_at': self.created_at, 'started_at': self.started_at, 'completed_at': self.completed_at,
            'delivered_at': self.delivered_at, 'duration_ms': self.duration_ms,
            'delivery_status': self.delivery_status, 'worker': self.worker,
        }

    @classmethod
    def from_record(cls, rec: Dict) -> 'AsyncTask':
        rec = dict(rec)
        rec['status'] = AsyncTaskStatus(rec.get('status', 'queued'))
        return cls(**{k: v for k, v in rec.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> Dict:
        d = {
            'task_id': self.task_id,
            'tool_name': self.tool_name,
            'status': self.status.value,
            'delivery_type': self.delivery_type,
            'delivery_destination': self.delivery_destination,
            'user_id': self.user_id,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'duration_ms': self.duration_ms,
            'delivery_status': self.delivery_status,
        }
        if self.status == AsyncTaskStatus.COMPLETED or self.status == AsyncTaskStatus.DELIVERED:
            d['result_preview'] = self._preview(self.result)
        if self.error:
            d['error'] = self.error
        return d

    def to_full_dict(self) -> Dict:
        """Full dict including arguments and result (for detail view)."""
        d = self.to_dict()
        d['arguments'] = self.arguments
        d['result'] = self.result
        d['delivery_config'] = {k: v for k, v in self.delivery_config.items() if k != 'headers'}
        return d

    @staticmethod
    def _preview(result: Any, max_len: int = 200) -> str:
        try:
            s = json.dumps(result, default=str)
            return s[:max_len] + ('...' if len(s) > max_len else '')
        except Exception:
            return str(result)[:max_len]


# ═══════════════════════════════════════════════════════════════════
# DELIVERY ROUTER
# ═══════════════════════════════════════════════════════════════════

class DeliveryError(ValueError):
    """A delivery destination that policy does not allow."""


_DEFAULT_PORTS = {'http': 80, 'https': 443}
_BLOCKED_WEBHOOK_HEADERS = {'host', 'content-length', 'transfer-encoding', 'connection'}


def _webhook_allowed_urls() -> List[str]:
    from sajha.core.config import _list
    return _list('async.delivery.webhook.allowed_urls', [])


def url_matches_prefix(url: str, prefix: str) -> bool:
    """Same scheme, host and port as ``prefix`` and a path at or under its path."""
    from urllib.parse import urlsplit
    try:
        u, p = urlsplit(url), urlsplit(prefix.strip())
        u_port = u.port or _DEFAULT_PORTS.get(u.scheme)
        p_port = p.port or _DEFAULT_PORTS.get(p.scheme)
    except ValueError:
        return False
    if not p.scheme or not p.hostname:
        return False
    if (u.scheme, (u.hostname or '').lower(), u_port) != (p.scheme, p.hostname.lower(), p_port):
        return False
    base = p.path.rstrip('/')
    return not base or u.path == base or u.path.startswith(base + '/')


class DeliveryRouter:
    """Routes task results to the configured destination."""

    def __init__(self, webhook_timeout: int = 10, webhook_retries: int = 3,
                 kafka_config: Dict = None, file_base_dir: str = 'data/async_results',
                 file_max_size_mb: int = 50, webhook_allowed_urls: Optional[Callable[[], List[str]]] = None,
                 webhook_allow_private: bool = False):
        self._webhook_timeout = webhook_timeout
        self._webhook_retries = webhook_retries
        self._kafka_config = kafka_config or {}
        self._kafka_producer = None
        self._file_base_dir = Path(file_base_dir)
        self._file_max_size_mb = file_max_size_mb
        self._webhook_allowed_urls = webhook_allowed_urls or _webhook_allowed_urls
        self._webhook_allow_private = webhook_allow_private

    # -- destination policy ------------------------------------------------

    def validate(self, delivery_type: str, destination: str) -> None:
        """Raise DeliveryError when the destination is not allowed (checked on submit and on delivery)."""
        if delivery_type == 'webhook':
            self._check_webhook_url(destination)
        elif delivery_type == 'file':
            self.resolve_file_destination(destination)
        elif delivery_type == 'kafka':
            if not destination or len(destination) > 249 or not all(
                    c.isalnum() or c in '._-' for c in destination):
                raise DeliveryError('kafka destination must be a topic name ([A-Za-z0-9._-], max 249)')
        else:
            raise DeliveryError('delivery must be webhook, kafka, or file')

    def _check_webhook_url(self, url: str):
        from urllib.parse import urlsplit
        try:
            p = urlsplit(url or '')
            p.port
        except ValueError:
            raise DeliveryError('webhook destination is not a valid URL')
        if p.scheme not in ('http', 'https') or not p.hostname:
            raise DeliveryError('webhook destination must be an http(s) URL')
        if p.username or p.password or '@' in p.netloc:
            raise DeliveryError('webhook URL must not contain credentials')
        allowed = self._webhook_allowed_urls()
        if not any(url_matches_prefix(url, prefix) for prefix in allowed):
            raise DeliveryError('webhook destination is not in async.delivery.webhook.allowed_urls')
        return p

    def _resolve_webhook_ip(self, host: str, port: int) -> str:
        """Resolve once and vet every address (the OAuth CIMD SSRF guard); returns the IP to connect to."""
        import ipaddress
        import socket
        from sajha.auth.oauth.clients import address_allowed
        try:
            addrs = [str(ipaddress.ip_address(host.strip('[]')))]
        except ValueError:
            try:
                addrs = [r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
            except OSError as e:
                raise DeliveryError(f'webhook host does not resolve: {e}')
        if not addrs:
            raise DeliveryError('webhook host does not resolve')
        for addr in addrs:
            if not address_allowed(ipaddress.ip_address(addr.split('%')[0]), host.lower(),
                                   allow_localhost=self._webhook_allow_private,
                                   allow_private=self._webhook_allow_private):
                raise DeliveryError('webhook host resolves to a non-public address '
                                    '(async.delivery.webhook.allow_private_networks)')
        return addrs[0]

    def resolve_file_destination(self, destination: str) -> Path:
        """A file destination inside the configured base directory (relative path, no traversal)."""
        rel = Path(destination or '')
        if not destination or rel.is_absolute() or destination.startswith(('/', '\\')) \
                or '..' in rel.parts or ':' in destination or '\x00' in destination:
            raise DeliveryError('file destination must be a relative path inside '
                                'async.delivery.file.base_dir (no "..", no absolute path)')
        base = self._file_base_dir
        if not base.is_absolute():
            base = Path.cwd() / base
        base = base.resolve()
        dest = (base / rel).resolve()
        if dest == base or base not in dest.parents:
            raise DeliveryError('file destination escapes async.delivery.file.base_dir')
        return dest

    def deliver(self, task: AsyncTask) -> bool:
        """Deliver task result to destination. Returns True on success."""
        try:
            self.validate(task.delivery_type, task.delivery_destination)
        except DeliveryError as e:
            logger.error(f"Delivery refused for task {task.task_id}: {e}")
            task.error = task.error or f'delivery refused: {e}'
            return False
        try:
            if task.delivery_type == 'webhook':
                return self._deliver_webhook(task)
            elif task.delivery_type == 'kafka':
                return self._deliver_kafka(task)
            elif task.delivery_type == 'file':
                return self._deliver_file(task)
            else:
                logger.error(f"Unknown delivery type: {task.delivery_type}")
                return False
        except Exception as e:
            logger.error(f"Delivery failed for task {task.task_id}: {e}", exc_info=True)
            return False

    def _build_payload(self, task: AsyncTask) -> Dict:
        return {
            'task_id': task.task_id,
            'tool_name': task.tool_name,
            'status': task.status.value,
            'result': task.result,
            'error': task.error,
            'arguments': task.arguments,
            'duration_ms': task.duration_ms,
            'timestamp': time.time(),
        }

    def _deliver_webhook(self, task: AsyncTask) -> bool:
        """POST result to an allow-listed webhook URL with retries (pinned IP, no redirects)."""
        import httpx
        from urllib.parse import urlunsplit
        url = task.delivery_destination
        p = self._check_webhook_url(url)
        body = json.dumps(self._build_payload(task), default=str).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'sajha-async',
            'X-Sajha-Task-Id': task.task_id,
        }
        if getattr(task, '_traceparent', None):          # W3C trace context of the submitting request
            headers['traceparent'] = task._traceparent
        # Merge custom headers from delivery config (never Host / framing headers)
        custom = task.delivery_config.get('headers', {})
        if isinstance(custom, dict):
            headers.update({str(k): str(v) for k, v in custom.items()
                            if str(k).lower() not in _BLOCKED_WEBHOOK_HEADERS})
        port = p.port or _DEFAULT_PORTS[p.scheme]
        headers['Host'] = p.netloc

        for attempt in range(1, self._webhook_retries + 1):
            try:
                # Resolve and vet on every attempt; connect to the vetted IP (no DNS rebinding)
                ip = self._resolve_webhook_ip(p.hostname, port)
                ip_host = f'[{ip}]' if ':' in ip else ip
                pinned = urlunsplit((p.scheme, f'{ip_host}:{port}', p.path or '/', p.query, ''))
                with httpx.Client(timeout=self._webhook_timeout, follow_redirects=False,
                                  trust_env=False) as client:
                    resp = client.post(pinned, content=body, headers=headers,
                                       extensions={'sni_hostname': p.hostname})
                if 200 <= resp.status_code < 300:
                    logger.info(f"Async webhook delivered: {task.task_id} → {p.hostname} (HTTP {resp.status_code})")
                    return True
                logger.warning(f"Webhook attempt {attempt}/{self._webhook_retries}: {p.hostname} "
                               f"returned HTTP {resp.status_code}")
            except DeliveryError as e:
                logger.error(f"Webhook delivery refused for {task.task_id}: {e}")
                return False
            except Exception as e:
                logger.warning(f"Webhook attempt {attempt}/{self._webhook_retries}: {p.hostname} — "
                               f"{type(e).__name__}: {e}")
            if attempt < self._webhook_retries:
                time.sleep(2 ** attempt)
        return False

    def _deliver_kafka(self, task: AsyncTask) -> bool:
        """Produce message to Kafka topic."""
        try:
            if self._kafka_producer is None:
                from confluent_kafka import Producer
                self._kafka_producer = Producer(self._kafka_config)

            topic = task.delivery_destination
            key = task.delivery_config.get('kafka_key', task.task_id)
            value = json.dumps(self._build_payload(task), default=str).encode('utf-8')

            self._kafka_producer.produce(topic, key=key.encode('utf-8'), value=value)
            self._kafka_producer.flush(timeout=10)
            logger.info(f"Async Kafka delivered: {task.task_id} → {topic}:{key}")
            return True
        except ImportError:
            logger.error("confluent_kafka not installed. pip install confluent-kafka", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Kafka delivery failed: {e}", exc_info=True)
            return False

    def _deliver_file(self, task: AsyncTask) -> bool:
        """Write result to filesystem (atomic write via temp file + rename)."""
        try:
            dest = self.resolve_file_destination(task.delivery_destination)

            # Size check
            payload = json.dumps(self._build_payload(task), default=str, indent=2)
            if len(payload) > self._file_max_size_mb * 1024 * 1024:
                logger.error(f"File delivery skipped: result too large ({len(payload)} bytes)")
                return False

            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_symlink():
                raise DeliveryError('file destination is a symbolic link')
            tmp = dest.with_name(f'.{dest.name}.{uuid.uuid4().hex[:8]}.tmp')
            tmp.write_text(payload)
            os.replace(tmp, dest)  # Atomic on same filesystem
            logger.info(f"Async file delivered: {task.task_id} → {dest}")
            return True
        except Exception as e:
            logger.error(f"File delivery failed: {e}", exc_info=True)
            return False


# ═══════════════════════════════════════════════════════════════════
# ASYNC EXECUTOR (Worker Pool + Queue)
# ═══════════════════════════════════════════════════════════════════

class AsyncExecutor:
    """
    Background execution engine with bounded work queue and daemon worker pool.

    Backpressure: rejects with queue.Full when queue_size exceeded.
    Workers reuse execute_with_tracking() for cache/circuit/replay integration.
    """

    def __init__(self, num_workers: int = 8, queue_size: int = 1000,
                 task_ttl_hours: int = 24, delivery_config: Dict = None):
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._tasks: Dict[str, AsyncTask] = {}
        self._lock = threading.Lock()
        self._num_workers = num_workers
        self._task_ttl_hours = task_ttl_hours
        self._workers: List[threading.Thread] = []
        self._running = False
        self._stats = {'submitted': 0, 'completed': 0, 'failed': 0, 'delivered': 0, 'cancelled': 0}

        # Delivery router
        dc = delivery_config or {}
        self._router = DeliveryRouter(
            webhook_timeout=dc.get('webhook', {}).get('timeout', 10),
            webhook_retries=dc.get('webhook', {}).get('max_retries', 3),
            kafka_config={'bootstrap.servers': dc.get('kafka', {}).get('bootstrap_servers', 'localhost:9092')},
            file_base_dir=dc.get('file', {}).get('base_dir', 'data/async_results'),
            file_max_size_mb=dc.get('file', {}).get('max_size_mb', 50),
            webhook_allow_private=bool(dc.get('webhook', {}).get('allow_private_networks', False)),
        )

    def start(self):
        """Start the worker pool."""
        if self._running:
            return
        self._running = True
        for i in range(self._num_workers):
            t = threading.Thread(target=self._worker_loop, name=f"async-worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        logger.info(f"Async executor started: {self._num_workers} workers, queue={self._queue.maxsize}")

    def stop(self):
        """Signal workers to stop (graceful shutdown)."""
        self._running = False
        # Send poison pills
        for _ in self._workers:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    # ── shared records (state.backend redis / database) ──────────────

    _KEY = 'async:task:'

    @staticmethod
    def _shared_store():
        """The state store when it is shared between workers, else None (memory: nothing to do)."""
        try:
            from sajha.core.state import get_state_store
            store = get_state_store()
        except Exception:
            return None
        return store if store.shared else None

    def _persist(self, task: 'AsyncTask') -> None:
        store = self._shared_store()
        if store is None:
            return
        try:
            store.set(self._KEY + task.task_id, task.to_record(), ttl=self._task_ttl_hours * 3600)
        except Exception as e:
            logger.warning(f"Async task {task.task_id}: shared record not written: {e}")

    def _remote(self, task_id: str) -> Optional['AsyncTask']:
        """A task another worker queued, from the shared store (orphans failed on read)."""
        store = self._shared_store()
        rec = store.get(self._KEY + task_id) if store is not None else None
        if rec is None:
            return None
        task = AsyncTask.from_record(rec)
        return self._reap(store, task)

    def _reap(self, store, task: 'AsyncTask') -> 'AsyncTask':
        from sajha.core.state import worker_alive
        if task.status in (AsyncTaskStatus.QUEUED, AsyncTaskStatus.RUNNING) and not worker_alive(task.worker, store):
            task.status = AsyncTaskStatus.FAILED
            task.error = 'The worker holding this task stopped before it finished'
            task.completed_at = time.time()
            self._persist(task)
        return task

    def submit(self, tool_name: str, arguments: Dict, delivery_type: str,
               delivery_destination: str, delivery_config: Dict = None,
               user_id: str = None) -> AsyncTask:
        """
        Submit a tool for async execution.
        Returns AsyncTask immediately.
        Raises DeliveryError for a destination policy does not allow,
        queue.Full if backpressure limit reached.
        """
        self._router.validate(delivery_type, delivery_destination)
        task = AsyncTask(
            task_id=f"t-{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            arguments=arguments,
            delivery_type=delivery_type,
            delivery_destination=delivery_destination,
            delivery_config=delivery_config or {},
            user_id=user_id,
        )
        from sajha.core.state import WORKER_ID
        task.worker = WORKER_ID
        try:   # the submitter, for the usage ledger and the policy engine (not persisted)
            from sajha.observability.caller import current as _current_caller
            who = _current_caller()
            task._caller = who if who.user_id == (user_id or who.user_id) else None
        except Exception:
            task._caller = None
        try:
            from sajha.observability.tracing import current_traceparent
            task._traceparent = current_traceparent()
        except Exception:
            task._traceparent = None

        with self._lock:
            self._tasks[task.task_id] = task
            self._stats['submitted'] += 1
        self._persist(task)

        # Submit to bounded queue (raises queue.Full on backpressure)
        self._queue.put_nowait(task)
        logger.info(f"Async task queued: {task.task_id} ({tool_name})")
        return task

    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        with self._lock:
            task = self._tasks.get(task_id)
        return task if task is not None else self._remote(task_id)

    def list_tasks(self, status: str = None, limit: int = 100, user_id: Optional[str] = None) -> List[Dict]:
        """Tasks newest first; only ``user_id``'s tasks when given (None = all, for admins)."""
        with self._lock:
            self._cleanup_old_tasks()
            tasks = list(self._tasks.values())
        store = self._shared_store()
        if store is not None:
            local = {t.task_id for t in tasks}
            tasks += [self._reap(store, AsyncTask.from_record(rec)) for _, rec in store.scan(self._KEY)
                      if rec.get('task_id') not in local]
        if user_id is not None:
            tasks = [t for t in tasks if t.user_id == user_id]
        if status:
            tasks = [t for t in tasks if t.status.value == status]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.status == AsyncTaskStatus.QUEUED:
                task.status = AsyncTaskStatus.CANCELLED
                self._stats['cancelled'] += 1
                cancelled = True
            else:
                cancelled = False
        if cancelled:
            self._persist(task)
            return True
        store = self._shared_store()
        if task is None and store is not None:
            # queued on another worker: mark the shared record; that worker checks it before running
            done = []

            def fn(rec):
                if rec is None or rec.get('status') != AsyncTaskStatus.QUEUED.value:
                    return rec
                done.append(True)
                return dict(rec, status=AsyncTaskStatus.CANCELLED.value)
            store.update(self._KEY + task_id, fn)
            return bool(done)
        return False

    def retry_task(self, task_id: str) -> Optional[AsyncTask]:
        """Re-submit a failed task."""
        with self._lock:
            old = self._tasks.get(task_id)
        if old is None:
            old = self._remote(task_id)
        if not old or old.status not in (AsyncTaskStatus.FAILED, AsyncTaskStatus.CANCELLED):
            return None
        return self.submit(old.tool_name, old.arguments, old.delivery_type,
                          old.delivery_destination, old.delivery_config, old.user_id)

    def stats(self) -> Dict:
        with self._lock:
            return {
                'workers': self._num_workers,
                'queue_size': self._queue.qsize(),
                'queue_max': self._queue.maxsize,
                'total_tasks': len(self._tasks),
                **self._stats,
            }

    def _worker_loop(self):
        """Worker thread main loop."""
        while self._running:
            try:
                task = self._queue.get(timeout=1)
                if task is None:  # Poison pill
                    break
                self._execute_task(task)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)

    def _execute_task(self, task: AsyncTask):
        """Execute a single task: run tool + deliver result."""
        # Check if cancelled while queued (here, or on another worker via the shared record)
        if task.status == AsyncTaskStatus.CANCELLED:
            return
        store = self._shared_store()
        if store is not None:
            rec = store.get(self._KEY + task.task_id)
            if rec and rec.get('status') == AsyncTaskStatus.CANCELLED.value:
                task.status = AsyncTaskStatus.CANCELLED
                return

        task.status = AsyncTaskStatus.RUNNING
        task.started_at = time.time()
        self._persist(task)

        try:
            # Get tool from registry
            from sajha.app import tools_registry
            tool = tools_registry.get_tool(task.tool_name) if tools_registry else None
            if not tool:
                raise ValueError(f"Tool not found: {task.tool_name}")

            # Execute (reuses cache, circuit breaker, replay)
            result = _run_as_submitter(task, lambda: tool.execute_with_tracking(task.arguments))
            task.result = result
            task.status = AsyncTaskStatus.COMPLETED
            task.completed_at = time.time()
            task.duration_ms = round((task.completed_at - task.started_at) * 1000, 1)

            with self._lock:
                self._stats['completed'] += 1

            logger.info(f"Async task completed: {task.task_id} ({task.duration_ms}ms)")

        except Exception as e:
            task.error = str(e)
            task.status = AsyncTaskStatus.FAILED
            task.completed_at = time.time()
            task.duration_ms = round((task.completed_at - task.started_at) * 1000, 1)

            with self._lock:
                self._stats['failed'] += 1

            logger.error(f"Async task failed: {task.task_id} — {e}", exc_info=True)

        # Deliver result
        try:
            success = self._router.deliver(task)
            task.delivery_status = 'success' if success else 'failed'
            task.delivered_at = time.time() if success else None
            if success:
                task.status = AsyncTaskStatus.DELIVERED
                with self._lock:
                    self._stats['delivered'] += 1
        except Exception as e:
            task.delivery_status = 'failed'
            logger.error(f"Delivery failed for {task.task_id}: {e}", exc_info=True)
        self._persist(task)

    def _cleanup_old_tasks(self):
        """Remove tasks older than TTL."""
        cutoff = time.time() - (self._task_ttl_hours * 3600)
        to_remove = [tid for tid, t in self._tasks.items()
                     if t.created_at < cutoff and t.status in
                     (AsyncTaskStatus.COMPLETED, AsyncTaskStatus.DELIVERED,
                      AsyncTaskStatus.FAILED, AsyncTaskStatus.CANCELLED)]
        for tid in to_remove:
            del self._tasks[tid]


# ═══════════════════════════════════════════════════════════════════
# MODULE SINGLETON
# ═══════════════════════════════════════════════════════════════════

_executor: Optional[AsyncExecutor] = None


def get_async_executor() -> AsyncExecutor:
    global _executor
    if _executor is None:
        # Read config (async.* in application.yml, SAJHA_ASYNC_* env)
        workers = 8
        queue_size = 1000
        task_ttl = 24
        delivery_config = {}
        try:
            from sajha.core.config import get_settings
            s = get_settings()
            workers = s.async_workers
            queue_size = s.async_queue_size
            task_ttl = s.async_task_ttl_hours
            delivery_config = {
                'webhook': {'timeout': s.async_webhook_timeout, 'max_retries': s.async_webhook_max_retries,
                            'allow_private_networks': s.async_webhook_allow_private_networks},
                'kafka': {'bootstrap_servers': s.async_kafka_bootstrap_servers},
                'file': {'base_dir': s.async_file_base_dir, 'max_size_mb': s.async_file_max_size_mb},
            }
        except Exception as e:
            logger.warning(f'Async executor config unavailable, using defaults: {e}')
        _executor = AsyncExecutor(
            num_workers=workers,
            queue_size=queue_size,
            task_ttl_hours=task_ttl,
            delivery_config=delivery_config,
        )
        _executor.start()
    return _executor
