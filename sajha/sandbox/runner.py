"""
SAJHA sandbox runner.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

This file runs in the sandbox, not in the server. It imports only the standard
library and nothing from ``sajha``, because the server's code and configuration
are exactly what the sandbox hides. The server copies it into the per-call work
directory (or passes it with ``python -c`` to a container) and talks to it with
one JSON request on stdin.

Request (one JSON object on stdin)::

    {"op": "python_tool" | "exec" | "probe",
     "files":   {"name": "content", ...},      # written into the work dir first
     "env":     {"NAME": "value", ...},        # the whole environment; nothing inherited
     "limits":  {"cpu_seconds", "memory_mb", "max_file_mb", "max_processes", "max_open_files"},
     "network": {"mode": "none" | "allowlist", "ports": [443], "hosts": ["api.example.com"]},
     "confine": {"userns": bool, "landlock": bool, "seccomp": bool, "strict": bool,
                 "deny_roots": [...], "extra_read_paths": [...]},
     # op == "python_tool"
     "source": "...", "class_name": "...", "arguments": {...}, "tool_config": {...},
     "packages": ["pandas", ...],
     # op == "exec"
     "argv": ["/bin/bash", "script.sh", "a1"]}

Reply. ``exec`` replaces this process with ``argv``: stdout, stderr and the exit
code are the program's own. ``python_tool`` and ``probe`` write one JSON object
to the original stdout; anything the tool prints goes to stderr. Exit code 125
with a line starting ``SAJHA-SANDBOX:`` on stderr means the runner itself failed
(bad request, or a confinement that ``strict`` demanded could not be applied).

Confinement, in order: user + PID (+ network) namespaces and a fork so the work
runs as PID 1 of its own namespace; rlimits; no_new_privs; Landlock (filesystem
read/exec only on the interpreter and system libraries, write only in the work
dir, TCP connect/bind only to allowed ports, no signals or abstract sockets
outside the sandbox); seccomp (no ptrace, io_uring, bpf, mount, unshare, and no
sockets when the network is off). Each step is best effort unless ``strict``;
what was applied is reported back in ``applied``.
"""

import ctypes
import json
import os
import platform
import signal
import struct
import sys
import traceback

APPLIED = {}
_RESULT_FD = None
_STRICT = False


def _die(msg, code=125):
    try:
        os.write(2, ('SAJHA-SANDBOX: ' + msg + '\n').encode('utf-8', 'replace'))
    finally:
        os._exit(code)


def _soft_fail(step, err):
    APPLIED[step] = 'failed: %s' % err
    if _STRICT:
        _die('%s could not be applied (%s) and sandbox.strict is on' % (step, err))


# ── Namespaces ─────────────────────────────────────────────────────────────

def _enter_namespaces(net_off):
    """New user + PID (+ net) namespace, then fork: the child continues as PID 1.

    The parent stays outside, waits, and mirrors the child's exit. It holds no
    secrets and runs no tool code. When the parent is killed (timeout), the child
    gets SIGKILL (PDEATHSIG), and the death of PID 1 kills everything in the
    namespace, including anything the tool forked or daemonised.
    """
    if not hasattr(os, 'unshare'):
        _soft_fail('userns', 'os.unshare needs Python 3.12+')
        return
    uid, gid = os.getuid(), os.getgid()
    flags = os.CLONE_NEWUSER | os.CLONE_NEWPID
    if net_off:
        flags |= os.CLONE_NEWNET
    try:
        os.unshare(flags)
        with open('/proc/self/uid_map', 'w') as f:
            f.write('%d %d 1' % (uid, uid))
        with open('/proc/self/setgroups', 'w') as f:
            f.write('deny')
        with open('/proc/self/gid_map', 'w') as f:
            f.write('%d %d 1' % (gid, gid))
    except OSError as e:
        _soft_fail('userns', e)
        return
    pid = os.fork()
    if pid:
        # Outside parent: forward termination, mirror the exit status.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda s, f: os.kill(pid, signal.SIGKILL))
        while True:
            try:
                _, status = os.waitpid(pid, 0)
                break
            except ChildProcessError:
                os._exit(125)
            except InterruptedError:
                continue
        if os.WIFSIGNALED(status):
            os._exit(128 + os.WTERMSIG(status))
        os._exit(os.WEXITSTATUS(status))
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(1, signal.SIGKILL, 0, 0, 0)  # PR_SET_PDEATHSIG
    except Exception:
        pass
    APPLIED['userns'] = True
    APPLIED['pidns'] = True
    APPLIED['netns'] = bool(net_off)


