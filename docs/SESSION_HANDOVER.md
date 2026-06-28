# SAJHA MCP Server — Session Handover Document

**Date:** June 28, 2026
**Version:** 5.2.0
**Owner:** Ashutosh Sinha (ajsinha@gmail.com)
**GitHub:** ajsinha/sajhamcpserver

---

## What is SAJHA?

SAJHA (Hindi: साझा — "shared, collaborative") is a production-grade Model Context Protocol (MCP) server built on FastAPI/Python. It is **fully compliant with MCP 2025-11-25** (latest released spec) and exposes **497 tools** across financial markets, government data, search, analytics, and enterprise integrations. It has **18 competitive advantages** that no other MCP server has.

---

## Current State (v5.2.0)

### Architecture

```
run_server.py → SajhaMCPServerWebApp (FastAPI)
  ├── 179 route functions across 14 route modules
  ├── MCPHandler (MCP 2025-11-25, 15 JSON-RPC methods)
  │     ├── TaskManager (async tracking)
  │     ├── ElicitationManager (form + URL user input)
  │     └── SamplingManager (LLM calls with tools)
  ├── ToolsRegistry (497 tools from JSON configs)
  ├── CompositeToolEngine + Composition Framework
  │     ├── StepResult (Kleisli envelope)
  │     ├── ParamLens ($.field parameter projection)
  │     └── EntropyGuard (confidence tracking)
  ├── AsyncExecutor (8-thread daemon pool, bounded queue)
  │     └── DeliveryRouter (webhook/Kafka/file)
  ├── ShellExecutor (Python + Bash sandbox)
  ├── ToolCache (file-based, per-tool TTL from config)
  ├── CircuitBreakerRegistry (16 providers)
  ├── AuditLogger (DB-persisted security events)
  ├── WebhookManager (event notifications)
  ├── LLM Gateway (6 providers via official SDKs)
  ├── Semantic Tool Resolver (vector embeddings)
  ├── TenantManager (multi-tenant isolation)
  ├── PluginManager (discover → validate → load)
  ├── OpenTelemetry (p50/p95/p99, health probes)
  └── OAuth Discovery (OIDC, CIMD, PRM)
```

### File Counts

| Category | Count |
|----------|------:|
| Python files | 211 |
| HTML templates | 54 |
| Documentation (markdown) | 50 files, 47,000+ lines |
| Route functions | 179 |
| MCP tools | 497 |
| DB tables | 19 (16 model + 3 junction/utility) |
| Security controls | 42 |
| CSS themes | 4 (Light, Dark, Wall Street, Ubuntu) |

### Key Modules

| Module | Lines | Purpose |
|--------|------:|---------|
| `sajha/core/mcp_handler.py` | 736 | MCP JSON-RPC dispatch (15 methods) |
| `sajha/core/mcp_2025_11_25.py` | 504 | Tasks, Elicitation, Sampling, Icons, OIDC, CIMD, PRM, SSE |
| `sajha/core/properties_configurator.py` | 734 | YAML/properties config with ${VAR:default}, auto-reload |
| `sajha/core/async_executor.py` | 447 | Background execution: queue, workers, delivery routing |
| `sajha/core/shell_executor.py` | 488 | Sandboxed Python + Bash (allowlisted, audit-logged) |
| `sajha/core/auth_manager.py` | 399 | DB-backed auth: bcrypt, sessions, lockout |
| `sajha/core/cache.py` | 303 | File-based tool output cache with per-tool TTL |
| `sajha/core/config.py` | 264 | YAML config loader, Settings model, env var substitution |
| `sajha/security.py` | 222 | bcrypt, SHA-256, rate limiting, security headers, CSRF |
| `sajha/core/tool_health.py` | 183 | Dependency graph, provider health, execution replay |
| `sajha/core/circuit_breaker.py` | 158 | Per-provider failure tracking (CLOSED→OPEN→HALF_OPEN) |
| `sajha/core/webhooks.py` | 127 | Event notifications with retry |
| `sajha/core/audit.py` | 92 | Structured security event logging |

---

## 18 Competitive Advantages

| # | Category | Advantage |
|:-:|----------|-----------|
| 1 | Design | MCP Studio — 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP) |
| 2 | Design | Composite Builder — visual pipeline designer with drag-drop + confidence |
| 3 | AI | LLM Gateway — 6 providers (Anthropic, OpenAI, Bedrock, Together, Ollama, Azure), DB-managed |
| 4 | AI | Semantic Tool Discovery — vector embeddings, natural language search |
| 5 | AI | Composition Framework — EntropyGuard + ParamLens (Kleisli/Giry from category theory) |
| 6 | Execution | Async execution — webhook/Kafka/file delivery, bounded queue, backpressure |
| 7 | Execution | Sandboxed shell — Python + Bash with allowlists, audit trail, disabled by default |
| 8 | Execution | Tool output caching — file-based, per-tool TTL from JSON config |
| 9 | Execution | Circuit breakers — 16 providers, auto-recovery (CLOSED→OPEN→HALF_OPEN) |
| 10 | Enterprise | Multi-tenancy — per-tenant tool access + quotas |
| 11 | Enterprise | Plugin system — discover → SHA-256 validate → load → hot-reload |
| 12 | Enterprise | Tool versioning — v1/v2 side-by-side, deprecation lifecycle |
| 13 | Enterprise | OpenTelemetry — per-tool p50/p95/p99, alerting, /health + /ready |
| 14 | Platform | MCP 2025-11-25 — full compliance (18/18 items) |
| 15 | Platform | 497 built-in tools (vs 0-20 for all competitors) |
| 16 | Platform | Web UI — 42+ screens, 4 themes, WCAG AA |
| 17 | Platform | Client SDK — 5 clients + TransportCoalgebra + ClientPipeline |
| 18 | Platform | Cybersecurity — 42 controls, OWASP aligned, bcrypt + SHA-256 |

