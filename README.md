# SAJHA MCP Server

**SAJHA** (साझा, "shared") is one governed catalog of tools that every MCP client and
agent shares. Market data, central banks, public statistics, filings, search, analytics
and financial calculators, plus the tools you build in the browser and the tools of other
MCP servers you put behind it, all live in one catalog on one `/mcp` endpoint, under one
set of credentials, roles, sandboxing and audit. A client, an agent or SAJHA's own
intelligence layer composes them on demand into whatever the question needs.
FastAPI, Python.

**Copyright © 2025–2030, Ashutosh Sinha** · ajsinha@gmail.com · [GitHub](https://github.com/ajsinha/sajhamcpserver)

## The constellation

Open the server and its catalog is drawn as a night sky: one star per tool the server
has loaded, clustered by provider group. Ask SAJHA a question (`/ask`) and the same sky
lights the tools it shortlists and draws a link to each one it calls, with the result
beside it. That is the idea in one picture: tools are not wired into pipelines ahead of
time, they are a shared sky that each question draws its own path across.

## Quick start

```bash
git clone https://github.com/ajsinha/sajhamcpserver.git
cd sajhamcpserver
pip install -r requirements.txt
python run_server.py
```

Open **http://localhost:3002**, sign in as `admin` / `admin123` and change the password
when the banner asks. MCP clients connect to `http://localhost:3002/mcp`; desktop clients
such as Claude Desktop and Claude Code can run `python run_server.py --stdio` instead.
The secrets, a first MCP call and the Python client are in the
[Quick Start](docs/getting-started/Quick%20Start.md).

## What's in the box

The live tool list is whatever the server has loaded: ask `tools/list`, or open the
Tools page.

**Serve tools to any MCP client.** Both spec eras on one `/mcp` endpoint, chosen per
request: stateless 2026-07-28 (streaming, `subscriptions/listen`, Multi Round-Trip
Requests, tasks, MCP Apps, `x-mcp-header`) and session-based 2025-11-25 with the older
versions. Streamable HTTP, SSE, WebSocket and stdio. The official conformance suite runs
against a live server for both eras on every push to `develop` and `main`
([workflow](.github/workflows/mcp-conformance.yml)).
→ [MCP Protocol Guide](docs/protocol/MCP%20Protocol%20Guide.md)

**Govern.** OAuth 2.1 on `/mcp` (off, optional or required; built-in authorization server
or your identity provider), users and roles, API keys scoped to the tools they may call,
Origin checks and rate limits, an audit log, and a sandbox for user code (subprocess,
bubblewrap, nsjail or Docker).
→ [Security Model](docs/security/Security%20Model.md) ·
[OAuth Guide](docs/protocol/OAuth%20Guide.md) · [Sandbox](docs/architecture/Sandbox.md)

**Build and compose.** MCP Studio turns a Python function, a REST call, a SQL query, a
script, Power BI, LiveLink, SharePoint or an OLAP dataset into a tool and deploys it into
the running server. Composite tools chain tools with confidence tracking. Federation puts
other MCP servers' tools in the same catalog, behind the same governance and approval.
→ [MCP Studio User Guide](docs/studio/MCP%20Studio%20User%20Guide.md) ·
[Composition Framework](docs/architecture/Composition%20Framework.md) ·
[Federation](docs/architecture/Federation.md)

**Ask.** The intelligence layer: LLM providers and models behind one gateway with aliases,
budgets and policy, an offline mock model as the default so it works with no keys, and
`/api/ai/ask`. **Ask SAJHA** is the chat page that shows the tools it uses as it uses
them. The **Python Playground** runs Python in your browser and calls tools with your own
permissions. The `sajha` command line (`pip install './clientsdk[cli]'`) and the Python
client SDK work from outside.
→ [Intelligence Layer](docs/architecture/Intelligence%20Layer.md) ·
[Python Playground](docs/getting-started/Python%20Playground.md) ·
[Command Line](docs/clients/Command%20Line.md) ·
[Client SDK Guide](docs/clients/Client%20SDK%20Guide.md)

**Operate.** Several workers or hosts over a shared state store (Redis or the database);
Prometheus metrics, OpenTelemetry traces, a usage and cost dashboard and alert rules;
per-tool caching and per-provider circuit breakers; local, S3, Azure Blob or GCS storage
with hot reload; SQLite or PostgreSQL; a Helm chart and Kustomize manifests for
Kubernetes, and recipes for AWS, Hetzner and bare metal.
→ [Scaling and State](docs/architecture/Scaling%20and%20State.md) ·
[Observability](docs/architecture/Observability.md) ·
[Kubernetes Deployment](docs/getting-started/Kubernetes%20Deployment.md) ·
[deployment recipes](deployment/README.md)

How SAJHA compares with MCP frameworks, gateways and hosted platforms, including where
they are stronger, is on the server's **How it compares** page (`/comparison`), with a
dated source for every verdict.

## Documentation

Start with [How SAJHA Fits Together](docs/getting-started/How%20SAJHA%20Fits%20Together.md),
the map that names the one document owning each topic, then the
[documentation index](docs/README.md) and its reading order. Also:
[CHANGELOG](CHANGELOG.md) · [GLOSSARY](GLOSSARY.md). The same guides are served inside the
app under **Help**.

The current version is `app.version` in `config/application.yml`.

## License

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
