"""
SAJHA MCP Server — tool versions: canary routing, pins, automatic rollback and deprecation.

MCP clients see one tool per name; versions are internal. ``config/tool_versions/<tool>.yaml``
(``quality.versions_dir``) declares a tool's other versions (overrides of the registered
config, or a whole config), how calls are routed to them (API-key pin > user pin > role >
canary percentage > stable), when a canary is rolled back (error rate or slow-call rate in a
sliding window, shared through the state store) and when a version or the tool is sunset.

``route_call`` is called at the top of ``BaseMCPTool.execute_with_tracking`` (the one place
every path runs a tool); it returns ``NOT_ROUTED`` for a tool without a versions file (a dict
miss), else runs the chosen version's ``execute_with_tracking`` and returns its result.
``collect_meta`` lets the MCP handler put ``_meta["io.sajha/tool-version"]`` (and
``io.sajha/deprecation``) on the result. Docs: docs/architecture/Tool Quality.md §6.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import contextlib
import contextvars
import copy
import hashlib
import importlib
import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

NOT_ROUTED = object()
META_VERSION = 'io.sajha/tool-version'
META_DEPRECATION = 'io.sajha/deprecation'
SLOW_FRACTION = 0.05                     # more than 5% of calls slower than max_p95_ms: p95 is above it
_VERSION_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+\-]{0,49}$')

_routing: contextvars.ContextVar[bool] = contextvars.ContextVar('sajha_version_routing', default=False)
_meta: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar('sajha_version_meta', default=None)


class VersionsError(ValueError):
    """A versions file that is not valid."""


# ── the file ─────────────────────────────────────────────────────────

def _date(v: Any, what: str) -> Optional[str]:
    if v in (None, ''):
        return None
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise VersionsError(f'{what} must be an ISO date (YYYY-MM-DD), got {v!r}')


def _past(d: Optional[str], today: Optional[date] = None) -> bool:
    return bool(d) and date.fromisoformat(d) < (today or date.today())


@dataclass
class VersionDef:
    version: str
    overrides: Dict[str, Any] = field(default_factory=dict)
    config: str = ''
    changelog: str = ''
    deprecated: bool = False
    sunset: Optional[str] = None
    successor: str = ''
    message: str = ''

    @property
    def is_deprecated(self) -> bool:
        return self.deprecated or bool(self.sunset)

    def past_sunset(self, today: Optional[date] = None) -> bool:
        return _past(self.sunset, today)

    def to_dict(self) -> Dict[str, Any]:
        return {'version': self.version, 'overrides': self.overrides, 'config': self.config,
                'changelog': self.changelog, 'deprecated': self.is_deprecated, 'sunset': self.sunset,
                'successor': self.successor, 'message': self.message}


@dataclass
class Rollback:
    enabled: bool = True
    max_error_rate: float = 0.2
    max_p95_ms: float = 0.0              # 0: latency never triggers
    min_calls: int = 20
    window_seconds: float = 300.0


@dataclass
class VersionsFile:
    tool: str
    stable: str = ''                     # '' -> the registered config's version
    versions: Dict[str, VersionDef] = field(default_factory=dict)
    canary_version: str = ''
    canary_percent: float = 0.0
    roles: Dict[str, str] = field(default_factory=dict)
    users: Dict[str, str] = field(default_factory=dict)
    api_keys: Dict[str, str] = field(default_factory=dict)
    rollback: Rollback = field(default_factory=Rollback)
    sunset: Optional[str] = None         # the tool as a whole
    successor: str = ''
    message: str = ''
    source: str = ''
    raw: Dict[str, Any] = field(default_factory=dict)

    def stable_version(self, base_version: str) -> str:
        return self.stable or base_version

    def known(self, base_version: str) -> List[str]:
        out = [base_version] + [v for v in self.versions if v != base_version]
        return out

    def definition(self, ver: str) -> VersionDef:
        return self.versions.get(ver) or VersionDef(ver)

    def retired(self, today: Optional[date] = None) -> bool:
        return _past(self.sunset, today)


def parse(doc: Any, source: str = '', tool_hint: str = '') -> VersionsFile:
    if not isinstance(doc, dict):
        raise VersionsError('a versions file is an object with "tool" and "versions"')
    tool = str(doc.get('tool') or tool_hint or '')
    if not tool:
        raise VersionsError('"tool" is required')
    if tool_hint and tool != tool_hint:
        raise VersionsError(f'the file is for {tool_hint!r} but names tool {tool!r}')
    vf = VersionsFile(tool=tool, source=source, raw=copy.deepcopy(doc))
    vf.stable = str(doc.get('stable') or '')
    raw_versions = doc.get('versions') or {}
    if not isinstance(raw_versions, dict):
        raise VersionsError('"versions" must map version -> definition')
    for ver, d in raw_versions.items():
        ver = str(ver)
        if not _VERSION_RE.match(ver):
            raise VersionsError(f'version {ver!r}: use letters, digits, ".", "-", "+" or "_" (at most 50)')
        d = d or {}
        if not isinstance(d, dict):
            raise VersionsError(f'version {ver}: definition must be an object')
        unknown = set(d) - {'overrides', 'config', 'changelog', 'deprecated', 'sunset', 'successor', 'message'}
        if unknown:
            raise VersionsError(f'version {ver}: unknown keys {sorted(unknown)}')
        ov = d.get('overrides') or {}
        if not isinstance(ov, dict):
            raise VersionsError(f'version {ver}: overrides must be an object')
        if 'name' in ov and ov['name'] != tool:
            raise VersionsError(f'version {ver}: overrides may not rename the tool (versions are internal)')
        if ov and d.get('config'):
            raise VersionsError(f'version {ver}: give overrides or config, not both')
        cfg = str(d.get('config') or '')
        if cfg and (os.path.isabs(cfg) or '..' in Path(cfg).parts):
            raise VersionsError(f'version {ver}: config must be a path inside the versions directory')
        vf.versions[ver] = VersionDef(ver, overrides=ov, config=cfg, changelog=str(d.get('changelog') or ''),
                                      deprecated=bool(d.get('deprecated', False)),
                                      sunset=_date(d.get('sunset'), f'version {ver}: sunset'),
                                      successor=str(d.get('successor') or ''), message=str(d.get('message') or ''))
    routing = doc.get('routing') or {}
    if not isinstance(routing, dict):
        raise VersionsError('"routing" must be an object')
    canary = routing.get('canary') or {}
    if canary:
        if not isinstance(canary, dict):
            raise VersionsError('routing.canary must be {version, percent}')
        vf.canary_version = str(canary.get('version') or '')
        try:
            vf.canary_percent = float(canary.get('percent', 0) or 0)
        except (TypeError, ValueError):
            raise VersionsError('routing.canary.percent must be a number')
        if not 0 <= vf.canary_percent <= 100:
            raise VersionsError('routing.canary.percent must be between 0 and 100')
        if vf.canary_percent and not vf.canary_version:
            raise VersionsError('routing.canary needs a version')
    for key in ('roles', 'users', 'api_keys'):
        m = routing.get(key) or {}
        if not isinstance(m, dict):
            raise VersionsError(f'routing.{key} must map name -> version')
        setattr(vf, key, {str(k): str(v) for k, v in m.items()})
    unknown = set(routing) - {'canary', 'roles', 'users', 'api_keys'}
    if unknown:
        raise VersionsError(f'routing: unknown keys {sorted(unknown)}')
    rb = doc.get('rollback') or {}
    if not isinstance(rb, dict):
        raise VersionsError('"rollback" must be an object')
    try:
        vf.rollback = Rollback(enabled=bool(rb.get('enabled', True)),
                               max_error_rate=float(rb.get('max_error_rate', 0.2)),
                               max_p95_ms=float(rb.get('max_p95_ms', 0) or 0),
                               min_calls=int(rb.get('min_calls', 20)),
                               window_seconds=float(rb.get('window_seconds', 300)))
    except (TypeError, ValueError) as e:
        raise VersionsError(f'rollback: {e}')
    if not 0 <= vf.rollback.max_error_rate <= 1:
        raise VersionsError('rollback.max_error_rate is a fraction between 0 and 1')
    if vf.rollback.min_calls < 1 or vf.rollback.window_seconds <= 0:
        raise VersionsError('rollback.min_calls must be >= 1 and window_seconds > 0')
    dep = doc.get('deprecation') or {}
    if not isinstance(dep, dict):
        raise VersionsError('"deprecation" must be an object')
    vf.sunset = _date(dep.get('sunset'), 'deprecation.sunset')
    vf.successor = str(dep.get('successor') or '')
    vf.message = str(dep.get('message') or '')
    unknown = set(doc) - {'tool', 'stable', 'versions', 'routing', 'rollback', 'deprecation'}
    if unknown:
        raise VersionsError(f'unknown keys {sorted(unknown)}')
    return vf


def check_references(vf: VersionsFile, base_version: str) -> None:
    """Every version routing names exists (the registered config's version always does)."""
    known = set(vf.known(base_version))
    refs = [('stable', vf.stable)] if vf.stable else []
    if vf.canary_version:
        refs.append(('routing.canary.version', vf.canary_version))
    refs += [(f'routing.roles.{k}', v) for k, v in vf.roles.items()]
    refs += [(f'routing.users.{k}', v) for k, v in vf.users.items()]
    refs += [(f'routing.api_keys.{k}', v) for k, v in vf.api_keys.items()]
    for where, ver in refs:
        if ver not in known:
            raise VersionsError(f'{where} names version {ver!r}, which is neither the registered config\'s '
                                f'({base_version}) nor in versions')


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _resolve(obj: Any) -> Any:
    from sajha.core.config import resolve_placeholders
    if isinstance(obj, str):
        return resolve_placeholders(obj)
    if isinstance(obj, dict):
        return {k: _resolve(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve(v) for v in obj]
    return obj


def instantiate(config: Dict[str, Any]):
    """A tool instance from a config, the way the registry builds one (sandbox first), never registered."""
    from sajha.tools.tools_registry import ToolsRegistry
    reg = ToolsRegistry._instance
    builtin = getattr(reg, 'builtin_tools', {}) or {}
    tool_type = config.get('type')
    if tool_type in builtin:
        path = builtin[tool_type]
    elif 'implementation' in config:
        from sajha.sandbox.tools import build_sandboxed_tool
        sandboxed = build_sandboxed_tool(config)
        if sandboxed is not None:
            return sandboxed
        path = config['implementation']
        if not isinstance(path, str):
            raise VersionsError('a version\'s implementation must be a dotted class path')
    else:
        raise VersionsError('a version config needs "implementation" (or a built-in "type")')
    module_path, class_name = path.rsplit('.', 1)
    cls = getattr(importlib.import_module(module_path), class_name)
    return cls(config)


# ── the manager ──────────────────────────────────────────────────────

def _store():
    from sajha.core.state import get_state_store
    return get_state_store()


def _key(*parts: str) -> str:
    return 'quality:versions:' + ':'.join(parts)


class VersionManager:
    def __init__(self, directory: Optional[str] = None, reload_seconds: Optional[float] = None):
        from sajha.quality import setting_int, versions_dir
        self.directory = Path(directory or versions_dir())
        self.reload_seconds = float(reload_seconds if reload_seconds is not None
                                    else setting_int('versions.reload_seconds', 5))
        self._files: Dict[str, VersionsFile] = {}
        self._errors: Dict[str, str] = {}
        self._stamp: Tuple = ()
        self._checked = 0.0
        self._lock = threading.RLock()
        self._instances: Dict[Tuple[str, str, int], Any] = {}
        self.reload(force=True)

    # -- loading -------------------------------------------------------

    def _scan(self) -> Tuple:
        if not self.directory.is_dir():
            return ()
        out = []
        for p in sorted(self.directory.iterdir()):
            if p.is_file():
                try:
                    st = p.stat()
                    out.append((p.name, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
        return tuple(out)

    def reload(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._checked < self.reload_seconds:
            return
        with self._lock:
            self._checked = now
            stamp = self._scan()
            if not force and stamp == self._stamp:
                return
            files, errors = {}, {}
            for name, _, _ in stamp:
                p = self.directory / name
                if p.suffix.lower() not in ('.yaml', '.yml', '.json'):
                    continue
                try:
                    doc = _load(p)
                    if isinstance(doc, dict) and 'tool' not in doc and 'implementation' in doc:
                        continue      # a whole version config referenced by a versions file
                    vf = parse(doc, str(p))
                except Exception as e:
                    errors[str(p)] = str(e)
                    logger.warning(f'tool versions: {p}: {e} (file ignored)')
                    continue
                if vf.tool in files:
                    errors[str(p)] = f'{vf.tool} already has a versions file ({files[vf.tool].source})'
                    continue
                files[vf.tool] = vf
            self._files, self._errors, self._stamp = files, errors, stamp
            self._instances.clear()

    def get(self, tool_name: str) -> Optional[VersionsFile]:
        if self.reload_seconds >= 0:
            self.reload()
        return self._files.get(tool_name)

    def files(self) -> Dict[str, VersionsFile]:
        self.reload()
        return dict(self._files)

    def errors(self) -> Dict[str, str]:
        return dict(self._errors)

    def is_listed(self, tool_name: str) -> bool:
        vf = self.get(tool_name)
        return not (vf and vf.retired())

    # -- instances -----------------------------------------------------

    def instance_for(self, tool: Any, ver: str):
        """The tool instance serving ``ver`` (the registered tool for its own version); None if unknown."""
        base_version = str(getattr(tool, 'version', '') or '')
        vf = self.get(tool.name)
        if ver == base_version:
            return tool
        if not vf or ver not in vf.versions:
            return None
        key = (tool.name, ver, id(tool))
        with self._lock:
            inst = self._instances.get(key)
            if inst is not None:
                return inst
            d = vf.versions[ver]
            base_cfg = dict(getattr(tool, 'config', None) or {})
            if d.config:
                cfg = _load(Path(vf.source).parent / d.config)
                if not isinstance(cfg, dict):
                    raise VersionsError(f'{d.config}: a tool config is an object')
                cfg = _resolve(cfg)
            else:
                cfg = _deep_merge(base_cfg, _resolve(d.overrides))
            cfg['name'] = tool.name
            cfg['version'] = ver
            cfg.pop('tests', None)
            cfg.pop('probe', None)
            inst = instantiate(cfg)
            inst._sajha_version_of = tool.name
            self._instances[key] = inst
            return inst

    # -- routing -------------------------------------------------------

    def rolled_back(self, tool: str, ver: str) -> Optional[Dict[str, Any]]:
        try:
            return _store().get(_key('rollback', tool, ver))
        except Exception:
            return None

    def rollbacks(self, tool: str) -> Dict[str, Dict[str, Any]]:
        vf = self.get(tool)
        out = {}
        for ver in (vf.versions if vf else {}):
            rb = self.rolled_back(tool, ver)
            if rb:
                out[ver] = rb
        return out

    def _usable(self, vf: VersionsFile, ver: str, base_version: str, allow_rolled_back: bool = False) -> bool:
        if ver not in vf.known(base_version):
            return False
        if vf.definition(ver).past_sunset():
            return False
        if not allow_rolled_back and ver != vf.stable_version(base_version) and self.rolled_back(vf.tool, ver):
            return False
        return True

    def choose(self, vf: VersionsFile, base_version: str, caller: Any) -> Tuple[str, str]:
        """(version, route) for this caller: api_key > user > role > canary > stable."""
        api_key = str(getattr(caller, 'api_key', '') or '')
        user = str(getattr(caller, 'user_id', '') or '')
        roles = list(getattr(caller, 'roles', ()) or ())
        if api_key and api_key in vf.api_keys and self._usable(vf, vf.api_keys[api_key], base_version, True):
            return vf.api_keys[api_key], 'api_key'
        if user and user != 'anonymous' and user in vf.users and self._usable(vf, vf.users[user], base_version):
            return vf.users[user], 'user'
        for r in roles:
            if r in vf.roles and self._usable(vf, vf.roles[r], base_version):
                return vf.roles[r], 'role'
        if vf.canary_version and vf.canary_percent > 0 and self._usable(vf, vf.canary_version, base_version):
            ident = api_key or (user if user and user != 'anonymous' else '')
            if ident:
                bucket = int(hashlib.sha256(f'{vf.tool}\x00{ident}'.encode()).hexdigest()[:8], 16) % 10000 / 100.0
            else:
                bucket = random.random() * 100.0
            if bucket < vf.canary_percent:
                return vf.canary_version, 'canary'
        stable = vf.stable_version(base_version)
        if stable != base_version and not self._usable(vf, stable, base_version, True):
            return base_version, 'stable-fallback'
        return stable, 'stable'

    # -- windows and rollback -----------------------------------------

    def record(self, vf: VersionsFile, ver: str, ok: bool, ms: float, base_version: str) -> Optional[Dict[str, Any]]:
        """Count one routed call; returns the rollback record when this call triggered one."""
        _metric_call(vf.tool, ver, 'ok' if ok else 'error', ms)
        rb = vf.rollback
        try:
            store = _store()
            w = rb.window_seconds
            _, calls = store.window_add(_key('w', vf.tool, ver, 'calls'), w)
            errors = store.window_count(_key('w', vf.tool, ver, 'errors'), w)
            slow = store.window_count(_key('w', vf.tool, ver, 'slow'), w)
            if not ok:
                _, errors = store.window_add(_key('w', vf.tool, ver, 'errors'), w)
            if rb.max_p95_ms and ms > rb.max_p95_ms:
                _, slow = store.window_add(_key('w', vf.tool, ver, 'slow'), w)
        except Exception as e:
            logger.debug(f'tool versions: window update failed: {e}')
            return None
        if not rb.enabled or ver == vf.stable_version(base_version) or calls < rb.min_calls:
            return None
        reason = ''
        if errors / calls > rb.max_error_rate:
            reason = f'error rate {errors}/{calls} = {errors / calls:.0%} > {rb.max_error_rate:.0%}'
        elif rb.max_p95_ms and slow / calls > SLOW_FRACTION:
            reason = f'p95 above {rb.max_p95_ms:.0f} ms ({slow}/{calls} calls slower)'
        if not reason:
            return None
        record = {'tool': vf.tool, 'version': ver, 'reason': reason, 'at': time.time(), 'calls': calls,
                  'errors': errors, 'slow': slow, 'by': 'automatic'}
        try:
            if not store.add(_key('rollback', vf.tool, ver), record):
                return None      # another worker (or call) rolled it back first
        except Exception as e:
            logger.warning(f'tool versions: could not store rollback of {vf.tool}@{ver}: {e}')
            return None
        logger.warning(f'tool versions: rolled back {vf.tool}@{ver}: {reason}')
        _metric_rollback(vf.tool, ver)
        try:
            from sajha import audit
            audit.record('quality.version.rollback', actor={'user': 'system'},
                         resource={'tool': vf.tool, 'version': ver}, outcome='rolled_back', details=record)
        except Exception:
            pass
        return record

    def window_stats(self, tool: str, ver: str, window: float) -> Dict[str, Any]:
        try:
            store = _store()
            calls = store.window_count(_key('w', tool, ver, 'calls'), window)
            errors = store.window_count(_key('w', tool, ver, 'errors'), window)
            slow = store.window_count(_key('w', tool, ver, 'slow'), window)
        except Exception:
            calls = errors = slow = 0
        return {'calls': calls, 'errors': errors, 'slow': slow,
                'error_rate': round(errors / calls, 4) if calls else 0.0,
                'slow_rate': round(slow / calls, 4) if calls else 0.0}

    def clear_rollback(self, tool: str, ver: str, by: str = '') -> bool:
        try:
            store = _store()
            done = store.delete(_key('rollback', tool, ver))
            for part in ('calls', 'errors', 'slow'):
                store.delete(_key('w', tool, ver, part))
        except Exception:
            return False
        try:
            from sajha import audit
            audit.record('quality.version.rollback_cleared', actor={'user': by or 'unknown'},
                         resource={'tool': tool, 'version': ver}, outcome='cleared')
        except Exception:
            pass
        return bool(done)

    # -- writing -------------------------------------------------------

    def path_for(self, tool: str) -> Path:
        vf = self._files.get(tool)
        if vf and vf.source:
            return Path(vf.source)
        safe = re.sub(r'[^A-Za-z0-9_.\-]', '_', tool)
        return self.directory / f'{safe}.yaml'

    def save_text(self, tool: str, text: str, base_version: str) -> VersionsFile:
        """Validate ``text`` (YAML or JSON) and write it as the tool's versions file."""
        import yaml
        try:
            doc = yaml.safe_load(text) if text.strip() else None
        except yaml.YAMLError as e:
            raise VersionsError(f'not valid YAML: {e}')
        vf = parse(doc, tool_hint=tool)
        check_references(vf, base_version)
        path = self.path_for(tool)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_text(text if text.endswith('\n') else text + '\n', encoding='utf-8')
        os.replace(tmp, path)
        self.reload(force=True)
        return self._files.get(tool) or vf

    def save_doc(self, tool: str, doc: Dict[str, Any], base_version: str) -> VersionsFile:
        import yaml
        return self.save_text(tool, yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), base_version)

    def set_canary(self, tool: str, version: str, percent: float, base_version: str) -> VersionsFile:
        vf = self.get(tool)
        doc = copy.deepcopy(vf.raw) if vf else {'tool': tool}
        routing = doc.setdefault('routing', {}) or {}
        doc['routing'] = routing
        routing['canary'] = {'version': version, 'percent': percent}
        return self.save_doc(tool, doc, base_version)

    def promote(self, tool: str, version: str, base_version: str) -> VersionsFile:
        vf = self.get(tool)
        doc = copy.deepcopy(vf.raw) if vf else {'tool': tool}
        doc['stable'] = version
        canary = ((doc.get('routing') or {}).get('canary') or {})
        if canary.get('version') == version:
            doc['routing']['canary'] = {'version': version, 'percent': 0}
        out = self.save_doc(tool, doc, base_version)
        self.clear_rollback(tool, version)
        return out

    def describe(self, tool: Any) -> Dict[str, Any]:
        """Everything the Tool Versions page shows for one tool."""
        vf = self.get(tool.name)
        base_version = str(getattr(tool, 'version', '') or '')
        if not vf:
            return {'tool': tool.name, 'base_version': base_version, 'managed': False}
        stable = vf.stable_version(base_version)
        window = vf.rollback.window_seconds
        versions = []
        for ver in vf.known(base_version):
            d = vf.definition(ver)
            versions.append({**d.to_dict(), 'registered': ver == base_version, 'stable': ver == stable,
                             'past_sunset': d.past_sunset(), 'rolled_back': self.rolled_back(tool.name, ver),
                             'window': self.window_stats(tool.name, ver, window)})
        return {'tool': tool.name, 'base_version': base_version, 'managed': True, 'stable': stable,
                'versions': versions,
                'routing': {'canary': {'version': vf.canary_version, 'percent': vf.canary_percent},
                            'roles': vf.roles, 'users': vf.users, 'api_keys': vf.api_keys},
                'rollback': vf.rollback.__dict__, 'deprecation': {'sunset': vf.sunset, 'successor': vf.successor,
                                                                  'message': vf.message, 'retired': vf.retired()},
                'source': vf.source}


def _load(path: Path) -> Any:
    text = Path(path).read_text(encoding='utf-8')
    if str(path).lower().endswith('.json'):
        return json.loads(text)
    import yaml
    return yaml.safe_load(text)


_manager: Optional[VersionManager] = None
_mlock = threading.Lock()


def get_manager() -> VersionManager:
    global _manager
    if _manager is None:
        with _mlock:
            if _manager is None:
                _manager = VersionManager()
    return _manager


def set_manager(m: Optional[VersionManager]) -> None:
    """Tests: install a manager (None: build from config on next use)."""
    global _manager
    _manager = m


def enabled() -> bool:
    from sajha.quality import setting_bool
    return setting_bool('versions.enabled', True)


# ── metrics ──────────────────────────────────────────────────────────

_families: Dict[str, Any] = {}


def _fam(name: str):
    if not _families:
        try:
            from sajha.observability import metrics as M
            _families['calls'] = M.Counter(M.REGISTRY, 'sajha_tool_version_calls_total',
                                           'Routed tool calls by tool, version and outcome (versioned tools only).',
                                           ('tool', 'version', 'outcome'))
            _families['latency'] = M.Histogram(M.REGISTRY, 'sajha_tool_version_call_duration_seconds',
                                               'Routed tool call latency by tool and version.', ('tool', 'version'))
            _families['rollbacks'] = M.Counter(M.REGISTRY, 'sajha_tool_version_rollbacks_total',
                                               'Automatic canary rollbacks by tool and version.', ('tool', 'version'))
        except Exception:
            return None
    return _families.get(name)


def _metric_call(tool: str, ver: str, outcome: str, ms: float) -> None:
    try:
        c, h = _fam('calls'), _fam('latency')
        if c is not None:
            c.inc((tool, ver, outcome))
            h.observe((tool, ver), ms / 1000.0)
    except Exception:
        pass


def _metric_rollback(tool: str, ver: str) -> None:
    try:
        c = _fam('rollbacks')
        if c is not None:
            c.inc((tool, ver))
    except Exception:
        pass


# ── the hook ─────────────────────────────────────────────────────────

@contextlib.contextmanager
def collect_meta() -> Iterator[Dict[str, Any]]:
    """Collect the ``_meta`` entries routing adds for the call made inside the block."""
    holder: Dict[str, Any] = {}
    token = _meta.set(holder)
    try:
        yield holder
    finally:
        _meta.reset(token)


def _not_errors():
    out = []
    for mod, name in (('sajha.core.mcp_mrtr', 'InputRequired'), ('sajha.policy.errors', 'PolicyError'),
                      ('sajha.tools.base_mcp_tool', 'ToolArgumentError'),
                      ('sajha.accounts.errors', 'ConnectedAccountRequired')):
        try:
            out.append(getattr(importlib.import_module(mod), name))
        except Exception:
            pass
    return tuple(out)


_CALLER_ERRORS: Optional[tuple] = None


def route_call(tool: Any, arguments: Dict[str, Any]) -> Any:
    """Run ``tool``'s call on the version routing chooses; ``NOT_ROUTED`` when the tool is not versioned."""
    global _CALLER_ERRORS
    if _routing.get() or getattr(tool, '_sajha_version_of', None):
        return NOT_ROUTED
    m = _manager if _manager is not None else (get_manager() if enabled() else None)
    if m is None:
        return NOT_ROUTED
    vf = m.get(tool.name)
    if vf is None:
        return NOT_ROUTED
    holder = _meta.get()
    base_version = str(getattr(tool, 'version', '') or '')
    if vf.retired():
        msg = f'Tool {tool.name} is retired (sunset {vf.sunset})'
        if vf.successor:
            msg += f'; use {vf.successor}'
        raise RuntimeError(msg + '.')
    from sajha.observability.caller import current
    ver, route = m.choose(vf, base_version, current())
    try:
        target = m.instance_for(tool, ver) or tool
    except Exception as e:      # a broken version must not take the tool down: serve the registered one
        logger.warning(f'tool versions: {tool.name}@{ver} could not be built ({e}); serving {base_version}')
        target, route = tool, 'fallback'
    if target is tool:
        ver = base_version
    d = vf.definition(ver)
    deprecation = None
    if vf.sunset:
        deprecation = {'scope': 'tool', 'sunset': vf.sunset, 'successor': vf.successor,
                       'message': vf.message or f'{tool.name} is deprecated and will be retired on {vf.sunset}.'}
    elif d.is_deprecated:
        deprecation = {'scope': 'version', 'version': ver, 'sunset': d.sunset, 'successor': d.successor,
                       'message': d.message or f'{tool.name} version {ver} is deprecated'
                       + (f' until {d.sunset}' if d.sunset else '') + '.'}
    if holder is not None:
        holder[META_VERSION] = {'version': ver, 'route': route}
        if deprecation:
            holder[META_DEPRECATION] = deprecation
    token = _routing.set(True)
    t0 = time.perf_counter()
    ok = True
    try:
        return target.execute_with_tracking(arguments)
    except Exception as e:
        if _CALLER_ERRORS is None:
            _CALLER_ERRORS = _not_errors()
        if not isinstance(e, _CALLER_ERRORS):
            ok = False
        raise
    finally:
        _routing.reset(token)
        try:
            m.record(vf, ver, ok, (time.perf_counter() - t0) * 1000, base_version)
        except Exception as e:
            logger.debug(f'tool versions: record failed: {e}')


def listed(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``tools/list`` entries without the tools retired by their versions file (past the tool's sunset)."""
    m = _manager if _manager is not None else (get_manager() if enabled() else None)
    if m is None or not m.files():
        return entries
    return [e for e in entries if m.is_listed(str(e.get('name', '')))]
