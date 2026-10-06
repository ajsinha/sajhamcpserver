"""
SAJHA MCP Server — Observability
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The JSON tool-metrics collector (/api/metrics), health probes (/health, /ready) and the
start-up of the observability layer: Prometheus metrics (metrics.py, /metrics),
OpenTelemetry (tracing.py), the usage ledger (usage.py) and alert rules (alerts.py).
Design: docs/architecture/Observability.md.
"""

import time
import math
import logging
import threading
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


# ── Metric Data Structures ───────────────────────────────────

@dataclass
class LatencyHistogram:
    """Streaming percentile calculator using sorted insertion."""
    values: List[float] = field(default_factory=list)
    _max_size: int = 10000

    def record(self, value_ms: float):
        if len(self.values) >= self._max_size:
            self.values = self.values[self._max_size // 2:]  # trim oldest half
        self.values.append(value_ms)

    def percentile(self, p: float) -> float:
        if not self.values:
            return 0.0
        s = sorted(self.values)
        k = (len(s) - 1) * (p / 100)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return s[int(k)]
        return s[f] * (c - k) + s[c] * (k - f)

    @property
    def p50(self) -> float: return self.percentile(50)
    @property
    def p95(self) -> float: return self.percentile(95)
    @property
    def p99(self) -> float: return self.percentile(99)
    @property
    def count(self) -> int: return len(self.values)
    @property
    def mean(self) -> float: return sum(self.values) / len(self.values) if self.values else 0


@dataclass
class ToolMetrics:
    """Per-tool metrics accumulator."""
    tool_name: str
    total_calls: int = 0
    success_count: int = 0
    error_count: int = 0
    latency: LatencyHistogram = field(default_factory=LatencyHistogram)
    last_error: str = ''
    last_error_at: Optional[datetime] = None
    last_call_at: Optional[datetime] = None

    @property
    def success_rate(self) -> float:
        return (self.success_count / self.total_calls * 100) if self.total_calls else 0

    @property
    def error_rate(self) -> float:
        return (self.error_count / self.total_calls * 100) if self.total_calls else 0

    def to_dict(self) -> Dict:
        return {
            'tool_name': self.tool_name,
            'total_calls': self.total_calls,
            'success_count': self.success_count,
            'error_count': self.error_count,
            'success_rate': round(self.success_rate, 2),
            'latency_p50_ms': round(self.latency.p50, 2),
            'latency_p95_ms': round(self.latency.p95, 2),
            'latency_p99_ms': round(self.latency.p99, 2),
            'latency_mean_ms': round(self.latency.mean, 2),
            'last_error': self.last_error,
            'last_error_at': self.last_error_at.isoformat() if self.last_error_at else None,
            'last_call_at': self.last_call_at.isoformat() if self.last_call_at else None,
        }


# ── Alert Rules ──────────────────────────────────────────────

@dataclass
class AlertRule:
    """Declarative alert condition."""
    name: str
    metric: str           # 'error_rate', 'latency_p95', 'error_count'
    operator: str         # 'gt', 'lt', 'gte', 'lte'
    threshold: float
    window_minutes: int = 5
    cooldown_minutes: int = 15
    webhook_url: str = ''
    last_fired: Optional[datetime] = None
    enabled: bool = True


# ── Metrics Collector (singleton) ────────────────────────────

class MetricsCollector:
    """
    Central metrics store for all tool executions.
    Thread-safe. Records latency, success/failure, and evaluates alert rules.
    """

    def __init__(self):
        self._tools: Dict[str, ToolMetrics] = {}
        self._lock = threading.Lock()
        self._alert_rules: List[AlertRule] = []
        self._alert_callbacks: List[Callable] = []
        self._window_errors: Dict[str, List[datetime]] = defaultdict(list)

    def record_execution(self, tool_name: str, duration_ms: float,
                         success: bool, error: str = ''):
        """Record a single tool execution."""
        now = datetime.utcnow()
        with self._lock:
            if tool_name not in self._tools:
                self._tools[tool_name] = ToolMetrics(tool_name=tool_name)
            m = self._tools[tool_name]
            m.total_calls += 1
            m.latency.record(duration_ms)
            m.last_call_at = now
            if success:
                m.success_count += 1
            else:
                m.error_count += 1
                m.last_error = error[:500]
                m.last_error_at = now
                self._window_errors[tool_name].append(now)

        # Check alerts (outside lock)
        self._evaluate_alerts(tool_name)

    def get_tool_metrics(self, tool_name: str) -> Optional[Dict]:
        with self._lock:
            m = self._tools.get(tool_name)
            return m.to_dict() if m else None

    def get_all_metrics(self) -> List[Dict]:
        with self._lock:
            return [m.to_dict() for m in sorted(self._tools.values(),
                    key=lambda x: x.total_calls, reverse=True)]

    def get_summary(self) -> Dict:
        with self._lock:
            total = sum(m.total_calls for m in self._tools.values())
            errors = sum(m.error_count for m in self._tools.values())
            all_latencies = []
            for m in self._tools.values():
                all_latencies.extend(m.latency.values)
            p50 = p95 = p99 = 0.0
            if all_latencies:
                h = LatencyHistogram()
                h.values = all_latencies
                p50, p95, p99 = h.p50, h.p95, h.p99
            return {
                'total_tools_called': len(self._tools),
                'total_executions': total,
                'total_errors': errors,
                'global_success_rate': round((total - errors) / total * 100, 2) if total else 0,
                'global_latency_p50_ms': round(p50, 2),
                'global_latency_p95_ms': round(p95, 2),
                'global_latency_p99_ms': round(p99, 2),
            }

    # ── Alerts ────────────────────────────────────────────────

    def add_alert_rule(self, rule: AlertRule):
        self._alert_rules.append(rule)

    def on_alert(self, callback: Callable):
        """Register callback: callback(rule_name, tool_name, metric_value, threshold)."""
        self._alert_callbacks.append(callback)

    def _evaluate_alerts(self, tool_name: str):
        now = datetime.utcnow()
        m = self._tools.get(tool_name)
        if not m:
            return
        for rule in self._alert_rules:
            if not rule.enabled:
                continue
            if rule.last_fired and (now - rule.last_fired).total_seconds() < rule.cooldown_minutes * 60:
                continue

            value = 0.0
            if rule.metric == 'error_rate':
                value = m.error_rate
            elif rule.metric == 'latency_p95':
                value = m.latency.p95
            elif rule.metric == 'latency_p99':
                value = m.latency.p99
            elif rule.metric == 'error_count':
                cutoff = now - timedelta(minutes=rule.window_minutes)
                self._window_errors[tool_name] = [
                    t for t in self._window_errors[tool_name] if t > cutoff]
                value = len(self._window_errors[tool_name])

            triggered = False
            if rule.operator == 'gt' and value > rule.threshold: triggered = True
            elif rule.operator == 'gte' and value >= rule.threshold: triggered = True
            elif rule.operator == 'lt' and value < rule.threshold: triggered = True

            if triggered:
                rule.last_fired = now
                for cb in self._alert_callbacks:
                    try:
                        cb(rule.name, tool_name, value, rule.threshold)
                    except Exception as e:
                        logger.warning(f"Alert callback error: {e}", exc_info=True)


# ── OpenTelemetry Integration ────────────────────────────────

class OTELIntegration:
    """
    Optional OpenTelemetry integration.
    If otel SDK is installed, creates real traces/metrics.
    Otherwise, uses the MetricsCollector as fallback.
    """

    def __init__(self, service_name: str = 'sajha-mcp-server'):
        self.service_name = service_name
        self._tracer = None
        self._meter = None
        self._tool_duration_histogram = None
        self._tool_call_counter = None
        self._enabled = False
        self._try_init()

    def _try_init(self):
        """OpenTelemetry is configured by tracing.py (observability.otel.*, OTEL_* env); off by default."""
        from sajha.observability import tracing
        tracing.init_tracing()
        self._tracer = tracing.tracer()
        self._enabled = self._tracer is not None

    def start_span(self, tool_name: str, user_id: str = '') -> Optional[object]:
        if not self._enabled or not self._tracer:
            return None
        span = self._tracer.start_span(
            f'tool.execute.{tool_name}',
            attributes={
                'tool.name': tool_name,
                'user.id': user_id,
                'service.name': self.service_name,
            })
        return span

    def end_span(self, span, duration_ms: float, success: bool, error: str = ''):
        if not span:
            return
        try:
            from opentelemetry.trace import StatusCode
            if not success:
                span.set_status(StatusCode.ERROR, error[:200])
                span.set_attribute('error.message', error[:500])
            span.set_attribute('tool.duration_ms', duration_ms)
            span.set_attribute('tool.success', success)
            span.end()
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
            pass

    def record_metric(self, tool_name: str, duration_ms: float, success: bool):
        from sajha.observability import tracing
        tracing.record_metric('sajha.tool.duration', 'histogram', duration_ms / 1000.0,
                              {'sajha.tool.name': tool_name, 'success': str(success)})


# ── Health Probes ────────────────────────────────────────────

class HealthProbe:
    """Kubernetes-style health probes: liveness + readiness."""

    def __init__(self):
        self._ready = False
        self._checks: Dict[str, Callable] = {}

    def set_ready(self, ready: bool = True):
        self._ready = ready

    def register_check(self, name: str, check_fn: Callable):
        """Register a readiness check: fn() -> bool."""
        self._checks[name] = check_fn

    def liveness(self) -> Dict:
        """Always returns OK if the process is running."""
        return {'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}

    def readiness(self) -> Dict:
        """Returns OK only if all registered checks pass."""
        results = {}
        all_ok = self._ready
        for name, fn in self._checks.items():
            try:
                ok = fn()
                results[name] = 'ok' if ok else 'fail'
                if not ok:
                    all_ok = False
            except Exception as e:
                results[name] = f'error: {e}'
                all_ok = False
        return {
            'status': 'ok' if all_ok else 'degraded',
            'checks': results,
            'timestamp': datetime.utcnow().isoformat(),
        }


# ── Singleton ────────────────────────────────────────────────

_collector: Optional[MetricsCollector] = None
_otel: Optional[OTELIntegration] = None
_health: Optional[HealthProbe] = None


def init_observability(service_name: str = 'sajha-mcp-server') -> tuple:
    """Start the layer: collector, OpenTelemetry, health probes, alert rules, the metrics
    snapshot publisher (several workers) and the optional separate metrics port."""
    global _collector, _otel, _health
    _collector = MetricsCollector()
    _otel = OTELIntegration(service_name)
    _health = HealthProbe()
    try:
        from sajha.observability import alerts, metrics, usage
        alerts.init_alerts()
        if not metrics.start_publisher():
            from sajha.core.state import worker_count_hint
            if worker_count_hint() > 1 and metrics._shared_store() is None:
                logger.warning("  Metrics: several workers but no shared state store (state.backend); "
                               "each /metrics scrape shows one worker only")
        if usage.enabled():
            usage.ensure_table()
        from sajha.observability.server import start_metrics_server
        start_metrics_server()
    except Exception as e:
        logger.warning(f"Observability: partial start ({e})", exc_info=True)
    return _collector, _otel, _health


def shutdown_observability() -> None:
    try:
        from sajha.observability import alerts, metrics, tracing, usage
        from sajha.observability.server import stop_metrics_server
        alerts.shutdown()
        metrics.stop_publisher()
        stop_metrics_server()
        usage.shutdown()
        tracing.shutdown()
    except Exception as e:
        logger.debug(f"observability shutdown: {e}")


def get_collector() -> Optional[MetricsCollector]:
    return _collector

def get_otel() -> Optional[OTELIntegration]:
    return _otel

def get_health() -> Optional[HealthProbe]:
    return _health
