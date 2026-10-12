# Atlassian Integration

**Status: works per user: Atlassian Cloud with each user's Atlassian sign-in (`oauth_user`), Data Center
with personal access tokens (`token_user`).** How SAJHA reaches Jira, Confluence
and other Atlassian products. Acting as each user rests on
[Per-User Sign-In for Proxied Servers](Per-User%20Sign-In%20for%20Proxied%20Servers.md).
How proxied servers work is in [Federation](Federation.md).

## 1. Recommendation

- **Atlassian Cloud:** proxy Atlassian's official Rovo MCP server as an external server
  (`vendor: atlassian`, tools as `atlassian__<tool>`), each user signed in with their own Atlassian
  account (OAuth 2.1).
- **Jira and Confluence Data Center (self-hosted):** run a well-maintained self-hosted MCP server
  (for example the community `mcp-atlassian` project) beside SAJHA and proxy it as an internal server,
  each user with a personal access token (`token_user`).

## 2. What Atlassian offers

- **The Rovo MCP server** (Atlassian Cloud only) covers Jira, Confluence and Compass and respects each
  user's permissions. Clients sign users in with OAuth 2.1; Atlassian also documents API-token access for
  machine-to-machine use when an administrator enables it
  ([Atlassian: getting started](https://developer.atlassian.com/cloud/rovo-mcp/guides/getting-started/),
  [Atlassian: configuring OAuth 2.1](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-oauth-2-1)).
- **Endpoint:** Atlassian's documentation points to a Streamable HTTP endpoint under
  `mcp.atlassian.com/v1/`; the older `/v1/sse` endpoint was retired after 30 June 2026. Third-party
  guides disagree on the exact path, so take it from Atlassian's current documentation.
- **Data Center:** no official remote server; community servers run on your own infrastructure.

## 3. What works today

- **Data Center, each user with their own personal access token** (`token_user`): run a self-hosted MCP
  server for Jira and Confluence on your network and copy
  `config/mcp_servers/12_atlassian_datacenter_token_user.json.example` (internal upstreams `jira_dc` and
  `confluence_dc`; set the header format your server expects). Each user saves their Data Center personal
  access token once on **Server connections**; calls carry it, so Jira's and Confluence's own permissions
  apply, and a user without one is asked to connect. Configuration and behaviour:
  [Federation §3, Per-user credentials](Federation.md#per-user-credentials-token_user).
- **Cloud with one shared API token** (where the administrator enabled API-token access) can be proxied
  with a static header, but then **every SAJHA user acts as that one Atlassian account**: suitable only for
  a read-only service account with narrow access.
- **Cloud, each user with their own Atlassian sign-in** (`oauth_user`): copy
  `config/mcp_servers/13_atlassian_cloud_oauth.json.example` and set `accounts.public_url`. Nothing is
  registered by hand: SAJHA reads the server's OAuth metadata and registers itself with Atlassian's
  authorization server (dynamic client registration, which Atlassian's OAuth 2.1 setup for MCP clients
  provides; [configuring OAuth 2.1](https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-oauth-2-1)).
  Each user clicks "Connect with Atlassian" on Server connections and approves at Atlassian; calls then
  run with that user's Jira and Confluence permissions, tokens are refreshed before they expire, and a
  user whose sign-in Atlassian stops accepting is asked to connect again. Take the endpoint path from
  Atlassian's current documentation (the template's `_comment` says so); a site administrator may have to
  allow the MCP server for your site first. Configuration and behaviour:
  [Federation, Per-user OAuth sign-in](Federation.md#per-user-oauth-sign-in-oauth_user).

## 4. With per-user sign-in

- Each user connects Atlassian once; Jira and Confluence permissions are Atlassian's own.
- Read tools first (search issues with JQL, read issues and comments, search and read Confluence
  pages); writes — creating or transitioning issues, commenting, creating or editing pages — behind
  the shipped approval rule for proxied writes ([Policy and Audit §5.1](Policy%20and%20Audit.md#51-the-shipped-rule-for-proxied-writes)).

## 5. Uses with the rest of SAJHA

- Ask SAJHA: "summarise the open risk-limit breaches in Jira and link the Confluence runbook".
- Workflows: raise or update a Jira issue (with approval) when a scheduled risk check breaches a limit;
  publish a weekly report page to Confluence (with approval).
- Residency: Confluence pages often carry internal material — classify Atlassian results so they stay
  on the server that fetched them unless a rule allows otherwise.

## 6. Risks

- Pages, issue descriptions and comments are untrusted text (prompt injection); approvals on writes.
- Broad OAuth scopes: request read scopes by default.
- The Cloud server does not reach Data Center sites; plan both routes if the organisation runs both.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
