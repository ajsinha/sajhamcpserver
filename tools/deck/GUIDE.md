# Deck generator

Regenerates SAJHA's deck from source, so it is reproducible rather than a binary nobody
can edit safely, and so every number on it is read from the code when it is built.

```bash
pip install -r requirements-dev.txt                       # python-pptx, once
python tools/deck/build.py                                # the deck, into docs/publications/
python tools/deck/audit.py docs/publications/SAJHA-MCP-Server.pptx
python -m pytest -q tests/test_deck_geometry.py           # the audit, as a test
python tools/deck/evidence.py                             # print every derived fact
```

## One deck

| Deck | Slides | Source |
|---|---|---|
| `docs/publications/SAJHA-MCP-Server.pptx` | 104 | `sajha_deck.py`, then `deck_part1.py`, `deck_part2.py`, `deck_part3.py`, `deck_net.py`, `deck_part4.py` |

**What it does, in order.** It teaches before it sells: someone who has never heard of MCP
can start at slide 1, and someone choosing a server ends with the evidence. After the title
slide (with the full proprietary notice) and a TL;DR (five questions, five answers) come eight
numbered sections. (1) The Model Context Protocol: what it is (N × M integrations against
N + M, drawn), ten principles, industry voices (each quotation traced to its source), the
primitives, host, client and server, the five steps of a tool call as a sequence across host,
client and server, and the benefits. (2) MCP integration with AI applications: an indicative
architecture, how an application connects in either era (drawn side by side), the
transports, the two eras, the conformance results, the four interaction patterns drawn with
real tools, streaming, tasks and views, and MCP in an LLM pipeline. (3) The SAJHA MCP server:
overview, what makes it different, the tools in the box, MCP Studio's creators, Describe a
tool, API import and data connectors (two lanes), federation (a pipeline from upstream to
catalog), the server's layers, the web console, the parallel SDLC, role-based access,
security layers, authentication (four callers, one access policy), OAuth 2.1 (client,
authorization server, resource server), credentials, sign-in and the browser, five
step-by-step flows in monospace, a policy rule and the example policy evaluated, the audit
chain tampered with (the captured run beside the chain drawn), the security fixes, deploy
anywhere, cloud and on-premises reference architectures, and production readiness in counted
facts. (4) Agents, composition and workflows: agent architecture, an illustrative analysis,
several agents, a composite tool (sibling and parent-child lanes inside one governed call),
the Composition Framework (sequential against parallel confidence, computed at build time),
a workflow (the Workflows guide's own example DAG, parsed and ordered by the engine, with its
triggers and every step kind), a run's states, how tool, composite, workflow and published
tool fit and reach local, proxied and SAJHA Net tools, extending the server, hot reload, and
making a tool step by step. (5) SAJHA Net and proxied MCP servers: why a net, membership on a
ring, admission (open shipped, the code's default, manual), one name one contract against
vendors, what happens on a call at home and at the host, routing and the waterfall fallback,
identity across servers and the test admin key, proxied MCP servers internal and external,
residency and redaction, planners and LLM tools across the net with the call-chain budget,
re-export and bridges, the three ways to take part with the conformance runner, and blocks
and the console. (6) Data and analytics: search tools, DuckDB and OLAP, the calculators, the
connector guard, search combined with analytics. (7) Intelligence and operations: the
intelligence layer as a stack (consumers, the public interface, the governed model, the
providers), LLM tools and the OpenAI-compatible endpoint, one Ask SAJHA question captured end
to end, planners, memory and RAG (drawn as a pipeline), evals, tool quality, observability,
sandbox and connected accounts, storage and state, clients, configuration (the resolution
chains drawn), the schema. (8) Where it's going (the Roadmap's open items and the known
limitations, both parsed), the comparison from `sajha/web/competitive.py`, where others are
stronger, where to start; then thanks, with the notice again.

**Diagrams, not paragraphs.** A slide that explains a flow, a structure or a comparison draws
it with native, editable shapes in the theme's colours (the `canvas` layout: boxes, connectors
with arrowheads and labels, groups, legends), and keeps only a few words on the slide; what
was said in prose is in the slide's speaker notes, after the source ("Speaker notes: ...").

**Proprietary.** SAJHA is proprietary, owned by Ashutosh Sinha; it is not open source. Every
slide's footer reads "© 2025-2030 Ashutosh Sinha. All rights reserved. Proprietary."
(`theme.FOOTER_TEXT`); the title slide carries the full notice (`theme.NOTICE`: no licence is
granted, with the address for enquiries from `app.email`), and so does the closing slide. The
test checks the footer on every slide, the notice on the title, and that no slide or note
calls SAJHA open source.

