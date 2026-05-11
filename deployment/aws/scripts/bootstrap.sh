#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# SAJHA MCP Server — Container Bootstrap Script
# Runs before uvicorn. Handles S3 sync, secrets injection,
# and database initialization.
# ═══════════════════════════════════════════════════════════════
set -e

echo "╔══════════════════════════════════════════════╗"
echo "║  SAJHA MCP Server v3.1.0 — Bootstrap        ║"
echo "║  Storage: ${SAJHA_STORAGE_BACKEND:-local}    ║"
echo "╚══════════════════════════════════════════════╝"

# ── 1. Inject secrets from AWS Secrets Manager ───────────────
if [ -n "$SAJHA_SECRETS_ARN" ]; then
    echo "[bootstrap] Fetching secrets from Secrets Manager..."
    SECRETS=$(aws secretsmanager get-secret-value \
        --secret-id "$SAJHA_SECRETS_ARN" \
        --query SecretString --output text 2>/dev/null || echo "{}")
    
    # Export each key as SAJHA_ env var
    for key in $(echo "$SECRETS" | python3 -c "import sys,json; [print(k) for k in json.load(sys.stdin)]" 2>/dev/null); do
        value=$(echo "$SECRETS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('$key',''))")
        export "SAJHA_${key^^}"="$value"
        echo "[bootstrap]   Set SAJHA_${key^^}"
    done
fi

# ── 2. Sync config from S3 (if S3 backend) ──────────────────
if [ "$SAJHA_STORAGE_BACKEND" = "s3" ] && [ -n "$SAJHA_S3_BUCKET" ]; then
    CACHE_DIR="${SAJHA_S3_CACHE_DIR:-/tmp/sajha-cache}"
    S3_PREFIX="${SAJHA_S3_PREFIX:-}"
    
    echo "[bootstrap] Syncing S3 → local cache..."
    echo "[bootstrap]   Bucket: $SAJHA_S3_BUCKET"
    echo "[bootstrap]   Prefix: $S3_PREFIX"
    echo "[bootstrap]   Cache:  $CACHE_DIR"
    
    mkdir -p "$CACHE_DIR/config/tools" "$CACHE_DIR/config/prompts" "$CACHE_DIR/sajha/tools/impl"
    
    # Sync tool configs
    aws s3 sync "s3://${SAJHA_S3_BUCKET}/${S3_PREFIX}config/tools/" \
        "$CACHE_DIR/config/tools/" --quiet 2>/dev/null || true
    
    # Sync prompt configs
    aws s3 sync "s3://${SAJHA_S3_BUCKET}/${S3_PREFIX}config/prompts/" \
        "$CACHE_DIR/config/prompts/" --quiet 2>/dev/null || true
    
    # Sync tool implementations (Python files)
    aws s3 sync "s3://${SAJHA_S3_BUCKET}/${S3_PREFIX}sajha/tools/impl/" \
        "$CACHE_DIR/sajha/tools/impl/" --quiet 2>/dev/null || true
    
    # Sync application.yml if present in S3
    aws s3 cp "s3://${SAJHA_S3_BUCKET}/${S3_PREFIX}config/application.yml" \
        "$CACHE_DIR/config/application.yml" --quiet 2>/dev/null || true
    
    TOOL_COUNT=$(ls "$CACHE_DIR/config/tools/"*.json 2>/dev/null | wc -l)
    echo "[bootstrap]   Synced: $TOOL_COUNT tool configs"
    
    # Add cache to PYTHONPATH so importlib finds synced .py files
    export PYTHONPATH="$CACHE_DIR:$PYTHONPATH"
    export SAJHA_BASE_DIR="$CACHE_DIR"
fi

# ── 3. Override config with env vars if set ──────────────────
# The SAJHA config system already handles SAJHA_ prefix env overrides,
# but we explicitly handle the most common ones for clarity
[ -n "$SAJHA_JWT_SECRET" ]    && echo "[bootstrap] JWT secret: set from environment"
[ -n "$SAJHA_FMP_API_KEY" ]   && echo "[bootstrap] FMP API key: set from environment"
[ -n "$SAJHA_FRED_API_KEY" ]  && echo "[bootstrap] FRED API key: set from environment"

# ── 4. Database setup ────────────────────────────────────────
if [ "$SAJHA_DB_TYPE" = "postgresql" ]; then
    echo "[bootstrap] Database: PostgreSQL at ${SAJHA_DB_HOST:-localhost}:${SAJHA_DB_PORT:-5432}"
    # Wait for RDS to be ready
    for i in $(seq 1 30); do
        if python3 -c "
import socket
s = socket.socket()
s.settimeout(2)
try:
    s.connect(('${SAJHA_DB_HOST:-localhost}', ${SAJHA_DB_PORT:-5432}))
    s.close()
    exit(0)
except:
    exit(1)
" 2>/dev/null; then
            echo "[bootstrap]   PostgreSQL ready"
            break
        fi
        echo "[bootstrap]   Waiting for PostgreSQL... ($i/30)"
        sleep 2
    done
else
    echo "[bootstrap] Database: SQLite at ${SAJHA_DB_PATH:-/app/data/sajha.db}"
    mkdir -p "$(dirname "${SAJHA_DB_PATH:-/app/data/sajha.db}")"
fi

# ── 5. Start server ──────────────────────────────────────────
echo "[bootstrap] Starting SAJHA MCP Server..."
echo "[bootstrap]   Host: ${SERVER_HOST:-0.0.0.0}"
echo "[bootstrap]   Port: ${SERVER_PORT:-3002}"
echo "[bootstrap]   Workers: ${UVICORN_WORKERS:-1}"

exec python3 -m uvicorn sajha.app:create_app \
    --host "${SERVER_HOST:-0.0.0.0}" \
    --port "${SERVER_PORT:-3002}" \
    --workers "${UVICORN_WORKERS:-1}" \
    --log-level "${LOG_LEVEL:-info}" \
    --factory \
    "$@"
