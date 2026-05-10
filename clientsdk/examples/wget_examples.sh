#!/bin/bash
# ============================================================================
# SAJHA MCP Server — wget Examples
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha
# ============================================================================

BASE_URL="http://localhost:3002"
API_KEY="sja_your_api_key_here"

echo "=== Health Check ==="
wget -qO- "$BASE_URL/health"

echo ""
echo "=== Tool List (API Key) ==="
wget -qO- --header="X-API-Key: $API_KEY" "$BASE_URL/api/tools/list"

echo ""
echo "=== Agent Card ==="
wget -qO- "$BASE_URL/.well-known/agent.json"

echo ""
echo "=== Login ==="
wget -qO- --post-data='{"user_id":"admin","password":"admin123"}' \
  --header="Content-Type: application/json" \
  "$BASE_URL/api/auth/login"

echo ""
echo "=== MCP Ping ==="
wget -qO- --post-data='{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}' \
  --header="Content-Type: application/json" \
  "$BASE_URL/mcp"

echo ""
echo "=== Execute Tool ==="
wget -qO- --post-data='{"tool":"fmp_stock_quote","arguments":{"symbol":"AAPL"}}' \
  --header="Content-Type: application/json" \
  --header="X-API-Key: $API_KEY" \
  "$BASE_URL/api/tools/execute"

echo ""
echo "=== Download Report CSV ==="
# wget -O report.csv --header="Authorization: Bearer $TOKEN" \
#   "$BASE_URL/api/admin/tools/metrics/export"