# ── rlimits ────────────────────────────────────────────────────────────────

def _apply_rlimits(limits):
    try:
        import resource
    except ImportError:
        _soft_fail('rlimits', 'no resource module on this platform')
        return
    done = {}

    def setl(name, soft, hard=None):
        res = getattr(resource, name, None)
        if res is None or soft is None:
            return
        hard = soft if hard is None else hard
        try:
            cur_soft, cur_hard = resource.getrlimit(res)
            if cur_hard != resource.RLIM_INFINITY:
                hard = min(hard, cur_hard)
                soft = min(soft, hard)
            resource.setrlimit(res, (soft, hard))
            done[name] = soft
        except (ValueError, OSError) as e:
            done[name] = 'failed: %s' % e

    mb = 1024 * 1024
    cpu = limits.get('cpu_seconds')
    if cpu:
        setl('RLIMIT_CPU', int(cpu), int(cpu) + 1)
    if limits.get('memory_mb'):
        setl('RLIMIT_AS', int(limits['memory_mb']) * mb)
        setl('RLIMIT_DATA', int(limits['memory_mb']) * mb)
    if limits.get('max_file_mb') is not None:
        setl('RLIMIT_FSIZE', int(limits['max_file_mb']) * mb)
    if limits.get('max_processes'):
        nproc = int(limits['max_processes'])
        if APPLIED.get('userns') is not True:
            # Without a user namespace RLIMIT_NPROC counts every process of this
            # uid on the host, so allow for the ones already running.
            nproc += _uid_process_count()
        setl('RLIMIT_NPROC', nproc)
    setl('RLIMIT_NOFILE', int(limits.get('max_open_files') or 256))
    setl('RLIMIT_CORE', 0)
    APPLIED['rlimits'] = done


def _uid_process_count():
    uid, n = os.getuid(), 0
    try:
        for d in os.listdir('/proc'):
            if d.isdigit():
                try:
                    if os.stat('/proc/' + d).st_uid == uid:
                        n += 1
                except OSError:
                    pass
    except OSError:
        return 0
    return n


# ── no_new_privs ───────────────────────────────────────────────────────────

def _no_new_privs():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), 'prctl')
        APPLIED['no_new_privs'] = True
        return True
    except Exception as e:
        _soft_fail('no_new_privs', e)
        return False


# ── Landlock ───────────────────────────────────────────────────────────────

_LL_CREATE, _LL_ADD_RULE, _LL_RESTRICT = 444, 445, 446  # same number on every arch
_FS_EXECUTE, _FS_WRITE_FILE, _FS_READ_FILE, _FS_READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
_FS_REFER, _FS_TRUNCATE, _FS_IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15
_FS_FILE_ONLY = _FS_EXECUTE | _FS_WRITE_FILE | _FS_READ_FILE | _FS_TRUNCATE | _FS_IOCTL_DEV
_NET_BIND_TCP, _NET_CONNECT_TCP = 1 << 0, 1 << 1
_SCOPE_ABSTRACT_UNIX, _SCOPE_SIGNAL = 1 << 0, 1 << 1

_SYSTEM_READ = ['/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64', '/libx32',
                '/etc/ld.so.cache', '/etc/ld.so.conf', '/etc/ld.so.conf.d', '/etc/localtime',
                '/etc/alternatives', '/etc/ssl', '/etc/ca-certificates', '/etc/pki',
                '/etc/crypto-policies', '/etc/mime.types', '/usr/share/zoneinfo']
