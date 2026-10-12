# Per-User Sign-In for Proxied Servers

**Status: built, every mode: `token_user` (phase 7.2), `oauth_user` (phase 7.3) and
`service_with_user` (wave 9)**, with the default approval rule for proxied writes; what is built:
[§10](#10-what-is-built). How a proxied MCP server's tools should run
**as the person who asked**, with that person's own account at the vendor, instead of one shared
credential. It is the prerequisite for the [Google](Google%20Integration.md),
[GitHub](GitHub%20Integration.md) and [Atlassian](Atlassian%20Integration.md) integrations and for most
hosted MCP servers. How proxied servers work, and how to configure each mode, is in
[Federation](Federation.md#per-user-credentials-token_user); per-user accounts
for SAJHA's own tools are in [Connected Accounts](Connected%20Accounts.md).

## 1. The problem

Before this design, a proxied server got **one** credential from `config/mcp_servers.json` (a header
such as a bearer token). Every user's calls then reached the vendor as that one identity: they saw what
it saw and acted as it. A server that asks each user to sign in answered HTTP 401 and could not be used.
Hosted servers from Google, GitHub, Atlassian, Notion, Linear and others work that way.

## 2. Credential modes

Each proxied server declares how it authenticates (a new `auth` key per entry; today's static header
stays the default, so nothing changes for existing entries):

| Mode | Who the vendor sees | When to use |
|---|---|---|
| `static` (the default) | One shared identity | Public data, a service account for read-only organisation data, servers without user sign-in |
| `oauth_user` | Each user, after they connect once | Hosted servers with OAuth (Google, GitHub, Atlassian Cloud, Notion, Linear) |
| `token_user` | Each user, with a personal token they paste once | Personal access tokens (GitHub PAT, Jira and Confluence Data Center tokens) |
| `service_with_user` | A shared identity, with the SAJHA user named in an audit header the vendor records | Vendors that support acting on behalf of users from a service identity |

## 3. At call time

1. SAJHA knows the caller (signed-in user, API-key owner, or a SAJHA Net user mapped to a local user).
2. It looks up that user's credential for this server in the encrypted vault (the connected-accounts
   vault, keyed by user and server).
3. A valid credential is sent with the call; an expired OAuth token is refreshed first.
4. No credential, or a refresh that fails: the call answers **"connect your account"** with a link, in
   each transport's own form (an input request on MCP 2026-07-28, URL elicitation on 2025-11-25, HTTP
   428 on REST, a Connect button in Ask SAJHA) — the same answers connected accounts already give.
5. The vendor refuses the user (scope or permission): the error is passed back as the vendor's answer,
   never retried as another identity.

## 4. Connecting

- **OAuth discovery:** read the server's protected-resource metadata (RFC 9728) and its authorization
  server's metadata (RFC 8414); register a client dynamically where the vendor allows it, otherwise use
  a client the operator registered (Google, GitHub organisation apps) configured by reference to an
  environment variable.
- **Authorization code with PKCE and `state`;** the redirect URI is SAJHA's own, on an allowlist.
- **Resource indicators (RFC 8707)** so each token is bound to the server it was issued for.
- **Least privilege:** read scopes by default; write scopes requested only for users and servers that
  need them.
- **A "Connections" view** for each user (connect, see scopes, disconnect) and for administrators
  (who is connected to what; revoke).

## 5. Sessions and discovery

- **Stateless servers (MCP 2026-07-28):** the user's token rides on each request; no per-user state.
- **Session-based servers (2025-11-25):** one upstream session per user, opened on first use and closed
  when idle, with a cap per server.
- **Tool lists can differ per user** (for example GitHub hides tools a token's scopes do not allow).
  SAJHA discovers the catalog with a representative identity or on a user's first connection, offers
  the union, and lets the vendor's per-call answer decide; a tool the user cannot use is never run
  under another identity.

## 6. SAJHA Net

Tokens never leave the server that holds them. A user on another member who calls a per-user proxied
tool is mapped to a local user at the defining server as usual; if that local user has not connected,
the "connect your account" request travels back to the caller as an input request (built in wave 6).
Residency rules keep vendor content on the defining server unless a rule allows otherwise.

## 7. Security rules

- **No token passthrough:** SAJHA never forwards a caller's SAJHA token or API key to a vendor (MCP
  forbids it), and never forwards a vendor token to another server.
- Tokens encrypted at rest; never logged; never shown after connection.
- Revocation: disabling a user, revoking their sessions, or disconnecting deletes their vendor tokens.
- Every call records which identity acted (user, mode, server) in the audit trail.
- Writes (send, create, update, delete, share, merge) require approval by default policy.
- Content from vendors is untrusted text for the planners (prompt injection); see the
  [Adversarial QA Plan](Adversarial%20QA%20Plan.md).

