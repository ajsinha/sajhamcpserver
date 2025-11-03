"""
Properties Configurator for Abhikarta System
Manages application configuration from properties files with precedence support

© 2025-2030 All rights reserved Ashutosh Sinha
email: ajsinha@gmail.com
https://www.github.com/ajsinha/abhikarta
"""

import os
import sys
from typing import Any, Dict, Optional, List


class PropertiesConfigurator:
    """
    Singleton class to manage application properties with precedence rules.

    Precedence Order (highest to lowest):
    1. Command-line arguments (--key=value)
    2. Environment variables
    3. Properties files (right to left when multiple files provided)

    Example:
        If files are provided as "a.txt,b.txt,c.txt", then:
        c.txt overrides b.txt, which overrides a.txt
    """

    _instance = None
    _properties: Dict[str, str] = {}
    _cli_properties: Dict[str, str] = {}
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PropertiesConfigurator, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize and parse command-line arguments if not already done"""
        if not self._initialized:
            self._parse_cli_arguments()
            self._initialized = True

    def _parse_cli_arguments(self) -> None:
        """
        Parse command-line arguments in the format --key=value

        Examples:
            --api.key=sk-123456
            --app.name=MyApp
        """
        for arg in sys.argv[1:]:
            if arg.startswith('--') and '=' in arg:
                # Remove the leading '--'
                arg = arg[2:]
                key, value = arg.split('=', 1)
                self._cli_properties[key.strip()] = value.strip()

    def load_properties(self, filepath: str) -> None:
        """
        Load properties from one or more files.

        Args:
            filepath: Single file path or comma-separated list of file paths
                     Files are processed left to right, with rightmost having highest precedence

        Raises:
            FileNotFoundError: If any specified file does not exist

        Examples:
            load_properties("llmconfig.properties")
            load_properties("base.properties,override.properties")
        """
        # Split by comma and process each file
        filepaths = [fp.strip() for fp in filepath.split(',')]

        # Validate all files exist before loading any
        for fp in filepaths:
            if not os.path.exists(fp):
                raise FileNotFoundError(f"Properties file not found: {fp}")

        # Load files from left to right (rightmost will override leftmost)
        for fp in filepaths:
            self._load_single_file(fp)

    def _load_single_file(self, filepath: str) -> None:
        """
        Load properties from a single file.

        Args:
            filepath: Path to the properties file
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Parse key=value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()

                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]

                    self._properties[key] = value

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a property value following precedence rules.

        Precedence: CLI args > Environment vars > Properties files

        Args:
            key: Property key to retrieve
            default: Default value if key not found

        Returns:
            Property value or default if not found
        """
        # 1. Check command-line arguments (highest precedence)
        if key in self._cli_properties:
            return self._cli_properties[key]

        # 2. Check environment variables
        env_value = os.environ.get(key)
        if env_value is not None:
            return env_value

        # 3. Check properties files (lowest precedence)
        return self._properties.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        """
        Get a property as integer.

        Args:
            key: Property key to retrieve
            default: Default value if key not found or conversion fails

        Returns:
            Property value as integer or default
        """
        value = self.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """
        Get a property as boolean.

        Accepts: true, yes, 1, on (case-insensitive) as True

        Args:
            key: Property key to retrieve
            default: Default value if key not found

        Returns:
            Property value as boolean or default
        """
        value = self.get(key)
        if value is None:
            return default
        return value.lower() in ('true', 'yes', '1', 'on')

    def get_float(self, key: str, default: float = 0.0) -> float:
        """
        Get a property as float.

        Args:
            key: Property key to retrieve
            default: Default value if key not found or conversion fails

        Returns:
            Property value as float or default
        """
        value = self.get(key)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            return default

    def get_list(self, key: str, separator: str = ',', default: Optional[List[str]] = None) -> List[str]:
        """
        Get a property as list of strings.

        Args:
            key: Property key to retrieve
            separator: Separator character (default: comma)
            default: Default value if key not found

        Returns:
            Property value as list of strings or default
        """
        value = self.get(key)
        if value is None:
            return default or []
        return [item.strip() for item in value.split(separator) if item.strip()]

    def set(self, key: str, value: str) -> None:
        """
        Set a property value in the properties dictionary.

        Note: This does not override CLI or environment values

        Args:
            key: Property key
            value: Property value
        """
        self._properties[key] = value

    def get_all(self) -> Dict[str, str]:
        """
        Get all properties with precedence applied.

        Returns:
            Dictionary of all properties with resolved precedence
        """
        # Start with file properties
        result = self._properties.copy()

        # Override with environment variables
        for key in result.keys():
            env_value = os.environ.get(key)
            if env_value is not None:
                result[key] = env_value

        # Override with CLI arguments
        result.update(self._cli_properties)

        return result

    def get_system_name(self) -> str:
        """
        Get the system/application name.

        Returns:
            Application name from llmconfig or 'Abhikarta' as default
        """
        return self.get('app.name', 'Abhikarta')

    def has_property(self, key: str) -> bool:
        """
        Check if a property exists.

        Args:
            key: Property key to check

        Returns:
            True if property exists, False otherwise
        """
        return self.get(key) is not None

    def clear(self) -> None:
        """
        Clear all properties (useful for testing).
        Does not clear CLI arguments.
        """
        self._properties.clear()

    def get_source(self, key: str) -> Optional[str]:
        """
        Get the source of a property value for debugging.

        Args:
            key: Property key

        Returns:
            Source string: 'cli', 'env', 'file', or None if not found
        """
        if key in self._cli_properties:
            return 'cli'
        if os.environ.get(key) is not None:
            return 'env'
        if key in self._properties:
            return 'file'
        return None