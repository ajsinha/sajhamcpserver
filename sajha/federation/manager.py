"""
SAJHA MCP Server — FederationManager: upstream MCP servers behind SAJHA's governance.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Owns one background event loop (thread ``sajha-federation``) and one UpstreamConnection per
enabled upstream. On every discovery it reconciles the upstream's tools, prompts and
resources with their approval state (FederationStore) and registers each approved tool in
the ToolsRegistry as a FederatedTool. ``call_tool`` / ``get_prompt`` / ``read_resource``
route calls from any thread to the upstream and back. Nothing here may take SAJHA down:
every entry point catches its own failures. Design: docs/architecture/Federation.md.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import fnmatch
import hashlib
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

from sajha.federation.config import (ConfigError, FederationSettings, UpstreamConfig, SEPARATOR,
                                     namespaced)
from sajha.federation.connection import (UpstreamConnection, UpstreamTimeout, UpstreamUnavailable,
                                         describe)
from sajha.federation import scale
from sajha.federation.security import (correct_annotations, redact, schema_problem, screen_schema,
                                       screen_text)
from sajha.federation.store import FederationStore
from sajha.federation.tool import FederatedTool, FederatedToolError

logger = logging.getLogger(__name__)

RESOURCE_SCHEME = 'sajha-federation'
VIEW_PREFIX = 'ui://sajha-federation/'      # an upstream's MCP Apps views (ui://), namespaced by upstream id
STATE_KEY = 'sajha.federation'
STATUSES = ('pending', 'approved', 'changed', 'rejected', 'disabled', 'invalid')
KINDS = ('tool', 'prompt', 'resource', 'template')
_TEMPLATE_EXPR = re.compile(r'(\{[^{}]*\})')
_TITLE_LIMIT = 200
_SCHEMA_TEXT_LIMIT = 512


class FederationError(RuntimeError):
    pass


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str)
                          .encode('utf-8')).hexdigest()[:32]


class _Upstream:
    """Runtime state of one upstream: its definition, connection and discovered items."""

    def __init__(self, config: UpstreamConfig):
        self.config = config
        self.conn: Optional[UpstreamConnection] = None
        # kind -> upstream name/uri -> {'exposed', 'definition', 'hash', 'flagged', 'raw'}
        self.items: Dict[str, Dict[str, Dict[str, Any]]] = {k: {} for k in KINDS}
        self.conflicts: Dict[str, str] = {}
        self.records: Optional[Dict[str, Dict[str, Any]]] = None     # approval records (the store's)
        self.last_refresh: Optional[float] = None
        self.last_refresh_error: Optional[str] = None
        self.calls = 0
        self.failures = 0
        self.last_call: Optional[float] = None
        self.total_ms = 0.0
        self.limiter = None
        # token_user: one open session per user on a session-based (2025-11-25) upstream, and the
        # tools users saw with their own tokens (discovery offers the union)
        self.user_sessions: Dict[str, '_UserSession'] = {}
        self.user_tools: Dict[str, Dict[str, Any]] = {}
        # service_with_user: the shared service credential, built once (None: the shared headers only)
        self.service_auth = None
        self.service_auth_built = False
        # gateway scale (sajha/federation/scale.py): every shared connection (``conn`` is the primary
        # one, which runs discovery), and the bound on calls in flight
        self.pool: List[UpstreamConnection] = []
        self.admission: Optional[scale.Admission] = None
        if config.max_calls_per_minute:
            from sajha.security import RateLimiter
            # Named per upstream: the window key is ratelimit:<name>:calls, so a shared
            # default name would put every upstream in one window.
            self.limiter = RateLimiter(max_requests=config.max_calls_per_minute, window_seconds=60,
                                       name=f'federation:{config.id}')


class _UserSession:
    """One user's open session on a session-based token_user upstream (lives on the federation loop)."""

    def __init__(self, conn: UpstreamConnection, fingerprint: str):
        self.conn = conn
        self.fingerprint = fingerprint      # a hash of the credential: a replaced token opens a new session
        self.last_used = time.time()
        self.busy = 0


def _net_external(upstream_id: str) -> Optional[Dict[str, Any]]:
    """``sajhanet.external_servers``' entry for this upstream, if SAJHA Net is loaded (else None)."""
    try:
        from sajha.net.integration.catalogs import get_catalogs
        c = get_catalogs()
        if c is None:
            return None
        x = next((x for x in c.settings.external_servers or [] if x.upstream == upstream_id), None)
        return {'upstream': x.upstream, 'vendor': x.vendor, 'prefix': x.effective_prefix} if x else None
    except Exception:
        return None


_SOURCES = {'config': 'federation.upstreams', 'file': 'the mcpServers file', 'store': 'added on the console'}


