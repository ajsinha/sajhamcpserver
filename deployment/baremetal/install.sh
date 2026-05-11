#!/bin/bash
# SAJHA MCP Server — Bare Metal Installation Script
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha
#
# Tested on: Ubuntu 22.04/24.04, Debian 12, RHEL 9, Rocky 9
# Usage: sudo ./install.sh
#
set -euo pipefail

echo "═══════════════════════════════════════════════"
echo "  SAJHA MCP Server v4.0.0 — Bare Metal Install"
echo "═══════════════════════════════════════════════"

# ── Check root ──
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: Run as root (sudo ./install.sh)"
    exit 1
fi

# ── Detect OS ──
if [ -f /etc/debian_version ]; then
    PKG_MGR="apt-get"
    PKG_INSTALL="apt-get install -y"
    PG_SERVICE="postgresql"
elif [ -f /etc/redhat-release ]; then
    PKG_MGR="dnf"
    PKG_INSTALL="dnf install -y"
    PG_SERVICE="postgresql-server"
else
    echo "WARNING: Unsupported OS. Install manually."
fi

# ── 1. System packages ──
echo "→ Installing system packages..."
$PKG_INSTALL python3 python3-venv python3-pip postgresql nginx certbot python3-certbot-nginx curl git

# ── 2. Create user ──
echo "→ Creating sajha user..."
useradd --system --shell /bin/false --home-dir /opt/sajha --create-home sajha 2>/dev/null || true

# ── 3. Clone/copy application ──
echo "→ Installing SAJHA..."
if [ -d "/opt/sajha/sajha" ]; then
    echo "  Application already exists, updating..."
    cd /opt/sajha && git pull 2>/dev/null || true
else
    git clone https://github.com/ajsinha/sajhamcpserver.git /opt/sajha
fi

# ── 4. Python virtual environment ──
echo "→ Setting up Python venv..."
python3 -m venv /opt/sajha/venv
/opt/sajha/venv/bin/pip install --upgrade pip
/opt/sajha/venv/bin/pip install -r /opt/sajha/requirements.txt

# ── 5. PostgreSQL setup ──
echo "→ Configuring PostgreSQL..."
systemctl enable $PG_SERVICE
systemctl start $PG_SERVICE

sudo -u postgres psql -c "CREATE USER sajha WITH PASSWORD 'sajha_secure_2025';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE sajha OWNER sajha;" 2>/dev/null || true

# ── 6. Environment file ──
echo "→ Creating environment file..."
if [ ! -f /opt/sajha/.env ]; then
    cat > /opt/sajha/.env << 'ENVEOF'
SAJHA_DB_USER=sajha
SAJHA_DB_PASSWORD=sajha_secure_2025
SAJHA_JWT_SECRET=$(openssl rand -hex 32)
# Add your API keys:
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
ENVEOF
    # Generate actual JWT secret
    JWT=$(openssl rand -hex 32)
    sed -i "s/\$(openssl rand -hex 32)/$JWT/" /opt/sajha/.env
fi

# ── 7. Directory permissions ──
echo "→ Setting permissions..."
mkdir -p /opt/sajha/data /opt/sajha/config/plugins
chown -R sajha:sajha /opt/sajha

# ── 8. systemd service ──
echo "→ Installing systemd service..."
cp /opt/sajha/deployment/baremetal/sajha.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable sajha
systemctl start sajha

# ── 9. Nginx ──
echo "→ Configuring Nginx..."
cp /opt/sajha/deployment/baremetal/nginx.conf /etc/nginx/sites-available/sajha
ln -sf /etc/nginx/sites-available/sajha /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

echo ""
echo "═══════════════════════════════════════════════"
echo "  SAJHA MCP Server installed!"
echo ""
echo "  Next steps:"
echo "  1. Edit /opt/sajha/.env (set API keys)"
echo "  2. Edit /etc/nginx/sites-available/sajha (set domain)"
echo "  3. sudo certbot --nginx -d your-domain.com"
echo "  4. sudo systemctl restart sajha"
echo ""
echo "  Status: sudo systemctl status sajha"
echo "  Logs:   sudo journalctl -u sajha -f"
echo "  Test:   curl http://localhost:3002/health"
echo "═══════════════════════════════════════════════"
