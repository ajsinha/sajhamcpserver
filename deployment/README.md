# SAJHA MCP Server — Deployment Guide

Three deployment targets, same application, identical behavior.

## Choose Your Deployment

| Target | Best For | Setup Time | Monthly Cost |
|--------|----------|:----------:|-------------:|
| [**AWS (CDK)**](aws/) | Enterprise, auto-scaling, managed services | 30 min | ~$52–170 |
| [**Hetzner Cloud**](hetzner/) | Cost-effective, European hosting, simple | 10 min | ~€4–15 |
| [**Bare Metal**](baremetal/) | Full control, on-prem, air-gapped | 20 min | Hardware only |

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

## Storage Backend

All deployments use the same SAJHA application. The only difference is the storage backend:

```yaml
# Bare metal / Hetzner (local filesystem)
SAJHA_STORAGE_BACKEND=local

# AWS (S3 for configs, hot-reload via S3 polling)
SAJHA_STORAGE_BACKEND=s3
SAJHA_S3_BUCKET=sajha-prod-123456
```

The Storage + Reload abstractions ensure identical behavior: hot-reload, tool discovery, prompt management, and plugin loading work the same way regardless of where files live.

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

---

*SAJHA MCP Server v5.1.0*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
