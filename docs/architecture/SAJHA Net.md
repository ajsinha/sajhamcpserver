# SAJHA Net

> **Status: being built.** Membership is built (wave 4, phase 4.1): the protocol core and its
> plug-in interfaces, names and name conflicts, the CA run by SAJHA, signed requests on the normal
> port, gossip, restarts and adding a peer by address; [section 5.5](#55-what-is-built) lists what
> and where. Catalogs, proxy tools, identity and the rest of this note are still design. This note
> is the design for **SAJHA Net**: a network of several SAJHA
> servers that share their tools with one another while each keeps its own data, credentials,
> policy, AI layer and conversation memory. It extends [Federation](Federation.md), which
> today brings other MCP servers' tools into one SAJHA by hand. It is item L16 on the
> [Roadmap](Roadmap.md).

A SAJHA server configured as an **instance** of a net (or of several named nets, kept apart)
automatically learns which tools the other instances offer, and builds a **proxy tool** for each one it is allowed to use. The proxy appears
in its catalog next to its own tools. When a caller (a person, an MCP client, a planner, an LLM
tool, a workflow) calls a proxy, SAJHA forwards the call to the instance that hosts the tool, as
that caller, and returns the result. To the caller, a net tool is just a tool.

The point is **domain data sovereignty**: risk data stays with the risk domain's server,
customer data with the customer domain's, EU data in the EU. Tools and the AI that uses them can
be spread across many servers, each governed by the people who own its data, and still answer
questions that span domains.

---

## Contents

1. [Why build this](#1-why-build-this)
2. [Goals and non-goals](#2-goals-and-non-goals)
3. [Vocabulary](#3-vocabulary)
4. [How it relates to federation](#4-how-it-relates-to-federation)
5. [Open to any MCP server: participants and plug-in points](#5-open-to-any-mcp-server-participants-and-plug-in-points)
6. [Membership](#6-membership)
7. [Catalog exchange](#7-catalog-exchange)
8. [Proxy tools and the unified catalog](#8-proxy-tools-and-the-unified-catalog)
9. [What happens on a call](#9-what-happens-on-a-call)
10. [Identity](#10-identity)
11. [Authorization](#11-authorization)
12. [Data sovereignty and residency](#12-data-sovereignty-and-residency)
13. [Planners, LLM tools and memory](#13-planners-llm-tools-and-memory)
14. [Hops and loops](#14-hops-and-loops)
15. [Reliability](#15-reliability)
16. [Observability and audit](#16-observability-and-audit)
17. [The SAJHA Net console](#17-the-sajha-net-console)
18. [Threats and mitigations](#18-threats-and-mitigations)
19. [Configuration](#19-configuration)
20. [Storage](#20-storage)
21. [Testing](#21-testing)
22. [Build plan](#22-build-plan)
23. [Competitive position](#23-competitive-position)
24. [Decisions for the owner](#24-decisions-for-the-owner)
25. [Alternatives considered](#25-alternatives-considered)

---

## 1. Why build this

Large organisations rarely have one place where all data may live. Business lines, legal
entities and regions each own their data and the rules for using it, and regulators expect those
boundaries to hold. A single central tool server either cannot reach that data or becomes the
place where every boundary is crossed.

A net puts a SAJHA server inside each boundary. Each one:

- holds the tools that touch its data, and the credentials those tools use;
- applies its own access rules, policy engine, approvals and audit;
- runs its own AI layer (models, budgets, planners, LLM tools) under its own governance;
- keeps its own users' conversation memory.

What crosses a boundary is a **tool call and its result**, and only when both sides' rules allow
it. Questions that span domains ("how exposed is the EU book to the rate move the US desk is
forecasting?") can then be answered by a planner on one instance using tools on several, without
copying either domain's data into the other.

---

## 2. Goals and non-goals

**Goals**

- G1. An instance discovers other instances' tools automatically and builds proxy tools for those it
  may use; `tools/list` shows local and remote tools together.
- G2. Calling a remote tool is transparent to callers, planners, LLM tools, composites and
  workflows.
- G3. The remote instance knows **which user** is calling, not only which server, and authorizes
  the call itself.
- G4. Each instance decides what it exports (and to whom) and what it imports (and for whom).
- G5. Data residency rules can stop data leaving a boundary, in arguments as well as results.
- G6. Local tools always win over remote ones for a plain name (unless the server exports that tool
  into a net where the name is quarantined, section 8.7); a plain name otherwise resolves in a
  stated, visible order (per-tool preferences, then nets in configured order); remote tools are never
  shadowed silently, and a qualified name always reaches exactly the tool it names.
- G7. Every cross-instance call is audited on both sides, linked by one trace id.
- G8. An instance that is slow, down, revoked or compromised cannot take the others down or widen
  what anyone may do.
- G9. Instances come and go without manual peer configuration: arrivals, clean departures and
  failures are detected automatically, and an instance's tools disappear from every peer the moment
  it is known to be gone.
- G10. Any MCP server can take part, natively, through the SAJHA Net agent, or sponsored by a
  SAJHA instance; every moving part is a pluggable interface (section 5).
- G11. A server can belong to several named nets at once, each fully separate; being in two nets
  never joins them.
- G12. When the host chosen for a plain name is down, the call goes to the next host offering the
  same tool, whenever that cannot run the tool twice.
- G13. Within a net a tool name means one contract: hosts that disagree about it cannot serve it
  until they agree (section 8.7).

**Non-goals**

- Shared state between instances. Each instance keeps its own database, state store and memory;
  only catalogs and calls travel.
- A consensus protocol or leader election. Who may join is decided by people, by issuing a
  certificate (section 6.4); everything after that is automatic.
- Moving data in bulk between instances. A net moves calls, not datasets.
- Replacing federation with third-party MCP servers; that stays as it is.
- Joining nets together. A server in two nets keeps them apart; a tool crosses from one net to
  another only where an administrator turns re-export on for the receiving net (section 14).

---

## 3. Vocabulary

These terms go into `GLOSSARY.md` when the feature is built.

| Term | Meaning |
|---|---|
| Net | A named group of SAJHA servers that share tools under each other's rules; one server may belong to several. |
| Net name | A net's name: lowercase, starting with a letter, at most 16 characters, never containing `__`; the first part of every qualified tool name. |
| Default net | The net a server is in when its configuration names none; it is called `default`. |
| Instance | One SAJHA server in a net, with a name unique in that net (for example `risk-eu`). |
| Home instance | The instance that received the caller's request. |
| Host instance | The instance whose tool is being called. |
| Proxy tool | A tool in the home instance's catalog that forwards calls to a host instance's tool. |
| Export rules | A host instance's rules for which tools it offers, to which instances and for which roles. |
| Import rules | A home instance's rules for which remote tools its users may see and what data may leave. |
| Data class | A label on data (for example `eu-personal`, `confidential`) used by residency rules. |
| Hop | One instance-to-instance forwarding step of a call. |
| Gossip | The protocol instances use to discover each other, detect arrivals, departures and failures, and spread digests of what changed. |
| SAJHA Net | The network of SAJHA servers and other MCP servers that share tools under each other's rules; a particular one is a net (for example `acme-net`). |
| Participant | Any server in a net: a SAJHA instance, a net-enabled MCP server, or a sponsored MCP server. |
| Sponsor | A SAJHA instance that represents an MCP server unaware of SAJHA Net, governing its tools in the net. |
| SAJHA Net agent | A small program run next to any MCP server that speaks the SAJHA Net protocol on its behalf. |
| SAJHA Net extension | The versioned MCP extension (`io.sajha/net`) that participants speak to each other. |
| Instance name | An instance's name in one net, set in its own configuration and unique in that net; a server in several nets may have a different name in each. |
| Qualified tool name | A remote tool's full name, `<net>__<instance>__<tool>`, which always reaches exactly that tool on that instance in that net. |
| Plain name | A tool name without net and instance; it resolves to the local tool, else in the resolution order. |
| Resolution order | The order in which a plain name is matched: the local tool, the tool's preference list, then the nets in configured order. |
| Preference list | An administrator's ordered list of nets, or instances in a net, to try first for one tool. |
| Tool contract | What a tool name promises: its input and output schemas and annotations (its description too, though a description difference only warns). |
| Contract hash | A hash of a tool's input schema, output schema and annotations, used to compare contracts between hosts. |
| Quarantine | The state of a tool name whose hosts in a net offer different contracts: no copy is listed or callable anywhere in the net until they agree. |
| Waterfall fallback | Trying the next host offering the same tool, in resolution order, when the chosen host did not run the call. |
| Not executed | A failed call the home knows, or the host has signed, never ran the tool; only such a failure lets any tool fall back. |
| Bridge | A server in two nets that offers one net's tools in the other, which it does only when re-export is on for the receiving net. |
| Net user | A user at an instance, written `user@instance`; the same person may be a different user on each instance. |
| Default API key | The API key every user always has; kept encrypted at its home instance so it can be forwarded. |
| Host and tool table | Each instance's live record of which instance, in which net, hosts which remote tool, and in what order a plain name tries them. |
| Block | An administrator's local decision to stop calls to or from another instance, a tool or a remote user. |
| Seed instance | A pre-identified instance a starting instance contacts first to learn a net. A net entry without seeds is a net of one (section 6.6). |
| Founder | The first server of a net, which starts with no seeds (or with `founder: true`, so that it starts alone when its seeds are all down), typically its CA instance. |
| Net of one | A net whose only member is this server: an entry with no seeds and no known peers (owner decision). It joins nothing, gossips with nobody and raises no error, and grows into an ordinary net when a peer joins through it or is added by address, without a restart. |
| Saved peer list | The peers of a net a server last knew, saved on local disk and tried after the seeds on a restart. |
| Incarnation | An instance's own counter that makes newer news about it override older news. |
| Identity resolver | The pluggable part that turns a caller into credentials on the home instance and back into a verified user on the host instance. |
| Net key directory | Every instance's synced copy of the API key records (hashes, never keys) issued across the net. |
| User assertion | A short-lived JWT signed by the home instance naming the user; a later identity resolver, not the first (section 10.2). |
| Address name | The `<ip>:<port>` an instance is named after when no instance name is configured (section 6.1). |
| CA instance | The one instance that runs the SAJHA Net CA: enrolls, renews and revokes instance certificates (section 6.4). |
| Enrollment token | A one-time, short-lived token, bound to one instance name, with which a new instance obtains its certificate (section 6.4). |
| Trust level | How a home instance accepts a peer's tools: `auto`, `review` or `pinned` (section 7.3). |
| Persistent key | An API key whose record is also kept, hashed, in a file so it survives a lost database (section 20.3). |
| Snapshot | A periodic, signed and chained record of an instance's users, keys and tools (section 20.4). |

---

## 4. How it relates to federation

Federation (`sajha/federation/`) already does the hard part of one direction: a remote MCP
server's tools become `FederatedTool` entries (`sajha/federation/tool.py`), reached through the
same `execute_with_tracking` path as every SAJHA tool, with namespacing, approval, description
screening, the SSRF guard, circuit breakers, caching, rate limits and per-user token passthrough.

The net **reuses all of that** and adds what federation lacks:

| Concern | Federation today | Net adds |
|---|---|---|
| Who configures it | An administrator adds each upstream by hand | Instances find each other by gossip, admitted by a net certificate, and exchange tools automatically (section 6) |
| Direction | One way: SAJHA consumes an upstream | Symmetric: every instance exports and imports |
| Who the remote side sees | The upstream's own credential for every caller, or the user's own SaaS token | The **SAJHA user**, identified by their API key and checked against a synced key directory (section 10) |
| Authorization at the remote side | Whatever the upstream does | The host instance's export rules, access rules and policy engine, every call (section 11) |
| Data residency | Not modelled | Data classes on arguments and results, checked on both sides (section 12) |
| Audit | Policy events only (denials, approvals, redactions); ordinary tool calls go to the usage ledger, not the audit chain | Every cross-instance call on both sides, linked by one trace id (section 16) |
| Planner awareness | A federated tool looks local | Locality, region, health and latency in the catalog (section 13) |

Implementation-wise, a net proxy is a subclass of the federated tool with a net connection
(instance identity plus user identity) instead of an upstream credential; discovery, refresh,
namespacing and failure isolation are shared code.

Federation's code did not do everything the net needs. The table names each change; those
marked **built** are in the code now (section 21.1 has the status of each item):

| Federation today (code) | What the net needs |
|---|---|
| An upstream prefix is 1 to 32 characters, starts with a letter and does not end in `_` (`UpstreamConfig.validate`); `namespaced()` cleaned names to the MCP rule `[A-Za-z0-9_.-]{1,128}`, which allows `.` | A net proxy's name has two prefixes, `<net>__<instance>__<tool>` (section 8.2); the instance part may be an address name that starts with a digit and is up to 44 characters for IPv6 (section 6.1), and `.` is not accepted by every LLM provider. **Built**: the qualified-name rule is `sajha/net/names.py`; the tool part (every character outside `[A-Za-z0-9_-]`, `.` included, becomes `_`) is `sajha/federation/names.py::tool_part`, which federation's `<prefix>__<tool>` now uses too, and two names that map to one are both refused |
| A tool whose definition changes goes to status `changed` and is withdrawn from the registry until approved again | `review` trust keeps the previously approved version serving (section 7.3); a changed contract under the same version is refused net-wide (section 8.7). **Built** in federation: an upstream's `on_change: hold` keeps the approved version serving (the default stays `withdraw`) |
| Annotations are copied from the upstream as they are | Annotations corrected, never widened (section 8.1). **Built**: `security.py::correct_annotations`, used by federation for every upstream tool |
| Imported schemas are taken as they are (only their text is screened) | Schemas checked for valid JSON Schema (section 7.3). **Built**: `security.py::schema_problem`; an invalid tool is `invalid`, with the reason in the approval queue |
| The tool cache (`sajha/core/cache.py`) keyed a result by tool name and arguments only | A cache key that includes the caller. **Built** (wave 1): `cache_per_user` adds the caller to the key, and federated tools default to it (`cache.per_user_federated`); federation still refuses `cache_ttl` with `connected_account`, and net proxies do not cache (section 9) |
| The SSRF guard (`sajha/federation/security.py::check_url`) refuses loopback and private addresses unless `federation.allow_localhost` / `allow_private_networks`, and hosts outside `federation.allowed_hosts` when that is set | Instances usually sit on private networks: the net's guard takes its own settings and binds a peer's URL to its certificate (section 18). **Built**: `check_peer_url`, with `sajhanet.allowed_networks`; binding to the certificate is the request signing's |
| Federation abandoned its local wait when its caller cancelled; a 2025-11-25 `notifications/cancelled` stopped nothing | Cancellation reaches the host. **Built**: either era's cancellation cancels the upstream request, which the SDK sends on (`sajha/core/mcp_cancellation.py`, [Federation](Federation.md#7-calls)) |
| No trace context was sent upstream; a server span only continued an inbound `traceparent` | Outbound `traceparent` on every forwarded call (section 16). **Built** (wave 1): SAJHA continues or starts a `traceparent` and sends it on its outbound calls (`sajha/observability/tracing.py::inject`), federation forwards the caller's (`sajha/federation/connection.py`), and a forwarded net call carries it in the header and in `_meta` (protocol §15.2) |
| Upstreams and approval records are one JSON document at `federation.state_path` in the storage backend | The same storage backend, plus the state store for what changes often (section 20.2) |

---

## 5. Open to any MCP server: participants and plug-in points

SAJHA Net is not only for SAJHA servers. **Any MCP server may join**, so the design separates the
protocol from SAJHA's implementation of it, and every moving part is behind an interface with
more than one implementation.

### 5.1 Three ways to take part

| Participant | What it is | How it joins | Who enforces the host side |
|---|---|---|---|
| **SAJHA instance** | A SAJHA server with SAJHA Net enabled | Natively: certificate, gossip, catalog, key directory, identity resolver | Itself (export rules, access, policy, audit) |
| **Net-enabled MCP server** | Any MCP server, in any language, that speaks the SAJHA Net extension, either built in through the reference library or added by running the **SAJHA Net agent** as a sidecar in front of it | The agent (or library) holds the certificate, gossips, publishes the catalog, verifies forwarded API keys against the key directory and applies a small export policy, then passes calls to the server | The agent, with the server's own authorization behind it |
| **Sponsored MCP server** | Any MCP server that knows nothing about SAJHA Net (a vendor's server, a SaaS MCP endpoint, a stdio tool) | A SAJHA instance **sponsors** it: the sponsor connects to it as federation does today, and represents it in the net under its own instance name (for example `vendor-search`) | The sponsor, fully: SAJHA's export rules, access, policy, residency and audit, plus whatever credential the server itself requires |

Every participant has an instance name, appears on the console's map and in every host and tool
table, and its tools become proxy tools on other instances exactly as a SAJHA instance's do.
Callers and planners cannot tell the kinds apart, except through the instance's metadata
(`kind: sajha | agent | sponsored`), which the console shows.

**What each kind can do.** Capabilities are negotiated, not assumed: a participant advertises what
it supports (gossip, key verification, residency labels, LLM tools, remote progress and
cancellation, MRTR), and peers use only what both sides support. A sponsored server gets the
sponsor's full governance but only the MCP features the server itself implements.

### 5.2 The SAJHA Net protocol is an MCP extension

What participants speak to each other is published as a versioned specification, so others can
implement it without SAJHA's code:

- it is an **MCP extension** (`io.sajha/net`), advertised in the server's capabilities on both
  protocol eras. On 2026-07-28 it goes in `capabilities.extensions` of the `server/discover`
  result, where SAJHA already lists the tasks (`io.modelcontextprotocol/tasks`) and MCP Apps
  (`io.modelcontextprotocol/ui`) extensions (`sajha/core/mcp_modern.py`). The 2025-11-25
  `initialize` result has no `extensions` map today (only `experimental.sajha`,
  `sajha/core/mcp_handler.py`), so advertising it there is new: under
  `capabilities.experimental["io.sajha/net"]`;
- it defines the gossip messages, the catalog's `_meta["io.sajha/net"]` metadata, the key-directory
  records and their signatures, the identity headers, the block and digest formats, and the
  error codes for refusals;
- it has its own version number, independent of MCP's, and a conformance test suite that the
  agent, the library and SAJHA itself all run in CI.

The specification is [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md): endpoints, schemas,
signatures, merge rules, error codes, limits and the conformance test list.

### 5.3 Plug-in points

SAJHA's implementation is a set of interfaces with registered implementations. Each is chosen in
configuration by name or by `package.module:Class`, and third parties can add their own through a
Python entry-point group (`sajha.net.plugins`), as planners already can.

| Interface | Decides | Shipped implementations | Possible others |
|---|---|---|---|
| **Membership provider** | how participants find each other and detect arrivals and departures | `gossip` (SWIM, section 6.3), `static` (a list in configuration) | Kubernetes service discovery, DNS SRV, a registry, Consul |
| **Admission and certificates** | who may join and how they prove it | `builtin_ca` (section 6.4), `manual` (section 6.5) | an organisation PKI, SPIFFE/SPIRE workload identities, cloud certificate services |
| **Peer connector** | how calls and catalogs travel to a participant | `sajha_native` (MCP with the extension, signed requests on the normal HTTP port), `mcp_generic` (plain MCP: Streamable HTTP, SSE, stdio, through federation's connection code) | gRPC, a message bus, an air-gapped file drop |
| **Identity resolver** | how the user travels with a call and is verified (section 10.2) | `api_key` | `assertion`, `token_exchange`, `none` (service identity only, for sponsored servers that have no user concept) |
| **Catalog source** | where a participant's tools come from | `native` (with net metadata), `mcp_tools_list` (any MCP server, metadata filled in by the sponsor) | an OpenAPI import, a registry listing |
| **Key directory store** | where synced key records live | `database` (the `sajhanet_api_keys` table) | Redis, an external secrets service |
| **Rule evaluators** | export, import, residency and blocking decisions | the policy engine | an external policy decision point (for example OPA) |
| **Snapshot sink** | where snapshots go | local files, the storage backend, the SIEM export | object storage with retention lock |
| **Routing strategy** | the order of the hosts within one net that offer a tool, after the tool's preferences (section 8.2) | `local_first` (the default: local tool first, then hosts in a stable order by instance name), `lowest_latency`, `pinned` (only hosts named in preferences) | cost-aware, region-pinned |

### 5.4 How the code is organised

- A protocol-only core (`sajha/net/<module>.py` for each part) holds the data models, the
  interfaces above, the extension's message schemas and the conformance tests. It imports nothing
  from the rest of SAJHA, so the agent and the library can be built from it.
- SAJHA's integration (the registry hooks for proxy tools, the policy engine, the audit log, the
  console, the CLI) sits on top and depends on the core, never the other way round.
- The **SAJHA Net agent** is a small separate program built from the core: it runs next to any MCP
  server, verifies signed requests, gossips, publishes the server's catalog with net metadata,
  verifies forwarded keys, applies its export rules, and forwards allowed calls to the server.
- Every interface has a contract test suite that each implementation, shipped or third-party,
  must pass before it can be selected.

### 5.5 What is built

Wave 4, phase 4.1 built membership; phase 4.2 built catalogs and routing (sections 7 to 9, 14 and 15)
alongside identity and authorization; phase 4.3 built the first console pages, the net of one and the
three-instance test net. Wave 5, phase 5.1 adds locality-aware planners, remote LLM tools and the
combined hop and depth limit (sections 13 and 14); phase 5.2 adds re-export and bridges, the
`assertion` and `token_exchange` identity resolvers and the topology data (sections 10.2, 14 and 17);
phase 5.3 adds the other MCP servers of section 5.1 (sponsored servers, the SAJHA Net agent and the
reference library), the conformance suite runner and third-party plug-in registration.
What is not listed here is still design.

- **The protocol core** is `sajha/net/` and imports nothing from the rest of SAJHA
  (`tests/net/test_net_plugins.py` checks it): names (`names.py`), RFC 8785 canonical JSON
  (`jcs.py`), the RFC 8941 fields the protocol uses (`sfv.py`), keys, certificates and record
  signatures (`crypto.py`), RFC 9421 request and response signatures with RFC 9530 digests
  (`httpsig.py`), the JSON Schemas of every `/sajhanet/v1/` message (`schemas.py`), errors and
  problem bodies (`errors.py`), the CA (`ca.py`), the SWIM rules and the saved peer list
  (`membership.py`), and a participant's nodes, one per net, with their endpoints and gossip
  agent (`node.py`).
- **Plug-in points** (section 5.3): every interface is in `sajha/net/plugins.py` with a registry,
  `package.module:Class` selection and the entry-point group `sajha.net.plugins`; each has a
  contract check in `sajha/net/contract.py` that every implementation passes. Shipped: membership
  `gossip` and `static`; admission `builtin_ca` and `manual`; connectors `sajha_native` and
  `in_process`; identity `none`, `api_key`, `assertion` and `token_exchange`; catalog source `static` (and `native`, SAJHA's registry);
  key directory store `memory` and `database`; rules `allow_all`, `deny_all` and `policy_engine`;
  snapshot sink `local_files`; routing `local_first`, `lowest_latency` and `pinned`.
  **Third-party plug-ins** (phase 5.3): at start SAJHA loads the entry-point group and every module named
  in `sajhanet.plugins.modules` (`plugins.load_plugins`); each newly registered class must pass its
  contract check or it is unregistered and cannot be selected; a module that cannot be imported, registers
  nothing or fails its check is an error notice (`sajhanet.plugin:<source>:<name>`) and an audit record,
  never a failed start; `GET /api/sajhanet/status` lists what loaded (`plugins`). The example is the
  routing strategy `region_first` (`sajha/examples/sajhanet/region_first.py`); tests in
  `tests/net/test_net_plugin_loading.py`.
- **SAJHA's integration** is `sajha/net/integration/` (configuration, state store, notices,
  metrics, audit, the gossip agent's lease) and `sajha/routes/sajhanet_routes.py` (the protocol
  endpoints, the admin API and the `/admin/sajhanet` page); the command line is `sajha net ...`.
  The keys are in the [Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net).
- **Built of section 6:** named nets kept apart by the signed `Sajha-Net-Name`; configured and
  address names with the refusals of section 6.1; name ownership by certificate lineage and loud
  `name_conflict` refusals; the CA per net (init, tokens refused for held names, enrollment,
  renewal with a new key, revocation by name or serial, the signed list spread by gossip digests);
  manual mode with pinned thumbprints (in configuration, `identity.pins`, or added with
  `sajha net pin`); open mode (`admission: open`, owner decision for now, the shipped setting): no CA,
  self-signed certificates accepted on first use and then held to their name, the remembered keys
  kept on disk (`first_use.json`) and forgettable by an administrator. Open mode trusts whoever
  first claims a name: any server that can reach a member and knows the net's name can join under an
  unused name and then receives forwarded calls (with the test admin key while that is on). Switch
  to `builtin_ca` before a net spans machines you do not control; SWIM gossip with suspicion, refutation, dissemination, anti-entropy, leave
  and dead probing; required seeds and `founder`; restarts through seeds, then the saved peer list,
  then a discovery plug-in, with back-off; adding a peer by address (admin API, console, CLI) with
  an optional runtime seed; one gossip agent per net through the renewing lease; and these notice
  sources of section 17.4: not joined (including no seeds), `name_conflict` (own and seen), member
  suspect, dead or left, certificate expiring or expired, renewal failing, revocation list stale, a
  peer added by hand, plain HTTP allowed, and a net still named `default`.
- **Built of sections 7 to 9, 14 and 15** (`sajha/net/catalog.py`, `sajha/net/routing.py`, and in SAJHA
  `sajha/net/integration/catalogs.py`): the catalog endpoint and its pull, driven by `digests.catalog`,
  a changed incarnation, a new run and `refresh_interval_seconds`, with `if_none_match`; complete tool
  definitions with net metadata and contract and description hashes, MCP Apps links stripped; a
  recomputed contract hash that does not match is not imported and flags the peer; schemas checked
  with federation's `schema_problem`, text screened with its markers, sizes capped; the three trust
  levels with approvals under `review`; the host and tool table (live rows only; the stored copy
  serves `if_none_match`, never listing); proxies in the registry under qualified names and bare
  aliases, with `_meta["io.sajha/net"]`; resolution (local, preferences, nets in order by the routing
  strategy) with a reason for every place and every host skipped; offline removal on `left`, `dead`
  and revocation, `unavailable` while `suspect`, nothing remote after a restart until a peer answers;
  one name, one contract with the signed conflicts document, quarantine of every copy (the local one
  included) and automatic re-activation, reported with the differing host and the first differing
  JSON Pointer; forwarded `tools/call` on the MCP endpoint in the order of the protocol's §15.4, with
  hop and loop checks and `executed` on every refusal; waterfall fallback; per-peer breakers, rate
  limits, timeouts and connection pools; the notices "tool quarantined", "active again" and "catalog
  flagged"; the metrics `sajha_net_contract_conflicts`, `sajha_net_remote_tools`,
  `sajha_net_catalog_pulls_total`, `sajha_net_remote_calls_total` and `sajha_net_fallbacks_total`; net
  badges and local, remote, net and instance filters on the Tools page; the net and host of a remote
  tool in the Ask page's "Servers and tools" log. Forwarded calls use the 2026-07-28 era only;
  progress, cancellation, input requests and tasks are not relayed yet. Re-export and bridges are in the
  bullet on sections 10.2, 14 and 17 below.
- **Built of sections 10, 11, 16 and 17.4** (`sajha/net/keydir.py` and `sajha/net/blocks.py` in the
  core; in SAJHA `sajha/net/integration/authz.py` and `keystore.py`, and `sajha/auth/presented_key.py`):
  the `api_key` identity resolver (the home forwards the key the caller presented, or a console user's
  default key from the vault; the host verifies it against the net key directory, refuses it with the
  protocol's reasons, and checks it came from its home); the net key directory in the
  `sajhanet_api_keys` table (owned keys and persistent-file keys published as signed records with one
  version counter per home, tombstones for deleted keys, re-signing after a renewal, delta pulls by
  `digests.keys`, the digest comparison every `key_directory.full_sync_interval_seconds`, records of a
  revoked certificate discarded and re-pulled, records of a home that left or was revoked kept and
  unusable); users across instances (explicit links, name matching on `users.user_id`, `unknown`
  `refuse` or `map_roles` with role maps, `remote_admin`, net settings only by a locally signed-in
  administrator); export and import rules and the key's tool access as a ceiling, through the
  `policy_engine` rule evaluator (the host's own access rules and policy engine run on execution, policy
  source `sajhanet`); blocks at the four levels with expiry, reasons and audit, published in a signed
  blocks document driven by `digests.blocks`; an instance blocked entirely has its key updates ignored;
  `linked_audit` for the records both sides write under one trace id and key id; the notice sources
  "key-directory sync failing for a peer" and "a block added against this server"; the identity and
  access section of the `/admin/sajhanet` page and its admin API. The extension advertises each net's
  `user_identity` (by default `["api_key"]`) and the features `key_directory`, `key_verification` and
  `blocks`. Not built: the "Users across the net" and "Access and blocks" pages of section 17.1 beyond
  the admin page's section.
- **Built of section 17 and the net of one** (`sajha/net/integration/console.py`, the routes in
  `sajha/routes/sajhanet_routes.py`, templates `net/instances.html`, `net/instance.html` and
  `admin/sajhanet_tools.html`): the **Instances** page for every signed-in user (`/net/instances`), with
  this server always first (a net of one when SAJHA Net is off or no one else has joined), each
  participant's net, name, kind, region, labels, state and last seen, and how many of its tools this
  user may use here (this server's tool access and visibility; the host decides again on every call),
  with search and filters by net, state, kind, region and label; an instance's page
  (`/net/instances/{net}/{instance}`, and `/net/instances/this`) with the tools it offers this user:
  name, qualified name, alias, description, inputs and outputs, health and latency, and the Tools page's
  Try it form; the JSON behind both (`/api/sajhanet/instances`); the navbar badge `Net · <instance
  name>` with a health dot in words on hover (`+N` for further nets), linking to Instances; a SAJHA Net
  menu (Instances for everyone, Remote tools and the admin page for administrators); and the admin's
  **Remote tools** page (`/admin/sajhanet/tools`): the host and tool table with filters by net, host,
  state and trust, approve and withdraw for tools held under `review` trust (the existing admin API), and
  the contract conflicts with every offer and hash. A net entry with no seeds is a net of one (section
  6.6), and a net of one may initialise its CA without `ca.enabled`. The three-instance test net runs in
  one process (`tests/net/test_net_three_instances.py`: join through a seed, catalog exchange, a call
  as the user with the `api_key` resolver, a block, a host down with fallback, a contract conflict
  quarantined and re-activated, a restart) and as containers (`deployment/sajhanet-demo/`, with a smoke
  script). A forwarded call now runs at the host with the local account's roles and permissions from
  the host's database.
- **Built of sections 13 and 14: planners, LLM tools and the combined limit** (wave 5, phase 5.1;
  `sajha/ai/locality.py`, `sajha/core/inner_calls.py`, and the hop handling in `sajha/net/routing.py`
  and `sajha/net/integration/catalogs.py`; tests in `tests/net/test_net_planners_llm.py`). **Locality-aware
  shortlists:** every shortlist entry (Ask SAJHA, and LLM tools in `answer` mode) records where the tool
  runs (`local`, `remote` with its net and host, or `federated`) and why it ranked where it did; local
  tools rank first, then remote hosts named in `sajhanet.preferences` for the tool, in this server's
  region in that net, healthy, and with a lower indicative latency (small nudges of the resolver's score,
  so a remote tool that is the right tool is still offered; a shortlist of local tools only keeps the
  resolver's order). Proxies of a host that is not `active`, or that reports itself down, are left out. A
  **locality restriction** (`any`, `local`, or `net:<name>`, which keeps this server's own tools and that
  net's) comes from the ask (`locality` on `POST /api/ai/ask`), else the planner's `settings.locality`
  (a graph planner file or a `planner_config` overlay), else `ai.ask.locality`; the `shortlist` event
  names the restriction and where it came from. **Remote LLM tools:** an LLM tool is exported with
  `llm_tool: true` unless `sajhanet.allow_remote_llm_tools` is false; called from another instance it runs
  on its host as the mapped user, on the host's models and budgets, and the host reports the run's spend in
  the result's `_meta["io.sajha/net"].usage` (`tokens`, `cost_usd`, `models`, `charged_by: "host"`), which
  the home records in its `net.call_attempt` audit record and never charges again. **The combined
  limit:** a forwarded call carries, besides `Sajha-Net-Hop` and `Sajha-Net-Visited`, the nesting depth it
  had (`params._meta["io.sajha/net"].depth`: tools running inside one another, such as composites, LLM tools
  and `sajha_ask`, on every instance passed); the host runs the tool with that chain, so a call its tool
  makes onward continues the hop count and visited list (protocol §16), and hops plus depth may not exceed
  `sajhanet.max_call_chain` (default 8, at most 32). The home refuses before sending (`-32016`, `loop`
  when the host is already in the visited list, `hop_limit`, `chain_limit` with `hops`, `depth` and
  `limit`), the host refuses on receipt (`chain_limit`), and a tool entered inside a forwarded call past
  the budget is refused with the key named. `ai.llm_tools.max_depth` and `tools.max_call_depth` stay
  per instance; the combined budget is what bounds a chain end to end.
- **Built of section 12: residency** (wave 5, phase 5.1; `sajha/net/residency.py` in the core, and in
  SAJHA `sajha/net/integration/residency.py`, the residency conditions of `sajha/policy/model.py` and
  `PolicyEngine.residency`; tests in `tests/net/test_net_residency.py`). **Data classes** come from
  `x-sajha-data-class` marks on `inputSchema` and `outputSchema` properties (nested objects and array items
  too; the marks are part of the contract hash), a tool's own `data_classes: {arguments, results}` (the
  whole tool), and `sajhanet.data_classes.tools` (classification by configuration, by tool name or glob,
  without editing the tool). Each exported tool carries the summary in its net metadata
  (`data_classes.arguments`, `data_classes.results`); at a home, a class in that summary with no field mark
  in the schema counts for the whole value. **Residency rules** are policy rules with the new conditions
  `data_classes`, `flow` (`arguments` or `results`) and `destination` (`net`, `instance`, `region`,
  `labels.<key>`, `here`, `differs_from_here`), evaluated deny-overrides among residency rules only
  ([Policy and Audit](Policy%20and%20Audit.md) 3.5); `sajhanet.residency.default_effect: deny` makes
  classified data need an `allow` rule. **Arguments** (step 4): before a call leaves, the home checks the
  classes of the fields present against the host's region and labels from its member record; a deny is
  `-32012 residency_arguments` with `executed: false`, and the words tell a planner to use a tool where
  the data may go; a call by plain name then moves to the next host (a home residency refusal is not that
  host's answer, unlike every other refusal); `redact: {data_classes: [...]}` sends the call with those
  fields replaced by `[REDACTED:<class>]` instead. **Results** (step 14, the protocol's §15.4 step 12):
  the host checks the classes of the fields present in its result against the home's region and labels;
  a deny is `-32012 residency_result` with `executed: true`; a redaction replaces the fields in
  `structuredContent`, in JSON text blocks and wherever a removed value is quoted in text, and lists them
  in `_meta["io.sajha/net"].redacted`; the answer carries `data_classes.results` (the classes it still
  holds). A class marked for the whole result cannot be redacted field by field and is refused. **As
  results arrive** the home applies its own residency rules (`flow: results`, `destination: {here:
  true}`): it may redact or refuse (`residency_result`, side `home`); a check that fails withholds the
  result. **Residency-aware shortlists:** a remote tool whose host may not receive the classes every call
  sends (whole-tool argument classes and those of required fields) is not eligible there
  (`not_eligible: residency rule` in the resolution order and on the Remote tools page); the plain name
  resolves to the hosts that may, and a tool no host may receive is left out of `tools/list` and of Ask
  SAJHA's shortlist for that caller. **Audit:** every decision on classified data (allowed, redacted,
  refused, on either side and on arrival) is one `net.residency` record with net, other instance, tool,
  flow, classes, rule, side, the redacted field paths and the trace id (never values); counted in
  `sajha_net_residency_decisions_total{flow, outcome}`. **Memory:** an answer that used remote results is
  kept as written, with every figure replaced by `[remote figure]`, or as a placeholder, by the classes of
  those results (`sajhanet.memory.remote_results`, and `sajhanet.memory.by_class` per class, where the
  strictest wins; the design put the per-class choice in rules, the build keeps it in configuration
  beside the default). RAG collections are built from documents only; no tool result enters them. The
  extension advertises the feature `residency`. **Console:** data classes on the Tools page's net badges
  and in a column of the Remote tools page. Not built: memory handling for LLM tools that record their own
  turns (they pass an answer without its steps; `ConversationMemory.record` accepts `steps=` for them), and an approval flow for residency (`require_approval` on
  a residency rule refuses).
- **Built of sections 10.2, 14 and 17: re-export, bridges, the `assertion` and `token_exchange`
  resolvers, topology data** (wave 5, phase 5.2; `sajha/net/integration/identity.py`, the re-export part of
  `sajha/net/integration/catalogs.py`, `CatalogBook.reexports` in `sajha/net/catalog.py` and the relay and
  path counting in `sajha/net/routing.py`; tests in `tests/net/test_net_reexport_identity.py`).
  **Identity resolvers per net:** `user_identity` (a net entry's, else `sajhanet.user_identity`) names one
  resolver or several; as a home this server sends the first that the host's member record also lists,
  as a host it accepts every one listed (and advertises them). `assertion`: the home signs a user
  assertion with its net certificate (`user` from its own key record, `key_id` of the key the caller
  presented, else the user's default key, else their newest usable key; never a per-member key or the test
  admin key, which stay features of `api_key`, whose order is unchanged), at most 60 seconds
  (`sajhanet.assertion.ttl_seconds`, default 30), with the call's trace id; the host checks schema, net,
  issuer (the sender on hop 1, else an instance on the chain), signature against the issuer's certificate,
  audience, time, one use of `jti` (in the state store) and trace id, then the key record and, as for keys,
  the block on the user and the mapping of section 11.3. `token_exchange` (between participants, not
  through a shared identity provider as first sketched): the home exchanges an assertion at the host's
  `POST /sajhanet/v1/token` (feature `token_exchange`) for an opaque token bound to the net and the home,
  kept hashed in the host's state store for `sajhanet.token_exchange.ttl_seconds` (default 300), cached at
  the home per host and key (per process) until ten seconds before it expires, and sent in
  `Sajha-Net-User-Token`; the host re-checks the key record, the block and the mapping on every call, and a
  `token_invalid` refusal makes the home exchange again and retry once. Remote users the host saw record
  the resolver (`identity` in the users view), the host's `net.host_call` audit records the identity,
  mapping, hops and visited list, the home's `net.call_attempt` the identity sent, and the host's
  `net.token_issued` each token issued (never the token). **Re-export** (section 14): off by default; with
  `reexport` on for the net offered into (advertised as the feature `reexport`) an imported tool goes
  onward only when a re-export rule names it (`reexport_rules`: `tools`, `from_nets`, `from_instances`,
  `to_instances`, `for_roles`). Within one net it carries `origin` and the host's contract unchanged (same
  contract hash, so one name, one contract holds); a tool is never offered back to its host or origin,
  never under a local tool's name, and an instance never imports a tool whose origin is itself. A home ranks
  direct offers before re-exported ones (the reason says "re-exported by ... from ..."), sends an assertion
  with `aud` = origin (never a key), and refuses to send a chain back to the host or origin it passed
  (`loop`). The intermediary verifies that assertion with the origin as audience, maps and authorizes the
  caller (blocks, mapping, re-export rules in place of export rules with the key's tool access as a
  ceiling, its own access to the tool or its proxy), then relays the assertion unchanged with hop + 1 and
  the visited list, through its own router: residency on arguments, results and arrival, the hop limit and
  the combined chain budget apply on each step, and a downstream refusal that did not execute is returned
  as the intermediary's refusal with `refused_by`. **Bridges:** with re-export on for a net N, a tool
  imported in another net M is offered in N as this server's own (no origin); a call from N runs as the
  local account the caller maps to, which calls into M with an assertion this server signs there (a guest
  mapping cannot cross a bridge), hops and visited list continuing. Every instance on a chain must accept
  the extra hop (`max_hops` 2 for one intermediary; default 1). **Topology data:**
  `GET /api/sajhanet/topology` ([API Reference](../protocol/API%20Reference.md#424-sajha-net-sajhanet_routespy)):
  per net the instances and the `offers`, `reexports` and `calls` edges this server knows; observed call
  paths are counted per process since start, like metrics. The console draws it (section 17).
- **Conformance** (protocol §20, the ids whose targets include S). Covered by tests under `tests/net/`
  (and `tests/test_sajhanet_groundwork.py` for CAP-01 to CAP-03): NAME-01 to NAME-11; NET-01 to NET-04
  and NET-06; CAP-01 to CAP-05; SIG-01 to SIG-15; REC-01, REC-02; GOS-01 to GOS-14; CAT-01 to CAT-04 and
  CAT-06 to CAT-08; CON-01 to CON-06; KEY-01 to KEY-05; BLK-01; REV-01; CA-01 to CA-03; CALL-01 to
  CALL-05, CALL-07 (`tests/net/test_net_residency.py`, which also covers FB-01's `residency_result`) and
  CALL-08 to CALL-10; NET-05, CALL-13, CALL-14 and CALL-15 (`tests/net/test_net_reexport_identity.py`);
  FB-01 to FB-06; ERR-01; LIM-01. Remaining: CAT-05 (the `visibility` feature is not built); CALL-11 and FB-07 (progress, cancellation, input requests and tasks are not
  relayed on forwarded calls); CALL-12 (forwarded calls use the 2026-07-28 era only, so there is no
  2025-11-25 session to share); CALL-06 is covered step by step across the files (each refusal, its code
  and `executed`) but not yet by one test that walks every step of §15.4 in order. The same ids are reported by the
  conformance suite runner (phase 5.3, below), which also runs the remote cases against an agent (target A)
  and a sponsored participant, and the library cases (target L).
- **Built of section 5.1: other MCP servers** (wave 5, phase 5.3). **Sponsored servers**
  (`sajha/net/integration/sponsored.py`): an entry of `sajhanet.sponsored` (or one added with
  `POST /api/sajhanet/sponsored`) names a net, an instance name and a federation upstream; the sponsor runs a
  node for it (kind `sponsored`, its member record and extension object carrying `sponsor`, the sponsor's
  name in the net, an optional field of protocol §9.1) on the sponsor's own URL, reached by `Sajha-Net-To`
  (`Participant` selects a sponsored node by it), seeded by the sponsor and ticked with the sponsor's gossip
  agent. Its key and certificate are the sponsor's to hold (`<data_dir>/<net>/sponsored/<name>/`):
  self-signed in an `open` or `manual` net, issued by the sponsor when it is the CA participant, else
  enrolled with a token (`POST /api/sajhanet/sponsored/{net}/{instance}/enroll`). Its catalog is the
  upstream's federated tools under the server's own names (filtered by `tools` globs) with the sponsor's
  data classes; a forwarded call runs the sponsor's checks as for its own tools (its identity resolvers with
  the sponsored participant as audience, `api_key` only; blocks; export rules under the tool's local
  registry name; the local account's access, policy and approvals; residency on the result; audit) and then
  federation's connection to the server. It imports nothing. The sponsor's other members pull its catalog
  and call it like any member; the sponsor's own users reach it through their proxies, by a signed call to
  the sponsor's own URL. Shown in the members of `GET /api/sajhanet/status`, the Instances data (kind and
  `sponsor`), the topology nodes and the Net overview data (`sponsored`). **The reference library**
  (`sajha/net/library.py`): `NetParticipant` assembles node, catalog book, host endpoint and (with key
  verification) the key directory from the core, with identity files, self-signed or CA-enrolled identities
  (`enroll`), an export policy (`ExportPolicy`) and the `api_key` resolver of a host without accounts
  (`KeyDirectoryIdentity`: the user is the key's owner at home, with the key's tool access as a ceiling).
  **The SAJHA Net agent** (`sajhanet_agent/`, `python -m sajhanet_agent`): the library in front of an MCP
  server over stdio or Streamable HTTP, served by the standard library's HTTP server (TLS optional), with the
  server's `tools/list` as its catalog and `tools/list_changed` honoured; it is never a home and publishes no
  keys. It imports nothing from SAJHA outside `sajha.net` (`tests/test_sajhanet_agent_boundary.py`; importing
  `sajha` no longer loads the server, as the package names its exports lazily). Its guide is
  [SAJHA Net Agent](../clients/SAJHA%20Net%20Agent.md). **The conformance suite** (`sajha/net/conformance/`,
  `python -m sajha.net.conformance --target <url>|library`): every id of protocol §20 with its targets; the
  remote cases run against a participant over HTTP as a participant that never joins (signed, tampered and
  oversized requests to `/sajhanet/v1/` and the signed MCP endpoint), the library cases against the core with
  the §21 vectors, and the cases that need a target's insides are reported `skip` naming the test file that
  covers them. The wave exit is `tests/net/test_net_mixed_conformance.py`: a SAJHA instance, a server it
  sponsors and an agent-fronted server in one net, a user's calls to the latter two with her own key, and the
  suite on all three targets and the library with no case failing. A SAJHA instance's signed `initialize`
  now carries the net's extension object under `capabilities.experimental` (CAP-02) also for nets built in
  code.
- **Built of section 17 in phase 5.2:** the Net overview with the topology map, the Your net access
  page, and the admission panel and runtime seeds on the admin page (section 17.5).
- **Not yet:** the other console pages of section 17.1 (instance detail, conflicts and reviews as their
  own page, users, access and blocks as a matrix, key directory, snapshots, live activity, certificates
  and net settings as pages of their own; certificates and settings are panels of the admin page) and mutual
  TLS (`mtls` stays off); for other MCP servers: an agent that is also a home (calls other members' tools),
  sponsored participants with the `assertion` or `token_exchange` identity, and console pages for
  sponsoring (the admin API and the data views carry it).
- **Built in phase 5.4:** vendors and external servers (section 5.6): `vendor` in the member record and
  every view; external servers (`sajhanet.external_servers`) offered by their defining instance as
  `<vendor>__<tool>`; published names with the host mapping calls back to its local tool (the core does
  it in `CatalogBook`, `sajha/net/catalog.py`, for every kind of participant); rules and blocks under
  either name; `rename`; the length refusal; and how a node recognises itself (section 6.1).

### 5.6 Vendors and external servers

**The problem.** One name, one contract (section 8.7) is the right rule inside one organisation: a
`var_calc` is a `var_calc` everywhere. Servers from unrelated organisations break it by accident. A
search server from acme and one from globex both offer `search`, `fetch` or `read_file`, with
different schemas, and the net would quarantine the name everywhere although nobody did anything wrong.

**The design** (owner decisions, 2026-10-07):

- **Every member names its vendor.** The vendor is the organisation that owns and answers for a
  participant's tools (`sajha`, `acme`). Its syntax is that of a safe federation prefix, lowercase: a
  lowercase letter, then lowercase letters, digits and `_`, at most 24 characters, never `__` and not
  ending with `_`. A SAJHA instance takes `sajhanet.vendor` (default `sajha`; a net entry may override
  it), a sponsored entry `vendor` (required), the agent `--vendor` (required). It is in the member
  record and shown on the Instances, Remote tools and Net overview pages, in `GET /api/sajhanet/status`
  and in the topology data. There is no vendor registry: the name is a claim, and the contract rule
  below keeps it honest.
- **An external server is not a member.** It is a proxied MCP server (one a SAJHA instance embeds
  and proxies calls to, through federation) marked external: an entry of the
  [mcpServers file](Federation.md#the-mcpservers-file) (external by default there), or an upstream
  listed in `sajhanet.external_servers` with its vendor. It has no member record, no instance name and
  no certificate; it never gossips, is never probed and never appears on the Instances page. The SAJHA
  instance that defines it is its **proxy**: the tools of an external server appear as the hosting
  instance's own tools, published as `<prefix>__<tool>` (the prefix defaults to the vendor), so the
  qualified name is `<net>__<defining instance>__<prefix>__<tool>` (`acme-net__risk-eu__acme__search`)
  and the plain name `acme__search`. No other tool name may contain `__`: it is reserved for namespaced
  tools (federated and external servers' tools, and SAJHA Net's remote tools), and the tools registry
  refuses any other tool that uses it ([Federation](Federation.md#names)). A prefix is unique on an
  instance, across federation upstreams and external servers, and never a local tool's name. Its
  endpoint and credentials never leave the defining instance; calls go to
  the defining instance, which runs them with its full governance (export rules, access, policy,
  approvals, residency, audit) and then calls the upstream through federation by the upstream's own
  name. The catalog entry says `vendor` and `external: true` in `_meta["io.sajha/net"]`, so every member
  shows "external (via risk-eu)" next to the tool.
- **Internal servers are unchanged.** Every member (a SAJHA instance, an agent-fronted server, a
  sponsored server) is internal: its tools keep their names and one name, one contract applies to them
  as before. A SAJHA instance is always a member; to offer another SAJHA's tools under a vendor prefix,
  define it as an external server (a federation upstream on its `/mcp`). A sponsored entry with
  `external: true` and the agent's `--external` are refused with a message pointing here, because a
  sponsored or agent-fronted server is a member by definition.
- **Rules accept either name.** At the defining instance, export rules and tool blocks match the
  published name (`acme__search`) or the local (registry) name of the federation tool (a block on
  either blocks the tool); access (roles and a key's tool list) is checked under the local name and
  also accepts the published name; policy and approvals see the local tool, which is what runs. Homes
  name the tool by its published (qualified) name in import rules, preferences and blocks. The host's
  `net.host_call` audit record has `tool` (the published name) and `local_tool`.
- **One name, one contract applies to the published name.** Two SAJHA instances that both define
  acme's server and offer the identical `acme__search` are one fallback set for the plain name
  (resolution and waterfall as in sections 8.2 and 9.1). Different vendors never meet on a name. Two
  instances claiming one vendor with different contracts are the loud quarantine of section 8.7, naming
  the differing defining host.
- **Deliberate short names.** `rename` (`{tool: published name}`) on an external server entry offers a
  tool under a name the operator chooses instead of the prefix; `sajhanet.rename` (or a net entry's
  `rename`) does the same for a member's own tools, a sponsored entry has `rename`, the agent
  `--rename local=published`. Such a name falls under the same rule: two hosts both choosing `find`
  with different contracts quarantine `find`.
- **Length.** A qualified name is at most 128 characters (protocol §5.3). A host whose published name
  would make it longer does not offer that tool: it logs a warning, raises a warning notice
  (`sajhanet.name:<net>:<tool>`) and an audit record (`tool_name_refused`) naming the tool, its published
  name and the room it has, and suggests `rename`; the Net overview and the agent's status list it under
  `refused_tools`. There is no automatic shortening: a truncated or hashed name would be unreadable to
  people and models and could collide, so the operator chooses the short name. The same check refuses a
  published name that is not a valid tool name or that two tools would share.
- **Re-export keeps the published name.** An intermediary re-exports `acme__search` as `acme__search`,
  with its `vendor` and `external` metadata, never adding a prefix of its own, so the contract is
  compared under one name everywhere.
- **Proxies all the way down.** A proxied server may itself proxy others (another SAJHA with its own
  proxied servers, or any MCP gateway), so the arrangement nests without limit, and every level applies
  its own governance (export rules, access, policy, approvals, residency, audit). Names compose: an
  external server's tool that is already prefixed comes through as `<outer prefix>__<inner prefix>__<tool>`
  and in a net as `<net>__<instance>__<outer>__<inner>__<tool>`, which still splits at the first two
  `__`. Each level is bounded by the 128-character name cap (the length rule above refuses a tool rather
  than shortening it; models see short per-request aliases, section 8.6) and by the call-chain budget
  that federation carries between SAJHA instances, so a cycle of proxies is refused at the limit
  ([Federation](Federation.md#proxies-all-the-way-down)).
- **Caution.** Choose a vendor that is not also the name of a net this server is in: a plain name such
  as `acme__files__read` would otherwise read as a qualified name in net `acme`.

Example: one SAJHA instance offers two vendors' `search` tools without either becoming a member. With
the mcpServers file (`config/mcp_servers.json`; templates in
[`config/mcp_servers/`](../../config/mcp_servers/README.md)) every entry is external unless it says
`"external": false`:

```json
{"mcpServers": {
  "acme":   {"url": "https://search.acme.example/mcp"},
  "globex": {"url": "https://mcp.globex.example/mcp", "tools": ["search", "fetch_*"]}
}}
```

The same in `application.yml`, with upstreams defined there:

```yaml
federation:
  upstreams:
    - {id: acme, url: "https://search.acme.example/mcp"}
    - {id: glx, url: "https://mcp.globex.example/mcp"}
sajhanet:
  vendor: sajha
  external_servers:
    - {upstream: acme, vendor: acme}
    - {upstream: glx, vendor: globex, tools: ["search", "fetch_*"], rename: {fetch_document: globex_fetch}}
```

`sajhanet.external_servers` entries take `upstream`, `vendor` (required), `prefix` (default the vendor),
`tools` (globs of the upstream's tool names offered, default all), `rename` and `nets` (default every
net). An upstream listed both there and in the mcpServers file uses the `sajhanet.external_servers`
entry.

Every member then lists `acme__search`, `globex__search` and `globex_fetch` (all hosted by this
instance), and nothing is quarantined. Without the `external_servers` entries the federation tools stay
local to this instance (federated tools are never exported into a net on their own), and sponsoring the
two servers instead would make them members offering `search` each, which the net quarantines.

The rules are normative in the [protocol spec](../protocol/SAJHA%20Net%20Protocol.md#55-vendors-and-published-tool-names);
the tests are `tests/net/test_net_vendors.py`.

---

## 6. Membership

Instances find each other, notice when one arrives or leaves, and agree on who is in the net
through a **gossip protocol**. No administrator has to add each peer by hand, and no central
server is needed.

### 6.1 Nets and instance identity

- **Named nets, several per server.** Every net has a **net name** (`acme-net`): lowercase letters,
  digits, `-` and `_`, starting with a letter, at most 16 characters, never containing `__` and not
  ending in `_` (the exact rule is in the [protocol spec](../protocol/SAJHA%20Net%20Protocol.md#51-net-names)).
  A server may be a member of **more than one net** at once, listed in `sajhanet.nets` (section 19);
  the order of that list is the server's order of preference between its nets (section 8.2). A net
  entry without a name is the net named **`default`**, and the console suggests naming nets in
  production.
- **Each net is fully separate.** Each has its own CA and its own certificate for every member, its
  own membership and gossip, key directory, blocks, export and import rules and trust levels. Nothing
  learned in one net (a member, a key record, a block, a catalog) is ever used in another, even when
  the same servers belong to both. Being in two nets never bridges them: a server never offers one
  net's imported tools to another net unless that net's `reexport` is explicitly on (section 14).
- **Instance names are per net.** In each net an instance is identified by its **instance name**,
  set in its own configuration (`instance_name` in that net's entry, for example `risk-eu` or
  `cust-na`) and unique in that net; a server may use a different name in each of its nets. The
  instance name is what gossip, the console, audit records, user identities (`alice@risk-eu`) and
  qualified tool names (`acme-net__risk-eu__var_calc`) use. An instance also has a base URL, a region
  and labels (`domain: risk`, `jurisdiction: EU`).
- **Names never collide.** Within a net, an instance name identifies exactly one server: the one
  whose certificate key first held it in that net (the rules below apply to each net separately). The name stays reserved for that key, running or not,
  until an administrator revokes its certificate. The CA refuses to create an enrollment token for
  a name that is held, and tells the administrator who holds it. A server that tries to join under
  a held name with a different key is refused by every instance it contacts (`name_conflict`,
  naming the holder): it does not join, it logs the error, raises an error notice (section 17.4)
  and an alert metric, and it stops retrying until its configuration or certificate
  changes. Its local tools keep working. A restart, or a certificate renewal by the CA (even with a new key pair), is the same holder
  and not a conflict: ownership follows the certificate's renewal lineage.
  The rule is normative in the [protocol spec](../protocol/SAJHA%20Net%20Protocol.md#52-instance-names).
- **When no name is configured, the address is the name.** An instance without an `instance_name`
  for a net is named, in that net, after the address other instances reach it on, as
  `<ip>:<port>` (for example `10.20.4.17:3002`; IPv6 as `[2001:db8::7]:3002`). The address must be
  real and reachable:
  - it is that net's `advertise_address` if set (needed behind NAT or a container network, where
    the address the server sees is not the one peers use);
  - otherwise the server's bind address, if that is a specific address;
  - otherwise, when bound to all interfaces, the address of the interface that carries the
    default route.

  Never `0.0.0.0`, `::`, a loopback address (`127.0.0.0/8`, `::1`), `localhost`, or a link-local
  address (`169.254.0.0/16`, `fe80::/10`). If no acceptable address is found, the instance does not
  join and says why at start-up and on its SAJHA Net settings page; local tools keep working.
- **Where an address name cannot be used as is.** MCP allows letters, digits, `_`, `-` and `.` in
  tool names (`[A-Za-z0-9_.-]{1,128}`, `sajha/federation/config.py`), but only letters, digits,
  `_` and `-` are accepted by every LLM provider, so the instance part of qualified tool names uses a
  safe form of the address: dots and colons become `_` (owner decision), so `10.20.4.17:3002` gives
  `acme-net__10_20_4_17_3002__var_calc`. An IPv6 address is first written out in full, without `::`
  shortening and without brackets, so the safe form never contains `__`, which separates the parts
  (`[2001:db8::7]:3002` gives `acme-net__2001_0db8_0000_0000_0000_0000_0000_0007_3002__var_calc`).
  Because the net name comes first, every qualified name starts with a letter, as some providers
  require. Long names are not a problem for providers with a length cap either: SAJHA maps them to
  short aliases when it sends tools to a model (section 8.6). Everywhere else (the console, gossip,
  audit, `alice@10.20.4.17:3002`) the address is shown as written.
- **Prefer a configured name in production.** An address name changes when the address does
  (DHCP, a restart that moves a container or Kubernetes pod), and with it every qualified tool
  name, user link, block and preference entry that refers to the instance, and its certificate (which
  names the instance) must be issued again. The console warns when an instance runs under an
  address name. An instance with several pods or workers is one instance and needs a configured
  name and an `advertise_address` (its Service), since each pod's own address would name a
  different instance. The Helm chart's `sajhanet` values set the nets list, each net's instance
  name and advertise address, and the Secrets that hold its certificate and keys, and the chart
  refuses to render several pods with a net that lacks either
  ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md#sajha-net)).
- **Admission is by certificate.** Each net has its own certificate authority. In each of its
  nets an instance holds a certificate signed by that net's CA whose subject names the net and the
  instance name there (and preferably a separate key pair per net), so an instance cannot claim a
  name, or a net, it was not issued. Every request between instances is **signed** with the sender's private key and carries its
  certificate (section 6.7), and an instance accepts a peer's request only if the certificate chains
  to that net's CA, names the net the request is for (the signed `Sajha-Net-Name` header, section
  6.7), matches the signature, and is not on that net's revocation list. Holding such a certificate is what makes a server an instance: there is no
  separate approval step, which is how instances can come and go automatically.
- **Revocation.** A net administrator removes an instance by adding its instance name (or certificate
  serial) to the revocation list, which is signed with the SAJHA Net CA's key and spread by gossip
  (section 6.3). Every instance checks it on every request.
- **Rotation.** Instance certificates are short-lived (default 30 days) and renewed before
  expiry; old and new are both accepted during an overlap window.
- **How addresses are advertised.** A participant's address is the `url` in its own signed member
  record (its `base_url`, or the address name built from its `advertise_address`), never an address a
  peer observed a request coming from: behind NAT, a proxy, a container network or a server bound to
  `0.0.0.0` the observed source says nothing reliable about identity, so it is used, at most, in debug
  diagnostics. A sponsored participant shares its sponsor's URL by design (requests reach it by
  `Sajha-Net-To`); an external server (section 5.6) has no record at all, so its real endpoint is never
  gossiped and stays with the instance that defines it.
- **How a server recognises itself** (`sajha/net/node.py`, protocol §9.4). Besides a record under its
  own name (which it refutes or ignores as before), a node treats as **itself**, never as a remote
  member: a record signed with its own key under another name (a renamed copy of itself), and a record
  whose `url` is its own address (its `base_url` or `advertise_address`; scheme and host compared in
  lower case, default ports dropped, no trailing `/`) under another name and key. Either raises a
  warning notice (`sajhanet.self_seen:<net>`) naming the name and URL seen, and an audit record
  (`self_seen`). The exception is a sponsored participant: a `sponsored` record whose `sponsor` is
  this server (and, at a sponsored node, its sponsor and the sponsor's other sponsored participants)
  shares the URL by design and is an ordinary member. A seed, runtime seed or saved peer at the node's
  own address is skipped, so a server never tries to join through itself.

### 6.2 Coming in and going out

| Event | What happens |
|---|---|
| An instance starts | It contacts its configured **seed instances** for that net (one or two are enough; with none it is a net of one, section 6.6), presents its certificate, and receives the current instance list. Its arrival spreads to everyone within a few gossip rounds; each instance then pulls its catalog and key directory (sections 7 and 10.3). |
| An instance stops cleanly | It gossips a `leave` message. Others mark it `left` and remove its tools at once (section 8.5). |
| An instance crashes or is cut off | The failure detector (section 6.3) marks it `suspect`: its tools stay listed but marked unavailable, and calls skip it. If no one can reach it within `suspect_timeout_seconds` it becomes `dead`, and its tools are removed at that moment (section 8.5). |
| An instance comes back | It rejoins with a higher **incarnation** number, which overrides any stale `suspect` or `dead` entry about it. Its tools are listed again once its catalog has been pulled anew. |
| An instance is revoked | Its instance name (or certificate serial) is on the signed revocation list; every instance refuses it and removes its tools, wherever the list reaches first. |

All of this happens in each net separately: a server leaving one net (its configuration no longer
lists it) stays in its others.

A server whose certificate is not from the SAJHA Net CA cannot join, gossip or call anyone, however
it learned the addresses.

### 6.3 The gossip protocol

The protocol follows the SWIM design (scalable, weakly consistent, infection-style membership),
which needs no leader and costs a few small messages per instance per second. At about ten
instances it is far more than enough.

- **Membership list.** For each of its nets, each instance keeps an entry per instance: id, URL, region, labels,
  `incarnation`, state (`alive`, `suspect`, `dead`, `left`) and digests (catalog hash, key
  directory version). Entries merge by (incarnation, state precedence), so every instance
  converges on the same list without coordination.
- **Failure detection.** Every `gossip_interval_ms` an instance pings one other instance chosen at
  random. If there is no answer within `ping_timeout_ms`, it asks `indirect_probes` other instances
  to ping it on its behalf (so one broken link does not condemn a healthy instance). No answer at
  all makes it `suspect`; a suspect that does not refute (by gossiping a higher incarnation)
  within `suspect_timeout_seconds` becomes `dead`.
- **Dissemination.** Changes (joins, leaves, suspicions, new digests, revocations) ride on the
  ping messages, each change repeated a bounded number of times (about `3 × log2(n)`), so news
  reaches every instance in a few rounds.
- **Anti-entropy.** Every `full_sync_interval_seconds` an instance exchanges its whole membership
  list and digests with one random instance, which repairs anything a lost message missed.
- **Transport.** Gossip messages are small HTTP POSTs on SAJHA's normal port, signed like every
  other request between instances (section 6.7). There is no other port, no UDP and no separate
  listener, so gossip passes through Kubernetes services, ingress and corporate proxies unchanged.
- **Digests trigger pulls.** Gossip carries only digests. When an instance sees a peer's catalog
  hash or key-directory version change, it pulls the changed part from that peer (sections 7.2 and 10.3). Gossip never carries tools, schemas or keys themselves.
- **One gossip agent per net.** An instance runs one gossip agent for each of its nets. With several
  workers it elects one of them to run each agent, through a lease per net in the state store: the worker that stores the lease key with the
  state store's atomic `add` and a TTL holds it (the primitive workflow cron and quality probes use
  to claim a slot, `sajha/workflows/service.py`, `sajha/quality/probes.py`), and renews it with
  an atomic `update` that succeeds only while the value is still its own. The renewing lease is
  new code on existing primitives; cron and probes claim one slot at a time and never renew. The
  membership list is kept in the state store so every worker sees the same net. If the agent's
  worker dies, its lease expires and another worker takes it. With `state.backend: memory` each
  process has its own store, so an instance with several workers needs `redis` or `database`.
- **No split-brain hazard.** Instances never need to agree on anything beyond membership: each
  call is point to point and authorized by the host. Two instances that briefly see different
  lists only disagree about which proxies to show.

### 6.4 The SAJHA Net CA, run by SAJHA

The certificate authority is part of SAJHA; no external PKI is needed.

- **One CA instance per net.** An administrator designates one instance as the net's CA instance
  (`ca.enabled: true` in that net's entry, on that instance only) and initialises it once
  (`sajha net ca init --net acme-net`), which creates the net's CA key pair. A net of one (no seeds)
  does this by itself at first start unless `ca.auto_init` is false. One server may be the CA
  instance of several nets, with a separate CA key for each. The private key is a secret reference
  (the net's `ca.key_ref`), stored with owner-only permissions and never sent anywhere; the
  administrator is prompted to back it up.
- **Enrolling an instance.** On the CA instance, an administrator creates an **enrollment token**
  for a named instance (`sajha net ca enroll cust-na`, or the console): one-time, short-lived,
  bound to that instance name. The new instance starts with the token and the CA's public
  certificate, generates its own key pair, and sends a certificate request with the token to the
  CA instance; the CA instance checks the token and issues a certificate naming `cust-na`. The new
  instance's private key never leaves it.
- **Renewal.** Each instance renews its own certificate before expiry by sending a request signed
  with its current, still-valid certificate; no token is needed. Renewal failures are shown in the
  console well before expiry.
- **Revocation.** `sajha net ca revoke <instance>` (or the console) adds the instance to the
  revocation list, which the CA instance signs and gossip spreads within seconds.
- **The CA instance is not a single point of failure for running the net.** If it is down,
  every instance keeps working with its current certificate; only new enrollments and renewals
  wait. Its key can be restored from backup onto another instance, which then becomes the CA
  instance.
- **Console.** On the CA instance, the SAJHA Net area has a **Certificates** page: issued
  certificates with instance, serial, expiry and state; pending enrollment tokens; the revocation
  list; actions to enroll, revoke and re-issue.

### 6.5 Manual mode

Where an administrator prefers not to run a CA, peers can still be added by hand with a one-time
join offer approved on both sides. Gossip then runs among the approved peers only. As built, the approval
is a pinned certificate thumbprint on each side (`identity.pins`, or `sajha net pin`), and every
other rule is the CA mode's (protocol §8.11).

### 6.6 Restarts

An instance that is shut down and started again finds its peers without anyone's help. In each of
its nets, separately, it tries in this order:

1. **Seeds.** The net's configured `seeds`, the pre-identified peers it connects to first and
   starts gossiping with. **A net entry with no seeds is a net of one** (owner decision): this
   server is that net's founder and only member. With no saved peer and no discovery result either,
   it joins at once alone: no "not joined" notice, no join retries and no gossip traffic, since there
   is nobody to talk to. It accepts a peer later without a restart: an instance that enrolls with
   its CA and joins with this server as its seed, or a peer an administrator adds by address. Until
   it holds a certificate it is not networked. By default it creates its own CA at first start
   (`sajhanet.ca_auto_init`, owner decision; audited, with a warning notice to back up the CA key), so
   peers can enroll at once; with `ca.auto_init: false` an administrator runs `sajha net ca init` (which
   a net of one may run without `ca.enabled`) or enrolls with another net's CA, and an info notice says
   how. `founder: true` is for the first server that also lists seeds: when they are
   all down it starts alone instead of retrying. Malformed seeds are still refused.
2. **Saved peers.** If no seed answers, the peers in its last saved peer list for that net, most
   recently seen first. Each server saves the peers it knows, per net, to **local disk**: on every
   membership change and at least every `peer_cache.interval_minutes` (default 10), to
   `peer_cache.path` (default `data/sajhanet/<net>/peers.json`), written atomically (a temporary file,
   then a rename) with owner-only permissions. For each peer it records the name, URL(s),
   certificate thumbprint, last state and last-seen time, plus the time of the save. It is kept on
   local disk, not only in the storage backend, so it is there even when the storage backend is
   remote or unavailable. An entry is only an address to try: the peer's certificate is verified on
   contact as always, and entries not seen for more than `peer_cache.max_age_days` (default 7) are
   skipped.
3. **Discovery plug-in, if configured.** For example DNS records of a Kubernetes service (section
   5.3).
4. **Peers look for it too.** An instance marked `dead` stays on every peer's list for
   `sajhanet.gossip.dead_retention_minutes`, during which peers probe its last address at a low
   rate (`dead_probe_interval_seconds`). A restarted instance whose seeds and saved peers were all
   down is still found as soon as any peer can reach it.

If the net has seeds and neither they nor saved peers answer, the server raises an error notice
("not joined to `<net>`: no seed or saved peer reachable", section 17.4) and keeps retrying with
back-off (a founder starts alone instead).

**Adding a peer by hand.** An administrator signed in to this instance can also point it at a peer
for one net, by IP and port or URL (Net settings or the admin view of Instances, the admin API, or
`sajha net peers add <ip:port> --net <name>`). The server contacts that address at once for that
net with an ordinary signed join (a sync). The address is only a hint: the peer's certificate must
still chain to that net's CA, name a valid instance name that conflicts with no holder, and not be
revoked (in manual mode the administrator confirms the certificate thumbprint shown before it is
pinned); injection never bypasses admission, `name_conflict` or the contract rule. The address must
pass the net's network allowlist and SSRF rules (no loopback or link-local, `allowed_networks`), and
injections are rate-limited.

- **On success** the peer enters membership through gossip as usual and is written to the saved
  peer list. An optional **keep as a seed** stores it as a runtime seed for that net in the storage
  backend; configured seeds stay as configured, and runtime seeds are listed separately in the
  console with who added them, and can be removed.
- **On failure** the console says why (unreachable, TLS, signature, wrong net, revoked,
  `name_conflict`) and nothing is stored.
- It is never possible through a remote call. Every injection, successful or not, is audited and
  raises a notice (info on success, warning on failure).

The first peer that answers sends the full membership list; within a few gossip rounds every
instance knows it is back.

- **Its return overrides the news of its death.** It rejoins with a higher incarnation, derived
  from its start time so that it is always higher after a restart even if the previous value was
  lost; that outranks any `suspect`, `dead` or `left` entry about it.
- **No remote tools until peers answer.** The key directory is in its database, so forwarded keys
  can be verified at once, and blocks, user links, trust levels and role maps are in the storage
  backend and apply from the first request. But it lists **no remote tools** until each peer's
  catalog actually arrives: a peer's tools appear when that peer has answered a catalog pull in this
  run. The last accepted catalog it stored is used only to ask "has it changed?" (so an unchanged
  catalog need not be transferred again), never to list or call a tool on its own (section 8.5).
- **Clean shutdown and crash end the same way.** A clean shutdown gossips `leave`, so peers remove
  its tools immediately; a crash is found by the failure detector, and peers remove its tools when it
  becomes `dead`. Either way the restart path above is the same.
- **Several workers.** The worker that wins the gossip lease (section 6.3) performs the rejoin;
  the others read the membership list from the state store as usual.

### 6.7 One port: how instances talk

Everything between instances uses SAJHA's normal HTTP port: the same server, the same listener,
the same port MCP clients and the web console use. There is no second port, no UDP and no other
TCP connection to open in a firewall. One port also serves every net the server belongs to.

- **One port, several nets.** The paths are the same for every net. Each request names its net in
  a signed `Sajha-Net-Name` header, and the receiver checks it with that net's CA, revocation list and
  rules only; a request for a net the receiver is not in gets the same plain `404` as a server with
  SAJHA Net off, so nobody learns which nets a server belongs to.
- **Paths.** Net traffic is ordinary HTTP under one path prefix, `/sajhanet/`: gossip
  messages, catalog and key-directory pulls, block and digest exchange, and CA enrollment and
  renewal. Calls to remote tools go to the host's normal MCP endpoint, with net headers added.
  These paths are refused unless SAJHA Net is enabled, and are never served to browsers.
- **Signed requests, not mutual TLS.** In most deployments TLS ends at an ingress, load balancer
  or nginx in front of SAJHA, so a peer's TLS client certificate would never reach SAJHA. Instead
  every request between instances carries an **HTTP Message Signature** (RFC 9421) made with the
  sender's private key, covering the method, path, the important headers, a content digest of the
  body (RFC 9530), a creation time and a nonce, plus the sender's net certificate in a header. The
  receiver checks the certificate against the net CA and the revocation list, checks the signature
  with the certificate's key, refuses requests older than `signature_max_age_seconds`, and keeps
  seen nonces in its state store for that window so a request cannot be replayed. This works the
  same whether TLS ends at SAJHA, at a proxy, or (in a lab) not at all.
- **Responses are signed too**, so an instance knows a catalog, key-directory record or tool result
  really came from the peer it asked, even through proxies.
- **TLS still protects the wire.** Signatures prove who sent a request; HTTPS keeps it private.
  Forwarded API keys (section 10.2) travel only over HTTPS hops (`require_https`, on by default);
  turning that off is for a lab only, and the server raises a warning notice while it is off (section
  17.4).
- **Mutual TLS remains an option** (`mtls: optional | required`, off by default because asking for
  client certificates can make browsers prompt console users) for deployments where SAJHA
  terminates TLS itself and wants the handshake check as well; it is never the only check.
- **Proxies need nothing special.** Because identity is inside the request, a proxy only has to
  pass headers through unchanged, which is the default for ingress controllers and nginx.

---

## 7. Catalog exchange

### 7.1 What a host instance exports

In each of its nets, for each tool that net's export rules allow a given peer to see, a host
instance publishes **everything about the tool**:

- its whole definition as its own MCP clients see it: name, title, description, `inputSchema`,
  `outputSchema`, annotations and metadata (`_meta`);
- its version (informational and for audit only, section 8.7) and, if versioned, its deprecation
  state;
- net metadata: net, host instance name, region, labels, data classes of its arguments and results
  (section 12), whether it is an LLM tool, an indicative latency, its health and its **contract
  hash** (of its schemas and annotations, section 8.7);
- a catalog hash, so a peer can tell whether anything changed.

Nothing else: no configuration, credentials, implementation details or usage data.

**MCP Apps views are not shared.** A tool's user-interface links (`_meta.ui`, `ui://` resources)
resolve only on the host, and the first protocol version does not proxy resource reads, so hosts
remove them from what they export and homes drop any that arrive. Federation already behaves this way
(it does not carry MCP Apps views); proxying them is a later protocol version.

### 7.2 How catalogs travel

- **Per net.** Catalogs are exchanged in each net separately, under that net's export rules.
- **Digest, then pull.** Every instance's catalog hash travels in gossip (section 6.3). When an
  instance sees a new hash for a peer (or a new peer), it pulls that peer's catalog over MCP
  (`tools/list`, with the net metadata in `_meta`) using its instance identity. An unchanged
  catalog is never transferred.
- **Fallback refresh.** Every `sajhanet.refresh_interval_seconds` an instance also re-pulls any peer
  whose catalog it has not checked in that time, in case a digest was missed.
- **Limits.** Catalog size, tool count per peer and description length are capped; a peer that
  exceeds them is flagged, and the excess is ignored.

### 7.3 Approval of imported tools

Descriptions and schemas from a peer are **untrusted text**: they are screened for injected
instructions (federation's screening), length-capped and checked for valid JSON Schema. Then,
according to the peer's trust level:

| Trust level | New tools from this peer |
|---|---|
| `auto` (default) | Become available at once if screening passes; a changed description or schema is applied at once too, and recorded in the audit log and on the SAJHA Net page |
| `review` | Wait on the SAJHA Net page for an administrator, as federation does today |
| `pinned` | Only tools an administrator listed by name are imported |

The owner's decision is that net instances are trusted, so `auto` is the default. Screening stays
on anyway: it is cheap, and it limits the damage if a trusted instance is ever compromised. Under
`review`, a tool whose description or schema changes after approval is held at its previous
approved version until reviewed. (Federation offers the same per upstream, `on_change: hold`,
and still withdraws such a tool by default, section 4.) Federation's screening covers descriptions,
titles and the text inside schemas (`sajha/federation/security.py`, `INJECTION_MARKERS`); the
JSON Schema validity check (`security.py::schema_problem`: a valid 2020-12 schema of type
`object`, else the tool is `invalid` with the reason in the approval queue) is federation's
too.

---

## 8. Proxy tools and the unified catalog

### 8.1 Automatic proxies

For every approved remote tool the home instance's import rules allow, in each of its nets, SAJHA
creates a **proxy tool** in its registry automatically: the remote schemas, the remote annotations
(corrected, never widened: a remote tool is at least `openWorldHint: true`; federation copies
annotations the same way, `security.py::correct_annotations`), and a net connection. When the tool
disappears from the peer's catalog, the proxy is removed. When the peer goes offline, its proxies
are marked unavailable or removed at once, as section 8.5 says; there is no grace period.

### 8.2 Names and resolution

| Name | Rule |
|---|---|
| Qualified name | Always `<net>__<instance>__<tool>` (for example `acme-net__risk-eu__var_calc`; an address name uses its safe form, section 6.1). It splits at the first two `__`; the tool part may itself contain `__`. Any character outside `[A-Za-z0-9_-]` in the host's tool name (MCP also allows `.`) becomes `_`, so the name is valid for every LLM provider's character rules, and it always starts with a letter (the net name's). A qualified name always goes **exactly** where it says, never anywhere else. Planners, audit and metrics always record this name. |
| Plain name (bare alias) | The tool's own name without net and instance (`var_calc`). It resolves in the **resolution order** below, so a call by plain name may reach a local tool or any host offering that tool. Offered when `sajhanet.bare_aliases` is `on` (the default); `preferences_only` offers plain names only for tools that have a preference list; `off` offers none for remote tools. |
| Collision with a local tool | The local tool keeps the plain name (step 1 below). The remote tools stay reachable by their qualified names. Reported on the SAJHA Net page. |
| Same tool on several hosts | Within a net, hosts offering the same name offer the same contract, or the name is quarantined (section 8.7). The plain name reaches them in resolution order and falls back between them (section 9.1). |
| Same name in two nets, different contracts | Nets are separate, so this can happen. The plain name follows the contract of the first net in the resolution order that offers the tool; copies with a different contract hash are reached only by qualified name, never by the plain name or a fallback, and the difference is reported. If that contract disappears from every host, the plain name moves to the next contract in order, and the change is logged and audited. |

**Resolution order** of a plain name, at the home instance:

1. **The local tool**, if this instance has one by that name. Local always wins (unless this
   instance exports that tool into a net where the name is quarantined, section 8.7).
2. **The tool's preference list**, in order, if `sajhanet.preferences` has one for it. Each entry is
   `"<net>/<instance>"` (that host in that net) or `"<net>"` (any host in that net, ordered by the
   routing strategy):

   ```yaml
   sajhanet:
     preferences:
       var_calc: ["acme-net/risk-eu", "acme-net", "partner-net/risk-uk"]
       customer_lookup: ["crm-net"]
   ```

   Entries naming a net or host the server is not in, or one that does not offer the tool, are
   skipped and reported on the Net settings page.
3. **The nets in configured order** (the order of `sajhanet.nets`): in each, the hosts offering the
   tool, ordered by the routing strategy (section 5.3). The first eligible host is called.

A host is **eligible** for a call when it offers the tool, is not `suspect` (section 8.5), is not
blocked, the tool is not quarantined (section 8.7), and this caller's import and residency rules allow
it. The resolution order of every plain name, and why each candidate is or is not eligible, is
shown in the host and tool table (section 8.4), on the Remote tools page and on each call's audit
record, so anyone can see why a call went where it went.

Local always wins, as requested, but a remote tool is never hidden behind a local one: it keeps
its qualified name, and the overlap is visible.

### 8.3 `tools/list` shows everything the caller may use

`tools/list`, the Tools page, the REST catalog and the Ask SAJHA shortlist show local tools and
proxies together, filtered as always by the caller's access, and now also by import rules.
Each proxy carries its net metadata in `_meta["io.sajha/net"]`:

```json
{ "net": "acme-net", "instance": "risk-eu", "qualified_name": "acme-net__risk-eu__var_calc",
  "region": "eu-west", "locality": "remote", "health": "ok", "latency_ms_p50": 85,
  "data_classes": { "results": ["confidential"] }, "llm_tool": false }
```

The Tools page gains net and instance badges, a "local / remote" filter and per-net and
per-instance filters. The landing-page constellation can colour stars by instance.

### 8.4 The host and tool table

Every instance keeps an explicit **routing table** of which instance, in which net, hosts which
tool. It is the single place the proxies, plain names, planners and console read from:

| Field | Meaning |
|---|---|
| `qualified_name` | `<net>__<instance>__<tool>`, always unique |
| `net`, `host_instance`, `host_tool` | which net and instance hosts it, and the tool's own name there |
| `alias` | the plain name, when one is offered |
| `resolution` | its place in the plain name's resolution order and why (`local`, `preference 2`, `net order: acme-net, 1st by routing`), or why it is not eligible now (`suspect`, `blocked`, `quarantined`, `import rule`, `other contract`) |
| `version`, `contract_hash`, `description_hash` | what was last accepted from the host (`version` informational) |
| `trust`, `state` | trust level; `active`, `held` (awaiting review), `hidden`, `blocked`, `unavailable` (host `suspect`), `quarantined` (contract conflict) |
| `first_seen`, `last_seen`, `last_changed` | when the host first offered it, last confirmed it, last changed it |

- A plain name always resolves through this table, so even a call by plain name knows exactly which
  host it goes to and why, and the audit record names the plain name, the qualified name and the
  reason for the choice.
- The table holds only what is live: it is rebuilt from catalogs as they arrive, kept in the state
  store (shared by the instance's workers), and entries leave it the moment their host is gone
  (section 8.5). It is not restored from storage after a restart.
- It is included in every snapshot (section 20.4), so an auditor can see which instance served
  which tool at any point in the retained window, and is the **Remote tools** page in the
  console (section 17).
- When a tool appears on another host or a host stops offering it, the change is a row in the
  table's history and an audit event.

### 8.5 When a host goes offline

A host's tools are only offered while the host is there. Peers remove everything about a host's
tools from memory as soon as they know it is gone:

| Host state (section 6.3) | What its peers do |
|---|---|
| `left` (clean shutdown) | Remove its tools at once. |
| `dead` (crash or cut-off, found by the failure detector) | Remove its tools at the moment it becomes `dead`. |
| `suspect` | Keep its tools listed, marked unavailable; calls skip it (a plain name goes to the next host, section 9.1; a qualified name fails fast with "instance unavailable"). |
| revoked | Remove its tools, as for `dead`. |

Removal covers every live artifact: the proxy tools in the catalog, the host and tool table's live
entries, plain-name resolution and aliases, planner and Ask SAJHA shortlists, and cached results.
Audit records and snapshots keep the history only. A returning host's tools come back after its
catalog is pulled again. After the **home's own restart** it lists no remote tools until each
peer's catalog actually arrives (section 6.6).

### 8.6 Tool names sent to a model

Qualified names can be longer than some model providers allow for a function name. When SAJHA sends
tools to a provider (Ask SAJHA, planners, LLM tools), the gateway maps each long qualified name to a
short alias for that request only and maps the model's tool calls back before anything runs. MCP
clients, audit, metrics and the console always see the full qualified name; the alias exists only
inside one request to the provider. See [LLM Tools](LLM%20Tools.md) for the model gateway.

### 8.7 One name, one contract

**Within a net, a tool name stands for exactly one contract, everywhere.** A tool's contract is its
name, `inputSchema`, `outputSchema` and annotations, compared by a **contract hash**; its
description and title belong to it too, but a difference there is only a warning.

- **Any difference quarantines the name.** If two or more hosts in a net offer a tool with the same
  name but different contracts, there is no winner. Every member that sees it logs a loud error
  (error level, an error notice (section 17.4), an entry in the conflicts queue naming the tool,
  every host offering it and their contract hashes, the `sajha_net_contract_conflicts` metric and an
  alert) and **evicts that tool name**: no copy of it is listed, resolvable, callable or a fallback
  target anywhere in the net, including on the hosts that offer it, for net calls and for plain-name
  calls alike.
- **The error says which server differs.** Members group the hosts offering the name by contract
  hash. When one group is larger, the hosts outside it are named as **differing** and the others as
  **agreeing**; on a tie every group is listed. The message also says what differs, down to the first
  differing place in each schema (a JSON Pointer) or annotation:

  ```
  ERROR  sajhanet  Tool var_calc quarantined in risk-net: cust-na offers a different contract.
         Differs: inputSchema /properties/horizon/type  (cust-na: "string"; others: "integer").
         Agreeing: risk-eu, treasury-na, risk-apac (3).  Differing: cust-na (1).
         Fix: correct var_calc on cust-na, or stop exporting it there. The tool is unavailable
         everywhere in risk-net until then.
  ```

  The same text is the notice's detail, the conflicts-queue entry and the audit record, so every
  member's log and console says the same thing about the same server.
- **Quarantine lifts by itself** once the contract is the same everywhere again: when every host
  still offering that name in the net offers the identical contract (the odd host is fixed, stops
  exporting the tool, or leaves). Entering and leaving quarantine are both logged and audited.
- **Every member decides from what it sees**, and publishes what it has observed itself, so members
  that cannot see every offer (because export rules show a tool to some peers only) still converge
  through gossip. The rule is normative in the
  [protocol spec](../protocol/SAJHA%20Net%20Protocol.md#107-one-name-one-contract).
- **Worked example: the differing host deactivates the tool.** `cust-na` offers `var_calc` with a
  different schema, so every member of `risk-net` quarantines `var_calc` and reports `cust-na` as
  differing. `cust-na`'s administrator disables the tool (or removes it from the export rules).
  `cust-na`'s catalog no longer contains `var_calc`, so its catalog digest changes; gossip carries the
  new digest to every member within a few rounds; each member pulls `cust-na`'s catalog, finds no
  `var_calc` there, re-checks the remaining offers, sees they all share one contract, and lifts the
  quarantine on its own. Each member logs it and raises an info notice ("`var_calc` active again in
  risk-net; cust-na no longer offers it"), and the tool is listed, resolvable and callable again,
  served by the agreeing hosts, typically within seconds. If `cust-na` later offers `var_calc` again
  with the agreed contract, it simply joins the hosts serving it; with a different one, the
  quarantine starts again.
- **Escape hatch.** A host that needs its own differing copy for its local callers stops exporting
  it (its export rules). It is then not part of the net's contract for that name, the conflict ends,
  and its local copy works for its own callers as before.
- **Changing a contract.** Because any difference quarantines the name, a mixed rollout, where some
  hosts already serve the new schemas and others the old, quarantines the tool for as long as it
  lasts. To avoid that, either change every host offering the tool together (one coordinated
  deployment, or take the tool out of the net's export rules on every host, change it, and put it
  back), or ship the new contract under a **new tool name** (`var_calc_v2`) and let callers move to it
  gradually. A tool's `version` is informational and recorded in audit; it does not separate
  contracts, and two versions of one name never coexist as different tools in a net.
- **Fallback needs nothing more.** Because hosts offering a name in a net always offer the same
  contract, any of them can stand in for another (section 9.1).
- **Unrelated servers.** Tools of different organisations that happen to share a name (`search`) are
  kept apart by defining their servers as external servers (section 5.6): the rule then applies to
  `acme__search` and `globex__search`, which never collide.

---

## 9. What happens on a call

```
caller ──► HOME instance                                   HOST instance
           0 resolve the name: qualified → that host; plain →
             local tool, else first eligible host (section 8.2)
           1 access check (caller may call proxy)
           2 import rules (this user, this remote tool)
           3 policy engine (deny / approval / rate limit / quota)
           4 residency check on arguments (section 12)
           5 argument validation (proxy's inputSchema), tool cache
           6 breaker, per-peer rate limit, hop check (section 14)
           7 identity resolver: attach the user's API key;
             signed request, trace id, hop count ──────────► 8 verify signature, certificate, revocation
                                                            9 identity resolver: hash the key, look
                                                              it up in the net key directory, check
                                                              enabled, expiry, home instance
                                                           10 map user and roles (section 11.3)
                                                           11 export rules (this peer, this user)
                                                           12 its own access check and policy
                                                           13 execute the real tool; audit
           15 screen the result (untrusted text),  ◄────── 14 residency check on the result
              cap its size, validate outputSchema
           16 audit (linked by trace id), metrics
caller ◄── 17 result
```

- Both instances' checks must pass; either can refuse. A refusal returns a normal tool error that
  says which side refused and why, in words safe to show the caller.
- Progress notifications and cancellation pass through: a caller's cancel reaches the host.
  Federation already relays progress and, on a cancel, abandons its request task
  (`FederationManager._wait`); the build must make sure the host also receives
  `notifications/cancelled`, rather than only the home side giving up.
- Steps 1, 3, 5 and 6 are what SAJHA already does for every tool, in this order: the access
  check (`sajha/auth/access.py`), then `execute_with_tracking`
  (`sajha/tools/base_mcp_tool.py`), which runs the policy engine before argument validation,
  the tool cache and the circuit breaker; federation adds its per-upstream rate limit inside the
  call. Redaction and output screening are the policy engine's work on the result, at step 15.
- Retries to the same host follow federation's rule: only tools annotated read-only or idempotent
  (`readOnlyHint` or `idempotentHint`), up to the peer's retry count. Moving to another host is the
  waterfall fallback of section 9.1. The result cache applies
  only to read-only tools with a `cache_ttl` and needs a cache key that includes the caller, which
  the tool cache does not have today (section 4); until it does, proxy tools are not cached.
- Destructive remote tools still require confirmation at the home instance (MRTR or `confirm`
  fingerprints), and the host instance may additionally require its own approval.

### 9.1 Waterfall fallback

When a call by plain name cannot be run by the host it went to, the home tries the **next eligible
host offering the same tool**, in resolution order (section 8.2), in any of its nets.

- **What starts a fallback.** A **"not executed"** failure: the connection was refused, the host's
  circuit breaker is open, the host is unavailable (`suspect`) or draining, or the host refused
  before running anything for availability reasons (overloaded, rate-limited). Hosts say so in a
  signed error field, `executed: false`, defined in the
  [protocol spec](../protocol/SAJHA%20Net%20Protocol.md#158-not-executed-and-fallback-to-another-host).
  A refusal for any other reason (access, policy, identity, a block, residency) is that host's answer
  and is returned to the caller: a refusal is a decision, not an outage.
- **After a failure that may have run the tool** (a timeout after the request was sent, a dropped
  connection, a proxy error with no signed answer), the home falls back only for tools that are
  read-only (`readOnlyHint`), or idempotent (`idempotentHint`) and marked non-destructive; never for
  destructive tools.
- **Which hosts are eligible.** Hosts offering the same tool name: within a net that guarantees the
  same contract (section 8.7); in another net the contract hash must also match. Quarantined, blocked,
  `suspect` and import- or residency-excluded hosts are skipped.
- **Each fallback is a full call.** The next host authorizes the user itself; if it refuses, for any
  reason, the home skips to the next host. The home's own checks that do not depend on the host
  (access, policy, argument validation, confirmation) run once; those that do (import rules,
  residency on arguments, breaker, rate limit, hops) run again for each host.
- **Limits.** At most `sajhanet.max_fallbacks` (default 3) fallbacks after the first attempt. All
  attempts share one overall deadline (`default_timeout_seconds`, or the caller's own) and one budget;
  no attempt starts after the deadline.
- **Visible.** Every attempt is audited under the same trace id with its attempt number, host and
  outcome; the caller's result carries the list of attempts; metrics count fallbacks
  (`sajha_net_fallbacks_total`). If no host answers, the caller gets the first host's failure with
  the list of attempts.
- **A qualified name never falls back**: it goes exactly where it says.

---

## 10. Identity

### 10.1 Instance identity

Every request between instances is signed with the sender's key and carries its net certificate
(sections 6.1 and 6.7). A request
from a server without one, or from a revoked instance, is refused before anything else is read.

### 10.2 User identity: a pluggable resolver, API keys first

The host instance must know which user a call is for; otherwise it can only authorize "instance A",
and any user of A gets whatever A may do.

How the user is identified across instances is a **pluggable resolver** with two halves:

- on the home instance, `outbound(caller) → credentials to attach to the forwarded call`;
- on the host instance, `inbound(request) → a verified net user` (user id, home instance,
  roles, tool allowlist) or a refusal.

The resolver is chosen per net by `user_identity` (section 5.5 has the as-built rules). **The first
implementation is `api_key`**, as the owner decided; `assertion` (a user assertion the home signs with
its net certificate, protocol §15.5) and `token_exchange` (the home trades an assertion at the host for a
host-scoped token, protocol §15.9; the design first sketched RFC 8693 through a shared identity provider)
are built as further implementations of the same interface, so switching needs no change anywhere else.

**`api_key`: the user's API key is their net identity.**

1. A user (or a script, or an agent) holds an API key issued by **one** instance, their home
   instance, and calls SAJHA there.
2. The home instance verifies the key: first in its database as it does today, then in its
   persistent key file if the database does not know it or is unavailable (section 20.3);
   either way the SHA-256 hash, enabled flag and expiry are checked (`ApiKeyDAO.validate_key`,
   `sajha/db/dao`), and the key's tool access mode and list when a tool is called.
3. When the call goes to a proxy tool, the home instance forwards the **key itself** to the host
   instance in a dedicated header of the signed request, over HTTPS, together with the trace id and
   hop count.
4. The host instance hashes the key and looks it up in its **net key directory** (section 10.3,
   which includes keys from instances' persistent key files),
   a synced copy of every instance's key records. It checks that the record exists, is enabled,
   is not expired or revoked, and that the request came **from the key's home instance** (a key can
   only enter the net through the instance that issued it).
5. The verified net user is the key's owner, with the owner's roles as recorded by the home
   instance, mapped to local roles (section 11.3), and the key's tool access list as an extra
   ceiling. Authorization then proceeds as in section 11.

**What API keys were, and what changed.** *Built in wave 1: owned keys, self-service, revocation
records, default keys and persistent keys are as-built in the
[Security Model](../security/Security%20Model.md#api-keys); the rest of this paragraph records
the starting point.* This resolver assumes a key acts as the user
who owns it. Before wave 1 it did not (`AuthManager.authenticate_apikey`, `sajha/auth/__init__.py`): a
key authenticated as a service identity `apikey:<key name>` with the single role `api_consumer`,
and what it may call is decided only by the key's own `tool_access_mode` (`all`, `allowlist`,
`denylist` or `regex`) and `tool_access_list` (`sajha/auth/access.py`), not by any user's roles.
The `api_keys` table has an `owner_id` column, but keys are created by administrators only
(`/admin/apikeys`, `sajha/routes/apikeys_routes.py`), and creation never sets it. A key has no
`revoked_at`: it is disabled (`enabled` toggled off) or deleted. The build therefore adds:

- keys bound to an owner: `owner_id` set when a key is created, and a key that has an owner
  authenticates as that user, with the user's roles and the key's access list as an extra
  ceiling (keys without an owner keep today's service identity and never cross the net);
- users creating and rotating their own keys, including the default key below;
- a record of revocation that survives deletion (section 10.3).

**Handling rules for forwarded keys.** The raw key exists only in memory during the call: it is
never logged, never written to the audit log (the key's id and prefix are), never stored, never
put in a trace attribute, and never forwarded onward when re-export is on (a further hop gets
the key id inside an instance-signed assertion instead). Only HTTPS hops may carry it (section 6.7).

**Why forward the key rather than only its id.** Forwarding lets the host instance verify the
user's possession of the key independently, against its own synced copy, instead of trusting
the home instance's word. The cost is that every instance sees every forwarded key in transit, so a
compromised instance could capture keys from calls that reach it. That is acceptable for a net
whose instances are trusted (an owner decision, section 24); a net that wants to remove that
exposure switches the resolver to `assertion`, where only a key id signed by the home instance
crosses, without other changes.

**Anonymous callers** never cross: proxy tools are not visible to them unless
`sajhanet.anonymous_may_call_remote` is set (off by default, refused for destructive tools).
**Every user has a default API key.** Every user account on every instance always has a
**default API key**, created with the account (and, when this ships, for every existing account
at start-up). It cannot be deleted, only rotated (regenerated) by the user or an administrator,
or disabled by an administrator. The user sees it on a new page in their own account area (today
that area has only Connected accounts, `/account/connections`), can copy it once after each
rotation, and uses it like any other key.

Because API keys are stored only as hashes, the home instance could not forward a key it had
not just received. So the default key is also kept **encrypted** at its home instance, with the
AES-256-GCM encryption and data key of the connected-accounts vault (`sajha/accounts/vault.py`:
`accounts.vault.key`, env `SAJHA_ACCOUNTS_VAULT_KEY`, or a `key_provider` hook, else a key
generated once in the server secrets file under the data directory), readable only by that
instance. When a signed-in
console user (or Ask SAJHA, a workflow or an LLM tool acting for them) calls a remote tool, the
home instance decrypts the user's default key and forwards it. A caller who arrived with an API
key forwards that key instead.

Default keys are ordinary keys everywhere else: in the key directory, in snapshots, under the
user's tool access list (by default `all`, so the user's own access) and revocable at once.

**Connected accounts.** A user's linked SaaS tokens never leave their home instance. A remote tool
that needs the user's token for a provider runs only on an instance where that user has linked the
account; otherwise the host instance answers "connect your account here", as federation's token
passthrough does.

### 10.3 The net key directory

Each instance publishes the records of the API keys it issued, and every instance keeps a synced
copy of everyone's: the **net key directory**. Each net has its own directory: an instance in
several nets publishes its key records in each, naming itself by its name in that net and signed
with that net's certificate, so its users' keys work in every net it belongs to, and a record from
one net means nothing in another.

| Field | Meaning |
|---|---|
| `key_id`, `key_prefix`, `name` | the key's identity, as in the issuing instance's `api_keys` table (`id`, `key_prefix`, `name`) |
| `key_hash` | the SHA-256 hash SAJHA already stores; **the raw key is never synced** |
| `home_instance` | the instance that issued it and is its only authority |
| `owner` | the owner's login name (`users.user_id`, carried in the record's `owner.user_name`), internal id (`users.id`, in `owner.user_id`), display name (`users.user_name`, in `owner.display_name`) and role names at the home instance; the protocol names the fields after what they are in the net, not after SAJHA's columns |
| `enabled`, `expires_at`, `revoked_at` | its current state; `revoked_at` is new (the `api_keys` table has none): it is set when the home instance deletes the key, and the directory keeps the record as a tombstone |
| `tool_access_mode`, `tool_access_list` | its tool access: `all`, `allowlist`, `denylist` or `regex`, and the patterns |
| `version`, `updated_at` | a counter the home instance increments on every change |
| `signature` | the home instance's signature over the record, so no other instance can forge or alter it |

**How it syncs.** Each instance's directory has a version (the highest record version it issued).
Gossip carries every instance's directory version in its digest (section 6.3). When an instance sees
a newer version for a peer, it pulls only the records changed since the version it holds, from
that peer, verifies each record's signature against the peer's certificate, and stores them. A
full comparison with one random instance runs every
`sajhanet.key_directory.full_sync_interval_seconds` (default 300; gossip's own anti-entropy,
`sajhanet.gossip.full_sync_interval_seconds`, exchanges only directory versions), so a missed
update is repaired within that time.

**Revocation is fast where it matters.** Disabling or revoking a key takes effect on its home
instance at once, and a forwarded key can only arrive from its home instance (section 10.2, step
4), so a
revoked key stops working across the net immediately even before the directory update has
spread. Revocations are also gossiped with priority, so every instance's copy follows within a
few rounds.

**Ownership.** Only the home instance can change a key's record; a record for `risk-eu`'s key that
arrives from anyone else, or that is not signed by `risk-eu`, is ignored. When an instance leaves
or is revoked, its keys are marked unusable in every directory.

**What it costs.** One row per API key in the net, a few hundred bytes each, stored in a new
table (section 20) so lookups by hash are indexed and local key administration is unaffected.

---

## 11. Authorization

### 11.1 Both sides decide, neither trusts the other

- The **home instance** decides whether its user may use the remote tool and whether these
  arguments may leave (import rules, access rules, policy engine).
- The **host instance** decides whether this peer, for this user, may run this tool (export rules,
  its own access rules mapped from the user's roles, its own policy engine and approvals).

The host instance never accepts "instance A says the user may": it applies its own rules to the user
the identity resolver verified (section 10.2). This is what prevents a confused-deputy attack, where an instance is used to
reach what its users could not reach directly.

### 11.2 Export and import rules

Rules are per net, in that net's entry of `sajhanet.nets` (instance names are that net's):

```yaml
sajhanet:
  nets:
    - name: acme-net
      export:                     # what this instance offers in acme-net
        - tools: ["var_*", "stress_*"]
          to_instances: ["risk-*", "treasury-na"]
          for_roles: ["risk_analyst", "treasurer"]     # remote roles after mapping (11.3)
          require_approval: false
        - tools: ["*_delete*"]
          to_instances: []                            # never exported
      import:                     # what this instance's users may use from acme-net
        - instances: ["risk-eu"]
          tools: ["var_*"]
          for_roles: ["analyst"]
        - instances: ["*"]
          tools: ["*"]
          for_roles: ["admin"]
```

Leaving a tool out of a net's export rules is also how a server keeps its own copy of a tool whose
contract differs from the net's (section 8.7).

Nothing is exported or imported unless a rule allows it. Rules are evaluated at catalog time (a
caller does not even see a proxy it may not call) and again at call time (rules can change
between the two).

### 11.3 Users across instances

Every instance has **its own users**. The same person may have an account on several instances,
under the same or a different user name, with different roles and different API keys on each;
and a person may have no account at all on some instances. Only the administrator account exists
on every instance (the seed creates user `admin` with role `admin` everywhere, though an operator
can delete it). The net never merges or copies user accounts.

A net user is therefore always **a user at an instance**, in a net: `alice@risk-eu`. Links, name
matching, role maps and unknown-user handling are set per net, since the same server may carry
different names, and meet different peers, in each. When `alice@risk-eu`
calls a tool hosted on `cust-na`, the host instance decides who she is *there*, in this order:

1. **An explicit link.** `cust-na`'s administrator has linked `alice@risk-eu` to a local account
   (say `a.smith`). The call runs as `a.smith`, with `a.smith`'s roles and policy.
2. **The same user name, if allowed.** With `sajhanet.users.match_by_name` on (the default), a local
   account with the same user id (`alice`: the login name, `users.user_id`, which is unique;
   `users.user_name` is a display name and is never matched) is used. Its local roles apply, never the roles
   `alice` has on `risk-eu`. An administrator can turn matching off for an instance or exclude
   names.
3. **No local account.** Governed by `sajhanet.users.unknown`:
   - `refuse` (default): the call is refused with "you have no account on cust-na"; the proxy
     tools that would need one are not shown to her at all (section 8.3);
   - `map_roles`: the call runs as a guest identity `alice@risk-eu` with the roles produced by
     the host's **role map** for `risk-eu` (`analyst@risk-eu → risk_analyst`); unmapped roles map
     to nothing.

**Administrators.** The administrator account exists everywhere, so by name matching an
administrator on one instance would be an administrator on every other. The design separates two
things:

- **Tool calls.** An administrator from another instance calls tools as the host's administrator
  only if `sajhanet.users.remote_admin` is `admin` (the default, given the net is trusted); `user`
  treats them like any linked or matched user; `refuse` blocks them. As built, under `user` a name
  match gives a remote administrator no `admin` role (the seed `admin` exists everywhere); only an
  explicit link to a local administrator does.
- **Net administration.** Blocking, trust levels, user links, role maps and every other net
  setting on an instance can only be changed by an administrator **signed in to that instance**,
  never through a remote call. Each instance governs itself.

**API keys.** A key belongs to one user on one instance. Alice's key on `risk-eu` and her key on
`cust-na` are different keys with different records in the key directory; either identifies her
only as the user on the instance that issued it, and the host maps that identity as above.

The SAJHA Net console (section 17) shows, for each instance, which remote users are linked, matched,
mapped or refused, and lets an administrator link or unlink them.

**Signing in to several consoles.** A person who uses the consoles of several instances signs in
once when those instances trust the same identity provider ([console single
sign-on](../security/Security%20Model.md#console-single-sign-on)); each instance still maps the
person to its own local user, as above.

### 11.4 Blocking

An administrator can block, on their own instance and per net, at four levels (a block on
`risk-eu` in `acme-net` does not touch the same server in another net). A block takes effect on the
next request (in-flight calls finish), is written to the audit log with who, when and why, may
have an expiry, and is shown everywhere it matters in the console.

| Block | Set by | Effect |
|---|---|---|
| **An instance, entirely** | any instance, for itself | This instance stops calling the blocked one (its proxy tools disappear from this instance's catalog), refuses every call from it, and ignores its catalog and key-directory updates. Gossip still reports the blocked instance's state, so the console can show it. |
| **One direction** | the host (inbound) or the caller (outbound) | Inbound: `cust-na` refuses calls *from* `risk-eu` but may still call `risk-eu`'s tools. Outbound: `risk-eu` stops calling `cust-na`'s tools (they are hidden from its users) but still serves calls from `cust-na`. |
| **A tool** | either side | The host refuses calls to that tool from a given instance (or from all), or the caller hides that remote tool from its users. |
| **A remote user** | the host | Calls on behalf of `alice@risk-eu` are refused, whatever her mapping. |

Each instance decides only for itself: an administrator on `treasury-na` cannot block calls from
`risk-eu` to `cust-na`. Removing an instance from the whole net is not a block: it is a
revocation of its certificate by the SAJHA Net CA (section 6.1), which every instance enforces.

Blocks are **local decisions, shared information**: each instance publishes the blocks it holds
in its gossip digest, so the console on any instance can draw the net-wide picture (who blocks
whom, and why) while each block is still enforced only by the instance that set it.

---

## 12. Data sovereignty and residency

Residency is about where data flows, in both directions.

Built in wave 5, phase 5.1: what was built, and where the build differs from this design, is in
section 5.5 ("Built of section 12: residency"); the rule conditions are in
[Policy and Audit](Policy%20and%20Audit.md) 3.5.

- **Data classes.** A tool's schema can mark arguments and result fields with
  `x-sajha-data-class` (for example `eu-personal`, `confidential`, `public`); a whole tool can
  declare classes for its results. Instances declare their jurisdiction labels.
- **Residency rules** are policy-engine rules with a new condition: *data of class C may (or may
  not) go to an instance whose jurisdiction is J*. Examples: `eu-personal` never leaves instances
  labelled `jurisdiction: EU`; `confidential` only to instances in the same legal entity. The
  rule language has nothing like this today: a rule matches on tools, groups, annotations,
  callers, sources, time and argument values (`sajha/policy/model.py`), and parsing is strict, so
  an unknown key is an error. Data classes, the destination instance and its labels are new
  match conditions.
- **Arguments.** Before a call leaves (step 4), the home instance checks the classes of the
  arguments' fields against the host instance's labels. A planner cannot route EU personal data to
  a US tool by accident: the call is refused, and the planner is told why so it can choose a
  local alternative.
- **Results.** The host instance checks its results' classes against the home instance's labels
  before answering (step 14) and can refuse, redact or summarise. Policy `redact` today masks
  kinds of personal data (emails, phones, cards, national ids, custom patterns) anywhere in a result;
  removing the fields of a data class is new.
- **What the home instance keeps.** Conversation memory stores answers, which may now contain data
  from other instances. Per data class, `sajhanet.memory.remote_results` decides whether such answers
  are stored as written, stored as a summary without the remote figures, or not stored.

---

## 13. Planners, LLM tools and memory

- **One catalog for planners.** The planner sees local and remote tools in one shortlist, with
  locality, region, health, indicative latency and data classes from the net metadata. Ranking
  adds small preferences: local over remote, healthy over degraded, same jurisdiction over
  different, so a remote tool is used when it is the right tool, not because it ranked first by
  wording.
- **Residency-aware shortlists.** Remote tools that residency rules would refuse for this caller
  are removed before planning, so the model is never offered a call that will be refused.
- **Only live tools.** Shortlists hold only eligible tools: those of `left`, `dead` or revoked hosts
  are removed at once, those of `suspect` hosts are left out while they are suspect, and
  quarantined names are never offered (sections 8.5 and 8.7). A planner that names a tool by its
  plain name gets the resolution order and the waterfall fallback like any caller.
- **Remote LLM tools.** A host instance's LLM tools ([LLM Tools](LLM%20Tools.md), itself a design not yet built) are exported
  like any tool (`sajhanet.allow_remote_llm_tools`, on by default: the owner decided LLM and plain
  tools are equally trusted). They run, plan and spend model budget
  on the host instance, under its AI governance, with the user's identity. Their inner calls may
  use the host instance's tools and, within the hop limit, other instances' tools.
- **Memory is always local.** Conversation memory lives only on the instance the user talks to. A
  remote tool, including a remote LLM tool, receives its arguments and nothing else: never the
  conversation, never another tool's results unless the planner put them in the arguments (and
  then residency rules apply to them).
- **Budgets.** Local limits (steps, tool calls, time, cost) count remote calls like local ones;
  the host instance's own budgets apply to the work it does.

---

## 14. Hops and loops

- **No transitive re-export by default.** An instance exports only its own tools, never proxies it
  imported (`reexport: false`, set per net). Without re-export, every remote call is exactly one hop.
- **Nets are never bridged by default.** A server in two nets offers in one net only its own tools,
  never tools it imported from the other. Only when `reexport` is on **for the net it offers into**
  does it act as a **bridge**: it offers the other net's tools as its own, authorizes the caller like
  any host, and calls into the other net as the local user it mapped the caller to (it can vouch
  only for its own users there, since nothing signed in one net can be checked in the other). The
  hop count and the list of visited instances (each written `<net>/<instance>`) continue across the
  bridge, so loops through several nets are caught too.
- **When re-export is enabled**, each call carries a hop count and the list of instances it has
  visited (in signed headers). An instance refuses a call that would exceed
  `sajhanet.max_hops` or revisit an instance, so A → B → A loops cannot form.
- **Remote LLM tools** count toward the hop limit: calls a remote LLM tool or planner makes for its own
  work carry the incoming hop count and visited list onward (protocol §16).
- **One combined budget.** A chain that crosses instances and nests planners, LLM tools and composites
  is bounded end to end by `sajhanet.max_call_chain` (default 8): hops plus tools nested in one another
  on every instance passed. The nesting depth travels with each forwarded call, the home refuses a call
  over the budget before sending it and the host refuses one on receipt (`-32016 chain_limit`), and the
  home also refuses to send a chain back to an instance it already passed (`loop`). The per-instance
  limits (`tools.max_call_depth`, `ai.llm_tools.max_depth`) still apply on each instance.
- **What goes onward** is chosen by re-export rules (`reexport_rules`), not by `reexport` alone: with it
  on and no rule, nothing is re-exported. A tool is never offered back to its host or origin, and an
  instance never imports a tool whose origin is itself, so a catalog cannot loop either. As built in
  section 5.5.

---

## 15. Reliability

- **Per-peer isolation.** Connection pools, timeouts, circuit breakers and rate limits are per
  peer, so one slow or failing instance affects only its own tools. Federation already works this
  way per upstream: one connection each, a circuit breaker registered for the upstream's prefix,
  and `max_calls_per_minute` (`sajha/federation/manager.py`).
- **Health.** Each instance probes its peers (and their catalogs) on a schedule and records health;
  the planner and the Tools page see it.
- **Graceful degradation.** An instance that cannot reach the net still serves all its local tools;
  a call by plain name moves to the next host offering the tool (section 9.1); a call by qualified name
  to an unreachable host fails fast with "instance unavailable".
- **Offline hosts disappear.** A host that leaves or is found dead has its tools removed from every
  peer at once; a suspect host's tools stay listed as unavailable and are skipped (section 8.5).
- **Version skew.** Instances advertise a net protocol version alongside the MCP eras they speak;
  an instance talks to a peer at the highest version both support and refuses peers below
  `sajhanet.min_protocol_version`.
- **Several workers.** Peer records and approvals live in the storage backend (as federation's
  do) and fast-changing state in the state store, so every worker of an instance sees the same
  net.

---

## 16. Observability and audit

- **Linked audit.** Both instances record the call in their own tamper-evident audit chains,
  sharing one trace id (W3C `traceparent`) and the API key's id. The home's record names the net,
  the plain and qualified names, why that host was chosen (section 8.2) and, for a call that fell
  back, one entry per attempt with its number, host and outcome (section 9.1). Contract quarantines
  and their lifting are audit events too. A cross-instance call can be
  reconstructed by joining the two records, and neither instance's records depend on the other's.
  This is a new audit event: today the chain (`sajha/audit/`, one chain per process) records
  policy decisions, approvals, administration and workflow events, not ordinary tool calls. A
  record's `details` is free JSON inside the hashed record, so the trace id, key id and peer
  instance fit without a schema change.
- **Tracing.** One trace spans home and host (OTLP), so latency per hop is visible. SAJHA already
  continues an inbound `traceparent` (HTTP header or MCP `_meta.traceparent`,
  `sajha/observability/tracing.py`); sending it on the forwarded call is new.
- **Metrics.** `sajha_net_calls_total{net,peer,tool,outcome}`, latency per peer, refusals by side
  and reason (`import`, `export`, `residency`, `identity`, `revoked`, `contract_conflict`), fallbacks
  (`sajha_net_fallbacks_total{net,peer,reason}`, counting each move away from a host), quarantined
  tool names (`sajha_net_contract_conflicts{net}`), catalog sizes and refresh results, peer health. Every existing metric is named `sajha_<subsystem>_*` (for example
  `sajha_federation_upstream_calls_total`), so `sajhanet_*` breaks that convention;
  `sajha_net_*` would keep it (section 24). Proxy calls also count in `sajha_tool_calls_total`
  under their qualified name, as every tool does.
- **Net page.** Instances and their health, pending joins and approvals, imported and exported
  tool counts, name conflicts, trust levels, role maps and the last refusals; a topology view of
  which instances call which.

---

## 17. The SAJHA Net console

The net is managed from a new **SAJHA Net** area in SAJHA's web console. It follows the
console's conventions (the four themes, light, dark, blue and green; page help whose terms come
from `GLOSSARY.md` through `sajha/web/page_help.py`; phone-width layouts checked by
`scripts/check_mobile.py`, whose `ROUTES` list gains each new page; the same tables, filters and
confirmation dialogs as the rest of the console) and its own bar: an operator should understand
the state of the net in ten seconds and change it safely in two clicks. Every page has a JSON API
behind it and the same actions in the `sajha` command line. That command is the client CLI
(`clientsdk/`, [Command Line](../clients/Command%20Line.md)), which works over HTTP, so
`sajha net ...` commands, including `sajha net ca init` and `sajha net ca enroll` (section 6.4),
call these APIs on an instance and run nothing locally.

### 17.1 Pages

| Page | What it shows | What an administrator can do |
|---|---|---|
| **Instances** (every signed-in user) | Every participant in this server's nets as a card or table row: net, name (configured or address), kind (SAJHA, agent, sponsored), region, labels, state with last seen, and how many of its tools **this user** may use. Search and filter by net, name, region, label, kind and state. Clicking an instance opens its tools: each tool's name, alias, description, inputs and outputs, health and latency, with the same **Try it** form as the local Tools page (subject to the user's access). Read-only for users | Administrators: add a peer by address for a net (section 6.6); everything else from the pages below |
| **Net overview** | One map per net, with a net selector when this server is in several. A live topology map: one node per instance (this one centred), coloured by state (`alive`, `suspect`, `dead`, `left`, blocked), edges showing traffic in the last hour with thickness by calls and colour by error rate; beside it, cards with each instance's name, region, labels, latency, tools shared, last seen, certificate expiry. Net totals: instances, remote tools in use, calls and refusals in the last hour. | Open an instance; filter by region or label; pause the live view |
| **Instance detail** | Header with state, incarnation, certificate and expiry, versions; tabs for **Tools** (what it exports to us, what we export to it), **Traffic** (calls each way, latency percentiles, errors and refusals by reason), **Users** (its users we link, match, map or refuse), **Keys** (its key-directory records: count, revoked, last sync), **Blocks** (ours toward it and, from gossip, its toward us), **History** (catalog changes with diffs, state changes, blocks) | Block or unblock (entirely, inbound, outbound), change trust level, edit role map, link users, force a catalog and key refresh |
| **Remote tools** | Every proxy tool in one searchable table: qualified name, net, hosting instance, plain name, health, latency, trust, data classes, contract hash, version, last change; for each plain name, its **resolution order** with the reason for each place (local, preference, net order) and why any host is skipped now (suspect, blocked, quarantined, rule); local tools can be included for comparison | Hide or block a tool, edit the tool's preference list, review a held change (diff of description and schema), open its audit trail |
| **Conflicts and reviews** | A queue of what needs a person: **contract conflicts** (each quarantined tool name with every host offering it and its contract hash, a diff of the schemas and annotations, and when it started; each open conflict is also an error notice, section 17.4), description differences (warnings), local tools whose contract differs from the net's, instance-name collisions, changes held under `review` trust, screening flags, tools refused by limits | Approve, reject; block the odd host or its tool; open the export rules to stop exporting a local copy; bulk actions with a reason |
| **Users across the net** | For each remote instance, its users seen calling here and how each resolved (linked, matched by name, mapped roles, refused), with their last calls | Link a remote user to a local account, unlink, block a remote user, turn name matching off for an instance |
| **Access and blocks** | A matrix of instances (rows: callers, columns: hosts) showing allowed, blocked inbound, blocked outbound and blocked entirely, from this instance's own blocks plus the blocks others publish; a list view with reasons, who set each, and expiries | Add, edit, expire or remove this instance's blocks, with a required reason and a confirmation that names the effect ("risk-eu's 214 users will lose access to 37 tools") |
| **Key directory** | Read-only view of synced key records by instance: owner, prefix, state, expiry, tool allowlist, last change, signature status; this instance's persistent keys marked | Force a re-sync; nothing here can change another instance's keys |
| **Snapshots** | The retained snapshots with time, size, chain status (verified, broken) and signature status | Verify the chain, compare any two snapshots (users, keys and tools added, removed and changed), download, restore users and persistent keys after confirmation |
| **Live activity** | A stream of cross-instance calls as they happen, drawn in the constellation style of the landing page: a call travels from instance to instance, refusals flash with their reason, and a fallback shows each attempt in turn with why it moved on | Filter by instance, user, tool or outcome; open any call's linked audit records on both sides |
| **Certificates** (CA instance only, section 6.4) | For each net this server is the CA of: issued certificates with instance, serial, expiry and state; pending enrollment tokens; the revocation list | Enroll an instance (create a token), revoke, re-issue |
| **Net settings** | The nets this server is in, in preference order, each with this instance's name there, region and labels (read from configuration), certificate status, configured seeds and, separately, runtime seeds (with who added them), and gossip health; a hint to give a name to a net still called `default`; the per-tool preference lists (with entries that match nothing flagged) and `max_fallbacks`; defaults for trust, name matching, unknown users and remote administrators | Add a peer by address for a net, optionally keeping it as a runtime seed, and remove runtime seeds (section 6.6); edit what may be edited at runtime; everything else names the configuration key to change |

### 17.2 Where the net shows up elsewhere

- **Tools page and tool detail:** a badge with the net, the hosting instance and its health on every
  remote tool, a "local / remote / net / instance" filter, and on the detail page the path a call
  takes: the plain name's resolution order with the reason for each host, and the fallback order.
- **Ask SAJHA:** remote tools are labelled with their instance in the plan and the answer's
  citations; the animation colours stars by instance.
- **Dashboard:** a SAJHA Net tile (instances alive, remote calls, refusals) linking to the overview.
- **Audit and usage pages:** filters by remote instance and remote user; a cross-instance call
  links to its counterpart record on the other side.
- **Navigation:** a SAJHA Net menu. Every signed-in user sees **Instances** (section 17.1);
  administrators also see the management pages.
- **Navbar:** the SAJHA wordmark stays as it is (owner decision). An instance that belongs to a net
  shows a small badge beside it, **Net · `<instance name>`** with a health dot for its connection
  to the net, linking to Instances (in several nets: **Nets · `<count>`**, listing each net and this
  instance's name there on hover). It tells a user at a glance which instance they are on. Problems
  in the net reach administrators as system notices (section 17.4), not as SAJHA Net banners of
  their own.

### 17.3 Quality bar

- **State is never ambiguous.** Every instance, tool and block shows its state in words and
  colour (never colour alone), with the time it was last confirmed.
- **Every destructive action explains its blast radius** before it is taken (users and tools
  affected), requires a reason, and can be undone from the history tab.
- **Fast at net size.** Pages load from the state store and local tables, never by calling
  every instance on page load; live views update by server-sent events.
- **Accessible and responsive.** Keyboard reachable, screen-reader labels on the map (with a table
  equivalent), phone-width layouts for every page, all four themes.
- **Tested like the rest of the console:** page tests for every view and action, the mobile check
  in all themes, and an end-to-end test that blocks an instance and sees its tools disappear.

### 17.4 System notices

SAJHA Net reports conditions that need a person through SAJHA's general
[System Notices](System%20Notices.md) service, never through banners of its own: an error notice
shows as a banner on every console page, the dashboard's System status panel lists all open notices,
and the navbar shows their count. Each notice names its source, links to the SAJHA Net page that
explains it, clears itself when the condition ends, and can be acknowledged by an administrator.
SAJHA Net's notice sources, all per net:

| Source | Severity | Clears when |
|---|---|---|
| Tool quarantined (`contract_conflict`), naming the tool, every host offering it and their contract hashes (section 8.7) | error | every host offering the name offers one contract again |
| `name_conflict`: this server refused under a held name, or a conflict seen between two other servers (section 6.1) | error (own), warning (seen) | the configuration or certificate changes; the claimant is gone |
| Member `suspect`, `dead` or `left` (section 8.5) | warning; `dead` is an error when the member hosts tools this server's users use | the member is `alive` again, or its retention ends |
| Seeds unreachable, or not joined to the net (a net with no seeds is a net of one and raises only an info notice while it has no certificate, section 6.6) | error | the server has joined the net |
| This server's certificate expiring (within a third of its validity) or expired | warning, then error | it is renewed |
| Revocation list stale (older than its expected refresh) | warning | a newer list arrives |
| Key-directory sync failing for a peer | warning | the next sync succeeds |
| CA instance unreachable for renewal | warning, error near expiry | renewal succeeds |
| A block added against this server by another (from published blocks, section 11.4) | info | the block is removed or expires |
| A peer added by hand: succeeded (info) or failed (warning), section 6.6 | info / warning | acknowledged, or after a day |
| Forwarded keys allowed over plain HTTP (`require_https: false`) | warning | the setting is on again |
| A net still named `default` | info | the net is given a name |

### 17.5 As built

The console has these SAJHA Net pages now (the rest of section 17.1 is not built; section 5.5):

| Page | Route | Who | Built |
|---|---|---|---|
| **Instances** | `/net/instances`, `/net/instances/{net}/{instance}` | every signed-in user | As in section 17.1 (section 5.5). |
| **Your net access** | `/net/access` | every signed-in user | Each remote tool by name, every host offering it in resolution order with its state and the host's member state, and whether this server lets the user call it there (Try it); the user's count of this server's own tools. This server's decision only: the host decides again on every call (section 11.1). |
| **Net overview** | `/admin/sajhanet/overview?net=` | administrators | A net selector; totals (membership and gossip health, instances by state, admission mode, remote tools by state, notices, quarantined and held tools, active blocks); the **topology map**; members with region and last seen, gossip details (joined via, last errors, interval, the gossip agent, incarnation, revocation-list version), seeds and runtime seeds; this net's open notices, quarantined names, description warnings and held tools (Approve); this server's blocks and those others publish; the admission panel; from the newest `net.*` records of the audit chain, the recent forwarded calls (side, tool, outcome, attempt, other instance, user, trace id), call-chain refusals (`hop_limit`, `loop`, `chain_limit`) and residency decisions by flow and outcome with the recent redactions and refusals; the router's call and fallback counters since start. |
| **Remote tools** | `/admin/sajhanet/tools` | administrators | The host and tool table, held tools, conflicts (section 5.5). |
| **SAJHA Net admin** | `/admin/sajhanet` | administrators | Membership, add a peer by address, runtime seeds with Remove, the admission panel, blocks, remote users and the key directory. |

- **Topology map:** plain SVG drawn by `sajha/web/static/js/sajhanet.js` from
  `GET /api/sajhanet/topology?net=` (`{nets: [{name, nodes: [{name, kind, region, state, self}], edges:
  [{from, to, kind, tools, calls}]}]}`): this server in the centre, the others on a ring, each node
  coloured by its state and labelled with it in words when it is not `alive`, and a link to the
  instance's tools; edges for `offers` (solid), `reexports` (dashed) and `calls` (thicker with more
  calls), each with a tooltip. A table under the map ("The map as a table") lists the same nodes and
  edges. It redraws at the container's width (phone widths included) and refreshes every 30 seconds
  while the tab is visible; **Pause live view** stops that. When the endpoint answers nothing, the map
  shows the members without links and says so.
- **Admission panel** (Net overview and SAJHA Net admin), by the net's admission mode: `open`: the
  remembered first-use keys (`GET .../first-use`) with **Forget** (`DELETE .../first-use/{instance}`);
  `manual`: the pins from configuration and from runtime (`GET .../pins`), add and remove; `builtin_ca`
  on the CA instance: issued certificates with **Revoke** (a reason is required), waiting enrollment
  tokens, **Create token** (shown once) and **Initialise** when the CA has no key yet; elsewhere it says
  this server is not the CA instance. Admission, routing, residency and locality are shown, never
  decided, here.
- **Confirmations:** every change (forget, pin, unpin, revoke, create a token, initialise the CA, remove
  a runtime seed, approve a held tool, add or remove a block) asks first in words that name its effect.
  The blast-radius counts, reasons on every action and undo from a history tab of section 17.3 are not
  built.
- **Data:** `sajha/net/integration/overview.py` (`overview_view`, `access_view`), read from the state
  store, this worker's registry and the audit chain; never from calling peers. JSON at
  `GET /api/sajhanet/overview` and `GET /api/sajhanet/access`
  ([API Reference](../protocol/API%20Reference.md)).

---

## 18. Threats and mitigations

| Threat | Mitigation |
|---|---|
| A server takes over an existing instance's name (by mistake or on purpose) | Names are bound to the holder's certificate key; the CA will not enroll a held name; any join or request claiming a held name with another key is refused with `name_conflict` and alerted on both sides |
| A rogue server pretends to be an instance | Every request signed with a key whose certificate comes from the SAJHA Net CA only, with a timestamp, nonce and body digest; the signed revocation list is checked on every request; gossip from a server without a net certificate is refused |
| A compromised instance impersonates users | Host instances authorize the named user against their own export and access rules, never "the instance says so"; role maps grant nothing by default; revocation is immediate |
| A request is replayed or altered in transit | Signatures cover method, path, key headers and a body digest; a creation time and nonce with a short window, seen nonces kept in the state store |
| A forwarded API key is captured | Keys travel only in signed requests over HTTPS, are never logged, stored or traced, and are accepted only from their home instance, so a captured key cannot be replayed through another instance; a net that wants no key in transit switches to the `assertion` resolver (section 10.2) |
| An administrator on one instance takes over another | Net settings can only be changed by an administrator signed in to that instance; remote administrators' tool calls are configurable (`remote_admin`) and audited |
| The CA key is stolen | It lives only on the CA instance as an owner-only secret; certificates are short-lived; re-keying the CA and re-enrolling instances is a procedure the build documents |
| An enrollment token is stolen | One-time, short-lived (the net's `ca.enrollment_token_minutes`), bound to one instance name; a used, expired or wrong-name token is refused, and every issue is audited and listed on the Certificates page |
| Default keys are read from the vault | AES-256-GCM with the connected-accounts vault key (`SAJHA_ACCOUNTS_VAULT_KEY` or a KMS `key_provider`; without either, a generated key in the owner-only server secrets file under the data directory), never in the database; only the home instance can decrypt |
| The persistent key file or a snapshot is copied | Hashes only, never keys; owner-only permissions; git-ignored; snapshots carry hashes only for persistent keys |
| Snapshots are edited or deleted to hide a change | Each snapshot chains to the previous one and is signed by the instance; rotation and every snapshot run are audited |
| An instance forges or alters another instance's key records | Every directory record is signed by its home instance and ignored otherwise; only the home instance may change its records |
| False gossip (a healthy instance reported dead, a fake instance advertised) | Indirect probes before suspicion; an instance refutes suspicion itself with a higher incarnation; only certificate-holding instances can gossip, and an instance's details are accepted only from itself or as gossip about a certificate-verified instance |
| A peer's description tries to instruct the model | Descriptions screened and capped; changes held for review; results treated as untrusted data (section 9 step 15) |
| A peer quietly changes what a tool does | Every description or schema change is recorded in the audit log with a diff and shown on the SAJHA Net page; a contract change that other hosts of the name do not share quarantines the name (section 8.7); under `review` trust the change is held at the last approved version |
| Data leaves its jurisdiction through arguments | Residency rules on arguments at the home instance; on results at the host instance; residency-aware shortlists |
| An instance is used as a stepping stone (confused deputy) | Dual authorization on the user's identity; no re-export by default; hop limits |
| A slow instance drags others down | Per-peer timeouts, breakers, pools and rate limits; local tools unaffected |
| SSRF through a peer URL | Federation's URL guard (`check_url`) on every peer URL learned from gossip, with the net's own allowed networks, since instances usually have private addresses that federation's defaults refuse; a URL must match the host name or address in the instance's certificate |
| Denial of service from a peer | Per-peer rate limits at the host instance; catalog size caps |
| An administrator adds a malicious or wrong peer address | The address is only a hint: the peer is admitted only with a certificate from that net's CA (or a thumbprint the administrator confirms in manual mode), under a non-conflicting name, not revoked; the address must pass the network allowlist and SSRF rules; injections are local-admin only, rate-limited, audited and raise a notice |
| Contract poisoning: a host offers a tool under a name the net already uses, with other schemas or annotations, so calls or fallbacks meant for one tool reach another | One name, one contract: any difference quarantines the name on every member, including the offering hosts, so no call ever reaches a copy whose contract differs (section 8.7). The trade-off is denial of service: one rogue or misconfigured host can quarantine a tool net-wide. Mitigations: the error notice names the odd host on every member; administrators can block that host or its tool, which removes its offer from their view; the CA can revoke it; `review` and `pinned` trust keep unreviewed tools out; the odd host can stop exporting the tool at once |
| A server in two nets leaks one net's tools or identities into the other | Nets share nothing but the port: separate CAs, certificates, membership, key directories, blocks and rules; a request for an unknown net gets a plain `404`; imported tools are never offered to another net unless that net's `reexport` is on, and then the other net sees only the bridge's own user (section 14) |
| A fallback runs a tool twice | Fallback after a failure that may have run the tool only for read-only or idempotent, non-destructive tools; otherwise only after a signed or self-evident "not executed" (section 9.1); a host that falsely signs "not executed" is identifiable from its signature |
| Fallback used to shop for a host that says yes | A refusal by the first host is returned, never routed around; only availability failures start a fallback, and each host authorizes the user itself |
| Calls planned against a host that is gone | Tools of left, dead and revoked hosts are removed at once; nothing is listed after a restart until the peer answers (section 8.5) |

---

## 19. Configuration

```yaml
sajhanet:
  enabled: false
  nets:                             # one entry per net; list order = preference order between nets (section 8.2)
    - name: acme-net                # section 6.1; omitted: the net is called `default` (the console suggests naming it)
      instance_name: risk-eu        # this server's name in this net; if unset: <ip>:<port> (section 6.1)
      advertise_address: ""         # ip:port peers in this net should use, behind NAT or container networks
      founder: false                # true only on the net's first server (typically the CA instance)
      seeds:                        # tried first (section 6.6); none: a net of one, this server its founder
        - https://sajha-treasury-na.example.internal
        - https://sajha-cust-eu.example.internal
      identity:                     # this net's CA certificate; requests are signed (section 6.7)
        cert_ref: file:/etc/sajha/sajhanet/acme-net/instance.crt
        key_ref: file:/etc/sajha/sajhanet/acme-net/instance.key   # secret references, never values
        ca_ref: file:/etc/sajha/sajhanet/acme-net/ca.pem
        revocation_list_ref: file:/etc/sajha/sajhanet/acme-net/revoked.json   # signed; also spread by gossip
      ca: { enabled: false, key_ref: file:/etc/sajha/sajhanet/acme-net/ca.key, cert_validity_days: 30, enrollment_token_minutes: 30 }   # section 6.4, CA instance only
      peer_cache: { path: data/sajhanet/acme-net/peers.json, interval_minutes: 10, max_age_days: 7 }   # local disk; tried after the seeds (section 6.6)
      static_peers: []              # membership: static only
      export: []                    # section 11.2
      import: []                    # section 11.2
      # any shared default below may also be set here, for this net only (for example
      # region, labels, users, user_identity, default_trust, reexport, reexport_rules, max_hops, gossip, limits)
    - name: partner-net
      instance_name: risk-eu-partner
      seeds: [https://sajha-partner-hub.example.net]
      identity: { cert_ref: file:/etc/sajha/sajhanet/partner-net/instance.crt, key_ref: file:/etc/sajha/sajhanet/partner-net/instance.key, ca_ref: file:/etc/sajha/sajhanet/partner-net/ca.pem, revocation_list_ref: file:/etc/sajha/sajhanet/partner-net/revoked.json }
      default_trust: review
      export: []
      import: []
  preferences:                      # per-tool resolution preferences, server-wide (section 8.2)
    var_calc: ["acme-net/risk-eu", "acme-net", "partner-net"]
  max_fallbacks: 3                  # waterfall fallbacks after the first attempt (section 9.1)
  # shared defaults for every net
  base_url: https://sajha-risk-eu.example.internal
  region: eu-west
  labels: { domain: risk, jurisdiction: EU, entity: acme-eu }
  signature_max_age_seconds: 30     # a signed request older than this is refused (replay window)
  require_https: true               # forwarded API keys only over HTTPS hops; false only for a lab
  mtls: off                         # extra check when SAJHA itself terminates TLS: off | optional | required
  users: { match_by_name: true, unknown: refuse, remote_admin: admin }   # section 11.3
  default_keys: { enabled: true, vault: accounts }   # section 10.2
  user_identity: api_key            # api_key (first) | assertion | token_exchange, or a list (section 10.2)
  reexport: false                   # offer imported tools onward (section 14); with reexport_rules naming them
  reexport_rules: []                # [{tools, from_nets, from_instances, to_instances, for_roles}]
  plugins:                          # section 5.3: a shipped name or package.module:Class
    membership: gossip              # gossip | static (static_peers in a net entry)
    admission: builtin_ca           # builtin_ca | manual (section 6.5)
    connector: sajha_native         # sajha_native | mcp_generic
    key_directory_store: database
    routing: local_first            # local_first | lowest_latency | pinned
  allowed_networks: []              # CIDRs peers may be reached on; private ranges need listing (section 18)
  key_directory: { sync: true, full_sync_interval_seconds: 300 }
  persistent_keys: { file: config/apikeys.json, reload: true }   # section 20.3
  snapshots: { enabled: true, interval_minutes: 10, keep: 20, dir: data/sajhanet/snapshots, compress: false, to_siem: false }   # section 20.4
  gossip:
    gossip_interval_ms: 1000
    ping_timeout_ms: 500
    indirect_probes: 3
    suspect_timeout_seconds: 10
    full_sync_interval_seconds: 30
    dead_retention_minutes: 60      # keep probing a dead instance's last address this long
    dead_probe_interval_seconds: 30
  refresh_interval_seconds: 300
  default_timeout_seconds: 30       # also the shared deadline of all fallback attempts
  bare_aliases: on                  # on | preferences_only | off (section 8.2)
  reexport: false                   # per net; never bridges nets unless on for the receiving net (section 14)
  max_hops: 1
  max_call_chain: 8                 # hops plus tools nested in one another on every instance passed (section 14)
  allow_remote_llm_tools: true     # LLM tools are shared like plain tools (owner decision)
  default_trust: auto               # auto | review | pinned, for newly joined peers (owner decision)
  anonymous_may_call_remote: false
  min_protocol_version: 1
  limits: { max_tools_per_peer: 2000, max_catalog_bytes: 5242880, max_description_chars: 1024 }
  memory: { remote_results: store }   # store | summary | none, per data class in rules
```

Membership is discovered by gossip, starting from each net's seeds. Trust levels, role maps, user
links and any manual-mode peers are managed per net on the SAJHA Net pages and kept in the storage
backend, like federation's upstream records.

**Which keys live where.** Only in a net entry: `name`, `instance_name`, `advertise_address`,
`founder`, `seeds`, `identity`, `ca`, `static_peers`, `export` and `import` (`peer_cache` may also be
set once as a shared default, with `<net>` in its path). Server-wide only:
`enabled`, `nets`, `preferences`, `max_fallbacks`, `default_keys`, `persistent_keys`, `snapshots`,
`memory`, `plugins`, `max_call_chain` and `allow_remote_llm_tools`. Every other key is a shared default that a net entry may override for its
own net. There is no `unhealthy_grace_seconds`: tools of an offline host are removed or marked at
once (section 8.5).

`persistent_keys` and `snapshots` apply even when `enabled` is false (they also serve a SAJHA that
is not in a net, section 22). The persistent key file's path duplicates the existing
`config.apikeys.path` (default `config/apikeys.json`), which wave 1 made the persistent key file;
the build reads that key rather than adding a second one. The shared keys resolve as
every `_get` key does: `SAJHA_SAJHANET_<KEY>` in the environment, then this YAML, then the code
default. The `nets` list cannot be addressed element by element through environment variables; it
is set in YAML or, on Kubernetes, through the chart's `config.overrides`.

---

## 20. Storage

### 20.1 Database

Every change goes into both schema files (`db/scripts/<dialect>/schema.sql`; no migrations:
operators run the DDL on PostgreSQL, SQLite creates the tables itself, and
`tests/test_db_schema.py` checks that models and both files agree).

- **New table `sajhanet_api_keys`** for the net key directory (section 10.3): one row per key
  issued anywhere in the net, indexed by key hash, holding the record fields and its home
  instance's signature. It is kept apart from the local `api_keys` table, so local key
  administration is unchanged.
- **New table for default keys:** the encrypted copy of each user's default key (section 10.2),
  keyed by the key id, next to `connected_accounts` and encrypted the same way.
- **New columns on `api_keys`:** a *persistent* flag (section 20.3) and a *default* flag (section
  10.2). `owner_id` already exists but is never set today (section 10.2).

### 20.2 Storage backend and state store

- **Storage backend** (local disk, S3, Azure Blob or GCS, `sajha/core/storage.py`), JSON records
  alongside federation's: blocks and user links (audited on change, published in the gossip
  digest), trust levels, role maps, manual-mode peers, the last accepted catalog per peer (used
  only to ask a peer whether it changed and to hold approved versions under `review`, never to list
  tools, section 8.5), and, on the CA instance only, issued certificates, enrollment tokens and the
  signed revocation list; all of it per net.
- **Local disk:** the saved peer list of each net (section 6.6), deliberately outside the storage
  backend so that a restart can find peers even when that backend is remote or down.
- **State store** (`state.backend`), shared across an instance's workers: per net, the membership
  list and incarnations, the gossip agent's lease, catalog, directory and conflicts digests, the host
  and tool table, contract quarantines, peer health, per-peer rate counters and seen request nonces
  (section 6.7).

### 20.3 Persistent API keys in a file

API keys live in the database, which can be lost: a corrupted SQLite file, a dropped PostgreSQL
schema, a restore gone wrong. Some keys must keep working anyway: the key an automation uses to
reach SAJHA, an administrator's break-glass key, the keys other systems depend on. Each instance
therefore also keeps **persistent keys** in a JSON file, `config/apikeys.json`, read in addition
to the database.

- **What the file holds.** One record per persistent key: key id, prefix, name, the SHA-256 hash
  (never the key itself), the owner's user name and roles (the users table may be gone too),
  enabled flag, expiry, tool allowlist, creation time and who created it. An administrator marks
  a key *persistent* when creating it (or later); the raw key is shown once, as today, and
  SAJHA writes only its record to the file.
- **When it is used.** Verification checks the database first and the file second, so a key in
  the file works when the database does not know it or is unreachable. A key present in both
  must agree; if the database says disabled or expired, that wins, so revoking in the database
  always takes effect.
- **Keeping it current.** SAJHA rewrites the file atomically (write a temporary file, then rename)
  whenever a persistent key is created, changed or revoked, and reloads it when it changes on
  disk (an operator may edit it, for example to revoke a key during an outage). Every change is
  written to the audit log. The reload can hang off the watch `sajha/core/hot_reload_manager.py`
  already keeps on `apikeys.json`, whose callback does nothing today.
- **Protection.** The file is created with owner-only permissions and is git-ignored; a tracked
  example file next to it documents the format. Today `config/apikeys.json` is itself tracked in
  git, so the build removes it from the repository and adds it to `.gitignore`. A hash of a long random key cannot be
  reversed, but the file still names users and their access, so it is treated as sensitive.
- **In the net.** Persistent keys are part of the instance's key directory like any other key, so
  every instance can verify them too.
- **The old file (built in wave 1).** `config/apikeys.json` used to hold four plaintext demo keys
  in an older format that nothing read. Wave 1 replaced it with the hashed format above
  (`sajha/auth/persistent_keys.py`, `config/apikeys.json.example`); the demo keys were not carried
  over, and the old format is never read.

### 20.4 Periodic snapshots

Every instance writes a **snapshot** of what it knows every `snapshots.interval_minutes` (default
10) and keeps the last `snapshots.keep` (default 20), so an auditor can see who and what existed
at any point in the retained window, and an instance can be rebuilt after losing its database.

- **Contents.**
  - Users: id, user name, roles, enabled (no password hashes).
  - API keys issued by this instance: the record fields of section 20.3 for every key, persistent
    or not; hashes only for persistent keys, so a snapshot alone cannot verify ordinary keys.
  - Tools: every local tool (name, version, contract hash, enabled) and every proxy tool (qualified
    name, net, host instance, version, contract hash, trust level, state including quarantine).
  - Net view, per net: instances and their states, incarnations and labels as this instance saw
    them, and the key directory's version per instance.
- **Format and place.** One JSON file per snapshot, named with the UTC time and a sequence number,
  in `data/sajhanet/snapshots/` (or the storage backend), owner-only permissions, optionally
  compressed.
- **Tamper evidence.** Each snapshot records the SHA-256 of the previous one and is signed with
  the instance's net key (outside a net, with the server signing key in `data/oauth/` that also
  signs the audit chain's anchors), so a deleted, reordered or edited snapshot is detected, the
  same idea as the audit chain. A snapshot run is also an audit event.
- **Rotation.** After writing a snapshot, the oldest beyond `keep` are deleted (and their deletion
  audited). Twenty snapshots ten minutes apart cover a little over three hours; for longer
  history each snapshot can also be sent to the SIEM export, which keeps it under the SIEM's own
  retention.
- **One writer.** With several workers, the gossip agent's lease holder writes the snapshot (a
  SAJHA outside a net takes the same kind of lease for snapshots alone, section 6.3), so an
  instance produces exactly one per interval.
- **Restoring.** After a database loss, an administrator can re-create users, roles and key
  records from a chosen snapshot (keys come back only if they were persistent, since only those
  snapshots carry hashes); tools and net state rebuild themselves from configuration and gossip.

---

## 21. Testing

- **Multi-instance tests in one process:** two or three SAJHA apps with separate databases and
  keys, joined into a net, exchanging catalogs and calling each other.
- **Participants and plug-ins:** a sponsored MCP server and an agent-fronted MCP server take part
  like SAJHA instances (proxies, identity, blocks, audit); capability negotiation; every
  interface's contract suite against each shipped implementation; the extension's conformance
  suite against SAJHA, the agent and the library.
- **Name collisions:** enrollment of a held name refused; a join under a held name with a different
  key refused everywhere, alerted, never retried until configuration changes; same-key restarts
  accepted.
- **Instance names:** a configured name is used as is; without one, the advertised address, a
  specific bind address or the default-route interface gives `<ip>:<port>`; `0.0.0.0`, `::`,
  loopback, `localhost` and link-local addresses are never used, and with nothing acceptable the
  instance stays out of the net with a clear message; the underscore form for IPv4 and fully
  expanded IPv6, never containing `__`; qualified names `<net>__<instance>__<tool>` split at the
  first two `__` and always start with a letter.
- **One port and signatures:** all net traffic on the normal port behind a TLS-terminating proxy;
  bad, missing, expired, replayed or wrong-certificate signatures refused; body tampering caught by
  the digest; signed responses verified; forwarded keys refused over plain HTTP unless the lab
  override is on.
- **Several nets:** one server in two nets under different names; net names validated (`default`
  when unnamed, with its notice); requests for an unknown net get a plain `404`; certificates,
  nonces, key records, blocks and catalogs of one net never accepted in the other; no tool offered
  across nets unless `reexport` is on for the receiving net, and then only as the bridge's own user;
  a user's key works in both nets of its home.
- **Seeds and restarts:** a net entry without seeds is a net of one (joined alone, no error notice,
  no join retries or gossip) and grows without a restart when a peer joins through it; a founder
  whose seeds are down starts alone; on restart seeds are tried
  first, then the saved peer list most recently seen first (entries over `max_age_days` skipped, a
  stale entry's certificate still verified), then discovery; with all down an error notice and
  back-off; the peer list saved atomically on change and every interval, on local disk with the
  storage backend unavailable; a peer added by hand joins only with a valid certificate for that
  net (wrong net, revoked, `name_conflict`, unreachable and SSRF-refused addresses fail with the
  reason and store nothing), is saved, optionally kept as a runtime seed, is refused over a remote
  call, and every attempt is audited.
- **Membership:** a dead instance found again by peers' low-rate probes; after a restart no remote
  tool is listed until that peer's catalog arrives; joins through a seed, clean leaves, crashes detected through indirect probes,
  false suspicion refuted, rejoin with a higher incarnation, revocation spreading, a server
  without a net certificate refused; a network split heals through anti-entropy.
- **Identity:** a forwarded key verified against the directory; unknown, disabled, expired or
  revoked keys refused; a key arriving from an instance other than its home refused; directory
  records with bad signatures ignored; the raw key absent from logs, audit and traces.
- **Persistent keys and snapshots:** a persistent key works with the database removed; database
  revocation overrides the file; an edited file reloads; snapshots appear every interval, only
  `keep` are kept, the chain detects an edited or missing snapshot, one writer across workers;
  users and keys restore from a snapshot.
- **Users and blocks:** linked, name-matched, mapped and refused remote users; a remote
  administrator under each setting; net settings refused over remote calls; each block level in
  each direction, expiry, and blocks published by gossip.
- **CA and default keys:** enrollment with a token (reused, expired and wrong-name tokens
  refused), renewal, revocation; every user has a default key that survives rotation and is
  forwarded for console sessions; the vault copy is unreadable without the instance's key.
- **Host and tool table and resolution:** a plain name resolves to the local tool, then the
  preference list, then the nets in order, with the reason recorded in the table and the audit; a
  qualified name goes only where it says; preference entries that match nothing are reported; the
  table holds only live entries and appears in snapshots.
- **Offline hosts:** on `left` and on `dead` a host's tools leave the catalog, the table, plain-name
  resolution, planner shortlists and caches at once; while `suspect` they are listed unavailable and
  skipped; they return only after a new catalog pull.
- **One name, one contract:** two hosts with different contract hashes for one name quarantine it on
  every member, including the hosts offering it, with an error notice, conflicts-queue entry, metric
  and audit event; a description difference only warns; a member that cannot see one offer
  quarantines through another member's published conflicts; quarantine lifts automatically (and is
  audited) when the odd host is fixed, stops exporting or leaves; a host that stops exporting keeps its
  local copy for its own callers.
- **Waterfall fallback:** each "not executed" case (connection refused, breaker open, suspect,
  draining, `-32019` with `executed: false`) moves to the next eligible host in order; a timeout after
  sending falls back only for read-only or idempotent non-destructive tools; refusals by the first
  host are returned; a refusing fallback host is skipped; `max_fallbacks` and the shared deadline
  hold; every attempt audited with one trace id; qualified names never fall back.
- **Tool names sent to a model:** long qualified names reach a provider as short per-request
  aliases and the model's calls map back to the full names; audit and MCP clients see full names.
- **Key directory sync:** a new or changed key reaches every instance; a missed update repaired by
  anti-entropy; a leaving instance's keys become unusable.
- **Authorization:** a user without access at the host instance is refused even when the home
  instance allows it, and the reverse; role maps; anonymous callers.
- **Names:** local wins; the same name in two nets with different contracts follows the first net
  in order and never falls back to the other contract.
- **Residency:** arguments and results of each data class to instances of each jurisdiction;
  residency-aware shortlists.
- **Resilience:** an instance down, slow, flapping or returning oversized catalogs; local tools keep
  working.
- **Planners:** a question needing tools on two instances is answered; memory stays on the home
  instance.
- **Catalog exchange:** a changed digest triggers a pull and an unchanged catalog is never
  transferred; the fallback refresh catches a missed digest; each trust level (`auto`, `review`,
  `pinned`); screening flags and the JSON Schema check; size limits.
- **Federation changes (section 4):** `<net>__<instance>__<tool>` names with address and IPv6 instance parts accepted for net proxies;
  `.` in a host tool name replaced; annotations never widened; a changed tool under `review`
  keeps serving its approved version; a proxy result never served from another user's cache
  entry; the SSRF guard with the net's allowed networks.
- **Hops and versions:** no re-export by default; with re-export on, the hop limit and a revisited
  instance refused; a peer below `min_protocol_version` refused; the extension advertised on both
  eras.
- **Audit, tracing and metrics:** both sides' audit records carry the same trace id and key id;
  one trace spans home and host; refusals counted by side and reason.
- **Conformance:** both MCP suites stay green on every instance.

---

### 21.1 New code this design needs

Checking the design against today's code found these pieces that do not exist yet. The
[Implementation Plan](Implementation%20Plan.md) refers to them by number.

1. API keys bound to an owner: a key signs in as its owner with the owner's roles (today it signs in
   as `apikey:<name>` with role `api_consumer`); `owner_id` set; self-service keys; a revocation
   record; a default key per user, kept encrypted in the accounts vault.
2. Advertising the extension on the 2025-11-25 era (today only 2026-07-28's `server/discover`
   advertises extensions). **Built** (wave 4, phase 4.1): `sajha/core/net_extension.py`, on both eras
   when `sajhanet.enabled`, reduced for unsigned requests; client declarations read from either place.
3. Every tool call as an audit event (today only policy, approval, admin and workflow events are in
   the chain), and an outbound `traceparent`.
4. A per-user key for the tool result cache (today the key is tool name plus arguments).
5. Federation changes: the instance-name prefix rule, `.` replaced in names, annotations corrected
   rather than copied, the old version kept serving under `review`. **Built** (wave 4, phase 4.1):
   section 4's table says where.
6. A SAJHA Net network allowlist in the SSRF guard (today private networks are refused unless
   `federation.allow_private_networks` is set). **Built** (wave 4, phase 4.1): `check_peer_url` and
   `sajhanet.allowed_networks`.
7. A renewing state-store lease (today cron and probes claim one slot at a time and never renew).
8. Policy conditions for data class and destination, and field-level redaction.
9. A Helm value for the nets list and instance names. **Built** (wave 4, phase 4.1): the chart's
   `sajhanet` values ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md#sajha-net)).
10. Untracking `config/apikeys.json` and replacing its plaintext legacy keys with the hashed format.
11. An account page where users manage their own keys.
12. `notifications/cancelled` reaching the host (today federation only abandons its local task).
    **Built** (wave 4, phase 4.1) for federation on both eras; net proxies, being federated tools, get it too.
13. JSON Schema validation of imported schemas. **Built** (wave 4, phase 4.1) for federation;
    the same check is there for net catalogs (phase 4.2).

## 22. Build plan

Each phase ends green: full suite, multi-instance tests, both conformance suites.

| Phase | Scope |
|---|---|
| 1 | The protocol-only core and every plug-in interface (section 5.3) from the start, each with its contract tests; then membership: named nets, several per server, kept apart on one port by the signed net header, and per-net instance names and address names (section 6.1), the SAJHA Net CA run by SAJHA (CA instance, enrollment tokens, renewal, revocation), certificates and signed requests on the normal port, revocation list, gossip agent per net (SWIM failure detection, dissemination, anti-entropy, required seeds and `founder`, incarnations, a renewing lease across workers), restarts (seeds first, then the saved peer list on local disk, probes of dead instances), manual mode, protocol version and extension advertisement on both eras; SAJHA Net page (instances and their states) |
| 2 | Catalog exchange driven by gossip digests, the live host and tool table, immediate removal of offline hosts' tools and nothing listed after a restart until peers answer (section 8.5), screening and trust levels, automatic proxy tools with the federation changes of section 4 (name rule, annotations, held versions, per-user cache key, SSRF settings), qualified names `<net>__<instance>__<tool>`, resolution order with per-tool preferences and routing strategies, one name one contract with quarantine and published conflicts (section 8.7), waterfall fallback (section 9.1), `tools/list` with net metadata, Tools page badges and filters, SAJHA Net's system notice sources (section 17.4) |
| 3 | Identity resolver interface; API keys bound to their owner (owner's roles, self-service keys, revocation record; section 10.2); the `api_key` resolver; default API keys for every user, kept encrypted at home; users across instances (links, name matching, unknown users, remote administrators); blocking at all four levels; the net key directory with signed records, digest-driven sync and the `sajhanet_api_keys` table in both schema files; host-side verification; persistent key file and periodic snapshots (these two also benefit a SAJHA that is not in a net); export and import rules, role maps; linked audit and tracing; metrics; per-peer isolation |
| 4 | Residency: data classes, residency rules on arguments and results, residency-aware shortlists, memory handling of remote results |
| 5 | Planners and LLM tools: locality-aware ranking, remote LLM tools, hop and depth limits combined |
| 6 | Re-export with hop limits; the `assertion` and `token_exchange` resolvers; topology view |
| 7 | The SAJHA Net console: Instances page for every signed-in user, overview map per net, instance detail, remote tools and the host and tool table with each plain name's resolution order, conflicts and reviews, users, access and blocks, key directory, snapshots, live activity, certificates, settings; net badges across the console, including the navbar badge; mobile check in all themes |
| 8 | Other MCP servers: sponsored participants; the SAJHA Net extension specification and its conformance suite; the SAJHA Net agent (sidecar) and the reference library; third-party plug-in registration |
| 9 | Docs: this note becomes as-built; glossary; tutorial ("two domains, one question"); Security Model; Configuration and API Reference; help card; CHANGELOG |

---

## 23. Competitive position

Putting several MCP servers or gateways behind one another is not new; some gateways advertise
federation between their own instances. Before SAJHA claims anything on the comparison page
(`sajha/web/competitive.py`), each such claim will be checked against the product's own
documentation and cited.

What this design would add, in combination, is aimed at regulated, multi-domain organisations:

- the **user's identity** carried across servers and authorized again by the server that owns
  the tool;
- **export and import rules** and **data residency** on arguments as well as results;
- **tamper-evident audit on both sides**, linked per call;
- **planners and LLM tools that know where each tool runs** and what data may go there;
- each server keeping **its own AI layer and memory** under its own governance.

---

## 24. Decisions for the owner

**Decided**

- **Size:** about ten instances; no registry (section 6).
- **Trust:** instances' tools are trusted, LLM tools and plain tools alike. New peers default to
  `auto` trust and remote LLM tools are on (sections 7.3 and 13). Screening stays on as a
  safeguard against a compromised instance.
- **Membership by gossip:** instances discover each other and detect arrivals and departures
  automatically (section 6), which makes admission by net certificate and signed requests the
  instance authentication.
- **User identity:** the user's API key, issued by one instance, is forwarded with the call and
  checked against a net key directory synced to every instance; the identity resolver is
  pluggable so assertions or token exchange can replace it later (section 10).

- **Persistent keys and snapshots:** API keys can also live in `config/apikeys.json` so they
  survive a lost database; every instance snapshots users, keys and tools every 10 minutes and
  keeps 20 (section 20).

- **Instances and users:** each instance is named in its own configuration; users and their API
  keys are per instance, and a user may not exist on some instances; the administrator account
  exists everywhere (sections 6.1 and 11.3).
- **Blocking:** an administrator can block another instance entirely, in one direction, per tool
  or per remote user, for their own instance (section 11.4).
- **Console:** a full SAJHA Net area in the web console (section 17).
- **The SAJHA Net CA is run by SAJHA:** one CA instance, enrollment tokens, automatic renewal,
  revocation (section 6.4).
- **Default API keys:** every user always has one, kept encrypted at home so console users can
  reach remote tools (section 10.2).
- **Plain names (bare aliases):** on (`bare_aliases: on`), always resolved through each instance's
  host and tool table in the resolution order (sections 8.2 and 8.4). This replaces the earlier
  `unique` setting: within a net a name now has one contract (section 8.7), so several hosts of one
  name are interchangeable rather than a collision.

- **Name:** SAJHA Net (config `sajhanet.*`, metrics `sajha_net_*` like every other SAJHA metric,
  command `sajha net`).
- **Instance names never collide:** a held name is refused loudly at enrollment and at join
  (section 6.1).
- **Any MCP server may join**, so the protocol is a published MCP extension and the
  implementation is pluggable (section 5).

- **SAJHA Net agent language:** Python, built from the shared protocol-only core; a single
  static binary only if a deployment later needs one.

- **Users with no account on a host** are refused, and the remote tools that would need one are
  hidden from them (`sajhanet.users.unknown: refuse`, section 11.3).
- **Administrators from other instances** call tools as the host's administrator
  (`sajhanet.users.remote_admin: admin`); net settings on an instance still change only through an
  administrator signed in to it (section 11.3).

- **Navbar:** keep the SAJHA wordmark; show a Net badge with the instance name when in a net.
- **Default instance name:** `<ip>:<port>` of a real, reachable address when none is configured.
- **Named nets, several per server:** each net fully separate (CA, certificates, membership, key
  directory, blocks, rules, trust); instance names per net; an unnamed net is `default`; nets are
  never bridged unless `reexport` is on for the receiving net (sections 6.1 and 14).
- **Configuration shape:** `sajhanet.nets` lists the nets, in preference order, with shared defaults
  at `sajhanet.*` (section 19).
- **Qualified names** are `<net>__<instance>__<tool>`, so they always start with a letter; long
  names reach model providers as short per-request aliases (sections 8.2 and 8.6).
- **Per-tool preferences and resolution order:** local tool, the tool's preference list, then nets
  in configured order; a qualified name goes exactly where it says (section 8.2).
- **Everything about a tool is shared**, and a host that goes offline has its tools removed by its
  peers at once (`left`, `dead`) or marked unavailable (`suspect`); after a restart nothing remote is
  listed until peers answer (sections 7.1 and 8.5).
- **Waterfall fallback** to the next host offering the same tool after a "not executed" failure, or
  after a possible execution only for read-only or idempotent non-destructive tools; up to
  `max_fallbacks` (default 3) (section 9.1).
- **One name, one contract:** any contract difference for one name in a net quarantines it
  everywhere until the hosts agree; `version` is informational; contract changes roll out together
  or under a new name (section 8.7).
- **No seeds, a net of one:** a net entry without seeds makes this server the net's founder and
  only member, with no error, retries or gossip; it grows into an ordinary net when a peer joins
  through it or is added by address, without a restart. Restarts try seeds first, then the peer list
  saved on local disk (section 6.6). This replaces the earlier "seeds required except on the founder".
- **System notices:** SAJHA Net reports through the general System Notices service (section 17.4).
- **Instances page for everyone:** every signed-in user can browse participants and the tools
  each offers them.

No decisions are open.

---

## 25. Alternatives considered

| Alternative | Why not |
|---|---|
| One central SAJHA with every tool | Moves every domain's credentials and data access into one place; the boundary sovereignty requires disappears |
| Membership configured by hand on every instance | Ten instances means up to ninety peer entries to keep consistent; arrivals and failures go unnoticed. Gossip with certificate admission keeps who-may-join a deliberate act (issuing a certificate) while making everything after it automatic |
| A central registry for membership | One more service to run and keep available; not needed at about ten instances |
| Syncing raw API keys | Every instance would store every key; a single compromised database leaks keys usable everywhere. Only hashes and signed records are synced |
| Server-to-server trust only (no user identity) | The host instance can only authorize "instance A", so any user of A gets all of A's access: a confused deputy by design |
| Shared database or state store across instances | Couples instances' availability and crosses the data boundary the net exists to keep |
| Remote tools under their bare names, local wins | Silent shadowing: the same name could mean different tools on different instances, and a planner would not know which it called |
| Copying tool definitions and running them locally | The tool would run outside its data's boundary with copied credentials, defeating sovereignty |
| One net per server | Organisations need overlapping groupings (a domain net and a partner net); separate named nets let one server take part in each under that net's own rules without joining them |
| Keeping an offline host's tools listed for a grace period | Planners and callers would keep choosing tools that cannot answer; removing them at once and falling back by plain name serves callers better |
| First host to offer a name fixes its contract | Needs agreement on who was first, which gossip cannot give reliably, and silently serves one contract while another host believes it serves the name; quarantine until the hosts agree has no winner to dispute |
| Versions side by side under one name | Callers and models choose by name; two contracts behind one name would make a call's meaning depend on routing. A new contract gets a new name |
| Retrying only on the same host | A host that is down or draining would fail every call by plain name although another host offers the same tool |
