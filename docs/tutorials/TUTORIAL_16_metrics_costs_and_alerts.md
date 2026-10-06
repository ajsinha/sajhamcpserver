# Tutorial 16: Metrics, Costs and Alerts

You will scrape SAJHA's Prometheus metrics, import the Grafana dashboard, read the
**Usage & cost** page, and make an alert fire. The design behind every step is in
[Observability](../architecture/Observability.md); every key is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#observability).

You need SAJHA running ([Tutorial 1](TUTORIAL_01_getting_started.md)) and, for steps 3
and 4, Docker.

---

## 1. Look at `/metrics` in the browser

Sign in as an administrator and open `http://localhost:3002/metrics`. By default
(`observability.metrics.auth: admin`) only a signed-in administrator may read it; without
a session the answer is `401`.

You see the Prometheus text format: a `# HELP` and `# TYPE` line per family, then
samples. Run a tool (**Tools → All tools**, open `calc_future_value`, execute it), reload,
and find:

```
sajha_tool_calls_total{tool="calc_future_value",group="calc",outcome="ok"} 1
sajha_tool_call_duration_seconds_bucket{tool="calc_future_value",group="calc",le="0.005"} 1
sajha_http_requests_total{method="POST",route="/api/tools/execute",status="200"} 1
```

`route` is the route template, never the raw path, and no metric is labelled by user;
per-user figures live in the usage ledger (step 5).

## 2. Give Prometheus a token

Prometheus cannot sign in, so switch `/metrics` to token mode. The token is a secret:
environment only.

```bash
export SAJHA_OBSERVABILITY_METRICS_AUTH=token
export SAJHA_OBSERVABILITY_METRICS_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python run_server.py
```

Check it:

```bash
curl -s -H "Authorization: Bearer $SAJHA_OBSERVABILITY_METRICS_TOKEN" \
     http://localhost:3002/metrics | head
curl -s -o /dev/null -w '%{http_code}\n' -H 'Authorization: Bearer wrong' http://localhost:3002/metrics   # 403
```

To keep scrapes off the public port, also set `observability.metrics.port: 9464`: SAJHA
then serves `/metrics` (same rule) on `127.0.0.1:9464` as well
(`observability.metrics.host`).

## 3. Scrape with Prometheus

The repository ships a scrape job, alert rules and a dashboard in
`deployment/observability/`. Copy them to a scratch folder, put the token where
`prometheus.yml` expects it and start Prometheus next to SAJHA:

```bash
cp -r deployment/observability ~/sajha-obs && cd ~/sajha-obs
printf '%s' "$SAJHA_OBSERVABILITY_METRICS_TOKEN" > sajha-metrics-token
sed -i 's#sajha:3002#host.docker.internal:3002#' prometheus.yml     # SAJHA runs on the host
docker run --rm -p 9090:9090 --add-host=host.docker.internal:host-gateway \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/sajha-alerts.yml:/etc/prometheus/sajha-alerts.yml:ro" \
  -v "$PWD/sajha-metrics-token:/etc/prometheus/sajha-metrics-token:ro" \
  prom/prometheus
```

Open `http://localhost:9090/targets`: the `sajha` job is `UP`. In the query box try:

```promql
sum by (tool) (rate(sajha_tool_calls_total[5m]))
histogram_quantile(0.95, sum by (le) (rate(sajha_http_request_duration_seconds_bucket[5m])))
sum(increase(sajha_llm_cost_usd_total[1h]))
```

**Alerts** (`http://localhost:9090/alerts`) lists the rules from `sajha-alerts.yml`;
route them with Alertmanager as you would any other rules.

Running SAJHA with several workers on one port? Read section 2.4 of the guide first: with a
shared `state.backend`, each scrape carries every worker under a `worker` label, so sum
with `sum without (worker) (...)`.

## 4. Import the Grafana dashboard

```bash
docker run --rm -p 3000:3000 --add-host=host.docker.internal:host-gateway grafana/grafana
```

Sign in at `http://localhost:3000` (admin / admin), add a Prometheus data source at
`http://host.docker.internal:9090`, then **Dashboards → New → Import**, upload
`deployment/observability/grafana-sajha-dashboard.json` and pick that data source. You get
tool rate and error rate, LLM spend and tokens for the range, HTTP status and latency
percentiles, MCP requests by era and method, top tools, LLM cost by model, ask runs by stop
reason, auth failures, open breakers, federated upstreams, sandbox runs, memory and CPU.

## 5. Read the Usage & cost page

Back in SAJHA: **Tools → Monitor → Usage & cost** (`/monitoring/usage`). Ask a question
on **AI → Ask SAJHA** first so there are LLM calls too (the mock provider answers when no
real one is configured; it costs nothing, so the cost is `$0`).

* The tiles total the range: tool calls and their error rate, tool latency p50/p95/p99,
  LLM calls, tokens in and out, and cost.
* **Cost by day, by provider** stacks spend per provider; **Tokens and tool calls by day**
  puts tokens against calls and errors.
* The tables break it down by user, API key, role, provider/model and tool; each has a
  **CSV** button (`/api/observability/usage.csv?dimension=...`).
* **Budgets today** compares each caller's tokens today with `ai.budgets` (the same
  counters the gateway enforces). Set `SAJHA_AI_BUDGETS_PER_USER_DAILY_TOKENS=2000` and
  restart to see a meter fill.

Change the range with **Today / 7 days / 30 days / 90 days** or the date fields, and
filter by user, API key, role, provider, model or tool. Sign in as a non-administrator:
the same page shows only that user's own calls (the server enforces the filter).

## 6. Make an alert fire, without Prometheus

For a single server, SAJHA can evaluate simple rules itself. Add to
`config/application.yml`:

```yaml
observability:
  alerts_interval_seconds: 5
  alerts:
    - name: tool-errors
      metric: tool_error_rate
      op: '>='
      threshold: 0.5
      window: 1m
      min_events: 3
      cooldown: 10m
      channel: {type: log}
```

Restart, then call a tool with bad arguments three times (for example
`calc_future_value` with `{}`), and watch the server log:

```
WARNING sajha.observability.alerts: ALERT tool-errors: tool_error_rate = 1.0 >= 0.5 over 60s
```

The **Alert rules** card on the Usage & cost page shows the rule as `firing`, and
`sajha_alerts_fired_total{rule="tool-errors"}` counts it. To post to a webhook instead,
use `channel: {type: webhook, url: https://hooks.example.com/sajha}` and allow-list the
prefix in `observability.alerts_webhook.allowed_urls`; a URL outside the list, or a host
that resolves to a private address, is refused (the same SSRF guard as async webhooks).

## 7. Optional: traces with OpenTelemetry

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
SAJHA_OBSERVABILITY_OTEL_ENABLED=true OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 python run_server.py
```

Call a tool over MCP, open Jaeger at `http://localhost:16686`, pick service
`sajha-mcp-server`: each request is an HTTP span with an `mcp tools/call` span, a `tool ...`
span and, for Ask SAJHA, `llm.chat` spans beneath. An MCP client that sends
`params._meta.traceparent` sees SAJHA's spans inside its own trace.

---

Next: [Observability](../architecture/Observability.md) for every family, label and limit.
