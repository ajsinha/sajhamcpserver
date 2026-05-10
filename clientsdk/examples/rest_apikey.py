#!/usr/bin/env python3
"""
Example: SAJHA REST Client with API Key Authentication

The simplest way to connect. Just provide your API key.
"""

from sajhaclient import SajhaClient, SajhaConfig

# ── Configuration ────────────────────────────────────────────────
config = SajhaConfig(
    base_url="http://localhost:3002",
    api_key="sja_your_api_key_here",   # Get this from Admin → API Keys
)

client = SajhaClient(config)

# ── Health Check ─────────────────────────────────────────────────
health = client.health()
print(f"Server: {health['app_name']} v{health['version']}")
print(f"Status: {health['status']}")
print(f"Tools:  {health['tools_count']}")

# ── List Tools ───────────────────────────────────────────────────
tools = client.list_tools()
print(f"\nAvailable tools ({len(tools)}):")
for t in tools[:10]:
    name = t['name'] if isinstance(t, dict) else t
    desc = t.get('description', '')[:60] if isinstance(t, dict) else ''
    print(f"  • {name}: {desc}")

# ── Execute a Tool ───────────────────────────────────────────────
print("\n--- Executing fmp_stock_quote ---")
result = client.execute_tool("fmp_stock_quote", symbol="AAPL")
print(f"Result: {result}")

# ── Execute Another Tool ─────────────────────────────────────────
print("\n--- Executing wikipedia_search ---")
result = client.execute_tool("wikipedia_search", query="Python programming language")
print(f"Result keys: {list(result.get('result', {}).keys()) if 'result' in result else result.keys()}")
