# Sandbox

This document owns how SAJHA runs code it did not ship: the threat model, the options
considered, the design chosen, what each backend guarantees, and what it does not. The
configuration keys are listed in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#sandbox); the
security posture of the rest of the server is in the
[Security Model](../security/Security%20Model.md). The code is `sajha/sandbox/`.

## 1. The problem

MCP Studio turns user input into tools. Two creators accept arbitrary code:

- the **Python code creator** (`sajha/studio/code_generator.py`) writes the body of a
  `@sajhamcptool` function into `sajha/tools/impl/studio_<name>.py`;
- the **script creator** (`sajha/studio/script_tool_generator.py`) saves a shell, Python,
  Node, Perl, Ruby or PowerShell script to `config/scripts/` with a wrapper module.

The admin shell (`sajha/core/shell_executor.py`, `POST /api/shell/python` and
`/api/shell/bash`) runs code typed into a request.

Before the sandbox, the registry imported the Python module into the server and the
script wrapper ran the script with `os.environ.copy()` and the server's working
directory. A deployed tool therefore ran with every privilege the server has.

## 2. Threat model

**Who is the attacker.** Whoever writes the code: a Studio user (an admin, but not
necessarily the operator of the host), a compromised admin account, or a tool imported
from someone else. Also an LLM or MCP client that controls a tool's *arguments* and uses
them to steer a careless tool (a path, a URL, a command fragment).

**What they want**, in order of damage:

| Asset | Examples |
|---|---|
| Server secrets | the JWT/session secrets (`data/secrets/`, `SAJHA_*` environment variables), the OAuth signing key (`data/oauth/`), provider API keys in the environment |
| Server data | the database (`data/sajha.db`), `config/` (users, API keys, tool configs), other tools' code |
| The host | files of the server's Unix user (`~/.ssh`, cloud credentials), other processes of that user (`/proc/<pid>/environ`, `ptrace`, signals), the Docker socket |
| The network | the internal network the server can reach, metadata endpoints, exfiltration |
| Availability | fork bombs, memory exhaustion, infinite loops, filling the disk or the log with output |

**In scope:** everything a tool can do from inside its own process tree.
**Out of scope:** kernel exploits against the shared kernel (use the `docker` backend with
gVisor, or a VM, if that matters); an attacker who can already write `sajha/` or
`config/tools/` (that is code execution in the server by definition); built-in tools
(shipped with SAJHA, reviewed, and trusted).

## 3. Options considered

| Option | Isolation | Cost per call | Runs native wheels and scripts | Availability | Verdict |
|---|---|---|---|---|---|
| In-process `exec` with a restricted namespace | None (Python cannot sandbox Python) | ~0 | yes | everywhere | rejected: the old behaviour |
| Subprocess with a clean environment, temp dir, rlimits | process boundary, resource limits; no file or network confinement on its own | tens of ms | yes | every POSIX host | **default backend**, strengthened below |
| …plus Landlock + seccomp + user/PID/net namespaces, applied by a small runner | filesystem allowlist, no sockets, own PID space | same | yes | Linux; each layer reported if missing | **built into the subprocess backend** |
| bubblewrap (`bwrap`) | namespaces and a new root with only what is bound | tens of ms | yes | Linux, if installed and user namespaces are allowed | **backend `bwrap`** |
| nsjail | as bwrap, plus its own rlimits | tens of ms | yes | Linux, if installed | **backend `nsjail`** |
| firejail | namespaces via a setuid binary with a large profile language | tens of ms | yes | Linux, if installed | not implemented: a setuid helper adds attack surface and bwrap covers the same ground |
| Docker/Podman container per call | namespaces, cgroups, capabilities, read-only root, image-defined filesystem | hundreds of ms | only what the image has | where a daemon (or rootless Podman) runs | **backend `docker`** |
| Warm container pool | as above | low | as above | as above | deferred: needs state reset between calls; a fresh container per call is simpler to reason about |
| gVisor (`runsc`) | user-space kernel: kernel exploits mostly contained | higher | as image | Linux with runsc installed | **supported** as `sandbox.docker.runtime: runsc` |
| WASM (wasmtime + a Python build, or Pyodide on the server) | strong (no syscalls at all) | startup cost | pure Python only: no numpy/pandas wheels, no shell scripts | needs a WASI Python build | not chosen: it cannot run script tools or common data libraries; a possible future backend for pure-Python tools |

## 4. Design

