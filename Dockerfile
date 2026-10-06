# syntax=docker/dockerfile:1
# ═══════════════════════════════════════════════════════════════════════════
# SAJHA MCP Server: production container image
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha
#
# Used by the Helm chart (charts/sajha) and the Kustomize manifests (deployment/k8s).
# Guide: docs/getting-started/Kubernetes Deployment.md
#
#   docker build -t sajha:dev .
#   docker build -t sajha:full \
#       --build-arg EXTRAS="redis s3 azure gcs otel" \
#       --build-arg WITH_OPENBB=true \
#       --build-arg PLAYGROUND_ASSETS=true .
#
# Build arguments
#   PYTHON_VERSION     base image tag (python:<v>-slim)
#   EXTRAS             optional packages, space separated:
#                        redis  state.backend: redis
#                        s3     storage.backend: s3 (boto3; also the bedrock provider)
#                        azure  storage.backend: azure
#                        gcs    storage.backend: gcs
#                        otel   OpenTelemetry OTLP export
#   WITH_OPENBB        true installs the OpenBB SDK (several hundred MB); the openbb_*
#                      tools report an error without it
#   PLAYGROUND_ASSETS  true vendors Pyodide into the image (scripts/fetch_pyodide.py,
#                      about 60 MB); otherwise set playground.assets: cdn, or the
#                      playground says its assets are missing
#
# The image runs as UID/GID 10001, writes only to /app/data, /app/logs, /app/temp,
# /app/config, /app/sajha/tools/impl and /tmp, and so runs with a read-only root
# filesystem when those are mounted (the chart does this).
# ═══════════════════════════════════════════════════════════════════════════

ARG PYTHON_VERSION=3.13

# ── Stage 1: Python dependencies in a virtual environment ─────────────────
FROM python:${PYTHON_VERSION}-slim AS deps

ARG EXTRAS="redis"
ARG WITH_OPENBB=false

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY requirements.txt /tmp/requirements.txt
RUN set -eux; \
    # test tools are not runtime dependencies; OpenBB only on request
    grep -v -E '^(pytest|pytest-asyncio)([<>=\[ ]|$)' /tmp/requirements.txt > /tmp/req.txt; \
    if [ "$WITH_OPENBB" != "true" ]; then sed -i '/^openbb/d' /tmp/req.txt; fi; \
    pip install -r /tmp/req.txt; \
    pkgs=""; \
    for e in $EXTRAS; do \
      case "$e" in \
        redis) pkgs="$pkgs redis>=5.0.0,<9.0.0" ;; \
        s3|boto3) pkgs="$pkgs boto3>=1.34.0,<2.0.0" ;; \
        azure) pkgs="$pkgs azure-storage-blob>=12.19.0,<13.0.0 azure-identity>=1.15.0,<2.0.0" ;; \
        gcs) pkgs="$pkgs google-cloud-storage>=2.14.0,<4.0.0" ;; \
        otel) pkgs="$pkgs opentelemetry-sdk>=1.20.0,<2.0.0 opentelemetry-exporter-otlp>=1.20.0,<2.0.0" ;; \
        *) echo "unknown EXTRAS entry: $e" >&2; exit 1 ;; \
      esac; \
    done; \
    if [ -n "$pkgs" ]; then pip install $pkgs; fi; \
    find /opt/venv -name '__pycache__' -prune -exec rm -rf {} +

# ── Stage 2: optional Pyodide assets for the Python Playground ────────────
FROM python:${PYTHON_VERSION}-slim AS playground

ARG PLAYGROUND_ASSETS=false
WORKDIR /src
COPY scripts/fetch_pyodide.py scripts/fetch_pyodide.py
RUN set -eux; mkdir -p /out; \
    if [ "$PLAYGROUND_ASSETS" = "true" ]; then python scripts/fetch_pyodide.py --dest /out; fi

# ── Stage 3: runtime ──────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="SAJHA MCP Server" \
      org.opencontainers.image.description="Model Context Protocol server (FastAPI)" \
      org.opencontainers.image.source="https://github.com/ajsinha/sajhamcpserver" \
      org.opencontainers.image.authors="Ashutosh Sinha <ajsinha@gmail.com>"

# tini reaps the sandbox's child processes and forwards SIGTERM
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends tini ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --system --gid 10001 sajha; \
    useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin sajha

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
# Code and defaults are owned by root and read-only to the server user.
COPY run_server.py ./
COPY sajha/ sajha/
COPY config/ config/
COPY db/ db/
COPY scripts/ scripts/
# In-app help renders docs/ and GLOSSARY.md; guide links may point at these files.
COPY docs/ docs/
COPY GLOSSARY.md README.md CHANGELOG.md ./
COPY deployment/README.md deployment/README.md
COPY --from=playground /out/ sajha/web/static/vendor/pyodide/

# Writable directories (the chart mounts volumes over them)
RUN set -eux; \
    mkdir -p data logs temp; \
    chown -R sajha:sajha data logs temp config sajha/tools/impl; \
    chmod -R a+rX /app

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=3002 \
    FORWARDED_ALLOW_IPS=127.0.0.1

USER 10001:10001
EXPOSE 3002

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('SERVER_PORT', '3002'), timeout=4)"]

ENTRYPOINT ["/usr/bin/tini", "--", "python", "/app/run_server.py"]
CMD ["--host", "0.0.0.0"]
