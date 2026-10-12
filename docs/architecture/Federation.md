# SAJHA MCP Server — Federation: proxied MCP servers

A SAJHA server can embed other MCP servers and offer their tools, and optionally their prompts and
resources, as its own. Each embedded server is a **proxied MCP server** (in the code and the
`federation.*` keys, an **upstream**): SAJHA connects to it, lists what it offers, and proxies calls to
it. A proxied server's tool is a first-class registry tool: it is listed by `tools/list` on both
protocol eras, shown on the Tools page, offered to Ask SAJHA, usable in composites and over A2A, and
every call to it passes through the same access control, policy, audit, metrics, cache, circuit breaker
and rate limits as a tool SAJHA implements itself.

This document owns proxied MCP servers: how to define them (configuration, the mcpServers file, the
console), names, credentials, approval, calls, failure handling, security and limits. Every
`federation.*` key and its default is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#federation); the hands-on
walkthrough is [Tutorial 11](../tutorials/TUTORIAL_11_federate_an_mcp_server.md); the terms are in the
[Glossary](../../GLOSSARY.md).

Federation is **off by default** (`federation.enabled: false`) and no upstream is configured by default,
so a fresh SAJHA serves exactly what it served before.

**Internal or external.** Every proxied server is one or the other:

| | Internal (`external: false`) | External (`external: true`) |
|---|---|---|
| Tools named | `<prefix>__<tool>` on this server | `<prefix>__<tool>` on this server |
| In SAJHA Net | Stays local: never offered to other members | Offered into this server's nets as this server's own tools, under the vendor's prefix ([SAJHA Net](SAJHA%20Net.md#56-vendors-and-external-servers) §5.6) |
| Member of a net | Never | Never: no member record, certificate or gossip; this server is its proxy |
| Defined as | An upstream in `federation.upstreams` or on the console (the default there), or an mcpServers file entry with `"external": false` | An mcpServers file entry (the default there), or an upstream listed in `sajhanet.external_servers` with its vendor |

