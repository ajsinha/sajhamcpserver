# Connected Accounts

A user links their own account at a third-party service (GitHub, Slack, Google Workspace,
Microsoft 365, Atlassian, Notion, or any OAuth 2.0 service an administrator describes)
once. SAJHA keeps the tokens encrypted, renews them, and tools that need the service call
it **as that user**, with that user's permissions there. Federated upstream MCP servers can
receive the user's token the same way (*token passthrough*).

This guide owns the topic: design, configuration of providers, the user flow, the token
vault, tool binding, how each client is asked to connect, federation passthrough, scaling
and security. Configuration keys are listed in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#accounts);
the example tools in the
[Connected Account Tools Reference Guide](../tools/enterprise/Connected%20Account%20Tools%20Reference%20Guide.md);
a walkthrough with a GitHub OAuth app in
[Tutorial 18](../tutorials/TUTORIAL_18_connect_your_accounts.md).

Code: `sajha/accounts/` (providers, vault, service, injection, respond, tools),
`sajha/routes/accounts_routes.py`, the pages `templates/account/connections.html` and
`templates/admin/connections.html`.

---

## 1. The pieces

```
 browser ──POST /account/connections/{p}/connect (CSRF)──► service.start ── state, PKCE, redirect URI ──► state store
    │                                                              │
    └──302──► provider authorize page ──user approves──► GET /account/connections/{p}/callback
                                                                   │
                         service.complete: pop state (single use), same user, same browser,
                         POST token endpoint (code + verifier + exact redirect URI) ──► token vault (AES-256-GCM)

 tool call (MCP either era, REST, Ask SAJHA, composites)
    └─ BaseMCPTool.execute_with_tracking ─ injection.bind(tool) ─ service.resolve(caller, provider, scopes)
            ├─ link ok ─ refresh if it expires within the skew ─ token bound to this call ─ tool calls the API
            └─ no usable link ─ ConnectedAccountRequired ─ each front end asks the user to connect (§6)
```

| Part | Module | Job |
|---|---|---|
| Provider registry | `sajha/accounts/providers.py` | Built-in templates plus `accounts.providers.*`; which hosts a token may go to |
| Token vault | `sajha/accounts/vault.py` | The `connected_accounts` table; tokens encrypted, metadata in clear |
| Service | `sajha/accounts/service.py` | Authorization-code flow with PKCE, refresh, revocation, audit |
| Injection | `sajha/accounts/injection.py` | Binds the caller's token to one tool call |
| Responders | `sajha/accounts/respond.py` | "Connect your account" for MCP 2026-07-28, 2025-11-25 and REST |
| Tools | `sajha/accounts/tools/` | `ConnectedAccountTool` and the example GitHub, Slack, Google, Microsoft tools |

## 2. Providers

A provider is configuration. SAJHA ships templates (`TEMPLATES` in
`sajha/accounts/providers.py`) for `github`, `slack`, `google`, `microsoft`, `atlassian`
and `notion`: authorize, token, revocation and user-info endpoints, default scopes,
whether PKCE is supported, the scope parameter and separator, scope implications (GitHub
`repo` implies `public_repo`), extra authorize parameters (Google's `access_type=offline`,
Atlassian's `audience`) and `api_hosts`, the only hosts a token for that provider is ever
sent to.

A template becomes usable when it has a **client id** (an OAuth app the administrator
registered with the service) and, for confidential clients, a **client-secret
reference**:

```yaml
accounts:
  providers:
    github:
      client_id: ${GITHUB_OAUTH_CLIENT_ID:}
      client_secret_ref: env:GITHUB_OAUTH_CLIENT_SECRET
    microsoft:
      client_id: ${MS_CLIENT_ID:}
      client_secret_ref: env:MS_CLIENT_SECRET
      tenant: contoso.onmicrosoft.com     # replaces {tenant} in the endpoints (default common)
```

* Any template field can be overridden there; an id that is not a template is a custom
  provider and gives every endpoint itself (`authorize_url`, `token_url`, `api_hosts`, and
  optionally `revoke_url` with `revoke_style: rfc7009`, `userinfo_url`, `login_field`).
  A Salesforce org, for example: `template` empty, its `/services/oauth2/authorize` and
  `/services/oauth2/token` URLs, `api_hosts: ["*.my.salesforce.com"]`.
* Each field can also come from `SAJHA_ACCOUNTS_PROVIDERS_<ID>_<FIELD>` (for example
  `SAJHA_ACCOUNTS_PROVIDERS_GITHUB_CLIENT_ID`); `SAJHA_ACCOUNTS_PROVIDERS` (a JSON object)
  replaces the YAML block.
* Secrets are references only: `client_secret_ref: env:NAME`, `file:/path` or
  `db:llm_providers/<type>`, resolved when a token request is made. An inline
  `client_secret` is refused, as is an `http://` endpoint (except loopback, for tests) and a
  provider without `api_hosts`. A public client (no secret) must use PKCE.
* Invalid definitions are skipped with a warning and shown on `/admin/connections`.
* The redirect URI registered with the service is
  `<public origin>/account/connections/<id>/callback`, where the origin is
  `accounts.public_url`, else `mcp.auth.public_url`, else the request's host (development
  only: set one of the two in production). `redirect_uri` on the provider pins it.

