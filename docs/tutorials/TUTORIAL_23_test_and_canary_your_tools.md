# Tutorial 23: Test and Canary Your Tools

Give a tool test cases, record its HTTP traffic once and replay it offline in CI, lint the
whole catalog, probe a tool on a schedule, measure Ask SAJHA with an eval set on the mock
provider, then ship a new version of a tool to a slice of callers and watch SAJHA roll it
back on its own when it fails. The design (file formats, routing rules, what is stored where)
is in [Tool Quality](../architecture/Tool%20Quality.md).

## What you'll learn

- How a test case and its assertions are written, and how `python -m sajha.quality test` runs them
- How a cassette records a tool's HTTP calls and replays them with no network
- How CI reads the JUnit XML the harness and the linter write
- What the schema linter checks, and how to read its report
- How a health probe is scheduled, and where its results show
- How an eval set scores tool selection, answers, steps, tokens and latency per model and planner
- How a tool gets a second version, a canary, a pin, an automatic rollback and a sunset date

## Prerequisites

- A SAJHA checkout with its virtual environment ([Tutorial 1](TUTORIAL_01_getting_started.md));
  steps 1 to 5 need no server
- For steps 6 to 8: SAJHA running on `http://localhost:3002`, an admin sign-in, and an API
  key (**Admin → API keys**; `export SAJHA_KEY=sja_...`)

## Steps

### 1. Run the shipped test cases

```bash
python -m sajha.quality test
```

```
PASS  calc_compound_interest :: ten years at five percent  (35 ms) [replay]
PASS  calc_npv :: small project  (1 ms) [replay]
PASS  calc_percentage_change :: increase  (0 ms) [replay]
...
PASS  wiki_search :: marie curie  (1 ms) [replay]
```

The cases are in `config/tool_tests/`. Open `calc_percentage_change.yaml`: each case gives
`arguments` and a list of assertions under `expect` (`schema: output` validates against the
tool's `outputSchema`; a `path` with `equals` and a `tolerance`; a `type`; a `latency_ms`
budget), and the third case expects the call to fail with a message matching `old_value`.
`[replay]` means a cassette was used: the calculators make no HTTP calls, so their replay is
trivially offline, and `wiki_search` is answered from
`config/tool_tests/cassettes/wiki_search/marie_curie.json`.

### 2. Write a case and record a cassette

In `config/tool_tests/`, create `wiki_get_summary.yaml`:

```yaml
tool: wiki_get_summary
cases:
  - name: python language
    arguments: {query: "Python (programming language)"}
    expect:
      - schema: output
      - path: $.title
        regex: "Python"
      - path: $.extract
        min_length: 50
```

Record it once against Wikipedia, then replay it with the network unplugged (in spirit):

```bash
python -m sajha.quality test --tool wiki_get_summary --record
python -m sajha.quality test --tool wiki_get_summary --replay
```

The cassette is `python_language.json` in a `wiki_get_summary` folder under
`config/tool_tests/cassettes/`. Open it: the request's method and URL, the response's status, headers and body. Request headers
are never written, secret query parameters (`apikey`, `token`, ...) appear as `REDACTED`, and
`Set-Cookie` is dropped. A response body is stored as received, so read it before you commit.

