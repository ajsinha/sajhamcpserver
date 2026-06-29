"""
SAJHA MCP Server v5.3.0 — Webhook Notifications
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Sends POST notifications to registered callback URLs when:
- Composite tool execution completes
- Long-running MCP task completes/fails
- Tool health status changes (circuit breaker opens/closes)
"""
import json
import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class WebhookManager:
    """Manages webhook subscriptions and delivery."""

    def __init__(self, max_retries: int = 3, timeout: int = 10):
        self._subscriptions: Dict[str, List[str]] = {}  # event_type → [callback_urls]
        self._max_retries = max_retries
        self._timeout = timeout
        self._lock = threading.Lock()
        self._delivery_log: List[Dict] = []

    def subscribe(self, event_type: str, callback_url: str):
        """Register a callback URL for an event type."""
        with self._lock:
            if event_type not in self._subscriptions:
                self._subscriptions[event_type] = []
            if callback_url not in self._subscriptions[event_type]:
                self._subscriptions[event_type].append(callback_url)
                logger.info(f"Webhook subscribed: {event_type} → {callback_url}")

    def unsubscribe(self, event_type: str, callback_url: str):
        """Remove a callback URL from an event type."""
        with self._lock:
            if event_type in self._subscriptions:
                self._subscriptions[event_type] = [
                    u for u in self._subscriptions[event_type] if u != callback_url
                ]

    def notify(self, event_type: str, payload: Dict):
        """Send notification to all subscribers (async, non-blocking)."""
        with self._lock:
            urls = list(self._subscriptions.get(event_type, []))
        if not urls:
            return
        # Fire-and-forget in background threads
        for url in urls:
            t = threading.Thread(target=self._deliver, args=(event_type, url, payload), daemon=True)
            t.start()

    def _deliver(self, event_type: str, url: str, payload: Dict):
        """Deliver webhook with retries."""
        body = json.dumps({
            'event': event_type,
            'timestamp': time.time(),
            'data': payload,
        }).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'sajha-webhook/5.3.0',
            'X-Sajha-Event': event_type,
        }
        for attempt in range(1, self._max_retries + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method='POST')
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    status = resp.status
                    if 200 <= status < 300:
                        logger.info(f"Webhook delivered: {event_type} → {url} (HTTP {status})")
                        self._record_delivery(event_type, url, True, status)
                        return
            except Exception as e:
                logger.warning(f"Webhook delivery attempt {attempt}/{self._max_retries} failed: {url} — {e}", exc_info=True)
                if attempt < self._max_retries:
                    time.sleep(2 ** attempt)  # Exponential backoff
        self._record_delivery(event_type, url, False, 0)
        logger.error(f"Webhook delivery failed after {self._max_retries} attempts: {url}")

    def _record_delivery(self, event_type: str, url: str, success: bool, status: int):
        self._delivery_log.append({
            'event': event_type, 'url': url, 'success': success,
            'status': status, 'timestamp': time.time(),
        })
        if len(self._delivery_log) > 1000:
            self._delivery_log = self._delivery_log[-500:]

    def list_subscriptions(self) -> Dict:
        with self._lock:
            return dict(self._subscriptions)

    def delivery_stats(self) -> Dict:
        total = len(self._delivery_log)
        success = sum(1 for d in self._delivery_log if d['success'])
        return {
            'total_deliveries': total,
            'successful': success,
            'failed': total - success,
            'success_rate': round(success / max(total, 1) * 100, 1),
            'recent': self._delivery_log[-10:],
        }


# Event type constants
EVENT_TOOL_COMPLETED = 'tool.completed'
EVENT_TOOL_FAILED = 'tool.failed'
EVENT_TASK_COMPLETED = 'task.completed'
EVENT_TASK_FAILED = 'task.failed'
EVENT_CIRCUIT_OPENED = 'circuit.opened'
EVENT_CIRCUIT_CLOSED = 'circuit.closed'
EVENT_HEALTH_DEGRADED = 'health.degraded'

# Module singleton
_webhook_mgr: Optional[WebhookManager] = None

def get_webhook_manager() -> WebhookManager:
    global _webhook_mgr
    if _webhook_mgr is None:
        _webhook_mgr = WebhookManager()
    return _webhook_mgr
