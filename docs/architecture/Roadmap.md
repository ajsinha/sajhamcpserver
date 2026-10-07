# SAJHA Roadmap

This document owns one topic: **what is not built yet, and what should come next**. It
has two kinds of item. *Unfinished work* is a gap that the code or a guide already
records: a feature that is stored but not enforced, a limit a guide lists, a release step
not taken. *Enhancements* are recommendations for making SAJHA the MCP server teams choose,
grounded in where the comparison (`/comparison`, data in `sajha/web/competitive.py`) says
others are stronger.

Each item is one line here. The detail of a feature's limits stays in the guide that owns
the feature, and every row links to it. When the two disagree, the owning guide is right
and this roadmap is the one to fix.

---

## 1. How to read this

**Horizons.** *Now* is what release 7.0.0 needs before it is cut. *Next* is the work that
closes the gaps an operator meets first (access control, sign-in, the intelligence layer,
evidence of performance). *Later* is larger work that changes what kind of product SAJHA
is (gateway scale, container isolation, SaaS breadth, hosting).

**IDs.** `N` (now), `X` (next) and `L` (later), so a "Depends on" cell can name an item.

**Size.**

| Size | Meaning |
|---|---|
| S | One module and its tests, plus an edit to the owning guide |
| M | A subsystem: code, tests, a guide section, usually a tutorial |
| L | Cross-cutting or a new subsystem: needs a design written down first |