PKCE (S256) is used wherever the template says the service supports it (GitHub, Google,
Microsoft); Slack, Atlassian and Notion templates use the client secret alone. Slack
issues user tokens through `user_scope` and returns them under `authed_user`; the
template says so (`scope_param`, `token_response_path`).

## 3. Linking an account (users)

`/account/connections` (user menu → Connected accounts) lists each configured service:
linked or not, the account at the service, the access granted, when it was linked and last
used, and whether the token renews itself. **Connect** sends the browser to the service;
after approval the service redirects back and the card shows **Linked**. **Disconnect**
revokes the token at the service where it offers revocation and deletes it.

When a tool asks for access the link does not grant (a scope), the connect link carries
`?connect=<id>&scope=...`: the page highlights that service, and connecting again asks for
the extra scope while keeping the ones already granted (incremental consent).

Connected accounts belong to signed-in users. API keys and anonymous callers have none;
tools that need one tell them so (§6).

### The flow, step by step

1. `POST /account/connections/{provider}/connect` (form with the page's CSRF token).
   The service creates a random `state`, a PKCE `code_verifier` (S256 challenge), fixes the
   exact `redirect_uri`, and stores `{user, provider, verifier, redirect_uri, scopes,
   hash(browser nonce), return_to}` in the state store under `accounts:flow:<state>` for
   `accounts.flow_ttl_seconds`. The browser nonce is set as the HttpOnly cookie
   `sajha_acct_flow` (path `/account/connections`, SameSite=Lax).
2. The browser goes to the provider's authorize URL with `client_id`, `redirect_uri`,
   `state`, scopes and the challenge.
3. `GET /account/connections/{provider}/callback?state=...&code=...`: the state is popped
   (single use, on any worker), and must have been issued to the same SAJHA user, for the
   same provider, in the same browser (the nonce cookie). Anything else is refused and
   audited as `connected_account_state_rejected`. An `error` from the provider (the user
   declined) is shown and audited.
4. The code is exchanged at the token endpoint with the same `redirect_uri` and the
   `code_verifier`. Tokens go to the vault; the account name comes from the provider's
   user-info endpoint. Audit: `connected_account_linked` (account, scopes, refreshable).

## 4. The token vault

Table `connected_accounts` (in the schema files under `db/scripts/sqlite/` and
`db/scripts/postgresql/`; SQLite creates it, on PostgreSQL the operator creates it from
the schema file and SAJHA only checks it is there): one row per (user, provider).

| Column | In clear? | |
|---|---|---|
| `token_ciphertext` | no | AES-256-GCM over `{access_token, refresh_token, token_type}`; associated data `user|provider`, so a ciphertext copied to another row does not decrypt |
| `key_id` | yes | which vault key encrypted the row |
| `account_login`, `account_id`, `scopes`, `expires_at`, `has_refresh_token`, `status`, `last_error`, timestamps | yes | what the pages show |

**The key.** `accounts.vault.key` (env `SAJHA_ACCOUNTS_VAULT_KEY`): 32 bytes as base64url,
or a passphrase stretched with HKDF-SHA256. Empty: a key is generated once into the server
secrets file (`<data.dir>/secrets/server_secrets.json`, mode 0600), which every worker on
the same data directory reads. Several hosts must share `SAJHA_ACCOUNTS_VAULT_KEY`.

**Rotation.** Put the new key in `accounts.vault.key` and the old one in
`accounts.vault.previous_keys`. Rows still decrypt (each records its `key_id`) and are
re-encrypted with the current key when used; `/admin/connections` shows rows per key and
re-encrypts all of them on request (audit `connected_account_vault_rotated`). Remove the old
key once no row uses it. Losing the key loses the links (users reconnect); nothing else.

**KMS hook.** `accounts.vault.key_provider: package.module:factory` returns an object
with `current() -> (key_id, 32 bytes)` and `lookup(key_id) -> bytes | None`, for example
one that unwraps a data key with AWS KMS or Vault Transit at start-up.

**Status.** `active`, or `reauth_required` after the provider refused a refresh or
rejected the token twice; the user reconnects (a new dance replaces the row).

## 5. Tools that act as the user

A tool declares the account it uses in its configuration:

```json
"auth": {"connected_account": "github", "scopes": ["repo"]}
```

On every run `BaseMCPTool.execute_with_tracking` calls `sajha.accounts.injection.bind`:
for a tool without that block it does nothing; otherwise it validates the arguments, finds
the **caller** (the context variable set by MCP on both eras, the REST execute endpoint
and Ask SAJHA: `sajha/observability/caller.py`), and asks the service for that user's
token with those scopes. The token is bound to the call through a context variable
(`current_token()`): it is never in the arguments, the result, the replay store or a log.

`service.resolve` refuses (with `ConnectedAccountRequired`) when the caller is not a
signed-in user, has no link, the link needs reconnecting, or lacks a scope; it refreshes
first when the access token expires within `accounts.refresh_skew_seconds`.

`ConnectedAccountTool` (`sajha/accounts/tools/base.py`) is the base for tools written
against one provider. Its `api()` method sends the request only to the provider's
`api_hosts` over https, adds the provider's API headers, retries once after a refresh on
HTTP 401 (Slack: `ok: false` with `invalid_auth` and similar), and marks the link
`reauth_required` when the second attempt is refused too. Such a tool is listed only
while its provider is configured. Per-user results are never cached: `cache_ttl` is
ignored for any tool with `auth.connected_account`.

The shipped tools are `github_list_my_repos`, `github_create_issue`,
`slack_post_message`, `google_drive_search`, `ms365_list_my_events`, and
`connected_http_request`, an administrator binding of a provider's API (base URL,
allowed methods, path patterns) that the model may call with a path and query. Write tools
carry `destructiveHint`, so Ask SAJHA and `mcp.confirm_destructive_tools` confirm them.