**What it deliberately is not.** It has no "Built:" status slides: built things are on the
capability slides, and only what is not built is under "Where it's going". It claims no
performance it has not measured. Slide titles keep a short heading's shape but say
something ("Four transports in SAJHA; two of them are the MCP standard"). Worked workflows
that were not run are marked *Illustrative*; the real runs are captured at build time.

**Where it came from.** The arc and the slide vocabulary (TL;DR rows, numbered section
dividers, the ten principles, quotations, step-by-step monospace flows, reference
architectures) follow an earlier deck by the same author, rebuilt in SAJHA Crimson with
every number derived and every outside claim cited. What could not be verified was left
out; `tests/test_deck_geometry.py` keeps the earlier deck's organisation out of every
slide, note and property.

## Outside sources

Statements about MCP itself and the quotations are not in the code, so they cite public
pages, with the date they were read, in the slide notes (`deck_part1.py` keeps the URLs in
one place): Anthropic's introduction of MCP and its December 2025 announcement of the
Agentic AI Foundation, the BCG article, the TechCrunch reports of Sam Altman's and Demis
Hassabis's statements, and the SDK list at modelcontextprotocol.io. A quotation found only
in secondary write-ups is not used.

## Every number is derived

`evidence.py` reads each figure from its owner while the deck is built, and runs the
worked examples against the code as it stands. Nothing is written to the repository: the
examples use the shipped configs read-only, a temporary SQLite file and a throwaway key.

