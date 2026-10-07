# Deck generator

Regenerates SAJHA's deck from source, so it is reproducible rather than a binary nobody
can edit safely, and so every number on it is read from the code when it is built.

```bash
pip install -r requirements-dev.txt                       # python-pptx, once
python tools/deck/build.py                                # the deck, into docs/publications/
python tools/deck/audit.py docs/publications/SAJHA-One-Governed-Catalog-of-Tools.pptx
python -m pytest -q tests/test_deck_geometry.py           # the audit, as a test
python tools/deck/evidence.py                             # print every derived fact
```

## One deck

| Deck | Slides | Source |
|---|---|---|
| `docs/publications/SAJHA-One-Governed-Catalog-of-Tools.pptx` | 55 | `sajha_deck.py`, then `deck_part1.py` to `deck_part4.py` |

**What it does, in order.** It is written for the people who must trust SAJHA with their
tools and their data, and answers their questions in the order they ask them, in nine
parts. (1) Why agents stall at the tools layer: every team wires its own tools, nobody
can say who called what, and SAJHA (साझा, "shared") in one slide. (2) The vocabulary from
nothing: tool, schema, tool group, catalog; MCP, client, server, transport, era;
composition, confidence, policy, audit chain, Ask SAJHA; and the one path every call
takes. (3) One question end to end, captured from a real Ask SAJHA run on the offline
mock model over the whole catalog: shortlist, call, answer with its citation and
confidence, and what the run does not show. (4) Speaking every client's language: two
eras on one endpoint, four transports, the conformance results, and what the 2026-07-28
era adds. (5) Governance an enterprise can sign off: identities and one access policy,
OAuth 2.1, a policy rule and the shipped example policy evaluated on four calls, an
audit chain tampered with and caught, the sandbox and connected accounts, and the
security fixes table. (6) Every tool you have: the catalog, the ways to add tools,
describe-a-tool, API import and data connectors, federation, composition (a confidence
chain computed), workflows. (7) The intelligence layer: providers behind one gateway,
planners, memory and document search, evals. (8) How it runs: storage, state, database,
Kubernetes, observability, schema and tool quality. (9) How it compares, from
`sajha/web/competitive.py`, including where others are stronger; what SAJHA does not do;
where to start.

**What it deliberately is not.** It has no implementation-status or project-progress
slide and no roadmap. Where an idea needs proof it shows a run, not a claim. Slide titles
are claims ("Change one stored field and the audit says which record and which field"),
not topics ("Audit"). No word is used before the slide that defines it.

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
| Providers, planners, sandbox, state, storage, schema, connector kinds, account templates, workflow kinds, SIEM sinks, Helm templates, Studio creators | the registries and constants that define them |
| The comparison | `sajha/web/competitive.py` (the data behind `/comparison`) |

If a source moves or changes shape, `evidence.py` raises `SourceChanged` naming it; the
fix is to the reader, never a number typed into a slide. A captured run's latency and
the test count change between builds; that is the point.

## How it is put together

| File | Purpose |
|---|---|
| `metrics.py` | The text estimator: greedy word-wrap simulation and paragraph heights. Shared by the builder and the audit, so the builder never believes a box fits that the audit then reports |
| `theme.py` | The SAJHA Crimson design system, its colours read from the first `:root` block of `sajha/web/static/css/tokens.css`: chrome, tables, cards, stat bars, monospaced panels, speaker notes, and `fitted()`, which shrinks a text block until it fits or raises `DoesNotFit` |
| `layouts.py` | Slide kinds drawn from plain dictionaries: `title`, `divider`, `bullets`, `table`, `cards`, `stats`, `split` (either column may be `lines`, a captured run), `flow`, `context` |
| `evidence.py` | Every number and every worked example, derived at build time |
| `prose.py` | Small text helpers (lists in prose, wrapped panel lines) |
| `sajha_deck.py`, `deck_part1.py` … `deck_part4.py` | The deck, as data: the title slide in `sajha_deck.py`, the nine parts in order in the four part modules (1–2, 3–4, 5–6, 7–9). They are one deck and are meant to be read in order |
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
`tests/test_deck_geometry.py` runs it on the deck, asserts the slide and part counts
above, checks that every content slide's notes name a source, that the palette comes from
`tokens.css`, and that the document properties name the author and no tool. It is
skipped where `python-pptx` is not installed.

`python-pptx` does not measure text, and PowerPoint does not clip overflow. The estimator
is deliberately pessimistic (a 6% width margin), so rendered text sits inside its boxes;
it is an estimate, and a deck should still be looked at after a large change:

```bash
soffice --headless --convert-to pdf --outdir /tmp docs/publications/SAJHA-One-Governed-Catalog-of-Tools.pptx
pdftoppm -r 60 -png /tmp/SAJHA-One-Governed-Catalog-of-Tools.pdf /tmp/slide
```

The mechanism mirrors the MAYA deck's (`tools/deck/` in the MAYA repository); the two
products share one palette, so the decks share one look.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
