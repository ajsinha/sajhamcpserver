# SAJHA MCP Server — working notes for Claude

SAJHA is a dual-era MCP server (stateless 2026-07-28 and session-based 2025-11-25 on
one `/mcp` endpoint) built on FastAPI. The version is `app.version` in
`config/application.yml`; that value is the only authority. Every other version
string in the repository is a copy that can rot.

This file is mostly about documentation, because that is where this repository has
drifted most: three glossaries that disagreed, a changelog with the same release
pasted four times, and docs that kept claiming "MCP 2025-11-25 (latest)", a tool count
and a screen count long after all three changed.

---

## Documentation rules

### 1. Derive, never restate

If the code knows it, the docs do not copy it. No hand-written tool counts, screen
counts, endpoint counts, test counts, method lists or version numbers. Say where the
live answer is instead: "the live catalog (`tools/list`, or the Tools page)", "every
route is in `sajha/routes/`", "`app.version`". A number in a doc is a promise to update
it forever; nobody keeps that promise.

- No per-file version headers ("Version 5.3.0", "Last updated ...") on any document.
- Conformance results are the exception: they are evidence of a specific run, stated
  with the suite version, and they live only in the two compliance reports (and the
  CHANGELOG entry that shipped them).

### 2. One owner per topic

Every topic has exactly one owning document; everything else links to it. The map of
owners is [`docs/getting-started/How SAJHA Fits Together.md`](docs/getting-started/How%20SAJHA%20Fits%20Together.md).
Before writing about a topic, find its owner and edit that. If two documents explain
the same thing, merge them and leave a link.

| Topic | Owner |
|---|---|
| Protocol behaviour (eras, transports, streaming, MRTR, tasks) | `docs/protocol/MCP Protocol Guide.md` |
| Protocol evidence (requirements, conformance results, limits) | `docs/protocol/MCP 2026-07-28 Compliance.md`, `docs/protocol/MCP 2025-11-25 Compliance.md` |
| OAuth on `/mcp` | `docs/protocol/OAuth Guide.md` |
| MCP Apps, `x-mcp-header` | `docs/protocol/MCP Apps and Headers Guide.md` |
| HTTP endpoints | `docs/protocol/API Reference.md` |
| Configuration keys | `docs/getting-started/Configuration Reference.md` |
| Storage backends | `docs/getting-started/Storage Guide.md` |
| Security | `docs/security/Security Model.md` |
| Internal structure | `docs/architecture/Architecture.md` |
| Composition theory | `docs/architecture/Composition Framework.md` |
| Definitions | `GLOSSARY.md` |
| Release history | `CHANGELOG.md` |

### 3. Where things go

```
README.md            first contact: what, why, quick start, links. Short.
CHANGELOG.md         newest first; one section per version; "## Unreleased" on top
GLOSSARY.md          the only glossary
CLAUDE.md            this file
docs/README.md       the index and reading order
docs/getting-started/  map, quick start, configuration, storage
docs/protocol/       MCP guide, compliance reports, API, OAuth, Apps/headers
docs/architecture/   architecture, composition framework
docs/studio/         MCP Studio guide + one guide per creator
docs/tools/<category>/  one "<Provider> Tool Reference Guide.md" per provider; prompts/
docs/tutorials/      TUTORIAL_NN_<slug>.md, numbered in reading order
docs/clients/        Client SDK Guide
docs/security/       Security Model
docs/archive/        point-in-time reports, not maintained
docs/requirements/   original requirements (binary, unchanged)
deployment/          deployment recipes (each with its README)
clientsdk/README.md  short pointer + install + quick start; the guide is in docs/clients/
```

- **Guide file names are unique across `docs/`** (excluding `README.md` files). The
  in-app help addresses a guide by file name alone, so a guide can move between
  folders without breaking links into it. Check before adding one:
  `find docs -name '*.md' ! -name README.md -printf '%f\n' | sort | uniq -d` must print
  nothing.
- File names use spaces and title case (`Storage Guide.md`), except tutorials
  (`TUTORIAL_NN_slug.md`). In markdown links, encode spaces as `%20`.
- Relative links must resolve from the file's own folder. After moving a file, grep
  for its old name.
- Move files with `git mv` so history follows them.

### 4. The glossary is the single source of definitions

`GLOSSARY.md` holds every definition. Format (a loader parses it, so keep it exact):

```
## N. Section title
| Term | Meaning |
|---|---|
| **Term** | One-line meaning, no pipe characters. |
| **Abbrev** (*Expansion*) | ... |
```

Sections are `## N. Title`; each term is one row starting `| **`. Templates must not
carry their own definitions (the old per-page `page_glossary` blocks are being replaced
by entries rendered from this file). Add a term here first, then link to it.

### 5. The in-app help follows the docs, not the other way round

Help pages under `sajha/web/templates/help/` are a quick tour that links to the owning
guide for the full reference. They must not hold facts the guides lack. When the help
catalog (in-app guide browser) serves markdown, it finds guides by unique file name
and groups them by their folder under `docs/`; adding a folder means adding it to the
catalog's folder map.

### 6. Archive, don't delete, point-in-time documents

Audits, assessments, handover notes and roadmaps that have been overtaken go to
`docs/archive/` with a one-line "Archived; not maintained" note and an entry in
`docs/archive/README.md` naming what supersedes them. Live docs never cite the archive
for facts.

### 7. Verify before you write

Every factual claim (route, config key, default, file path, method name, tool name,
parameter) is checked against the code before it goes into a doc. When the docs and
the code disagree, read the code, but do not assume the doc is the wrong one: report
the disagreement.

---

## Code facts that are cheap to get wrong

- Configuration: `sajha/core/config.py::_get` resolves `SAJHA_<DOTTED_KEY>` env →
  YAML (with `${ENV:default}`) → code default, but not every subsystem reads through
  `_get` (storage and `${...}` in tool configs use `PropertiesConfigurator`; `ai.*`
  reads the raw YAML). The Configuration Reference records which keys behave how.
- Secrets never go in `config/application.yml`; it is tracked. Use environment
  variables. The OAuth signing key lives in `data/oauth/` (git-ignored).
- Protocol state (MCP sessions, MCP tasks, listen streams, OAuth codes and refresh
  tokens) is per process.

## Git

- Commit or push only when asked. Never rewrite published history.
- When other agents may be working, stage explicit paths, never `git add -A`.
