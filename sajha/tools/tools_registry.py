"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Tools Registry - Singleton pattern for managing MCP tools v2.9.8
"""

import json
import logging
import importlib
import os
import re
import threading
from contextlib import contextmanager
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
from .base_mcp_tool import BaseMCPTool
from sajha.core.storage import get_storage

# The conventional tools directory: storage paths written with it are mapped onto config.tools.dir (_config_rel)
from sajha.tools.tool_files import DEFAULT_PREFIX as DEFAULT_TOOLS_DIR


class ToolsRegistry:
    """
    Singleton registry for managing MCP tools with dynamic loading
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, tools_config_dir: str = None):
        """
        Initialize the tools registry
        
        Args:
            tools_config_dir: Directory containing tool configuration files (relative to project root or absolute)
        """
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        
        # Handle config directory path
        if tools_config_dir is None:
            from sajha.tools.tool_files import default_prefix
            tools_config_dir = default_prefix()
        
        self.tools_config_dir = Path(tools_config_dir)
        if not self.tools_config_dir.is_absolute():
            self.tools_config_dir = Path.cwd() / self.tools_config_dir

        # Logical prefix for tool configs *relative to the storage backend base*
        # (e.g. 'config/tools'). All tool-config IO flows through get_storage()
        # using this prefix, so configs can live on local disk, S3, Azure, or GCS.
        try:
            self._config_prefix = str(self.tools_config_dir.relative_to(Path.cwd())).replace('\\', '/')
        except ValueError:
            self._config_prefix = self._outside_prefix()
        
        self.tools: Dict[str, BaseMCPTool] = {}
        self.tool_configs: Dict[str, Dict] = {}
        self.tool_errors: Dict[str, str] = {}
        # tools skipped because a module their config "requires" is not installed: name -> missing modules
        self.skipped_tools: Dict[str, List[str]] = {}
        self._tools_lock = threading.RLock()
        self.logger = logging.getLogger(__name__)
        
        # Initialize properties configurator reference
        self._properties_configurator = None
        self._init_properties_configurator()
        
        self.logger.info(f"ToolsRegistry initializing with config dir: {self.tools_config_dir}")
        
        # File monitoring
        self._file_timestamps: Dict[str, float] = {}
        self._monitor_thread = None
        self._stop_monitor = threading.Event()
        
        # Built-in tools mapping
        self.builtin_tools = {}
        '''
        self.builtin_tools = {
            'wikipedia': 'sajha.tools.impl.wikipedia_tool.WikipediaTool',
            'yahoo_finance': 'sajha.tools.impl.yahoo_finance_tool.YahooFinanceTool',
            'google_search': 'sajha.tools.impl.google_search_tool.GoogleSearchTool',
            'fed_reserve': 'sajha.tools.impl.fed_reserve_tool.FedReserveTool',
            'tavily': 'sajha.tools.impl.tavily_tool.TavilyTool'
        }
        '''
        # Load initial tools
        self.load_all_tools()
        
        # Start file monitoring, and the retry of tools that failed to load
        self.start_monitoring()
        self.start_retrying()
    
    def _outside_prefix(self) -> str:
        """A tools directory outside the storage base cannot be addressed by storage paths; the tool file
        index's default (sajha/tools/tool_files.py) is used instead, and that is logged."""
        from sajha.tools.tool_files import DEFAULT_PREFIX
        logging.getLogger(__name__).warning(
            f'tools directory {self.tools_config_dir} is outside the working directory; config.tools.dir must be '
            f'relative to the storage base; using {DEFAULT_PREFIX}')
        return DEFAULT_PREFIX

    def _init_properties_configurator(self):
        """Initialize reference to PropertiesConfigurator for variable substitution"""
        try:
            from sajha.core.properties_configurator import PropertiesConfigurator
            # Load the SAME config the rest of the app uses, so ${...} references in
            # tool JSON configs (e.g. ${data.duckdb.dir}) resolve against application.yml.
            # Respects the --config / SAJHA_CONFIG_FILE override. Without a yaml_file the
            # configurator is empty and every ${key} falls through to its literal text,
            # which previously created directories literally named "${data.duckdb.dir}".
            config_file = os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml')
            self._properties_configurator = PropertiesConfigurator(yaml_file=config_file)
            self.logger.debug(f"PropertiesConfigurator initialized from {config_file} for variable substitution")
        except Exception as e:
            self.logger.warning(f"Could not initialize PropertiesConfigurator: {e}", exc_info=True)
            self._properties_configurator = None
    
    def _substitute_variables(self, obj: Any) -> Any:
        """
        Recursively substitute ${key} patterns in config values with values from PropertiesConfigurator.
        
        Args:
            obj: The object to process (dict, list, or string)
            
        Returns:
            Object with all ${key} patterns substituted
        """
        if obj is None:
            return None
            
        if isinstance(obj, str):
            # Pattern to match ${key} or ${key:default}
            pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'
            
            def replace_var(match):
                key = match.group(1)
                default = match.group(2)
                
                # Try to get value from PropertiesConfigurator
                value = None
                if self._properties_configurator:
                    try:
                        value = self._properties_configurator.get(key)
                    except Exception as e:
                        logger.error(f"Unexpected error: {e}", exc_info=True)
                        pass
                
                # If not found, try environment variable
                if value is None:
                    value = os.environ.get(key)
                
                # If still not found, use default or keep original
                if value is None:
                    if default is not None:
                        return default
                    return match.group(0)  # Keep original ${key}
                
                return str(value)
            
            return re.sub(pattern, replace_var, obj)
        
        elif isinstance(obj, dict):
            return {k: self._substitute_variables(v) for k, v in obj.items()}
        
        elif isinstance(obj, list):
            return [self._substitute_variables(item) for item in obj]
        
        else:
            return obj
    
    def _config_rel(self, ref) -> str:
        """Normalize any reference to the storage-relative path of a tool config: a storage path
        ('config/tools/fmp/foo.json') or a local Path under the tools directory keeps its folder; a
        bare tool name or filename ('foo', 'foo.json') is looked up in the tool file index, so a tool
        in a folder resolves to its own file (a name with no file resolves to the root)."""
        s = str(ref).replace('\\', '/')
        p = Path(str(ref))
        if p.is_absolute():
            try:
                s = f"{self._config_prefix}/{p.relative_to(self.tools_config_dir).as_posix()}"
            except ValueError:
                s = p.name
        elif s.startswith(DEFAULT_TOOLS_DIR + '/') and self._config_prefix != DEFAULT_TOOLS_DIR:
            s = f"{self._config_prefix}/{s[len(DEFAULT_TOOLS_DIR) + 1:]}"
        if s.startswith(self._config_prefix + '/'):
            return s if s.endswith('.json') else f'{s}.json'
        if '/' in s:
            return f"{self._config_prefix}/{s if s.endswith('.json') else s + '.json'}"
        name = s[:-5] if s.endswith('.json') else s
        return self.file_index().target_path(name, '')

    def file_index(self):
        """The tool file index of this registry's tools directory (sajha/tools/tool_files.py)."""
        from sajha.tools.tool_files import get_index
        return get_index(self._config_prefix)

    def tool_path(self, tool_name: str) -> Optional[str]:
        """The storage-relative config file of a file-backed tool (None: plugin, federated, ...)."""
        return self.file_index().path_of(tool_name)

    def tool_folder(self, tool_name: str) -> Optional[str]:
        """The tool folder of a file-backed tool ('' for the root, None when it has no file)."""
        return self.file_index().folder_of(tool_name)

    # ── change notification ──────────────────────────────────────────
    # One registration used to publish one change (three bus events, each also written to the
    # state store's 'changes' channel), so loading 500 tools wrote ~1,500 events.  Bulk work
    # runs inside bulk(): it publishes once at the end, and only if the catalog changed.

    @contextmanager
    def bulk(self):
        """Coalesce the change notifications of everything done inside into at most one."""
        with self._tools_lock:
            depth = getattr(self, '_bulk_depth', 0)
            self._bulk_depth = depth + 1
            if depth == 0:
                self._bulk_dirty = False
        if depth == 0:
            self._bulk_before = self._catalog_fingerprint()
        try:
            yield
        finally:
            with self._tools_lock:
                self._bulk_depth -= 1
                outermost = self._bulk_depth == 0
                dirty = outermost and self._bulk_dirty
                skipped_dirty = outermost and self.__dict__.pop('_skipped_dirty', False)
            if skipped_dirty:
                self._report_skipped()
            if dirty and self._catalog_fingerprint() != getattr(self, '_bulk_before', None):
                _publish_tools_changed()
                self._notify_change()

    def _catalog_fingerprint(self):
        """What tools/list would show: names, enabled flags and advertised definitions."""
        with self._tools_lock:
            tools = dict(getattr(self, 'tools', {}) or {})
        return tuple((name, _tool_fingerprint(tool)) for name, tool in sorted(tools.items()))

    def _changed(self):
        """The catalog changed: publish now, or once at the end of the enclosing bulk()."""
        if getattr(self, '_bulk_depth', 0) > 0:
            self._bulk_dirty = True
            return
        _publish_tools_changed()
        self._notify_change()

    def add_change_listener(self, callback):
        """Call ``callback()`` after every change to the catalog: each register, unregister,
        enable and disable, or once at the end of a bulk() that changed something. This covers
        every path that adds tools (Studio creators, composites, federation, API import, the
        file watcher, plug-ins); the Ask SAJHA tool-search index listens here. A bound method is
        held weakly, so a discarded listener's owner is not kept alive."""
        import weakref
        ref = weakref.WeakMethod(callback) if hasattr(callback, '__self__') else (lambda cb=callback: cb)
        with self._tools_lock:
            if not hasattr(self, '_change_listeners'):
                self._change_listeners = []
            self._change_listeners.append(ref)

    def _notify_change(self):
        with self._tools_lock:
            refs = list(getattr(self, '_change_listeners', []))
        dead = []
        for ref in refs:
            cb = ref()
            if cb is None:
                dead.append(ref)
                continue
            try:
                cb()
            except Exception as e:
                self.logger.error(f"Change listener error: {e}", exc_info=True)
        if dead:
            with self._tools_lock:
                self._change_listeners = [r for r in self._change_listeners if r not in dead]

    def load_all_tools(self):
        """Load all tools from the configured store (local | s3 | azure | gcs): the root of the tools
        directory and its folders, one level deep. A name in two files loads neither."""
        storage = get_storage()
        self.logger.info(f"Loading tools from '{self._config_prefix}' via {type(storage).__name__}")
        from sajha.tools.tool_files import get_index
        idx = get_index(self._config_prefix, build=False)
        configs = {}
        rels = [r.replace('\\', '/') for r in storage.list_files(self._config_prefix, '*.json')]
        for rel in rels:
            if Path(rel).name.startswith('.') or not idx.split(rel)[1]:
                continue
            configs[rel] = self._read_config(rel)
        idx.refresh({rel: cfg for rel, cfg in configs.items() if cfg is not None}, rels=rels)
        self._report_layout(idx)
        dups = idx.duplicates()
        with self.bulk():
            self._load_domain_texts()
            for rel, config in configs.items():
                if config is None:
                    continue
                name = idx.name_at(rel)
                if name in dups:
                    continue
                self.register_tool_from_dict(config, source=rel)

    # ── domain descriptions (sajha/tools/domain_text.py) ─────────────
    # <folder>/domain.txt is appended to the served description of the folder's tools. A change to one
    # changes the served definitions, so it is announced like a tool change (list_changed).

    def domain_texts(self):
        from sajha.tools.domain_text import get_domain_texts
        return get_domain_texts(self._config_prefix)

    def domain_description(self, folder: str) -> str:
        """The accepted domain description of a tool folder ('' when it has none or it is refused)."""
        try:
            return self.domain_texts().text(folder)
        except Exception:
            return ''

    def _load_domain_texts(self) -> None:
        try:
            if self.domain_texts().load():
                self._changed()
        except Exception as e:
            self.logger.warning(f"Domain descriptions not loaded: {e}")

    def _scan_domain_texts(self) -> None:
        try:
            if self.domain_texts().scan():
                self.logger.info("Domain descriptions changed")
                self._changed()
        except Exception as e:
            self.logger.warning(f"Domain descriptions not rescanned: {e}")

    def _read_config(self, rel: str):
        """Read one config file (recording its time), or None with the error recorded."""
        storage = get_storage()
        try:
            self._file_timestamps[rel] = storage.get_modified_time(rel)
            return storage.read_json(rel)
        except FileNotFoundError:
            self.logger.error(f"Tool config not found: {rel}")
            self.tool_errors[Path(rel).stem] = "Config not found"
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in {rel}: {e}", exc_info=True)
            self.tool_errors[Path(rel).stem] = f"Invalid JSON: {str(e)}"
        except Exception as e:
            self.logger.error(f"Error reading tool config {rel}: {e}", exc_info=True)
            self.tool_errors[Path(rel).stem] = str(e)
        return None

    def _report_layout(self, idx) -> None:
        """Duplicate names and too-deep files: unload, log and raise (or clear) their notices."""
        dups = idx.duplicates()
        for name, rels in dups.items():
            self._mark_duplicate(name, rels)
        try:
            from sajha import notices
            for n in notices.list_notices(state='open', source='tools'):
                nid = str(n.get('id') or '')
                if nid.startswith('tools.duplicate:') and nid.split(':', 1)[1] not in dups:
                    notices.clear_notice(nid)
            deep = idx.too_deep()
            if deep:
                for rel in deep:
                    self.logger.warning(f"Tool config ignored, nested deeper than one folder: {rel}")
                notices.raise_notice('tools.too_deep', severity='warning', source='tools',
                                     title=f'{len(deep)} tool config file(s) nested too deep are ignored',
                                     detail='A tool config must be in the tools directory or one folder below '
                                            'it. Ignored: ' + ', '.join(deep),
                                     link='/help/guides/Architecture.md', ttl_minutes=0)
            else:
                notices.clear_notice('tools.too_deep')
            bad = idx.bad_folder()
            if bad:
                folders = sorted({rel.rsplit('/', 2)[-2] for rel in bad})
                for rel in bad:
                    self.logger.warning(f"Tool config ignored, its folder name is not allowed: {rel}")
                notices.raise_notice('tools.bad_folder', severity='warning', source='tools',
                                     title=f'{len(folders)} tool folder(s) with a name that is not allowed are ignored',
                                     detail='A tool folder (a domain) is named with letters, digits and "_" only, '
                                            'with at least one letter. Ignored: ' + ', '.join(folders),
                                     link='/help/guides/Architecture.md', ttl_minutes=0)
            else:
                notices.clear_notice('tools.bad_folder')
        except Exception:
            pass

    # ── optional dependencies ("requires") ───────────────────────────
    # A tool config may declare "requires": ["<module>", ...]. While one of those modules is not
    # importable the tool is skipped: not loaded, not a failed tool, not in tools/list; one info notice
    # per missing module says how many tools wait for it. retry_failed re-checks them, so installing
    # the module loads them without a restart (docs/architecture/Architecture.md §5).

    def _skip(self, name: str, missing: List[str]) -> None:
        with self._tools_lock:
            if name in self.tools:
                self.unregister_tool(name)
            self.tool_configs.pop(name, None)
            self.tool_errors.pop(name, None)
            new = self.skipped_tools.get(name) != missing
            self.skipped_tools[name] = missing
        if new:
            self.logger.info(f"Tool {name} skipped: {', '.join(missing)} not installed")
            self._skipped_changed()

    def _unskip(self, name: str) -> None:
        if self.skipped_tools.pop(name, None) is not None:
            self._skipped_changed()

    def _skipped_changed(self) -> None:
        """Refresh the notices now, or once at the end of the current bulk() (a load of many tools)."""
        if getattr(self, '_bulk_depth', 0):
            self._skipped_dirty = True
        else:
            self._report_skipped()

    def _report_skipped(self) -> None:
        """One info notice per missing module (with the count of tools waiting for it); clear the rest."""
        by_module: Dict[str, List[str]] = {}
        for name, mods in list(self.skipped_tools.items()):
            for m in mods:
                by_module.setdefault(m, []).append(name)
        try:
            from sajha import notices
            for n in notices.list_notices(state='open', source='tools'):
                nid = str(n.get('id') or '')
                if nid.startswith('tools.requires:') and nid.split(':', 1)[1] not in by_module:
                    notices.clear_notice(nid)
            for module, names in sorted(by_module.items()):
                names = sorted(names)
                notices.raise_notice(
                    f'tools.requires:{module}', severity='info', source='tools',
                    title=f'{module} is not installed: {len(names)} {module} tool{"s" if len(names) != 1 else ""} '
                          f'{"are" if len(names) != 1 else "is"} skipped',
                    detail=f'Their configs declare "requires": ["{module}"]. Install {module} into SAJHA\'s Python '
                           f'environment (pip install it, or its wheel) to enable them; they load within '
                           f'tools.retry_failed_seconds, without a restart. Skipped: ' + ', '.join(names),
                    link='/help/guides/Architecture.md', ttl_minutes=0)
        except Exception:
            pass

    def get_skipped_tools(self) -> Dict[str, List[str]]:
        with self._tools_lock:
            return {k: list(v) for k, v in self.skipped_tools.items()}

    def retry_skipped(self) -> List[str]:
        """Load the skipped tools whose required modules are importable now; returns the ones that loaded."""
        with self._tools_lock:
            waiting = dict(self.__dict__.setdefault('skipped_tools', {}))
        if not waiting:
            return []
        importlib.invalidate_caches()              # a module installed since start-up is found
        loaded = []
        with self.bulk():
            for name, mods in sorted(waiting.items()):
                if missing_modules(mods):
                    continue
                rel = self.tool_path(name)
                if rel is None:
                    self._unskip(name)
                    continue
                self.load_tool_from_config(rel)
                if name in self.tools:
                    loaded.append(name)
                    self.logger.info(f"Tool {name} loaded: its required modules are installed now")
        return loaded

    def _mark_duplicate(self, name: str, rels) -> None:
        """Two or more files share a tool name: load none of them until one is removed."""
        self._unskip(name)
        with self._tools_lock:
            if name in self.tools:
                self.unregister_tool(name)
            self.tool_configs.pop(name, None)
            why = f"Duplicate tool name: {name} is defined in {', '.join(rels)}; none is loaded"
            self.tool_errors[name] = why
        self.logger.error(why + '. Remove (or move) all but one of them.')
        try:
            from sajha import notices
            notices.raise_notice(f'tools.duplicate:{name}', severity='critical', source='tools',
                                 title=f'Tool {name} is defined twice and is not loaded',
                                 detail=why + '. A tool name may exist in one place only (the tools directory '
                                              'or one folder). Remove or move all but one file; the tool loads '
                                              'again on the next reload. Move files, never copy them.',
                                 link='/help/guides/Architecture.md', ttl_minutes=0)
        except Exception:
            pass

    def _clear_duplicate(self, name: str) -> None:
        try:
            from sajha import notices
            notices.clear_notice(f'tools.duplicate:{name}')
        except Exception:
            pass

    def load_tool_from_config(self, config_ref):
        """
        Load a tool from its JSON configuration, read through the storage backend.

        Args:
            config_ref: a storage-relative path, a Path, or a bare tool name / filename; see
                        _config_rel. A tool whose name is in another file too is not loaded.
        """
        rel = self._config_rel(config_ref)
        idx = self.file_index()
        with self._tools_lock:
            config = self._read_config(rel)
            if config is None:
                return
            if not idx.split(rel)[1]:
                self.logger.warning(f"Tool config ignored, nested deeper than one folder: {rel}")
                return
            from sajha.tools.tool_files import _name_of
            name = _name_of(config, rel)
            idx.note(rel, name)
            others = [r for r in idx.refresh().paths_of(name) if r != rel]
            if others:
                self._mark_duplicate(name, sorted([rel] + others))
                return
            self.register_tool_from_dict(config, source=rel)

    def rescan(self, changed=(), deleted=()) -> None:
        """Apply file changes (storage-relative paths) to the catalog: load the changed files, drop the
        deleted ones, and keep the one-place rule (a name in two files loads neither; when one goes, the
        other loads again)."""
        from sajha.tools.tool_files import _name_of
        idx = self.file_index()
        affected, read = set(), {}
        with self._tools_lock:
            for rel in deleted:
                old = idx.name_at(rel)
                idx.forget(rel)
                self._file_timestamps.pop(rel, None)
                if old:
                    affected.add(old)
            for rel in changed:
                old = idx.name_at(rel)
                config = self._read_config(rel)
                name = _name_of(config, rel) if config is not None else (old or Path(rel).stem)
                idx.note(rel, name)
                read[rel] = config
                affected.update(n for n in (old, name) if n)
            for name in sorted(affected):
                paths = idx.paths_of(name)
                if not paths:
                    if name in self.tools:
                        self.unregister_tool(name)
                    self.tool_configs.pop(name, None)
                    self.tool_errors[name] = "Configuration file deleted"
                    self._clear_duplicate(name)
                    self._unskip(name)
                elif len(paths) > 1:
                    self._mark_duplicate(name, paths)
                else:
                    rel = paths[0]
                    was_duplicate = str(self.tool_errors.get(name, '')).startswith('Duplicate tool name')
                    self._clear_duplicate(name)
                    if was_duplicate:
                        self.tool_errors.pop(name, None)
                    if rel in read:
                        if name in self.tools:
                            self.unregister_tool(name)
                        if read[rel] is not None:
                            self.register_tool_from_dict(read[rel], source=rel)
                    elif name not in self.tools or was_duplicate:
                        config = self._read_config(rel)
                        if config is not None:
                            self.register_tool_from_dict(config, source=rel)

    def register_tool_from_dict(self, config: dict, source: str = ''):
        """
        Register a tool from an already-parsed config dict.

        Shared by the file loader (load_tool_from_config) and the plugin loader,
        which parses its own JSON. Implementation classes are resolved by dotted
        module path via importlib — those modules ship with the package, so they
        are always available locally regardless of where the JSON config lives.
        """
        with self._tools_lock:
            try:
                config = self._substitute_variables(config)

                tool_name = config.get('name')
                if not tool_name:
                    raise ValueError("Tool configuration missing 'name' field")

                self.__dict__.setdefault('skipped_tools', {})     # registries built without __init__ (tests)
                missing = missing_requirements(config)
                if missing:
                    self._skip(tool_name, missing)
                    return
                self._unskip(tool_name)

                self.tool_configs[tool_name] = config

                tool_type = config.get('type')
                if tool_type in self.builtin_tools:
                    tool_class_path = self.builtin_tools[tool_type]
                    module_path, class_name = tool_class_path.rsplit('.', 1)
                    try:
                        module = importlib.import_module(module_path)
                        tool_class = getattr(module, class_name)
                        self.register_tool(tool_class(config))
                        self.logger.info(f"Loaded built-in tool: {tool_name} ({tool_type})")
                        self.tool_errors.pop(tool_name, None)
                    except Exception as e:
                        self.logger.error(f"Error loading built-in tool {tool_name}: {e}", exc_info=True)
                        self.tool_errors[tool_name] = f"Failed to load: {str(e)}"

                elif 'implementation' in config:
                    impl_path = config['implementation']
                    try:
                        # Studio-generated module or script kept on a cloud storage backend:
                        # fetch it when the local copy is missing or stale (no shared file system)
                        from sajha.core.storage_modules import materialise_for_config
                        materialise_for_config(config)
                    except Exception as e:
                        self.logger.warning(f"Tool {tool_name}: materialising from storage failed: {e}")
                    try:
                        # User code (Studio Python code and script tools) runs in a
                        # sandbox and is never imported here: docs/architecture/Sandbox.md
                        from sajha.sandbox.tools import build_sandboxed_tool
                        sandboxed = build_sandboxed_tool(config)
                        if sandboxed is not None:
                            self.register_tool(sandboxed)
                            self.logger.info(f"Loaded sandboxed tool: {tool_name}")
                            self.tool_errors.pop(tool_name, None)
                            return
                        if isinstance(impl_path, dict):
                            # Legacy Studio script-tool config: the implementation was
                            # written as an object; its wrapper module is
                            # sajha.tools.impl.<name>_script_tool, exporting TOOL_CLASS.
                            module = importlib.import_module(f'sajha.tools.impl.{tool_name}_script_tool')
                            tool_class = _script_tool_compat(getattr(module, 'TOOL_CLASS'))
                        else:
                            module_path, class_name = impl_path.rsplit('.', 1)
                            module = importlib.import_module(module_path)
                            tool_class = getattr(module, class_name)
                        self.register_tool(tool_class(config))
                        self.logger.info(f"Loaded custom tool: {tool_name}")
                        self.tool_errors.pop(tool_name, None)
                    except Exception as e:
                        self.logger.error(f"Error loading custom tool {tool_name}: {e}", exc_info=True)
                        self.tool_errors[tool_name] = f"Failed to load: {str(e)}"

                else:
                    self.logger.warning(f"Tool {tool_name} has no implementation specified")
                    self.tool_errors[tool_name] = "No implementation specified"

            except Exception as e:
                label = (config.get('name') if isinstance(config, dict) else None) or (Path(source).stem if source else 'unknown')
                self.logger.error(f"Error registering tool {label}: {e}", exc_info=True)
                self.tool_errors[label] = str(e)
    
    def register_tool(self, tool: BaseMCPTool):
        """
        Register a tool instance
        
        Args:
            tool: Tool instance to register
        """
        from sajha.tools.naming import is_namespaced_tool, reserved_name_problem
        why = None if is_namespaced_tool(tool) else reserved_name_problem(tool.name)
        if why:                         # '__' is reserved for namespaced tools (docs/architecture/Federation.md)
            self.tool_errors[tool.name] = why
            self.logger.error(f'Tool not registered: {why}')
            try:
                from sajha import notices
                notices.raise_notice(f'tools.reserved_name:{tool.name}', severity='error', source='tools',
                                     title=f'Tool {tool.name} is not registered', detail=why, ttl_minutes=0)
            except Exception:
                pass
            raise ValueError(why)
        with self._tools_lock:
            previous = self.tools.get(tool.name)
            self.tools[tool.name] = tool
            try:                        # the registry serving it: its folder's domain description (domain_text.py)
                import weakref
                tool._served_by = weakref.ref(self)
            except Exception:
                pass
            self.logger.info(f"Tool registered: {tool.name}")
        if previous is not None and _tool_fingerprint(previous) == _tool_fingerprint(tool):
            return                          # same definition re-registered: nothing to announce
        self._changed()
    
    def unregister_tool(self, tool_name: str):
        """
        Unregister a tool
        
        Args:
            tool_name: Name of the tool to unregister
        """
        with self._tools_lock:
            if tool_name not in self.tools:
                return                      # nothing changed: nothing to announce
            del self.tools[tool_name]
            self.logger.info(f"Tool unregistered: {tool_name}")
        self._changed()
    
    def get_tool(self, tool_name: str) -> Optional[BaseMCPTool]:
        """
        Get a tool by name
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool instance or None
        """
        with self._tools_lock:
            return self.tools.get(tool_name)
    
    def get_all_tools(self) -> List[Dict]:
        """
        Get all registered tools in MCP format
        
        Returns:
            List of tool dictionaries
        """
        with self._tools_lock:
            return [tool.to_mcp_format() for tool in self.tools.values() if tool.enabled]
    
    def enable_tool(self, tool_name: str) -> bool:
        """
        Enable a tool
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            True if successful
        """
        with self._tools_lock:
            tool = self.tools.get(tool_name)
            if not tool:
                return False
            was = bool(tool.enabled)
            tool.enable()
            # Update config file if exists
            if tool_name in self.tool_configs:
                self.tool_configs[tool_name]['enabled'] = True
                self._save_enabled_flag(tool_name, True)
        if was != True:
            self._changed()
        return True
    
    def disable_tool(self, tool_name: str) -> bool:
        """
        Disable a tool
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            True if successful
        """
        with self._tools_lock:
            tool = self.tools.get(tool_name)
            if not tool:
                return False
            was = bool(tool.enabled)
            tool.disable()
            # Update config file if exists
            if tool_name in self.tool_configs:
                self.tool_configs[tool_name]['enabled'] = False
                self._save_enabled_flag(tool_name, False)
        if was != False:
            self._changed()
        return True
    
    def _save_enabled_flag(self, tool_name: str, enabled: bool):
        """Persist only ``enabled`` in the tool's config file. The in-memory config has its
        ${...} references substituted (API keys included), so writing it back would put
        resolved secrets into the file; the stored (unsubstituted) JSON is edited instead."""
        rel = self._config_rel(tool_name)
        try:
            storage = get_storage()
            raw = storage.read_json(rel)
            if not isinstance(raw, dict):
                return
            raw['enabled'] = enabled
            storage.write_json(rel, raw)
            self._file_timestamps[rel] = storage.get_modified_time(rel)
        except FileNotFoundError:
            pass                        # a tool with no config file (plugin, federated, ...)
        except Exception as e:
            self.logger.error(f"Error saving enabled flag for {tool_name}: {e}", exc_info=True)

    def _save_tool_config(self, tool_name: str):
        """Save tool configuration through the storage backend (local | s3 | azure | gcs)."""
        if tool_name not in self.tool_configs:
            return

        config = self.tool_configs[tool_name]
        rel = self._config_rel(tool_name)
        try:
            storage = get_storage()
            storage.write_json(rel, config)
            self._file_timestamps[rel] = storage.get_modified_time(rel)
        except Exception as e:
            self.logger.error(f"Error saving tool config for {tool_name}: {e}", exc_info=True)
    
    def get_tool_metrics(self) -> List[Dict]:
        """
        Get metrics for all tools
        
        Returns:
            List of tool metrics
        """
        with self._tools_lock:
            return [tool.get_metrics() for tool in self.tools.values()]
    
    def get_tool_errors(self) -> Dict[str, str]:
        """
        Get tool loading errors
        
        Returns:
            Dictionary of tool errors
        """
        with self._tools_lock:
            return self.tool_errors.copy()
    
    def start_monitoring(self):
        """Start monitoring tool configs for changes.

        The built-in poller watches the *local* filesystem (mtime polling). For cloud
        backends (s3/azure/gcs) there is no inotify, so reload is driven by the
        object-store sync manager wired at app startup instead — we skip the local
        poller to avoid acting on a stale or empty local config dir."""
        from sajha.core.storage import LocalStorageBackend
        if not isinstance(get_storage(), LocalStorageBackend):
            self.logger.info("Tool config monitor: cloud backend detected — local poller disabled "
                             "(reload handled by the object-store sync manager)")
            return
        if not self._monitor_thread or not self._monitor_thread.is_alive():
            self._stop_monitor.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_files, daemon=True)
            self._monitor_thread.start()
            self.logger.info("Started file monitoring for tool configurations")
    
    # ── retry of failed tools ────────────────────────────────────────
    # A tool that failed to load (an environment variable, key, package or upstream missing) loads
    # later without a change to its file. Per process on purpose: every worker has its own registry.

    RETRY_CAP_SECONDS = 1800

    @staticmethod
    def retry_interval() -> int:
        """``tools.retry_failed_seconds`` (0: off)."""
        try:
            from sajha.core.config import _get
            return max(0, int(float(_get('tools.retry_failed_seconds', '300') or 0)))
        except (TypeError, ValueError):
            return 300

    def _retryable(self, name: str, error: str) -> bool:
        """A failed tool with a config file of its own; not a duplicate name or a deleted file (those
        resolve only through a file change)."""
        if name in self.tools or error.startswith('Duplicate tool name') or error == 'Configuration file deleted':
            return False
        return self.tool_path(name) is not None

    def retry_failed(self, now: Optional[float] = None) -> List[str]:
        """Try the failed tools whose back-off has run out once more; returns the ones that loaded. The
        first retry is ``tools.retry_failed_seconds`` after the failure, each later one twice as long,
        at most RETRY_CAP_SECONDS. Logs once when a tool starts retrying and once when it loads."""
        import time as _time
        base = self.retry_interval()
        if not base:
            return []
        now = _time.time() if now is None else now
        loaded_skipped = []
        if now >= self.__dict__.get('_skipped_next', 0):
            self._skipped_next = now + base
            loaded_skipped = self.retry_skipped()
        state = self.__dict__.setdefault('_retry_state', {})
        with self._tools_lock:
            failed = {n: str(e) for n, e in self.tool_errors.items() if self._retryable(n, str(e))}
        for gone in [n for n in state if n not in failed]:
            state.pop(gone, None)
        loaded = []
        with self.bulk():
            for name, error in sorted(failed.items()):
                st = state.get(name)
                if st is None:
                    state[name] = {'attempts': 0, 'next': now + base, 'error': error}
                    self.logger.warning(f"Tool {name} failed to load ({error}); retrying every "
                                        f"{base}s and less often after that")
                    continue
                if now < st['next']:
                    continue
                rel = self.tool_path(name)
                if rel:
                    self.load_tool_from_config(rel)
                if name in self.tools:
                    state.pop(name, None)
                    self.tool_errors.pop(name, None)
                    loaded.append(name)
                    self.logger.info(f"Tool {name} loaded on retry {st['attempts'] + 1}")
                    continue
                st['attempts'] += 1
                st['next'] = now + min(base * (2 ** st['attempts']), self.RETRY_CAP_SECONDS)
                err = str(self.tool_errors.get(name, ''))
                if err != st['error']:
                    st['error'] = err
                    self.logger.warning(f"Tool {name} still fails to load, now: {err}")
        return loaded_skipped + loaded

    def start_retrying(self):
        """Start the retry thread (``tools.retry_failed_seconds``; 0: none)."""
        base = self.retry_interval()
        if not base:
            return
        if getattr(self, '_retry_thread', None) is not None and self._retry_thread.is_alive():
            return
        tick = max(1, min(base, 30))

        def loop():
            while not self._stop_monitor.wait(tick):
                try:
                    self.retry_failed()
                except Exception as e:
                    self.logger.error(f"Retrying failed tools: {e}", exc_info=True)
        self._retry_thread = threading.Thread(target=loop, daemon=True, name='tool-retry')
        self._retry_thread.start()

    def stop_monitoring(self):
        """Stop monitoring configuration files (and retrying failed tools)"""
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self.logger.info("Stopped file monitoring")
    
    def _monitor_files(self):
        """Monitor configuration files for changes"""
        # Also track Python module timestamps
        if not hasattr(self, '_module_timestamps'):
            self._module_timestamps = {}
        
        def where():
            st = get_storage()
            return type(st), str(getattr(st, 'base_dir', ''))
        watched = where()              # the directory this monitor watches: a scan never follows a backend
        while not self._stop_monitor.wait(5):  # pointed elsewhere (as tests do; that is not every file deleted)
            if where() != watched:
                continue
            with self.bulk():          # one notification per scan, whatever it found
                self._scan_once()

    def _scan_once(self):
        """One pass of the file monitor (see _monitor_files): the root and every folder."""
        try:
            storage = get_storage()
            idx = self.file_index()
            current, deep = {}, []
            for rel in storage.list_files(self._config_prefix, '*.json'):
                rel = rel.replace('\\', '/')
                if Path(rel).name.startswith('.'):
                    continue
                if not idx.split(rel)[1]:
                    deep.append(rel)
                    continue
                try:
                    current[rel] = storage.get_modified_time(rel)
                except FileNotFoundError:
                    continue
            changed = [rel for rel, mtime in current.items()
                       if rel not in self._file_timestamps or self._file_timestamps[rel] < mtime]
            deleted = [rel for rel in list(self._file_timestamps) if rel not in current]
            for rel in changed:
                self.logger.info(f"Tool configuration {'changed' if rel in self._file_timestamps else 'detected'}: {rel}")
            for rel in deleted:
                self.logger.info(f"Tool configuration deleted: {rel}")
            if changed or deleted:
                self.rescan(changed, deleted)
            self._scan_domain_texts()
            if sorted(deep) != idx.ignored():
                idx.refresh()
                self._report_layout(idx)

            # Check for Python module changes (every iteration)
            self._check_python_modules()

        except Exception as e:
            self.logger.error(f"Error in file monitoring: {e}", exc_info=True)

    def _check_python_modules(self):
        """Check for changes in tool Python modules and reload if needed"""
        try:
            impl_path = Path(__file__).parent / 'impl'
            if not impl_path.exists():
                return
            
            for py_file in impl_path.glob('*.py'):
                if py_file.stem == '__init__':
                    continue
                
                file_path = str(py_file)
                current_mtime = py_file.stat().st_mtime
                
                if file_path in self._module_timestamps:
                    if current_mtime > self._module_timestamps[file_path]:
                        self.logger.info(f"Tool module changed: {py_file.name}")
                        self._module_timestamps[file_path] = current_mtime
                        
                        # Reload the module and affected tools
                        module_name = f'sajha.tools.impl.{py_file.stem}'
                        self._reload_module_and_tools(module_name)
                else:
                    # First time seeing this file
                    self._module_timestamps[file_path] = current_mtime
                    
        except Exception as e:
            self.logger.error(f"Error checking Python modules: {e}", exc_info=True)
    
    def _reload_module_and_tools(self, module_name: str):
        """Reload a Python module and all tools that depend on it"""
        import sys
        
        try:
            # Reload the module
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                self.logger.info(f"Reloaded module: {module_name}")
            
            # Find and reload all tools using this module
            tools_to_reload = []
            for tool_name, config in list(self.tool_configs.items()):
                impl = config.get('implementation', '')
                if module_name in impl:
                    tools_to_reload.append((tool_name, config))
            
            # Reload affected tools
            for tool_name, config in tools_to_reload:
                self.logger.info(f"Re-registering tool {tool_name} due to module change")
                
                # Unregister existing
                if tool_name in self.tools:
                    self.unregister_tool(tool_name)
                
                # Find config file and reload
                rel = self.tool_path(tool_name)
                if rel and get_storage().exists(rel):
                    self.load_tool_from_config(rel)
                    
        except Exception as e:
            self.logger.error(f"Error reloading module {module_name}: {e}", exc_info=True)
    
    def reload_all_tools(self):
        """Reload all tools from configuration"""
        with self.bulk():           # one notification, and none if nothing changed
            with self._tools_lock:
                # Clear existing tools
                self.tools.clear()
                self.tool_configs.clear()
                self.tool_errors.clear()
                self.__dict__.setdefault('skipped_tools', {}).clear()
                self._file_timestamps.clear()
                self._bulk_dirty = True

                # Reload all
                self.load_all_tools()
                self._report_skipped()

            # Listeners run outside the lock but inside bulk(): composites re-register here,
            # so a reload that ends where it started announces nothing
            self._notify_reload()

    def add_reload_listener(self, callback):
        """Register a no-arg callback fired after tools are reloaded (add/remove/modify).
        Used by the semantic tool index to re-sync embeddings incrementally."""
        if not hasattr(self, '_reload_listeners'):
            self._reload_listeners = []
        self._reload_listeners.append(callback)

    def _notify_reload(self):
        for cb in getattr(self, '_reload_listeners', []):
            try:
                cb()
            except Exception as e:
                self.logger.error(f"Reload listener error: {e}", exc_info=True)
    
    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (useful for reconfiguration)."""
        with cls._lock:
            cls._instance = None
            logger = logging.getLogger(__name__)
            logger.info("ToolsRegistry singleton reset")
    
    def reconfigure(self, tools_config_dir: str):
        """
        Reconfigure the registry with a new tools directory.
        
        Args:
            tools_config_dir: New tools config directory path
        """
        with self._tools_lock:
            # Update path
            self.tools_config_dir = Path(tools_config_dir)
            if not self.tools_config_dir.is_absolute():
                self.tools_config_dir = Path.cwd() / self.tools_config_dir
            try:
                self._config_prefix = str(self.tools_config_dir.relative_to(Path.cwd())).replace('\\', '/')
            except ValueError:
                self._config_prefix = self._outside_prefix()
            
            self.logger.info(f"ToolsRegistry reconfigured with: {self.tools_config_dir}")
            
            # Reload all tools
            self.reload_all_tools()


def missing_modules(modules) -> List[str]:
    """The modules of ``modules`` that cannot be imported (found without importing them)."""
    import importlib.util
    out = []
    for m in modules:
        try:
            found = importlib.util.find_spec(m) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            out.append(m)
    return out


def missing_requirements(config: dict) -> List[str]:
    """The modules a tool config's ``requires`` names that are not installed ([] when none, or no requires)."""
    req = config.get('requires') if isinstance(config, dict) else None
    if isinstance(req, str):
        req = [req]
    if not isinstance(req, list):
        return []
    return missing_modules([str(m).strip() for m in req if str(m).strip()])


