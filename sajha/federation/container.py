"""
SAJHA MCP Server — a container per federated stdio upstream.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A stdio upstream (``transport: stdio``, allowed by ``federation.allow_stdio``) runs as

* ``isolation: container`` — its own long-lived container, launched through the sandbox's
  ``docker`` backend (``sandbox.docker.binary``, ``sandbox.docker.runtime``, the backend's launch
  environment) with the sandbox's network policy and limits: ``--network none`` unless the
  upstream's ``container.network`` is ``allowlist``, a read-only root file system, ``/tmp`` a
  small tmpfs, memory, CPU and process limits (capped by ``sandbox.max``), every capability
  dropped, ``no-new-privileges``, the ``nobody`` user, and only the host folders listed in
  ``container.mounts``, each mounted read-only. One container per connection; it is removed when
  the connection closes and a fresh one is started by the connection's reconnect loop, which
  backs off from 1 s to 60 s (``sajha/federation/connection.py``);
* ``isolation: none`` — a plain subprocess of SAJHA, as before. Only when set explicitly, and
  then with the warning notice ``federation.stdio_unconfined:<upstream>``.

Left unset, ``isolation`` means ``container`` when docker answers (``docker info``); when it does
not, the upstream is refused (state ``error``, notice ``federation.stdio_isolation:<upstream>``)
rather than started unconfined.

Per upstream::

    isolation: container            # container | none; unset: container when docker is available
    container:
      image: ghcr.io/acme/mcp-fetch:1.4     # default federation.container.image, else sandbox.docker.image
      mounts: ["/srv/mcp/data:/data"]       # host:container, always read-only; never SAJHA's own folders
      memory_mb: 512                        # default sandbox.defaults.memory_mb, capped by sandbox.max
      cpus: "1"                             # default sandbox.docker.cpus
      max_processes: 64                     # default sandbox.defaults.max_processes, capped by sandbox.max
      network: none                         # none | allowlist (then allow_hosts, as a sandbox block)
      allow_hosts: ["api.example.com:443"]
      user: "65534:65534"                   # default nobody
      tmpfs_mb: 64                          # size of the writable /tmp (HOME is /tmp)

The command and args run inside the image (``command`` is the executable there, given to docker as
``--entrypoint`` so the image's own entrypoint does not wrap it); ``env`` and
``env_refs`` are passed by name (``-e NAME``), so a secret never appears on the docker command
line. ``cwd`` becomes the container's working directory. Design: docs/architecture/Federation.md.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ISOLATIONS = ('container', 'none')
CONTAINER_KEYS = ('image', 'mounts', 'memory_mb', 'cpus', 'max_processes', 'network', 'allow_hosts', 'user',
                  'tmpfs_mb')
LABEL = 'sajha.federation.upstream'
_IMAGE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$')
_USER_RE = re.compile(r'^[0-9]{1,10}(:[0-9]{1,10})?$')
_CPUS_RE = re.compile(r'^[0-9]{1,3}(\.[0-9]{1,3})?$')
_DOCKER_CACHE: Dict[str, Tuple[float, bool, str]] = {}
_DOCKER_TTL = 60.0
_lock = threading.Lock()


class IsolationError(PermissionError):
    """A stdio upstream that may not start the way it is configured."""


# ── configuration ────────────────────────────────────────────────────

def _cfg_error(msg: str):
    from sajha.federation.config import ConfigError
    return ConfigError(msg)


def parse_mount(item: Any) -> Tuple[str, str]:
    """``"host:container"`` or ``{"source": host, "target": container}`` -> (host, container)."""
    if isinstance(item, dict):
        src, dst = str(item.get('source') or ''), str(item.get('target') or item.get('source') or '')
    else:
        text = str(item or '')
        if text.endswith(':ro'):
            text = text[:-3]
        src, _, dst = text.partition(':')
        dst = dst or src
    src, dst = src.strip(), dst.strip()
    if not src.startswith('/') or not dst.startswith('/'):
        raise _cfg_error(f'container.mounts: {item!r} must be host:container with absolute paths')
    if any(c in src + dst for c in (',', '\n', '\0')) or '..' in src.split('/') + dst.split('/'):
        raise _cfg_error(f'container.mounts: {item!r} is not a plain path')
    return os.path.normpath(src), os.path.normpath(dst)


def validate(transport: str, isolation: str, block: Dict[str, Any]) -> None:
    """Checks ``isolation`` and ``container`` of one upstream (UpstreamConfig.validate calls this)."""
    if isolation and isolation not in ISOLATIONS:
        raise _cfg_error(f'isolation must be one of {", ".join(ISOLATIONS)}')
    if transport != 'stdio':
        if isolation or block:
            raise _cfg_error('isolation and container apply to stdio upstreams only')
        return
    if not block:
        return
    if not isinstance(block, dict):
        raise _cfg_error('container must be an object')
    if isolation == 'none':
        raise _cfg_error('container settings need isolation: container (or isolation unset)')
    unknown = set(block) - set(CONTAINER_KEYS)
    if unknown:
        raise _cfg_error(f'container: unknown field(s): {", ".join(sorted(unknown))}')
    image = block.get('image')
    if image not in (None, '') and not _IMAGE_RE.match(str(image)):
        raise _cfg_error('container.image is not an image reference')
    mounts = block.get('mounts') or []
    if not isinstance(mounts, list):
        raise _cfg_error('container.mounts must be a list')
    for m in mounts:
        parse_mount(m)
    for key in ('memory_mb', 'max_processes', 'tmpfs_mb'):
        if block.get(key) not in (None, ''):
            try:
                if int(block[key]) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                raise _cfg_error(f'container.{key} must be a positive integer')
    if block.get('cpus') not in (None, '') and not _CPUS_RE.match(str(block['cpus'])):
        raise _cfg_error('container.cpus must be a number such as "1" or "0.5"')
    if block.get('user') not in (None, '') and not _USER_RE.match(str(block['user'])):
        raise _cfg_error('container.user must be uid or uid:gid (numbers)')
    if block.get('user') not in (None, '') and str(block['user']).split(':')[0] == '0':
        raise _cfg_error('container.user must not be root (0)')
    from sajha.sandbox import PolicyError, policy_from_config
    try:
        policy_from_config({'network': block.get('network') or 'none', 'allow_hosts': block.get('allow_hosts') or []})
    except PolicyError as e:
        raise _cfg_error(f'container: {e}')


# ── docker ───────────────────────────────────────────────────────────

def _sandbox():
    """The sandbox's docker backend object (its binary, runtime and launch environment), whether or
    not it is the sandbox's active backend."""
    from sajha.sandbox import BACKENDS, load_settings
    return BACKENDS['docker'](load_settings())


