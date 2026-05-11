# ═══════════════════════════════════════════════════════════════
# SAJHA MCP Server v3.1.0 — Production Docker Image
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha
#
# Multi-stage build: build deps → production image
# Runs on ECS Fargate, EKS, Docker Compose, or bare metal
# ═══════════════════════════════════════════════════════════════

# ── Stage 1: Build dependencies ──────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && pip install --no-cache-dir --prefix=/install boto3 awscli

# ── Stage 2: Production image ────────────────────────────────
FROM python:3.11-slim AS production

LABEL maintainer="Ashutosh Sinha <ajsinha@gmail.com>"
LABEL version="3.1.0"
LABEL description="SAJHA MCP Server — Production Container"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd -r sajha && useradd -r -g sajha -d /app -s /sbin/nologin sajha

WORKDIR /app

# ── Copy application code (immutable in image) ───────────────
# Core framework, routes, templates, static assets, SQL scripts
COPY sajha/           /app/sajha/
COPY run_server.py    /app/
COPY db/              /app/db/

# ── Copy default configs (overridden at runtime by S3 or mount) ─
COPY config/application.yml  /app/config/application.yml
COPY config/tools/           /app/config/tools/
COPY config/prompts/         /app/config/prompts/

# ── Copy AWS bootstrap and health check ──────────────────────
COPY aws/scripts/bootstrap.sh  /app/bootstrap.sh
COPY aws/scripts/health_check.sh /app/health_check.sh
RUN chmod +x /app/bootstrap.sh /app/health_check.sh

# ── Create writable directories ──────────────────────────────
RUN mkdir -p /app/data /app/logs /tmp/sajha-cache && \
    chown -R sajha:sajha /app /tmp/sajha-cache

# ── Environment defaults ─────────────────────────────────────
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    SAJHA_STORAGE_BACKEND=local \
    SAJHA_DB_TYPE=sqlite \
    SAJHA_DB_PATH=/app/data/sajha.db \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=3002 \
    LOG_LEVEL=INFO

EXPOSE 3002

USER sajha

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/app/health_check.sh"]

ENTRYPOINT ["/app/bootstrap.sh"]
