# SAJHA MCP Server — Hetzner Cloud Deployment

Deploy SAJHA as a Docker container on Hetzner Cloud with PostgreSQL, Caddy (auto-SSL), and optional Hetzner managed database.

## Architecture

```
Internet → Caddy (port 443, auto-SSL Let's Encrypt)
             → SAJHA container (port 3002)
                  → PostgreSQL container (port 5432)
                  → Volume: /app/data, /app/config
```

## Prerequisites

- Hetzner Cloud account ([hetzner.com](https://www.hetzner.com/cloud))
- Domain name with DNS access
- SSH key uploaded to Hetzner

## Option 1: One-Command Deploy

```bash
# From your local machine
./deploy.sh <server-ip> sajha.yourdomain.com
```

This script:
1. Copies files to your Hetzner server
2. Installs Docker if needed
3. Generates secure passwords
4. Starts SAJHA + PostgreSQL + Caddy
5. Caddy auto-provisions SSL

## Option 2: Cloud-Init (fully automated)

```bash
# Create server with cloud-init (auto-deploys on first boot)
hcloud server create \
  --name sajha \
  --type cx22 \
  --image ubuntu-24.04 \
  --location nbg1 \
  --ssh-key your-key \
  --user-data-from-file cloud-init.yml
```

## Option 3: Manual Setup

```bash
# SSH into your Hetzner server
ssh root@<server-ip>

# Clone repo
git clone https://github.com/ajsinha/sajhamcpserver.git
cd sajhamcpserver/deployment/hetzner

# Configure
cp .env.example .env
nano .env  # Set domain, passwords, API keys

# Update Caddyfile with your domain
sed -i 's/sajha.example.com/your-domain.com/' Caddyfile

# Deploy
docker compose up -d
```

## Recommended Hetzner Server Types

| Type | vCPU | RAM | Storage | Cost | Suitable For |
|------|-----:|----:|--------:|-----:|-------------|
| CX22 | 2 | 4 GB | 40 GB | €4.35/mo | Dev/staging |
| CX32 | 4 | 8 GB | 80 GB | €7.49/mo | Small production |
| CX42 | 8 | 16 GB | 160 GB | €15.49/mo | Medium production |
| CCX23 | 4 | 16 GB | 80 GB | €15.49/mo | CPU-intensive (many tools) |

## Hetzner Managed Database (optional)

Instead of running PostgreSQL in Docker, use Hetzner's managed database:

```bash
# Create managed PostgreSQL
hcloud database create --name sajha-db --type cx22 --database-type postgresql-16

# Update .env
SAJHA_DB_HOST=<managed-db-host>
SAJHA_DB_PORT=5432
SAJHA_DB_NAME=sajha
SAJHA_DB_USER=sajha
SAJHA_DB_PASSWORD=<managed-db-password>
```

Then remove the `postgres` service from `docker-compose.yml`.

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | SAJHA + PostgreSQL + Caddy (auto-SSL) |
| `Caddyfile` | Reverse proxy with automatic HTTPS |
| `.env.example` | Environment variables template |
| `cloud-init.yml` | Automated server setup on first boot |
| `deploy.sh` | One-command deployment script |

## WebSocket Support

Caddy automatically handles WebSocket upgrade headers. Connect via:

```
wss://your-domain.com/mcp/ws?token=<jwt>
```

## Backup

```bash
# Database backup
docker exec sajha-postgres pg_dump -U sajha sajha > backup.sql

# Full backup (data + config)
docker compose stop
tar czf sajha-backup.tar.gz pgdata/ sajha-data/ sajha-config/ .env
docker compose start
```

## Costs

| Component | Monthly |
|-----------|--------:|
| CX22 server | €4.35 |
| 20 GB volume (optional) | €0.96 |
| Managed DB (optional) | €6.90 |
| **Total (self-hosted DB)** | **€4.35** |
| **Total (managed DB)** | **€11.25** |

~95% cheaper than equivalent AWS setup.

---

*SAJHA MCP Server v4.0.0 — Hetzner Deployment*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
