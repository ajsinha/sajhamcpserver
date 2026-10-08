# Observability recipes

Example files for watching SAJHA with Prometheus, Alertmanager and Grafana. What SAJHA
exposes, and why, is in [Observability](../../docs/architecture/Observability.md); the
walk-through is [Tutorial 16](../../docs/tutorials/TUTORIAL_16_metrics_costs_and_alerts.md).

| File | What it is |
|---|---|
| `prometheus.yml` | A scrape job for `/metrics` with a bearer token (`observability.metrics.auth: token`), the rule file and an Alertmanager. |
| `sajha-alerts.yml` | Alerting rules: target down, 5xx rate, tool error rate and p95 latency, open breakers, LLM spend and errors, auth-failure bursts, lockouts, federated upstreams down, usage-ledger drops. |
| `grafana-sajha-dashboard.json` | An importable Grafana dashboard (Dashboards → New → Import) on a Prometheus data source. |

Several workers behind one port: see section 2.4 of the guide (a shared `state.backend`
merges every worker into each scrape under a `worker` label). Prefer one worker per
container and one scrape target per container.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