_NET_READ = ['/etc/resolv.conf', '/etc/hosts', '/etc/nsswitch.conf', '/etc/gai.conf',
             '/etc/host.conf', '/etc/services', '/etc/protocols']


def _is_within(path, root):
    return path == root or path.startswith(root.rstrip('/') + '/')


def _read_paths(confine, net_on):
    """Directories the sandboxed program may read and execute from."""
    deny = [os.path.realpath(p) for p in confine.get('deny_roots') or []]
    prefixes = {os.path.realpath(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix)}
    cands = list(_SYSTEM_READ) + (list(_NET_READ) if net_on else [])
    cands += list(prefixes) + [os.path.dirname(os.path.realpath(sys.executable))]
    cands += [p for p in sys.path if p and os.path.isdir(p)]
    cands += list(confine.get('extra_read_paths') or [])
    out = []
    for p in cands:
        for q in {p, os.path.realpath(p)}:
            if not os.path.exists(q):
                continue
            # Never a directory that contains a denied root (it would expose it) ...
            if any(_is_within(d, q) for d in deny):
                continue
            # ... and nothing inside one, unless it is the interpreter's own tree
            # (a virtualenv inside the project directory is fine; config is not).
            if any(_is_within(q, d) for d in deny) and not any(_is_within(q, x) for x in prefixes):
                continue
            if q not in out:
                out.append(q)
    return out


def _landlock(confine, network, workdir):
    if not sys.platform.startswith('linux'):
        _soft_fail('landlock', 'Linux only')
        return
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    abi = libc.syscall(_LL_CREATE, None, ctypes.c_size_t(0), ctypes.c_uint32(1))
    if abi < 1:
        _soft_fail('landlock', 'kernel has no Landlock (errno %d)' % ctypes.get_errno())
        return
    fs_all = (1 << 13) - 1
    if abi >= 2:
        fs_all |= _FS_REFER
    if abi >= 3:
        fs_all |= _FS_TRUNCATE
    if abi >= 5:
        fs_all |= _FS_IOCTL_DEV
    net_handled = (_NET_BIND_TCP | _NET_CONNECT_TCP) if abi >= 4 else 0
    scoped = (_SCOPE_ABSTRACT_UNIX | _SCOPE_SIGNAL) if abi >= 6 else 0
    if abi >= 6:
        attr, size = struct.pack('QQQ', fs_all, net_handled, scoped), 24
    elif abi >= 4:
        attr, size = struct.pack('QQ', fs_all, net_handled), 16
    else:
        attr, size = struct.pack('Q', fs_all), 8
    buf = ctypes.create_string_buffer(attr, size)
    rfd = libc.syscall(_LL_CREATE, buf, ctypes.c_size_t(size), ctypes.c_uint32(0))
    if rfd < 0:
        _soft_fail('landlock', 'create_ruleset errno %d' % ctypes.get_errno())
        return

    def allow_path(path, access):
        try:
            fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        except OSError:
            return False
        try:
            if not os.path.isdir(path):
                access &= _FS_FILE_ONLY
            access &= fs_all
            rule = ctypes.create_string_buffer(struct.pack('=Qi', access, fd), 12)
            return libc.syscall(_LL_ADD_RULE, ctypes.c_int(rfd), ctypes.c_int(1), rule,
                                ctypes.c_uint32(0)) == 0
        finally:
            os.close(fd)

    read_x = _FS_READ_FILE | _FS_READ_DIR | _FS_EXECUTE
    net_on = network.get('mode') == 'allowlist'
    readable = _read_paths(confine, net_on)
    for p in readable:
        allow_path(p, read_x)
    if net_on and os.path.exists('/etc/resolv.conf'):
        allow_path(os.path.realpath('/etc/resolv.conf'), _FS_READ_FILE)
    for dev in ('/dev/null', '/dev/zero', '/dev/urandom', '/dev/random', '/dev/full'):
        allow_path(dev, _FS_READ_FILE | _FS_WRITE_FILE | _FS_TRUNCATE)
    if not allow_path(workdir, fs_all):
        _soft_fail('landlock', 'could not allow the work directory')
        os.close(rfd)
        return
    ports = []
    if net_handled and net_on:
        for port in network.get('ports') or []:
            rule = ctypes.create_string_buffer(struct.pack('QQ', _NET_CONNECT_TCP, int(port)), 16)
            if libc.syscall(_LL_ADD_RULE, ctypes.c_int(rfd), ctypes.c_int(2), rule,
                            ctypes.c_uint32(0)) == 0:
                ports.append(int(port))
    if libc.syscall(_LL_RESTRICT, ctypes.c_int(rfd), ctypes.c_uint32(0)) != 0:
        _soft_fail('landlock', 'restrict_self errno %d' % ctypes.get_errno())
        os.close(rfd)
        return
    os.close(rfd)
    APPLIED['landlock'] = {'abi': abi, 'filesystem': True,
                           'tcp': bool(net_handled), 'tcp_ports': ports,
                           'signals_and_abstract_sockets': bool(scoped),
                           'readable': readable}


