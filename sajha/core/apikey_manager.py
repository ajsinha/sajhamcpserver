"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
API Key Manager for SAJHA MCP Server v2.2.0
Handles creation, validation, and management of API keys
"""

import os
import json
import re
import secrets
import string
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Default path relative to project root
DEFAULT_APIKEYS_PATH = 'config/apikeys.json'


class APIKeyManager:
    """
    Manages API keys for SAJHA MCP Server.
    Supports tool-level access control with allowlist, denylist, and regex patterns.
    """
    
    KEY_PREFIX = "sja_"
    KEY_LENGTH = 32
    
    def __init__(self, config_path: str = None):
        """
        Initialize the API Key Manager.
        
        Args:
            config_path: Path to apikeys.json file (relative to project root or absolute)
        """
        if config_path is None:
            config_path = DEFAULT_APIKEYS_PATH
        
        # Handle relative paths - make relative to project root (cwd)
        self.config_path = Path(config_path)
        if not self.config_path.is_absolute():
            # Relative paths are relative to current working directory (project root)
            self.config_path = Path.cwd() / self.config_path
        
        self._lock = threading.RLock()
        self._apikeys: Dict[str, Dict] = {}
        self._settings: Dict = {}
        
        logger.info(f"APIKeyManager initializing with config: {self.config_path}")
        
        # Load existing keys
        self._load_keys()
    
    def _load_keys(self):
        """Load API keys from JSON file"""
        with self._lock:
            logger.info(f"Loading API keys from: {self.config_path}")
            logger.info(f"  File exists: {self.config_path.exists()}")
            
            if not self.config_path.exists():
                logger.warning(f"API keys config not found at {self.config_path}, creating default")
                # Create default config
                self._create_default_config()
                return
            
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self._settings = data.get('settings', {})
                
                # Index by key for fast lookup
                self._apikeys = {}
                for key_data in data.get('apikeys', []):
                    key = key_data.get('key')
                    if key:
                        self._apikeys[key] = key_data
                
                logger.info(f"Loaded {len(self._apikeys)} API keys from {self.config_path}")
                
            except Exception as e:
                logger.error(f"Error loading API keys from {self.config_path}: {e}")
                self._apikeys = {}
                self._settings = {}
    
    def _create_default_config(self):
        """Create default apikeys.json file"""
        default_config = {
            "apikeys": [],
            "settings": {
                "key_prefix": self.KEY_PREFIX,
                "key_length": self.KEY_LENGTH,
                "default_rate_limit": {
                    "requests_per_minute": 60,
                    "requests_per_hour": 1000
                },
                "max_keys_per_user": 10
            }
        }
        
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2)
            
            self._settings = default_config['settings']
            logger.info(f"Created default API keys config at {self.config_path}")
            
        except Exception as e:
            logger.error(f"Error creating default config: {e}")
    
    def _save_keys(self):
        """Save API keys to JSON file"""
        with self._lock:
            try:
                data = {
                    "apikeys": list(self._apikeys.values()),
                    "settings": self._settings
                }
                
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                
                logger.info(f"Saved {len(self._apikeys)} API keys")
                return True
                
            except Exception as e:
                logger.error(f"Error saving API keys: {e}")
                return False
    
    def generate_key(self) -> str:
        """Generate a new unique API key"""
        prefix = self._settings.get('key_prefix', self.KEY_PREFIX)
        length = self._settings.get('key_length', self.KEY_LENGTH)
        
        # Generate random alphanumeric string
        chars = string.ascii_letters + string.digits
        random_part = ''.join(secrets.choice(chars) for _ in range(length))
        
        return f"{prefix}{random_part}"
    
    def create_key(self, 
                   name: str,
                   description: str = "",
                   created_by: str = "admin",
                   tool_access_mode: str = "all",
                   tools: List[str] = None,
                   regex_patterns: List[str] = None,
                   expires_at: str = None,
                   rate_limit_rpm: int = None,
                   rate_limit_rph: int = None,
                   metadata: Dict = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Create a new API key.
        
        Args:
            name: Human-readable name for the key
            description: Description of the key's purpose
            created_by: Username of creator
            tool_access_mode: 'all', 'allowlist', 'denylist', or 'regex'
            tools: List of tool names for allowlist/denylist
            regex_patterns: List of regex patterns for tool matching
            expires_at: Expiration datetime (ISO format) or None for no expiry
            rate_limit_rpm: Requests per minute limit
            rate_limit_rph: Requests per hour limit
            metadata: Additional metadata dict
            
        Returns:
            Tuple of (success, message, key_data)
        """
        with self._lock:
            # Generate unique key
            attempts = 0
            while attempts < 10:
                key = self.generate_key()
                if key not in self._apikeys:
                    break
                attempts += 1
            else:
                return False, "Failed to generate unique key", None
            
            # Validate regex patterns
            if regex_patterns:
                for pattern in regex_patterns:
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        return False, f"Invalid regex pattern '{pattern}': {e}", None
            
            # Get default rate limits
            default_rpm = self._settings.get('default_rate_limit', {}).get('requests_per_minute', 60)
            default_rph = self._settings.get('default_rate_limit', {}).get('requests_per_hour', 1000)
            
            # Create key data
            now = datetime.now(timezone.utc).isoformat()
            key_data = {
                "key": key,
                "name": name,
                "description": description,
                "created_by": created_by,
                "created_at": now,
                "expires_at": expires_at,
                "enabled": True,
                "tool_access": {
                    "mode": tool_access_mode,
                    "tools": tools or [],
                    "regex_patterns": regex_patterns or []
                },
                "rate_limit": {
                    "requests_per_minute": rate_limit_rpm or default_rpm,
                    "requests_per_hour": rate_limit_rph or default_rph
                },
                "metadata": metadata or {},
                "usage_stats": {
                    "total_requests": 0,
                    "last_used": None
                }
            }
            
            self._apikeys[key] = key_data
            
            if self._save_keys():
                logger.info(f"Created API key '{name}' by {created_by}")
                return True, "API key created successfully", key_data
            else:
                del self._apikeys[key]
                return False, "Failed to save API key", None
    
    def validate_key(self, key: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Validate an API key.
        
        Args:
            key: The API key to validate
            
        Returns:
            Tuple of (is_valid, key_data, message)
        """
        if not key:
            return False, None, "No API key provided"
        
        # Check prefix
        prefix = self._settings.get('key_prefix', self.KEY_PREFIX)
        if not key.startswith(prefix):
            return False, None, "Invalid API key format"
        
        with self._lock:
            key_data = self._apikeys.get(key)
            
            if not key_data:
                return False, None, "API key not found"
            
            if not key_data.get('enabled', False):
                return False, None, "API key is disabled"
            
            # Check expiration
            expires_at = key_data.get('expires_at')
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                    if datetime.now(timezone.utc) > exp_dt:
                        return False, None, "API key has expired"
                except:
                    pass
            
            return True, key_data, "Valid"
    
    def check_tool_access(self, key: str, tool_name: str) -> Tuple[bool, str]:
        """
        Check if an API key has access to a specific tool.
        
        Args:
            key: The API key
            tool_name: Name of the tool to check
            
        Returns:
            Tuple of (has_access, message)
        """
        is_valid, key_data, msg = self.validate_key(key)
        if not is_valid:
            return False, msg
        
        tool_access = key_data.get('tool_access', {})
        mode = tool_access.get('mode', 'all')
        tools = tool_access.get('tools', [])
        patterns = tool_access.get('regex_patterns', [])
        
        if mode == 'all':
            return True, "Full access"
        
        elif mode == 'allowlist':
            if tool_name in tools:
                return True, "Tool in allowlist"
            return False, f"Tool '{tool_name}' not in allowlist"
        
        elif mode == 'denylist':
            if tool_name in tools:
                return False, f"Tool '{tool_name}' is denied"
            return True, "Tool not in denylist"
        
        elif mode == 'regex':
            for pattern in patterns:
                try:
                    if re.match(pattern, tool_name):
                        return True, f"Tool matches pattern '{pattern}'"
                except re.error:
                    continue
            return False, f"Tool '{tool_name}' doesn't match any pattern"
        
        return False, f"Unknown access mode: {mode}"
    
    def record_usage(self, key: str):
        """Record usage of an API key"""
        with self._lock:
            if key in self._apikeys:
                self._apikeys[key]['usage_stats']['total_requests'] += 1
                self._apikeys[key]['usage_stats']['last_used'] = datetime.now(timezone.utc).isoformat()
                # Save periodically (every 100 requests)
                if self._apikeys[key]['usage_stats']['total_requests'] % 100 == 0:
                    self._save_keys()
    
    def update_key(self, key: str, updates: Dict) -> Tuple[bool, str]:
        """
        Update an existing API key.
        
        Args:
            key: The API key to update
            updates: Dictionary of fields to update
            
        Returns:
            Tuple of (success, message)
        """
        with self._lock:
            if key not in self._apikeys:
                return False, "API key not found"
            
            # Fields that can be updated
            allowed_fields = ['name', 'description', 'enabled', 'expires_at', 
                            'tool_access', 'rate_limit', 'metadata']
            
            for field, value in updates.items():
                if field in allowed_fields:
                    if field == 'tool_access' and isinstance(value, dict):
                        # Validate regex patterns
                        patterns = value.get('regex_patterns', [])
                        for pattern in patterns:
                            try:
                                re.compile(pattern)
                            except re.error as e:
                                return False, f"Invalid regex pattern '{pattern}': {e}"
                    
                    self._apikeys[key][field] = value
            
            self._apikeys[key]['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            if self._save_keys():
                return True, "API key updated successfully"
            else:
                return False, "Failed to save changes"
    
    def delete_key(self, key: str) -> Tuple[bool, str]:
        """
        Delete an API key.
        
        Args:
            key: The API key to delete
            
        Returns:
            Tuple of (success, message)
        """
        with self._lock:
            if key not in self._apikeys:
                return False, "API key not found"
            
            key_name = self._apikeys[key].get('name', key)
            del self._apikeys[key]
            
            if self._save_keys():
                logger.info(f"Deleted API key '{key_name}'")
                return True, "API key deleted successfully"
            else:
                return False, "Failed to save changes"
    
    def enable_key(self, key: str) -> Tuple[bool, str]:
        """Enable an API key"""
        return self.update_key(key, {'enabled': True})
    
    def disable_key(self, key: str) -> Tuple[bool, str]:
        """Disable an API key"""
        return self.update_key(key, {'enabled': False})
    
    def list_keys(self, include_key: bool = False) -> List[Dict]:
        """
        List all API keys.
        
        Args:
            include_key: If True, include the actual key value
            
        Returns:
            List of key data dictionaries
        """
        with self._lock:
            keys = []
            for key_data in self._apikeys.values():
                data = dict(key_data)
                if not include_key:
                    # Mask the key
                    key = data.get('key', '')
                    if len(key) > 12:
                        data['key'] = key[:8] + '...' + key[-4:]
                keys.append(data)
            return keys
    
    def get_key(self, key: str, include_full_key: bool = False) -> Optional[Dict]:
        """
        Get a specific API key's data.
        
        Args:
            key: The API key
            include_full_key: If True, include the full key value
            
        Returns:
            Key data dictionary or None
        """
        with self._lock:
            key_data = self._apikeys.get(key)
            if key_data:
                data = dict(key_data)
                if not include_full_key:
                    k = data.get('key', '')
                    if len(k) > 12:
                        data['key'] = k[:8] + '...' + k[-4:]
                return data
            return None
    
    def get_key_by_partial(self, partial_key: str) -> Optional[str]:
        """
        Find a key by partial match (for admin lookup).
        Handles masked key format like 'sja_demo...2345'.
        
        Args:
            partial_key: Partial key string (can be masked with ...)
            
        Returns:
            Full key if found, None otherwise
        """
        with self._lock:
            # Handle masked key format (e.g., sja_demo...2345)
            if '...' in partial_key:
                parts = partial_key.split('...')
                if len(parts) == 2:
                    prefix = parts[0]  # e.g., 'sja_demo'
                    suffix = parts[1]  # e.g., '2345'
                    
                    for key in self._apikeys.keys():
                        if key.startswith(prefix) and key.endswith(suffix):
                            return key
                    return None
            
            # Handle regular partial key lookup (substring match)
            for key in self._apikeys.keys():
                if partial_key in key:
                    return key
            
            # Also try matching by name
            for key, data in self._apikeys.items():
                if data.get('name', '').lower() == partial_key.lower():
                    return key
            
            return None
    
    def get_statistics(self) -> Dict:
        """Get overall API key statistics"""
        with self._lock:
            total = len(self._apikeys)
            enabled = sum(1 for k in self._apikeys.values() if k.get('enabled', False))
            expired = 0
            now = datetime.now(timezone.utc)
            
            for k in self._apikeys.values():
                exp = k.get('expires_at')
                if exp:
                    try:
                        exp_dt = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                        if now > exp_dt:
                            expired += 1
                    except:
                        pass
            
            total_requests = sum(k.get('usage_stats', {}).get('total_requests', 0) 
                               for k in self._apikeys.values())
            
            return {
                'total_keys': total,
                'enabled_keys': enabled,
                'disabled_keys': total - enabled,
                'expired_keys': expired,
                'total_requests': total_requests
            }
    
    def reload(self):
        """Reload keys from file"""
        self._load_keys()


# Singleton instance
_api_key_manager: Optional[APIKeyManager] = None
_api_key_manager_lock = threading.Lock()


def get_api_key_manager(config_path: str = None, force_reinit: bool = False) -> APIKeyManager:
    """
    Get the singleton APIKeyManager instance.
    
    Args:
        config_path: Path to apikeys.json (used on first call or when force_reinit=True)
        force_reinit: If True, reinitialize with new config_path
        
    Returns:
        APIKeyManager instance
    """
    global _api_key_manager
    
    with _api_key_manager_lock:
        if _api_key_manager is None or force_reinit:
            if force_reinit and _api_key_manager is not None:
                logger.info(f"Reinitializing APIKeyManager with path: {config_path}")
            _api_key_manager = APIKeyManager(config_path)
        return _api_key_manager


def reset_api_key_manager():
    """Reset the singleton instance (useful for testing or reconfiguration)."""
    global _api_key_manager
    with _api_key_manager_lock:
        _api_key_manager = None
        logger.info("APIKeyManager singleton reset")