## 8. Background work

Workflows and scheduled jobs run as their owner and use the owner's connection. An expired or missing
connection fails the run with a clear notice instead of silently using another identity.

## 9. Build order

1. `auth` modes and the vault lookup; `token_user` first (simplest: no OAuth flow), tested against a
   fake server that checks per-user tokens.
2. `oauth_user` with discovery, PKCE, refresh and the Connections view; tested against a fake OAuth
   authorization server and MCP server.
3. Per-user sessions for 2025-11-25 servers; per-user discovery.
4. SAJHA Net relay of "connect your account"; audit and revocation; documentation and a tutorial.

## 10. What is built

The modes are configured and operated as described in [Federation §3](Federation.md#per-user-credentials-token_user)
(personal tokens), [Per-user OAuth sign-in](Federation.md#per-user-oauth-sign-in-oauth_user) and
[A shared identity naming the user](Federation.md#a-shared-identity-naming-the-user-service_with_user);
the walkthrough is [Tutorial 42](../tutorials/TUTORIAL_42_per_user_sign_in.md).

| Design item | Built |
|---|---|
| Credential modes (§2) | `auth.type` `static` (default; today's headers and credentials, unchanged), `token_user` (phase 7.2), `oauth_user` (phase 7.3) and `service_with_user` (wave 9: the shared credential in `auth.service`, the caller's SAJHA user id in `auth.user_header`, default `X-SAJHA-User`, shaped by `user_format`; discovery with the service identity alone; anonymous callers refused; on a session-based upstream a session per user), in `federation.upstreams`, console-added upstreams and `config/mcp_servers.json` alike. |
| At call time (§3) | The caller (signed-in user, owned API key's owner, SAJHA Net mapped user) → their token from the vault (`upstream:<id>`) → sent with that call only. An OAuth token due within `accounts.refresh_skew_seconds` is refreshed first. No token, or a refused refresh: the connected-accounts "connect your account" answers on every front end. Anonymous callers refused. A vendor 401 to an OAuth token refreshes it once and retries; otherwise a 401/403 is passed back and (for a personal token, or a refused OAuth refresh) the connection is marked "needs re-connect"; never retried as anyone else. |
| Connecting (§4) | Personal tokens: the connect page with the token's label, where to create one, prefix/pattern checks and a test call. OAuth: discovery of the server's protected-resource metadata (RFC 9728, from the 401's `WWW-Authenticate` or the well-known URL) and its authorization server's metadata (RFC 8414 or OpenID Connect discovery), or operator-given endpoints; dynamic client registration (RFC 7591) or an operator-registered client (`client_id`, `client_secret_ref`); authorization code with PKCE `S256` and `state` on the connected-accounts machinery; one allowlisted redirect URI (`/account/server-connections/oauth/callback`); the resource indicator (RFC 8707) on authorization, token and refresh requests; read `scopes` by default and `write_scopes` only for users who opt in. The Connections view per user and the administrators' view show both kinds (OAuth: scopes and expiry), with revoke. |
| Sessions and discovery (§5) | Per request on 2026-07-28 upstreams; one session per user on session-based ones (idle close, cap per upstream; a refreshed OAuth token opens a new one); discovery with a discovery credential or the first connected user's token (refreshed when due), the union of what users' tokens list. |
| SAJHA Net (§6) | The connect request relayed back to a remote caller as an input request; the token stays on the defining server. |
| Security (§7) | Encrypted in the vault, never logged or returned; revoked (OAuth tokens also at the vendor, RFC 7009, where advertised) when a user disconnects, is disabled or deleted on the console or in the users file, or signs out everywhere; every connect, refresh, disconnect and refusal audited (`proxied_connection.*`), every call's audit record names the identity mode and user. Discovered URLs pass the federation URL guard and must be https. Writes: the shipped, enabled policy `config/policies/20-proxied-writes.yaml` requires approval for every proxied tool without `readOnlyHint: true` (the person at the client confirms where it can, else an administrator); `enabled: false` in that file switches it off ([Policy and Audit §5.1](Policy%20and%20Audit.md#51-the-shipped-rule-for-proxied-writes)). |
| Background work (§8) | Workflows and scheduled jobs run as their owner, so they use the owner's token; a missing token fails the step with the connect message. |

**Limits:** the write rule trusts the vendor's `readOnlyHint` (a tool that wrongly claims it is not
caught); `service_with_user` names the user by SAJHA user id only, and the vendor decides what the
service identity may do for that user.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