def docker_available(refresh: bool = False) -> Tuple[bool, str]:
    """Whether the docker (or podman) daemon answers ``info``; cached for a minute."""
    sb = _sandbox()
    exe = shutil.which(sb.binary())
    if not exe:
        return False, f'{sb.binary()} is not installed'
    now = time.monotonic()
    with _lock:
        hit = _DOCKER_CACHE.get(exe)
        if hit and not refresh and now - hit[0] < _DOCKER_TTL:
            return hit[1], hit[2]
    try:
        r = subprocess.run([exe, 'info', '--format', '{{.ServerVersion}}'], capture_output=True, text=True,
                           timeout=15, env=sb.launch_env())
        ok = r.returncode == 0
        why = f'{exe} (server {r.stdout.strip()})' if ok else \
            f'{exe} cannot reach its daemon: {(r.stderr or r.stdout).strip()[:200]}'
    except Exception as e:
        ok, why = False, f'{exe}: {e}'
    with _lock:
        _DOCKER_CACHE[exe] = (now, ok, why)
    return ok, why


def effective_isolation(cfg) -> Tuple[str, str]:
    """(``container`` or ``none``, why) for a stdio upstream; raises IsolationError when it may not start."""
    iso = (getattr(cfg, 'isolation', '') or '').strip()
    if iso == 'none':
        return 'none', 'isolation: none (set explicitly): runs unconfined as a subprocess of SAJHA'
    ok, why = docker_available()
    if ok:
        return 'container', why
    if iso == 'container':
        raise IsolationError(f'stdio upstream {cfg.id} needs a container (isolation: container) but docker is not '
                             f'available: {why}')
    raise IsolationError(f'stdio upstream {cfg.id} is not started: docker is not available ({why}), and an '
                         f'unconfined stdio upstream runs only with isolation: none set explicitly')


def _setting(key: str, default: str = '') -> str:
    try:
        from sajha.core.config import _get
        v = _get(key, default)
        return default if v is None else str(v)
    except Exception:
        return default


def _forbidden_sources() -> List[str]:
    """Host folders a mount may not expose: SAJHA's own tree, its working directory, the home folder,
    the database folder, and the docker socket's folder."""
    from sajha.sandbox.backends import deny_roots
    return [os.path.realpath(p) for p in deny_roots()] + ['/var/run', '/run', '/proc', '/sys', '/dev', '/etc', '/root']