---

## Configuration System

**Single source:** `config/application.yml` (YAML-only, no .properties files)

**Override via CLI:** `python run_server.py --config /path/to/custom.yml`

**Override via env:** `SAJHA_CONFIG_FILE=/path/to/custom.yml`

**Key sections:** app, server, db, auth, oauth, ai, cache, async, shell, logging, hot_reload, features

**Config contract:**
- `_get('key', default)` — returns default only if key NOT defined. Empty string IS a valid value.
- `_int()`, `_bool()` — safe conversion, handle empty strings
- `_flatten()` — None values excluded from dict (key not present → default kicks in)
- `${ENV_VAR:default}` substitution in YAML values
- PropertiesConfigurator with native YAML support via `yaml_file` param

---

## Database

**Dual support:** SQLite (auto-creates on startup) / PostgreSQL (schema must pre-exist)

**Schema files:** `db/scripts/sqlite/001_schema.sql` and `db/scripts/postgres/001_schema.sql`

**Generated from:** SQLAlchemy models via AST parsing (models are source of truth)

**Tables:** 16 model tables + 3 junction/utility = 19 total, 150 columns

**Critical principle:** No SQL reserved words as column names. Use `created_at` (not `timestamp`), `user_id` (not `actor_id`), `rate_key` (not `key`).

**No migrations.** Delete `data/sajha.db` when schema changes.

---

## MCP Protocol

**Version:** 2025-11-25 (latest released)

**Transports:** Streamable HTTP (POST+GET on `/mcp`), SSE (alias `/mcp/sse`), WebSocket (`/mcp/ws`)

**Methods:** 15 (initialize, tools/list, tools/call, tasks/get/list/cancel, elicitation/respond, notifications/cancelled, resources, prompts, completion, logging, ping)

**Next spec:** 2026-07-28 RC — breaking revision (stateless core, extensions framework). Plan v6.0.0 after July 28 final.

---

## Key Learnings & Recurring Bug Patterns

1. **Model ↔ Schema sync:** Column names in SQLAlchemy model MUST match SQL schema exactly. Use AST-based audit script to verify.
2. **SQL reserved words:** Never use `timestamp`, `text`, `password`, `type`, `order`, `group`, `key`, `value`, `index`, `query` as column names.
3. **Config empty strings:** `int(config.get('key', 3600))` crashes when config returns `''`. Use `int(value or 3600)` or the fixed `_int()` helper.
4. **CSS theme discipline:** All colors via `var(--t-*)`. Never hardcode hex in templates. Bootstrap `navbar-dark` class overrides theme colors.
5. **Router prefix double-up:** `admin_routes` has `prefix='/admin'`, so routes should be `@router.get('/users')` not `@router.get('/admin/users')`.
6. **DAO constructor order:** `BaseDAO.__init__(model, db)` — model first, db second. Three DAOs had these swapped.
7. **Python booleans:** Use `True`/`False` in Python code, not JSON `true`/`false`.
8. **Import render:** Routes that render templates need `from sajha.app import render`.
9. **File-based cache default:** NO caching by default. Per-tool opt-in via `"cache_ttl": 3600` in tool JSON config.
10. **Shell tools default:** DISABLED by default. `shell.enabled: false` in config.

---

## What's On the Horizon

1. **MCP 2026-07-28 migration** (plan v6.0.0 after July 28 final spec)
2. **Tool expansion toward 2,000+**
3. **Pydantic request models** for all POST endpoints
4. **Per-user API rate limiting** wiring into tool execution
5. **CSRF tokens** for web forms (beyond SameSite=lax)
6. **mTLS** for inter-service communication
7. **3 remaining SharePoint abstract class failures** to fix

---

## Documentation Inventory

| Document | Lines | Content |
|----------|------:|---------|
| README.md | 282 | Quick start, features, competitive analysis, architecture |
| CHANGELOG.md | 535 | v3.1.0 → v4.0.0 → v4.5.0 → v5.0.0 → v5.2.0 |
| docs/API_Reference.md | 608 | 179 endpoints with curl examples |
| docs/Cybersecurity_Assessment.md | 547 | 42 controls, OWASP mapping, verification checklist |
| docs/MCP_2025_11_25_Compliance.md | 293 | 18 items with code evidence |
| docs/Composition_Framework.md | 293 | Kleisli, Lenses, EntropyGuard deep-dive |
| docs/architecture/*.md | 770+ | Architecture + Glossary (195 terms) |
| clientsdk/docs/USER_GUIDE.md | 857 | Complete SDK reference |

---

## Code Archive

**Latest:** `sajha-5.2.0.tar.gz` in `/mnt/user-data/outputs/`

**Extract:** `tar xzf sajha-5.2.0.tar.gz`

**Run:** `rm data/sajha.db && python run_server.py`

---

## Session History

Transcripts from previous sessions are at `/mnt/transcripts/`:
- `2026-05-12-23-00-55-sajha-v4-to-v4.5-full-build.txt`
- `2026-06-28-13-06-08-sajha-v4-to-v5-full-build.txt`
- `2026-06-28-20-53-20-sajha-v4-to-v5.1-full-build.txt`
