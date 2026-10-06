# Tutorial 17: Deploy SAJHA on Kubernetes

In this tutorial you build the SAJHA image, install it on a local kind cluster with the
Helm chart, put it behind ingress-nginx, and then scale it to three pods that share their
state through Redis and PostgreSQL. Everything the chart does, and every value, is
explained in the [Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md)
guide; this tutorial is the hands-on path through it.

## What you'll learn

- How to build the production image and load it into a cluster
- How to install, test and upgrade the chart
- Why streaming endpoints get their own Ingress
- What changes when you go from one pod to three
- How to confirm that all pods sign with the same keys

## Prerequisites

- Docker
- [kind](https://kind.sigs.k8s.io/), `kubectl` and [Helm](https://helm.sh/) 3.8 or later
- A SAJHA checkout (you build the image from it)
- `curl` and `openssl`

## Steps

### 1. Build the image

From the repository root:

```bash
docker build -t sajha:tutorial .
```

The defaults give a slim image with the Redis client. Section 1 of the guide lists the
build arguments (bucket SDKs, OpenTelemetry, OpenBB, vendored Pyodide).

### 2. Create a cluster and load the image

```bash
kind create cluster --name sajha
kind load docker-image sajha:tutorial --name sajha
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl -n ingress-nginx wait --for=condition=ready pod \
    -l app.kubernetes.io/component=controller --timeout=180s
```

### 3. Install one pod

```bash
helm install sajha charts/sajha -n sajha --create-namespace \
    --set fullnameOverride=sajha \
    --set image.repository=sajha --set image.tag=tutorial --set image.pullPolicy=Never \
    --set playground.assets=cdn \
    --set ingress.enabled=true --set 'ingress.hosts={sajha.localtest.me}' \
    --wait
helm test sajha -n sajha --logs
```

The test pod prints the `/health` summary and the reply to an MCP `initialize` sent
through the Service. Look at what was created:

```bash
kubectl -n sajha get deploy,pod,svc,ingress,pvc,secret
kubectl -n sajha logs deploy/sajha -c seed
```

The `seed` init container copied the image's configuration into the writable volumes and
wrote `config/application.yml`. The Secret `sajha-secrets` holds the JWT secret, the
session secret, an OAuth signing key and the metrics token; it was generated once and is
kept across upgrades.

### 4. Reach it through the ingress

kind does not route host ports to the controller by default, so forward one:

```bash
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80 &
curl -s -H 'Host: sajha.localtest.me' http://127.0.0.1:8080/health
```

Open `http://sajha.localtest.me:8080` in a browser (`localtest.me` resolves to
127.0.0.1), sign in as `admin` / `admin123`, and change the password when the banner asks.

There are two Ingress objects:

```bash
kubectl -n sajha get ingress sajha-streams -o yaml | grep nginx.ingress
```

`sajha-streams` carries `/mcp`, `/api/mcp` and `/api/ai/ask` with buffering off and
one-hour timeouts, so Streamable HTTP and SSE events reach the client as they are
written. The other object serves everything else with ordinary timeouts.

### 5. Scrape the metrics

```bash
TOKEN=$(kubectl -n sajha get secret sajha-secrets -o jsonpath='{.data.metrics-token}' | base64 -d)
curl -s -H 'Host: sajha.localtest.me' -H "Authorization: Bearer $TOKEN" \
    http://127.0.0.1:8080/metrics | grep -v '^#' | head
```

Without the token the endpoint answers 401. With the Prometheus Operator installed,
`--set metrics.serviceMonitor.enabled=true` makes Prometheus send it.

### 6. Try to scale, and read the refusal

```bash
helm upgrade sajha charts/sajha -n sajha --reuse-values --set replicaCount=3
```

The chart refuses: three pods need PostgreSQL, because SQLite cannot be shared between
pods. The chart checks each of the requirements in section 4 of the guide before it
renders anything.

### 7. Add PostgreSQL and Redis, then scale

Start a throwaway PostgreSQL (use a managed database in production):

```bash
kubectl -n sajha create secret generic sajha-postgres --from-literal=password="$(openssl rand -hex 16)"
kubectl -n sajha create deployment postgres --image=postgres:16-alpine --port=5432
kubectl -n sajha set env deployment/postgres POSTGRES_DB=sajha POSTGRES_USER=sajha
kubectl -n sajha set env deployment/postgres --from=secret/sajha-postgres --prefix=POSTGRES_
kubectl -n sajha expose deployment postgres --port=5432
kubectl -n sajha rollout status deployment/postgres
```

(`--prefix=POSTGRES_` turns the Secret's `password` key into `POSTGRES_PASSWORD`.) Now
scale, with the bundled Redis as the state store and no `ReadWriteOnce` data volume:

```bash
helm upgrade sajha charts/sajha -n sajha --reuse-values \
    --set replicaCount=3 \
    --set database.type=postgresql \
    --set database.postgresql.host=postgres \
    --set database.postgresql.existingSecret=sajha-postgres \
    --set redis.enabled=true \
    --set persistence.data.enabled=false \
    --wait
kubectl -n sajha get pods -o wide
```

`state.backend` was left at `auto`, which resolved to `redis` because Redis is enabled.
Each pod reports it:

```bash
for i in 1 2 3 4 5 6; do
  curl -s -H 'Host: sajha.localtest.me' http://127.0.0.1:8080/health \
    | python3 -c "import sys,json; s=json.load(sys.stdin)['state']; print(s['backend'], s['reachable'], s['worker_id'])"
done
```

The worker ids differ from line to line: the ingress spreads requests over the pods, and
every pod uses the same Redis.

### 8. Check that the pods share their keys

Turn on optional MCP authorization through `config.overrides` (the seed step merges it
into `application.yml`), and ask the pods for their OAuth signing key:

```bash
helm upgrade sajha charts/sajha -n sajha --reuse-values \
    --set config.overrides.mcp.auth.mode=optional --wait
for i in 1 2 3 4 5 6; do
  curl -s -H 'Host: sajha.localtest.me' http://127.0.0.1:8080/oauth/jwks \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['keys'][0]['kid'])"
done | sort | uniq -c
```

One key id, six times: every pod signs tokens with the PEM from `sajha-secrets`. Without
it, each pod would generate its own key and reject the others' tokens.

### 9. Clean up

```bash
kind delete cluster --name sajha
```

## What you learned

- The image runs as a non-root user on a read-only root filesystem; the chart mounts the
  few writable directories
- The secrets every pod shares come from one Secret, generated once and kept
- Streaming paths get their own Ingress with buffering off and long timeouts
- Several pods need PostgreSQL, a shared state store, and no `ReadWriteOnce` volume; the
  chart refuses anything else
- `config.overrides` changes any part of `application.yml` without rebuilding the image

## Next steps

- Without Helm: `kubectl apply -k deployment/k8s/overlays/prod` (section 9 of the guide)
- Lock the network down with `networkPolicy.enabled=true` (section 8 of the guide)
- Read [Scaling and State](../architecture/Scaling%20and%20State.md) for what is shared
  between pods, and what stays in each one

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