Any other tool may declare `auth.connected_account` and read the token with
`sajha.accounts.current_token()`.

## 6. "Connect your account", per client

`ConnectedAccountRequired` subclasses MRTR's `InputRequired`: the circuit breaker, the
replay store and federation treat it as "input needed", never as a tool failure. Each front
end answers it:

| Caller | Client can open URLs | Answer |
|---|---|---|
| MCP 2026-07-28 | `capabilities.elicitation.url` | `InputRequiredResult` with `elicitation/create`, `mode: "url"`, key `sajha.connect.<provider>`, pointing at the connect page. The client opens it, the user links, the client retries with `inputResponses`; the retry runs the tool. A retry that still finds no link answers with a tool error rather than asking again. |
| MCP 2025-11-25 | `capabilities.elicitation.url` | JSON-RPC error `-32042` (URLElicitationRequiredError) with `data.elicitations: [{mode: "url", elicitationId, url, message}]`; the client shows it and calls the tool again. |
| MCP, either era | no URL elicitation | `CallToolResult` with `isError: true`, the connect URL in the text, details in `_meta["sajha/connected_account"]` |
| REST `POST /api/tools/execute` | | HTTP 428 with `error_code: connected_account_required`, `provider`, `reason`, `scopes`, `connect_url` |
| Ask SAJHA | | a `needs_connection` event; the page shows **Connect &lt;service&gt;** (opens the connect page) and **ask again**; the ask stops with `stopped_by: needs_connection` |

`reason` is `not_connected`, `insufficient_scope` (with the missing `scopes`),
`reauth_required` or `sign_in_required` (an API key or anonymous caller: no URL is offered).
SAJHA does not send `notifications/elicitation/complete`; the client's retry is the signal.

