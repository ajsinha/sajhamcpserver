# SAJHA MCP Server — Deployment Guide

Four deployment targets, one application.

## Choose Your Deployment

| Target | Best For | Setup Time | Monthly Cost |
|--------|----------|:----------:|-------------:|
| [**AWS (CDK)**](aws/) | Enterprise, auto-scaling, managed services | 30 min | ~$52–170 |
| [**Hetzner Cloud**](hetzner/) | Cost-effective, European hosting, simple | 10 min | ~€4–15 |
| [**Bare Metal**](baremetal/) | Full control, on-prem, air-gapped | 20 min | Hardware only |
| [**Kubernetes**](k8s/) (Helm chart [`charts/sajha`](../charts/sajha/), or Kustomize) | Any cluster: EKS, GKE, AKS, on-prem | 15 min | Your cluster |

## Architecture Comparison

| Component | AWS | Hetzner | Bare Metal |
|-----------|-----|---------|-----------|
| Compute | ECS Fargate (serverless) | Docker on VPS | systemd service |
| Database | RDS PostgreSQL (managed) | Docker PostgreSQL or Hetzner managed | Local PostgreSQL |
| Reverse proxy | ALB | Caddy (auto-SSL) | Nginx + certbot |
| SSL | ACM | Let's Encrypt (auto) | Let's Encrypt |
| Storage | S3 | Local volumes | Local filesystem |
| Scaling | Auto (2–6 tasks) | Manual (upgrade VPS) | Manual |
| IAC | CDK (Python) | docker-compose + cloud-init | install.sh + systemd |

Every PostgreSQL target has one manual step: SAJHA does not create tables on PostgreSQL, so
an operator runs `db/scripts/postgresql/schema.sql` (then `seed.sql`) with `psql` once,
before the first start. There are no migrations. Each recipe's README shows the commands;
[Database Setup](../docs/getting-started/Database%20Setup.md) is the procedure.

## SAJHA Net demo

Three SAJHA instances in one net on one machine, with a smoke script: [`sajhanet-demo/`](sajhanet-demo/)
(a lab: plain HTTP and the test admin key).

## Monitoring

Prometheus scrape job, alerting rules and a Grafana dashboard for any of the targets:
[`observability/`](observability/).

## Storage Backend

All deployments use the same SAJHA application. The only difference is the storage backend:

```yaml
# Bare metal / Hetzner (local filesystem)
SAJHA_STORAGE_BACKEND=local

# AWS (S3 for configs, hot-reload via S3 polling)
SAJHA_STORAGE_BACKEND=s3
SAJHA_S3_BUCKET=sajha-prod-123456
```

Tool and prompt configs, the federation store and the guides go through the storage backend,
and hot reload follows them; plugins, Studio-generated `.py` files, the database and the cache
stay on a real filesystem whatever the backend. What goes where is in the
[Storage Guide](../docs/getting-started/Storage%20Guide.md).

## Quick Start

### AWS
```bash
cd deployment/aws/cdk && pip install -r requirements.txt
cdk bootstrap && cdk deploy
```

### Hetzner
```bash
cd deployment/hetzner
./deploy.sh <server-ip> sajha.yourdomain.com
```

### Bare Metal
```bash
cd deployment/baremetal
sudo ./install.sh
```

### Kubernetes
```bash
docker build -t <registry>/sajha:<tag> . && docker push <registry>/sajha:<tag>
helm install sajha charts/sajha -n sajha --create-namespace \
    --set image.repository=<registry>/sajha --set image.tag=<tag>
```
Guide: [Kubernetes Deployment](../docs/getting-started/Kubernetes%20Deployment.md).

## Several workers or hosts

One worker needs nothing extra. More than one worker process (`UVICORN_WORKERS`, or
`run_server.py --workers N`), or more than one host behind a load balancer, needs a shared
state store, or OAuth codes, MCP sessions and tasks, rate limits and change notifications
split between workers. The design is in
[Scaling and State](../docs/architecture/Scaling%20and%20State.md), and the walkthrough is
[Tutorial 13](../docs/tutorials/TUTORIAL_13_run_sajha_on_several_workers.md).

| Target | Shared state | How |
|--------|--------------|-----|
| Hetzner (compose) | Redis, optional `scale` profile | `UVICORN_WORKERS=4 SAJHA_STATE_BACKEND=redis docker compose --profile scale up -d` |
| Hetzner (compose), no Redis | the PostgreSQL service | `UVICORN_WORKERS=4 SAJHA_STATE_BACKEND=database docker compose up -d` |
| AWS (CDK) | RDS (`SAJHA_STATE_BACKEND=database` is set on the ECS tasks) | For Redis, add an ElastiCache endpoint and set `SAJHA_STATE_BACKEND=redis` and `SAJHA_STATE_REDIS_URL` |
| AWS local compose | Redis, optional `scale` profile | `UVICORN_WORKERS=4 SAJHA_STATE_BACKEND=redis docker compose --profile scale up --build` |
| Bare metal | Redis or the database | set `SAJHA_STATE_BACKEND` (and `SAJHA_STATE_REDIS_URL`) in the service environment |
| Kubernetes (Helm) | bundled Redis, an external Redis, or PostgreSQL | `replicaCount` > 1 with `database.type: postgresql`; `state.backend: auto` picks Redis when configured, else the database; the chart refuses unshared settings |

Separate hosts must also share the secrets listed in
[Scaling and State §5](../docs/architecture/Scaling%20and%20State.md#5-secrets-every-worker-must-share):
`JWT_SECRET`, `SESSION_SECRET` and the OAuth signing key
(`SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`). `GET /health` reports the backend each worker
uses under `state`.

---

*SAJHA MCP Server*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
