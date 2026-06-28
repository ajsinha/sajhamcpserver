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
            'User-Agent': 'sajhaclient-mcp/5.1.0',
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

    def initialize(self, client_name: str = "sajhaclient", client_version: str = "5.1.0") -> Dict:
        """
        Initialize the MCP session. Must be called first.

        Returns:
            Server capabilities dict (tools, prompts, resources, etc.)
        """
        result = self._rpc('initialize', {
            'protocolVersion': '2025-11-25',
            'clientInfo': {'name': client_name, 'version': client_version},
            'capabilities': {},
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
    MCP client using Streamable HTTP transport (SSE).

    Per MCP 2025-11-25: connects to GET /mcp for SSE stream,
    POSTs JSON-RPC requests to POST /mcp.

    Usage:
        sse = MCPSSEClient(config)
        sse.connect()       # GET /mcp → opens SSE stream
        sse.initialize()    # POST /mcp → initialize handshake

        result = sse.call_tool("yahoo_quote", symbol="AAPL")

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
                        logger.debug("SSE data not JSON, skipping", exc_info=True)
                        pass
        except Exception as e:
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

    def _rpc(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send JSON-RPC 2.0 request via the SSE message POST endpoint."""
        if not self._message_url:
            raise SajhaConnectionError("Not connected — call connect() first")
        self._request_id += 1
        payload = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params or {},
            'id': self._request_id,
        }
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'sajhaclient-sse/5.1.0',
            **self._auth.get_headers(),
        }
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self._message_url, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                body = json.loads(resp.read().decode('utf-8'))
                if 'error' in body:
                    raise SajhaMCPError(body['error'].get('message', 'RPC error'), body['error'].get('code', -1))
                return body.get('result')
        except urllib.error.HTTPError as e:
            raise SajhaMCPError(f"SSE RPC failed: HTTP {e.code}", e.code)
        except Exception as e:
            logger.error(f"SSE RPC error: {e}", exc_info=True)
            raise SajhaConnectionError(f"SSE RPC failed: {e}")

    def initialize(self, client_name: str = "sajhaclient-sse", client_version: str = "5.1.0") -> Dict:
        """Initialize MCP session over SSE transport."""
        if not self._connected:
            self.connect()
        result = self._rpc('initialize', {
            'protocolVersion': '2025-11-25',
            'clientInfo': {'name': client_name, 'version': client_version},
            'capabilities': {},
        })
        return result or {}

    def list_tools(self, cursor: str = None) -> List[Dict]:
        """List available tools."""
        params = {}
        if cursor:
            params['cursor'] = cursor
        result = self._rpc('tools/list', params)
        return result.get('tools', []) if isinstance(result, dict) else []

    def call_tool(self, name: str, **arguments) -> Any:
        """Execute a tool by name."""
        return self._rpc('tools/call', {'name': name, 'arguments': arguments})

    def ping(self) -> Dict:
        """Ping the server."""
        return self._rpc('ping', {}) or {}

    def list_prompts(self) -> List[Dict]:
        """List available prompts."""
        result = self._rpc('prompts/list', {})
        return result.get('prompts', []) if isinstance(result, dict) else []


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
                except TimeoutError as e:
                    logger.debug(f"Handled: {e}")
                    continue
                except Exception as e:
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.debug("WS message not valid JSON, skipping", exc_info=True)
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
                            logger.warning(f"Notification handler error: {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
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

    def initialize(self, client_name: str = 'sajhaclient-ws', client_version: str = '5.1.0') -> dict:
        """Send initialize request."""
        result = self._send_request('initialize', {
            'protocolVersion': '2025-11-25',
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
            except Exception as e:
                logger.warning(f"Error handled: {e}", exc_info=True)
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


# ═══════════════════════════════════════════════════════════════
# PILLAR 2: Transport Coalgebra
# ═══════════════════════════════════════════════════════════════

class TransportCoalgebra:
    """
    Abstract coalgebraic interface for MCP transports.

    All three transport clients (HTTP, SSE, WebSocket) implement the same
    transition function: step(request) → (response, new_state).

    This enables:
      - Behavioral equivalence testing (bisimulation)
      - Runtime transport hot-swap
      - Unified retry/fallback logic
    """

    def __init__(self, config: Optional[SajhaConfig] = None, auth: Optional[AuthProvider] = None):
        self.config = config or SajhaConfig()
        self._auth = auth or NoAuth()
        self._state = {'initialized': False, 'request_count': 0, 'transport': 'unknown'}

    @property
    def state(self) -> dict:
        return dict(self._state)

    def step(self, method: str, params: Optional[Dict] = None) -> tuple:
        """
        Coalgebraic transition: (state, input) → (output, new_state).
        Input = (method, params). Output = JSON-RPC result.
        """
        raise NotImplementedError

    def initialize(self) -> Dict:
        """Initialize the MCP session."""
        result, _ = self.step('initialize')
        return result

    def list_tools(self) -> Dict:
        """List available tools."""
        result, _ = self.step('tools/list')
        return result

    def call_tool(self, name: str, **kwargs) -> Any:
        """Call a tool by name."""
        result, _ = self.step('tools/call', {'name': name, 'arguments': kwargs})
        return result

    def ping(self) -> Dict:
        """Ping the server."""
        result, _ = self.step('ping')
        return result


class HTTPTransport(TransportCoalgebra):
    """HTTP POST transport as a coalgebra."""

    def __init__(self, config=None, auth=None):
        super().__init__(config, auth)
        self._client = MCPClient(config, auth)
        self._state['transport'] = 'http_post'

    def step(self, method, params=None):
        self._state['request_count'] += 1
        if method == 'initialize' and not self._state['initialized']:
            result = self._client.initialize()
            self._state['initialized'] = True
        elif method == 'tools/list':
            result = self._client.list_tools()
        elif method == 'tools/call':
            result = self._client.call_tool(params['name'], params.get('arguments', {}))
        elif method == 'ping':
            result = self._client.ping()
        else:
            result = self._client._rpc(method, params)
        return result, self.state


class SSETransport(TransportCoalgebra):
    """SSE transport as a coalgebra."""

    def __init__(self, config=None, auth=None):
        super().__init__(config, auth)
        self._client = MCPSSEClient(config, auth)
        self._state['transport'] = 'sse'

    def step(self, method, params=None):
        self._state['request_count'] += 1
        if method == 'initialize' and not self._state['initialized']:
            result = self._client.initialize()
            self._state['initialized'] = True
        elif method == 'tools/list':
            result = self._client.list_tools()
        elif method == 'tools/call':
            result = self._client.call_tool(params['name'], params.get('arguments', {}))
        elif method == 'ping':
            result = self._client.ping()
        else:
            result = self._client._rpc(method, params)
        return result, self.state


class WSTransport(TransportCoalgebra):
    """WebSocket transport as a coalgebra."""

    def __init__(self, config=None, auth=None):
        super().__init__(config, auth)
        self._client = MCPWebSocketClient(config, auth)
        self._state['transport'] = 'websocket'

    def step(self, method, params=None):
        self._state['request_count'] += 1
        if method == 'initialize' and not self._state['initialized']:
            self._client.connect()
            result = self._client.initialize()
            self._state['initialized'] = True
        elif method == 'tools/list':
            result = self._client.list_tools()
        elif method == 'tools/call':
            result = self._client.call_tool(params['name'], params.get('arguments', {}))
        elif method == 'ping':
            result = self._client.ping()
        else:
            result = self._client._send_rpc(method, params)
        return result, self.state


def bisimilar(transport_a: TransportCoalgebra, transport_b: TransportCoalgebra,
              test_sequence: list, comparator=None) -> Dict:
    """
    Bisimulation check: verify two transports produce equivalent outputs
    for the same input sequence.

    Returns: {passed: bool, steps: [...], first_divergence: int|None}
    """
    if comparator is None:
        def comparator(a, b):
            # Compare structure, not exact values (timestamps etc differ)
            if type(a) != type(b):
                return False
            if isinstance(a, dict) and isinstance(b, dict):
                return set(a.keys()) == set(b.keys())
            return True

    results = []
    divergence = None

    for i, (method, params) in enumerate(test_sequence):
        out_a, state_a = transport_a.step(method, params)
        out_b, state_b = transport_b.step(method, params)
        equivalent = comparator(out_a, out_b)
        results.append({
            'step': i,
            'method': method,
            'transport_a': state_a.get('transport'),
            'transport_b': state_b.get('transport'),
            'equivalent': equivalent,
        })
        if not equivalent and divergence is None:
            divergence = i

    return {
        'passed': divergence is None,
        'steps': results,
        'first_divergence': divergence,
        'total_steps': len(test_sequence),
    }


# ═══════════════════════════════════════════════════════════════
# PILLAR 1: Client-Side Composition (Kleisli)
# ═══════════════════════════════════════════════════════════════

class ClientPipeline:
    """
    Client-side tool composition using Kleisli arrows.

    Chains multiple tool calls where output of one feeds the next.
    Tracks confidence and entropy client-side.

    Usage:
        client = SajhaClient(config, auth)
        pipeline = ClientPipeline(client)
        pipeline.add_step("yahoo_quote", param_map={"symbol": "$input.ticker"})
        pipeline.add_step("calc_sharpe", param_map={"returns": "$.history"})
        result = pipeline.execute({"ticker": "AAPL"})
        print(result['_composition']['confidence'])
    """

    def __init__(self, client):
        """
        Args:
            client: SajhaClient instance with execute_tool() method.
        """
        self._client = client
        self._steps: list = []

    def add_step(self, tool_name: str, param_map: Dict[str, str] = None,
                 static_params: Dict[str, Any] = None, output_key: str = None):
        """
        Add a step to the pipeline.

        param_map values:
          "$input.field"  → from original pipeline input
          "$.field"       → from previous step's output
          "literal"       → static value
        """
        self._steps.append({
            'tool_name': tool_name,
            'param_map': param_map or {},
            'static_params': static_params or {},
            'output_key': output_key or tool_name,
        })
        return self  # fluent API

    def execute(self, initial_input: Dict, max_entropy_bits: float = 3.0) -> Dict:
        """
        Execute the pipeline with Kleisli composition semantics.
        Each step's output feeds the next. Errors short-circuit.
        """
        import time
        import math

        result = {}
        prev_output = {}
        cumulative_confidence = 1.0
        trace = []
        total_duration = 0.0
        step_count = 0

        for step in self._steps:
            # Build params using lens-like projection
            params = dict(step['static_params'])
            for target, source in step['param_map'].items():
                if isinstance(source, str):
                    if source.startswith('$input.'):
                        params[target] = initial_input.get(source[7:], '')
                    elif source.startswith('$.'):
                        params[target] = prev_output.get(source[2:], '')
                    else:
                        params[target] = source
                else:
                    params[target] = source

            # Execute tool
            start = time.time()
            try:
                tool_result = self._client.execute_tool(step['tool_name'], **params)
                duration = (time.time() - start) * 1000
                step_confidence = 0.92  # default for API tools
                trace.append(f"✓ {step['tool_name']}: {duration:.0f}ms")
            except Exception as e:
                duration = (time.time() - start) * 1000
                trace.append(f"✗ {step['tool_name']}: {e}")
                result[step['output_key']] = {'error': str(e)}
                return {
                    **result,
                    '_composition': {
                        'confidence': 0.0,
                        'entropy_bits': float('inf'),
                        'error': str(e),
                        'trace': trace,
                        'steps_executed': step_count + 1,
                    }
                }

            total_duration += duration
            cumulative_confidence *= step_confidence
            step_count += 1

            # Store result
            result[step['output_key']] = tool_result
            prev_output = tool_result if isinstance(tool_result, dict) else {}

        # Calculate entropy
        if cumulative_confidence >= 1.0:
            entropy = 0.0
        elif cumulative_confidence <= 0.0:
            entropy = float('inf')
        else:
            p = cumulative_confidence
            entropy = -(p * math.log2(p) + (1 - p) * math.log2(1 - p))

        return {
            **result,
            '_composition': {
                'confidence': round(cumulative_confidence, 4),
                'entropy_bits': round(entropy, 3),
                'confidence_floor': round(2.0 ** (-entropy) if entropy < 100 else 0.0, 4),
                'duration_ms': round(total_duration, 1),
                'steps_executed': step_count,
                'trace': trace,
                'guard_passed': entropy <= max_entropy_bits,
            }
        }

    def __repr__(self):
        tools = ' >=> '.join(s['tool_name'] for s in self._steps)
        return f"ClientPipeline({tools})"
