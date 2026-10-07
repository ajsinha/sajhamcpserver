# Observability

How SAJHA tells you what it is doing: Prometheus metrics on `/metrics`, OpenTelemetry
traces and metrics over OTLP, a usage ledger behind the **Usage & cost** dashboard, and
in-process alert rules. This guide owns the topic; every configuration key is listed in
the [Configuration Reference](../getting-started/Configuration%20Reference.md#observability),
and the hands-on walk-through is
[Tutorial 16](../tutorials/TUTORIAL_16_metrics_costs_and_alerts.md).

The code is `sajha/observability/` and `sajha/routes/observability_routes.py`.

---

## 1. Shape

`sajha/observability/__init__.py` holds the `MetricsCollector` (per-tool calls and
latency percentiles, served as JSON on `/api/metrics`), the OpenTelemetry integration and
the `/health` and `/ready` probes. Around them:

| Piece | Module | What it does |
|---|---|---|
| Metric registry and exposition | `metrics.py` | Counters, gauges and histograms with labels; the Prometheus text format (0.0.4), written by SAJHA itself, no `prometheus_client` needed. |
| Instrumentation points | `metrics.py` (`record_*`) | Called from the HTTP middleware, both MCP eras, `execute_with_tracking`, the LLM gateway, the ask service, sign-in and request authentication, and the sandbox. |
| Caller context | `caller.py` | A context variable naming who is calling (user, API key, roles, auth type), set where the MCP session or REST auth is known and read where the tool or model runs. |
| HTTP middleware | `middleware.py` | A plain ASGI middleware (streams and SSE pass through untouched): requests by route template, method and status, a latency histogram, and the server span. |
| Tracing | `tracing.py` | Configures an OTLP exporter when `observability.otel.enabled` and the SDK are present; spans for HTTP, MCP, tool and LLM, with `traceparent` honoured from the HTTP header and from MCP `_meta`. |
| Usage ledger | `usage.py` | One row per tool call and per LLM call (who, what, outcome, latency, tokens, cost), written in batches off the request path; the dashboard's queries and CSV export. |
| Alerts | `alerts.py` | `observability.alerts[]` rules evaluated in the process every `observability.alerts_interval_seconds`, sent to a log, an allow-listed webhook (SSRF-guarded) or email. |
| Routes and page | `sajha/routes/observability_routes.py`, `templates/monitoring/usage.html` | `/metrics`, `/monitoring/usage`, `/api/observability/*`. |

`execute_with_tracking` feeds the collector behind the JSON endpoints `/api/metrics` and
`/api/metrics/tools`, as well as the Prometheus families below.

---

## 2. Prometheus metrics

### 2.1 The endpoint

`GET /metrics` returns `text/plain; version=0.0.4`. Who may read it is
`observability.metrics.auth`:

| Mode | Who may scrape |
|---|---|
| `admin` (default) | A signed-in administrator (session cookie or admin JWT). |
| `token` | `Authorization: Bearer <token>` equal to `SAJHA_OBSERVABILITY_METRICS_TOKEN` (constant-time comparison), or an administrator. With no token set, only administrators. |
| `none` | Anyone who can reach the port. Use only on a private network or with `observability.metrics.port`. |

`observability.metrics.port` (default `0`, off) also serves `/metrics` on a separate
listener bound to `observability.metrics.host` (default `0.0.0.0`, like the main server), with the same
`auth` rule, so the scrape port can be kept off the public interface.
`observability.metrics.enabled: false` removes the endpoint (404) and stops recording.

### 2.2 The metrics

Names follow Prometheus conventions (`_total` counters, `_seconds` histograms, base
units). The live list is the endpoint itself; each family carries `# HELP` and `# TYPE`.

| Family | Type | Labels |
|---|---|---|
| `sajha_http_requests_total` | counter | `method`, `route` (the route template, `/tools/{tool_name}`; unmatched paths are `<unmatched>`), `status` |
| `sajha_http_request_duration_seconds` | histogram | `method`, `route` |
| `sajha_mcp_requests_total` | counter | `era` (`modern` 2026-07-28, `legacy` 2025-11-25 and earlier), `method`, `outcome` (`ok`, `error`, `stream`, `notification`) |
| `sajha_mcp_request_duration_seconds` | histogram | `era`, `method` |
| `sajha_tool_calls_total` | counter | `tool`, `group`, `outcome` (`ok`, `error`, `cache_hit`, `circuit_open`, `input_required`, `policy_denied`, `approval_required`, `rate_limited`) |
| `sajha_tool_call_duration_seconds` | histogram | `tool`, `group` |
| `sajha_tool_cache_hits_total` | counter | `tool`, `group` |
| `sajha_tool_cache_entries`, `sajha_tool_cache_requests_total` | gauge / counter (collected) | `result` (`hit`, `miss`) |
| `sajha_circuit_breaker_state` | gauge (collected) | `breaker`, `state`; 1 for the breaker's current state |
| `sajha_llm_calls_total` | counter | `provider`, `model`, `outcome` (`ok`, `cache_hit`, `error`, `auth_failed`, a gateway error code) |
| `sajha_llm_call_duration_seconds` | histogram | `provider`, `model` |
| `sajha_llm_tokens_total` | counter | `provider`, `model`, `direction` (`input`, `output`) |
| `sajha_llm_cost_usd_total` | counter | `provider`, `model` |
| `sajha_ask_runs_total` | counter | `stopped_by` (`answer`, `step_limit`, `tool_limit`, `timeout`, `budget`, `error`, `needs_confirmation`) |
| `sajha_auth_failures_total` | counter | `method` (`password`, `bearer`, `apikey`, `session`) |
| `sajha_auth_lockouts_total` | counter | none |
| `sajha_sandbox_runs_total` | counter | `backend`, `outcome` (`ok`, `error`, `timeout`, `output_limit`, `runner_error`) |
| `sajha_sandbox_run_duration_seconds` | histogram | `backend` |
| `sajha_federation_upstream_up` | gauge (collected) | `upstream`, `state`; 1 when connected. Present only when `sajha/federation` is importable and a manager is running. |
| `sajha_federation_upstream_calls_total`, `sajha_federation_upstream_failures_total` | counter (collected) | `upstream` |
| `sajha_alerts_fired_total` | counter | `rule` |
| `sajha_policy_decisions_total`, `sajha_policy_redactions_total`, `sajha_policy_output_flags_total`, `sajha_audit_records_total`, `sajha_audit_export_total` | counter | policy and audit; labels in [Policy and Audit §6](Policy%20and%20Audit.md#6-decisions-are-logged-and-counted) |
| `sajha_tool_probe_runs_total`, `sajha_tool_probe_up`, `sajha_tool_probe_duration_seconds`, `sajha_tool_version_calls_total`, `sajha_tool_version_call_duration_seconds`, `sajha_tool_version_rollbacks_total` | counter, gauge, histogram | health probes and tool versions; labels in [Tool Quality §4 and §6.4](Tool%20Quality.md#4-health-probes) |
| `sajha_info` | gauge | `version` |
| `process_*`, `python_*` | gauge / counter (collected) | resident memory, CPU seconds, open file descriptors, start time, threads, GC collections, Python version |

"Collected" families are read from their owner (the cache, the breaker registry, the
federation manager, the process) when `/metrics` is scraped, so they are never stale and
cost nothing between scrapes.

### 2.3 Label cardinality

A Prometheus series per distinct label set is cheap until a label takes unbounded values.
SAJHA's unbounded inputs are tool names (a catalog of hundreds, plus federated and Studio
tools), model ids and HTTP paths:

* **Routes** are always the route template, never the raw path.
* **Tools**: `observability.metrics.tool_label` is `name` (default; one series per tool),
  `group` (the `tool` label is set to the group, the text before the first `_`, so the
  catalog collapses to its provider groups) or `none` (`tool="_all"`).
* **Every family** is capped at `observability.metrics.max_series` label sets
  (default 2000). A new label set beyond the cap is recorded under the same family with
  every label value `_other`, and `sajha_metrics_series_dropped_total{family}` counts it.
* User ids and API key names are **never** labels; per-caller figures are in the usage
  ledger (section 4), which is a table, not a time series.

### 2.4 Several workers

Metrics live in the process. With one worker per container (the recommended shape;
scale with replicas and let Prometheus scrape each pod) nothing more is needed.

With several workers behind one port (`uvicorn --workers N`), a scrape reaches one worker
at random. When `state.backend` is shared (`redis` or `database`, see
[Scaling and State](Scaling%20and%20State.md)) and `observability.metrics.multiworker` is
`auto` (default), every worker publishes a snapshot of its own families to the state store
every `observability.metrics.publish_interval_seconds` (default 15) under
`obs:metrics:<worker id>` with a TTL of three intervals, and `/metrics` serves this
worker's live values plus every other live worker's last snapshot, each sample labelled
`worker="<host:pid:nonce>"`. Counters therefore aggregate correctly with
`sum without (worker) (...)`; a dead worker's series disappear when its snapshot
expires. With the memory backend and several workers, each scrape shows one worker only,
and start-up logs a warning. `prometheus_client`'s multiprocess mode is not used: it needs
a shared directory on one host, which the state store already generalises.

---

## 3. OpenTelemetry

### 3.1 Configuration

Off by default. `observability.otel.enabled: true` (or the standard
`OTEL_SDK_DISABLED=false` with an `OTEL_EXPORTER_OTLP_ENDPOINT`) turns it on when the
packages are installed:

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http   # or -grpc
```

| Setting | Key | Standard environment variable (wins over the key) |
|---|---|---|
| Endpoint | `observability.otel.endpoint` | `OTEL_EXPORTER_OTLP_ENDPOINT`, and `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` / `..._METRICS_ENDPOINT` for one signal |
| Protocol | `observability.otel.protocol` (`http/protobuf` or `grpc`) | `OTEL_EXPORTER_OTLP_PROTOCOL` |
| Headers | `observability.otel.headers` (`k=v,k2=v2`) | `OTEL_EXPORTER_OTLP_HEADERS` (put credentials here, never in the YAML) |
| Service name | `observability.otel.service_name` | `OTEL_SERVICE_NAME` (and `service.name` in `OTEL_RESOURCE_ATTRIBUTES`) |
| Sampling | `observability.otel.sample_ratio` | `OTEL_TRACES_SAMPLER_ARG` (parent-based ratio sampler) |
| Signals | `observability.otel.traces`, `observability.otel.metrics` | `OTEL_TRACES_EXPORTER=none`, `OTEL_METRICS_EXPORTER=none` |

When the SDK is missing, SAJHA logs once and runs without tracing; nothing else changes.
When the SDK is present but OTel is off, SAJHA does not install a global tracer provider.

### 3.2 Spans

```
HTTP POST /mcp                     (server span; parent: the traceparent header, if any)
└── mcp tools/call                 (parent: _meta.traceparent when the client sent one,
    │                                otherwise the HTTP span)
    └── tool fred_get_series       (execute_with_tracking: cache, breaker, outcome)
        └── llm.chat               (the gateway, one per model call: provider, model,
                                     tokens, latency, outcome; prompts only with
                                     ai.gateway.trace_prompts)
```

* **HTTP**: `http.request.method`, `http.route`, `http.response.status_code`, `url.path`.
* **MCP**: `mcp.method`, `mcp.era`, `mcp.outcome`, `rpc.jsonrpc.request_id`. A
  2026-07-28 request carries W3C trace context in `params._meta.traceparent` (and
  `tracestate`); SAJHA also reads it from a 2025-11-25 request's `params._meta`. When it is
  present the MCP span continues the client's trace (the HTTP span remains the transport
  record of the same request, linked).
* **Tool**: `sajha.tool.name`, `sajha.tool.group`, `sajha.tool.outcome`, `enduser.id`.
* **LLM**: the gateway's `llm.chat` span (`llm.provider`, `llm.model`,
  `llm.input_tokens`, `llm.output_tokens`, `llm.latency_ms`, `llm.outcome`), nested under
  the tool or ask that made the call.

Spans cross into worker threads because both Starlette's thread pool and anyio copy
context variables. OTel metrics, when `observability.otel.metrics` is on, export the
same instruments as section 2 through a periodic reader (`OTEL_METRIC_EXPORT_INTERVAL`).

---

## 4. Cost and usage

### 4.1 The ledger

`usage.py` owns one table, `obs_usage_events`, in SAJHA's database. It is in the schema
file ([Database Setup](../getting-started/Database%20Setup.md)); on SQLite
`usage.py` also creates it on first use, on PostgreSQL it only checks that it exists and
logs once that the ledger is off when it does not. One row per tool call and per LLM call:

| Column | Meaning |
|---|---|
| `kind` | `tool` or `llm` |
| `ts`, `day` | UTC time, and the UTC day for grouping |
| `user_id`, `api_key`, `roles`, `auth_type` | the caller, from the caller context (an API key's user id is `apikey:<name>`) |
| `tool`, `tool_group` | for a tool call |
| `provider`, `model` | for an LLM call |
| `outcome`, `latency_ms` | as in the metrics |
| `input_tokens`, `output_tokens`, `cost_usd` | for an LLM call (cost from the model's per-token prices) |

Rows are queued and written by a daemon thread in batches (every second or 200 rows), so
a slow database never slows a call; the queue is bounded
(`observability.usage.queue_size`) and drops, with a counter
(`sajha_usage_events_dropped_total`), rather than grow. Rows older than
`observability.usage.retention_days` are deleted once a day. `observability.usage.enabled:
false` stops recording. Several workers share the database, so the dashboard already sees
every worker.

The separate `tool_usage_events` table (the **Reports** page) is written only by the
REST execute endpoint.

### 4.2 The dashboard

`/monitoring/usage` (**Tools → Monitor → Usage & cost**). Administrators see everyone and
can filter by user, API key, role, provider, model and tool; any other signed-in user sees
the same page restricted to their own calls (the API forces the filter server-side).

* Totals for the date range: tool calls, error rate, LLM calls, tokens in and out, cost.
* Tokens and cost by day (stacked by provider), tool calls by day.
* Tables: by user, by API key, by role, by provider/model, by tool (calls, errors, error
  rate, p50/p95/p99 latency).
* Budgets: today's tokens against `ai.budgets.per_user_daily_tokens` and
  `ai.budgets.per_role_daily_tokens`, from the gateway's token tracker (the same counters
  that enforce the budget).
* CSV export of any table: `/api/observability/usage.csv?dimension=user|api_key|role|model|tool|day`.

Charts use the vendored Chart.js and `SajhaChartTheme` from `static/js/main.js`, so they
follow the four themes.

API: `GET /api/observability/usage?since=YYYY-MM-DD&until=YYYY-MM-DD[&user=&api_key=&role=&provider=&model=&tool=]`
returns every figure the page shows; `GET /api/observability/alerts` lists the rules and
their last state (admin).

Percentiles are computed from the ledger rows of the range, up to
`observability.usage.max_rows_for_percentiles` rows (default 200000, the most recent);
beyond that the page says the figures are sampled.

---

## 5. Alerts

Two ways, use either or both:

**In-process rules** for a single server without Prometheus: `observability.alerts` is a
list in `application.yml` (or a JSON list in `SAJHA_OBSERVABILITY_ALERTS`):

```yaml
observability:
  alerts:
    - name: tool-errors
      metric: tool_error_rate        # see the table below
      op: '>'                        # > >= < <=
      threshold: 0.2
      window: 5m                     # s, m, h
      min_events: 20                 # optional: do not judge a rate on a handful of calls
      cooldown: 15m
      channel: {type: webhook, url: "https://hooks.example.com/sajha"}
    - name: daily-spend
      metric: llm_cost_usd
      op: '>='
      threshold: 25
      window: 24h
      channel: {type: log}
```

| `metric` | Value over the window |
|---|---|
| `http_error_rate` | share of HTTP responses with status >= 500 |
| `http_latency_p95_ms` | 95th percentile HTTP latency |
| `tool_error_rate` | share of tool calls that failed (optional `tool:` filter) |
| `tool_latency_p95_ms` | 95th percentile tool latency (optional `tool:`) |
| `tool_calls` | number of tool calls |
| `llm_cost_usd` | LLM spend |
| `llm_tokens` | LLM tokens in + out |
| `llm_error_rate` | share of LLM calls that failed |
| `auth_failures` | failed authentications |
| `breaker_open` | circuit breakers open now (window ignored) |
| `federation_upstreams_down` | enabled upstreams not connected now |

A background thread evaluates the rules every `observability.alerts_interval_seconds`
(default 30) over an in-memory window of recent events. A rule fires when the condition
holds and its cooldown has passed, and sends one message to its channel:

* `log`: a `WARNING` line from logger `sajha.observability.alerts`.
* `webhook`: a JSON POST to `url`, which must match a prefix in
  `observability.alerts_webhook.allowed_urls`; the host is resolved once and every address
  must pass the same SSRF guard as async webhooks and OAuth CIMD fetches
  (`address_allowed`: public addresses only unless
  `observability.alerts_webhook.allow_private_networks`), connected by pinned IP with no
  redirects and no proxy.
* `email`: through `observability.alerts_email` (`smtp_host`, `smtp_port`, `from`,
  `starttls`; the password from `SAJHA_OBSERVABILITY_ALERTS_EMAIL_PASSWORD`) to the rule's
  `to`.

Each worker evaluates its own traffic. With several workers, prefer Prometheus rules.

**Prometheus and Alertmanager** for anything larger: `deployment/observability/` ships
`prometheus.yml` (a scrape job with the bearer token), `sajha-alerts.yml` (alerting rules
on the families above) and `grafana-sajha-dashboard.json` (an importable dashboard).

---

## 6. As built: decisions and limits

* **No `prometheus_client` dependency.** The exposition format is small and stable;
  writing it keeps SAJHA's install unchanged and lets the multi-worker merge add a
  `worker` label without the client's multiprocess directory. The output passes
  `promtool check metrics` style rules: one `# HELP`/`# TYPE` per family, escaped label
  values, cumulative `le` buckets ending in `+Inf`, `_sum` and `_count`.
* **Histogram buckets** (seconds): 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10,
  30, 60, 120.
* **Instrumentation never raises.** Every `record_*` call is wrapped; a metrics fault is
  logged at debug and the call proceeds.
* **What is not measured**: WebSocket frames (the upgrade request is counted), the bytes
  of responses. There is no tenant dimension: SAJHA has no tenants.
* **Conformance**: the middleware and MCP wrappers do not change a response; the
  conformance suites run unchanged.
