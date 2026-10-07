# How SAJHA Fits Together

This is the map of SAJHA. It says what each part is for, how the parts connect, and
**which single document owns the details of each one**. It does not repeat those
details: each section ends with an **Authority** line pointing to the document that
does. If this map and an authority ever disagree, the authority is right and this map
is the one to fix.

---

## 1. What SAJHA is

SAJHA (साझा, "shared") is a [Model Context Protocol](https://modelcontextprotocol.io)
server: one governed catalog of tools that every MCP client and agent shares, composed
on demand. The catalog holds the built-in data and utility tools (market data, central
banks, public statistics, filings, search, analytics, calculators), the tools built in
MCP Studio or composed from others, and the tools of other MCP servers federated behind
SAJHA, plus reusable prompts. Any MCP client (an AI assistant, an agent framework, a
script, a desktop app over stdio) can discover and call them, and SAJHA's own
intelligence layer can answer a question with them. Around that core sit what running
it for real needs: a web console, users, roles, API keys and OAuth, a sandbox for user
code, caching and circuit breakers, observability, shared state for several workers,
and pluggable storage.

**Authority:** [README](../../README.md) (first contact); [Architecture](../architecture/Architecture.md).

---

## 2. The process at a glance

```
  MCP clients              programs / agents            people (browser)
       │                          │                            │
  /mcp (both eras)          /api/* REST, /a2a,           console, /ask, /playground,
  /mcp/sse, /mcp/ws         /api/ai/ask                  /help, /glossary, /comparison
  stdio (desktop clients)   (JWT or API key)             (session cookie; help is public)
       │                          │                            │
       └──── Origin check · authorization (API key · JWT · OAuth 2.1) ────┘
                                  │
     MCPHandler (+ 2026-07-28 envelope) · REST routes · page routes · intelligence layer
                                  │                                   (LLM gateway)
   ToolsRegistry ◄─ tool configs              PromptsRegistry ◄─ prompt configs
   composite tools · Studio tools · plugins · federated tools · versions · tenants
                                  │
   cache → circuit breaker → tool → provider API | sandbox | upstream MCP server
                                  │
   storage backend (local | S3 | Azure | GCS)        database (SQLite | PostgreSQL)
   state store (memory | Redis | database)           change bus → listeners
   metrics · traces · usage ledger · alerts
```

One process by default. Cross-request state (sessions, tasks, OAuth codes, rate limits)
lives in the state store: process memory by default, Redis or the database for several
workers ([Scaling and State](../architecture/Scaling%20and%20State.md)).

**Authority:** [Architecture](../architecture/Architecture.md).

---

## 3. Speaking MCP

| Concern | What it is | Authority |
|---|---|---|
| Protocol versions and eras | Stateless 2026-07-28 and session-based 2025-11-25 (and older) on one `/mcp` endpoint, chosen per request | [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md) |
| Evidence of compliance | Requirement tables, conformance-suite results, known limits | [MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md), [MCP 2025-11-25 Compliance](../protocol/MCP%202025-11-25%20Compliance.md) |
| Streaming, `subscriptions/listen`, MRTR, tasks | The 2026-07-28 features | MCP Protocol Guide §2 |
| OAuth 2.1 on `/mcp` | Modes off / optional / required; built-in authorization server or an external IdP | [OAuth Guide](../protocol/OAuth%20Guide.md) |
| MCP Apps and `x-mcp-header` | Interactive tool views; arguments mirrored into headers | [MCP Apps and Headers Guide](../protocol/MCP%20Apps%20and%20Headers%20Guide.md) |
| MCP over stdio | `run_server.py --stdio` / `sajha serve --stdio` for desktop clients; one caller per process | [Command Line](../clients/Command%20Line.md) |
| Every HTTP endpoint | REST, MCP, OAuth, A2A, AI, federation, playground and observability routes | [API Reference](../protocol/API%20Reference.md) |
| A2A | The agent card and the A2A task lifecycle on `POST /a2a` | [API Reference](../protocol/API%20Reference.md); the A2A client in the [Client SDK Guide](../clients/Client%20SDK%20Guide.md) |

---

## 4. Tools and prompts

| Concern | What it is | Authority |
|---|---|---|
| The catalog | Whatever the server has loaded: ask `tools/list`, or open the Tools page. Not listed in any document. | the running server |
| A provider's tools | Parameters, examples and API keys, one guide per provider | the guides under [`docs/tools/`](../README.md#tools) |
| Prompts | Prompt configs, arguments, the prompt pages | [Prompts Management Guide](../tools/prompts/Prompts%20Management%20Guide.md) |
| Writing a tool by hand | A tool config in `config/tools/` and its `BaseMCPTool` class | [Tutorial 2](../tutorials/TUTORIAL_02_create_a_custom_tool.md); internals in [Architecture](../architecture/Architecture.md) |
| Building tools in the browser | MCP Studio and its creators; deploy into the running server | [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md) |
| Tools from a description | Describe a tool: a sentence to a proposed, checked and tested tool (Python in the sandbox, REST, DB query, composite, or an API import), deployed only after an administrator approves the reviewed version; `studio.describe.*`, the `toolsmith` alias | [Tool Generation](../architecture/Tool%20Generation.md) |
| Tools from an API description | API Import: an OpenAPI 3.x / Swagger 2.0 spec or a GraphQL schema to reviewed tools on one generic executor; re-import diff; `api_import.*` | [API Import](../architecture/API%20Import.md) |
| Enterprise data as tools | Data connectors: a database, warehouse, vector store or search cluster to `<id>__list_tables`, `__describe_table`, `__query` and curated-view tools; the statement guard, read-only sessions, row/byte/time limits, masking; the Data Connectors page; `connectors.*` | [Data Connectors](../architecture/Data%20Connectors.md); per kind, the [Data Connectors Reference Guide](../tools/enterprise/Data%20Connectors%20Reference%20Guide.md) |
| Chaining tools | Composite tools, `StepResult`, `ParamLens`, `EntropyGuard` | [Composition Framework](../architecture/Composition%20Framework.md) |
| Workflows | DAGs of tool, composite and Ask SAJHA steps with branches, loops, waits and approvals; cron, webhook, file and event triggers; durable runs, resume, re-run; the Workflows page; `workflows.*` | [Workflows](../architecture/Workflows.md) |
| Plugins | Packages of tool configs and classes with a `plugin.json` manifest | [Tutorial 4](../tutorials/TUTORIAL_04_create_a_plugin.md) |
| Caching and circuit breakers | Per-tool `cache_ttl`, the cache statistics, per-provider breakers | [Tutorial 6](../tutorials/TUTORIAL_06_configure_tool_caching.md) |
| Background execution | Async tool runs delivered to a webhook, Kafka or a file (not the MCP tasks extension) | [Tutorial 7](../tutorials/TUTORIAL_07_submit_async_tool_execution.md); keys in the [Configuration Reference](Configuration%20Reference.md) |
| Tool quality and versions | Test cases with HTTP cassettes (`python -m sajha.quality test`, JUnit), the schema linter, health probes, evals for Ask SAJHA, tool versions with canary routing, pins, automatic rollback and sunset dates; the Tool Health, Evals and Tool Versions pages; `quality.*` | [Tool Quality](../architecture/Tool%20Quality.md) |
| Tenants | Tenant-scoped catalogs and quotas | [Architecture](../architecture/Architecture.md) |
| Python in the browser | The Python Playground: a Pyodide notebook; `import sajha` calls tools with the user's session; vendored or CDN assets; its own CSP and COOP/COEP | [Python Playground](Python%20Playground.md) |
| Asking SAJHA questions with an LLM | LLM providers and models, gateway aliases, policy and budgets, the mock provider, `/api/ai/ask`, the Ask SAJHA page, semantic tool search | [Intelligence Layer](../architecture/Intelligence%20Layer.md) |
| Extending the intelligence layer | Writing a provider, a model or a planner; the provider contract suite | [Extending the Intelligence Layer](../architecture/Extending%20the%20Intelligence%20Layer.md) |
| Fronting other MCP servers | Federation: upstreams, namespaced tools, approval, the Federation admin page, `federation.*` | [Federation](../architecture/Federation.md) |
| Acting as the user at other services | Connected accounts: providers, the OAuth flow with PKCE, the token vault, tool binding (`auth.connected_account`), "connect your account" on MCP, REST and Ask, federation token passthrough, `accounts.*` | [Connected Accounts](../architecture/Connected%20Accounts.md) |

---

## 5. Running it

| Concern | What it is | Authority |
|---|---|---|
| First run | Install, sign in, first call | [Quick Start](Quick%20Start.md) |
| Configuration | `config/application.yml`, `${ENV:default}`, `SAJHA_*` overrides, every key | [Configuration Reference](Configuration%20Reference.md) |
| Storage | Where configs, prompts, Studio output and docs live; local, S3, Azure, GCS; hot reload | [Storage Guide](Storage%20Guide.md) |
| Database | SQLite or PostgreSQL (`db.*`) for users, keys, audit, composites and usage; one schema file per database, the manual PostgreSQL step, upgrades | [Database Setup](Database%20Setup.md) |
| Security | Credentials, users, roles, API keys, tool access, OAuth, Origin checks, headers, rate limits, audit log, deployment checklist | [Security Model](../security/Security%20Model.md) |
| Running user code | The sandbox for Studio Python and script tools and the shell: threat model, backends, guarantees, tool `sandbox` policy | [Sandbox](../architecture/Sandbox.md) |
| Deployment | AWS CDK, Hetzner, bare metal | [`deployment/README.md`](../../deployment/README.md) |
| Kubernetes | The container image, the Helm chart (`charts/sajha`), Kustomize manifests, secrets every pod shares, several replicas, streaming ingress | [Kubernetes Deployment](Kubernetes%20Deployment.md) |
| Several workers and hosts | The state store (`state.backend`: memory, Redis, database), what is shared between workers and what stays per process, durable tasks, secrets every host must share | [Scaling and State](../architecture/Scaling%20and%20State.md) |
| Watching it run | Prometheus `/metrics`, OpenTelemetry traces and metrics, the usage ledger and the Usage & cost page, alert rules, `observability.*` | [Observability](../architecture/Observability.md) |
| Governing tool calls; audit | Policy rules on every call (`config/policies/`, `policy.*`): deny, approval, argument constraints, rate limits, quotas, PII redaction, injection screening; the hash-chained, signed audit, `python -m sajha.audit verify`, SIEM export (`audit.*`) | [Policy and Audit](../architecture/Policy%20and%20Audit.md) |
| Calling SAJHA from Python | `SajhaMCPClient` on the official SDK; REST and A2A clients | [Client SDK Guide](../clients/Client%20SDK%20Guide.md) |
| Command line and desktop clients | The `sajha` CLI; MCP over stdio for Claude Desktop, Claude Code, IDEs | [Command Line](../clients/Command%20Line.md) |

---

## 6. Where the documentation lives, and which kind wins

Each kind of document has one job. When two documents cover the same thing, the one
whose job it is holds the content, and the other links to it.

| Kind | Job | Location |
|---|---|---|
| **Guides** | How to use a feature: configuration, behaviour, operations. **The authority for usage.** | `docs/<topic>/`, indexed in [`docs/README.md`](../README.md) |
| **Compliance reports** | What the protocol implementation does, requirement by requirement, with test evidence | `docs/protocol/MCP * Compliance.md` |
| **Architecture** | How the server is built inside | `docs/architecture/` |
| **Tutorials** | Learning by doing, in order | `docs/tutorials/TUTORIAL_*.md` |
| **In-app help** | The help catalog, these guides rendered at `/help/guides/<name>`, the glossary at `/glossary`, and an "About this page" panel on every console page, each linking to the owning guide | `sajha/web/help_catalog.py`, `sajha/web/guides.py`, `sajha/web/page_help.py` |
| **Comparison** | How SAJHA compares with other MCP products: one verdict, note, source and date per cell | `/comparison`, rendered from `sajha/web/competitive.py` (the only copy) |
| **Glossary** | One definition per term | [`GLOSSARY.md`](../../GLOSSARY.md) |
| **Release log** | What changed, version by version | [`CHANGELOG.md`](../../CHANGELOG.md) |
| **Version** | The one version number | `app.version` in `config/application.yml` |
| **Archive** | Point-in-time reports, not maintained | `docs/archive/` |
| **README** | First contact: what it is, install, first run | repository root |

The conventions behind this table are in [`CLAUDE.md`](../../CLAUDE.md).

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
