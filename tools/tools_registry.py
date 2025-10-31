"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Tools Registry - Singleton pattern for managing MCP tools
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
    
    def __init__(self, tools_config_dir: str = 'config/tools'):
        """
        Initialize the tools registry
        
        Args:
            tools_config_dir: Directory containing tool configuration files
        """
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.tools_config_dir = tools_config_dir
        self.tools: Dict[str, BaseMCPTool] = {}
        self.tool_configs: Dict[str, Dict] = {}
        self.tool_errors: Dict[str, str] = {}
        self._tools_lock = threading.RLock()
        self.logger = logging.getLogger(__name__)
        
        # File monitoring
        self._file_timestamps: Dict[str, float] = {}
        self._monitor_thread = None
        self._stop_monitor = threading.Event()
        
        # Built-in tools mapping
        self.builtin_tools = {}
        '''
        self.builtin_tools = {
            'wikipedia': 'tools.impl.wikipedia_tool.WikipediaTool',
            'yahoo_finance': 'tools.impl.yahoo_finance_tool.YahooFinanceTool',
            'google_search': 'tools.impl.google_search_tool.GoogleSearchTool',
            'fed_reserve': 'tools.impl.fed_reserve_tool.FedReserveTool',
             'tavily': 'tools.impl.tavily_tool.TavilyTool'
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
        os.makedirs(self.tools_config_dir, exist_ok=True)
        
        # Scan for JSON configuration files
        config_path = Path(self.tools_config_dir)
        for config_file in config_path.glob('*.json'):
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
        while not self._stop_monitor.wait(5):  # Check every 5 seconds
            try:
                config_path = Path(self.tools_config_dir)
                
                # Check for new or modified files
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
                
                # Check for deleted files
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
                    
            except Exception as e:
                self.logger.error(f"Error in file monitoring: {e}")
    
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
