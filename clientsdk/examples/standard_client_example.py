#!/usr/bin/env python3
"""
Example: SAJHA standard MCP client (official MCP Python SDK under the hood)

    pip install 'sajhaclient[mcp]'
    python standard_client_example.py [base_url]

SajhaMCPClient speaks Streamable HTTP to <base_url>/mcp and lets the SDK
negotiate the protocol era automatically: MCP 2026-07-28 (server/discover)
on new servers, the initialize handshake (2025-11-25 and earlier) otherwise.
The same object also exposes SAJHA extras: .rest, .a2a and .websocket().
"""

import asyncio
import os
import sys

from sajhaclient import SajhaMCPClient, SajhaMCPSyncClient

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SAJHA_URL", "http://localhost:3002")

# Credentials: X-API-Key (api_key=...) or Authorization: Bearer (jwt_token=... /
# username+password). SAJHA executes tools/call only for authenticated sessions.
AUTH = {}
if os.environ.get("SAJHA_API_KEY"):
    AUTH["api_key"] = os.environ["SAJHA_API_KEY"]
elif os.environ.get("SAJHA_JWT"):
    AUTH["jwt_token"] = os.environ["SAJHA_JWT"]
else:
    AUTH.update(username=os.environ.get("SAJHA_USER", "admin"),
                password=os.environ.get("SAJHA_PASSWORD", "admin123"))


async def main() -> None:
    async with SajhaMCPClient(BASE_URL, **AUTH) as client:
        # ── Negotiated session ───────────────────────────────────
        print(f"Connected: {client}")
        print(f"Negotiated MCP version: {client.negotiated_protocol_version}")
        if client.server_info:
            print(f"Server: {client.server_info.name} {client.server_info.version}")

        # ── Tools ────────────────────────────────────────────────
        tools = await client.list_all_tools()          # follows pagination
        print(f"\n{len(tools)} tools, e.g. {[t.name for t in tools[:5]]}")

        result = await client.call_tool("calc_percentage_change", {"old_value": 100, "new_value": 125})
        print(f"calc_percentage_change -> is_error={result.is_error}: "
              f"{result.structured_content or [c.text for c in result.content if hasattr(c, 'text')]}")

        # ── Prompts ──────────────────────────────────────────────
        prompts = await client.list_all_prompts()
        print(f"\nPrompts: {[p.name for p in prompts]}")
        prompt = await client.get_prompt("bug_diagnosis", {
            "bug_description": "Average of an empty list crashes",
            "error_message": "ZeroDivisionError: division by zero",
            "code": "def avg(xs):\n    return sum(xs) / len(xs)",
            "language": "python",
        })
        print(f"bug_diagnosis -> {len(prompt.messages)} message(s)")

        # ── Resources ────────────────────────────────────────────
        resources = await client.list_all_resources()
        print(f"\nResources: {[str(r.uri) for r in resources]}")
        if resources:
            contents = await client.read_resource(str(resources[0].uri))
            print(f"{resources[0].uri}: {len(contents.contents)} content item(s)")

        # ── SAJHA extras ─────────────────────────────────────────
        print(f"\nHealth: {(await client.health()).get('status')}")
        print(f"Schema keys: {list((await client.tool_schema('calc_percentage_change')).keys())}")
        print(f"A2A agent: {client.a2a.get_agent_card().get('name')}")   # blocking REST/A2A clients
        # client.rest.report_tools_usage('7d'), client.rest.admin_list_users(), ...
        # ws = client.websocket(); ws.connect(); ws.initialize()   # needs `pip install websockets`

        # Anything not wrapped: the underlying mcp.Client
        _ = client.sdk


def sync_demo() -> None:
    """The same API without asyncio (runs the async client on a background loop)."""
    with SajhaMCPSyncClient(BASE_URL, **AUTH) as client:
        print(f"\n[sync] MCP {client.negotiated_protocol_version}, "
              f"{len(client.list_tools().tools)} tools on first page")


if __name__ == "__main__":
    asyncio.run(main())
    sync_demo()
