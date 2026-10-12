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
  `requests` (`Session.send`) and `httpx` (sync and async transports) in
  `sajha/quality/cassette.py`; `urllib3` (`HTTPConnectionPool.urlopen`), `aiohttp`
  (`ClientSession._request`, what the OpenBB providers use) and `curl_cffi` (`Session.request`
  and `AsyncSession.request`, what yfinance uses) in `sajha/quality/cassette_transports.py`, each
  when its package is installed. botocore, the AWS SDK's transport, sends through urllib3, so boto3
  clients are recorded at the wire with no AWS-specific stub (its streamed, undecoded bodies are
  kept byte for byte). A request made inside another intercepted client (`requests` sits on
  urllib3) is recorded once, by the outer client. A tool on any other client is not
  intercepted; in `--replay` such a call is not caught.
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
| `unit`: every `x-sajha-unit` in the `outputSchema` is a unit of the workspace's grammar ([Quantitative Planners](Quantitative%20Planners.md) §2.2: `percent`, `bp`, `USD mn`, `count k`, ...) | error; on a property whose type holds no number (`object`, `boolean`): warning |
| `annotations` hints are booleans; `readOnlyHint` and `destructiveHint` are not both true | error |
| a tool whose name says it deletes, drops, purges, removes, revokes, truncates or wipes has `destructiveHint: true` | warning |
| a tool whose name says it only reads (`get`, `list`, `search`, `fetch`, `query`, ...) has `readOnlyHint: true` | info |
| every test case's `arguments` validate against the input schema (unless the case expects an error) | error |
| `required-default`: a required property has a `default` (it is never filled in, 12.1) | warning |
| `unapplied-default`: a `default` under `oneOf`/`anyOf`/`allOf`/`if`/`then`/`else`, `items` or `$defs` (never filled in) | info |
| `missing-example`: the live tool check cannot derive arguments (no test case, no `inputSchema` `examples`, a required property without `examples` or `default`) | warning |
| `description-length`: the tool's own description plus its folder's domain description is longer than `sajhanet.limits.max_description_chars` (1024), so SAJHA Net catalogs get the own description only ([Architecture §5](Architecture.md#domain-descriptions)) | warning |
| `llm-config`: an [LLM tool](LLM%20Tools.md)'s `llm` block passes the loader's checks (LLM Tools §5.2), including one the loader refused, so the tool is not in the catalog | error |
| `llm-catalog`: every `tools.allow` pattern matches a tool; a `narrate` source is in the catalog | error |
| `llm-annotations`: an LLM tool's config claims no less than its derived annotations (read-only only if every tool it may call is; destructive if any is) | warning |

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
  `tolerance`, `equals`), case-insensitive except `regex` flags you give, plus the optional
  model-graded `graded` check below;
* **limits**: steps, total tokens, cost and latency against the question's (or the set's
  default) limits; the ask must stop by `answer` unless `expect_stop` says otherwise.

**LLM tools.** A set with `tool: <name>` evaluates that [LLM tool](LLM%20Tools.md) instead of
Ask SAJHA (enabled or not): each question's `arguments` are the call (default
`{question: <question>}`), memory is off and no audit record is written. The checks apply to the
result's `answer`, `text` or `label` (else its JSON), and `expect_tools` to the inner tool calls.
The shipped example LLM tools have theirs: `config/evals/llm_*.yaml`. The quantitative planners have
theirs, with `number` checks and tolerances: `config/evals/quant_*.yaml`
([Quantitative Planners](Quantitative%20Planners.md) §4).

```yaml
name: llm_triage_ticket
tool: llm_triage_ticket
models: [mock/mock-planner]
questions:
  - id: billing
    question: A double charge on an invoice goes to billing.
    arguments: {message: "I was charged twice on my last invoice and need a refund."}
    answer: [{equals: billing}]
```

**Model-graded checks.** A `graded` check states a criterion in words; a grader model scores the
answer against it from 1 to 5 (the question is given for context) and the check passes at
`min_score` (default 4) or above (`sajha/quality/judge.py`):

```yaml
    answer:
      - number: 25
        tolerance: 0.01
      - graded: "says the value rose and by how much"
        min_score: 4            # optional, 1-5
        model: fast             # optional: a model alias; default quality.evals.grader_model
```

