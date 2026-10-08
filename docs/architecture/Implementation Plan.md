# Implementation Plan

> **Status: waves 1 to 5 done (8.1.0); wave 6 in progress** (the Status column of
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
| 6 | 8.2.0 | Protocol uniformity between servers, and its security | Server to server on the same streaming MCP as client to server: progress, partial results, cancellation, input requests and tasks relayed to the client on its own transport (Roadmap L17a), with security per event: signing, replay protection, residency on partial results (L17b) | 5 | pending |
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

## 8. After wave 5

**Wave 6 (decided by the owner, 2026-10-07): protocol uniformity between servers, and its
security.** Roadmap [L17](Roadmap.md): server to server speaks the same streaming MCP as client to
server, so progress, partial results and cancellation reach the client as the remote work builds,
over whatever transport the client chose (L17a); and the security that goes with it, per event
(L17b). Both are in wave 6. Phases are cut when wave 6 starts; it ships as its own release, 8.2.0.

Other open Roadmap items not placed in a wave, in suggested order. Each keeps its Roadmap entry as
the owner of its detail.

| Item | Why not earlier |
|---|---|
| X13 benchmark suite with published numbers, then X14 SLOs and failure tests | Most useful once LLM tools and SAJHA Net exist to measure; CI (wave 1) is its prerequisite |
| X3 per-user access to prompts and data resources | Independent; can be pulled into any wave if a user needs it |
| X10 Weaviate and Chroma connectors, X11 push-based reload, X12 protocol gaps | Independent, small to medium |
| L1–L7: storage, federation, workflows, API import, tool quality, sandbox, provider tools | Finishing work on existing features |
| L9–L12: container per stdio server, gateway scale, SaaS packs, signed plugins | Larger enhancements; L12 pairs naturally with SAJHA Net's plug-ins |
| L13 one-click deployment templates, L14 console in other languages | Packaging and reach |
| L15 planners chosen by learning from results | Needs traffic and eval history from waves 3–5 |
| X16 TypeScript client | Deferred by decision |

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
| Roadmap Next (X2–X17) | X4, X17: wave 1; X7 (closed), X8, X9: wave 2; X2, X15: wave 3; X5, X6: wave 5; X3, X10–X14, X16: section 8 |
| Roadmap Later (L1–L16) | L16 (SAJHA Net): waves 4–5; all others: section 8 |
| System Notices | wave 1 (service, console, first sources); its later sources with the waves that add them (LLM tools: 2; SAJHA Net: 4) |

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
