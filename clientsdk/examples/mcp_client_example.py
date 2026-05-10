#!/usr/bin/env python3
"""
Example: SAJHA MCP Protocol Client

Full MCP (Model Context Protocol) client using JSON-RPC 2.0.
This is how AI agents connect to SAJHA.
"""

from sajhaclient import SajhaConfig
from sajhaclient.mcp_client import MCPClient

# ── Connect ──────────────────────────────────────────────────────
config = SajhaConfig(
    base_url="http://localhost:3002",
    api_key="sja_your_key",  # or username/password
)
mcp = MCPClient(config)

# ── Initialize MCP Session ───────────────────────────────────────
caps = mcp.initialize(client_name="my-agent", client_version="1.0")
print(f"Server: {mcp.server_info}")
print(f"Capabilities: {list(mcp.capabilities.keys())}")

# ── Ping ─────────────────────────────────────────────────────────
pong = mcp.ping()
print(f"Ping: {pong}")

# ── List Tools ───────────────────────────────────────────────────
tools = mcp.list_tools()
print(f"\nMCP tools: {len(tools)}")
for t in tools[:5]:
    print(f"  • {t['name']}: {t.get('description', '')[:50]}")

# ── Call a Tool ──────────────────────────────────────────────────
print("\n--- Calling fmp_stock_quote via MCP ---")
result = mcp.call_tool("fmp_stock_quote", symbol="TSLA")
print(f"Result: {result}")

# ── List Prompts ─────────────────────────────────────────────────
prompts = mcp.list_prompts()
print(f"\nPrompts: {len(prompts)}")

# ── List Resources ───────────────────────────────────────────────
resources = mcp.list_resources()
print(f"Resources: {len(resources)}")

# ── Auto-complete ────────────────────────────────────────────────
suggestions = mcp.complete("fmp_stock_quote", "symbol", "AA")
print(f"Completions for 'AA': {suggestions}")

# ── Set Log Level ────────────────────────────────────────────────
mcp.set_log_level("DEBUG")
print("Server log level set to DEBUG")