The grader is reached only through `llm_factory().model(alias)`, so the intelligence layer's role
policy, budgets, retries, fallback, audit and cost apply to it like any model call. Graded checks
are off by default because they cost tokens and a real model is not deterministic: while
`quality.evals.graded_checks` is false they are skipped, listed in the question's
`skipped_checks` and neither passed nor failed; `python -m sajha.quality eval --graded` turns them
on for one run. On the mock provider the grader is deterministic (the call is marked
`metadata.sajha_llm_mode: judge`: the criterion's content words found in the answer score 5,
otherwise 3), so sets with graded checks still run offline in CI. A grader that cannot answer (no
model, a refusal, a reply that is not a score) fails the check with the reason; it is never an
error of the run.

A question passes when all three hold. A run's summary: tool-selection accuracy, answer
accuracy, pass rate, mean steps, total and mean tokens, total cost, mean and p95 latency, per
(model, planner). Runs are saved in `quality_runs`; **compare** takes two runs and reports the
metric deltas and the questions that regressed or improved.

```
python -m sajha.quality eval [SET ...] [--model M ...] [--planner P ...] [--json FILE] [--junit FILE] [--no-save] [--graded]
python -m sajha.quality compare RUN_A RUN_B           # run ids, or JSON files written by --json
python -m sajha.quality runs [--kind eval|test]
```

