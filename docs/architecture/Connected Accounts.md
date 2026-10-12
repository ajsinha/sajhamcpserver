# Connected Accounts

A user links their own account at a third-party service (GitHub, Slack, Google Workspace,
Microsoft 365, Atlassian, Notion, or any OAuth 2.0 service an administrator describes)
once. SAJHA keeps the tokens encrypted, renews them, and tools that need the service call
it **as that user**, with that user's permissions there. Federated upstream MCP servers can
receive the user's token the same way (*token passthrough*).

This guide owns the topic: design, configuration of providers, the user flow, the token
vault, tool binding, how each client is asked to connect, federation passthrough, scaling,
security, and provider packs (§11). Configuration keys are listed in the
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
* A provider pack (§11) installs a **preset**: the provider's fields stored in
  `config/accounts/provider_presets/<id>.json` through the storage backend. A field resolves from
  the environment variable, then the YAML, then the preset, then the template, so a preset never
  overrides what an operator configured.
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

Document search reads through connected accounts too: `ai.rag.accounts.sources` (Drive,
OneDrive, SharePoint, GitHub, Confluence) are listed and read with each user's own token and
indexed per user, searched with `sajha_search_my_docs`
([Intelligence Layer](Intelligence%20Layer.md#documents-from-connected-accounts)).

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

### Proxied-server connections (personal tokens and OAuth sign-in)

Proxied MCP servers that act as each user have their own credential modes
([Federation §3](Federation.md#per-user-credentials-token_user)): `token_user` for a **personal token**
(a GitHub personal access token, a Jira or Confluence Data Center token) and `oauth_user` for an
**OAuth sign-in at the vendor** ([Per-user OAuth sign-in](Federation.md#per-user-oauth-sign-in-oauth_user)).
`oauth_user` runs on this page's machinery: the same authorization-code flow (state in the state store
bound to the user and the browser, PKCE `S256`, exact redirect URI), refresh (a lock per user and
upstream, `accounts.refresh_skew_seconds`, a refused refresh marks the link for re-connect) and
revocation, with three differences: the endpoints come from the server's OAuth metadata rather than
`accounts.providers`, the client is registered dynamically when the operator configured none, and the
callback is one route for every upstream (`/account/server-connections/oauth/callback`). Both kinds of
token live in this same vault,
one row per user and upstream under the provider key `upstream:<id>` (encrypted and bound to both like
every row, re-encrypted by the same rotation), and use the same "connect your account" answers (§6),
pointing at the connect page `/account/server-connections/<id>` instead of `/account/connections`.
They have their own pages, **Server connections** (`/account/server-connections`, in the user menu)
and **Server connections: all users** (`/admin/server-connections`), and are left out of the
connected-accounts pages and APIs. A connection's status is connected, needs re-connect (the vendor
refused it, or a refresh was refused) or not connected; of a personal token only `••••` and its last
four characters are ever shown, of an OAuth sign-in its granted scopes and expiry. A dynamically
registered client of an upstream is kept in the vault too (row `#client`), never listed as a user's. Design and status:
[Per-User Sign-In for Proxied Servers](Per-User%20Sign-In%20for%20Proxied%20Servers.md).

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

## 11. Provider packs

A **provider pack** brings a service that users ask for in one reviewed step: a connected-account
**preset** (the provider: OAuth endpoints, scopes, the hosts a token may go to) and an
[API Import](API%20Import.md) of the service's OpenAPI spec whose tools act as the calling user
(`auth.type: connected_account`, §5). The spec is bundled with the pack and never fetched when it
is installed. Code: `sajha/packs/` (format, review, install), `sajha/accounts/presets.py` (the
stored presets), `sajha/routes/packs_routes.py` (the admin API).

### The format

A pack is a folder: `pack.json`, the spec file and the licence the spec is published under.

| `pack.json` field | Meaning |
|---|---|
| `format`, `id`, `title`, `version`, `description` | `format` is `1`; `id` (a lower-case letter, then letters, digits, `-` or `_`) equals the folder name |
| `provider` | The preset: any provider field of §2 (`template`, endpoints, `scopes`, `api_hosts`, ...) except `client_id`, `client_secret_ref`, `redirect_uri` and `enabled`, which belong to the administrator. `id` is the provider users link (default: the pack id) |
| `install_fields` | What the administrator supplies on install: `client_id`, `client_secret_ref`, `tenant`, `redirect_uri` (default the first two) |
| `api` | `spec` (a file in the folder) and its `spec_sha256`; `prefix` (the API Import prefix and tool-name prefix), `base_url`, `folder` (the tool folder), `security_scheme` (the spec's scheme bound to the account; empty: the binding is added to every operation), `scopes` (what each tool asks of the user's link), `operations` (the reviewed selection, as API Import operation keys `METHOD /path`) |
| `source` | `url`, `file`, `revision`, `retrieved`, `licence` (one of MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, CC0-1.0, CC-BY-4.0), `licence_file`, and `changes` (how the bundled copy differs from the upstream one) |

A pack is refused when the spec does not match `spec_sha256`, the licence is not one of those, a
file name leaves the folder, the provider sets a field that belongs to the administrator, or an
operation key is malformed. Packs are read from `sajha/packs/bundled/`, then from the folders in
`packs.dirs` ([Configuration Reference](../getting-started/Configuration%20Reference.md#packs)).

### The bundled packs

Each bundled spec is an excerpt: the pack's operations and the components they reference, with
examples, `externalDocs` and `x-` extensions removed, and its `info.description` replaced by a
notice naming the source, the revision and the licence. The live list, with each pack's operations
and install state, is `python -m sajha.packs list` or `GET /api/admin/packs`.

| Pack | Provider | Spec source | Licence | Notes |
|---|---|---|---|---|
| `github` | the `github` template | [github/rest-api-description](https://github.com/github/rest-api-description) `descriptions/api.github.com/api.github.com.json` | MIT | The spec declares no security scheme, so the account binding applies to every operation |
| `slack` | the `slack` template, with history and user scopes added | [slackapi/slack-api-specs](https://github.com/slackapi/slack-api-specs) `web-api/slack_web_openapi_v2.json` (Swagger 2.0) | MIT | The `token` parameter is removed from every operation (the user token goes in `Authorization: Bearer`); upstream has not been updated since 2021 |
| `box` | a custom provider (Box's OAuth 2.0 endpoints, `api.box.com` and `upload.box.com`) | [box/box-openapi](https://github.com/box/box-openapi) `openapi.json` | Apache-2.0 | The modified file carries the notice the licence asks for; the licence is in the pack folder |

### Review and install

Installing is the review-and-approve gate of Describe a tool
([Tool Generation §6](Tool%20Generation.md#6-deploy)) without a stored draft:

1. **Plan.** `POST /api/admin/packs/{id}/plan` with the install inputs (`client_id`,
   `client_secret_ref` as `env:NAME`, `file:/path` or `db:...`; a literal secret is refused) answers
   with everything an install would do: the provider as the registry would build it (checked by its
   own rules), the redirect URI to register with the service, every operation as API Import plans it
   (tool name, annotations, conflicts, new or changed), the policy preview, errors and warnings,
   and the review **hash** of all of it. The plan is an error when the provider has no client id,
   when the API's base URL is not https on one of the provider's `api_hosts` (a user's token would
   go elsewhere; API Import refuses that too, API Import §4), when an operation is missing, unsupported or its name is taken, or when the prefix
   belongs to an import that is not this pack.
2. **Install.** `POST /api/admin/packs/{id}/install` with the same inputs, `hash` and
   `approve: true`. It is refused unless the plan made again has no errors and the same hash
   (nothing changed since the review: the pack, its spec, the inputs, the names, the tools it
   would replace), and the [policy engine](Policy%20and%20Audit.md) allows the pseudo tool call
   `studio.deploy` with `{"tool": "pack:<id>", "kind": "pack"}`; `require_approval` creates an
   approval request that another administrator decides on the Approvals page, and installing again
   consumes the grant. Then the preset is saved and API Import's own deploy writes and hot-loads
   the tools. A deploy refused before any tool is written restores the previous preset; when some
   tools do not load, the answer names them and the install is reported as failed (the tools that
   loaded stay, as with any API Import deploy, and installing again retries).
3. **Users link** the provider on `/account/connections` as for any provider; the pack's tools
   then call the service as each caller, and a caller without a link is asked to connect (§6).

Installing again (a new pack version, other inputs) is a new review: the plan shows the
operations as changed or unchanged and has a new hash. `POST /api/admin/packs/{id}/uninstall`
removes the pack's import (its tools) and the preset it created; users' links stay in the vault
until they or an administrator unlink them (§9). Every install, failed install and uninstall is
audited (`config_change`, `packs.install`, `packs.install_failed`, `packs.uninstall`). Install
records are `config/packs/<id>.json` in the storage backend.

The admin API needs the admin role; a cookie session sends the page's CSRF token in
`X-CSRF-Token`. The same steps from a shell, against the working directory's configuration and
storage (a running server notices the new tool configs and the preset):

```
python -m sajha.packs list
python -m sajha.packs show box
python -m sajha.packs plan box --client-id <id> --client-secret-ref env:BOX_CLIENT_SECRET
python -m sajha.packs install box --client-id <id> --client-secret-ref env:BOX_CLIENT_SECRET --hash <hash> --approve
python -m sajha.packs uninstall box
```

A `require_approval` policy rule needs a shared state store (`state.backend: redis` or `database`)
for an approval asked from the command line to reach the Approvals page.

### Presets on several workers

The provider registry records which preset files (and their modification times) it was built
from; on use it lists them again at most every 10 seconds per process and reloads when they
changed, so a pack installed on one worker is linkable on every worker on the same storage within
seconds. The tool registry picks up the new tool configs the same way.

### Limits

* There is no console page for packs yet: the admin API and `python -m sajha.packs` are the installer.
* A pack ships the operations its author reviewed; another operation of the same service is an API
  Import with `auth.type: connected_account` (API Import §4), made in Studio.
* The provider's `api_headers` (GitHub's `Accept` and API version) are not sent by imported tools.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