def check_mounts(block: Dict[str, Any]) -> List[Tuple[str, str]]:
    out = []
    forbidden = _forbidden_sources()
    for item in block.get('mounts') or []:
        src, dst = parse_mount(item)
        real = os.path.realpath(src)
        for f in forbidden:
            if real == f or real.startswith(f.rstrip('/') + '/') or f.startswith(real.rstrip('/') + '/') or real == '/':
                raise IsolationError(f'container.mounts: {src} would expose {f} to the upstream')
        if not os.path.exists(real):
            raise IsolationError(f'container.mounts: {src} does not exist')
        out.append((real, dst))
    return out


@dataclass
class Launch:
    """What a containerised stdio upstream runs: the docker command and its environment."""
    name: str
    argv: List[str]
    env: Dict[str, str]
    image: str
    policy: Dict[str, Any] = field(default_factory=dict)


def container_name(upstream_id: str) -> str:
    return f'sajha-fed-{upstream_id}-{os.getpid()}-{uuid.uuid4().hex[:8]}'


def build(cfg, env: Dict[str, str], name: Optional[str] = None) -> Launch:
    """The ``docker run`` command for one connection to the stdio upstream ``cfg``; ``env`` holds the
    variables the server needs (resolved ``env_refs`` included), passed by name only."""
    from sajha.sandbox import load_settings, policy_from_config
    settings = load_settings()
    sb = _sandbox()
    block = dict(getattr(cfg, 'container', None) or {})
    policy = policy_from_config({
        'network': block.get('network') or 'none', 'allow_hosts': block.get('allow_hosts') or [],
        **{k: block[k] for k in ('memory_mb', 'max_processes') if block.get(k) not in (None, '')}}, settings)
    image = str(block.get('image') or _setting('federation.container.image', '') or sb.image())
    name = name or container_name(cfg.id)
    exe = shutil.which(sb.binary()) or sb.binary()
    mem = f'{policy.memory_mb}m'
    tmpfs = max(16, int(block.get('tmpfs_mb') or 64))
    hook = getattr(sb, 'network_args', None)       # the sandbox's egress enforcement, when it offers one
    net = list(hook(policy, name)) if callable(hook) else \
        ['--network', 'none' if policy.network != 'allowlist' else 'bridge']
    argv = [exe, 'run', '--rm', '-i', '--name', name, '--label', f'{LABEL}={cfg.id}', *net,
            '--read-only', '--tmpfs', f'/tmp:rw,nosuid,nodev,size={tmpfs}m,mode=1777',
            '--memory', mem, '--memory-swap', mem,
            '--cpus', str(block.get('cpus') or settings.docker.get('cpus') or '1'),
            '--pids-limit', str(policy.max_processes), '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--user', str(block.get('user') or '65534:65534'),
            '--log-driver', 'none', '-e', 'HOME=/tmp', '-e', 'TMPDIR=/tmp']
    runtime = settings.docker.get('runtime')
    if runtime:
        argv += ['--runtime', runtime]
    if policy.network == 'allowlist':
        for host in policy.allow_hosts:                 # what the upstream may reach, for operators and audit
            argv += ['--label', f'sajha.allow_host={host}']
    for src, dst in check_mounts(block):
        argv += ['--mount', f'type=bind,source={src},target={dst},readonly']
    if getattr(cfg, 'cwd', ''):
        argv += ['-w', cfg.cwd]
    for k in sorted(env):
        argv += ['-e', k]                              # by name: the value comes from docker's own environment
    # the command is the executable inside the image whatever the image's own ENTRYPOINT says
    argv += ['--entrypoint', cfg.command, image, *list(cfg.args or [])]
    launch_env = dict(sb.launch_env())
    launch_env.update(env)
    return Launch(name=name, argv=argv, env=launch_env, image=image,
                  policy={'network': policy.network, 'allow_hosts': policy.allow_hosts,
                          'memory_mb': policy.memory_mb, 'max_processes': policy.max_processes})


def remove(name: str) -> None:
    """Remove a container by name (it outlives a killed docker client). Never raises."""
    try:
        sb = _sandbox()
        subprocess.run([shutil.which(sb.binary()) or sb.binary(), 'rm', '-f', name], capture_output=True,
                       timeout=20, env=sb.launch_env())
    except Exception as e:
        logger.debug(f'federation: removing container {name}: {e}')


async def aremove(name: str) -> None:
    import asyncio
    await asyncio.to_thread(remove, name)


