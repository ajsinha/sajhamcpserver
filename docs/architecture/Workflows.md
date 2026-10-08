# SAJHA MCP Server — Workflows

A workflow is a saved DAG of steps: tool calls, composite tools, Ask SAJHA questions,
conditions with branches, loops over lists, waits and human approvals. It runs by hand
(the Workflows page, `sajha workflows run`, the REST API) or from a trigger (a cron
schedule, a signed webhook, a file arriving on the storage backend, a change-bus event),
every run is recorded step by step in the database, and a run that a worker was executing
when it died is picked up by another worker. A workflow can also be published as an
ordinary MCP tool.

This document owns the topic: the definition format, how a run executes, triggers,
durability, identity and security, the API, the CLI, and the limits. Configuration keys
and their defaults are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#workflows); the
hands-on walkthrough is [Tutorial 22](../tutorials/TUTORIAL_22_schedule_a_workflow.md);
the terms are in the [Glossary](../../GLOSSARY.md). Composite tools, which a workflow can
call as steps, are in the [Composition Framework](Composition%20Framework.md).

Workflows are on by default (`workflows.enabled: true`) and none exist until someone
saves one, so a fresh SAJHA behaves as before.

---

## 1. Shape

```
 triggers      manual (page, CLI, API) · cron · signed webhook · file arrival · change-bus event
               · a call to the published tool
                     │ start_run (idempotency key) ─► workflow_runs row, status queued
 dispatch      concurrency limit per workflow (all workers) ─► status running on one worker
                     │
 executor      RunExecutor: DAG in dependency order, up to max_parallel steps at once,
               each step: mapping ─► policy + RBAC as the owner ─► call with timeout/retries
                     │ every state change ─► workflow_run_steps row
 end           succeeded / failed / cancelled ─► output stored, delivered (async delivery)
               waits and approvals ─► status waiting, worker freed; the scheduler wakes it
```

| Code | What |
|---|---|
| `sajha/workflows/model.py` | The definition: parse JSON or YAML, validate, fill defaults, implicit dependencies, topological order |
| `sajha/workflows/expr.py` | Parameter mapping (`$input`, `$steps`, `$item`, `{{...}}`) and conditions |
| `sajha/workflows/cron.py` | Five-field cron in an IANA timezone, no dependency |
| `sajha/workflows/store.py` | The three tables (SQLAlchemy Core) and every read and write |
| `sajha/workflows/identity.py` | Run as: the owner's identity and tool policy |
| `sajha/workflows/engine.py` | `RunExecutor`: one run of the DAG |
| `sajha/workflows/service.py` | `WorkflowService`: definitions, runs, triggers, the scheduler, recovery, delivery |
| `sajha/workflows/tool.py` | `WorkflowTool`: a workflow published as a registry tool |
| `sajha/routes/workflow_routes.py` | The page and `/api/workflows` |
| `sajha/web/templates/workflows/workflows.html`, `sajha/web/static/js/workflows.js` | The Workflows page |

---

## 2. The definition

A definition is JSON or YAML. The page edits it as a form, as JSON or as YAML; the API
takes either.

```yaml
name: rates_watch                      # [A-Za-z][A-Za-z0-9_-]*, unique
description: Ten-year yield, and an alert when it moves
input_schema: {type: object, properties: {limit: {type: integer}}}   # optional; the published tool's schema
concurrency: 1                         # runs of this workflow at once, all workers (default workflows.default_concurrency)
max_parallel: 4                        # steps of one run at once (default workflows.max_parallel_steps)
timeout_seconds: 3600                  # the whole run (optional)
steps:
  - id: yield
    kind: tool
    tool: fred_10yr_treasury
    params: {limit: $input.limit}
    retry: {max_attempts: 3, backoff_seconds: 2, backoff_factor: 2, max_backoff_seconds: 60}
    timeout_seconds: 30
  - id: moved
    kind: condition
    if: "$steps.yield.change > 0.1"
    then: [explain]
    else: [quiet]
  - id: explain
    kind: ask
    question: "Explain this move in two sentences: {{$steps.yield}}"
  - id: quiet
    kind: wait
    seconds: 1
  - id: done
    kind: tool
    tool: calc_percentage_change
    params: {old_value: 1, new_value: 2}
    depends_on: [explain, quiet]
    join: any_success                  # one branch is skipped; run once either finished
output: {yield: $steps.yield, note: $steps.explain.answer}   # optional; default: every step's output
triggers:
  - {id: weekday_morning, type: cron, cron: "0 7 * * 1-5", timezone: Europe/London}
delivery: {type: file, destination: workflows/rates_watch.json}   # optional
publish: {enabled: true, tool_name: rates_watch, timeout_seconds: 120}  # optional, administrators
```