# ── seccomp ────────────────────────────────────────────────────────────────

_SECCOMP = {
    # arch: (AUDIT_ARCH, socket nr, {blocked syscall numbers})
    'x86_64': (0xC000003E, 41, {
        101, 310, 311,          # ptrace, process_vm_readv/writev
        425, 426, 427,          # io_uring_setup/enter/register (bypass seccomp)
        321, 298, 323,          # bpf, perf_event_open, userfaultfd
        248, 249, 250,          # add_key, request_key, keyctl
        165, 166, 155, 161,     # mount, umount2, pivot_root, chroot
        272, 308,               # unshare, setns
        246, 320, 175, 313,     # kexec_load, kexec_file_load, init/finit_module
    }),
    'aarch64': (0xC00000B7, 198, {
        117, 270, 271, 425, 426, 427, 280, 241, 282, 217, 218, 219,
        40, 39, 41, 51, 97, 268, 104, 294, 105, 273,
    }),
}


def _seccomp(network):
    machine = platform.machine().lower()
    machine = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(machine, machine)
    if not sys.platform.startswith('linux') or machine not in _SECCOMP:
        _soft_fail('seccomp', 'no filter for %s/%s' % (sys.platform, machine))
        return
    arch, socket_nr, blocked = _SECCOMP[machine]
    allowed_families = [2, 10, 16] if network.get('mode') == 'allowlist' else []  # INET, INET6, NETLINK
    LD, JEQ, JGE, RET = 0x20, 0x15, 0x35, 0x06
    ALLOW, EPERM, EACCES = 0x7FFF0000, 0x00050000 | 1, 0x00050000 | 13
    # Assemble with symbolic jump targets, then resolve to relative offsets.
    prog = [('LD', 4), ('JEQ', arch, 'next', 'deny'), ('LD', 0)]
    if machine == 'x86_64':
        prog.append(('JGE', 0x40000000, 'deny', 'next'))  # x32 ABI
    for nr in sorted(blocked):
        prog.append(('JEQ', nr, 'deny', 'next'))
    prog.append(('JEQ', socket_nr, 'next', 'allow'))
    prog.append(('LD', 16))  # args[0] (domain), low 32 bits
    for fam in allowed_families:
        prog.append(('JEQ', fam, 'allow', 'next'))
    prog.append(('RET', EACCES))
    labels = {'allow': len(prog), 'deny': len(prog) + 1}
    prog += [('RET', ALLOW), ('RET', EPERM)]
    raw = b''
    for i, ins in enumerate(prog):
        if ins[0] == 'LD':
            raw += struct.pack('HBBI', LD, 0, 0, ins[1])
        elif ins[0] == 'RET':
            raw += struct.pack('HBBI', RET, 0, 0, ins[1])
        else:
            def off(t):
                return 0 if t == 'next' else labels[t] - i - 1
            raw += struct.pack('HBBI', JEQ if ins[0] == 'JEQ' else JGE, off(ins[2]), off(ins[3]), ins[1])
    n = len(prog)
    filt = ctypes.create_string_buffer(raw, len(raw))

    class SockFprog(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ushort), ('filter', ctypes.c_void_p)]

    fprog = SockFprog(n, ctypes.cast(filt, ctypes.c_void_p))
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_SECCOMP, SECCOMP_MODE_FILTER
    if libc.prctl(22, 2, ctypes.byref(fprog), 0, 0) != 0:
        _soft_fail('seccomp', 'prctl errno %d' % ctypes.get_errno())
        return
    APPLIED['seccomp'] = {'arch': machine, 'sockets': 'inet only' if allowed_families else 'none'}


