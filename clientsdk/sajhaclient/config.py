"""
SAJHA MCP Server — Client SDK Configuration

Configure the SDK once, use everywhere:

    from sajhaclient import SajhaConfig
    config = SajhaConfig(base_url="http://localhost:3002", api_key="sja_xxx")
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SajhaConfig:
    """
    Client SDK configuration.

    Args:
        base_url: SAJHA server URL (e.g., "http://localhost:3002")
        api_key: API key for authentication (sja_xxx format)
        jwt_token: Pre-obtained JWT token
        username: Username for JWT login
        password: Password for JWT login
        timeout: Request timeout in seconds
        max_retries: Number of retry attempts on transient errors
        verify_ssl: Whether to verify SSL certificates
        headers: Additional HTTP headers to send with every request
    """

    base_url: str = "http://localhost:3002"
    api_key: Optional[str] = None
    jwt_token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    verify_ssl: bool = True
    headers: dict = field(default_factory=dict)

    def __post_init__(self):
        # Remove trailing slash from base_url
        self.base_url = self.base_url.rstrip('/')

    @property
    def mcp_url(self) -> str:
        """MCP JSON-RPC endpoint."""
        return f"{self.base_url}/mcp"

    @property
    def mcp_sse_url(self) -> str:
        """MCP Streamable HTTP endpoint (GET for SSE, POST for JSON-RPC). Per 2025-11-25 spec."""
        return f"{self.base_url}/mcp"

    @property
    def a2a_url(self) -> str:
        """A2A protocol endpoint."""
        return f"{self.base_url}/a2a"

    @property
    def agent_card_url(self) -> str:
        """A2A agent card endpoint."""
        return f"{self.base_url}/.well-known/agent.json"
