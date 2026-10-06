"""
SAJHA sandbox — backends.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A backend launches ``runner.py`` somewhere the server's privileges do not reach
and feeds it one JSON request. The launch differs per backend; the protocol,
the output cap and the wall-clock timeout are the same for all of them and live
in :meth:`Sandbox.run`.

* ``subprocess`` — a child process of the server. On Linux the runner itself adds
  user/PID/network namespaces, rlimits, Landlock and seccomp; elsewhere it is a
  clean environment, a temp work dir, rlimits and the timeout (see ``describe``).
* ``bwrap`` — bubblewrap: a fresh mount namespace holding only the system
  libraries, the interpreter and the work dir; no network unless allowlisted.
  The runner's Landlock/seccomp/rlimits apply inside it as well.
* ``nsjail`` — the same idea through nsjail.
* ``docker`` — one container per call (``--network none``, read-only rootfs,
  memory/CPU/PID limits, all capabilities dropped, nobody user); set
  ``sandbox.docker.runtime: runsc`` for gVisor. ``sandbox.docker.binary: podman``
  works too.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .policy import SandboxPolicy
from .settings import SandboxSettings, load_settings

logger = logging.getLogger(__name__)

RUNNER_PATH = Path(__file__).with_name('runner.py')
#: Repository root: never readable from a sandbox
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_WORKDIR = '/work'

SYSTEM_READ = ['/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64', '/libx32',
               '/etc/ld.so.cache', '/etc/ld.so.conf', '/etc/ld.so.conf.d', '/etc/localtime',
               '/etc/alternatives', '/etc/ssl', '/etc/ca-certificates', '/etc/pki',
               '/etc/crypto-policies', '/etc/mime.types']
NET_READ = ['/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf', '/etc/gai.conf',
            '/etc/host.conf', '/etc/services', '/etc/protocols']


# ── Errors and results ─────────────────────────────────────────────────────

class SandboxError(RuntimeError):
    """The sandbox could not run the code, or the code broke a sandbox limit."""


class SandboxUnavailable(SandboxError):
    pass


class SandboxTimeout(SandboxError):
    pass


class SandboxOutputLimit(SandboxError):
    pass


class SandboxToolError(SandboxError):
    """The sandboxed tool itself raised an exception."""


@dataclass
class SandboxResult:
    backend: str
    exit_code: int = 0
    stdout: str = ''
    stderr: str = ''
    duration_ms: float = 0.0
    timed_out: bool = False
    output_truncated: bool = False
    runner_error: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not (self.timed_out or self.output_truncated or self.runner_error)


# ── Helpers ────────────────────────────────────────────────────────────────

def deny_roots() -> List[str]:
    """Directories no readable path may contain or be inside (except the interpreter)."""
    roots = {str(PROJECT_ROOT), os.getcwd(), os.path.expanduser('~')}
    db = os.environ.get('SAJHA_DB_PATH')
    if db:
        roots.add(os.path.dirname(os.path.abspath(db)))
    return sorted(r for r in roots if r and r != '/')


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip('/') + '/')


_INTERP_CACHE: Dict[str, Dict[str, Any]] = {}


def interpreter_paths(python: str) -> Dict[str, Any]:
    """The interpreter's prefixes and isolated sys.path (asked once, cached)."""
    if python in _INTERP_CACHE:
        return _INTERP_CACHE[python]
    code = ('import sys,json,os;print(json.dumps({"prefixes":[sys.prefix,sys.base_prefix,sys.exec_prefix,'
            'os.path.dirname(os.path.realpath(sys.executable))],"path":[p for p in sys.path if p and os.path.isdir(p)]}))')
    try:
        out = subprocess.run([python, '-I', '-c', code], capture_output=True, text=True, timeout=20,
                             env={'PATH': '/usr/bin:/bin'})
        info = json.loads(out.stdout)
    except Exception as e:
        logger.warning(f'Could not query interpreter {python}: {e}')
        info = {'prefixes': [sys.prefix, sys.base_prefix], 'path': []}
    _INTERP_CACHE[python] = info
    return info


