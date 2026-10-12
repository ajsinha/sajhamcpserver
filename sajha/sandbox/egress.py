"""
SAJHA sandbox — the egress proxy: a sandbox's network allowlist enforced on the wire.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A sandboxed run whose policy says ``network: allowlist`` gets no direct network at all
(its own network namespace, or a container with ``--network none``, holding only a
loopback interface). The one way out is this proxy: the server starts one per run,
listening on a Unix socket in a per-run directory; the runner, inside the sandbox,
relays ``127.0.0.1:PROXY_PORT`` to that socket and sets ``HTTP_PROXY``/``HTTPS_PROXY``.

The proxy speaks HTTP/1.1:

* ``CONNECT host:port`` (HTTPS and any other TCP protocol a client tunnels), answered
  ``200`` and then relayed byte for byte;
* a request with an absolute ``http://`` URI (plain HTTP forward proxying), forwarded
  in origin form with ``Connection: close`` (one request per connection).

Each connection is decided by :func:`decide`: the ``host:port`` must be in the run's
``allow_hosts`` (exact name, case-insensitive; the port defaults to 443 as in the
policy), and every address the host resolves to must pass the outbound guard's
blocked-address rule (``sajha.core.outbound.blocked_reason``: cloud metadata and
link-local, loopback, multicast and reserved always; private ranges unless
``sandbox.egress.block_private_networks`` is false). ``sandbox.egress.exempt_hosts``
(host patterns and CIDRs) skips the address rule, never the allowlist. The proxy
resolves the name itself and connects to an address it checked (no rebinding).

Every allowed and denied connection is written to the tamper-evident audit as a
``sandbox.egress`` record and counted in ``sajha_sandbox_egress_total``.

Settings (``sandbox.egress.*``, read live through ``sajha.core.config._get``):

    mode: proxy                    # proxy | direct (the old library-level host check)
    block_private_networks: true
    exempt_hosts: []
    connect_timeout_seconds: 10
    idle_timeout_seconds: 120
    max_connections: 32            # concurrent connections per run
"""

from __future__ import annotations

import atexit
import fnmatch
import ipaddress
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: The port the runner's bridge listens on inside the sandbox (its own loopback).
PROXY_PORT = 3128
#: Where the per-run socket directory appears inside bwrap, nsjail and docker sandboxes.
INNER_SOCKET_DIR = '/run/sajha-egress'
SOCKET_NAME = 'egress.sock'
MAX_HEAD = 16384

EGRESS_DEFAULTS = {
    'mode': 'proxy',
    'block_private_networks': True,
    'exempt_hosts': [],
    'connect_timeout_seconds': 10,
    'idle_timeout_seconds': 120,
    'max_connections': 32,
}


# ── settings ─────────────────────────────────────────────────────────

@dataclass
class EgressSettings:
    mode: str = 'proxy'
    block_private_networks: bool = True
    exempt_patterns: List[str] = field(default_factory=list)
    exempt_networks: List = field(default_factory=list)
    connect_timeout: float = 10.0
    idle_timeout: float = 120.0
    max_connections: int = 32


def load_egress_settings() -> EgressSettings:
    from .settings import _as_bool, _as_int, _raw
    d = EGRESS_DEFAULTS
    patterns, networks = [], []
    try:
        from sajha.core.outbound import _patterns_and_networks
        patterns, networks = _patterns_and_networks('sandbox.egress.exempt_hosts')
    except Exception as e:                                  # pragma: no cover - config unavailable
        logger.debug(f'sandbox.egress.exempt_hosts unreadable: {e}')
    mode = str(_raw('egress.mode', d['mode']) or 'proxy').strip().lower()
    return EgressSettings(
        mode=mode if mode in ('proxy', 'direct') else 'proxy',
        block_private_networks=_as_bool(_raw('egress.block_private_networks', True), True),
        exempt_patterns=patterns, exempt_networks=networks,
        connect_timeout=float(max(1, _as_int(_raw('egress.connect_timeout_seconds', 10), 10))),
        idle_timeout=float(max(1, _as_int(_raw('egress.idle_timeout_seconds', 120), 120))),
        max_connections=max(1, _as_int(_raw('egress.max_connections', 32), 32)),
    )


def proxy_env(port: int = PROXY_PORT) -> Dict[str, str]:
    """The environment that points HTTP clients in the sandbox at the bridge."""
    url = f'http://127.0.0.1:{port}'
    return {'HTTP_PROXY': url, 'HTTPS_PROXY': url, 'http_proxy': url, 'https_proxy': url,
            'ALL_PROXY': url, 'all_proxy': url, 'NO_PROXY': '', 'no_proxy': ''}


