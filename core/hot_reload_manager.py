"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Hot Reload Manager for SAJHA MCP Server v2.0.1
Handles automatic reloading of:
- users.json (user configuration)
- apikeys.json (API key configuration)
- Tool JSON configs (config/tools/*.json)
- Tool Python modules (tools/impl/*.py)
"""

import os
import sys
import json
import logging
import threading
import importlib
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable, Set
import traceback

logger = logging.getLogger(__name__)


class HotReloadManager:
    """
    Centralized hot-reload manager for SAJHA MCP Server.
    Monitors and reloads configuration files and Python modules.
    """
    
    DEFAULT_INTERVAL = 300  # 5 minutes
    
    def __init__(self, 
                 reload_interval: int = None,
                 base_path: str = None):
        """
        Initialize the hot-reload manager.
        
        Args:
            reload_interval: Check interval in seconds (default: 300 = 5 minutes)
            base_path: Base path for the application
        """
        self.reload_interval = reload_interval or self.DEFAULT_INTERVAL
        self.base_path = Path(base_path) if base_path else Path(__file__).parent.parent
        
        # File timestamps tracking
        self._file_timestamps: Dict[str, float] = {}
        self._module_timestamps: Dict[str, float] = {}
        
        # Callback handlers
        self._reload_callbacks: Dict[str, List[Callable]] = {
            'users': [],
            'apikeys': [],
            'tools_config': [],
            'tools_module': [],
            'prompts': []
        }
        
        # Monitoring thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        
        # Track what we're monitoring
        self._monitored_paths: Dict[str, Path] = {}
        self._monitored_modules: Dict[str, Path] = {}
        
        # Statistics
        self._stats = {
            'last_check': None,
            'total_reloads': 0,
            'users_reloads': 0,
            'apikeys_reloads': 0,
            'tools_config_reloads': 0,
            'tools_module_reloads': 0,
            'prompts_reloads': 0,
            'errors': []
        }
        
        logger.info(f"HotReloadManager initialized with {self.reload_interval}s interval")
    
    def register_callback(self, category: str, callback: Callable):
        """
        Register a callback to be called when a category is reloaded.
        
        Args:
            category: One of 'users', 'apikeys', 'tools_config', 'tools_module', 'prompts'
            callback: Function to call on reload
        """
        if category in self._reload_callbacks:
            self._reload_callbacks[category].append(callback)
            logger.debug(f"Registered callback for '{category}'")
    
    def add_file_watch(self, name: str, file_path: Path, category: str):
        """
        Add a file to watch for changes.
        
        Args:
            name: Identifier for this file
            file_path: Path to the file
            category: Category for callbacks
        """
        with self._lock:
            file_path = Path(file_path)
            if file_path.exists():
                self._monitored_paths[name] = file_path
                self._file_timestamps[name] = file_path.stat().st_mtime
                logger.debug(f"Watching file: {name} -> {file_path}")
    
    def add_module_watch(self, module_name: str, module_path: Path):
        """
        Add a Python module to watch for changes.
        
        Args:
            module_name: Full module name (e.g., 'tools.impl.wikipedia_tool')
            module_path: Path to the .py file
        """
        with self._lock:
            module_path = Path(module_path)
            if module_path.exists():
                self._monitored_modules[module_name] = module_path
                self._module_timestamps[module_name] = module_path.stat().st_mtime
                logger.debug(f"Watching module: {module_name} -> {module_path}")
    
    def start(self):
        """Start the hot-reload monitoring thread."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.warning("Hot-reload monitor already running")
            return
        
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="HotReloadMonitor",
            daemon=True
        )
        self._monitor_thread.start()
        logger.info(f"Hot-reload monitoring started (interval: {self.reload_interval}s)")
    
    def stop(self):
        """Stop the hot-reload monitoring thread."""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10)
            logger.info("Hot-reload monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while not self._stop_event.wait(self.reload_interval):
            try:
                self._check_and_reload()
            except Exception as e:
                logger.error(f"Error in hot-reload monitor: {e}")
                self._stats['errors'].append({
                    'time': datetime.now().isoformat(),
                    'error': str(e)
                })
    
    def _check_and_reload(self):
        """Check all monitored files and reload if changed."""
        with self._lock:
            self._stats['last_check'] = datetime.now().isoformat()
            
            # Check JSON config files
            self._check_config_files()
            
            # Check Python modules
            self._check_python_modules()
    
    def _check_config_files(self):
        """Check configuration files for changes."""
        for name, file_path in list(self._monitored_paths.items()):
            try:
                if not file_path.exists():
                    # File was deleted
                    logger.info(f"Config file deleted: {name}")
                    del self._monitored_paths[name]
                    del self._file_timestamps[name]
                    self._trigger_callbacks(self._get_category_from_name(name), 'deleted', name)
                    continue
                
                current_mtime = file_path.stat().st_mtime
                if current_mtime > self._file_timestamps.get(name, 0):
                    logger.info(f"Config file changed: {name} ({file_path})")
                    self._file_timestamps[name] = current_mtime
                    
                    category = self._get_category_from_name(name)
                    self._trigger_callbacks(category, 'modified', name, file_path)
                    self._stats[f'{category}_reloads'] = self._stats.get(f'{category}_reloads', 0) + 1
                    self._stats['total_reloads'] += 1
                    
            except Exception as e:
                logger.error(f"Error checking config file {name}: {e}")
    
    def _check_python_modules(self):
        """Check Python modules for changes and reload if needed."""
        for module_name, module_path in list(self._monitored_modules.items()):
            try:
                if not module_path.exists():
                    # Module file was deleted
                    logger.info(f"Module file deleted: {module_name}")
                    del self._monitored_modules[module_name]
                    del self._module_timestamps[module_name]
                    self._trigger_callbacks('tools_module', 'deleted', module_name)
                    continue
                
                current_mtime = module_path.stat().st_mtime
                if current_mtime > self._module_timestamps.get(module_name, 0):
                    logger.info(f"Module changed: {module_name} ({module_path})")
                    self._module_timestamps[module_name] = current_mtime
                    
                    # Reload the module
                    if self._reload_module(module_name):
                        self._trigger_callbacks('tools_module', 'modified', module_name, module_path)
                        self._stats['tools_module_reloads'] += 1
                        self._stats['total_reloads'] += 1
                    
            except Exception as e:
                logger.error(f"Error checking module {module_name}: {e}")
    
    def _reload_module(self, module_name: str) -> bool:
        """
        Reload a Python module.
        
        Args:
            module_name: Full module name
            
        Returns:
            True if reload was successful
        """
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                logger.info(f"Successfully reloaded module: {module_name}")
                return True
            else:
                # Module not loaded yet, just import it fresh
                importlib.import_module(module_name)
                logger.info(f"Successfully loaded module: {module_name}")
                return True
        except Exception as e:
            logger.error(f"Failed to reload module {module_name}: {e}\n{traceback.format_exc()}")
            return False
    
    def _get_category_from_name(self, name: str) -> str:
        """Determine category from file name."""
        if 'users' in name.lower():
            return 'users'
        elif 'apikey' in name.lower():
            return 'apikeys'
        elif 'prompt' in name.lower():
            return 'prompts'
        elif 'tool' in name.lower():
            return 'tools_config'
        return 'unknown'
    
    def _trigger_callbacks(self, category: str, action: str, name: str, path: Path = None):
        """Trigger all callbacks for a category."""
        callbacks = self._reload_callbacks.get(category, [])
        for callback in callbacks:
            try:
                callback(action, name, path)
            except Exception as e:
                logger.error(f"Error in reload callback for {category}: {e}")
    
    def force_reload_all(self):
        """Force reload all monitored files and modules."""
        logger.info("Forcing reload of all monitored files and modules")
        
        with self._lock:
            # Reset all timestamps to force reload
            for name in self._file_timestamps:
                self._file_timestamps[name] = 0
            for name in self._module_timestamps:
                self._module_timestamps[name] = 0
            
            # Run check
            self._check_and_reload()
    
    def get_statistics(self) -> Dict:
        """Get reload statistics."""
        with self._lock:
            return {
                **self._stats,
                'monitored_files': len(self._monitored_paths),
                'monitored_modules': len(self._monitored_modules),
                'is_running': self._monitor_thread is not None and self._monitor_thread.is_alive(),
                'interval_seconds': self.reload_interval
            }
    
    def get_monitored_items(self) -> Dict:
        """Get list of all monitored items."""
        with self._lock:
            return {
                'files': {name: str(path) for name, path in self._monitored_paths.items()},
                'modules': {name: str(path) for name, path in self._monitored_modules.items()}
            }


class ConfigReloader:
    """
    Helper class to set up hot-reloading for SAJHA MCP Server components.
    """
    
    def __init__(self, 
                 auth_manager=None,
                 apikey_manager=None,
                 tools_registry=None,
                 prompts_registry=None,
                 reload_interval: int = 300):
        """
        Initialize config reloader with component references.
        
        Args:
            auth_manager: AuthManager instance
            apikey_manager: APIKeyManager instance  
            tools_registry: ToolsRegistry instance
            prompts_registry: PromptsRegistry instance
            reload_interval: Reload interval in seconds
        """
        self.auth_manager = auth_manager
        self.apikey_manager = apikey_manager
        self.tools_registry = tools_registry
        self.prompts_registry = prompts_registry
        
        self.hot_reload = HotReloadManager(reload_interval=reload_interval)
        
        # Set up watches and callbacks
        self._setup_watches()
        self._setup_callbacks()
    
    def _setup_watches(self):
        """Set up file watches for all components."""
        base_path = Path(__file__).parent.parent
        
        # Watch users.json
        users_path = base_path / 'config' / 'users.json'
        if users_path.exists():
            self.hot_reload.add_file_watch('users.json', users_path, 'users')
        
        # Watch apikeys.json
        apikeys_path = base_path / 'config' / 'apikeys.json'
        if apikeys_path.exists():
            self.hot_reload.add_file_watch('apikeys.json', apikeys_path, 'apikeys')
        
        # Watch all tool JSON configs
        tools_config_path = base_path / 'config' / 'tools'
        if tools_config_path.exists():
            for config_file in tools_config_path.glob('*.json'):
                self.hot_reload.add_file_watch(
                    f'tool_config:{config_file.stem}',
                    config_file,
                    'tools_config'
                )
        
        # Watch all tool Python modules
        tools_impl_path = base_path / 'tools' / 'impl'
        if tools_impl_path.exists():
            for py_file in tools_impl_path.glob('*.py'):
                if py_file.stem != '__init__':
                    module_name = f'tools.impl.{py_file.stem}'
                    self.hot_reload.add_module_watch(module_name, py_file)
        
        # Watch prompts JSON files
        prompts_path = base_path / 'config' / 'prompts'
        if prompts_path.exists():
            for prompt_file in prompts_path.glob('*.json'):
                self.hot_reload.add_file_watch(
                    f'prompt:{prompt_file.stem}',
                    prompt_file,
                    'prompts'
                )
        
        logger.info("File watches configured for hot-reload")
    
    def _setup_callbacks(self):
        """Set up reload callbacks for each component."""
        
        # Users callback
        def on_users_change(action, name, path):
            if self.auth_manager:
                logger.info(f"Reloading users configuration ({action})")
                self.auth_manager.load_users()
        
        self.hot_reload.register_callback('users', on_users_change)
        
        # API Keys callback
        def on_apikeys_change(action, name, path):
            if self.apikey_manager:
                logger.info(f"Reloading API keys configuration ({action})")
                self.apikey_manager.reload()
        
        self.hot_reload.register_callback('apikeys', on_apikeys_change)
        
        # Tools config callback
        def on_tools_config_change(action, name, path):
            if self.tools_registry:
                tool_name = name.replace('tool_config:', '')
                if action == 'deleted':
                    logger.info(f"Unregistering deleted tool: {tool_name}")
                    self.tools_registry.unregister_tool(tool_name)
                else:
                    logger.info(f"Reloading tool configuration: {tool_name}")
                    if path and path.exists():
                        self.tools_registry.load_tool_from_config(path)
        
        self.hot_reload.register_callback('tools_config', on_tools_config_change)
        
        # Tools module callback
        def on_tools_module_change(action, module_name, path):
            if self.tools_registry:
                logger.info(f"Tool module changed: {module_name}")
                # Re-register tools that use this module
                self._reload_tools_using_module(module_name)
        
        self.hot_reload.register_callback('tools_module', on_tools_module_change)
        
        # Prompts callback
        def on_prompts_change(action, name, path):
            if self.prompts_registry:
                prompt_name = name.replace('prompt:', '')
                if action == 'deleted':
                    logger.info(f"Prompt deleted: {prompt_name}")
                    # PromptsRegistry should handle this
                else:
                    logger.info(f"Reloading prompt: {prompt_name}")
                self.prompts_registry.reload()
        
        self.hot_reload.register_callback('prompts', on_prompts_change)
        
        logger.info("Reload callbacks configured")
    
    def _reload_tools_using_module(self, module_name: str):
        """Reload all tools that use a specific module."""
        if not self.tools_registry:
            return
        
        # Find tools using this module
        for tool_name, config in list(self.tools_registry.tool_configs.items()):
            impl = config.get('implementation', '')
            if impl.startswith(module_name) or module_name in impl:
                logger.info(f"Re-registering tool {tool_name} due to module change")
                
                # Find the config file
                base_path = Path(__file__).parent.parent
                config_path = base_path / 'config' / 'tools' / f'{tool_name}.json'
                
                if config_path.exists():
                    # Unregister and reload
                    self.tools_registry.unregister_tool(tool_name)
                    self.tools_registry.load_tool_from_config(config_path)
    
    def start(self):
        """Start hot-reload monitoring."""
        self.hot_reload.start()
    
    def stop(self):
        """Stop hot-reload monitoring."""
        self.hot_reload.stop()
    
    def force_reload(self):
        """Force immediate reload of all configurations."""
        self.hot_reload.force_reload_all()
    
    def get_status(self) -> Dict:
        """Get hot-reload status and statistics."""
        return {
            'hot_reload': self.hot_reload.get_statistics(),
            'monitored': self.hot_reload.get_monitored_items()
        }


# Singleton instance
_config_reloader: Optional[ConfigReloader] = None


def get_config_reloader(auth_manager=None, 
                        apikey_manager=None,
                        tools_registry=None,
                        prompts_registry=None,
                        reload_interval: int = 300) -> ConfigReloader:
    """
    Get or create the singleton ConfigReloader instance.
    
    Args:
        auth_manager: AuthManager instance
        apikey_manager: APIKeyManager instance
        tools_registry: ToolsRegistry instance
        prompts_registry: PromptsRegistry instance
        reload_interval: Reload interval in seconds
        
    Returns:
        ConfigReloader instance
    """
    global _config_reloader
    if _config_reloader is None:
        _config_reloader = ConfigReloader(
            auth_manager=auth_manager,
            apikey_manager=apikey_manager,
            tools_registry=tools_registry,
            prompts_registry=prompts_registry,
            reload_interval=reload_interval
        )
    return _config_reloader
