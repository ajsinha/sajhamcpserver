"""
SAJHA sandbox — a warm container pool for the docker backend.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A container per call costs hundreds of milliseconds, most of it creating and starting the
container. The pool keeps ``sandbox.docker.pool.size`` containers started ahead of time,
each with exactly the confinement a per-call container has (``--network none``, read-only
root, tmpfs ``/work`` and ``/tmp``, memory, CPU and PID limits, all capabilities dropped,
no-new-privileges, user 65534, the configured runtime), and runs a call in one of them
with ``docker exec``. PID 1 of a pool container is a tiny Python loop that only reaps
orphans.

After a call the container is reset in one of two ways (``sandbox.docker.pool.reset``):

* ``recreate`` (default): the used container is removed and a fresh one started in the
  background. Nothing a call did can survive; the start cost moves off the call's path.
* ``reuse``: every process but PID 1 is killed, ``/work``, ``/tmp``, ``/dev/shm`` and
  ``/dev/mqueue`` are emptied and SysV IPC objects removed; the reset is verified and a
  container that fails it, timed out, or served ``max_uses`` calls is recreated instead.

Only calls whose limits equal the pool's profile (``sandbox.defaults``: ``memory_mb``,
``max_processes``, ``max_file_mb``) and whose network is off or goes through the egress
proxy use the pool; anything else, and any call that finds no idle container, gets a
per-call container as before (counted as a miss). The pool never holds more than
``size`` containers (idle, busy, starting or resetting together), capped at
``MAX_POOL_SIZE``. A health thread checks idle containers every
``health_interval_seconds`` and replaces dead ones. Containers carry the label
``sajha.sandbox.pool=<host>:<pid>``; a starting pool removes containers left by a
process of this host that no longer runs.

Each pool container has its own host directory mounted read-only at
``/run/sajha-egress``; a call that uses the egress proxy gets its proxy socket there.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_POOL_SIZE = 32
LABEL = 'sajha.sandbox.pool'
WORKDIR = '/work'

#: PID 1 of a pool container: reaps orphans, nothing else (signals from inside the
#: container to an init without a handler for them are ignored by the kernel).
INIT_SOURCE = '''import os, signal
def reap(*a):
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return
signal.signal(signal.SIGCHLD, reap)
while True:
    signal.pause()
'''

#: Run as the container's user after a call in ``reuse`` mode; prints RESET-OK when clean.
RESET_SOURCE = '''import ctypes, os, shutil, signal, sys, time
me = os.getpid()
def live():
    out = []
    for p in os.listdir('/proc'):
        if not p.isdigit() or int(p) in (1, me):
            continue
        try:
            with open('/proc/%s/stat' % p) as f:
                state = f.read().rsplit(')', 1)[1].split()[0]
        except (OSError, IndexError):
            continue
        if state not in ('Z', 'X'):
            out.append(int(p))
    return out
for _ in range(50):
    pids = live()
    if not pids:
        break
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(0.02)
else:
    print('RESET-PROCESSES-LEFT')
    raise SystemExit(3)
def fix(func, path, exc):
    try:
        os.chmod(os.path.dirname(path), 0o700)
        os.chmod(path, 0o700)
    except OSError:
        pass
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
    except OSError:
        pass
DIRS = ('/work', '/tmp', '/dev/shm', '/dev/mqueue')
for d in DIRS:
    if not os.path.isdir(d):
        continue
    for n in os.listdir(d):
        p = os.path.join(d, n)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, **({'onexc': fix} if sys.version_info >= (3, 12) else {'onerror': fix}))
        else:
            try:
                os.unlink(p)
            except OSError:
                pass
libc = ctypes.CDLL(None)
for kind in ('shm', 'sem', 'msg'):
    try:
        with open('/proc/sysvipc/' + kind) as f:
            rows = f.read().splitlines()[1:]
    except OSError:
        continue
    for row in rows:
        ident = int(row.split()[1])
        if kind == 'shm':
            libc.shmctl(ident, 0, None)
        elif kind == 'sem':
            libc.semctl(ident, 0, 0)
        else:
            libc.msgctl(ident, 0, None)
left = [n for d in DIRS if os.path.isdir(d) for n in os.listdir(d)]
ipc = 0
for kind in ('shm', 'sem', 'msg'):
    try:
        with open('/proc/sysvipc/' + kind) as f:
            ipc += len(f.read().splitlines()[1:])
    except OSError:
        pass
if left or ipc or live():
    print('RESET-LEFT files=%d ipc=%d' % (len(left), ipc))
    raise SystemExit(4)
print('RESET-OK')
'''


# ── settings ─────────────────────────────────────────────────────────

@dataclass
class PoolConfig:
    size: int = 0
    reset: str = 'recreate'
    max_uses: int = 20
    health_interval: float = 30.0
    start_timeout: float = 60.0


def load_pool_config() -> PoolConfig:
    from .settings import _as_int, _raw
    size = max(0, min(MAX_POOL_SIZE, _as_int(_raw('docker.pool.size', 0), 0)))
    reset = str(_raw('docker.pool.reset', 'recreate') or 'recreate').strip().lower()
    return PoolConfig(size=size, reset=reset if reset in ('recreate', 'reuse') else 'recreate',
                      max_uses=max(1, _as_int(_raw('docker.pool.max_uses', 20), 20)),
                      health_interval=float(max(1, _as_int(_raw('docker.pool.health_interval_seconds', 30), 30))),
                      start_timeout=float(max(5, _as_int(_raw('docker.pool.start_timeout_seconds', 60), 60))))


@dataclass
class Profile:
    """The fixed confinement of a pool's containers."""
    binary: str
    image: str
    memory_mb: int
    max_processes: int
    max_file_mb: int
    cpus: str = '1'
    runtime: str = ''


