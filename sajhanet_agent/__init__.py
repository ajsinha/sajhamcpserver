"""
The SAJHA Net agent: runs next to any MCP server (stdio or HTTP) and makes it a full SAJHA Net
participant (kind ``agent``): identity, gossip, catalog, signed calls, key verification and a small
export policy. Built on the reference library (:mod:`sajha.net.library`) and the protocol core
(``sajha/net/``) only; it never loads the SAJHA server (``tests/test_sajhanet_agent_boundary.py``).

    python -m sajhanet_agent --net acme-net --instance vendor-search --url https://agent.example:8790 \\
        --seed https://risk-eu.example:3002 --mcp-command "python my_server.py"

The guide is docs/clients/SAJHA Net Agent.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from sajhanet_agent.agent import Agent, AgentConfig, McpCatalog, make_client  # noqa: F401
from sajhanet_agent.mcp_client import (CallableMCPClient, HttpMCPClient, MCPClient, MCPError,  # noqa: F401
                                       MCPUnavailable, StdioMCPClient)
