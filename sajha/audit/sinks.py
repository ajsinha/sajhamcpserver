"""
SAJHA MCP Server — SIEM export of audit records.

``audit.export.sinks`` (raw YAML list, or the JSON list in ``SAJHA_AUDIT_EXPORT_SINKS``)
configures any number of sinks:

* ``syslog``: RFC 5424 messages with RFC 6587 octet-counted framing over TCP, or TLS;
* ``http``: ``flavor`` ``splunk_hec`` | ``datadog`` | ``generic``, batched JSON, through the SSRF
  guard (allowlist ``audit.export.allowed_urls``, public addresses unless the sink sets
  ``allow_private_networks``, pinned IP, no redirects, no proxy);
* ``file``: JSON Lines with size rotation; ``{pid}`` / ``{host}`` in the path.

Each sink has a bounded queue and its own thread: records are batched (``batch_size``,
``flush_seconds``), a failed batch is retried with exponential backoff up to
``max_retries`` and then dropped and counted. A full queue drops rather than block the
caller. The database chain is the record of authority; the export is best-effort with
visible loss (``sajha_audit_export_total{sink,outcome}``). Design: docs/architecture/Policy
and Audit.md, section 8.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import ssl
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sajha.audit import formats

logger = logging.getLogger(__name__)

TYPES = ('syslog', 'http', 'file')
FLAVORS = ('splunk_hec', 'datadog', 'generic')
_EXPORTS = None


def _counter():
    global _EXPORTS
    if _EXPORTS is None:
        from sajha.observability import metrics as m
        _EXPORTS = m.REGISTRY._families.get('sajha_audit_export_total') or m.Counter(
            m.REGISTRY, 'sajha_audit_export_total', 'Audit records exported to SIEM sinks by sink and outcome.',
            ('sink', 'outcome'))
    return _EXPORTS


class SinkConfigError(ValueError):
    pass


class Sink:
    """A queue, a thread, batching and retries; subclasses implement :meth:`send`."""

    type = 'abstract'

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.name = str(cfg.get('name') or self.type)
        self.format = str(cfg.get('format') or 'json').lower()
        if self.format not in formats.FORMATS:
            raise SinkConfigError(f'sink {self.name}: format must be one of {", ".join(formats.FORMATS)}')
        self.batch_size = max(1, int(cfg.get('batch_size') or 100))
        self.flush_seconds = max(0.01, float(cfg.get('flush_seconds') or 2))
        self.max_retries = max(0, int(cfg.get('max_retries') if cfg.get('max_retries') is not None else 5))
        self.retry_base = max(0.01, float(cfg.get('retry_base_seconds') or 1.0))
        self.timeout = max(1.0, float(cfg.get('timeout_seconds') or 10))
        self._q: queue.Queue = queue.Queue(maxsize=max(10, int(cfg.get('queue_size') or 10000)))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._inflight = 0
        self._lock = threading.Lock()
        self.sent = self.failed = self.dropped = 0
        self.last_error = ''
        self.last_sent_at: Optional[float] = None

    # -- lifecycle ---------------------------------------------------

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name=f'sajha-audit-sink-{self.name}', daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self.close()

    def close(self) -> None:
        pass

    def submit(self, record: Dict[str, Any]) -> bool:
        try:
            self._q.put_nowait(record)
        except queue.Full:
            self.dropped += 1
            _counter().inc((self.name, 'dropped'))
            return False
        self.start()
        return True

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until the queue is empty and nothing is in flight; True when it is."""
        end = time.time() + timeout
        while time.time() < end:
            if self._q.empty() and self._inflight == 0:
                return True
            time.sleep(0.01)
        return False

    def status(self) -> Dict[str, Any]:
        return {'name': self.name, 'type': self.type, 'format': self.format, 'target': self.target(),
                'queued': self._q.qsize(), 'sent': self.sent, 'failed': self.failed, 'dropped': self.dropped,
                'last_error': self.last_error, 'last_sent_at': self.last_sent_at}

    def target(self) -> str:
        return ''

    # -- the worker --------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                self._inflight += 1
            batch = [first]
            deadline = time.time() + self.flush_seconds
            while len(batch) < self.batch_size:
                left = deadline - time.time()
                if left <= 0:
                    break
                try:
                    batch.append(self._q.get(timeout=min(left, 0.05)))
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    # deliver promptly when the producer has gone quiet
                    if self._q.empty() and len(batch) and left < self.flush_seconds - 0.05:
                        break
            try:
                self._deliver(batch)
            finally:
                with self._lock:
                    self._inflight -= 1

    def _deliver(self, batch: List[Dict[str, Any]]) -> None:
        attempt = 0
        while True:
            try:
                self.send(batch)
                self.sent += len(batch)
                self.last_sent_at = time.time()
                self.last_error = ''
                _counter().inc((self.name, 'sent'), len(batch))
                return
            except Exception as e:
                self.failed += 1
                self.last_error = f'{type(e).__name__}: {e}'[:300]
                _counter().inc((self.name, 'failed'))
                if attempt >= self.max_retries or self._stop.is_set():
                    self.dropped += len(batch)
                    _counter().inc((self.name, 'dropped'), len(batch))
                    logger.warning(f'Audit sink {self.name}: dropped {len(batch)} record(s) after '
                                   f'{attempt + 1} attempt(s): {self.last_error}')
                    return
                self._stop.wait(min(30.0, self.retry_base * (2 ** attempt)))
                attempt += 1

    def send(self, batch: List[Dict[str, Any]]) -> None:
        raise NotImplementedError


