# SAJHA MCP Server — Federation

Federation lets SAJHA front other MCP servers ("upstreams") and re-expose their tools, and
optionally their prompts and resources, as its own. A federated tool is a first-class
registry tool: it is listed by `tools/list` on both protocol eras, shown on the Tools page,
offered to Ask SAJHA, usable in composites and over A2A, and every call to it passes
through the same access control, audit, metrics, cache, circuit breaker and rate limits
as a tool that SAJHA implements itself.

This document owns the topic: the design, what was built, how to operate it, and its
limits. Every configuration key and its default is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#federation);
the hands-on walkthrough is
[Tutorial 11](../tutorials/TUTORIAL_11_federate_an_mcp_server.md); the terms are in the
[Glossary](../../GLOSSARY.md).

Federation is **off by default** (`federation.enabled: false`) and no upstream is
configured by default, so a fresh SAJHA serves exactly what it served before.

An upstream is a **proxied MCP server**: a server this instance embeds and proxies calls to. Each is
**internal** (its tools keep their names and are governed like local tools; SAJHA Net's one name, one
contract applies to them) or **external** (`external: true`: never a member of a net, its tools
published as `<prefix>__<tool>`; [SAJHA Net](SAJHA%20Net.md) §5.6). The console page is **Proxied MCP
servers** (`/admin/federation`, under the admin menu); the mechanism and its `federation.*` keys keep
the name federation.

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

