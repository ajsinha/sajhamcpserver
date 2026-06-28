"""
SAJHA MCP Server v5.2.0 — Async Tool Executor
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
import urllib.request
import urllib.error
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

class DeliveryRouter:
    """Routes task results to the configured destination."""

    def __init__(self, webhook_timeout: int = 10, webhook_retries: int = 3,
                 kafka_config: Dict = None, file_base_dir: str = 'data/async_results',
                 file_max_size_mb: int = 50):
        self._webhook_timeout = webhook_timeout
        self._webhook_retries = webhook_retries
        self._kafka_config = kafka_config or {}
        self._kafka_producer = None
        self._file_base_dir = Path(file_base_dir)
        self._file_max_size_mb = file_max_size_mb

    def deliver(self, task: AsyncTask) -> bool:
        """Deliver task result to destination. Returns True on success."""
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
        """POST result to webhook URL with retries."""
        url = task.delivery_destination
        body = json.dumps(self._build_payload(task), default=str).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'sajha-async/5.2.0',
            'X-Sajha-Task-Id': task.task_id,
        }
        # Merge custom headers from delivery config
        headers.update(task.delivery_config.get('headers', {}))

        for attempt in range(1, self._webhook_retries + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=self._webhook_timeout) as resp:
                    if 200 <= resp.status < 300:
                        logger.info(f"Async webhook delivered: {task.task_id} → {url} (HTTP {resp.status})")
                        return True
            except Exception as e:
                logger.warning(f"Webhook attempt {attempt}/{self._webhook_retries}: {url} — {e}", exc_info=True)
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
            dest = Path(task.delivery_destination)
            if not dest.is_absolute():
                dest = self._file_base_dir / dest

            # Size check
            payload = json.dumps(self._build_payload(task), default=str, indent=2)
            if len(payload) > self._file_max_size_mb * 1024 * 1024:
                logger.error(f"File delivery skipped: result too large ({len(payload)} bytes)")
                return False

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix('.tmp')
            tmp.write_text(payload)
            tmp.rename(dest)  # Atomic on same filesystem
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

    def submit(self, tool_name: str, arguments: Dict, delivery_type: str,
               delivery_destination: str, delivery_config: Dict = None,
               user_id: str = None) -> AsyncTask:
        """
        Submit a tool for async execution.
        Returns AsyncTask immediately.
        Raises queue.Full if backpressure limit reached.
        """
        task = AsyncTask(
            task_id=f"t-{uuid.uuid4().hex[:12]}",
            tool_name=tool_name,
            arguments=arguments,
            delivery_type=delivery_type,
            delivery_destination=delivery_destination,
            delivery_config=delivery_config or {},
            user_id=user_id,
        )

        with self._lock:
            self._tasks[task.task_id] = task
            self._stats['submitted'] += 1

        # Submit to bounded queue (raises queue.Full on backpressure)
        self._queue.put_nowait(task)
        logger.info(f"Async task queued: {task.task_id} ({tool_name})")
        return task

    def get_task(self, task_id: str) -> Optional[AsyncTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, status: str = None, limit: int = 100) -> List[Dict]:
        with self._lock:
            self._cleanup_old_tasks()
            tasks = list(self._tasks.values())
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
                return True
        return False

    def retry_task(self, task_id: str) -> Optional[AsyncTask]:
        """Re-submit a failed task."""
        with self._lock:
            old = self._tasks.get(task_id)
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
        # Check if cancelled while queued
        if task.status == AsyncTaskStatus.CANCELLED:
            return

        task.status = AsyncTaskStatus.RUNNING
        task.started_at = time.time()

        try:
            # Get tool from registry
            from sajha.app import tools_registry
            tool = tools_registry.get_tool(task.tool_name) if tools_registry else None
            if not tool:
                raise ValueError(f"Tool not found: {task.tool_name}")

            # Execute (reuses cache, circuit breaker, replay)
            result = tool.execute_with_tracking(task.arguments)
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
        # Read config
        workers = 8
        queue_size = 1000
        task_ttl = 24
        delivery_config = {}
        try:
            from sajha.core.config import get_settings
            s = get_settings()
            workers = getattr(s, 'async_workers', 8)
            queue_size = getattr(s, 'async_queue_size', 1000)
            task_ttl = getattr(s, 'async_task_ttl_hours', 24)
        except Exception:
            pass
        _executor = AsyncExecutor(
            num_workers=workers,
            queue_size=queue_size,
            task_ttl_hours=task_ttl,
            delivery_config=delivery_config,
        )
        _executor.start()
    return _executor
