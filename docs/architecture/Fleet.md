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
- G9. Members come and go without manual peer configuration: arrivals, clean departures and
  failures are detected automatically.

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
| Data class | A label on data (for example `eu-personal`, `confidential`) used by residency rules. |
| Hop | One member-to-member forwarding step of a call. |
| Gossip | The protocol members use to discover each other, detect arrivals, departures and failures, and spread digests of what changed. |
| Seed member | A member a starting member contacts first to learn the fleet. |
| Incarnation | A member's own counter that makes newer news about it override older news. |
| Identity resolver | The pluggable part that turns a caller into credentials on the home member and back into a verified user on the host member. |
| Fleet key directory | Every member's synced copy of the API key records (hashes, never keys) issued across the fleet. |
| User assertion | (later resolver) A short-lived JWT signed by the home member naming the user. |

---

## 4. How it relates to federation

Federation (`sajha/federation/`) already does the hard part of one direction: a remote MCP
server's tools become `FederatedTool` entries (`sajha/federation/tool.py`), reached through the
same `execute_with_tracking` path as every SAJHA tool, with namespacing, approval, description
screening, the SSRF guard, circuit breakers, caching, rate limits and per-user token passthrough.

The fleet **reuses all of that** and adds what federation lacks:

| Concern | Federation today | Fleet adds |
|---|---|---|
| Who configures it | An administrator adds each upstream by hand | Members find each other by gossip, admitted by a fleet certificate, and exchange tools automatically (section 5) |
| Direction | One way: SAJHA consumes an upstream | Symmetric: every member exports and imports |
| Who the remote side sees | The upstream's own credential for every caller, or the user's own SaaS token | The **SAJHA user**, identified by their API key and checked against a synced key directory (section 9) |
| Authorization at the remote side | Whatever the upstream does | The host member's export rules, access rules and policy engine, every call (section 10) |
| Data residency | Not modelled | Data classes on arguments and results, checked on both sides (section 11) |
| Audit | Local only | Both sides, linked by one trace id (section 15) |
| Planner awareness | A federated tool looks local | Locality, region, health and latency in the catalog (section 12) |

Implementation-wise, a fleet proxy is a subclass of the federated tool with a fleet connection
(member identity plus user identity) instead of an upstream credential; discovery, refresh,
namespacing and failure isolation are shared code.

---

## 5. Membership

Members find each other, notice when one arrives or leaves, and agree on who is in the fleet
through a **gossip protocol**. No administrator has to add each peer by hand, and no central
server is needed.

### 5.1 Fleet and member identity

- A fleet has a name (`acme-fleet`). A member has an id unique in that fleet (`risk-eu`,
  `cust-na`), a base URL, a region and labels (`domain: risk`, `jurisdiction: EU`).
- **Admission is by certificate.** The fleet has its own certificate authority. Each member
  holds a key pair and a certificate signed by the fleet CA whose subject names the fleet and
  the member id. Every request between members is mutual TLS, and a member accepts a peer only
  if its certificate chains to the fleet CA, names the same fleet, and is not on the fleet's
  revocation list. Holding such a certificate is what makes a server a member: there is no
  separate approval step, which is how members can come and go automatically.
- **Revocation.** A fleet administrator removes a member by adding its id (or certificate
  serial) to the revocation list, which is signed with the fleet CA's key and spread by gossip
  (section 5.3). Every member checks it on every request.
- **Rotation.** Member certificates are short-lived (default 30 days) and renewed before
  expiry; old and new are both accepted during an overlap window.

### 5.2 Coming in and going out

| Event | What happens |
|---|---|
| A member starts | It contacts any of its configured **seed members** (one or two are enough), presents its certificate, and receives the current member list. Its arrival spreads to everyone within a few gossip rounds; each member then pulls its catalog and key directory (sections 6 and 9.3). |
| A member stops cleanly | It gossips a `leave` message. Others mark it `left` at once and remove its proxy tools after `fleet.unhealthy_grace_seconds`. |
| A member crashes or is cut off | The failure detector (section 5.3) marks it `suspect`, then `dead` if no one can reach it within `suspect_timeout_seconds`. Its proxy tools stay listed as unavailable during the grace period, then are hidden. |
| A member comes back | It rejoins with a higher **incarnation** number, which overrides any stale `suspect` or `dead` entry about it. |
| A member is revoked | Its id is on the signed revocation list; every member refuses it and removes its tools, wherever the list reaches first. |

