# SAJHA Helm chart

Installs the SAJHA MCP Server: Deployment (with a seed init container), Service, optional
Ingress pair (console, and streaming paths with buffering off), HPA, PodDisruptionBudget,
bundled Redis, NetworkPolicies and a Prometheus ServiceMonitor.

```bash
helm install sajha charts/sajha -n sajha --create-namespace \
    --set image.repository=<registry>/sajha --set image.tag=<tag>
helm test sajha -n sajha
```

With PostgreSQL, apply the schema files first: the chart never creates tables, the install
notes print the two `psql` commands, and pods crash-loop with the refusal message until
the schema exists ([Database Setup](../../docs/getting-started/Database%20Setup.md)).

Every value is described in [`values.yaml`](values.yaml) and validated by
[`values.schema.json`](values.schema.json). The guide is
[Kubernetes Deployment](../../docs/getting-started/Kubernetes%20Deployment.md); the
walkthrough on kind is
[Tutorial 17](../../docs/tutorials/TUTORIAL_17_deploy_sajha_on_kubernetes.md).
