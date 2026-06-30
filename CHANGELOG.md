# SAJHA MCP Server — Changelog

## v5.3.0 (June 2026) — Storage-Backed Registries, Studio & Cloud Hot-Reload

Builds on the v5.2.0 multi-cloud storage abstraction by routing the live subsystems
through it: tool configs, prompts, and Studio output can now live on local disk, S3,
Azure Blob, or GCS, with cloud hot-reload. Default backend remains **local**.

### Tool registry → storage backend
- **`tools_registry` reads migrated.** `load_all_tools()` enumerates via
  `get_storage().list_files('config/tools', '*.json')` and reads each config through
  `get_storage().read_json()`. The loader (`load_tool_from_config`) now accepts a logical
  path (storage-relative string, `Path`, or filename) instead of a filesystem `Path`, and
  is normalized internally — so **tool configs can live in S3/Azure/GCS**. Verified end to
  end: real tool configs uploaded to a mocked S3 bucket load and instantiate correctly.
- **`register_tool_from_dict(config, source)` extracted** as the shared register path for
  the file loader and the plugin loader. This fixes a latent bug where `plugins.py` called
  `load_tool_from_config(name, config)` with two arguments against a one-arg method.
- **Implementation classes stay package-local.** Tool `.py` implementations are resolved by
  dotted module path via `importlib` and ship with the package, so they import locally
  regardless of where the JSON config lives.
- **Config writes migrated** (`_save_tool_config`) to `get_storage().write_json()`; the
  admin reload route (`api_routes`) uses the storage-backed path.

### Prompts registry → storage backend
- **Reads and writes migrated.** `_load_all_prompts_internal` lists/reads through storage;
  `create_prompt` / `update_prompt` write via `write_json()`; `delete_prompt` via
  `delete()`. Time-based auto-refresh now reloads from whichever backend is active.

### MCP Studio → storage backend
- **All eight tool generators** (code, REST, DB-query, script, SharePoint, LiveLink,
  PowerBI, PowerBI-DAX) write their JSON config through a shared
  `write_tool_config()` storage helper. Generated `.py` implementations are still written
  locally because `importlib` needs a real module on the path — on multi-instance cloud
  deployments, place that directory on shared EFS.

### Cloud hot-reload (no inotify on object stores)
- **`S3SyncManager` activated for cloud backends** at startup: it polls the bucket every
  `sync_interval` seconds, mirrors changed objects into the local cache, and fires the same
  reload paths (`tools_registry.reload_all_tools`, `prompts_registry.reload`). On the
  `local` backend the registry's filesystem poller is used and the sync manager is skipped,
  so exactly one mechanism runs per deployment. Verified via mocked S3: initial sync
  materializes the cache and a new object triggers the reload callback.

### Semantic tool search (pluggable embedder)
- **Natural-language tool discovery** at `/api/ai/resolve-tool`: a query like "discount future
  cash flows to today" returns the top-k matching tools by vector similarity. The index
  embeds each tool's name + description + parameter names + tags + an optional `literature`
  field.
- **Configurable ranking** via `ai.tool_search.embedder`:
  - `bm25` (default) — a dependency-free lexical BM25/TF-IDF ranker (no model, no key, no
    network), built over the same rich text (name + description + parameters + tags + literature).
  - `gateway` — optional API-driven vector similarity via the LLM gateway's embedding provider
    (e.g. OpenAI) for paraphrase matching. Switch with one config value; no code change.
  - Decoupled from the LLM gateway — semantic search needs no provider in the default mode.
- **Accurate on change.** The index does incremental, content-hash-based sync: only tools
  whose embedding text changed are re-embedded, removed tools are dropped, unchanged tools
  keep their vectors. It hooks the registry's reload path (`add_reload_listener`), so adds /
  edits / deletes — local or via the cloud sync manager — keep embeddings current.