# ── the decision ─────────────────────────────────────────────────────

@dataclass
class Decision:
    allowed: bool
    host: str
    port: int
    addresses: List[str] = field(default_factory=list)
    reason: str = ''


def parse_allow_hosts(entries: Sequence[str]) -> List[Tuple[str, int]]:
    """``["api.x.com", "b.y:8443", "[2001:db8::1]:443"]`` as (host, port) pairs; port 443 by default."""
    out = []
    for raw in entries or []:
        e = str(raw).strip().lower()
        if not e:
            continue
        if e.startswith('['):
            host, _, rest = e[1:].partition(']')
            port = rest.lstrip(':') or '443'
        elif e.count(':') == 1:
            host, port = e.split(':')
        elif ':' in e:                                      # bare IPv6 literal
            host, port = e, '443'
        else:
            host, port = e, '443'
        try:
            out.append((host.rstrip('.'), int(port)))
        except ValueError:
            out.append((host.rstrip('.'), 443))
    return out


def _default_resolver(host: str, port: int) -> List[str]:
    from sajha.core.outbound import resolve
    return resolve(host, port)


def decide(host: str, port: int, allow: Sequence[Tuple[str, int]], settings: EgressSettings,
           resolver: Optional[Callable[[str, int], List[str]]] = None) -> Decision:
    """Whether a sandbox may open ``host:port``, and the addresses it may connect to."""
    from sajha.core.outbound import METADATA_HOSTS, blocked_reason, literal_address
    host = (host or '').strip().strip('[]').lower().rstrip('.')
    if not host or not (0 < int(port) < 65536):
        return Decision(False, host, port, reason='bad destination')
    if (host, int(port)) not in set(allow):
        return Decision(False, host, port, reason='not in sandbox.allow_hosts')
    exempt = any(fnmatch.fnmatchcase(host, p) for p in settings.exempt_patterns)
    if not exempt:
        if host in METADATA_HOSTS:
            return Decision(False, host, port, reason='blocked address (cloud metadata)')
        if host == 'localhost' or host.endswith('.localhost'):
            return Decision(False, host, port, reason='blocked address (loopback)')
    lit = literal_address(host)
    try:
        addrs = [str(lit)] if lit is not None else list((resolver or _default_resolver)(host, int(port)))
    except Exception as e:
        return Decision(False, host, port, reason=f'does not resolve ({e.__class__.__name__})')
    if not addrs:
        return Decision(False, host, port, reason='does not resolve')
    if not exempt:
        for a in addrs:
            ip = ipaddress.ip_address(a.split('%')[0])
            if any(ip.version == n.version and ip in n for n in settings.exempt_networks):
                continue
            why = blocked_reason(ip, settings.block_private_networks)
            if why:
                return Decision(False, host, port, addrs, reason=f'blocked address ({why})')
    return Decision(True, host, port, addrs, reason='allowed')


# ── audit and metrics ────────────────────────────────────────────────

def _audit(run_id: str, tool: str, method: str, d: Decision) -> None:
    outcome = 'allowed' if d.allowed else 'denied'
    msg = f'sandbox egress {outcome}: {d.host}:{d.port} ({d.reason}) run={run_id} tool={tool or "-"}'
    (logger.info if d.allowed else logger.warning)(msg)
    try:
        from sajha import audit
        audit.record('sandbox.egress', actor={'user': 'sandbox'},
                     resource={'type': 'sandbox_run', 'id': run_id}, outcome=outcome,
                     details={'tool': tool, 'method': method, 'host': d.host, 'port': d.port,
                              'addresses': d.addresses[:8], 'reason': d.reason}, defer=True)
    except Exception as e:                                  # audit never breaks the run
        logger.debug(f'sandbox egress audit failed: {e}')
    try:
        from sajha.observability.metrics import record_sandbox_egress
        record_sandbox_egress(outcome)
    except Exception:
        pass


# ── the proxy ────────────────────────────────────────────────────────

class _ProxyError(Exception):
    def __init__(self, status: int, reason: str, message: str):
        super().__init__(message)
        self.status, self.reason, self.message = status, reason, message


