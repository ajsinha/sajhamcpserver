# SAJHA MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io) server with a large
built-in tool catalog, a web UI, and the operational pieces a real deployment needs.
FastAPI, Python.

**Copyright © 2025–2030, Ashutosh Sinha** · ajsinha@gmail.com · [GitHub](https://github.com/ajsinha/sajhamcpserver)

---

## What it is

SAJHA (साझा, "shared") exposes tools and prompts to any MCP client: AI assistants,
agent frameworks, scripts. The catalog covers market data, central banks, public
statistics, SEC filings and investor relations, web and document search, analytics
(DuckDB, OLAP, SQL) and financial calculators. The live list is whatever the server has
loaded: ask `tools/list`, or open the Tools page.

It is a **dual-era** MCP server: stateless **2026-07-28** and session-based
**2025-11-25** (plus 2025-06-18, 2025-03-26 and 2024-11-05) on the same `/mcp`
endpoint, chosen per request. Every push runs the official MCP conformance suite against
a live server for both versions ([workflow](.github/workflows/mcp-conformance.yml);
results in the [compliance reports](docs/protocol/)).

## Why use it

- **Protocol, done properly.** `server/discover`, streamed progress and cancellation,
  `subscriptions/listen`, Multi Round-Trip Requests, the tasks extension, MCP Apps and
  `x-mcp-header` on 2026-07-28; sessions, SSE and WebSocket for older clients.
- **OAuth 2.1 when you need it.** Off by default; optional or required on `/mcp`, with a
  built-in authorization server (PKCE, client ID metadata documents, rotating refresh
  tokens) or your own identity provider. API keys and JWTs keep working.
- **Compose and generate tools.** The composite builder designs pipelines of existing
  tools with confidence tracking; a saved composite is registered as a tool and callable
  over MCP (see the [Composition Framework](docs/architecture/Composition%20Framework.md)).
  MCP Studio's generators turn a Python function, a REST call,
  a SQL query, a script, Power BI or DAX, LiveLink or SharePoint into a tool, and deploy
  loads it into the running server (see the
  [MCP Studio User Guide](docs/studio/MCP%20Studio%20User%20Guide.md)).
- **Operations built in.** Users, roles and API keys; per-tool output cache;
  per-provider circuit breakers; Prometheus metrics, OpenTelemetry tracing, a usage and
  cost dashboard and alerts ([Observability](docs/architecture/Observability.md)); health
  probes; audit log; multi-tenancy;
  plugins; tool versioning; background execution with webhook, Kafka or file delivery.
- **AI-aware.** Natural-language tool search (lexical by default, embeddings optional)
  and an LLM gateway for Anthropic, OpenAI, AWS Bedrock, Together.ai, Ollama and Azure
  OpenAI.
- **Runs anywhere.** SQLite or PostgreSQL; configs and prompts on local disk, S3, Azure
  Blob or GCS with hot reload; deployment recipes for AWS, Hetzner and bare metal.

How SAJHA compares with MCP frameworks, gateways and hosted platforms, including where
they are stronger, is on the server's **How it compares** page (`/comparison`, under Help),
with a dated source for every verdict; its data lives in `sajha/web/competitive.py`.

## Quick start

```bash
git clone https://github.com/ajsinha/sajhamcpserver.git
cd sajhamcpserver
pip install -r requirements.txt
python run_server.py
```

Open **http://localhost:3002** and sign in as `admin` / `admin123`; a banner asks you to
change that password (`/account/password`). The JWT and session secrets are generated on first
start into `data/secrets/` (git-ignored); see the
[Security Model](docs/security/Security%20Model.md) before exposing the server. MCP clients connect to `http://localhost:3002/mcp`.

From Python, with the standard client (the official MCP SDK under a SAJHA wrapper):

```python
# pip install './clientsdk[mcp]'
from sajhaclient import SajhaMCPSyncClient

with SajhaMCPSyncClient("http://localhost:3002") as mcp:
    print(mcp.negotiated_protocol_version)    # 2026-07-28
    result = mcp.call_tool("calc_percentage_change", {"old_value": 80, "new_value": 100})
```

From a terminal, `pip install './clientsdk[cli]'` gives the `sajha` command (`sajha login`,
`sajha tools call ...`, `sajha ask "..."`), and `python run_server.py --stdio` serves MCP to
desktop clients such as Claude Desktop and Claude Code: see [Command Line](docs/clients/Command%20Line.md).

More in the [Quick Start](docs/getting-started/Quick%20Start.md).

## Documentation

Start with the [documentation index](docs/README.md), or
[How SAJHA Fits Together](docs/getting-started/How%20SAJHA%20Fits%20Together.md), the
map that names the one document owning each topic. Also: [CHANGELOG](CHANGELOG.md),
[GLOSSARY](GLOSSARY.md), [deployment recipes](deployment/README.md).

The current version is `app.version` in `config/application.yml`.

## License

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