# ── syslog ──────────────────────────────────────────────────────────

def _sd_escape(v: Any) -> str:
    return str(v).replace('\\', '\\\\').replace('"', '\\"').replace(']', '\\]')


def _printable(s: str, n: int) -> str:
    out = ''.join(ch if 33 <= ord(ch) <= 126 else '_' for ch in (s or '-'))
    return out[:n] or '-'


def syslog_message(rec: Dict[str, Any], fmt: str = 'json', facility: int = 13, app: str = 'sajha',
                   host: Optional[str] = None) -> bytes:
    """One RFC 5424 message (without framing)."""
    pri = facility * 8 + formats.syslog_severity(rec.get('event', ''))
    sd = (f'[sajha@32473 chain="{_sd_escape(rec.get("chain", ""))}" seq="{_sd_escape(rec.get("seq", ""))}" '
          f'hash="{_sd_escape(rec.get("hash", ""))}"]')
    head = (f'<{pri}>1 {rec.get("ts") or "-"} {_printable(host or socket.gethostname(), 255)} '
            f'{_printable(app, 48)} {os.getpid()} {_printable(rec.get("event", ""), 32)} {sd} ')
    return head.encode('utf-8') + b'\xef\xbb\xbf' + formats.render(rec, fmt).encode('utf-8')


def frame(msg: bytes) -> bytes:
    """RFC 6587 octet counting."""
    return str(len(msg)).encode('ascii') + b' ' + msg


class SyslogSink(Sink):
    type = 'syslog'

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.host = str(cfg.get('host') or '')
        if not self.host:
            raise SinkConfigError(f'sink {self.name}: syslog needs host')
        self.tls = bool(cfg.get('tls', False))
        self.port = int(cfg.get('port') or (6514 if self.tls else 601))
        self.facility = int(cfg.get('facility') if cfg.get('facility') is not None else 13)
        if not 0 <= self.facility <= 23:
            raise SinkConfigError(f'sink {self.name}: facility is 0..23')
        self.app = str(cfg.get('app_name') or 'sajha')
        self.ca_file = cfg.get('ca_file') or None
        self.verify = cfg.get('verify', True) is not False
        self.cert_file = cfg.get('cert_file') or None
        self.key_file = cfg.get('key_file') or None
        self._sock: Optional[socket.socket] = None

    def target(self) -> str:
        return f'{"tls" if self.tls else "tcp"}://{self.host}:{self.port}'

    def _connect(self) -> socket.socket:
        s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.tls:
            ctx = ssl.create_default_context(cafile=self.ca_file)
            if not self.verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            if self.cert_file:
                ctx.load_cert_chain(self.cert_file, self.key_file)
            s = ctx.wrap_socket(s, server_hostname=self.host)
        return s

    def send(self, batch: List[Dict[str, Any]]) -> None:
        data = b''.join(frame(syslog_message(r, self.format, self.facility, self.app)) for r in batch)
        if self._sock is None:
            self._sock = self._connect()
        try:
            self._sock.sendall(data)
        except OSError:
            self.close()
            raise

    def close(self) -> None:
        if self._sock is not None:
            try:
                if isinstance(self._sock, ssl.SSLSocket):
                    self._sock = self._sock.unwrap()      # TLS close_notify, so the receiver sees a clean end
            except (OSError, ValueError):
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


# ── HTTP ────────────────────────────────────────────────────────────

