# SAJHA Fleet

> **Status: design, not built.** This note is the design for a **fleet**: several SAJHA
> servers that share their tools with one another while each keeps its own data, credentials,
> policy, AI layer and conversation memory. It extends [Federation](Federation.md), which
> today brings other MCP servers' tools into one SAJHA by hand. It is item L16 on the
> [Roadmap](Roadmap.md).

A SAJHA server configured as a **instance** of a fleet automatically learns which tools the other
instances offer, and builds a **proxy tool** for each one it is allowed to use. The proxy appears
in its catalog next to its own tools. When a caller (a person, an MCP client, a planner, an LLM
tool, a workflow) calls a proxy, SAJHA forwards the call to the instance that hosts the tool, as
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
16. [The fleet console](#16-the-fleet-console)
17. [Threats and mitigations](#17-threats-and-mitigations)
18. [Configuration](#18-configuration)
19. [Storage](#19-storage)
20. [Testing](#20-testing)
21. [Build plan](#21-build-plan)
22. [Competitive position](#22-competitive-position)
23. [Decisions for the owner](#23-decisions-for-the-owner)
24. [Alternatives considered](#24-alternatives-considered)

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
- G6. Local tools always win over remote ones for an unqualified name; remote tools are never
  shadowed silently.
- G7. Every cross-instance call is audited on both sides, linked by one trace id.
- G8. An instance that is slow, down, revoked or compromised cannot take the others down or widen
  what anyone may do.
- G9. Instances come and go without manual peer configuration: arrivals, clean departures and
  failures are detected automatically.

**Non-goals**

- Shared state between instances. Each instance keeps its own database, state store and memory;
  only catalogs and calls travel.
- A consensus protocol or leader election. Membership is configured and approved by people.
- Moving data in bulk between instances. A fleet moves calls, not datasets.
- Replacing federation with third-party MCP servers; that stays as it is.

---

## 3. Vocabulary

These terms go into `GLOSSARY.md` when the feature is built.

| Term | Meaning |
|---|---|
| Fleet | A named group of SAJHA servers that share tools under each other's rules. |
| Instance | One SAJHA server in a fleet, with a fleet-unique id (for example `risk-eu`). |
| Home instance | The instance that received the caller's request. |
| Host instance | The instance whose tool is being called. |
| Proxy tool | A tool in the home instance's catalog that forwards calls to a host instance's tool. |
| Export rules | A host instance's rules for which tools it offers, to which instances and for which roles. |
| Import rules | A home instance's rules for which remote tools its users may see and what data may leave. |
| Data class | A label on data (for example `eu-personal`, `confidential`) used by residency rules. |
| Hop | One instance-to-instance forwarding step of a call. |
| Gossip | The protocol instances use to discover each other, detect arrivals, departures and failures, and spread digests of what changed. |
| Instance name | An instance's name, set in its own configuration and unique in the fleet. |
| Fleet user | A user at an instance, written `user@instance`; the same person may be a different user on each instance. |
| Default API key | The API key every user always has; kept encrypted at its home instance so it can be forwarded. |
| Host and tool table | Each instance's record of which instance hosts which remote tool. |
| Block | An administrator's local decision to stop calls to or from another instance, a tool or a remote user. |
| Seed instance | An instance a starting instance contacts first to learn the fleet. |
| Incarnation | An instance's own counter that makes newer news about it override older news. |
| Identity resolver | The pluggable part that turns a caller into credentials on the home instance and back into a verified user on the host instance. |
| Fleet key directory | Every instance's synced copy of the API key records (hashes, never keys) issued across the fleet. |
| User assertion | (later resolver) A short-lived JWT signed by the home instance naming the user. |

---

## 4. How it relates to federation

Federation (`sajha/federation/`) already does the hard part of one direction: a remote MCP
server's tools become `FederatedTool` entries (`sajha/federation/tool.py`), reached through the
same `execute_with_tracking` path as every SAJHA tool, with namespacing, approval, description
screening, the SSRF guard, circuit breakers, caching, rate limits and per-user token passthrough.

The fleet **reuses all of that** and adds what federation lacks:

| Concern | Federation today | Fleet adds |
|---|---|---|
| Who configures it | An administrator adds each upstream by hand | Instances find each other by gossip, admitted by a fleet certificate, and exchange tools automatically (section 5) |
| Direction | One way: SAJHA consumes an upstream | Symmetric: every instance exports and imports |
| Who the remote side sees | The upstream's own credential for every caller, or the user's own SaaS token | The **SAJHA user**, identified by their API key and checked against a synced key directory (section 9) |
| Authorization at the remote side | Whatever the upstream does | The host instance's export rules, access rules and policy engine, every call (section 10) |
| Data residency | Not modelled | Data classes on arguments and results, checked on both sides (section 11) |
| Audit | Local only | Both sides, linked by one trace id (section 15) |
| Planner awareness | A federated tool looks local | Locality, region, health and latency in the catalog (section 12) |

Implementation-wise, a fleet proxy is a subclass of the federated tool with a fleet connection
(instance identity plus user identity) instead of an upstream credential; discovery, refresh,
namespacing and failure isolation are shared code.

---

## 5. Membership

Instances find each other, notice when one arrives or leaves, and agree on who is in the fleet
through a **gossip protocol**. No administrator has to add each peer by hand, and no central
server is needed.

### 5.1 Fleet and instance identity

- A fleet has a name (`acme-fleet`). Each instance is identified by its **instance name**, set in
  that instance's own configuration (`fleet.instance_name`, for example `risk-eu` or `cust-na`)
  and unique in the fleet. The instance name is what gossip, the console, audit records, user
  identities (`alice@risk-eu`) and qualified tool names (`risk-eu__var_calc`) use. An instance
  also has a base URL, a region and labels (`domain: risk`, `jurisdiction: EU`).
- **Admission is by certificate.** The fleet has its own certificate authority. Each instance
  holds a key pair and a certificate signed by the fleet CA whose subject names the fleet and
  the instance name, so an instance cannot claim a name it was not issued. Every request between instances is mutual TLS, and an instance accepts a peer only
  if its certificate chains to the fleet CA, names the same fleet, and is not on the fleet's
  revocation list. Holding such a certificate is what makes a server an instance: there is no
  separate approval step, which is how instances can come and go automatically.
- **Revocation.** A fleet administrator removes an instance by adding its instance name (or certificate
  serial) to the revocation list, which is signed with the fleet CA's key and spread by gossip
  (section 5.3). Every instance checks it on every request.
- **Rotation.** Instance certificates are short-lived (default 30 days) and renewed before
  expiry; old and new are both accepted during an overlap window.

### 5.2 Coming in and going out

| Event | What happens |
|---|---|
| An instance starts | It contacts any of its configured **seed instances** (one or two are enough), presents its certificate, and receives the current instance list. Its arrival spreads to everyone within a few gossip rounds; each instance then pulls its catalog and key directory (sections 6 and 9.3). |
| An instance stops cleanly | It gossips a `leave` message. Others mark it `left` at once and remove its proxy tools after `fleet.unhealthy_grace_seconds`. |
| An instance crashes or is cut off | The failure detector (section 5.3) marks it `suspect`, then `dead` if no one can reach it within `suspect_timeout_seconds`. Its proxy tools stay listed as unavailable during the grace period, then are hidden. |
| An instance comes back | It rejoins with a higher **incarnation** number, which overrides any stale `suspect` or `dead` entry about it. |
| An instance is revoked | Its id is on the signed revocation list; every instance refuses it and removes its tools, wherever the list reaches first. |

A server whose certificate is not from the fleet CA cannot join, gossip or call anyone, however
it learned the addresses.

### 5.3 The gossip protocol

The protocol follows the SWIM design (scalable, weakly consistent, infection-style membership),
which needs no leader and costs a few small messages per instance per second. At about ten
instances it is far more than enough.

- **Membership list.** Each instance keeps an entry per instance: id, URL, region, labels,
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
- **Transport.** Gossip messages are small HTTPS POSTs over the same mutual TLS as calls, not
  UDP, so they pass through Kubernetes services, ingress and corporate proxies unchanged.
- **Digests trigger pulls.** Gossip carries only digests. When an instance sees a peer's catalog
  hash or key-directory version change, it pulls the changed part from that peer (sections 6.2
  and 9.3). Gossip never carries tools, schemas or keys themselves.
- **One gossip agent per instance.** An instance running several workers elects one of them to run
  the agent, through a lease in the state store (the same claim mechanism workflow cron uses);
  the membership list is kept in the state store so every worker sees the same fleet. If the
  agent's worker dies, another takes the lease.
- **No split-brain hazard.** Instances never need to agree on anything beyond membership: each
  call is point to point and authorized by the host. Two instances that briefly see different
  lists only disagree about which proxies to show.

### 5.4 The fleet CA, run by SAJHA

The certificate authority is part of SAJHA; no external PKI is needed.

- **One CA instance.** An administrator designates one instance as the fleet's CA instance
  (`fleet.ca.enabled: true` on that instance only) and initialises it once
  (`sajha fleet ca init`), which creates the CA key pair. The private key is a secret reference
  (`fleet.ca.key_ref`), stored with owner-only permissions and never sent anywhere; the
  administrator is prompted to back it up.
- **Enrolling an instance.** On the CA instance, an administrator creates an **enrollment token**
  for a named instance (`sajha fleet ca enroll cust-na`, or the console): one-time, short-lived,
  bound to that instance name. The new instance starts with the token and the CA's public
  certificate, generates its own key pair, and sends a certificate request with the token to the
  CA instance; the CA instance checks the token and issues a certificate naming `cust-na`. The new
  instance's private key never leaves it.
- **Renewal.** Each instance renews its own certificate before expiry by sending a request signed
  with its current, still-valid certificate; no token is needed. Renewal failures are shown in the
  console well before expiry.
- **Revocation.** `sajha fleet ca revoke <instance>` (or the console) adds the instance to the
  revocation list, which the CA instance signs and gossip spreads within seconds.
- **The CA instance is not a single point of failure for running the fleet.** If it is down,
  every instance keeps working with its current certificate; only new enrollments and renewals
  wait. Its key can be restored from backup onto another instance, which then becomes the CA
  instance.
- **Console.** On the CA instance, the Fleet area has a **Certificates** page: issued
  certificates with instance, serial, expiry and state; pending enrollment tokens; the revocation
  list; actions to enroll, revoke and re-issue.

### 5.5 Manual mode

Where an administrator prefers not to run a CA, peers can still be added by hand with a one-time
join offer approved on both sides. Gossip then runs among the approved peers only.

---

## 6. Catalog exchange

### 6.1 What a host instance exports

For each tool its export rules allow a given peer to see, a host instance publishes:

- the tool's name, description, `inputSchema`, `outputSchema` and annotations;
- its version and, if versioned, its deprecation state;
- fleet metadata: host instance id, region, labels, data classes of its arguments and results
  (section 11), whether it is an LLM tool, an indicative latency and its health;
- a catalog hash, so a peer can tell whether anything changed.

Nothing else: no configuration, credentials, implementation details or usage data.

### 6.2 How catalogs travel

- **Digest, then pull.** Every instance's catalog hash travels in gossip (section 5.3). When a
  instance sees a new hash for a peer (or a new peer), it pulls that peer's catalog over MCP
  (`tools/list`, with the fleet metadata in `_meta`) using its instance identity. An unchanged
  catalog is never transferred.
- **Fallback refresh.** Every `fleet.refresh_interval_seconds` an instance also re-pulls any peer
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

The owner's decision is that fleet instances are trusted, so `auto` is the default. Screening stays
on anyway: it is cheap, and it limits the damage if a trusted instance is ever compromised. Under
`review`, a tool whose description or schema changes after approval is held at its previous
approved version until reviewed.

---

## 7. Proxy tools and the unified catalog

### 7.1 Automatic proxies

For every approved remote tool the home instance's import rules allow, SAJHA creates a **proxy
tool** in its registry automatically: the remote schemas, the remote annotations (corrected,
never widened: a remote tool is at least `openWorldHint: true`), and a fleet connection. When
the tool disappears from the peer's catalog, the proxy is removed; when the peer is unhealthy,
the proxy stays listed with its health for `fleet.unhealthy_grace_seconds` and calls fail fast,
then it is hidden until the peer recovers.

### 7.2 Names

| Name | Rule |
|---|---|
| Qualified name | Always `<instance>__<tool>` (for example `risk-eu__var_calc`), the same `__` convention federation uses, valid for every LLM provider's tool-name rules. Planners, audit and metrics always record this name. |
| Bare alias | Offered in addition only when `fleet.bare_aliases` allows it **and** the bare name is unique across the home instance's own tools and every imported tool, **or** an administrator pinned the alias to one instance. |
| Collision with a local tool | The local tool keeps the bare name. The remote tool is reachable only by its qualified name. Reported on the fleet page. |
| Collision between two instances | Neither gets the bare name unless an administrator pins one. Both stay reachable by qualified name. Reported. |
| Same name, different meaning | Prevented by the rules above: a bare name never silently switches from one implementation to another. If a pinned alias's tool changes its schema, the alias is suspended until reviewed. |

Local always wins, as requested, but a remote tool is never hidden behind a local one: it keeps
its qualified name, and the conflict is visible.

### 7.3 `tools/list` shows everything the caller may use

`tools/list`, the Tools page, the REST catalog and the Ask SAJHA shortlist show local tools and
proxies together, filtered as always by the caller's access, and now also by import rules.
Each proxy carries its fleet metadata in `_meta["io.sajha/fleet"]`:

```json
{ "instance": "risk-eu", "region": "eu-west", "locality": "remote",
  "health": "ok", "latency_ms_p50": 85, "data_classes": { "results": ["confidential"] },
  "llm_tool": false }
```

The Tools page gains an instance badge, a "local / remote" filter and a per-instance filter. The
landing-page constellation can colour stars by instance.

### 7.4 The host and tool table

Every instance keeps an explicit **routing table** of which instance hosts which tool. It is the
single place the proxies, aliases, planners and console read from:

| Field | Meaning |
|---|---|
| `qualified_name` | `<instance>__<tool>`, always unique |
| `alias` | the bare name, when one is offered (unique in this instance's view, or pinned) |
| `host_instance`, `host_tool` | which instance hosts it, and the tool's own name there |
| `version`, `schema_hash`, `description_hash` | what was last accepted from the host |
| `trust`, `state` | trust level; `active`, `held` (awaiting review), `hidden`, `blocked`, `unavailable` |
| `first_seen`, `last_seen`, `last_changed` | when the host first offered it, last confirmed it, last changed it |

- A bare alias always resolves through this table, so even a call by alias knows exactly which
  host it goes to, and the audit record names both the alias and the qualified name.
- The table is rebuilt from catalogs as they arrive and kept in the state store (shared by the
  instance's workers) and in the storage backend (so it survives restarts before peers answer).
- It is included in every snapshot (section 19.4), so an auditor can see which instance served
  which tool at any point in the retained window, and is the **Remote tools** page in the
  console (section 16).
- When a tool moves (the same tool name appears on a different host, or a host stops offering
  it), the change is a row in the table's history and an audit event; an alias whose host
  changes is suspended until an administrator confirms the new host.

---

## 8. What happens on a call

```
caller ──► HOME instance                                   HOST instance
           1 access check (caller may call proxy)
           2 import rules (this user, this remote tool)
           3 argument validation (proxy's inputSchema)
           4 residency check on arguments (section 11)
           5 policy engine (deny / redact / approval / rate limit)
           6 breaker, rate limit, hop check (section 13)
           7 identity resolver: attach the user's API key;
             mutual TLS, trace id, hop count ──────────────► 8 verify instance certificate, revocation
                                                            9 identity resolver: hash the key, look
                                                              it up in the fleet key directory, check
                                                              enabled, expiry, home instance
                                                           10 map user and roles (section 10.3)
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
- Retries happen only for tools annotated read-only and idempotent; the result cache applies
  only to read-only tools with a `cache_ttl`, keyed by user where the host instance says results
  differ per user.
- Destructive remote tools still require confirmation at the home instance (MRTR or `confirm`
  fingerprints), and the host instance may additionally require its own approval.

---

## 9. Identity

### 9.1 Instance identity

Every request between instances is mutual TLS with a fleet certificate (section 5.1). A request
from a server without one, or from a revoked instance, is refused before anything else is read.

### 9.2 User identity: a pluggable resolver, API keys first

The host instance must know which user a call is for; otherwise it can only authorize "instance A",
and any user of A gets whatever A may do.

How the user is identified across instances is a **pluggable resolver** with two halves:

- on the home instance, `outbound(caller) → credentials to attach to the forwarded call`;
- on the host instance, `inbound(request) → a verified fleet user` (user id, home instance,
  roles, tool allowlist) or a refusal.

The resolver is chosen by `fleet.user_identity`. **The first implementation is `api_key`**, as
the owner decided; `assertion` (an instance-signed JWT) and `token_exchange` (RFC 8693 through a
shared identity provider) are later implementations of the same interface, so switching needs no
change anywhere else.

**`api_key`: the user's API key is their fleet identity.**

1. A user (or a script, or an agent) holds an API key issued by **one** instance, their home
   instance, and calls SAJHA there.
2. The home instance verifies the key: first in its database as it does today, then in its
   persistent key file if the database does not know it or is unavailable (section 19.3);
   either way the hash, enabled flag, expiry and tool allowlist are checked.
3. When the call goes to a proxy tool, the home instance forwards the **key itself** to the host
   instance in a dedicated header, over the mutual-TLS connection, together with the trace id and
   hop count.
4. The host instance hashes the key and looks it up in its **fleet key directory** (section 9.3,
   which includes keys from instances' persistent key files),
   a synced copy of every instance's key records. It checks that the record exists, is enabled,
   is not expired or revoked, and that the request came **from the key's home instance** (a key can
   only enter the fleet through the instance that issued it).
5. The verified fleet user is the key's owner, with the owner's roles as recorded by the home
   instance, mapped to local roles (section 10.3), and the key's tool allowlist as an extra
   ceiling. Authorization then proceeds as in section 10.

**Handling rules for forwarded keys.** The raw key exists only in memory during the call: it is
never logged, never written to the audit log (the key's id and prefix are), never stored, never
put in a trace attribute, and never forwarded onward when re-export is on (a further hop gets
the key id inside an instance-signed assertion instead). Only mutual-TLS connections may carry it.

**Why forward the key rather than only its id.** Forwarding lets the host instance verify the
user's possession of the key independently, against its own synced copy, instead of trusting
the home instance's word. The cost is that every instance sees every forwarded key in transit, so a
compromised instance could capture keys from calls that reach it. That is acceptable for a fleet
whose instances are trusted (an owner decision, section 23); a fleet that wants to remove that
exposure switches the resolver to `assertion`, where only a key id signed by the home instance
crosses, without other changes.

**Anonymous callers** never cross: proxy tools are not visible to them unless
`fleet.anonymous_may_call_remote` is set (off by default, refused for destructive tools).
**Every user has a default API key.** Every user account on every instance always has a
**default API key**, created with the account (and, when this ships, for every existing account
at start-up). It cannot be deleted, only rotated (regenerated) by the user or an administrator,
or disabled by an administrator. The user sees it on their profile page, can copy it once after
each rotation, and uses it like any other key.

Because API keys are stored only as hashes, the home instance could not forward a key it had
not just received. So the default key is also kept **encrypted** at its home instance, in the
same AES-256-GCM vault connected accounts use, readable only by that instance. When a signed-in
console user (or Ask SAJHA, a workflow or an LLM tool acting for them) calls a remote tool, the
home instance decrypts the user's default key and forwards it. A caller who arrived with an API
key forwards that key instead.

Default keys are ordinary keys everywhere else: in the key directory, in snapshots, under the
user's tool allowlist (by default the user's own access) and revocable at once.

**Connected accounts.** A user's linked SaaS tokens never leave their home instance. A remote tool
that needs the user's token for a provider runs only on an instance where that user has linked the
account; otherwise the host instance answers "connect your account here", as federation's token
passthrough does.

### 9.3 The fleet key directory

Each instance publishes the records of the API keys it issued, and every instance keeps a synced
copy of everyone's: the **fleet key directory**.

| Field | Meaning |
|---|---|
| `key_id`, `key_prefix`, `name` | the key's identity, as in the issuing instance's `api_keys` table |
| `key_hash` | the SHA-256 hash SAJHA already stores; **the raw key is never synced** |
| `home_member` | the instance that issued it and is its only authority |
| `owner` | the owner's user id, display name and role names at the home instance |
| `enabled`, `expires_at`, `revoked_at` | its current state |
| `tool_access_mode`, `tool_access_list` | its tool allowlist |
| `version`, `updated_at` | a counter the home instance increments on every change |
| `signature` | the home instance's signature over the record, so no other instance can forge or alter it |

**How it syncs.** Each instance's directory has a version (the highest record version it issued).
Gossip carries every instance's directory version in its digest (section 5.3). When an instance sees
a newer version for a peer, it pulls only the records changed since the version it holds, from
that peer, verifies each record's signature against the peer's certificate, and stores them. A
full comparison runs during anti-entropy, so a missed update is repaired within
`full_sync_interval_seconds`.

**Revocation is fast where it matters.** Disabling or revoking a key takes effect on its home
instance at once, and a forwarded key can only arrive from its home instance (step 4 above), so a
revoked key stops working across the fleet immediately even before the directory update has
spread. Revocations are also gossiped with priority, so every instance's copy follows within a
few rounds.

**Ownership.** Only the home instance can change a key's record; a record for `risk-eu`'s key that
arrives from anyone else, or that is not signed by `risk-eu`, is ignored. When an instance leaves
or is revoked, its keys are marked unusable in every directory.

**What it costs.** One row per API key in the fleet, a few hundred bytes each, stored in a new
table (section 19) so lookups by hash are indexed and local key administration is unaffected.

---

## 10. Authorization

### 10.1 Both sides decide, neither trusts the other

- The **home instance** decides whether its user may use the remote tool and whether these
  arguments may leave (import rules, access rules, policy engine).
- The **host instance** decides whether this peer, for this user, may run this tool (export rules,
  its own access rules mapped from the user's roles, its own policy engine and approvals).

The host instance never accepts "instance A says the user may": it applies its own rules to the user
the identity resolver verified (section 9.2). This is what prevents a confused-deputy attack, where an instance is used to
reach what its users could not reach directly.

### 10.2 Export and import rules

```yaml
fleet:
  export:                         # what this instance offers
    - tools: ["var_*", "stress_*"]
      to_members: ["risk-*", "treasury-na"]
      for_roles: ["risk_analyst", "treasurer"]     # remote roles after mapping (10.3)
      require_approval: false
    - tools: ["*_delete*"]
      to_members: []                                # never exported
  import:                         # what this instance's users may use
    - instances: ["risk-eu"]
      tools: ["var_*"]
      for_roles: ["analyst"]
    - instances: ["*"]
      tools: ["*"]
      for_roles: ["admin"]
```

Nothing is exported or imported unless a rule allows it. Rules are evaluated at catalog time (a
caller does not even see a proxy it may not call) and again at call time (rules can change
between the two).

### 10.3 Users across instances

Every instance has **its own users**. The same person may have an account on several instances,
under the same or a different user name, with different roles and different API keys on each;
and a person may have no account at all on some instances. Only the administrator account exists
on every instance. The fleet never merges or copies user accounts.

A fleet user is therefore always **a user at an instance**: `alice@risk-eu`. When `alice@risk-eu`
calls a tool hosted on `cust-na`, the host instance decides who she is *there*, in this order:

1. **An explicit link.** `cust-na`'s administrator has linked `alice@risk-eu` to a local account
   (say `a.smith`). The call runs as `a.smith`, with `a.smith`'s roles and policy.
2. **The same user name, if allowed.** With `fleet.users.match_by_name` on (the default), a local
   account with the same user name (`alice`) is used. Its local roles apply, never the roles
   `alice` has on `risk-eu`. An administrator can turn matching off for an instance or exclude
   names.
3. **No local account.** Governed by `fleet.users.unknown`:
   - `refuse` (default): the call is refused with "you have no account on cust-na"; the proxy
     tools that would need one are not shown to her at all (section 7.3);
   - `map_roles`: the call runs as a guest identity `alice@risk-eu` with the roles produced by
     the host's **role map** for `risk-eu` (`analyst@risk-eu → risk_analyst`); unmapped roles map
     to nothing.

**Administrators.** The administrator account exists everywhere, so by name matching an
administrator on one instance would be an administrator on every other. The design separates two
things:

- **Tool calls.** An administrator from another instance calls tools as the host's administrator
  only if `fleet.users.remote_admin` is `admin` (the default, given the fleet is trusted); `user`
  treats them like any linked or matched user; `refuse` blocks them.
- **Fleet administration.** Blocking, trust levels, user links, role maps and every other fleet
  setting on an instance can only be changed by an administrator **signed in to that instance**,
  never through a remote call. Each instance governs itself.

**API keys.** A key belongs to one user on one instance. Alice's key on `risk-eu` and her key on
`cust-na` are different keys with different records in the key directory; either identifies her
only as the user on the instance that issued it, and the host maps that identity as above.

The fleet console (section 16) shows, for each instance, which remote users are linked, matched,
mapped or refused, and lets an administrator link or unlink them.

### 10.4 Blocking

An administrator can block, on their own instance, at four levels. A block takes effect on the
next request (in-flight calls finish), is written to the audit log with who, when and why, may
have an expiry, and is shown everywhere it matters in the console.

| Block | Set by | Effect |
|---|---|---|
| **An instance, entirely** | any instance, for itself | This instance stops calling the blocked one (its proxy tools disappear from this instance's catalog), refuses every call from it, and ignores its catalog and key-directory updates. Gossip still reports the blocked instance's state, so the console can show it. |
| **One direction** | the host (inbound) or the caller (outbound) | Inbound: `cust-na` refuses calls *from* `risk-eu` but may still call `risk-eu`'s tools. Outbound: `risk-eu` stops calling `cust-na`'s tools (they are hidden from its users) but still serves calls from `cust-na`. |
| **A tool** | either side | The host refuses calls to that tool from a given instance (or from all), or the caller hides that remote tool from its users. |
| **A remote user** | the host | Calls on behalf of `alice@risk-eu` are refused, whatever her mapping. |

Each instance decides only for itself: an administrator on `treasury-na` cannot block calls from
`risk-eu` to `cust-na`. Removing an instance from the whole fleet is not a block: it is a
revocation of its certificate by the fleet CA (section 5.1), which every instance enforces.

Blocks are **local decisions, shared information**: each instance publishes the blocks it holds
in its gossip digest, so the console on any instance can draw the fleet-wide picture (who blocks
whom, and why) while each block is still enforced only by the instance that set it.

---

## 11. Data sovereignty and residency

Residency is about where data flows, in both directions.

- **Data classes.** A tool's schema can mark arguments and result fields with
  `x-sajha-data-class` (for example `eu-personal`, `confidential`, `public`); a whole tool can
  declare classes for its results. Instances declare their jurisdiction labels.
- **Residency rules** are policy-engine rules with a new condition: *data of class C may (or may
  not) go to an instance whose jurisdiction is J*. Examples: `eu-personal` never leaves instances
  labelled `jurisdiction: EU`; `confidential` only to instances in the same legal entity.
- **Arguments.** Before a call leaves (step 4), the home instance checks the classes of the
  arguments' fields against the host instance's labels. A planner cannot route EU personal data to
  a US tool by accident: the call is refused, and the planner is told why so it can choose a
  local alternative.
- **Results.** The host instance checks its results' classes against the home instance's labels
  before answering (step 14) and can refuse, redact (policy `redact`) or summarise.
- **What the home instance keeps.** Conversation memory stores answers, which may now contain data
  from other instances. Per data class, `fleet.memory.remote_results` decides whether such answers
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
- **Remote LLM tools.** A host instance's LLM tools ([LLM Tools](LLM%20Tools.md)) are exported
  like any tool (`fleet.allow_remote_llm_tools`, on by default: the owner decided LLM and plain
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

## 13. Hops and loops

- **No transitive re-export by default.** An instance exports only its own tools, never proxies it
  imported (`fleet.reexport: false`). Without re-export, every remote call is exactly one hop.
- **When re-export is enabled**, each call carries a hop count and the list of instances it has
  visited (in headers carried over mutual TLS). An instance refuses a call that would exceed
  `fleet.max_hops` or revisit an instance, so A → B → A loops cannot form.
- **Remote LLM tools** count toward both the LLM-tool depth limit and the hop limit.

---

## 14. Reliability

- **Per-peer isolation.** Connection pools, timeouts, circuit breakers and rate limits are per
  peer, so one slow or failing instance affects only its own tools.
- **Health.** Each instance probes its peers (and their catalogs) on a schedule and records health;
  the planner and the Tools page see it.
- **Graceful degradation.** An instance that cannot reach the fleet still serves all its local tools;
  proxies fail fast with "instance unavailable".
- **Version skew.** Instances advertise a fleet protocol version alongside the MCP eras they speak;
  an instance talks to a peer at the highest version both support and refuses peers below
  `fleet.min_protocol_version`.
- **Several workers.** Peer records and approvals live in the storage backend and the state store
  (as federation's do), so every worker of an instance sees the same fleet.

---

## 15. Observability and audit

- **Linked audit.** Both instances record the call in their own tamper-evident audit chains,
  sharing one trace id (W3C `traceparent`) and the API key's id. A cross-instance call can be
  reconstructed by joining the two records, and neither instance's records depend on the other's.
- **Tracing.** One trace spans home and host (OTLP), so latency per hop is visible.
- **Metrics.** `sajha_fleet_calls_total{peer,tool,outcome}`, latency per peer, refusals by side
  and reason (`import`, `export`, `residency`, `identity`, `revoked`), catalog sizes and
  refresh results, peer health.
- **Fleet page.** Instances and their health, pending joins and approvals, imported and exported
  tool counts, name conflicts, trust levels, role maps and the last refusals; a topology view of
  which instances call which.

---

## 16. The fleet console

The fleet is managed from a new **Fleet** area in SAJHA's web console. It follows the console's
conventions (the four themes, page help from the glossary, phone-width layouts checked by
`scripts/check_mobile.py`, the same tables, filters and confirmation dialogs as the rest of the
console) and its own bar: an operator should understand the state of the fleet in ten seconds
and change it safely in two clicks. Every page has a JSON API behind it and the same actions in
the `sajha` command line.

### 16.1 Pages

| Page | What it shows | What an administrator can do |
|---|---|---|
| **Fleet overview** | A live topology map: one node per instance (this one centred), coloured by state (`alive`, `suspect`, `dead`, `left`, blocked), edges showing traffic in the last hour with thickness by calls and colour by error rate; beside it, cards with each instance's name, region, labels, latency, tools shared, last seen, certificate expiry. Fleet totals: instances, remote tools in use, calls and refusals in the last hour. | Open an instance; filter by region or label; pause the live view |
| **Instance detail** | Header with state, incarnation, certificate and expiry, versions; tabs for **Tools** (what it exports to us, what we export to it), **Traffic** (calls each way, latency percentiles, errors and refusals by reason), **Users** (its users we link, match, map or refuse), **Keys** (its key-directory records: count, revoked, last sync), **Blocks** (ours toward it and, from gossip, its toward us), **History** (catalog changes with diffs, state changes, blocks) | Block or unblock (entirely, inbound, outbound), change trust level, edit role map, link users, force a catalog and key refresh |
| **Remote tools** | Every proxy tool in one searchable table: qualified name, alias, hosting instance, health, latency, trust, data classes, version, last change; local tools can be included for comparison | Hide or block a tool, pin or unpin an alias, review a held change (diff of description and schema), open its audit trail |
| **Conflicts and reviews** | A queue of what needs a person: name collisions, schema or description changes held under `review` trust, screening flags, pinned aliases suspended by a change, tools refused by limits | Approve, reject, pin, rename alias; bulk actions with a reason |
| **Users across the fleet** | For each remote instance, its users seen calling here and how each resolved (linked, matched by name, mapped roles, refused), with their last calls | Link a remote user to a local account, unlink, block a remote user, turn name matching off for an instance |
| **Access and blocks** | A matrix of instances (rows: callers, columns: hosts) showing allowed, blocked inbound, blocked outbound and blocked entirely, from this instance's own blocks plus the blocks others publish; a list view with reasons, who set each, and expiries | Add, edit, expire or remove this instance's blocks, with a required reason and a confirmation that names the effect ("risk-eu's 214 users will lose access to 37 tools") |
| **Key directory** | Read-only view of synced key records by instance: owner, prefix, state, expiry, tool allowlist, last change, signature status; this instance's persistent keys marked | Force a re-sync; nothing here can change another instance's keys |
| **Snapshots** | The retained snapshots with time, size, chain status (verified, broken) and signature status | Verify the chain, compare any two snapshots (users, keys and tools added, removed and changed), download, restore users and persistent keys after confirmation |
| **Live activity** | A stream of cross-instance calls as they happen, drawn in the constellation style of the landing page: a call travels from instance to instance, refusals flash with their reason | Filter by instance, user, tool or outcome; open any call's linked audit records on both sides |
| **Fleet settings** | This instance's name, region and labels (read from configuration), certificate status, seeds, gossip health, defaults for trust, name matching, unknown users and remote administrators | Edit what may be edited at runtime; everything else names the configuration key to change |

### 16.2 Where the fleet shows up elsewhere

- **Tools page and tool detail:** a badge with the hosting instance and its health on every remote
  tool, a "local / remote / instance" filter, and on the detail page the path a call takes.
- **Ask SAJHA:** remote tools are labelled with their instance in the plan and the answer's
  citations; the animation colours stars by instance.
- **Dashboard:** a fleet tile (instances alive, remote calls, refusals) linking to the overview.
- **Audit and usage pages:** filters by remote instance and remote user; a cross-instance call
  links to its counterpart record on the other side.
- **Navigation:** a Fleet menu for administrators; non-administrators see remote tools in the
  catalog but none of the fleet pages.

### 16.3 Quality bar

- **State is never ambiguous.** Every instance, tool and block shows its state in words and
  colour (never colour alone), with the time it was last confirmed.
- **Every destructive action explains its blast radius** before it is taken (users and tools
  affected), requires a reason, and can be undone from the history tab.
- **Fast at fleet size.** Pages load from the state store and local tables, never by calling
  every instance on page load; live views update by server-sent events.
- **Accessible and responsive.** Keyboard reachable, screen-reader labels on the map (with a table
  equivalent), phone-width layouts for every page, all four themes.
- **Tested like the rest of the console:** page tests for every view and action, the mobile check
  in all themes, and an end-to-end test that blocks an instance and sees its tools disappear.

---

## 17. Threats and mitigations

| Threat | Mitigation |
|---|---|
| A rogue server pretends to be an instance | Mutual TLS with certificates from the fleet CA only; the signed revocation list is checked on every request; gossip from a server without a fleet certificate is refused |
| A compromised instance impersonates users | Host instances authorize the named user against their own export and access rules, never "the instance says so"; role maps grant nothing by default; revocation is immediate |
| A forwarded API key is captured | Keys travel only over mutual TLS, are never logged, stored or traced, and are accepted only from their home instance, so a captured key cannot be replayed through another instance; a fleet that wants no key in transit switches to the `assertion` resolver (section 9.2) |
| An administrator on one instance takes over another | Fleet settings can only be changed by an administrator signed in to that instance; remote administrators' tool calls are configurable (`remote_admin`) and audited |
| The CA key is stolen | It lives only on the CA instance as an owner-only secret; certificates are short-lived; re-keying the CA and re-enrolling instances is a documented procedure |
| Default keys are read from the vault | AES-256-GCM with the instance's vault key (from the environment, never in the database); only the home instance can decrypt |
| The persistent key file or a snapshot is copied | Hashes only, never keys; owner-only permissions; git-ignored; snapshots carry hashes only for persistent keys |
| Snapshots are edited or deleted to hide a change | Each snapshot chains to the previous one and is signed by the instance; rotation and every snapshot run are audited |
| An instance forges or alters another instance's key records | Every directory record is signed by its home instance and ignored otherwise; only the home instance may change its records |
| False gossip (a healthy instance reported dead, a fake instance advertised) | Indirect probes before suspicion; an instance refutes suspicion itself with a higher incarnation; only certificate-holding instances can gossip, and an instance's details are accepted only from itself or as gossip about a certificate-verified instance |
| A peer's description tries to instruct the model | Descriptions screened and capped; changes held for review; results treated as untrusted data (section 8 step 15) |
| A peer quietly changes what a tool does | Every description or schema change is recorded in the audit log with a diff and shown on the fleet page; pinned aliases are suspended until reviewed; under `review` trust the change is held at the last approved version |
| Data leaves its jurisdiction through arguments | Residency rules on arguments at the home instance; on results at the host instance; residency-aware shortlists |
| An instance is used as a stepping stone (confused deputy) | Dual authorization on the user's identity; no re-export by default; hop limits |
| A slow instance drags others down | Per-peer timeouts, breakers, pools and rate limits; local tools unaffected |
| SSRF through a peer URL | Federation's URL guard on every peer URL learned from gossip; a URL must match the host name in the instance's certificate |
| Denial of service from a peer | Per-peer rate limits at the host instance; catalog size caps |

---

## 18. Configuration

```yaml
fleet:
  enabled: false
  name: acme-fleet
  instance_name: risk-eu
  base_url: https://sajha-risk-eu.example.internal
  region: eu-west
  labels: { domain: risk, jurisdiction: EU, entity: acme-eu }
  identity:                         # mutual TLS with a fleet-CA certificate (section 5.1)
    cert_ref: file:/etc/sajha/fleet/instance.crt
    key_ref: file:/etc/sajha/fleet/instance.key      # secret references, never values
    ca_ref: file:/etc/sajha/fleet/ca.pem
    revocation_list_ref: file:/etc/sajha/fleet/revoked.json   # signed; also spread by gossip
  users: { match_by_name: true, unknown: refuse, remote_admin: admin }   # section 10.3
  default_keys: { enabled: true, vault: accounts }   # section 9.2
  ca: { enabled: false, key_ref: file:/etc/sajha/fleet/ca.key, cert_validity_days: 30, enrollment_token_minutes: 30 }   # section 5.4, CA instance only
  user_identity: api_key            # api_key (first) | assertion | token_exchange (section 9.2)
  key_directory: { sync: true, full_sync_interval_seconds: 300 }
  persistent_keys: { file: config/apikeys.json, reload: true }   # section 19.3
  snapshots: { enabled: true, interval_minutes: 10, keep: 20, dir: data/fleet/snapshots, compress: false, to_siem: false }   # section 19.4
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
  bare_aliases: unique              # unique | pinned_only | off  (owner decision: unique)
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

## 19. Storage

### 19.1 Database

- **One new table, `fleet_api_keys`,** for the fleet key directory (section 9.3): one row per key
  issued anywhere in the fleet, indexed by key hash, holding the record fields and its home
  instance's signature. It is added to both schema files (no migrations: operators run the
  `CREATE TABLE` on PostgreSQL; SQLite creates it) and kept apart from the local `api_keys`
  table, so local key administration is unchanged.

### 19.2 Storage backend and state store

- **Default keys:** the encrypted copy of each user's default key, in a small table next to the
  connected-accounts vault (both schema files), keyed by the key id.
- **Blocks and user links:** records in the storage backend, audited on change, published in the
  gossip digest.
- **Host and tool table:** state store, with a copy in the storage backend (section 7.4).
- **CA instance only:** issued certificates, enrollment tokens and the signed revocation list.

- **Storage backend:** trust levels, role maps, manual-mode peers and catalog snapshots as JSON
  records, alongside federation's.
- **State store:** the membership list and incarnations, the gossip agent's lease, catalog and
  directory digests, peer health and per-peer rate counters (shared across an instance's workers).

### 19.3 Persistent API keys in a file

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
  written to the audit log.
- **Protection.** The file is created with owner-only permissions and is git-ignored; a tracked
  a tracked example file next to it documents the format. A hash of a long random key cannot be
  reversed, but the file still names users and their access, so it is treated as sensitive.
- **In the fleet.** Persistent keys are part of the instance's key directory like any other key, so
  every instance can verify them too.
- **Today's file.** `config/apikeys.json` currently holds a plaintext demo key that nothing reads
  (Roadmap item N5). This design replaces it with the hashed format above; the demo key is not
  carried over.

### 19.4 Periodic snapshots

Every instance writes a **snapshot** of what it knows every `snapshots.interval_minutes` (default
10) and keeps the last `snapshots.keep` (default 20), so an auditor can see who and what existed
at any point in the retained window, and an instance can be rebuilt after losing its database.

- **Contents.**
  - Users: id, user name, roles, enabled (no password hashes).
  - API keys issued by this instance: the record fields of section 19.3 for every key, persistent
    or not; hashes only for persistent keys, so a snapshot alone cannot verify ordinary keys.
  - Tools: every local tool (name, version, schema hash, enabled) and every proxy tool (name,
    host instance, version, schema hash, trust level).
  - Fleet view: instances and their states, incarnations and labels as this instance saw them, and
    the key directory's version per instance.
- **Format and place.** One JSON file per snapshot, named with the UTC time and a sequence number,
  in `data/fleet/snapshots/` (or the storage backend), owner-only permissions, optionally
  compressed.
- **Tamper evidence.** Each snapshot records the SHA-256 of the previous one and is signed with
  the instance's key, so a deleted, reordered or edited snapshot is detected, the same idea as the
  audit chain. A snapshot run is also an audit event.
- **Rotation.** After writing a snapshot, the oldest beyond `keep` are deleted (and their deletion
  audited). Twenty snapshots ten minutes apart cover a little over three hours; for longer
  history each snapshot can also be sent to the SIEM export, which keeps it under the SIEM's own
  retention.
- **One writer.** With several workers, the gossip agent's lease holder writes the snapshot, so a
  instance produces exactly one per interval.
- **Restoring.** After a database loss, an administrator can re-create users, roles and key
  records from a chosen snapshot (keys come back only if they were persistent, since only those
  snapshots carry hashes); tools and fleet state rebuild themselves from configuration and gossip.

---

## 20. Testing

- **Multi-instance tests in one process:** two or three SAJHA apps with separate databases and
  keys, joined into a fleet, exchanging catalogs and calling each other.
- **Membership:** joins through a seed, clean leaves, crashes detected through indirect probes,
  false suspicion refuted, rejoin with a higher incarnation, revocation spreading, a server
  without a fleet certificate refused; a network split heals through anti-entropy.
- **Identity:** a forwarded key verified against the directory; unknown, disabled, expired or
  revoked keys refused; a key arriving from an instance other than its home refused; directory
  records with bad signatures ignored; the raw key absent from logs, audit and traces.
- **Persistent keys and snapshots:** a persistent key works with the database removed; database
  revocation overrides the file; an edited file reloads; snapshots appear every interval, only
  `keep` are kept, the chain detects an edited or missing snapshot, one writer across workers;
  users and keys restore from a snapshot.
- **Users and blocks:** linked, name-matched, mapped and refused remote users; a remote
  administrator under each setting; fleet settings refused over remote calls; each block level in
  each direction, expiry, and blocks published by gossip.
- **CA and default keys:** enrollment with a token (reused, expired and wrong-name tokens
  refused), renewal, revocation; every user has a default key that survives rotation and is
  forwarded for console sessions; the vault copy is unreadable without the instance's key.
- **Host and tool table:** aliases resolve through it; a tool moving host suspends its alias;
  it appears in snapshots.
- **Key directory sync:** a new or changed key reaches every instance; a missed update repaired by
  anti-entropy; a leaving instance's keys become unusable.
- **Authorization:** a user without access at the host instance is refused even when the home
  instance allows it, and the reverse; role maps; anonymous callers.
- **Names:** local wins; collisions between instances; pinned aliases; schema change suspends an
  alias.
- **Residency:** arguments and results of each data class to instances of each jurisdiction;
  residency-aware shortlists.
- **Resilience:** an instance down, slow, flapping or returning oversized catalogs; local tools keep
  working.
- **Planners:** a question needing tools on two instances is answered; memory stays on the home
  instance.
- **Conformance:** both MCP suites stay green on every instance.

---

## 21. Build plan

Each phase ends green: full suite, multi-instance tests, both conformance suites.

| Phase | Scope |
|---|---|
| 1 | Membership: the fleet CA run by SAJHA (CA instance, enrollment tokens, renewal, revocation), certificates and mutual TLS, revocation list, gossip agent (SWIM failure detection, dissemination, anti-entropy, seeds, incarnations, leases across workers); fleet page (instances and their states) |
| 2 | Catalog exchange driven by gossip digests, the host and tool table, screening and trust levels, automatic proxy tools, qualified names and alias rules, `tools/list` with fleet metadata, Tools page badges and filters |
| 3 | Identity resolver interface; the `api_key` resolver; default API keys for every user, kept encrypted at home; users across instances (links, name matching, unknown users, remote administrators); blocking at all four levels; the fleet key directory with signed records, digest-driven sync and the `fleet_api_keys` table in both schema files; host-side verification; persistent key file and periodic snapshots (these two also benefit a SAJHA that is not in a fleet); export and import rules, role maps; linked audit and tracing; metrics; per-peer isolation |
| 4 | Residency: data classes, residency rules on arguments and results, residency-aware shortlists, memory handling of remote results |
| 5 | Planners and LLM tools: locality-aware ranking, remote LLM tools, hop and depth limits combined |
| 6 | Re-export with hop limits; the `assertion` and `token_exchange` resolvers; topology view |
| 7 | The Fleet console: overview map, instance detail, remote tools and the host and tool table, conflicts and reviews, users, access and blocks, key directory, snapshots, live activity, certificates, settings; fleet badges across the console; mobile check in all themes |
| 8 | Docs: this note becomes as-built; glossary; tutorial ("two domains, one question"); Security Model; Configuration and API Reference; help card; CHANGELOG |

---

## 22. Competitive position

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

## 23. Decisions for the owner

**Decided**

- **Size:** about ten instances; no registry (section 5).
- **Trust:** instances' tools are trusted, LLM tools and plain tools alike. New peers default to
  `auto` trust and remote LLM tools are on (sections 6.3 and 12). Screening stays on as a
  safeguard against a compromised instance.
- **Membership by gossip:** instances discover each other and detect arrivals and departures
  automatically (section 5), which makes admission by fleet certificate and mutual TLS the
  instance authentication.
- **User identity:** the user's API key, issued by one instance, is forwarded with the call and
  checked against a fleet key directory synced to every instance; the identity resolver is
  pluggable so assertions or token exchange can replace it later (section 9).

- **Persistent keys and snapshots:** API keys can also live in `config/apikeys.json` so they
  survive a lost database; every instance snapshots users, keys and tools every 10 minutes and
  keeps 20 (section 19).

- **Instances and users:** each instance is named in its own configuration; users and their API
  keys are per instance, and a user may not exist on some instances; the administrator account
  exists everywhere (sections 5.1 and 10.3).
- **Blocking:** an administrator can block another instance entirely, in one direction, per tool
  or per remote user, for their own instance (section 10.4).
- **Console:** a full Fleet area in the web console (section 16).
- **The fleet CA is run by SAJHA:** one CA instance, enrollment tokens, automatic renewal,
  revocation (section 5.4).
- **Default API keys:** every user always has one, kept encrypted at home so console users can
  reach remote tools (section 9.2).
- **Bare aliases:** on for unique names (`unique`), always resolved through each instance's host
  and tool table (section 7.4).

**Still open**

1. **Users with no account on a host:** refuse (default, recommended) or run them with mapped
   roles (`fleet.users.unknown`)?
2. **Administrators from other instances** calling tools: as the host's administrator (default,
   given the fleet is trusted), as an ordinary user, or refused (`fleet.users.remote_admin`)?

---

## 24. Alternatives considered

| Alternative | Why not |
|---|---|
| One central SAJHA with every tool | Moves every domain's credentials and data access into one place; the boundary sovereignty requires disappears |
| Membership configured by hand on every instance | Ten instances means up to ninety peer entries to keep consistent; arrivals and failures go unnoticed. Gossip with certificate admission keeps who-may-join a deliberate act (issuing a certificate) while making everything after it automatic |
| A central registry for membership | One more service to run and keep available; not needed at about ten instances |
| Syncing raw API keys | Every instance would store every key; a single compromised database leaks keys usable everywhere. Only hashes and signed records are synced |
| Server-to-server trust only (no user identity) | The host instance can only authorize "instance A", so any user of A gets all of A's access: a confused deputy by design |
| Shared database or state store across instances | Couples instances' availability and crosses the data boundary the fleet exists to keep |
| Remote tools under their bare names, local wins | Silent shadowing: the same name could mean different tools on different instances, and a planner would not know which it called |
| Copying tool definitions and running them locally | The tool would run outside its data's boundary with copied credentials, defeating sovereignty |