From the command line the runner builds its own gateway from `ai:` in the config file and
its own registry from `config/tools/` and its tool folders (only the set's `tools`), so the shipped set runs offline
on the mock provider with no server. On the Evals page (`/admin/evals`) a run executes in a
background thread of the server against the live registry and gateway; the page polls it.

Saved runs are also evidence for choosing planners: the planner learning job ranks planners per
tool and question class from them, and each question's row carries the run's automatic planner
choice (`planner_choice`) when it had one ([LLM Tools](LLM%20Tools.md#913-automatic-planner-selection) §9.13).

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

The registered config (from `config/tools/` or a tool folder) is always the version named by its own `version`
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
| `/admin/tool-health` | probes (state, latency, history, run now), the live tool check's latest outcomes, the latest saved test runs, the linter |
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

* Cassettes intercept `urllib.request`, `requests`, `httpx`, `urllib3` (and so botocore),
  `aiohttp` and `curl_cffi`; a tool on another client (gRPC, a raw socket, a subprocess) runs
  live. A streamed `curl_cffi` response is recorded whole, not as a stream.
* Rollback reacts after `min_calls` calls in the window; a canary that fails fast and rarely
  may stay up until it reaches the minimum.
* Probe metrics are per worker (the worker that ran the probe sets them); the probe state the
  page reads is shared.
* An eval's lexical answer checks do not judge meaning; a `graded` check does, at the cost of a
  model call per check, and on a real model its score can vary between runs.

## 11. Tests

`tests/test_schema_defaults.py` (12.1), `tests/test_quality_check.py` (12.4),
`tests/test_quality_harness.py` (assertions, JSONPath, cassettes in all three clients, the CLI,
JUnit), `tests/test_quality_cassette_transports.py` (urllib3 and botocore's call pattern, aiohttp,
curl_cffi), `tests/test_quality_lint.py`, `tests/test_quality_probes.py`,
`tests/test_quality_evals.py` (offline on the mock provider), `tests/test_quality_graded_checks.py`, `tests/test_quality_versions.py`
(routing, canary stickiness, rollback, deprecation, MCP exposure), and the pages.

---

## 12. Tool health (wave 8, phase 8.1)

> **Status: built in 8.8.0**, as phase 8.1 of the
> [Implementation Plan](Implementation%20Plan.md#7b-wave-8-tool-health-open-data-business-intelligence-and-reports):
> schema defaults (12.1), the broken-tool fixes and removals (12.2), the shared SDMX client (12.3),
> the live tool check (12.4), the generated guide tables (12.5) and the lint rules of 12.6 except
> `openbb-command`, which is still planned. Domain descriptions, the other part of phase 8.1, belong
> to tool folders; they are described in [Architecture §5](Architecture.md#domain-descriptions).
> [Tutorial 44](../tutorials/TUTORIAL_44_tool_health.md) walks through all of it.

A review of every tool's description against its code found tools that cannot work and tools
whose behaviour differs from what their schema promises. This section designs the fixes and the
checks that keep them fixed.

### 12.1 Schema defaults applied before a call

> **Built (8.8.0).** `sajha/tools/schema_defaults.py`; tests in `tests/test_schema_defaults.py`.

Before 8.8.0 nothing copied an `inputSchema` `default` into the arguments: each implementation
applied its own default, and many disagreed with the schema the client reads (most `fred_*`
tools advertised `limit` 20 or 30 and used 40 or 60; `av_sma`, `av_ema`, `av_bbands` and `av_cci`
advertised `time_period` 14 and used 20; the `boj_*` tools advertised `recent_periods` 10 and
returned the full history).

**Where it runs.** `apply_schema_defaults(schema, arguments)` runs once, in
`BaseMCPTool.execute_with_tracking`, after version routing and SAJHA Net's name check and before
policy, validation, the cache, the circuit breaker, the call and the audit record. Every transport
reaches a tool through that method (MCP in both eras, the REST API, Ask SAJHA, LLM tools,
workflows, async tasks, SAJHA Net calls into this server), so they all see the same filled
arguments. The two places that call `execute` directly apply it too: the composite step executor
(`sajha/core/composition.py::execute_step`) and the quality harness (`sajha/quality/runner.py`).
A schema defined in Python (`get_input_schema`) is used exactly like one in a JSON config:
the helper reads `tool.input_schema`.

The rules:

1. **Absent keys only.** A key that is present is never replaced, even when its value is `null`;
   validation then judges that `null`.
2. **Never a `required` property.** A required property with a `default` is a contradiction;
   lint reports it (`required-default`, warning) and the call fails validation as before.
3. **Nested objects only when supplied.** For a property of `type: object` with its own
   `properties`, the helper recurses only when the caller supplied that object. A `default` on the
   object property itself fills the whole object when it is absent.
4. **Nothing through `oneOf`, `anyOf`, `allOf`, `if`/`then`, `$ref` or array `items`.** Which branch
   applies is not known before validation; lint reports such defaults (`unapplied-default`, info).
5. **Copies.** Defaults are deep-copied and the caller's dict is never changed.
6. **A default that fails its own property schema is not applied** (logged once), so a bad default
   cannot turn a call that used to work into an argument error; lint already warns (`default`).
7. **Recorded.** The `tool.call` audit record carries `details.defaults_applied` (the dotted names
   filled) and the tool span the attribute `sajha.tool.defaults_applied`. The result cache keys on
   the filled arguments, so `{}` and an explicit `{"limit": 30}` share one entry.

**Proxies.** Tools proxied from another MCP server (`FederatedTool`) and remote SAJHA Net tools
(`NetProxyTool`) set `apply_schema_defaults = False`: the arguments are forwarded as the caller sent
them, and the server that owns the tool applies its own contract. The contract hash (schemas and
annotations) is unchanged.

**Compatibility.** The schema is the contract: where a code default differed, the schema's value now
applies. The CHANGELOG (8.8.0, "Upgrading") lists every tool whose effective default changed.
Schema defaults always apply: the one-release off switch of 8.8.0 (`tools.apply_schema_defaults`)
was removed in 8.14.0, and only a tool that sets `apply_schema_defaults = False` (the proxies above)
opts out.

### 12.2 Broken tools: fix or remove

Each finding below was confirmed against the code. The decision for each is to **fix** it when a
documented upstream exists, and otherwise to **remove** the tool. A tool is never left returning
an error or invented data. Removed tools go in the CHANGELOG with their replacement, if any.

| Finding | Where | Decision |
|---|---|---|
| OpenBB commands absent in OpenBB 4.6 | `sajha/tools/impl/openbb_tools.py`: `openbb_treasury_rates`, `openbb_yield_curve`, `openbb_earnings`, `openbb_commodity_price`, `openbb_commodity_lbma_gold`, `openbb_commodity_lbma_silver`, `openbb_commodity_search`, `openbb_index_search`, `openbb_index_constituents` (the default `sp500` path), `openbb_equity_fundamental_overview`, `openbb_fixedincome_ice_bofa`, `openbb_fixedincome_moody`, `openbb_regulators_sec_filings`, `openbb_economy_interest_rate` | Fix where 4.6 has a successor: `fixedincome.government.treasury_rates`, `fixedincome.government.yield_curve`, `commodity.price.spot`, `index.constituents`, `economy.interest_rates`. Remove the rest. A load-time check refuses an OpenBB tool whose command path does not resolve in the installed OpenBB, with the info notice `tools.openbb_command:<tool>` |
| Yahoo `quoteSummary` answers 401 | `yahoo_get_quote` (`sajha/tools/impl/yahoo_finance_tool.py`) | Fix: go through yfinance, which handles Yahoo's cookie and crumb |
| `yf.Screener` no longer exists | `yf_screener` and `yf_trending_tickers` (`sajha/tools/impl/yfinance_tools.py`) | Fix: use `yf.screen` with `EquityQuery`. Remove `yf_trending_tickers` if no keyless equivalent exists |
| Silent truncation of results | yfinance tools (`_df_to_records`, `limit=100`) and the generic OpenBB tool (`records[:100]`) | Fix: a `limit` argument in the schema, capped at a maximum, and `truncated: true` with the total row count whenever rows were cut |
| Banque de France tools call a dead host | `bdf_*` (`sajha/tools/impl/france_central_bank.py`): `sdw-wsrest.ecb.europa.eu`, a dotted series path, a hard-coded series key in the parser, and one series for all four OAT tenors | Fix: use the shared SDMX client (12.3) on `data-api.ecb.europa.eu`, with a series per tenor, each verified live |
| Reserve Bank of India API returns 418 | `rbi_*` (module `india_central_bank.py`, removed in 8.8.0), an undocumented `rbi.org.in` endpoint | Remove. Re-add only from a documented source; FRED and the IMF carry some Indian series, and each re-added tool states its source |
| Federal Reserve tools return demo data | `fed_*` (`sajha/tools/impl/fed_reserve_tool_refactored.py`): synthetic values when the key is `demo` | Fix: without a key, return a configuration error that names the key, never synthetic values. The principle "no tool returns invented data" becomes a review rule |
| `un_get_sdg_progress` is a stub | `sajha/tools/impl/united_nations_tool_refactored.py` | Remove. `un_get_sdg_data` covers the indicator series |
| IMF uses the legacy host | `sajha/tools/impl/imf_tool_refactored.py`: `http://dataservices.imf.org/REST/SDMX_JSON.svc` | Fix: move to the IMF's current SDMX API through the shared SDMX client, verified live in the phase (including whether it needs a subscription key) |
| `NameError: logger` | `EDGARCompaniesBySICTool` (`edgar_companies_by_sic`, `sajha/tools/impl/enhanced_edgar_tool.py`): an error handler uses a `logger` that is never defined | Fix: use `self.logger`, and add a test that drives the error path |
| CoinGecko `order` values that CoinGecko does not document | `cg_top_gainers`, `cg_top_losers` (`percent_change_24h_desc` and `_asc`); `cg_coin_markets` passes any `order` | Fix: fetch by market cap and sort by `price_change_percentage_24h` in SAJHA; give `cg_coin_markets.order` an `enum` of the documented values |
| Options that do nothing | `wiki_get_page` (`sajha/tools/impl/wikipedia_tool.py`): `include_references` (ignored), `include_links` (always empty), `html_content` (always empty), `redirect: false` (MediaWiki treats any value as true) | Fix `include_links` with a bounded `prop=links` request; fix `redirect` by omitting the parameter; remove the other options from the schema |
| Misnamed series | `boj` `trade_balance` (an OECD exports series); `pboc` `lending` and `deposit` (both one IMF discount-rate series), `prime_rate` (a CPI series), `eur_cny` (`EXCHUS`); `bdf` `m3` (a loans series) | Fix each to the series its label names, verified live; remove any label with no openly available series |

A tool's description is rewritten in the same change as its fix, so that the description promises
only what the code does.

**Built: the market data rows (OpenBB, Yahoo, Alpha Vantage).** As described in the
[OpenBB](../tools/market-data/OpenBB%20Tool%20Reference%20Guide.md#how-a-call-runs),
[Yahoo Finance](../tools/market-data/Yahoo%20Finance%20Tool%20Reference%20Guide.md) and
[Alpha Vantage](../tools/market-data/Alpha%20Vantage%20Tool%20Reference%20Guide.md) guides, with three
differences from the decisions above. The OpenBB command check runs when a tool is called, not when it
loads, because importing OpenBB takes seconds; `tests/test_market_data_fixes.py` checks every shipped
tool's command, providers and arguments against the installed OpenBB instead. `openbb_news_search` was
removed as well (its command has no search parameter). `yf_trending_tickers` was kept: Yahoo's trending
endpoint needs no cookie, and `yf_screener` uses Yahoo's predefined screens, so `EquityQuery` is not
needed.

**Built: the open data rows (central banks, IMF, UN, EDGAR, CoinGecko, Wikipedia, FRED, World Bank,
FBI).** Each fix was verified live; `tests/test_open_data_fixes.py` pins them with fakes, and also
checks that every description in these folders is at most 1000 characters with an `Example:` that
validates against the tool's schema. Differences from the decisions above, all because the live check
found less than the table assumed:

- **Banque de France.** The ECB publishes one French government bond yield (the 10-year convergence
  yield), so `bdf_get_oat_yield` offers only `10y`. The ECB retired its `ICP` inflation dataflow in
  February 2026; inflation reads `HICP`, in the `ecb_` tools too, which also lost EONIA (no data since
  2022) and moved €STR, GDP and unemployment to live keys.
- **RBI.** No `rbi_` tool was re-added: Indian exchange rates, CPI and reserves are in
  `imf_get_ifs_data` (country IND); FRED and the IMF carry no current Indian policy rate.
- **IMF.** The current API (`api.imf.org/external/sdmx/2.1`) needs no key. The IMF retired IFS, so
  `imf_get_ifs_data` reads the successor dataflows (CPI, ER, MFS_IR, IL, MFS_MA) for the indicators
  that have one, and `imf_get_databases` / `imf_get_dataflows` list live dataflows and key structures.
- **PBoC and BoJ.** FRED has no Chinese government bond yield, lending, deposit or Loan Prime Rate,
  and its Chinese money supply stopped in 2019, so `pboc_get_cgb_yield` and `pboc_get_money_supply`
  were removed; Chinese and Japanese CPI, Japanese broad money and Chinese GDP growth come from the
  IMF. Several BoJ series had also ended on FRED (discount rate, M1-M3, CPI, PPI, industrial
  production) and were dropped. With no date, these tools return the last `recent_periods` (10).
- **Federal Reserve.** One FRED key lookup serves every FRED-backed tool (`sajha/tools/impl/fred_key.py`);
  `fred_` tools no longer send the placeholder `DEMO_KEY` either.
- **FRED series.** `GOLDAMGBD228NLBM` and `SLVPRUSD` are no longer on FRED: `fred_gold_price` and
  `fred_silver_price` were removed (the IMF's PCPS dataflow replaces them). `USSLIND` ended in 2020;
  `fred_leading_index` reads the OECD leading indicator `USALOLITOAASTSAM`.
- **Found while fixing.** `un_get_sdg_data` read the SDG API's paged answer as a list (always empty)
  and sent ISO codes the API ignores; it now converts to M49 (`sajha/tools/impl/country_codes.py`) and
  pages. The EDGAR tickers file had moved (`edgar_company_search` always failed); the `edgar_` tools
  read `company_tickers_exchange.json`, which carries the exchange. `edgar_companies_by_sic` scans the
  `max_scan` largest companies. EDGAR's SCHEDULE 13D/G names (since December 2024) match the SC names;
  frames fall back to instant periods; `edgar_financial_ratios` picks the period's own values, not the
  comparatives; `sec_get_mutual_fund_holdings` lists NPORT-P. World Bank search covers the whole
  catalogue and `most_recent_year` works; FBI year schemas lost their fixed maximum.

### 12.3 A shared SDMX client

**Built** (`sajha/tools/impl/sdmx_client.py`). One client for SDMX 2.1 REST (`data/{flow}/{key}` with
`startPeriod`, `endPeriod`, `lastNObservations` and `firstNObservations`):

- **Host profiles** (`SdmxHost`): the base URL, the flow-reference syntax (a bare id, or
  `AGENCY,ID[,VERSION]` with a default agency), the CSV selector (a `format=` value, or an `Accept`
  header) and the attribution put on every result. `ecb` and `imf` ship; `register_host` adds one,
  which is how phase 8.2's BIS, Eurostat, OECD and ABS tools join.
- **Parsing.** SDMX-CSV is the wire format (the ECB's `csvdata` flavour and SDMX-CSV 1.0 and 2.0);
  `parse_sdmx_json` reads SDMX-JSON 1.0 for a host without CSV. Series come back with their
  dimensions, series attributes (title, unit, unit multiplier) and observations oldest first;
  `YYYY-Mnn` periods become `YYYY-MM`. `fetch_series` gives the flat one-series shape the central
  bank tools return.
- **No data is not an error**: a 404, a `NoRecordsFound` body, an empty body or the IMF's single blank
  row gives no series. Any other HTTP error, a timeout or a refused destination is an `SdmxError`.
- **Every fetch** goes through the outbound fetch guard and HTTP proxy (`sajha/core/outbound.py`), and
  only to the profile's own base URL.
- **Structure**: `dataflows` (a host's dataflows) and `flow_structure` (a dataflow's dimensions in key
  order with their codes, from the dimension's own codelist or its concept's) are cached per process
  for an hour.

The ECB, Banque de France and IMF tools use it, and the PBoC and BoJ tools read their IMF series
through it ([Open Data Tools](Open%20Data%20Tools.md#3-one-sdmx-client)).

### 12.4 The live tool check

> **Built (8.8.0).** `sajha/quality/check.py`; tests in `tests/test_quality_check.py` (fake tools only:
> the test suite never calls a live service).

Probes (section 4) run only the cases someone wrote. The **live tool check** calls every eligible
tool once and reports which are broken. It rides the probe scheduler rather than adding a second one.

- **Arguments.** For each tool the check takes, in this order:
  1. its `probe:` case, else its first test case that is expected to succeed;
  2. else the first entry of its `inputSchema` `examples` (an object; JSON Schema 2020-12's own
     keyword, so no `x-` extension is needed);
  3. else the first `examples` entry (or the `default`, or the `const`) of each required property; a
     tool with nothing required is called with `{}`.

  It never parses prose in a description. A tool with no derivable arguments is `not_checked`, and
  lint reports it (`missing-example`, warning). The call then gets the schema defaults (12.1),
  validation and `execute`, as in the harness: not `execute_with_tracking`, so a cached result or an
  open circuit breaker cannot hide a broken upstream, and the check's calls are not billed to users.
- **What it skips**, each with its reason: tools without `annotations.readOnlyHint: true`, tools with
  `destructiveHint`, LLM tools (each call costs tokens), proxied and SAJHA Net tools (their own
  servers' business), tools bound to a connected account, disabled tools, and tools matching
  `quality.check.exclude`. Every shipped tool that only reads (market data, macro data, filings,
  search, the web crawler's fetches, calculators, the read-only SQL and document tools) declares
  `readOnlyHint: true`, with `openWorldHint` true when it calls an outside service; tools that write,
  send, or act on a connected account do not, so the check never calls them.
- **Outcomes.**

  | Outcome | Meaning |
  |---|---|
  | `ok` | The call succeeded |
  | `empty` | The call succeeded but returned nothing: `null`, `{}`, `[]`, or an object whose lists are all empty |
  | `error` | An exception, an `{"error": ...}` result, `isError: true`, or no answer within `quality.check.timeout_seconds`; recorded with its class. A rate-limited call (the message says `rate limit`, `HTTP 429` or `too many requests`) is an `error` even when it also suggests a key |
  | `schema_mismatch` | The result fails the tool's `outputSchema` |
  | `not_configured` | A key field of the tool's config (`api_key`, `*_token`, ...) is empty or an unresolved `${...}` (no call is made), or the error says a key or credential is missing: configuration, not breakage. A tool class that sets `keyless_fallback = True` (a public or demo tier without the key: the FBI tools' `DEMO_KEY`, UN Comtrade's preview API, CoinGecko's public API) is called even when its key is empty (8.14.0) |
  | `not_checked` | No derivable arguments |
  | `skipped` | Not eligible, or the run's budget ran out; the reason is given |

  Broken means `error` or `schema_mismatch`.
- **Load on upstreams.** One call at a time per tool folder (one provider), with
  `quality.check.pause_ms` between calls in a folder, or longer when the tool's
  `check_pause_seconds` asks for it (the `cg_` tools ask for 60 divided by
  `coingecko.calls_per_minute`, so the check never trips CoinGecko's limit); at most `quality.check.concurrency` folders at
  once; `quality.check.timeout_seconds` per call; a total `quality.check.budget_seconds`, after which
  the remaining tools are `skipped`.
- **Running it.** `python -m sajha.quality check [--tool GLOB] [--folder NAME] [--json FILE]
  [--junit FILE] [--save] [--all]` prints one line per tool that is not skipped (`--all` shows those
  too), writes the JSON report (`summary` and `results`: tool, folder, outcome, message, where the
  arguments came from, the arguments, duration, error class) and JUnit, and with `--save` stores the
  run in `quality_runs` (kind `check`). It exits 1 when a tool is broken. The schedule is optional:
  `quality.check.cron` (with `quality.check.timezone`) is evaluated by the probe scheduler, which then
  starts even when `quality.probes.enabled` is false; a slot is claimed with
  `state_store.add('quality:check:fire:<slot>')`, so one worker runs it, in a background thread.
- **Notices.** The `quality` notice source raises one warning notice per tool folder with broken
  tools (`quality.check:<folder>`, administrators, no ttl). It lists the tools and their outcomes, and
  clears when a later run checks that folder and finds nothing broken; a run of another folder leaves
  it alone. One notice per folder keeps a provider outage from becoming a hundred notices.
- **Results.** The latest outcome per tool is kept in the state store (`quality:check:last`), shown in
  the Live tool check section of the Tool Health page (problems first) and returned by
  `GET /api/quality/check`.

### 12.5 Tool Reference Guide tables, generated

The tool tables of the guides under `docs/tools/` are generated from the tool configs
(`sajha/tools/guides.py`). The prose around them stays hand-written.

- `python -m sajha.tools guides [--folder NAME] [--check]` rewrites only the region between
  `<!-- generated:tools folder=<name> ... -->` and `<!-- /generated:tools -->`. Marker attributes:
  `folder` (required), `group=category` (one `###` table per `metadata.category`), `include` and
  `exclude` (comma-separated globs of tool names; an `exclude` entry `!glob` keeps what it names).
- Columns: tool, title (when any tool in the region has one), the first sentence of the tool's own
  description, required parameters, optional parameters with their schema defaults, annotations
  (and `disabled`), and the key the tool needs: a `${...}` reference to a key, secret, token or
  password, with the environment variable `config/application.yml` binds it to. When every tool in
  the region needs the same key, it is stated once above the table instead of in a column.
- A schema built in code (no `inputSchema` in the config) is read from the tool class. When a module
  the config `requires` is not installed, the region is left as it is and reported as unavailable,
  not stale.
- `--check` writes nothing and exits 1 when a region is stale; `tests/test_tool_guides.py` runs it,
  so a changed tool config fails the suite until the guide is regenerated. Every guide whose table
  lists a folder's tools has a marked region; tables that carry facts a config does not hold
  (scopes, response sizes) stay hand-written.

### 12.6 Lint additions

- `required-default` (warning), `unapplied-default` (info) and `missing-example` (warning): built in
  8.8.0, in the rule table of section 3
- `description-length` (warning): the tool's description plus its folder's domain description is
  longer than SAJHA Net's catalog limit (`limits.max_description_chars`, 1024 by default,
  `sajha/net/catalog.py`): built in 8.8.0
- `openbb-command` (error): planned. Today the OpenBB tool itself refuses a command path the
  installed OpenBB does not have, with the info notice `tools.openbb_command:<tool>`

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
