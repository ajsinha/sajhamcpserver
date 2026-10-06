#!/bin/bash
# SAJHA MCP Server — Hetzner Deployment Script
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha
#
# Usage: ./deploy.sh <server-ip> <domain>
#
set -euo pipefail

SERVER_IP="${1:?Usage: ./deploy.sh <server-ip> <domain>}"
DOMAIN="${2:?Usage: ./deploy.sh <server-ip> <domain>}"

echo "═══ SAJHA Hetzner Deployment ═══"
echo "Server: $SERVER_IP"
echo "Domain: $DOMAIN"

# 1. Copy files to server
echo "→ Copying deployment files..."
scp -r . root@${SERVER_IP}:~/sajha-deploy/

# 2. Run setup on server
echo "→ Running setup on server..."
ssh root@${SERVER_IP} << REMOTE
set -e
cd ~/sajha-deploy

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    apt-get update && apt-get install -y docker.io docker-compose-v2 curl
    systemctl enable docker && systemctl start docker
fi

# Configure
cp .env.example .env
sed -i "s/sajha.example.com/${DOMAIN}/" .env
sed -i "s/sajha.example.com/${DOMAIN}/" Caddyfile

# Generate secure passwords
DB_PASS=\$(openssl rand -hex 16)
JWT_SEC=\$(openssl rand -hex 32)
sed -i "s/your-strong-password-here/\${DB_PASS}/" .env
sed -i "s/your-jwt-secret-here/\${JWT_SEC}/" .env

# Firewall
ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable 2>/dev/null || true

# Deploy the database only: SAJHA does not create PostgreSQL tables, and refuses to
# start until the schema is applied (docs/getting-started/Database Setup.md).
docker compose pull 2>/dev/null || docker compose build
docker compose up -d postgres
REMOTE

echo "═══ Database is up; the schema is a manual step ═══"
echo "1. On ${SERVER_IP}, in ~/sajha-deploy: create the schema and the default roles/admin, once:"
echo "     docker compose run --rm --no-deps --entrypoint python3 sajha -m sajha.db sql --dialect postgresql > schema.sql"
echo "     docker compose run --rm --no-deps --entrypoint python3 sajha -m sajha.db sql --dialect postgresql --seed > seed.sql"
echo "     docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U sajha -d sajha < schema.sql"
echo "     docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U sajha -d sajha < seed.sql"
echo "2. Start SAJHA and Caddy:  docker compose up -d"
echo "3. Point DNS A record for ${DOMAIN} → ${SERVER_IP}; Caddy provisions the certificate"
echo "4. Access: https://${DOMAIN}"