async def watch(conn, name: str) -> None:
    """Wait for the connection's container to end (``docker wait``) and mark the connection lost, so
    its reconnect loop starts a new container at once rather than at the next call or refresh.
    Cancelled when the connection closes."""
    import asyncio
    sb = _sandbox()
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            shutil.which(sb.binary()) or sb.binary(), 'wait', name, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=sb.launch_env())
        out, err = await proc.communicate()
        code = out.decode(errors='replace').strip() or (err.decode(errors='replace').strip()[:120] or '?')
        if not conn._stop.is_set():
            logger.warning(f'federation: upstream {conn.config.id}: container {name} ended ({code}); restarting')
            conn.mark_lost(f'container {name} ended (exit {code})')
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug(f'federation: watching container {name}: {e}')
    finally:
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass


_NAME_PID = re.compile(r'^sajha-fed-.+-(\d+)-[0-9a-f]{8}$')
_orphans_checked = False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def remove_orphans() -> List[str]:
    """Remove upstream containers left by a SAJHA process that is gone (a killed server's
    containers outlive it). Only containers carrying the federation label and a name whose
    process id is not running on this host. Returns the names removed; never raises."""
    removed: List[str] = []
    try:
        sb = _sandbox()
        exe = shutil.which(sb.binary()) or sb.binary()
        r = subprocess.run([exe, 'ps', '-a', '--filter', f'label={LABEL}', '--format', '{{.Names}}'],
                           capture_output=True, text=True, timeout=20, env=sb.launch_env())
        for n in r.stdout.split():
            m = _NAME_PID.match(n)
            if m and not _pid_alive(int(m.group(1))):
                remove(n)
                removed.append(n)
    except Exception as e:
        logger.debug(f'federation: looking for orphaned containers: {e}')
    if removed:
        logger.info(f'federation: removed {len(removed)} orphaned upstream container(s): {", ".join(removed)}')
    return removed


def _remove_orphans_once() -> None:
    global _orphans_checked
    with _lock:
        if _orphans_checked:
            return
        _orphans_checked = True
    remove_orphans()


# ── notices ──────────────────────────────────────────────────────────

def notice_unconfined(cfg) -> None:
    try:
        from sajha import notices
        notices.clear_notice(f'federation.stdio_isolation:{cfg.id}')
        notices.raise_notice(f'federation.stdio_unconfined:{cfg.id}', severity='warning', source='federation',
                             title=f'stdio upstream {cfg.id} runs unconfined',
                             detail=f'{cfg.id} has isolation: none, so its command runs as a subprocess of SAJHA '
                                    f'with the server\'s user, files and network. Remove isolation: none to run it '
                                    f'in its own container.', ttl_minutes=0)
    except Exception as e:
        logger.debug(f'federation: notice for {cfg.id}: {e}')


def notice_refused(cfg, why: str) -> None:
    try:
        from sajha import notices
        notices.raise_notice(f'federation.stdio_isolation:{cfg.id}', severity='error', source='federation',
                             title=f'stdio upstream {cfg.id} is not started', detail=why, ttl_minutes=0)
    except Exception as e:
        logger.debug(f'federation: notice for {cfg.id}: {e}')


def clear_notices(cfg, keep_unconfined: bool = False) -> None:
    try:
        from sajha import notices
        notices.clear_notice(f'federation.stdio_isolation:{cfg.id}')
        if not keep_unconfined:
            notices.clear_notice(f'federation.stdio_unconfined:{cfg.id}')
    except Exception:
        pass


def stdio_target(conn, env: Dict[str, str]):
    """The SDK ``StdioServerParameters`` for one connection of ``conn`` (an UpstreamConnection):
    a container launch, or the plain command with ``isolation: none``. Sets ``conn.container_name``
    and ``conn.isolation``; raises IsolationError (and raises the notice) when it may not start."""
    from mcp.client.stdio import StdioServerParameters
    cfg = conn.config
    try:
        iso, why = effective_isolation(cfg)
    except IsolationError as e:
        notice_refused(cfg, str(e))
        raise
    conn.isolation = iso
    if iso == 'none':
        notice_unconfined(cfg)
        conn.container_name = None
        return StdioServerParameters(command=cfg.command, args=list(cfg.args or []), env=env or None,
                                     cwd=cfg.cwd or None)
    _remove_orphans_once()
    try:
        launch = build(cfg, env)
    except IsolationError as e:
        notice_refused(cfg, str(e))
        raise
    clear_notices(cfg)
    conn.container_name = launch.name
    logger.info(f'federation: upstream {cfg.id}: container {launch.name} from {launch.image} '
                f'(network {launch.policy["network"]}, memory {launch.policy["memory_mb"]} MB)')
    return StdioServerParameters(command=launch.argv[0], args=launch.argv[1:], env=launch.env)
