# Tutorial 42: Per-User Sign-In for Proxied Servers

A proxied MCP server can run its tools **as the person who asked**, with that person's own account at the
vendor, instead of one shared credential. SAJHA has two credential modes for that: `token_user` (each user
saves a personal token once) and `oauth_user` (each user signs in at the vendor once). This tutorial shows
the first with GitHub's remote server and then runs the second end to end, offline, against a fake OAuth
authorization server and MCP server that ship with the lab. The design is
[Per-User Sign-In for Proxied Servers](../architecture/Per-User%20Sign-In%20for%20Proxied%20Servers.md); every
key is in [Federation §3](../architecture/Federation.md#per-user-credentials-token_user).

**What was verified.** Part 2 (steps 3 to 9) was run as written against a scratch server (its own
database, on another port) with the fake server: sign-in, scopes, calls, write scopes, refresh, a refused
refresh and disconnect, with the console checked in a browser. Part 1 (steps 1 and 2) needs a GitHub
account and was not run for this tutorial; the same machinery is covered by `tests/test_proxied_per_user_tokens.py`.

## What you'll learn

- What `token_user` and `oauth_user` configure, and who the vendor sees
- How a user connects: a pasted token, or "Connect with <vendor>" and the vendor's consent page
- What SAJHA discovers (protected-resource and authorization-server metadata) and registers
- Read scopes by default, write scopes only when a user opts in
- Refresh, "needs re-connect", and revocation at the vendor

## Prerequisites

- SAJHA running from a checkout ([Quick Start](../getting-started/Quick%20Start.md)), with federation
  switched on; a scratch database is fine (`SAJHA_DB_PATH=/tmp/sajha42.db`)
- A browser, and for part 1 a GitHub account

## Part 1: personal tokens (`token_user`)

### 1. Add GitHub's remote server

Copy the template into `config/mcp_servers.json` (the file is git-ignored):

```bash
cp config/mcp_servers/11_github_token_user.json.example config/mcp_servers.json
```

The entry says `"auth": {"type": "token_user", ...}`: a header format (`Bearer {token}`), the label users
see, where to create a token, and a pattern that catches a pasted password before anything is sent.

### 2. Each user saves their token

Signed in as yourself, open **Server connections** in the user menu (`/account/server-connections`), click
**Connect** on GitHub, paste a personal access token and **Test and save**. SAJHA lists the server's tools
with it first, then keeps it encrypted and shows only its last four characters. Every `github__*` call you
make now carries your token; a colleague who has not saved one is asked to connect (an input request on MCP
2026-07-28, URL elicitation on 2025-11-25, HTTP 428 on REST, a Connect button in Ask SAJHA).

## Part 2: OAuth sign-in (`oauth_user`), offline

### 3. Start the fake vendor

```bash
python deployment/local-lab/fake_oauth_mcp.py --port 3020 --access-ttl 60
```

```text
MCP server (OAuth-protected): http://127.0.0.1:3020/mcp
Authorization server (issuer): http://127.0.0.1:3020/as  dynamic registration: on
```

[`fake_oauth_mcp.py`](../../deployment/local-lab/fake_oauth_mcp.py) is an OAuth authorization server
(metadata, dynamic client registration, an authorize form that believes the user name you type, token,
refresh with rotation, revocation) and an MCP server with three tools (`whoami`, `list_notes`,
`add_note`) that accepts only tokens it issued for itself. Without one it answers HTTP 401 with
`WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"`, which is
where SAJHA's discovery starts. `--access-ttl 60` makes access tokens last a minute, so you will see
refresh. Never use it outside a lab.

### 4. Add it as an `oauth_user` server

Write `config/mcp_servers.json` (or add the entry to the GitHub one):

```json
{
  "mcpServers": {
    "notes": {
      "url": "http://127.0.0.1:3020/mcp",
      "title": "Lab notes",
      "external": false,
      "auth": {"type": "oauth_user", "vendor": "Lab notes",
               "scopes": ["notes:read"], "write_scopes": ["notes:write"]}
    }
  }
}
```

No client id: SAJHA registers itself. Start SAJHA with federation on, loopback upstreams allowed (the fake
is on `127.0.0.1`), tool approval off for the lab, and the public address it is reached at, from which the
redirect URI derives:

```bash
SAJHA_FEDERATION_ENABLED=true SAJHA_FEDERATION_ALLOW_LOCALHOST=true SAJHA_FEDERATION_REQUIRE_APPROVAL=false \
SAJHA_ACCOUNTS_PUBLIC_URL=http://127.0.0.1:3002 python run_sajha_web.py --host 127.0.0.1 --port 3002
```

On **Admin > Proxied MCP servers** the `notes` upstream shows "waiting for a user to connect": it has no
discovery credential, so it lists its tools with the first user's token.

### 5. Connect with the vendor

Open **Server connections**, click **Connect** on Lab notes, then **Connect with Lab notes**. Your browser
goes to the fake's consent page; the address bar shows what SAJHA sent: `client_id=dyn_...` (the
registration it just made), `redirect_uri=http://127.0.0.1:3002/account/server-connections/oauth/callback`
(one callback for every upstream), `code_challenge_method=S256`, a `state`, `scope=notes:read` and
`resource=http://127.0.0.1:3020/mcp` (the resource indicator: the token is issued for this server only).
Type a user name, for example `alice-lab`, and **Allow**. You are back on Server connections:
"Connected to Lab notes", with scopes `notes:read` and an expiry marked "renewed automatically".

