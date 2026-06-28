"""
MCP 2025-11-25 Features — Tasks, Elicitation, Sampling
SAJHA MCP Server v5.2.0
Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

Implements the new primitives from MCP spec 2025-11-25:
  - Tasks: async tracking for long-running requests (SEP-1686)
  - Elicitation: server-initiated user input requests (SEP-1330, SEP-1036)
  - Sampling with tools: server-initiated LLM calls with tool use (SEP-1577)
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
# TASKS (SEP-1686) — Async tracking for durable requests
# ═══════════════════════════════════════════════════

class TaskState(str, Enum):
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class MCPTask:
    """A trackable task for long-running MCP requests."""
    task_id: str
    method: str
    params: Dict[str, Any]
    state: TaskState = TaskState.WORKING
    progress: Optional[float] = None  # 0.0–1.0
    progress_message: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    ttl_seconds: int = 3600  # Server-defined duration to retain results

    def to_dict(self) -> Dict:
        d = {
            "taskId": self.task_id,
            "state": self.state.value,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if self.progress is not None:
            d["progress"] = self.progress
        if self.progress_message:
            d["progressMessage"] = self.progress_message
        if self.state == TaskState.COMPLETED and self.result is not None:
            d["result"] = self.result
        if self.state == TaskState.FAILED and self.error:
            d["error"] = self.error
        return d


class TaskManager:
    """Manages async MCP tasks with state tracking and polling."""

    def __init__(self, default_ttl: int = 3600):
        self._tasks: Dict[str, MCPTask] = {}
        self._default_ttl = default_ttl
        self._lock = __import__('threading').Lock()

    def create_task(self, method: str, params: Dict) -> MCPTask:
        task = MCPTask(
            task_id=str(uuid.uuid4()),
            method=method,
            params=params,
            ttl_seconds=self._default_ttl,
        )
        with self._lock:
            self._tasks[task.task_id] = task
        logger.info(f"Task created: {task.task_id} for {method}")
        return task

    def get_task(self, task_id: str) -> Optional[MCPTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(self, task_id: str, state: TaskState,
                    result: Any = None, error: str = None,
                    progress: float = None, progress_message: str = None):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.state = state
            task.updated_at = time.time()
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            if progress is not None:
                task.progress = progress
            if progress_message is not None:
                task.progress_message = progress_message
        logger.info(f"Task {task_id}: state={state.value}")

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.state == TaskState.WORKING:
                task.state = TaskState.CANCELLED
                task.updated_at = time.time()
                return True
        return False

    def list_tasks(self) -> List[Dict]:
        with self._lock:
            self._cleanup_expired()
            return [t.to_dict() for t in self._tasks.values()]

    def _cleanup_expired(self):
        now = time.time()
        expired = [tid for tid, t in self._tasks.items()
                   if t.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED)
                   and now - t.updated_at > t.ttl_seconds]
        for tid in expired:
            del self._tasks[tid]

    def handle_tasks_get(self, params: Dict) -> Dict:
        """Handle tasks/get MCP method."""
        task_id = params.get("taskId")
        if not task_id:
            return {"error": {"code": -32602, "message": "taskId required"}}
        task = self.get_task(task_id)
        if not task:
            return {"error": {"code": -32602, "message": f"Task {task_id} not found"}}
        return task.to_dict()

    def handle_tasks_list(self, params: Dict) -> Dict:
        """Handle tasks/list MCP method."""
        return {"tasks": self.list_tasks()}

    def handle_tasks_cancel(self, params: Dict) -> Dict:
        """Handle tasks/cancel MCP method."""
        task_id = params.get("taskId")
        if not task_id:
            return {"error": {"code": -32602, "message": "taskId required"}}
        if self.cancel_task(task_id):
            return {"cancelled": True, "taskId": task_id}
        return {"error": {"code": -32602, "message": "Task not found or not cancellable"}}


# ═══════════════════════════════════════════════════
# ELICITATION (SEP-1330, SEP-1036) — Server asks user for input
# ═══════════════════════════════════════════════════

class ElicitationMode(str, Enum):
    FORM = "form"
    URL = "url"


@dataclass
class ElicitationRequest:
    """Server-initiated request for user input."""
    request_id: str
    mode: ElicitationMode
    # Form mode fields
    message: Optional[str] = None
    schema: Optional[Dict] = None  # JSON Schema for form fields
    # URL mode fields
    url: Optional[str] = None
    reason: Optional[str] = None
    # Response
    response: Optional[Dict] = None
    status: str = "pending"  # pending, completed, cancelled
    created_at: float = field(default_factory=time.time)

    def to_request_dict(self) -> Dict:
        """Format as elicitation/create request params."""
        d = {"requestId": self.request_id, "mode": self.mode.value}
        if self.mode == ElicitationMode.FORM:
            d["message"] = self.message or ""
            if self.schema:
                d["schema"] = self.schema
        elif self.mode == ElicitationMode.URL:
            d["url"] = self.url
            if self.reason:
                d["reason"] = self.reason
        return d


class ElicitationManager:
    """
    Manages server-initiated elicitation requests.
    
    Elicitation allows the server to ask the user for additional input
    during tool execution. Two modes:
      - form: structured form with JSON Schema
      - url: redirect user to a URL (e.g., OAuth consent page)
    """

    def __init__(self):
        self._pending: Dict[str, ElicitationRequest] = {}
        self._handlers: List[Callable] = []

    @property
    def supported_modes(self) -> List[str]:
        return [ElicitationMode.FORM.value, ElicitationMode.URL.value]

    def create_form_elicitation(self, message: str, schema: Dict) -> ElicitationRequest:
        """Create a form-mode elicitation request."""
        req = ElicitationRequest(
            request_id=str(uuid.uuid4()),
            mode=ElicitationMode.FORM,
            message=message,
            schema=schema,
        )
        self._pending[req.request_id] = req
        logger.info(f"Elicitation created (form): {req.request_id}")
        return req

    def create_url_elicitation(self, url: str, reason: str = None) -> ElicitationRequest:
        """Create a URL-mode elicitation request."""
        req = ElicitationRequest(
            request_id=str(uuid.uuid4()),
            mode=ElicitationMode.URL,
            url=url,
            reason=reason,
        )
        self._pending[req.request_id] = req
        logger.info(f"Elicitation created (url): {req.request_id}")
        return req

    def respond(self, request_id: str, response: Dict) -> bool:
        """Handle user's response to an elicitation request."""
        req = self._pending.get(request_id)
        if not req or req.status != "pending":
            return False
        req.response = response
        req.status = "completed"
        logger.info(f"Elicitation responded: {request_id}")
        return True

    def cancel(self, request_id: str) -> bool:
        """Cancel a pending elicitation."""
        req = self._pending.get(request_id)
        if not req or req.status != "pending":
            return False
        req.status = "cancelled"
        return True

    def get_request(self, request_id: str) -> Optional[ElicitationRequest]:
        return self._pending.get(request_id)

    def handle_elicitation_respond(self, params: Dict) -> Dict:
        """Handle elicitation/respond MCP method (client → server)."""
        request_id = params.get("requestId")
        action = params.get("action", "submit")
        content = params.get("content", {})
        if not request_id:
            return {"error": {"code": -32602, "message": "requestId required"}}
        if action == "cancel":
            self.cancel(request_id)
            return {"cancelled": True}
        if self.respond(request_id, content):
            return {"accepted": True}
        return {"error": {"code": -32602, "message": "Request not found or already responded"}}


