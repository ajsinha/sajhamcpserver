#!/usr/bin/env python3
"""
Example: SAJHA Admin Operations

Manage users, tools, and API keys programmatically.
Requires admin role.
"""

from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(
    base_url="http://localhost:3002",
    username="admin",
    password="admin123",
))

# ── User Management ──────────────────────────────────────────────

# List users
users = client.admin_list_users()
print("Users:")
for u in users:
    print(f"  {u['user_id']:15s}  roles={u['roles']}  enabled={u['enabled']}")

# Create a new user
client.admin_create_user(
    user_id="analyst1",
    user_name="Jane Analyst",
    password="securepass123",
    roles=["analyst"],
    email="jane@company.com",
)
print("\nCreated user: analyst1")

# Disable a user
client.admin_disable_user("analyst1")
print("Disabled user: analyst1")

# Re-enable
client.admin_enable_user("analyst1")
print("Re-enabled user: analyst1")

# ── Tool Management ──────────────────────────────────────────────

# Disable a tool
client.admin_disable_tool("fmp_senate_trading")
print("\nDisabled tool: fmp_senate_trading")

# Re-enable
client.admin_enable_tool("fmp_senate_trading")
print("Re-enabled tool: fmp_senate_trading")

# Reload all tools from config
client.admin_reload_tools()
print("All tools reloaded from config")

# Get tool config
config = client.admin_get_tool_config("fmp_stock_quote")
print(f"\nfmp_stock_quote config keys: {list(config.keys())}")

# ── Reports ──────────────────────────────────────────────────────

overview = client.report_overview("7d")
print(f"\n7-day overview: {overview}")

audit = client.report_audit(limit=5)
print(f"\nRecent audit entries: {len(audit.get('audit', []))}")

# ── Cleanup ──────────────────────────────────────────────────────
client.admin_delete_user("analyst1")
print("\nDeleted user: analyst1")