class HttpSink(Sink):
    type = 'http'

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.url = str(cfg.get('url') or '')
        self.flavor = str(cfg.get('flavor') or 'generic').lower()
        if self.flavor not in FLAVORS:
            raise SinkConfigError(f'sink {self.name}: flavor must be one of {", ".join(FLAVORS)}')
        from urllib.parse import urlsplit
        p = urlsplit(self.url)
        if p.scheme not in ('http', 'https') or not p.hostname:
            raise SinkConfigError(f'sink {self.name}: url must be an http(s) URL')
        if p.username or p.password or '@' in p.netloc:
            raise SinkConfigError(f'sink {self.name}: url must not contain credentials; use token')
        self.allow_private = bool(cfg.get('allow_private_networks', False))
        self.token_ref = cfg.get('token')
        self.index = cfg.get('index')
        self.sourcetype = str(cfg.get('sourcetype') or 'sajha:audit')
        self.tags = str(cfg.get('tags') or '')
        self.host = socket.gethostname()

    def target(self) -> str:
        return f'{self.flavor} {self.url}'

    def _token(self) -> str:
        if not self.token_ref:
            return ''
        from sajha.federation.security import secrets
        return secrets().resolve(str(self.token_ref)) or ''

    def body(self, batch: List[Dict[str, Any]]) -> bytes:
        if self.flavor == 'splunk_hec':
            from sajha.audit.chain import parse_ts
            lines = []
            for r in batch:
                ev = {'time': round(parse_ts(r['ts']).timestamp(), 6) if r.get('ts') else time.time(),
                      'host': self.host, 'source': 'sajha', 'sourcetype': self.sourcetype,
                      'event': formats.as_object(r, self.format)}
                if self.index:
                    ev['index'] = self.index
                lines.append(json.dumps(ev, separators=(',', ':'), default=str))
            return '\n'.join(lines).encode('utf-8')
        if self.flavor == 'datadog':
            items = [{'ddsource': 'sajha', 'service': 'sajha', 'hostname': self.host, 'ddtags': self.tags,
                      'message': r.get('event', ''), 'sajha': formats.as_object(r, self.format)} for r in batch]
            return json.dumps(items, separators=(',', ':'), default=str).encode('utf-8')
        return json.dumps([formats.as_object(r, self.format) for r in batch], separators=(',', ':'),
                          default=str).encode('utf-8')

    def headers(self) -> Dict[str, str]:
        h = {'Content-Type': 'application/json', 'User-Agent': 'sajha-audit'}
        tok = self._token()
        if tok:
            if self.flavor == 'splunk_hec':
                h['Authorization'] = f'Splunk {tok}'
            elif self.flavor == 'datadog':
                h['DD-API-KEY'] = tok
            else:
                h['Authorization'] = f'Bearer {tok}'
        return h

    def send(self, batch: List[Dict[str, Any]]) -> None:
        post_pinned(self.url, self.body(batch), self.headers(), allow_private=self.allow_private,
                    timeout=self.timeout)


class ExportRefused(ValueError):
    pass