def _read_head(conn: socket.socket) -> Tuple[bytes, bytes]:
    buf = b''
    while b'\r\n\r\n' not in buf:
        if len(buf) > MAX_HEAD:
            raise _ProxyError(431, 'Request Header Fields Too Large', 'request head too large')
        chunk = conn.recv(4096)
        if not chunk:
            raise _ProxyError(400, 'Bad Request', 'connection closed before the request head')
        buf += chunk
    head, _, rest = buf.partition(b'\r\n\r\n')
    return head, rest


def _split_hostport(text: str, default_port: int) -> Tuple[str, int]:
    text = text.strip()
    if text.startswith('['):
        host, _, rest = text[1:].partition(']')
        port = rest.lstrip(':')
    elif text.count(':') == 1:
        host, port = text.split(':')
    else:
        host, port = text, ''
    try:
        return host, int(port) if port else default_port
    except ValueError:
        raise _ProxyError(400, 'Bad Request', f'bad port in {text!r}')


def _pump(src: socket.socket, dst: socket.socket, counter: List[int], idle: float) -> None:
    src.settimeout(idle)
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
            counter[0] += len(data)
    except (OSError, ValueError):
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


class EgressProxy:
    """One run's proxy. ``start_unix(path)`` (the sandboxes) or ``start_tcp()`` (tests, tools)."""

    def __init__(self, allow_hosts: Sequence[str], run_id: str = '', tool: str = '',
                 settings: Optional[EgressSettings] = None,
                 resolver: Optional[Callable[[str, int], List[str]]] = None):
        self.allow = parse_allow_hosts(allow_hosts)
        self.run_id = run_id or 'sandbox'
        self.tool = tool
        self.settings = settings or load_egress_settings()
        self.resolver = resolver
        self._srv: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(self.settings.max_connections)
        self._conns: set = set()
        self._lock = threading.Lock()
        self.path: Optional[str] = None
        #: stop_for_run removes the socket's directory only when start_for_run created it
        self.owns_dir = False
        self.address: Optional[Tuple[str, int]] = None
        self.stats = {'allowed': 0, 'denied': 0, 'bytes_up': 0, 'bytes_down': 0}

    # -- lifecycle ---------------------------------------------------------
    def start_unix(self, path: str) -> str:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        self.path = path
        self._serve(srv)
        return path

    def start_tcp(self, host: str = '127.0.0.1', port: int = 0) -> Tuple[str, int]:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        self.address = srv.getsockname()[:2]
        self._serve(srv)
        return self.address

    def _serve(self, srv: socket.socket) -> None:
        srv.listen(64)
        srv.settimeout(0.5)
        self._srv = srv
        self._thread = threading.Thread(target=self._accept_loop, name=f'egress-{self.run_id}', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
        with self._lock:
            conns = list(self._conns)
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                c.close()
            except OSError:
                pass
        if self.path:
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()

    # -- serving -----------------------------------------------------------
    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._slots.acquire(blocking=False):
                threading.Thread(target=self._reject_busy, args=(conn,), daemon=True).start()
                continue
            threading.Thread(target=self._handle_guarded, args=(conn,), daemon=True).start()

    def _reject_busy(self, conn: socket.socket) -> None:
        """More concurrent connections than ``sandbox.egress.max_connections``: 503, then close
        gently (drain what the client sent, so it reads the answer instead of a reset)."""
        try:
            conn.settimeout(2)
            conn.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n'
                         b'Connection: close\r\n\r\n')
            conn.shutdown(socket.SHUT_WR)
            while conn.recv(4096):
                pass
        except OSError:
            pass
        finally:
            conn.close()

    def _track(self, *socks: socket.socket) -> None:
        with self._lock:
            self._conns.update(socks)

    def _untrack(self, *socks: socket.socket) -> None:
        with self._lock:
            for s in socks:
                self._conns.discard(s)

    def _handle_guarded(self, conn: socket.socket) -> None:
        self._track(conn)
        try:
            self._handle(conn)
        except Exception as e:                              # a bad client must not kill the proxy
            logger.debug(f'egress proxy connection failed: {e}')
        finally:
            self._untrack(conn)
            try:
                conn.close()
            except OSError:
                pass
            self._slots.release()

    @staticmethod
    def _reply(conn: socket.socket, status: int, reason: str, message: str = '') -> None:
        body = (message + '\n').encode('utf-8') if message else b''
        head = (f'HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\n'
                f'Content-Length: {len(body)}\r\nConnection: close\r\nX-Sajha-Egress: denied\r\n\r\n')
        try:
            conn.sendall(head.encode('ascii') + body)
        except OSError:
            pass

    def _decide(self, method: str, host: str, port: int) -> Decision:
        d = decide(host, port, self.allow, self.settings, self.resolver)
        self.stats['allowed' if d.allowed else 'denied'] += 1
        _audit(self.run_id, self.tool, method, d)
        return d

    def _connect(self, d: Decision) -> socket.socket:
        last: Optional[Exception] = None
        for a in d.addresses:
            try:
                return socket.create_connection((a, d.port), timeout=self.settings.connect_timeout)
            except OSError as e:
                last = e
        raise _ProxyError(502, 'Bad Gateway', f'cannot connect to {d.host}:{d.port} '
                                              f'({last.__class__.__name__ if last else "no address"})')

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(self.settings.idle_timeout)
        try:
            head, rest = _read_head(conn)
            lines = head.decode('latin-1').split('\r\n')
            parts = lines[0].split(' ')
            if len(parts) != 3 or not parts[2].startswith('HTTP/'):
                raise _ProxyError(400, 'Bad Request', 'malformed request line')
            method, target, version = parts
            if method.upper() == 'CONNECT':
                host, port = _split_hostport(target, 443)
                d = self._decide('CONNECT', host, port)
                if not d.allowed:
                    raise _ProxyError(403, 'Forbidden', f'sandbox egress refused: {d.host}:{d.port} {d.reason}')
                upstream = self._connect(d)
                try:
                    conn.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
                    if rest:
                        upstream.sendall(rest)
                    self._relay(conn, upstream)
                finally:
                    upstream.close()
                return
            try:
                u = urlsplit(target)
                port = u.port or 80
            except ValueError:
                raise _ProxyError(400, 'Bad Request', 'unparseable request target')
            if u.scheme == 'https':
                raise _ProxyError(400, 'Bad Request', 'https:// through this proxy needs CONNECT')
            if u.scheme != 'http' or not u.hostname:
                raise _ProxyError(400, 'Bad Request', 'only CONNECT and absolute http:// requests are proxied')
            if u.username or u.password:
                raise _ProxyError(400, 'Bad Request', 'credentials in the URL are not forwarded')
            d = self._decide(method.upper(), u.hostname, port)
            if not d.allowed:
                raise _ProxyError(403, 'Forbidden', f'sandbox egress refused: {d.host}:{d.port} {d.reason}')
            path = (u.path or '/') + (f'?{u.query}' if u.query else '')
            out = [f'{method} {path} {version}']
            for line in lines[1:]:
                name = line.split(':', 1)[0].strip().lower()
                if name in ('proxy-authorization', 'proxy-connection', 'connection', 'keep-alive'):
                    continue
                out.append(line)
            out.append('Connection: close')
            upstream = self._connect(d)
            try:
                upstream.sendall(('\r\n'.join(out) + '\r\n\r\n').encode('latin-1') + rest)
                self._relay(conn, upstream)
            finally:
                upstream.close()
        except _ProxyError as e:
            self._reply(conn, e.status, e.reason, e.message)
        except socket.timeout:
            self._reply(conn, 408, 'Request Timeout', 'request head not received in time')

    def _relay(self, client: socket.socket, upstream: socket.socket) -> None:
        self._track(upstream)
        up, down = [0], [0]
        t = threading.Thread(target=_pump, args=(client, upstream, up, self.settings.idle_timeout), daemon=True)
        t.start()
        _pump(upstream, client, down, self.settings.idle_timeout)
        t.join(timeout=self.settings.idle_timeout)
        self._untrack(upstream)
        self.stats['bytes_up'] += up[0]
        self.stats['bytes_down'] += down[0]


