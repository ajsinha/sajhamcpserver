#!/usr/bin/env python3
"""
Example: SAJHA Client with OAuth 2.0 Authentication

For enterprise deployments where SAJHA is protected by an
external Identity Provider (Azure AD, Okta, Auth0, Keycloak).
"""

from sajhaclient import SajhaClient, SajhaConfig, OAuthAuth

# ── Azure AD Example ─────────────────────────────────────────────
auth = OAuthAuth(
    token_url="https://login.microsoftonline.com/YOUR_TENANT_ID/oauth2/v2.0/token",
    client_id="your-app-client-id",
    client_secret="your-client-secret",
    scope="api://sajha-mcp-server/.default",
)

client = SajhaClient(
    SajhaConfig(base_url="https://sajha.yourcompany.com"),
    auth=auth,
)

# Auth is handled — use normally
tools = client.list_tools()
print(f"Tools: {len(tools)}")

# ── Okta Example ─────────────────────────────────────────────────
# auth = OAuthAuth(
#     token_url="https://yourorg.okta.com/oauth2/default/v1/token",
#     client_id="0oa...",
#     client_secret="...",
#     scope="sajha",
# )

# ── Auth0 Example ────────────────────────────────────────────────
# auth = OAuthAuth(
#     token_url="https://yourorg.auth0.com/oauth/token",
#     client_id="...",
#     client_secret="...",
#     scope="sajha:tools:execute",
# )

# ── Keycloak Example ─────────────────────────────────────────────
# auth = OAuthAuth(
#     token_url="https://keycloak.yourcompany.com/realms/sajha/protocol/openid-connect/token",
#     client_id="sajha-client",
#     client_secret="...",
# )