| Code | What |
|---|---|
| `sajha/federation/config.py` | `FederationSettings`, `UpstreamConfig` (parse and validate), the name rules |
| `sajha/federation/security.py` | URL guards (SSRF; also SAJHA Net's peer guard), text sanitising, annotation correction, schema validation, secret references, redaction |
| `sajha/federation/names.py` | the provider-safe tool part of an imported name |
| `sajha/federation/auth.py` | credentials sent to an upstream: static header, OAuth client credentials |
| `sajha/federation/connection.py` | `UpstreamConnection`: the official `mcp` SDK v2 `Client` for one upstream |
| `sajha/federation/tool.py` | `FederatedTool`, the `BaseMCPTool` subclass registered in the registry |
| `sajha/federation/store.py` | `FederationStore`: admin-managed upstreams and approvals, through the storage backend |
| `sajha/federation/manager.py` | `FederationManager`: discovery, approval, registration, routing, status |
| `sajha/routes/federation_routes.py` | the admin page (`/admin/federation`) and its JSON API (`/api/federation/...`) |
| `sajha/examples/federation/units_server.py` | a small upstream for trying it out (Tutorial 11) |
| `tests/test_federation.py` | an in-process upstream on the official SDK server; every behaviour below |

## 2. The upstream model

An upstream is one MCP server, identified by an `id` (lower case letters, digits, `-`
and `_`, starting with a letter, at most 32 characters, no `__`). Upstreams come from two
places, merged at start-up:

* **Configuration**: `federation.upstreams[]` in `config/application.yml` (or the
  `SAJHA_FEDERATION_UPSTREAMS` environment variable, a JSON list). These are read-only in
  the admin page; change them in the file.
* **The admin page**: upstreams added, edited or removed on `/admin/federation` are
  persisted by `FederationStore` as one JSON document at `federation.state_path`
  (default `config/federation/federation.json`), read and written through the storage
  backend, so it lives on local disk, S3, Azure Blob or GCS like the tool configurations.
  The same document holds the approval state of every discovered tool, prompt and
  resource. An id defined in configuration cannot be redefined from the page.

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
| `refresh_interval_seconds` | `federation.refresh_interval_seconds` | periodic re-discovery |
| `include_tools`, `exclude_tools` | all, none | fnmatch patterns on the upstream's own tool names |
| `expose_prompts`, `expose_resources` | `false` | also federate prompts and resources |
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
| `none` (default) | | nothing |
| `bearer` | `token_ref` | `Authorization: Bearer <token>` |
| `header` | `header`, `value_ref` | `<header>: <value>` (an API-key header such as `X-API-Key`) |
| `oauth_client_credentials` | `token_url`, `client_id`, `client_secret_ref`, `scope`, `audience`, `resource` | a bearer token from an OAuth 2.0 client-credentials grant, cached until shortly before it expires and fetched again on a 401 |
| `connected_account` | `provider`, `scopes`, `discovery` (one of the types above, for `tools/list`) | per-user token passthrough: each tool call carries the **calling user's** token for `provider` on a connection opened for that call; a caller without a link is asked to connect |

The token URL passes the same URL guard as the upstream URL (section 9). With
`connected_account` the upstream acts as the SAJHA user who made the call; `cache_ttl` and
`stdio` are refused for it. How links, refresh and "connect your account" work:
[Connected Accounts §7](Connected%20Accounts.md#7-federation-token-passthrough). Every other
type uses the upstream's own credentials for every caller, and SAJHA's access policy decides
who may make the call.

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
configuration error naming both sources (in the federation status and the `federation.mcp_servers` or
`sajhanet.external_servers` notice); the second definition is not loaded.

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
The [SAJHA Net](SAJHA%20Net.md#73-approval-of-imported-tools) design gives its `review` trust
level the same behaviour.

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
(`security.py::schema_problem`) is meant for SAJHA Net's imported catalogs.

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
tool. The upstream's own `_meta` (MCP Apps views, for instance) and its task support are
not carried over.

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
saying so. A 2025-11-25 upstream that sends a server-to-client `elicitation/create` during
a call is declined: SAJHA's client is not on that connection to answer it.

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
(`disabled`, `connecting`, `connected`, `error`), the negotiated protocol version, the
server's name and version, the last error (redacted), the last refresh time, counts of
tools by status, calls and failures, and the circuit breaker. The breaker is also listed
by `GET /api/circuits` with SAJHA's other providers.

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
  `title`, `timeout_seconds`. A key starting with `_` is a comment, at any depth; any other key is an
  error for that entry.
- **External by default.** An entry is an external server ([SAJHA Net](SAJHA%20Net.md) §5.6): this
  instance offers its tools into its nets as its own, published `<prefix>__<tool>`, and the server is
  never a member of a net. `"external": false` makes it an ordinary internal federation upstream.
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
- **Servers that need each user to sign in.** Hosted servers such as Notion's or Supabase's MCP
  endpoints use per-user OAuth (MCP authorization with discovery and dynamic client registration),
  which federation does not do for upstreams yet. Such an upstream, reached without a credential,
  answers HTTP 401; its state is then `needs_sign_in` ("needs sign-in (not supported yet)") with a
  warning notice `federation.sign_in:<id>`, and it is retried slowly. Keep it `"enabled": false` until
  this is built ([Roadmap](Roadmap.md)). A static bearer or API-key header (a GitHub token) and servers
  without auth work.

## 11. Using it

1. Turn it on: `federation.enabled: true` (and `allow_localhost: true` for an upstream
   on the same machine), then restart.
2. Add an upstream: in configuration, or on **Admin → Federation** (`/admin/federation`):
   **Add upstream**, fill in the id and URL, choose the credentials, **Test connection**,
   **Save**.
3. Review what it offers: each discovered tool is listed with its description, schema and
   status. Approve the ones you want (or **Approve all**).
4. Approved tools appear in `tools/list`, on the Tools page and in Ask SAJHA's tool search
   within seconds. Grant them like any tool: roles, API-key patterns (`<prefix>__*`).
5. Watch it: the page shows the upstream's state, errors and call counts; refresh it, or
   disable a single tool, at any time.

The page's JSON API (list, add, edit, remove, refresh, approve and test, all admin only)
is in the [API Reference](../protocol/API%20Reference.md#416-federation-federation_routespy).

## 12. Limits

* Per-user credentials (`auth.type: connected_account`) cost one MCP handshake per call: a
  user's token is never put on the shared connection (section 3).
* Server-to-client requests from a 2025-11-25 upstream (elicitation, sampling, roots) are
  declined; client input reaches upstreams only through 2026-07-28 MRTR (section 7).
* Resource templates, completions, `resources/subscribe` and upstream tasks are not
  federated; an upstream's MCP Apps views (`ui://`) are not carried over.
* Federated prompts and resources have no per-caller policy, like SAJHA's own: every
  caller who can list prompts sees the approved ones.
* Connection state, the event loop and the circuit breaker are per process; the store
  (upstreams and approvals) is shared by every process that shares the storage backend,
  and `max_calls_per_minute` counts in the state store
  ([Scaling and State](Scaling%20and%20State.md)).
* A 2025-11-25 `notifications/cancelled` is matched to its request through the MCP session
  id; a sessionless 2025-11-25 request cannot be cancelled that way.
* The SSRF guard checks addresses before each connection; a DNS answer that changes
  between that check and the connection itself is not caught. Pin hosts with
  `federation.allowed_hosts` for upstreams outside your control.

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
