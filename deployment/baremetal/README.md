# SAJHA MCP Server — Bare Metal Deployment

Install SAJHA directly on a Linux server with systemd, Nginx, and PostgreSQL. No containers.

## Architecture

```
Internet → Nginx (port 443, SSL via Let's Encrypt)
             → SAJHA (127.0.0.1:3002, systemd service)
                  → PostgreSQL (localhost:5432)
                  → Filesystem: /opt/sajha/data, /opt/sajha/config
```

## Automated Install

```bash
git clone https://github.com/ajsinha/sajhamcpserver.git
cd sajhamcpserver/deployment/baremetal
sudo ./install.sh
```

This script installs Python, PostgreSQL, Nginx, creates the `sajha` system user, sets up a virtualenv, configures the database, and starts the systemd service.

## Manual Install

### 1. System Packages

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip postgresql nginx certbot
```

**RHEL/Rocky:**
```bash
sudo dnf install -y python3 python3-pip postgresql-server nginx certbot
sudo postgresql-setup --initdb
```

### 2. PostgreSQL

```bash
sudo systemctl enable postgresql && sudo systemctl start postgresql
sudo -u postgres psql -c "CREATE USER sajha WITH PASSWORD 'your-password';"
sudo -u postgres psql -c "CREATE DATABASE sajha OWNER sajha;"
```

### 3. Application

```bash
sudo useradd --system --shell /bin/false --home-dir /opt/sajha --create-home sajha
sudo git clone https://github.com/ajsinha/sajhamcpserver.git /opt/sajha
cd /opt/sajha
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt
sudo chown -R sajha:sajha /opt/sajha
```

### 4. Environment

```bash
sudo cp deployment/baremetal/.env.example /opt/sajha/.env
sudo nano /opt/sajha/.env  # Set passwords, API keys
```

### 5. systemd Service

```bash
sudo cp deployment/baremetal/sajha.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sajha
sudo systemctl start sajha
```

### 6. Nginx + SSL

```bash
sudo cp deployment/baremetal/nginx.conf /etc/nginx/sites-available/sajha
sudo ln -s /etc/nginx/sites-available/sajha /etc/nginx/sites-enabled/
# Edit: replace sajha.yourdomain.com with your domain
sudo nano /etc/nginx/sites-available/sajha

# SSL certificate
sudo certbot --nginx -d sajha.yourdomain.com

sudo systemctl reload nginx
```

## Nginx Configuration Highlights

The provided `nginx.conf` handles all three transports:

| Path | Config | Why |
|------|--------|-----|
| `/` | Standard proxy | Regular HTTP requests |
| `/mcp/sse` | `proxy_buffering off` + 1hr timeout | SSE requires unbuffered, long-lived connections |
| `/mcp/ws` | `Upgrade: websocket` headers + 1hr timeout | WebSocket upgrade handshake |

## Management

```bash
# Service
sudo systemctl status sajha
sudo systemctl restart sajha
sudo systemctl stop sajha

# Logs
sudo journalctl -u sajha -f          # follow live
sudo journalctl -u sajha --since today

# Health
curl http://localhost:3002/health
curl http://localhost:3002/ready

# Update
cd /opt/sajha && sudo -u sajha git pull
sudo -u sajha ./venv/bin/pip install -r requirements.txt
sudo systemctl restart sajha
```

## Security Hardening

The systemd service includes:

| Setting | Effect |
|---------|--------|
| `NoNewPrivileges=true` | Prevents privilege escalation |
| `ProtectSystem=strict` | Mounts filesystem read-only except allowed paths |
| `ProtectHome=true` | Hides /home from the service |
| `PrivateTmp=true` | Isolated /tmp namespace |
| `ReadWritePaths` | Only /opt/sajha/data and /opt/sajha/config writable |

## Files

| File | Purpose |
|------|---------|
| `install.sh` | Automated installation (Ubuntu/Debian/RHEL) |
| `sajha.service` | systemd unit file |
| `nginx.conf` | Nginx reverse proxy (HTTP + SSE + WebSocket) |
| `.env.example` | Environment variables template |

## Recommended Hardware

| Workload | CPU | RAM | Disk |
|----------|----:|----:|-----:|
| Dev/testing | 2 cores | 4 GB | 20 GB |
| Small production (<10 users) | 4 cores | 8 GB | 50 GB |
| Medium production (<50 users) | 8 cores | 16 GB | 100 GB |
| Large (100+ concurrent tools) | 16 cores | 32 GB | 200 GB |

---

*SAJHA MCP Server v5.1.0 — Bare Metal Deployment*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