- **Persisted via the storage backend** (local | s3 | azure | gcs) with a header recording the
  embedder + dimension; a restart reloads vectors (no re-embedding) and a changed embedder
  forces a clean rebuild (vectors from different models aren't comparable).
- **Non-blocking + graceful.** The initial index builds in a background thread so startup is
  never blocked; until it's ready (or if no embedder is available) search falls back to
  keyword matching. In-memory numpy cosine search — a `VectorIndex` seam is left for FAISS /
  Chroma if scale ever demands it.

### Database scripts cleanup
- **Fixed a critical regression where the file monitor unloaded all tools every 5s.** The
  storage migration changed `load_tool_from_config` to key `_file_timestamps` by
  storage-relative paths (`config/tools/foo.json`), but the registry's `_monitor_files`
  poller still compared against absolute paths — so every tool looked simultaneously "new"
  and "deleted" each cycle and the delete branch unregistered them all, leaving the registry
  empty. The monitor now keys on the same relative paths (`_config_rel`), so new/modified/
  deleted detection works correctly and legitimate hot-reload is preserved. Semantic tool
  search was also made fully non-blocking on reload, so the optional feature can never affect
  core tool loading.
- **Fixed SharePoint tools failing to load.** `SharePointBaseTool` never implemented the
  `get_input_schema` / `get_output_schema` abstract methods from `BaseMCPTool`, so all three
  SharePoint tools (documents, lists, search) raised "Can't instantiate abstract class …" at
  load. Added both getters to the base (returning the config's `inputSchema` / `outputSchema`,
  matching every other tool), making all four SharePoint classes concrete. Tool count
  496 → 499.
- **Removed obsolete top-level `db/scripts/001_schema.sql` + `002_seed.sql`.** The engine runs
  the dialect-specific `db/scripts/<db.type>/` directory; the top-level scripts were bypassed
  for SQLite and only reached as a buggy fallback (below).
- **Renamed `db/scripts/postgres/` → `db/scripts/postgresql/`** to match `db.type: postgresql`.
  Previously the engine looked for `db/scripts/postgresql/` (the `db.type` value), didn't find
  it, and silently fell back to the top-level scripts — so a Postgres deployment never used its
  own schema. Now `db/scripts/sqlite/` and `db/scripts/postgresql/` are the single source of
  truth per dialect.
- **Reconciled schema drift:** `llm_usage` and `user_ai_preferences` (previously only in the
  top-level file) are now defined in **both** dialect schemas alongside `rate_limit_log` and
  `tenant_users`, so SQLite and Postgres create an identical table set. Verified: SQLite boot
  creates all tables; both `db.type` values select the correct script directory.

### Documentation
- **New Storage Management help page** (`/help/storage`) with sections on local, EFS, S3,
  Azure Blob, and GCS — backend selection, auth, the read-mostly-vs-mutable-state rule, and
  how hot-reload works. Linked from the Help index.
- **README, ARCHITECTURE, and STORAGE_ROADMAP updated** to describe the storage-backed
  registries and cloud hot-reload. Version bumped to **5.3.0**.

## v5.2.0 (June 2026) — Offline Assets, Self-Only CSP & UI Polish

### Front-End Vendoring (offline-capable, no CDNs)

- **All third-party assets vendored** to `sajha/web/static/vendor/`: jQuery 3.7.1, Bootstrap 5.3.0 (CSS + bundle JS), Bootstrap Icons 1.10.0 (+ fonts), Socket.IO 4.5.4, marked 4.3.0 (pinned — preserves the `marked.setOptions({highlight})` API the docs viewer relies on), highlight.js 11.9.0 (+ 7 language packs + github-dark theme), Chart.js 4.4.0, jsoneditor 9.10.4 (+ icons), and three webfonts (Ubuntu, Plus Jakarta Sans, JetBrains Mono).
- **Zero external resource loads** remain across all 52 templates — the app renders fully offline / air-gapped.

### Security — Content-Security-Policy

- **Docs viewer fixed**: the markdown viewer previously spun forever because jQuery and Socket.IO were loaded from CDNs that the CSP `script-src` did not whitelist, so `$` was undefined and `$(document).ready()` threw before the render path. With everything vendored, this class of failure is gone.
- **CSP tightened to self-only**: `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:`. No third-party origins to drift out of sync with.
- **CORS** default aligned with the `0.0.0.0` bind: localhost / 127.0.0.1 / 0.0.0.0 on :3002 (override via `SAJHA_CORS_ORIGINS`).

### Config Substitution Fix

- **`${data.duckdb.dir}` / `${data.sqlselect.dir}` now resolve correctly.** Root cause: `tools_registry` constructed `PropertiesConfigurator()` with no `yaml_file`, so it loaded nothing and every `${key}` fell through to its literal text — which created directories literally named `${data.duckdb.dir}`. The registry now loads the same config the app uses (respecting `SAJHA_CONFIG_FILE` / `--config`).
- `app.py` PropertiesConfigurator load also respects `SAJHA_CONFIG_FILE` instead of hardcoding the path.
- All 15 affected tool configs given `:default` fallbacks (e.g. `${data.duckdb.dir:./data/duckdb}`) as defense-in-depth.

### Storage Abstraction (on-prem ↔ cloud)

- **Pluggable storage backend** wired into startup: `storage:` config block (`backend: local|s3|azure|gcs`), `init_storage()` called before tools/prompts load, `get_storage()` available app-wide. Default `local` is a transparent filesystem wrapper — no behaviour change on-prem, and it needs none of the cloud SDKs.
- **Four backends behind one `StorageBackend` interface**: `LocalStorageBackend` (default) plus three object stores — **S3** (boto3, now with `endpoint_url` for MinIO/R2/Wasabi), **Azure Blob** (azure-storage-blob; connection-string or managed-identity auth), and **GCS** (google-cloud-storage; ADC/workload-identity auth). The three object stores share an `_ObjectStorageBackend` base (app-prefix namespacing, local read-through cache, recursive listing, `get_local_path` materialization); each implements only six small primitives. Cloud SDKs are lazy-imported, so only the selected backend's SDK is required.
- **Docs viewer migrated** to read through the backend (listing + content), so docs can be served from any backend; added a path-traversal guard.
- **`list_files` contract aligned** across local and object backends (recursive listing, filename-pattern match).
- Validated: S3 against a `moto`-mocked bucket; Azure + GCS against the real SDK surfaces (API-method introspection) plus injected-client logic tests; and the local default proven to boot with all cloud SDKs blocked. Remaining adoption (tools/prompts/studio, mutable-state placement, cloud hot-reload) tracked in `docs/STORAGE_ROADMAP.md`.

### Config-Driven UI Metadata

- Version, author, copyright, email, and GitHub URL/repo-name are all surfaced on the UI from `application.yml` via Jinja globals. Closed the two remaining hardcoded spots (About-page email, an Enterprise help version literal) and added a GitHub link to the About page.

### UI / Theming

- **About page rewritten**: 1384 → 314 lines. The old page duplicated its marketing cards 7–14× with malformed closing tags (causing visual overlap); the rewrite renders each section exactly once, is structurally valid, and is fully theme-driven via `var(--t-*)` surfaces and `card-header-*` helpers.
- **Theme sweep**: 113 `card-header` elements using fixed `bg-*`/`text-white` across 28 templates converted to the theme-aware `card-header-*` helpers (no more colour bleed in Dark / Wall Street / Ubuntu themes). Intentional fixed colours (code-editor surfaces, provider/brand accents, status badges, landing-page gradients) deliberately preserved.
- **Landing page**: added a `<canvas>` "living intelligence mesh" behind the hero — a pulsing SAJHA hub routing animated data packets between AI-agent nodes (Claude, GPT-4o, Bedrock, Together, Ollama, Azure) and data-provider nodes (FMP, OpenBB, FRED, Yahoo, SEC EDGAR, CoinGecko). Vanilla JS, theme-matched, DPR/resize-aware, pointer-interactive, and respects `prefers-reduced-motion` (renders a single static frame).
- Dead duplicate templates removed: `help/docs_list.html`, `help/docs_view.html` (the live versions live under `docs/`).

### Dependencies

- **`requirements.txt` pinned** with next-major ceilings on all dependencies (0 unbounded) to keep fresh installs reproducible. A `pip freeze` lockfile from a tested environment remains the gold standard for full reproducibility.

---

## v5.1.0 (May 2026) — Security Hardening + System Monitor

### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

### Cybersecurity Overhaul

- **bcrypt password hashing** (12 rounds) — replaces plaintext comparison
- **SHA-256 API key hashing** — keys stored as hashes, never plaintext
- **DB-persisted sessions** — user_sessions table with hashed tokens
- **Account lockout** — 5 failed attempts → 15 minute lock
- **Rate limiting** — 5 login attempts per minute per IP (HTTP 429)
- **Security headers middleware** — X-Frame-Options, CSP, HSTS, XSS-Protection, Referrer-Policy, Permissions-Policy
- **CORS restricted** — configurable via SAJHA_CORS_ORIGINS env var (no more wildcard)
- **Cookie hardening** — HttpOnly + SameSite=lax + Secure (auto-detect HTTPS)
- **Request body limit** — 10 MB via RequestSizeLimitMiddleware
- **DuckDB SQL allowlist** — only SELECT/WITH/EXPLAIN permitted (comment-stripping)
- **Passwords never returned** — get_all_users() excludes password_hash
- **No hardcoded credentials** — admin password is bcrypt hash in seed SQL

### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

---

## v5.1.0 (May 2026) — Composition Framework + UX Overhaul

Category-theory-inspired composition, 4 UI themes, full UX redesign, CSS rewrite.

### Composition Framework (from "On the Composability of Intelligence")

- **Kleisli Composition** (`sajha/core/composition.py`): Every tool execution wrapped in `StepResult` envelope carrying value, error, trace, duration, and confidence. Errors short-circuit the pipeline. Traces accumulate across steps. Confidences compound via Giry bind.
- **ParamLens**: Lens-based parameter projection. Child tools receive ONLY mapped fields via `$.field` / `$input.field` syntax. Prevents accidental coupling to upstream output structure.
- **EntropyGuard**: Cumulative confidence tracking with parallel-aware model. Sequential steps multiply (Giry bind). Parallel steps use weakest-link (min). Mixed pipelines combine both. `entropy_threshold` per composite — refuses execution if uncertainty exceeds limit.
- **Tool Confidence Registry**: 497 tools classified by reliability — calculators 1.0, FRED 0.95, FMP 0.93, web crawlers 0.80. Composite results include `_composition.confidence` and `_composition.entropy_bits`.
- **CompositeTool.execute()** rewritten to use composition framework. All composites now return `_composition` metadata block with confidence, entropy, trace, and guard status.

### Client SDK Enhancements

- **Transport Coalgebra**: `TransportCoalgebra` abstract class with `step(input) → (output, new_state)`. `HTTPTransport`, `SSETransport`, `WSTransport` implementations. Enables runtime transport hot-swap.
- **bisimilar()**: Behavioral equivalence testing. Runs same operation sequence against two transports, verifies identical output structure. Proves transport interchangeability.
- **ClientPipeline**: Client-side tool composition. `add_step()` with `$input.` / `$.` param mapping. `execute()` with confidence tracking and entropy guard. Works without server-side composite definitions.

### UX Overhaul (22 recommendations implemented)

- **4 UI Themes**: Light, Dark (landing-page glass-morphism), Wall Street (Bloomberg terminal amber-on-black, Consolas font), Ubuntu (aubergine + orange, Ubuntu font). Variable-driven CSS — 545 lines replaces 4,441.
- **CSS rewrite**: Clean architecture — design tokens → theme definitions (var(--t-*)) → components. Zero hardcoded colors. Every Bootstrap color class overridden for all themes. WCAG AA contrast verified.
- **Landing page**: Standalone dark-navy theme, gradient hero, 9 feature cards, code snippet, stats bar.
- **Login page**: Standalone dark theme matching landing page. Glass-morphism card.
- **Dashboard**: Welcome bar with transport badges, 4 metric cards, quick actions panel, platform stats, status panel, onboarding wizard.
- **Tools list**: Card-grid view toggle, category filter chips (auto-generated from tool data).
- **AI → LLM**: 5 Bootstrap tabs (Providers, Models, Preferences, Semantic Search, Usage). Add Provider form with type-specific fields (Bedrock: region+AWS keys, Azure: deployment+endpoint, Ollama: host+model, Custom: class+JSON).
- **Composite Builder**: Visual SVG flow diagram (updates live), drag-and-drop step reorder.
- **Studio sub-navigation**: Horizontal chip bar across all 10 studio pages.
- **Help page**: Search-within-help, 6 tutorial cards, 5 v4 feature sections.
- **Active nav highlighting**, button press feedback, loading skeletons, keyboard shortcuts (/ = search, Shift+? = help), skip-to-content link, focus-visible outlines, empty state CTAs with action buttons.
- **0 modals** — all replaced with inline forms/banners.
- **table-enhance.js**: Reusable component — search, pagination, rows-per-page for any table via `data-enhance="true"`.
- **Custom SVG icon set**: 8 icons (sajha, mcp, tool, composite, provider, transport, plugin, agent) as inline sprite.

### Infrastructure

- **Deployment restructured**: `aws/` → `deployment/aws/`, added `deployment/hetzner/` (Docker+Caddy+auto-SSL), `deployment/baremetal/` (systemd+Nginx+certbot).
- **AWS CDK** replaces Terraform: `deployment/aws/cdk/sajha_stack.py` (238 lines Python) — VPC, ECS Fargate, RDS, S3, Secrets Manager, CloudWatch dashboard, auto-scaling.
- **Property-driven configuration**: Version, email, author, github, copyright, all paths (data.dir, logging.dir, config.plugins.dir) — all from `config/application.yml`. Footer shows `© {{ app_copyright_years }} {{ app_name }} | {{ app_author }} · Version {{ app_version }}`.
- **PostgreSQL config**: 3 commented-out examples in application.yml (local, AWS RDS, Hetzner managed).
- **Two SQL scripts only**: `001_schema.sql` (19 tables, CREATE IF NOT EXISTS), `002_seed.sql` (INSERT OR IGNORE). No migrations.

### Bug Fixes

- `tool_schema.html` 500 error: `schema_json` passed as separate pre-serialized string, not mutating MCP format dict.
- `tool_enabled` / `tool_version` passed as separate template variables — MCP `to_mcp_format()` dict never modified.
- Help/About/Docs pages made public (`get_current_user` instead of `require_auth`).
- Login POST indentation bug fixed.
- All `ToolsRegistry.get_instance()` calls replaced with `from sajha.app import tools_registry` (6 occurrences across composite_routes.py and ops_routes.py).
- Theme switcher Chrome fix: `<button>` elements replace `<a href="#">`, event delegation via `addEventListener`.
- Navbar dropdown z-index: `z-index: 1050` prevents dropdown hiding behind page content.
- `color-scheme: dark` for dark themes fixes native `<select>` dropdown colors.

## v5.1.0 (May 2026) — Security Hardening + System Monitor

### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

### Cybersecurity Overhaul

- **bcrypt password hashing** (12 rounds) — replaces plaintext comparison
- **SHA-256 API key hashing** — keys stored as hashes, never plaintext
- **DB-persisted sessions** — user_sessions table with hashed tokens
- **Account lockout** — 5 failed attempts → 15 minute lock
- **Rate limiting** — 5 login attempts per minute per IP (HTTP 429)
- **Security headers middleware** — X-Frame-Options, CSP, HSTS, XSS-Protection, Referrer-Policy, Permissions-Policy
- **CORS restricted** — configurable via SAJHA_CORS_ORIGINS env var (no more wildcard)
- **Cookie hardening** — HttpOnly + SameSite=lax + Secure (auto-detect HTTPS)
- **Request body limit** — 10 MB via RequestSizeLimitMiddleware
- **DuckDB SQL allowlist** — only SELECT/WITH/EXPLAIN permitted (comment-stripping)
- **Passwords never returned** — get_all_users() excludes password_hash
- **No hardcoded credentials** — admin password is bcrypt hash in seed SQL

### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

---

## v4.0.0 (May 2026) — Production Hardening

WebSocket transport, OpenTelemetry, tool versioning, multi-tenancy, plugin system. See git history.

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. See git history.

## v5.1.0 (May 2026) — Security Hardening + System Monitor

### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

### Cybersecurity Overhaul

- **bcrypt password hashing** (12 rounds) — replaces plaintext comparison
- **SHA-256 API key hashing** — keys stored as hashes, never plaintext
- **DB-persisted sessions** — user_sessions table with hashed tokens
- **Account lockout** — 5 failed attempts → 15 minute lock
- **Rate limiting** — 5 login attempts per minute per IP (HTTP 429)
- **Security headers middleware** — X-Frame-Options, CSP, HSTS, XSS-Protection, Referrer-Policy, Permissions-Policy
- **CORS restricted** — configurable via SAJHA_CORS_ORIGINS env var (no more wildcard)
- **Cookie hardening** — HttpOnly + SameSite=lax + Secure (auto-detect HTTPS)
- **Request body limit** — 10 MB via RequestSizeLimitMiddleware
- **DuckDB SQL allowlist** — only SELECT/WITH/EXPLAIN permitted (comment-stripping)
- **Passwords never returned** — get_all_users() excludes password_hash
- **No hardcoded credentials** — admin password is bcrypt hash in seed SQL

### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

---

*SAJHA MCP Server — Changelog*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*

## v5.1.0 (May 2026) — Security Hardening + System Monitor

### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

### Cybersecurity Overhaul

- **bcrypt password hashing** (12 rounds) — replaces plaintext comparison
- **SHA-256 API key hashing** — keys stored as hashes, never plaintext
- **DB-persisted sessions** — user_sessions table with hashed tokens
- **Account lockout** — 5 failed attempts → 15 minute lock
- **Rate limiting** — 5 login attempts per minute per IP (HTTP 429)
- **Security headers middleware** — X-Frame-Options, CSP, HSTS, XSS-Protection, Referrer-Policy, Permissions-Policy
- **CORS restricted** — configurable via SAJHA_CORS_ORIGINS env var (no more wildcard)
- **Cookie hardening** — HttpOnly + SameSite=lax + Secure (auto-detect HTTPS)
- **Request body limit** — 10 MB via RequestSizeLimitMiddleware
- **DuckDB SQL allowlist** — only SELECT/WITH/EXPLAIN permitted (comment-stripping)
- **Passwords never returned** — get_all_users() excludes password_hash
- **No hardcoded credentials** — admin password is bcrypt hash in seed SQL

### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

---

## v5.1.0 (May 2026) — MCP 2025-11-25 Full Compliance

Upgraded from MCP protocol version 2025-06-18 to 2025-11-25. All 19 spec changes implemented.

### Major Features (from MCP 2025-11-25)

- **Tasks (SEP-1686)**: Async task tracking for long-running MCP requests. `TaskManager` with create/get/list/cancel. States: working → input_required → completed/failed/cancelled. Polling-based result retrieval. MCP methods: `tasks/get`, `tasks/list`, `tasks/cancel`.
- **Elicitation (SEP-1330, SEP-1036)**: Server-initiated user input requests. Two modes: Form (structured JSON Schema) and URL (redirect to OAuth/consent page). `ElicitationManager` with create_form/create_url/respond/cancel. MCP method: `elicitation/respond`.
- **Sampling with Tools (SEP-1577)**: Server-initiated LLM calls with tool definitions. `SamplingManager` supports `tools` and `toolChoice` parameters per spec. Enables server-side agent loops.
- **Tool Icons (SEP-973)**: Icon metadata in tools/list responses. Supports `{"type":"url","url":"..."}` and `{"type":"emoji","emoji":"📊"}`. Configured per-tool in JSON config.
- **Origin Validation (Minor 3)**: Streamable HTTP endpoints respond with HTTP 403 for invalid Origin headers. `validate_origin()` in SSE route.
- **Tool Execution Errors (Minor 5)**: Input validation and execution errors now return `{"isError": true}` in tool result content (Tool Execution Error) instead of JSON-RPC Protocol Errors. Enables model self-correction.
- **Server Description (Minor 2)**: `description` field added to `serverInfo` in initialize response.
- **notifications/cancelled**: Client can cancel pending requests via `notifications/cancelled` method.
- **JSON Schema 2020-12 (Minor 10)**: Declared as default dialect for schema definitions.

### Updated Capabilities Declaration

```json
{
  "protocolVersion": "2025-11-25",
  "capabilities": {
    "tools": {"listChanged": true},
    "prompts": {"listChanged": true},
    "resources": {"subscribe": true, "listChanged": true},
    "logging": {},
    "completions": {},
    "elicitation": {"form": {}, "url": {}},
    "sampling": {"tools": true},
    "tasks": {"experimental": true}
  }
}
```

### Exception Handling Overhaul

- 42 bare `except:` blocks → `except Exception as e:` + logging
- 21 swallowed exceptions → added logging with `exc_info=True`
- 280+ `exc_info=True` additions for full stack traces in log files
- Before: 11 good / 304 issues. After: 308 good / 102 issues.

### Files Added

- `sajha/core/mcp_2025_11_25.py` — Tasks, Elicitation, Sampling, Icons, Origin validation
