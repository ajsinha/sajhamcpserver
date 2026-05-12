"""
SAJHA MCP Server — Client SDK Core REST Client

The SajhaClient is the primary interface for interacting with
the SAJHA MCP Server via its REST API.

    from sajhaclient import SajhaClient, SajhaConfig, ApiKeyAuth

    config = SajhaConfig(base_url="http://localhost:3002")
    auth = ApiKeyAuth("sja_your_key")
    client = SajhaClient(config, auth=auth)

    # Execute a tool
    result = client.execute_tool("wikipedia_search", query="Python programming")

    # List all tools
    tools = client.list_tools()

    # Get health status
    health = client.health()
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error
import logging
from typing import Optional, Dict, Any, List

from sajhaclient.config import SajhaConfig
from sajhaclient.auth import AuthProvider, NoAuth, ApiKeyAuth, JWTAuth
from sajhaclient.exceptions import (
    SajhaError, SajhaConnectionError, SajhaAuthError,
    SajhaPermissionError, SajhaNotFoundError, SajhaValidationError,
    SajhaServerError,
)

logger = logging.getLogger(__name__)


class SajhaClient:
    """
    REST API client for SAJHA MCP Server.

    Provides methods for:
      - Tool discovery and execution
      - User and API key management (admin)
      - Reporting and analytics
      - Health monitoring
    """

    def __init__(self, config: Optional[SajhaConfig] = None, auth: Optional[AuthProvider] = None):
        """
        Initialize the client.

        Args:
            config: Server configuration (URL, timeouts, etc.)
            auth: Authentication provider (ApiKeyAuth, JWTAuth, OAuthAuth)

        Shortcuts — if config has credentials, auth is created automatically:
            SajhaClient(SajhaConfig(base_url="...", api_key="sja_xxx"))
            SajhaClient(SajhaConfig(base_url="...", username="admin", password="pass"))
        """
        self.config = config or SajhaConfig()
        self._auth = auth

        # Auto-create auth from config if not provided
        if not self._auth:
            if self.config.api_key:
                self._auth = ApiKeyAuth(self.config.api_key)
            elif self.config.jwt_token:
                self._auth = JWTAuth.from_token(self.config.jwt_token)
            elif self.config.username and self.config.password:
                self._auth = JWTAuth(self.config.base_url, self.config.username, self.config.password)
            else:
                self._auth = NoAuth()

    # ── HTTP Transport ───────────────────────────────────────────

    def _request(self, method: str, path: str, body: Optional[Dict] = None,
                 params: Optional[Dict] = None) -> Any:
        """Make an HTTP request with auth, retries, and error handling."""
        self._auth.refresh_if_needed()

        url = f"{self.config.base_url}{path}"
        if params:
            url += '?' + urllib.parse.urlencode(params)

        headers = {
            'Accept': 'application/json',
            'User-Agent': 'sajhaclient/3.0.0',
            **self.config.headers,
            **self._auth.get_headers(),
        }

        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                    response_body = resp.read().decode('utf-8')
                    if response_body:
                        return json.loads(response_body)
                    return {}
            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8', errors='replace')
                if e.code == 401:
                    raise SajhaAuthError(f"Authentication failed: {error_body}")
                elif e.code == 403:
                    raise SajhaPermissionError(f"Permission denied: {error_body}")
                elif e.code == 404:
                    raise SajhaNotFoundError(f"Not found: {path}")
                elif e.code == 400:
                    raise SajhaValidationError(f"Invalid request: {error_body}")
                elif e.code >= 500:
                    last_error = SajhaServerError(f"Server error {e.code}: {error_body}")
                    if attempt < self.config.max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    raise last_error
                else:
                    raise SajhaError(f"HTTP {e.code}: {error_body}")
            except urllib.error.URLError as e:
                last_error = SajhaConnectionError(f"Cannot connect to {self.config.base_url}: {e.reason}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise last_error
            except json.JSONDecodeError:
                logger.debug("Non-JSON response received", exc_info=True)
                return {}

        raise last_error or SajhaError("Request failed after retries")

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        return self._request('GET', path, params=params)

    def _post(self, path: str, body: Optional[Dict] = None) -> Any:
        return self._request('POST', path, body=body)

    def _delete(self, path: str) -> Any:
        return self._request('DELETE', path)

    # ── Health ───────────────────────────────────────────────────

    def health(self) -> Dict:
        """Get server health status, tool count, version."""
        return self._get('/health')

    # ── Tool Discovery ───────────────────────────────────────────

    def list_tools(self) -> List[Dict]:
        """Get list of all available tools with names and descriptions."""
        data = self._get('/api/tools/list')
        return data.get('tools', [])

    def get_tool_schema(self, tool_name: str) -> Dict:
        """Get the full schema (input/output) for a specific tool."""
        return self._get(f'/api/tools/{tool_name}/schema')

    # ── Tool Execution ───────────────────────────────────────────

    def execute_tool(self, tool_name: str, **arguments) -> Dict:
        """
        Execute a tool by name with the given arguments.

        Args:
            tool_name: Name of the tool to execute
            **arguments: Tool-specific arguments

        Returns:
            Tool execution result

        Example:
            result = client.execute_tool("wikipedia_search", query="Python")
            result = client.execute_tool("fmp_stock_quote", symbol="AAPL")
        """
        return self._post('/api/tools/execute', {
            'tool': tool_name,
            'arguments': arguments,
        })

    # ── Prompts ──────────────────────────────────────────────────

    def list_prompts(self) -> List[Dict]:
        """Get list of all available prompts."""
        data = self._get('/api/prompts/list')
        return data.get('prompts', [])

    def get_prompt(self, prompt_name: str) -> Dict:
        """Get a specific prompt by name."""
        return self._get(f'/api/prompts/{prompt_name}')

    # ── Reports ──────────────────────────────────────────────────

    def report_overview(self, period: str = '24h') -> Dict:
        """Get usage overview — total calls, error rate, active users."""
        return self._get('/api/reports/overview', {'period': period})

    def report_tools_usage(self, period: str = '7d') -> Dict:
        """Get per-tool usage statistics."""
        return self._get('/api/reports/tools/usage', {'period': period})

    def report_tool_detail(self, tool_name: str, period: str = '30d') -> Dict:
        """Get detailed stats for a specific tool (p50/p95/p99, errors)."""
        return self._get(f'/api/reports/tools/{tool_name}/detail', {'period': period})

    def report_user_activity(self, period: str = '30d') -> Dict:
        """Get per-user activity statistics."""
        return self._get('/api/reports/users/activity', {'period': period})

    def report_heatmap(self, days: int = 30, tool: Optional[str] = None) -> Dict:
        """Get usage heatmap (day-of-week × hour)."""
        params = {'days': days}
        if tool:
            params['tool'] = tool
        return self._get('/api/reports/heatmap', params)

    def report_audit(self, limit: int = 100, action: Optional[str] = None) -> Dict:
        """Get audit log entries."""
        params = {'limit': limit}
        if action:
            params['action'] = action
        return self._get('/api/reports/audit', params)

    # ── Admin: Users ─────────────────────────────────────────────

    def admin_list_users(self) -> List[Dict]:
        """List all users (admin only)."""
        data = self._get('/api/admin/users')
        return data.get('users', [])

    def admin_create_user(self, user_id: str, user_name: str, password: str,
                          roles: Optional[List[str]] = None, email: str = '') -> Dict:
        """Create a new user (admin only)."""
        return self._post('/api/admin/users/create', {
            'user_id': user_id,
            'user_name': user_name,
            'password': password,
            'roles': roles or ['user'],
            'email': email,
        })

    def admin_enable_user(self, user_id: str) -> Dict:
        return self._post(f'/api/admin/users/{user_id}/enable')

    def admin_disable_user(self, user_id: str) -> Dict:
        return self._post(f'/api/admin/users/{user_id}/disable')

    def admin_delete_user(self, user_id: str) -> Dict:
        return self._delete(f'/api/admin/users/{user_id}/delete')

    # ── Admin: Tools ─────────────────────────────────────────────

    def admin_enable_tool(self, tool_name: str) -> Dict:
        return self._post(f'/api/admin/tools/{tool_name}/enable')

    def admin_disable_tool(self, tool_name: str) -> Dict:
        return self._post(f'/api/admin/tools/{tool_name}/disable')

    def admin_get_tool_config(self, tool_name: str) -> Dict:
        return self._get(f'/api/admin/tools/{tool_name}/config')

    def admin_save_tool_config(self, tool_name: str, config: Dict) -> Dict:
        return self._post(f'/api/admin/tools/{tool_name}/config', config)

    def admin_reload_tools(self) -> Dict:
        return self._post('/api/admin/tools/reload')

    # ── Auth Info ────────────────────────────────────────────────

    @property
    def auth_type(self) -> str:
        """Return current auth method name."""
        return self._auth.auth_type

    def login(self, username: str, password: str) -> str:
        """
        Login and obtain a JWT token. Updates the client's auth.

        Returns:
            JWT token string
        """
        self._auth = JWTAuth(self.config.base_url, username, password)
        return self._auth.token
