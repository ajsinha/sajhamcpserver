#!/bin/bash
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
# ═══════════════════════════════════════════════════════════════
# Upload local config/tools to S3 for ECS containers to consume
# Run this from the project root on your dev machine:
#   deployment/aws/scripts/sync_to_s3.sh my-sajha-bucket [prefix/]
# ═══════════════════════════════════════════════════════════════
set -e

BUCKET="${1:?Usage: sync_to_s3.sh <bucket> [prefix]}"
PREFIX="${2:-}"

echo "Uploading SAJHA configs to s3://$BUCKET/$PREFIX ..."

# Tool JSON configs (every file in config/tools; the count is printed below)
aws s3 sync config/tools/ "s3://$BUCKET/${PREFIX}config/tools/" \
    --exclude "*.md" --delete
echo "  ✓ config/tools/ → $(aws s3 ls "s3://$BUCKET/${PREFIX}config/tools/" | wc -l) files"

# Prompt configs
aws s3 sync config/prompts/ "s3://$BUCKET/${PREFIX}config/prompts/" \
    --exclude "*.md" --delete 2>/dev/null || true
echo "  ✓ config/prompts/"

# Tool Python implementations
aws s3 sync sajha/tools/impl/ "s3://$BUCKET/${PREFIX}sajha/tools/impl/" \
    --exclude "__pycache__/*" --exclude "*.pyc" --delete
echo "  ✓ sajha/tools/impl/"

# Studio-generated modules and scripts, where every instance materialises them from
# (docs/getting-started/Storage Guide.md, "Studio modules without a shared file system")
for f in sajha/tools/impl/studio_*.py sajha/tools/impl/dbquery_*.py sajha/tools/impl/rest_*.py \
         sajha/tools/impl/livelink_*.py sajha/tools/impl/powerbi_*.py sajha/tools/impl/powerbidax_*.py \
         sajha/tools/impl/*_script_tool.py; do
    [ -f "$f" ] && aws s3 cp "$f" "s3://$BUCKET/${PREFIX}studio/modules/$(basename "$f")" >/dev/null
done
[ -d config/scripts ] && aws s3 sync config/scripts/ "s3://$BUCKET/${PREFIX}config/scripts/" >/dev/null
echo "  ✓ studio/modules/, config/scripts/"

# Plugins (mirrored by every instance at start)
[ -d config/plugins ] && aws s3 sync config/plugins/ "s3://$BUCKET/${PREFIX}config/plugins/" \
    --exclude "__pycache__/*" --exclude "*.pyc" >/dev/null && echo "  ✓ config/plugins/"

# Application config (without secrets — those go to Secrets Manager)
aws s3 cp config/application.yml "s3://$BUCKET/${PREFIX}config/application.yml"
echo "  ✓ application.yml"

# API key JSON (users live in the database only; config/users.json is retired)
aws s3 cp config/apikeys.json "s3://$BUCKET/${PREFIX}config/apikeys.json" 2>/dev/null || true

echo ""
echo "Done. ECS containers will sync from s3://$BUCKET/$PREFIX at startup."
echo "To update tools in production: edit locally → run this script → containers auto-sync."