### 6. Call a tool as yourself

On the Tools page run `notes__whoami`, or from the shell with your session or API key:

```bash
curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H "X-API-Key: $SAJHA_KEY" \
  -H 'Content-Type: application/json' -d '{"tool": "notes__whoami", "arguments": {}}'
```

```text
... "you are alice-lab with scopes notes:read" ...
```

(An API key acts as its owner, so use a key you own.) `notes__add_note` declares no `readOnlyHint`, so the
shipped rule for proxied writes (`config/policies/20-proxied-writes.yaml`) holds it for approval first: the
answer names an approval id. Approve it on the **Approvals** page (`/admin/approvals`, as an administrator other
than the caller) and repeat the call; for the lab you may instead set `enabled: false` in that file. Then it
fails: the fake answers HTTP 403 `insufficient_scope`, and SAJHA passes that back with a hint to re-connect,
without marking your connection.

### 7. Allow changes

On the connect page tick **Also allow changes (notes:write)** and **Sign in again with Lab notes**. The
request now asks for `notes:read notes:write`; the page shows "changes allowed", and `notes__add_note`
answers "added for alice-lab". Signing in again without ticking it goes back to read only. In production,
keep write scopes paired with the approval rule for proxied writes
([Policy and Audit §5.1](../architecture/Policy%20and%20Audit.md#51-the-shipped-rule-for-proxied-writes)).

### 8. Refresh and "needs re-connect"

Each access token lasts a minute and SAJHA refreshes one that expires within
`accounts.refresh_skew_seconds` (default 120), so every call now refreshes first: **Admin > Audit** shows
`proxied_connection.refreshed` events (never a token). Now stop the fake (Ctrl+C) and start it again with
the same command: it forgets every token, as a vendor revoking them would. Your next call answers HTTP 428,
"Lab notes no longer accepts your linked account ... Reconnect", the audit shows
`proxied_connection.refresh_failed` (`invalid_grant`), and Server connections shows "Needs re-connect".
Sign in again (step 5) and calls work.

### 9. Disconnect

On the connect page click **Disconnect**. SAJHA revokes the token at the fake's revocation endpoint and
deletes it; the audit's `proxied_connection.disconnected` says `revoked_at_vendor: true`, and your next
call asks you to connect. Administrators see and revoke everyone's connections on **Server connections:
all users** (`/admin/server-connections`); disabling a user, on the console or in the users file, or
"Sign out everywhere" does the same.

## For a real vendor

- **Discovery and dynamic registration** (Atlassian Cloud, Notion, Linear, Sentry): the templates
  `13_atlassian_cloud_oauth.json.example` and `06_remote_oauth_sign_in.json.example`; nothing to register.
- **A client you register** (GitHub, Google): `14_github_oauth.json.example`,
  `15_google_workspace_oauth.json.example`, with `client_id` and `client_secret_ref: env:NAME`, and the
  callback `<accounts.public_url>/account/server-connections/oauth/callback` registered at the vendor.
- Set `accounts.public_url` to the address users reach, over https; leave `federation.allow_localhost`
  off. See [GitHub](../architecture/GitHub%20Integration.md),
  [Atlassian](../architecture/Atlassian%20Integration.md) and [Google](../architecture/Google%20Integration.md).

## What you learned

- `token_user` sends each user's saved personal token; `oauth_user` each user's OAuth access token, never
  anyone else's, never a shared credential
- SAJHA finds the authorization server from the server's 401 and metadata, registers itself where allowed,
  and signs users in with PKCE, a `state` bound to user and browser, and a resource indicator
- Read scopes by default; write scopes per user, on opt-in
- Tokens are refreshed before they expire and once after a 401; a refused refresh asks the user to sign
  in again; every revocation path revokes at the vendor

## Next

- How proxied servers work, and every `auth` key: [Federation](../architecture/Federation.md#per-user-oauth-sign-in-oauth_user)
- The security rules: [Security Model](../security/Security%20Model.md#per-user-tokens-for-proxied-servers)
- Next tutorial: [Tutorial 43: Connect and Configure LLM Providers](TUTORIAL_43_llm_providers.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
