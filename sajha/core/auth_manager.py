"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Authentication and Authorization Manager v2.2.0
"""

import json
import secrets
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import threading

from .apikey_manager import get_api_key_manager, reset_api_key_manager

# Default path relative to project root
DEFAULT_USERS_PATH = 'config/users.json'
DEFAULT_APIKEYS_PATH = 'config/apikeys.json'


class AuthManager:
    """
    Manages authentication and authorization for the MCP server
    Supports both session-based authentication and API key authentication
    """
    
    # Username field aliases accepted in API requests
    USERNAME_ALIASES = ['uid', 'username', 'user_name', 'user_id', 'userid']
    
    def __init__(self, users_config_path: str = None, apikeys_config_path: str = None):
        """
        Initialize the AuthManager
        
        Args:
            users_config_path: Path to users configuration file (relative to project root or absolute)
            apikeys_config_path: Path to API keys configuration file (relative to project root or absolute)
        """
        self.logger = logging.getLogger(__name__)
        
        # Handle users config path
        if users_config_path is None:
            users_config_path = DEFAULT_USERS_PATH
        
        self.users_config_path = Path(users_config_path)
        if not self.users_config_path.is_absolute():
            self.users_config_path = Path.cwd() / self.users_config_path
        
        # Handle apikeys config path
        if apikeys_config_path is None:
            apikeys_config_path = DEFAULT_APIKEYS_PATH
        
        apikeys_path = Path(apikeys_config_path)
        if not apikeys_path.is_absolute():
            apikeys_path = Path.cwd() / apikeys_path
        
        self.users: Dict[str, Dict] = {}
        self.sessions: Dict[str, Dict] = {}
        self.failed_attempts: Dict[str, List[datetime]] = {}
        self._lock = threading.RLock()
        
        self.logger.info(f"AuthManager initializing:")
        self.logger.info(f"  Users config: {self.users_config_path} (exists: {self.users_config_path.exists()})")
        self.logger.info(f"  APIKeys config: {apikeys_path} (exists: {apikeys_path.exists()})")
        
        # Initialize API Key Manager with explicit path (force reinit to ensure correct path)
        self.apikey_manager = get_api_key_manager(str(apikeys_path), force_reinit=True)
        
        # Load users configuration
        self.load_users()
        
        # Session configuration
        self.session_timeout_minutes = 60
        self.max_login_attempts = 5
        self.lockout_duration_minutes = 5
    
    def load_users(self):
        """Load users from configuration file"""
        try:
            if self.users_config_path.exists():
                with open(self.users_config_path, 'r') as f:
                    config = json.load(f)
                    self.users = {user['user_id']: user for user in config.get('users', [])}
                    self.logger.info(f"Loaded {len(self.users)} users from {self.users_config_path}")
            else:
                # Create default admin user if no config exists
                self.logger.warning(f"Users config not found at {self.users_config_path}, creating default")
                default_config = {
                    "users": [
                        {
                            "user_id": "admin",
                            "user_name": "Administrator",
                            "password": "admin123",
                            "roles": ["admin"],
                            "tools": ["*"],
                            "enabled": True,
                            "email": "admin@example.com",
                            "created_at": datetime.now().isoformat() + "Z"
                        }
                    ]
                }
                self.users_config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.users_config_path, 'w') as f:
                    json.dump(default_config, f, indent=2)
                self.users = {user['user_id']: user for user in default_config['users']}
                self.logger.info("Created default admin user configuration")
        except Exception as e:
            self.logger.error(f"Error loading users configuration: {e}")
            self.users = {}
    
    def authenticate(self, user_id: str, password: str) -> Optional[str]:
        """
        Authenticate a user and create a session
        
        Args:
            user_id: User identifier
            password: User password
            
        Returns:
            Session token if successful, None otherwise
        """
        with self._lock:
            # Check if user is locked out
            if self.is_user_locked_out(user_id):
                self.logger.warning(f"Login attempt for locked out user: {user_id}")
                return None
            
            # Check if user exists and is enabled
            user = self.users.get(user_id)
            if not user or not user.get('enabled', True):
                self.record_failed_attempt(user_id)
                self.logger.warning(f"Login attempt for invalid/disabled user: {user_id}")
                return None
            
            # Verify password
            if user.get('password') != password:
                self.record_failed_attempt(user_id)
                self.logger.warning(f"Invalid password for user: {user_id}")
                return None
            
            # Create session
            session_token = secrets.token_urlsafe(32)
            session_data = {
                'user_id': user_id,
                'user_name': user.get('user_name', user_id),
                'roles': user.get('roles', []),
                'tools': user.get('tools', []),
                'created_at': datetime.now(),
                'last_activity': datetime.now()
            }
            
            self.sessions[session_token] = session_data
            
            # Update last login
            self.update_last_login(user_id)

            # Clear failed attempts
            if user_id in self.failed_attempts:
                del self.failed_attempts[user_id]

            self.logger.info(f"User authenticated successfully: {user_id}")
            return session_token

    def validate_session(self, token: str) -> Optional[Dict]:
        """
        Validate a session token

        Args:
            token: Session token

        Returns:
            Session data if valid, None otherwise
        """
        with self._lock:
            session = self.sessions.get(token)
            if not session:
                return None

            # Check session timeout
            timeout = timedelta(minutes=self.session_timeout_minutes)
            if datetime.now() - session['last_activity'] > timeout:
                del self.sessions[token]
                self.logger.info(f"Session expired for user: {session['user_id']}")
                return None

            # Update last activity
            session['last_activity'] = datetime.now()
            return session

    def logout(self, token: str) -> bool:
        """
        Logout a user by invalidating their session

        Args:
            token: Session token

        Returns:
            True if successful
        """
        with self._lock:
            if token in self.sessions:
                user_id = self.sessions[token]['user_id']
                del self.sessions[token]
                self.logger.info(f"User logged out: {user_id}")
                return True
            return False

    def has_tool_access(self, session: Dict, tool_name: str) -> bool:
        """
        Check if a session has access to a specific tool

        Args:
            session: Session data
            tool_name: Name of the tool

        Returns:
            True if user has access to the tool
        """
        tools = session.get('tools', [])
        if '*' in tools or tool_name in tools:
            return True

        # Check if user has admin role
        if 'admin' in session.get('roles', []):
            return True

        return False

    def is_admin(self, session: Dict) -> bool:
        """
        Check if a session has admin privileges

        Args:
            session: Session data

        Returns:
            True if user is admin
        """
        return 'admin' in session.get('roles', [])

    def get_user_accessible_tools(self, session: Dict) -> List[str]:
        """
        Get list of tools accessible to a user

        Args:
            session: Session data

        Returns:
            List of accessible tool names
        """
        tools = session.get('tools', [])
        if '*' in tools or self.is_admin(session):
            return ['*']  # All tools
        return tools

    def record_failed_attempt(self, user_id: str):
        """Record a failed login attempt"""
        with self._lock:
            if user_id not in self.failed_attempts:
                self.failed_attempts[user_id] = []

            self.failed_attempts[user_id].append(datetime.now())

            # Clean up old attempts
            cutoff = datetime.now() - timedelta(minutes=self.lockout_duration_minutes)
            self.failed_attempts[user_id] = [
                attempt for attempt in self.failed_attempts[user_id]
                if attempt > cutoff
            ]

    def is_user_locked_out(self, user_id: str) -> bool:
        """Check if a user is locked out due to too many failed attempts"""
        with self._lock:
            if user_id not in self.failed_attempts:
                return False

            # Clean up old attempts
            cutoff = datetime.now() - timedelta(minutes=self.lockout_duration_minutes)
            recent_attempts = [
                attempt for attempt in self.failed_attempts[user_id]
                if attempt > cutoff
            ]

            return len(recent_attempts) >= self.max_login_attempts

    def save_users(self):
        """Save users configuration to file"""
        try:
            config = {"users": list(self.users.values())}
            config_path = Path(self.users_config_path)
            config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)

            self.logger.info(f"Saved {len(self.users)} users to configuration")
        except Exception as e:
            self.logger.error(f"Error saving users configuration: {e}")

    # =========================================================================
    # User Management Methods (for Admin UI)
    # =========================================================================

    def get_user(self, user_id: str) -> Optional[Dict]:
        """
        Get user by ID

        Args:
            user_id: User identifier

        Returns:
            User data dictionary or None
        """
        with self._lock:
            return self.users.get(user_id)

    def get_all_users(self) -> List[Dict]:
        """
        Get all users (includes passwords for admin editing)

        Returns:
            List of user dictionaries
        """
        with self._lock:
            return list(self.users.values())

    def create_user(self, user_data: Dict) -> bool:
        """
        Create a new user

        Args:
            user_data: User configuration dictionary

        Returns:
            True if successful
        """
        with self._lock:
            try:
                user_id = user_data.get('user_id')

                if not user_id:
                    self.logger.error("Cannot create user: user_id is required")
                    return False

                if user_id in self.users:
                    self.logger.error(f"Cannot create user: {user_id} already exists")
                    return False

                # Set creation timestamp if not provided
                if 'created_at' not in user_data:
                    user_data['created_at'] = datetime.now().isoformat() + 'Z'

                # Set defaults
                user_data.setdefault('enabled', True)
                user_data.setdefault('roles', ['user'])
                user_data.setdefault('tools', ['*'])

                # Add user to memory
                self.users[user_id] = user_data

                # Save to file
                self.save_users()

                self.logger.info(f"User created: {user_id}")
                return True

            except Exception as e:
                self.logger.error(f"Error creating user: {e}")
                return False

    def update_user(self, user_id: str, user_data: Dict) -> bool:
        """
        Update existing user

        Args:
            user_id: User identifier
            user_data: Updated user configuration

        Returns:
            True if successful
        """
        with self._lock:
            try:
                if user_id not in self.users:
                    self.logger.error(f"User {user_id} not found")
                    return False

                # Keep original created_at if not provided
                if 'created_at' not in user_data and 'created_at' in self.users[user_id]:
                    user_data['created_at'] = self.users[user_id]['created_at']

                # If password is empty or None, keep the old password
                if not user_data.get('password'):
                    user_data['password'] = self.users[user_id].get('password', '')

                # Update user in memory (replace entire user object)
                self.users[user_id] = user_data

                # Save to file
                self.save_users()

                self.logger.info(f"User updated: {user_id}")
                return True

            except Exception as e:
                self.logger.error(f"Error updating user: {e}")
                return False

    def delete_user(self, user_id: str) -> bool:
        """
        Delete a user

        Args:
            user_id: User identifier

        Returns:
            True if successful
        """
        with self._lock:
            try:
                # Prevent deleting admin
                if user_id == 'admin':
                    self.logger.error("Cannot delete admin user")
                    return False

                if user_id not in self.users:
                    self.logger.error(f"User {user_id} not found")
                    return False

                # Remove from memory
                del self.users[user_id]

                # Save to file
                self.save_users()

                # Invalidate all sessions for this user
                tokens_to_remove = [
                    token for token, session in self.sessions.items()
                    if session['user_id'] == user_id
                ]
                for token in tokens_to_remove:
                    del self.sessions[token]

                self.logger.info(f"User deleted: {user_id}")
                return True

            except Exception as e:
                self.logger.error(f"Error deleting user: {e}")
                return False

    def enable_user(self, user_id: str) -> bool:
        """
        Enable a user account

        Args:
            user_id: User identifier

        Returns:
            True if successful
        """
        with self._lock:
            try:
                if user_id not in self.users:
                    self.logger.error(f"User {user_id} not found")
                    return False

                self.users[user_id]['enabled'] = True
                self.save_users()

                self.logger.info(f"User enabled: {user_id}")
                return True

            except Exception as e:
                self.logger.error(f"Error enabling user: {e}")
                return False

    def disable_user(self, user_id: str) -> bool:
        """
        Disable a user account

        Args:
            user_id: User identifier

        Returns:
            True if successful
        """
        with self._lock:
            try:
                # Prevent disabling admin
                if user_id == 'admin':
                    self.logger.error("Cannot disable admin user")
                    return False

                if user_id not in self.users:
                    self.logger.error(f"User {user_id} not found")
                    return False

                self.users[user_id]['enabled'] = False
                self.save_users()

                # Invalidate all active sessions for this user
                tokens_to_remove = [
                    token for token, session in self.sessions.items()
                    if session['user_id'] == user_id
                ]
                for token in tokens_to_remove:
                    del self.sessions[token]

                self.logger.info(f"User disabled: {user_id}")
                return True

            except Exception as e:
                self.logger.error(f"Error disabling user: {e}")
                return False

    def update_last_login(self, user_id: str):
        """
        Update user's last login timestamp

        Args:
            user_id: User identifier
        """
        try:
            if user_id in self.users:
                self.users[user_id]['last_login'] = datetime.now().isoformat() + 'Z'
                self.save_users()
        except Exception as e:
            self.logger.error(f"Error updating last login: {e}")

    # =========================================================================
    # Legacy Methods (for backward compatibility)
    # =========================================================================

    def add_user(self, user_data: Dict) -> bool:
        """
        Add a new user (legacy method, use create_user instead)

        Args:
            user_data: User data dictionary

        Returns:
            True if successful
        """
        return self.create_user(user_data)

    # =========================================================================
    # API Key Authentication Methods
    # =========================================================================

    def extract_username_from_request(self, data: Dict) -> Optional[str]:
        """
        Extract username from request data using various field aliases.
        
        Args:
            data: Request data dictionary
            
        Returns:
            Username if found, None otherwise
        """
        for alias in self.USERNAME_ALIASES:
            if alias in data:
                return data[alias]
        return None

    def authenticate_basic(self, data: Dict) -> Tuple[bool, Optional[str], str]:
        """
        Authenticate using basic credentials (username/password).
        Returns a session token for subsequent requests.
        
        Args:
            data: Dictionary containing username (various aliases) and password
            
        Returns:
            Tuple of (success, token, message)
        """
        # Extract username using aliases
        user_id = self.extract_username_from_request(data)
        password = data.get('password')
        
        if not user_id:
            return False, None, "Username not provided. Use one of: uid, username, user_name, user_id"
        
        if not password:
            return False, None, "Password not provided"
        
        # Use existing authenticate method
        token = self.authenticate(user_id, password)
        
        if token:
            return True, token, "Authentication successful"
        else:
            if self.is_user_locked_out(user_id):
                return False, None, "Account locked due to too many failed attempts"
            return False, None, "Invalid credentials"

    def validate_api_key(self, api_key: str) -> Tuple[bool, Optional[Dict], str]:
        """
        Validate an API key.
        
        Args:
            api_key: The API key to validate
            
        Returns:
            Tuple of (is_valid, key_data, message)
        """
        return self.apikey_manager.validate_key(api_key)

    def check_api_key_tool_access(self, api_key: str, tool_name: str) -> Tuple[bool, str]:
        """
        Check if an API key has access to a specific tool.
        
        Args:
            api_key: The API key
            tool_name: Name of the tool
            
        Returns:
            Tuple of (has_access, message)
        """
        return self.apikey_manager.check_tool_access(api_key, tool_name)

    def authenticate_request(self, headers: Dict, data: Dict = None) -> Tuple[bool, Optional[Dict], str]:
        """
        Authenticate an API request using either Bearer token or API key.
        
        Args:
            headers: Request headers
            data: Request body data (for basic auth)
            
        Returns:
            Tuple of (is_authenticated, auth_context, message)
            auth_context contains: type ('session' or 'apikey'), data (session or key data)
        """
        # Check for Authorization header
        auth_header = headers.get('Authorization', headers.get('authorization', ''))
        
        # Check for API key in header
        api_key = headers.get('X-API-Key', headers.get('x-api-key', ''))
        
        # Option 1: Bearer token authentication
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            session = self.validate_session(token)
            if session:
                return True, {'type': 'session', 'data': session}, "Session valid"
            else:
                return False, None, "Invalid or expired session token"
        
        # Option 2: API key in X-API-Key header
        if api_key:
            is_valid, key_data, msg = self.validate_api_key(api_key)
            if is_valid:
                self.apikey_manager.record_usage(api_key)
                return True, {'type': 'apikey', 'data': key_data, 'key': api_key}, msg
            else:
                return False, None, msg
        
        # Option 3: API key in Authorization header (without Bearer prefix)
        if auth_header and auth_header.startswith('sja_'):
            is_valid, key_data, msg = self.validate_api_key(auth_header)
            if is_valid:
                self.apikey_manager.record_usage(auth_header)
                return True, {'type': 'apikey', 'data': key_data, 'key': auth_header}, msg
            else:
                return False, None, msg
        
        return False, None, "No valid authentication provided"

    def check_tool_access_for_auth_context(self, auth_context: Dict, tool_name: str) -> Tuple[bool, str]:
        """
        Check if an authentication context has access to a specific tool.
        
        Args:
            auth_context: Authentication context from authenticate_request
            tool_name: Name of the tool
            
        Returns:
            Tuple of (has_access, message)
        """
        if not auth_context:
            return False, "Not authenticated"
        
        auth_type = auth_context.get('type')
        
        if auth_type == 'session':
            session = auth_context.get('data', {})
            if self.has_tool_access(session, tool_name):
                return True, "Access granted"
            return False, f"User does not have access to tool '{tool_name}'"
        
        elif auth_type == 'apikey':
            api_key = auth_context.get('key')
            return self.check_api_key_tool_access(api_key, tool_name)
        
        return False, "Unknown authentication type"

    # =========================================================================
    # API Key Management (Admin Operations)
    # =========================================================================

    def create_api_key(self, **kwargs) -> Tuple[bool, str, Optional[Dict]]:
        """Create a new API key (wrapper for admin operations)"""
        return self.apikey_manager.create_key(**kwargs)

    def update_api_key(self, key: str, updates: Dict) -> Tuple[bool, str]:
        """Update an API key"""
        return self.apikey_manager.update_key(key, updates)

    def delete_api_key(self, key: str) -> Tuple[bool, str]:
        """Delete an API key"""
        return self.apikey_manager.delete_key(key)

    def list_api_keys(self, include_key: bool = False) -> List[Dict]:
        """List all API keys"""
        return self.apikey_manager.list_keys(include_key)

    def get_api_key(self, key: str, include_full_key: bool = False) -> Optional[Dict]:
        """Get a specific API key's data"""
        return self.apikey_manager.get_key(key, include_full_key)

    def enable_api_key(self, key: str) -> Tuple[bool, str]:
        """Enable an API key"""
        return self.apikey_manager.enable_key(key)

    def disable_api_key(self, key: str) -> Tuple[bool, str]:
        """Disable an API key"""
        return self.apikey_manager.disable_key(key)

    def get_api_key_statistics(self) -> Dict:
        """Get API key statistics"""
        return self.apikey_manager.get_statistics()