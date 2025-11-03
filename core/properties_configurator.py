"""
Properties configurator for managing application properties with auto-reload
Enhanced with command-line args, precedence ordering, and source tracking
"""
import os
import re
import sys
import threading
import time
from typing import Optional, List, Union, Dict, Any
from pathlib import Path


class PropertiesConfigurator:
    """
    Singleton thread-safe class for managing properties from configuration files.
    Supports property value resolution with ${...} patterns and auto-reload.

    Order of precedence (highest to lowest):
    1. Command line arguments (--key=value)
    2. Environment variables
    3. Property files (rightmost file has highest precedence)
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, properties_files: Union[str, List[str]] = None, reload_interval: int = 300):
        """
        Initialize the PropertiesConfigurator

        Args:
            properties_files: List of property file paths OR comma-delimited string of file paths
            reload_interval: Interval in seconds for auto-reload (default: 300 seconds = 5 minutes)
        """
        if hasattr(self, '_initialized'):
            return

        self._initialized = True

        # Parse properties_files - handle both string and list
        self._properties_files = self._parse_file_paths(properties_files)

        self._reload_interval = reload_interval
        self._properties: Dict[str, str] = {}
        self._properties_lock = threading.RLock()
        self._stop_reload = threading.Event()
        self._file_timestamps: Dict[str, float] = {}

        # Track source of each property: "commandline", "env", or "file"
        self._property_sources: Dict[str, str] = {}

        # Parse command line arguments (--key=value format)
        self._commandline_args: Dict[str, str] = {}
        self._parse_commandline_args()

        # Initial load
        self._load_properties()

        # Start auto-reload thread
        self._reload_thread = threading.Thread(target=self._auto_reload_worker, daemon=True)
        self._reload_thread.start()

    def _parse_file_paths(self, properties_files: Union[str, List[str], None]) -> List[str]:
        """
        Parse properties files input - handle both string and list formats

        Args:
            properties_files: String (comma-delimited) or list of file paths

        Returns:
            List of file paths
        """
        if properties_files is None:
            return []

        if isinstance(properties_files, str):
            # Split by comma and strip whitespace
            return [path.strip() for path in properties_files.split(',') if path.strip()]

        if isinstance(properties_files, list):
            return [str(path).strip() for path in properties_files if path]

        return []

    def _parse_commandline_args(self):
        """
        Parse command line arguments in --key=value format
        Stores them in _commandline_args dictionary
        """
        for arg in sys.argv[1:]:
            if arg.startswith('--') and '=' in arg:
                # Remove leading '--'
                arg = arg[2:]

                # Split by first '=' only
                key, value = arg.split('=', 1)
                key = key.strip()
                value = value.strip()

                if key:
                    self._commandline_args[key] = value

    def _load_properties(self):
        """
        Load properties from all configured files
        Files are processed in order, with rightmost file having highest precedence
        """
        with self._properties_lock:
            new_properties = {}
            new_sources = {}

            # Process files in order (left to right)
            # Later files will overwrite earlier ones, giving rightmost highest precedence
            for file_path in self._properties_files:
                if not os.path.exists(file_path):
                    continue

                # Track file modification time
                self._file_timestamps[file_path] = os.path.getmtime(file_path)

                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line_num, line in enumerate(f, 1):
                            line = line.strip()

                            # Skip empty lines and comments
                            if not line or line.startswith('#') or line.startswith('//'):
                                continue

                            # Split by first '=' only
                            if '=' not in line:
                                continue

                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()

                            if key:
                                # Rightmost file overwrites previous values
                                new_properties[key] = value
                                new_sources[key] = 'file'

                except Exception as e:
                    print(f"Error loading properties from {file_path}: {e}")

            # Resolve all property references (only for file-based properties)
            resolved_properties = self._resolve_all_properties(new_properties)

            # Now apply precedence: file < env < commandline
            final_properties = {}
            final_sources = {}

            for key in resolved_properties:
                # Start with file value (lowest precedence)
                value = resolved_properties[key]
                source = 'file'

                # Check environment variables (higher precedence)
                env_value = os.environ.get(key)
                if env_value is not None:
                    value = env_value
                    source = 'env'

                # Check command line arguments (highest precedence)
                if key in self._commandline_args:
                    value = self._commandline_args[key]
                    source = 'commandline'

                final_properties[key] = value
                final_sources[key] = source

            # Also add command-line only keys (not in files)
            for key, value in self._commandline_args.items():
                if key not in final_properties:
                    final_properties[key] = value
                    final_sources[key] = 'commandline'

            # Also add env-only keys (not in files or commandline)
            # Optional: You can enable this if you want ALL env vars accessible
            # for key, value in os.environ.items():
            #     if key not in final_properties:
            #         final_properties[key] = value
            #         final_sources[key] = 'env'

            self._properties = final_properties
            self._property_sources = final_sources

    def _resolve_all_properties(self, properties: Dict[str, str]) -> Dict[str, str]:
        """Resolve all ${...} references in properties"""
        resolved = {}

        for key, value in properties.items():
            resolved[key] = self._resolve_value(value, properties, set())

        return resolved

    def _resolve_value(self, value: str, properties: Dict[str, str], visited: set) -> str:
        """
        Recursively resolve ${...} references in a value, including nested references

        Args:
            value: The value to resolve
            properties: Dictionary of all properties
            visited: Set of keys already visited (to prevent circular references)

        Returns:
            Resolved value
        """
        if not value or '${' not in value:
            return value

        max_iterations = 100  # Prevent infinite loops
        iteration = 0

        while '${' in value and iteration < max_iterations:
            iteration += 1

            # Find innermost ${...} pattern
            pattern = r'\$\{([^{}]+)\}'
            matches = list(re.finditer(pattern, value))

            if not matches:
                # Handle nested patterns like ${x${y}}
                nested_pattern = r'\$\{([^}]*\$\{[^}]*\}[^}]*)\}'
                nested_matches = list(re.finditer(nested_pattern, value))

                if nested_matches:
                    # Process innermost references first
                    for match in reversed(nested_matches):
                        inner_ref = match.group(1)
                        resolved_inner = self._resolve_value(inner_ref, properties, visited)
                        value = value[:match.start()] + '${' + resolved_inner + '}' + value[match.end():]
                    continue
                else:
                    break

            # Replace all simple ${key} references
            for match in reversed(matches):
                ref_key = match.group(1)

                # Check for circular reference
                if ref_key in visited:
                    replacement = match.group(0)  # Keep original if circular
                else:
                    # Check command line args first (highest precedence)
                    replacement = self._commandline_args.get(ref_key)

                    # Then check environment variables
                    if replacement is None:
                        replacement = os.environ.get(ref_key)

                    # Finally check properties
                    if replacement is None:
                        replacement = properties.get(ref_key, match.group(0))

                        # Recursively resolve the replacement
                        if replacement != match.group(0):
                            new_visited = visited.copy()
                            new_visited.add(ref_key)
                            replacement = self._resolve_value(replacement, properties, new_visited)

                value = value[:match.start()] + replacement + value[match.end():]

        return value

    def _auto_reload_worker(self):
        """Worker thread for auto-reloading properties"""
        while not self._stop_reload.wait(self._reload_interval):
            try:
                # Check if any files have been modified
                needs_reload = False

                for file_path in self._properties_files:
                    if os.path.exists(file_path):
                        current_mtime = os.path.getmtime(file_path)
                        if file_path not in self._file_timestamps or \
                                self._file_timestamps[file_path] < current_mtime:
                            needs_reload = True
                            break

                if needs_reload:
                    self._load_properties()

            except Exception as e:
                print(f"Error in auto-reload: {e}")

    def get(self, key: str, default_value: Optional[str] = None) -> Optional[str]:
        """
        Get a property value by key

        Precedence order (highest to lowest):
        1. Command line arguments (--key=value)
        2. Environment variables
        3. Property files (rightmost file has highest precedence)

        Args:
            key: Property key
            default_value: Default value if key not found

        Returns:
            Property value or default_value
        """
        with self._properties_lock:
            return self._properties.get(key, default_value)

    def get_source(self, key: str) -> Optional[str]:
        """
        Get the source of a property value

        Args:
            key: Property key

        Returns:
            Source of the property value: "commandline", "env", "file", or None if not found
        """
        with self._properties_lock:
            return self._property_sources.get(key)

    def get_system_name(self) -> Optional[str]:
        """
        Get the system/application name from 'app.name' property

        Returns:
            Value of 'app.name' property or None if not found
        """
        return self.get('app.name')

    def get_int(self, key: str, default_value: Optional[int] = None) -> Optional[int]:
        """
        Get a property value as integer

        Args:
            key: Property key
            default_value: Default value if key not found

        Returns:
            Property value as int or default_value
        """
        value = self.get(key)
        if value is None:
            return default_value

        try:
            return int(value)
        except (ValueError, TypeError):
            return default_value

    def get_float(self, key: str, default_value: Optional[float] = None) -> Optional[float]:
        """
        Get a property value as float

        Args:
            key: Property key
            default_value: Default value if key not found

        Returns:
            Property value as float or default_value
        """
        value = self.get(key)
        if value is None:
            return default_value

        try:
            return float(value)
        except (ValueError, TypeError):
            return default_value

    def get_bool(self, key: str, default_value: Optional[bool] = None) -> Optional[bool]:
        """
        Get a property value as boolean

        Recognizes the following as True (case-insensitive):
        - true, yes, on, 1, y, t

        Recognizes the following as False (case-insensitive):
        - false, no, off, 0, n, f

        Args:
            key: Property key
            default_value: Default value if key not found or cannot be converted

        Returns:
            Property value as bool or default_value
        """
        value = self.get(key)
        if value is None:
            return default_value

        # Handle boolean values
        if isinstance(value, bool):
            return value

        # Handle string values (case-insensitive)
        if isinstance(value, str):
            value_lower = value.lower().strip()

            # True values
            if value_lower in ('true', 'yes', 'on', '1', 'y', 't'):
                return True

            # False values
            if value_lower in ('false', 'no', 'off', '0', 'n', 'f'):
                return False

        # If value is numeric, use Python's bool conversion
        try:
            num_value = float(value)
            return bool(num_value)
        except (ValueError, TypeError):
            pass

        # Cannot convert, return default
        return default_value

    def get_list(self, key: str, delim: str = ',') -> Optional[List[str]]:
        """
        Get a property value as list by splitting with delimiter

        Args:
            key: Property key
            delim: Delimiter for splitting (default: ',')

        Returns:
            List of strings or None
        """
        value = self.get(key)
        if value is None:
            return None

        return [item.strip() for item in value.split(delim) if item.strip()]

    def get_int_list(self, key: str, delim: str = ',') -> Optional[List[int]]:
        """
        Get a property value as list of integers

        Args:
            key: Property key
            delim: Delimiter for splitting (default: ',')

        Returns:
            List of integers or None
        """
        str_list = self.get_list(key, delim)
        if str_list is None:
            return None

        result = []
        for item in str_list:
            try:
                result.append(int(item))
            except (ValueError, TypeError):
                continue  # Skip invalid integers

        return result if result else None

    def get_float_list(self, key: str, delim: str = ',') -> Optional[List[float]]:
        """
        Get a property value as list of floats

        Args:
            key: Property key
            delim: Delimiter for splitting (default: ',')

        Returns:
            List of floats or None
        """
        str_list = self.get_list(key, delim)
        if str_list is None:
            return None

        result = []
        for item in str_list:
            try:
                result.append(float(item))
            except (ValueError, TypeError):
                continue  # Skip invalid floats

        return result if result else None

    def get_values_by_pattern(self, pattern: str) -> List[str]:
        """
        Get all property values whose keys match the given regex pattern

        Args:
            pattern: Regex pattern to match against property keys

        Returns:
            List of property values for matching keys (empty list if no matches)
        """
        with self._properties_lock:
            try:
                regex = re.compile(pattern)
                matching_values = []

                for key, value in self._properties.items():
                    if regex.match(key):
                        matching_values.append(value)

                return matching_values
            except re.error as e:
                print(f"Invalid regex pattern '{pattern}': {e}")
                return []

    def get_properties_by_pattern(self, pattern: str) -> Dict[str, str]:
        """
        Get all properties (key-value pairs) whose keys match the given regex pattern

        Args:
            pattern: Regex pattern to match against property keys

        Returns:
            Dictionary of matching properties (empty dict if no matches)
        """
        with self._properties_lock:
            try:
                regex = re.compile(pattern)
                matching_properties = {}

                for key, value in self._properties.items():
                    if regex.match(key):
                        matching_properties[key] = value

                return matching_properties
            except re.error as e:
                print(f"Invalid regex pattern '{pattern}': {e}")
                return {}

    def get_all_properties(self) -> Dict[str, str]:
        """
        Get all properties

        Returns:
            Dictionary of all properties
        """
        with self._properties_lock:
            return self._properties.copy()

    def get_all_sources(self) -> Dict[str, str]:
        """
        Get sources for all properties

        Returns:
            Dictionary mapping property keys to their sources
        """
        with self._properties_lock:
            return self._property_sources.copy()

    def stop_reload(self):
        """Stop the auto-reload thread"""
        self._stop_reload.set()
        if hasattr(self, '_reload_thread'):
            self._reload_thread.join(timeout=5)