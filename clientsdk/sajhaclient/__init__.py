"""
SAJHA MCP Server — Python Client SDK
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    pip install sajhaclient

Quick Start:

    from sajhaclient import SajhaClient, SajhaConfig

    # With API key
    client = SajhaClient(SajhaConfig(
        base_url="http://localhost:3002",
        api_key="sja_your_key_here"
    ))
    result = client.execute_tool("fmp_stock_quote", symbol="AAPL")

    # With username/password (JWT)
    client = SajhaClient(SajhaConfig(
        base_url="http://localhost:3002",
        username="admin",
        password="admin123"
    ))
    tools = client.list_tools()

Standard MCP client (official MCP Python SDK; pip install sajhaclient[mcp]):

    from sajhaclient import SajhaMCPClient

    async with SajhaMCPClient("http://localhost:3002", api_key="sja_xxx") as mcp:
        print(mcp.negotiated_protocol_version)
        tools = await mcp.list_all_tools()
"""

__version__ = "5.4.0"
__author__ = "Ashutosh Sinha"
__email__ = "ajsinha@gmail.com"

from sajhaclient.config import SajhaConfig
from sajhaclient.auth import AuthProvider, NoAuth, ApiKeyAuth, JWTAuth, OAuthAuth
from sajhaclient.client import SajhaClient
from sajhaclient.mcp_client import MCPClient, MCPSSEClient, MCPWebSocketClient
from sajhaclient.mcp_client import TransportCoalgebra, HTTPTransport, SSETransport, WSTransport
from sajhaclient.mcp_client import ClientPipeline, bisimilar
from sajhaclient.a2a_client import A2AClient
# Standard MCP client: importing it does NOT import the optional `mcp` SDK;
# that happens lazily when a SajhaMCPClient is constructed.
from sajhaclient.standard import SajhaMCPClient, SajhaMCPSyncClient
from sajhaclient.exceptions import (
    SajhaError, SajhaConnectionError, SajhaAuthError,
    SajhaPermissionError, SajhaNotFoundError, SajhaMCPError, SajhaA2AError,
)

__all__ = [
    # Config
    'SajhaConfig',
    # Clients
    'SajhaClient', 'MCPClient', 'MCPSSEClient', 'MCPWebSocketClient', 'A2AClient',
    'SajhaMCPClient', 'SajhaMCPSyncClient',
    # Auth
    'AuthProvider', 'NoAuth', 'ApiKeyAuth', 'JWTAuth', 'OAuthAuth',
    # Exceptions
    'SajhaError', 'SajhaConnectionError', 'SajhaAuthError',
    'SajhaPermissionError', 'SajhaNotFoundError', 'SajhaMCPError', 'SajhaA2AError',
]