# ── Python tool support ────────────────────────────────────────────────────

def _install_shims():
    """A minimal ``sajha.tools.base_mcp_tool`` so a Studio module can be exec'd
    without the server package (which the sandbox cannot see)."""
    import logging
    import types

    class BaseMCPTool(object):
        def __init__(self, config=None):
            self.config = dict(config or {})
            self.logger = logging.getLogger('sajha.sandboxed.%s' % self.config.get('name', 'tool'))

        name = property(lambda self: self.config.get('name', 'unknown'))
        description = property(lambda self: self.config.get('description', ''))
        version = property(lambda self: self.config.get('version', '1.0.0'))
        enabled = property(lambda self: self.config.get('enabled', True))

        def get_input_schema(self):
            return self.config.get('inputSchema') or {'type': 'object'}

        def get_output_schema(self):
            return self.config.get('outputSchema') or {}

        def execute(self, arguments):
            raise NotImplementedError

    def sajhamcptool(*a, **k):
        if a and callable(a[0]) and not k:
            return a[0]
        return lambda f: f

    mods = {}
    for name in ('sajha', 'sajha.tools', 'sajha.tools.base_mcp_tool', 'sajha.studio'):
        m = types.ModuleType(name)
        m.__path__ = []
        mods[name] = m
    mods['sajha.tools.base_mcp_tool'].BaseMCPTool = BaseMCPTool
    mods['sajha.studio'].sajhamcptool = sajhamcptool
    mods['sajha'].tools = mods['sajha.tools']
    mods['sajha'].studio = mods['sajha.studio']
    mods['sajha.tools'].base_mcp_tool = mods['sajha.tools.base_mcp_tool']
    sys.modules.update(mods)
    return BaseMCPTool


