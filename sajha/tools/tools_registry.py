"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Tools Registry - Singleton pattern for managing MCP tools v2.2.0
"""

import json
import logging
import importlib
import os
import threading
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
from .base_mcp_tool import BaseMCPTool

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
        
        self.tools: Dict[str, BaseMCPTool] = {}
        self.tool_configs: Dict[str, Dict] = {}
        self.tool_errors: Dict[str, str] = {}
        self._tools_lock = threading.RLock()
        self.logger = logging.getLogger(__name__)
        
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
    
    def load_all_tools(self):
        """Load all tools from configuration directory"""
        self.logger.info(f"Loading tools from {self.tools_config_dir}")
        
        # Create directory if it doesn't exist
        self.tools_config_dir.mkdir(parents=True, exist_ok=True)
        
        # Scan for JSON configuration files
        for config_file in self.tools_config_dir.glob('*.json'):
            try:
                self.load_tool_from_config(config_file)
            except Exception as e:
                self.logger.error(f"Error loading tool from {config_file}: {e}")
                self.tool_errors[config_file.stem] = str(e)
    
    def load_tool_from_config(self, config_file: Path):
        """
        Load a tool from a JSON configuration file
        
        Args:
            config_file: Path to the configuration file
        """
        with self._tools_lock:
            try:
                # Track file timestamp
                self._file_timestamps[str(config_file)] = config_file.stat().st_mtime
                
                # Load configuration
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                tool_name = config.get('name')
                if not tool_name:
                    raise ValueError("Tool configuration missing 'name' field")
                
                # Store configuration
                self.tool_configs[tool_name] = config
                
                # Check if it's a built-in tool
                tool_type = config.get('type')
                if tool_type in self.builtin_tools:
                    # Load built-in tool
                    tool_class_path = self.builtin_tools[tool_type]
                    module_path, class_name = tool_class_path.rsplit('.', 1)
                    
                    try:
                        module = importlib.import_module(module_path)
                        tool_class = getattr(module, class_name)
                        tool_instance = tool_class(config)
                        
                        # Register the tool
                        self.register_tool(tool_instance)
                        self.logger.info(f"Loaded built-in tool: {tool_name} ({tool_type})")
                        
                        # Clear any previous errors
                        if tool_name in self.tool_errors:
                            del self.tool_errors[tool_name]
                            
                    except Exception as e:
                        self.logger.error(f"Error loading built-in tool {tool_name}: {e}")
                        self.tool_errors[tool_name] = f"Failed to load: {str(e)}"
                
                elif 'implementation' in config:
                    # Load custom tool implementation
                    impl_path = config['implementation']
                    module_path, class_name = impl_path.rsplit('.', 1)
                    
                    try:
                        module = importlib.import_module(module_path)
                        tool_class = getattr(module, class_name)
                        tool_instance = tool_class(config)
                        
                        # Register the tool
                        self.register_tool(tool_instance)
                        self.logger.info(f"Loaded custom tool: {tool_name}")
                        
                        # Clear any previous errors
                        if tool_name in self.tool_errors:
                            del self.tool_errors[tool_name]
                            
                    except Exception as e:
                        self.logger.error(f"Error loading custom tool {tool_name}: {e}")
                        self.tool_errors[tool_name] = f"Failed to load: {str(e)}"
                
                else:
                    # Generic tool configuration without implementation
                    self.logger.warning(f"Tool {tool_name} has no implementation specified")
                    self.tool_errors[tool_name] = "No implementation specified"
                    
            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid JSON in {config_file}: {e}")
                self.tool_errors[config_file.stem] = f"Invalid JSON: {str(e)}"
            except Exception as e:
                self.logger.error(f"Error loading tool from {config_file}: {e}")
                self.tool_errors[config_file.stem] = str(e)
    
    def register_tool(self, tool: BaseMCPTool):
        """
        Register a tool instance
        
        Args:
            tool: Tool instance to register
        """
        with self._tools_lock:
            self.tools[tool.name] = tool
            self.logger.info(f"Tool registered: {tool.name}")
    
    def unregister_tool(self, tool_name: str):
        """
        Unregister a tool
        
        Args:
            tool_name: Name of the tool to unregister
        """
        with self._tools_lock:
            if tool_name in self.tools:
                del self.tools[tool_name]
                self.logger.info(f"Tool unregistered: {tool_name}")
    
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
            if tool:
                tool.enable()
                # Update config file if exists
                if tool_name in self.tool_configs:
                    self.tool_configs[tool_name]['enabled'] = True
                    self._save_tool_config(tool_name)
                return True
            return False
    
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
            if tool:
                tool.disable()
                # Update config file if exists
                if tool_name in self.tool_configs:
                    self.tool_configs[tool_name]['enabled'] = False
                    self._save_tool_config(tool_name)
                return True
            return False
    
    def _save_tool_config(self, tool_name: str):
        """Save tool configuration to file"""
        if tool_name not in self.tool_configs:
            return
        
        config = self.tool_configs[tool_name]
        config_file = Path(self.tools_config_dir) / f"{tool_name}.json"
        
        try:
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            self._file_timestamps[str(config_file)] = config_file.stat().st_mtime
        except Exception as e:
            self.logger.error(f"Error saving tool config for {tool_name}: {e}")
    
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
        """Start monitoring configuration files for changes"""
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
            try:
                config_path = Path(self.tools_config_dir)
                
                # Check for new or modified JSON config files
                for config_file in config_path.glob('*.json'):
                    file_path = str(config_file)
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
                
                # Check for deleted JSON files
                tracked_files = set(self._file_timestamps.keys())
                existing_files = {str(f) for f in config_path.glob('*.json')}
                
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
                self.logger.error(f"Error in file monitoring: {e}")
    
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
                        module_name = f'tools.impl.{py_file.stem}'
                        self._reload_module_and_tools(module_name)
                else:
                    # First time seeing this file
                    self._module_timestamps[file_path] = current_mtime
                    
        except Exception as e:
            self.logger.error(f"Error checking Python modules: {e}")
    
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
            self.logger.error(f"Error reloading module {module_name}: {e}")
    
    def reload_all_tools(self):
        """Reload all tools from configuration"""
        with self._tools_lock:
            # Clear existing tools
            self.tools.clear()
            self.tool_configs.clear()
            self.tool_errors.clear()
            self._file_timestamps.clear()
            
            # Reload all
            self.load_all_tools()
    
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
