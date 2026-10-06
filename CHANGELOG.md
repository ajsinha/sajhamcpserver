# SAJHA MCP Server — Changelog

Newest first. The current version is `app.version` in `config/application.yml`.

## Unreleased

MCP authorization (OAuth 2.1), MCP Apps and `x-mcp-header`: the items 6.0.0 deferred. Details: [OAuth Guide](docs/protocol/OAuth%20Guide.md), [MCP Apps and Headers Guide](docs/protocol/MCP%20Apps%20and%20Headers%20Guide.md), [MCP 2026-07-28 Compliance §4](docs/protocol/MCP%202026-07-28%20Compliance.md).

### Security hardening (behaviour changes)
Details: [Security Model](docs/security/Security%20Model.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md).
- **Secrets.** `config/application.yml` no longer ships JWT or session secrets. Empty secrets are generated once into `data/secrets/server_secrets.json` (mode 0600, git-ignored; `auth.secrets_file`), so existing JWTs signed with the old placeholder stop working and users sign in again. A secret (or `mcp.mrtr.state_secret`) set to any placeholder SAJHA ever shipped stops start-up. The MRTR secret derives from the persisted session secret, so `requestState` survives restarts.
- **Tool access everywhere.** One policy (`sajha/auth/access.py`) for REST, MCP (both eras, SSE, WebSocket), A2A and async: users by role permissions (`read` lists, `execute` runs), API keys by their tool access mode (allowlist, denylist and regex are now enforced, and keys no longer get 403 on `POST /api/tools/execute`), external OAuth identities without an account by a role named `api_consumer` (none by default). **Anonymous MCP and A2A callers see and run no registry tools by default**: list them in `mcp.anonymous.tools`, grant a role with `mcp.anonymous.role`, or refuse anonymous callers with `mcp.anonymous.enabled: false`. MCP `logging/setLevel` changes the server log level only for admins.
- **A2A.** Tool runs need execute access; tasks are visible only to their creator.
- **Async execution.** Needs admin or `async:execute` plus tool access; file delivery only inside `async.delivery.file.base_dir`; webhooks only to `async.delivery.webhook.allowed_urls` (empty = none) with the CIMD SSRF guard; tasks scoped to their owner. `async.*` and `shell.*` keys now take effect (they were dead code in `config.py`).
- **Admin-only endpoints.** `POST /api/logging/setLevel`, `GET /api/ws/sessions`, `GET /api/replay/recent`, `GET /api/replay/tool/{tool}`, `GET /api/reports/users/activity`, the tool configuration page; the shell endpoints need admin or `shell:execute`.
- **Sign-in.** Account lockout (`auth.login.max_failed_attempts`, `lockout_minutes`; 423) and a failed-sign-in limit per IP (`auth.login.ip_max_failures`, `ip_window_seconds`; 429) on the web form, `POST /api/auth/login` and the OAuth sign-in. The old 5-per-minute limit on the JSON login (which counted successful logins) is gone.
- **Passwords.** Change-password page `/account/password` and `POST /api/auth/change-password`; admin reset `POST /api/admin/users/{uid}/password`; password policy (8+ characters, no well-known defaults); `users.must_change_password` (migration `003_password_policy.sql`, also checked at start-up) with a banner for the seed `admin`/`admin123`, admin-set passwords and default passwords. `POST /api/admin/users/create` now requires a password.
- **Errors.** Unauthenticated API/JSON requests (`/api`, `/mcp`, `/a2a`, `/admin/studio`, `/oauth`, any non-GET, or `Accept: application/json`) get a JSON 401 instead of a redirect; 403s on those are JSON too.
- **WebSocket.** An invalid `token`/`api_key` closes the connection (1008) instead of falling back to anonymous.
- **Config.** `.env` names that are not settings no longer stop start-up (`extra='ignore'`; unknown `SAJHA_*` names are logged). Storage env vars (`SAJHA_STORAGE_BACKEND`, `SAJHA_S3_BUCKET`, `AZURE_STORAGE_CONNECTION_STRING`, ...) now override `application.yml`. `ai.tool_search.enabled`/`persist` are parsed as booleans. New `alpha_vantage.api.key` (`ALPHA_VANTAGE_API_KEY`). `sajha/auth/password.py` no longer raises `NameError` on an invalid hash.
- **nginx** (`deployment/baremetal/nginx.conf`): `/mcp` and `/api/mcp` are proxied unbuffered (SSE responses to POST). Compose files no longer pass placeholder secrets.

