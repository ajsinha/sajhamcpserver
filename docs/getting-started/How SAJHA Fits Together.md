# How SAJHA Fits Together

This is the map of SAJHA. It says what each part is for, how the parts connect, and
**which single document owns the details of each one**. It does not repeat those
details: each section ends with an **Authority** line pointing to the document that
does. If this map and an authority ever disagree, the authority is right and this map
is the one to fix.

---

## 1. What SAJHA is

SAJHA (साझा, "shared") is a [Model Context Protocol](https://modelcontextprotocol.io)
server. It turns a catalog of data and utility tools (market data, central banks,
public statistics, filings, search, analytics, calculators) and reusable prompts into
something any MCP client (an AI assistant, an agent framework, a script) can discover
and call. Around that core it adds what running such a server for real needs: a web
UI, users and roles, API keys, OAuth, a visual tool builder, tool composition, caching,
circuit breakers, observability, and pluggable storage.

**Authority:** [README](../../README.md) (first contact); [Architecture](../architecture/Architecture.md).

---

## 2. The process at a glance

```
  MCP clients            programs / agents          people (browser)
       │                        │                          │
  /mcp (both eras)        /api/* REST, /a2a          web UI, /help, /glossary
  /mcp/sse, /mcp/ws       (JWT or API key)           (session cookie; help is public)
       │                        │                          │
       └──── Origin check · authorization (API key · JWT · OAuth 2.1) ────┘
                                 │
         MCPHandler (+ 2026-07-28 envelope) · REST routes · page routes
                                 │
   ToolsRegistry ◄─ tool configs        PromptsRegistry ◄─ prompt configs
   composite tools · Studio tools · plugins · versions · tenants
                                 │
   cache → circuit breaker → tool → provider API          change bus → listeners
                                 │
   storage backend (local | S3 | Azure | GCS)      database (SQLite | PostgreSQL)
```

One process by default. Several pieces of protocol state live in memory, which is why
scaling out needs sticky routing.

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
| Every HTTP endpoint | REST, MCP, OAuth and A2A routes | [API Reference](../protocol/API%20Reference.md) |

---

## 4. Tools and prompts

| Concern | What it is | Authority |
|---|---|---|
| The catalog | Whatever the server has loaded: ask `tools/list`, or open the Tools page. Not listed in any document. | the running server |
| A provider's tools | Parameters, examples and API keys, one guide per provider | the guides under [`docs/tools/`](../README.md#tools) |
| Prompts | Prompt configs, arguments, the prompt pages | [Prompts Management Guide](../tools/prompts/Prompts%20Management%20Guide.md) |
| Building tools in the browser | MCP Studio and its nine creators | [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md) |
| Chaining tools | Composite tools, `StepResult`, `ParamLens`, `EntropyGuard` | [Composition Framework](../architecture/Composition%20Framework.md) |
| Asking SAJHA questions with an LLM | LLM providers and models, gateway aliases, the mock provider, `/api/ai/ask` | [Intelligence Layer](../architecture/Intelligence%20Layer.md) |

---

## 5. Running it

| Concern | What it is | Authority |
|---|---|---|
| First run | Install, sign in, first call | [Quick Start](Quick%20Start.md) |
| Configuration | `config/application.yml`, `${ENV:default}`, `SAJHA_*` overrides, every key | [Configuration Reference](Configuration%20Reference.md) |
| Storage | Where configs, prompts, Studio output and docs live; local, S3, Azure, GCS; hot reload | [Storage Guide](Storage%20Guide.md) |
| Security | Credentials, roles, OAuth, Origin checks, headers, rate limits, deployment checklist | [Security Model](../security/Security%20Model.md) |
| Deployment | AWS CDK, Hetzner, bare metal | [`deployment/README.md`](../../deployment/README.md) |
| Calling SAJHA from Python | `SajhaMCPClient` on the official SDK; REST and A2A clients | [Client SDK Guide](../clients/Client%20SDK%20Guide.md) |

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
| **Glossary** | One definition per term | [`GLOSSARY.md`](../../GLOSSARY.md) |
| **Release log** | What changed, version by version | [`CHANGELOG.md`](../../CHANGELOG.md) |
| **Version** | The one version number | `app.version` in `config/application.yml` |
| **Archive** | Point-in-time reports, not maintained | `docs/archive/` |
| **README** | First contact: what it is, install, first run | repository root |

The conventions behind this table are in [`CLAUDE.md`](../../CLAUDE.md).

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
