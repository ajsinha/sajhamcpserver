# SAJHA MCP Server — Glossary

**Version:** 5.1.0 · **Last Updated:** May 2026

---

## A

**A2A (Agent-to-Agent):** A protocol for inter-agent communication. SAJHA implements agent card discovery at `/.well-known/agent.json` and task lifecycle endpoints (`tasks/send`, `tasks/get`, `tasks/cancel`).

**API Key:** An authentication credential (`X-API-Key` header) with optional tool permission patterns. Managed via the Admin panel and stored as bcrypt hashes in the `api_keys` database table.

**application.yml:** The single configuration source for SAJHA v3. Located at `config/application.yml`. Supports `${ENV_VAR:default}` substitution and `SAJHA_` prefix environment variable overrides.

**AuthContext:** A dataclass returned by FastAPI dependency injection containing `user_id`, `user_name`, `roles`, and `is_admin`. Used by all authenticated routes.

**AuthManager:** The authentication orchestrator in `sajha/auth/__init__.py`. Resolves credentials from cookies, Bearer tokens, API keys, or OAuth tokens.

## B

**BaseMCPTool:** The abstract base class (`sajha/tools/base_mcp_tool.py`) that all tools must extend. Requires `get_input_schema()`, `get_output_schema()`, and `execute()` methods.

**bcrypt:** The password hashing library used directly (not via passlib) for compatibility with bcrypt 4.x.

## C

**Capabilities:** The set of MCP features a server declares during `initialize`. SAJHA declares: tools (listChanged), prompts (listChanged), resources (subscribe, listChanged), logging, completions.

**Cursor-based pagination:** The pagination method used by `tools/list` (100/page) and `resources/list` (50/page) in the MCP protocol handler.

## D

**DAO (Data Access Object):** Classes in `sajha/db/dao/__init__.py` that encapsulate database queries. Seven DAOs: UserDAO, RoleDAO, PermissionDAO, ApiKeyDAO, ToolExecutionDAO, ToolErrorDAO, SessionDAO.

**DeclarativeBase:** SQLAlchemy's base class for ORM model definitions, in `sajha/db/base.py`.

## F

**FastAPI:** The ASGI web framework powering SAJHA v3, replacing Flask from v2. Provides async support, automatic OpenAPI docs, and dependency injection.

**FMPGenericTool:** A generic tool class that auto-maps tool names to Financial Modeling Prep API endpoints. Adding a new FMP tool requires only a JSON config — no Python code.

## G

**Generic Tool Pattern:** An architecture where a single Python class handles multiple tools by deriving the API endpoint from the tool name. Used by `FMPGenericTool`, `OpenBBGenericTool`, and `FREDCustomSeriesTool`.

## H

**Hot-Reload:** The system (`sajha/core/hot_reload_manager.py`) that monitors `config/` for changes and reloads tool configs, prompts, users, and API keys without server restart.

## J

**JSON-RPC 2.0:** The protocol used for MCP communication. Every MCP request contains `jsonrpc`, `id`, `method`, and optionally `params`.

**JWT (JSON Web Token):** The token format used for session authentication. Created with `python-jose`, HS256 algorithm, configurable expiry.

## L

**Lifespan:** The FastAPI async context manager (`_lifespan()` in `app.py`) that runs initialization on startup and cleanup on shutdown.

## M

**MCP (Model Context Protocol):** A standardized protocol enabling AI systems to discover and invoke external tools. SAJHA implements version 2025-11-25 (latest), with full support for Tasks, Elicitation, Sampling, tool icons, and all authorization enhancements.

**MCPHandler:** The class (`sajha/core/mcp_handler.py`) that routes and handles all 12 MCP JSON-RPC methods.

**MCP Studio:** The visual tool creation platform at `/studio`. Supports 7 creator types: Python Code, REST Service, DB Query, Script, PowerBI Report, PowerBI DAX, and LiveLink.

## O

**OAuth:** Optional enterprise SSO support with 4 modes: `none`, `internal`, `external`, `hybrid`. Supports Azure AD, Okta, Auth0, and Keycloak.

**OpenBBGenericTool:** Similar to FMPGenericTool — auto-maps tool names to OpenBB SDK commands.

## P

**PropertiesConfigurator:** A singleton (`sajha/core/properties_configurator.py`) that resolves `${variable}` references in tool JSON configs using values from the flattened YAML config.

**Protocol Version:** The MCP specification version declared during `initialize`. SAJHA declares `2025-11-25` (latest). Includes Tasks, Elicitation, Sampling with tools, OIDC Discovery, CIMD, and PRM.

## R

**RBAC (Role-Based Access Control):** Authorization via roles (`admin`, `user`) mapped to permissions through the `user_roles` and `role_permissions` tables.

**Route Module:** One of 13 `APIRouter` instances in `sajha/routes/` registered with the FastAPI app during startup.