# ── per-run helpers used by the backends ─────────────────────────────

def egress_dir_for(run_id: str, base: Optional[str] = None) -> str:
    """The per-run directory holding the proxy's socket: short (a Unix socket path is at most
    107 bytes), created fresh with ``os.mkdir`` (fails if anyone pre-created it)."""
    import tempfile
    return os.path.join(base or tempfile.gettempdir(), f'{run_id}.egress')


def start_for_run(run_id: str, allow_hosts: Sequence[str], tool: str = '', world_reachable: bool = False,
                  base: Optional[str] = None, settings: Optional[EgressSettings] = None) -> EgressProxy:
    """Create the run's socket directory and start its proxy there.

    ``world_reachable``: the directory is 0711 and the socket 0666, for a container whose user
    (65534) is not the server's; otherwise both are private to the server's user (which the
    namespace backends map the sandbox to)."""
    d = egress_dir_for(run_id, base)
    os.mkdir(d, 0o700)
    proxy = EgressProxy(allow_hosts, run_id=run_id, tool=tool, settings=settings)
    path = os.path.join(d, SOCKET_NAME)
    if len(path.encode()) > 107:
        os.rmdir(d)
        raise OSError(f'egress socket path too long: {path}')
    proxy.start_unix(path)
    proxy.owns_dir = True
    if world_reachable:
        os.chmod(d, 0o711)
        os.chmod(path, 0o666)
    return proxy


