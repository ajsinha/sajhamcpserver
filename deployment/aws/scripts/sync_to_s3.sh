#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# Upload local config/tools to S3 for ECS containers to consume
# Run this from the project root on your dev machine:
#   ./aws/scripts/sync_to_s3.sh my-sajha-bucket v3.1.0
# ═══════════════════════════════════════════════════════════════
set -e

BUCKET="${1:?Usage: sync_to_s3.sh <bucket> [prefix]}"
PREFIX="${2:-}"

echo "Uploading SAJHA configs to s3://$BUCKET/$PREFIX ..."

# Tool JSON configs (501 files)
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

# Application config (without secrets — those go to Secrets Manager)
aws s3 cp config/application.yml "s3://$BUCKET/${PREFIX}config/application.yml"
echo "  ✓ application.yml"

# Legacy user/apikey JSON
aws s3 cp config/users.json "s3://$BUCKET/${PREFIX}config/users.json" 2>/dev/null || true
aws s3 cp config/apikeys.json "s3://$BUCKET/${PREFIX}config/apikeys.json" 2>/dev/null || true

echo ""
echo "Done. ECS containers will sync from s3://$BUCKET/$PREFIX at startup."
echo "To update tools in production: edit locally → run this script → containers auto-sync."
