"""
Enhanced Base class for MCP tools with stateful capabilities using SSE
"""
import json
import time
import uuid
from typing import Dict, Any, List, Optional, Callable
from collections import deque
from datetime import datetime
import threading
import queue


class StatefulSession:
    """Represents a stateful session for a tool"""
    
    def __init__(self, session_id: str, tool_name: str, max_message_history: int = 100):
        self.session_id = session_id
        self.tool_name = tool_name
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.state = {}  # Custom state dictionary
        self.message_queue = queue.Queue()  # Queue for SSE messages
        self.message_history = deque(maxlen=max_message_history)
        self.subscriptions = []  # List of event subscriptions
        self.is_active = True
        self._lock = threading.RLock()
        
    def update_activity(self):
        """Update last activity timestamp"""
        with self._lock:
            self.last_activity = datetime.now()
    
    def set_state(self, key: str, value: Any):
        """Set a state value"""
        with self._lock:
            self.state[key] = value
            self.update_activity()
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """Get a state value"""
        with self._lock:
            return self.state.get(key, default)
    
    def push_message(self, event_type: str, data: Dict[str, Any]):
        """Push a message to the SSE queue"""
        with self._lock:
            if not self.is_active:
                return
            
            message = {
                'id': str(uuid.uuid4()),
                'event': event_type,
                'data': data,
                'timestamp': datetime.now().isoformat()
            }
            
            self.message_queue.put(message)
            self.message_history.append(message)
            self.update_activity()
    
    def get_messages(self, timeout: float = 30.0) -> List[Dict[str, Any]]:
        """Get pending messages (blocking with timeout)"""
        messages = []
        try:
            # Get first message with timeout
            msg = self.message_queue.get(timeout=timeout)
            messages.append(msg)
            
            # Get any other pending messages without blocking
            while not self.message_queue.empty():
                try:
                    msg = self.message_queue.get_nowait()
                    messages.append(msg)
                except queue.Empty:
                    break
        except queue.Empty:
            pass
        
        return messages
    
    def close(self):
        """Close the session"""
        with self._lock:
            self.is_active = False
            # Clear the queue
            while not self.message_queue.empty():
                try:
                    self.message_queue.get_nowait()
                except queue.Empty:
                    break