@dataclass
class Lease:
    name: str
    egress_dir: str
    uses: int = 0
    broken: bool = False
    created: float = field(default_factory=time.time)


def _metric_event(event: str) -> None:
    try:
        from sajha.observability.metrics import record_sandbox_pool_event
        record_sandbox_pool_event(event)
    except Exception:
        pass


def _metric_sizes(sizes: Dict[str, int]) -> None:
    try:
        from sajha.observability.metrics import set_sandbox_pool_containers
        for state, n in sizes.items():
            set_sandbox_pool_containers(state, n)
    except Exception:
        pass


def owner_label() -> str:
    return f'{socket.gethostname()}:{os.getpid()}'


# ── the pool ─────────────────────────────────────────────────────────

class WarmPool:
    def __init__(self, profile: Profile, config: PoolConfig, launch_env: Optional[Dict[str, str]] = None,
                 egress_base: Optional[str] = None):
        self.profile = profile
        self.config = config
        self.size = max(0, min(MAX_POOL_SIZE, config.size))
        self.launch_env = launch_env or {'PATH': '/usr/local/bin:/usr/bin:/bin'}
        self.egress_base = egress_base or tempfile.gettempdir()
        self.owner = owner_label()
        self._idle: Deque[Lease] = deque()
        self._busy: Dict[str, Lease] = {}
        self._starting = 0
        self._resetting = 0
        self._cv = threading.Condition()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._fail_streak = 0
        self.counters: Dict[str, int] = {k: 0 for k in (
            'hits', 'misses', 'started', 'start_failed', 'recycled', 'reset_ok', 'reset_failed',
            'discarded', 'health_failed')}
        self.last_error = ''

    # -- docker -------------------------------------------------------------
    def _docker(self, *args: str, timeout: float = 30.0, data: Optional[bytes] = None) -> subprocess.CompletedProcess:
        exe = shutil.which(self.profile.binary) or self.profile.binary
        return subprocess.run([exe, *args], input=data, capture_output=True, timeout=timeout, env=self.launch_env)

    def create_args(self, name: str, egress_dir: str) -> List[str]:
        p = self.profile
        mem = f'{p.memory_mb}m'
        args = ['run', '-d', '--name', name, '--label', f'{LABEL}={self.owner}', '--network', 'none',
                '--read-only',
                '--tmpfs', f'{WORKDIR}:rw,exec,nosuid,nodev,size={max(16, p.max_file_mb * 2)}m,mode=1777',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m,mode=1777', '-w', WORKDIR,
                '--memory', mem, '--memory-swap', mem, '--cpus', str(p.cpus or '1'),
                '--pids-limit', str(p.max_processes), '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--user', '65534:65534', '--log-driver', 'none',
                '-v', f'{egress_dir}:/run/sajha-egress:ro']
        if p.runtime:
            args += ['--runtime', p.runtime]
        return args + [p.image, 'python3', '-I', '-S', '-c', INIT_SOURCE]

    def exec_command(self, lease: Lease, runner_source: str) -> List[str]:
        """The argv that runs the runner in a leased container (stdin carries the request)."""
        exe = shutil.which(self.profile.binary) or self.profile.binary
        return [exe, 'exec', '-i', '-w', WORKDIR, '-u', '65534:65534', lease.name,
                'python3', '-I', '-B', '-c', runner_source]

    def _start_one(self) -> Optional[Lease]:
        name = f'sajha-pool-{uuid.uuid4().hex[:12]}'
        egress_dir = os.path.join(self.egress_base, f'{name}.egress')
        try:
            os.mkdir(egress_dir, 0o700)
            os.chmod(egress_dir, 0o711)
            r = self._docker(*self.create_args(name, egress_dir), timeout=self.config.start_timeout)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or r.stdout).decode('utf-8', 'replace').strip()[:300])
            self.counters['started'] += 1
            _metric_event('started')
            return Lease(name=name, egress_dir=egress_dir)
        except Exception as e:
            self.counters['start_failed'] += 1
            self.last_error = f'start failed: {e}'
            _metric_event('start_failed')
            logger.warning(f'sandbox pool: could not start a container: {e}')
            self._remove(name, egress_dir)
            return None

    def _remove(self, name: str, egress_dir: str) -> None:
        try:
            self._docker('rm', '-f', name, timeout=30)
        except Exception as e:
            logger.debug(f'sandbox pool: rm {name}: {e}')
        shutil.rmtree(egress_dir, ignore_errors=True)

    # -- lifecycle ------------------------------------------------------------
    def start(self) -> 'WarmPool':
        if self._threads or self.size <= 0:
            return self
        self.cleanup_stale()
        for target, nm in ((self._fill_loop, 'fill'), (self._health_loop, 'health')):
            t = threading.Thread(target=target, name=f'sandbox-pool-{nm}', daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def shutdown(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
            leases = list(self._idle) + list(self._busy.values())
            self._idle.clear()
            self._busy.clear()
        for t in self._threads:
            t.join(timeout=self.config.start_timeout + 5)
        with self._cv:                                      # let in-flight resets finish and clean up
            deadline = time.monotonic() + 30
            while self._resetting and time.monotonic() < deadline:
                self._cv.wait(timeout=0.5)
        for lease in leases:
            self._remove(lease.name, lease.egress_dir)
        self._publish()

    def cleanup_stale(self) -> int:
        """Remove pool containers of this host whose owning process is gone."""
        try:
            r = self._docker('ps', '-a', '--filter', f'label={LABEL}', '--format',
                             '{{.Names}} {{.Label "' + LABEL + '"}}', timeout=20)
        except Exception:
            return 0
        host = socket.gethostname()
        removed = 0
        for line in r.stdout.decode('utf-8', 'replace').splitlines():
            parts = line.split()
            if len(parts) != 2 or ':' not in parts[1]:
                continue
            name, owner = parts
            o_host, _, o_pid = owner.rpartition(':')
            if o_host != host or owner == self.owner:
                continue
            try:
                os.kill(int(o_pid), 0)
                continue                                    # its process still runs
            except (ProcessLookupError, ValueError):
                pass
            except PermissionError:
                continue
            self._remove(name, os.path.join(self.egress_base, f'{name}.egress'))
            removed += 1
        return removed

    def _total(self) -> int:
        return len(self._idle) + len(self._busy) + self._starting + self._resetting

    def _fill_loop(self) -> None:
        while not self._stop.is_set():
            with self._cv:
                while not self._stop.is_set() and self._total() >= self.size:
                    self._cv.wait(timeout=self.config.health_interval)
                if self._stop.is_set():
                    return
                self._starting += 1
            lease = self._start_one()
            late = False
            with self._cv:
                self._starting -= 1
                if lease is not None and not self._stop.is_set():
                    self._idle.append(lease)
                    self._fail_streak = 0
                    self._cv.notify_all()
                elif lease is not None:
                    late = True                             # started while the pool shut down
                else:
                    self._fail_streak += 1
            if late:
                self._remove(lease.name, lease.egress_dir)
            self._publish()
            if lease is None:                               # back off on a failing daemon or image
                self._stop.wait(min(60.0, 0.5 * (2 ** min(self._fail_streak, 7))))

    def _health_loop(self) -> None:
        while not self._stop.wait(self.config.health_interval):
            self.check_health()

    def check_health(self) -> int:
        """Inspect idle containers; replace the ones that are not running. Returns how many died."""
        with self._cv:
            names = [l.name for l in self._idle]
        if not names:
            return 0
        try:
            r = self._docker('inspect', '--format', '{{.Name}} {{.State.Running}}', *names, timeout=30)
            running = {ln.split()[0].lstrip('/') for ln in r.stdout.decode('utf-8', 'replace').splitlines()
                       if ln.strip().endswith('true')}
        except Exception as e:
            logger.debug(f'sandbox pool: health check failed: {e}')
            return 0
        dead: List[Lease] = []
        with self._cv:
            for lease in list(self._idle):
                if lease.name not in running:
                    self._idle.remove(lease)
                    dead.append(lease)
            if dead:
                self._cv.notify_all()
        for lease in dead:
            self.counters['health_failed'] += 1
            _metric_event('health_failed')
            self._remove(lease.name, lease.egress_dir)
        self._publish()
        return len(dead)

    # -- calls --------------------------------------------------------------
    def eligible(self, memory_mb: int, max_processes: int, max_file_mb: int, network_ok: bool) -> bool:
        p = self.profile
        return (self.size > 0 and network_ok and memory_mb == p.memory_mb
                and max_processes == p.max_processes and max_file_mb == p.max_file_mb)

    def acquire(self) -> Optional[Lease]:
        """An idle container, or None (the caller runs a per-call container instead)."""
        with self._cv:
            if self._idle:
                lease = self._idle.popleft()
                lease.uses += 1
                self._busy[lease.name] = lease
                self.counters['hits'] += 1
                hit = lease
            else:
                self.counters['misses'] += 1
                hit = None
        _metric_event('hit' if hit else 'miss')
        self._publish()
        return hit

    def release(self, lease: Lease) -> None:
        """Hand a container back after a call: reset it (reuse) or replace it (recreate)."""
        with self._cv:
            self._busy.pop(lease.name, None)
            self._resetting += 1
        threading.Thread(target=self._recycle, args=(lease,), daemon=True).start()

    def _recycle(self, lease: Lease) -> None:
        keep = False
        try:
            if (self.config.reset == 'reuse' and not lease.broken and lease.uses < self.config.max_uses
                    and not self._stop.is_set()):
                keep = self.reset(lease)
            if not keep:
                self.counters['recycled'] += 1
                _metric_event('recycled')
                self._remove(lease.name, lease.egress_dir)
        finally:
            with self._cv:
                self._resetting -= 1
                if keep and not self._stop.is_set():
                    self._idle.append(lease)
                self._cv.notify_all()
            if keep and self._stop.is_set():
                self._remove(lease.name, lease.egress_dir)
            self._publish()

    def reset(self, lease: Lease) -> bool:
        try:
            r = self._docker('exec', '-u', '65534:65534', lease.name, 'python3', '-I', '-S', '-c', RESET_SOURCE,
                             timeout=30)
            ok = r.returncode == 0 and b'RESET-OK' in r.stdout
        except Exception as e:
            ok = False
            self.last_error = f'reset failed: {e}'
        try:                                                # nothing may be left in the socket directory
            for n in os.listdir(lease.egress_dir):
                os.unlink(os.path.join(lease.egress_dir, n))
        except OSError:
            pass
        self.counters['reset_ok' if ok else 'reset_failed'] += 1
        _metric_event('reset_ok' if ok else 'reset_failed')
        return ok

    def kill(self, lease: Lease) -> None:
        """A call timed out or overflowed: its processes die with the container."""
        lease.broken = True
        try:
            self._docker('rm', '-f', lease.name, timeout=30)
        except Exception:
            pass

    # -- status -------------------------------------------------------------
    def sizes(self) -> Dict[str, int]:
        with self._cv:
            return {'idle': len(self._idle), 'busy': len(self._busy), 'starting': self._starting,
                    'resetting': self._resetting}

    def _publish(self) -> None:
        _metric_sizes(self.sizes())

    def stats(self) -> Dict[str, Any]:
        return {'size': self.size, 'reset': self.config.reset, 'max_uses': self.config.max_uses,
                'image': self.profile.image, 'memory_mb': self.profile.memory_mb,
                'max_processes': self.profile.max_processes, 'max_file_mb': self.profile.max_file_mb,
                'containers': self.sizes(), 'counters': dict(self.counters), 'last_error': self.last_error}

    def wait_ready(self, n: Optional[int] = None, timeout: float = 120.0) -> bool:
        """Block until ``n`` (default: size) containers are idle (start-up, tests)."""
        want = self.size if n is None else n
        deadline = time.monotonic() + timeout
        with self._cv:
            while len(self._idle) < want:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._cv.wait(timeout=min(left, 0.5))
        return True


# ── the process's pools ──────────────────────────────────────────────

_POOLS: Dict[tuple, WarmPool] = {}
_lock = threading.Lock()


def pool_for(binary: str, image: str, defaults: Dict[str, Any], cpus: str, runtime: str,
             launch_env: Optional[Dict[str, str]] = None, config: Optional[PoolConfig] = None) -> Optional[WarmPool]:
    """The started pool for this docker profile, or None when ``sandbox.docker.pool.size`` is 0."""
    config = config or load_pool_config()
    if config.size <= 0:
        return None
    profile = Profile(binary=binary, image=image, memory_mb=int(defaults.get('memory_mb', 512)),
                      max_processes=int(defaults.get('max_processes', 64)),
                      max_file_mb=int(defaults.get('max_file_mb', 64)), cpus=str(cpus or '1'),
                      runtime=runtime or '')
    key = (profile.binary, profile.image, profile.memory_mb, profile.max_processes, profile.max_file_mb,
           profile.cpus, profile.runtime, config.size, config.reset, config.max_uses)
    with _lock:
        pool = _POOLS.get(key)
        if pool is None:
            for old_key in [k for k in _POOLS if k[:2] == key[:2]]:   # settings changed: retire the old pool
                threading.Thread(target=_POOLS.pop(old_key).shutdown, daemon=True).start()
            pool = _POOLS[key] = WarmPool(profile, config, launch_env).start()
        return pool


def all_pools() -> List[WarmPool]:
    with _lock:
        return list(_POOLS.values())


def status() -> List[Dict[str, Any]]:
    return [p.stats() for p in all_pools()]


def shutdown_all() -> None:
    with _lock:
        pools = list(_POOLS.values())
        _POOLS.clear()
    for p in pools:
        try:
            p.shutdown()
        except Exception as e:
            logger.debug(f'sandbox pool shutdown: {e}')


atexit.register(shutdown_all)


__all__ = ['MAX_POOL_SIZE', 'Lease', 'PoolConfig', 'Profile', 'WarmPool', 'all_pools', 'load_pool_config',
           'pool_for', 'shutdown_all', 'status']