def start_in_dir(directory: str, run_id: str, allow_hosts: Sequence[str], tool: str = '',
                 world_reachable: bool = False, settings: Optional[EgressSettings] = None) -> EgressProxy:
    """Start a run's proxy in an existing directory (a warm container's mounted socket directory)."""
    path = os.path.join(directory, SOCKET_NAME)
    try:
        os.unlink(path)                                     # a leftover from a killed run
    except FileNotFoundError:
        pass
    proxy = EgressProxy(allow_hosts, run_id=run_id, tool=tool, settings=settings)
    proxy.start_unix(path)
    if world_reachable:
        os.chmod(path, 0o666)
    return proxy


def stop_for_run(proxy: Optional[EgressProxy]) -> None:
    if proxy is None:
        return
    proxy.stop()
    if proxy.path and proxy.owns_dir:
        try:
            os.rmdir(os.path.dirname(proxy.path))
        except OSError:
            pass


# ── long-lived containers (federated stdio upstreams) ────────────────

#: The bridge for a container that runs someone else's program (not the runner): a sidecar
#: container with no network listens on its loopback and relays to the proxy socket; the
#: upstream container joins the sidecar's network namespace (``--network container:<sidecar>``),
#: so its only route is that loopback.
BRIDGE_SOURCE = '''import socket, sys, threading
path, port = sys.argv[1], int(sys.argv[2])
def pump(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    finally:
        try:
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass
def serve(c):
    u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        u.connect(path)
    except OSError:
        c.close(); u.close(); return
    t = threading.Thread(target=pump, args=(c, u), daemon=True); t.start()
    pump(u, c); t.join(); c.close(); u.close()
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", port)); srv.listen(64)
while True:
    c, _ = srv.accept()
    threading.Thread(target=serve, args=(c,), daemon=True).start()
'''