The console page is **Proxied MCP servers** (`/admin/federation`, under the admin menu); the mechanism
and its keys keep the name federation. To make a plain MCP server a **member** of a net instead (its own
instance name, governed by this server), sponsor it ([SAJHA Net](SAJHA%20Net.md#57-sponsored-servers)
§5.7).

---

## 1. Shape

```
 MCP clients, REST, A2A, Ask SAJHA, composites
                     │  tools/list · tools/call · prompts/* · resources/*
 SAJHA governance    access policy (sajha/auth/access.py) · usage + audit · cache ·
                     circuit breaker · rate limit · MRTR · progress · cancellation
                     │
 registry            ToolsRegistry: native tools  +  FederatedTool  (<prefix>__<tool>)
                     │                                 │ execute()
 federation          FederationManager (sajha/federation/manager.py)
                     │  one background event loop, one UpstreamConnection per upstream
                     │
 upstreams           Streamable HTTP (2026-07-28 or 2025-11-25) · legacy SSE · stdio
```

Federation needs the official MCP SDK (`mcp`, pinned in `requirements.txt`) at run time: every
upstream connection is an SDK `Client` (`sajha/federation/connection.py`).

| Code | What |
|---|---|
| `sajha/federation/config.py` | `FederationSettings`, `UpstreamConfig` (parse and validate), the name rules |
| `sajha/federation/security.py` | URL guards (SSRF; also SAJHA Net's peer guard), text sanitising, annotation correction, schema validation, secret references, redaction |
| `sajha/federation/names.py` | the provider-safe tool part of an imported name |
| `sajha/federation/auth.py` | credentials sent to an upstream: static header, OAuth client credentials |
| `sajha/federation/connection.py` | `UpstreamConnection`: the official `mcp` SDK v2 `Client` for one upstream |
| `sajha/federation/tool.py` | `FederatedTool`, the `BaseMCPTool` subclass registered in the registry |
| `sajha/federation/tasks.py` | upstream tasks: the tasks extension SAJHA declares to an upstream, and following a task to its end |
| `sajha/federation/relay.py` | a 2025-11-25 upstream's requests to the client (sampling, elicitation, roots), relayed to SAJHA's caller |
| `sajha/federation/store.py` | `FederationStore`: admin-managed upstreams and approvals, through the storage backend |
| `sajha/federation/manager.py` | `FederationManager`: discovery, approval, registration, routing, status |
| `sajha/routes/federation_routes.py` | the admin page (`/admin/federation`) and its JSON API (`/api/federation/...`) |
| `sajha/examples/federation/units_server.py` | a small upstream for trying it out (Tutorial 11) |
| `tests/test_federation.py`, `tests/test_federation_complete.py` | in-process upstreams on the official SDK server; every behaviour below |

## 2. The upstream model

An upstream is one MCP server, identified by an `id` (lower case letters, digits, `-`
and `_`, starting with a letter, at most 32 characters, no `__`). Upstreams come from three
places, merged:

* **Configuration**: `federation.upstreams[]` in `config/application.yml` (or the
  `SAJHA_FEDERATION_UPSTREAMS` environment variable, a JSON list). These are read-only on
  the console; change them in the file.
* **The mcpServers file**: `config/mcp_servers.json`, in the `mcpServers` JSON of Claude
  Desktop, Cursor and VS Code, re-read when it changes ([The mcpServers file](#the-mcpservers-file)).
  Its entries are external unless they say otherwise, and are not editable on the console.
* **The console**: upstreams added, edited or removed on `/admin/federation` are
  persisted by `FederationStore` as one JSON document at `federation.state_path`
  (default `config/federation/federation.json`), read and written through the storage
  backend, so it lives on local disk, S3, Azure Blob or GCS like the tool configurations.
  The same document holds the approval state of every discovered tool, prompt and
  resource. An id defined in configuration or the mcpServers file cannot be redefined from
  the page.

| Field | Default | Meaning |
|---|---|---|
| `id` | required | the upstream's identity, used in URLs, logs and the store |
| `title` | the id | a display name |
| `enabled` | `true` | connect and expose this upstream |
| `transport` | `streamable_http` | `streamable_http`, `sse` (the legacy 2024-11-05 transport) or `stdio` |
| `url` | required for HTTP | the upstream's MCP endpoint, for example `https://mcp.example.com/mcp` |
| `protocol` | `auto` | `auto` (probe `server/discover`, fall back to `initialize`), `legacy` (2025-11-25 handshake) or `2026-07-28` |
| `prefix` | the id | the namespace for this upstream's names (see section 4) |
| `auth` | none | credentials SAJHA presents to the upstream (section 3) |
| `headers` | `{}` | extra, non-secret request headers |
| `timeout_seconds` | `federation.default_timeout_seconds` | one call's deadline, end to end |
| `retries` | `1` | extra attempts after a transport failure, only for tools annotated `readOnlyHint` or `idempotentHint` |
| `max_calls_per_minute` | `0` (no limit) | SAJHA's own rate limit on calls to this upstream, across all callers |
| `cache_ttl` | `0` | seconds a successful result may be served from SAJHA's tool cache |
| `cache_per_user` | `cache.per_user_federated` (`true`) | keep a cached result per calling user, so one user's result is never served to another; `false` shares it |
| `breaker` | `{failure_threshold: 5, recovery_timeout: 60}` | the upstream's circuit breaker |
| `urls` | none | replicas: more endpoints serving this same upstream (HTTP only); calls go to a healthy one ([Gateway scale](#gateway-scale)) |
| `pool_size` | `federation.pool_size` (`1`) | shared connections to the upstream (to each replica) in each worker |
| `max_in_flight` | `federation.max_in_flight` (`0`, no limit) | calls in flight to this upstream in each worker; over it calls wait in the queue |
| `max_queue` | `federation.max_queue` (`64`) | calls that may wait for a slot; over it a call is refused at once |
| `refresh_interval_seconds` | `federation.refresh_interval_seconds` | periodic re-discovery |
| `include_tools`, `exclude_tools` | all, none | fnmatch patterns on the upstream's own tool names |
| `expose_prompts`, `expose_resources` | `false` | also federate prompts, and resources with their templates |
| `auto_approve` | `false` | trust this upstream: expose new tools without approval |
| `on_change` | `withdraw` | what serves while a changed definition waits for review: `withdraw` (nothing) or `hold` (the previously approved version; section 6) |
| `command`, `args`, `env`, `env_refs`, `cwd` | | stdio only: the process to launch |

### Transports

* **Streamable HTTP** is the default and speaks both protocol eras through the official
  `mcp` SDK v2 `Client`, the same client `clientsdk` wraps (`SajhaMCPClient`). With
  `protocol: auto` the SDK probes `server/discover` (2026-07-28) and falls back to the
  `initialize` handshake (2025-11-25), exactly as a standard client does.
* **Legacy SSE** (`transport: sse`) is the 2024-11-05 HTTP+SSE transport, for old
  servers; it always uses the handshake.
* **stdio** launches the upstream as a subprocess of SAJHA and talks over its stdin and
  stdout. It is **off unless `federation.allow_stdio: true`**, and only an administrator
  can configure it. The risk is plain: a stdio upstream is arbitrary code running as the
  SAJHA process user, with its file system and network access. Enable it only for
  commands you would run on that host yourself, pin the command to an absolute path, and
  pass secrets through `env_refs` rather than literal `env` values.

## 3. Credentials sent to an upstream

`auth.type` chooses what SAJHA presents. Secrets are never written in the configuration
or the store: every secret is a **reference** resolved by the intelligence layer's
`SecretStore` (`sajha/ai/llm/secrets.py`): `env:NAME`, `file:/path` or
`db:llm_providers/<type>`. The admin page accepts only references.

| `auth.type` | Fields | Sends |
|---|---|---|
| `none` (default), or `static` | | nothing beyond the upstream's `headers` (one shared identity) |
| `bearer` | `token_ref` | `Authorization: Bearer <token>` |
| `header` | `header`, `value_ref` | `<header>: <value>` (an API-key header such as `X-API-Key`) |
| `oauth_client_credentials` | `token_url`, `client_id`, `client_secret_ref`, `scope`, `audience`, `resource` | a bearer token from an OAuth 2.0 client-credentials grant, cached until shortly before it expires and fetched again on a 401 |
| `connected_account` | `provider`, `scopes`, `discovery` (one of the types above, for `tools/list`) | per-user token passthrough: each tool call carries the **calling user's** token for `provider` on a connection opened for that call; a caller without a link is asked to connect |
| `token_user` | `header` (default `Authorization`), `format` (default `Bearer {token}`), `label`, `help_url`, `token_prefix`, `token_pattern`, `test_call` (default true), `discovery` | each tool call carries the **calling user's own personal token** (one they saved on Server connections) as `<header>: <format>`; a caller without one is asked to connect ([Per-user credentials](#per-user-credentials-token_user)) |
| `service_with_user` | `service` (one of `none`, `bearer`, `header`, `oauth_client_credentials`, with its fields; or the shared credential in `headers`), `user_header` (default `X-SAJHA-User`), `user_format` (default `{user}`) | the **shared service identity** on every request, and on each tool call the **calling SAJHA user's id** in `user_header` for the vendor's audit record ([A shared identity naming the user](#a-shared-identity-naming-the-user-service_with_user)) |
| `oauth_user` | `scopes`, `write_scopes`, `vendor`, `client_id`, `client_secret_ref`, `token_auth_method`, `authorization_server`, `authorize_url`, `token_url`, `revoke_url`, `revoke_style`, `resource`, `resource_indicator` (default true), `authorize_params`, `help_url`, `discovery` | each tool call carries the **calling user's own OAuth access token** (`Authorization: Bearer`), obtained when they signed in at the vendor on Server connections; a caller who has not is asked to connect ([Per-user OAuth sign-in](#per-user-oauth-sign-in-oauth_user)) |

In YAML, the console and the mcpServers file alike, `auth: token_user` is short for
`auth: {type: token_user}` (and `auth: oauth_user` for `{type: oauth_user}`, `auth: service_with_user`
for `{type: service_with_user}`).

The token URL passes the same URL guard as the upstream URL (section 9). With
`connected_account` the upstream acts as the SAJHA user who made the call; `cache_ttl` and
`stdio` are refused for it. How links, refresh and "connect your account" work:
[Connected Accounts §7](Connected%20Accounts.md#7-federation-token-passthrough). Every other
type uses the upstream's own credentials for every caller, and SAJHA's access policy decides
who may make the call.

### Per-user credentials (token_user)

The **credential mode** says who the vendor sees: `static` (every type above except the per-user
ones and `service_with_user`: one shared identity), `token_user` (each user, with a personal token
they paste once), `oauth_user` (each user, after an OAuth sign-in at the vendor:
[below](#per-user-oauth-sign-in-oauth_user)) or `service_with_user` (one shared identity that names
the user on each call: [below](#a-shared-identity-naming-the-user-service_with_user)).
The design and what is built is [Per-User Sign-In for Proxied Servers](Per-User%20Sign-In%20for%20Proxied%20Servers.md).

```yaml
- id: github
  url: https://api.githubcopilot.com/mcp/
  auth:
    type: token_user
    header: Authorization
    format: "Bearer {token}"
    label: GitHub personal access token
    help_url: https://github.com/settings/personal-access-tokens
    token_pattern: "(ghp_|github_pat_)[A-Za-z0-9_]+"
```

* **Connecting.** Each user saves their token on **Server connections**
  (`/account/server-connections/<id>`). SAJHA checks `token_prefix` / `token_pattern`, makes a test
  call (`tools/list` with that token; `test_call: false` or the page's "save without testing" skips
  it), and stores the token in the connected-accounts vault under `upstream:<id>`, encrypted and bound
  to that user and upstream (`sajha/federation/user_tokens.py`).
* **At call time** the caller is resolved (signed-in user, the owner of an owned API key, or the local
  user a SAJHA Net caller maps to); that user's token is sent with that call only. No token: the call
  answers "connect your account" with a link to the connect page, in each transport's own form (the
  connected-accounts answers: an MRTR URL elicitation on 2026-07-28, `-32042` on 2025-11-25, HTTP 428 on
  REST, a Connect button in Ask SAJHA). An anonymous caller, or an API key without an owner, is refused.
  SAJHA never falls back to another user's token, the discovery credential or a static header (a
  `headers` entry with the token's header name is a configuration error).
* **Refused tokens.** A vendor 401 or 403 is passed back as the vendor's answer, the user's connection
  is marked "needs re-connect" (their next call asks them to connect again), nothing is retried as
  anyone else, and the upstream's circuit breaker does not count it.
* **Connections.** On a 2026-07-28 upstream the header rides on a connection opened for that call (no
  per-user state). On a session-based upstream (2025-11-25, legacy SSE) each user has **one session of
  their own**, opened on first use, closed after `federation.per_user_session_idle_seconds` (default
  900) without a call, at most `federation.per_user_sessions_max` (default 50) per upstream (the oldest
  idle one is closed to make room; when all are busy the call is refused). Replacing or removing a token
  closes that user's session.
* **Discovery.** `tools/list` runs with `auth.discovery` when given; otherwise with the token of the
  first user who connected (until then the upstream's state is `waiting_for_user`, offering nothing).
  Each user's test call adds what their token lists, so the catalog is the **union** of what users see;
  the vendor decides per call what each user may do.
* **Status and audit.** The upstream's status shows `auth_mode` and the number of open user sessions;
  the Proxied MCP servers page shows the identity mode and links to who is connected. Every connect,
  replace, disconnect and refusal is audited (`proxied_connection.*`), and every call's `tool.call`
  record names the identity used (`identity: {upstream, mode, user}`), never the token.

### Per-user OAuth sign-in (oauth_user)

For servers that sign each user in with OAuth (hosted MCP servers from Atlassian, Notion, Linear,
Sentry and others; GitHub and Google through a client you register). Everything said above for
`token_user` about the vault, call time, sessions, discovery, status and audit holds; what differs is
how the token is obtained and kept fresh (`sajha/federation/oauth_user.py`).

```yaml
- id: atlassian                                  # discovery and dynamic registration: nothing else to set
  url: https://mcp.atlassian.com/v1/mcp
  auth: {type: oauth_user, vendor: Atlassian}
- id: github                                     # an OAuth app your organisation registered
  url: https://api.githubcopilot.com/mcp/
  auth:
    type: oauth_user
    vendor: GitHub
    client_id: Iv1.0123456789abcdef
    client_secret_ref: env:GITHUB_OAUTH_CLIENT_SECRET
    authorize_url: https://github.com/login/oauth/authorize
    token_url: https://github.com/login/oauth/access_token
    scopes: [read:user, read:org]
    write_scopes: [repo]
```

* **Discovery.** SAJHA sends the upstream an unauthenticated request; its HTTP 401 names the
  protected-resource metadata (RFC 9728, the `resource_metadata` parameter of `WWW-Authenticate`; else
  the well-known URL `/.well-known/oauth-protected-resource[/path]`), which names the authorization
  server; that server's metadata (RFC 8414 `/.well-known/oauth-authorization-server`, or OpenID Connect
  discovery) gives the endpoints. `authorization_server` names the issuer when the server publishes no
  resource metadata; `authorize_url` and `token_url` (with `client_id`) skip discovery for vendors that
  publish none. The metadata must name the same issuer it was fetched for and advertise PKCE with
  `S256`; every discovered URL passes the URL guard of section 9 and must be https (plain http only on
  loopback with `federation.allow_localhost`). Results are reused for an hour.
* **The client.** With `client_id` (and `client_secret_ref`, a reference, for a confidential client)
  SAJHA uses the client the operator registered at the vendor. Without it SAJHA registers itself
  (dynamic client registration, RFC 7591) where the authorization server offers it, once per upstream;
  the registration is kept encrypted in the vault and redone when SAJHA's redirect URI changes. Neither
  possible: the connect page says that an administrator must register a client.
* **The redirect URI** is one route for every upstream: `/account/server-connections/oauth/callback` on
  `accounts.public_url` (set it, so the URI you register at a vendor never changes), else on the
  request's own origin. It is the only redirect URI SAJHA registers or sends, and the callback accepts
  only a `state` it issued.
* **Signing in.** "Connect with <vendor>" on the connect page starts an authorization-code flow with
  PKCE (`S256`) and a single-use `state` bound to the SAJHA user and the browser (the connected-accounts
  machinery: the state lives in the state store, so the callback can land on any worker). The
  authorization, token and refresh requests carry the **resource indicator** (RFC 8707, the upstream's
  URL, or the `resource` its metadata names) so the token is issued for this server only
  (`resource_indicator: false` for a vendor that rejects it). `scopes` are requested by default;
  `write_scopes` only when the user ticks "allow changes"; signing in again without ticking it asks for
  read scopes only. The granted scopes and expiry show on the user's and the administrators' views.
* **Refresh.** An access token due within `accounts.refresh_skew_seconds` is refreshed before the call;
  a vendor 401 refreshes it once and retries with the new token. A refused refresh marks the connection
  "needs re-connect" (the next call asks the user to sign in again). A vendor 403 (for example a scope
  the user did not grant) is passed back without marking the connection. Session-based upstreams open
  the user's session again with the refreshed token.
* **Revocation.** Disconnecting, an administrator's revoke, disabling or deleting the user (on the
  console or in the users file) and signing out everywhere revoke the token at the vendor when it
  advertises a revocation endpoint (RFC 7009; `revoke_style: github` or `google` for those vendors'
  own forms), then delete it; the token is deleted even when the vendor cannot be reached.

### A shared identity naming the user (service_with_user)

For vendors that let a service identity act on behalf of named users and record who asked:
every request carries the shared service credential, and each tool call adds a header naming
the SAJHA user who made it.

```yaml
- id: tickets
  url: https://tickets.example.com/mcp
  auth:
    type: service_with_user
    service: {type: bearer, token_ref: env:TICKETS_SERVICE_TOKEN}
    user_header: X-On-Behalf-Of        # default X-SAJHA-User
    user_format: "sajha:{user}"        # default {user}: the SAJHA user id
```

* **Discovery** (`tools/list`) uses the service identity alone, without a user header.
* **Calls.** On a 2026-07-28 upstream the call goes on a connection of its own carrying the
  service credential and the header (nothing kept per user); on a session-based upstream each user
  gets a session of their own, opened on first use and closed when idle, under the same cap as
  `token_user` (`federation.per_user_session_idle_seconds`, `federation.per_user_sessions_max`),
  because a session's headers are fixed when it opens.
* **The user's name.** `{user}` in `user_format` is the SAJHA user id; a value outside printable
  ASCII is percent-encoded, so no header can be injected. An anonymous caller is refused before
  anything is sent: the mode exists to say who asked.
* **Refusals.** A vendor 403 (it will not act for this user) is passed back to that caller as the
  vendor's answer and does not count against the upstream's circuit breaker; a 401 means the shared
  service credential was refused, and the error tells the caller an administrator must fix
  `auth.service`. Neither is retried without the header or as anyone else.
* **Rules.** `user_header` must be a plain header name, not `Authorization`, a cookie or an MCP
  protocol header, and must not also be in `headers` or be the service credential's header;
  `user_format` contains `{user}` and no other placeholder; `cache_ttl` and `stdio` are refused, as
  for the per-user modes. The tool-call audit names the mode (`service_with_user`) and the user.

The Federation page offers this mode with a bearer service token (and the header); a `header` or
`oauth_client_credentials` service credential is configured in YAML or the mcpServers file.

The vendor is trusted to honour the header: SAJHA names the user, the vendor decides what that user
may do. Choose `token_user` or `oauth_user` when each user's own permissions at the vendor must apply.

## 4. Namespacing

Every federated name is `<prefix>__<name>`: the upstream's prefix, two underscores, the
upstream's own name. `weather` upstream's `get_forecast` is exposed as
`weather__get_forecast`.

Two underscores rather than a dot: the MCP tool-name rules (2025-11-25) allow
`A-Z a-z 0-9 _ - .`, so both would be valid MCP, but the tool names an LLM provider accepts
(Anthropic, OpenAI and others: `^[a-zA-Z0-9_-]{1,64}$` or similar) exclude the dot, and
federated tools are offered to Ask SAJHA's models. `__` keeps one name valid everywhere,
and access patterns read naturally: an API key with allowlist `weather__*` may call every
tool of that upstream and nothing else.

The upstream's own name becomes the **tool part**: every character outside
`[A-Za-z0-9_-]` becomes `_`, the `.` that MCP allows included, so `v1.get_forecast` is
exposed as `weather__v1_get_forecast` and the name is valid for every LLM provider
(`sajha/federation/names.py::tool_part`, shared with SAJHA Net's qualified names). The
whole name is cut at 128 characters. The original name is kept for routing: the upstream
is always called with its own name. When two upstream names map to the same exposed name
(`a.b` and `a_b`), **neither** is exposed and both are reported as a conflict on the admin
page; a federated name equal to a native tool's name is not exposed either. Native tools
always win.

### Names

`__` in a tool name is **reserved for namespaced tools**: a federated upstream's tools and an
external server's tools (`<prefix>__<tool>`), a data connector's tools (`<connector prefix>__<operation>`)
and SAJHA Net's remote tools (`<net>__<instance>__<tool>`). No other tool may contain it: native and
configured tools, composites, generated (Describe) tools, workflows published as tools, LLM tools,
API-import tools and sandboxed tools. The tools registry enforces it in one place
(`sajha/tools/naming.py`, `ToolsRegistry.register_tool`): such a tool is refused with an error naming it
and the rule, an error notice `tools.reserved_name:<tool>`, and an entry in the registry's tool errors;
the server keeps starting. The creators (Studio, Describe, API import, workflows, the LLM tool builder)
check the same rule up front, so the message appears in the form.

A prefix is **unique on an instance**, across federation upstreams (wherever defined: `federation.upstreams`,
the mcpServers file, the console) and external servers, and is never a local tool's name. A clash is a
configuration error naming both sources (in the federation status, and the error notice
`federation.prefix_clash` for two upstreams, or the `sajhanet.external_servers` notice for an external
server); the second definition is not loaded and exposes no tools. The prefix defaults to the vendor, so
an internal and an external entry of the same vendor clash unless one is given its own `prefix`. The
notice clears when the clash is gone (for the mcpServers file, on the reload that removes it).

### Proxies all the way down

A proxied MCP server can itself proxy others: another SAJHA with its own proxied servers, or any MCP
gateway. The arrangement nests and expands without limit:

- **Names compose.** An upstream's tool that is itself prefixed comes through as
  `<outer prefix>__<inner prefix>__<tool>` (`corp__weather__get_forecast`), and in SAJHA Net as
  `<net>__<instance>__<outer>__<inner>__<tool>`; a qualified name still splits at its first two `__`.
- **Limits.** MCP caps a tool name at 128 characters: a federated name is cut there, and a SAJHA Net
  host refuses a tool whose qualified name would be longer rather than shortening it ([SAJHA
  Net](SAJHA%20Net.md) §5.6, give it a `rename`). Model providers with shorter caps get per-request
  aliases (SAJHA Net §8.6).
- **Cycles and depth.** A call to an upstream carries the chain depth it has reached in
  `params._meta["io.sajha/chain"].depth` (the depth carried in, the nesting of composites and LLM tools
  here, plus one for the hop). A SAJHA upstream runs the call with that depth (`MCPHandler` and the
  2026-07-28 handler, `sajha/core/inner_calls.py::proxied_entered`), so hops and nesting along a chain
  of proxies are one budget, `tools.max_call_depth` (default 8). When A proxies B and B proxies A (or a
  chain is simply too long), the call is refused at the limit with a clear error ("... would make the
  call chain N deep ...; proxied servers that proxy each other form a cycle") instead of recursing.
  Other MCP servers ignore the `_meta` entry; a cycle through one of them is bounded only by timeouts.
  Within SAJHA Net, forwarded calls have their own hop and chain budget (SAJHA Net §14).
- **Governance at every level.** Each proxy applies its own access control, policy, approvals, residency
  and audit to the calls it passes on; none trusts another's decision.

Prompts follow the same rule (`<prefix>__<prompt>`). Resource URIs are rewritten to
`sajha-federation://<upstream id>/<the original URI, percent-encoded>` so they cannot
collide with SAJHA's own `sajha://` resources, and `resources/read` routes them back.
Who may see a federated prompt or resource is SAJHA's own prompt and data-resource rule,
applied to the namespaced name or the rewritten URI (role `prompt` / `resource` permissions,
API-key `prompt:` / `resource:` entries, `mcp.anonymous.prompts` / `mcp.anonymous.resources`;
[Security Model](../security/Security%20Model.md#tool-access)).

Everything else an upstream offers around them is carried the same way:

* **Resource templates.** With `expose_resources`, the upstream's `resources/templates/list` is
  discovered too; each template is an approval item of kind `template` and is listed by SAJHA's
  `resources/templates/list` as `sajha-federation://<upstream id>/<template>`, its literal parts
  percent-encoded like a resource URI and its `{...}` expressions kept, so a client expands it as
  usual (`units://factor/{unit}` becomes `sajha-federation://units/units%3A%2F%2Ffactor%2F{unit}`).
  `resources/read` of an expansion goes to the upstream's own URI when it matches an approved
  template. The resource rule applies to the template as listed and to each URI read.
* **Completions.** `completion/complete` for a federated prompt (`ref/prompt`, the namespaced name)
  or template (`ref/resource`, the rewritten template) is answered by the upstream, after the
  caller's prompt or resource rule (a hidden item gets no values) and only for approved items of an
  upstream that offers `completions`. Values are screened like other upstream text.
* **Subscriptions.** A client that subscribes to a federated resource (2025-11-25:
  `resources/subscribe` on a Streamable HTTP session, delivered on the session's `GET /mcp` stream;
  2026-07-28: `resourceSubscriptions` on `subscriptions/listen`) makes SAJHA subscribe at the
  upstream while anyone holds it: `resources/subscribe` on a 2025-11-25 upstream, a
  `subscriptions/listen` stream with `resourceSubscriptions` on a 2026-07-28 one (reopened when the
  set changes). The upstream's `notifications/resources/updated` comes back to the subscribed
  clients under SAJHA's URI. Subscribing needs the resource rule, an approved resource or template
  expansion, and an upstream that offers subscriptions; otherwise the request is refused (2025-11-25)
  or the URI is left out of the acknowledged filter (2026-07-28). Unsubscribing, deleting the
  session or closing the stream releases it.
* **MCP Apps views.** An upstream tool's `_meta.ui.resourceUri` (`ui://...`) is rewritten to
  `ui://sajha-federation/<upstream id>/<the original URI, percent-encoded>` and listed on the
  2026-07-28 path like SAJHA's own views (`resources/list`, the tool's `_meta.ui`), when
  `mcp.apps.enabled`. Reading it fetches the view from the upstream, and only for a caller who may
  see a tool that uses it. SAJHA's view rules apply: only a `text/html;profile=mcp-app` document
  within SAJHA's view size limit is served, and the upstream's `_meta.ui.csp` domains and
  `permissions` are removed, so the host's sandbox gives the view no network access and no extra
  permissions ([MCP Apps and Headers Guide](../protocol/MCP%20Apps%20and%20Headers%20Guide.md)).
  A view is not a separate approval item: it is served while a tool that uses it is.

## 5. Discovery and refresh

When an upstream connects, SAJHA lists its tools (every page), and its prompts and
resources when they are exposed, then reconciles: new names are recorded, changed
definitions are compared, vanished names are unregistered. Discovery runs:

* **at start-up**, in the background; start-up waits at most
  `federation.startup_wait_seconds` so the first `tools/list` and the tool-search index
  already include reachable upstreams, and never fails because an upstream is down;
* **periodically**, every `refresh_interval_seconds`, which doubles as the health check;
* **on change**: on a 2026-07-28 upstream SAJHA holds a `subscriptions/listen` stream
  (tools, prompts and resources list changes); on a 2025-11-25 upstream it receives the
  `notifications/*/list_changed` notifications on the session. Either triggers a refresh;
* **on demand**, from the admin page (Refresh) or `POST /api/federation/upstreams/{id}/refresh`.

Each change that alters SAJHA's catalog publishes SAJHA's own list-changed notifications
(through the registry and the change bus), so SAJHA's clients see federated tools come and
go like any other, and re-syncs the tool-search index used by Ask SAJHA.

## 6. Approval

With `federation.require_approval: true` (the default) a newly discovered tool, prompt or
resource is **pending**: recorded and shown on the admin page, but not exposed until an
administrator approves it. Each item has one status:

| Status | Exposed | Meaning |
|---|---|---|
| `pending` | no | discovered, awaiting a decision |
| `approved` | yes | exposed through SAJHA |
| `changed` | no, or the approved version with `on_change: hold` | was approved, but the upstream changed its definition since; approve again |
| `rejected` | no | an administrator said no; stays hidden through refreshes |
| `disabled` | no | approved once, switched off for now |
| `invalid` | no | the tool's `inputSchema` or `outputSchema` is not a valid JSON Schema object schema; cannot be approved (the reason is shown) |

`changed` defends against an upstream that swaps a reviewed tool's description or schema
after approval (a "rug pull"): the definition's hash is stored with the approval, and any
difference sends the tool back for review. What serves meanwhile is the upstream's
`on_change`: with `withdraw` (the default) the tool leaves the catalog until it is approved
again; with `hold` the **previously approved version keeps serving** (its description,
schemas and annotations; the call still goes to the upstream's tool of that name) and the
admin page says so, until an administrator approves the change, or the upstream goes back
to the approved definition. A held version needs the approved definition, which SAJHA
stores with every approval; a tool approved before SAJHA stored it is withdrawn instead.
SAJHA Net's `review` trust level behaves the same for tools imported from other members
([SAJHA Net](SAJHA%20Net.md#73-approval-of-imported-tools) §7.3).

An upstream with `auto_approve: true`, or `federation.require_approval: false`, approves
new and changed items automatically, **except** items whose text tripped the injection
screen (section 9), which always wait for a person.

**Schema validation.** Each discovered tool's `inputSchema` (and `outputSchema`, when it has
one) must be a valid JSON Schema whose `type` is `object`: SAJHA checks it against the
2020-12 meta-schema (or the dialect its `$schema` names) before anything else. A tool that
fails is `invalid`, with the reason (for example `inputSchema is not a valid JSON Schema at
properties/a/type: 'strng' is not valid ...`) on the admin page and in
`GET /api/federation/upstreams/{id}` (`items[].reason`); approving it is refused. When the
upstream fixes the schema, the tool is treated as newly discovered. A held version
(`on_change: hold`) keeps serving while a changed definition is invalid. The same check
(`security.py::schema_problem`) is applied to SAJHA Net's imported catalogs.

## 7. Calls

A call to `weather__get_forecast` reaches `FederatedTool.execute_with_tracking`, the same
method every SAJHA tool runs, so before anything leaves SAJHA:

1. the caller's tool access was checked by the surface that received the call (MCP on
   both eras, REST, A2A, Ask SAJHA), by name, through `sajha/auth/access.py`;
2. the tool is enabled and the arguments satisfy its `inputSchema` (JSON Schema, checked locally before the upstream sees them);
3. the tool cache answers if `cache_ttl` is set and a fresh result exists (per calling user
   unless `cache_per_user: false`);
4. the upstream's circuit breaker is consulted (open: fail fast);
5. the upstream's rate limit is consulted.

Then the manager routes the call on the upstream's connection, under the upstream's
timeout, with the caller's W3C trace context in the request's `_meta.traceparent`
([Observability](Observability.md#33-outbound-trace-context)), so the upstream can continue the
trace. A transport failure (connection refused, reset, closed stream) reconnects and, for
a tool annotated `readOnlyHint` or `idempotentHint`, is retried up to `retries` times; a
tool that may have side effects is never retried. The outcome is recorded in the
breaker, the tool's metrics, the replay store and the caller surface's usage events,
exactly as for a native tool.

**Results pass through.** The upstream's `CallToolResult` (its `content` blocks and
`structuredContent`) is returned to an MCP caller unchanged; other surfaces (REST, A2A,
Ask SAJHA, composites) receive the same object as a JSON value. An upstream result with
`isError: true` is a tool failure in SAJHA too: MCP callers get `isError: true` with the
upstream's text, and the breaker counts it.

**Schemas pass through.** `inputSchema`, `outputSchema`, `icons` and `title` are the
upstream's, validated (section 6) and with descriptions screened (section 9).
**Annotations are corrected, never widened** (`security.py::correct_annotations`): only the
MCP hints (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) with
boolean values are kept, so anything else falls back to the cautious MCP default;
`destructiveHint` is dropped when the tool claims to be read-only; other keys are dropped;
and `openWorldHint` is always `true`, because the tool runs on another server. The title is
screened like any upstream text. SAJHA adds
`_meta["sajha/federation"] = {"upstream": <id>, "tool": <upstream name>}` to each listed
tool. Two parts of the upstream's tool are carried as well: its MCP Apps view (section 4) and its
task support (below); the rest of its `_meta` is not.

**Writes need approval.** The shipped policy `config/policies/20-proxied-writes.yaml` (enabled)
requires approval for every proxied server's tool that does not declare `readOnlyHint: true`
(an absent hint takes the MCP default, `false`): the person at the client confirms where the
client can (an MCP 2026-07-28 form, Ask SAJHA's Confirm button), otherwise an administrator approves
on the Approvals page ([Policy and Audit §5](Policy%20and%20Audit.md#5-approvals)). Annotations are
the vendor's hints: a tool that wrongly claims `readOnlyHint` is not caught. To switch the rule off,
set `enabled: false` in that file.

**Progress** reported by the upstream is forwarded to the SAJHA caller when the caller
asked for it (a 2026-07-28 `tools/call` with `_meta.progressToken` on a streamed
response).

**Cancellation** reaches the upstream, so it stops its work too. SAJHA's caller cancels a
call in its own era's way:

* **2026-07-28**: by closing the call's response stream, or `tasks/cancel` for a task;
* **2025-11-25**: with `notifications/cancelled` naming the request id. The call runs in a
  worker thread, so the notification sets a flag for that request instead
  (`sajha/core/mcp_cancellation.py`, keyed by the MCP session and request id; over stdio
  by the connection). With a shared state store the flag is relayed to whichever worker
  runs the call.

While SAJHA waits for the upstream it checks both; once cancelled it cancels the upstream
request, which the SDK sends on as `notifications/cancelled` to a 2025-11-25 upstream or as
a closed request stream to a 2026-07-28 upstream, and SAJHA's caller gets
`cancelled by the client`. Tools of SAJHA's own can check the same flag
(`mcp_tool_context.is_cancelled()`).

**Client input (MRTR, elicitation).** When a 2026-07-28 upstream answers with an
`InputRequiredResult`, SAJHA surfaces it to its own 2026-07-28 caller as SAJHA's
`InputRequiredResult`: the upstream's `inputRequests` are passed on unchanged and the
upstream's opaque `requestState` is carried inside SAJHA's signed `requestState`. When the
caller retries with `inputResponses`, SAJHA calls the upstream again with those responses
and the upstream's state. A caller that cannot provide the input (it did not declare the
capability, or it is on the 2025-11-25 era, REST, A2A or Ask SAJHA) gets a tool error
saying so.

**Requests from the upstream (sampling, elicitation, roots).** A 2025-11-25 upstream may send its
client `sampling/createMessage`, `elicitation/create` or `roots/list` during a call. SAJHA relays
them to its own caller when the caller can answer: a 2025-11-25 client on a Streamable HTTP session
that declared `sampling` or `elicitation`, calling with `Accept: text/event-stream`. The call then
runs on an upstream connection opened for it (with the upstream's shared credentials), so every
request the upstream sends on it belongs to this caller; each one goes to the caller on the call's
SSE stream and the caller's answer (a POST to `/mcp`) goes back to the upstream. A request whose
capability the caller did not declare (an elicitation mode included), and every such request from a
call that has no relay (2026-07-28 callers, REST, A2A, Ask SAJHA, a client that took no stream, a
per-user credential mode), is answered with an error that says so, which the upstream reports as it
sees fit.

**Tasks.** SAJHA's shared connection to a 2026-07-28 upstream declares the tasks extension
(`io.modelcontextprotocol/tasks`). When an upstream tool answers with a task, SAJHA polls
`tasks/get` at the upstream's `pollIntervalMs` until it ends, within the upstream's
`timeout_seconds`, and returns its result as the call's own; when SAJHA's call is cancelled (any of
the ways above), `tasks/cancel` goes to the upstream. A tool that declares
`execution.taskSupport` keeps it in SAJHA's `tools/list` (2026-07-28), so a client that declares the
extension can make the call a SAJHA task and poll and cancel it through SAJHA
([MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md)); the cancel reaches the upstream task.

## 8. Health, status and failure isolation

All upstream I/O runs on one background event loop owned by the manager, never on the
request loop, and every entry point catches its own failures. An upstream that is down,
slow or misbehaving never prevents SAJHA from starting, never blocks another upstream, and
never breaks `tools/list`:

* start-up waits a bounded time and continues;
* a failed connection is retried in the background with backoff (1 s doubling to 60 s);
* tools of an upstream that went away **stay listed** (the catalog does not churn) and
  their calls fail fast with a tool error naming the upstream; the circuit breaker opens
  after repeated failures;
* a slow call is bounded by `timeout_seconds`, and the caller's thread is released then.

The admin page and `GET /api/federation/upstreams` report, per upstream: state
(`disabled`, `connecting`, `connected`, `error`, or `needs_sign_in` for a server that wants
per-user OAuth, [below](#the-mcpservers-file)), the negotiated protocol version, the
server's name and version, the last error (redacted), the last refresh time, counts of
tools by status, calls and failures, and the circuit breaker. The breaker is also listed
by `GET /api/circuits` with SAJHA's other providers. With the fields of
[Gateway scale](#gateway-scale) they also report `pool`, `replicas`, `admission` (the limit, calls
in flight and waiting, calls shed) and `cluster`, every worker's published view.

### Gateway scale

Built in `sajha/federation/scale.py` for one SAJHA in front of many upstreams. With the defaults
(one connection, no limit, no replicas) a call takes the same path as before.

**Connection pools.** Each worker opens `pool_size` shared connections to an upstream (to each
replica). One of them, the **primary**, runs discovery, listens for list changes and carries
resource subscriptions; the others only carry `tools/call`. A call takes the connected connection
with the fewest calls in flight, then the lowest recent latency, then the next in turn. Prompts,
resource reads and completions use the primary. Per-user credential modes (section 3) open a
connection per call or per user as before and do not use the pool.

**Admission and load shedding.** `max_in_flight` bounds the calls in flight to one upstream in a
worker; when it is reached, up to `max_queue` calls wait in line, first come first served, for at
most `federation.queue_timeout_seconds`. A call over the bound (the queue is full, or there is no
queue, or the wait timed out) is refused at once with a tool error that says the upstream is at
capacity, that nothing was sent and to retry in a moment. A refused call is never sent, so it is safe
to retry whatever the tool does. It does not count as a call, a failure or against the breaker, and
it is counted in `sajha_federation_upstream_shed_total` ([Observability](Observability.md#22-the-metrics)).
The bound is per worker: with N workers an upstream sees at most N × `max_in_flight` calls.

**Replicas.** `urls` lists more endpoints of the same upstream (the same tools, behind one id and
one prefix); `url` is the first replica. Each replica gets its own pool. A call prefers a connected
connection on a replica that neither this worker nor a peer reports failing. When a connection is
found closed before the call is sent, the next connection takes the call, for any tool; after a
failure during the call, another replica is tried only for a tool that may be retried (`retries`,
read-only or idempotent tools). When the primary connection is down and another is connected, that
one becomes the primary (on another replica when there is one) at the next health tick, and
discovery and change listening continue there. Every replica URL passes the SSRF guard (section 9).

**Shared upstream health.** Every `federation.health.publish_seconds` each worker publishes its view
of each upstream to the state store, under `fed:health:<upstream>:<worker id>` with a TTL of
`federation.health.ttl_seconds`: the state, connected connections, calls, failures, average latency,
calls in flight, waiting and shed, the last error (redacted), each replica's connections, and the
breaker (state, when it changed, the last failure, and whether this worker opened it or followed a
peer). It then reads every live worker's view back. The admin page and status show that view as
`cluster` (workers reporting, workers connected, workers whose breaker is open), `/metrics` exports
it, and routing uses it: replica choice skips replicas peers report failing, and breakers follow
peers. A worker that stops publishing drops out of the view after the TTL. With the `memory` backend
the view is this worker's own ([Scaling and State](Scaling%20and%20State.md)).

**The breaker rule.** Each worker keeps its own breaker for an upstream. When a peer's published view
shows a breaker that the peer opened after its own failures, a worker whose breaker is closed opens its
own as of the peer's last failure (`federation.health.follow_peer_breakers`, on by default), so the
other workers stop sending calls to a failing upstream without each paying the failures first. From
then on each worker probes on its own: after its `recovery_timeout` it lets one call through (half
open) and closes on success, whatever the peer does. A breaker opened by following is published as
followed and is never followed in turn, and one peer's opening is followed once (a worker that has
recovered is not re-opened by the same news). News older than the recovery timeout is ignored. With
following off, a peer's open breaker is only shown.

## 9. Security

* **SSRF guard.** An upstream URL (and an OAuth token URL) must be `http` or `https`
  without credentials in it; its host must match `federation.allowed_hosts` when that list
  is set; and every address it resolves to must pass `address_allowed`, the guard the OAuth
  client-metadata fetch and webhook delivery use: public addresses only, unless
  `federation.allow_localhost` (loopback, for a localhost name) or
  `federation.allow_private_networks` (RFC 1918 and unique-local, never link-local, so
  never a cloud metadata address). The check runs when the upstream is saved and again
  before every connection attempt. Redirects are not followed.
  SAJHA Net peers have a guard of their own (`check_peer_url`): private addresses are
  allowed there only inside `sajhanet.allowed_networks`, independent of
  `federation.allow_private_networks`, and loopback and link-local never
  ([Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net)).
* **No secrets in logs.** Credentials are references; resolved values live only in the
  HTTP client's headers. Errors and statuses shown on the page or logged pass through
  `SecretStore.redact`, and a configuration is shown with its references, never their
  values.
* **Upstream text is untrusted.** Tool, prompt and resource names, titles and
  descriptions, and schema property descriptions, are what an LLM reads when it chooses a
  tool, so a hostile upstream can try to steer it from there ("tool poisoning"). Before
  anything is exposed SAJHA strips control characters, caps each description at
  `federation.max_description_chars`, and screens for injection markers (instructions to
  ignore earlier instructions, chat-template tokens, hidden `<IMPORTANT>`-style blocks,
  requests to read secrets or call other tools). A marker is replaced with `[removed]` and
  the item is flagged; flagged items always need an administrator's approval.
* **Approval before exposure** (section 6), on by default.
* **Who may call.** A federated tool is a registry tool, so the caller's role
  permissions, API-key allowlist, denylist or regex, and the anonymous policy apply to its
  namespaced name, on every surface.
* **Admin only.** Every federation route requires the admin role, and every change
  (add, edit, remove, approve, reject, enable, disable) is written to the audit log.

## 10. Configuration

The `federation.*` keys (the master switch, approval, the SSRF switches, intervals,
timeouts and the store path), with their defaults, are listed once, in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#federation). An
upstream in configuration takes the fields of section 2:

```yaml
federation:
  enabled: true
  upstreams:
    - id: weather
      url: https://mcp.example.com/mcp
      auth: {type: bearer, token_ref: env:WEATHER_MCP_TOKEN}
      include_tools: ["get_*"]
      max_calls_per_minute: 120
      cache_ttl: 300
```

The upstream list can also come from `SAJHA_FEDERATION_UPSTREAMS`, a JSON list.

### The mcpServers file

Upstreams can also be listed in the de-facto standard `mcpServers` JSON that Claude Desktop, Cursor and
VS Code use, so an administrator can paste a block they already have. The file is
`config/mcp_servers.json` (`federation.mcp_servers_file`), **git-ignored** because it may hold
credentials; `config/mcp_servers.json.example` and the templates in
[`config/mcp_servers/`](../../config/mcp_servers/README.md) (with the README's key table) are tracked.
The loader is `sajha/federation/mcp_servers.py`; `tests/test_federation_mcp_servers.py` parses every
template with it, so they cannot drift apart.

```json
{"mcpServers": {
  "github":   {"url": "https://api.githubcopilot.com/mcp/", "headers": {"Authorization": "Bearer ${GITHUB_PAT}"}},
  "context7": {"url": "https://mcp.context7.com/mcp"},
  "fetch":    {"command": "uvx", "args": ["mcp-server-fetch"], "vendor": "mcp_reference"},
  "pricing":  {"url": "http://pricing.internal.example:9000/mcp", "external": false}
}}
```

- **Each entry is an upstream** whose id is the entry's key. Standard keys: `url`, `headers`,
  `command`, `args`, `env`, and `type` (`http`, `sse` or `stdio`; without it a `command` means stdio and
  a `url` Streamable HTTP).
- **SAJHA keys**, all optional: `vendor` (default the entry's key), `prefix` (default the vendor; the
  tools are `<prefix>__<tool>`), `external` (default **true** in this file), `tools` (globs of the tools
  to take; nothing else is federated), `enabled` (`false`: listed, never connected), `cwd` (stdio),
  `title`, `timeout_seconds`, `auth` (the credential mode of section 3: `"static"`, the default,
  `{"type": "token_user", ...}` or `{"type": "oauth_user", ...}`, whose `client_id` may be `${NAME}`);
  `"disabled": true` means `"enabled": false`, and `description` is accepted
  and ignored. A key starting with `_` is a comment, at any depth; any other key is an error for that
  entry.
- **External by default.** An entry is an external server ([SAJHA Net](SAJHA%20Net.md) §5.6): this
  instance offers its tools into its nets as its own, published `<prefix>__<tool>`, and the server is
  never a member of a net. `"external": false` makes it an ordinary internal federation upstream, whose
  tools a SAJHA Net member offers into its nets under their federation names, like its own tools.
- **Secrets.** `${NAME}` and `${NAME:default}` in `url`, header values, `command`, `args`, `env` and
  `cwd` are read from the environment. A raw credential still works (the owner's intranet stance): each
  raw `Authorization`-like header is logged once by name (never its value) and listed in an info notice
  (`federation.mcp_servers.raw_secrets`).
- **Merging.** The file's upstreams join those of `federation.upstreams` and the console. An id defined
  in both `federation.upstreams` and the file uses the YAML definition, with a configuration error
  naming both sources; a console-added upstream with an id the file defines is ignored. Invalid entries
  are reported per entry (notice `federation.mcp_servers`) and the rest load.
- **Reload.** The file is checked every `federation.mcp_servers_reload_seconds` (default 5) by its
  modification time and size, never per call: new entries connect, removed ones are withdrawn, changed
  ones are replaced. A file entry is not editable on the console.
- **Servers that need each user to sign in.** Servers that accept personal tokens work per user with
  `"auth": {"type": "token_user"}` (templates `11_github_token_user.json.example` and
  `12_atlassian_datacenter_token_user.json.example`). Hosted servers such as Notion's, Linear's or
  Atlassian's MCP endpoints use per-user OAuth (MCP authorization with discovery and dynamic client
  registration): give them `"auth": "oauth_user"` ([above](#per-user-oauth-sign-in-oauth_user);
  templates `06_remote_oauth_sign_in.json.example`, `13_atlassian_cloud_oauth.json.example`,
  `14_github_oauth.json.example`, `15_google_workspace_oauth.json.example`). Such an upstream reached
  without a credential and without `oauth_user` answers HTTP 401; its state is then `needs_sign_in`
  ("needs sign-in") with a warning notice `federation.sign_in:<id>` that suggests `oauth_user`, and it is
  retried once a minute. A static bearer or API-key header and servers without auth work as before.

## 11. Using it

1. Turn it on: `federation.enabled: true` (and `allow_localhost: true` for an upstream
   on the same machine), then restart.
2. Add an upstream: in configuration, in the mcpServers file (copy a template from
   [`config/mcp_servers/`](../../config/mcp_servers/README.md)), or on **Proxied MCP servers**
   (`/admin/federation`): **Add upstream**, fill in the id and URL, choose the credentials,
   **Test connection**, **Save**.
3. Review what it offers: each discovered tool is listed with its description, schema and
   status. Approve the ones you want (or **Approve all**).
4. Approved tools appear in `tools/list`, on the Tools page and in Ask SAJHA's tool search
   within seconds. Grant them like any tool: roles, API-key patterns (`<prefix>__*`).
5. Watch it: the page shows the upstream's state, errors and call counts; refresh it, or
   disable a single tool, at any time.

The page's JSON API (list, add, edit, remove, refresh, approve and test, all admin only)
is in the [API Reference](../protocol/API%20Reference.md#416-federation-federation_routespy).

## 12. Limits

* Per-user credentials (`auth.type: connected_account`, and `token_user`, `oauth_user` or
  `service_with_user` on a 2026-07-28 upstream) cost one connection per call: a user's token is never put on the shared
  connection (section 3). Per-user sessions (on a session-based upstream) and discovered OAuth metadata
  are per process.
* A 2025-11-25 upstream's requests to the client are relayed only to a 2025-11-25 caller on a
  streamed call, and that call costs one upstream connection; 2026-07-28 callers get an error for
  them (2026-07-28 has no server-to-client requests; MRTR from a 2026-07-28 upstream is forwarded,
  section 7). A request the upstream sends outside any call (a `roots/list` after connecting) is
  refused.
* Upstream tasks are followed on 2026-07-28 upstreams over the shared connection only: a per-user
  credential mode, and a 2025-11-25 upstream, call such a tool without a task (a tool whose task
  support is `required` then fails). An upstream task that asks for client input is cancelled with an
  error. Polling stops at the upstream's `timeout_seconds`.
* Resource subscriptions: on 2025-11-25 they live with the session in the worker that took the
  request, and updates go out on that worker's `GET /mcp` stream of the session (several workers
  need sticky sessions for them); the WebSocket, legacy SSE and stdio transports accept
  `resources/subscribe` without sending updates. A session that expires without unsubscribing is
  released at the next discovery.
* Connections, the event loop, the circuit breaker, the admission bound and the queue are per
  process; each worker publishes its view of every upstream to the state store, follows peers' open
  breakers and reads the cluster-wide view ([Gateway scale](#gateway-scale)). The store (upstreams and
  approvals) is shared by every process that shares the storage backend, and `max_calls_per_minute`
  counts in the state store ([Scaling and State](Scaling%20and%20State.md)).
* `max_in_flight` is a bound per worker, not per cluster. Replicas must serve the same tools: discovery
  runs on the primary only, and a replica whose tools differ is not detected. Per-user credential modes
  go to the primary's replica (failing over when the primary moves) and do not use the pool.
* A 2025-11-25 `notifications/cancelled` is matched to its request through the MCP session
  id; a sessionless 2025-11-25 request cannot be cancelled that way.
* The SSRF guard checks addresses before each connection; a DNS answer that changes
  between that check and the connection itself is not caught. Pin hosts with
  `federation.allowed_hosts` for upstreams outside your control.
* `oauth_user` needs PKCE with `S256` and, without `authorize_url`/`token_url`, published metadata;
  a vendor offering neither dynamic registration nor an operator-registered client cannot be used.
  Server-to-client elicitation from the upstream during sign-in is not used: users sign in on the
  connect page.
* A cycle of proxies through an MCP server that is not SAJHA is bounded only by timeouts: other
  servers ignore the call-chain depth SAJHA sends ([Proxies all the way down](#proxies-all-the-way-down)).

## 13. Tests

`tests/test_federation.py` starts an upstream built on the official SDK server
(`MCPServer`) on a local port, in both protocol eras, and checks: discovery, namespacing
and name cleaning (`.` replaced, clashing names refused), schema pass-through, schema
validation (`invalid`), corrected annotations, call routing, upstream tool errors,
timeouts, progress, cancellation reaching the upstream from either era, the cache, the
circuit breaker, the rate limit, access control on namespaced names, approval gating
including re-approval after a definition change and held versions (`on_change: hold`), the
injection screen, refresh on a list change, MRTR pass-through, an upstream that is down
at start-up and one that goes down later, the SSRF guard, the store, the admin API, and
that federated tools appear in `tools/list` on both eras and in Ask SAJHA's shortlist.
`tests/test_federation_complete.py` adds an upstream with the MCP Apps extension and a small tasks
extension and checks, on both eras where they apply: resource templates (listed, expanded, read,
approval and the resource rule), completions for prompts and templates (and none when hidden),
subscriptions reaching the upstream and updates coming back (also end to end on a session's
`GET /mcp` stream), upstream tasks followed and cancelled upstream, views namespaced, listed, read
without CSP or permissions and hidden with their tool, and sampling, roots and elicitation relayed to
a caller that can answer (end to end over a session's SSE stream) or refused with a clear error.
`tests/test_proxied_per_user_tokens.py` covers `token_user` against a fake vendor that checks each
request's token: per-user answers, the connect answer on every front end, vendor refusals, per-user
sessions with idle eviction and the cap, the discovery union, secrecy (a canary token), revocation,
the SAJHA Net relay of the connect request, and that static upstreams are unchanged.
`tests/test_proxied_oauth_user.py` covers `oauth_user` against `deployment/local-lab/fake_oauth_mcp.py`
(a fake authorization server and an MCP server that checks its own tokens and the resource indicator):
discovery and dynamic registration, two users signing in, PKCE and `state` refusals, refresh before
expiry and after a 401, a refused refresh, an operator client, write scopes on opt-in, revocation at the
vendor on every path, secrecy, the SAJHA Net relay, a session-based upstream and the pages.
`tests/test_federation_scale.py` covers gateway scale: configuration rules, the admission queue (order,
the bound, the timeout), connection choice, pools spreading calls, load shedding (fast refusal, no
breaker count, the metric), replica failover and promotion of a new primary, and, with two managers
standing for two workers on the memory, fakeredis and SQLite state stores, the shared view, a followed
breaker probing on its own, the view expiring, and following switched off. `tools/bench/bench_federation.py`
measures proxied calls and shedding ([Scaling and State](Scaling%20and%20State.md#9-measured-performance)).
`tests/test_proxied_service_with_user.py` covers `service_with_user` against a fake vendor that accepts
only the service token and records the user header (configuration rules, discovery without the header,
per-request and per-session calls, refusals, the audit identity) and the shipped approval rule for
proxied writes.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
