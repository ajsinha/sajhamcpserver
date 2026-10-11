# Implementation Plan

> **Status: waves 1 to 7 done (between waves, 8.3.0 shipped qlrisk and tool domains, and 8.5.0 the outbound fetch guard); wave 8 done in its wrap-up scope (8.8.0 to 8.11.0); waves 9 to 16 planned (section 7c)** (the Status column of
> section 2 is the per-wave record). This is the build order for the two features,
> [LLM Tools](LLM%20Tools.md) (with the [Planner Reference](Planner%20Reference.md)) and
> [SAJHA Net](SAJHA%20Net.md) (with the [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md)),
> together with the open [Roadmap](Roadmap.md) items, grouped into waves (five planned at the start; wave 6 added by the owner). The designs say
> *what* to build; this plan says *in which order* and *what has to be true* before each wave is
> done. Items are referred to by the IDs and step numbers their owning documents use.

---

## Contents

1. [How the waves are cut](#1-how-the-waves-are-cut)
2. [Wave overview](#2-wave-overview)
3. [Wave 1: foundations](#3-wave-1-foundations)
4. [Wave 2: the model interface and LLM tools](#4-wave-2-the-model-interface-and-llm-tools)
5. [Wave 3: planners, authoring and the OpenAI endpoint](#5-wave-3-planners-authoring-and-the-openai-endpoint)
6. [Wave 4: SAJHA Net core](#6-wave-4-sajha-net-core)
7. [Wave 5: sovereignty, the console and other MCP servers](#7-wave-5-sovereignty-the-console-and-other-mcp-servers)
   - [Wave 7: per-user sign-in, access to prompts and resources, a hardened test suite](#7a-wave-7-per-user-sign-in-access-to-prompts-and-resources-a-hardened-test-suite)
   - [Wave 8: tool health, open data, business intelligence and reports](#7b-wave-8-tool-health-open-data-business-intelligence-and-reports)
   - [Waves 9 to 16: the backlog, then wave 8's remainder](#7c-waves-9-to-16-the-backlog-then-wave-8s-remainder)
8. [After wave 5](#8-after-wave-5)
9. [Gates every wave must pass](#9-gates-every-wave-must-pass)
10. [Risks and how the plan handles them](#10-risks-and-how-the-plan-handles-them)
11. [Where everything went](#11-where-everything-went)

---

## 1. How the waves are cut

- **Each wave is a release.** It ends merged to `main` with a version, a CHANGELOG section, its
  operator actions and green gates (section 9). Nothing half-built ships enabled: features land
  behind their configuration switches, off until the wave that completes them.
- **Shared foundations first.** Both features need the same groundwork: knowing the caller inside
  a tool, API keys that belong to users, tool calls in the audit chain, a lease that renews. That
  goes in wave 1, so neither feature builds its own version of it.
- **LLM tools before SAJHA Net.** SAJHA Net shares LLM tools across instances and gives planners
  remote tools to choose from (SAJHA Net section 13), so the LLM tool type and planners come
  first. SAJHA Net's membership and identity work does not depend on them and could start in
  parallel if two streams of work are wanted; the plan keeps them sequential by default to stay
  within the agreed limit on concurrent work.
- **Every wave carries its own documentation.** The design notes become as-built for the parts
  that shipped, with tutorials, glossary terms, help cards, the Configuration and API References,
  and the Security Model updated in the same wave, as with every earlier wave.
- **Roadmap items ride with the wave they fit.** Where an open Roadmap item touches the same code
  as a wave's main work, it is done in that wave; the rest are listed in section 8.

---

**How a wave runs.** Each wave is split into **phases** that run one after another; within a phase,
independent **streams** run in parallel (at most four at a time, usually two, to keep cost down).
Every wave ends with a phase that runs the combined gate (section 9), releases, and drills (commit,
merge to `main`, tag). The next wave starts right after. Each wave's phase table below shows its
streams, what each phase waits for, and its status.

## 2. Wave overview

| Wave | Release | Theme | Main content | Depends on | Status |
|---|---|---|---|---|---|
| 1 | 7.1.0 | Foundations | Caller identity in tools, API keys owned by users with a default key each, tool calls audited, renewing lease, system notices, release hygiene, CI | none | done (7.1.0) |
| 2 | 7.2.0 | Model interface and LLM tools | OpenAI-style canonical interface and providers, the LLM tool type and its modes, conversation memory and resource safety, `sajha_ask` moved onto the type | 1 | done (7.2.0) |
| 3 | 7.3.0 | Planners and authoring | Configurable planners and every shipped strategy, `auto`, Studio LLM tool creator and planner editor, sampling, the OpenAI-compatible endpoint | 2 | done (7.3.0) |
| 4 | 8.0.0 | SAJHA Net core | Named nets (several per server), membership with required seeds, CA, signed requests on one port, catalogs and proxy tools, resolution order and preferences, offline removal, one name one contract, waterfall fallback, identity across instances, blocks, the Instances page | 1 (3 for remote LLM tools) | done (8.0.0) |
| 5 | 8.1.0 | Sovereignty, console, other MCP servers | Residency, locality-aware planners, re-export, the full SAJHA Net console, sponsored servers, the agent and library, the extension's conformance suite | 4 | done (8.1.0) |
| 6 | 8.2.0 | Protocol uniformity between servers, and its security | Server to server on the same streaming MCP as client to server: progress, partial results, cancellation and input requests relayed to the client on its own transport, tasks at the home wrapping forwarded calls (Roadmap L17a; host-side tasks are L19), with security per event: signing, replay protection, residency on partial results (L17b) | 5 | done (8.2.0) |
| 7 | 8.4.0 | Per-user sign-in, access to prompts and resources, a hardened test suite | Roadmap X3 (prompts and data resources under the same allow/deny rules as tools), the Adversarial QA Plan's first automation (suite integrity and P0 attacks), Roadmap L18 (proxied MCP servers acting as each user: personal tokens, then OAuth; per-user sessions; the SAJHA Net connect relay), with GitHub and Atlassian as the first integrations | 6 | done (8.4.0) |
| 8 | 8.8.0–8.11.0 | Tool health, quantitative planners, open data, business intelligence and reports | Schema defaults applied, broken tools fixed or removed, a live tool check, domain descriptions, generated guide tables (8.8.0); a quantitative workspace and planners that compute figures with units and lineage (8.9.0); verified open data sources in their tool folders (8.10.0); a metrics layer and BI tools (8.11.0); report definitions, formats and narration under a numbers check (8.11.0, with BI). Roadmap L21–L59 | 7 | done, in its wrap-up scope: 8.1 (8.8.0), 8.2 (8.9.0), 8.3 P1 (8.10.0), 8.4 and 8.5 cores (8.11.0); the slipped parts are Roadmap rows |
| 9 | 8.12.0 | Platform depth | Ask SAJHA over MCP finished (X7), protocol gaps (X12), async provider paths (X9), federation carrying every MCP feature (L2), `service_with_user` and an approval rule for proxied writes (L20), workflow engine limits (L3), API Import multipart and pagination (L4) | 8 | planned |
| 10 | 8.13.0 | Operations and scale | A benchmark suite with published numbers (X13), SLOs and failure tests (X14), federation at gateway scale (L10), push-based reload (X11), storage finished (L1) | 9 | planned |
| 11 | 8.14.0 | Security and ecosystem | Sandbox egress proxy and warm pool (L6), a container per federated stdio server (L9), signed plugins and a catalog (L12), SaaS provider packs (L11), RAG sources through connected accounts with OCR (X8), Weaviate and Chroma (X10), tool quality reach (L5), provider tool gaps (L7) | 10 | planned |
| 12 | 8.15.0 | Finishing | SAJHA Net finished and tasks held at the host (L16, L19), planners chosen by learning from results (L15), the console in other languages (L14) | 11 | planned |
| 13 | 8.16.0 | Cleanup and hardening | Runtime files untracked, the legacy `test/` folder archived, the `tools.apply_schema_defaults` switch removed, every tool fetch through the outbound guard, known broken tools fixed, cassettes for the wave 8 tools, a tighter numbers check, policy-denied tools not offered to Ask SAJHA, domain text in Studio, a faster test suite | 12 | planned |
| 14 | 8.17.0 | Reports finished | Delivery with approval and scheduling (L48), PNG charts in PPTX and DOCX (L46), the Studio Report creator (L49), more flagships (L50), figure lineage on the Ask page and `x-sajha-unit` (L60) | 13 | planned |
| 15 | 8.18.0 | Business intelligence finished | Cohort retention, anomalies, forecast (L41); dataset catalogue, profiling and data quality (L43); dashboards and the BI page (L44) | 14 | planned |
| 16 | 8.19.0 | Open data P2 and P3 | CFTC, Eurostat and OECD, the statistics offices, BLS, BEA and EIA (L32–L35); hazards, research, news events, public spending (L36–L39), each source's terms checked again first | 15 | planned |
Wave 4 is a major version because it adds a new table (`sajhanet_api_keys`), new columns on
`api_keys` and a new signed protocol surface; operators must apply schema changes on PostgreSQL by
hand, as for every schema change.

---

## 3. Wave 1: foundations

**Goal:** the groundwork both features stand on, plus the release hygiene the Roadmap lists as
"Now". Nothing user-visible beyond API-key self-service and better audit.

| Item | Source | Notes |
|---|---|---|
| Inner tool calls run as the caller; depth and cycle context | LLM Tools step 1 | Also fixes `sajha_ask`'s fixed `mcp:sajha_ask` identity (Roadmap X7, part) |
| API keys owned by users: authenticate as the owner with the owner's roles; `owner_id` set; self-service keys; revocation record; a default key for every user, kept encrypted in the accounts vault; an account page for keys | SAJHA Net §10.2 (what must change), new-code item 1 and 11 | Changes how existing keys authenticate: an operator action and a migration path for unowned keys (they keep `api_consumer` until assigned) |
| Persistent API keys in a hashed file; untrack `config/apikeys.json`; snapshots of users, keys and tools (work without a net) | SAJHA Net §20.3–20.4, new-code item 10; Roadmap N5 | |
| Every tool call as an audit event (not only policy and admin events), trace id in details; outbound `traceparent` | SAJHA Net new-code item 3 | Volume control: sampling and SIEM routing documented |
| Per-user key option for the tool result cache | SAJHA Net new-code item 4 | |
| A renewing state-store lease (claim, renew, release) | SAJHA Net new-code item 7 | Used later by the gossip agent and the memory purge |
| System notices: service, console banner, dashboard System status panel, navbar badge; first sources (schema check, breakers, failed jobs, provider down) | [System Notices](System%20Notices.md) | Later waves add their own sources: LLM tools in wave 2, SAJHA Net in wave 4 |
| Planner and other YAML files loaded without YAML 1.1 surprises | Planner Reference §16 | Whatever fix the reconciled design adopts |
| 6.0.0 SQLite upgrade message prints the SQL | Roadmap N2 | |
| The test suite in CI | Roadmap N3 | Every later gate runs there |
| One rate limiter | Roadmap N4 | |
| Revocable sign-in | Roadmap X4 | Needed before keys and sessions become net identities |
| Upgrade helper for schema changes (prints, never runs, DDL) | Roadmap X17 | Makes waves 2 and 4's schema changes easy for operators |

**Phases** (done; released as 7.1.0)

| Phase | Streams, in parallel | Depends on | Status |
|---|---|---|---|
| 1.1 | A identity and API keys ‖ B audit, tracing, cache, lease ‖ C system notices ‖ D hygiene and snapshots | none | done |
| 1.2 | Combined gate (suite, conformance, mobile), release 7.1.0, drill | 1.1 | done |

**Exit:** gates of section 9; a user can create, rotate and revoke their own keys; every tool call
is in the audit chain; CI runs the full suite on every push.

---

## 4. Wave 2: the model interface and LLM tools

**Goal:** the portable model interface and the LLM tool type, with memory and resource safety, so
that governed LLM tools work end to end with the existing four planners.

| Item | Source | Notes |
|---|---|---|
| Canonical OpenAI-style interface: Chat Completions types, gateway and model interfaces, adapters (pass-through for OpenAI-compatible servers), declared capabilities, field coverage, the mock in the same format, golden translation tests, portability suite | LLM Tools step 2, §13 | Converters keep today's callers working while they move |
| Native async providers, Vertex AI, Entra ID | Roadmap X9 | Same code as the adapters |
| The `LLMTool` type, config validation, modes `answer`, `complete`, `extract`, `classify`; derived annotations; lint rules | LLM Tools step 3 | |
| Conversation memory: handle, `tool_name` and `expires_ts` columns, turn folding, scheduled purge, `client` history | LLM Tools step 6 | Schema change in both files; operator note |
| Resource safety: working-set budget, spool and janitor, concurrency limit and queue, memory guard, optional hot cache, state-store caps; the soak test | LLM Tools step 7 | The pressure test is a gate of this wave; the memory guard raises system notices (wave 1's service) |
| Modes `grounded`, `narrate`, `judge`; caching for deterministic modes | LLM Tools step 8 | |
| Documents (PDF, Word) as RAG sources | Roadmap X8 | Makes `grounded` useful beyond text files |
| `sajha_ask` moved onto the type; shipped example tools (off); eval sets | LLM Tools step 9; closes Roadmap X7 | |

**Phases** (done; released as 7.2.0)

| Phase | Streams, in parallel | Depends on | Status |
|---|---|---|---|
| 2.1 | A OpenAI-style model interface and providers ‖ B conversation memory and document sources | wave 1 | done |
| 2.2 | C LLM tool type, modes, resource safety, `sajha_ask` ‖ D pluggable sqlite-vec document store (owner addition); Ask page "Servers and tools" log (owner addition) | 2.1 | done |
| 2.3 | Combined gate, release 7.2.0, drill | 2.2 | done |

**Exit:** gates of section 9; the soak test drives the process to its soft and hard memory limits
without a crash; every provider passes the portability suite; eval sets pass on the mock.

---

## 5. Wave 3: planners, authoring and the OpenAI endpoint

**Goal:** strategies become configuration, authors get tools to build LLM tools and planners, and
SAJHA becomes usable from any OpenAI-style client.

| Item | Source | Notes |
|---|---|---|
| Planner engine: stage library, validation, bounded loops, state, `when` language, registry, versions; built-ins as files | LLM Tools step 4; Planner Reference | The built-ins' existing tests pass against both forms |
| Shipped strategies and `auto` (selection and escalation); planner resolution and `planner_choices`; dry run; per-stage events and metrics | LLM Tools step 5, §9.12–9.13 | |
| Studio LLM tool creator; planner editor with validation and dry run; Describe-a-tool proposals; conversations page | LLM Tools step 10 | |
| Studio permissions per creator, and ownership | Roadmap X2 | Lands with the new creators |
| Sampling (`prefer`, `require`) on both eras | LLM Tools step 11 | Built for `complete`, `extract`, `classify`, `judge` |
| SAJHA as an OpenAI-compatible endpoint; LLM tools listed as models | LLM Tools step 12 | Built (`tests/ai/test_openai_api.py`, with the `openai` SDK) |
| One LLM package boundary: everything LLM in `sajha/ai/llm/` (gateway moved in, the legacy `sajha.ai.providers` layer retired), application code using only the OpenAI-style public API and the abstract provider and model classes, old message types removed from callers; an `LLMFactory` (from configuration and the registry) as the only way to obtain providers and models, returning a `GovernedModel` proxy that applies policy, budgets, cache, retries, breakers, fallback, audit and usage before delegating to the provider model, with vendor specifics delegated to per-provider functions; and an architecture test that fails on any vendor SDK, provider module, direct construction or old type used outside the package | Owner decision; LLM Tools §13 |
| Console end-to-end and accessibility checks | Roadmap X15 | The new editor pages are their first users |
| LLM Tools, Planner Reference and Intelligence Layer docs become as-built; tutorials | LLM Tools step 13 | |

**Phases**

| Phase | Streams, in parallel | Depends on | Status |
|---|---|---|---|
| 3.1 | A planner engine and shipped strategies ‖ B OpenAI-compatible endpoint and MCP sampling | wave 2 | done |
| 3.2 | C authoring: Studio LLM tool creator, planner editor with dry run, Describe-a-tool proposals, conversations page, Studio permissions per creator (X2), console end-to-end and accessibility checks (X15) ‖ D LLM package boundary: factory, governed model proxy, old types retired from callers, architecture test | 3.1 | done |
| 3.3 | Comparison page update, docs as-built and tutorials, combined gate (suite, conformance, mobile, evals), release 7.3.0, drill | 3.2 | done |

**Exit:** gates of section 9; every shipped strategy has path and bound tests; an OpenAI SDK
client completes a chat and calls an LLM tool as a model.

---

## 6. Wave 4: SAJHA Net core

**Goal:** SAJHA servers form a net, share tools and know who is calling, with the safety rules in
place from the first release.

| Item | Source | Notes |
|---|---|---|
| Protocol-only core and every plug-in interface with contract tests | SAJHA Net phase 1, §5.3–5.4 | |
| Named nets, several per server, each fully separate, chosen per request by the signed `Sajha-Net-Name` header on the one port; `sajhanet.nets` configuration with shared defaults; an unnamed net is `default` | SAJHA Net phase 1, §6.1, §6.7, §19; Protocol §5.1, §7.7 | |
| Instance names per net (configured and address names, collisions refused loudly), the CA run by SAJHA (one per net), signed requests on one port, revocation, gossip with leases | SAJHA Net phase 1, §6; Protocol §5, §8–9, §14 | |
| Required seeds (`founder: true` exempt); restarts trying seeds first, then the peer list saved on local disk every 10 minutes and on change, then discovery; "not joined" notice and back-off; an administrator adding a peer by address (console, admin API, `sajha net peers add`), optionally kept as a runtime seed | SAJHA Net §6.6; Protocol §9.7, §9.9 | |
| Extension advertised on both eras | SAJHA Net new-code item 2 | |
| Catalog exchange (everything about a tool shared), the live host and tool table, trust levels, proxy tools with the federation changes (`<net>__<instance>__<tool>` names, `.` replaced, annotations corrected, old version kept under `review`) | SAJHA Net phase 2, new-code item 5 | |
| Offline hosts: tools removed at once on `left` and `dead`, marked unavailable on `suspect`; nothing remote listed after a restart until peers answer | SAJHA Net phase 2, §8.5; Protocol §10.6 | Replaces the earlier grace period and "unconfirmed" tools |
| Resolution order of plain names (local, per-tool preferences, nets in order) shown in the table and console; long names mapped to per-request aliases for model providers | SAJHA Net phase 2, §8.2, §8.6 | The provider aliasing sits in wave 2's model gateway |
| One name, one contract: contract hash, quarantine on any difference, published conflicts, automatic re-activation, notices | SAJHA Net phase 2, §8.7; Protocol §10.7 | |
| Waterfall fallback after "not executed" failures, `executed` in host refusals, `max_fallbacks`, shared deadline, per-attempt audit and metrics | SAJHA Net phase 2, §9.1; Protocol §15.8, §17 | |
| SAJHA Net's system notice sources | SAJHA Net §17.4; [System Notices](System%20Notices.md) | On wave 1's notices service |
| A SAJHA Net network allowlist for the SSRF guard | New-code item 6 | |
| Imported schemas validated as JSON Schema | New-code item 13 | |
| Identity resolver and the `api_key` resolver; the net key directory; users across instances; blocks; export and import rules; role maps; linked audit; metrics; per-peer isolation | SAJHA Net phase 3 | Builds on wave 1's owned keys |
| Cancellation reaches the host | New-code item 12 | |
| The Instances page for every signed-in user and the navbar badge; minimal admin pages for membership, blocks, certificates and the conflicts queue | SAJHA Net §17 (subset) | The full console is wave 5 |
| Helm value for the nets list (each net's instance name, advertise address and seeds) | New-code item 9 | |

**Phases**

| Phase | Streams, in parallel | Depends on | Status |
|---|---|---|---|
| 4.1 | A protocol core and plug-in interfaces, membership (names and collisions, CA, signed requests on one port, gossip, restarts, peer cache, admin peer injection) ‖ B changes to existing code (federation names and annotations, SSRF network allowlist, extension on both eras, cancellation to the host, imported schema validation, Helm values) | wave 3 | done |
| 4.2 | C catalogs and routing (catalog exchange, host and tool table, proxies, named nets and preferences, one name one contract with quarantine, offline removal, waterfall fallback) ‖ D identity and authorization (API-key resolver, key directory, users across instances, blocks, export and import rules, role maps, linked audit, notice sources) | 4.1 | done |
| 4.3 | Instances page and navbar badge, minimal admin pages; three-instance test net (in process and as containers); SAJHA's conformance cases; combined gate, release 8.0.0, drill | 4.2 | done |

**Exit:** gates of section 9; a three-instance test net (in one process and as three containers)
joins through its seeds, survives restarts (seeds down: through the saved peer list) and a crash,
refuses a name collision, exchanges catalogs, removes a crashed host's tools when it is dead,
quarantines a tool two hosts disagree about and re-activates it when they agree, falls back to a
second host when the first is down, and answers a call as the right user on each host; one server
in two nets keeps them apart; the extension's conformance cases for SAJHA pass.

---

## 7. Wave 5: sovereignty, the console and other MCP servers

**Goal:** the parts that make SAJHA Net worth adopting in a regulated organisation, and opening it
to servers that are not SAJHA.

| Item | Source | Notes |
|---|---|---|
| Residency: data classes, policy conditions for data class and destination, field-level redaction, residency-aware shortlists, memory handling of remote results | SAJHA Net phase 4, new-code item 8 | |
| Locality-aware planners, remote LLM tools, hop and depth limits combined | SAJHA Net phase 5 | Needs wave 3 |
| Re-export with hop limits; `assertion` and `token_exchange` resolvers; topology view | SAJHA Net phase 6 | |
| The full SAJHA Net console | SAJHA Net phase 7 | |
| Sponsored MCP servers; the SAJHA Net agent (Python) and reference library; the extension's conformance suite for all three targets; third-party plug-in registration | SAJHA Net phase 8 | |
| Single sign-on for the console | Roadmap X5 | Console users of several instances |
| Browser and transport hardening | Roadmap X6 | More pages, more cross-instance traffic |
| SAJHA Net docs as-built; tutorial "two domains, one question" | SAJHA Net phase 9 | |

**Phases**

| Phase | Streams, in parallel | Depends on | Status |
|---|---|---|---|
| 5.1 | A residency (data classes, policy conditions, field redaction, shortlists, memory handling) ‖ B locality-aware planners, remote LLM tools, combined hop and depth limits | wave 4 | done |
| 5.2 | C re-export and the assertion and token-exchange resolvers ‖ D the full SAJHA Net console | 5.1 | done |
| 5.3 | E sponsored servers, the agent and library, the extension's full conformance suite ‖ F console single sign-on (X5), browser and transport hardening (X6) | 5.2 | done |
| 5.4a | Vendors and external servers (an external server is never a member: the SAJHA that defines it proxies its tools as `vendor__tool`); self-recognition by key and URL (owner design) | 5.3 | done |
| 5.4b | Full documentation review and rewrite against the code, consolidating overlapping documents (owner request) | 5.4a | done |
| 5.4c | New tutorials for every wave 4 and 5 capability, including the local test lab (Ollama, Qwen, three instances on one host) with its launcher script | 5.4a | done |
| 5.4d | Comparison page update, deck, combined gate, release 8.1.0, drill | 5.4b, 5.4c | done |

**Exit:** gates of section 9; a mixed net (SAJHA instances, an agent-fronted server, a sponsored
server) passes the conformance suite and the end-to-end residency tests.

---

## 7a. Wave 7: per-user sign-in, access to prompts and resources, a hardened test suite

Owner decision, 2026-10-10, after release 8.3.0. Design for the main item:
[Per-User Sign-In for Proxied Servers](Per-User%20Sign-In%20for%20Proxied%20Servers.md).

| Phase | Streams, in parallel | Depends on | Status |
|---|---|---|---|
| 7.1 | A: Roadmap X3 — prompts and data resources under the same allow/deny rules as tools, for API keys, roles and remote callers ‖ B: the [Adversarial QA Plan](Adversarial%20QA%20Plan.md)'s first automation — random test order, a shifted clock, failing on unexpected skips, a clean install in CI, and its P0 attack tests | 8.3.0 | done |
| 7.2 | L18 part 1: credential modes, the vault lookup at call time, `token_user` (personal tokens) end to end, the "connect your account" answers on every transport, the Connections view | 7.1 | done |
| 7.3 | L18 part 2: `oauth_user` (discovery, PKCE, refresh, resource indicators), per-user sessions and discovery, the SAJHA Net connect relay, audit and revocation; GitHub and Atlassian templates and guides updated from proposal to built; a tutorial; release 8.4.0 | 7.2 | done (8.4.0) |

## 7b. Wave 8: tool health, open data, business intelligence and reports

Owner decision, 2026-10-11, after release 8.6.0. The owner asked for the tools to be built, placed
in existing tool folders where they fit and in new ones where they do not. The same day the owner
approved quantitative planners ("add to the roadmap and build at the first opportunity"), placed as
phase 8.2, ahead of open data. Wave 8 is five phases, and each phase is a release. The designs are:

- [Tool Quality §12](Tool%20Quality.md#12-tool-health-wave-8-phase-81) (tool health);
- [Architecture §5](Architecture.md#domain-descriptions) (domain descriptions);
- [Quantitative Planners](Quantitative%20Planners.md);
- [Open Data Tools](Open%20Data%20Tools.md);
- [Business Intelligence](Business%20Intelligence.md);
- [Reports](Reports.md).

The Roadmap rows are L21–L59.

| Phase | Streams, in parallel | Depends on | Release | Status |
|---|---|---|---|---|
| 8.1 | A schema defaults applied on every call path, with the per-tool decisions and their compatibility list (L21) ‖ B broken tools fixed or removed, with the shared SDMX client (L22) ‖ C the live tool check, its notice source and the `missing-example` lint, with structured examples added to every shipped tool (L23) ‖ D domain descriptions (L24) and the generator for Tool Reference Guide tables with `--check` (L25) | 8.6.0 | 8.8.0 | done (8.8.0) |
| 8.2 | Quantitative planners: A the quantitative workspace (quantities with units, as-of and source), the operation library, the numbers validator and the `numbers_check` setting (L51, L57) ‖ then, on A: B `calc_graph` and `estimate_then_compute` (L52) ‖ C `scenario`, and `data_analyst` with the tool-result loader (L53, L54) ‖ D `code_act` and `optimize` (L55, L56). Then `research_writer` and `reconcile` (L58), router and `auto` candidates and the quantitative eval sets (L59) | 8.1 | 8.9.0 | done (8.9.0) |
| 8.3 | P1 sources: A calendars and GLEIF (L26, L27) ‖ B BIS and US Treasury (L28, L29) ‖ C sanctions (L30) ‖ D FDIC (L31). Then P2: CFTC, Eurostat and OECD, the three statistics offices, BLS, BEA and EIA (L32–L35). Then P3: hazards, research, GDELT, spending (L36–L39). P2 and P3 may slip to a later release by the owner's decision; P1 may not | 8.1 (shared SDMX client, defaults, live check) | 8.10.0 | P1 done (8.10.0), with the Wikidata tools; P2 and P3 slipped (owner: wrap up soon) |
| 8.4 | A metrics layer and `bi_query_metric` (L40) ‖ B analysis tools on the OLAP engines (L41), started once A's compiler is merged ‖ C charts, and `bi_load_tool_result` over the loader built in 8.2 (L42) ‖ D catalogue, profiling and data-quality suites, then dashboards (L43, L44) | 8.3 (open data tools to blend and chart), 8.2 (the tool-result loader) | 8.11.0 | A and C done (8.11.0), B in part (compare, top N, crosstab, explain change); cohort, anomalies, forecast and D (catalogue, quality, dashboards) slipped |
| 8.5 | A report definitions, engine, tools and history (L45) ‖ B formats (L46) ‖ C narration with the numbers check (L47) ‖ D delivery, approval, scheduling and audit (L48). Then the Studio Report creator and the library page (L49) and the flagship reports (L50) | 8.4 (metric tiles and charts), 8.2 (the numbers validator) | 8.11.0 | A, B and C done (8.11.0, shipped together with 8.4); D (delivery, scheduling) and the Studio creator slipped |

Each phase ends the way every phase does. It turns its guide sections from planned to as-built and
adds a tutorial, glossary terms and help cards. Then the combined gate runs (section 9), and the
phase releases and drills (commit, merge to `main`, tag). At most four streams run at once.

**Phase gates, in addition to section 9:**

- **8.1**
  - The live tool check reports no `error` or `schema_mismatch` for any shipped tool that has a
    key configured in CI's live job.
  - Every tool removed in 8.1 is listed in the CHANGELOG with its replacement.
  - `python -m sajha.tools guides --check` is clean.
  - Lint reports no `required-default` and no `openbb-command`.
- **8.2**
  - The quantitative eval sets pass on the mock provider in CI, including the scripted wrong graphs
    and wrong units, which must be refused and re-planned.
  - Every figure in a quantitative planner's answer has lineage back to tool calls, and the
    numbers validator rejects an invented figure under `numbers_check: enforce`.
  - `code_act` is never offered to a role outside `ai.quant.code_act.roles`; `optimize` never
    answers with a solution that fails its feasibility check.
- **8.3**
  - Each source's licence, key and rate-limit facts in [Open Data Tools](Open%20Data%20Tools.md)
    are re-checked live in the week of the release.
  - Every new tool has a probe case and a cassette, so CI never calls the live service.
  - Attribution lines appear in tool output where the licence asks for them.
- **8.4**
  - Compilation tests prove that no caller value reaches SQL text.
  - A metric cannot read a table its connector denies.
  - Loaded tool results are invisible to other users.
- **8.5**
  - The narration validator's rejection tests pass: an invented figure is never delivered.
  - External delivery waits for approval.
  - Every flagship report renders in every format whose dependency is installed.

## 7c. Waves 9 to 16: the backlog, then wave 8's remainder

Owner decision, 2026-10-11, after release 8.11.0: continue with the open Roadmap rows first (waves 9
to 12), then cleanup and the parts of wave 8 that were cut to wrap it up (waves 13 to 16). The
TypeScript client SDK (X16) is dropped. Each wave is one release, built in phases of at most four
parallel streams, and passes the gates of section 9.

| Phase | Streams | Release | Status |
|---|---|---|---|
| 9.1 | A Ask SAJHA over MCP finished (X7) ‖ B protocol gaps (X12) ‖ C async Bedrock and embeddings (X9), `service_with_user` and the proxied-write approval rule (L20) ‖ D API Import multipart and pagination (L4) | 8.12.0 | planned |
| 9.2 | A federation: resource templates, completions, subscriptions, upstream tasks, `ui://` views, 2025-11-25 upstream requests (L2) ‖ B workflow sub-graph bodies, trigger relay through the state store, opt-in replay of missed slots (L3) | 8.12.0 | planned |

Waves 10 to 16 are cut into phases when each starts; their content is in section 2 and the Roadmap.

## 8. After wave 5

**Wave 6 (decided by the owner, 2026-10-07): protocol uniformity between servers, and its
security.** Roadmap L17 (its row removed once built; host-side tasks, deferred by the owner, are
[L19](Roadmap.md)): server to server speaks the same streaming MCP as client to
server, so progress, partial results and cancellation reach the client as the remote work builds,
over whatever transport the client chose (L17a); and the security that goes with it, per event
(L17b). Both are in wave 6; it ships as its own release, 8.2.0.

| Phase | Streams, in parallel | Depends on | Status |
|---|---|---|---|
| 6.1 | A signed streaming hop (event chain, host stream at execution, home stream reader, limits, the new refusals, FB-07) ‖ B protocol sections and conformance cases | wave 5 | done |
| 6.2 | A progress and cancellation on every client transport ‖ B residency on streamed events, audit of streams | 6.1 | done |
| 6.3 | A input requests (MRTR) across the net, a task at the home wrapping the streamed call ‖ B guides, configuration, glossary, tutorial | 6.2 | done |

Other open Roadmap items not placed in a wave, in suggested order. Each keeps its Roadmap entry as
the owner of its detail.

| Item | Why not earlier |
|---|---|
| X13 benchmark suite with published numbers, then X14 SLOs and failure tests | Most useful once LLM tools and SAJHA Net exist to measure; CI (wave 1) is its prerequisite |
| X10 Weaviate and Chroma connectors, X11 push-based reload, X12 protocol gaps | Independent, small to medium |
| L1–L7: storage, federation, workflows, API import, tool quality, sandbox, provider tools | Finishing work on existing features |
| L9–L12: container per stdio server, gateway scale, SaaS packs, signed plugins | Larger enhancements; L12 pairs naturally with SAJHA Net's plug-ins |
| L13 one-click deployment templates, L14 console in other languages | Packaging and reach |
| L16's remaining items, L19 host-side tasks across a net (deferred by the owner), L20 the rest of per-user sign-in | Remainders of features built in waves 5 to 7 |
| L15 planners chosen by learning from results | Needs traffic and eval history from waves 3–5 |
| X16 TypeScript client | Dropped by the owner (2026-10-11) |

---

## 9. Gates every wave must pass

- The full test suite, in CI, with no failures, in default and random order.
- Both MCP conformance suites (2025-11-25 and 2026-07-28) at full pass.
- `scripts/check_mobile.py` clean in all four themes for every new or changed page.
- Doc-rot, help-catalog and glossary tests; every new page and guide has its help card.
- Schema files in sync with the models (`tests/test_db_schema.py`), proved on a real PostgreSQL
  by running the schema file; no DDL run by SAJHA on PostgreSQL.
- Wave-specific gates listed under each wave (soak test, portability suite, strategy path tests,
  multi-instance tests, extension conformance).
- When a wave ships a capability that changes an answer on the comparison page
  (`sajha/web/competitive.py`), the comparison is updated in that wave, every claim about another
  product checked against its own documentation and cited: expected after wave 3 (LLM tools,
  configurable planners, the OpenAI-compatible endpoint) and wave 5 (SAJHA Net).
- After wave 5, a full documentation pass (README, docs map, tutorials sequence, glossary, help
  cards, the deck), as before 7.0.0.
- A CHANGELOG section with operator actions, a version bump everywhere the version is copied
  (configuration, banner, client SDK, Helm chart, rendered manifests), a merge to `main` and a tag.

---

## 10. Risks and how the plan handles them

| Risk | Handling |
|---|---|
| Changing how API keys authenticate (wave 1) breaks existing integrations | Unowned keys keep today's behaviour until an administrator assigns an owner; the console lists them; the CHANGELOG states the operator action |
| The canonical model interface (wave 2) touches every provider | Converters let callers move one at a time; golden translation tests per provider; the portability suite runs on every change |
| Configurable planners loop or overspend | Bounded edges are a load-time rule; global ceilings always apply; bound tests are a gate |
| Memory pressure under real load | The wave 2 soak test is a gate, not a follow-up |
| SAJHA Net is a large surface (waves 4–5) | Split across two releases; the protocol-only core and contract tests come first; the conformance suite pins behaviour before other implementations exist |
| Schema changes on PostgreSQL are manual | Every schema change is in both files, listed as an operator action, and printed by the upgrade helper from wave 1 |
| Scope creep from new ideas mid-wave | New ideas go to the Roadmap; a wave's scope changes only by the owner's decision, recorded here |

---

## 11. Where everything went

Every build step and phase of the two designs, every new-code item the SAJHA Net design lists,
the System Notices design, and every open Roadmap item appears exactly once in this plan:

| Source | Placed in |
|---|---|
| LLM Tools steps 1–13 | 1: wave 1; 2, 3, 6, 7, 8, 9: wave 2; 4, 5, 10, 11, 12, 13: wave 3 |
| SAJHA Net phases 1–9 | 1, 2, 3: wave 4 (with wave 1's identity groundwork; named nets, seeds and restarts, offline removal, resolution and preferences, one name one contract and waterfall fallback are in phases 1 and 2); 4, 5, 6, 7, 8, 9: wave 5 (Instances page and badge from phase 7 come early, in wave 4) |
| SAJHA Net new-code items 1–13 ([SAJHA Net design note, "new code this design needs"](../archive/SAJHA%20Net%20Design%20Note.md)) | 1, 3, 4, 7, 10, 11: wave 1; 2, 5, 6, 9, 12, 13: wave 4; 8: wave 5 |
| Roadmap Now (N2–N5) | wave 1 |
| Roadmap Next (X2–X17) | X4, X17: wave 1; X7 (closed), X8, X9: wave 2; X2, X15: wave 3; X5, X6: wave 5; X3: wave 7; X10–X14, X16: section 8 |
| Roadmap Later (L1–L50) | L16 (SAJHA Net): waves 4–5; L17: wave 6; L18: wave 7; L21–L50: wave 8; L19 and L20 (added after waves 6 and 7) and all others: section 8 |
| System Notices | wave 1 (service, console, first sources); its later sources with the waves that add them (LLM tools: 2; SAJHA Net: 4) |

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
