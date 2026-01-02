"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Base MCP Tool Class
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

class BaseMCPTool(ABC):
    """
    Abstract base class for all MCP tools
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the tool
        
        Args:
            config: Tool configuration dictionary
        """
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._name = self.config.get('name', self.__class__.__name__)
        self._description = self.config.get('description', '')
        self._version = self.config.get('version', '1.0.0')
        self._enabled = self.config.get('enabled', True)
        self._input_schema = self.config.get('inputSchema', {})
        self._output_schema = self.config.get('outputSchema', {})
        self._metadata = self.config.get('metadata', {})
        self._execution_count = 0
        self._last_execution = None
        self._total_execution_time = 0.0
    
    @property
    def name(self) -> str:
        """Get tool name"""
        return self._name
    
    @property
    def description(self) -> str:
        """Get tool description"""
        return self._description
    
    @property
    def version(self) -> str:
        """Get tool version"""
        return self._version
    
    @property
    def enabled(self) -> bool:
        """Check if tool is enabled"""
        return self._enabled
    
    @property
    def input_schema(self) -> Dict:
        """Get input schema for the tool"""
        if not self._input_schema:
            return self.get_input_schema()
        return self._input_schema

    @property
    def output_schema(self) -> Dict:
        if not self._output_schema:
            return self.get_output_schema()
        return self._output_schema


    def enable(self):
        """Enable the tool"""
        self._enabled = True
        self.logger.info(f"Tool enabled: {self.name}")
    
    def disable(self):
        """Disable the tool"""
        self._enabled = False
        self.logger.info(f"Tool disabled: {self.name}")
    
    @abstractmethod
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute the tool with given arguments
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Tool execution result
        """
        pass
    
    @abstractmethod
    def get_input_schema(self) -> Dict:
        """
        Get the JSON schema for tool inputs
        
        Returns:
            JSON schema dictionary
        """
        pass

    @abstractmethod
    def get_output_schema(self) -> Dict:
        """
            Get the JSON schema for tool outputs

            Returns:
                JSON schema dictionary
            """
        pass


    def validate_arguments(self, arguments: Dict[str, Any]) -> bool:
        """
        Validate arguments against input schema
        
        Args:
            arguments: Tool arguments
            
        Returns:
            True if valid
        """
        # Basic validation - can be enhanced with jsonschema
        required_params = self.input_schema.get('required', [])
        for param in required_params:
            if param not in arguments:
                raise ValueError(f"Missing required parameter: {param}")
        return True
    
    def execute_with_tracking(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute tool with performance tracking
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Tool execution result
        """
        if not self.enabled:
            raise RuntimeError(f"Tool is disabled: {self.name}")
        
        # Validate arguments
        self.validate_arguments(arguments)
        
        # Track execution
        start_time = datetime.now()
        try:
            result = self.execute(arguments)
            execution_time = (datetime.now() - start_time).total_seconds()
            
            # Update metrics
            self._execution_count += 1
            self._last_execution = datetime.now()
            self._total_execution_time += execution_time
            
            self.logger.info(f"Tool executed successfully: {self.name} ({execution_time:.2f}s)")
            return result
            
        except Exception as e:
            self.logger.error(f"Tool execution failed: {self.name} - {str(e)}", exc_info=True)
            raise
    
    def get_metrics(self) -> Dict:
        """
        Get tool execution metrics
        
        Returns:
            Metrics dictionary
        """
        avg_execution_time = (
            self._total_execution_time / self._execution_count 
            if self._execution_count > 0 else 0
        )
        
        return {
            "name": self.name,
            "version": self.version,
            "enabled": self.enabled,
            "execution_count": self._execution_count,
            "last_execution": self._last_execution.isoformat() + "Z" if self._last_execution else None,
            "total_execution_time": self._total_execution_time,
            "average_execution_time": avg_execution_time
        }
    
    def to_mcp_format(self) -> Dict:
        """
        Convert tool to MCP format for tools/list response
        
        Returns:
            MCP formatted tool dictionary
        """
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema
        }
    
    def load_from_config(self, config_path: str):
        """
        Load tool configuration from JSON file
        
        Args:
            config_path: Path to configuration file
        """
        try:
            with open(config_path, 'r') as f:
                self.config = json.load(f)
                self._name = self.config.get('name', self.name)
                self._description = self.config.get('description', self.description)
                self._version = self.config.get('version', self.version)
                self._enabled = self.config.get('enabled', True)
                self._input_schema = self.config.get('inputSchema', {})
                self._metadata = self.config.get('metadata', {})
                self.logger.info(f"Tool configuration loaded: {self.name}")
        except Exception as e:
            self.logger.error(f"Error loading tool configuration: {e}")
            raise