A server whose certificate is not from the fleet CA cannot join, gossip or call anyone, however
it learned the addresses.

### 5.3 The gossip protocol

The protocol follows the SWIM design (scalable, weakly consistent, infection-style membership),
which needs no leader and costs a few small messages per member per second. At about ten
members it is far more than enough.

- **Membership list.** Each member keeps an entry per member: id, URL, region, labels,
  `incarnation`, state (`alive`, `suspect`, `dead`, `left`) and digests (catalog hash, key
  directory version). Entries merge by (incarnation, state precedence), so every member
  converges on the same list without coordination.
- **Failure detection.** Every `gossip_interval_ms` a member pings one other member chosen at
  random. If there is no answer within `ping_timeout_ms`, it asks `indirect_probes` other members
  to ping it on its behalf (so one broken link does not condemn a healthy member). No answer at
  all makes it `suspect`; a suspect that does not refute (by gossiping a higher incarnation)
  within `suspect_timeout_seconds` becomes `dead`.
- **Dissemination.** Changes (joins, leaves, suspicions, new digests, revocations) ride on the
  ping messages, each change repeated a bounded number of times (about `3 × log2(n)`), so news
  reaches every member in a few rounds.
- **Anti-entropy.** Every `full_sync_interval_seconds` a member exchanges its whole membership
  list and digests with one random member, which repairs anything a lost message missed.
- **Transport.** Gossip messages are small HTTPS POSTs over the same mutual TLS as calls, not
  UDP, so they pass through Kubernetes services, ingress and corporate proxies unchanged.
- **Digests trigger pulls.** Gossip carries only digests. When a member sees a peer's catalog
  hash or key-directory version change, it pulls the changed part from that peer (sections 6.2
  and 9.3). Gossip never carries tools, schemas or keys themselves.
- **One gossip agent per member.** A member running several workers elects one of them to run
  the agent, through a lease in the state store (the same claim mechanism workflow cron uses);
  the membership list is kept in the state store so every worker sees the same fleet. If the
  agent's worker dies, another takes the lease.
- **No split-brain hazard.** Members never need to agree on anything beyond membership: each
  call is point to point and authorized by the host. Two members that briefly see different
  lists only disagree about which proxies to show.

### 5.4 Manual mode

Where a fleet CA is not available, peers can still be added by hand with a one-time join offer
approved on both sides (the earlier design). Gossip then runs among the approved peers only.

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

- **Digest, then pull.** Every member's catalog hash travels in gossip (section 5.3). When a
  member sees a new hash for a peer (or a new peer), it pulls that peer's catalog over MCP
  (`tools/list`, with the fleet metadata in `_meta`) using its member identity. An unchanged
  catalog is never transferred.
- **Fallback refresh.** Every `fleet.refresh_interval_seconds` a member also re-pulls any peer
  whose catalog it has not checked in that time, in case a digest was missed.
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
           7 identity resolver: attach the user's API key;
             mutual TLS, trace id, hop count ──────────────► 8 verify member certificate, revocation
                                                            9 identity resolver: hash the key, look
                                                              it up in the fleet key directory, check
                                                              enabled, expiry, home member
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

Every request between members is mutual TLS with a fleet certificate (section 5.1). A request
from a server without one, or from a revoked member, is refused before anything else is read.

### 9.2 User identity: a pluggable resolver, API keys first

The host member must know which user a call is for; otherwise it can only authorize "member A",
and any user of A gets whatever A may do.

How the user is identified across members is a **pluggable resolver** with two halves:

- on the home member, `outbound(caller) → credentials to attach to the forwarded call`;
- on the host member, `inbound(request) → a verified fleet user` (user id, home member,
  roles, tool allowlist) or a refusal.

The resolver is chosen by `fleet.user_identity`. **The first implementation is `api_key`**, as
the owner decided; `assertion` (a member-signed JWT) and `token_exchange` (RFC 8693 through a
shared identity provider) are later implementations of the same interface, so switching needs no
change anywhere else.