## S

**SAJHA (साझा):** Hindi/Urdu word meaning "shared," "common," or "collaborative." Reflects the server's purpose of creating a shared bridge between AI systems and data sources.

**SajhaMCPServerWebApp:** The main application class in `sajha/app.py`. Creates the FastAPI app, initializes all subsystems, and manages lifecycle.

**Settings:** A dataclass in `sajha/core/config.py` exposing typed configuration values derived from `application.yml`.

**SSE (Server-Sent Events):** One of two MCP transports supported. Endpoints: `GET /mcp/sse` (event stream) and `POST /mcp/message` (send messages).

## T

**Tool Config:** A JSON file in `config/tools/` defining a tool's name, implementation class path, description, and metadata.

**Tool Group:** A UI grouping derived from the text before the first `_` in a tool name (e.g., `yahoo_finance_quote` belongs to group `yahoo`).

**ToolsRegistry:** The singleton (`sajha/tools/tools_registry.py`) that loads, instantiates, and manages all tool instances. Provides `get_tools_registry()`.

## U

**url_for:** A custom template function in `app.py` that maps endpoint names to URL paths, providing Flask-style URL resolution across Jinja2 templates.

**Uvicorn:** The ASGI server used to run the FastAPI application.

---

*SAJHA MCP Server v5.1.0 — Glossary*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*

**ClientPipeline:** Client-side tool composition class in the SDK (`clientsdk/sajhaclient/mcp_client.py`). Chains `add_step()` calls with `$input.` / `$.` param mapping. `execute()` tracks confidence and entropy without server-side composite definitions.

**Confidence Score:** A float 0.0–1.0 indicating a tool's reliability. 1.0 = deterministic (calculators), 0.95 = stable API (FRED), 0.80 = web crawl. Composite results compound scores: sequential multiplies, parallel takes min.

## E

**EntropyGuard:** Pre/post-execution uncertainty tracker (`sajha/core/composition.py`). Records per-step confidence, calculates cumulative Shannon entropy. Can refuse pipelines exceeding `max_entropy_bits`. Supports `begin_parallel()`/`end_parallel()` for weakest-link model.

**Entropy (Shannon):** Information-theoretic measure of uncertainty in bits. `H = -p*log2(p) - (1-p)*log2(1-p)`. A deterministic result has 0 bits. Binary uncertainty (50/50) has 1 bit. Used by `EntropyGuard` to quantify pipeline uncertainty.

## K

**Kleisli Composition:** From category theory — composing functions that return monadic values. In SAJHA: every tool is a Kleisli arrow `Dict → StepResult`. Composition via `bind()`: error short-circuits, traces accumulate, confidence compounds.

## P

**ParamLens:** A lens (view/set pair) for parameter projection (`sajha/core/composition.py`). `view()` extracts child params from parent context using `$.field` / `$input.field` syntax. `set()` merges child result back. Ensures child tools see only mapped fields.

**PipelineResult:** The final output of a composite pipeline. Contains merged tool outputs + `_composition` metadata block with confidence, entropy_bits, trace, guard_passed, steps_executed.

**Plugin:** An extension package in `config/plugins/` with a `plugin.json` manifest. Contains tool configs and optionally Python classes. Flow: `discover()` → `validate()` (checksum) → `load_plugin()` (install deps, register tools).

## S

**StepResult:** The monadic result envelope (`sajha/core/composition.py`). Carries: value, error, trace, duration_ms, confidence, step_name. `pure()` lifts a value (confidence=1.0). `fail()` lifts an error (confidence=0.0). `bind()` chains with short-circuit on error.

## T

**Theme:** One of four visual styles applied via `data-theme` attribute on `<html>`. Light (white, blue accents), Dark (navy glass-morphism), Wall Street (black, amber, Consolas), Ubuntu (aubergine, orange). CSS uses `var(--t-*)` variables, 545 lines total.

**TransportCoalgebra:** Abstract interface for MCP transport clients (`clientsdk/sajhaclient/mcp_client.py`). `step(method, params) → (result, new_state)`. Implementations: `HTTPTransport`, `SSETransport`, `WSTransport`. Enables `bisimilar()` equivalence testing.

## W

**Weakest-Link Model:** The confidence aggregation model for parallel (sibling) composite steps. `confidence = min(step_a, step_b, step_c)` rather than multiplying. Correct because parallel steps are independent — the composite is as reliable as its least reliable component.

**WebSocket Transport:** Full-duplex MCP transport at `/mcp/ws`. Connect with `?token=jwt` or `?api_key=key`. Supports bidirectional messaging — server can push notifications without polling. `WSSession` tracks auth, init state, last activity.

**MCPTask:** A trackable async operation in the MCP Tasks primitive (SEP-1686, 2025-11-25). States: working → input_required → completed → failed → cancelled. Clients poll via `tasks/get`. Server creates tasks for long-running tool executions.