**Decision** marks an item whose direction is the owner's call, not an engineering
judgement. They are collected in [section 5](#5-decisions-needed).

---

## 2. Now: release 7.0.0 hygiene

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| N1 | **Decision:** cut release 7.0.0 | Everything since 6.0.0 ships unversioned; operators cannot pin it, and the deck and `/about` report the old version | `app.version` in `config/application.yml` is still the 6.0.0 value; the [CHANGELOG](../../CHANGELOG.md) section is "Unreleased (planned 7.0.0)"; the newest tag is `v6.0.0` | Set `app.version`, give the CHANGELOG heading its version and date, rebuild the deck ([deck guide](../../tools/deck/GUIDE.md)), tag `v7.0.0` on `main` after merging `develop` | S | N2, N3 |
| N2 | A 6.0.0 SQLite database stops at start-up with no statement to run | The one manual step of the upgrade is in the CHANGELOG only; the start-up message says "add them by hand" without saying how | `users.must_change_password` is new on an existing table; `sajha/db/schema.py` (`not_ready_message`) names the missing column for SQLite but prints no SQL; the CHANGELOG has the one-liner | **Decided: a start-up message, not a migration.** On SQLite only, print the exact `ALTER TABLE ... ADD COLUMN ...` line for each missing column, taken from the column's definition in `db/scripts/sqlite/schema.sql`. Print it; never run it. PostgreSQL keeps pointing at the CHANGELOG SQL ([Database Setup](../getting-started/Database%20Setup.md#4-upgrades)) | S | none |
| N3 | Run the test suite in CI | The suite runs only on developers' machines; CI proves conformance and nothing else | The only workflow is `.github/workflows/mcp-conformance.yml` (the conformance suite against a live server) | A second workflow: `python -m pytest -q -p no:randomly tests clientsdk/tests` on the dev requirements, with a PostgreSQL service and `SAJHA_TEST_POSTGRES_URL` set so `tests/test_db_schema.py` applies the real PostgreSQL file | S | none |
| N4 | One rate limiter, not two | Dead limiters read as protection that is not there | `check_user_rate_limit` and `check_key_rate_limit` in `sajha/security.py` are defined and never called; tool calls are limited only by a policy `rate_limit` rule, and the shipped `config/policies/00-default.yaml` has none ([Security Model](../security/Security%20Model.md#rate-limiting-and-lockout)) | Delete the unused limiters; ship a commented `rate_limit` rule (per `user` and `api_key`) in the default policy so the one mechanism is visible, and say so in the Security Model | S | none |
| N5 | Remove the demo credential files | Plaintext demo passwords and keys in a tracked file get copied into real deployments | `config/users.json` and `config/apikeys.json` are not imported (identities live in the database), yet `sajha/core/hot_reload_manager.py` still watches them with callbacks that do nothing ([Security Model](../security/Security%20Model.md#8-known-limitations), "Hygiene") | Delete both files and the two watches; remove the Hygiene bullet | S | none |

---

## 3. Next

### 3.1 Unfinished work

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| X1 | **Decision:** tenancy, enforced or removed | A tenant record that limits nothing looks like isolation to an administrator who creates one | `sajha/core/tenancy.py` stores tool patterns, blocked tools and quotas; `has_tool_access` and `check_quota` are never called; `/api/tenants` serves the records ([Security Model](../security/Security%20Model.md#8-known-limitations); GLOSSARY "Tenant") | Either enforce: resolve a tenant from the user or API key, check its patterns in the one access path (`sajha/auth/access.py`), count its quotas in the state store like policy quotas, and label usage by tenant. Or remove the records, the routes and the table, and state that roles, API-key tool access and policy rules are the model | L (enforce) or S (remove) | none |
| X2 | Studio permissions per creator, and ownership | A developer who should only wrap REST endpoints can also run code tools and delete anyone's tools | One `studio` permission (`STUDIO_PERMISSION` in `sajha/auth/__init__.py`) opens every creator; `POST /admin/studio/delete` in `sajha/routes/studio_routes.py` checks that a tool came from Studio, not who made it ([Security Model](../security/Security%20Model.md#8-known-limitations)) | A permission per creator in the existing role permissions (`has_permission(resource_type, resource_name, action)`), with `studio` kept as "all"; record the deploying user on each generated tool; delete only your own unless admin | M | none |
| X3 | Per-user access to prompts and data resources | An API key limited to a few tools can still read every prompt and data file | Only anonymous callers are filtered (`mcp.anonymous.prompts`, `mcp.anonymous.resources`); federated prompts and resources likewise ([Security Model](../security/Security%20Model.md#8-known-limitations), [Federation](Federation.md#12-limits)) | Extend the tool allow and deny patterns of `sajha/auth/access.py` to prompts and resources, so `prompts/list`, `resources/list` and reads use one policy | M | none |
| X4 | Revocable sign-in | A stolen JWT stays valid until it expires; changing a password does not end other sessions | Logout clears the cookie only; OAuth access tokens are not revocable before `exp` ([Security Model](../security/Security%20Model.md#8-known-limitations), [MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md#8-known-limits)) | A per-user token generation (a claim checked against the user row or the state store), bumped on password change, admin reset and "sign out everywhere"; a schema change in both schema files with the CHANGELOG SQL | M | none |
| X5 | Single sign-on for the console | Enterprises expect their identity provider for people, not only for MCP clients | No login path uses an external identity provider; the `oauth_provider` and `oauth_subject` columns and `get_by_oauth` in `sajha/db/dao/__init__.py` are unused ([Security Model](../security/Security%20Model.md#8-known-limitations)) | OpenID Connect sign-in against the issuer already configured for `/mcp`, with a claim-to-role mapping and just-in-time user creation | M | X4 |
| X6 | Browser and transport hardening | Each is a standard reviewer finding | CSP allows `'unsafe-inline'` (`sajha/security.py`); the WebSocket transport does not check `Origin` (`sajha/routes/ws_routes.py`); the size limit relies on `Content-Length` ([Security Model](../security/Security%20Model.md#8-known-limitations)) | Per-request CSP nonces in the templates; the `/mcp` Origin allow-list applied to the socket upgrade; a streaming byte cap for chunked bodies | M | none |
| X7 | Ask SAJHA over MCP, finished | `sajha_ask` is the one tool most clients will call; today it is the least capable path | Destructive-tool confirmation comes back as `needs_confirmation`, not as an MRTR round trip; no conversation memory over MCP (`sajha/ai/ask_tool.py` runs as a fixed `mcp:sajha_ask` identity); no history trimming on `ContextTooLong`; no page for past conversations although `/api/ai/conversations` exists ([Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | Confirmation as MRTR on 2026-07-28; run as the authenticated caller so memory and tool access are theirs; trim oldest turns before falling back to a larger model; a conversations page on the existing API | M | none |
| X8 | Documents as RAG sources | Answers grounded in SharePoint, Drive or Confluence are what most people ask an assistant for | A source is a folder of text files in the storage backend, or an upload; only the text types in `sajha/ai/rag/chunking.py` are read ([Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | PDF and Word extraction behind optional packages; sources that read through connected accounts, so a user's index respects their own access; incremental re-index | M | none |
| X9 | LLM providers: native async, Vertex AI, Entra ID | Thread-pool wrappers limit concurrency under load; Google Cloud and Azure shops need their own sign-in | `agenerate` in `sajha/ai/llm/model.py` wraps the sync call in a thread; `sajha/ai/llm/providers/gemini.py` says Vertex is not wired; Azure takes a bearer token as the key ([Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | Native async clients on the HTTP providers; Vertex AI for Gemini and Claude with workload identity; Entra ID token acquisition and refresh | M | none |
| X10 | Weaviate and Chroma connectors | Two common vector stores reachable today only by federating their own MCP servers | Not built ([Data Connectors](Data%20Connectors.md#14-limits-of-this-design)); the `VectorAdapter` interface in `sajha/connectors/vector.py` is small | One adapter each, with the same allowlist, filters and masking as Qdrant | S | none |
| X11 | Push-based reload | Polling delays a change on cloud storage by up to the interval, and costs list calls | `hot_reload.interval_seconds` polls; workflow file triggers poll too ([Storage Guide](../getting-started/Storage%20Guide.md#planned-not-yet-built), [Workflows](Workflows.md#9-limits)) | Bucket event notifications (S3 to SQS or EventBridge, Azure Event Grid, GCS Pub/Sub) feeding the change bus; polling stays as the fallback | M | none |
| X12 | Protocol gaps | Each is a client a strict reviewer can name | `notifications/tasks` is not emitted; legacy streamable-HTTP sessions get no `list_changed`; external issuers must issue JWTs (no RFC 7662 introspection); no CORS on the OAuth endpoints for browser clients ([MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md#8-known-limits), [MCP 2025-11-25 Compliance](../protocol/MCP%202025-11-25%20Compliance.md#7-not-implemented-on-this-path)) | Take them in that order; each lands with conformance evidence in its compliance report | M | none |

### 3.2 Enhancements

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| X13 | A benchmark suite with published numbers | A buyer comparing servers asks "how fast, on what hardware"; SAJHA has no answer | Nothing measures throughput or latency; the deck states that it "claims no performance it has not measured" ([deck guide](../../tools/deck/GUIDE.md)) | A repeatable load harness against `/mcp` in both eras, calling mock tools, at one and several workers on each `state.backend`; publish p50, p99 and throughput with the hardware in [Scaling and State](Scaling%20and%20State.md), and let the deck read them at build time | M | N3 |
| X14 | SLOs and failure tests | The failure behaviour is written down but not exercised | [Scaling and State](Scaling%20and%20State.md#7-failure-behaviour-and-limits) describes Redis loss, slow databases and dying workers; [Observability](Observability.md) ships alert rules | State SLOs on the existing metrics; failure tests that stop Redis, kill a worker mid-task and break an upstream, asserting the documented behaviour | M | X13 |
| X15 | Console end-to-end and accessibility checks | The console is large and has no flow tests; accessibility is unchecked | `scripts/check_mobile.py` drives Playwright over the console for layout, and `tests/test_mobile_layout.py` skips it without a server | Playwright flows for sign-in, Studio deploy, approvals and Ask SAJHA; an automated accessibility scan (axe-core) over the same route list; both in CI against a scratch server | M | N3 |
| X16 | **Decision:** a TypeScript client SDK | Most agent front ends are TypeScript | The client SDK (`clientsdk`) is Python only; any standard MCP client already works against `/mcp` ([Client SDK Guide](../clients/Client%20SDK%20Guide.md)). The owner has deferred this | A thin package on the official TypeScript MCP SDK, mirroring `SajhaMCPClient`, plus the REST and A2A helpers | M | none |
| X17 | An upgrade helper for schema changes | N2 fixes one column; the next schema change needs the same answer | `python -m sajha.db check` names what is missing; `python -m sajha.db sql` prints the full files ([Database Setup](../getting-started/Database%20Setup.md#6-the-helper)) | `python -m sajha.db sql --missing`: print the `CREATE TABLE` and `ALTER TABLE ... ADD COLUMN` statements for what `check` reports, for either dialect, for an operator to review and run. It never executes anything on PostgreSQL | S | N2 |

---

## 4. Later

### 4.1 Unfinished work

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L1 | Storage, finished | Cloud deployments still need a shared file system in places | DuckDB reads a local directory only; Studio modules need a shared file system; plugins and some other subsystems use direct file IO; no storage-backend tests in CI; no Azure or GCP deployment guide ([Storage Guide](../getting-started/Storage%20Guide.md#planned-not-yet-built)) | The Storage Guide's planned list, in its order; backend tests on emulators in CI | M | N3 |
| L2 | Federation, complete | Federated servers lose features they have | Resource templates, completions, `resources/subscribe`, upstream tasks and `ui://` views are not carried; 2025-11-25 upstreams' requests to the client are declined ([Federation](Federation.md#12-limits)) | Carry each feature through with the same namespacing and policy | M | none |
| L3 | Workflow engine limits | Long or fan-out workflows hit them first | A `foreach` body is one call; change-bus event triggers fire only on the producing worker; missed cron slots are coalesced ([Workflows](Workflows.md#9-limits)) | Sub-graph bodies; relay trigger events through the state store; an opt-in replay of missed slots | M | none |
| L4 | API Import coverage | Real-world specs use what is not imported | No multipart or binary bodies, callbacks or GraphQL subscriptions; pagination is a hint, not followed; remote `$ref` in Swagger 2.0 not converted ([API Import](API%20Import.md#8-limits)) | Multipart first (it blocks uploads), then opt-in pagination following with a page cap | M | none |
| L5 | Tool quality reach | Tests that run live are flaky; lexical evals miss meaning | Cassettes cover `urllib.request`, `requests` and `httpx` only; eval answer checks are lexical ([Tool Quality](Tool%20Quality.md#10-limits)) | Cassettes for other HTTP clients and SDK transports; an optional model-graded check beside the lexical ones | M | none |
| L6 | Sandbox depth | Host-name allowlisting is library-level; a container per call is slow | No egress proxy; no warm pool; no WASM backend ([Sandbox](Sandbox.md#9-limits-and-future-work)) | An egress proxy that enforces the allowlist on the wire; a warm container pool with state reset; WASM for pure-Python tools | M | none |
| L7 | Provider tool gaps | Each limits a common task | SharePoint uploads stop at Graph's simple-upload size and only the client-credentials grant is implemented (`sajha/tools/impl/sharepoint_tool.py`; [SharePoint Tool Reference Guide](../tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md#known-issues)); the web crawler runs no JavaScript and parses HTML only ([Web Crawler Tool Reference Guide](../tools/search/Web%20Crawler%20Tool%20Reference%20Guide.md#limitations)). The other provider guides' limitations are the upstream APIs' own | Upload sessions and certificate credentials for SharePoint; PDF text for the crawler | S | none |
| L8 | Per-tenant figures | Chargeback needs usage by tenant | Metrics and the usage ledger have no tenant dimension ([Observability](Observability.md#6-as-built-decisions-and-limits)) | A tenant label on usage and cost once tenants are enforced | S | X1 |

### 4.2 Enhancements

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L9 | A container per federated stdio server | Docker's and Microsoft's gateways run each server in its own container (`/comparison`, "isolation"); SAJHA runs a stdio upstream as its own process user | stdio upstreams are off unless `federation.allow_stdio` is set, and then run unconfined (`sajha/federation/connection.py`; [Federation](Federation.md)) | Launch stdio upstreams through the sandbox's `docker` backend with its network policy, one container per upstream, restarted by the federation manager | L | L6 |
| L10 | Federation at gateway scale | The gateways are built to put many servers behind one endpoint (`/comparison`) | Connection state, the event loop and breakers are per process; federation is off by default ([Federation](Federation.md#12-limits)) | Shared upstream health in the state store, connection pools per upstream, routing and load shedding across many upstreams, published with X13's numbers | L | X13 |
| L11 | SaaS breadth through packs | Composio, Zapier and Smithery reach thousands of apps with per-user sign-in (`/comparison`, "integrations") | Connected accounts link a handful of providers; any OAuth 2.0 service can be added ([Connected Accounts](Connected%20Accounts.md)) | Provider packs: a connected-account preset plus a reviewed API Import of the service's spec, installed together; start with the services users ask for most | L | L12 |
| L12 | Signed plugins and a catalog | Sharing tools between teams needs trust in who wrote them | A plugin's optional `checksum` sits beside its code and detects corruption, not tampering (`sajha/core/plugins.py`; [Security Model](../security/Security%20Model.md#plugins)) | Publisher signatures verified against configured trusted keys; a catalog page that installs a signed plugin through the same review-and-approve gate as Describe a tool. Separately, list SAJHA in the official MCP Registry (https://registry.modelcontextprotocol.io, launched as a preview in September 2025) | L | none |
| L13 | **Decision:** one-click deployment, then a hosted service | Every hosted competitor in `/comparison` is chosen partly because nobody has to run it | No hosted service; the Helm chart and recipes for AWS, Hetzner and bare metal exist ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md), `deployment/README.md`) | First, one-click templates (Azure and Google Cloud recipes, a published Helm repository, a marketplace image); a hosted service is a business decision that needs X1 enforced | L | X1 |
| L14 | Console in other languages | Regulated and global users ask for it | Every console string is English in the templates | Extract strings with a gettext catalog for templates and page help; the glossary and guides stay English | L | X15 |

---

## 5. Decisions needed

| ID | The question |
|---|---|
| N1 | When to cut 7.0.0. |
| X1 | Enforce tenants (L), or remove the records and rely on roles, API-key tool access and policy rules (S)? |
| X16 | Build a TypeScript client now, or keep it deferred? |
| L13 | One-click templates only, or a hosted service as well? |

---

## 6. Not planned

Limits that are deliberate, so they are not roadmap items. Each owner says why.

- **No open-source licence**: decided. SAJHA is proprietary ("All rights reserved", as `/comparison` records); evaluations that require an OSI licence are out of scope.

- **No stream resumability on the 2026-07-28 path**: by design of that protocol version
  ([MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md#8-known-limits)).
- **No writes or stored procedures through data connectors**
  ([Data Connectors](Data%20Connectors.md#14-limits-of-this-design)).
- **No DDL on PostgreSQL from SAJHA**; an operator runs the schema files
  ([Database Setup](../getting-started/Database%20Setup.md)). N2 and X17 only print SQL.
- **SQLite on several hosts** ([Scaling and State](Scaling%20and%20State.md#7-failure-behaviour-and-limits)).
- **Template creators run in-process** ([Sandbox](Sandbox.md#9-limits-and-future-work)).
- **Syslog over UDP** for SIEM export ([Policy and Audit](Policy%20and%20Audit.md#11-limits)).
- **Killing a running thread-pool call**: Python cannot; calls are abandoned and tools may
  poll for cancellation ([Workflows](Workflows.md#9-limits)).

---

## 7. Keeping this document current

- **When an item ships**, delete its row, describe it in the CHANGELOG's Unreleased
  section, and remove it from the owning guide's limits section. A shipped feature is
  described by its guide, not here.
- **When a new gap is found**, add it to the owning guide's limits section first, then
  one row here that links to it.
- **No numbers from the code** (tool counts, test counts, versions); name where the live
  answer is ([CLAUDE.md](../../CLAUDE.md)).

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