### Step kinds

| Kind | Fields | What it does |
|---|---|---|
| `tool` | `tool`, `params` | Calls a registry tool through `execute_with_tracking` (policies, cache, circuit breaker, metrics, usage) |
| `composite` | `tool`, `params` | The same, for a composite tool (composites are registry tools); kept as its own kind so the graph says what it is |
| `ask` | `question`, `model` | Asks Ask SAJHA (`sajha/ai/intelligence.py`) as the owner; the output is the answer record (`answer`, `steps`, `citations`, ...). Fails when no LLM provider is configured |
| `condition` | `if`, `then`, `else` | Evaluates a condition to `{"result": true/false}`; the steps named in the branch not taken are skipped |
| `foreach` | `items`, `do`, `max_items`, `parallel`, `on_overflow` | Runs one `tool`, `composite` or `ask` call per element of a list (`$item`, `$index`); output `{items, count, truncated, failed}` |
| `wait` | `seconds` or `until` | Waits; up to `workflows.inline_wait_seconds` in the worker, longer by parking the run |
| `approval` | `reason`, `ttl_seconds` | Holds the run for a human decision on the Approvals page (the policy engine's approval store) |

Every step also takes `depends_on`, `join` (`all_success`, the default; `any_success`;
`all_done`), `when` (a condition; false skips the step), `on_error` (`fail`, the default,
fails the run; `continue` records the failure and goes on) and, for calls, `retry`,
`timeout_seconds`, `idempotent` and `idempotency_param`.

A step that reads `$steps.<id>` depends on that step without saying so, and a step named
in a condition's `then` or `else` depends on the condition. A cycle, an unknown step, a
bad operator, an invalid cron expression or timezone, or a file prefix that is absolute
or contains `..` is refused when the definition is saved.

### Mapping and conditions

Parameter mapping extends the composite syntax (`resolve_source` in
`sajha/core/composition.py`):

| Expression | Value |
|---|---|
| `$input.x` (or `$.input.x`) | the run's input |
| `$steps.<id>`, `$steps.<id>.a.0.b` | a finished step's output, or a path into it |
| `$item`, `$item.x`, `$index` | inside a `foreach`: the element and its position |
| `$run.id`, `$run.workflow`, `$run.trigger` | the run |
| `"text {{$input.x}} text"` | interpolation (non-strings are inserted as JSON) |
| anything else | a literal |

A condition is a string `"<ref> <op> <value>"` (`==`, `!=`, `>`, `>=`, `<`, `<=`, `in`,
`not_in`, `contains`, `startswith`), a unary string `"exists <ref>"` (`exists`,
`not_exists`, `truthy`, `falsy`), an object `{left, op, right}`, `{all: [...]}`,
`{any: [...]}`, `{not: ...}`, a bare reference (its truthiness) or a boolean.

---

## 3. A run

`RunExecutor` (`sajha/workflows/engine.py`) loads the run's step records, then loops:
every pending step whose dependencies are all finished either runs (its `join` and `when`
allow it and no condition skipped it) or is skipped with the reason; up to `max_parallel`
steps run at once on their own thread pool. When a step fails and its `on_error` is
`fail`, no new step starts, the steps in flight finish, the rest are marked skipped and
the run fails.

- **Retries and backoff.** A call that raises, returns `{"error": ...}` or an MCP result
  with `isError` is retried up to `retry.max_attempts`, sleeping `backoff_seconds ×
  backoff_factor^(n-1)` (at most `max_backoff_seconds`) between attempts. A policy denial
  or a run-as refusal is never retried; a policy rate limit waits at least its
  `retry_after`.
- **Timeouts.** Each attempt is limited by `timeout_seconds` (default
  `workflows.step_timeout_seconds`); a timeout is retried unless `retry.on_timeout` is
  false. A run's `timeout_seconds` fails the whole run. Python cannot kill a thread: a
  timed-out call is abandoned, not stopped, and its late result is ignored.
- **Cancel.** `POST /api/workflows/runs/{id}/cancel` (or the page) sets a flag in the
  run's row; the executor, on whichever worker, sees it within half a second, cancels
  every step not yet finished and finishes the run `cancelled`. A call already in flight
  completes in the background (it cannot be interrupted); its step is recorded as
  cancelled. A queued or parked run is cancelled at once.
- **Waits and approvals park the run.** A wait longer than
  `workflows.inline_wait_seconds`, an `approval` step, or a tool step that a policy rule
  holds for approval (`effect: require_approval`) records what it waits for (`wake_at` or
  `approval_id`) and, when nothing else can run, the run becomes `waiting` and its worker
  is freed. Each scheduler tick checks parked runs and, when a wait is over or an approval
  is decided, one worker claims the run and continues it. A policy approval is then
  consumed by the repeated call, exactly as for a direct call (see
  [Policy and Audit](Policy%20and%20Audit.md)). The workflow owner cannot approve their own
  approval step unless `policy.approvals.allow_self_approval` is on.
- **Output.** The run's output is the `output` mapping, or every finished step's output
  keyed by step id. Stored step inputs are cut at `workflows.step_input_max_chars` and
  outputs at `workflows.step_output_max_chars`; a larger value is stored as
  `{"_truncated": true, "chars": N, "preview": "..."}`.
- **Delivery.** With `delivery`, the finished run (status in `delivery.on`, default
  `succeeded` and `failed`) is sent through the async executor's `DeliveryRouter`
  (`sajha/core/async_executor.py`): `webhook` only to URLs in
  `async.delivery.webhook.allowed_urls` (with its SSRF guard), `file` only inside
  `async.delivery.file.base_dir`, or `kafka`. The destination is validated when the
  definition is saved. The result goes in the run's `delivery_status`.

### Durability, resume and re-run

Runs live in three tables (section 7). Each step's status, attempts, input, output,
error and timing are written as they change, and the executing worker refreshes the run's
`heartbeat_at` every `workflows.heartbeat_seconds`.

When a worker dies mid-run, its run keeps status `running` with a heartbeat that stops
moving. Each scheduler tick on every worker looks for running runs whose heartbeat is
older than `workflows.stale_seconds` and whose worker is not alive in the state store, and
takes one over with a conditional `UPDATE ... WHERE worker_id = <old> AND heartbeat_at =
<old>`, so exactly one worker wins. The new executor:

- reuses the stored output of every step that had succeeded (it is never run again);
- runs again a step that was `running` when the worker died **only if it is idempotent**:
  `idempotent: true` on the step, or a tool whose annotations say `readOnlyHint` or
  `idempotentHint`, or a `condition`, `wait` or `approval`;
- marks a non-idempotent interrupted step `failed` ("interrupted ... not idempotent"),
  because SAJHA cannot know whether its effect happened, and the run fails.

Every call also has an idempotency key (a hash of run, step, item and resolved
parameters), stored on the step. `idempotency_param: request_id` passes it to the tool as
that argument, so a tool that de-duplicates on a request id can be made safe to repeat.

**Re-run from a step** (`POST /api/workflows/runs/{id}/rerun`, the page's Re-run button):
a new run with the same input and the definition the old run used (`latest_definition:
true` uses the current one), which copies the results of every step that is not the
chosen step (default: the first failed or cancelled step) or downstream of it, and runs
the rest. It records `parent_run_id` and `from_step`.

### Concurrency

A new run is `queued`. A worker starts it only while the workflow has fewer runs
`running` or `waiting` than its `concurrency` (default `workflows.default_concurrency`),
counted in the database under a short state-store lock, so the limit holds across workers.
A queued run starts when a run of the same workflow ends, or at the next tick. Each worker
executes at most `workflows.max_concurrent_runs` runs at once.

**Run idempotency keys.** A run started with an idempotency key (the `Idempotency-Key`
header or `idempotency_key` in the body of a manual run, a webhook's `X-Sajha-Delivery`,
a cron slot, a file and its modification time) is unique per workflow (a unique index), so
a repeated request returns the first run instead of starting another.

---

## 4. Triggers

| Type | Fields | Fires |
|---|---|---|
| manual | (always available) | the page, `sajha workflows run`, `POST /api/workflows/{name}/runs` |
| `cron` | `cron`, `timezone` | at each due slot of a five-field cron expression in an IANA timezone |
| `webhook` | `secret` or `secret_ref: env:NAME`, `tolerance_seconds` | on a correctly signed `POST /api/workflows/{name}/hooks/{trigger}` |
| `file` | `prefix`, `pattern`, `interval_seconds`, `fire_existing` | when a file under `prefix` matching `pattern` appears or changes on the storage backend |
| `event` | `kinds`, `uri`, `debounce_seconds` | on a change-bus event (`tools`, `prompts`, `resources`, `resource_updated`) |

Every trigger may carry `input` (merged under what the trigger supplies) and `enabled`.
A disabled workflow fires no triggers; it can still be run by hand.

**Cron.** `minute hour day-of-month month day-of-week`, with `*`, ranges, steps, lists and
month and weekday names, plus `@hourly`, `@daily`, `@weekly`, `@monthly`, `@yearly`.
When both day fields are restricted, either matching fires (classic cron). Times are
evaluated in `timezone` (default UTC): a wall time skipped by a daylight-saving change does
not fire that day, and a repeated one fires once. Slots missed while no worker was running
are coalesced: at most one run (the latest slot) per tick. **One fire across workers:**
the worker that fires a slot first claims `wf:cron:<workflow>:<trigger>:<slot>` with an
atomic `add` in the state store; the others see it taken. The run's idempotency key is
`cron:<trigger>:<slot>`, so even two workers with separate memory stores could not create
two runs for one slot in one database. With several workers, use a shared state store
(`state.backend: redis` or `database`, see [Scaling and State](Scaling%20and%20State.md)).

**Signed webhooks.** On save, a webhook trigger without `secret` or `secret_ref` gets a
generated secret (shown masked; `GET /api/workflows/{name}?reveal=1` shows it to the owner
or an administrator; saving the masked value back keeps it). The sender sends:

```
POST /api/workflows/<name>/hooks/<trigger>
X-Sajha-Timestamp: <unix seconds>
X-Sajha-Signature: sha256=<hex HMAC-SHA256(secret, "<timestamp>." + body)>
X-Sajha-Delivery: <optional unique id>       (makes the run idempotent)
```

A timestamp more than `tolerance_seconds` (default 300) away from the server's clock is
refused (401), as is a bad signature; a signature seen before within twice the tolerance
is refused as a replay (409; remembered in the state store, so across workers). The JSON
body becomes the run's input. The route needs no session: the signature is the
authentication. Bodies over 1 MiB are refused.

**File arrival.** Every `interval_seconds` one worker (a state-store lock) lists `prefix`
on the configured storage backend (`sajha/core/storage.py`: local disk, S3, Azure Blob or
GCS; see the [Storage Guide](../getting-started/Storage%20Guide.md)), matching `pattern`
against the file name. A file is new when its modification time differs from the one
recorded in the state store; the run's input has `path` and `modified`. The first poll
records what is there without firing unless `fire_existing: true`. This is polling, not
notification: a file can wait up to an interval, and object stores are listed in full each
time (the first 1000 matches are considered).

**Change-bus events.** The service listens to the change bus (`sajha/core/change_bus.py`)
on each worker; an event fires on the worker that produced it, debounced per trigger. The
run's input has `event: {kind, uri}`.

---

## 5. Identity and security

- **Run as the owner.** The creator of a workflow is its owner, and every step runs as
  the owner, whoever or whatever started the run. At the start of each run (and each
  resume) the owner is re-read from the database (`sajha/workflows/identity.py`): a
  user's current roles decide which tools the steps may execute (administrators may run
  every tool), and an owner `apikey:<name>` uses that key's allow or deny list. A deleted
  or disabled owner fails the run. The owner is set as the caller, so policy rules (with
  source `workflow`), the usage ledger and the audit see the owner; Ask SAJHA steps use the
  owner's tool access as their `can_use_tool`.
- **Who may do what.** Any signed-in user may create workflows (they run with that user's
  rights). The owner and administrators may edit, run, enable, disable, delete, cancel and
  re-run; others do not see the workflow. Only administrators may publish a workflow as a
  tool, because callers of the published tool would run its steps with the owner's rights.
- **Policies on every step.** Tool steps go through `execute_with_tracking`, so every
  policy rule, approval, rate limit, quota and redaction applies, with source `workflow`.
- **Audit.** `workflow.save`, `workflow.delete`, `workflow.run`, `workflow.finish`,
  `workflow.cancel`, `workflow.rerun` and `workflow.resume` are recorded in the audit chain.
- **Secrets.** Webhook secrets are stored in the definition (database) and masked in every
  API response unless revealed by the owner or an administrator; `secret_ref: env:NAME`
  keeps the secret out of the database.

---

## 6. Published as a tool

`publish: {enabled: true}` (administrators) registers a `WorkflowTool` named
`publish.tool_name` (default the workflow's name; it is not published if another tool
already has the name). Workflow and tool names never contain `__`, which is reserved for
namespaced tools (`sajha/tools/naming.py`; [Federation](Federation.md#names)). Its input schema is the workflow's `input_schema`. A call starts a
run (trigger `tool`), waits up to `publish.timeout_seconds` and returns `{run_id, status,
output}`; a failed run is a tool error; a run still going returns its id to follow. It is
an ordinary registry tool: listed by `tools/list` in both protocol eras, subject to tool
RBAC and policies for who may call it, usable from Ask SAJHA and composites, and
federatable. Disabling or deleting the workflow unregisters it; a registry reload
publishes it again. A workflow cannot call itself through its published tool, directly or
through other workflows.

---

## 7. Storage

| Table | One row per |
|---|---|
| `workflows` | definition: `definition_json`, `owner`, `enabled`, `published`, `version` |
| `workflow_runs` | run: status, trigger, `run_as`, input, output, error, `idempotency_key`, `parent_run_id`, `from_step`, `worker_id`, `heartbeat_at`, `cancel_requested`, `delivery_status`, the definition it ran |
| `workflow_run_steps` | step of a run: status, attempts, input, output, error, `idempotency_key`, `detail_json` (wake time, approval id, reuse), timings |

They are in both schema files, `db/scripts/sqlite/schema.sql` and
`db/scripts/postgresql/schema.sql` (see [Database Setup](../getting-started/Database%20Setup.md)).
SQLite creates them at start-up; on PostgreSQL an operator applies the schema file and
SAJHA only checks that they exist. Times are epoch seconds. Finished runs older than
`workflows.run_retention_days` are deleted by the scheduler (0 keeps them).

---

## 8. The API, the page and the CLI

| Route | What |
|---|---|
| `GET /workflows` | The Workflows page |
| `GET /api/workflows` | Your workflows (administrators: all) and the service status |
| `POST /api/workflows` | Create or update: a JSON definition, or `{"text": "<YAML or JSON>"}` |
| `POST /api/workflows/validate` | Validate without saving; returns the normalised definition, its YAML and the step order |
| `GET /api/workflows/{name}` | One definition (`?format=yaml`, `?reveal=1`) |
| `PUT /api/workflows/{name}`, `DELETE /api/workflows/{name}` | Update, delete (with its run history) |
| `POST /api/workflows/{name}/enable`, `POST /api/workflows/{name}/disable` | Switch triggers and the published tool on or off |
| `POST /api/workflows/{name}/runs` | Manual run: `{"input": {...}, "wait": seconds}`, `Idempotency-Key` header; 202 while running, 200 when finished |
| `GET /api/workflows/{name}/runs` | Run history (`?status=`, `?limit=`) |
| `GET /api/workflows/runs/{id}` | One run with its steps |
| `POST /api/workflows/runs/{id}/cancel`, `POST /api/workflows/runs/{id}/rerun` | Cancel; re-run (`{"from_step": "...", "latest_definition": false}`) |
| `POST /api/workflows/{name}/hooks/{trigger}` | Signed inbound webhook (no session) |

**The page** lists your workflows; edits a definition as a form of steps, as triggers and
delivery, as JSON or as YAML; draws the DAG (dashed edges are condition branches); runs it
with an input; and shows run history with a step timeline (bars on a shared time axis,
each step's status, attempts, duration, error, input and output) that refreshes while a
run is going, colouring the graph by step status.

**The CLI** (`clientsdk/sajhaclient/cli/main.py`, guide [Command Line](../clients/Command%20Line.md)):

```
sajha workflows list
sajha workflows run rates_watch --input limit=5 --wait 60
sajha workflows runs rates_watch --status failed
sajha workflows show rates_watch --yaml
sajha workflows show <run-id>
```

---

## 9. Limits

- A timed-out or cancelled call cannot be stopped mid-flight (Python threads cannot be
  killed); it is abandoned and its result ignored.
- Waits and approvals are checked on the scheduler tick, so a parked run resumes up to
  `workflows.tick_seconds` late.
- File triggers poll; they do not receive storage notifications.
- Change-bus event triggers fire on the worker that produced the event; events from other
  workers reach only their own triggers.
- A `foreach` body is one call (tool, composite or ask), not a sub-graph; a policy
  approval inside a `foreach` fails the item.
- A resumed run sees a truncated preview, not the full value, for a step output larger
  than `workflows.step_output_max_chars`.
- Cron slots missed while every worker was down are coalesced into one run, not replayed.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
