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
import fnmatch
import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

from sajha.federation.config import (ConfigError, FederationSettings, UpstreamConfig, SEPARATOR,
                                     namespaced)
from sajha.federation.connection import (UpstreamConnection, UpstreamTimeout, UpstreamUnavailable,
                                         describe)
from sajha.federation.security import (correct_annotations, redact, schema_problem, screen_schema,
                                       screen_text)
from sajha.federation.store import FederationStore
from sajha.federation.tool import FederatedTool, FederatedToolError

logger = logging.getLogger(__name__)

RESOURCE_SCHEME = 'sajha-federation'
STATE_KEY = 'sajha.federation'
STATUSES = ('pending', 'approved', 'changed', 'rejected', 'disabled', 'invalid')
KINDS = ('tool', 'prompt', 'resource')
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
        if config.max_calls_per_minute:
            from sajha.security import RateLimiter
            # Named per upstream: the window key is ratelimit:<name>:calls, so a shared
            # default name would put every upstream in one window.
            self.limiter = RateLimiter(max_requests=config.max_calls_per_minute, window_seconds=60,
                                       name=f'federation:{config.id}')


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
        await asyncio.gather(*(u.conn.stop() for u in self._upstreams.values() if u.conn is not None),
                             return_exceptions=True)

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
                    f'{cfg.id} ({_SOURCES.get(cfg.source, cfg.source)}) is not loaded')
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
            return False
        self._upstreams[cfg.id] = _Upstream(cfg)
        return True

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
            fresh = []
            for i in changed + added:
                if not self._add_loaded(new[i]):
                    self.file_external = [x for x in self.file_external if x['upstream'] != i]
                    continue
                fresh.append(self._upstreams[i])
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
            check_url(cfg.url, self.settings)
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
        if up.conn is not None and self._loop is not None:
            try:
                self._run(up.conn.stop(), timeout=10)
            except Exception as e:
                logger.debug(f'federation: stopping {up.config.id}: {e}')
        up.conn = None
        self._sync_registry()

    def _connect(self, up: _Upstream) -> None:
        if up.conn is not None:
            return
        loop = self._ensure_loop()
        up.conn = UpstreamConnection(up.config, self.settings, self._discover,
                                     refresh_seconds=up.config.refresh_interval_seconds)
        self._register_breaker(up.config)
        loop.call_soon_threadsafe(up.conn.start)

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
        dump = lambda m: m.model_dump(mode='json', by_alias=True, exclude_none=True)   # noqa: E731
        changed = self._reconcile(up, [dump(t) for t in tools], [dump(p) for p in prompts],
                                  [dump(r) for r in resources])
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
        return d, bool(f1 or f2 or f3 or f4 or f5)

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

    def _reconcile(self, up: _Upstream, tools: List[Dict], prompts: List[Dict], resources: List[Dict]) -> bool:
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
                   ('resource', resources, 'uri', self._screen_resource))
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
                discovered[kind][ident] = {'exposed': definition.get('name') if kind != 'resource'
                                           else definition['uri'], 'definition': definition, 'hash': h,
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
        started = time.time()
        up.calls += 1
        up.last_call = started
        from sajha.observability.tracing import inject as _inject_trace
        from sajha.core import inner_calls
        try:                                        # the chain budget across proxies (Federation.md)
            chain_depth = inner_calls.proxy_outgoing(tool.name)
        except inner_calls.CallTooDeep as e:
            up.calls -= 1
            raise FederationError(str(e))
        trace_meta = _inject_trace({}) or {}        # W3C context, sent as params._meta.traceparent
        trace_meta[inner_calls.PROXY_META_KEY] = {'depth': chain_depth}
        try:
            # Per-user token passthrough (auth.type connected_account): the caller's own token,
            # on a connection of its own; ConnectedAccountRequired when the caller has none.
            user_token = self._caller_token(up, tool) if self._passthrough(up) else None
            for attempt in range(attempts):
                try:
                    if user_token is not None:
                        result = self._call_as_user(up, tool, user_token, arguments, timeout, progress,
                                                    responses, request_state, ctx, trace_meta)
                    else:
                        result = self._wait(up.conn.call_tool(tool.upstream_name, arguments, timeout, progress,
                                                              responses, request_state, trace_meta),
                                            timeout + 5.0, ctx)
                    break
                except UpstreamUnavailable:
                    if attempt + 1 >= attempts:
                        raise
                    time.sleep(min(0.25 * (attempt + 1), 1.0))
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
                raise FederatedToolError(redact(text or f'{tool.name} failed upstream', up.conn.secret_values())
                                         [:2000], data)
            return data
        except InputRequired:
            raise
        except Exception:
            up.failures += 1
            raise
        finally:
            up.total_ms += (time.time() - started) * 1000

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
        rest = uri[len(RESOURCE_SCHEME) + 3:]
        uid, _, encoded = rest.partition('/')
        original = unquote(encoded)
        up = self._upstreams.get(uid)
        if (up is None or not self.settings.enabled or not up.config.enabled or not up.config.expose_resources
                or original not in up.items['resource'] or self._status(up, 'resource', original) != 'approved'):
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
        return {
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
            'definition': cfg.to_dict(),
        }

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