| Fact | Where it comes from |
|---|---|
| Tool and group counts, the groups table | `ToolsRegistry` loaded from `config/tools`, counted by `live_tool_groups` |
| Protocol versions | `MODERN_PROTOCOL_VERSIONS`, `HANDSHAKE_PROTOCOL_VERSIONS` (`sajha/core/mcp_modern.py`) |
| CI matrix and branches | `.github/workflows/mcp-conformance.yml` |
| Conformance results | the table in §5 of `docs/protocol/MCP 2026-07-28 Compliance.md` (and the 2025-11-25 report's result line) |
| Test count | `pytest --collect-only` over `tests` and `clientsdk/tests` |
| The Ask SAJHA run | `IntelligenceService.stream_ask` on `mock/mock-planner` over the full registry |
| Eval results | `sajha.quality.evals.run_set` over `config/evals/calculators.yaml`, planners `react` and `plan_execute` |
| Confidence values and discounts | `get_tool_confidence`, `IntelligenceService._confidence`, `UNVERIFIED_CONFIDENCE` |
| Policy decisions | `PolicyEngine.evaluate` over `config/policies` (disabled examples included); nothing is run |
| Audit tamper detection | `ChainWriter` and `verify` on a temporary database, before and after one `UPDATE` |
| Security fixes and known limitations | the two sections of `docs/security/Security Model.md` |
| Providers, planners, sandbox, state, storage, schema dialects, connector kinds, account templates, workflow kinds, SIEM sinks, Helm templates | the registries and constants that define them |
| The comparison | `sajha/web/competitive.py` (the data behind `/comparison`) |
| Studio creators | the pages in `sajha/routes/studio_routes.py`, plus Describe a tool and Import an API |
| Schema tables | `CREATE TABLE` in both `db/scripts/*/schema.sql` (the two must define the same set) |
| Seeded roles and permissions | `db/scripts/sqlite/seed.sql` |
| CLI commands | `clientsdk/sajhaclient/cli/main.py` |
| Console pages | `sajha.web.page_help.PAGE_HELP` |
| Search, analytics and calculator tools | names and descriptions from the registry (`describe_tools`) |
| Tool names in examples | `require_tools`: a name not in the registry fails the build |
| Workflow step kinds, trigger types, joins, run states and the example DAG | `sajha/workflows/model.py` STEP_KINDS, TRIGGER_TYPES, JOINS; `store.py` RUN_ACTIVE, RUN_DONE; the definition in §2 of `docs/architecture/Workflows.md`, parsed by `model.normalize` and ordered by `model.topo_order` |
| Sequential and parallel confidence | `EntropyGuard` over `get_tool_confidence` for four registry tools (`composition_compare`) |
| SAJHA Net plug-ins, admission modes, shipped switches and limits | `sajha/net/plugins.py` registry (after importing the integration's resolvers), `Shared.admission`, and the shipped `config/application.yml` (`sajhanet.*`, `federation.enabled`, `auth.credential_storage`, `ai.openai_api.enabled`) |
| The name separator | `sajha/tools/naming.py` SEPARATOR |
| What is not built | the open items of `docs/architecture/Roadmap.md` (sections 2 to 4) |
| RAG stores, LLM tool modes | `sajha.ai.rag.registry.registered_stores()`, `sajha/ai/llm_tools/config.py` MODES |

If a source moves or changes shape, `evidence.py` raises `SourceChanged` naming it; the
fix is to the reader, never a number typed into a slide. A captured run's latency and
the test count change between builds; that is the point.

## How it is put together

| File | Purpose |
|---|---|
| `metrics.py` | The text estimator: greedy word-wrap simulation and paragraph heights. Shared by the builder and the audit, so the builder never believes a box fits that the audit then reports |
| `theme.py` | The SAJHA Crimson design system, its colours read from the first `:root` block of `sajha/web/static/css/tokens.css`, and SAJHA's mark, drawn from the `icon-sajha` symbol in `sajha/web/static/icons/sajha-icons.svg`: chrome (the footer carries the proprietary notice and the slide number; `NOTICE` is the full notice), section dividers, tables, cards, boxed diagram text, arrows, stat bars, monospaced panels (never wrapped), speaker notes, and `fitted()`, which shrinks a text block until it fits or raises `DoesNotFit` |
| `layouts.py` | Slide kinds drawn from plain dictionaries: `title`, `divider`, `tldr`, `principles`, `quotes`, `steps`, `bullets`, `table`, `cards`, `stats`, `split` (either column may be `lines`, a captured run), `flow`, `context`, `diagram` (groups, boxes, arrows), `canvas` (free diagrams of native shapes: groups, nodes in several shapes and styles, connectors that leave a shape's edge, optionally through waypoints, with labels and arrowheads, free labels, monospaced panels, lists and a legend; drawn last, edges never run under a filled shape), `mono` (a step-by-step exchange) and `thanks`. A slide's `talk` becomes its speaker notes after the source |
| `diagrams.py` | Geometry for canvas slides: a layered left-to-right layout of a DAG, points on a ring, evenly spaced rows |
| `evidence.py` | Every number and every worked example, derived at build time |
| `prose.py` | Small text helpers (lists in prose, wrapped panel lines) |
| `sajha_deck.py`, `deck_part1.py` … `deck_part4.py`, `deck_net.py` | The deck, as data: the title slide and TL;DR in `sajha_deck.py`, then the eight sections: 1–2 in `deck_part1.py`, 3 in `deck_part2.py`, 4 and 6 in `deck_part3.py`, 5 (SAJHA Net) in `deck_net.py`, 7–8 in `deck_part4.py`. `sajha_deck.SECTIONS` lists the sections in order; the dividers are numbered from it, so moving a section is one line |
| `build.py` | Builds the deck and sets the document properties (author, title, subject) explicitly |
| `audit.py` | The geometry audit (below) |

A slide that cannot be made to fit **fails the build** naming the slide; the fix is to
shorten the text or split the slide, never to lower the floor. A content slide without a
`source` also fails the build: the source becomes the slide's speaker notes and names
where each number and claim on it comes from.

## The audit

`audit.py` re-derives the geometry of every shape on every slide and reports: a shape off
the slide; a table taller than its frame (PowerPoint treats a row height as a minimum);
an opaque shape drawn over earlier content; anything printed over a table; text escaping
a filled or outlined container, or the card its textbox sits in; content crossing the
footer rule; and a free textbox whose overflow lands on another shape.
`tests/test_deck_geometry.py` runs it on the deck, asserts the slide and section counts
above (a divider is the slide with the `Section numeral` shape), checks that every content
slide's notes name a source, that the palette comes from `tokens.css`, that the document
properties name the author and no tool, and that no slide, note or property names the earlier deck's
organisation or product (the banned words are in the test), and that every slide carries the
proprietary footer, the title slide the full notice, and no slide or note calls SAJHA open
source. It is skipped where `python-pptx` is not installed.

`python-pptx` does not measure text, and PowerPoint does not clip overflow. The estimator
is deliberately pessimistic (a 6% width margin), so rendered text sits inside its boxes;
it is an estimate, and a deck must still be looked at after a change: render every slide and
look at each one for overlaps, text too small to read, connectors that miss their shapes and
poor contrast (a contact sheet of twelve slides at a time is a quick first pass):

```bash
soffice --headless --convert-to pdf --outdir /tmp/deck docs/publications/SAJHA-MCP-Server.pptx
pdftoppm -r 80 -png /tmp/deck/SAJHA-MCP-Server.pdf /tmp/deck/s
montage /tmp/deck/s-00[1-9].png /tmp/deck/s-01[0-2].png -tile 3x4 -geometry 640x360+4+4 /tmp/deck/sheet.png
```

The mechanism mirrors the MAYA deck's (`tools/deck/` in the MAYA repository); the two
products share one palette, so the decks share one look.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
