# SAJHA MCP Server — Tool Generation ("Describe a tool")

Someone with MCP Studio access (an administrator, or a role with the `studio:describe` or
`studio:*` permission) describes a tool in plain words ("get the 10-year US treasury yield and
its change over 30 days", "wrap this REST endpoint …", "query table orders by region",
"classify a support message into billing, technical or other").
SAJHA asks a model to design it, checks the design as untrusted input, renders the exact
files a deploy would write, runs the design's test cases (Python code in the sandbox, REST
against canned replies), and deploys only when that person approves that exact
version and the policy engine agrees.

This document owns the topic. The page is **Studio → Describe a tool**
(`/studio/describe`, permission `studio:describe`; admins always); the command is `sajha studio describe` (see
[Command Line](../clients/Command%20Line.md#3-commands)); the walkthrough is
[Tutorial 24](../tutorials/TUTORIAL_24_describe_a_tool.md); the keys are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#studio-describe-a-tool);
the terms are in the [Glossary](../../GLOSSARY.md). The code is `sajha/studio/describe.py`
(the service), `sajha/routes/describe_routes.py` (the page and endpoints) and
`sajha/ai/llm/mock_toolsmith.py` (the offline model).

---

## 1. Shape

```
 description ──► screen (injection markers removed, length cap) ──► prompt: rules + context + DATA block
                                                                      │  gateway alias "toolsmith"
                                                                      ▼  (structured output)
 proposal  {kind, name, description, category, input_schema, output_schema, implementation, tests, notes}
           kind: python | rest | dbquery | composite | openapi | llm
      │  validate: every field is untrusted (names, URLs, SQL, headers, sandbox requests, code)
      ▼
 draft     state store, bound to proposal hash · files rendered by Studio's own generators · policy preview
      │  the administrator reads the files, may edit the proposal (new hash), runs the tests
      ▼
 tests     python: sandbox (offline cases get no network) · rest: fixtures (live on request)
           dbquery: the generated tool on the listed database · llm: the mock model
           composite / openapi: live only
      │  approve: true + the reviewed hash + tests run on that hash + policy allows studio.deploy
      ▼
 deploy    module + config/tools/<name>.json, hot-loaded (python, rest, dbquery)
           config/tools/<name>.json only, hot-loaded (llm)
           a composite record in the database (composite) · hand-off to Import an API (openapi)
```

## 2. The model

The service calls the [intelligence layer](Intelligence%20Layer.md) gateway with the alias
named by `studio.describe.model` (default `toolsmith`), a system prompt that states the
proposal format and the rules, and `response_schema` set to the proposal schema
(`PROPOSAL_SCHEMA` in `sajha/studio/describe.py`), so a provider with structured output
returns JSON. A reply in a code fence, or with text around the object, is still parsed.

`config/application.yml` maps `toolsmith` to `mock/mock-toolsmith`. When the alias is not
configured at all, the service uses `mock/mock-toolsmith` directly, so the feature works
with no keys. Point the alias at a real model to get real designs, keeping the mock as the
fallback:

```bash
SAJHA_AI_ALIASES_TOOLSMITH=anthropic,mock/mock-toolsmith
```

The gateway applies its usual role policy, budgets, retries, fallback, cache and tracing to
the call; nothing about generation bypasses it.

**mock-toolsmith** (`sajha/ai/llm/mock_toolsmith.py`) is deterministic and reads only the
request, like every mock model. It recognises: a URL that looks like an OpenAPI or Swagger
spec (kind `openapi`); any other URL (kind `rest`, path parameters from `{braces}`, the
method from an upper-case `POST`/`PUT`/`PATCH`/`DELETE` in the text); a table the context
lists, or "table X" (kind `dbquery`, a `WHERE col = {{col}}` per "by <column>"); two or more
existing tools named, or "combine"/"together"/"snapshot" with matching tools (kind
`composite`, sibling); a treasury or FRED series with "change over N days", and summary
statistics of a list of numbers (kind `python`); "summarise", "classify … into a, b or c",
"extract the x, y and z from", "sentiment", or "answer questions" / "assistant" (kind `llm`:
mode `complete`, `classify`, `extract`, or `answer` with `tools.allow` from tools or tool
prefixes the description names, else `grounded` over `sajha_docs`). Anything else gets a Python skeleton that
echoes its input, with a note saying so. It exists for demos, tests and air-gapped
installs; it does not understand language.

## 3. What the model is told, and what it is not trusted with

The description is untrusted. Before the model sees it, it is cut to
`studio.describe.max_description_chars`, control characters are removed, and the same
injection markers federation screens for (`sajha/federation/security.py`) are replaced
with `[removed]`; the page and the result say when that happened. It is then placed
between `<<<DESCRIPTION <nonce>` and `DESCRIPTION <nonce>>>>` markers with a random nonce,
and the system prompt says that block is data, never instructions.

The context block gives the model what it needs and no more: existing tools that share
words with the description (name, screened description, input names; at most
`studio.describe.context_tools`), and the DuckDB analytics database's tables, columns and a
few example values of low-cardinality text columns. No secrets, configuration or files.

The model's reply is untrusted too. `validate()` normalises it and lists errors (which
block testing and deploying) and warnings (shown for review):

| Field | Checks |
|---|---|
| `kind` | one of `python`, `rest`, `dbquery`, `composite`, `openapi`, `llm` |
| `name` | 3-64 lowercase letters, digits, underscores, never `__` (reserved for namespaced tools, [Federation](Federation.md#names)); an invalid one is replaced by a slug; a taken one gets `_2`, `_3`, … |
| `description`, `category`, notes | one line, no quotes or backslashes (they end up inside generated Python), capped |
| python `code` | at most 20,000 characters; compiles; exactly one `@sajhamcptool` function; imports of `os`, `subprocess`, `socket` and similar, and calls to `eval`, `exec`, `open` and similar, are flagged |
| python `sandbox` | `network` `none` or `allowlist` with `host[:port]` entries; hosts the description does not mention are flagged; `secrets`, `env` and `backend` are removed (a generated tool cannot ask for them); the block must pass `policy_from_config`, so `sandbox.max` caps it |
| rest `endpoint` | an http(s) URL with no spaces, quotes or backslashes, accepted by the API Import SSRF guard's host checks (`api_import.allowed_hosts`); a host the description does not mention is flagged |
| rest headers | plain names and values only; credential headers (`Authorization`, `Cookie`, `X-API-Key`, …) are removed: credentials are never generated |
| dbquery | `duckdb` or `sqlite`; the connection string must be one the context listed; one statement, `SELECT` or `WITH`, no writes, DDL, `ATTACH`, `COPY`, `PRAGMA` or file-reading functions (`read_csv`, `read_parquet`, `glob`, …); only listed tables; every `{{placeholder}}` has a parameter |
| composite | the master tool and every step tool are loaded tools, other than the new one; plain output keys; at most 8 steps |
| openapi | the spec URL passes the same checks as a REST endpoint; the prefix is 2-31 lowercase characters |
| llm | `implementation` is the tool's `llm` block, and the block with the proposal's schemas is checked by the LLM-tool loader itself (`parse_llm_block` and the catalog rules: `tools.allow` must match a tool, a narrate source must exist); each problem is an error prefixed `llm:`. `tools.allow: ["*"]` is flagged |
| tests | at most `studio.describe.max_tests` cases; arguments are JSON objects under 4,000 characters; a REST case without a fixture, and every composite and openapi case, is live; an llm case is never live |

## 4. The draft and its hash

A proposal that has been checked is stored as a draft in the state store (key prefix
`studio.describe.draft:`, kept for `studio.describe.draft_ttl_seconds`), so it survives a
page reload and any worker can serve it. The draft holds the screened description, the
model that answered, the checked proposal, its errors and warnings, the files a deploy
would write (each with a unified diff against nothing: every file is new), the policy
preview, and the last test run.

The **proposal hash** is the SHA-256 of the checked proposal's canonical JSON. Editing the
proposal (the page's edit box, or `POST /admin/studio/describe/revise`) checks it again and
gives it a new hash, which clears the test results. A deploy names the hash the
reviewer saw; if the draft has moved on, the deploy is refused.

The files are produced by Studio's own generators, so a deploy writes exactly what the
creators would: `ToolCodeGenerator` for Python (`sajha/tools/impl/studio_<name>.py`),
`RESTToolGenerator` (`rest_<name>.py`), `DBQueryToolGenerator` (`dbquery_<name>.py`), each
with `config/tools/<name>.json`; an LLM tool is the config file alone, with
`implementation` `sajha.ai.llm_tools.LLMTool` and the proposal's `llm` block, as the
[LLM tool creator](../studio/MCP%20Studio%20LLM%20Tool%20Creator%20Guide.md) writes it. The
config's `metadata` records `generated_from: description`, the draft id and, on deploy, the
deploying user (`created_by`). A Python tool's config always carries
`"sandbox": {"enabled": true, ...}`, so it is sandboxed even when
`sandbox.enforce_for_generated_tools` is off; its `inputSchema` comes from the function's
signature and its `outputSchema` from the proposal when that names properties.

## 5. Tests

`POST /admin/studio/describe/test` runs the draft's cases and records the result against
the current hash. A case has `arguments`, an `expect` (`ok`, `keys`, `equals`,
`error_contains`) and is either offline or live; live cases run only when asked ("include
live tests" on the page, `--live` in the CLI).

| Kind | How a case runs |
|---|---|
| python | the generated module in the [sandbox](Sandbox.md) (`op: python_tool`), never in the server process. An offline case runs with `network: none` whatever the tool's policy allows; a live case gets the tool's policy. A sandbox that is unavailable skips the case. The result is also checked against the output schema. |
| rest | the generated tool with `requests` replaced by the case's fixture (status, JSON or text), so the URL, headers and parsing are exercised without a call. A live case calls the endpoint after the SSRF guard resolves it, and only for `GET`. |
| dbquery | the generated tool against the listed database (the query is read-only by construction, §3) |
| composite | live: the composite built from the definition runs its tools |
| openapi | live: the spec is fetched and planned by API Import; it passes when it lists operations |
| llm | offline: the tool runs once on `ai.planners.dry_run_model` (the mock model), remembering and auditing nothing; tools it may call are offered and only read-only ones run, as in the planner dry run |

A REST or DB query module is SAJHA's own template filled with checked values, so it runs
in-process for its tests; only Python code tools contain model-written code, and that runs
only in the sandbox.

The generated config of a Python, REST, DB query or LLM tool carries the proposal's
non-fixture cases as its `tests` list, in the format of the tool test harness
([Tool Quality](Tool%20Quality.md)): `keys` become `exists` assertions, `equals` become
`equals`, an expected error becomes `error`, and live cases are tagged `live`. You review
them with the files, and `python -m sajha.quality test` keeps running them after the deploy.
(The import is still guarded in `sajha/studio/describe.py`, so a build without
`sajha/quality/` keeps the cases with the draft.)

## 6. Deploy

`POST /admin/studio/describe/deploy` with `draft_id`, `hash`, `approve: true` and optionally
`accept_failures`. It is refused unless every one of these holds, checked on the server:

1. the caller has Studio access (every route needs the admin role or `studio:describe`; a
   non-admin works only on drafts they created, any other draft id answers 404), has the
   permission of the kind deployed (`studio:python`, `studio:rest`, `studio:dbquery`,
   `studio:composite` or `studio:llm`, or `studio:*`), and sent `approve: true`;
2. the draft has no errors and is not deployed already; an `openapi` proposal is never
   deployed here: the page links to Import an API with the URL and prefix filled in, where
   the operations are chosen;
3. `hash` is the draft's current hash;
4. the tests ran on that hash, none failed and at least one passed, or `accept_failures`
   is set (the audit record says so);
5. the name is still free;
6. the [policy engine](Policy%20and%20Audit.md) allows the pseudo tool call
   `studio.deploy` with arguments `{"tool": <name>, "kind": <kind>}` from source `rest`. A
   `deny` refuses; `require_approval` creates an approval request that an
   administrator other than the requester decides on the Approvals page (self-approval follows
   `policy.approvals.allow_self_approval`); deploying again then consumes the grant.

Developers may deploy Describe a tool proposals: the deploy is gated by the same checks for
them as for an administrator, and the policy engine is where an operator narrows it, for
example a `studio.deploy` rule matching the `developer` role with `require_approval`, so an
administrator approves every tool a developer generates. A generated Python tool always
carries `"sandbox": {"enabled": true}`, so it runs in the sandbox whatever
`sandbox.enforce_for_generated_tools` says.

Files are written module first, then the config through the storage backend, then the tool
is hot-loaded; if it does not load, the files are removed and the error returned. An LLM tool
has no module: its config is written and loaded the same way. A
composite is created in the database and the composite engine reloads. Generation, test
runs and deploys are audited (`studio.describe.generate`, `.test`, `.deploy`). A deployed
Python, REST, DB query or LLM tool is an ordinary Studio tool (Studio's delete removes it,
and the LLM tool creator edits an LLM tool); a
composite is managed in the Composite builder.

The page also shows, before any deploy, what the policy engine would decide for the
deploy and for calls to the new tool.

## 7. Endpoints

| Method and path | What it does |
|---|---|
| `GET /studio/describe` | the page |
| `POST /admin/studio/describe/propose` | `{description, kind?}` → a draft (proposal, errors, warnings, files, policy) |
| `POST /admin/studio/describe/revise` | `{draft_id, proposal}` → the draft, checked again, new hash |
| `POST /admin/studio/describe/test` | `{draft_id, live?}` → the draft with `tests_run` |
| `POST /admin/studio/describe/deploy` | `{draft_id, hash, approve, accept_failures?}` → the draft with `deployed` |
| `GET /api/studio/describe/drafts/{id}` | a draft |

Refusals return `success: false`, an `error`, and a status: 400 bad input, 403 turned off
or denied by policy, 404 unknown or expired draft, 409 a precondition in §6 (with
`approval_id` when a second approval is pending), 503 no model available.

## 8. Limits

* The mock designs a few shapes; real designs need a real model behind `toolsmith`.
* A generated database query may use only the DuckDB analytics database SAJHA lists; other
  databases, and credentials of any kind, are set up in the DB Query and REST creators.
* A Python tool's network access is what its sandbox policy allows; host names in an
  allowlist are enforced by a library-level check in the runner, ports by the kernel where
  the backend can (see [Sandbox](Sandbox.md#network-allowlist)).
* Tests show behaviour on their cases, not correctness; the review of the files is the
  control, which is why a deploy needs it.
