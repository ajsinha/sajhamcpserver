"""
SAJHA MCP Server — in-process alert rules (``observability.alerts``).

Each rule names a metric, a comparison, a threshold, a window and a channel (log,
webhook, email, or notice: a system notice in the console while the rule holds). The
instrumentation points feed a bounded in-memory window of recent events; a daemon thread
evaluates every rule each ``observability.alerts_interval_seconds`` and sends one message
when a rule's condition holds and its cooldown has passed.
Webhooks go only to ``observability.alerts_webhook.allowed_urls`` and through the same
SSRF guard as async webhooks and OAuth CIMD fetches (``address_allowed``): resolved once,
connected by pinned IP, no redirects, no proxy. Design: docs/architecture/Observability.md,
section 5.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import operator
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from sajha.observability import settings as S

logger = logging.getLogger('sajha.observability.alerts')

METRICS = ('http_error_rate', 'http_latency_p95_ms', 'tool_error_rate', 'tool_latency_p95_ms', 'tool_calls',
           'llm_cost_usd', 'llm_tokens', 'llm_error_rate', 'auth_failures', 'breaker_open',
           'federation_upstreams_down')
OPS: Dict[str, Callable[[float, float], bool]] = {
    '>': operator.gt, '>=': operator.ge, '<': operator.lt, '<=': operator.le,
    'gt': operator.gt, 'gte': operator.ge, 'lt': operator.lt, 'lte': operator.le}
CHANNELS = ('log', 'webhook', 'email', 'notice')   # notice: a system notice (sajha/notices)


def parse_duration(v: Any, default: float) -> float:
    if v is None or v == '':
        return default
    if isinstance(v, (int, float)):
        return float(v)
    m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*', str(v))
    if not m:
        raise ValueError(f'bad duration {v!r} (use e.g. 30s, 5m, 1h)')
    return float(m.group(1)) * {'': 1, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}[m.group(2)]


@dataclass
class Rule:
    name: str
    metric: str
    op: str
    threshold: float
    window_s: float = 300.0
    cooldown_s: float = 900.0
    min_events: int = 0
    tool: str = ''
    channel: Dict[str, Any] = field(default_factory=lambda: {'type': 'log'})
    error: str = ''
    last_value: Optional[float] = None
    last_eval: Optional[float] = None
    last_fired: Optional[float] = None
    firing: bool = False

    def to_dict(self) -> Dict[str, Any]:
        ch = dict(self.channel)
        ch.pop('password', None)
        return {'name': self.name, 'metric': self.metric, 'op': self.op, 'threshold': self.threshold,
                'window_seconds': self.window_s, 'cooldown_seconds': self.cooldown_s,
                'min_events': self.min_events, 'tool': self.tool or None, 'channel': ch,
                'error': self.error or None, 'value': self.last_value, 'firing': self.firing,
                'last_eval': self.last_eval, 'last_fired': self.last_fired}


def parse_rule(raw: Dict[str, Any], index: int = 0) -> Rule:
    name = str(raw.get('name') or f'rule-{index + 1}')
    metric = str(raw.get('metric') or '')
    op = str(raw.get('op') or raw.get('operator') or '>')
    channel = raw.get('channel') or {'type': 'log'}
    if isinstance(channel, str):
        channel = {'type': channel}
    rule = Rule(name=name, metric=metric, op=op, threshold=0.0, channel=dict(channel))
    try:
        rule.threshold = float(raw.get('threshold'))
        rule.window_s = parse_duration(raw.get('window'), 300.0)
        rule.cooldown_s = parse_duration(raw.get('cooldown'), 900.0)
        rule.min_events = int(raw.get('min_events') or 0)
        rule.tool = str(raw.get('tool') or '')
        if metric not in METRICS:
            raise ValueError(f'unknown metric {metric!r} (one of {", ".join(METRICS)})')
        if op not in OPS:
            raise ValueError(f'unknown op {op!r} (> >= < <=)')
        ctype = str(rule.channel.get('type') or 'log')
        if ctype not in CHANNELS:
            raise ValueError(f'unknown channel {ctype!r} (log, webhook, email, notice)')
        if ctype == 'webhook':
            check_webhook_url(str(rule.channel.get('url') or ''))
        if ctype == 'email' and not rule.channel.get('to'):
            raise ValueError('an email channel needs "to"')
        if ctype == 'notice':
            from sajha.notices import SEVERITIES, AUDIENCES
            if str(rule.channel.get('severity') or 'warning') not in SEVERITIES:
                raise ValueError(f'a notice channel\'s severity must be one of {", ".join(SEVERITIES)}')
            if str(rule.channel.get('audience') or 'admin') not in AUDIENCES:
                raise ValueError('a notice channel\'s audience must be admin or everyone')
    except (TypeError, ValueError) as e:
        rule.error = str(e) if str(e) else 'threshold must be a number'
    return rule


# ── the event window ────────────────────────────────────────────────

class EventWindow:
    def __init__(self, maxlen: int = 200000):
        self._events: Deque[Tuple[float, str, Dict[str, Any]]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, kind: str, event: Dict[str, Any], at: Optional[float] = None) -> None:
        with self._lock:
            self._events.append((at if at is not None else time.time(), kind, event))

    def since(self, kind: str, start: float) -> List[Dict[str, Any]]:
        with self._lock:
            return [e for t, k, e in self._events if k == kind and t >= start]

    def prune(self, before: float) -> None:
        with self._lock:
            while self._events and self._events[0][0] < before:
                self._events.popleft()

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def _p95(values: List[float]) -> float:
    from sajha.observability.usage import percentile
    return percentile(values, 95)


class AlertManager:
    def __init__(self, rules: Optional[List[Rule]] = None, window: Optional[EventWindow] = None):
        self.rules: List[Rule] = rules or []
        self.window = window or EventWindow(max(1000, S.get_int('observability.alerts_max_events', 200000)))
        self.sent: List[Dict[str, Any]] = []        # the last messages (status page, tests)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- values --
    def value(self, rule: Rule, now: float) -> Tuple[Optional[float], int]:
        """(value, events considered) for a rule; None when there is nothing to judge."""
        start = now - rule.window_s
        m = rule.metric
        if m.startswith('http_'):
            ev = self.window.since('http', start)
            if not ev:
                return None, 0
            if m == 'http_error_rate':
                return sum(1 for e in ev if e['status'] >= 500) / len(ev), len(ev)
            return _p95([e['ms'] for e in ev]), len(ev)
        if m.startswith('tool_'):
            ev = [e for e in self.window.since('tool', start)
                  if e['outcome'] != 'input_required' and (not rule.tool or e['tool'] == rule.tool)]
            if m == 'tool_calls':
                return float(len(ev)), len(ev)
            if not ev:
                return None, 0
            if m == 'tool_error_rate':
                return sum(1 for e in ev if e['outcome'] in ('error', 'circuit_open')) / len(ev), len(ev)
            lat = [e['ms'] for e in ev if e['outcome'] in ('ok', 'error', 'cache_hit')]
            return (_p95(lat) if lat else None), len(lat)
        if m.startswith('llm_'):
            ev = self.window.since('llm', start)
            if m == 'llm_cost_usd':
                return float(sum(e['cost'] for e in ev)), len(ev)
            if m == 'llm_tokens':
                return float(sum(e['tokens'] for e in ev)), len(ev)
            if not ev:
                return None, 0
            return sum(1 for e in ev if e['outcome'] not in ('ok', 'cache_hit')) / len(ev), len(ev)
        if m == 'auth_failures':
            ev = self.window.since('auth', start)
            return float(len(ev)), len(ev)
        if m == 'breaker_open':
            try:
                from sajha.core.circuit_breaker import get_circuit_registry
                n = sum(1 for b in get_circuit_registry().all_status() if b.get('state') == 'open')
            except Exception:
                n = 0
            return float(n), 1
        if m == 'federation_upstreams_down':
            try:
                from sajha.federation.manager import get_federation
                fed = get_federation()
                st = fed.status() if fed is not None else []
            except Exception:
                st = []
            return float(sum(1 for s in st if s.get('enabled') and s.get('state') not in ('connected', 'disabled'))), 1
        return None, 0

    def evaluate(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Evaluate every rule once; returns the messages sent."""
        now = now if now is not None else time.time()
        out = []
        longest = max([r.window_s for r in self.rules] or [0])
        for rule in self.rules:
            if rule.error:
                continue
            value, n = self.value(rule, now)
            rule.last_eval, rule.last_value = now, value
            if value is None or n < rule.min_events:
                rule.firing = False
                self._notice(rule, False)
                continue
            holds = OPS[rule.op](value, rule.threshold)
            rule.firing = holds
            self._notice(rule, holds)
            if not holds or (rule.last_fired is not None and now - rule.last_fired < rule.cooldown_s):
                continue
            rule.last_fired = now
            msg = {'rule': rule.name, 'metric': rule.metric, 'value': round(value, 6), 'op': rule.op,
                   'threshold': rule.threshold, 'window_seconds': rule.window_s, 'events': n,
                   'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now)), 'source': 'sajha'}
            self._send(rule, msg)
            out.append(msg)
        if longest:
            self.window.prune(now - longest)
        return out

    @staticmethod
    def _notice(rule: Rule, holds: bool) -> None:
        """The notice channel: a system notice while the rule holds, cleared when it stops."""
        if (rule.channel.get('type') or 'log') == 'notice':
            from sajha.notices.sources import alert_rule
            alert_rule(rule, holds)

    def _send(self, rule: Rule, msg: Dict[str, Any]) -> None:
        from sajha.observability.metrics import record_alert
        record_alert(rule.name)
        self.sent = (self.sent + [msg])[-50:]
        ctype = rule.channel.get('type') or 'log'
        text = (f'ALERT {rule.name}: {rule.metric} = {msg["value"]} {rule.op} {rule.threshold} '
                f'over {int(rule.window_s)}s')
        logger.warning(text)
        try:
            if ctype == 'webhook':
                threading.Thread(target=send_webhook, args=(str(rule.channel.get('url')), msg),
                                 name='sajha-alert-webhook', daemon=True).start()
            elif ctype == 'email':
                threading.Thread(target=send_email, args=(rule.channel, text, msg),
                                 name='sajha-alert-email', daemon=True).start()
        except Exception as e:
            logger.error(f'alert {rule.name}: delivery failed to start: {e}')

    # -- lifecycle --
    def start(self) -> bool:
        if self._thread is not None or not self.rules:
            return False
        interval = max(1.0, S.get_float('observability.alerts_interval_seconds', 30.0))

        def loop():
            while not self._stop.wait(interval):
                try:
                    self.evaluate()
                except Exception as e:
                    logger.debug(f'alert evaluation failed: {e}')

        self._thread = threading.Thread(target=loop, name='sajha-alerts', daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    def observe(self, kind: str, event: Dict[str, Any]) -> None:
        if self.rules:
            self.window.add(kind, event)


# ── channels ────────────────────────────────────────────────────────

class AlertDeliveryError(ValueError):
    pass


def check_webhook_url(url: str):
    """Syntax and allowlist (observability.alerts_webhook.allowed_urls); returns the split URL."""
    from urllib.parse import urlsplit
    from sajha.core.async_executor import url_matches_prefix
    try:
        p = urlsplit(url or '')
        p.port
    except ValueError:
        raise AlertDeliveryError('webhook url is not a valid URL')
    if p.scheme not in ('http', 'https') or not p.hostname:
        raise AlertDeliveryError('webhook url must be an http(s) URL')
    if p.username or p.password or '@' in p.netloc:
        raise AlertDeliveryError('webhook url must not contain credentials')
    allowed = S.get_list('observability.alerts_webhook.allowed_urls')
    if not any(url_matches_prefix(url, prefix) for prefix in allowed):
        raise AlertDeliveryError('webhook url is not in observability.alerts_webhook.allowed_urls')
    return p


def _resolve_pinned(host: str, port: int) -> str:
    import ipaddress
    import socket
    from sajha.auth.oauth.clients import address_allowed
    allow_private = S.get_bool('observability.alerts_webhook.allow_private_networks', False)
    try:
        addrs = [str(ipaddress.ip_address(host.strip('[]')))]
    except ValueError:
        try:
            addrs = [r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
        except OSError as e:
            raise AlertDeliveryError(f'webhook host does not resolve: {e}')
    if not addrs:
        raise AlertDeliveryError('webhook host does not resolve')
    for a in addrs:
        if not address_allowed(ipaddress.ip_address(a.split('%')[0]), host.lower(),
                               allow_localhost=allow_private, allow_private=allow_private):
            raise AlertDeliveryError('webhook host resolves to a non-public address '
                                     '(observability.alerts_webhook.allow_private_networks)')
    return addrs[0]


def send_webhook(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> bool:
    import httpx
    from sajha.observability.tracing import inject as tracing_inject
    from urllib.parse import urlunsplit
    try:
        p = check_webhook_url(url)
        port = p.port or {'http': 80, 'https': 443}[p.scheme]
        ip = _resolve_pinned(p.hostname, port)
    except AlertDeliveryError as e:
        logger.error(f'alert webhook refused: {e}')
        return False
    ip_host = f'[{ip}]' if ':' in ip else ip
    pinned = urlunsplit((p.scheme, f'{ip_host}:{port}', p.path or '/', p.query, ''))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            r = client.post(pinned, content=json.dumps(payload, default=str).encode(),
                            headers=tracing_inject({'Content-Type': 'application/json', 'User-Agent': 'sajha-alerts',
                                                    'Host': p.netloc}), extensions={'sni_hostname': p.hostname})
        if 200 <= r.status_code < 300:
            return True
        logger.warning(f'alert webhook {p.hostname} answered HTTP {r.status_code}')
    except Exception as e:
        logger.warning(f'alert webhook {p.hostname} failed: {type(e).__name__}: {e}')
    return False


def send_email(channel: Dict[str, Any], subject: str, payload: Dict[str, Any]) -> bool:
    import smtplib
    from email.message import EmailMessage
    host = S.get_str('observability.alerts_email.smtp_host', '')
    if not host:
        logger.error('alert email: observability.alerts_email.smtp_host is not set')
        return False
    to = channel.get('to')
    to = [to] if isinstance(to, str) else list(to or [])
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = S.get_str('observability.alerts_email.from', 'sajha@localhost')
    msg['To'] = ', '.join(to)
    msg.set_content(json.dumps(payload, indent=2, default=str))
    try:
        with smtplib.SMTP(host, S.get_int('observability.alerts_email.smtp_port', 587), timeout=15) as smtp:
            if S.get_bool('observability.alerts_email.starttls', True):
                smtp.starttls()
            user = S.get_str('observability.alerts_email.username', '')
            password = os.environ.get('SAJHA_OBSERVABILITY_ALERTS_EMAIL_PASSWORD', '')
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        logger.warning(f'alert email failed: {type(e).__name__}: {e}')
        return False


# ── singleton ───────────────────────────────────────────────────────

_manager: Optional[AlertManager] = None


def load_rules() -> List[Rule]:
    rules = [parse_rule(r, i) for i, r in enumerate(S.alert_rules_raw())]
    for r in rules:
        if r.error:
            logger.warning(f'alert rule {r.name!r} is not active: {r.error}')
    return rules


def init_alerts() -> AlertManager:
    global _manager
    if _manager is not None:
        _manager.stop()
    _manager = AlertManager(load_rules())
    from sajha.observability.metrics import add_listener
    add_listener(_observe)
    _manager.start()
    return _manager


def _observe(kind: str, event: Dict[str, Any]) -> None:
    if _manager is not None:
        _manager.observe(kind, event)


def get_alert_manager() -> Optional[AlertManager]:
    return _manager


def shutdown() -> None:
    if _manager is not None:
        _manager.stop()