def readable_paths(python: str, network_on: bool, extra: List[str]) -> List[str]:
    """Host paths a namespace backend binds read-only (same rules as the runner's Landlock)."""
    info = interpreter_paths(python)
    prefixes = [os.path.realpath(p) for p in info['prefixes']]
    deny = [os.path.realpath(d) for d in deny_roots()]
    cands = SYSTEM_READ + (NET_READ if network_on else []) + prefixes + info['path'] + list(extra)
    out: List[str] = []
    for p in cands:
        if not os.path.lexists(p):
            continue
        if any(_within(d, p) for d in deny):
            continue
        if any(_within(os.path.realpath(p), d) for d in deny) and \
                not any(_within(os.path.realpath(p), x) for x in prefixes):
            continue
        if p not in out:
            out.append(p)
    return out


def _capped_reader(stream, cap: int, sink: List[bytes], state: Dict[str, Any], on_exceed):
    total = 0
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            if total < cap:
                sink.append(chunk[:cap - total])
            total += len(chunk)
            if total > cap and not state.get('exceeded'):
                state['exceeded'] = True
                on_exceed()
    except (OSError, ValueError):
        pass


# ── Backend base ───────────────────────────────────────────────────────────

class Sandbox:
    """One way of running the runner. Subclasses fill in the launch."""

    name = 'base'
    #: what the backend promises when it is fully available, by guarantee
    summary = ''

    def __init__(self, settings: Optional[SandboxSettings] = None):
        self.settings = settings or load_settings()
        self._probe: Optional[Dict[str, Any]] = None

    # -- availability ------------------------------------------------------
    def available(self) -> Tuple[bool, str]:
        raise NotImplementedError

    # -- launch pieces -----------------------------------------------------
    def python(self) -> str:
        return self.settings.python or sys.executable

    def inner_workdir(self, host_workdir: str) -> str:
        return SANDBOX_WORKDIR

    def confine(self, policy: SandboxPolicy) -> Dict[str, Any]:
        return {'userns': False, 'landlock': sys.platform.startswith('linux'),
                'seccomp': sys.platform.startswith('linux'), 'strict': self.settings.strict,
                'deny_roots': deny_roots(), 'extra_read_paths': self.settings.extra_read_paths}

    def command(self, workdir: str, policy: SandboxPolicy, run_id: str) -> List[str]:
        raise NotImplementedError

    def launch_env(self) -> Dict[str, str]:
        return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}

    def popen_cwd(self, workdir: str) -> str:
        return workdir

    def on_kill(self, run_id: str) -> None:
        """Extra cleanup when a run is killed (containers outlive their client)."""

    # -- the run -----------------------------------------------------------
    def sandbox_env(self, inner: str, policy: SandboxPolicy) -> Dict[str, str]:
        env = {
            'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': inner, 'TMPDIR': inner,
            'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1', 'MALLOC_ARENA_MAX': '2',
            'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
            'SAJHA_SANDBOX': self.name,
        }
        env.update(policy.env)
        env.update(policy.secret_env(self.settings))
        return env

    def run(self, request: Dict[str, Any], policy: SandboxPolicy) -> SandboxResult:
        ok, why = self.available()
        if not ok:
            raise SandboxUnavailable(f'sandbox backend {self.name} is not available: {why}')
        base = self.settings.work_dir or None
        if base:
            os.makedirs(base, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix='sajha-sbx-', dir=base)
        run_id = f'sajha-sbx-{uuid.uuid4().hex[:12]}'
        try:
            os.chmod(workdir, 0o700)
            shutil.copyfile(RUNNER_PATH, os.path.join(workdir, 'runner.py'))
            inner = self.inner_workdir(workdir)
            req = dict(request)
            req['env'] = self.sandbox_env(inner, policy)
            req['limits'] = {'cpu_seconds': policy.cpu_seconds, 'memory_mb': policy.memory_mb,
                             'max_file_mb': policy.max_file_mb, 'max_processes': policy.max_processes}
            req['network'] = {'mode': policy.network, 'ports': policy.allow_ports,
                              'hosts': policy.allow_hostnames}
            req['confine'] = self.confine(policy)
            argv = req.get('argv')
            if argv:
                req['argv'] = [self.python() if a == '{python}' else a for a in argv]
            return self._launch(self.command(workdir, policy, run_id), json.dumps(req).encode('utf-8'),
                                policy, workdir, run_id)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _launch(self, cmd: List[str], data: bytes, policy: SandboxPolicy,
                workdir: str, run_id: str) -> SandboxResult:
        start = time.monotonic()
        kwargs: Dict[str, Any] = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      cwd=self.popen_cwd(workdir), env=self.launch_env(), close_fds=True)
        if os.name == 'posix':
            kwargs['start_new_session'] = True
        try:
            proc = subprocess.Popen(cmd, **kwargs)
        except OSError as e:
            raise SandboxUnavailable(f'cannot start sandbox backend {self.name}: {e}')
        killed = {'done': False}

        def kill():
            if killed['done']:
                return
            killed['done'] = True
            try:
                if os.name == 'posix':
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except (ProcessLookupError, PermissionError, OSError):
                pass
            self.on_kill(run_id)

        out: List[bytes] = []
        err: List[bytes] = []
        state_out: Dict[str, Any] = {}
        state_err: Dict[str, Any] = {}
        cap = policy.max_output_bytes
        readers = [threading.Thread(target=_capped_reader, args=(proc.stdout, cap, out, state_out, kill), daemon=True),
                   threading.Thread(target=_capped_reader, args=(proc.stderr, cap, err, state_err, kill), daemon=True)]
        for t in readers:
            t.start()
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        timed_out = False
        try:
            proc.wait(timeout=policy.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for t in readers:
            t.join(timeout=3)
        for s in (proc.stdout, proc.stderr):
            try:
                s.close()
            except Exception:
                pass
        stdout = b''.join(out).decode('utf-8', 'replace')
        stderr = b''.join(err).decode('utf-8', 'replace')
        res = SandboxResult(backend=self.name, exit_code=proc.returncode if proc.returncode is not None else -9,
                            stdout=stdout, stderr=stderr, duration_ms=(time.monotonic() - start) * 1000,
                            timed_out=timed_out,
                            output_truncated=bool(state_out.get('exceeded') or state_err.get('exceeded')))
        if res.exit_code == 125 and 'SAJHA-SANDBOX:' in stderr:
            res.runner_error = stderr.split('SAJHA-SANDBOX:', 1)[1].strip().splitlines()[0]
        try:   # sajha_sandbox_runs_total / _duration_seconds (sajha/observability)
            from sajha.observability.metrics import record_sandbox_run
            record_sandbox_run(res)
        except Exception:
            pass
        return res

    # -- probe / guarantees --------------------------------------------------
    def probe(self, refresh: bool = False) -> Dict[str, Any]:
        """Run the runner once with network off and report what it actually applied."""
        if self._probe is not None and not refresh:
            return self._probe
        from .policy import policy_from_config
        ok, why = self.available()
        if not ok:
            self._probe = {'ok': False, 'error': why}
            return self._probe
        try:
            res = self.run({'op': 'probe'}, policy_from_config({'timeout_seconds': 60}, self.settings))
            payload = json.loads(res.stdout) if res.stdout.strip() else {}
            self._probe = {'ok': bool(payload.get('ok')), 'applied': payload.get('applied') or {},
                           'error': res.runner_error or (None if payload else res.stderr[-300:])}
        except Exception as e:
            self._probe = {'ok': False, 'error': str(e)}
        return self._probe

    def guarantees(self, probe: bool = True) -> List[Dict[str, Any]]:
        """What this backend enforces here, each with how; from a live probe when asked."""
        raise NotImplementedError

    def _runner_guarantees(self, applied: Dict[str, Any]) -> List[Dict[str, Any]]:
        ll = applied.get('landlock') if isinstance(applied.get('landlock'), dict) else None
        sc = applied.get('seccomp') if isinstance(applied.get('seccomp'), dict) else None
        rl = applied.get('rlimits') if isinstance(applied.get('rlimits'), dict) else {}
        return [
            {'guarantee': 'Filesystem: read only system libraries and the interpreter; write only the work dir',
             'enforced': bool(ll), 'how': f"Landlock ABI {ll['abi']}" if ll else applied.get('landlock', 'not applied')},
            {'guarantee': 'Network off unless allowlisted',
             'enforced': bool(applied.get('netns') or sc),
             'how': ', '.join(x for x in ['network namespace' if applied.get('netns') else '',
                                          'seccomp: no sockets' if sc else '',
                                          'Landlock TCP' if ll and ll.get('tcp') else ''] if x) or 'not applied'},
            {'guarantee': 'Cannot see, signal or trace server processes',
             'enforced': bool(applied.get('pidns') or (ll and ll.get('signals_and_abstract_sockets'))),
             'how': ', '.join(x for x in ['PID namespace' if applied.get('pidns') else '',
                                          'Landlock signal scope' if ll and ll.get('signals_and_abstract_sockets') else '',
                                          'seccomp: no ptrace' if sc else ''] if x) or 'not applied'},
            {'guarantee': 'CPU, memory, file size, process count limits',
             'enforced': bool(rl), 'how': ', '.join(f'{k}={v}' for k, v in rl.items()) or 'not applied'},
            {'guarantee': 'Children killed with the sandbox (no daemons left behind)',
             'enforced': bool(applied.get('pidns')), 'how': 'PID namespace' if applied.get('pidns') else 'process group kill only'},
        ]

    def _common_guarantees(self) -> List[Dict[str, Any]]:
        return [
            {'guarantee': 'Server environment not inherited (allowlisted env and declared secrets only)',
             'enforced': True, 'how': 'explicit environment'},
            {'guarantee': 'Fresh temporary work directory per call, deleted afterwards', 'enforced': True,
             'how': 'tempfile.mkdtemp'},
            {'guarantee': 'Wall-clock timeout and output size cap', 'enforced': True,
             'how': 'process group SIGKILL'},
        ]


# ── subprocess ─────────────────────────────────────────────────────────────

class SubprocessSandbox(Sandbox):
    name = 'subprocess'
    summary = ('Separate process with a clean environment, temp work dir and rlimits; on Linux also '
               'user/PID/network namespaces, Landlock and seccomp applied by the runner.')

    def available(self) -> Tuple[bool, str]:
        return (True, 'always available') if os.name == 'posix' else \
            (True, 'Windows: timeout, clean environment and output cap only')

    def inner_workdir(self, host_workdir: str) -> str:
        return host_workdir

    def confine(self, policy: SandboxPolicy) -> Dict[str, Any]:
        c = super().confine(policy)
        c['userns'] = sys.platform.startswith('linux')
        return c

    def command(self, workdir: str, policy: SandboxPolicy, run_id: str) -> List[str]:
        return [self.python(), '-I', '-B', os.path.join(workdir, 'runner.py')]

    def guarantees(self, probe: bool = True) -> List[Dict[str, Any]]:
        applied = self.probe().get('applied', {}) if probe else {}
        return self._common_guarantees() + self._runner_guarantees(applied)


# ── bubblewrap ─────────────────────────────────────────────────────────────

_AVAIL_CACHE: Dict[str, Tuple[bool, str]] = {}


class BwrapSandbox(Sandbox):
    name = 'bwrap'
    summary = ('bubblewrap: user, PID, IPC, UTS, cgroup and network namespaces; a new root holding only '
               'system libraries, the interpreter (read-only) and the work dir; runner limits inside.')

    def available(self) -> Tuple[bool, str]:
        if 'bwrap' not in _AVAIL_CACHE:
            exe = shutil.which('bwrap')
            if not exe:
                _AVAIL_CACHE['bwrap'] = (False, 'bwrap is not installed')
            else:
                try:
                    r = subprocess.run([exe, '--unshare-all', '--ro-bind', '/', '/', '--', '/bin/true'],
                                       capture_output=True, text=True, timeout=15)
                    _AVAIL_CACHE['bwrap'] = (r.returncode == 0, exe if r.returncode == 0 else
                                             f'bwrap cannot create namespaces here: {r.stderr.strip()[:200]}')
                except Exception as e:
                    _AVAIL_CACHE['bwrap'] = (False, str(e))
        return _AVAIL_CACHE['bwrap']

    def command(self, workdir: str, policy: SandboxPolicy, run_id: str) -> List[str]:
        net = policy.network == 'allowlist'
        cmd = [shutil.which('bwrap') or 'bwrap', '--die-with-parent', '--new-session', '--unshare-all',
               '--cap-drop', 'ALL', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
               '--setenv', 'LANG', 'C.UTF-8']
        if net:
            cmd.append('--share-net')
        # /proc, /dev and /tmp first: a later bind under /tmp (a virtualenv there) must stay visible
        cmd += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
        bound: List[str] = []
        for p in sorted(readable_paths(self.python(), net, self.settings.extra_read_paths), key=len):
            if os.path.islink(p) and os.path.dirname(p) in ('/', '/etc'):
                cmd += ['--symlink', os.readlink(p), p]
                continue
            if any(_within(p, b) for b in bound):
                continue
            cmd += ['--ro-bind', p, p]
            bound.append(p)
        cmd += ['--bind', workdir, SANDBOX_WORKDIR, '--chdir', SANDBOX_WORKDIR,
                '--', self.python(), '-I', '-B', f'{SANDBOX_WORKDIR}/runner.py']
        return cmd

    def guarantees(self, probe: bool = True) -> List[Dict[str, Any]]:
        applied = self.probe().get('applied', {}) if probe else {}
        g = self._common_guarantees() + [
            {'guarantee': 'Only system libraries, the interpreter and the work dir exist in the sandbox',
             'enforced': True, 'how': 'bubblewrap mount namespace, read-only binds'},
            {'guarantee': 'Network off unless allowlisted', 'enforced': True, 'how': 'network namespace'},
            {'guarantee': 'Cannot see, signal or trace server processes', 'enforced': True,
             'how': 'PID namespace'},
            {'guarantee': 'Children killed with the sandbox', 'enforced': True, 'how': '--die-with-parent, PID namespace'},
        ]
        rl = applied.get('rlimits') if isinstance(applied.get('rlimits'), dict) else {}
        g.append({'guarantee': 'CPU, memory, file size, process count limits', 'enforced': bool(rl),
                  'how': ', '.join(f'{k}={v}' for k, v in rl.items()) or 'not applied'})
        return g


# ── nsjail ─────────────────────────────────────────────────────────────────

class NsjailSandbox(Sandbox):
    name = 'nsjail'
    summary = ('nsjail: namespaces, read-only binds of system libraries and the interpreter, the work '
               'dir read-write, its own rlimits and time limit; runner limits inside.')

    def available(self) -> Tuple[bool, str]:
        exe = shutil.which('nsjail')
        return (True, exe) if exe else (False, 'nsjail is not installed')

    def command(self, workdir: str, policy: SandboxPolicy, run_id: str) -> List[str]:
        net = policy.network == 'allowlist'
        cmd = [shutil.which('nsjail') or 'nsjail', '--mode', 'o', '--quiet',
               '--time_limit', str(policy.timeout_seconds + 1),
               '--rlimit_as', str(policy.memory_mb), '--rlimit_cpu', str(policy.cpu_seconds),
               '--rlimit_fsize', str(policy.max_file_mb), '--rlimit_nofile', '256',
               '--rlimit_nproc', str(policy.max_processes), '--disable_proc',
               '--tmpfsmount', '/tmp', '--bindmount', f'{workdir}:{SANDBOX_WORKDIR}', '--cwd', SANDBOX_WORKDIR]
        for p in readable_paths(self.python(), net, self.settings.extra_read_paths):
            cmd += ['--bindmount_ro', p]
        if net:
            cmd.append('--disable_clone_newnet')
        cmd += ['--', self.python(), '-I', '-B', f'{SANDBOX_WORKDIR}/runner.py']
        return cmd

    def guarantees(self, probe: bool = True) -> List[Dict[str, Any]]:
        return self._common_guarantees() + [
            {'guarantee': 'Only system libraries, the interpreter and the work dir exist in the sandbox',
             'enforced': True, 'how': 'nsjail mount namespace'},
            {'guarantee': 'Network off unless allowlisted', 'enforced': True, 'how': 'network namespace'},
            {'guarantee': 'Cannot see server processes', 'enforced': True, 'how': 'PID namespace'},
            {'guarantee': 'CPU, memory, file size, process count limits', 'enforced': True, 'how': 'nsjail rlimits'},
        ]


# ── docker / podman ────────────────────────────────────────────────────────

class DockerSandbox(Sandbox):
    name = 'docker'
    summary = ('One container per call: --network none, read-only root, memory/CPU/PID limits, all '
               'capabilities dropped, no-new-privileges, nobody user; optional gVisor runtime.')

    def binary(self) -> str:
        return self.settings.docker.get('binary') or 'docker'

    def image(self) -> str:
        return self.settings.docker.get('image') or 'python:3.13-slim'

    def available(self) -> Tuple[bool, str]:
        key = f'docker:{self.binary()}:{self.image()}'
        if key not in _AVAIL_CACHE:
            exe = shutil.which(self.binary())
            if not exe:
                _AVAIL_CACHE[key] = (False, f'{self.binary()} is not installed')
            else:
                try:
                    r = subprocess.run([exe, 'image', 'inspect', '--format', '{{.Id}}', self.image()],
                                       capture_output=True, text=True, timeout=20, env=self.launch_env())
                    _AVAIL_CACHE[key] = (True, f'{exe}, image {self.image()}') if r.returncode == 0 else \
                        (False, f'image {self.image()} is not present (pull it first) or the daemon is '
                                f'unreachable: {(r.stderr or r.stdout).strip()[:200]}')
                except Exception as e:
                    _AVAIL_CACHE[key] = (False, str(e))
        return _AVAIL_CACHE[key]

    def python(self) -> str:
        return 'python3'

    def launch_env(self) -> Dict[str, str]:
        env = super().launch_env()
        for k in ('HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_CERT_PATH',
                  'DOCKER_TLS_VERIFY', 'XDG_RUNTIME_DIR', 'CONTAINER_HOST'):
            if k in os.environ:
                env[k] = os.environ[k]
        return env

    def confine(self, policy: SandboxPolicy) -> Dict[str, Any]:
        c = super().confine(policy)
        c.update({'userns': False, 'deny_roots': [], 'extra_read_paths': []})
        return c

    def command(self, workdir: str, policy: SandboxPolicy, run_id: str) -> List[str]:
        mem = f'{policy.memory_mb}m'
        cmd = [shutil.which(self.binary()) or self.binary(), 'run', '--rm', '-i', '--name', run_id,
               '--network', 'none' if policy.network != 'allowlist' else 'bridge',
               '--read-only', '--tmpfs', f'{SANDBOX_WORKDIR}:rw,exec,nosuid,nodev,size={max(16, policy.max_file_mb * 2)}m,mode=1777',
               '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m,mode=1777', '-w', SANDBOX_WORKDIR,
               '--memory', mem, '--memory-swap', mem, '--cpus', str(self.settings.docker.get('cpus') or '1'),
               '--pids-limit', str(policy.max_processes), '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--user', '65534:65534', '--log-driver', 'none']
        runtime = self.settings.docker.get('runtime')
        if runtime:
            cmd += ['--runtime', runtime]
        src = RUNNER_PATH.read_text(encoding='utf-8')
        cmd += [self.image(), 'python3', '-I', '-B', '-c', src]
        return cmd

    def on_kill(self, run_id: str) -> None:
        try:
            subprocess.run([shutil.which(self.binary()) or self.binary(), 'kill', run_id],
                           capture_output=True, timeout=15, env=self.launch_env())
        except Exception:
            pass

    def guarantees(self, probe: bool = True) -> List[Dict[str, Any]]:
        applied = self.probe().get('applied', {}) if probe else {}
        rt = self.settings.docker.get('runtime')
        return self._common_guarantees() + [
            {'guarantee': 'Only the container image and the work dir exist in the sandbox; root is read-only',
             'enforced': True, 'how': f'container image {self.image()}, --read-only'},
            {'guarantee': 'Network off unless allowlisted', 'enforced': True, 'how': '--network none'},
            {'guarantee': 'Cannot see, signal or trace server processes', 'enforced': True,
             'how': 'container PID namespace, --cap-drop ALL'},
            {'guarantee': 'CPU, memory, process count limits', 'enforced': True,
             'how': f'--memory, --cpus, --pids-limit (runner rlimits: {bool(applied.get("rlimits"))})'},
            {'guarantee': 'Kernel attack surface reduced', 'enforced': bool(rt),
             'how': f'runtime {rt}' if rt else 'shared host kernel (set sandbox.docker.runtime: runsc for gVisor)'},
        ]


BACKENDS = {'subprocess': SubprocessSandbox, 'bwrap': BwrapSandbox, 'nsjail': NsjailSandbox,
            'docker': DockerSandbox}
#: order 'auto' tries
AUTO_ORDER = ('bwrap', 'nsjail', 'subprocess')

_INSTANCES: Dict[str, Sandbox] = {}
_lock = threading.Lock()


def get_backend(name: Optional[str] = None, settings: Optional[SandboxSettings] = None) -> Sandbox:
    """The backend to use: ``name`` (a tool's choice), else ``sandbox.default_backend``.

    An unavailable backend falls back to ``subprocess`` (logged) unless
    ``sandbox.strict`` is on, in which case it is an error.
    """
    settings = settings or load_settings()
    wanted = (name or settings.default_backend or 'subprocess').lower()
    if wanted == 'auto':
        for cand in AUTO_ORDER:
            b = _instance(cand, settings)
            if b.available()[0]:
                return b
        wanted = 'subprocess'
    if wanted not in BACKENDS:
        raise SandboxUnavailable(f"unknown sandbox backend '{wanted}' (one of {', '.join(BACKENDS)} or auto)")
    b = _instance(wanted, settings)
    ok, why = b.available()
    if ok:
        return b
    if settings.strict:
        raise SandboxUnavailable(f'sandbox backend {wanted} is not available: {why}')
    logger.warning(f'Sandbox backend {wanted} unavailable ({why}); using subprocess')
    return _instance('subprocess', settings)


def _instance(name: str, settings: SandboxSettings) -> Sandbox:
    with _lock:
        b = _INSTANCES.get(name)
        if b is None or b.settings != settings:
            prev = b
            b = BACKENDS[name](settings)
            if prev is not None and prev.settings.__dict__ == settings.__dict__:
                b._probe = prev._probe
            _INSTANCES[name] = b
        return b


def reset() -> None:
    """Forget cached backends, probes and availability (tests, config reload)."""
    with _lock:
        _INSTANCES.clear()
    _AVAIL_CACHE.clear()