class FederationManager:
    def __init__(self, registry=None, settings: Optional[FederationSettings] = None,
                 store: Optional[FederationStore] = None):
        self.settings = settings or FederationSettings.load()
        self.registry = registry
        self.store = store or FederationStore(self.settings.state_path)
        self._lock = threading.RLock()
        self._upstreams: Dict[str, _Upstream] = {}
        self._exposed: Dict[str, Tuple[str, str]] = {}          # exposed tool name -> (upstream id, tool)
        self._tools: Dict[str, FederatedTool] = {}               # exposed tool name -> registered tool
        self._prompts: Dict[str, Tuple[str, str]] = {}           # exposed prompt name -> (upstream id, prompt)
        self._views: Dict[str, Tuple[str, str, List[str]]] = {}   # exposed ui:// view -> (upstream, view, tools)
        self._holders: Dict[str, set] = {}                       # subscriber -> exposed resource URIs it watches
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self.config_errors: Dict[str, str] = {}
        from sajha.federation.mcp_servers import McpServersFile
        self.mcp_file = McpServersFile(self.settings.mcp_servers_file) if self.settings.mcp_servers_file else None
        self.file_external: List[Dict[str, Any]] = []      # {upstream, vendor} of the file's external servers
        self.file_vendors: Dict[str, str] = {}              # the file's entries: id -> vendor
        self._file_stop = threading.Event()
        self._file_thread: Optional[threading.Thread] = None
        if registry is not None and hasattr(registry, 'add_reload_listener'):
            registry.add_reload_listener(self._reregister_after_reload)
        # the cluster-wide view of upstream health (sajha/federation/scale.py)
        from sajha.core.state import WORKER_ID
        self.worker_id = WORKER_ID
        self.health = scale.HealthBoard(self.worker_id, self.settings.health_ttl_seconds)
        self._health_stop = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._peer_tripped: Dict[str, float] = {}     # upstream -> when a peer's open breaker opened ours

    # ══ lifecycle ══════════════════════════════════════════════════
    def start(self) -> None:
        """Load the upstreams and connect the enabled ones (no-op when federation is off)."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._load_upstreams()
        if not self.settings.enabled:
            logger.info('Federation: off (federation.enabled)')
            return
        self._watch_file()
        self._ensure_loop()
        self._watch_health()
        for up in list(self._upstreams.values()):
            if up.config.enabled:
                self._connect(up)
        wait = self.settings.startup_wait_seconds
        if wait > 0 and any(u.config.enabled for u in self._upstreams.values()):
            self.wait_until_discovered(wait)
        logger.info(f'Federation: {len(self._upstreams)} upstream(s), {len(self._tools)} tool(s) exposed')

    def wait_until_discovered(self, timeout: float) -> bool:
        """Block until every enabled upstream finished a discovery or failed, at most ``timeout`` s."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            pending = [u for u in self._upstreams.values() if u.config.enabled and u.conn is not None
                       and u.last_refresh is None and u.last_refresh_error is None
                       and u.conn.state in ('connecting', 'connected')]
            if not pending:
                return True
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        self._file_stop.set()
        self._health_stop.set()
        for uid in list(self._upstreams):
            self.health.forget(uid)
        loop = self._loop
        if loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._stop_all(), loop)
            fut.result(timeout=10)
        except Exception as e:
            logger.debug(f'federation stop: {e}')
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    async def _stop_all(self) -> None:
        sessions = [s.conn for u in self._upstreams.values() for s in u.user_sessions.values()]
        for u in self._upstreams.values():
            u.user_sessions.clear()
        await asyncio.gather(*(c.stop() for u in self._upstreams.values() for c in self._members(u)),
                             *(c.stop(timeout=2.0) for c in sessions), return_exceptions=True)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                ready = threading.Event()

                def run():
                    asyncio.set_event_loop(loop)
                    loop.call_soon(ready.set)
                    loop.run_forever()
                    try:
                        loop.run_until_complete(loop.shutdown_asyncgens())
                    finally:
                        loop.close()

                self._thread = threading.Thread(target=run, name='sajha-federation', daemon=True)
                self._thread.start()
                ready.wait(5)
                self._loop = loop
            return self._loop

    def _submit(self, coro) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())

    def _run(self, coro, timeout: float):
        return self._submit(coro).result(timeout=timeout)

    # ══ upstream definitions ═══════════════════════════════════════
    def _prefix_clash(self, cfg: UpstreamConfig) -> Optional[str]:
        """Prefixes are unique on an instance and never a local tool's name (Federation.md, "Names")."""
        p = cfg.effective_prefix
        other = next((u.config for i, u in self._upstreams.items() if i != cfg.id and u.config.effective_prefix == p),
                     None)
        if other is not None:
            return (f'prefix {p} is already used by upstream {other.id} ({_SOURCES.get(other.source, other.source)}); '
                    f'{cfg.id} ({_SOURCES.get(cfg.source, cfg.source)}) is not loaded and exposes no tools. The prefix '
                    f'defaults to the vendor: give one of them its own "prefix"')
        reg = self.registry
        if reg is not None and getattr(reg, 'tools', None) is not None:
            t = reg.tools.get(p)
            if t is not None and not isinstance(t, FederatedTool):
                return f'prefix {p} of upstream {cfg.id} is the name of a local tool; it is not loaded'
        return None

    def _add_loaded(self, cfg: UpstreamConfig) -> bool:
        why = self._prefix_clash(cfg)
        if why:
            self.config_errors[cfg.id] = why
            logger.error(f'federation: {why}')
            self._prefix_notice()
            return False
        if str(self.config_errors.get(cfg.id, '')).startswith('prefix '):
            self.config_errors.pop(cfg.id, None)            # an earlier clash, resolved
        self._upstreams[cfg.id] = _Upstream(cfg)
        return True

    def _prefix_notice(self) -> None:
        """A configuration error notice while an upstream is not loaded because its prefix clashes (never a
        silent upstream with no tools); cleared when no clash is left."""
        clashes = {k: v for k, v in self.config_errors.items() if str(v).startswith('prefix ')}
        try:
            from sajha import notices
            if clashes:
                notices.raise_notice('federation.prefix_clash', severity='error', source='federation',
                                     title='A proxied MCP server is not loaded: its tool prefix is taken',
                                     detail='; '.join(f'{k}: {v}' for k, v in sorted(clashes.items()))[:1000],
                                     link='/admin/federation', audience='admin', ttl_minutes=0)
            else:
                notices.clear_notice('federation.prefix_clash')
        except Exception as e:
            logger.debug(f'federation: prefix clash notice: {e}')

    def _load_upstreams(self) -> None:
        self.config_errors.clear()
        seen = set()
        for raw in self.settings.upstreams:
            try:
                cfg = UpstreamConfig.from_dict(raw, source='config')
            except ConfigError as e:
                uid = str((raw or {}).get('id') or '?')
                self.config_errors[uid] = str(e)
                logger.error(f'federation: upstream {uid} in configuration is invalid: {e}')
                continue
            seen.add(cfg.id)
            self._add_loaded(cfg)
        for cfg in self._file_upstreams(seen, force=True):
            seen.add(cfg.id)
            if not self._add_loaded(cfg):
                self.file_external = [x for x in self.file_external if x['upstream'] != cfg.id]
        for raw in self.store.upstreams():
            try:
                cfg = UpstreamConfig.from_dict(raw, source='store')
            except ConfigError as e:
                uid = str((raw or {}).get('id') or '?')
                self.config_errors[uid] = str(e)
                logger.error(f'federation: stored upstream {uid} is invalid: {e}')
                continue
            if cfg.id in seen:
                self.config_errors[cfg.id] = 'defined in configuration; the stored definition is ignored'
                continue
            self._add_loaded(cfg)
        self._prefix_notice()

    # ── the mcpServers file (sajha/federation/mcp_servers.py) ──────
    def _file_upstreams(self, yaml_ids, force: bool = False) -> List[UpstreamConfig]:
        """The file's upstreams that are valid and not defined in ``federation.upstreams`` (the YAML one
        wins a duplicate id, with an error naming both sources); sets ``file_external``."""
        if self.mcp_file is None:
            self.file_external = []
            return []
        p = self.mcp_file.load(force=force)
        path = self.mcp_file.path
        out: List[UpstreamConfig] = []
        for key in [k for k in self.config_errors if self.config_errors[k].startswith(f'{path}:')]:
            self.config_errors.pop(key, None)
        for key, why in p.errors.items():
            self.config_errors[key] = f'{path}: {why}'
        for raw in p.upstreams:
            uid = raw.get('id')
            if uid in yaml_ids:
                self.config_errors[uid] = (f'{path}: {uid} is also defined in federation.upstreams '
                                           f'(config/application.yml); the YAML definition is used')
                continue
            try:
                out.append(UpstreamConfig.from_dict(raw, source='file'))
            except ConfigError as e:
                self.config_errors[str(uid)] = f'{path}: {e}'
        ok = {c.id for c in out}
        self.file_external = [x for x in p.external if x['upstream'] in ok]
        self.file_vendors = {k: v for k, v in p.vendors.items() if k in ok}
        self._file_notices(p)
        return out

    def _file_notices(self, p) -> None:
        try:
            from sajha import notices
            path = self.mcp_file.path
            errs = {k: v for k, v in self.config_errors.items() if v.startswith(f'{path}:')}
            if errs:
                notices.raise_notice('federation.mcp_servers', severity='warning', source='federation',
                                     title=f'Some entries of {path} are not used',
                                     detail='; '.join(f'{k}: {v[len(path) + 2:]}' for k, v in sorted(errs.items()))[:1000],
                                     ttl_minutes=0)
            else:
                notices.clear_notice('federation.mcp_servers')
            if p.raw_secrets:
                notices.raise_notice('federation.mcp_servers.raw_secrets', severity='info', source='federation',
                                     title=f'{path} holds raw credentials',
                                     detail=f'These headers are raw values: {", ".join(p.raw_secrets)}. The file is '
                                            f'git-ignored; ${{ENV_NAME}} keeps them out of it altogether.',
                                     ttl_minutes=0)
            else:
                notices.clear_notice('federation.mcp_servers.raw_secrets')
        except Exception as e:
            logger.debug(f'federation: notices for {self.mcp_file.path}: {e}')

    def reload_file(self, force: bool = False) -> bool:
        """Apply a changed mcpServers file: new entries connect, removed ones go, changed ones are
        replaced. True when something changed. Runs on a timer (federation.mcp_servers_reload_seconds)."""
        if self.mcp_file is None or not (force or self.mcp_file.changed()):
            return False
        with self._lock:
            yaml_ids = {i for i, u in self._upstreams.items() if u.config.source == 'config'}
            new = {c.id: c for c in self._file_upstreams(yaml_ids, force=True)}
            old = {i: u for i, u in self._upstreams.items() if u.config.source == 'file'}
            gone = [old[i] for i in old if i not in new]
            changed = [i for i in new if i in old and old[i].config.to_dict() != new[i].to_dict()]
            added = [i for i in new if i not in old and i not in self._upstreams]
            for i in [u.config.id for u in gone] + changed:
                self._upstreams.pop(i, None)
            for i, why in list(self.config_errors.items()):         # clashes of entries the file no longer has
                if str(why).startswith('prefix ') and f'{i} (the mcpServers file)' in str(why) and i not in new:
                    self.config_errors.pop(i, None)
            fresh = []
            for i in changed + added:
                if not self._add_loaded(new[i]):
                    self.file_external = [x for x in self.file_external if x['upstream'] != i]
                    continue
                fresh.append(self._upstreams[i])
            self._prefix_notice()
        for up in gone + [old[i] for i in changed]:
            self._teardown(up, forget=False)
        if self.settings.enabled:
            for up in fresh:
                if up.config.enabled:
                    self._connect(up)
        if gone or fresh:
            logger.info(f'federation: {self.mcp_file.path} reloaded: {len(added)} added, {len(changed)} changed, '
                        f'{len(gone)} removed')
        return bool(gone or fresh)

    def _watch_file(self) -> None:
        if self.mcp_file is None or self._file_thread is not None:
            return
        every = self.settings.mcp_servers_reload_seconds

        def loop():
            while not self._file_stop.wait(every):
                try:
                    self.reload_file()
                except Exception as e:
                    logger.warning(f'federation: reloading {self.mcp_file.path}: {e}')
        self._file_thread = threading.Thread(target=loop, name='federation-mcp-servers', daemon=True)
        self._file_thread.start()

    def external_servers(self) -> List[Dict[str, Any]]:
        """The file's entries that are external servers in SAJHA Net (design §5.6): ``{upstream, vendor}``."""
        return list(self.file_external)

    def upstream_ids(self) -> List[str]:
        return sorted(self._upstreams)

    def get_config(self, upstream_id: str) -> Optional[UpstreamConfig]:
        up = self._upstreams.get(upstream_id)
        return up.config if up else None

    def validate_definition(self, data: Dict[str, Any]) -> UpstreamConfig:
        cfg = UpstreamConfig.from_dict(dict(data or {}), source='store')
        if cfg.transport == 'stdio' and not self.settings.allow_stdio:
            raise ConfigError('stdio upstreams are disabled (federation.allow_stdio)')
        if cfg.transport != 'stdio':
            from sajha.federation.security import check_url
            for url in cfg.replica_urls:            # url and every replica
                check_url(url, self.settings)
        prefixes = {u.config.effective_prefix: uid for uid, u in self._upstreams.items() if uid != cfg.id}
        if cfg.effective_prefix in prefixes:
            raise ConfigError(f'prefix {cfg.effective_prefix} is already used by upstream {prefixes[cfg.effective_prefix]}')
        return cfg

    def add_upstream(self, data: Dict[str, Any], replace: bool = False) -> UpstreamConfig:
        cfg = self.validate_definition(data)
        with self._lock:
            existing = self._upstreams.get(cfg.id)
            if existing is not None and existing.config.source in ('config', 'file'):
                raise ConfigError(f'upstream {cfg.id} is defined in configuration; edit it there')
            if existing is not None and not replace:
                raise ConfigError(f'upstream {cfg.id} already exists')
            if existing is None and replace:
                raise KeyError(cfg.id)
            self.store.put_upstream(cfg.to_dict())
        if existing is not None:
            self._teardown(existing, forget=False)
        up = _Upstream(cfg)
        with self._lock:
            self._upstreams[cfg.id] = up
        if self.settings.enabled and cfg.enabled:
            self._connect(up)
        return cfg

    def remove_upstream(self, upstream_id: str) -> bool:
        with self._lock:
            up = self._upstreams.get(upstream_id)
            if up is None:
                return False
            if up.config.source in ('config', 'file'):
                raise ConfigError(f'upstream {upstream_id} is defined in configuration; remove it there')
            self._upstreams.pop(upstream_id, None)
        self._teardown(up, forget=True)
        self.store.delete_upstream(upstream_id)
        return True

    def _teardown(self, up: _Upstream, forget: bool) -> None:
        if up.user_sessions and self._loop is not None:
            try:
                self._run(self._close_sessions(up, list(up.user_sessions)), timeout=10)
            except Exception as e:
                logger.debug(f'federation: closing per-user sessions of {up.config.id}: {e}')
        if up.conn is not None and self._loop is not None:
            try:
                self._run(self._stop_members(self._members(up)), timeout=10)
            except Exception as e:
                logger.debug(f'federation: stopping {up.config.id}: {e}')
        up.conn = None
        up.pool = []
        self.health.forget(up.config.id)
        self._sync_registry()

    @staticmethod
    async def _stop_members(members: List[UpstreamConnection]) -> None:
        await asyncio.gather(*(c.stop() for c in members), return_exceptions=True)

    def _connect(self, up: _Upstream) -> None:
        if up.conn is not None:
            return
        loop = self._ensure_loop()
        cfg = up.config
        pool: List[UpstreamConnection] = []
        size = self._pool_size(cfg)
        for r, url in enumerate(cfg.replica_urls):          # url, then each replica in urls
            mcfg = cfg if r == 0 else dataclasses.replace(cfg, url=url, urls=[])
            for i in range(size):
                c = UpstreamConnection(mcfg, self.settings, self._discover,
                                       refresh_seconds=cfg.refresh_interval_seconds)
                c.role, c.replica, c.slot = ('primary' if not pool else 'pool'), r, i
                pool.append(c)
        up.pool = pool
        up.conn = pool[0]
        up.conn.on_resource_updated = lambda uri, uid=cfg.id: self._resource_updated(uid, uri)
        up.conn.watched = self._watched_originals(cfg.id)
        limit, queue = self._limits(cfg)
        if up.admission is None:
            up.admission = scale.Admission(cfg.id, limit, queue, self.settings.queue_timeout_seconds)
        else:
            up.admission.reconfigure(limit, queue, self.settings.queue_timeout_seconds)
        self._register_breaker(cfg)
        for c in pool:
            loop.call_soon_threadsafe(c.start)

    # ── gateway scale: pools, replicas, admission, shared health ────
    def _pool_size(self, cfg: UpstreamConfig) -> int:
        from sajha.federation.config import POOL_MAX
        return max(1, min(POOL_MAX, int(cfg.pool_size or self.settings.pool_size or 1)))

    def _limits(self, cfg: UpstreamConfig) -> Tuple[int, int]:
        limit = cfg.max_in_flight if cfg.max_in_flight is not None else self.settings.max_in_flight
        queue = cfg.max_queue if cfg.max_queue is not None else self.settings.max_queue
        return max(0, int(limit or 0)), max(0, int(queue or 0))

    @staticmethod
    def _members(up: _Upstream) -> List[UpstreamConnection]:
        return list(up.pool) if up.pool else ([up.conn] if up.conn is not None else [])

    def _pick(self, up: _Upstream, exclude=()) -> Optional[UpstreamConnection]:
        """The shared connection for the next call (scale.pick_member); the primary when none is
        connected (its ready_client then waits briefly and names the failure)."""
        members = self._members(up)
        if len(members) <= 1:
            return up.conn
        m = scale.pick_member(members, exclude, self.health.down_replicas(up.config.id))
        if m is None:
            rest = [c for c in members if c not in exclude]
            return up.conn if up.conn in rest or not rest else rest[0]
        return m

    def _breaker(self, cfg: UpstreamConfig):
        try:
            from sajha.core.circuit_breaker import get_circuit_registry
            return get_circuit_registry().get_breaker(cfg.effective_prefix + SEPARATOR + 'x')
        except Exception:
            return None

    def _watch_health(self) -> None:
        if self._health_thread is not None:
            return
        every = self.settings.health_publish_seconds

        def loop():
            while not self._health_stop.wait(every):
                try:
                    self.health_tick()
                except Exception as e:
                    logger.debug(f'federation: health tick: {e}')
        self._health_thread = threading.Thread(target=loop, name='federation-health', daemon=True)
        self._health_thread.start()

    def health_snapshot(self, up: _Upstream) -> Dict[str, Any]:
        """This worker's view of one upstream, as published to the state store."""
        members = self._members(up)
        conn = up.conn
        b = self._breaker(up.config)
        breaker = None
        if b is not None:
            d = b.to_dict()
            followed = self._peer_tripped.get(up.config.id)
            source = 'peer' if (d['state'] != 'closed' and followed and abs(followed - d['last_failure']) < 1e-6) \
                else 'local'
            breaker = {'state': d['state'], 'since': d['last_state_change'], 'last_failure': d['last_failure'],
                       'failure_count': d['failure_count'], 'source': source}
        replicas = []
        for r, _url in enumerate(up.config.replica_urls):
            mine = [c for c in members if c.replica == r]
            replicas.append({'replica': r, 'members': len(mine),
                             'connected': sum(1 for c in mine if c.state == 'connected'),
                             'fail_streak': max([c.fail_streak for c in mine] or [0])})
        lat = [c.ewma_ms for c in members if c.ewma_ms is not None]
        adm = up.admission.snapshot() if up.admission is not None else {}
        secrets = conn.secret_values() if conn else []
        state = ('disabled' if not (self.settings.enabled and up.config.enabled) else
                 conn.state if conn is not None else 'connecting')
        if state != 'connected' and any(c.state == 'connected' for c in members):
            state = 'connected'                     # a pool member or replica carries calls
        return {'state': state,
                'connected': sum(1 for c in members if c.state == 'connected'), 'pool': len(members),
                'calls': up.calls, 'failures': up.failures,
                'latency_ms': round(sum(lat) / len(lat), 1) if lat else None,
                'in_flight': adm.get('in_flight', 0), 'waiting': adm.get('waiting', 0), 'shed': adm.get('shed', 0),
                'last_error': redact((conn.last_error if conn else None) or up.last_refresh_error or '', secrets)[:300]
                or None,
                'breaker': breaker, 'replicas': replicas}

    def health_tick(self) -> None:
        """Publish this worker's view of every upstream, read every worker's back, follow a peer's open
        breaker (when federation.health.follow_peer_breakers) and promote a connected member when the
        primary connection is down. Runs every federation.health.publish_seconds."""
        if not self.settings.enabled:
            return
        ups = list(self._upstreams.values())
        for up in ups:
            if up.conn is None:
                continue
            try:
                self.health.publish(up.config.id, self.health_snapshot(up))
            except Exception as e:
                logger.debug(f'federation: publishing health of {up.config.id}: {e}')
        try:
            self.health.read()
        except Exception as e:
            logger.debug(f'federation: reading the cluster health: {e}')
            return
        for up in ups:
            if up.conn is None:
                continue
            if self.settings.follow_peer_breakers:
                self._follow_peer_breaker(up)
            self._promote(up)

    def _follow_peer_breaker(self, up: _Upstream) -> None:
        """A breaker a peer opened after its own failures opens this worker's (closed) breaker as of
        the peer's last failure; this breaker then probes on its own after its recovery timeout. One
        peer opening is followed once; a breaker the peer itself followed is never passed on."""
        peer = self.health.open_breaker_from_peer(up.config.id)
        b = self._breaker(up.config)
        if peer is None or b is None or b.state.value != 'closed':
            return
        since = float(peer.get('since') or 0)
        if since <= self._peer_tripped.get(up.config.id + ':seen', 0.0):
            return
        at = float(peer.get('last_failure') or since) or time.time()
        if time.time() - at > b.recovery_timeout:
            return                                  # the peer is probing by now; do not follow stale news
        self._peer_tripped[up.config.id + ':seen'] = since
        self._peer_tripped[up.config.id] = at
        b.trip(at)
        logger.warning(f'federation: breaker of {up.config.id} opened: worker {peer.get("worker")} opened its own')

    def _promote(self, up: _Upstream) -> None:
        """The primary connection (discovery, change listening, subscriptions) is down while another
        member is connected: that member becomes the primary (on another replica when there is one)."""
        old = up.conn
        if old is None or old.state == 'connected' or len(up.pool) < 2 or self._loop is None:
            return
        live = [c for c in up.pool if c is not old and c.state == 'connected']
        if not live:
            return
        new = sorted(live, key=lambda c: (c.replica == old.replica, c.fail_streak, c.slot))[0]

        def swap():
            if up.conn is not old:
                return
            old.role, new.role = 'pool', 'primary'
            new.on_resource_updated, old.on_resource_updated = old.on_resource_updated, None
            new.watched = set(old.watched)
            up.conn = new
            new.kick()                      # reopen as primary: discovery and change listening start
        self._loop.call_soon_threadsafe(swap)
        logger.warning(f'federation: upstream {up.config.id}: primary connection down; replica {new.replica} '
                       f'connection {new.slot} takes over discovery')

    def _register_breaker(self, cfg: UpstreamConfig) -> None:
        try:
            from sajha.core.circuit_breaker import get_circuit_registry
            b = cfg.breaker or {}
            get_circuit_registry().register_prefix(
                cfg.effective_prefix + SEPARATOR, f'Federation: {cfg.display_title}',
                failure_threshold=int(b.get('failure_threshold', 5) or 5),
                recovery_timeout=int(b.get('recovery_timeout', 60) or 60))
        except Exception as e:
            logger.debug(f'federation: breaker for {cfg.id}: {e}')

    # ══ discovery ══════════════════════════════════════════════════
    async def _discover(self, conn: UpstreamConnection) -> None:
        up = self._upstreams.get(conn.config.id)
        if up is None or up.conn is not conn:
            return
        cfg = up.config
        timeout = float(cfg.timeout_seconds or self.settings.default_timeout_seconds)
        caps = conn.capabilities or {}
        try:
            tools = await conn.list_all('tools', timeout) if 'tools' in caps or not caps else []
            prompts = await conn.list_all('prompts', timeout) if cfg.expose_prompts and 'prompts' in caps else []
            resources = (await conn.list_all('resources', timeout)
                         if cfg.expose_resources and 'resources' in caps else [])
        except Exception as e:
            up.last_refresh_error = describe(e)
            raise
        templates = []
        if cfg.expose_resources and 'resources' in caps:
            try:                    # optional on the upstream: one that does not serve it has none
                templates = await conn.list_all('resource_templates', timeout)
            except Exception as e:
                logger.debug(f'federation: resources/templates/list on {cfg.id}: {describe(e)}')
        dump = lambda m: m.model_dump(mode='json', by_alias=True, exclude_none=True)   # noqa: E731
        tool_dicts = [dump(t) for t in tools]
        if up.user_tools:           # token_user: the union of what each user's own token lists
            seen = {t.get('name') for t in tool_dicts}
            tool_dicts += [t for n, t in sorted(up.user_tools.items()) if n not in seen]
        changed = self._reconcile(up, tool_dicts, [dump(p) for p in prompts], [dump(r) for r in resources],
                                  [dump(t) for t in templates])
        self._prune_holders()
        up.last_refresh = time.time()
        up.last_refresh_error = None
        if changed:
            await asyncio.get_running_loop().run_in_executor(None, self._sync_registry, cfg.id)

    def _included(self, cfg: UpstreamConfig, name: str) -> bool:
        if cfg.include_tools and not any(fnmatch.fnmatchcase(name, p) for p in cfg.include_tools):
            return False
        return not any(fnmatch.fnmatchcase(name, p) for p in cfg.exclude_tools)

    def _screen_tool(self, cfg: UpstreamConfig, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        limit = self.settings.max_description_chars
        desc, f1 = screen_text(raw.get('description') or '', limit)
        title, f2 = screen_text(raw.get('title') or '', _TITLE_LIMIT)
        schema, f3 = screen_schema(raw.get('inputSchema') or {'type': 'object', 'properties': {}},
                                   _SCHEMA_TEXT_LIMIT)
        out_schema, f4 = screen_schema(raw.get('outputSchema') or {}, _SCHEMA_TEXT_LIMIT)
        ann = correct_annotations(raw.get('annotations'))     # corrected, never widened
        if 'title' in ann:
            ann['title'], f5 = screen_text(ann['title'], _TITLE_LIMIT)
        else:
            f5 = False
        d = {'name': namespaced(cfg.effective_prefix, raw['name']), 'description': desc,
             'inputSchema': schema if isinstance(schema, dict) else {'type': 'object', 'properties': {}}}
        if title:
            d['title'] = title
        if isinstance(out_schema, dict) and out_schema.get('type') == 'object':
            d['outputSchema'] = out_schema
        d['annotations'] = ann
        icons = [i for i in (raw.get('icons') or []) if isinstance(i, dict) and
                 str(i.get('src', '')).startswith(('https://', 'data:image/'))]
        if icons:
            d['icons'] = icons
        support = (raw.get('execution') or {}).get('taskSupport') if isinstance(raw.get('execution'), dict) else None
        if support in ('optional', 'required'):      # upstream tasks (sajha/federation/tasks.py)
            d['execution'] = {'taskSupport': support}
        ui = self._tool_view(cfg, raw)
        if ui:
            d['_meta'] = {'ui': ui}
        return d, bool(f1 or f2 or f3 or f4 or f5)

    def _tool_view(self, cfg: UpstreamConfig, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """An upstream tool's MCP Apps view (``_meta.ui``), namespaced: ``ui://sajha-federation/<id>/<view>``."""
        meta = raw.get('_meta')
        ui = meta.get('ui') if isinstance(meta, dict) else None
        uri = ui.get('resourceUri') if isinstance(ui, dict) else None
        if not isinstance(uri, str) or not uri.startswith('ui://') or len(uri) > 1000:
            return None
        out: Dict[str, Any] = {'resourceUri': self.view_uri(cfg.id, uri)}
        visibility = ui.get('visibility')
        if isinstance(visibility, list) and visibility and all(v in ('model', 'app') for v in visibility):
            out['visibility'] = list(visibility)
        return out

    @staticmethod
    def _tool_problem(raw: Dict[str, Any]) -> Optional[str]:
        """Why an upstream tool cannot be imported (its schemas are not valid JSON Schema
        object schemas), or None. Shown in the approval queue; such a tool cannot be approved."""
        if raw.get('inputSchema') is not None:
            problem = schema_problem(raw.get('inputSchema'), 'inputSchema')
            if problem:
                return problem
        return schema_problem(raw.get('outputSchema'), 'outputSchema', required=False)

    def _screen_prompt(self, cfg: UpstreamConfig, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        limit = self.settings.max_description_chars
        desc, f1 = screen_text(raw.get('description') or '', limit)
        args, flagged = [], f1
        for a in raw.get('arguments') or []:
            if not isinstance(a, dict) or not a.get('name'):
                continue
            ad, f = screen_text(a.get('description') or '', _SCHEMA_TEXT_LIMIT)
            flagged = flagged or f
            item = {'name': str(a['name']), 'required': bool(a.get('required', False))}
            if ad:
                item['description'] = ad
            args.append(item)
        d = {'name': namespaced(cfg.effective_prefix, raw['name']), 'description': desc}
        if args:
            d['arguments'] = args
        if raw.get('title'):
            d['title'], f = screen_text(raw['title'], _TITLE_LIMIT)
            flagged = flagged or f
        return d, flagged

    def _screen_resource(self, cfg: UpstreamConfig, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        limit = self.settings.max_description_chars
        desc, f1 = screen_text(raw.get('description') or '', limit)
        name, f2 = screen_text(raw.get('name') or raw.get('uri'), _TITLE_LIMIT)
        d = {'uri': self.resource_uri(cfg.id, raw['uri']), 'name': f'{cfg.effective_prefix}{SEPARATOR}{name}'}
        if desc:
            d['description'] = desc
        if raw.get('mimeType'):
            d['mimeType'] = str(raw['mimeType'])[:100]
        return d, bool(f1 or f2)

    def _screen_template(self, cfg: UpstreamConfig, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        limit = self.settings.max_description_chars
        desc, f1 = screen_text(raw.get('description') or '', limit)
        name, f2 = screen_text(raw.get('name') or raw.get('uriTemplate'), _TITLE_LIMIT)
        d = {'uriTemplate': self.template_uri(cfg.id, raw['uriTemplate']),
             'name': f'{cfg.effective_prefix}{SEPARATOR}{name}'}
        if desc:
            d['description'] = desc
        if raw.get('title'):
            d['title'], f3 = screen_text(raw['title'], _TITLE_LIMIT)
            f2 = f2 or f3
        if raw.get('mimeType'):
            d['mimeType'] = str(raw['mimeType'])[:100]
        return d, bool(f1 or f2)

    def _reconcile(self, up: _Upstream, tools: List[Dict], prompts: List[Dict], resources: List[Dict],
                   templates: List[Dict] = ()) -> bool:
        """Record what the upstream offers now and decide each item's status. True when the
        set of exposed definitions changed."""
        cfg = up.config
        auto = (not self.settings.require_approval) or cfg.auto_approve
        records = self.store.items(cfg.id)
        now = self.store.now()
        before = {k: {n: (i['hash'], i['exposed']) for n, i in up.items[k].items()} for k in KINDS}
        before_status = {k: v.get('status') for k, v in records.items()}
        discovered: Dict[str, Dict[str, Dict[str, Any]]] = {k: {} for k in KINDS}
        sources = (('tool', tools, 'name', self._screen_tool), ('prompt', prompts, 'name', self._screen_prompt),
                   ('resource', resources, 'uri', self._screen_resource),
                   ('template', templates, 'uriTemplate', self._screen_template))
        for kind, raws, key, screen in sources:
            for raw in raws:
                ident = raw.get(key)
                if not isinstance(ident, str) or not ident:
                    continue
                if kind == 'tool' and not self._included(cfg, ident):
                    continue
                definition, flagged = screen(cfg, raw)
                h = _hash(raw)
                rk = f'{kind}:{ident}'
                rec = records.get(rk)
                problem = self._tool_problem(raw) if kind == 'tool' else None
                if problem:
                    # refused, whatever was decided before: an invalid schema is never served
                    rec = dict(rec or {'first_seen': now})
                    if rec.get('status') != 'invalid' or rec.get('current_hash') != h:
                        rec['updated_at'] = now
                    if rec.get('status') in ('approved', 'changed') and rec.get('approved_definition'):
                        rec['status'] = 'changed'        # a held approved version keeps serving
                    elif rec.get('status') not in ('rejected', 'disabled'):
                        rec['status'] = 'invalid'
                    rec['reason'] = problem
                elif rec is None or rec.get('status') == 'invalid':
                    rec = {'status': 'approved' if (auto and not flagged) else 'pending', 'hash': h,
                           'first_seen': (rec or {}).get('first_seen', now), 'updated_at': now}
                elif rec.get('hash') != h:
                    if rec.get('status') in ('approved', 'changed'):
                        rec['status'] = 'approved' if (auto and not flagged) else 'changed'
                        if rec['status'] == 'approved':
                            rec['hash'] = h
                    elif rec.get('status') == 'pending':
                        rec['hash'] = h
                    rec['updated_at'] = now
                elif rec.get('status') == 'changed':
                    rec['status'] = 'approved'          # the upstream went back to the approved definition
                if not problem:
                    rec.pop('reason', None)
                    if rec.get('status') == 'approved' and rec.get('hash') == h:
                        rec['approved_definition'] = definition     # what a held version serves
                rec['flagged'] = bool(flagged)
                rec['current_hash'] = h
                records[rk] = rec
                exposed = {'resource': definition.get('uri'), 'template': definition.get('uriTemplate')}.get(
                    kind, definition.get('name'))
                discovered[kind][ident] = {'exposed': exposed, 'definition': definition, 'hash': h,
                                           'flagged': flagged, 'raw': raw}
        # forget pending records of items that vanished; keep decisions (approved/rejected/disabled)
        live = {f'{k}:{n}' for k in KINDS for n in discovered[k]}
        for rk in [rk for rk, r in records.items() if rk not in live and r.get('status') == 'pending']:
            records.pop(rk, None)
        try:
            self.store.set_items(cfg.id, records)
        except Exception:
            pass                                  # logged by the store; state stays in memory
        with self._lock:
            up.items = discovered
            up.records = records
        after = {k: {n: (i['hash'], i['exposed']) for n, i in discovered[k].items()} for k in KINDS}
        after_status = {k: v.get('status') for k, v in records.items()}
        return before != after or before_status != after_status

    # ══ registry ═══════════════════════════════════════════════════
    def _status(self, up: _Upstream, kind: str, ident: str) -> str:
        rec = (getattr(up, 'records', None) or {}).get(f'{kind}:{ident}') or {}
        return rec.get('status') or 'pending'

    def _desired_tools(self) -> Dict[str, Tuple[_Upstream, str, Dict[str, Any]]]:
        """Exposed name -> (upstream, upstream tool name, item) for every approved tool."""
        out: Dict[str, Tuple[_Upstream, str, Dict[str, Any]]] = {}
        if not self.settings.enabled:
            return out
        for uid in sorted(self._upstreams):
            up = self._upstreams[uid]
            up.conflicts = {}
            if not up.config.enabled:
                continue
            # two upstream names that map to one exposed name (a.b and a_b): neither is offered
            by_exposed: Dict[str, List[str]] = {}
            for name, item in up.items['tool'].items():
                by_exposed.setdefault(item['exposed'], []).append(name)
            for name, item in sorted(up.items['tool'].items()):
                item = self._serving(up, name, item)
                if item is None:
                    continue
                exposed = item['exposed']
                clash = [n for n in by_exposed.get(exposed, []) if n != name]
                if clash:
                    up.conflicts[name] = (f'{exposed} would also name {", ".join(sorted(clash))}; '
                                          f'neither is offered')
                    continue
                if exposed in out:
                    up.conflicts[name] = f'{exposed} is already exposed by upstream {out[exposed][0].config.id}'
                    continue
                out[exposed] = (up, name, item)
        return out

    def _serving(self, up: _Upstream, name: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The item to register for an upstream tool: the current one when approved; under
        ``on_change: hold``, the previously approved version while a changed (or now invalid)
        definition waits for review; else None."""
        rec = (getattr(up, 'records', None) or {}).get(f'tool:{name}') or {}
        status = rec.get('status') or 'pending'
        if status == 'approved':
            return item
        if status == 'changed' and up.config.on_change == 'hold' and isinstance(rec.get('approved_definition'), dict):
            return {**item, 'definition': rec['approved_definition'], 'hash': rec.get('hash'), 'held': True}
        return None

    def _sync_registry(self, changed_upstream: Optional[str] = None) -> None:
        """Make the registry's federated tools match the approved set (thread-safe, idempotent);
        the registry announces the result once, not once per federated tool."""
        from sajha.tools.tools_registry import registry_bulk
        with registry_bulk(self.registry):
            self._sync_registry_now(changed_upstream)

    def _sync_registry_now(self, changed_upstream: Optional[str] = None) -> None:
        reg = self.registry
        with self._lock:
            desired = self._desired_tools()
            changed = False
            for name in list(self._tools):
                tool = self._tools[name]
                keep = desired.get(name)
                if keep is None or keep[2]['hash'] != tool.config.get('_federation_hash') \
                        or keep[0].config is not tool.manager_config:
                    self._tools.pop(name, None)
                    self._exposed.pop(name, None)
                    if reg is not None and reg.get_tool(name) is tool:
                        reg.unregister_tool(name)
                    changed = True
            for name, (up, upstream_name, item) in desired.items():
                if name in self._tools:
                    continue
                existing = reg.get_tool(name) if reg is not None else None
                if existing is not None and not isinstance(existing, FederatedTool):
                    up.conflicts[upstream_name] = f'{name} is a native SAJHA tool; the native tool wins'
                    continue
                extra = {'_federation_hash': item['hash']}
                if up.config.cache_ttl:
                    extra['cache_ttl'] = up.config.cache_ttl
                if up.config.cache_per_user is not None:
                    extra['cache_per_user'] = up.config.cache_per_user
                tool = FederatedTool(self, up.config.id, upstream_name, item['definition'], extra)
                tool.manager_config = up.config
                self._tools[name] = tool
                self._exposed[name] = (up.config.id, upstream_name)
                if reg is not None:
                    reg.register_tool(tool)
                changed = True
            # prompts
            prompts: Dict[str, Tuple[str, str]] = {}
            if self.settings.enabled:
                for uid, up in self._upstreams.items():
                    if not up.config.enabled or not up.config.expose_prompts:
                        continue
                    for name, item in up.items['prompt'].items():
                        if self._status(up, 'prompt', name) == 'approved':
                            prompts.setdefault(item['exposed'], (uid, name))
            prompts_changed = prompts != self._prompts
            self._prompts = prompts
            # MCP Apps views of the served tools (resolved back to their upstream on read)
            views: Dict[str, Tuple[str, str, List[str]]] = {}
            for name in sorted(self._tools):
                tool = self._tools[name]
                ui = ((tool.definition.get('_meta') or {}).get('ui') or {}).get('resourceUri')
                if isinstance(ui, str) and ui.startswith(VIEW_PREFIX):
                    original = unquote(ui[len(VIEW_PREFIX):].partition('/')[2])
                    views.setdefault(ui, (tool.upstream_id, original, []))[2].append(name)
            self._views = views
        if changed:
            self._notify_registry()
        if prompts_changed:
            try:
                from sajha.core.change_bus import get_change_bus
                bus = get_change_bus()
                if hasattr(bus, 'prompts_changed'):
                    bus.prompts_changed()
            except Exception:
                pass

    def _notify_registry(self) -> None:
        """Re-sync listeners of the registry (the tool-search index used by Ask SAJHA)."""
        reg = self.registry
        notify = getattr(reg, '_notify_reload', None)
        if callable(notify):
            try:
                notify()
            except Exception as e:
                logger.debug(f'federation: registry listeners: {e}')

    def _reregister_after_reload(self) -> None:
        """ToolsRegistry.reload_all_tools() clears every tool; put the federated ones back."""
        reg = self.registry
        with self._lock:
            for name, tool in list(self._tools.items()):
                existing = reg.get_tool(name)
                if existing is tool:
                    continue
                if existing is None:
                    reg.register_tool(tool)

    # ══ calls ══════════════════════════════════════════════════════
    def call_tool(self, tool: FederatedTool, arguments: Dict[str, Any], ctx=None) -> Dict[str, Any]:
        """Route one call; returns the upstream CallToolResult as a dict (content, structuredContent).
        Raises InputRequired (MRTR), FederatedToolError (isError) or a RuntimeError subclass."""
        from sajha.core.mcp_mrtr import InputRequired
        up = self._upstreams.get(tool.upstream_id)
        if up is None or not self.settings.enabled or not up.config.enabled:
            raise FederationError(f'upstream {tool.upstream_id} is not enabled')
        if self._tools.get(tool.name) is not tool:
            raise FederationError(f'{tool.name} is no longer exposed by upstream {tool.upstream_id}')
        if up.conn is None:
            raise UpstreamUnavailable(f'upstream {tool.upstream_id} is not connected')
        from sajha.federation.user_tokens import PER_USER_MODES, auth_mode
        mode = auth_mode(up.config)
        user_cred = None
        if mode in PER_USER_MODES:
            # the caller's own token (an OAuth one refreshed when due), or "connect your account"
            # (ConnectedAccountRequired) before anything is sent; never another user's token or a
            # shared credential
            from sajha.accounts.injection import caller_user_id
            from sajha.federation.user_tokens import get_tokens, header_for
            uid = caller_user_id()
            token = get_tokens().resolve(up.config, uid, tool=tool.name)
            user_cred = (uid, token, header_for(up.config, token))
        service_user = None
        if mode == 'service_with_user':
            # the shared service identity, with the caller named in the audit header; anonymous refused
            from sajha.accounts.injection import caller_user_id
            from sajha.federation.user_tokens import on_behalf_header
            uid = caller_user_id()
            try:
                service_user = (uid,) + tuple(on_behalf_header(up.config, uid))
            except PermissionError as e:
                raise FederationError(str(e)) from None
        if up.limiter is not None and not up.limiter.is_allowed('calls'):
            raise FederationError(f'rate limit reached for upstream {tool.upstream_id} '
                                  f'({up.config.max_calls_per_minute} calls per minute)')
        timeout = float(up.config.timeout_seconds or self.settings.default_timeout_seconds)
        state = (getattr(ctx, 'state', None) or {}).get(STATE_KEY) if ctx is not None else None
        responses, request_state = None, None
        if isinstance(state, dict) and state.get('tool') == tool.name:
            keys = set(state.get('keys') or [])
            responses = {k: v for k, v in (getattr(ctx, 'input_responses', None) or {}).items() if k in keys}
            request_state = state.get('rs')
        progress = None
        if ctx is not None and getattr(ctx, 'progress_token', None) is not None:
            async def progress(p, total=None, message=None):
                try:
                    ctx.emit_progress(p, total, message)
                except Exception:
                    pass
        ann = tool.definition.get('annotations') or {}
        safe_to_retry = bool(ann.get('readOnlyHint') or ann.get('idempotentHint'))
        attempts = 1 + (up.config.retries if safe_to_retry else 0)
        adm = up.admission                          # max_in_flight and the queue (scale.Admission)
        if adm is not None:
            adm.acquire()                           # UpstreamOverloaded: refused before anything is sent
        started = time.time()
        up.calls += 1
        up.last_call = started
        from sajha.observability.tracing import inject as _inject_trace
        from sajha.core import inner_calls
        try:                                        # the chain budget across proxies (Federation.md)
            chain_depth = inner_calls.proxy_outgoing(tool.name)
        except inner_calls.CallTooDeep as e:
            up.calls -= 1
            if adm is not None:
                adm.release()
            raise FederationError(str(e))
        trace_meta = _inject_trace({}) or {}        # W3C context, sent as params._meta.traceparent
        trace_meta[inner_calls.PROXY_META_KEY] = {'depth': chain_depth}
        try:
            # Per-user token passthrough (auth.type connected_account): the caller's own token,
            # on a connection of its own; ConnectedAccountRequired when the caller has none.
            user_token = self._caller_token(up, tool) if self._passthrough(up) else None
            # a 2025-11-25 caller that can answer the upstream's requests to its client (sampling,
            # elicitation, roots): the call gets a connection of its own whose requests go to that caller
            from sajha.federation import relay as _relay
            client_relay = (_relay.current(tool.name) if user_cred is None and service_user is None
                            and user_token is None and self._modern(up) is False else None)
            tried: List[UpstreamConnection] = []    # the shared connections this call tried (pool, replicas)
            attempt = 0
            while True:
                try:
                    if user_cred is not None:
                        result = self._call_token_user(up, tool, user_cred, arguments, timeout, progress,
                                                       responses, request_state, ctx, trace_meta)
                    elif service_user is not None:
                        result = self._call_service_with_user(up, tool, service_user, arguments, timeout,
                                                              progress, responses, request_state, ctx, trace_meta)
                    elif user_token is not None:
                        result = self._call_as_user(up, tool, user_token, arguments, timeout, progress,
                                                    responses, request_state, ctx, trace_meta)
                    elif client_relay is not None:
                        result = self._wait(up.conn.call_tool_relayed(client_relay, tool.upstream_name, arguments,
                                                                      timeout, progress, trace_meta),
                                            timeout + min(timeout, 30.0) + 5.0, ctx)
                    else:
                        result = self._call_member(up, tried, tool, arguments, timeout, progress, responses,
                                                   request_state, ctx, trace_meta)
                    break
                except UpstreamUnavailable as e:
                    from sajha.federation.connection import UpstreamNotConnected
                    if (isinstance(e, UpstreamNotConnected) and tried
                            and len(tried) < len(self._members(up))):
                        continue                    # nothing was sent: the next member or replica takes it
                    attempt += 1
                    if attempt >= attempts:
                        raise
                    time.sleep(min(0.25 * attempt, 1.0))
            from mcp_types import InputRequiredResult
            if isinstance(result, InputRequiredResult):
                ir = result.model_dump(mode='json', by_alias=True, exclude_none=True)
                requests = ir.get('inputRequests') or {}
                if ctx is None or not hasattr(ctx, 'require_input'):
                    raise FederationError(f'{tool.name} needs client input (elicitation); call it over '
                                          f'MCP 2026-07-28 from a client that can answer')
                raise InputRequired(requests, {STATE_KEY: {'tool': tool.name, 'rs': ir.get('requestState'),
                                                           'keys': sorted(requests)}})
            data = result.model_dump(mode='json', by_alias=True, exclude_none=True)
            data.pop('_meta', None)
            data.pop('resultType', None)
            if data.pop('isError', False):
                text = ' '.join(b.get('text', '') for b in data.get('content') or [] if b.get('type') == 'text')
                raise FederatedToolError(redact(text or f'{tool.name} failed upstream',
                                                up.conn.secret_values() + (list(user_cred[1:2]) if user_cred else []))
                                         [:2000], data)
            return data
        except InputRequired:
            raise
        except Exception:
            up.failures += 1
            raise
        finally:
            up.total_ms += (time.time() - started) * 1000
            if adm is not None:
                adm.release()

    def _call_member(self, up: _Upstream, tried: List[UpstreamConnection], tool: FederatedTool, arguments,
                     timeout, progress, responses, request_state, ctx, trace_meta):
        """tools/call on the shared credentials, on one pool connection (scale.pick_member: connected,
        healthy replica, least busy); a retry or failover takes another one."""
        member = self._pick(up, tried) or up.conn
        tried.append(member)
        member.in_flight += 1
        t0 = time.time()
        ok = True
        try:
            return self._wait(member.call_tool(tool.upstream_name, arguments, timeout, progress, responses,
                                               request_state, trace_meta), timeout + 5.0, ctx)
        except (UpstreamUnavailable, UpstreamTimeout):
            ok = False
            raise
        finally:
            member.in_flight -= 1
            scale.record_outcome(member, ok, (time.time() - t0) * 1000)

    def relays_for(self, tool: FederatedTool) -> bool:
        """Would a call of ``tool`` relay its upstream's requests to the client (a session-based upstream
        on its shared credentials)? The transport streams such a call only then."""
        up = self._upstreams.get(getattr(tool, 'upstream_id', None))
        if up is None or up.conn is None or self._passthrough(up):
            return False
        from sajha.federation.user_tokens import PER_USER_MODES, auth_mode
        mode = auth_mode(up.config)
        return mode not in PER_USER_MODES and mode != 'service_with_user' and self._modern(up) is False

    @staticmethod
    def _passthrough(up: _Upstream) -> bool:
        return (up.config.auth or {}).get('type') == 'connected_account'

    @staticmethod
    def _caller_token(up: _Upstream, tool: FederatedTool):
        """The calling user's token for the upstream's provider (sajha/accounts); raises
        ConnectedAccountRequired (an InputRequired) when there is no usable link."""
        from sajha.accounts.injection import caller_user_id
        from sajha.accounts.service import get_service
        a = up.config.auth or {}
        return get_service().resolve(caller_user_id(), str(a.get('provider')), list(a.get('scopes') or []),
                                     tool=tool.name)

    def _call_as_user(self, up: _Upstream, tool: FederatedTool, token, arguments, timeout, progress,
                      responses, request_state, ctx, trace_meta=None):
        """tools/call with the user's bearer token; on HTTP 401 refresh once, then ask to reconnect."""
        from sajha.accounts.service import get_service
        from sajha.federation.connection import UpstreamUnauthorized
        for attempt in range(2):
            try:
                return self._wait(up.conn.call_tool_as(token.access_token, tool.upstream_name, arguments, timeout,
                                                       progress, responses, request_state, trace_meta),
                                  timeout + 5.0, ctx)
            except UpstreamUnauthorized:
                svc = get_service()
                if attempt == 0:
                    token = svc.refresh_after_rejection(token, tool=tool.name)
                    continue
                svc.mark_rejected(token, f'upstream {up.config.id} refused the token')
                raise svc.required(token.provider.id, 'reauth_required', token.user_id, tool=tool.name)
        raise AssertionError('unreachable')

    # ── token_user: the caller's own token ─────────────────────────
    def _modern(self, up: _Upstream) -> Optional[bool]:
        """True: a stateless 2026-07-28 upstream; False: session-based; None: not known yet."""
        cfg = up.config
        if cfg.transport == 'sse' or cfg.protocol == 'legacy':
            return False
        if cfg.protocol == '2026-07-28':
            return True
        pv = up.conn.protocol_version if up.conn is not None else None
        return (pv >= '2026-07-28') if pv else None

    def _call_token_user(self, up: _Upstream, tool: FederatedTool, cred, arguments, timeout, progress,
                         responses, request_state, ctx, trace_meta=None):
        """tools/call as the caller: on a 2026-07-28 upstream the header rides on this call's own
        connection; on a session-based one, in the caller's own session (opened on first use). A
        refused token (HTTP 401/403) is the vendor's answer: passed back, the connection marked
        "needs re-connect", never retried as anyone else. oauth_user: an HTTP 401 first refreshes the
        caller's token once and retries with it; a 403 (for example a scope the user did not grant)
        is passed back without marking the connection."""
        from sajha.federation.connection import UpstreamUnauthorized
        from sajha.federation.user_tokens import auth_mode, get_tokens, header_for
        uid, token, (header, value) = cred
        oauth = auth_mode(up.config) == 'oauth_user'
        connect_wait = min(timeout, 30.0)
        tokens = get_tokens()
        seen = [token, value]
        for attempt in range(2):
            try:
                if self._modern(up):
                    coro = up.conn.call_tool_with_header(header, value, tool.upstream_name, arguments, timeout,
                                                         progress, responses, request_state, trace_meta)
                else:
                    coro = self._call_in_session(up, uid, header, value, tool.upstream_name, arguments, timeout,
                                                 progress, responses, request_state, trace_meta)
                return self._wait(coro, timeout + connect_wait + 5.0, ctx)
            except UpstreamUnauthorized as e:
                if oauth and e.status == 401 and attempt == 0:
                    token = tokens.refresh_after_401(up.config, uid, tool=tool.name)   # or "re-connect"
                    header, value = header_for(up.config, token)
                    seen += [token, value]
                    continue
                vendor = redact(e.vendor or '', seen).strip()
                if oauth and e.status == 403:
                    err = FederatedToolError(
                        f'{up.config.display_title} refused this call for your account (HTTP 403)'
                        + (f': {vendor}' if vendor else '') + '. If it needs permissions you did not grant, '
                        f're-connect at {tokens.connect_url(up.config.id)} and allow them.',
                        {'content': [], 'isError': True})
                else:
                    tokens.mark_needs_reconnect(up.config.id, uid, f'the server refused the token (HTTP {e.status})')
                    err = FederatedToolError(
                        f'{up.config.display_title} refused your token (HTTP {e.status})'
                        + (f': {vendor}' if vendor else '') + '. Your connection is marked "needs re-connect"; '
                        + (f'sign in again at {tokens.connect_url(up.config.id)}.' if oauth
                           else f'replace the token at {tokens.connect_url(up.config.id)}.'),
                        {'content': [], 'isError': True})
                err.caller_specific = True          # one user's credential: not the upstream's failure (breaker)
                raise err from None
        raise AssertionError('unreachable')

    # ── service_with_user: the service identity, naming the caller ──
    def _service_auth(self, up: _Upstream):
        if not up.service_auth_built:
            from sajha.federation.auth import build_auth
            up.service_auth = build_auth(up.config, self.settings)
            up.service_auth_built = True
        return up.service_auth

    def _call_service_with_user(self, up: _Upstream, tool: FederatedTool, cred, arguments, timeout, progress,
                                responses, request_state, ctx, trace_meta=None):
        """tools/call with the shared service credential and the caller named in ``user_header``: on a
        2026-07-28 upstream on this call's own connection; on a session-based one in a session per
        user (the header is per connection). A 401/403 is the vendor's answer, passed back; never
        retried without the header or as anyone else."""
        from sajha.federation.connection import UpstreamUnauthorized
        uid, header, value = cred
        inner = self._service_auth(up)
        connect_wait = min(timeout, 30.0)
        try:
            if self._modern(up):
                coro = up.conn.call_tool_with_header(header, value, tool.upstream_name, arguments, timeout,
                                                     progress, responses, request_state, trace_meta, inner=inner)
            else:
                coro = self._call_in_session(up, uid, header, value, tool.upstream_name, arguments, timeout,
                                             progress, responses, request_state, trace_meta, inner=inner)
            return self._wait(coro, timeout + connect_wait + 5.0, ctx)
        except UpstreamUnauthorized as e:
            secrets = list(getattr(inner, 'secret_values', lambda: [])()) if inner is not None else []
            vendor = redact(e.vendor or '', secrets).strip()
            if e.status == 403:
                msg = (f'{up.config.display_title} refused this call for {uid} (HTTP 403)'
                       + (f': {vendor}' if vendor else '') + '. The service identity may not act for this user.')
            else:
                msg = (f'{up.config.display_title} refused the shared service credential (HTTP {e.status})'
                       + (f': {vendor}' if vendor else '') + '. An administrator must fix auth.service.')
            err = FederatedToolError(msg, {'content': [], 'isError': True})
            err.caller_specific = e.status == 403        # one user refused: not the upstream's failure
            raise err from None

    async def _call_in_session(self, up: _Upstream, uid: str, header: str, value: str, name: str, arguments,
                               timeout: float, progress, responses, request_state, meta, inner=None):
        from sajha.federation.connection import UpstreamUnauthorized
        s = await self._acquire_session(up, uid, header, value, inner)
        try:
            try:
                await s.conn.ready_client(min(timeout, 30.0))
                result = await s.conn.call_tool(name, arguments, timeout, progress, responses, request_state, meta)
            except UpstreamUnauthorized:
                raise
            except Exception as e:
                refused = s.conn.refusal(e, True)
                if refused is not None:
                    raise refused from None
                raise
        except BaseException:
            if s.conn.refused is not None or s.conn.state in ('disabled',):
                await self._close_sessions(up, [uid], only=s)
            raise
        finally:
            s.busy -= 1
            s.last_used = time.time()
        if s.conn.protocol_version and s.conn.protocol_version >= '2026-07-28':
            await self._close_sessions(up, [uid], only=s)      # stateless after all: nothing to keep
        return result

    async def _acquire_session(self, up: _Upstream, uid: str, header: str, value: str,
                               inner=None) -> _UserSession:
        fp = hashlib.sha256(f'{header}\n{value}'.encode('utf-8')).hexdigest()
        s = up.user_sessions.get(uid)
        if s is not None and (s.fingerprint != fp or s.conn.refused is not None or s.conn.state == 'disabled'):
            await self._close_sessions(up, [uid], only=s)       # token replaced, refused or closed
            s = None
        if s is None:
            await self._sweep_idle(up)
            if len(up.user_sessions) >= self.settings.per_user_sessions_max:
                idle = sorted((x for x in up.user_sessions.items() if x[1].busy == 0), key=lambda x: x[1].last_used)
                if not idle:
                    raise FederationError(f'upstream {up.config.id}: every per-user session is busy '
                                          f'(federation.per_user_sessions_max = {self.settings.per_user_sessions_max})')
                await self._close_sessions(up, [idle[0][0]])
            conn = up.conn.user_connection(header, value, inner)
            conn.start()
            s = _UserSession(conn, fp)
            up.user_sessions[uid] = s
            self._ensure_sweeper()
        s.busy += 1
        s.last_used = time.time()
        return s

    async def _close_sessions(self, up: _Upstream, uids: List[str], only: Optional[_UserSession] = None) -> None:
        stops = []
        for uid in uids:
            s = up.user_sessions.get(uid)
            if s is None or (only is not None and s is not only):
                continue
            up.user_sessions.pop(uid, None)
            stops.append(s.conn.stop(timeout=2.0))
        if stops:
            await asyncio.gather(*stops, return_exceptions=True)

    async def _sweep_idle(self, up: _Upstream) -> None:
        cutoff = time.time() - self.settings.per_user_session_idle_seconds
        idle = [uid for uid, s in up.user_sessions.items() if s.busy == 0 and s.last_used < cutoff]
        if idle:
            await self._close_sessions(up, idle)

    def _ensure_sweeper(self) -> None:
        if getattr(self, '_sweeper', None) is not None and not self._sweeper.done():
            return

        async def sweep():
            period = max(0.5, min(self.settings.per_user_session_idle_seconds / 2.0, 30.0))
            while any(u.user_sessions for u in self._upstreams.values()):
                await asyncio.sleep(period)
                for up in list(self._upstreams.values()):
                    await self._sweep_idle(up)
        self._sweeper = asyncio.ensure_future(sweep())

    def user_sessions(self, upstream_id: str) -> List[str]:
        """The users with an open session on a session-based token_user upstream (status, tests)."""
        up = self._upstreams.get(upstream_id)
        return sorted(up.user_sessions) if up else []

    def close_user_sessions(self, upstream_id: str, user_id: Optional[str] = None) -> None:
        """Close one user's session (token removed or replaced) or every session of the upstream."""
        up = self._upstreams.get(upstream_id)
        if up is None or not up.user_sessions or self._loop is None:
            return
        uids = [user_id] if user_id else list(up.user_sessions)
        try:
            self._run(self._close_sessions(up, uids), timeout=10)
        except Exception as e:
            logger.debug(f'federation: closing per-user sessions of {upstream_id}: {e}')

    def test_user_token(self, upstream_id: str, token: str, timeout: Optional[float] = None) -> List[str]:
        """The connect page's test call: tools/list with ``token``. Returns the tool names; the tools
        join the upstream's discovery (the union of what users see). Raises TokenRejected."""
        from sajha.federation.connection import UpstreamUnauthorized
        from sajha.federation.user_tokens import TokenRejected, header_for
        up = self._upstreams.get(upstream_id)
        if up is None:
            raise TokenRejected(f'There is no proxied server {upstream_id}.')
        if not self.settings.enabled or not up.config.enabled:
            raise TokenRejected(f'{up.config.display_title} is not enabled, so the token cannot be tested now.')
        header, value = header_for(up.config, token)
        t = float(timeout or up.config.timeout_seconds or self.settings.default_timeout_seconds)
        probe = up.conn if up.conn is not None else UpstreamConnection(up.config, self.settings, self._discover)
        try:
            tools = self._run(probe.list_tools_with_header(header, value, t), timeout=t * 2 + 10)
        except UpstreamUnauthorized as e:
            vendor = redact(e.vendor or '', [token, value]).strip()
            raise TokenRejected(f'{up.config.display_title} refused this token (HTTP {e.status})'
                                + (f': {vendor}' if vendor else '') + '. Check it and its permissions.') from None
        except Exception as e:
            raise TokenRejected(f'{up.config.display_title} could not be reached to test the token: '
                                f'{redact(describe(e), [token, value])}') from None
        dump = [x.model_dump(mode='json', by_alias=True, exclude_none=True) for x in tools]
        for d in dump:
            if isinstance(d.get('name'), str) and d['name'] not in up.user_tools:
                up.user_tools[d['name']] = d
                up.user_tools_new = True
        return [d.get('name') for d in dump]

    def user_connected(self, upstream_id: str) -> None:
        """A user saved a token: discovery can use it now (the first user), and tools only their token
        lists join the catalog (the union)."""
        up = self._upstreams.get(upstream_id)
        conn = up.conn if up is not None else None
        if conn is None or self._loop is None:
            return
        if conn.state != 'connected' or conn.waiting_for_user:
            self._loop.call_soon_threadsafe(conn.kick)
        elif getattr(up, 'user_tools_new', False):
            up.user_tools_new = False
            self._submit(conn.request_refresh())

    def _wait(self, coro, timeout: float, ctx=None):
        """Wait for a coroutine on the federation loop. When the caller is cancelled (a dropped
        2026-07-28 stream or task cancel: ``ctx.cancelled``; a 2025-11-25
        ``notifications/cancelled``: ``mcp_cancellation``), cancel it: the SDK then tells the
        upstream (``notifications/cancelled``, or on a 2026-07-28 upstream the request's
        stream is closed), so the upstream stops its work too."""
        from sajha.core import mcp_cancellation
        fut = self._submit(coro)
        deadline = time.time() + timeout
        while True:
            try:
                return fut.result(timeout=0.2)
            except concurrent.futures.TimeoutError:
                if fut.done():          # the coroutine's own TimeoutError (UpstreamTimeout), not the poll's
                    raise
                if (ctx is not None and getattr(ctx, 'cancelled', False)) or mcp_cancellation.is_cancelled():
                    fut.cancel()
                    raise FederationError('cancelled by the client')
                if time.time() >= deadline:
                    fut.cancel()
                    raise UpstreamTimeout(f'no answer within {timeout:g}s')
            except concurrent.futures.CancelledError:
                raise FederationError('cancelled')

    # ── prompts ────────────────────────────────────────────────────
    def prompt_definitions(self) -> List[Dict[str, Any]]:
        out = []
        with self._lock:
            for exposed, (uid, name) in sorted(self._prompts.items()):
                up = self._upstreams.get(uid)
                item = up.items['prompt'].get(name) if up else None
                if item:
                    out.append(dict(item['definition']))
        return out

    def has_prompt(self, name: str) -> bool:
        return isinstance(name, str) and name in self._prompts

    def get_prompt(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        uid, upstream_name = self._prompts[name]
        up = self._upstreams[uid]
        if up.conn is None:
            raise UpstreamUnavailable(f'upstream {uid} is not connected')
        timeout = float(up.config.timeout_seconds or self.settings.default_timeout_seconds)
        args = {k: v if isinstance(v, str) else json.dumps(v) for k, v in (arguments or {}).items()}
        result = self._wait(up.conn.get_prompt(upstream_name, args, timeout), timeout + 5.0)
        data = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        data.pop('_meta', None)
        data.pop('resultType', None)
        if 'description' in data:
            data['description'], _ = screen_text(data['description'], self.settings.max_description_chars)
        return data

    # ── resources ──────────────────────────────────────────────────
    @staticmethod
    def resource_uri(upstream_id: str, uri: str) -> str:
        return f'{RESOURCE_SCHEME}://{upstream_id}/{quote(uri, safe="")}'

    def resource_definitions(self) -> List[Dict[str, Any]]:
        out = []
        if not self.settings.enabled:
            return out
        with self._lock:
            for uid in sorted(self._upstreams):
                up = self._upstreams[uid]
                if not up.config.enabled or not up.config.expose_resources:
                    continue
                for uri, item in sorted(up.items['resource'].items()):
                    if self._status(up, 'resource', uri) == 'approved':
                        out.append(dict(item['definition']))
        return out

    def owns_resource(self, uri: str) -> bool:
        return isinstance(uri, str) and uri.startswith(RESOURCE_SCHEME + '://')

    def read_resource(self, uri: str) -> Dict[str, Any]:
        from sajha.core.mcp_2025_11_25 import MCPError
        up, original = self._split(uri)
        uid = up.config.id if up is not None else '?'
        if not self._readable(up, original):          # an approved resource, or an approved template's expansion
            raise MCPError(-32002, 'Resource not found', {'uri': uri})
        if up.conn is None:
            raise MCPError(-32603, f'upstream {uid} is not connected')
        timeout = float(up.config.timeout_seconds or self.settings.default_timeout_seconds)
        result = self._wait(up.conn.read_resource(original, timeout), timeout + 5.0)
        data = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        for c in data.get('contents') or []:
            if isinstance(c, dict):
                c['uri'] = uri
        return {'contents': data.get('contents') or []}

    def _readable(self, up: Optional[_Upstream], original: str) -> bool:
        """An approved resource of the upstream, or a URI an approved template of it expands to."""
        if up is None or not self.settings.enabled or not up.config.enabled or not up.config.expose_resources:
            return False
        if original in up.items['resource'] and self._status(up, 'resource', original) == 'approved':
            return True
        return self._template_of(up, original) is not None

    def _template_of(self, up: _Upstream, original: str) -> Optional[str]:
        for tmpl in sorted(up.items['template']):
            if self._status(up, 'template', tmpl) == 'approved' and _template_regex(tmpl).fullmatch(original):
                return tmpl
        return None

    def _split(self, uri: str) -> Tuple[Optional[_Upstream], str]:
        rest = uri[len(RESOURCE_SCHEME) + 3:]
        uid, _, encoded = rest.partition('/')
        return self._upstreams.get(uid), unquote(encoded)

    # ── resource templates ────────────────────────────────────────
    @staticmethod
    def template_uri(upstream_id: str, template: str) -> str:
        """``sajha-federation://<id>/<template>``: literal parts percent-encoded like a resource URI,
        the ``{...}`` expressions kept, so a client expands it as usual and the expansion reads back
        as the upstream's own URI."""
        parts = _TEMPLATE_EXPR.split(template)
        return f'{RESOURCE_SCHEME}://{upstream_id}/' + ''.join(
            p if _TEMPLATE_EXPR.fullmatch(p) else quote(p, safe='') for p in parts)

    def template_definitions(self) -> List[Dict[str, Any]]:
        out = []
        if not self.settings.enabled:
            return out
        with self._lock:
            for uid in sorted(self._upstreams):
                up = self._upstreams[uid]
                if not up.config.enabled or not up.config.expose_resources:
                    continue
                for tmpl, item in sorted(up.items['template'].items()):
                    if self._status(up, 'template', tmpl) == 'approved':
                        out.append(dict(item['definition']))
        return out

    # ── completions ───────────────────────────────────────────────
    def owns_completion(self, ref: Dict[str, Any]) -> bool:
        if not isinstance(ref, dict):
            return False
        if ref.get('type') == 'ref/prompt':
            return self.has_prompt(ref.get('name'))
        return ref.get('type') == 'ref/resource' and self.owns_resource(ref.get('uri'))

    def complete(self, ref: Dict[str, Any], argument: Dict[str, Any],
                 context_arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """completion/complete for a federated prompt or resource template, answered by its upstream
        (no values when the item is not approved or the upstream does not offer completions)."""
        empty = {'completion': {'values': [], 'hasMore': False}}
        if ref.get('type') == 'ref/prompt':
            uid, upstream_name = self._prompts.get(ref.get('name'), (None, None))
            up = self._upstreams.get(uid) if uid else None
            upstream_ref = {'type': 'ref/prompt', 'name': upstream_name}
        else:
            up, original = self._split(str(ref.get('uri') or ''))
            if (up is None or not up.config.expose_resources or original not in up.items['template']
                    or self._status(up, 'template', original) != 'approved'):
                return empty
            upstream_ref = {'type': 'ref/resource', 'uri': original}
        if up is None or up.conn is None or 'completions' not in (up.conn.capabilities or {}):
            return empty
        timeout = float(up.config.timeout_seconds or self.settings.default_timeout_seconds)
        arg = {'name': str(argument.get('name') or ''), 'value': str(argument.get('value') or '')}
        ctx_args = {str(k): str(v) for k, v in (context_arguments or {}).items()} or None
        result = self._wait(up.conn.complete(upstream_ref, arg, ctx_args, timeout), timeout + 5.0)
        data = result.model_dump(mode='json', by_alias=True, exclude_none=True).get('completion') or {}
        values = []
        for v in (data.get('values') or [])[:100]:
            text, flagged = screen_text(str(v), _SCHEMA_TEXT_LIMIT)
            if text and not flagged:
                values.append(text)
        out = {'values': values, 'hasMore': bool(data.get('hasMore'))}
        if isinstance(data.get('total'), int):
            out['total'] = data['total']
        return {'completion': out}

    # ── resources/subscribe ───────────────────────────────────────
    def subscribe_problem(self, uri: str) -> Optional[str]:
        """Why SAJHA cannot pass on a subscription to this federated URI, or None."""
        up, original = self._split(uri)
        if not self._readable(up, original):
            return f'Resource not found: {uri}'
        caps = (up.conn.capabilities if up.conn is not None else {}) or {}
        if not (caps.get('resources') or {}).get('subscribe'):
            return f'upstream {up.config.id} does not offer resource subscriptions'
        return None

    def watch(self, holder: str, uri: str) -> None:
        """``holder`` (a 2025-11-25 session, a 2026-07-28 listen stream) subscribes to a federated URI;
        the upstream is subscribed while anyone holds it."""
        with self._lock:
            self._holders.setdefault(holder, set()).add(uri)
        self._push_watches(self._split(uri)[0])

    def unwatch(self, holder: str, uri: str) -> None:
        with self._lock:
            held = self._holders.get(holder)
            if held is not None:
                held.discard(uri)
                if not held:
                    self._holders.pop(holder, None)
        self._push_watches(self._split(uri)[0])

    def release(self, holder: str) -> None:
        with self._lock:
            uris = self._holders.pop(holder, set())
        for up in {id(u): u for u in (self._split(x)[0] for x in uris) if u is not None}.values():
            self._push_watches(up)

    def watched_uris(self) -> List[str]:
        with self._lock:
            return sorted({u for held in self._holders.values() for u in held})

    def _watched_originals(self, upstream_id: str) -> set:
        prefix = f'{RESOURCE_SCHEME}://{upstream_id}/'
        with self._lock:
            return {unquote(u[len(prefix):]) for held in self._holders.values() for u in held if u.startswith(prefix)}

    def _push_watches(self, up: Optional[_Upstream]) -> None:
        if up is None or up.conn is None or self._loop is None:
            return
        uris = self._watched_originals(up.config.id)
        self._loop.call_soon_threadsafe(up.conn.set_watched, uris)

    def _prune_holders(self) -> None:
        """Forget the subscriptions of 2025-11-25 sessions that ended without unsubscribing."""
        stale = [h for h in list(self._holders) if h.startswith('session:')]
        if not stale:
            return
        try:
            from sajha.core.mcp_sessions import get_session_store
            store = get_session_store()
            for h in stale:
                if store.get(h[len('session:'):]) is None:
                    self.release(h)
        except Exception as e:
            logger.debug(f'federation: pruning subscriptions: {e}')

    def _resource_updated(self, upstream_id: str, uri: str) -> None:
        """An upstream says one of its resources changed: tell SAJHA's subscribers, by SAJHA's URI."""
        try:
            from sajha.core.change_bus import RESOURCE_UPDATED, get_change_bus
            get_change_bus().publish(RESOURCE_UPDATED, self.resource_uri(upstream_id, uri))
        except Exception as e:
            logger.debug(f'federation: resource update from {upstream_id}: {e}')

    # ── MCP Apps views (ui://) ────────────────────────────────────
    @staticmethod
    def view_uri(upstream_id: str, uri: str) -> str:
        return f'{VIEW_PREFIX}{upstream_id}/{quote(uri, safe="")}'

    def owns_view(self, uri: Any) -> bool:
        return isinstance(uri, str) and uri.startswith(VIEW_PREFIX)

    def has_view(self, uri: Any) -> bool:
        return isinstance(uri, str) and uri in self._views

    def view_definitions(self, can_see_tool: Callable[[str], bool]) -> List[Dict[str, Any]]:
        """The views of the served tools the caller may see, as resources/list entries."""
        from sajha.core.mcp_apps import APP_MIME_TYPE
        out = []
        for uri, (uid, original, tools) in sorted(self._views.items()):
            visible = [t for t in tools if can_see_tool(t)]
            if not visible:
                continue
            up = self._upstreams.get(uid)
            prefix = up.config.effective_prefix if up else uid
            name = original[len('ui://'):] if original.startswith('ui://') else original
            out.append({'uri': uri, 'name': f'{prefix}{SEPARATOR}{name}'[:_TITLE_LIMIT], 'mimeType': APP_MIME_TYPE,
                        'description': f'MCP App view of {", ".join(visible)} (proxied from {uid})'})
        return out

    def read_view(self, uri: str, can_see_tool: Callable[[str], bool]) -> Dict[str, Any]:
        """resources/read of a federated view: from its upstream, only as an MCP App document within
        SAJHA's size limit, with the upstream's CSP domains and permissions removed (a view gets no
        network access and no extra permissions, like SAJHA's own)."""
        from sajha.core.mcp_2025_11_25 import MCPError
        from sajha.core.mcp_apps import APP_MIME_TYPE, MAX_VIEW_BYTES
        entry = self._views.get(uri)
        if entry is None or not any(can_see_tool(t) for t in entry[2]):
            raise MCPError(-32002, 'Resource not found', {'uri': uri})
        uid, original, _tools = entry
        up = self._upstreams.get(uid)
        if up is None or up.conn is None:
            raise MCPError(-32603, f'upstream {uid} is not connected')
        timeout = float(up.config.timeout_seconds or self.settings.default_timeout_seconds)
        result = self._wait(up.conn.read_resource(original, timeout), timeout + 5.0)
        data = result.model_dump(mode='json', by_alias=True, exclude_none=True)
        contents = []
        for c in data.get('contents') or []:
            if not isinstance(c, dict) or str(c.get('mimeType') or '').replace(' ', '') != APP_MIME_TYPE:
                continue
            body = c.get('text') if 'text' in c else c.get('blob')
            if not isinstance(body, str) or len(body.encode('utf-8')) > MAX_VIEW_BYTES:
                raise MCPError(-32603, f'view {original} from upstream {uid} is not a usable MCP App document '
                                       f'(at most {MAX_VIEW_BYTES} bytes)')
            item = {'uri': uri, 'mimeType': APP_MIME_TYPE, ('text' if 'text' in c else 'blob'): body}
            ui = ((c.get('_meta') or {}).get('ui') or {}) if isinstance(c.get('_meta'), dict) else {}
            item['_meta'] = {'ui': {'prefersBorder': bool(ui.get('prefersBorder', True))}}
            contents.append(item)
        if not contents:
            raise MCPError(-32603, f'upstream {uid} returned no {APP_MIME_TYPE} document for {original}')
        return {'contents': contents}

    # ══ administration ═════════════════════════════════════════════
    def set_item_status(self, upstream_id: str, kind: str, name: str, action: str) -> int:
        """approve | reject | disable | enable | reset | approve_all. Returns the number changed."""
        up = self._upstreams.get(upstream_id)
        if up is None:
            raise KeyError(upstream_id)
        if kind not in KINDS:
            raise ValueError(f'kind must be one of {", ".join(KINDS)}')
        to = {'approve': 'approved', 'reject': 'rejected', 'disable': 'disabled', 'enable': 'approved',
              'reset': 'pending', 'approve_all': 'approved'}.get(action)
        if to is None:
            raise ValueError('action must be approve, reject, disable, enable, reset or approve_all')
        with self._lock:
            records = dict(getattr(up, 'records', None) or self.store.items(upstream_id))
            names = list(up.items[kind]) if action == 'approve_all' else [name]
            n = 0
            for ident in names:
                item = up.items[kind].get(ident)
                if item is None:
                    if action == 'approve_all':
                        continue
                    raise KeyError(f'{kind} {ident}')
                rk = f'{kind}:{ident}'
                rec = dict(records.get(rk) or {'first_seen': self.store.now()})
                if action == 'approve_all' and rec.get('status') in ('approved', 'rejected', 'disabled'):
                    continue
                if action == 'enable' and rec.get('status') != 'disabled':
                    continue
                if to == 'approved' and rec.get('reason') and rec.get('current_hash') == item['hash']:
                    if action == 'approve_all':
                        continue
                    raise ValueError(f'{kind} {ident} cannot be approved: {rec["reason"]}')
                rec['status'] = to
                rec['hash'] = item['hash']
                rec['updated_at'] = self.store.now()
                if to == 'approved':
                    rec['approved_definition'] = item['definition']
                    rec.pop('reason', None)
                records[rk] = rec
                n += 1
            self.store.set_items(upstream_id, records)
            up.records = records
        self._sync_registry(upstream_id)
        return n

    def refresh(self, upstream_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        """Reconnect if needed and run a discovery now; returns the upstream's status."""
        up = self._upstreams.get(upstream_id)
        if up is None:
            raise KeyError(upstream_id)
        if not self.settings.enabled:
            raise FederationError('federation is off (federation.enabled)')
        if not up.config.enabled:
            raise FederationError(f'upstream {upstream_id} is disabled')
        if up.conn is None:
            self._connect(up)
        conn = up.conn
        try:
            self._run(self._refresh_now(conn, timeout), timeout=timeout + 5)
        except Exception as e:
            raise FederationError(describe(e))
        return self.status(upstream_id)

    async def _refresh_now(self, conn: UpstreamConnection, timeout: float) -> None:
        await conn.ready_client(min(timeout, 15.0))
        await conn.request_refresh(wait=True, timeout=timeout)

    def test_connection(self, data: Dict[str, Any], timeout: float = 20.0) -> Dict[str, Any]:
        """Connect to an unsaved definition, list what it offers, disconnect."""
        cfg = self.validate_definition(data)

        async def probe():
            seen: Dict[str, Any] = {}

            async def on_discover(c):
                t = float(cfg.timeout_seconds or self.settings.default_timeout_seconds)
                caps = c.capabilities or {}
                seen['tools'] = [x.name for x in await c.list_all('tools', t)] if 'tools' in caps or not caps else []
                seen['prompts'] = [x.name for x in await c.list_all('prompts', t)] if 'prompts' in caps else []
                seen['resources'] = len(await c.list_all('resources', t)) if 'resources' in caps else 0
            conn = UpstreamConnection(cfg, self.settings, on_discover, refresh_seconds=0)
            conn.start()
            try:
                await conn.ready_client(timeout)
                await conn.request_refresh(wait=True, timeout=timeout)
                return {'ok': True, 'protocol_version': conn.protocol_version, 'server_info': conn.server_info,
                        **seen}
            except Exception as e:
                return {'ok': False, 'error': conn.last_error or describe(e)}
            finally:
                await conn.stop()
        return self._run(probe(), timeout=timeout * 2 + 10)

    # ── status ─────────────────────────────────────────────────────
    def status(self, upstream_id: Optional[str] = None) -> Any:
        if upstream_id is not None:
            up = self._upstreams.get(upstream_id)
            if up is None:
                raise KeyError(upstream_id)
            return self._status_of(up)
        return [self._status_of(self._upstreams[u]) for u in sorted(self._upstreams)]

    def _status_of(self, up: _Upstream) -> Dict[str, Any]:
        cfg = up.config
        conn = up.conn
        if not self.settings.enabled or not cfg.enabled:
            state = 'disabled'
        elif conn is None:
            state = 'connecting'
        else:
            state = conn.state
        secrets = conn.secret_values() if conn else []
        records = getattr(up, 'records', None) or self.store.items(cfg.id)
        items = []
        for kind in KINDS:
            for ident, item in sorted(up.items[kind].items()):
                rec = records.get(f'{kind}:{ident}') or {}
                d = item['definition']
                items.append({
                    'kind': kind, 'name': ident, 'exposed': item['exposed'],
                    'status': rec.get('status', 'pending'), 'flagged': bool(item['flagged']),
                    'title': d.get('title') or '', 'description': d.get('description') or '',
                    'annotations': d.get('annotations') or {},
                    'inputSchema': d.get('inputSchema') if kind == 'tool' else None,
                    'arguments': d.get('arguments') if kind == 'prompt' else None,
                    'registered': kind == 'tool' and item['exposed'] in self._tools,
                    'conflict': up.conflicts.get(ident) if kind == 'tool' else None,
                    'reason': rec.get('reason'),
                    'held': bool(kind == 'tool' and rec.get('status') == 'changed' and item['exposed'] in self._tools),
                    'first_seen': rec.get('first_seen'), 'updated_at': rec.get('updated_at'),
                })
        counts = {s: sum(1 for i in items if i['status'] == s) for s in STATUSES}
        try:
            from sajha.core.circuit_breaker import get_circuit_registry
            b = get_circuit_registry().get_breaker(cfg.effective_prefix + SEPARATOR + 'x')
            breaker = b.to_dict() if b else None
        except Exception:
            breaker = None
        ext = next((x for x in self.file_external if x['upstream'] == cfg.id), None) or _net_external(cfg.id)
        from sajha.federation.user_tokens import auth_mode
        mode = auth_mode(cfg)
        return {
            'auth_mode': mode,
            'auth_note': '',
            'user_sessions': len(up.user_sessions),
            'id': cfg.id, 'title': cfg.display_title, 'source': cfg.source, 'enabled': cfg.enabled,
            'vendor': (ext or {}).get('vendor') or self.file_vendors.get(cfg.id) or '',
            'external': ext is not None,                   # SAJHA Net design §5.6
            'tools': sum(1 for n, (uid, _t) in self._exposed.items() if uid == cfg.id and n in self._tools),
            'transport': cfg.transport, 'url': cfg.url if cfg.transport != 'stdio' else '',
            'command': cfg.command if cfg.transport == 'stdio' else '',
            'prefix': cfg.effective_prefix, 'state': state,
            'protocol_version': conn.protocol_version if conn else None,
            'server_info': conn.server_info if conn else {},
            'listening': bool(conn and conn.listening),
            'last_error': redact(conn.last_error or up.last_refresh_error or '', secrets) or None
            if conn else (up.last_refresh_error or None),
            'last_refresh': up.last_refresh,
            'calls': up.calls, 'failures': up.failures,
            'avg_ms': round(up.total_ms / up.calls, 1) if up.calls else None,
            'counts': counts, 'items': items, 'breaker': breaker,
            **self._scale_status(up),
            'definition': _masked_definition(cfg.to_dict(), secrets),
        }

    def _scale_status(self, up: _Upstream) -> Dict[str, Any]:
        """Pool, replicas, admission and the cluster-wide view (sajha/federation/scale.py)."""
        members = self._members(up)
        replicas = []
        for r, url in enumerate(up.config.replica_urls):
            mine = [c for c in members if c.replica == r]
            lat = [c.ewma_ms for c in mine if c.ewma_ms is not None]
            replicas.append({'replica': r, 'url': url if up.config.transport != 'stdio' else '',
                             'connections': len(mine), 'connected': sum(1 for c in mine if c.state == 'connected'),
                             'primary': any(c is up.conn for c in mine),
                             'in_flight': sum(c.in_flight for c in mine), 'fail_streak': max([c.fail_streak for c in mine] or [0]),
                             'latency_ms': round(sum(lat) / len(lat), 1) if lat else None})
        limit, queue = self._limits(up.config)
        adm = up.admission.snapshot() if up.admission is not None else {
            'limit': limit, 'queue': queue, 'queue_timeout_seconds': self.settings.queue_timeout_seconds,
            'in_flight': 0, 'waiting': 0, 'admitted': 0, 'queued_total': 0, 'shed': 0, 'peak_in_flight': 0}
        return {'pool': {'size': self._pool_size(up.config), 'connections': len(members),
                         'connected': sum(1 for c in members if c.state == 'connected')},
                'replicas': replicas, 'admission': adm,
                'cluster': self.health.summary(up.config.id) if self.health.last_read else None}

    def summary(self) -> Dict[str, Any]:
        return {'enabled': self.settings.enabled, 'require_approval': self.settings.require_approval,
                'allow_stdio': self.settings.allow_stdio, 'upstreams': len(self._upstreams),
                'exposed_tools': len(self._tools), 'config_errors': dict(self.config_errors)}

    def exposed_tool_names(self) -> List[str]:
        return sorted(self._tools)


# ── module singleton ────────────────────────────────────────────────

_manager: Optional[FederationManager] = None
_manager_lock = threading.Lock()


def init_federation(registry=None, settings: Optional[FederationSettings] = None,
                    store: Optional[FederationStore] = None) -> FederationManager:
    """Create (replacing any previous one), start, and return the process's manager."""
    global _manager
    with _manager_lock:
        old = _manager
        _manager = FederationManager(registry, settings, store)
    if old is not None:
        try:
            old.stop()
        except Exception:
            pass
    try:
        _manager.start()
    except Exception as e:      # federation never stops SAJHA from starting
        logger.error(f'Federation: start failed: {e}', exc_info=True)
    return _manager


def get_federation() -> Optional[FederationManager]:
    return _manager


def shutdown_federation() -> None:
    global _manager
    with _manager_lock:
        m, _manager = _manager, None
    if m is not None:
        m.stop()


def _template_regex(template: str):
    """A URI template (RFC 6570) as a pattern its expansions match: each expression is any text."""
    parts = _TEMPLATE_EXPR.split(template)
    return re.compile(''.join('(?s:.*?)' if _TEMPLATE_EXPR.fullmatch(p) else re.escape(p) for p in parts))


def _masked_definition(d: Dict[str, Any], secrets=None) -> Dict[str, Any]:
    """An upstream's definition as status shows it (console, admin API): credential-named header and
    environment values given raw (the owner's intranet stance allows them) are masked, every other value
    redacted like an error message, so the status never shows a credential (Adversarial QA Plan 3.6)."""
    from sajha.federation.mcp_servers import _SECRET_HEADER
    out = dict(d)
    for field_name in ('headers', 'env'):
        values = out.get(field_name)
        if isinstance(values, dict) and values:
            out[field_name] = {k: ('********' if _SECRET_HEADER.search(str(k)) and '${' not in str(v)
                                   else redact(v, secrets)) for k, v in values.items()}
    return out