def _gated_builtins(packages):
    """Builtins for the tool module whose ``__import__`` admits only the stdlib and
    the declared packages. Import hygiene, not a security boundary (the OS
    confinement is): it makes an undeclared dependency fail loudly. Modules the
    tool imports keep the real ``__import__`` for their own dependencies."""
    import builtins
    allowed = set(packages) | set(getattr(sys, 'stdlib_module_names', ())) | {'sajha'}
    real = builtins.__import__

    def gated(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name.split('.')[0] not in allowed:
            raise ImportError("package '%s' is not in this tool's sandbox.packages" % name.split('.')[0])
        return real(name, globals, locals, fromlist, level)

    table = dict(vars(builtins))
    table['__import__'] = gated
    return table


def _gate_hosts(hosts, ports):
    """Python tools with ``network: allowlist``: resolve and connect only to the
    allowlisted hosts. The kernel enforces the ports (Landlock) and, under the
    namespace backends, nothing else; this adds the host names for Python code."""
    import socket
    hosts = set(h.lower() for h in hosts)
    resolved = set(hosts)
    real_gai, real_connect = socket.getaddrinfo, socket.socket.connect

    def getaddrinfo(host, *a, **k):
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name.lower() not in resolved:
            raise OSError('host %s is not in sandbox.allow_hosts' % name)
        res = real_gai(host, *a, **k)
        for r in res:
            resolved.add(str(r[4][0]).lower())
        return res

    def connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            if str(address[0]).lower() not in resolved:
                raise OSError('address %s is not in sandbox.allow_hosts' % (address[0],))
            if ports and int(address[1]) not in ports:
                raise OSError('port %s is not in sandbox.allow_hosts' % (address[1],))
        return real_connect(self, address)

    socket.getaddrinfo = getaddrinfo
    socket.socket.connect = connect


def _write_result(obj):
    data = json.dumps(obj, default=str).encode('utf-8')
    view = memoryview(data)
    while view:
        n = os.write(_RESULT_FD, view)
        view = view[n:]


def _run_python_tool(req):
    base = _install_shims()
    pkgs = req.get('packages') or []
    import builtins
    ns = {'__name__': 'sajha_sandboxed_tool', '__file__': 'tool.py',
          '__builtins__': _gated_builtins(pkgs) if pkgs else builtins}
    try:
        exec(compile(req['source'], 'tool.py', 'exec'), ns)
        cls = ns.get(req.get('class_name') or '')
        if cls is None:
            cands = [v for v in ns.values() if isinstance(v, type) and issubclass(v, base) and v is not base]
            if not cands:
                raise RuntimeError('no tool class found in the module')
            cls = cands[0]
        tool = cls(req.get('tool_config') or {})
        result = tool.execute(req.get('arguments') or {})
        if hasattr(result, '__await__'):
            import asyncio
            result = asyncio.run(result)
        _write_result({'ok': True, 'result': result, 'applied': APPLIED})
    except BaseException as e:  # noqa: B902 — report everything, including SystemExit
        _write_result({'ok': False, 'error_type': type(e).__name__, 'error': str(e),
                       'traceback': traceback.format_exc(limit=8), 'applied': APPLIED})


# ── main ───────────────────────────────────────────────────────────────────

def main():
    global _RESULT_FD, _STRICT
    try:
        req = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    except Exception as e:
        _die('bad request: %s' % e)
    workdir = os.getcwd()
    for name, content in (req.get('files') or {}).items():
        if not name or '/' in name or name.startswith('.'):
            _die('bad file name %r' % name)
        with open(os.path.join(workdir, name), 'w', encoding='utf-8') as f:
            f.write(content)
        if name.endswith(('.sh', '.py', '.pl', '.rb', '.js')):
            os.chmod(os.path.join(workdir, name), 0o700)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)

    confine = req.get('confine') or {}
    network = req.get('network') or {'mode': 'none'}
    _STRICT = bool(confine.get('strict'))
    net_off = network.get('mode') != 'allowlist'

    if confine.get('userns'):
        _enter_namespaces(net_off)
    _apply_rlimits(req.get('limits') or {})
    if confine.get('landlock') or confine.get('seccomp'):
        _no_new_privs()
    if confine.get('landlock'):
        _landlock(confine, network, workdir)
    if confine.get('seccomp'):
        _seccomp(network)

    os.environ.clear()
    os.environ.update({str(k): str(v) for k, v in (req.get('env') or {}).items()})

    op = req.get('op')
    if op == 'exec':
        argv = req.get('argv') or []
        if not argv:
            _die('exec needs argv')
        sys.stdout.flush()
        try:
            os.execvpe(argv[0], argv, dict(os.environ))
        except OSError as e:
            _die('cannot execute %s: %s' % (argv[0], e), 127)
    _RESULT_FD = os.dup(1)
    os.dup2(2, 1)  # the tool's prints go to stderr; stdout carries only the result
    if op == 'python_tool':
        if network.get('mode') == 'allowlist' and network.get('hosts'):
            _gate_hosts(network.get('hosts'), network.get('ports') or [])
        _run_python_tool(req)
    elif op == 'probe':
        _write_result({'ok': True, 'result': {'python': sys.version.split()[0], 'uid': os.getuid(),
                                              'pid': os.getpid()}, 'applied': APPLIED})
    else:
        _die('unknown op %r' % op)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == '__main__':
    main()
