#!/usr/bin/env python3
"""
Example: SAJHA REST Client with JWT (Username/Password) Authentication

Login with username and password. The SDK handles JWT token
management and auto-refresh.
"""

from sajhaclient import SajhaClient, SajhaConfig

# ── Method 1: Credentials in config (auto-login) ────────────────
client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    username="admin",
    password="admin123",
))
print(f"Auth type: {client.auth_type}")  # "jwt"

# ── Method 2: Login after creation ───────────────────────────────
client2 = SajhaClient(SajhaConfig(base_url="http://localhost:3002"))
token = client2.login("admin", "admin123")
print(f"JWT token: {token[:40]}...")

# ── Use the client normally ──────────────────────────────────────
tools = client.list_tools()
print(f"\nTools available: {len(tools)}")

# Execute tools
result = client.execute_tool("fmp_company_profile", symbol="MSFT")
print(f"\nMSFT Profile: {result}")

# Admin operations (requires admin role)
users = client.admin_list_users()
print(f"\nUsers: {[u['user_id'] for u in users]}")

# Reports
overview = client.report_overview(period="24h")
print(f"\nUsage (24h): {overview}")
