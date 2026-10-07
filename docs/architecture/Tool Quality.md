# SAJHA MCP Server — Tool Quality

How SAJHA keeps its tools trustworthy as they change: a **test harness** with recorded HTTP
fixtures, a **schema linter**, opt-in **health probes**, **evals** for Ask SAJHA, and **tool
versions** with canary routing, automatic rollback and deprecation. All of it lives in
`sajha/quality/`.

This document owns the topic: the design, how to operate it and its limits. Every key and
default is in the [Configuration Reference](../getting-started/Configuration%20Reference.md#quality);
the walkthrough is [Tutorial 23](../tutorials/TUTORIAL_23_test_and_canary_your_tools.md);
terms are in the [Glossary](../../GLOSSARY.md).

**Nothing changes by default.** Probes are off (`quality.probes.enabled: false`), no tool has
a versions file, so routing is a dictionary miss per call and no result gains `_meta`. The
harness, the linter and evals run only when someone runs them.

---

## 1. Shape

```
 config/tool_tests/*.yaml  ──►  cases ──►  runner ──► assertions ──► results ──► text · JSON · JUnit XML
 (or "tests" in a tool config)     │          │                                      └─► quality_runs (optional)
                                   │          └─ cassette (record | replay | live): urllib, requests, httpx
                                   └─ "probe:" ──► probe scheduler (state-store single fire) ──► metrics · Tool Health page

 every tool's config ──► linter (JSON Schema 2020-12, descriptions, examples, MCP names, annotations) ──► report

 config/evals/*.yaml ──► eval runner ──► IntelligenceService.ask (per model × planner) ──► scores ──► quality_runs ──► compare

 config/tool_versions/<tool>.yaml ──► VersionManager ──► BaseMCPTool.execute_with_tracking (the choke point)
        routing: API-key pin > user > role > canary % > stable        ├─► chosen version's execute_with_tracking
        rollback: windowed error rate / slow-call rate (state store)  └─► _meta["io.sajha/tool-version"]
        deprecation: warnings in _meta, hidden from tools/list after sunset
```

| Code | What |
|---|---|
| `sajha/quality/jsonpath.py` | a small JSONPath subset (`$`, `.key`, `['key']`, `[n]`, `[-1]`, `[*]`, `.*`, `..key`) |
| `sajha/quality/assertions.py` | the assertion language (JSON Schema, JSONPath equals/contains/regex/..., numeric tolerance, latency budget) |
| `sajha/quality/cassette.py` | the VCR-style HTTP recorder and player for `urllib.request`, `requests` and `httpx` |
| `sajha/quality/cases.py` | loads test cases and probe definitions |
| `sajha/quality/runner.py` | runs cases, renders text, JSON and JUnit XML |
| `sajha/quality/lint.py` | the schema linter |
| `sajha/quality/probes.py` | the probe scheduler, probe state and probe metrics |
| `sajha/quality/evals.py` | eval sets, the eval runner, scoring and run comparison |
| `sajha/quality/versions.py` | versions files, routing, canary, rollback, deprecation |
| `sajha/quality/store.py` | the `quality_runs` table (test and eval runs) |
| `sajha/quality/__main__.py` | `python -m sajha.quality test | lint | eval | compare | runs` |
| `sajha/routes/quality_routes.py` | the Tool Health, Evals and Tool Versions pages and their API |
| `sajha/core/tool_versioning.py` | the older contract-test runner and lifecycle enum (`/api/contract-test`), kept; its version manager now delegates to `sajha/quality/versions.py` |

---

## 2. The test harness

### 2.1 Test cases

A test file is YAML (or JSON) in `quality.tests_dir` (default `config/tool_tests/`). One file
names one tool; several files may name the same tool.

```yaml
tool: calc_percentage_change
cases:
  - name: increase
    arguments: {old_value: 80, new_value: 100}
    expect:
      - schema: output                     # the tool's outputSchema (or an inline schema object)
      - path: $.percentage_change
        equals: 25
        tolerance: 0.001                   # numeric tolerance (absolute)
      - path: $.old_value
        type: number
      - latency_ms: 500                    # latency budget for the call
  - name: rejects a string
    arguments: {old_value: "x", new_value: 1}
    error: "old_value"                     # the call must fail; the message must match this regex
probe:                                     # optional: run one case on a schedule (section 4)
  case: increase
  every: 300                               # seconds; or cron: "*/5 * * * *" with timezone:
```

A tool config may carry the same list as `"tests": [...]` (and `"probe": {...}`); the harness
reads both. Case fields: `name` (unique within the tool), `arguments`, `expect` (a list of
assertions), `error` (`true`, or a regex the error must match), `version` (run a specific
tool version, section 6), `tags`, `skip` (a reason), `cassette` (a cassette name other than
the case's own).

### 2.2 Assertions

Each `expect` item is one assertion:

| Form | Passes when |
|---|---|
| `schema: output` / `schema: {...}` | the result validates against the tool's `outputSchema` (Draft 2020-12) / that schema |
| `path: <jsonpath>` with `exists: true|false` | the path matches something / nothing |
| `path` + `equals: v` (`tolerance: t` for numbers) | the single match equals `v` (all matches, as a list, when several) |
| `path` + `not_equals: v` | the opposite |
| `path` + `contains: v` | substring of a string, element of a list, sub-object of an object |
| `path` + `regex: r` | every match (as a string) matches `r` |
| `path` + `type: string|number|integer|boolean|object|array|null` | every match has the type |
| `path` + `min: a` / `max: b` | every match is a number within the bounds |
| `path` + `length: n` (or `min_length`, `max_length`) | the match's length |
| `latency_ms: n` | the call took at most `n` ms |

The result asserted on is the tool's return value (a JSON value). A string result that parses
as JSON is parsed first.

### 2.3 Recorded fixtures: cassettes

Most tools call an HTTP API. A cassette records a case's HTTP exchanges once and plays them
back, so a test runs offline, fast and deterministically in CI.

* **Modes:** `--record` runs live and writes the cassette; `--replay` serves every request from
  the cassette and fails on any request it does not hold (no network); the default `auto`
  replays when a cassette exists and runs live otherwise; `--live` ignores cassettes.
* **Clients covered:** `urllib.request.urlopen` (what nearly every built-in tool uses),
  `requests` (`Session.send`) and `httpx` (sync and async transports). A tool that uses
  another client is not intercepted; in `--replay` such a call is not caught.
* **Matching:** method and URL, with secret-looking query parameters (`apikey`, `api_key`,
  `token`, `key`, `access_token`, `client_secret`, `password`, `sig`, `signature`) replaced
  by `REDACTED` before matching and before writing. Repeated identical requests are played in
  order. Request bodies are matched by SHA-256 when present.
* **What is stored:** `quality.cassettes_dir/<tool>/<case>.json`: request method, redacted URL,
  body hash, response status, response headers except `Set-Cookie`, and the body (text, or
  base64 for binary or compressed bodies). Request headers are never stored, so an
  `Authorization` header or API key header never reaches the file. Review a cassette before
  committing it: a response body can still carry data you do not want in git.
* **Errors:** an HTTP error status is recorded and replayed as the same `HTTPError`; a network
  failure is not recorded (the case fails while recording).

### 2.4 The command line

```
python -m sajha.quality test [--tool GLOB] [--case GLOB] [--tag TAG] [--record | --replay | --live]
                             [--junit FILE] [--json FILE] [--save]
python -m sajha.quality lint [--tool GLOB] [--strict] [--junit FILE] [--json FILE]
```

The exit status is 0 when every case passed (and, for `lint`, no error, or no warning with
`--strict`), 1 otherwise, 2 for a usage error. `--junit` writes JUnit XML (one `<testsuite>`
per tool, one `<testcase>` per case, `failure` with the failed assertions, `skipped` for skips)
that CI systems read. `--save` records the run in `quality_runs` so the Tool Health page shows
it. The harness runs a tool with `validate_arguments` then `execute`: it tests the tool, not
the platform around it (policy, cache and circuit breaker are not involved, and no usage row is
written).

---

## 3. The schema linter

`python -m sajha.quality lint` (and the Lint tab of the Tool Health page) checks every tool in
the registry:

| Rule | Level |
|---|---|
| `name` matches MCP's tool-name rule: 1 to 128 of `A-Z a-z 0-9 _ - .` | error |
| a description exists | error; shorter than `quality.lint.min_description` (40) characters: warning |
| `inputSchema` is a valid JSON Schema 2020-12 document of `type: object` | error |
| every `required` name is a property | error |
| every input property has a `description` | warning |
| every `examples` entry and `default` validates against its (sub)schema | error (examples), warning (default) |
| `outputSchema`, when present, is a valid 2020-12 schema of `type: object` | error |
| `annotations` hints are booleans; `readOnlyHint` and `destructiveHint` are not both true | error |
| a tool whose name says it deletes, drops, purges, removes, revokes, truncates or wipes has `destructiveHint: true` | warning |
| a tool whose name says it only reads (`get`, `list`, `search`, `fetch`, `query`, ...) has `readOnlyHint: true` | info |
| every test case's `arguments` validate against the input schema (unless the case expects an error) | error |

The report groups findings by tool, with counts per level; JSON and JUnit outputs are the same
findings. Lint is static: no tool runs.

---

## 4. Health probes

A probe runs one test case of a tool on a schedule, against the live service (never a
cassette), and records the outcome. Probes are opt-in twice: `quality.probes.enabled: true`
turns on the scheduler, and only tools whose test file (or config) has a `probe:` block are
probed.

* **Schedule:** `every: <seconds>` (aligned to the epoch, so every worker computes the same
  slots) or `cron: "<5 fields>"` with optional `timezone:`, parsed by the workflows cron
  parser (`sajha/workflows/cron.py`). The scheduler is a daemon thread in each worker that
  wakes every `quality.probes.tick_seconds`.
* **Single fire:** before running a slot, a worker claims it with `state_store.add`
  (`quality:probe:fire:<tool>:<slot>`); only the worker that wins runs it. With `state.backend:
  memory` each worker is its own store, so each would probe; use `redis` or `database` with
  several workers (as for every shared counter, [Scaling and State](Scaling%20and%20State.md)).
* **State:** the latest result and the last `quality.probes.history` results per tool are kept
  in the state store (`quality:probe:state:<tool>`), so every worker's Tool Health page shows
  the same thing.
* **Metrics:** `sajha_tool_probe_runs_total{tool,outcome}` (outcome `pass | fail | error`),
  `sajha_tool_probe_up{tool}` (1 when the last run passed) and
  `sajha_tool_probe_duration_seconds{tool}`, on `/metrics` beside the rest
  ([Observability](Observability.md)); an alert rule on `sajha_tool_probe_up` turns a failing
  probe into a page.
* **Run now:** the Tool Health page and `POST /api/quality/probes/{tool}/run` run a probe at
  once (admin).

---

## 5. Evals for Ask SAJHA

An eval set is a YAML file in `quality.evals_dir` (default `config/evals/`):

```yaml
name: calculators
description: The offline calculators; runs on the mock provider.
models: [mock/mock-planner]           # default models; the CLI or page may override
planners: [react]                     # default planners
tools: ["calc_*"]                     # optional: only these tools are offered (glob list)
defaults: {max_steps: 4}
questions:
  - id: pct-change
    question: What is the percentage change from 80 to 100?
    expect_tools: [calc_percentage_change]   # every one must be called
    forbid_tools: []                          # none may be called
    answer:
      - contains: "25"
      - regex: "25(\\.0+)?\\s*%"
      - not_contains: "cannot"
      - number: 25
        tolerance: 0.01                       # some number in the answer is within tolerance
    max_steps: 3
    max_tokens: 6000
    max_cost_usd: 0.01
    max_latency_ms: 20000
```

The runner asks every question through `IntelligenceService.ask` once per (model, planner)
pair and scores each answer:

* **tool selection** is correct when every `expect_tools` tool was called and no
  `forbid_tools` tool was; recall and precision against `expect_tools` are kept too;
* **answer checks** are the `answer` list (`contains`, `not_contains`, `regex`, `number` with
  `tolerance`, `equals`), case-insensitive except `regex` flags you give;
* **limits**: steps, total tokens, cost and latency against the question's (or the set's
  default) limits; the ask must stop by `answer` unless `expect_stop` says otherwise.

A question passes when all three hold. A run's summary: tool-selection accuracy, answer
accuracy, pass rate, mean steps, total and mean tokens, total cost, mean and p95 latency, per
(model, planner). Runs are saved in `quality_runs`; **compare** takes two runs and reports the
metric deltas and the questions that regressed or improved.

```
python -m sajha.quality eval [SET ...] [--model M ...] [--planner P ...] [--json FILE] [--junit FILE] [--no-save]
python -m sajha.quality compare RUN_A RUN_B           # run ids, or JSON files written by --json
python -m sajha.quality runs [--kind eval|test]
```

From the command line the runner builds its own gateway from `ai:` in the config file and
its own registry from `config/tools/` (only the set's `tools`), so the shipped set runs offline
on the mock provider with no server. On the Evals page (`/admin/evals`) a run executes in a
background thread of the server against the live registry and gateway; the page polls it.

---

## 6. Tool versions and canary

### 6.1 Versions are internal

MCP clients see one tool per name. Versions live behind it: `tools/list` lists `calc_x` once,
`tools/call calc_x` runs whichever version routing chooses, and the result's
`_meta["io.sajha/tool-version"]` says which (`{"version": "2.0.0", "route": "canary"}`). A
tool without a versions file is untouched.

### 6.2 The versions file

`quality.versions_dir/<tool>.yaml` (default `config/tool_versions/`):

```yaml
tool: calc_percentage_change
stable: "4.5.0"                    # default: the registered config's own version
versions:
  "5.0.0":
    overrides:                     # deep-merged over the registered config (any key: implementation, description, ...)
      implementation: sajha.tools.impl.calc_tools.CalcPercentageChangeTool
    changelog: Rounds to 2 places.
  # or  config: calc_percentage_change-5.0.0.json   (a whole tool config, relative to this directory)
  "4.5.0":
    sunset: 2027-06-30             # deprecated: warn until the date, never route after it
    successor: "5.0.0"
routing:
  canary: {version: "5.0.0", percent: 10}   # sticky per caller (hash of the API key or user id)
  roles: {beta: "5.0.0"}
  users: {alice: "5.0.0"}
  api_keys: {ci-pipeline: "4.5.0"}          # API key *names*
rollback:
  max_error_rate: 0.2              # roll back when errors / calls exceeds this ...
  max_p95_ms: 3000                 # ... or when more than 5% of calls are slower than this
  min_calls: 20                    # ... over at least this many calls ...
  window_seconds: 300              # ... in this sliding window
deprecation:                       # the tool as a whole
  sunset: 2027-12-31
  successor: calc_percent_change
  message: Use calc_percent_change.
```

The registered config (from `config/tools/`) is always the version named by its own `version`
field; other versions are built from it (overrides) or from their own config, instantiated
the way the registry builds tools, and never registered, so nothing else sees them.

### 6.3 Routing

For each call, in order: an **API key pin** (`routing.api_keys`, by the key's name), a **user
pin**, the first matching **role**, the **canary** (a stable hash of the caller into 0–100 %:
the same caller gets the same version, anonymous callers are drawn at random), then
**stable**. A route to a version that is past its sunset, or one that has been rolled back
(except an API-key pin, which is a contract with that client), falls through to the next rule.

Routing happens at the top of `BaseMCPTool.execute_with_tracking`, so every path that runs a
tool through it (MCP in both eras, stdio, WebSocket, REST and the playground, Ask SAJHA, async
tasks, A2A, workflows) routes the same way; the chosen version's own `execute_with_tracking`
then applies policy, validation, cache, circuit breaker and metrics under the tool's one name.
Composite steps call a tool's `execute()` directly (`sajha/core/composition.py`), so a step
inside a composite always runs the registered version.

### 6.4 Automatic rollback

Every routed call is counted per version in the state store's sliding windows (calls, errors,
calls slower than `max_p95_ms`) and in `sajha_tool_version_calls_total{tool,version,outcome}`.
After a call to a non-stable version, when the window holds at least `min_calls` calls and the
error rate exceeds `max_error_rate` or more than 5 % of calls exceeded `max_p95_ms` (that is,
the p95 is above it), the version is **rolled back**: a record goes into the state store
(`quality:versions:rollback:<tool>:<version>`, written once with `add`, so one worker wins), a
warning is logged, an audit record is written and `sajha_tool_version_rollbacks_total` is
incremented. From then on, no canary, role or user rule routes to it, on every worker, until an
administrator clears the rollback (the Tool Versions page, or `DELETE
/api/quality/versions/{tool}/rollback/{version}`). The versions file is not changed.

### 6.5 Deprecation

A version with `sunset` (or `deprecated: true`) is deprecated: calls routed to it carry
`_meta["io.sajha/deprecation"]` (`{"version", "sunset", "successor", "message"}`) until the
sunset date; after it, the version is never routed to. The tool-level `deprecation` block does
the same for the whole tool: calls carry the warning until the sunset; after it the tool is
hidden from `tools/list` and a call fails with "retired" in the message.

### 6.6 Changing versions

The Tool Versions page (`/admin/tool-versions`) shows each versioned tool, its versions,
routing, per-version calls, errors and p95 in the current window, and rollbacks. An admin can
edit the YAML (validated before it is written, through the storage-free `config/tool_versions`
directory), set the canary percentage, promote a version to stable, or clear a rollback. The
files are re-read when they change (checked at most every `quality.versions.reload_seconds`).
API: `GET /api/quality/versions`, `PUT /api/quality/versions/{tool}` (YAML body),
`POST /api/quality/versions/{tool}/canary` (`{"version", "percent"}`),
`POST /api/quality/versions/{tool}/promote` (`{"version"}`).

---

## 7. Storage

| What | Where |
|---|---|
| test cases, eval sets, versions files | `config/tool_tests/`, `config/evals/`, `config/tool_versions/` (files, in git) |
| cassettes | `config/tool_tests/cassettes/<tool>/<case>.json` |
| test and eval runs | the `quality_runs` table (both schema files; SQLite creates it, PostgreSQL gets it from `schema.sql`) |
| probe state, probe claims, rollback records, version windows | the state store |

`quality_runs` holds one row per run: `id`, `kind` (`test` or `eval`), `name`, `status`
(`running | done | failed`), `started_at`, `finished_at`, `created_by`, `summary_json` (the
summary) and `detail_json` (per case or per question).

---

## 8. Pages and API

| Page | What |
|---|---|
| `/admin/tool-health` | probes (state, latency, history, run now), the latest saved test runs, the linter |
| `/admin/evals` | eval sets, start a run (model, planner), recent runs, a run's questions, compare two runs |
| `/admin/tool-versions` | versioned tools, routing, per-version stats, rollbacks; edit, canary, promote |

All three are administrator pages. Their JSON API is under `/api/quality/` (admin; a cookie
session sends the page's CSRF token as `X-CSRF-Token`); every route is listed in the
[API Reference §4.19](../protocol/API%20Reference.md#419-tool-quality-quality_routespy).

---

## 9. Security notes

* Cassettes never hold request headers, and secret query parameters are redacted, but a
  response body is stored as received: treat cassettes like any test data and review them.
* `--record` makes live calls with the credentials in your environment; `--replay` makes no
  network call at all (an unmatched request is an error, not a fallthrough).
* Versions files can point a tool at another implementation class. Only administrators can
  write them (the page and the API are admin-only); the file is validated before it is saved,
  and an override's `implementation` goes through the same loader (and sandbox for Studio
  code) as any tool config.
* Eval runs through the page use the server's gateway, so they spend real tokens on real
  providers; the cost shows in the run and in the usage ledger.

## 10. Limits

* Cassettes intercept `urllib.request`, `requests` and `httpx` only; tools on other clients
  (or SDKs with their own transports) run live.
* Rollback reacts after `min_calls` calls in the window; a canary that fails fast and rarely
  may stay up until it reaches the minimum.
* Probe metrics are per worker (the worker that ran the probe sets them); the probe state the
  page reads is shared.
* An eval's answer checks are lexical; they do not judge meaning.

## 11. Tests

`tests/test_quality_harness.py` (assertions, JSONPath, cassettes in all three clients, the CLI,
JUnit), `tests/test_quality_lint.py`, `tests/test_quality_probes.py`,
`tests/test_quality_evals.py` (offline on the mock provider), `tests/test_quality_versions.py`
(routing, canary stickiness, rollback, deprecation, MCP exposure), and the pages.