# ═══════════════════════════════════════════════════
# SAMPLING WITH TOOLS (SEP-1577)
# ═══════════════════════════════════════════════════

@dataclass
class SamplingRequest:
    """Server-initiated LLM sampling request with optional tool use."""
    request_id: str
    messages: List[Dict]
    model_preferences: Optional[Dict] = None
    system_prompt: Optional[str] = None
    max_tokens: int = 1024
    temperature: Optional[float] = None
    # SEP-1577: tool calling support
    tools: Optional[List[Dict]] = None
    tool_choice: Optional[Dict] = None  # {"type": "auto"} | {"type": "tool", "name": "..."} | {"type": "none"}
    # Response
    response: Optional[Dict] = None
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


class SamplingManager:
    """
    Manages server-initiated sampling requests.
    
    Sampling allows the server to request an LLM completion from the client.
    2025-11-25 adds tool calling support: the server can include tool definitions
    and the client's LLM can call tools during sampling.
    """

    def __init__(self):
        self._pending: Dict[str, SamplingRequest] = {}

    def create_request(self, messages: List[Dict],
                       system_prompt: str = None,
                       max_tokens: int = 1024,
                       temperature: float = None,
                       tools: List[Dict] = None,
                       tool_choice: Dict = None) -> SamplingRequest:
        req = SamplingRequest(
            request_id=str(uuid.uuid4()),
            messages=messages,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
        )
        self._pending[req.request_id] = req
        logger.info(f"Sampling request created: {req.request_id}")
        return req

    def to_request_dict(self, req: SamplingRequest) -> Dict:
        """Format as sampling/createMessage params."""
        d = {
            "messages": req.messages,
            "maxTokens": req.max_tokens,
        }
        if req.system_prompt:
            d["systemPrompt"] = req.system_prompt
        if req.model_preferences:
            d["modelPreferences"] = req.model_preferences
        if req.temperature is not None:
            d["temperature"] = req.temperature
        if req.tools:
            d["tools"] = req.tools
        if req.tool_choice:
            d["toolChoice"] = req.tool_choice
        return d

    def handle_response(self, request_id: str, response: Dict) -> bool:
        req = self._pending.get(request_id)
        if not req:
            return False
        req.response = response
        req.status = "completed"
        return True


# ═══════════════════════════════════════════════════
# TOOL ICONS & ANNOTATIONS (SEP-973)
# ═══════════════════════════════════════════════════