class BaseMCPTool:
    """Base class for all MCP tools with optional stateful capabilities"""

    def __init__(self, config_path: str):
        """
        Initialize the MCP tool with configuration

        Args:
            config_path: Path to the JSON configuration file
        """
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        self.name = self.config.get('name', 'unnamed_tool')
        self.module = self.config.get('module', '')
        self.max_hits = self.config.get('max_hits', 1000)
        self.max_hit_interval = self.config.get('max_hit_interval', 10)
        self.tool_description = self.config.get('tool_description', {})
        
        # Stateful configuration
        self.stateful_enabled = self.config.get('stateful_enabled', False)
        self.session_timeout = self.config.get('session_timeout', 3600)  # 1 hour default
        self.max_sessions = self.config.get('max_sessions', 100)
        self.sse_enabled = self.config.get('sse_enabled', False)
        self.push_enabled = self.config.get('push_enabled', False)

        # Tracking variables
        self.call_history = deque(maxlen=50)  # Last 50 calls
        self.error_history = deque(maxlen=50)  # Last 50 errors
        self.call_count = 0
        self.rate_limiter = deque()  # For rate limiting
        self._lock = threading.RLock()
        
        # Stateful session management
        self.sessions: Dict[str, StatefulSession] = {}
        self._session_lock = threading.RLock()
        
        # Background thread for session cleanup
        if self.stateful_enabled:
            self._cleanup_thread = threading.Thread(target=self._session_cleanup_worker, daemon=True)
            self._cleanup_thread.start()

        # Initialize tool-specific components
        self._initialize()

    def _initialize(self):
        """Override in subclasses for tool-specific initialization"""
        pass

    def check_rate_limit(self) -> bool:
        """
        Check if the rate limit has been exceeded

        Returns:
            True if rate limit exceeded, False otherwise
        """
        with self._lock:
            current_time = time.time()

            # Remove old entries outside the interval window
            while self.rate_limiter and self.rate_limiter[0] < current_time - self.max_hit_interval:
                self.rate_limiter.popleft()

            # Check if we've exceeded max_hits
            if len(self.rate_limiter) >= self.max_hits:
                return True

            # Add current request
            self.rate_limiter.append(current_time)
            return False

    def record_call(self, method_name: str, arguments: Dict[str, Any], result: Any = None, error: str = None):
        """
        Record a tool call for monitoring

        Args:
            method_name: Name of the method called
            arguments: Arguments passed to the method
            result: Result of the call (if successful)
            error: Error message (if failed)
        """
        with self._lock:
            self.call_count += 1

            call_record = {
                'timestamp': datetime.now().isoformat(),
                'method': method_name,
                'arguments': arguments,
                'call_number': self.call_count
            }

            if error:
                call_record['error'] = error
                self.error_history.append(call_record)
            else:
                call_record['result'] = str(result)[:200] if result else None  # Truncate large results

            self.call_history.append(call_record)

    def get_tools_definition(self) -> List[Dict[str, Any]]:
        """
        Get MCP tools definition for this tool

        Returns:
            List of tool definitions in MCP format
        """
        tools = self.tool_description.get('tools', [])
        
        # Add stateful session management tools if enabled
        if self.stateful_enabled:
            stateful_tools = [
                {
                    "name": "create_session",
                    "description": f"Create a new stateful session for {self.name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "initial_state": {
                                "type": "object",
                                "description": "Initial state for the session"
                            }
                        }
                    }
                },
                {
                    "name": "close_session",
                    "description": f"Close an existing stateful session",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to close"
                            }
                        },
                        "required": ["session_id"]
                    }
                },
                {
                    "name": "get_session_state",
                    "description": f"Get the current state of a session",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID"
                            }
                        },
                        "required": ["session_id"]
                    }
                },
                {
                    "name": "set_session_state",
                    "description": f"Update the state of a session",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID"
                            },
                            "state": {
                                "type": "object",
                                "description": "State to update"
                            }
                        },
                        "required": ["session_id", "state"]
                    }
                }
            ]
            tools.extend(stateful_tools)
        
        return tools

    def get_resources_definition(self) -> List[Dict[str, Any]]:
        """
        Get MCP resources definition for this tool

        Returns:
            List of resource definitions in MCP format
        """
        return self.tool_description.get('resources', [])

    def get_prompts_definition(self) -> List[Dict[str, Any]]:
        """
        Get MCP prompts definition for this tool

        Returns:
            List of prompt definitions in MCP format
        """
        return self.tool_description.get('prompts', [])

    def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle a tool call - override in subclasses

        Args:
            tool_name: Name of the tool being called
            arguments: Arguments for the tool

        Returns:
            Result of the tool call
        """
        # Handle stateful session management calls
        if self.stateful_enabled:
            if tool_name == "create_session":
                return self._create_session(arguments)
            elif tool_name == "close_session":
                return self._close_session(arguments)
            elif tool_name == "get_session_state":
                return self._get_session_state(arguments)
            elif tool_name == "set_session_state":
                return self._set_session_state(arguments)
        
        raise NotImplementedError("Subclasses must implement handle_tool_call")
    
    # ==================== STATEFUL SESSION METHODS ====================
    
    def _create_session(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new stateful session"""
        with self._session_lock:
            # Check if we've reached max sessions
            if len(self.sessions) >= self.max_sessions:
                return {
                    "error": "Maximum number of sessions reached",
                    "max_sessions": self.max_sessions
                }
            
            # Generate session ID
            session_id = str(uuid.uuid4())
            
            # Create session
            session = StatefulSession(session_id, self.name)
            
            # Set initial state if provided
            initial_state = arguments.get('initial_state', {})
            for key, value in initial_state.items():
                session.set_state(key, value)
            
            self.sessions[session_id] = session
            
            return {
                "session_id": session_id,
                "created_at": session.created_at.isoformat(),
                "sse_enabled": self.sse_enabled,
                "push_enabled": self.push_enabled
            }
    
    def _close_session(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Close a stateful session"""
        session_id = arguments.get('session_id')
        
        if not session_id:
            return {"error": "Session ID required"}
        
        with self._session_lock:
            session = self.sessions.get(session_id)
            
            if not session:
                return {"error": "Session not found"}
            
            session.close()
            del self.sessions[session_id]
            
            return {
                "success": True,
                "session_id": session_id,
                "message": "Session closed successfully"
            }
    
    def _get_session_state(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get session state"""
        session_id = arguments.get('session_id')
        
        if not session_id:
            return {"error": "Session ID required"}
        
        with self._session_lock:
            session = self.sessions.get(session_id)
            
            if not session:
                return {"error": "Session not found"}
            
            return {
                "session_id": session_id,
                "state": session.state.copy(),
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat()
            }
    
    def _set_session_state(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Set session state"""
        session_id = arguments.get('session_id')
        state = arguments.get('state', {})
        
        if not session_id:
            return {"error": "Session ID required"}
        
        with self._session_lock:
            session = self.sessions.get(session_id)
            
            if not session:
                return {"error": "Session not found"}
            
            for key, value in state.items():
                session.set_state(key, value)
            
            return {
                "success": True,
                "session_id": session_id,
                "state": session.state.copy()
            }
    
    def get_session(self, session_id: str) -> Optional[StatefulSession]:
        """Get a session by ID"""
        with self._session_lock:
            return self.sessions.get(session_id)
    
    def push_to_session(self, session_id: str, event_type: str, data: Dict[str, Any]):
        """Push a message to a session's SSE queue"""
        if not self.push_enabled:
            return
        
        session = self.get_session(session_id)
        if session:
            session.push_message(event_type, data)
    
    def _session_cleanup_worker(self):
        """Background worker to clean up expired sessions"""
        while True:
            try:
                time.sleep(60)  # Check every minute
                
                current_time = datetime.now()
                expired_sessions = []
                
                with self._session_lock:
                    for session_id, session in self.sessions.items():
                        age = (current_time - session.last_activity).total_seconds()
                        if age > self.session_timeout:
                            expired_sessions.append(session_id)
                    
                    # Remove expired sessions
                    for session_id in expired_sessions:
                        session = self.sessions[session_id]
                        session.close()
                        del self.sessions[session_id]
                        print(f"Cleaned up expired session: {session_id}")
                        
            except Exception as e:
                print(f"Error in session cleanup worker: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics for this tool

        Returns:
            Dictionary of statistics
        """
        with self._lock:
            current_time = time.time()

            # Calculate calls per minute
            recent_calls = [t for t in self.rate_limiter if t > current_time - 60]
            calls_per_minute = len(recent_calls)
            
            stats = {
                'name': self.name,
                'total_calls': self.call_count,
                'calls_per_minute': calls_per_minute,
                'recent_calls': list(self.call_history),
                'recent_errors': list(self.error_history),
                'error_count': len(self.error_history),
                'stateful_enabled': self.stateful_enabled
            }
            
            # Add stateful stats if enabled
            if self.stateful_enabled:
                with self._session_lock:
                    stats['active_sessions'] = len(self.sessions)
                    stats['max_sessions'] = self.max_sessions
                    stats['session_timeout'] = self.session_timeout
                    stats['sse_enabled'] = self.sse_enabled
                    stats['push_enabled'] = self.push_enabled
            
            return stats