**`api_key`: the user's API key is their fleet identity.**

1. A user (or a script, or an agent) holds an API key issued by **one** member, their home
   member, and calls SAJHA there.
2. The home member verifies the key: first in its database as it does today, then in its
   persistent key file if the database does not know it or is unavailable (section 18.3);
   either way the hash, enabled flag, expiry and tool allowlist are checked.
3. When the call goes to a proxy tool, the home member forwards the **key itself** to the host
   member in a dedicated header, over the mutual-TLS connection, together with the trace id and
   hop count.
4. The host member hashes the key and looks it up in its **fleet key directory** (section 9.3,
   which includes keys from members' persistent key files),
   a synced copy of every member's key records. It checks that the record exists, is enabled,
   is not expired or revoked, and that the request came **from the key's home member** (a key can
   only enter the fleet through the member that issued it).
5. The verified fleet user is the key's owner, with the owner's roles as recorded by the home
   member, mapped to local roles (section 10.3), and the key's tool allowlist as an extra
   ceiling. Authorization then proceeds as in section 10.

**Handling rules for forwarded keys.** The raw key exists only in memory during the call: it is
never logged, never written to the audit log (the key's id and prefix are), never stored, never
put in a trace attribute, and never forwarded onward when re-export is on (a further hop gets
the key id inside a member-signed assertion instead). Only mutual-TLS connections may carry it.

**Why forward the key rather than only its id.** Forwarding lets the host member verify the
user's possession of the key independently, against its own synced copy, instead of trusting
the home member's word. The cost is that every member sees every forwarded key in transit, so a
compromised member could capture keys from calls that reach it. That is acceptable for a fleet
whose members are trusted (an owner decision, section 22); a fleet that wants to remove that
exposure switches the resolver to `assertion`, where only a key id signed by the home member
crosses, without other changes.

**Anonymous callers** never cross: proxy tools are not visible to them unless
`fleet.anonymous_may_call_remote` is set (off by default, refused for destructive tools).
Signed-in console users without an API key reach remote tools through the same resolver once the
home member issues them a short-lived, fleet-scoped key automatically; that comes with the
`assertion` resolver.

**Connected accounts.** A user's linked SaaS tokens never leave their home member. A remote tool
that needs the user's token for a provider runs only on a member where that user has linked the
account; otherwise the host member answers "connect your account here", as federation's token
passthrough does.

### 9.3 The fleet key directory

Each member publishes the records of the API keys it issued, and every member keeps a synced
copy of everyone's: the **fleet key directory**.

| Field | Meaning |
|---|---|
| `key_id`, `key_prefix`, `name` | the key's identity, as in the issuing member's `api_keys` table |
| `key_hash` | the SHA-256 hash SAJHA already stores; **the raw key is never synced** |
| `home_member` | the member that issued it and is its only authority |
| `owner` | the owner's user id, display name and role names at the home member |
| `enabled`, `expires_at`, `revoked_at` | its current state |
| `tool_access_mode`, `tool_access_list` | its tool allowlist |
| `version`, `updated_at` | a counter the home member increments on every change |
| `signature` | the home member's signature over the record, so no other member can forge or alter it |

**How it syncs.** Each member's directory has a version (the highest record version it issued).
Gossip carries every member's directory version in its digest (section 5.3). When a member sees
a newer version for a peer, it pulls only the records changed since the version it holds, from
that peer, verifies each record's signature against the peer's certificate, and stores them. A
full comparison runs during anti-entropy, so a missed update is repaired within
`full_sync_interval_seconds`.

**Revocation is fast where it matters.** Disabling or revoking a key takes effect on its home
member at once, and a forwarded key can only arrive from its home member (step 4 above), so a
revoked key stops working across the fleet immediately even before the directory update has
spread. Revocations are also gossiped with priority, so every member's copy follows within a
few rounds.

**Ownership.** Only the home member can change a key's record; a record for `risk-eu`'s key that
arrives from anyone else, or that is not signed by `risk-eu`, is ignored. When a member leaves
or is revoked, its keys are marked unusable in every directory.

**What it costs.** One row per API key in the fleet, a few hundred bytes each, stored in a new
table (section 18) so lookups by hash are indexed and local key administration is unaffected.

---

## 10. Authorization

### 10.1 Both sides decide, neither trusts the other

- The **home member** decides whether its user may use the remote tool and whether these
  arguments may leave (import rules, access rules, policy engine).
- The **host member** decides whether this peer, for this user, may run this tool (export rules,
  its own access rules mapped from the user's roles, its own policy engine and approvals).

The host member never accepts "member A says the user may": it applies its own rules to the user
the identity resolver verified (section 9.2). This is what prevents a confused-deputy attack, where a member is used to
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
  visited (in headers carried over mutual TLS). A member refuses a call that would exceed
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
  sharing one trace id (W3C `traceparent`) and the API key's id. A cross-member call can be
  reconstructed by joining the two records, and neither member's records depend on the other's.
- **Tracing.** One trace spans home and host (OTLP), so latency per hop is visible.
- **Metrics.** `sajha_fleet_calls_total{peer,tool,outcome}`, latency per peer, refusals by side
  and reason (`import`, `export`, `residency`, `identity`, `revoked`), catalog sizes and
  refresh results, peer health.
- **Fleet page.** Members and their health, pending joins and approvals, imported and exported
  tool counts, name conflicts, trust levels, role maps and the last refusals; a topology view of
  which members call which.

---

## 16. Threats and mitigations

| Threat | Mitigation |
|---|---|
| A rogue server pretends to be a member | Mutual TLS with certificates from the fleet CA only; the signed revocation list is checked on every request; gossip from a server without a fleet certificate is refused |
| A compromised member impersonates users | Host members authorize the named user against their own export and access rules, never "the member says so"; role maps grant nothing by default; revocation is immediate |
| A forwarded API key is captured | Keys travel only over mutual TLS, are never logged, stored or traced, and are accepted only from their home member, so a captured key cannot be replayed through another member; a fleet that wants no key in transit switches to the `assertion` resolver (section 9.2) |
| The persistent key file or a snapshot is copied | Hashes only, never keys; owner-only permissions; git-ignored; snapshots carry hashes only for persistent keys |
| Snapshots are edited or deleted to hide a change | Each snapshot chains to the previous one and is signed by the member; rotation and every snapshot run are audited |
| A member forges or alters another member's key records | Every directory record is signed by its home member and ignored otherwise; only the home member may change its records |
| False gossip (a healthy member reported dead, a fake member advertised) | Indirect probes before suspicion; a member refutes suspicion itself with a higher incarnation; only certificate-holding members can gossip, and a member's details are accepted only from itself or as gossip about a certificate-verified member |
| A peer's description tries to instruct the model | Descriptions screened and capped; changes held for review; results treated as untrusted data (section 8 step 15) |
| A peer quietly changes what a tool does | Every description or schema change is recorded in the audit log with a diff and shown on the fleet page; pinned aliases are suspended until reviewed; under `review` trust the change is held at the last approved version |
| Data leaves its jurisdiction through arguments | Residency rules on arguments at the home member; on results at the host member; residency-aware shortlists |
| A member is used as a stepping stone (confused deputy) | Dual authorization on the user's identity; no re-export by default; hop limits |
| A slow member drags others down | Per-peer timeouts, breakers, pools and rate limits; local tools unaffected |
| SSRF through a peer URL | Federation's URL guard on every peer URL learned from gossip; a URL must match the host name in the member's certificate |
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
  identity:                         # mutual TLS with a fleet-CA certificate (section 5.1)
    cert_ref: file:/etc/sajha/fleet/member.crt
    key_ref: file:/etc/sajha/fleet/member.key      # secret references, never values
    ca_ref: file:/etc/sajha/fleet/ca.pem
    revocation_list_ref: file:/etc/sajha/fleet/revoked.json   # signed; also spread by gossip
  user_identity: api_key            # api_key (first) | assertion | token_exchange (section 9.2)
  key_directory: { sync: true, full_sync_interval_seconds: 300 }
  persistent_keys: { file: config/apikeys.json, reload: true }   # section 18.3
  snapshots: { enabled: true, interval_minutes: 10, keep: 20, dir: data/fleet/snapshots, compress: false, to_siem: false }   # section 18.4
  gossip:
    seeds: [https://sajha-treasury-na.example.internal, https://sajha-cust-eu.example.internal]
    gossip_interval_ms: 1000
    ping_timeout_ms: 500
    indirect_probes: 3
    suspect_timeout_seconds: 10
    full_sync_interval_seconds: 30
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

Membership is discovered by gossip. Trust levels, role maps and any manual-mode peers are managed
on the fleet page and kept in the storage backend, like federation's upstream records.

---

## 18. Storage

### 18.1 Database

- **One new table, `fleet_api_keys`,** for the fleet key directory (section 9.3): one row per key
  issued anywhere in the fleet, indexed by key hash, holding the record fields and its home
  member's signature. It is added to both schema files (no migrations: operators run the
  `CREATE TABLE` on PostgreSQL; SQLite creates it) and kept apart from the local `api_keys`
  table, so local key administration is unchanged.

### 18.2 Storage backend and state store

- **Storage backend:** trust levels, role maps, manual-mode peers and catalog snapshots as JSON
  records, alongside federation's.
- **State store:** the membership list and incarnations, the gossip agent's lease, catalog and
  directory digests, peer health and per-peer rate counters (shared across a member's workers).

### 18.3 Persistent API keys in a file

API keys live in the database, which can be lost: a corrupted SQLite file, a dropped PostgreSQL
schema, a restore gone wrong. Some keys must keep working anyway: the key an automation uses to
reach SAJHA, an administrator's break-glass key, the keys other systems depend on. Each member
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
  written to the audit log.
- **Protection.** The file is created with owner-only permissions and is git-ignored; a tracked
  a tracked example file next to it documents the format. A hash of a long random key cannot be
  reversed, but the file still names users and their access, so it is treated as sensitive.
- **In the fleet.** Persistent keys are part of the member's key directory like any other key, so
  every member can verify them too.
- **Today's file.** `config/apikeys.json` currently holds a plaintext demo key that nothing reads
  (Roadmap item N5). This design replaces it with the hashed format above; the demo key is not
  carried over.

### 18.4 Periodic snapshots

Every member writes a **snapshot** of what it knows every `snapshots.interval_minutes` (default
10) and keeps the last `snapshots.keep` (default 20), so an auditor can see who and what existed
at any point in the retained window, and a member can be rebuilt after losing its database.

- **Contents.**
  - Users: id, user name, roles, enabled (no password hashes).
  - API keys issued by this member: the record fields of section 18.3 for every key, persistent
    or not; hashes only for persistent keys, so a snapshot alone cannot verify ordinary keys.
  - Tools: every local tool (name, version, schema hash, enabled) and every proxy tool (name,
    host member, version, schema hash, trust level).
  - Fleet view: members and their states, incarnations and labels as this member saw them, and
    the key directory's version per member.
- **Format and place.** One JSON file per snapshot, named with the UTC time and a sequence number,
  in `data/fleet/snapshots/` (or the storage backend), owner-only permissions, optionally
  compressed.
- **Tamper evidence.** Each snapshot records the SHA-256 of the previous one and is signed with
  the member's key, so a deleted, reordered or edited snapshot is detected, the same idea as the
  audit chain. A snapshot run is also an audit event.
- **Rotation.** After writing a snapshot, the oldest beyond `keep` are deleted (and their deletion
  audited). Twenty snapshots ten minutes apart cover a little over three hours; for longer
  history each snapshot can also be sent to the SIEM export, which keeps it under the SIEM's own
  retention.
- **One writer.** With several workers, the gossip agent's lease holder writes the snapshot, so a
  member produces exactly one per interval.
- **Restoring.** After a database loss, an administrator can re-create users, roles and key
  records from a chosen snapshot (keys come back only if they were persistent, since only those
  snapshots carry hashes); tools and fleet state rebuild themselves from configuration and gossip.

---

## 19. Testing

- **Multi-member tests in one process:** two or three SAJHA apps with separate databases and
  keys, joined into a fleet, exchanging catalogs and calling each other.
- **Membership:** joins through a seed, clean leaves, crashes detected through indirect probes,
  false suspicion refuted, rejoin with a higher incarnation, revocation spreading, a server
  without a fleet certificate refused; a network split heals through anti-entropy.
- **Identity:** a forwarded key verified against the directory; unknown, disabled, expired or
  revoked keys refused; a key arriving from a member other than its home refused; directory
  records with bad signatures ignored; the raw key absent from logs, audit and traces.
- **Persistent keys and snapshots:** a persistent key works with the database removed; database
  revocation overrides the file; an edited file reloads; snapshots appear every interval, only
  `keep` are kept, the chain detects an edited or missing snapshot, one writer across workers;
  users and keys restore from a snapshot.
- **Key directory sync:** a new or changed key reaches every member; a missed update repaired by
  anti-entropy; a leaving member's keys become unusable.
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
| 1 | Membership: fleet CA certificates and mutual TLS, revocation list, gossip agent (SWIM failure detection, dissemination, anti-entropy, seeds, incarnations, leases across workers); fleet page (members and their states) |
| 2 | Catalog exchange driven by gossip digests, screening and trust levels, automatic proxy tools, qualified names and alias rules, `tools/list` with fleet metadata, Tools page badges and filters |
| 3 | Identity resolver interface; the `api_key` resolver; the fleet key directory with signed records, digest-driven sync and the `fleet_api_keys` table in both schema files; host-side verification; persistent key file and periodic snapshots (these two also benefit a SAJHA that is not in a fleet); export and import rules, role maps; linked audit and tracing; metrics; per-peer isolation |
| 4 | Residency: data classes, residency rules on arguments and results, residency-aware shortlists, memory handling of remote results |
| 5 | Planners and LLM tools: locality-aware ranking, remote LLM tools, hop and depth limits combined |
| 6 | Re-export with hop limits; the `assertion` and `token_exchange` resolvers; topology view |
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

- **Size:** about ten members; no registry (section 5).
- **Trust:** members' tools are trusted, LLM tools and plain tools alike. New peers default to
  `auto` trust and remote LLM tools are on (sections 6.3 and 12). Screening stays on as a
  safeguard against a compromised member.
- **Membership by gossip:** members discover each other and detect arrivals and departures
  automatically (section 5), which makes admission by fleet certificate and mutual TLS the
  member authentication.
- **User identity:** the user's API key, issued by one member, is forwarded with the call and
  checked against a fleet key directory synced to every member; the identity resolver is
  pluggable so assertions or token exchange can replace it later (section 9).

- **Persistent keys and snapshots:** API keys can also live in `config/apikeys.json` so they
  survive a lost database; every member snapshots users, keys and tools every 10 minutes and
  keeps 20 (section 18).

**Still open**

1. **Who runs the fleet CA** and issues member certificates (an existing organisation PKI, or a
   small CA SAJHA provides with a command to issue and revoke member certificates)?
2. **Console users without API keys:** wait for the `assertion` resolver, or issue them
   short-lived fleet-scoped keys sooner?
3. **Bare aliases** for unique remote names on by default (`unique`, recommended) or only when
   pinned?

---

## 23. Alternatives considered

| Alternative | Why not |
|---|---|
| One central SAJHA with every tool | Moves every domain's credentials and data access into one place; the boundary sovereignty requires disappears |
| Membership configured by hand on every member | Ten members means up to ninety peer entries to keep consistent; arrivals and failures go unnoticed. Gossip with certificate admission keeps who-may-join a deliberate act (issuing a certificate) while making everything after it automatic |
| A central registry for membership | One more service to run and keep available; not needed at about ten members |
| Syncing raw API keys | Every member would store every key; a single compromised database leaks keys usable everywhere. Only hashes and signed records are synced |
| Server-to-server trust only (no user identity) | The host member can only authorize "member A", so any user of A gets all of A's access: a confused deputy by design |
| Shared database or state store across members | Couples members' availability and crosses the data boundary the fleet exists to keep |
| Remote tools under their bare names, local wins | Silent shadowing: the same name could mean different tools on different members, and a planner would not know which it called |
| Copying tool definitions and running them locally | The tool would run outside its data's boundary with copied credentials, defeating sovereignty |