`--replay` fails a case that makes a request the cassette does not hold, rather than going to
the network: change the `query` in the case and run `--replay` again to see the miss. (Had you
written `title:` instead of `query:`, the case would fail on the tool's input schema, and
`python -m sajha.quality lint` would report the case's arguments as an error before any run.)

### 3. Put it in CI

```bash
python -m sajha.quality test --replay --junit build/tool-tests.xml
python -m sajha.quality lint --junit build/tool-lint.xml
```

Both exit 1 on a failure, and the XML files are what Jenkins, GitLab and GitHub test
reporters read (one test suite per tool, one test case per case).

### 4. Lint the catalog

```bash
python -m sajha.quality lint --info | tail -5
python -m sajha.quality lint --tool 'calc_*'
```

Every tool's name is checked against MCP's tool-name rule, its schemas against JSON Schema
2020-12, every `examples` entry against its schema, and its annotations for sense. A tool
called `..._delete` without `destructiveHint: true` is a warning; a missing property
description is a warning; an invalid schema is an error. Add `--strict` to fail on warnings.

### 5. Measure Ask SAJHA with an eval set

```bash
python -m sajha.quality eval calculators --no-save --json /tmp/react.json
python -m sajha.quality eval calculators --no-save --planner plan_execute --json /tmp/plan.json
python -m sajha.quality compare /tmp/react.json /tmp/plan.json
```

`config/evals/calculators.yaml` lists three questions, the tool each should use, a check on
the answer (`number: 25` with a tolerance, a regex), and limits on steps, tokens, cost and
latency. Both runs use the mock provider, so they run offline and cost nothing; `compare`
prints each metric for both runs with the change, and the questions that regressed or
improved. Without `--no-save` a run is stored, and its id works in `compare` too.

### 6. Probe a tool on a schedule

`calc_percentage_change.yaml` ends with a `probe:` block (`case: increase`, `every: 300`), and
`wiki_search.yaml` has one with `cron: "*/30 * * * *"`. Probes are off until you turn them on;
restart SAJHA with:

```bash
SAJHA_QUALITY_PROBES_ENABLED=true python run_server.py
```

Open **Admin → Operations → Tool health** (`/admin/tool-health`). The Probes table shows each
probe's schedule and next slot; press **Run now** on `calc_percentage_change` and its result
and a green square appear. The same results are on `/metrics` as `sajha_tool_probe_up`,
`sajha_tool_probe_runs_total` and `sajha_tool_probe_duration_seconds`. With several workers on
a shared state store, only one worker runs each slot.

On the same page, **Run tests** runs the harness in the server (replaying cassettes) and
saves the run; **Lint every tool** shows the linter's findings.

### 7. Ship a second version behind a canary

Activate the example versions file:

```bash
cp config/tool_versions/calc_percentage_change.yaml.example config/tool_versions/calc_percentage_change.yaml
```

It declares version `5.0.0` of `calc_percentage_change` as an override of the registered
config (version `4.5.0`): another class, `sajha.examples.quality.pct_change_v2.PercentChangeV2`,
that rounds to two places and adds `direction`. Routing sends 10% of callers to it, and
everyone with the `beta` role.

Open **Admin → Operations → Tool versions** (`/admin/tool-versions`). Set the canary to
`5.0.0` at `100` percent and call the tool:

```bash
curl -s -X POST http://localhost:3002/api/tools/execute -H "X-API-Key: $SAJHA_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"tool": "calc_percentage_change", "arguments": {"old_value": 80, "new_value": 90}}'
```

```json
{"success": true, "result": {"old_value": 80, "new_value": 90, "percentage_change": 12.5, "direction": "up"},
 "_meta": {"io.sajha/tool-version": {"version": "5.0.0", "route": "canary"}}}
```

An MCP client sees the same: `tools/list` still lists `calc_percentage_change` once, and the
`tools/call` result carries `_meta["io.sajha/tool-version"]`. Set the canary back to `0` and
call again: `4.5.0` answers, and because the example gives it a sunset date the result also
carries `_meta["io.sajha/deprecation"]` with the date and the successor. After that date
`4.5.0` is never routed to; a `deprecation:` block for the whole tool would instead hide it
from `tools/list` after its date.

To pin a client to the old version whatever the canary does, add its API key's name under
`routing.api_keys` in the editor on the page (**Validate and save**).

### 8. Watch a bad version roll back

Edit the versions file on the page so `5.0.0` points at a class that always fails, with a
short rollback window:

```yaml
versions:
  "5.0.0":
    overrides:
      implementation: sajha.examples.quality.pct_change_v2.FlakyPercentChange
rollback:
  max_error_rate: 0.2
  min_calls: 5
  window_seconds: 300
```

Call the tool six times (the `curl` above). The first five fail; then the page shows
`5.0.0` as **rolled back** with the reason (`error rate 5/5 = 100% > 20%`), the server log
has a warning, the audit has a `quality.version.rollback` record, and
`sajha_tool_version_rollbacks_total` counts it. The sixth call, and every call on every
worker after it, runs `4.5.0` (`"route": "stable"`). Fix the version, then **Clear rollback**
to let the canary resume; **Promote** makes a version the stable one.

Finally, delete `calc_percentage_change.yaml` from `config/tool_versions/` to return to one version.

## What happened

- Test cases describe calls and what their results must be; the harness runs the tool directly,
  inside a cassette that records or replays its HTTP, and writes text, JSON and JUnit XML.
- The linter reads every tool's definition and runs nothing.
- Probes run one case on a schedule against the live service; the state store keeps their
  results and makes each slot fire once.
- An eval set asks Ask SAJHA golden questions and scores each answer; two runs compare metric
  by metric.
- A versions file puts several implementations behind one tool name; routing happens where
  every call passes (`execute_with_tracking`), the version is reported in `_meta`, and the
  rollback is shared by every worker through the state store.

## Next steps

- [Tool Quality](../architecture/Tool%20Quality.md): every assertion, the cassette format,
  lint rules, probe scheduling, eval scoring, routing precedence and rollback rules
- [Observability](../architecture/Observability.md): alert on `sajha_tool_probe_up == 0` or on
  a rollback
- [Configuration Reference](../getting-started/Configuration%20Reference.md#quality): the `quality.*` keys