class ContainerEgress:
    """The egress proxy and bridge sidecar of one long-lived container, torn down when the
    container ends (a watcher polls ``docker inspect``) or on :meth:`stop`."""

    def __init__(self, name: str, allow_hosts: Sequence[str], binary: str, image: str,
                 launch_env: Dict[str, str], tool: str = '', runtime: str = '',
                 appear_timeout: float = 120.0, poll: float = 2.0):
        self.name, self.binary, self.image, self.runtime = name, binary, image, runtime
        self.launch_env = launch_env
        self.sidecar = f'{name}-egress'
        self.appear_timeout, self.poll = appear_timeout, poll
        import uuid                                         # a short socket path whatever the name's length
        self.proxy: Optional[EgressProxy] = start_for_run(f'sajha-ce-{uuid.uuid4().hex[:12]}', allow_hosts,
                                                          tool=tool or f'container:{name}', world_reachable=True)
        self.proxy.run_id = name                            # the audit names the container
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._since = time.time() - 1

    def _docker(self, *args: str, timeout: float = 30.0):
        import shutil
        import subprocess
        return subprocess.run([shutil.which(self.binary) or self.binary, *args], capture_output=True, text=True,
                              timeout=timeout, env=self.launch_env)

    def start(self) -> 'ContainerEgress':
        args = ['run', '-d', '--rm', '--name', self.sidecar, '--label', f'sajha.egress.sidecar={self.name}',
                '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--user', '65534:65534', '--memory', '64m', '--memory-swap', '64m', '--pids-limit', '64',
                '--log-driver', 'none', '-v', f'{os.path.dirname(self.proxy.path)}:{INNER_SOCKET_DIR}:ro']
        if self.runtime:
            args += ['--runtime', self.runtime]
        args += [self.image, 'python3', '-I', '-S', '-c', BRIDGE_SOURCE,
                 f'{INNER_SOCKET_DIR}/{SOCKET_NAME}', str(PROXY_PORT)]
        try:
            r = self._docker(*args, timeout=60)
            if r.returncode != 0:
                raise OSError(f'egress sidecar for {self.name} did not start: {(r.stderr or r.stdout).strip()[:300]}')
            deadline = time.monotonic() + 20
            while True:
                st = self._docker('inspect', '-f', '{{.State.Running}}', self.sidecar)
                if st.stdout.strip() == 'true':
                    break
                if time.monotonic() > deadline:
                    raise OSError(f'egress sidecar for {self.name} is not running')
                time.sleep(0.2)
        except Exception:
            self.stop()
            raise
        self._thread = threading.Thread(target=self._watch, name=f'egress-watch-{self.name}', daemon=True)
        self._thread.start()
        return self

    def _watch(self) -> None:
        """Until the container dies (``docker events``, replayed from before it started, so a container
        that ended between two polls counts) or never appears within ``appear_timeout``."""
        import select
        import shutil
        import subprocess
        events = None
        try:
            events = subprocess.Popen(
                [shutil.which(self.binary) or self.binary, 'events', '--since', str(int(self._since)),
                 '--filter', f'container={self.name}', '--filter', 'event=die', '--format', '{{.Actor.Attributes.name}}'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=self.launch_env)
        except OSError as e:
            logger.debug(f'egress: docker events for {self.name}: {e}')
        seen, started = False, time.monotonic()
        while not self._stop.is_set():
            if events is not None:
                ready, _, _ = select.select([events.stdout], [], [], self.poll)
                if ready:
                    line = events.stdout.readline()
                    if not line or line.decode('utf-8', 'replace').strip() == self.name:
                        break                               # it died (or the events stream ended)
                    continue                                # a container whose name merely starts the same
            elif self._stop.wait(self.poll):
                break
            if not seen:
                r = self._docker('inspect', '-f', '{{.State.Running}}', self.name)
                seen = r.returncode == 0
                if not seen and time.monotonic() - started > self.appear_timeout:
                    break
            elif events is None:
                r = self._docker('inspect', '-f', '{{.State.Running}}', self.name)
                if not (r.returncode == 0 and r.stdout.strip() == 'true'):
                    break
        if events is not None:
            events.kill()
            events.wait(timeout=5)
        self.stop()

    def stop(self) -> None:
        with _CONTAINERS_LOCK:
            if self.proxy is None:
                return
            proxy, self.proxy = self.proxy, None
        self._stop.set()
        try:
            self._docker('rm', '-f', self.sidecar)
        except Exception:
            pass
        stop_for_run(proxy)
        with _CONTAINERS_LOCK:
            if _CONTAINERS.get(self.name) is self:
                del _CONTAINERS[self.name]


_CONTAINERS: Dict[str, ContainerEgress] = {}
_CONTAINERS_LOCK = threading.Lock()


def container_network_args(name: str, allow_hosts: Sequence[str], binary: str, image: str,
                           launch_env: Dict[str, str], runtime: str = '', tool: str = '') -> List[str]:
    """``docker run`` arguments that confine the long-lived container ``name`` to an egress proxy
    for ``allow_hosts``: no network of its own (it joins a sidecar's loopback-only namespace) and
    ``HTTP(S)_PROXY`` pointing at the sidecar's bridge. Starts the proxy and the sidecar now; both
    end when the container ends (or never appears)."""
    stop_container_egress(name)
    ce = ContainerEgress(name, allow_hosts, binary, image, launch_env, tool=tool, runtime=runtime).start()
    with _CONTAINERS_LOCK:
        _CONTAINERS[name] = ce
    args = ['--network', f'container:{ce.sidecar}']
    for k, v in proxy_env().items():
        args += ['-e', f'{k}={v}']
    return args


def stop_container_egress(name: str) -> None:
    with _CONTAINERS_LOCK:
        ce = _CONTAINERS.get(name)
    if ce is not None:
        ce.stop()


def _stop_all_containers() -> None:
    with _CONTAINERS_LOCK:
        everyone = list(_CONTAINERS.values())
    for ce in everyone:
        ce.stop()


atexit.register(_stop_all_containers)


__all__ = ['PROXY_PORT', 'INNER_SOCKET_DIR', 'SOCKET_NAME', 'EgressProxy', 'EgressSettings', 'Decision',
           'decide', 'load_egress_settings', 'parse_allow_hosts', 'proxy_env', 'egress_dir_for',
           'start_for_run', 'start_in_dir', 'stop_for_run', 'ContainerEgress', 'container_network_args',
           'stop_container_egress']
