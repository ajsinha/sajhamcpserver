# SAJHA Roadmap

This document owns one topic: **what is not built yet, and what should come next**. It
has two kinds of item. *Unfinished work* is a gap that the code or a guide already
records: a feature that is half built, a limit a guide lists, a release step
not taken. *Enhancements* are recommendations for making SAJHA the MCP server teams choose,
grounded in where the comparison (`/comparison`, data in `sajha/web/competitive.py`) says
others are stronger.

Each item is one line here. The detail of a feature's limits stays in the guide that owns
the feature, and every row links to it. When the two disagree, the owning guide is right
and this roadmap is the one to fix.

---

## 1. How to read this

The order in which these items are built is the
[Implementation Plan](Implementation%20Plan.md): waves, each a release, with each wave's status.

**Horizons.** *Now* is what the next release needs before it is cut. *Next* is the work that
closes the gaps an operator meets first (access control, the intelligence layer, evidence of
performance). *Later* is larger work that changes what kind of product SAJHA is (gateway
scale, container isolation, SaaS breadth, hosting, streaming between servers).

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

## 2. Now

Nothing open. The release hygiene items (N2 to N5) shipped in wave 1 of the
[Implementation Plan](Implementation%20Plan.md); what the release in progress still needs is
that plan's open phases.

---

## 3. Next