### One interface, several backends

`sajha/sandbox/backends.py` defines `Sandbox` with `available()`, `run(request, policy)`,
`probe()` and `guarantees()`. Every backend launches the same standalone program,
`sajha/sandbox/runner.py`, and differs only in *where* it launches it:

| Backend | Launch |
|---|---|
| `subprocess` (default) | `python -I -B runner.py` in a fresh temp directory |
| `bwrap` | the same inside `bwrap --unshare-all --die-with-parent`, with a new root that holds only read-only binds of system libraries and the interpreter, and the temp directory at `/work` |
| `nsjail` | the same inside `nsjail --mode o` with equivalent mounts and nsjail's rlimits |
| `docker` | `docker run --rm -i --network none --read-only --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 --memory … --pids-limit …` on `sandbox.docker.image`, runner passed with `python3 -c` |

`sandbox.default_backend` picks one (`auto` tries bwrap, nsjail, then subprocess). A tool
may name another in its policy. An unavailable backend falls back to `subprocess` with a
warning, or fails if `sandbox.strict` is on.

### The runner protocol

The runner imports only the standard library and nothing from `sajha` (the server's code
is exactly what it must not see). The server writes one JSON request to its stdin:

```json
{"op": "python_tool" | "exec" | "probe",
 "files": {"script.sh": "..."}, "env": {"PATH": "..."},
 "limits": {"cpu_seconds": 30, "memory_mb": 512, "max_file_mb": 64, "max_processes": 64},
 "network": {"mode": "none" | "allowlist", "ports": [443], "hosts": ["api.example.com"]},
 "confine": {"userns": true, "landlock": true, "seccomp": true, "strict": false, "deny_roots": ["..."]},
 "source": "...", "class_name": "...", "arguments": {}, "tool_config": {}}
```

- `exec` runs `argv` with `execvpe` after confinement: stdout, stderr and the exit code
  are the program's own (script tools, the shell).
- `python_tool` executes the Studio module's source with a stub
  `sajha.tools.base_mcp_tool.BaseMCPTool`, instantiates the class, calls `execute`, and
  writes `{"ok": true, "result": ...}` or `{"ok": false, "error_type", "error",
  "traceback"}` to the original stdout. The tool's own prints go to stderr, so they
  cannot corrupt the result.
- `probe` reports what confinement was actually applied.

Exit code 125 with `SAJHA-SANDBOX:` on stderr means the runner itself failed.

The server side (`Sandbox.run`) enforces what the runner cannot: the **wall-clock
timeout** (SIGKILL to the process group; `docker kill` for containers), the **output
cap** (both streams; the run is killed when exceeded) and **cleanup** of the temp
directory.

### Confinement the runner applies (Linux)

In order, each reported in `applied`:

1. **Namespaces** (subprocess backend): `unshare(CLONE_NEWUSER | CLONE_NEWPID [| CLONE_NEWNET])`,
   same uid mapped, then a fork so the work runs as PID 1 of its own PID namespace with
   `PR_SET_PDEATHSIG`. When the run ends or is killed, everything it forked dies with it,
   and `RLIMIT_NPROC` counts only the sandbox's processes. The network namespace (no
   interfaces but a down loopback) is used when the network is off.
2. **rlimits**: `RLIMIT_CPU`, `RLIMIT_AS` and `RLIMIT_DATA` (memory), `RLIMIT_FSIZE`,
   `RLIMIT_NPROC`, `RLIMIT_NOFILE`, `RLIMIT_CORE=0`.
3. **no_new_privs.**
4. **Landlock** (Linux 5.13+): read and execute only system library directories
   (`/usr`, `/lib*`, `/bin`, a few `/etc` files such as `ld.so.cache`, `localtime`,
   `ssl`), the interpreter's prefixes and its isolated `sys.path`; read-write only the
   work directory and `/dev/null`-style devices. Never a directory that contains the
   project root, the server's working directory, the server user's home or the
   database directory, and nothing inside them except the interpreter's own tree (a
   virtualenv inside the project is fine; `config/` is not). With ABI 4+ (Linux 6.7+),
   TCP connect and bind only to allowlisted ports. With ABI 6+ (Linux 6.12+), no signals
   to and no abstract Unix sockets of processes outside the sandbox.
