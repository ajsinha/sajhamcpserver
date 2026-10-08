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

# Default path relative to project root
DEFAULT_TOOLS_DIR = 'config/tools'


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
            tools_config_dir = DEFAULT_TOOLS_DIR
        
        self.tools_config_dir = Path(tools_config_dir)
        if not self.tools_config_dir.is_absolute():
            self.tools_config_dir = Path.cwd() / self.tools_config_dir

        # Logical prefix for tool configs *relative to the storage backend base*
        # (e.g. 'config/tools'). All tool-config IO flows through get_storage()
        # using this prefix, so configs can live on local disk, S3, Azure, or GCS.
        try:
            self._config_prefix = str(self.tools_config_dir.relative_to(Path.cwd())).replace('\\', '/')
        except ValueError:
            self._config_prefix = 'config/tools'
        
        self.tools: Dict[str, BaseMCPTool] = {}
        self.tool_configs: Dict[str, Dict] = {}
        self.tool_errors: Dict[str, str] = {}
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
        
        # Start file monitoring
        self.start_monitoring()
    
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
        """Normalize any reference (storage path / Path / bare filename) to the
        storage-relative tool-config path, e.g. 'config/tools/foo.json'."""
        name = Path(str(ref)).name
        if not name.endswith('.json'):
            name = f'{name}.json'
        return f"{self._config_prefix}/{name}"

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
        """Load all tools from the configured store (local | s3 | azure | gcs)."""
        storage = get_storage()
        self.logger.info(f"Loading tools from '{self._config_prefix}' via {type(storage).__name__}")
        with self.bulk():
            for rel in storage.list_files(self._config_prefix, '*.json'):
                try:
                    self.load_tool_from_config(rel)
                except Exception as e:
                    self.logger.error(f"Error loading tool from {rel}: {e}", exc_info=True)
                    self.tool_errors[Path(rel).stem] = str(e)

    def load_tool_from_config(self, config_ref):
        """
        Load a tool from its JSON configuration, read through the storage backend.

        Args:
            config_ref: a storage-relative path, a Path, or a bare filename. All are
                        normalized to 'config/tools/<name>.json' and read via get_storage().
        """
        rel = self._config_rel(config_ref)
        storage = get_storage()
        with self._tools_lock:
            try:
                self._file_timestamps[rel] = storage.get_modified_time(rel)
                config = storage.read_json(rel)
            except FileNotFoundError:
                self.logger.error(f"Tool config not found: {rel}")
                self.tool_errors[Path(rel).stem] = "Config not found"
                return
            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid JSON in {rel}: {e}", exc_info=True)
                self.tool_errors[Path(rel).stem] = f"Invalid JSON: {str(e)}"
                return
            except Exception as e:
                self.logger.error(f"Error reading tool config {rel}: {e}", exc_info=True)
                self.tool_errors[Path(rel).stem] = str(e)
                return
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
    
    def stop_monitoring(self):
        """Stop monitoring configuration files"""
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self.logger.info("Stopped file monitoring")
    
    def _monitor_files(self):
        """Monitor configuration files for changes"""
        # Also track Python module timestamps
        if not hasattr(self, '_module_timestamps'):
            self._module_timestamps = {}
        
        while not self._stop_monitor.wait(5):  # Check every 5 seconds
            with self.bulk():          # one notification per scan, whatever it found
                self._scan_once()

    def _scan_once(self):
        """One pass of the file monitor (see _monitor_files)."""
        try:
            config_path = Path(self.tools_config_dir)
            
            # Check for new or modified JSON config files
            for config_file in config_path.glob('*.json'):
                # Key by the storage-relative path so it matches the timestamps
                # recorded by load_tool_from_config (which is storage-backed).
                file_path = self._config_rel(config_file)
                current_mtime = config_file.stat().st_mtime
                
                if file_path not in self._file_timestamps:
                    # New file
                    self.logger.info(f"New tool configuration detected: {config_file.name}")
                    self.load_tool_from_config(config_file)
                elif self._file_timestamps[file_path] < current_mtime:
                    # Modified file
                    self.logger.info(f"Tool configuration changed: {config_file.name}")
                    tool_name = config_file.stem
                    
                    # Unload existing tool
                    if tool_name in self.tools:
                        self.unregister_tool(tool_name)
                    
                    # Reload tool
                    self.load_tool_from_config(config_file)
            
            # Check for deleted JSON files (compare on the same relative keys)
            tracked_files = set(self._file_timestamps.keys())
            existing_files = {self._config_rel(f) for f in config_path.glob('*.json')}
            
            for deleted_file in tracked_files - existing_files:
                self.logger.info(f"Tool configuration deleted: {Path(deleted_file).name}")
                tool_name = Path(deleted_file).stem
                
                # Unregister tool
                if tool_name in self.tools:
                    self.unregister_tool(tool_name)
                
                # Remove from tracking
                del self._file_timestamps[deleted_file]
                
                # Remove from configs
                if tool_name in self.tool_configs:
                    del self.tool_configs[tool_name]
                
                # Mark as error
                self.tool_errors[tool_name] = "Configuration file deleted"
            
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
                config_path = Path(self.tools_config_dir)
                config_file = config_path / f'{tool_name}.json'
                if config_file.exists():
                    self.load_tool_from_config(config_file)
                    
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
                self._file_timestamps.clear()
                self._bulk_dirty = True

                # Reload all
                self.load_all_tools()

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
            
            self.logger.info(f"ToolsRegistry reconfigured with: {self.tools_config_dir}")
            
            # Reload all tools
            self.reload_all_tools()


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
