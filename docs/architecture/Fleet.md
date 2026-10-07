# SAJHA Fleet

> **Status: design, not built.** This note is the design for a **fleet**: several SAJHA
> servers that share their tools with one another while each keeps its own data, credentials,
> policy, AI layer and conversation memory. It extends [Federation](Federation.md), which
> today brings other MCP servers' tools into one SAJHA by hand. It is item L16 on the
> [Roadmap](Roadmap.md).

A SAJHA server configured as a **member** of a fleet automatically learns which tools the other
members offer, and builds a **proxy tool** for each one it is allowed to use. The proxy appears
in its catalog next to its own tools. When a caller (a person, an MCP client, a planner, an LLM
tool, a workflow) calls a proxy, SAJHA forwards the call to the member that hosts the tool, as
that caller, and returns the result. To the caller, a fleet tool is just a tool.

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
5. [Membership](#5-membership)
6. [Catalog exchange](#6-catalog-exchange)
7. [Proxy tools and the unified catalog](#7-proxy-tools-and-the-unified-catalog)
8. [What happens on a call](#8-what-happens-on-a-call)
9. [Identity](#9-identity)
10. [Authorization](#10-authorization)
11. [Data sovereignty and residency](#11-data-sovereignty-and-residency)
12. [Planners, LLM tools and memory](#12-planners-llm-tools-and-memory)
13. [Hops and loops](#13-hops-and-loops)
14. [Reliability](#14-reliability)
15. [Observability and audit](#15-observability-and-audit)
16. [Threats and mitigations](#16-threats-and-mitigations)
17. [Configuration](#17-configuration)
18. [Storage](#18-storage)
19. [Testing](#19-testing)
20. [Build plan](#20-build-plan)
21. [Competitive position](#21-competitive-position)
22. [Decisions for the owner](#22-decisions-for-the-owner)
23. [Alternatives considered](#23-alternatives-considered)

---

## 1. Why build this

Large organisations rarely have one place where all data may live. Business lines, legal
entities and regions each own their data and the rules for using it, and regulators expect those
boundaries to hold. A single central tool server either cannot reach that data or becomes the
place where every boundary is crossed.

A fleet puts a SAJHA server inside each boundary. Each one:

- holds the tools that touch its data, and the credentials those tools use;
- applies its own access rules, policy engine, approvals and audit;
- runs its own AI layer (models, budgets, planners, LLM tools) under its own governance;
- keeps its own users' conversation memory.

What crosses a boundary is a **tool call and its result**, and only when both sides' rules allow
it. Questions that span domains ("how exposed is the EU book to the rate move the US desk is
forecasting?") can then be answered by a planner on one member using tools on several, without
copying either domain's data into the other.

---

## 2. Goals and non-goals

**Goals**

- G1. A member discovers other members' tools automatically and builds proxy tools for those it
  may use; `tools/list` shows local and remote tools together.
- G2. Calling a remote tool is transparent to callers, planners, LLM tools, composites and
  workflows.
- G3. The remote member knows **which user** is calling, not only which server, and authorizes
  the call itself.
- G4. Each member decides what it exports (and to whom) and what it imports (and for whom).
- G5. Data residency rules can stop data leaving a boundary, in arguments as well as results.
- G6. Local tools always win over remote ones for an unqualified name; remote tools are never
  shadowed silently.
- G7. Every cross-member call is audited on both sides, linked by one trace id.
- G8. A member that is slow, down, revoked or compromised cannot take the others down or widen
  what anyone may do.

**Non-goals**

- Shared state between members. Each member keeps its own database, state store and memory;
  only catalogs and calls travel.
- A consensus protocol or leader election. Membership is configured and approved by people.
- Moving data in bulk between members. A fleet moves calls, not datasets.
- Replacing federation with third-party MCP servers; that stays as it is.

---

## 3. Vocabulary

These terms go into `GLOSSARY.md` when the feature is built.

| Term | Meaning |
|---|---|
| Fleet | A named group of SAJHA servers that share tools under each other's rules. |
| Member | One SAJHA server in a fleet, with a fleet-unique id (for example `risk-eu`). |
| Home member | The member that received the caller's request. |
| Host member | The member whose tool is being called. |
| Proxy tool | A tool in the home member's catalog that forwards calls to a host member's tool. |
| Export rules | A host member's rules for which tools it offers, to which members and for which roles. |
| Import rules | A home member's rules for which remote tools its users may see and what data may leave. |
| User assertion | A short-lived, signed statement from the home member naming the user a call is made for. |
| Data class | A label on data (for example `eu-personal`, `confidential`) used by residency rules. |
| Hop | One member-to-member forwarding step of a call. |

---

## 4. How it relates to federation

Federation (`sajha/federation/`) already does the hard part of one direction: a remote MCP
server's tools become `FederatedTool` entries (`sajha/federation/tool.py`), reached through the
same `execute_with_tracking` path as every SAJHA tool, with namespacing, approval, description
screening, the SSRF guard, circuit breakers, caching, rate limits and per-user token passthrough.

The fleet **reuses all of that** and adds what federation lacks:

| Concern | Federation today | Fleet adds |
|---|---|---|
| Who configures it | An administrator adds each upstream by hand | Members discover each other's tools automatically after joining |
| Direction | One way: SAJHA consumes an upstream | Symmetric: every member exports and imports |
| Who the remote side sees | The upstream's own credential for every caller, or the user's own SaaS token | The **SAJHA user**, carried in a signed assertion or an exchanged token (section 9) |
| Authorization at the remote side | Whatever the upstream does | The host member's export rules, access rules and policy engine, every call (section 10) |
| Data residency | Not modelled | Data classes on arguments and results, checked on both sides (section 11) |
| Audit | Local only | Both sides, linked by one trace id (section 15) |
| Planner awareness | A federated tool looks local | Locality, region, health and latency in the catalog (section 12) |

Implementation-wise, a fleet proxy is a subclass of the federated tool with a fleet connection
(member identity plus user identity) instead of an upstream credential; discovery, refresh,
namespacing and failure isolation are shared code.

---

## 5. Membership

### 5.1 Fleet and member identity

- A fleet has a name (`acme-fleet`). A member has an id unique in that fleet (`risk-eu`,
  `cust-na`), a base URL, a region and a set of labels (`domain: risk`, `jurisdiction: EU`).
- Each member has its own **key pair**. Members authenticate to each other with one of:
  - **mutual TLS** with certificates issued by a fleet certificate authority (recommended where
    the organisation runs a PKI);
  - **OAuth 2.1 client credentials with `private_key_jwt`**: the calling member signs a JWT
    with its private key and receives an access token from the host member's authorization
    server, which SAJHA already has (built-in or external).
- Member keys rotate on a schedule with an overlap window; a member can be **revoked** at once,
  which every other member honours on its next request.

### 5.2 Joining

Joining is deliberate and approved by people on both sides:

1. An administrator of member A creates a **join offer** for member B: a one-time token, valid
   for a short time, bound to B's expected id and URL.
2. B's administrator enters the offer. B and A exchange public keys and metadata over TLS,
   each verifying the other's id, URL and the token.
3. Both administrators see the pending peer on their fleet page and **approve** it. Until both
   approve, nothing is exchanged.
4. Each side records the peer with a **trust level** (section 6.3) and its role mapping
   (section 10.3).

### 5.3 Topology

- **Peer list.** Each member lists the peers it trusts. The expected fleet is about ten members,
  for which this is the right shape: at most nine peers per member.
  There is no gossip: a member only talks to peers it approved.
- **Registry (not planned at this size).** Only if a fleet grows well beyond that, one or more registry members hold the membership list
  and public keys; members still approve which peers they exchange tools with. The registry
  never holds tools, data or user credentials.

---

## 6. Catalog exchange

### 6.1 What a host member exports

For each tool its export rules allow a given peer to see, a host member publishes:

- the tool's name, description, `inputSchema`, `outputSchema` and annotations;
- its version and, if versioned, its deprecation state;
- fleet metadata: host member id, region, labels, data classes of its arguments and results
  (section 11), whether it is an LLM tool, an indicative latency and its health;
- a catalog hash, so a peer can tell whether anything changed.

Nothing else: no configuration, credentials, implementation details or usage data.

### 6.2 How catalogs travel

- **Pull.** Each member pulls each approved peer's catalog over MCP (`tools/list`, with the
  fleet metadata in `_meta`) using its member identity, at start-up and every
  `fleet.refresh_interval_seconds`, sending the last catalog hash so an unchanged catalog costs
  one small response.
- **Change notification.** A 2026-07-28 `subscriptions/listen` stream from each peer delivers
  `tools/list_changed`, so new and removed tools appear within seconds instead of at the next
  refresh.
- **Limits.** Catalog size, tool count per peer and description length are capped; a peer that
  exceeds them is flagged, and the excess is ignored.

### 6.3 Approval of imported tools

Descriptions and schemas from a peer are **untrusted text**: they are screened for injected
instructions (federation's screening), length-capped and checked for valid JSON Schema. Then,
according to the peer's trust level:

| Trust level | New tools from this peer |
|---|---|
| `auto` (default) | Become available at once if screening passes; a changed description or schema is applied at once too, and recorded in the audit log and on the fleet page |
| `review` | Wait on the fleet page for an administrator, as federation does today |
| `pinned` | Only tools an administrator listed by name are imported |

The owner's decision is that fleet members are trusted, so `auto` is the default. Screening stays
on anyway: it is cheap, and it limits the damage if a trusted member is ever compromised. Under
`review`, a tool whose description or schema changes after approval is held at its previous
approved version until reviewed.

---

## 7. Proxy tools and the unified catalog

### 7.1 Automatic proxies

For every approved remote tool the home member's import rules allow, SAJHA creates a **proxy
tool** in its registry automatically: the remote schemas, the remote annotations (corrected,
never widened: a remote tool is at least `openWorldHint: true`), and a fleet connection. When
the tool disappears from the peer's catalog, the proxy is removed; when the peer is unhealthy,
the proxy stays listed with its health for `fleet.unhealthy_grace_seconds` and calls fail fast,
then it is hidden until the peer recovers.

### 7.2 Names

| Name | Rule |
|---|---|
| Qualified name | Always `<member>__<tool>` (for example `risk-eu__var_calc`), the same `__` convention federation uses, valid for every LLM provider's tool-name rules. Planners, audit and metrics always record this name. |
| Bare alias | Offered in addition only when `fleet.bare_aliases` allows it **and** the bare name is unique across the home member's own tools and every imported tool, **or** an administrator pinned the alias to one member. |
| Collision with a local tool | The local tool keeps the bare name. The remote tool is reachable only by its qualified name. Reported on the fleet page. |
| Collision between two members | Neither gets the bare name unless an administrator pins one. Both stay reachable by qualified name. Reported. |
| Same name, different meaning | Prevented by the rules above: a bare name never silently switches from one implementation to another. If a pinned alias's tool changes its schema, the alias is suspended until reviewed. |

Local always wins, as requested, but a remote tool is never hidden behind a local one: it keeps
its qualified name, and the conflict is visible.

### 7.3 `tools/list` shows everything the caller may use

`tools/list`, the Tools page, the REST catalog and the Ask SAJHA shortlist show local tools and
proxies together, filtered as always by the caller's access, and now also by import rules.
Each proxy carries its fleet metadata in `_meta["io.sajha/fleet"]`:

```json
{ "member": "risk-eu", "region": "eu-west", "locality": "remote",
  "health": "ok", "latency_ms_p50": 85, "data_classes": { "results": ["confidential"] },
  "llm_tool": false }
```

The Tools page gains a member badge, a "local / remote" filter and a per-member filter. The
landing-page constellation can colour stars by member.

---

## 8. What happens on a call

```
caller ──► HOME member                                   HOST member
           1 access check (caller may call proxy)
           2 import rules (this user, this remote tool)
           3 argument validation (proxy's inputSchema)
           4 residency check on arguments (section 11)
           5 policy engine (deny / redact / approval / rate limit)
           6 breaker, rate limit, hop check (section 13)
           7 sign user assertion, attach member identity,
             trace id, hop count ─────────────────────────► 8 verify member identity, revocation
                                                            9 verify user assertion (signature,
                                                              audience, expiry, replay)
                                                           10 map user and roles (section 10.3)
                                                           11 export rules (this peer, this user)
                                                           12 its own access check and policy
                                                           13 execute the real tool; audit
           15 screen the result (untrusted text),  ◄────── 14 residency check on the result
              cap its size, validate outputSchema
           16 audit (linked by trace id), metrics
caller ◄── 17 result
```

- Both members' checks must pass; either can refuse. A refusal returns a normal tool error that
  says which side refused and why, in words safe to show the caller.
- Progress notifications and cancellation pass through: a caller's cancel reaches the host.
- Retries happen only for tools annotated read-only and idempotent; the result cache applies
  only to read-only tools with a `cache_ttl`, keyed by user where the host member says results
  differ per user.
- Destructive remote tools still require confirmation at the home member (MRTR or `confirm`
  fingerprints), and the host member may additionally require its own approval.

---

## 9. Identity

### 9.1 Member identity

Every request between members is authenticated as a member (section 5.1). A request from an
unknown, unapproved or revoked member is refused before anything else is read.

### 9.2 User identity

The host member must know which user the call is for; otherwise it can only authorize "member
A", and any user of A gets whatever A may do. Two modes, chosen per fleet:

**Mode A: token exchange through a shared identity provider (recommended where one exists).**
The home member exchanges the user's token at the organisation's identity provider for a token
for the host member (RFC 8693 token exchange): audience the host member, the user as subject, the
home member as actor, scopes narrowed to the tool. The host member validates it like any OAuth
token on its `/mcp` endpoint.

**Mode B: a fleet user assertion (when there is no shared identity provider).** The home member
signs a short JWT with its member key:

| Claim | Value |
|---|---|
| `iss` | home member id |
| `aud` | host member id |
| `sub` | the user's id at the home member |
| `roles`, `groups` | the user's roles and groups at the home member |
| `act` | `{ "sub": "<home member id>" }` |
| `tool` | the host tool's own name |
| `args_sha256` | hash of the canonical arguments, so the assertion cannot be reused for other arguments |
| `trace`, `hop` | trace id and hop count |
| `iat`, `exp` | issued now, expires within `fleet.assertion_ttl_seconds` (default 60) |
| `jti` | unique id; the host member keeps seen ids in its state store until expiry, so an assertion cannot be replayed |

**Callers who are not people.** An API-key caller travels as the key's owner, with the key's tool
patterns added as a ceiling the host member also enforces. Anonymous callers never cross: proxy
tools are not visible to them unless `fleet.anonymous_may_call_remote` is set, which is off by
default and refused for tools marked destructive.

**Connected accounts.** A user's linked SaaS tokens never leave their home member. A remote tool
that needs the user's token for a provider runs only on a member where that user has linked the
account; otherwise the host member answers "connect your account here", like federation's
token passthrough.

---

## 10. Authorization

### 10.1 Both sides decide, neither trusts the other

- The **home member** decides whether its user may use the remote tool and whether these
  arguments may leave (import rules, access rules, policy engine).
- The **host member** decides whether this peer, for this user, may run this tool (export rules,
  its own access rules mapped from the user's roles, its own policy engine and approvals).

The host member never accepts "member A says the user may": it applies its own rules to the user
the assertion names. This is what prevents a confused-deputy attack, where a member is used to
reach what its users could not reach directly.

### 10.2 Export and import rules

```yaml
fleet:
  export:                         # what this member offers
    - tools: ["var_*", "stress_*"]
      to_members: ["risk-*", "treasury-na"]
      for_roles: ["risk_analyst", "treasurer"]     # remote roles after mapping (10.3)
      require_approval: false
    - tools: ["*_delete*"]
      to_members: []                                # never exported
  import:                         # what this member's users may use
    - members: ["risk-eu"]
      tools: ["var_*"]
      for_roles: ["analyst"]
    - members: ["*"]
      tools: ["*"]
      for_roles: ["admin"]
```

Nothing is exported or imported unless a rule allows it. Rules are evaluated at catalog time (a
caller does not even see a proxy it may not call) and again at call time (rules can change
between the two).

### 10.3 Role mapping

Roles do not mean the same thing on every member. Each peer record carries a **role map** from
the peer's role names to local ones (`analyst@risk-eu → risk_analyst`). Unmapped roles map to
nothing. A host member never grants a remote user `admin` through mapping unless an
administrator mapped it explicitly, and the fleet page warns when someone does.

---

## 11. Data sovereignty and residency

Residency is about where data flows, in both directions.

- **Data classes.** A tool's schema can mark arguments and result fields with
  `x-sajha-data-class` (for example `eu-personal`, `confidential`, `public`); a whole tool can
  declare classes for its results. Members declare their jurisdiction labels.
- **Residency rules** are policy-engine rules with a new condition: *data of class C may (or may
  not) go to a member whose jurisdiction is J*. Examples: `eu-personal` never leaves members
  labelled `jurisdiction: EU`; `confidential` only to members in the same legal entity.
- **Arguments.** Before a call leaves (step 4), the home member checks the classes of the
  arguments' fields against the host member's labels. A planner cannot route EU personal data to
  a US tool by accident: the call is refused, and the planner is told why so it can choose a
  local alternative.
- **Results.** The host member checks its results' classes against the home member's labels
  before answering (step 14) and can refuse, redact (policy `redact`) or summarise.
- **What the home member keeps.** Conversation memory stores answers, which may now contain data
  from other members. Per data class, `fleet.memory.remote_results` decides whether such answers
  are stored as written, stored as a summary without the remote figures, or not stored.

---

## 12. Planners, LLM tools and memory

- **One catalog for planners.** The planner sees local and remote tools in one shortlist, with
  locality, region, health, indicative latency and data classes from the fleet metadata. Ranking
  adds small preferences: local over remote, healthy over degraded, same jurisdiction over
  different, so a remote tool is used when it is the right tool, not because it ranked first by
  wording.
- **Residency-aware shortlists.** Remote tools that residency rules would refuse for this caller
  are removed before planning, so the model is never offered a call that will be refused.
- **Remote LLM tools.** A host member's LLM tools ([LLM Tools](LLM%20Tools.md)) are exported
  like any tool (`fleet.allow_remote_llm_tools`, on by default: the owner decided LLM and plain
  tools are equally trusted). They run, plan and spend model budget
  on the host member, under its AI governance, with the user's identity. Their inner calls may
  use the host member's tools and, within the hop limit, other members' tools.
- **Memory is always local.** Conversation memory lives only on the member the user talks to. A
  remote tool, including a remote LLM tool, receives its arguments and nothing else: never the
  conversation, never another tool's results unless the planner put them in the arguments (and
  then residency rules apply to them).
- **Budgets.** Local limits (steps, tool calls, time, cost) count remote calls like local ones;
  the host member's own budgets apply to the work it does.

---

## 13. Hops and loops

- **No transitive re-export by default.** A member exports only its own tools, never proxies it
  imported (`fleet.reexport: false`). Without re-export, every remote call is exactly one hop.
- **When re-export is enabled**, each call carries a hop count and the list of members it has
  visited (in the assertion and a header). A member refuses a call that would exceed
  `fleet.max_hops` or revisit a member, so A → B → A loops cannot form.
- **Remote LLM tools** count toward both the LLM-tool depth limit and the hop limit.

---

## 14. Reliability

- **Per-peer isolation.** Connection pools, timeouts, circuit breakers and rate limits are per
  peer, so one slow or failing member affects only its own tools.
- **Health.** Each member probes its peers (and their catalogs) on a schedule and records health;
  the planner and the Tools page see it.
- **Graceful degradation.** A member that cannot reach the fleet still serves all its local tools;
  proxies fail fast with "member unavailable".
- **Version skew.** Members advertise a fleet protocol version alongside the MCP eras they speak;
  a member talks to a peer at the highest version both support and refuses peers below
  `fleet.min_protocol_version`.
- **Several workers.** Peer records and approvals live in the storage backend and the state store
  (as federation's do), so every worker of a member sees the same fleet.

---

## 15. Observability and audit

- **Linked audit.** Both members record the call in their own tamper-evident audit chains,
  sharing one trace id (W3C `traceparent`) and the assertion's `jti`. A cross-member call can be
  reconstructed by joining the two records, and neither member's records depend on the other's.
- **Tracing.** One trace spans home and host (OTLP), so latency per hop is visible.
- **Metrics.** `sajha_fleet_calls_total{peer,tool,outcome}`, latency per peer, refusals by side
  and reason (`import`, `export`, `residency`, `assertion`, `revoked`), catalog sizes and
  refresh results, peer health.
- **Fleet page.** Members and their health, pending joins and approvals, imported and exported
  tool counts, name conflicts, trust levels, role maps and the last refusals; a topology view of
  which members call which.

---

## 16. Threats and mitigations

| Threat | Mitigation |
|---|---|
| A rogue server pretends to be a member | Member authentication (mTLS or `private_key_jwt`) against approved peer keys; joining needs a one-time offer and approval on both sides |
| A compromised member impersonates users | Host members authorize the named user against their own export and access rules, never "the member says so"; role maps grant nothing by default; revocation is immediate |
| A captured assertion is replayed | Short expiry, audience bound to the host member, arguments hash, `jti` replay cache |
| A peer's description tries to instruct the model | Descriptions screened and capped; changes held for review; results treated as untrusted data (section 8 step 15) |
| A peer quietly changes what a tool does | Every description or schema change is recorded in the audit log with a diff and shown on the fleet page; pinned aliases are suspended until reviewed; under `review` trust the change is held at the last approved version |
| Data leaves its jurisdiction through arguments | Residency rules on arguments at the home member; on results at the host member; residency-aware shortlists |
| A member is used as a stepping stone (confused deputy) | Dual authorization on the user's identity; no re-export by default; hop limits |
| A slow member drags others down | Per-peer timeouts, breakers, pools and rate limits; local tools unaffected |
| SSRF through a peer URL | Federation's URL guard on peer URLs; peers are fixed at join time |
| Denial of service from a peer | Per-peer rate limits at the host member; catalog size caps |

---

## 17. Configuration

```yaml
fleet:
  enabled: false
  name: acme-fleet
  member_id: risk-eu
  base_url: https://sajha-risk-eu.example.internal
  region: eu-west
  labels: { domain: risk, jurisdiction: EU, entity: acme-eu }
  identity:
    method: mtls                    # mtls | private_key_jwt
    key_ref: file:/etc/sajha/fleet/member.key      # a secret reference, never a value
    ca_ref: file:/etc/sajha/fleet/ca.pem
  user_identity: assertion          # assertion | token_exchange
  token_exchange: { token_url: "", client_id: "", client_secret_ref: "" }
  assertion_ttl_seconds: 60
  refresh_interval_seconds: 300
  unhealthy_grace_seconds: 120
  default_timeout_seconds: 30
  bare_aliases: unique              # unique | pinned_only | off
  reexport: false
  max_hops: 1
  allow_remote_llm_tools: true     # LLM tools are shared like plain tools (owner decision)
  default_trust: auto               # auto | review | pinned, for newly joined peers (owner decision)
  anonymous_may_call_remote: false
  min_protocol_version: 1
  limits: { max_tools_per_peer: 2000, max_catalog_bytes: 5242880, max_description_chars: 1024 }
  memory: { remote_results: store }   # store | summary | none, per data class in rules
  export: []                        # section 10.2
  import: []                        # section 10.2
```

Peers, trust levels, role maps and approvals are managed on the fleet page and kept in the
storage backend, like federation's upstream records.

---

## 18. Storage

- **No new database tables in the first phases.** Peer records, approvals, role maps and catalog
  snapshots are JSON records in the storage backend, alongside federation's; nothing needs a
  schema change, which keeps the no-migrations rule simple for operators.
- **State store:** the assertion replay cache, catalog hashes, peer health and per-peer rate
  counters (shared across a member's workers).
- **Audit:** the existing audit tables, with the trace id and peer id in each record.

---

## 19. Testing

- **Multi-member tests in one process:** two or three SAJHA apps with separate databases and
  keys, joined into a fleet, exchanging catalogs and calling each other.
- **Identity:** wrong member key, revoked member, expired, mis-addressed, replayed or
  argument-mismatched assertions are refused; token exchange against a test identity provider.
- **Authorization:** a user without access at the host member is refused even when the home
  member allows it, and the reverse; role maps; anonymous callers.
- **Names:** local wins; collisions between members; pinned aliases; schema change suspends an
  alias.
- **Residency:** arguments and results of each data class to members of each jurisdiction;
  residency-aware shortlists.
- **Resilience:** a member down, slow, flapping or returning oversized catalogs; local tools keep
  working.
- **Planners:** a question needing tools on two members is answered; memory stays on the home
  member.
- **Conformance:** both MCP suites stay green on every member.

---

## 20. Build plan

Each phase ends green: full suite, multi-member tests, both conformance suites.

| Phase | Scope |
|---|---|
| 1 | Member identity and keys, join offers and two-sided approval, peer records, revocation; fleet page (members, pending joins) |
| 2 | Catalog exchange (pull, hashes, `subscriptions/listen`), screening and trust levels, automatic proxy tools, qualified names and alias rules, `tools/list` with fleet metadata, Tools page badges and filters |
| 3 | Calls: user assertions (and token exchange), host-side verification, export and import rules, role maps, linked audit and tracing, metrics, per-peer isolation |
| 4 | Residency: data classes, residency rules on arguments and results, residency-aware shortlists, memory handling of remote results |
| 5 | Planners and LLM tools: locality-aware ranking, remote LLM tools (shared from the first release with this phase), hop and depth limits combined |
| 6 | Re-export with hop limits, topology view (a registry member only if a fleet outgrows peer lists) |
| 7 | Docs: this note becomes as-built; glossary; tutorial ("two domains, one question"); Security Model; Configuration and API Reference; help card; CHANGELOG |

---

## 21. Competitive position

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

## 22. Decisions for the owner

**Decided**

- **Size:** about ten members. Peer lists, no registry (section 5.3).
- **Trust:** members' tools are trusted, LLM tools and plain tools alike. New peers default to
  `auto` trust and remote LLM tools are on (sections 6.3 and 12). Screening stays on as a
  safeguard against a compromised member.

**Still open**

1. **User identity.** Is there a shared enterprise identity provider across domains (token
   exchange), or should fleet assertions be the default?
2. **Member authentication.** mTLS with an organisation CA, or `private_key_jwt`?
3. **Bare aliases** for unique remote names on by default (`unique`, recommended) or only when
   pinned?

---

## 23. Alternatives considered

| Alternative | Why not |
|---|---|
| One central SAJHA with every tool | Moves every domain's credentials and data access into one place; the boundary sovereignty requires disappears |
| Gossip-based membership | Unpredictable who talks to whom; harder to approve and audit; unnecessary at tens of members |
| Server-to-server trust only (no user identity) | The host member can only authorize "member A", so any user of A gets all of A's access: a confused deputy by design |
| Shared database or state store across members | Couples members' availability and crosses the data boundary the fleet exists to keep |
| Remote tools under their bare names, local wins | Silent shadowing: the same name could mean different tools on different members, and a planner would not know which it called |
| Copying tool definitions and running them locally | The tool would run outside its data's boundary with copied credentials, defeating sovereignty |
