#!/bin/bash
# ============================================================================
# SAJHA MCP Server — curl Examples
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha
#
# Replace BASE_URL, API_KEY, and credentials with your values.
# ============================================================================

BASE_URL="http://localhost:3002"
API_KEY="sja_your_api_key_here"

echo "=== Health Check ==="
curl -s "$BASE_URL/health" | python3 -m json.tool

echo ""
echo "=== Login (get JWT token) ==="
TOKEN=$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "admin", "password": "admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
echo "Token: ${TOKEN:0:40}..."

echo ""
echo "=== List Tools (API Key auth) ==="
curl -s "$BASE_URL/api/tools/list" \
  -H "X-API-Key: $API_KEY" | python3 -m json.tool | head -20

echo ""
echo "=== List Tools (JWT auth) ==="
curl -s "$BASE_URL/api/tools/list" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool | head -20

echo ""
echo "=== Execute Tool ==="
curl -s -X POST "$BASE_URL/api/tools/execute" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "tool": "fmp_stock_quote",
    "arguments": {"symbol": "AAPL"}
  }' | python3 -m json.tool

echo ""
echo "=== MCP Initialize ==="
curl -s -X POST "$BASE_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"clientInfo": {"name": "curl-client", "version": "1.0"}}
  }' | python3 -m json.tool

echo ""
echo "=== MCP tools/list ==="
curl -s -X POST "$BASE_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}' \
  | python3 -m json.tool | head -30

echo ""
echo "=== MCP tools/call ==="
curl -s -X POST "$BASE_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "fmp_stock_quote", "arguments": {"symbol": "MSFT"}}
  }' | python3 -m json.tool

echo ""
echo "=== MCP Ping ==="
curl -s -X POST "$BASE_URL/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 4, "method": "ping", "params": {}}' \
  | python3 -m json.tool

echo ""
echo "=== A2A Agent Card ==="
curl -s "$BASE_URL/.well-known/agent.json" | python3 -m json.tool | head -20

echo ""
echo "=== A2A Send Task ==="
curl -s -X POST "$BASE_URL/a2a" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tasks/send",
    "params": {
      "message": {"parts": [{"type": "text", "text": "Get AAPL stock quote"}]}
    }
  }' | python3 -m json.tool

echo ""
echo "=== Reports: Overview ==="
curl -s "$BASE_URL/api/reports/overview?period=24h" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo ""
echo "=== Reports: Tool Usage ==="
curl -s "$BASE_URL/api/reports/tools/usage?period=7d" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo ""
echo "=== Reports: Audit Log ==="
curl -s "$BASE_URL/api/reports/audit?limit=5" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo ""
echo "=== Admin: List Users ==="
curl -s "$BASE_URL/api/admin/users" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo ""
echo "=== Admin: Create User ==="
curl -s -X POST "$BASE_URL/api/admin/users/create" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "user_id": "curl_test",
    "user_name": "Curl Test User",
    "password": "test123",
    "roles": ["analyst"]
  }' | python3 -m json.tool

echo ""
echo "=== SSE Transport (streaming) ==="
echo "Run this in a separate terminal to test SSE:"
echo "  curl -N '$BASE_URL/mcp/sse' -H 'Authorization: Bearer $TOKEN'"