### 3.1 Unfinished work

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| X3 | Per-user access to prompts and data resources | An API key limited to a few tools can still read every prompt and data file | Only anonymous callers are filtered (`mcp.anonymous.prompts`, `mcp.anonymous.resources`); federated prompts and resources likewise ([Security Model](../security/Security%20Model.md#8-known-limitations), [Federation](Federation.md#12-limits)) | Extend the tool allow and deny patterns of `sajha/auth/access.py` to prompts and resources, so `prompts/list`, `resources/list` and reads use one policy | M | none |
| X7 | Ask SAJHA over MCP, finished | `sajha_ask` is the one tool most clients will call | Destructive-tool confirmation comes back as `needs_confirmation`, not as a Multi Round-Trip Request; history is not trimmed on `ContextTooLong`; freshness and agreement are not in the confidence score ([Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | Confirmation as MRTR on 2026-07-28; trim oldest turns before falling back to a larger model | M | none |
| X8 | Document connectors as RAG sources | Answers grounded in SharePoint, Drive or Confluence are what most people ask an assistant for | A source is a folder in the storage backend, or an upload; PDF and Word are read, scanned PDFs are not (no OCR) ([Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | Sources that read through connected accounts, so a user's index respects their own access; incremental re-index; optional OCR | M | none |
| X9 | LLM providers: the last synchronous paths | Thread-pool wrappers limit concurrency under load | Bedrock (boto3 is synchronous) and embeddings run in a worker thread; Bedrock refuses `reasoning_effort` (`sajha/ai/llm/providers/bedrock.py`; [Intelligence Layer](Intelligence%20Layer.md#9-not-built-yet)) | An async Bedrock client; native async embeddings on the HTTP providers; `reasoning_effort` through `additionalModelRequestFields` per model | S | none |
| X10 | Weaviate and Chroma connectors | Two common vector stores reachable today only by federating their own MCP servers | Not built ([Data Connectors](Data%20Connectors.md#14-limits-of-this-design)); the `VectorAdapter` interface in `sajha/connectors/vector.py` is small | One adapter each, with the same allowlist, filters and masking as Qdrant | S | none |
| X11 | Push-based reload | Polling delays a change on cloud storage by up to the interval, and costs list calls | `hot_reload.interval_seconds` polls; workflow file triggers poll too ([Storage Guide](../getting-started/Storage%20Guide.md#planned-not-yet-built), [Workflows](Workflows.md#9-limits)) | Bucket event notifications (S3 to SQS or EventBridge, Azure Event Grid, GCS Pub/Sub) feeding the change bus; polling stays as the fallback | M | none |
| X12 | Protocol gaps | Each is a client a strict reviewer can name | `notifications/tasks` is not emitted; legacy streamable-HTTP sessions get no `list_changed`; external issuers must issue JWTs (no RFC 7662 introspection); no CORS on the OAuth endpoints for browser clients ([MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md#8-known-limits), [MCP 2025-11-25 Compliance](../protocol/MCP%202025-11-25%20Compliance.md#7-not-implemented-on-this-path)) | Take them in that order; each lands with conformance evidence in its compliance report | M | none |

### 3.2 Enhancements

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| X13 | A benchmark suite with published numbers | A buyer comparing servers asks "how fast, on what hardware"; SAJHA has no answer | Nothing measures throughput or latency; the deck states that it "claims no performance it has not measured" ([deck guide](../../tools/deck/GUIDE.md)) | A repeatable load harness against `/mcp` in both eras, calling mock tools, at one and several workers on each `state.backend`; publish p50, p99 and throughput with the hardware in [Scaling and State](Scaling%20and%20State.md), and let the deck read them at build time | M | none |
| X14 | SLOs and failure tests | The failure behaviour is written down but not exercised | [Scaling and State](Scaling%20and%20State.md#7-failure-behaviour-and-limits) describes Redis loss, slow databases and dying workers; [Observability](Observability.md) ships alert rules | State SLOs on the existing metrics; failure tests that stop Redis, kill a worker mid-task and break an upstream, asserting the documented behaviour | M | X13 |
| X16 | A TypeScript client SDK (deferred by decision) | Most agent front ends are TypeScript | The client SDK (`clientsdk`) is Python only; any standard MCP client already works against `/mcp` ([Client SDK Guide](../clients/Client%20SDK%20Guide.md)). The owner has deferred this | A thin package on the official TypeScript MCP SDK, mirroring `SajhaMCPClient`, plus the REST and A2A helpers | M | none |

---

## 4. Later

### 4.1 Unfinished work

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L1 | Storage, finished | Cloud deployments still need a shared file system in places | DuckDB reads a local directory only; Studio modules need a shared file system; plugins and some other subsystems use direct file IO; no storage-backend tests in CI; no Azure or GCP deployment guide ([Storage Guide](../getting-started/Storage%20Guide.md#planned-not-yet-built)) | The Storage Guide's planned list, in its order; backend tests on emulators in CI | M | none |
| L2 | Federation, complete | Federated servers lose features they have | Resource templates, completions, `resources/subscribe`, upstream tasks and `ui://` views are not carried; 2025-11-25 upstreams' requests to the client are declined ([Federation](Federation.md#12-limits)) | Carry each feature through with the same namespacing and policy | M | none |
| L3 | Workflow engine limits | Long or fan-out workflows hit them first | A `foreach` body is one call; change-bus event triggers fire only on the producing worker; missed cron slots are coalesced ([Workflows](Workflows.md#9-limits)) | Sub-graph bodies; relay trigger events through the state store; an opt-in replay of missed slots | M | none |
| L4 | API Import coverage | Real-world specs use what is not imported | No multipart or binary bodies, callbacks or GraphQL subscriptions; pagination is a hint, not followed; remote `$ref` in Swagger 2.0 not converted ([API Import](API%20Import.md#8-limits)) | Multipart first (it blocks uploads), then opt-in pagination following with a page cap | M | none |
| L5 | Tool quality reach | Tests that run live are flaky; lexical evals miss meaning | Cassettes cover `urllib.request`, `requests` and `httpx` only; eval answer checks are lexical ([Tool Quality](Tool%20Quality.md#10-limits)) | Cassettes for other HTTP clients and SDK transports; an optional model-graded check beside the lexical ones | M | none |
| L6 | Sandbox depth | Host-name allowlisting is library-level; a container per call is slow | No egress proxy; no warm pool; no WASM backend ([Sandbox](Sandbox.md#9-limits-and-future-work)) | An egress proxy that enforces the allowlist on the wire; a warm container pool with state reset; WASM for pure-Python tools | M | none |
| L7 | Provider tool gaps | Each limits a common task | SharePoint uploads stop at Graph's simple-upload size and only the client-credentials grant is implemented (`sajha/tools/impl/sharepoint_tool.py`; [SharePoint Tool Reference Guide](../tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md#known-issues)); the web crawler runs no JavaScript and parses HTML only ([Web Crawler Tool Reference Guide](../tools/search/Web%20Crawler%20Tool%20Reference%20Guide.md#limitations)). The other provider guides' limitations are the upstream APIs' own | Upload sessions and certificate credentials for SharePoint; PDF text for the crawler | S | none |

### 4.2 Enhancements

| ID | Item | Why it matters | Current state | Proposed approach | Size | Depends on |
|---|---|---|---|---|---|---|
| L9 | A container per federated stdio server | Docker's and Microsoft's gateways run each server in its own container (`/comparison`, "isolation"); SAJHA runs a stdio upstream as its own process user | stdio upstreams are off unless `federation.allow_stdio` is set, and then run unconfined (`sajha/federation/connection.py`; [Federation](Federation.md)) | Launch stdio upstreams through the sandbox's `docker` backend with its network policy, one container per upstream, restarted by the federation manager | L | L6 |
| L18 | Per-user OAuth sign-in to upstream MCP servers | Hosted MCP servers (Notion, Supabase and others) let each user sign in with OAuth; federation cannot reach them without a static credential | An upstream that answers HTTP 401 without a credential is shown as `needs_sign_in` ("needs sign-in (not supported yet)") with a notice (`sajha/federation/connection.py`; [Federation](Federation.md#the-mcpservers-file)); `auth.type: connected_account` works only with providers configured by hand ([Connected Accounts](Connected%20Accounts.md)) | MCP authorization discovery (protected-resource and authorization-server metadata), dynamic client registration, and the user's token kept in the connected-accounts vault, sent per call as `connected_account` upstreams do today | M | none |
| L10 | Federation at gateway scale | The gateways are built to put many servers behind one endpoint (`/comparison`) | Connection state, the event loop and breakers are per process; federation is off by default ([Federation](Federation.md#12-limits)) | Shared upstream health in the state store, connection pools per upstream, routing and load shedding across many upstreams, published with X13's numbers | L | X13 |
| L11 | SaaS breadth through packs | Composio, Zapier and Smithery reach thousands of apps with per-user sign-in (`/comparison`, "integrations") | Connected accounts link a handful of providers; any OAuth 2.0 service can be added ([Connected Accounts](Connected%20Accounts.md)) | Provider packs: a connected-account preset plus a reviewed API Import of the service's spec, installed together; start with the services users ask for most | L | L12 |
| L12 | Signed plugins and a catalog | Sharing tools between teams needs trust in who wrote them | A plugin's optional `checksum` sits beside its code and detects corruption, not tampering (`sajha/core/plugins.py`; [Security Model](../security/Security%20Model.md#plugins)) | Publisher signatures verified against configured trusted keys; a catalog page that installs a signed plugin through the same review-and-approve gate as Describe a tool. Separately, list SAJHA in the official MCP Registry (https://registry.modelcontextprotocol.io, launched as a preview in September 2025) | L | none |
| L13 | One-click deployment templates (no hosted service, by decision) | Every hosted competitor in `/comparison` is chosen partly because nobody has to run it | No hosted service; the Helm chart and recipes for AWS, Hetzner and bare metal exist ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md), `deployment/README.md`) | First, one-click templates (Azure and Google Cloud recipes, a published Helm repository, a marketplace image); a hosted service is a business decision, and would need tenant isolation, which SAJHA does not have (see [section 6](#6-not-planned)) | L | none |
| L14 | Console in other languages | Regulated and global users ask for it | Every console string is English in the templates | Extract strings with a gettext catalog for templates and page help; the glossary and guides stay English | L | none (console checks: X15, shipped) |
| L15 | Planners chosen by learning from results | The `auto` planner chooses by rules, a model's label and escalation on failed checks; it does not yet learn which strategy actually wins for each tool and kind of question | SAJHA records what a learner needs (verify outcomes, confidence, `stopped_by`, cost, latency, eval scores per planner), but nothing feeds it back into the choice ([LLM Tools](LLM%20Tools.md#913-automatic-planner-selection)) | Offline first: eval sets rank planners per tool and question class, and a person approves updated routing rules. Then an opt-in online bandit (Thompson sampling or epsilon-greedy) across a tool's allowed planners, scoring quality minus a cost weight, exploring a capped share of traffic through the canary machinery with automatic rollback | M | LLM tools built; enough traffic and eval history |
| L16 | SAJHA Net, finished | Domain data sovereignty across SAJHA and other MCP servers is built (waves 4 and 5 of the [Implementation Plan](Implementation%20Plan.md)); a few parts of the design are not | [SAJHA Net §5.5](SAJHA%20Net.md#55-what-is-built) lists what is built and what remains, with the protocol's conformance ids not yet covered | Take the remaining items in that section's order; each lands with its conformance case | M | none |
| L17 | Protocol uniformity between servers, and its security: server to server on the same streaming protocol as client to server (owner idea, 2026-10-07) | A tool that runs on another member should feel like a local one: progress, partial results and cancellation reach the client as the remote work builds, whatever transport the client chose | A forwarded call is one signed POST to the host's `/mcp` (2026-07-28 `tools/call`) answered with one JSON body (`sajha/net/routing.py`); the home relays only the final result over the client's own transport (SSE, WebSocket or REST); progress, cancellation, input requests and tasks are not relayed (SAJHA Net conformance ids CALL-11, FB-07, CALL-12 in [SAJHA Net](SAJHA%20Net.md)) | Make the server-to-server leg streaming MCP: the signed request asks for `text/event-stream`, the host streams progress, partial content and the final result as events, and the home re-emits each event at once on the client's transport (an SSE event, a WebSocket message, or buffered into the REST body); carry cancellation to the host and relay input requests and tasks; optionally keep a 2025-11-25 session per host. Explore whether the hop should mirror the client's era. Planned as wave 6 of the [Implementation Plan](Implementation%20Plan.md), after wave 5. In two steps, both in wave 6 (owner decision, 2026-10-07): **L17a**, streaming as above with the request signed as today and the events relayed as they arrive, the hop, loop and residency checks made once per call; **L17b**, security per event: each event signed or covered by a running digest closed by a signed final event, so an injected or reordered event is refused, plus replay protection and residency checks on partial results. L17b ships in the same wave, so no streamed answer is trusted on the network alone | M (L17a), S (L17b) | none |

---

## 5. Decisions needed

None open. Recorded decisions:

- **Release 7.0.0** cut on the owner's decision (formerly N1).
- **TypeScript client** stays deferred (X16).
- **Deployment:** one-click templates only; no hosted service (L13).
- **No tenants** (formerly X1, see section 6) and **no open-source licence**.

---

## 6. Not planned

Limits that are deliberate, so they are not roadmap items. Each owner says why.

- **No tenants**: decided (formerly X1). The tenant records, which were stored but never
  enforced, were removed; roles, API-key tool access and policy rules (which also meter
  quotas) separate teams ([Security Model](../security/Security%20Model.md#tool-access)).
  Usage and cost are therefore not reported per tenant.
- **No open-source licence**: decided. SAJHA is proprietary ("All rights reserved", as `/comparison` records); evaluations that require an OSI licence are out of scope.

- **No stream resumability on the 2026-07-28 path**: by design of that protocol version
  ([MCP 2026-07-28 Compliance](../protocol/MCP%202026-07-28%20Compliance.md#8-known-limits)).
- **No writes or stored procedures through data connectors**
  ([Data Connectors](Data%20Connectors.md#14-limits-of-this-design)).
- **No DDL on PostgreSQL from SAJHA**; an operator runs the schema files
  ([Database Setup](../getting-started/Database%20Setup.md)); the start-up check and `python -m sajha.db upgrade-sql` only print SQL.
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