def _script_tool_compat(tool_class):
    """Wrappers written by older Studio script generators left the schema methods
    abstract and made execute() async; fill both in so the tool can load and run."""
    import asyncio
    import inspect
    if not getattr(tool_class, '__abstractmethods__', None) and \
            not inspect.iscoroutinefunction(tool_class.execute):
        return tool_class

    class _Compat(tool_class):
        def get_input_schema(self):
            return self.config.get('inputSchema') or self.config.get('input_schema') or {'type': 'object'}

        def get_output_schema(self):
            return self.config.get('outputSchema') or self.config.get('output_schema') or {}

        def execute(self, arguments):
            result = super().execute(arguments)
            return asyncio.run(result) if inspect.iscoroutine(result) else result

    _Compat.__name__ = tool_class.__name__
    return _Compat


def _tool_fingerprint(tool) -> tuple:
    """What tools/list shows of one tool: its enabled flag and advertised definition."""
    try:
        definition = json.dumps(tool.to_mcp_format(), sort_keys=True, default=str)
    except Exception:
        definition = repr(tool)
    return bool(getattr(tool, 'enabled', True)), definition


def registry_bulk(registry):
    """``registry.bulk()`` when the registry has it (test doubles may not), else a no-op."""
    from contextlib import nullcontext
    bulk = getattr(registry, 'bulk', None)
    return bulk() if callable(bulk) else nullcontext()


def _publish_tools_changed():
    """Tell MCP clients (listen streams, legacy SSE, WebSocket) the tool list changed."""
    try:
        from sajha.core.change_bus import get_change_bus
        get_change_bus().tools_changed()
    except Exception as e:  # never let notification plumbing break the registry
        _logging.getLogger(__name__).debug(f"tools change notification failed: {e}")


# Module-level logger for reset function
import logging as _logging
_tools_logger = _logging.getLogger(__name__)


def get_tools_registry(tools_config_dir: str = None, force_reinit: bool = False) -> ToolsRegistry:
    """
    Get the ToolsRegistry instance, optionally forcing reinitialization.
    
    Args:
        tools_config_dir: Tools config directory path
        force_reinit: If True, reset and reinitialize with new path
        
    Returns:
        ToolsRegistry instance
    """
    if force_reinit:
        ToolsRegistry.reset_instance()
        _tools_logger.info(f"Forcing ToolsRegistry reinit with: {tools_config_dir}")
    
    return ToolsRegistry(tools_config_dir)
