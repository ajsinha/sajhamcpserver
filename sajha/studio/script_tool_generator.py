"""
SAJHA MCP Server - Script Tool Generator v2.8.0

Generates MCP tools from shell scripts, Python scripts, and other executable scripts.
Scripts receive an array of string arguments and return STDOUT/STDERR.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import os
import json
import stat
import logging
import subprocess
import tempfile
import shutil
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ScriptToolConfig:
    """Configuration for a script-based MCP tool."""
    
    # Basic Info
    tool_name: str
    description: str
    script_type: str  # 'shell', 'python', 'bash', 'powershell', 'node'
    script_content: str
    
    # Optional metadata
    version: str = "2.8.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Execution settings
    timeout_seconds: int = 30
    working_directory: str = ""
    environment_vars: Dict[str, str] = field(default_factory=dict)
    
    # Input configuration
    max_args: int = 10
    arg_descriptions: List[str] = field(default_factory=list)
    
    # Security settings
    allow_stdin: bool = False
    capture_stderr: bool = True
    
    # Tool literature for AI context
    literature: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'tool_name': self.tool_name,
            'description': self.description,
            'script_type': self.script_type,
            'script_content': self.script_content,
            'version': self.version,
            'author': self.author,
            'tags': self.tags,
            'timeout_seconds': self.timeout_seconds,
            'working_directory': self.working_directory,
            'environment_vars': self.environment_vars,
            'max_args': self.max_args,
            'arg_descriptions': self.arg_descriptions,
            'allow_stdin': self.allow_stdin,
            'capture_stderr': self.capture_stderr,
            'literature': self.literature
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ScriptToolConfig':
        """Create from dictionary."""
        return cls(
            tool_name=data.get('tool_name', ''),
            description=data.get('description', ''),
            script_type=data.get('script_type', 'shell'),
            script_content=data.get('script_content', ''),
            version=data.get('version', '2.8.0'),
            author=data.get('author', ''),
            tags=data.get('tags', []),
            timeout_seconds=data.get('timeout_seconds', 30),
            working_directory=data.get('working_directory', ''),
            environment_vars=data.get('environment_vars', {}),
            max_args=data.get('max_args', 10),
            arg_descriptions=data.get('arg_descriptions', []),
            allow_stdin=data.get('allow_stdin', False),
            capture_stderr=data.get('capture_stderr', True),
            literature=data.get('literature', '')
        )


class ScriptToolGenerator:
    """Generator for script-based MCP tools."""
    
    # Script type to file extension and interpreter mapping
    SCRIPT_TYPES = {
        'shell': {'extension': '.sh', 'interpreter': '/bin/sh', 'shebang': '#!/bin/sh'},
        'bash': {'extension': '.sh', 'interpreter': '/bin/bash', 'shebang': '#!/bin/bash'},
        'python': {'extension': '.py', 'interpreter': 'python3', 'shebang': '#!/usr/bin/env python3'},
        'powershell': {'extension': '.ps1', 'interpreter': 'pwsh', 'shebang': '#!/usr/bin/env pwsh'},
        'node': {'extension': '.js', 'interpreter': 'node', 'shebang': '#!/usr/bin/env node'},
        'perl': {'extension': '.pl', 'interpreter': 'perl', 'shebang': '#!/usr/bin/env perl'},
        'ruby': {'extension': '.rb', 'interpreter': 'ruby', 'shebang': '#!/usr/bin/env ruby'}
    }
    
    def __init__(self, config_dir: str, scripts_dir: str, impl_dir: str):
        """
        Initialize the generator.
        
        Args:
            config_dir: Directory for tool JSON configs (config/tools/)
            scripts_dir: Directory for script files (config/scripts/)
            impl_dir: Directory for Python wrapper implementations (sajha/tools/impl/)
        """
        self.config_dir = config_dir
        self.scripts_dir = scripts_dir
        self.impl_dir = impl_dir
        
        # Ensure directories exist
        os.makedirs(scripts_dir, exist_ok=True)
    
    def validate_config(self, config: ScriptToolConfig) -> List[str]:
        """
        Validate the script tool configuration.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        
        # Tool name validation
        if not config.tool_name:
            errors.append("Tool name is required")
        elif not config.tool_name.replace('_', '').isalnum():
            errors.append("Tool name must contain only alphanumeric characters and underscores")
        elif config.tool_name[0].isdigit():
            errors.append("Tool name cannot start with a digit")
        
        # Script type validation
        if config.script_type not in self.SCRIPT_TYPES:
            errors.append(f"Invalid script type: {config.script_type}. Valid types: {list(self.SCRIPT_TYPES.keys())}")
        
        # Script content validation
        if not config.script_content or not config.script_content.strip():
            errors.append("Script content is required")
        
        # Description validation
        if not config.description:
            errors.append("Description is required")
        
        # Timeout validation
        if config.timeout_seconds < 1 or config.timeout_seconds > 300:
            errors.append("Timeout must be between 1 and 300 seconds")
        
        # Max args validation
        if config.max_args < 0 or config.max_args > 100:
            errors.append("Max args must be between 0 and 100")
        
        return errors
    
    def detect_script_type(self, content: str, filename: Optional[str] = None) -> str:
        """
        Auto-detect script type from content or filename.
        
        Args:
            content: Script content
            filename: Optional filename for extension-based detection
            
        Returns:
            Detected script type
        """
        # Check filename extension first
        if filename:
            ext = os.path.splitext(filename)[1].lower()
            ext_map = {
                '.sh': 'bash',
                '.bash': 'bash',
                '.py': 'python',
                '.ps1': 'powershell',
                '.js': 'node',
                '.pl': 'perl',
                '.rb': 'ruby'
            }
            if ext in ext_map:
                return ext_map[ext]
        
        # Check shebang line
        first_line = content.strip().split('\n')[0] if content else ''
        if first_line.startswith('#!'):
            shebang = first_line.lower()
            if 'python' in shebang:
                return 'python'
            elif 'bash' in shebang:
                return 'bash'
            elif 'sh' in shebang:
                return 'shell'
            elif 'node' in shebang:
                return 'node'
            elif 'perl' in shebang:
                return 'perl'
            elif 'ruby' in shebang:
                return 'ruby'
            elif 'pwsh' in shebang or 'powershell' in shebang:
                return 'powershell'
        
        # Content-based heuristics
        if 'def ' in content and 'import ' in content:
            return 'python'
        elif 'function ' in content and ('$' in content or 'param(' in content.lower()):
            return 'powershell'
        elif 'const ' in content or 'require(' in content or 'import ' in content:
            return 'node'
        
        # Default to bash
        return 'bash'
    
    def generate_tool_config(self, config: ScriptToolConfig) -> dict:
        """
        Generate the MCP tool JSON configuration.
        
        Args:
            config: Script tool configuration
            
        Returns:
            Tool configuration dictionary
        """
        # Generate input schema
        input_schema = {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": config.max_args,
                    "description": "Array of string arguments to pass to the script"
                }
            },
            "required": []
        }
        
        # Add individual arg descriptions if provided
        if config.arg_descriptions:
            input_schema["properties"]["args"]["description"] = (
                "Arguments: " + ", ".join(
                    f"[{i}] {desc}" for i, desc in enumerate(config.arg_descriptions)
                )
            )
        
        # Generate output schema
        output_schema = {
            "type": "object",
            "properties": {
                "stdout": {
                    "type": "string",
                    "description": "Standard output from the script"
                },
                "stderr": {
                    "type": "string",
                    "description": "Standard error output from the script"
                },
                "exit_code": {
                    "type": "integer",
                    "description": "Exit code from the script (0 = success)"
                },
                "success": {
                    "type": "boolean",
                    "description": "Whether the script executed successfully"
                }
            }
        }
        
        tool_config = {
            "name": config.tool_name,
            "description": config.description,
            "version": config.version,
            "author": config.author,
            "tags": config.tags,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "implementation": {
                "type": "script",
                "script_type": config.script_type,
                "script_file": f"{config.tool_name}{self.SCRIPT_TYPES[config.script_type]['extension']}",
                "timeout_seconds": config.timeout_seconds,
                "working_directory": config.working_directory,
                "environment_vars": config.environment_vars,
                "capture_stderr": config.capture_stderr
            },
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "created_by": "MCP Studio Script Tool Creator",
                "generator_version": "2.8.0"
            }
        }
        
        # Add literature if provided
        if config.literature:
            tool_config["literature"] = config.literature
        
        return tool_config
    
    def generate_python_wrapper(self, config: ScriptToolConfig) -> str:
        """
        Generate the Python wrapper implementation that executes the script.
        
        Args:
            config: Script tool configuration
            
        Returns:
            Python implementation code
        """
        script_info = self.SCRIPT_TYPES.get(config.script_type, self.SCRIPT_TYPES['bash'])
        script_filename = f"{config.tool_name}{script_info['extension']}"
        
        code = f'''"""
SAJHA MCP Server - Script Tool: {config.tool_name}

Auto-generated by MCP Studio Script Tool Creator v2.8.0
Generated: {datetime.now().isoformat()}

{config.description}

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import os
import subprocess
import logging
from typing import Dict, Any, List, Optional

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)


class {self._to_class_name(config.tool_name)}(BaseMCPTool):
    """
    Script-based MCP Tool: {config.tool_name}
    
    {config.description}
    
    Script Type: {config.script_type}
    Timeout: {config.timeout_seconds} seconds
    """
    
    def __init__(self, tool_config: dict):
        """Initialize the script tool."""
        super().__init__(tool_config)
        self.script_type = "{config.script_type}"
        self.script_filename = "{script_filename}"
        self.timeout_seconds = {config.timeout_seconds}
        self.capture_stderr = {config.capture_stderr}
        self.working_directory = "{config.working_directory}" or None
        self.environment_vars = {repr(config.environment_vars)}
        
        # Locate the script file
        self.script_path = self._find_script_path()
    
    def _find_script_path(self) -> str:
        """Find the script file path."""
        # Check in config/scripts directory
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        scripts_dir = os.path.join(base_dir, "config", "scripts")
        script_path = os.path.join(scripts_dir, self.script_filename)
        
        if os.path.exists(script_path):
            return script_path
        
        # Fallback to current directory
        logger.warning(f"Script not found at {{script_path}}, will try relative path")
        return self.script_filename
    
    def _get_interpreter(self) -> List[str]:
        """Get the interpreter command for this script type."""
        interpreters = {{
            'shell': ['/bin/sh'],
            'bash': ['/bin/bash'],
            'python': ['python3'],
            'powershell': ['pwsh', '-File'],
            'node': ['node'],
            'perl': ['perl'],
            'ruby': ['ruby']
        }}
        return interpreters.get(self.script_type, ['/bin/sh'])
    
    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the script with provided arguments.
        
        Args:
            arguments: Dictionary with 'args' key containing list of string arguments
            
        Returns:
            Dictionary with stdout, stderr, exit_code, and success
        """
        try:
            # Get arguments
            args = arguments.get('args', [])
            if not isinstance(args, list):
                args = [str(args)] if args else []
            
            # Ensure all args are strings
            args = [str(arg) for arg in args]
            
            # Build command
            interpreter = self._get_interpreter()
            cmd = interpreter + [self.script_path] + args
            
            logger.info(f"Executing script: {{' '.join(cmd)}}")
            
            # Prepare environment
            env = os.environ.copy()
            if self.environment_vars:
                env.update(self.environment_vars)
            
            # Execute the script
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=self.working_directory,
                env=env
            )
            
            return {{
                "stdout": result.stdout,
                "stderr": result.stderr if self.capture_stderr else "",
                "exit_code": result.returncode,
                "success": result.returncode == 0
            }}
            
        except subprocess.TimeoutExpired as e:
            logger.error(f"Script timeout after {{self.timeout_seconds}}s: {{e}}")
            return {{
                "stdout": "",
                "stderr": f"Script timed out after {{self.timeout_seconds}} seconds",
                "exit_code": -1,
                "success": False
            }}
        except FileNotFoundError as e:
            logger.error(f"Script not found: {{e}}")
            return {{
                "stdout": "",
                "stderr": f"Script file not found: {{self.script_path}}",
                "exit_code": -2,
                "success": False
            }}
        except Exception as e:
            logger.error(f"Script execution error: {{e}}")
            return {{
                "stdout": "",
                "stderr": str(e),
                "exit_code": -3,
                "success": False
            }}


# Export the tool class
TOOL_CLASS = {self._to_class_name(config.tool_name)}
'''
        return code
    
    def _to_class_name(self, tool_name: str) -> str:
        """Convert tool name to Python class name."""
        # Convert snake_case to PascalCase
        parts = tool_name.split('_')
        return ''.join(part.capitalize() for part in parts) + 'ScriptTool'
    
    def save_script_file(self, config: ScriptToolConfig) -> str:
        """
        Save the script file to disk.
        
        Args:
            config: Script tool configuration
            
        Returns:
            Path to the saved script file
        """
        script_info = self.SCRIPT_TYPES.get(config.script_type, self.SCRIPT_TYPES['bash'])
        script_filename = f"{config.tool_name}{script_info['extension']}"
        script_path = os.path.join(self.scripts_dir, script_filename)
        
        # Prepare script content
        content = config.script_content
        
        # Add shebang if not present (for Unix scripts)
        if config.script_type in ['shell', 'bash', 'python', 'perl', 'ruby', 'node']:
            if not content.strip().startswith('#!'):
                content = script_info['shebang'] + '\n' + content
        
        # Write the script
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Make executable on Unix
        if config.script_type in ['shell', 'bash', 'python', 'perl', 'ruby', 'node']:
            os.chmod(script_path, os.stat(script_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        logger.info(f"Saved script file: {script_path}")
        return script_path
    
    def generate_tool(self, config: ScriptToolConfig) -> Dict[str, Any]:
        """
        Generate the complete script tool (config, script file, and Python wrapper).
        
        Args:
            config: Script tool configuration
            
        Returns:
            Dictionary with generation results and file paths
        """
        # Validate configuration
        errors = self.validate_config(config)
        if errors:
            return {
                'success': False,
                'errors': errors
            }
        
        try:
            # Generate tool config JSON
            tool_config = self.generate_tool_config(config)
            config_path = os.path.join(self.config_dir, f"{config.tool_name}.json")
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(tool_config, f, indent=2)
            
            logger.info(f"Generated tool config: {config_path}")
            
            # Save script file
            script_path = self.save_script_file(config)
            
            # Generate Python wrapper
            wrapper_code = self.generate_python_wrapper(config)
            wrapper_path = os.path.join(self.impl_dir, f"{config.tool_name}_script_tool.py")
            
            with open(wrapper_path, 'w', encoding='utf-8') as f:
                f.write(wrapper_code)
            
            logger.info(f"Generated Python wrapper: {wrapper_path}")
            
            return {
                'success': True,
                'tool_name': config.tool_name,
                'config_path': config_path,
                'script_path': script_path,
                'wrapper_path': wrapper_path,
                'tool_config': tool_config,
                'message': f"Script tool '{config.tool_name}' created successfully"
            }
            
        except Exception as e:
            logger.error(f"Failed to generate script tool: {e}")
            return {
                'success': False,
                'errors': [str(e)]
            }
    
    def delete_tool(self, tool_name: str) -> Dict[str, Any]:
        """
        Delete a script tool and all its files.
        
        Args:
            tool_name: Name of the tool to delete
            
        Returns:
            Dictionary with deletion results
        """
        deleted_files