def add_tool_icon(tool_dict: Dict, tool_config: Dict) -> Dict:
    """Add icon metadata to a tool's MCP format if configured."""
    icon = tool_config.get('icon')
    if icon:
        tool_dict['icon'] = icon  # e.g., {"type": "url", "url": "https://..."} or {"type": "emoji", "emoji": "📊"}
    # Annotations (from 2025-06-18, carried forward)
    annotations = tool_config.get('annotations')
    if annotations:
        tool_dict['annotations'] = annotations
    return tool_dict


# ═══════════════════════════════════════════════════
# ORIGIN VALIDATION (Minor 3)
# ═══════════════════════════════════════════════════

def validate_origin(request_origin: Optional[str], allowed_origins: List[str] = None) -> bool:
    """
    Validate Origin header per MCP 2025-11-25 Streamable HTTP transport.
    Servers MUST respond with 403 for invalid Origin headers.
    """
    if not request_origin:
        return True  # No origin = same-origin or non-browser
    if not allowed_origins:
        return True  # No restrictions configured
    if '*' in allowed_origins:
        return True
    return request_origin in allowed_origins


# ═══════════════════════════════════════════════════
# OIDC DISCOVERY (Major 1) & PRM (Minor 8) & CIMD (Major 8)
# ═══════════════════════════════════════════════════

def build_openid_configuration(issuer_url: str, server_url: str) -> Dict:
    """
    Build an OpenID Connect Discovery 1.0 document.
    MCP 2025-11-25 Major 1: Enhance auth server discovery with OIDC Discovery.
    Served at: GET /.well-known/openid-configuration
    """
    return {
        "issuer": issuer_url,
        "authorization_endpoint": f"{server_url}/oauth/authorize",
        "token_endpoint": f"{server_url}/oauth/token",
        "jwks_uri": f"{server_url}/oauth/jwks",
        "registration_endpoint": f"{server_url}/oauth/register",
        "scopes_supported": ["openid", "profile", "tools:read", "tools:execute", "admin"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256", "HS256"],
    }


def build_protected_resource_metadata(server_url: str) -> Dict:
    """
    Build an OAuth 2.0 Protected Resource Metadata document per RFC 9728.
    MCP 2025-11-25 Minor 8: Align with RFC 9728.
    Served at: GET /.well-known/oauth-protected-resource
    """
    return {
        "resource": server_url,
        "authorization_servers": [server_url],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["tools:read", "tools:execute", "admin"],
        "resource_documentation": f"{server_url}/docs",
    }


def build_client_id_metadata_document(client_id: str, client_name: str,
                                       redirect_uris: List[str] = None) -> Dict:
    """
    Build a Client ID Metadata Document (CIMD) per SEP-991.
    MCP 2025-11-25 Major 8: Recommended client registration mechanism.
    Served at: GET /.well-known/oauth-client/{client_id}
    """
    doc = {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris or [f"http://localhost:3002/oauth/callback"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_basic",
        "scope": "tools:read tools:execute",
    }
    return doc


# ═══════════════════════════════════════════════════
# SSE EVENT IDs + RESUMPTION (Minor 7)
# ═══════════════════════════════════════════════════

class SSEEventTracker:
    """
    Tracks SSE event IDs for stream resumption.
    MCP 2025-11-25 Minor 7: Event IDs encode stream identity.
    Clients send Last-Event-ID to resume from where they left off.
    """

    def __init__(self, max_buffer: int = 1000):
        self._counter = 0
        self._buffer: List[Dict] = []  # Ring buffer of recent events
        self._max_buffer = max_buffer
        self._lock = __import__('threading').Lock()

    def next_id(self, session_id: str) -> str:
        """Generate next event ID: session:counter format."""
        with self._lock:
            self._counter += 1
            return f"{session_id}:{self._counter}"

    def record_event(self, event_id: str, event_type: str, data: str):
        """Store event for replay on reconnection."""
        with self._lock:
            self._buffer.append({
                "id": event_id,
                "event": event_type,
                "data": data,
                "timestamp": time.time(),
            })
            if len(self._buffer) > self._max_buffer:
                self._buffer = self._buffer[-self._max_buffer:]

    def get_events_after(self, last_event_id: str) -> List[Dict]:
        """Get all events after a given ID for stream resumption."""
        with self._lock:
            found = False
            result = []
            for evt in self._buffer:
                if found:
                    result.append(evt)
                elif evt["id"] == last_event_id:
                    found = True
            return result

    def format_sse_event(self, event_type: str, data: str,
                         event_id: str = None) -> str:
        """Format an SSE event with id: field per spec."""
        lines = []
        if event_id:
            lines.append(f"id: {event_id}")
        lines.append(f"event: {event_type}")
        for d_line in data.split('\n'):
            lines.append(f"data: {d_line}")
        lines.append("")
        lines.append("")
        return '\n'.join(lines)
