# Tutorial 44: Tool Health and Domain Descriptions

A tool is only as good as its contract: the schema a client reads, the description a model reads,
and an upstream that still answers. This tutorial walks through the tool-health features: schema
defaults that the server now applies itself, a tool folder's `domain.txt`, the read-only
annotations that tell SAJHA which tools it may call on its own, the live tool check with its notices
and the Tool Health page, and the generated tables in the Tool Reference Guides. The design is
[Tool Quality §12](../architecture/Tool%20Quality.md#12-tool-health-wave-8-phase-81); domain
descriptions are in [Architecture §5](../architecture/Architecture.md#domain-descriptions).

**What was verified.** Every step below was run as written against a server started from a
checkout on a scratch database (`SAJHA_DB_PATH`) with `SAJHA_STATE_BACKEND=database`, and the
outputs shown are from that run, shortened where marked. Step 6 calls live public services (the
web crawler fetches `docs.python.org`), so your outcomes depend on the network.

## What you'll learn

- How schema defaults fill a call's absent arguments, where that is recorded, and the switch
- What a folder's `domain.txt` adds to every tool's description, and what happens when it is too long
- Which tools the live tool check calls, and why `readOnlyHint` matters
- How to run the check, read its notices and the Tool Health page, and exclude a tool
- How the Tool Reference Guide tables are regenerated and checked

## Prerequisites

- SAJHA running from a checkout ([Quick Start](../getting-started/Quick%20Start.md)) and an
  administrator credential. The examples use the development key from `config/apikeys.json`
  (`X-API-Key: sja_test_admin_dev_key_0001`) and a server on port 3044:

```bash
SAJHA_DB_PATH=/tmp/t44.db SAJHA_STATE_BACKEND=database \
  .venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3044
K='X-API-Key: sja_test_admin_dev_key_0001'
```

`SAJHA_STATE_BACKEND=database` matters for steps 6 and 7: the live check runs in its own process
from the command line, and its results and notices reach the server through the state store. With
the default `memory` backend they stay in the command's process.

## 1. Schema defaults fill absent arguments

`calc_compound_interest` declares `compounds_per_year` with `"default": 12` in its `inputSchema`.
Call it without that argument:

```bash
curl -s -H "$K" -H 'Content-Type: application/json' http://127.0.0.1:3044/api/tools/execute \
  -d '{"tool":"calc_compound_interest","arguments":{"principal":10000,"rate":5,"years":10}}'
```

```json
{"success":true,"result":{"principal":10000,"rate":5,"years":10,"future_value":16470.09,"total_interest":6470.09}}
```

The server filled `compounds_per_year` from the schema before validation and the call. The audit
record says so:

```bash
curl -s -H "$K" "http://127.0.0.1:3044/api/audit/records?event=tool.call&limit=1"
```

```text
"details": {"arguments_sha256": "...", "defaults_applied": ["compounds_per_year"], "duration_ms": 2.083, "source": "rest", ...}
```

The rules are short: only absent keys (a key sent as `null` stays `null`), never a `required`
property, nested objects only when the caller sent them, and nothing through `oneOf`/`anyOf`.
Every transport gets the same filled arguments, because the helper runs in
`BaseMCPTool.execute_with_tracking`. Proxied and SAJHA Net tools are left alone: the server that
owns the tool applies its own contract.

**The switch.** If a tool you depend on behaved differently under its old code default, turn the
helper off for this release only:

```bash
SAJHA_TOOLS_APPLY_SCHEMA_DEFAULTS=false .venv/bin/python run_sajha_web.py ...
```

(`tools.apply_schema_defaults` in `config/application.yml`; it is removed in the release after
8.8.0). The CHANGELOG lists every tool whose effective default changed.

**Lint.** A `required` property with a `default` is a contradiction (`required-default`, warning);
a default that cannot be applied, inside `anyOf` for example, is a note (`unapplied-default`):

```bash
.venv/bin/python -m sajha.quality lint --tool 'wb_*'
```

```text
10 tools checked: 0 errors, 0 warnings, 0 notes (0 tools with errors)
```

## 2. Read a domain description

Everything the tools of one folder share (the source, the key and its environment variable, units,
how to cite) is said once, in `config/tools/<folder>/domain.txt`. SAJHA serves it after each tool's
own description, separated by a blank line:

```bash
cat config/tools/fred/domain.txt
curl -s -H "$K" http://127.0.0.1:3044/api/tools/fred_gdp/schema | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['description'])"
```

```text
The US Gross Domestic Product from FRED, the St. Louis Fed's economic database: series GDP (...).
Returns {"series": "GDP", "data": <FRED observations response>}; ...
Inputs (* required): limit (integer, number of newest observations; default 30).
Related: fred_gdp_growth (growth rate), fred_real_gdp_per_capita.
Example: {"limit": 12}

FRED (Federal Reserve Economic Data), the St. Louis Fed's database at api.stlouisfed.org. Every tool
here needs a free API key: env FRED_API_KEY (config fred.api.key); without one a call fails with a
message saying how to set it, never with invented values. For a series no named tool covers, use
fred_custom_series.
```

The tool's JSON holds only the first part; the editors and the configuration page never write the
domain text into it. The same served text reaches `tools/list` in both protocol eras, Ask SAJHA and
its tool search, and SAJHA Net catalogs.

## 3. Write a domain description

Add one to a folder that has none. The registry's file monitor picks it up without a restart:

```bash
printf '%s\n' "World Bank Open Data (api.worldbank.org/v2); no API key. Countries are ISO codes (US, GBR) or World Bank aggregates (WLD, EUU); indicators are World Bank codes such as NY.GDP.MKTP.CD. Cite the World Bank." \
  > config/tools/worldbank/domain.txt
curl -s -H "$K" http://127.0.0.1:3044/api/tools/wb_get_regions/schema | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['description'][-60:])"
```

```text
orld Bank codes such as NY.GDP.MKTP.CD. Cite the World Bank.
```

(In this run the change was served within eight seconds.) Now make the file too long. The limit is
`tools.domain_description_max_chars` (600 characters after trimming):

```bash
python3 -c "print('x'*700)" > config/tools/worldbank/domain.txt
curl -s -H "$K" http://127.0.0.1:3044/api/notices
```

```text
tools.domain_description:worldbank  warning  The domain description of tool folder worldbank is refused
```

A long file is refused, never cut, because a cut sentence can change its meaning; the folder's
tools are served without it until the file is fixed. Remove the file and the notice clears:

```bash
rm config/tools/worldbank/domain.txt
```

**Write it well.** Keep to what every tool in the folder shares and is true for all of them. Then
remove those sentences from the tools' own descriptions. SAJHA Net accepts descriptions of at most
1024 characters (`sajhanet.limits.max_description_chars`); when a tool's own description plus the
domain text is longer, catalogs get the tool's own words only, and lint warns
(`description-length`). Every shipped tool fits.

## 4. Mark the tools that only read

The live check (next step) calls a tool on its own only when the tool's config says the call
cannot change anything:

```json
"annotations": {"readOnlyHint": true, "idempotentHint": true, "openWorldHint": true}
```

`openWorldHint` is true when the tool calls an outside service, false when it computes locally
(the calculators, the read-only DuckDB and SQL tools). Every shipped data tool that only reads
carries these. Tools that write, send, delete, or act on a user's connected account do not, and
neither do the SharePoint tools (they can check files out, copy and delete) or
`duckdb_refresh_views`; the check never calls them.

## 5. Give the check its arguments

The check never reads prose. It takes, in order: the tool's probe case, else its first passing test
case, else the first entry of `inputSchema.examples`, else the `examples` or `default` of each
required property:

```bash
python3 -c "import json; print(json.load(open('config/tools/calc/calc_wacc.json'))['inputSchema']['examples'])"
```

```text
[{'equity_value': 800, 'debt_value': 200, 'cost_of_equity': 10, 'cost_of_debt': 5, 'tax_rate': 25}]
```

Keep it the same as the description's `Example:` line. A tool with nothing derivable is
`not_checked`, and lint reports it (`missing-example`).

## 6. Run the live check

Check one folder (one provider) and save the run:

```bash
SAJHA_DB_PATH=/tmp/t44.db SAJHA_STATE_BACKEND=database \
  .venv/bin/python -m sajha.quality check --folder webcrawler --save
```

```text
ok              webcrawler             check_robots_txt
ok              webcrawler             crawl_sitemap
...
7 tools: 7 ok, 0 empty, 0 error, 0 schema_mismatch, 0 not_configured, 0 not_checked, 0 skipped
saved run d8cb5d55-de7e-4c5c-8e49-5631c660fcf7
```

Calls to one folder are one at a time, `quality.check.pause_ms` apart; `--json FILE` and
`--junit FILE` write reports, and the command exits 1 when a tool is broken (`error` or
`schema_mismatch`). A tool whose key is not configured is `not_configured`, without a call.

Now a folder that fails here. The document tools read `data/msdocs`, which is empty in a fresh
checkout:

```bash
SAJHA_DB_PATH=/tmp/t44.db SAJHA_STATE_BACKEND=database \
  .venv/bin/python -m sajha.quality check --folder msdoc
```

```text
error           msdoc                  msdoc_search_word                            ValueError: File not found: report.docx
10 tools: 0 ok, 1 empty, 9 error, 0 schema_mismatch, 0 not_configured, 0 not_checked, 0 skipped
```

## 7. Read the notices and the Tool Health page

One warning notice per folder with broken tools, for administrators:

```bash
curl -s -H "$K" http://127.0.0.1:3044/api/notices
```

```text
quality.check:msdoc  warning  Live tool check: 9 broken tools in msdoc
  msdoc_extract_text: error (ValueError: File not found: report.docx); ...   link: /admin/tool-health
```

The **Tool Health** page (`/admin/tool-health`) shows the latest outcome per tool in its Live tool
check section, problems first; `GET /api/quality/check` returns the same, and
`python -m sajha.quality runs --kind check` lists saved runs:

```text
d8cb5d55-de7e-4c5c-8e49-5631c660fcf7  2026-10-11 13:21  check  done     broken 0/7      cli webcrawler
```

A folder's notice clears when a later run of that folder finds nothing broken. Here the failures
are this machine's (no documents), not the tools', so exclude them instead:

```bash
SAJHA_QUALITY_CHECK_EXCLUDE='msdoc_*' SAJHA_DB_PATH=/tmp/t44.db SAJHA_STATE_BACKEND=database \
  .venv/bin/python -m sajha.quality check --folder msdoc --all
```

```text
skipped         msdoc                  msdoc_search_word                            excluded by quality.check.exclude
10 tools: 0 ok, 0 empty, 0 error, 0 schema_mismatch, 0 not_configured, 0 not_checked, 10 skipped
```

The `quality.check:msdoc` notice is gone. In `config/application.yml` the same setting is
`quality.check.exclude`; `quality.check.cron` runs the whole check on the probe scheduler inside the
server, where no shared state store is needed.

## 8. Regenerate the guide tables

The tool table in each Tool Reference Guide is generated from the configs, between
`<!-- generated:tools folder=... -->` markers; the prose around it is hand-written. After changing
a config (the steps above changed the web crawler's examples and output schemas while this
tutorial was written), check and regenerate:

```bash
.venv/bin/python -m sajha.tools guides --folder webcrawler --check
```

```text
stale       docs/tools/search/Web Crawler Tool Reference Guide.md [webcrawler]
1 region(s) stale or broken: run python -m sajha.tools guides
```

```bash
.venv/bin/python -m sajha.tools guides --folder webcrawler
```

```text
written     docs/tools/search/Web Crawler Tool Reference Guide.md [webcrawler]
```

The table lists each tool's first sentence, its required and optional parameters with their schema
defaults, and its annotations. `tests/test_tool_guides.py` runs `--check`, so a config change fails
the suite until the guide is regenerated.

## Summary

- Schema defaults fill absent, non-required arguments on every call path; the audit record names
  them; `tools.apply_schema_defaults` turns this off for one release
- `domain.txt` says once what a folder's tools share; at most 600 characters, refused (with a
  notice) rather than cut; own description plus domain text within 1024 characters for SAJHA Net
- The live check calls only `readOnlyHint: true` tools, with arguments from tests or schema
  examples; one notice per broken folder; results on the Tool Health page
- `python -m sajha.tools guides [--check]` keeps the guide tables in step with the configs

## Next

- The design and every setting: [Tool Quality](../architecture/Tool%20Quality.md)
- Test cases, probes and evals: [Tutorial 23: Test and Canary Your Tools](TUTORIAL_23_test_and_canary_your_tools.md)
- Next: [Tutorial 45: Quantitative Planners](TUTORIAL_45_quantitative_planners.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