## 7. Federation: token passthrough

An upstream MCP server that authenticates its users with the same service (a GitHub MCP
server that takes a GitHub token, say) can receive each caller's own token:

```yaml
federation:
  upstreams:
    - id: ghmcp
      url: https://mcp.example.com/mcp
      auth:
        type: connected_account
        provider: github
        scopes: [repo]
        discovery: {type: bearer, token_ref: env:GHMCP_SERVICE_TOKEN}   # optional
```

* Discovery (`tools/list`, refresh, list-change listening) runs on the shared connection
  with `auth.discovery` (`none`, `bearer`, `header` or `oauth_client_credentials`) or no
  credential.
* Each tool call resolves the **caller's** token as in §5 and opens a connection for that
  call carrying `Authorization: Bearer <user token>`, closed afterwards: no user's token is
  on the shared connection or reused for another user. An HTTP 401 from the upstream
  refreshes once, then asks the user to reconnect.
* A caller without a link gets the answers of §6 (the namespaced tool raises
  `ConnectedAccountRequired` like a native one).
* `cache_ttl` is refused for such an upstream (results are per user); `stdio` is refused
  (a token per call needs HTTP).
* The cost is one MCP handshake per call. The design of federation is in
  [Federation](Federation.md).

## 8. Several workers

* Flow state (`accounts:flow:*`) is in the state store, so the callback may land on any
  worker; with several workers set `state.backend: redis` or `database`
  ([Scaling and State](Scaling%20and%20State.md)).
* Refresh takes a lock in the state store (`accounts:refresh:<user>:<provider>`, 30 s), so
  one worker refreshes and the others wait and read the result: providers that rotate
  refresh tokens (Google, Microsoft, Slack with rotation) never see the same refresh token
  twice.
* Tokens live in the database: every worker reads the same rows. The vault key must be
  the same on every worker (the shared secrets file, or `SAJHA_ACCOUNTS_VAULT_KEY`).

## 9. Administration

`/admin/connections` (Admin → Connected accounts) lists every link: user, service,
account, scopes, status, expiry, last use. It never shows a token. Administrators can
unlink a user's account (offboarding; audited with `by_admin`), filter by user or service,
see which vault keys rows use and re-encrypt them, and see which providers are configured
or invalid. `GET /api/admin/accounts/connections` returns the same metadata as JSON;
`GET /api/accounts/connections` and `DELETE /api/accounts/connections/{provider}` are the
user's own.

## 10. Security

| Threat | Control |
|---|---|
| Forged or replayed callback (login CSRF: linking the attacker's account to the victim) | `state` random, single use, TTL, bound to the SAJHA user and to the browser that started the flow (nonce cookie) |
| Code interception | PKCE S256 where supported; the token request repeats the exact `redirect_uri` |
| Open redirect after linking | `return_to` must be a local path |
| Cross-site Connect / Disconnect | POST forms with a CSRF token bound to the session cookie; the JSON `DELETE` needs `X-CSRF-Token` with a cookie session |
| Token theft from the database or a backup | AES-256-GCM with a key outside the database; associated data binds each ciphertext to its user and provider |
| A token sent to the wrong host (SSRF, a model choosing a URL) | every API request checked against the provider's `api_hosts`, https only; `connected_http_request` limits methods and path patterns and rejects `..`, `//` and schemes |
| One user's token used for another | resolved per call from the caller context; never cached; federation opens a connection per call |
| Tokens in logs or audit | never logged; audit details carry account names, scopes and outcomes only; admin views show metadata only |
| Stale access after offboarding | admin unlink revokes at the provider where possible and deletes the row; refused refreshes mark links `reauth_required` |

Audit events (`audit_log`, `resource_type = connected_account`):
`connected_account_linked`, `connected_account_link_failed`,
`connected_account_state_rejected`, `connected_account_refreshed`,
`connected_account_refresh_failed`, `connected_account_disconnected`,
`connected_account_vault_rotated`.

Limits: GitHub OAuth-app tokens do not expire and have no refresh token; Microsoft has no
token revocation endpoint (disconnect deletes the token; revoke sessions in Entra ID if
needed); Atlassian tools need the user's cloud id (Atlassian's accessible-resources endpoint on
`api.atlassian.com`), which a `connected_http_request` binding can reach.
