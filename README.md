# SAJHA MCP Server

**SAJHA** (साझा, "shared") is one governed catalog of tools that every MCP client and
agent shares. Market data, central banks, public statistics, filings, search, analytics
and financial calculators, plus the tools you build in the browser, tools a model runs,
and the tools of other MCP servers SAJHA proxies, all live in one catalog on one `/mcp`
endpoint, under one set of credentials, roles, policy, sandboxing and audit. A client, an
agent or SAJHA's own intelligence layer composes them on demand into whatever the
question needs. Several SAJHA servers can form a **SAJHA Net** and share their tools while
each keeps its own data, rules, models and memory. FastAPI, Python.

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
python run_sajha_web.py
```

Open **http://localhost:3002**, sign in as `admin` / `admin123` and change the password
when the banner asks. The shipped settings suit a development machine or a trusted
intranet (the test admin switch is on, credentials are stored as given); the
[Quick Start](docs/getting-started/Quick%20Start.md) says what to change first. MCP clients connect to `http://localhost:3002/mcp`; desktop clients
such as Claude Desktop and Claude Code can run `python run_sajha_web.py --stdio` instead.
A first MCP call, a first question to Ask SAJHA and the Python client are in the Quick
Start.

## What's in the box

The live tool list is whatever the server has loaded: ask `tools/list`, or open the
Tools page.

**Serve tools to any MCP client.** Both spec eras on one `/mcp` endpoint, chosen per
request: stateless 2026-07-28 (streaming, `subscriptions/listen`, Multi Round-Trip
Requests, tasks, MCP Apps, `x-mcp-header`) and session-based 2025-11-25 with the older
versions, over Streamable HTTP, SSE, WebSocket and stdio. The official conformance suite
runs against a live server for both eras on every push to `develop` and `main`
([workflow](.github/workflows/mcp-conformance.yml)).
→ [MCP Protocol Guide](docs/protocol/MCP%20Protocol%20Guide.md)

**Govern every call.** OAuth 2.1 on `/mcp` (built-in authorization server or your identity
provider), users, roles and API keys scoped to the tools they may call, nothing for
anonymous callers by default, and declarative policy rules on every path a tool runs
through: deny, human approval, argument constraints, quotas, PII redaction and
prompt-injection screening. Every audit record is hash-chained and signed, and can be
streamed to a SIEM. User code runs in a sandbox (subprocess, bubblewrap, nsjail or Docker).
The console offers single sign-on with OpenID Connect beside passwords, the administrators'
users and keys files, and API keys.
→ [Security Model](docs/security/Security%20Model.md) ·
[Policy and Audit](docs/architecture/Policy%20and%20Audit.md) ·
[OAuth Guide](docs/protocol/OAuth%20Guide.md) · [Sandbox](docs/architecture/Sandbox.md)

**Build tools.** MCP Studio turns a Python function, a REST call, a SQL query, a script,
Power BI, LiveLink, SharePoint or an OLAP dataset into a tool and deploys it into the
running server. Import an API turns an OpenAPI, Swagger or GraphQL description into a
reviewed set of tools; Describe a tool has a model propose one from a sentence, then
checks and tests it before an administrator approves the deploy. LLM tools are tools
whose work a model does (summarise, classify, extract, an assistant over other tools),
configured like any tool and run as the caller. Composite tools chain tools with
confidence tracking, and proxied MCP servers (paste a Claude Desktop or Cursor
`mcpServers` file) put other servers' tools in the same catalog under the same governance.
→ [MCP Studio User Guide](docs/studio/MCP%20Studio%20User%20Guide.md) ·
[API Import](docs/architecture/API%20Import.md) ·
[Tool Generation](docs/architecture/Tool%20Generation.md) ·
[LLM Tools](docs/architecture/LLM%20Tools.md) ·
[Composition Framework](docs/architecture/Composition%20Framework.md) ·
[Federation](docs/architecture/Federation.md)

**Reach your data and accounts.** Data connectors put PostgreSQL, MySQL, SQL Server,
Oracle, Snowflake, BigQuery, Databricks and vector stores behind read-only tools with a
statement guard, limits and column masking. Connected accounts let each user link
GitHub, Slack, Google, Microsoft 365 and others once, so tools act as that user.
→ [Data Connectors](docs/architecture/Data%20Connectors.md) ·
[Connected Accounts](docs/architecture/Connected%20Accounts.md)

**Ask.** The intelligence layer puts LLM providers and models behind one package with an
OpenAI-style interface, aliases, budgets and policy, with an offline mock model as the
default so it works with no keys. **Ask SAJHA** is the chat page that shows the tools it
uses as it uses them, with planners you configure as files, per-user conversation memory
and search over the guides and your own documents. SAJHA can also serve its models as an
OpenAI-compatible endpoint (opt-in). The **Python Playground** runs Python in your browser and calls tools with
your own permissions; the `sajha` command line and the Python client SDK work from outside.
→ [Intelligence Layer](docs/architecture/Intelligence%20Layer.md) ·
[Python Playground](docs/getting-started/Python%20Playground.md) ·
[Command Line](docs/clients/Command%20Line.md) ·
[Client SDK Guide](docs/clients/Client%20SDK%20Guide.md)

**Share tools between servers.** SAJHA Net joins SAJHA servers into named nets: signed
requests on the normal port, gossip membership, a CA SAJHA runs (or first-use keys),
remote tools under one name with fallback between hosts, the caller's identity on every
call, data residency rules, linked audit and the console pages to watch it. Any other MCP
server can join through the SAJHA Net agent or be sponsored by a SAJHA server. A server
with no peers is a net of one; the whole feature is off unless `sajhanet.enabled`.
→ [SAJHA Net](docs/architecture/SAJHA%20Net.md) ·
[SAJHA Net Protocol](docs/protocol/SAJHA%20Net%20Protocol.md) ·
[SAJHA Net Agent](docs/clients/SAJHA%20Net%20Agent.md)

**Automate and keep tools honest.** Workflows run DAGs of tools, composites and Ask SAJHA
steps on schedules, signed webhooks, file arrivals or events, durably, as their owner.
Tool test cases replay recorded HTTP offline in CI, a linter checks every schema, health
probes watch live services, evals score Ask SAJHA, and tool versions roll out by canary
with automatic rollback.
→ [Workflows](docs/architecture/Workflows.md) · [Tool Quality](docs/architecture/Tool%20Quality.md)

**Operate.** Several workers or hosts over a shared state store (Redis or the database);
Prometheus metrics, OpenTelemetry traces, a usage and cost dashboard and alert rules;
per-tool caching and per-provider circuit breakers; local, S3, Azure Blob or GCS storage
with hot reload; SQLite or PostgreSQL from one schema file an operator applies; a console
that works on phones; a Helm chart and Kustomize manifests for Kubernetes, and recipes
for AWS, Hetzner, bare metal and a three-instance SAJHA Net demo.
→ [Scaling and State](docs/architecture/Scaling%20and%20State.md) ·
[Observability](docs/architecture/Observability.md) ·
[Database Setup](docs/getting-started/Database%20Setup.md) ·
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