5. **seccomp** (x86_64 and aarch64): `ptrace`, `process_vm_readv/writev`, `io_uring_*`,
   `bpf`, `perf_event_open`, `userfaultfd`, keyring calls, `mount`, `umount2`,
   `pivot_root`, `chroot`, `unshare`, `setns`, module and kexec loading fail with EPERM;
   `socket()` fails for every family when the network is off (including `AF_UNIX`, so a
   reachable Docker socket is useless) and for everything but IPv4, IPv6 and netlink when
   it is allowlisted. 32-bit and x32 system calls are refused.

Every step is best effort: if the kernel lacks it, the runner continues and reports it,
unless `sandbox.strict` is on, in which case it refuses to run.

### What each backend guarantees

`GET /api/sandbox/status` (admin) answers this for the running host from a live probe;
the table below is what each layer gives when present.

| Guarantee | subprocess (Linux) | subprocess (macOS) | subprocess (Windows) | bwrap | nsjail | docker |
|---|---|---|---|---|---|---|
| Server environment not inherited | yes | yes | yes | yes | yes | yes |
| Fresh temp work dir, removed after | yes | yes | yes | yes | yes | yes (tmpfs) |
| Wall-clock timeout, output cap | yes | yes | yes | yes | yes | yes |
| CPU, memory, file size, process limits | rlimits (process limit per user namespace) | rlimits; memory (`RLIMIT_AS`) is not enforced by macOS | no | rlimits | nsjail rlimits | cgroups and rlimits |
| Cannot read server files | Landlock | **no** | **no** | not mounted, plus Landlock | not mounted | not in the image, plus Landlock if the container allows it |
| Cannot write outside the work dir | Landlock | **no** | **no** | read-only binds | read-only binds | read-only root |
| Network off | network namespace and seccomp | **no** | **no** | network namespace | network namespace | `--network none` |
| Cannot see, signal or trace server processes | PID namespace, Landlock scope, seccomp | **no** | **no** | PID namespace | PID namespace | container PID namespace, no capabilities |
| Children killed with the sandbox | PID namespace | process group only | no | yes | yes | yes |
| Kernel attack surface reduced | seccomp blocklist | no | no | seccomp blocklist | nsjail seccomp if configured | gVisor when `runtime: runsc` |

On Linux the `subprocess` backend needs unprivileged user namespaces for its namespace
layer (some distributions restrict them, for example Ubuntu's
`kernel.apparmor_restrict_unprivileged_userns`); without them it still has Landlock,
seccomp and rlimits, and `RLIMIT_NPROC` is then raised by the number of processes the
user already runs. `bwrap` needs user namespaces too. `nsjail` support follows nsjail's
documented flags and is not exercised by the test suite unless nsjail is installed.

### Network allowlist

`"network": "allowlist"` with `"allow_hosts": ["api.example.com:443"]` (port defaults to
443). What is enforced, and by what:

- **Ports** by the kernel (Landlock TCP rules) on the subprocess and bwrap backends.
- **Host names** for Python tools by the runner, which wraps `socket.getaddrinfo` and
  `socket.connect` so only the listed names (and the addresses they resolve to) can be
  reached. This is a library-level check: code that issues raw system calls through
  `ctypes` can reach any address on an allowed port. Script tools get the port rule only.
- **docker** uses the default bridge network for allowlisted tools; host names and ports
  are not enforced by Docker itself (put an egress proxy in front if that matters).

UDP is not filtered when the network is allowlisted.

## 5. Policy

A tool's JSON config may carry a `sandbox` block; unset keys take the administrator's
`sandbox.defaults`, and every number is capped by `sandbox.max` (`sajha/sandbox/policy.py`):

```json
"sandbox": {
  "backend": "bwrap",
  "network": "allowlist",
  "allow_hosts": ["api.weather.example:443"],
  "timeout_seconds": 20, "cpu_seconds": 20, "memory_mb": 256,
  "max_output_bytes": 65536, "max_processes": 16, "max_file_mb": 8,
  "packages": ["requests"],
  "secrets": ["WEATHER_API_KEY"],
  "env": {"UNITS": "metric"}
}
```

- **Secrets** are the only way a server environment value reaches a sandbox: by name,
  only if the name is in `sandbox.secrets_allowlist`, never a `SAJHA_*` variable, read at
  call time.
- **env** holds literal, non-secret values. `HOME`, `TMPDIR`, `LD_PRELOAD`, `PYTHONPATH`
  and similar are reserved.
