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

# Deploy
docker compose pull 2>/dev/null || docker compose build
docker compose up -d

echo "SAJHA deployed. Point DNS A record for ${DOMAIN} to ${SERVER_IP}"
echo "Then access: https://${DOMAIN}"
REMOTE

echo "═══ Deployment complete ═══"
echo "1. Point DNS A record for ${DOMAIN} → ${SERVER_IP}"
echo "2. Caddy will auto-provision SSL certificate"
echo "3. Access: https://${DOMAIN}"