def check_destination(url: str, allow_private: bool):
    """Allowlist and address guard for an HTTP sink; returns (split url, pinned ip, port)."""
    import ipaddress
    from urllib.parse import urlsplit
    from sajha.auth.oauth.clients import address_allowed
    from sajha.core.async_executor import url_matches_prefix
    from sajha.core.config import _list
    p = urlsplit(url)
    allowed = _list('audit.export.allowed_urls', [])
    if allowed and not any(url_matches_prefix(url, a) for a in allowed):
        raise ExportRefused('url is not in audit.export.allowed_urls')
    port = p.port or {'http': 80, 'https': 443}[p.scheme]
    host = p.hostname
    try:
        addrs = [str(ipaddress.ip_address(host.strip('[]')))]
    except ValueError:
        try:
            addrs = [r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
        except OSError as e:
            raise ExportRefused(f'host does not resolve: {e}')
    if not addrs:
        raise ExportRefused('host does not resolve')
    for a in addrs:
        if not address_allowed(ipaddress.ip_address(a.split('%')[0]), host.lower(),
                               allow_localhost=allow_private, allow_private=allow_private):
            raise ExportRefused('host resolves to a non-public address (set allow_private_networks on the sink)')
    return p, addrs[0], port


def post_pinned(url: str, body: bytes, headers: Dict[str, str], allow_private: bool = False,
                timeout: float = 10.0) -> int:
    import httpx
    from urllib.parse import urlunsplit
    p, ip, port = check_destination(url, allow_private)
    ip_host = f'[{ip}]' if ':' in ip else ip
    pinned = urlunsplit((p.scheme, f'{ip_host}:{port}', p.path or '/', p.query, ''))
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        r = client.post(pinned, content=body, headers={**headers, 'Host': p.netloc},
                        extensions={'sni_hostname': p.hostname})
    if not 200 <= r.status_code < 300:
        raise RuntimeError(f'HTTP {r.status_code}')
    return r.status_code


# ── file ────────────────────────────────────────────────────────────

class FileSink(Sink):
    type = 'file'

    def __init__(self, cfg: Dict[str, Any]):
        cfg = dict(cfg)
        cfg.setdefault('flush_seconds', 0.2)
        super().__init__(cfg)
        raw = str(cfg.get('path') or 'logs/audit/audit-{host}-{pid}.jsonl')
        self.path = Path(raw.replace('{pid}', str(os.getpid())).replace('{host}', socket.gethostname().split('.')[0]))
        self.max_bytes = max(1024, int(cfg.get('max_bytes') or 10 * 1024 * 1024))
        self.backups = max(0, int(cfg.get('backups') if cfg.get('backups') is not None else 10))

    def target(self) -> str:
        return str(self.path)

    def _rotate(self) -> None:
        if self.backups == 0:
            self.path.unlink(missing_ok=True)
            return
        for i in range(self.backups - 1, 0, -1):
            src = self.path.with_name(f'{self.path.name}.{i}')
            if src.exists():
                os.replace(src, self.path.with_name(f'{self.path.name}.{i + 1}'))
        os.replace(self.path, self.path.with_name(f'{self.path.name}.1'))

    def send(self, batch: List[Dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for r in batch:
            line = (formats.render(r, self.format) + '\n').encode('utf-8')
            if self.path.exists() and self.path.stat().st_size + len(line) > self.max_bytes:
                self._rotate()
            with open(self.path, 'ab') as f:
                f.write(line)


# ── the manager ─────────────────────────────────────────────────────

def build_sink(cfg: Dict[str, Any]) -> Sink:
    if not isinstance(cfg, dict):
        raise SinkConfigError('a sink is a mapping with a type')
    t = str(cfg.get('type') or '').lower()
    if t == 'syslog':
        return SyslogSink(cfg)
    if t == 'http':
        return HttpSink(cfg)
    if t == 'file':
        return FileSink(cfg)
    raise SinkConfigError(f'sink {cfg.get("name") or "?"}: type must be one of {", ".join(TYPES)}')


def configured_sinks_raw() -> List[Dict[str, Any]]:
    env = os.environ.get('SAJHA_AUDIT_EXPORT_SINKS')
    if env:
        try:
            v = json.loads(env)
        except ValueError as e:
            logger.warning(f'SAJHA_AUDIT_EXPORT_SINKS is not a JSON list: {e}')
            return []
        return [s for s in v if isinstance(s, dict)] if isinstance(v, list) else []
    path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return []
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    except Exception as e:
        logger.warning(f'audit export: cannot read {path}: {e}')
        return []
    sinks = (((data.get('audit') or {}).get('export') or {}).get('sinks')) or []
    from sajha.core.config import _substitute_vars
    out = []
    for s in sinks if isinstance(sinks, list) else []:
        if isinstance(s, dict):
            out.append({k: _substitute_vars(v) if isinstance(v, str) else v for k, v in s.items()})
    return out


class ExportManager:
    def __init__(self, sinks: Optional[List[Sink]] = None):
        self.sinks: List[Sink] = list(sinks or [])
        self.errors: List[str] = []

    @classmethod
    def from_config(cls) -> 'ExportManager':
        m = cls()
        for raw in configured_sinks_raw():
            if raw.get('enabled', True) is False:
                continue
            try:
                m.sinks.append(build_sink(raw))
            except (SinkConfigError, ValueError, TypeError) as e:
                m.errors.append(str(e))
                logger.error(f'Audit export: {e}')
        if m.sinks:
            logger.info(f'Audit export: {len(m.sinks)} sink(s): '
                        + ', '.join(f'{s.name} ({s.type}, {s.format})' for s in m.sinks))
        return m

    def dispatch(self, record: Dict[str, Any]) -> None:
        for s in self.sinks:
            s.submit(record)

    def flush(self, timeout: float = 10.0) -> bool:
        return all(s.flush(timeout) for s in self.sinks)

    def stop(self, timeout: float = 5.0) -> None:
        for s in self.sinks:
            try:
                s.stop(timeout)
            except Exception as e:
                logger.debug(f'audit sink {s.name} stop: {e}')

    def status(self) -> Dict[str, Any]:
        return {'sinks': [s.status() for s in self.sinks], 'errors': list(self.errors)}
