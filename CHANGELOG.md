# SAJHA MCP Server — Changelog

---

## v4.0.0 (May 2026) — Production Hardening

Major release: WebSocket transport, OpenTelemetry observability, tool versioning, multi-tenancy, and plugin system.

### New Features

- **WebSocket transport** (`/mcp/ws`): Full-duplex bidirectional MCP communication. Server pushes notifications without polling. Auth via `?token=` or `?api_key=` query params. WSSession tracks auth context and state. `MCPWebSocketClient` added to SDK.
- **OpenTelemetry observability** (`sajha/observability/`): MetricsCollector with per-tool LatencyHistogram (p50/p95/p99). AlertRule engine for error spikes and latency thresholds with webhook support. OTELIntegration optionally exports to Datadog/Grafana/Splunk. HealthProbe with `/health` (liveness) and `/ready` (readiness).
- **Tool versioning** (`sajha/core/tool_versioning.py`): ToolVersion with lifecycle states (active → deprecated → sunset → retired). ToolVersionManager resolves `tool@version` names with deprecation warnings. ContractTestRunner validates schemas against live execution. `tool_versions` DB table.
- **Multi-tenancy** (`sajha/core/tenancy.py`): Tenant-isolated tool access with wildcard patterns + blocked lists. TenantQuota with daily/monthly call limits and token budgets. Data isolation via per-tenant directory prefixes. `tenants` DB table. Admin CRUD API.
- **Plugin system** (`sajha/core/plugins.py`): Standardized `plugin.json` manifest format. PluginManager discovers, validates (checksum + version + config keys), installs dependencies, and registers tools. Supports JSON configs and Python classes. Admin load/unload API.
- **19 database tables** (was 17): added `tenants` and `tool_versions`.
- **Operations routes** (`sajha/routes/ops_routes.py`): `/health`, `/ready`, `/api/metrics/*`, `/api/tenants/*`, `/api/plugins/*`, `/api/contract-test/*`, `/api/tool-versions/*`.
- **Embedded LLM Gateway**: 6 providers (Anthropic, OpenAI, Bedrock, Together, Ollama, Azure OpenAI) via official SDKs. Registry-based factory pattern (`register_provider_class()`). DB-managed providers and models (`llm_providers` + `llm_models` tables). User-level overrides (`user_ai_preferences`). Response cache (SHA-256 LRU). Token budget tracking (`llm_usage`).
- **Semantic Tool Discovery**: Vector embeddings of 497 tool descriptions. Cosine similarity search. NL parameter extraction via LLM. Keyword fallback for offline use.
- **Composite Tools**: Sibling (parallel) and Parent-Child (fan-out) patterns. Declarative DB definitions (`composite_tools` + `composite_tool_steps`). Dynamic input/output schema building at boot. Visual builder UI at `/composite/builder`.
- **Storage & Reload Abstractions**: `StorageBackend` ABC (Local + S3) and `ReloadManager` ABC (Local + S3). Factory pattern via `SAJHA_STORAGE_BACKEND` config. Identical behavior on-prem and AWS.
- **AWS Deployment Blueprint**: Dockerfile (multi-stage), AWS CDK Python stack (VPC + ALB + ECS Fargate + RDS + S3 + Secrets Manager + CloudWatch dashboard), bootstrap.sh.
- **DB-driven prompts**: `prompts` + `prompt_tags` tables with PromptDAO (12 methods). Migration utility from legacy JSON.

### API Changes

- New: `GET /mcp/ws` (WebSocket), `GET /health`, `GET /ready`
- New: `GET /api/metrics`, `GET /api/metrics/tools`, `GET /api/metrics/tools/{name}`
- New: `GET/POST/PUT/DELETE /api/tenants/*`
- New: `GET/POST /api/plugins/*`
- New: `POST /api/contract-test`, `POST /api/contract-test/{tool_name}`
- New: `GET/POST /api/ai/providers/*`, `GET/POST /api/ai/models/*`, `GET/POST/DELETE /api/ai/preferences`
- New: `POST /api/ai/resolve-tool`, `POST /api/ai/complete`, `GET /api/ai/usage`
- New: `GET/POST/PUT/DELETE /api/composite-tools/*`
- New: `GET /api/ws/sessions`

### SDK Changes

- Added `MCPWebSocketClient` with full WebSocket MCP support (requires `websockets` package)
- Updated `__init__.py` exports to include `MCPWebSocketClient`
- Version bumped to 4.0.0

---

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. Every component rebuilt, all documentation rewritten.

### Breaking Changes

- **Framework:** Flask → FastAPI (ASGI). All routes converted from Blueprints to APIRouters.
- **Configuration:** `.properties` files removed. All config now in `config/application.yml`.
- **Database:** Alembic removed. Schema managed via SQL scripts with `CREATE TABLE IF NOT EXISTS`.
- **Transport:** Socket.IO removed. MCP transport uses HTTP POST and SSE per MCP spec.
- **Password hashing:** passlib removed, replaced with direct bcrypt 4.x.

### New in v3.1.0

- FastAPI orchestrator, 13 route modules, 79+ endpoints
- MCP compliance (2025-06-18): 12 methods, 5 capabilities
- A2A protocol with agent card and task lifecycle
- Reporting: 6 API endpoints + Chart.js dashboard
- 497 tools loaded from JSON configs
- YAML-only config with env var substitution
- SQL-based schema: 9 tables
- Zero-dependency client SDK

---

## v2.9.8 and Earlier (Flask)

Flask-based implementation with .properties configuration. See git history for detailed v2 changelog.

---

*SAJHA MCP Server — Changelog*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
