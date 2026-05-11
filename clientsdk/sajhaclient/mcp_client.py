"""
SAJHA MCP Server — Client SDK MCP Protocol Client

Full MCP (Model Context Protocol) client implementing JSON-RPC 2.0.

    from sajhaclient import SajhaConfig, ApiKeyAuth
    from sajhaclient.mcp_client import MCPClient

    config = SajhaConfig(base_url="http://localhost:3002", api_key="sja_xxx")
    mcp = MCPClient(config)

    # Initialize the MCP session
    caps = mcp.initialize(client_name="my-agent", client_version="1.0")

    # List and execute tools
    tools = mcp.list_tools()
    result = mcp.call_tool("wikipedia_search", query="Python programming")

    # List and get prompts
    prompts = mcp.list_prompts()
    prompt = mcp.get_prompt("code_review", arguments={"language": "python"})
"""

import json
import time
import threading
import urllib.request
import urllib.parse
import logging
from typing import Optional, Dict, Any, List, Callable

from sajhaclient.config import SajhaConfig
from sajhaclient.auth import AuthProvider, NoAuth, ApiKeyAuth, JWTAuth
from sajhaclient.exceptions import SajhaMCPError, SajhaConnectionError, SajhaAuthError

logger = logging.getLogger(__name__)


class MCPClient:
    """
    MCP (Model Context Protocol) client — JSON-RPC 2.0.

    Supports:
      - initialize / ping
      - tools/list / tools/call
      - prompts/list / prompts/get
      - resources/list / resources/read
      - completion/complete
      - logging/setLevel
      - SSE streaming transport
    """

    def __init__(self, config: Optional[SajhaConfig] = None, auth: Optional[AuthProvider] = None):
        self.config = config or SajhaConfig()
        self._auth = auth

        if not self._auth:
            if self.config.api_key:
                self._auth = ApiKeyAuth(self.config.api_key)
            elif self.config.jwt_token:
                self._auth = JWTAuth.from_token(self.config.jwt_token)
            elif self.config.username and self.config.password:
                self._auth = JWTAuth(self.config.base_url, self.config.username, self.config.password)
            else:
                self._auth = NoAuth()

        self._request_id = 0
        self._server_info: Optional[Dict] = None
        self._capabilities: Optional[Dict] = None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _rpc(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send a JSON-RPC 2.0 request and return the result."""
        self._auth.refresh_if_needed()

        request_body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'sajhaclient-mcp/4.0.0',
            **self._auth.get_headers(),
        }

        data = json.dumps(request_body).encode('utf-8')
        url = self.config.mcp_url

        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                response = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace')
            if e.code == 401:
                raise SajhaAuthError(f"MCP auth failed: {body}")
            raise SajhaMCPError(-32000, f"HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            raise SajhaConnectionError(f"Cannot connect to MCP server: {e.reason}")

        if 'error' in response:
            err = response['error']
            raise SajhaMCPError(err.get('code', -1), err.get('message', 'Unknown error'), err.get('data'))

        return response.get('result')

    # ── MCP Protocol Methods ─────────────────────────────────────

    def initialize(self, client_name: str = "sajhaclient", client_version: str = "4.0.0") -> Dict:
        """
        Initialize the MCP session. Must be called first.

        Returns:
            Server capabilities dict (tools, prompts, resources, etc.)
        """
        result = self._rpc('initialize', {
            'clientInfo': {'name': client_name, 'version': client_version}
        })
        self._server_info = result.get('serverInfo', {})
        self._capabilities = result.get('capabilities', {})
        logger.info(f"MCP initialized: {self._server_info.get('name')} v{self._server_info.get('version')}")
        return result

    def ping(self) -> Dict:
        """Ping the server. Returns status."""
        return self._rpc('ping')

    # ── Tools ────────────────────────────────────────────────────

    def list_tools(self) -> List[Dict]:
        """Get all available tools with names, descriptions, and input schemas."""
        result = self._rpc('tools/list')
        return result.get('tools', [])

    def call_tool(self, tool_name: str, **arguments) -> Any:
        """
        Execute a tool via MCP protocol.

        Args:
            tool_name: Tool to execute
            **arguments: Tool-specific arguments

        Returns:
            Tool result (content array per MCP spec)

        Example:
            result = mcp.call_tool("wikipedia_search", query="Python")
            result = mcp.call_tool("fmp_stock_quote", symbol="AAPL")
        """
        result = self._rpc('tools/call', {
            'name': tool_name,
            'arguments': arguments,
        })
        return result

    # ── Prompts ──────────────────────────────────────────────────

    def list_prompts(self) -> List[Dict]:
        """Get all available prompts."""
        result = self._rpc('prompts/list')
        return result.get('prompts', [])

    def get_prompt(self, prompt_name: str, arguments: Optional[Dict] = None) -> Dict:
        """Get a specific prompt with optional argument substitution."""
        result = self._rpc('prompts/get', {
            'name': prompt_name,
            'arguments': arguments or {},
        })
        return result

    # ── Resources ────────────────────────────────────────────────

    def list_resources(self) -> List[Dict]:
        """Get all available resources (datasets, catalogs, etc.)."""
        result = self._rpc('resources/list')
        return result.get('resources', [])

    def read_resource(self, uri: str) -> Dict:
        """Read a resource by URI."""
        return self._rpc('resources/read', {'uri': uri})

    # ── Completion ───────────────────────────────────────────────

    def complete(self, tool_name: str, argument_name: str, partial_value: str = "") -> List[str]:
        """
        Get auto-completion suggestions for a tool argument.

        Returns:
            List of suggested values
        """
        result = self._rpc('completion/complete', {
            'ref': {'type': 'ref/tool', 'name': tool_name},
            'argument': {'name': argument_name, 'value': partial_value},
        })
        return result.get('completion', {}).get('values', [])

    # ── Logging ──────────────────────────────────────────────────

    def set_log_level(self, level: str) -> Dict:
        """Set server log level (DEBUG, INFO, WARNING, ERROR)."""
        return self._rpc('logging/setLevel', {'level': level})

    # ── Server Info ──────────────────────────────────────────────

    @property
    def server_info(self) -> Optional[Dict]:
        return self._server_info

    @property
    def capabilities(self) -> Optional[Dict]:
        return self._capabilities


class MCPSSEClient:
    """
    MCP client using Server-Sent Events (SSE) transport.

    Connects to the SSE endpoint for streaming notifications,
    while sending requests via the paired HTTP POST endpoint.

    Usage:
        sse = MCPSSEClient(config)
        sse.connect()

        # Send requests via the SSE message endpoint
        result = sse.call_tool("wikipedia_search", query="Python")

        # Listen for notifications
        sse.on_notification(lambda n: print(f"Notification: {n}"))

        sse.disconnect()
    """

    def __init__(self, config: Optional[SajhaConfig] = None, auth: Optional[AuthProvider] = None):
        self.config = config or SajhaConfig()
        self._auth = auth or NoAuth()
        self._message_url: Optional[str] = None
        self._connected = False
        self._notification_handlers: List[Callable] = []
        self._listener_thread: Optional[threading.Thread] = None
        self._request_id = 0

    def connect(self) -> None:
        """Connect to the SSE endpoint and obtain the message URL."""
        headers = {
            'Accept': 'text/event-stream',
            **self._auth.get_headers(),
        }

        try:
            req = urllib.request.Request(self.config.mcp_sse_url, headers=headers)
            self._sse_response = urllib.request.urlopen(req, timeout=self.config.timeout)
            self._connected = True

            # Read the first event to get the message endpoint
            for line in self._sse_response:
                line = line.decode('utf-8').strip()
                if line.startswith('data:'):
                    endpoint = line[5:].strip()
                    self._message_url = f"{self.config.base_url}{endpoint}"
                    logger.info(f"SSE connected, message URL: {self._message_url}")
                    break

            # Start background listener for notifications
            self._listener_thread = threading.Thread(target=self._listen, daemon=True)
            self._listener_thread.start()

        except Exception as e:
            raise SajhaConnectionError(f"SSE connection failed: {e}")

    def _listen(self) -> None:
        """Background listener for SSE notifications."""
        try:
            for line in self._sse_response:
                line = line.decode('utf-8').strip()
                if line.startswith('data:') and line != 'data: ':
                    try:
                        notification = json.loads(line[5:].strip())
                        for handler in self._notification_handlers:
                            handler(notification)
                    except json.JSONDecodeError:
                        pass
        except Exception:
            self._connected = False

    def on_notification(self, handler: Callable) -> None:
        """Register a callback for incoming notifications."""
        self._notification_handlers.append(handler)

    def disconnect(self) -> None:
        """Disconnect from SSE."""
        self._connected = False
        if hasattr(self, '_sse_response'):
            self._sse_response.close()

    @property
    def connected(self) -> bool:
        return self._connected


# ═════════════════════════════════════════════════════════════════
# MCPWebSocketClient — Full-duplex WebSocket MCP transport
# ═════════════════════════════════════════════════════════════════

class MCPWebSocketClient:
    """
    WebSocket transport for MCP JSON-RPC 2.0.

    Full-duplex: send requests AND receive server-pushed notifications
    on the same connection. No separate SSE stream needed.

    Requires: pip install websockets (optional dependency)

    Usage:
        ws = MCPWebSocketClient(config, auth=ApiKeyAuth("sk-..."))
        ws.connect()

        # Initialize session
        ws.initialize()

        # Call tools
        result = ws.call_tool("yahoo_quote", symbol="AAPL")

        # Listen for notifications (non-blocking)
        ws.on_notification(lambda n: print(f"Changed: {n}"))

        ws.disconnect()
    """

    def __init__(self, config: Optional[SajhaConfig] = None, auth: Optional[AuthProvider] = None):
        self.config = config or SajhaConfig()
        self._auth = auth or NoAuth()
        self._ws = None
        self._connected = False
        self._initialized = False
        self._request_id = 0
        self._pending: Dict[int, threading.Event] = {}
        self._responses: Dict[int, dict] = {}
        self._notification_handlers: List[Callable] = []
        self._listener_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    @property
    def ws_url(self) -> str:
        """Build WebSocket URL with auth query params."""
        base = self.config.base_url.replace('http://', 'ws://').replace('https://', 'wss://')
        url = f"{base}/mcp/ws"
        headers = self._auth.get_headers()
        if 'Authorization' in headers:
            token = headers['Authorization'].replace('Bearer ', '')
            url += f"?token={token}"
        elif 'X-API-Key' in headers:
            url += f"?api_key={headers['X-API-Key']}"
        return url

    def connect(self) -> None:
        """Connect to the WebSocket endpoint."""
        try:
            import websockets.sync.client as ws_sync
        except ImportError:
            raise ImportError(
                "WebSocket client requires the 'websockets' package. "
                "Install it with: pip install websockets"
            )

        try:
            self._ws = ws_sync.connect(self.ws_url)
            self._connected = True

            # Start background listener
            self._listener_thread = threading.Thread(target=self._listen, daemon=True)
            self._listener_thread.start()

            logger.info(f"WebSocket connected to {self.ws_url.split('?')[0]}")
        except Exception as e:
            raise SajhaConnectionError(f"WebSocket connection failed: {e}")

    def _listen(self) -> None:
        """Background thread: read messages, route responses vs notifications."""
        try:
            while self._connected and self._ws:
                try:
                    raw = self._ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                except Exception:
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if 'id' in msg and msg['id'] in self._pending:
                    # Response to a request we sent
                    req_id = msg['id']
                    self._responses[req_id] = msg
                    self._pending[req_id].set()
                elif 'method' in msg and 'id' not in msg:
                    # Server-initiated notification
                    for handler in self._notification_handlers:
                        try:
                            handler(msg)
                        except Exception as e:
                            logger.warning(f"Notification handler error: {e}")
        except Exception:
            pass
        finally:
            self._connected = False

    def _send_request(self, method: str, params: dict = None, timeout: float = None) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        if not self._connected or not self._ws:
            raise SajhaConnectionError("Not connected")

        req_id = self._next_id()
        msg = {'jsonrpc': '2.0', 'id': req_id, 'method': method}
        if params:
            msg['params'] = params

        event = threading.Event()
        self._pending[req_id] = event

        self._ws.send(json.dumps(msg))

        # Wait for response
        wait_timeout = timeout or self.config.timeout
        if not event.wait(timeout=wait_timeout):
            self._pending.pop(req_id, None)
            raise SajhaTimeoutError(f"Timeout waiting for response to {method}")

        self._pending.pop(req_id, None)
        response = self._responses.pop(req_id, {})

        if 'error' in response:
            err = response['error']
            raise SajhaError(f"[{err.get('code')}] {err.get('message')}")

        return response.get('result', {})

    def initialize(self, client_name: str = 'sajhaclient-ws', client_version: str = '1.0.0') -> dict:
        """Send initialize request."""
        result = self._send_request('initialize', {
            'protocolVersion': '2025-06-18',
            'clientInfo': {'name': client_name, 'version': client_version},
            'capabilities': {},
        })
        self._initialized = True
        # Send initialized notification (no response expected)
        self._ws.send(json.dumps({
            'jsonrpc': '2.0', 'method': 'initialized', 'params': {}
        }))
        return result

    def list_tools(self, cursor: str = None) -> dict:
        """List available tools."""
        params = {}
        if cursor:
            params['cursor'] = cursor
        return self._send_request('tools/list', params)

    def call_tool(self, name: str, **arguments) -> dict:
        """Execute a tool."""
        return self._send_request('tools/call', {'name': name, 'arguments': arguments})

    def list_resources(self) -> dict:
        return self._send_request('resources/list', {})

    def read_resource(self, uri: str) -> dict:
        return self._send_request('resources/read', {'uri': uri})

    def list_prompts(self) -> dict:
        return self._send_request('prompts/list', {})

    def get_prompt(self, name: str, arguments: dict = None) -> dict:
        return self._send_request('prompts/get', {'name': name, 'arguments': arguments or {}})

    def ping(self) -> dict:
        return self._send_request('ping', {})

    def on_notification(self, handler: Callable) -> None:
        """Register a callback for server-pushed notifications."""
        self._notification_handlers.append(handler)

    def disconnect(self) -> None:
        """Close the WebSocket connection."""
        self._connected = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._connected

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()
