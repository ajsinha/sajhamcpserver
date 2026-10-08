# SAJHA Net

**SAJHA Net** joins several SAJHA servers, and other MCP servers, into a **net** in which each
server's tools can be called from every other, while each server keeps its own data, credentials,
policy, AI layer and conversation memory. A server in a net learns which tools the other members
offer and puts a **proxy tool** for each one it may use into its own catalog. When a caller (a person,
an MCP client, a planner, an LLM tool, a workflow) calls a proxy, the server forwards the call, signed
and with the caller's identity, to the member that hosts the tool, and returns the result. To the
caller a remote tool is just a tool.

This guide owns SAJHA Net as built: concepts, membership and admission, catalogs, names, routing,
identity, authorization, residency, the call-chain budget, re-export, the console and operations.
The bytes on the wire are the [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md); every
configuration key and its default is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net); every route is
in the [API Reference](../protocol/API%20Reference.md#424-sajha-net-sajhanet_routespy); the
definitions are in the [Glossary](../../GLOSSARY.md#12-sajha-net); the hands-on walkthrough is
[Tutorial 28](../tutorials/TUTORIAL_28_build_a_sajha_net.md). What is not built is listed in
[section 5.5](#55-what-is-built) and tracked in the [Roadmap](Roadmap.md) (L16, L17).

SAJHA Net is **off by default** (`sajhanet.enabled: false`). Off, every `/sajhanet/` path answers a
bare `404` and a server behaves exactly as without it.

---

## Contents

1. [Why SAJHA Net](#1-why-sajha-net)
2. [What it guarantees](#2-what-it-guarantees)
3. [Vocabulary](#3-vocabulary)
4. [How it relates to federation](#4-how-it-relates-to-federation)
5. [Participants, names and plug-in points](#5-participants-names-and-plug-in-points)
6. [Membership and admission](#6-membership-and-admission)
7. [Catalog exchange](#7-catalog-exchange)
8. [Proxy tools and the unified catalog](#8-proxy-tools-and-the-unified-catalog)
9. [What happens on a call](#9-what-happens-on-a-call)
10. [Identity](#10-identity)
11. [Authorization](#11-authorization)
12. [Data sovereignty and residency](#12-data-sovereignty-and-residency)
13. [Planners, LLM tools and memory](#13-planners-llm-tools-and-memory)
14. [Hops, the call-chain budget, re-export and bridges](#14-hops-the-call-chain-budget-re-export-and-bridges)
15. [Reliability](#15-reliability)
16. [Observability and audit](#16-observability-and-audit)
17. [The SAJHA Net console](#17-the-sajha-net-console)
18. [Threats and mitigations](#18-threats-and-mitigations)
19. [Configuration](#19-configuration)
20. [Storage](#20-storage)
21. [Operations](#21-operations)

---

## 1. Why SAJHA Net

Large organisations rarely have one place where all data may live. Business lines, legal entities and
regions each own their data and the rules for using it, and regulators expect those boundaries to
hold. A single central tool server either cannot reach that data or becomes the place where every
boundary is crossed.

A net puts a SAJHA server inside each boundary. Each one holds the tools that touch its data and the
credentials those tools use; applies its own access rules, policy engine, approvals and audit; runs its
own AI layer (models, budgets, planners, LLM tools); and keeps its own users' conversation memory. What
crosses a boundary is **a tool call and its result**, and only when both sides' rules allow it. A
question that spans domains ("how exposed is the EU book to the rate move the US desk is forecasting?")
is answered by a planner on one server using tools on several, without copying either domain's data
into the other.

## 2. What it guarantees

| Property | How | Section |
|---|---|---|
| Members find each other and each other's tools without per-peer configuration; a member's tools disappear from every peer the moment it is known to be gone | Gossip (SWIM) from one or two seeds; catalogs pulled when a digest changes; withdrawal on `left`, `dead` and revocation | 6, 7, 8.5 |
| A remote tool is called like a local one, by callers, planners, LLM tools, composites and workflows | Proxy tools in the registry, through `execute_with_tracking` like every tool | 8, 9 |
| The host knows **which user** is calling and authorizes the call itself | Identity resolvers (`api_key`, `assertion`, `token_exchange`); the host maps the user to its own account and applies its own rules | 10, 11 |
| Each server decides what it offers, to whom, and what its users may use | Export and import rules per net; trust levels; blocks | 7.3, 11 |
| Data classes can stop data leaving a boundary, in arguments as well as results | Residency rules in the policy engine, at the home and at the host | 12 |
| Local tools win a plain name; a qualified name reaches exactly the tool it names; nothing is shadowed silently | The resolution order, recorded for every call | 8.2 |
| Within a net a tool name means one contract | Any difference quarantines the name on every member until the hosts agree | 8.7 |
| A slow, down, revoked or compromised member cannot take the others down or widen what anyone may do | Per-peer breakers, rate limits and timeouts; signed requests; both sides authorize. This holds in a `builtin_ca` or `manual` net with the test admin key off: open mode admits whoever first claims a name, and the test admin key makes every forwarded call an administrator's | 6.4, 10.2, 15, 18 |
| Every cross-instance call is audited on both sides under one trace id | `net.call` / `net.host_call` records in each side's tamper-evident chain | 16 |
| Any MCP server can take part | Natively, through the SAJHA Net agent, or sponsored by a SAJHA server | 5.1 |
| One server can be in several nets, kept fully apart | Per-net certificates, membership, key directories, rules; a signed net header on every request | 6.1, 14 |

What SAJHA Net does **not** do: share state between servers (each keeps its own database, state store
and memory; only catalogs, key records and calls travel), elect a leader or run consensus, move data in
bulk, or join nets together (a tool crosses from one net into another only through a bridge an
administrator turns on, section 14).

## 3. Vocabulary

Every SAJHA Net term (net, participant, instance name, home and host instance, proxy tool, qualified and
plain names, vendor, external server, resolution order, contract hash, quarantine, waterfall fallback,
net key directory, user assertion, admission mode, first-use key, re-export, bridge, and the rest) is
defined once, in [GLOSSARY.md section 12](../../GLOSSARY.md#12-sajha-net). The protocol says
**participant** for any member of a net and **instance** where this guide does; on the wire they are
the same thing.

## 4. How it relates to federation

[Federation](Federation.md) is how one SAJHA server embeds other MCP servers (**proxied MCP
servers**) and offers their tools as its own. SAJHA Net reuses federation's machinery (the name rules of
`sajha/federation/names.py`, annotation correction and schema validation in
`sajha/federation/security.py`, description screening, the SSRF guard, cancellation and trace
propagation) and adds what federation does not have:

| Concern | Federation | SAJHA Net |
|---|---|---|
| Who configures it | An administrator adds each upstream | Members find each other by gossip and exchange catalogs automatically |
| Direction | One way: SAJHA consumes an upstream | Symmetric: every member exports and imports |
| Who the remote side sees | The upstream's own credential for every caller, or the user's own SaaS token | The SAJHA **user**, verified by the host (section 10) |
| Authorization at the remote side | Whatever the upstream does | The host's export rules, access rules and policy engine on every call |
| Data residency | Not modelled | Data classes on arguments and results, checked on both sides |
| Audit | The usage ledger and the tool-call audit record | Linked records on both sides under one trace id |

The two meet in two places. A proxied MCP server marked **external** is offered into the nets by the
server that embeds it, under a vendor prefix (section 5.6); and a SAJHA server can **sponsor** a plain
MCP server as a member of a net (section 5.7). Either way the embedded server never takes part in the
protocol itself.

---

## 5. Participants, names and plug-in points

### 5.1 Three ways to take part

| Participant | What it is | Who enforces the host side |
|---|---|---|
| **SAJHA instance** (`kind: sajha`) | A SAJHA server with SAJHA Net on | Itself: export rules, access, policy, residency, audit |
| **Agent-fronted MCP server** (`kind: agent`) | Any MCP server with the **SAJHA Net agent** beside it, or a Python server with the reference library built in (section 5.8) | The agent's export policy, with the server's own authorization behind it |
| **Sponsored MCP server** (`kind: sponsored`) | An MCP server that knows nothing about SAJHA Net, represented in the net by a SAJHA server under its own instance name (section 5.7) | The sponsor, fully: its export rules, access, policy, residency and audit |

Every participant has an instance name, appears on the Instances page and in every host and tool table,
and its tools become proxy tools on other members in the same way. Callers and planners cannot tell the
kinds apart except through the member record (`kind`, and `sponsor` for a sponsored member), which the
console shows. Capabilities are negotiated, not assumed: a participant lists the features it supports
and peers use only what both list (protocol §6.2).

### 5.2 The protocol is an MCP extension

What participants say to each other is the `io.sajha/net` MCP extension, specified on its own so
others can implement it without SAJHA's code: [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md)
(endpoints, schemas, signatures, merge rules, error codes, limits and the conformance list). With
SAJHA Net on, SAJHA advertises it on both MCP eras (`sajha/core/net_extension.py`): in
`capabilities.extensions` of the 2026-07-28 `server/discover` result, and in
`capabilities.experimental` of the 2025-11-25 `initialize` result. To a request that is not signed by a
participant the object is reduced to `protocol_versions` and `endpoint`, so an anonymous client learns
neither the net nor the features.

### 5.3 Plug-in points

Every moving part is an interface in `sajha/net/plugins.py` with registered implementations, chosen in
configuration by name or by `package.module:Class`. Each implementation must pass its contract check
(`sajha/net/contract.py`) before it can be selected.

| Interface | Decides | Shipped |
|---|---|---|
| Membership provider | how participants find each other | `gossip` (SWIM, section 6.3), `static` (`static_peers` in a net entry) |
| Admission | who may join and how they prove it | `open`, `builtin_ca`, `manual` (section 6.4) |
| Peer connector | how requests travel | `sajha_native` (signed HTTP on the normal port), `in_process` (tests and the agent) |
| Identity resolver | how the user travels with a call | `api_key`, `assertion`, `token_exchange`, `none` (section 10.2) |
| Catalog source | where a participant's tools come from | `native` (SAJHA's registry), `static` (a fixed list, for the library) |
| Key directory store | where synced key records live | `database` (the `sajhanet_api_keys` table), `memory` |
| Rule evaluator | export, import and block decisions | `policy_engine` (SAJHA's rules), `allow_all`, `deny_all` |
| Snapshot sink | where a participant writes snapshots | `local_files` (SAJHA's own snapshots are `sajha/snapshots/`, section 20.4) |
| Routing strategy | the order of one tool's hosts within a net | `local_first` (by instance name), `lowest_latency` (measured median first), `pinned` (only hosts named in the preferences) |

**Third-party plug-ins.** At start SAJHA loads the entry-point group `sajha.net.plugins` and every module
named in `sajhanet.plugins.modules` (`plugins.load_plugins`). A newly registered class that fails its
contract check is unregistered; a module that cannot be imported, registers nothing or fails its check
raises an error notice (`sajhanet.plugin:<source>:<name>`) and an audit record, and start goes on.
`GET /api/sajhanet/status` lists what loaded (`plugins`). The example is the routing strategy
`region_first` (`sajha/examples/sajhanet/region_first.py`); tests are in
`tests/net/test_net_plugin_loading.py`.

### 5.4 How the code is organised

- **The protocol core**, `sajha/net/`, imports nothing from the rest of SAJHA
  (`tests/net/test_net_plugins.py` checks it): names (`names.py`), canonical JSON (`jcs.py`), structured
  fields (`sfv.py`), keys, certificates and record signatures (`crypto.py`), request and response
  signatures (`httpsig.py`), message schemas (`schemas.py`), errors (`errors.py`), the CA (`ca.py`),
  admission (`trust.py`), SWIM rules and the saved peer list (`membership.py`), a participant's node per
  net (`node.py`), catalogs (`catalog.py`), routing and the host's processing order (`routing.py`), the
  key directory (`keydir.py`), blocks (`blocks.py`), residency (`residency.py`), the reference library
  (`library.py`) and the conformance suite (`conformance/`).
- **SAJHA's integration**, `sajha/net/integration/`, sits on top: configuration (`config.py`), the
  service, notices and metrics (`__init__.py`), catalogs and proxies (`catalogs.py`), identity and
  authorization (`authz.py`, `identity.py`, `keystore.py`), residency (`residency.py`), sponsored servers
  (`sponsored.py`) and the console data (`console.py`, `overview.py`). The routes are
  `sajha/routes/sajhanet_routes.py`.
- **The agent** is `sajhanet_agent/`, built from the core and the library only
  (`tests/test_sajhanet_agent_boundary.py`).

### 5.5 What is built

Everything this guide describes is built, with these exceptions (each a [Roadmap](Roadmap.md) item:
L17 for the streaming items, L16 for the rest):

| Not built | Effect today | Protocol |
|---|---|---|
| Progress, cancellation, input requests (MRTR) and tasks on forwarded calls | A forwarded call is one signed request answered with one JSON result; the caller sees only the final result, and cancelling does not reach the host | §15.6; CALL-11, FB-07 |
| Forwarding on the 2025-11-25 era | Forwarded calls always use 2026-07-28 (every SAJHA host speaks it) | §6.4; CALL-12 |
| The `visibility` feature | A home cannot ask a host which tools a user may call there; it shows what its own rules allow, and the host decides again on every call | §10.5; CAT-05 |
| Mutual TLS (`sajhanet.mtls`) | A value other than `off` only logs a warning; requests are checked by their signatures | — |
| Discovery plug-ins (Kubernetes DNS, DNS SRV, a registry) | The interface exists (`MembershipProvider.discover`); no shipped provider discovers anything | §9.7 |
| The net view in snapshots | Snapshots record users, keys and local tools, not proxies or membership | — |
| Console pages: instance detail tabs, a conflicts-and-reviews queue, users across the net, an access-and-blocks matrix, the key directory, snapshots, live activity, certificates and net settings as pages of their own; blast-radius counts, reasons on every action and undo | Most of their data is on the SAJHA Net admin page, the Net overview and the admin API (section 17) | — |
| An agent that is also a home (calls other members' tools); the agent with blocks, residency, re-export, `assertion` or `token_exchange` | The agent only hosts, with the `api_key` identity | — |
| Sponsored members with `assertion` or `token_exchange`; console pages for sponsoring | Sponsored members accept `api_key` only; sponsoring is configuration and admin API | — |
| Memory handling for LLM tools that record their own turns; an approval flow for residency rules | Such tools record an answer without its steps; `require_approval` on a residency rule refuses | — |
| Per-peer rate limits and breakers shared across workers; caching proxy results | Breakers and per-peer rate limits count per process (section 15); proxy results are never cached | — |

The conformance ids SAJHA's own suite covers, and the runner, are in section 5.9.

### 5.6 Vendors and external servers

**The problem.** One name, one contract (section 8.7) is right inside one organisation, but servers
from unrelated organisations break it by accident: a search server from acme and one from globex both
offer `search` with different schemas, and the net would quarantine the name everywhere although
nobody did anything wrong. Vendors and external servers keep such tools apart.

- **Every member names its vendor**: the organisation that owns and answers for its tools (`sajha`,
  `acme`). A lowercase letter, then lowercase letters, digits and `_`, at most 24 characters, never
  `__`, not ending with `_`. A SAJHA instance takes `sajhanet.vendor` (default `sajha`; a net entry may
  override it), a sponsored entry `vendor` (required), the agent `--vendor` (required). It is in the
  member record and shown on the Instances, Remote tools and Net overview pages, in
  `GET /api/sajhanet/status` and in the topology data. There is no vendor registry: the name is a
  claim, and the contract rule keeps it honest.
- **An external server is not a member.** It is a proxied MCP server marked external: an entry of the
  [mcpServers file](Federation.md#the-mcpservers-file) (external unless it says `"external": false`), or a
  federation upstream listed in `sajhanet.external_servers` with its vendor. It has no member record,
  instance name or certificate, never gossips, and never appears on the Instances page. The SAJHA
  server that defines it is its proxy: its tools are offered as that server's own, published as
  `<prefix>__<tool>` (the prefix defaults to the vendor), so the qualified name is
  `<net>__<defining instance>__<prefix>__<tool>` (`acme-net__risk-eu__acme__search`) and the plain
  name `acme__search`. Its endpoint and credentials never leave the defining server, which runs every
  call with its full governance and then calls the upstream through federation. The catalog entry
  carries `vendor` and `external: true` in `_meta["io.sajha/net"]`, so every member shows "external (via
  risk-eu)".
- **`__` is reserved for namespaced tools** (federated and external servers' tools, data connectors'
  tools and SAJHA Net's remote tools); the tools registry refuses any other tool that uses it
  ([Federation](Federation.md#names)). A prefix is unique on a server, across federation upstreams and
  external servers, and never a local tool's name.
- **Internal servers keep their names.** Every member (a SAJHA instance, an agent-fronted server, a
  sponsored server) is internal: its tools keep their names and one name, one contract applies to them.
  So are a member's **internal proxied MCP servers** (`external: false`): their tools are offered into the
  net under their federation names (`<prefix>__<tool>`), governed and exported like the member's own
  tools (`_own_tools`, `sajha/net/integration/catalogs.py`). A SAJHA instance is always a member; to offer another SAJHA's tools under a vendor prefix, define it as
  an external server (a federation upstream on its `/mcp`). A sponsored entry with `external: true`, a net
  entry with `external`, and the agent's `--external` are refused with a message pointing here.
- **Rules accept either name.** At the defining server, export rules and tool blocks match the
  published name (`acme__search`) or the local registry name of the federation tool; access (roles and a
  key's tool list) is checked under the local name and also accepts the published name; policy and
  approvals see the local tool, which is what runs. Homes name the tool by its published (qualified) name.
  The host's `net.host_call` audit record has `tool` (the published name) and `local_tool`.
- **One name, one contract applies to the published name.** Two SAJHA instances that both define acme's
  server and offer the identical `acme__search` are one fallback set for the plain name. Different
  vendors never meet on a name; two instances claiming one vendor with different contracts are the loud
  quarantine of section 8.7, naming the differing host.
- **Deliberate short names.** `rename` (`{tool: published name}`) on an external server entry,
  `sajhanet.rename` (or a net entry's `rename`) for a member's own tools, `rename` on a sponsored entry,
  and the agent's `--rename local=published` offer a tool under a name the operator chooses. Such a name
  falls under the same contract rule.
- **Length.** A qualified name is at most 128 characters (protocol §5.3). A host whose published name
  would make it longer does not offer that tool: it logs a warning, raises a warning notice
  (`sajhanet.name:<net>:<tool>`) and an audit record (`tool_name_refused`), and the Net overview and the
  agent's status list it under `refused_tools`. Nothing is shortened automatically; give it a `rename`.
  The same check refuses a published name that is not a valid tool name or that two tools would share.
- **Re-export keeps the published name**, with its `vendor` and `external` metadata, so the contract is
  compared under one name everywhere.
- **Proxies all the way down.** A proxied server may itself proxy others; names compose
  (`<net>__<instance>__<outer>__<inner>__<tool>`, still split at the first two `__`), each level applies
  its own governance, and the 128-character cap and the call-chain budget bound the nesting
  ([Federation](Federation.md#proxies-all-the-way-down)).
- **Caution.** Do not choose a vendor that is also the name of a net this server is in: a plain name
  such as `acme__files__read` would then read as a qualified name in net `acme`.

Example: one SAJHA server offers two vendors' `search` tools without either becoming a member. With the
mcpServers file (`config/mcp_servers.json`; templates in
[`config/mcp_servers/`](../../config/mcp_servers/README.md)):

```json
{"mcpServers": {
  "acme":   {"url": "https://search.acme.example/mcp"},
  "globex": {"url": "https://mcp.globex.example/mcp", "tools": ["search", "fetch_*"]}
}}
```

The same with upstreams defined in `application.yml`:

```yaml
federation:
  upstreams:
    - {id: acme, url: "https://search.acme.example/mcp"}
    - {id: glx, url: "https://mcp.globex.example/mcp"}
sajhanet:
  external_servers:
    - {upstream: acme, vendor: acme}
    - {upstream: glx, vendor: globex, tools: ["search", "fetch_*"], rename: {fetch_document: globex_fetch}}
```

Every member then lists `acme__search`, `globex__search` and `globex_fetch`, all hosted by this server,
and nothing is quarantined. Federated tools that are not external stay local: they are never exported
into a net on their own. The rules are normative in the
[protocol](../protocol/SAJHA%20Net%20Protocol.md#55-vendors-and-published-tool-names); the tests are
`tests/net/test_net_vendors.py`.

### 5.7 Sponsored servers

A sponsored server is an MCP server that cannot have an agent beside it (a vendor's or SaaS endpoint, a
stdio tool) and is made a member by a SAJHA server, its **sponsor** (`sajha/net/integration/sponsored.py`).

- **Defining one.** An entry of `sajhanet.sponsored`, or one added with `POST /api/sajhanet/sponsored`
  (kept in the storage backend at `<data_dir>/sponsored.json`), names a net, an instance name, a
  federation upstream and a vendor, with optional `tools` globs, `rename`, `region` and `labels`.
- **How it runs.** The sponsor runs a node for it (kind `sponsored`, its member record and extension
  object carrying `sponsor`) on the sponsor's own URL; requests reach it by `Sajha-Net-To`. Its key and
  certificate are held by the sponsor in `<data_dir>/<net>/sponsored/<name>/`: self-signed in an `open` or
  `manual` net, issued by the sponsor when it is the net's CA, else enrolled with a token
  (`POST /api/sajhanet/sponsored/{net}/{instance}/enroll`).
- **What it offers.** The upstream's federated tools under the server's own names (filtered by `tools`),
  with the sponsor's data classes. A forwarded call runs the sponsor's checks as for its own tools (the
  `api_key` identity with the sponsored member as audience, blocks, export rules under the tool's local
  name, the mapped account's access, policy and approvals, residency on the result, audit) and then
  federation's connection to the server. A sponsored member imports nothing.
- **Who sees it.** Other members pull its catalog and call it like any member; the sponsor's own users
  reach it through proxies, by a signed call to the sponsor's own URL. It is shown in
  `GET /api/sajhanet/status` (`sponsored`), the Instances data (kind and `sponsor`), the topology and
  the Net overview.

### 5.8 The SAJHA Net agent and the reference library

The **agent** (`python -m sajhanet_agent`) puts any MCP server, reached over stdio or Streamable HTTP,
into a net as a member of kind `agent`: it holds the certificate, gossips, publishes the server's
`tools/list` as its catalog (and follows `notifications/tools/list_changed`), verifies forwarded keys
against the net key directory, applies a small export policy and passes allowed calls to the server. It
only hosts: it never calls other members' tools and publishes no keys. The **reference library**
(`sajha.net.library`, `NetParticipant`) is the same participant without the MCP client, for a Python
server that joins a net itself. Both are documented in the
[SAJHA Net Agent](../clients/SAJHA%20Net%20Agent.md) guide.

### 5.9 Conformance

The protocol's §20 lists every conformance case with its targets (S a SAJHA instance, A the agent, L the
library). The runner is `python -m sajha.net.conformance --target <url>|library` (`sajha/net/conformance/`):
it checks from outside, as a participant that never joins, every case observable that way, runs the
library cases against the core with the protocol's §21 vectors, and reports each id `pass`, `fail` or
`skip` (a skip names the test file of SAJHA's suite that covers a case needing the target's insides).
Usage is in [SAJHA Net Agent](../clients/SAJHA%20Net%20Agent.md) section 9.

SAJHA's own suite covers every S case under `tests/net/` (and `tests/test_sajhanet_groundwork.py` for
CAP-01 to CAP-03) except those of section 5.5: CAT-05, CALL-11, FB-07 and CALL-12. CALL-06 (every
step of the host's processing order, in order) is covered step by step across the files rather than by
one test. The wave exit `tests/net/test_net_mixed_conformance.py` puts a SAJHA instance, a server it
sponsors and an agent-fronted server in one net and runs the suite on all three targets and the library.

---

## 6. Membership and admission

### 6.1 Nets and instance names

- **Named nets, several per server.** Each entry of `sajhanet.nets` is one net; the list order is the
  server's order of preference between its nets (section 8.2). A net name is lowercase letters, digits,
  `-` and `_`, starting with a letter, at most 16 characters, never `__`, not ending with `_`
  ([protocol §5.1](../protocol/SAJHA%20Net%20Protocol.md#51-net-names)). An entry without a name is the
  net **`default`**, and an info notice (`sajhanet.default_name`) asks to name it.
- **Each net is fully separate**: its own certificates, membership, key directory, blocks, rules and
  trust levels. Nothing learned in one net is used in another, and being in two nets never bridges them
  (section 14).
- **Instance names are per net.** In each net a server has an instance name (`instance_name` in the net
  entry: lowercase letters, digits and single hyphens, 2 to 32 characters, starting with a letter). It is
  what gossip, the console, audit records, net users (`alice@risk-eu`) and qualified tool names use. A
  configured name needs a `base_url` (`sajhanet.base_url`, or the entry's own), the URL peers reach the
  server on.
- **Names never collide.** A name belongs to the certificate lineage that first held it in the net
  ([protocol §5.2](../protocol/SAJHA%20Net%20Protocol.md#52-instance-names)). A server claiming a held
  name with a different key is refused by every member with `409 name_conflict` naming the holder: it
  does not join, raises an error notice (`sajhanet.name_conflict:<net>`) and the
  `sajha_net_name_conflict` metric, and stops retrying until its configuration or certificate changes;
  its local tools keep working. Members that see such a claim raise a warning
  (`sajhanet.name_conflict_seen:<net>:<claimant>`). A restart, or a renewal by the CA, is the same
  holder. How firmly a name is held depends on the admission mode (section 6.4).
- **When no name is configured, the address is the name**: `<ip>:<port>` (`10.20.4.17:3002`, IPv6
  `[2001:db8::7]:3002`), from the net's `advertise_address`, else a specific bind address, else the
  interface of the default route; never an unspecified, loopback, `localhost` or link-local address
  (with none acceptable the net is not joined and an error notice says why). In qualified names its
  dots and colons become `_` and an IPv6 address is written out in full
  (`acme-net__10_20_4_17_3002__var_calc`); everywhere else it is shown as written. An address name
  changes when the address does, and with it every qualified name, link, block and preference that
  names the instance, so production servers configure a name. A server with several pods or workers is
  one instance and needs a configured name and an `advertise_address`; the Helm chart refuses to render
  several pods without them ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md#sajha-net)).
- **Advertised addresses.** A participant's address is the `url` of its own signed member record, never
  the address a request came from. A sponsored member shares its sponsor's URL by design; an external
  server has no record, so its endpoint is never gossiped.
- **How a server recognises itself** (`sajha/net/node.py`, protocol §9.4 rule 7). Besides a record under
  its own name, a node treats as itself a record signed with its own key under another name, and a record
  whose `url` is its own address under another name and key. Either raises a warning notice
  (`sajhanet.self_seen:<net>`) and an audit record (`self_seen`). A sponsored member of this server
  shares the URL by design and is an ordinary member. A seed, runtime seed or saved peer at the node's
  own address is skipped.

### 6.2 Coming and going

| Event | What happens |
|---|---|
| A server starts | It contacts its seeds for the net (one or two are enough; with none it is a net of one, section 6.6), presents its certificate and receives the member list. Its arrival spreads within a few gossip rounds; each member then pulls its catalog and key directory (sections 7, 10.3). |
| It stops cleanly | It gossips a signed `leave`; others mark it `left` and remove its tools at once. |
| It crashes or is cut off | The failure detector marks it `suspect` (its tools stay listed as unavailable and calls skip it); after `suspect_timeout_seconds` without a refutation it is `dead` and its tools are removed. |
| It comes back | It rejoins with a higher incarnation, which overrides any stale `suspect` or `dead` entry; its tools are listed again once its catalog has been pulled. |
| It is revoked | Every member refuses it and removes its tools as soon as the revocation reaches it (`builtin_ca` only; section 6.4 for the other modes). |

Each net does this separately; a server whose configuration no longer lists a net leaves that net only.
Member state changes other than `alive` raise a warning notice (`sajhanet.member:<net>:<member>`) that
clears when the member is `alive` again or leaves retention.

### 6.3 Gossip

Membership follows SWIM: no leader, a few small messages per member per second.

- **Failure detection.** Every `gossip_interval_ms` (default 1000) a member pings one other at random.
  Without an answer within `ping_timeout_ms` (500) it asks `indirect_probes` (3) others to ping it
  (`ping-req`), so one broken link does not condemn a healthy member. No answer at all makes it
  `suspect`; a suspect that does not refute (by a higher incarnation) within `suspect_timeout_seconds`
  (10) becomes `dead`.
- **Dissemination and anti-entropy.** Changes ride on the pings, each repeated a bounded number of times;
  every `full_sync_interval_seconds` (30) a member exchanges its whole list with one random member.
- **Digests trigger pulls.** Gossip carries only digests (catalog, key directory, blocks, conflicts,
  revocation list); a changed digest makes peers pull that part point to point. Gossip never carries
  tools, schemas or keys.
- **Dead members are still probed** for `dead_retention_minutes` (60) every
  `dead_probe_interval_seconds` (30), so a restarted member whose seeds are all down is found again.
- **Transport.** Small signed HTTP POSTs on SAJHA's normal port (section 6.7): no other port, no UDP.
- **One gossip agent per net.** With several workers, one worker per net runs the agent, holding the
  renewing state-store lease `sajhanet:agent:<net>` (TTL `sajhanet.agent_lease_seconds`, default 15;
  [Scaling and State](Scaling%20and%20State.md#47-leases)); the membership list is in the state store,
  so every worker sees the same net. When the holder dies another worker takes over within one TTL.
  Several workers need `state.backend: redis` or `database`.

The defaults above are in the [Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net)
(`sajhanet.gossip.*`).

### 6.4 Admission modes

How a net admits a participant is the admission plug-in, `sajhanet.plugins.admission`, set for the
server (every net of a server uses the same mode). The code default is `builtin_ca`; the shipped
`config/application.yml` sets **`open`** (owner decision, for now).

| Mode | Certificates | Who can join | Revocation | Use it when |
|---|---|---|---|---|
| `open` (shipped) | Each server makes a self-signed certificate for each net (`O=<net>, CN=<name>`) at first start | **Anyone who can reach a member and knows the net's name**, under any unused instance name. The first key seen for a name is remembered (a first-use key) and later held to it; another key claiming the name is refused with `name_conflict` | None: an administrator **forgets** a remembered key (Net overview or SAJHA Net admin page; `DELETE /api/sajhanet/nets/{net}/first-use/{instance}`), after which the next claimant of the name is accepted | Every machine that can reach the members is yours (a lab, an intranet segment you control) |
| `builtin_ca` | Issued by the net's CA, which SAJHA runs (section 6.5), after a one-time enrollment token | Only servers an administrator enrolled, under the name the token names | The CA's signed revocation list, by name or serial, spread by gossip | Anything beyond machines you control |
| `manual` | Self-signed, approved by thumbprint on each side (`identity.pins` in the net entry, or `sajha net pin` / `POST /api/sajhanet/nets/{net}/pins`) | Only peers whose thumbprint each administrator pinned | Removing the pin | Small fixed nets without a CA |

**What open mode trusts.** Open mode trusts whoever **first** claims a name. A server that can reach a
member and knows the net's name can join under an unused name, see what is exported to it, and receive
forwarded calls; with the test admin key on (the shipped setting, section 10.2) those calls carry an
administrator's key. A name taken by the wrong server first stays taken until an administrator forgets
its key. The remembered keys are in the storage backend (`<data_dir>/<net>/first_use.json`), each
remembered key is audited (`peer_key_remembered`, and `peer_key_forgotten` when forgotten), and the
admission panel lists them. Switch to `builtin_ca` before a net spans machines you do not control
(section 21.3).

Whatever the mode, every request between participants is signed (section 6.7), names are held to a key,
and the host still authorizes every user it is sent (sections 10 and 11).

### 6.5 The built-in CA and manual mode

With `builtin_ca`, the CA is part of SAJHA; no external PKI is needed.

- **One CA instance per net.** One server per net has `ca.enabled: true` in that net's entry and
  initialises the CA once (`sajha net ca init --net <net>`, or **Initialise** on the admission panel),
  which writes the CA key (`ca.key_ref`, owner-only; it never leaves the server: back it up) and
  certificate. A net of one (no seeds) creates its CA by itself at first start unless `ca.auto_init`
  (default `sajhanet.ca_auto_init`, true) is false; that is audited (`ca_initialised`) and raises a
  warning notice (`sajhanet.ca_created:<net>`) asking to back up the key. One server may be the CA of
  several nets, with a key for each.
- **Enrolling.** On the CA instance an administrator creates an enrollment token for a named instance
  (`sajha net ca enroll <name> --net <net>`, or **Create token**): single use, short-lived
  (`ca.enrollment_token_minutes`, default 30), bound to the name, stored as a hash, shown once. The CA
  refuses a token for a held name and says who holds it. The new server runs
  `sajha net enroll --net <net> --ca-url <url> --token <token>`: it makes its own key pair and sends a
  certificate request with the token; its private key never leaves it. Enrollment is HTTPS only and
  rate-limited per address (`ca.enrollments_per_minute`).
- **Renewal.** Certificates are short-lived (`ca.cert_validity_days`, default 30); each server renews its
  own, signed with its current certificate, when a third of the validity remains, with a new key pair.
  The renewed certificate records the serial it renews, so the name's lineage is unbroken. Renewal
  failures and approaching expiry raise notices (`sajhanet.renewal:<net>`, `sajhanet.certificate:<net>`).
- **Revocation.** `sajha net ca revoke <name> --net <net>` (or `--serial`; **Revoke** on the panel, with a
  required reason) adds the name or serial to the CA-signed revocation list, which gossip spreads; every
  member checks it on every request. A stale list raises `sajhanet.revocations:<net>`.
- **The CA is not on the call path.** When it is down, members keep working with their certificates;
  only enrollment and renewal wait. Its key can be restored onto another server, which then becomes the
  CA instance.

**Manual mode** uses self-signed certificates with pinned thumbprints and otherwise every rule of the CA
mode (protocol §8.11); the pins from configuration and from runtime are listed on the admission panel.

### 6.6 Restarts

In each net, separately, a starting server tries:

1. **Its seeds** (`seeds` in the net entry). **A net entry with no seeds is a net of one** (owner
   decision): this server is the net's founder and only member, joined at once, with no error notice, no
   join retries and no gossip. It accepts a peer later without a restart: one that joins with it as its
   seed, or one an administrator adds by address. With `builtin_ca`, until it holds a certificate it is
   not networked, and an info notice (`sajhanet.not_joined:<net>`) says how to give it one. `founder: true` is for a first
   server that also lists seeds: when they are all down it starts alone instead of retrying.
2. **Its saved peers**, most recently seen first: the members it knew, saved per net to local disk
   (`peer_cache.path`, default `<data_dir>/<net>/peers.json`) on every membership change and at least
   every `peer_cache.interval_minutes` (10), atomically and owner-only. Local disk, not the storage
   backend, so a restart finds peers even when that backend is down. An entry is only an address: the
   peer's certificate is verified on contact, and entries older than `peer_cache.max_age_days` (7) are
   skipped.
3. **A discovery plug-in**, when the membership provider has one (none is shipped, section 5.5).
4. **Peers look for it too**: a `dead` member is probed during its retention (section 6.3).

With seeds and saved peers all down (and not `founder`), the net is not joined: an error notice
(`sajhanet.not_joined:<net>`) and retries with back-off; the server's other nets are unaffected. The
restarted server rejoins with a higher incarnation (milliseconds since the epoch, at least the last one
plus one), and lists **no remote tool** until each peer's catalog has arrived in this run (section 8.5).

**Adding a peer by hand.** An administrator signed in to this server can point it at a peer for one
net by `ip:port`, `host:port` or URL (the SAJHA Net admin page, `POST /api/sajhanet/nets/{net}/peers`,
or `sajha net peers add`). The server sends an ordinary signed join at once. The address is only a hint:
the peer is admitted by the net's admission mode and the name rules like any member; the address must
pass the SSRF rules (`sajhanet.allowed_networks`; loopback and link-local never); additions are
rate-limited (`sajhanet.max_injections_per_minute`), never possible through a remote call, audited
(`peer_added`, `peer_add_failed`) and raise a notice (`sajhanet.peer_added:<net>:<url>`, info on success, warning on
failure, with the reason). **Keep as a seed** stores it as a runtime seed (storage backend,
`<data_dir>/<net>/runtime_seeds.json`), listed apart from the configured seeds with who added it and
removable (`DELETE /api/sajhanet/nets/{net}/seeds`). On failure nothing is stored.

### 6.7 One port: signed requests

Everything between participants uses SAJHA's normal HTTP port, for every net the server is in. Net
traffic is ordinary HTTP under `/sajhanet/v1/` (gossip, catalogs, key directory, blocks, conflicts,
revocation list, enrollment and renewal, token exchange); forwarded tool calls go to the host's normal
MCP endpoint with net headers added.

- **Several nets on one port.** Each request names its net in a signed `Sajha-Net-Name` header; a
  request for a net the receiver is not in gets the same bare `404` as a server with SAJHA Net off, so
  nobody learns which nets a server belongs to.
- **Signed requests and responses, not mutual TLS.** TLS usually ends at an ingress or proxy, so a
  client certificate would never reach SAJHA. Every request and response carries an RFC 9421 HTTP
  Message Signature by the sender's key (Ed25519 or ECDSA P-256), over the method, path, the important
  headers, an RFC 9530 body digest, a creation time and (on requests) a nonce, plus the sender's
  certificate. The receiver checks the certificate against the net's admission mode, the signature,
  the age (`sajhanet.signature_max_age_seconds`, default 30, never more than 300) and that the nonce is
  new (seen nonces are kept in the state store for the window, so a replay to another worker fails too).
  The full order is protocol §8.7.
- **Not for browsers.** Net endpoints set no cookies, carry no CORS headers, take no session or API key,
  and answer a browser navigation with `404`.
- **TLS keeps it private.** Signatures prove who sent a request; HTTPS keeps it confidential.
  `sajhanet.require_https` (default true) requires HTTPS for enrollment, peer URLs and forwarded keys;
  turning it off is for a lab and raises a warning notice (`sajhanet.plain_http:<net>`) while off.
- **Proxies need nothing special**: they pass headers through unchanged, as ingress controllers and
  nginx do by default. Path-rewriting proxies break verification.
- **SSRF.** Peer URLs come only from signed member records whose host is in the member's certificate,
  and pass `check_peer_url` (`sajha/federation/security.py`): public addresses always, private ones only
  inside `sajhanet.allowed_networks`, loopback and link-local never, independently of federation's own
  settings.

---

## 7. Catalog exchange

### 7.1 What a host exports

In each net, for each tool its export rules let a given peer see (section 11.2), a host publishes the
tool's whole definition as its own MCP clients see it (name, title, description, both schemas,
annotations, `_meta`), its configured `version` (informational only), and net metadata in
`_meta["io.sajha/net"]`: net, instance, region, labels, data classes of its arguments and results
(section 12), whether it is an LLM tool, health and indicative latency, and its **contract hash** (of
its schemas and annotations) and description hash. MCP Apps links (`_meta.ui`, `ui://` references) are
removed, because those resources resolve only at the host and the protocol does not proxy resource
reads. Nothing else crosses: no configuration, credentials or usage data.

A server's catalog source is its own registry (`native`): its own tools, never federated tools unless
they are external servers (section 5.6), and never proxies unless re-export is on (section 14).

### 7.2 How catalogs travel

Each member's catalog digest travels in gossip. A member pulls a peer's catalog
(`POST /sajhanet/v1/catalog`, with `if_none_match` so an unchanged catalog is not sent again) when it
first learns of the peer, when the peer's digest or incarnation changes, and at least every
`sajhanet.refresh_interval_seconds` (300). Imported catalogs are capped (`sajhanet.limits.*`: tools per
peer, catalog bytes, description length); a peer over a cap is flagged with a warning notice
(`sajhanet.catalog:<net>:<peer>`) and the excess ignored. A tool whose stated contract hash differs from
the one the home computes is not imported, and the peer is flagged.

### 7.3 Approval of imported tools

Descriptions and schemas from a peer are untrusted text: they are screened for injected instructions
with federation's markers, length-capped, and checked to be valid JSON Schema of type `object`
(`schema_problem`). Then the peer's **trust level** decides:

| Trust level | New tools from this peer |
|---|---|
| `auto` (default, `sajhanet.default_trust`) | Available at once if screening passes; a change applies at once too and is audited |
| `review` | Held until an administrator approves each one (Remote tools page, or `POST /api/sajhanet/nets/{net}/peers/{peer}/tools/{tool}/approve`); a tool that changes after approval keeps serving its approved version until reviewed |
| `pinned` | Only tools an administrator listed are imported |

The owner's decision is that members are trusted, so `auto` is the default; screening stays on to limit
the damage of a compromised member. A peer's trust level is set per net on the SAJHA Net pages or with
`POST /api/sajhanet/nets/{net}/peers/{peer}/trust`, and kept in the storage backend
(`<data_dir>/<net>/trust.json`).

---

## 8. Proxy tools and the unified catalog

### 8.1 Automatic proxies

For every imported tool its import rules allow, the home puts a **proxy tool** (`NetProxyTool`) into its
registry: the remote schemas, the remote annotations corrected and never widened (a remote tool is at
least `openWorldHint: true`; federation's `correct_annotations`), and the routing to its hosts. A proxy
is registered under its qualified name and, while a plain name is offered, under that too. When the tool
leaves the peer's catalog, or the peer goes away, the proxy goes with it (section 8.5). Every worker
keeps its registry equal to the host and tool table in the state store.

### 8.2 Names and resolution

| Name | Rule |
|---|---|
| **Qualified name** | `<net>__<instance>__<tool>` (`acme-net__risk-eu__var_calc`; an address name uses its safe form, section 6.1). It splits at the first two `__`; the tool part may itself contain `__`. Any character of the host's tool name outside `[A-Za-z0-9_-]` becomes `_`, so the name is valid for every LLM provider and starts with a letter. A qualified name always goes exactly where it says, and never falls back. Audit and metrics always record it. |
| **Plain name** (bare alias) | The tool's own name (`var_calc`), resolved in the resolution order below. Offered while `sajhanet.bare_aliases` is `on` (the default) and no local tool has the name; `preferences_only` offers plain names only for tools with a preference list; `off` offers none. |
| Collision with a local tool | The local tool keeps the plain name; the remote ones stay reachable by qualified name, and the overlap is visible on the Remote tools page. |
| Same tool on several hosts in one net | They offer one contract (section 8.7); the plain name reaches them in order and falls back between them (section 9.1). |
| Same name in two nets, different contracts | The plain name follows the first net in order that offers it; copies with another contract hash are reached only by qualified name, never by a fallback. |

**Resolution order** of a plain name, at the home:

1. **The local tool**, if this server has one by that name (unless it exports that tool into a net where
   the name is quarantined, section 8.7).
2. **The tool's preference list** (`sajhanet.preferences`), in order: `"<net>/<instance>"` (that host) or
   `"<net>"` (that net's hosts, ordered by the routing strategy).

   ```yaml
   sajhanet:
     preferences:
       var_calc: ["acme-net/risk-eu", "acme-net", "partner-net/risk-uk"]
   ```

   Entries naming a net, host or tool that is not there are skipped.
3. **The nets in configured order**: in each, the hosts offering the tool, ordered by the routing
   strategy (`sajhanet.plugins.routing`).

A host is **eligible** when it offers the tool, is not `suspect`, is not blocked, the tool is not
quarantined, and this caller's import and residency rules allow it. Each candidate's place, and why any
host is skipped, is recorded in the host and tool table, shown on the Remote tools and Your net access
pages, and written to the call's audit record, so anyone can see why a call went where it went.

### 8.3 `tools/list` shows everything the caller may use

`tools/list`, the Tools page, the REST catalog and Ask SAJHA's shortlist show local tools and proxies
together, filtered by the caller's access and by import rules. Each proxy carries its net metadata in
`_meta["io.sajha/net"]`, for example:

```json
{ "net": "acme-net", "instance": "risk-eu", "qualified_name": "acme-net__risk-eu__var_calc",
  "host_tool": "var_calc", "alias": "var_calc", "locality": "remote", "region": "eu-west",
  "health": "ok", "latency_ms_p50": 85, "data_classes": { "results": ["confidential"] },
  "llm_tool": false }
```

The Tools page shows net badges (net, host, data classes) and filters for local, remote, net and
instance; the Ask page's "Servers and tools" log names the net and host of each remote tool.

### 8.4 The host and tool table

Every server keeps a live **host and tool table** per net: for each remote tool, its qualified name,
net, host and host tool name, plain name, place in the resolution order and why, version, contract and
description hashes, trust level and state (`active`, `held` under review, `unavailable` while its host is
`suspect`, `quarantined`). Proxies, plain names, planners and the console all read from it. It holds
only what is live: it is rebuilt from catalogs as they arrive, kept in the state store (shared by the
server's workers), and its entries leave the moment their host is gone. It is the **Remote tools** page
(`/admin/sajhanet/tools`) and `GET /api/sajhanet/tools`.

### 8.5 When a host goes offline

| Host state | What every peer does |
|---|---|
| `left`, `dead` or revoked | Removes its tools at once: proxies, table entries, plain names, shortlists |
| `suspect` | Keeps its tools listed, marked unavailable; calls skip it (a plain name goes to the next host; a qualified name fails fast with `-32019 unavailable`) |

A returning host's tools come back after its catalog is pulled again. After the **home's own restart**
nothing remote is listed or callable until that peer has answered a catalog pull in this run; the stored
copy of a catalog is used only to ask whether it changed.

### 8.6 Tool names sent to a model

Qualified names can be longer than a model provider allows for a function name. When SAJHA sends tools
to a provider (Ask SAJHA, planners, LLM tools), it maps each long name to a short alias for that request
only and maps the model's calls back before anything runs. MCP clients, audit, metrics and the console
always see the full qualified name.

### 8.7 One name, one contract

**Within a net, a tool name stands for exactly one contract, everywhere.** A contract is the tool's
name, `inputSchema`, `outputSchema` and annotations, compared by contract hash; a difference in
description or title is only a warning. The rule is normative in
[protocol §10.7](../protocol/SAJHA%20Net%20Protocol.md#107-one-name-one-contract).

- **Any difference quarantines the name.** When hosts in a net offer one name with different contract
  hashes there is no winner: every member that sees it logs an error, raises an error notice
  (`sajhanet.conflict:<net>:<tool>`), counts it in `sajha_net_contract_conflicts`, audits it
  (`tool_quarantined`) and **evicts the name**: no copy is listed, resolvable, callable or a fallback
  target anywhere in the net, including on the hosts that offer it (a forwarded call gets
  `-32011 contract_conflict`; a caller at a home gets `-32018 contract_conflict` naming every offer).
- **The error says which server differs.** Members group the offering hosts by hash; when one group is
  strictly larger, the others are named as differing. The message gives the first differing place (a JSON
  Pointer into a schema, or an annotation):

  ```
  Tool var_calc quarantined in risk-net: cust-na offers a different contract.
  Differs: inputSchema /properties/horizon/type  (cust-na: "string"; others: "integer").
  Agreeing: risk-eu, treasury-na, risk-apac (3).  Differing: cust-na (1).
  ```

- **Members converge.** Each member decides from what it sees and publishes what it has itself observed
  in a signed conflicts document (pulled when `digests.conflicts` changes), so members that cannot see
  every offer still quarantine.
- **Quarantine lifts by itself** when every host still offering the name offers one contract again (the
  odd host is fixed, stops exporting it, or leaves): an info notice (`sajhanet.reactivated:<net>:<tool>`)
  and an audit record (`tool_reactivated`).
- **Escape hatch.** A host that needs its own differing copy for its local callers stops exporting it
  (its export rules); its local copy then works as before.
- **Changing a contract.** A mixed rollout quarantines the tool for as long as it lasts. Change every
  host together (or take the tool out of every host's export rules, change it, put it back), or ship the
  new contract under a **new name** (`var_calc_v2`). `version` is informational and never separates
  contracts.
- **Unrelated vendors** that happen to share a name are kept apart by defining their servers as external
  servers (section 5.6).

---

## 9. What happens on a call

```
caller ──► HOME                                              HOST
           resolve the name (8.2): qualified → that host;
             plain → local tool, else first eligible host
           access check, policy engine, argument validation
             (execute_with_tracking, as for every tool)
           import rules for this user and tool
           residency on the arguments (12)
           per-peer breaker and rate limit; hop and
             call-chain checks (14)
           identity: key, assertion or token (10.2);
           signed request, trace id, hop, visited ───────► verify the request (6.7)
                                                            protocol version
                                                            blocks on the sender
                                                            hops and loops
                                                            identity: verify the user (10)
                                                            block on the user; map the user (11.3)
                                                            block on the tool; export rules
                                                            own access, policy, approvals
                                                            execute; audit (net.host_call)
                                                            residency on the result (12)
           verify the signed answer  ◄───────────────────── signed answer
           residency on arrival; audit (net.call)
caller ◄── result
```

The host's order is protocol §15.4, and every refusal before execution carries `executed: false`. Both
sides' checks must pass; either can refuse. A refusal reaches the caller as an ordinary tool result
with `isError: true`, words that say which side refused and why, and the refusal's data in
`_meta["io.sajha/net"].refusal`. Forwarded calls use the 2026-07-28 era; the host's result is returned
as it is.

- **Retries** to the same host are not made; moving to another host is the waterfall fallback below.
- **Caching.** Proxy results are never served from the tool cache.
- **Destructive remote tools** still need confirmation at the home (MRTR or `confirm`), and the host may
  require its own approval (`-32011 approval_required`).
- **Connected accounts.** A user's linked SaaS tokens never leave their home. A remote tool that needs
  the user's token runs only where the user has linked the account; elsewhere the host answers "connect
  your account here", as federation's token passthrough does.

### 9.1 Waterfall fallback

When a call by plain name cannot be run by the host it went to, the home tries the **next eligible host
offering the same tool**, in resolution order, in any of its nets
([protocol §15.8](../protocol/SAJHA%20Net%20Protocol.md#158-not-executed-and-fallback-to-another-host)).

- **What starts a fallback**: a failure that certainly did not run the tool: never sent (connection
  refused, breaker open, host `suspect`, the home's own per-peer rate limit), or a signed `-32019` refusal
  with `executed: false` (draining, overloaded, rate-limited). Any other refusal (access, policy,
  identity, a block, residency at the host) is that host's decision and is returned: a refusal is a
  decision, not an outage. A residency refusal **at the home** for one host is the exception: the call
  moves on to a host that may receive the data.
- **After a failure that may have run the tool** (a timeout after sending, a dropped connection, an
  unsigned proxy error), the home falls back only for tools that are read-only, or idempotent and marked
  non-destructive; never for destructive tools.
- **Which hosts**: those offering the same tool part (in another net, also the same contract hash),
  skipping quarantined, blocked, `suspect`, and import- or residency-excluded hosts. Each fallback is a
  full call that the next host authorizes itself; a host that refuses is skipped.
- **Limits**: at most `sajhanet.max_fallbacks` (default 3) after the first attempt, all within one
  deadline (`sajhanet.default_timeout_seconds`, 30).
- **Visible**: every attempt is audited under the same trace id with its number, host and outcome
  (`net.call_attempt`), counted in `sajha_net_fallbacks_total`, and listed in the caller's result
  (`_meta["io.sajha/net"].attempts`). When no host answers, the caller gets the first attempt's
  refusal.

---

## 10. Identity

### 10.1 Instance identity

Every request between participants is signed with the sender's key and carries its net certificate
(section 6.7). A request without one, or from a revoked or unpinned participant, is refused before
anything else is read.

### 10.2 User identity: identity resolvers

The host must know which user a call is for; otherwise it could authorize only "server A", and any user
of A would get whatever A may do. How the user travels is an **identity resolver**, chosen per net by
`user_identity` (a net entry's, else `sajhanet.user_identity`, default `api_key`). It names one resolver
or several: as a home a server sends the first that the host's member record also lists; as a host it
accepts every one it lists, and advertises them. A call to a re-exported tool and a bridge's call always
use `assertion` (section 14).

**`api_key`: an API key travels and the host verifies it.** The home sends a key in
`Sajha-Net-Api-Key`, only over HTTPS and only on the first hop; the host hashes it, finds its record in
the net key directory (section 10.3), and refuses it unless it is enabled, unexpired, not revoked, from a
home still in the net, and **sent by its own home** (`key_not_from_home`: a key enters the net only
through the server that issued it). The verified user is the key's owner at home
(`alice@risk-eu`), with the owner's roles there and the key's tool access as an extra ceiling; the host
then maps the user to its own account (section 11.3). The home chooses the key in this order
(`NetAuthz.key_for`, `sajha/net/integration/authz.py`):

1. **A per-member key**, when this server is configured with one for the target member
   (`sajhanet.peer_keys`: `"<net>/<instance>"` or `"<instance>"` → a key, or `${ENV_NAME}`). The setting
   is local to this server and never shared. The key is one the **target member issued**: the host
   checks it first as one of its own API keys (`NetAuthz.local_key_user`: keys file, database, dump)
   and runs the call as that key's local owner, with the key's tool access as a ceiling and the host's
   user blocks applied (audited with mapping `peer_key`); a key the host does not know falls through to
   the key directory and is refused (`key_unknown`). The shipped configuration holds a sample entry for
   `default/peer-b` (and `config/apikeys.json.example` the matching record for peer-b to hold).
2. **The test admin key**, while `sajhanet.test_admin_key.enabled` is on (the shipped setting, owner
   decision for development and testing): **every** forwarded call from this server carries it. A host
   accepts it only if its own `config/apikeys.json` holds the same `test_admin` record and its own switch
   is on; it then runs the call as an administrator (its own `testadmin` account if it has one, else the
   guest `testadmin@<home>`, with the `admin` role under `users.remote_admin: admin`, the default), whoever
   the caller at the home was. The home's audit records
   the original caller and that the test admin key was used; the host's records identity
   `test_admin_key`. A critical notice (`auth.test_admin_key`) shows on every page while it is active
   ([Security Model](../security/Security%20Model.md#test-admin-key)).
3. **The key the caller presented** on this request (an API key caller).
4. **The user's default key**, decrypted from the vault, for a caller signed in another way (a console
   session, Ask SAJHA, a workflow or an LLM tool acting for them). Every user has a default key
   ([Security Model](../security/Security%20Model.md#api-keys)), kept encrypted with the connected-accounts
   vault key so the home can forward it.

The raw key lives only in memory for the call (`sajha/auth/presented_key.py`): it is never logged,
stored, traced or audited (the key id and prefix are recorded), and never forwarded past the first hop.
Forwarding the key lets the host verify possession against its own copy instead of trusting the home;
the cost is that every member a call reaches sees the key in transit, which is accepted for a net of
trusted members. A net that will not accept that exposure uses `assertion`.

**`assertion`: only a key id crosses.** The home signs a **user assertion** with its net certificate:
the user (from its own key record), the `key_id` of the key the caller presented, else the user's
default key, else their newest usable key (never a per-member key or the test admin key, which stay
features of `api_key`), the audience host, the trace id, and a lifetime of at most 60 seconds
(`sajhanet.assertion.ttl_seconds`, default 30). The host checks schema, net, issuer (the sender on the
first hop, else an instance on the chain), the signature against the issuer's certificate, audience,
time, one use of `jti` (kept in the state store), trace id, and the key record; then blocks and user
mapping as for a key (protocol §15.5).

**`token_exchange`: a host-scoped token.** The home exchanges an assertion at the host's
`POST /sajhanet/v1/token` for an opaque token bound to the net and the home, which the host keeps hashed
in its state store for `sajhanet.token_exchange.ttl_seconds` (default 300). The home caches it per host
and key, in its own process, until ten seconds before it expires, and sends it in `Sajha-Net-User-Token`.
The host re-checks the key record, the block and the mapping on every call; a `token_invalid` refusal
makes the home exchange again and retry once. The host audits each token issued (`net.token_issued`,
never the token). The exchange is between the two participants, RFC 8693 shaped (protocol §15.9).

**`none`**: service identity only, accepted when the host allows calls without a user
(`sajhanet.service_calls`). **Anonymous callers** never cross unless
`sajhanet.anonymous_may_call_remote` is on (off by default), and most hosts refuse such calls.

### 10.3 The net key directory

Each SAJHA server publishes, per net, a signed record of every API key it issued (its owned keys and the
keys of its persistent key file), and every member keeps a synced copy of everyone's: the **net key
directory**, in the `sajhanet_api_keys` table ([Database Setup](../getting-started/Database%20Setup.md)).
A record holds the key's id, prefix and name, its SHA-256 hash (**never the key**), its home, the owner
(login name, internal id, display name, roles at home), enabled, expiry, revocation and tool access, a
version from one counter per home, and the home's signature. A deleted key stays as a tombstone with
`revoked_at`.

- **Sync.** Each home's directory version travels in gossip; a member pulls only the records changed
  since the version it holds, verifies each signature against the home's certificate, and stores them.
  Every `sajhanet.key_directory.full_sync_interval_seconds` (300) it compares each home's digest and
  re-pulls from version 0 on any difference. Failures raise a warning notice
  (`sajhanet.keysync:<net>:<member>`).
- **Ownership.** Only the home can change its records: a record arriving from anyone else, or not
  signed by the home, is ignored; records signed by a revoked certificate are discarded and re-pulled;
  records of a home that left or was revoked are kept and unusable; an instance blocked entirely has its
  key updates ignored.
- **Revocation is immediate where it matters.** Disabling or revoking a key takes effect at its home at
  once, and a forwarded key is accepted only from its home, so it stops working across the net before
  the directory update has spread.
- **Several nets.** A home publishes its records in each of its nets under its name there and that net's
  certificate, so its users' keys work in every net it belongs to, and a record means nothing in another
  net.

The directory is administered on the SAJHA Net admin page and with
`GET /api/sajhanet/nets/{net}/keys` and `POST /api/sajhanet/nets/{net}/keys/resync`.

---

## 11. Authorization

### 11.1 Both sides decide, neither trusts the other

The **home** decides whether its user may use the remote tool and whether these arguments may leave
(its access rules, import rules, policy engine and residency). The **host** decides whether this peer,
for this user, may run this tool (blocks, its export rules, its own access rules for the mapped user, its
policy engine and approvals, with policy source `sajhanet`). The host never accepts "server A says the
user may": it applies its own rules to the user the identity resolver verified. That is what prevents a
confused deputy.

### 11.2 Export and import rules

Rules are per net, in that net's entry; nothing is exported or imported unless a rule allows it:

```yaml
sajhanet:
  nets:
    - name: acme-net
      export:                     # what this server offers in acme-net
        - tools: ["var_*", "stress_*"]
          to_instances: ["risk-*", "treasury-na"]
          for_roles: ["risk_analyst", "treasurer"]     # the caller's roles here, after mapping (11.3)
        - tools: ["*_delete*"]
          to_instances: []                            # never exported, whatever other rules say
      import:                     # what this server's users may use from acme-net
        - instances: ["risk-eu"]
          tools: ["var_*"]
          for_roles: ["analyst"]
```

Rules are evaluated at catalog time (a caller does not even see a proxy it may not call) and again on
every call, and the key's tool access is a ceiling on both. The fields are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net). Leaving a tool out
of a net's export rules is also how a server keeps its own copy of a tool whose contract differs from
the net's (section 8.7).

### 11.3 Users across instances

Every server has **its own users**. One person may have accounts on several servers, under the same or
different names, with different roles and keys; and no account at all on some. The net never merges or
copies accounts. A net user is always a user at an instance, in a net: `alice@risk-eu`. When
`alice@risk-eu` calls a tool hosted on `cust-na`, the host decides who she is there, in this order
(per net; `NetAuthz.map_user`):

1. **An explicit link** an administrator of `cust-na` made from `alice@risk-eu` to a local account.
2. **The same login name** (`users.user_id`; display names are never matched), while
   `sajhanet.users.match_by_name` is on (default), unless the name or the home is excluded
   (`users.exclude_names`, `users.no_name_match`, or exceptions added at runtime). The local account's
   roles apply, never her roles at home.
3. **No local account**, by `sajhanet.users.unknown`: `refuse` (default: "you have no account on
   cust-na") or `map_roles` (a guest identity `alice@risk-eu` with the roles the host's role map gives
   her home roles; with none mapped, refused).

**Remote administrators** (callers with the `admin` role at home), by `sajhanet.users.remote_admin`:
`admin` (default, for a trusted net: they call tools here as administrators, as a guest with the `admin`
role when no account matches), `user` (like any linked or matched user; a name match gives no `admin`
role, only an explicit link to a local administrator does) or `refuse`. **Net administration** (blocks,
trust levels, links, role maps, name matching) changes only through an administrator signed in to this
server; the admin API refuses a caller that arrived through the net.

The SAJHA Net admin page lists the remote users seen, how each resolved (linked, name, role map, admin,
refused) and the resolver used, and links and unlinks them
(`GET /api/sajhanet/nets/{net}/users`, `POST|DELETE /api/sajhanet/nets/{net}/users/links`,
`PUT /api/sajhanet/nets/{net}/role-maps/{instance}`, `PUT /api/sajhanet/nets/{net}/name-matching/{instance}`).
A person who uses several consoles signs in once when those servers trust the same identity provider
([console single sign-on](../security/Security%20Model.md#console-single-sign-on)); each still maps the
person to its own user.

### 11.4 Blocking

An administrator can block, on their own server and per net, at five levels; a block takes effect on the
next request, may expire, carries a reason, and is audited (`block_added`, `block_removed`):

| Block | Effect |
|---|---|
| **An instance, entirely** | This server stops calling it (its proxies leave the catalog), refuses every call from it, and ignores its catalog and key-directory updates |
| **Inbound** | Refuses calls from that instance, while still calling its tools |
| **Outbound** | Stops calling that instance's tools (hidden from local users), while still serving its calls |
| **A tool** | Refuses calls to one of its tools from an instance (or all), or hides one remote tool from local users |
| **A remote user** | Refuses calls on behalf of `alice@risk-eu`, whatever her mapping |

Blocks are local decisions and shared information: each server publishes its blocks in a signed blocks
document, so any console can draw the picture, but only the server that set a block enforces it. A block
published against this server raises an info notice (`sajhanet.blocked_by:<net>:<member>`). Removing a
server from the whole net is not a block but a revocation (`builtin_ca`) or a removed pin (`manual`).
Blocks are managed on the SAJHA Net admin page and with `GET|POST /api/sajhanet/nets/{net}/blocks` and
`DELETE /api/sajhanet/nets/{net}/blocks/{block_id}`, and kept in the storage backend
(`<data_dir>/<net>/blocks.json`).

---

## 12. Data sovereignty and residency

Residency decides where classified data may flow between instances, in both directions
(`sajha/net/residency.py`, `sajha/net/integration/residency.py`; tests
`tests/net/test_net_residency.py`). The rule conditions belong to the policy engine and are in
[Policy and Audit](Policy%20and%20Audit.md#35-residency-rules-sajha-net) 3.5.

- **Data classes** come from `x-sajha-data-class` marks on `inputSchema` and `outputSchema` properties
  (nested objects and array items too; the marks are part of the contract hash), a tool's own
  `data_classes: {arguments, results}` (the whole tool), and `sajhanet.data_classes.tools` (classification
  by configuration, by tool name or glob, without editing the tool). Each exported tool carries a summary
  (`data_classes.arguments`, `data_classes.results`); at a home, a class in the summary without a field
  mark counts for the whole value.
- **Residency rules** are policy rules with the conditions `data_classes`, `flow` (`arguments` or
  `results`) and `destination` (`net`, `instance`, `region`, `labels.<key>`, `here`,
  `differs_from_here`), evaluated deny-overrides among residency rules only. With
  `sajhanet.residency.default_effect: deny`, classified data crosses only when a rule allows it.
  `sajhanet.residency.enabled: false` (or `policy.enabled: false`) turns the checks off.
- **Arguments.** Before a call leaves, the home checks the classes of the fields present against the
  host's region and labels from its member record. A deny is `-32012 residency_arguments` with
  `executed: false`, worded so a planner chooses a tool where the data may go; a call by plain name then
  moves to the next host. `redact: {data_classes: [...]}` sends the call with those fields replaced by
  `[REDACTED:<class>]` instead.
- **Results.** The host checks the classes of the fields in its result against the home's region and
  labels. A deny is `-32012 residency_result` with `executed: true`; a redaction replaces the fields in
  `structuredContent`, in JSON text blocks and wherever a removed value is quoted in text, and lists them
  in `_meta["io.sajha/net"].redacted`. A class marked for the whole result cannot be redacted field by
  field and is refused.
- **On arrival** the home applies its own rules (`flow: results`, `destination: {here: true}`): it may
  redact or refuse (`residency_result`, side `home`); a check that fails withholds the result.
- **Residency-aware shortlists.** A remote tool whose host may not receive the classes every call sends
  (whole-tool argument classes and those of required fields) is not eligible there
  (`not_eligible: residency rule` in the resolution order and on the Remote tools page); a tool no host
  may receive is left out of `tools/list` and of Ask SAJHA's shortlist for that caller.
- **Audit.** Every decision on classified data, on either side, is one `net.residency` record (net,
  other instance, tool, flow, classes, rule, side, redacted field paths, trace id; never values), counted
  in `sajha_net_residency_decisions_total{flow, outcome}`.
- **Memory.** Conversation memory keeps an answer that used remote results as written, with every
  figure replaced by `[remote figure]`, or as a placeholder (`sajhanet.memory.remote_results`:
  `store`, `summary`, `none`; `sajhanet.memory.by_class` per class, the strictest wins). RAG collections
  are built from documents only; no tool result enters them.

---

## 13. Planners, LLM tools and memory

- **Locality-aware shortlists** (`sajha/ai/locality.py`). Every shortlist entry (Ask SAJHA, LLM tools in
  `answer` mode) records where the tool runs (`local`, `remote` with its net and host, or `federated`)
  and why it ranked where it did. Local tools rank first, then remote hosts named in the tool's
  preferences, in this server's region, healthy, and with lower indicative latency: small nudges of the
  resolver's score, so a remote tool that is the right tool is still offered. Proxies of a host that is
  not `active`, or reports itself down, are left out; quarantined names are never offered.
- **Locality restriction**: `any`, `local` (this server's tools only) or `net:<name>` (this server's and
  that net's), from the ask (`locality` on `POST /api/ai/ask`), else the planner's `settings.locality`,
  else `ai.ask.locality`; the `shortlist` event names it and where it came from
  ([Planner Reference](Planner%20Reference.md)).
- **Remote LLM tools.** An LLM tool is exported with `llm_tool: true` unless
  `sajhanet.allow_remote_llm_tools` is false (the owner decided LLM and plain tools are equally trusted).
  Called from another instance it runs on its host as the mapped user, on the host's models and budgets;
  the host reports the run's spend in `_meta["io.sajha/net"].usage` (`tokens`, `cost_usd`, `models`,
  `charged_by: "host"`), which the home records in its `net.call_attempt` audit record and never charges
  again.
- **Memory is always local.** Conversation memory lives only on the server the user talks to. A remote
  tool, including a remote LLM tool, receives its arguments and nothing else; residency applies to them
  (section 12).
- **Budgets.** Local limits count remote calls like local ones; the host's own budgets apply to the work
  it does.

---

## 14. Hops, the call-chain budget, re-export and bridges

- **One hop by default.** A server exports only its own tools, never proxies it imported
  (`reexport: false`), so every forwarded call is one hop (`sajhanet.max_hops`, default 1, at most 8).
- **Hops and loops.** A forwarded call carries `Sajha-Net-Hop` and `Sajha-Net-Visited` (each entry
  `<net>/<instance>`). A receiver refuses one past its `max_hops` (`hop_limit`), one whose visited list
  contains any of its own identities in any of its nets (`loop`), or an inconsistent one
  (`hop_inconsistent`), all `-32016`.
- **The call-chain budget.** A chain that crosses instances and nests planners, LLM tools, composites and
  `sajha_ask` is bounded end to end by `sajhanet.max_call_chain` (default 8, at most 32): hops plus the
  nesting depth on every instance passed. The depth travels in `params._meta["io.sajha/net"].depth`, and
  the host runs the tool with that chain, so a call its tool makes onward continues the hop count and
  visited list (`sajha/core/inner_calls.py`). The home refuses before sending (`chain_limit` with `hops`,
  `depth` and `limit`; `loop` when the host is already on the chain), the host on receipt, and a tool
  entered inside a forwarded call past the budget is refused. `tools.max_call_depth` and
  `ai.llm_tools.max_depth` still apply on each instance. Proxied MCP servers carry a budget of their own
  between SAJHA servers ([Federation](Federation.md#proxies-all-the-way-down)).
- **Re-export within one net.** With `reexport` on for a net (advertised as the feature `reexport`), an
  imported tool goes onward only when a re-export rule names it (`sajhanet.reexport_rules`: `tools`,
  `from_nets`, `from_instances`, `to_instances`, `for_roles`). It carries `origin` and the host's contract
  unchanged (one name, one contract holds); it is never offered back to its host or origin, never under a
  local tool's name, and a server never imports a tool whose origin is itself. A home ranks direct offers
  before re-exported ones ("re-exported by ... from ..."), sends an assertion with `aud` = origin (never a
  key), and refuses to send a chain back to its host or origin (`loop`). The intermediary verifies the
  assertion with the origin as audience, maps and authorizes the caller (blocks, mapping, re-export rules
  in place of export rules, the key's tool access as a ceiling, its own access to the proxy), then relays
  the assertion unchanged with hop + 1 through its own router, so residency, hops and the chain budget
  apply on every step; a downstream refusal that did not execute comes back as the intermediary's with
  `refused_by`.
- **Bridges between nets.** A server in two nets never offers one net's tools in the other unless
  `reexport` is on for **the net it offers into**. Then a tool imported in net M is offered in net N as
  this server's own (no origin: nothing signed in M can be checked in N). A call from N runs as the local
  account the caller maps to, which calls into M with an assertion this server signs there (a guest
  mapping cannot cross a bridge); hops and the visited list continue, so loops through several nets are
  caught too.
- **Every instance on a chain must accept the extra hop**: raise `max_hops` to 2 for one intermediary, on
  the intermediary and the origin.

The tests are `tests/net/test_net_reexport_identity.py` and `tests/net/test_net_planners_llm.py`.

---

## 15. Reliability

- **Per-peer isolation** (`sajha/net/routing.py`). Each peer has its own circuit breaker
  (`sajhanet.peer.breaker_threshold` consecutive availability failures open it for
  `peer.breaker_reset_seconds`), outbound rate limit (`peer.calls_per_minute`), inbound rate limit
  (`peer.inbound_calls_per_minute`, `-32019 rate_limited` beyond) and timeout
  (`default_timeout_seconds`). Breakers and these rate limits are **per process**: with several workers
  each counts alone (section 5.5).
- **Graceful degradation.** A server that cannot reach the net still serves all its local tools; a plain
  name moves to the next host; a qualified name to an unreachable host fails fast.
- **Version skew.** Members advertise the protocol versions they speak; a peer below
  `sajhanet.min_protocol_version` is refused (`unsupported_version`).
- **Several workers.** Membership, catalogs, the host and tool table, quarantines, nonces and assertion
  `jti`s live in the state store (keys under `sajhanet:<net>:`), and trust levels, blocks, user links,
  pins, runtime seeds and first-use keys in the storage backend, so every worker sees the same net
  ([Scaling and State](Scaling%20and%20State.md)).

## 16. Observability and audit

**Audit.** Each side records a cross-instance call in its own tamper-evident audit chain
([Policy and Audit](Policy%20and%20Audit.md) section 7), sharing one trace id (W3C `traceparent`, sent in
the header and in `_meta`) and the key id (`linked_audit`, `sajha/net/integration/authz.py`):

| Record | Side | Holds |
|---|---|---|
| `net.call` | home | the name called, the resolution with each host's place, the outcome |
| `net.call_attempt` | home | one per attempt: number, net, host, outcome, `executed`, the identity sent (a per-member or test admin key is marked, never the key), a remote LLM tool's usage |
| `net.host_call`, `net.host_refused` | host | sender, tool (published) and `local_tool`, outcome, `executed`, identity, mapping, hops and visited list |
| `net.residency` | either | every residency decision on classified data (section 12) |
| `net.token_issued` | host | each host-scoped token issued (never the token) |

Administration and membership events are audit records with resource `sajhanet.<event>`:
`peer_added`, `peer_add_failed`, `runtime_seed_removed`, `pin_added`, `pin_removed`, `peer_key_remembered`,
`peer_key_forgotten`, `ca_initialised`, `ca_token_created`, `ca_token_refused`, `ca_revoked`, `enrolled`,
`renewed`, `certificate_renewed`, `name_conflict`, `self_seen`, `trust_changed`, `tool_approved`,
`tool_quarantined`, `tool_reactivated`, `tool_name_refused`, `remote_tool_offered`, `remote_tool_changed`,
`remote_tool_withdrawn`, `block_added`, `block_removed`,
`user_linked`, `user_unlinked`, `role_map_set`, `name_matching_set`, `key_directory_resync`,
`sponsored_added`, `sponsored_removed`, `sponsored_enrolled`, `plugin_failed`.

**Metrics** (on `/metrics`, [Observability](Observability.md)):

| Metric | Type | Meaning |
|---|---|---|
| `sajha_net_joined{net}` | gauge | this server has joined the net (1) or not (0) |
| `sajha_net_members{net, state}` | gauge | members known, by state |
| `sajha_net_name_conflict{net}` | gauge | this server is refused under a held name |
| `sajha_net_remote_tools{net, state}` | gauge | rows of the host and tool table |
| `sajha_net_contract_conflicts{net}` | gauge | tool names quarantined |
| `sajha_net_catalog_pulls_total{net}` | counter | catalog pulls from peers |
| `sajha_net_remote_calls_total{outcome}` | counter | calls to remote tools at this home |
| `sajha_net_fallbacks_total{outcome}` | counter | fallback attempts to another host |
| `sajha_net_residency_decisions_total{flow, outcome}` | counter | residency decisions on classified data |

Proxy calls also count in `sajha_tool_calls_total` under their qualified name, as every tool does.
**Tracing**: one trace spans home and host; SAJHA continues or starts a `traceparent` and sends it on the
forwarded call ([Observability](Observability.md#33-outbound-trace-context)).

---

## 17. The SAJHA Net console

The console follows SAJHA's conventions (the themes, page help with glossary terms, phone-width layouts
checked by `scripts/check_mobile.py`). Every page has JSON behind it, and the client CLI has the same
actions (`sajha net ...`, [Command Line](../clients/Command%20Line.md)), which call these APIs over HTTP
and run nothing locally. The data is read from the state store, this worker's registry and the audit
chain, never by calling peers on page load (`sajha/net/integration/console.py`, `overview.py`).

### 17.1 Pages

| Page | Route | Who | What it shows and does |
|---|---|---|---|
| **Instances** | `/net/instances`, `/net/instances/{net}/{instance}`, `/net/instances/this` | every signed-in user | Every participant of this server's nets, this server first (a net of one when SAJHA Net is off or no one else has joined): net, name, vendor, kind, region, labels, state and last seen, and how many of its tools this user may use here; search and filters by net, state, kind, region and label. An instance's page lists the tools it offers this user (name, qualified name, alias, description, inputs and outputs, health and latency) with the Tools page's Try it form. JSON: `GET /api/sajhanet/instances` |
| **Your net access** | `/net/access` | every signed-in user | Each remote tool by name, every host offering it in resolution order with its state and the host's member state, and whether this server lets the user call it there; this server's decision only, since the host decides again on every call. JSON: `GET /api/sajhanet/access` |
| **Net overview** | `/admin/sajhanet/overview?net=` | administrators | A net selector; totals (membership and gossip health, instances by state, admission mode, remote tools by state, notices, quarantined and held tools, active blocks); the **topology map**; members, gossip details, seeds and runtime seeds; this net's notices, quarantined names, description warnings and held tools (Approve); blocks set here and published by others; the admission panel; refused tool names; from the newest `net.*` audit records, recent forwarded calls, call-chain refusals and residency decisions; the router's counters. JSON: `GET /api/sajhanet/overview` |
| **Remote tools** | `/admin/sajhanet/tools` | administrators | The host and tool table with filters by net, host, state and trust; Approve and withdraw for tools held under `review`; the contract conflicts with every offer and hash |
| **SAJHA Net admin** | `/admin/sajhanet` | administrators | Membership, add a peer by address, runtime seeds (Remove), the admission panel, blocks, remote users, links and role maps, the key directory |

- **Topology map**: plain SVG drawn by `sajha/web/static/js/sajhanet.js` from
  `GET /api/sajhanet/topology?net=`: this server in the centre, the others on a ring, each node coloured
  by state and labelled in words when not `alive`; edges for `offers` (solid), `reexports` (dashed) and
  observed `calls` (thicker with more calls; counted per process since start). A table under the map
  lists the same nodes and edges. It refreshes every 30 seconds while visible; **Pause live view** stops
  it.
- **Admission panel** (Net overview and SAJHA Net admin), by the net's mode: `open`, the remembered
  first-use keys with **Forget**; `manual`, the pins from configuration and runtime, add and remove;
  `builtin_ca` on the CA instance, issued certificates with **Revoke** (a reason is required), waiting
  tokens, **Create token** (shown once) and **Initialise** when there is no CA key yet.
- **Confirmations**: every change (forget, pin, unpin, revoke, create a token, initialise the CA, remove a
  runtime seed, approve a held tool, add or remove a block) asks first in words that name its effect.

### 17.2 Where the net shows up elsewhere

- **Navbar:** a server in a net shows the badge **Net · `<instance name>`** beside the SAJHA wordmark,
  with a health dot (described in words on hover) and `+N` for further nets, linking to Instances.
- **Navigation:** a SAJHA Net menu: Instances and Your net access for every signed-in user; Net overview,
  Remote tools and SAJHA Net admin for administrators.
- **Tools page and Ask SAJHA**: section 8.3.
- **Problems** reach administrators as system notices (section 17.4), never as banners of SAJHA Net's
  own.

### 17.3 Page help

Each page's "About this page" panel names its glossary terms in `sajha/web/page_help.py` and links to
this guide; the definitions come only from the [Glossary](../../GLOSSARY.md#12-sajha-net).

### 17.4 System notices

SAJHA Net reports conditions that need a person through the general System Notices service (source
`sajhanet`, ids `sajhanet.<condition>[:<net>[:<subject>]]`), never through banners of its own: an error
shows on every console page, the dashboard lists every open notice, and the navbar counts them. Every
id, its severity, when it is raised and when it clears is in
[System Notices](System%20Notices.md#4-sources), together with the credential notices that concern a
net, `auth.test_admin_key` (critical) and `auth.plain_credentials`.

---

## 18. Threats and mitigations

| Threat | Mitigation |
|---|---|
| A server takes over a name | Names are held to the first key (open) or certificate lineage (CA, manual); a different key is refused with `name_conflict` and alerted on both sides; the CA will not enroll a held name |
| A rogue server joins the net | `builtin_ca`: only enrolled servers hold certificates; `manual`: only pinned thumbprints. **`open` admits any server that can reach a member and knows the net's name** (section 6.4): use it only where every reachable machine is yours |
| A request is forged, replayed or altered | Signatures over method, path, the important headers and a body digest, with a creation time and a nonce kept in the state store; responses are signed and bound to their request |
| A compromised member impersonates users | Hosts verify each user against their own key directory copy and rules, never "the server says so"; a key is accepted only from its home; role maps grant nothing by default |
| A forwarded API key is captured | Keys travel only in signed requests over HTTPS, only on the first hop, never logged, stored or traced, and accepted only from their home; a net that wants no key in transit uses `assertion` |
| The test admin key is left on | While `sajhanet.test_admin_key.enabled` is on every forwarded call carries it and runs as an administrator at every host that holds the same record: a critical notice shows on every page until it is turned off (section 10.2) |
| An administrator on one server takes over another | Net settings change only through an administrator signed in to that server; remote administrators' tool calls are governed by `remote_admin` and audited |
| The CA key is stolen | It lives only on the CA instance, owner-only; certificates are short-lived; revocation by name or serial |
| An enrollment token is stolen | Single use, short-lived, bound to one name, stored hashed, HTTPS only, rate-limited, one refusal reason for every failure |
| Key records are forged | Every record is signed by its home and ignored otherwise |
| False gossip | Indirect probes before suspicion; a member refutes suspicion itself; member records are signed by their subjects, whose certificate must name the record's URL host |
| A peer's description instructs the model | Descriptions screened and capped; `review` trust holds changes; results treated as untrusted data |
| Contract poisoning (a host offers a known name with other schemas) | Any difference quarantines the name everywhere, so no call reaches a differing copy; the cost is denial of service, mitigated by the loud error naming the odd host, blocks, revocation and `review` / `pinned` trust |
| Data leaves its jurisdiction | Residency rules on arguments at the home and on results at the host and on arrival; residency-aware shortlists |
| A server is used as a stepping stone | Dual authorization on the user's identity; no re-export by default; hop limits and the call-chain budget |
| A server in two nets leaks one into the other | Nets share nothing but the port; an unknown net gets a bare `404`; a bridge exists only where an administrator turns re-export on, and carries only its own user |
| A fallback runs a tool twice | After a possible execution only read-only or idempotent non-destructive tools fall back; otherwise only after a signed or self-evident "not executed" |
| Fallback used to shop for a host that says yes | A refusal is returned, never routed around |
| SSRF through a peer URL | URLs only from signed records whose host is in the certificate; `check_peer_url` with `sajhanet.allowed_networks`; ping-req targets are names, never URLs |
| A slow or hostile peer drags others down | Per-peer timeouts, breakers and rate limits; catalog caps; local tools unaffected |

The wire-level considerations are
[protocol §19](../protocol/SAJHA%20Net%20Protocol.md#19-security-considerations); SAJHA's security as a
whole is the [Security Model](../security/Security%20Model.md#sajha-net).

---

## 19. Configuration

Every key, its default and how it resolves is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net); this section shows
the shape. Scalar keys resolve as every `_get` key does (`SAJHA_SAJHANET_<KEY>` → YAML → default);
`sajhanet.nets` is YAML (or `SAJHA_SAJHANET_NETS`, a JSON list, which replaces it). Keys and certificates
are files (secret references), never values; secrets never go in `config/application.yml`.

```yaml
sajhanet:
  enabled: true
  base_url: https://sajha-risk-eu.example.internal     # what peers reach this server on
  region: eu-west
  labels: {domain: risk, jurisdiction: EU, entity: acme-eu}
  plugins: {admission: builtin_ca}                     # shipped: open (section 6.4)
  test_admin_key: {enabled: false}                     # shipped: true (section 10.2)
  nets:                                                # one entry per net, in preference order
    - name: acme-net
      instance_name: risk-eu
      seeds: [https://sajha-treasury-na.example.internal]
      ca: {enabled: false}                             # true on the net's one CA instance
      export:
        - {tools: ["var_*"], to_instances: ["*"], for_roles: ["risk_analyst"]}
      import:
        - {instances: ["*"], tools: ["*"], for_roles: ["analyst"]}
    - name: partner-net
      instance_name: risk-eu-partner
      seeds: [https://sajha-partner-hub.example.net]
      default_trust: review
  preferences:
    var_calc: ["acme-net/risk-eu", "acme-net"]
```

**Where keys live.** Only in a net entry: `name`, `instance_name`, `advertise_address`, `founder`,
`seeds`, `identity`, `ca`, `static_peers`, `export`, `import`. Server-wide only: among others
`enabled`, `nets`, the `plugins` (admission included), `preferences`, `max_fallbacks`,
`max_call_chain`, `allow_remote_llm_tools`, `residency`, `data_classes`, `memory`, `sponsored`,
`external_servers`, `peer_keys` and `test_admin_key`. The rest are shared defaults a net entry may
override for its own net; the Configuration Reference says which. Trust levels, blocks, user links, role
maps, pins, runtime seeds and first-use keys are not configuration: they are set on the console or the
admin API and kept in the storage backend.

On Kubernetes the chart's `sajhanet` values write these keys and hold the certificates and keys in
Secrets ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md#sajha-net)).

## 20. Storage

### 20.1 Database

The net key directory is the `sajhanet_api_keys` table, in both schema files
(`db/scripts/<dialect>/schema.sql`; [Database Setup](../getting-started/Database%20Setup.md)). The
default keys SAJHA Net forwards are API keys whose value is kept encrypted in `api_keys.secret_ciphertext`
([Security Model](../security/Security%20Model.md#api-keys)).

### 20.2 Files, the storage backend and the state store

| Where | What |
|---|---|
| Local disk, `sajhanet.data_dir` (default `data/sajhanet`, git-ignored) | per net: this server's key (`instance.key`, owner-only), certificate (`instance.crt`), the CA certificate (`ca.pem`), the revocation list it starts with (`revoked.json`), the CA key on the CA instance (`ca.key`), the saved peer list (`peers.json`); sponsored members' keys under `<net>/sponsored/<name>/` |
| The storage backend, under the same path | per net: the CA's state on the CA instance (`ca-state.json`: tokens as hashes, issued certificates, the signed revocation list), `runtime_seeds.json`, `pins.json`, `first_use.json`, `trust.json`, `blocks.json`, `users.json` (links, role maps, name-matching exceptions); and `sponsored.json` |
| The state store (`state.backend`) | per net under `sajhanet:<net>:`: membership and incarnations, catalogs and the host and tool table, quarantines and conflicts documents, seen nonces, assertion `jti`s, host-scoped tokens (hashed); the gossip agent's lease `sajhanet:agent:<net>` |

### 20.3 Credential files

API keys and users can also be defined in the administrators' credential files (`config/apikeys.json`,
`config/users.json`), which win over the database, and the database's keys are dumped to
`config/apikeys_db.json`; all three are git-ignored. Their records are published in the net key directory
like database keys. Precedence, the test admin record and plain or hashed storage are owned by the
[Security Model](../security/Security%20Model.md#credential-storage-and-files).

### 20.4 Periodic snapshots

SAJHA writes signed, chained snapshots of users, API key records and local tools with or without a net
([Policy and Audit](Policy%20and%20Audit.md#75-snapshots-of-users-api-keys-and-tools)). They do not yet
record the net view (proxies, membership, the key directory per home): section 5.5.

---

## 21. Operations

### 21.1 A first net

1. On every server: `sajhanet.enabled: true`, a `base_url`, and one net entry with an `instance_name`.
2. On the first server, no seeds: it is a net of one and, with `builtin_ca`, creates its CA at first
   start (back up the key; the `sajhanet.ca_created:<net>` notice says where).
3. On each further server, the first one as a seed. With `open` (shipped) that is all; with `builtin_ca`
   create a token on the CA instance (`sajha net ca enroll <name> --net <net>`) and enroll the new server
   with it (`sajha net enroll ...`).
4. Write export rules on the hosts and import rules on the homes, then check **SAJHA Net > Instances**
   and the Net overview.

[Tutorial 28](../tutorials/TUTORIAL_28_build_a_sajha_net.md) does this step by step;
[`deployment/sajhanet-demo/`](../../deployment/sajhanet-demo/README.md) runs three instances in
containers with a smoke script.

### 21.2 Several workers and Kubernetes

Several workers of one server need `state.backend: redis` or `database` (the gossip agent's lease,
membership, nonces and the host and tool table are shared there) and one configured `instance_name` with
an `advertise_address`. Per-peer rate limits and breakers stay per process (section 15). On Kubernetes
use the chart's `sajhanet` values ([Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md#sajha-net)).

### 21.3 Before a net spans machines you do not control

- Set `sajhanet.plugins.admission: builtin_ca` on every member (or `manual` for a small fixed net),
  and enroll every member with the net's CA (the mode is read at start; self-signed identities from open
  mode do not chain to a CA).
- Turn the test admin key off (`sajhanet.test_admin_key.enabled: false`) on every member, and remove the
  sample `sajhanet.peer_keys` entry.
- Keep `sajhanet.require_https` on, list your private ranges in `sajhanet.allowed_networks`, and decide
  `sajhanet.users.remote_admin` and `sajhanet.users.unknown` for each host.
- Consider `user_identity: assertion` when members should not see users' keys in transit.

### 21.4 Troubleshooting

Start from the notice ([System Notices](System%20Notices.md#4-sources)): it names the condition and links to this guide.
`GET /api/sajhanet/status` (or `sajha net status`) shows, per net, this server's name, URL, seeds and
runtime seeds, whether it joined or was refused, errors, features and the members it knows; the Net
overview shows recent forwarded calls and refusals with their trace ids, which join the home's and the
host's audit records.

### 21.5 Tests

`tests/net/` holds the multi-instance tests (one process, separate databases and keys:
`tests/net/test_net_three_instances.py` joins through a seed, exchanges catalogs, calls as a user, blocks,
falls back when a host is down, quarantines and re-activates a conflict, and restarts), one file per area
(names, signatures, membership, the CA, catalogs, routing, identity, keys, residency, re-export, vendors,
planners, console, plug-ins) and the mixed conformance run; the agent's own tests are in
`sajhanet_agent/tests/`.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