### Observability: Prometheus, OpenTelemetry, usage and cost, alerts
Details: [Observability](docs/architecture/Observability.md), [Tutorial 16](docs/tutorials/TUTORIAL_16_metrics_costs_and_alerts.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#observability).
- **`GET /metrics`** in the Prometheus text format, written by SAJHA (no `prometheus_client`): HTTP requests by route template/status with a latency histogram; MCP requests by era, method and outcome; tool calls by tool, group and outcome with latency, cache hits and breaker state; LLM calls, tokens and cost by provider and model; ask runs by `stopped_by`; auth failures and lockouts; sandbox runs; federated upstream health (when federation runs); process and Python metrics. Protected by `observability.metrics.auth` (`admin` default, `token` with `SAJHA_OBSERVABILITY_METRICS_TOKEN`, `none`); optional separate listener (`observability.metrics.port`); label cardinality controls (`tool_label`, `max_series`). With several workers and a shared `state.backend`, every scrape merges all workers under a `worker` label.
- **OpenTelemetry** (opt-in, `observability.otel.*`, standard `OTEL_*` honoured): OTLP traces and metrics; spans HTTP → MCP → tool → LLM, continuing `traceparent` from the HTTP header and from MCP `params._meta`. The SDK no longer installs a tracer provider with no exporter when tracing is off.
- **Usage & cost page** (`/monitoring/usage`, Tools → Monitor): tokens and cost by user, API key, role, provider, model and day; tool calls, error rates and p50/p95/p99 latency by tool; budgets against today's usage; date range, filters, CSV export. Administrators see everyone, others their own calls. Backed by a new usage ledger table `obs_usage_events` (created on first use; `observability.usage.*`), written in batches off the request path. API: `/api/observability/usage`, `/api/observability/usage.csv`, `/api/observability/alerts`, `/api/observability/status`.
- **Alerts.** `observability.alerts[]` rules (metric, threshold, window, cooldown; log, webhook or email) evaluated in the process; webhooks only to `observability.alerts_webhook.allowed_urls` through the shared SSRF guard. `deployment/observability/` ships a Prometheus scrape job, alerting rules and a Grafana dashboard.
- **Fixed:** `/api/metrics` and `/api/metrics/tools` were always empty (nothing fed the collector); `execute_with_tracking` now does. The collector's two built-in log-only alert rules are replaced by the configurable rules.

### Sandboxed user code (behaviour change)
Details: [Sandbox](docs/architecture/Sandbox.md), [Tutorial 14](docs/tutorials/TUTORIAL_14_sandboxed_studio_tools.md).
- **Studio Python code tools and script tools no longer run in the server.** The registry loads them as sandboxed stand-ins (`sajha/sandbox/tools.py`): a Python tool's module is parsed for its schemas but never imported, a script runs per call in a fresh sandbox. No server environment (secrets only by name through `sandbox.secrets_allowlist`, never `SAJHA_*`), a temp work dir, CPU/memory/file/process/output/time limits, no network unless the tool's `sandbox` block allowlists hosts. Callers (MCP, REST, A2A, Ask SAJHA) see the same contract; a sandboxed Python tool cannot import `sajha`, read files outside its work dir or use the network by default, and a script's `working_directory` is ignored. `sandbox.enforce_for_generated_tools: false` restores in-process loading. Built-in tools and Studio's template creators (REST, DB query, Power BI, LiveLink, SharePoint, OLAP) stay in-process.
- **Backends** (`sandbox.default_backend`): `subprocess` (default; on Linux the runner adds user/PID/network namespaces, rlimits, Landlock and seccomp, each reported), `bwrap`, `nsjail`, `docker` (`--network none`, read-only root, limits, `runtime: runsc` for gVisor), or `auto`. The JSON runner protocol is `sajha/sandbox/runner.py`.
- **The admin shell** (`/api/shell/python`, `/api/shell/bash`) runs through the same sandbox after its filters; `shell.python.memory_limit_mb` is now applied and `tier` reads `sandbox:<backend>`.
- **Status:** `GET /api/sandbox/status` (admin, live probe of what is enforced), `sandbox` in `GET /health`, the backend in `/api/shell/capabilities`; the Python and script creator pages show the policy a new tool gets. Studio writes a `sandbox` block into the configs it generates.
- New `sandbox.*` keys ([Configuration Reference](docs/getting-started/Configuration%20Reference.md#sandbox)); escape tests per installed backend in `tests/test_sandbox.py`.

### Several workers and hosts: shared state (`state.backend`)
Details: [Scaling and State](docs/architecture/Scaling%20and%20State.md), [Tutorial 13](docs/tutorials/TUTORIAL_13_run_sajha_on_several_workers.md), [Configuration Reference](docs/getting-started/Configuration%20Reference.md#state).
- **State store** (`sajha/core/state/`): one interface with three backends. `memory` is the default, and with it a single process behaves as before. `redis` uses the optional `redis` package and Redis pub/sub. `database` uses SAJHA's database or `state.database.url`, in the tables `sajha_state` and `sajha_state_events`, with polled pub/sub. New keys: `state.backend`, `state.key_prefix`, `state.redis.url` (`SAJHA_STATE_REDIS_URL`), `state.database.url`, `state.database.poll_interval_ms`, `state.tasks.durable`.
- **Moved into it:** OAuth pending consents, authorization codes (redemption is atomic and fixes the refresh family), refresh tokens and revoked families, DCR clients; 2025-11-25 sessions (a client's answer to a server request is relayed to the worker holding the stream); legacy HTTP+SSE queues (relayed); 2026-07-28 task records; rate limits and the sign-in IP throttle; LLM token usage and daily budgets; async-executor task records. Change-bus events reach `subscriptions/listen`, legacy SSE and WebSocket subscribers on every worker. Caches, circuit breakers, metrics and WebSocket sessions stay per worker on purpose: the inventory and the reasons are in the design document.
- **Durable tasks.** With a shared backend (`state.tasks.durable: auto`), MCP task records are kept in the database. They survive a restart and any worker reads, cancels or answers them. `tasks/update` on another worker rebuilds the runner from the stored call spec. A `working` task whose worker stopped heart-beating is reported `failed` and never re-run.
- **Operations.** `GET /health` has a `state` object (backend, reachable, tasks, worker ID). Start-up stops when a shared backend does not answer, and warns when several workers (`WEB_CONCURRENCY`, `UVICORN_WORKERS`, `SAJHA_WORKERS`, `--workers`) run on `memory`. `run_server.py --workers N` now starts N uvicorn workers through the `sajha.app:create_app` factory. New `mcp.auth.builtin.signing_key_pem` (env `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`) gives hosts that do not share a data directory the same OAuth signing key.
- **Deployment.** The Hetzner and local AWS compose files have an optional `scale` profile with Redis. The AWS CDK stack sets `SAJHA_STATE_BACKEND=database` for its several Fargate tasks, and the image installs `redis`.
- **Tests.** `tests/test_state_store.py` runs the store contract and the migrated components against memory, fakeredis, a real Redis (`SAJHA_TEST_REDIS_URL`) and SQLite. `tests/test_state_multiworker.py` starts two server processes that share a backend: an OAuth code issued on A is redeemed on B, a task created on A is read and cancelled on B, sign-in failures are counted across both, and a change on A reaches a listen stream on B. It also starts `--workers 2`. The conformance server suites are unchanged (43/43 for 2025-11-25 with 0.1.16, 152/152 for 2026-07-28 with 0.2.0-alpha.12) on the memory, redis and database backends.

### Kubernetes: production image, Helm chart, Kustomize manifests
Details: [Kubernetes Deployment](docs/getting-started/Kubernetes%20Deployment.md), [Tutorial 17](docs/tutorials/TUTORIAL_17_deploy_sajha_on_kubernetes.md).
- **`Dockerfile`** (repository root) and `.dockerignore`: multi-stage, venv copied into a slim runtime, UID 10001 under `tini`, `HEALTHCHECK` on `/health`, read-only-root ready (writes only `data`, `logs`, `temp`, `config`, `sajha/tools/impl`, `/tmp`). Build args `EXTRAS` (`redis` by default; `s3`, `azure`, `gcs`, `otel`), `WITH_OPENBB` (off), `PLAYGROUND_ASSETS` (vendors Pyodide). Secrets, `data/`, tests and the SDK are kept out of the image.
- **Helm chart `charts/sajha`** with `values.schema.json`: Deployment with a seed init container (seeds writable config volumes, deep-merges `config.overrides` into `application.yml`, waits for Redis and PostgreSQL), Service, two Ingress objects (streaming paths `/mcp`, `/api/mcp`, `/api/ai/ask` unbuffered with one-hour timeouts), HPA, PodDisruptionBudget, optional single-node Redis, NetworkPolicies with an egress allowlist hook, ServiceMonitor with bearer-token auth, `helm test`. One Secret (generated once and kept, or `secrets.existingSecret`) gives every pod the same JWT secret, session secret, OAuth signing key and metrics token. The chart refuses multi-pod settings that would split state (SQLite, `state.backend: memory`, `ReadWriteOnce` volumes).
- **Kustomize** `deployment/k8s/` (base, dev and prod overlays) rendered from the chart by `deployment/k8s/render.py`; `tests/test_k8s_deployment.py` checks the chart version against `app.version`, the values against the schema, the seed step, and (with Helm installed) that the manifests are up to date.
- **Verified** on kind (Kubernetes 1.33, ingress-nginx, kindnet NetworkPolicy): `helm lint`, kubeconform on default and full-feature renders and both overlays; three pods on Redis and PostgreSQL behind the streams Ingress without session affinity passed the 2025-11-25 suite (`@modelcontextprotocol/conformance` 0.1.16, 43 passed, 0 failed), the 2026-07-28 suite (0.2.0-alpha.12, 152 passed, 0 failed) and the ten tasks-extension scenarios (44 passed, 0 failed); all pods served one OAuth key id.
- **AWS:** the CDK stack now creates generated `sajha/<env>/jwt` and `sajha/<env>/session` secrets and passes them to every Fargate task (`SAJHA_JWT_SECRET`, `SAJHA_SECRET_KEY`; it previously referenced a `jwt_secret` key nobody created and passed no session secret), and `-c oauth_signing_key_secret=<name>` passes a stored PEM as `SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`. The stack synthesizes again (an output reused the `LogGroup` construct id). `deployment/aws/Dockerfile` and the AWS compose file build from the repository root (the old paths did not resolve).

### OAuth 2.1 for `/mcp` (off by default)
- `mcp.auth.mode`: `off` (default) | `optional` | `required`.
- Resource server: RFC 9728 protected-resource metadata, `WWW-Authenticate` with `resource_metadata` and `scope`, audience-bound RS256 access tokens, scopes `mcp:read` / `mcp:tools`.
- Authorization server: built in (backed by SAJHA users; authorization code + PKCE S256, RFC 9207 `iss`, Client ID Metadata Documents with SSRF guards, rotating refresh tokens with reuse detection, CSRF-protected consent), or an external issuer validated through its JWKS (`mcp.auth.authorization_server`).
- API keys and SAJHA JWTs keep working in every mode. The signing key is generated under `data/oauth/` (git-ignored).
- Conformance `authorization` suite 3/3 for both spec versions; the server suites are unchanged (43/43 and 152/152); the official SDK completes the OAuth flow end to end.

### MCP Apps (`io.modelcontextprotocol/ui`)
- Tools bind `ui://` views, served by `resources/read` as `text/html;profile=mcp-app` (`mcp.apps.enabled`, default on). Example view for `calc_loan_amortization`.

### `x-mcp-header`
- Validated when a tool schema is loaded (invalid annotations are dropped with a warning); `Mcp-Param-Symbol` on the quote tools.

### The `sajha` command line and MCP over stdio
- **stdio transport** (`sajha/cli/stdio.py`; `sajha serve --stdio`, `python run_server.py --stdio`): desktop clients (Claude Desktop, Claude Code, IDEs) launch SAJHA as a subprocess. Both eras on one connection (a client in auto mode probes `server/discover` and falls back to `initialize`), newline-delimited JSON-RPC, nothing but protocol on stdout (fd 1 is pointed at stderr), `notifications/cancelled` honoured on both paths, `list_changed` pushed after `initialize`. One caller per process: `--user` / `SAJHA_STDIO_USER`, `--api-key` / `SAJHA_API_KEY`, else anonymous; mapped through the usual tool access. Loads only what MCP needs (no web UI; the LLM gateway with `--with-ai`). Tested with the official SDK client (`StdioServerParameters`) in `legacy` and `auto` modes; the conformance suite's server runner takes only `--url`, so it does not run over stdio.
- **`sajha` CLI** (`clientsdk/sajhaclient/cli/`, console script from `pip install 'sajhaclient[cli]'`): `login` (token stored 0600 in `~/.config/sajha`), profiles, `tools list|show|call` (schema-typed `--arg`, `--json`), `prompts list|get`, a streamed `ask`, `studio deploy|delete`, `federation list|add|refresh|remove`, `health`, `config show`, `completion bash|zsh|fish`, `serve`; `--server`/`--api-key`, `SAJHA_URL`/`SAJHA_API_KEY`; exit codes 0-6. Details: [Command Line](docs/clients/Command%20Line.md), [Tutorial 15](docs/tutorials/TUTORIAL_15_sajha_cli_and_claude_desktop.md).

### Python Playground
- **`/playground`** (signed-in users; **Tools → Python Playground**, a dashboard quick action): a small notebook running Python in the browser with Pyodide (WebAssembly) in a Web Worker. Cells with a vendored CodeMirror 6 editor (Python highlighting, line numbers, Ctrl/Cmd+Enter), Run / Run all / Stop / Reset, stdout, stderr in red, REPL-style last-expression display, pandas DataFrames as tables, matplotlib figures inline, `display()`, examples (numpy, pandas, matplotlib, SciPy, scikit-learn, SAJHA tools, Ask SAJHA), save/load in browser storage, `.py` download, `.py`/`.ipynb` upload. Packages load on first import (`loadPackagesFromImports`); micropip installs pure-Python wheels from PyPI (`playground.allow_pypi`).
- **`import sajha`** in the playground: `sajha.tools()`, `sajha.schema()`, `sajha.call(name, **args)` (through `POST /api/tools/execute`) and `sajha.ask()` (through `POST /api/ai/ask`), with the user's session, so access control and limits are the server's usual ones. New `GET /api/playground/tools`. MCP Studio's Python code creator has **Open in playground**.
- **Assets.** `scripts/fetch_pyodide.py` vendors a pinned Pyodide release (core archive checked against GitHub's published SHA-256, every wheel against `pyodide-lock.json`) into `sajha/web/static/vendor/pyodide/` (git-ignored); `playground.assets: cdn` loads it from cdn.jsdelivr.net instead. Missing assets show an administrator hint. New keys `playground.enabled`, `playground.assets`, `playground.pyodide_version`, `playground.allow_pypi`.
- **Headers, playground only.** `/playground` sends COOP `same-origin` and COEP `require-corp` (cross-origin isolation, so Stop interrupts Python through a `SharedArrayBuffer`); its worker's CSP alone allows `'wasm-unsafe-eval'` (and the CDN or PyPI origins when configured). Every other route keeps the self-only policy. Code runs only in the browser. Details: [Python Playground](docs/getting-started/Python%20Playground.md), [Tutorial 12](docs/tutorials/TUTORIAL_12_python_playground.md).

### Ask SAJHA
- **Ask SAJHA** (`/ask`, AI menu and dashboard): a chat over `POST /api/ai/ask` that streams each step (shortlist, tool calls and results, answer, confidence), shows the tool chain as expandable chips with sources and caveats, asks before a destructive call, and draws the chain live on the tool sky. Model picker, a *Mock model active* pill, Stop, per-tab history. Details: [Intelligence Layer](docs/architecture/Intelligence%20Layer.md#using-ask-sajha), [Tutorial 10](docs/tutorials/TUTORIAL_10_ask_sajha.md).
- The landing page's constellation drawing moved to `sajha/web/static/js/constellation.js`, shared by both pages; the landing page is unchanged.

### Federation (off by default)
SAJHA can front other MCP servers ("upstreams") and re-expose their tools, and optionally prompts and resources, as its own. Details: [Federation](docs/architecture/Federation.md), [Tutorial 11](docs/tutorials/TUTORIAL_11_federate_an_mcp_server.md).
- A federated tool is a registry tool named `<prefix>__<tool>` (`sajha/federation/`, `FederatedTool`): listed by `tools/list` on both eras, on the Tools page, in Ask SAJHA's tool search, composites and A2A; calls pass through the same access policy, cache, circuit breaker (one per upstream), metrics and usage events as native tools, plus an optional per-upstream rate limit.
- Upstreams over Streamable HTTP (2026-07-28 or 2025-11-25, through the official `mcp` SDK v2 client), legacy SSE, or stdio (`federation.allow_stdio`, off). Credentials by secret reference: bearer, API-key header, OAuth client credentials.
- Discovery at start-up (bounded wait), periodically, on the upstream's `subscriptions/listen` or `list_changed` notifications, and on demand. Results, schemas, progress and cancellation pass through; an upstream's MRTR `InputRequiredResult` reaches 2026-07-28 callers.
- Security: approval before exposure (`federation.require_approval`, on), re-approval when an approved definition changes, screening of upstream text for injection markers, the SSRF guard on upstream and token URLs (`federation.allow_localhost`, `allow_private_networks`, `allowed_hosts`), no secrets in config or logs, admin-only routes with audit.
- Admin page **Admin → Federation** (`/admin/federation`) and its API under `/api/federation/`; admin-added upstreams and approvals persist through the storage backend (`federation.state_path`). Example upstream: `sajha/examples/federation/units_server.py`. Tests: `tests/test_federation.py`.

### How SAJHA compares
- **`/comparison`** (Help menu, help catalog under Reference, linked from About): SAJHA next to FastMCP, IBM ContextForge, Docker MCP Gateway, Microsoft MCP Gateway, Kong AI Gateway, Cloudflare, Composio, Zapier MCP and Smithery on protocol, security, tools, operations and deployment. Every competitor cell is a verdict (Yes, Partial, No or Unknown) with a note, a source and an as-of date; SAJHA's column follows its code, with its numbers read from the running registries. The data has one home, `sajha/web/competitive.py`, and `tests/test_competitive.py` checks it.

### Fixes
- `/login?next=` open redirect.
- Path traversal in `sajha://data` resources.
- WebSocket authentication called a method that did not exist.
- Security headers no longer overwrite stricter per-route values.
- **FBI tools rewritten for the current Crime Data Explorer API** (every call returned 404). All nine `fbi_` tools keep their names and now call the documented `api.usa.gov/crime/fbi/cde` paths (`/summarized/...`, `/agency/byStateAbbr/{state}`, `/pe/{state}/{ori}`, `/nibrs/...`); input and output schemas changed to match (config `version` 3.0.0). `fbi_search_agencies` now needs `state` (the API lists agencies per state; there is no free-text search); `fbi_get_offense_data` returns NIBRS victim/offender/weapon/location breakdowns and accepts only offenses with a NIBRS code; `fbi_get_participation_rate` reports population coverage (agency counts are no longer published); `fbi_get_crime_trend` makes one request for the whole range. Key errors (403) and rate limits (429, including the shared `DEMO_KEY`) name `FBI_API_KEY` / `fbi.api.key`; timeouts are configurable per tool (`timeout`, default 30 s). Details: [FBI Tool Reference Guide](docs/tools/public-data/FBI%20Tool%20Reference%20Guide.md).
- **OLAP `customer_analytics` and `inventory_analysis` datasets now work.** The sample data adds the `customer_data` view (one row per customer and order; customers gain `city`, `state` and `tier`) and the `inventory_data` table (stock snapshot per product and distribution centre), created with the rest of the sample schema and, when `sales_data` already exists, added only if missing. `customer_analytics` no longer declares a join to `sales_data` (its `ON` clause referenced a table it had aliased away). Details: [OLAP Analytics Tool Reference Guide](docs/tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md).

### Documentation
- Documentation reorganised under `docs/` by topic, with one owning document per topic, a root `GLOSSARY.md` and `CLAUDE.md` documentation conventions. Internal point-in-time reports moved to `docs/archive/`.
- [Extending the Intelligence Layer](docs/architecture/Extending%20the%20Intelligence%20Layer.md): writing a provider, a model and a real planner, with tested examples in `sajha/examples/intelligence/` (`tests/ai/test_extension_examples.py`) and a proposed `Planner` extension point.


## v6.0.0 (October 2026) — MCP 2026-07-28, dual-era

SAJHA now serves the stateless **MCP 2026-07-28** protocol and the session-based **2025-11-25**
protocol on the same `/mcp` endpoint. The request's `_meta` decides which: a protocol version
there means stateless, `initialize` means a 2025-11-25 session. Both are verified in CI by the
official conformance suite (`.github/workflows/mcp-conformance.yml`):
- **2026-07-28:** 40/40 scenarios, 152/152 checks; tasks extension 44/44.
- **2025-11-25:** 32/32 scenarios, 43/43 checks.

### 2026-07-28 (new)
- `server/discover`.
- Version, capabilities and log level read from `_meta` on every request.
- Required `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers (-32020); version errors are -32022.
- `resultType` and `ttlMs`/`cacheScope` on results.
- `GET`/`DELETE /mcp` return 405 for these clients.
- Streamed `tools/call` with progress and log notifications. Closing the stream cancels the call.
- `subscriptions/listen`, fed by a change bus over the tool and prompt registries. The legacy `/mcp/sse` and `/mcp/ws` streams receive the same events.
- Multi Round-Trip Requests with an HMAC-signed `requestState`, and elicitation through them. Optional confirmation for destructive tools: `mcp.confirm_destructive_tools`.
- Tasks extension `io.modelcontextprotocol/tasks`. Tools opt in with `execution.taskSupport`.
- Tool context API (`report_progress`, `report_log`, `is_cancelled`) for long-running tools.

### Client SDK
- `SajhaMCPClient` / `SajhaMCPSyncClient` (from 5.4.0) negotiate 2026-07-28 automatically through the official SDK (`pip install sajhaclient[mcp]`).

### Compatibility
- 2025-11-25 clients are unaffected.
- `v5.4.0` (also tagged `mcp-2025-11-25`) remains the last 2025-only release.

## v5.4.0 (October 2026) — MCP 2025-11-25, verified

This release makes SAJHA's MCP 2025-11-25 support match what it claims, proven by the official
MCP conformance suite 0.1.16: **32/32 server scenarios, 43 checks passed, 0 failed**, plus the
official Python SDK 2.3.0 client. It is tagged `v5.4.0` and `mcp-2025-11-25`.

### Protocol and transport
- `initialize` negotiates the version (2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05) instead of ignoring the client's.
- Streamable HTTP on `/mcp`:
  - `Mcp-Session-Id` sessions; `DELETE /mcp` ends a session.
  - The `MCP-Protocol-Version` header is validated.
  - Notifications get 202 with no body; JSON-RPC batches get 400.
  - `GET /mcp` returns 405 to Streamable HTTP clients.
- `Origin` allow-list (`mcp.allowed_origins`, env `SAJHA_MCP_ALLOWED_ORIGINS`) with 403 for other origins.
- The legacy 2024-11-05 HTTP+SSE flow now delivers responses over its stream.
- MCP tool calls run off the event loop. They now use the same path as the REST API: disabled tools are refused, and arguments, cache, circuit breaker and metrics all apply.

### Tools, prompts, resources
- `tools/list` emits `title`, `outputSchema`, `annotations` and `icons[]`.
- `tools/call` returns JSON text plus `structuredContent`. Turn this off with `mcp.tools.advertise_output_schema: false`.
- `prompts/list` includes arguments, and prompts responses carry their `id`.
- `prompts/get` returns real messages.
- Errors are proper JSON-RPC errors, not error objects inside `result`.

### Honesty fixes (breaking)
- Server capabilities no longer advertise client-only `elicitation`/`sampling`, or a `tasks` shape that never ran. `listChanged` and `subscribe` are `false` until notifications exist. Custom keys moved under `experimental.sajha`.
- Removed `/.well-known/openid-configuration`, `/.well-known/oauth-protected-resource` and `/.well-known/oauth-client/{id}`. They advertised OAuth endpoints that did not exist.
- `ping` returns `{}`. Unknown resources return `-32002`. Tool icons are `icons[]`.

### Also
- Opt-in conformance fixtures: `mcp.conformance_fixtures` / `SAJHA_MCP_CONFORMANCE_FIXTURES=true`.
- Client SDK: `SajhaMCPClient`, a wrapper over the official `mcp` SDK v2 (`pip install sajhaclient[mcp]`), with SAJHA's REST, A2A and WebSocket extras.
- Fixed: `POST /api/auth/login` 500; prompt pages' Save/Delete/Test endpoints; prompt detail 500.
- WCAG AA contrast pass across all screens and themes.

### Design: MAYA design language and themes

SAJHA now uses MAYA's look and MAYA's four themes, with the same names and the same colour values.

- **Themes:** Crimson (stored as `light`), Dark, Blue and Green replace Light / Dark / Wall Street / Ubuntu.
  - The palette menu matches MAYA's: a swatch and a name for each theme.
  - With nothing stored, the page follows the system's light/dark setting.
  - A stored Light or Dark choice carries over; a stored Wall Street or Ubuntu choice resets to the default.
- **Tokens:** `static/css/tokens.css` is MAYA's token set, renamed from `--maya-*` to `--sajha-*`. It is the only place colours are defined.
  - `style.css` maps its `--t-*` roles onto these tokens once and re-points Bootstrap's variables at them.
- **Chrome:**
  - A fixed gradient top bar with mega-menu panels (`common/_nav.html`).
  - Gradient `h1`s, soft-shadow 14px cards, alerts with a left rule, gradient primary buttons.
  - Hero banners and MAYA's footer.
  - The system-ui font at 14px.
- **Pages:**
  - Sign-in stands on the theme gradient.
  - The landing page is laid out with MAYA's `lp2-*` sections.
  - The Studio pages share `_studio_theme.html`.
  - Help and About use MAYA's hero, card and box classes.
  - Charts read their colours from the tokens (`window.SajhaChartTheme`) and re-colour when the theme changes.

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

## v5.1.0 (May 2026) — Security hardening, System Monitor, Composition Framework, MCP 2025-11-25

Three bodies of work were released under 5.1.0. Several MCP claims below were later found to be inaccurate and were corrected in v5.4.0 (see its "Honesty fixes").

### Security hardening and System Monitor

#### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

#### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

#### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

#### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

#### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

#### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

#### Cybersecurity Overhaul

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

#### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

#### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

#### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

### Composition Framework and UX overhaul

Category-theory-inspired composition, 4 UI themes, full UX redesign, CSS rewrite.

#### Composition Framework (from "On the Composability of Intelligence")

- **Kleisli Composition** (`sajha/core/composition.py`): Every tool execution wrapped in `StepResult` envelope carrying value, error, trace, duration, and confidence. Errors short-circuit the pipeline. Traces accumulate across steps. Confidences compound via Giry bind.
- **ParamLens**: Lens-based parameter projection. Child tools receive ONLY mapped fields via `$.field` / `$input.field` syntax. Prevents accidental coupling to upstream output structure.
- **EntropyGuard**: Cumulative confidence tracking with parallel-aware model. Sequential steps multiply (Giry bind). Parallel steps use weakest-link (min). Mixed pipelines combine both. `entropy_threshold` per composite — refuses execution if uncertainty exceeds limit.
- **Tool Confidence Registry**: 497 tools classified by reliability — calculators 1.0, FRED 0.95, FMP 0.93, web crawlers 0.80. Composite results include `_composition.confidence` and `_composition.entropy_bits`.
- **CompositeTool.execute()** rewritten to use composition framework. All composites now return `_composition` metadata block with confidence, entropy, trace, and guard status.

#### Client SDK Enhancements

- **Transport Coalgebra**: `TransportCoalgebra` abstract class with `step(input) → (output, new_state)`. `HTTPTransport`, `SSETransport`, `WSTransport` implementations. Enables runtime transport hot-swap.
- **bisimilar()**: Behavioral equivalence testing. Runs same operation sequence against two transports, verifies identical output structure. Proves transport interchangeability.
- **ClientPipeline**: Client-side tool composition. `add_step()` with `$input.` / `$.` param mapping. `execute()` with confidence tracking and entropy guard. Works without server-side composite definitions.

#### UX Overhaul (22 recommendations implemented)

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

#### Infrastructure

- **Deployment restructured**: `aws/` → `deployment/aws/`, added `deployment/hetzner/` (Docker+Caddy+auto-SSL), `deployment/baremetal/` (systemd+Nginx+certbot).
- **AWS CDK** replaces Terraform: `deployment/aws/cdk/sajha_stack.py` (238 lines Python) — VPC, ECS Fargate, RDS, S3, Secrets Manager, CloudWatch dashboard, auto-scaling.
- **Property-driven configuration**: Version, email, author, github, copyright, all paths (data.dir, logging.dir, config.plugins.dir) — all from `config/application.yml`. Footer shows `© {{ app_copyright_years }} {{ app_name }} | {{ app_author }} · Version {{ app_version }}`.
- **PostgreSQL config**: 3 commented-out examples in application.yml (local, AWS RDS, Hetzner managed).
- **Two SQL scripts only**: `001_schema.sql` (19 tables, CREATE IF NOT EXISTS), `002_seed.sql` (INSERT OR IGNORE). No migrations.

#### Bug Fixes

- `tool_schema.html` 500 error: `schema_json` passed as separate pre-serialized string, not mutating MCP format dict.
- `tool_enabled` / `tool_version` passed as separate template variables — MCP `to_mcp_format()` dict never modified.
- Help/About/Docs pages made public (`get_current_user` instead of `require_auth`).
- Login POST indentation bug fixed.
- All `ToolsRegistry.get_instance()` calls replaced with `from sajha.app import tools_registry` (6 occurrences across composite_routes.py and ops_routes.py).
- Theme switcher Chrome fix: `<button>` elements replace `<a href="#">`, event delegation via `addEventListener`.
- Navbar dropdown z-index: `z-index: 1050` prevents dropdown hiding behind page content.
- `color-scheme: dark` for dark themes fixes native `<select>` dropdown colors.

### MCP 2025-11-25 upgrade

Upgraded from MCP protocol version 2025-06-18 to 2025-11-25. All 19 spec changes implemented.

#### Major Features (from MCP 2025-11-25)

- **Tasks (SEP-1686)**: Async task tracking for long-running MCP requests. `TaskManager` with create/get/list/cancel. States: working → input_required → completed/failed/cancelled. Polling-based result retrieval. MCP methods: `tasks/get`, `tasks/list`, `tasks/cancel`.
- **Elicitation (SEP-1330, SEP-1036)**: Server-initiated user input requests. Two modes: Form (structured JSON Schema) and URL (redirect to OAuth/consent page). `ElicitationManager` with create_form/create_url/respond/cancel. MCP method: `elicitation/respond`.
- **Sampling with Tools (SEP-1577)**: Server-initiated LLM calls with tool definitions. `SamplingManager` supports `tools` and `toolChoice` parameters per spec. Enables server-side agent loops.
- **Tool Icons (SEP-973)**: Icon metadata in tools/list responses. Supports `{"type":"url","url":"..."}` and `{"type":"emoji","emoji":"📊"}`. Configured per-tool in JSON config.
- **Origin Validation (Minor 3)**: Streamable HTTP endpoints respond with HTTP 403 for invalid Origin headers. `validate_origin()` in SSE route.
- **Tool Execution Errors (Minor 5)**: Input validation and execution errors now return `{"isError": true}` in tool result content (Tool Execution Error) instead of JSON-RPC Protocol Errors. Enables model self-correction.
- **Server Description (Minor 2)**: `description` field added to `serverInfo` in initialize response.
- **notifications/cancelled**: Client can cancel pending requests via `notifications/cancelled` method.
- **JSON Schema 2020-12 (Minor 10)**: Declared as default dialect for schema definitions.

#### Updated Capabilities Declaration

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

#### Exception Handling Overhaul

- 42 bare `except:` blocks → `except Exception as e:` + logging
- 21 swallowed exceptions → added logging with `exc_info=True`
- 280+ `exc_info=True` additions for full stack traces in log files
- Before: 11 good / 304 issues. After: 308 good / 102 issues.

#### Files Added

- `sajha/core/mcp_2025_11_25.py` — Tasks, Elicitation, Sampling, Icons, Origin validation

---

## v4.0.0 (May 2026) — Production Hardening

WebSocket transport, OpenTelemetry, tool versioning, multi-tenancy, plugin system. See git history.

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. See git history.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