**Elicitation:** Server-initiated request for user input (SEP-1330, SEP-1036, 2025-11-25). Two modes: Form (structured JSON Schema fields) and URL (redirect to OAuth consent page). Client responds via `elicitation/respond`.

**Sampling:** Server-initiated LLM completion request. 2025-11-25 adds tool calling support (SEP-1577): server can include `tools` and `toolChoice` parameters, enabling server-side agent loops where the LLM can call tools during sampling.

**CIMD (Client ID Metadata Document):** OAuth client registration mechanism (SEP-991, 2025-11-25). Replaces Dynamic Client Registration. Served at `/.well-known/oauth-client/{client_id}`.

**PRM (Protected Resource Metadata):** OAuth 2.0 resource discovery per RFC 9728. Served at `/.well-known/oauth-protected-resource`. Declares authorization servers, supported scopes, and bearer methods.

## New in v5.1.0

**ToolCache:** File-based cache with per-tool TTL for tool output results (`sajha/core/cache.py`). Each entry is a JSON file on disk: `data/cache/{tool_name}/{md5_hash}.json`. Default: no caching. Tools opt in via `cache_ttl` in their JSON config. Max 50,000 files with oldest-file eviction. Survives server restarts. Zero memory overhead.

**CircuitBreaker:** Per-provider failure tracking (`sajha/core/circuit_breaker.py`). States: CLOSED (normal) → OPEN (after 5 consecutive failures, 60s recovery) → HALF_OPEN (one probe request allowed). Prevents cascading failures when external APIs go down. Registry maps 16 providers to circuit breakers.

**WebhookManager:** Event notification system (`sajha/core/webhooks.py`). Subscribers register callback URLs for events (tool.completed, task.failed, circuit.opened). Delivery with 3 retries and exponential backoff. Fire-and-forget in background threads.

**ExecutionReplayStore:** Stores last 20 executions per tool (`sajha/core/tool_health.py`). Each entry: tool_name, arguments, result preview, duration_ms, timestamp, user_id, success. Enables replay for debugging and regression testing.

**AuditLogger:** Structured security event logging (`sajha/core/audit.py`). Writes to `audit_log` DB table. Events: login_success, login_failed, logout, user_create, user_delete, apikey_create, apikey_revoke, tool_execute, config_change, permission_change, account_locked.

**ProviderHealth:** Aggregates circuit breaker state with tool dependency graph (`sajha/core/tool_health.py`). Maps 497 tools → 16 providers → external API endpoints. Status per provider: healthy (circuit closed), degraded (half_open), down (open).


**AsyncExecutor:** Background tool execution engine (`sajha/core/async_executor.py`). Bounded work queue (`queue.Queue(maxsize=1000)`) with daemon worker pool (configurable, default 8 threads). Workers call `execute_with_tracking()` for cache/circuit/replay integration. Supports backpressure (HTTP 503 when full).

**AsyncTask:** A background tool execution unit. Lifecycle: queued → running → completed/failed → delivered. Tracks task_id, tool_name, arguments, delivery type/destination, result, duration, timestamps.

**DeliveryRouter:** Routes completed async task results to the configured destination: webhook (POST with retry), Kafka (produce to topic), or file (atomic write via rename). Lazy Kafka import — only loaded if Kafka delivery is used.


**ShellExecutor:** Unified sandboxed execution interface (`sajha/core/shell_executor.py`). Three tiers: Python sandbox (restricted imports, 30s timeout, 256MB), Bash sandbox (allowlisted commands, 15s timeout), Unrestricted (admin-only, disabled by default). Every execution audit-logged.

**SecurityValidator:** Pre-execution code/command validator. Python: blocks `os`, `subprocess`, `socket`, `exec()`, `eval()`, file operations. Bash: allowlist of safe commands (cat, grep, awk, etc.), blocks `rm`, `sudo`, `ssh`, pipe-to-shell, command chaining.

**PythonSandbox:** Executes Python in a subprocess with restricted PATH, no PYTHONPATH, limited env vars. Allowed imports: json, math, csv, statistics, re, datetime, pandas, numpy. Temp file written to scratch dir, deleted after execution.


**Semantic Tool Discovery:** Natural-language tool search via vector embeddings (`sajha/core/resolver.py`). All 497 tool descriptions are embedded as vectors. User queries are embedded and compared via cosine similarity. Returns ranked tool list with relevance scores. API: `POST /api/ai/resolve-tool`. No other MCP server has this capability.

**LLM Gateway:** Multi-provider AI inference layer (`sajha/ai/`). 6 providers: Anthropic, OpenAI, AWS Bedrock, Together.ai, Ollama, Azure OpenAI. All via official SDKs. Providers and models managed in DB tables. Three-tier model resolution: explicit → user prefs → system defaults. Registry-based factory supports custom provider classes.