- **packages** (Python tools): when set, the tool's own `import` statements may name only
  the standard library and these packages. It is import hygiene that makes an undeclared
  dependency fail loudly, not a boundary; the backend decides what is installed (the
  server's interpreter for subprocess/bwrap/nsjail, the image for docker).
- Script tools: the script config's `timeout_seconds` and `environment_vars` feed the
  policy when the `sandbox` block does not set them. `working_directory` is ignored: a
  sandboxed script always runs in its temp work dir.

Studio writes `"sandbox": {"network": "none"}` (plus the timeout for scripts) into every
Python code and script tool it generates, and both creator pages show the policy and
the active backend's guarantees before you deploy.

## 6. What is sandboxed

`sajha/sandbox/tools.py::classify` decides when the registry loads a tool
(`sajha/tools/tools_registry.py::register_tool_from_dict`):

| Tool | Where it runs |
|---|---|
| Studio Python code tool (`implementation` in `sajha.tools.impl.studio_*`) | sandbox; the module is parsed for its schemas but never imported into the server |
| Studio script tool (a `script` block, a `*_script_tool` implementation, or a legacy object `implementation`) | sandbox; the wrapper module is not imported |
| Any tool whose config says `"sandbox": {"enabled": true}` | sandbox (its module source runs in the runner) |
| Built-in tools, composites, and Studio's template creators (REST, DB query, Power BI, LiveLink, SharePoint, OLAP) | in-process: their code is SAJHA's template, the user supplies only configuration, and they need the server's connections and credentials |
| Admin shell (`/api/shell/python`, `/api/shell/bash`) | sandbox, after the existing import and command filters |

`sandbox.enforce_for_generated_tools: true` (the default) sandboxes Studio code and
script tools whatever their config says. Set it to `false` to load them in-process again
(the old behaviour) unless their config opts in. The hot-reload watchers never import a
`studio_*` or `*_script_tool` module either.

The tool contract does not change for callers (MCP, REST, A2A, Ask SAJHA): same name,
schemas and result shape. A Python tool's exception is raised as `SandboxToolError`
(`"ValueError: message"`); a timeout, an output overflow or a killed run is raised as
`SandboxTimeout`, `SandboxOutputLimit` or `SandboxError`, and the caller sees an ordinary
tool error. A script tool returns `{stdout, stderr, exit_code, success}` as before, with
`exit_code` -1 for a timeout, -2 for a missing script, -3 for a sandbox error and -4 for
an output overflow.

What a sandboxed Python tool cannot do any more: import `sajha` (only `BaseMCPTool` and
`sajhamcptool` stubs exist), read files outside its work dir, keep state between calls on
disk, or reach the network unless its policy allowlists it.

## 7. Status

- `GET /health` includes `sandbox`: the active backend and whether generated tools are
  enforced (no probe).
- `GET /api/sandbox/status` (admin): every backend's availability, the active backend's
  guarantees from a live probe, defaults and caps (`sajha/routes/sandbox_routes.py`).
- `GET /api/shell/capabilities` names the backend the shell uses.

## 8. Tests

`tests/test_sandbox.py` runs each escape attempt under every backend installed on the
host and skips the others, naming why: reading `/etc/passwd`, the server's
`config/application.yml` and source, the user's home; listing the project; seeing
`SAJHA_JWT_SECRET` in the environment or in `/proc/<server>/environ`; writing to `/tmp`
or the project; signalling the server; a Python fork loop and the bash fork bomb (and
that nothing survives); a 2 GB allocation; an infinite loop (timeout) and a busy loop
(CPU limit); unbounded output; a 50 MB file; TCP to a listener on the host's loopback and
to the internet; a Unix socket on the host. It also checks normal results, the network
allowlist (listed port reachable, others not, unlisted host names refused), the policy
caps and secret rules, the registry wiring for Studio Python and script tools, and the
shell.

## 9. Limits and future work

- The `subprocess` and namespace backends share the host kernel; a kernel exploit is out
  of scope. Use `docker` with `runtime: runsc`, or run SAJHA itself in a VM.
- Host-name allowlisting is library-level (section 4); no egress proxy is shipped.
- macOS and Windows get process separation, a clean environment, the timeout and the
  output cap only; run SAJHA on Linux (or in a container) where user code matters.
- A container per call costs hundreds of milliseconds; a warm pool and a WASM backend
  for pure-Python tools are possible additions.
- Template creators (REST, DB query, ...) run in-process by design; a hand-edited
  generated module is trusted like any other code under `sajha/tools/impl/`.
