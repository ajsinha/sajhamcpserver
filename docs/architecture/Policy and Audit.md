# SAJHA MCP Server — Policy and Audit

Two governance layers that sit on every tool call:

* the **policy engine** (`sajha/policy/`): declarative rules, kept in YAML or JSON files,
  evaluated before every tool call on every path. A rule can allow, deny (with a reason),
  require human approval, constrain arguments, rate-limit or meter a quota, redact personal
  data from the result, and screen the result for prompt injection;
* the **tamper-evident audit** (`sajha/audit/`): every audit record is hash-chained to the
  one before it, the chain is periodically anchored with a signature from the server's key,
  `python -m sajha.audit verify` (and the Audit page) prove it has not been edited, and
  records stream to a SIEM over syslog, HTTP (Splunk HEC, Datadog, generic) or a rotated
  JSONL file, as JSON, CEF or OCSF-style JSON.

This document owns both topics: the design, what was built, how to operate it and its
limits. Every key and default is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#policy-and-audit);
the walkthrough is [Tutorial 20](../tutorials/TUTORIAL_20_policies_approvals_and_audit.md);
terms are in the [Glossary](../../GLOSSARY.md).

**Nothing changes by default.** The shipped policy file has no rules, the shipped example
policies are disabled, `policy.default_effect` is `allow`, and no SIEM sink is configured. A
fresh SAJHA behaves exactly as before; the audit records it already wrote are now also
hash-chained.

---

## 1. Shape

```
 MCP (2026-07-28, 2025-11-25, stdio, WebSocket) · REST · playground · A2A · Ask SAJHA ·
 async tasks · composite steps · federated tools
                         │
                         ▼
 BaseMCPTool.execute_with_tracking            (sajha/tools/base_mcp_tool.py: the choke point)
   │ 1. policy.enforce(tool, arguments)        rules → deny / constraints / approval / limits
   │ 2. _execute_tracked                       enabled, validation, cache, breaker, execute
   │ 3. decision.apply_output(result)          redaction · injection screening
   ▼
 result to the caller
                         │ non-allow decisions, approvals, admin changes, sign-ins ...
                         ▼
 sajha.audit.record(event)  →  ChainWriter (one chain per process)  →  audit_chain / audit_anchors
                                         └──────────────────────────→  SIEM sinks (syslog · HTTP · file)
```

| Code | What |
|---|---|
| `sajha/policy/model.py` | the rule language: parse and validate policy files (`Policy`, `Rule`, `Match`, conditions) |
| `sajha/policy/loader.py` | loads `config/policies/*` through the storage backend; hot reload |
| `sajha/policy/engine.py` | `PolicyEngine.evaluate` (pure) and `enforce` (approvals, limits, audit, metrics) |
| `sajha/policy/context.py` | the call source (`mcp`, `rest`, ...) and the caller-confirmation flag, as context variables |
| `sajha/policy/redact.py` | PII patterns: emails, phone numbers, card numbers (Luhn), national IDs, custom regexes |
| `sajha/policy/approvals.py` | pending approvals in the state store, grants, notification |
| `sajha/policy/errors.py` | `PolicyDenied`, `ApprovalRequired`, `RateLimited` |
| `sajha/audit/chain.py` | canonical JSON, the hash chain, the per-process `ChainWriter`, anchors, the tables |
| `sajha/audit/verify.py` | chain verification (used by the CLI and the Audit page) |
| `sajha/audit/formats.py` | JSON, CEF and OCSF-style renderings of a record |
| `sajha/audit/sinks.py` | the SIEM exporters: syslog (RFC 5424 over TCP/TLS), HTTP, JSONL file |
| `sajha/audit/__main__.py` | `python -m sajha.audit verify|chains|show` |
| `sajha/routes/policy_routes.py` | the Policies, Approvals and Audit admin pages and their JSON API |
| `config/policies/` | the policy files: `00-default.yaml` (no rules) and disabled examples |
| `tests/test_policy.py`, `tests/test_audit_chain.py` | every behaviour below |

---

## 2. Where the engine runs

Every way of running a tool ends in `BaseMCPTool.execute_with_tracking`: the MCP handlers of
both eras (and so stdio and WebSocket, which reuse them), `POST /api/tools/execute` (the
console, the playground bridge and the REST client), A2A `tasks/send`, Ask SAJHA's tool loop,
async tasks, and federated tools (which are registry tools). The engine is called there,
before the enabled check, validation, the cache and the circuit breaker, so a denied call
costs nothing and a cache hit is still governed. Composite tools are governed twice, by
design: the composite as a whole, then each step (`sajha/core/composition.py::execute_step`).

The engine needs three facts the tool does not have:

| Fact | Where it comes from |
|---|---|
| the caller (user, API key, roles, auth type) | `sajha.observability.caller.current()`, set by each entry point (A2A and async tasks now set it too) |
| the source | `sajha.policy.context`: `mcp`, `stdio`, `websocket`, `rest`, `playground`, `a2a`, `ask`, `async`, `workflow` (a workflow step, run as the workflow owner; docs/architecture/Workflows.md), else `other`. The first entry point to set it wins, so a stdio call stays `stdio` when it reaches the MCP handler; Ask SAJHA and workflows override it, because its tool calls are chosen by a model |
| whether the caller confirmed | the MRTR answer on the 2026-07-28 path, or the Ask SAJHA confirm button (section 5) |

---

## 3. The rule language

A policy is one YAML (`.yaml`, `.yml`) or JSON file under `policy.dir` (default
`config/policies`), read through the storage backend (local, S3, Azure Blob, GCS), so a
policy can live in a bucket like every other config. Files are loaded in name order, rules in
file order.

```yaml
name: finance-guardrails          # default: the file name
description: Payments need approval; no PII leaves the server.
enabled: true                     # false: listed and testable, not enforced
rules:
  - id: approve-large-payments
    match:
      tools: ["payments_*"]
      arguments: {amount: {gt: 10000}}
    effect: require_approval
    reason: Payments over 10,000 need a second pair of eyes.
    approval: {approver: admin}
  - id: payment-limits
    match: {tools: ["payments_*"]}
    constraints:
      currency: {enum: [USD, EUR, GBP]}
      amount: {min: 0, max: 50000}
      reference: {pattern: "^[A-Z0-9-]{4,32}$"}
    rate_limit: {limit: 10, window: 1m, per: [user]}
    quota: {limit: 200, period: day, per: [user]}
  - id: no-pii-out
    match: {groups: [crm, hr]}
    redact: {emails: true, phones: true, cards: true, national_ids: true, mode: mask}
  - id: screen-federated
    match: {tools: ["*__*"]}
    screen_output: strip
```

### 3.1 Match

Every key is optional; all given keys must hold (AND); list values are alternatives (OR).

| Key | Matches when |
|---|---|
| `tools` / `exclude_tools` | the tool name matches one of the globs (`fnmatch`, case-sensitive) / none of them |
| `groups` | the tool group (GLOSSARY "Tool group": the text before the first `_`) is listed |
| `annotations` | each listed annotation has that value in the tool's config (`{destructiveHint: true}`) |
| `callers.anonymous` | `true`: only unauthenticated calls; `false`: only authenticated ones |
| `callers.users` / `callers.api_keys` | the user id / API key name matches a glob |
| `callers.roles` | the caller has one of the roles |
| `callers.auth_types` | `session`, `apikey`, `jwt`, `oauth`, ... (the AuthContext's `auth_type`) |
| `sources` | the call came in through one of the sources in section 2 |
| `time` | `{days: [mon, tue, ...], hours: "09:00-17:00", timezone: Europe/London}`; hours may wrap midnight |
| `arguments` | each named argument (dotted path for nested ones) satisfies its condition (3.3) |

A rule without `match` matches every call.

### 3.2 Effects and obligations

`effect` is the access decision: `allow`, `deny` or `require_approval`. A rule may leave it
out and carry only obligations. The effects of all matching rules in all enabled policies
combine **deny-overrides**: any `deny` denies (the first one's `reason` is reported); else any
`require_approval` requires approval; else the call is allowed. With
`policy.default_effect: deny`, a call that no rule explicitly `allow`s is denied: an
allowlist mode for locked-down deployments.

Obligations accumulate from every matching rule and are applied in this order:

1. `constraints` (argument constraints, 3.3): a violation denies, naming the argument;
2. approval (section 5);
3. `rate_limit` (`{limit, window, per}`, a sliding window) and `quota` (`{limit, period: hour|day|week|month, per}`,
   a UTC calendar period). `per` lists the dimensions the counter is kept for: `tool`, `user`,
   `api_key`, `caller` (the API key when there is one, else the user), or `global`;
   default `[tool, caller]`. Counters live in the state store, so with `state.backend: redis`
   or `database` every worker shares them; with `memory` each worker counts alone;
4. the tool runs;
5. `redact` and `screen_output` on the result (section 4).

### 3.3 Conditions

The same grammar serves `match.arguments` (does this rule apply?) and `constraints` (is this
call allowed?):

| Key | Holds when the value ... |
|---|---|
| `required: true` | is present |
| `eq`, `ne` | equals / does not equal |
| `enum` (alias `in`), `not_in` | is / is not one of the list |
| `min`, `max`, `gt`, `lt` | is a number within the bound |
| `min_length`, `max_length` | is a string, list or object of that size |
| `pattern`, `not_pattern` | is a string that matches / does not match the regex (`re.search`) |
| `type` | has the JSON type (`string`, `number`, `integer`, `boolean`, `array`, `object`, `null`) |

In `constraints`, an absent argument satisfies every condition except `required`, so a
constraint never invents a requirement the tool's schema does not have. In
`match.arguments`, an absent argument fails every condition except `ne` and `not_in`.

### 3.4 Validation and hot reload

A file that does not parse, or a rule with an unknown key, effect, condition or source, or a
regex that does not compile, is reported (log, Policies page) and that **whole file** is not
enforced; the other files still are. A broken file never widens access by accident: with
`policy.on_error: deny` (default `ignore`), a broken file denies every call until fixed.
The loader rechecks the directory at most every `policy.reload_seconds` (default 5) on the
next call and reloads when a file was added, removed or changed; the Policies page has a
"Reload now" button.

---

## 4. Output governance

**Redaction** walks the result (dicts, lists, strings; keys are never touched; base64
`data`/`blob` fields of image, audio and resource blocks are skipped) and replaces matches:

| Kind | Pattern |
|---|---|
| `emails` | RFC 5322-ish `local@domain.tld` |
| `phones` | international (`+44 20 7946 0958`) and North American (`(415) 555-0132`) forms, 8 to 15 digits |
| `cards` | 13 to 19 digits, optionally grouped, **and** a valid Luhn check digit, so order numbers survive |
| `national_ids` | `us_ssn`, `uk_nino`, `in_aadhaar`, `in_pan`, `ca_sin` (Luhn); `true` means all |
| `custom` | `[{name, pattern, replacement?}]` |

`mode: redact` (default) replaces with `[REDACTED:<kind>]`; `mode: mask` keeps the last four
characters (`************4242`, `j***@example.com`). Each redaction is counted
(`sajha_policy_redactions_total{kind}`) and the call is audited once with the counts, never
the values.

**Injection screening** runs the result's strings through the same markers federation uses
for upstream descriptions (`sajha/federation/security.py::INJECTION_MARKERS`):
`flag` audits and counts but returns the result unchanged, `strip` replaces each marker with
`[removed]`, `block` withholds the result and returns a policy error. The strictest mode of
the matching rules applies.

---

## 5. Approvals

`effect: require_approval` with `approval: {approver: caller | admin, ttl: 1h}`.

**`approver: caller`, interactive clients.** The person at the client confirms the call:

* MCP 2026-07-28, when the client declared form elicitation: the call returns an
  `InputRequiredResult` (MRTR) with a yes/no form (the same mechanism as
  `mcp.confirm_destructive_tools`); the retry with `confirm: true` runs, a decline returns
  a tool error;
* Ask SAJHA: the step shows as "needs confirmation" with the policy's reason, and the
  Confirm button re-runs the question with the call confirmed, as for destructive tools.

Any other client (2025-11-25, REST, A2A, async, a 2026-07-28 client without elicitation)
falls back to `admin`.

**`approver: admin`.** The call is refused with an `ApprovalRequired` error that carries an
approval id, and a pending approval is created in the state store
(`policy:approval:<id>`, kept `policy.approvals.ttl_seconds`, default one day). Repeating
the same call (same caller, tool and arguments) while it is pending returns the same id
rather than a new one. An administrator approves or denies it on the **Approvals** page
(`/admin/approvals`) or with `POST /api/policy/approvals/{id}/approve` (or `/deny`). Once approved,
the same caller making the same call (tool + canonical arguments, the "fingerprint") within
`policy.approvals.grant_ttl_seconds` (default one hour) runs it, once: the grant is consumed
atomically, so two workers cannot both use it. An administrator cannot approve their own
request unless `policy.approvals.allow_self_approval` is true.

When `policy.approvals.notify_url` is set, each new approval is posted there (generic JSON,
or `{"text": ...}` for a Slack incoming webhook with `notify_format: slack`) through the
alert webhook guard: the URL must be in `observability.alerts_webhook.allowed_urls`, it is
resolved once, refused if it resolves to a private address, and connected by pinned IP with
no redirects.

How each path shows a policy outcome:

| Path | deny / constraint | approval required | rate limit or quota |
|---|---|---|---|
| MCP (both eras, stdio, WebSocket) | tool error (`isError: true`) with the reason | tool error naming the approval id (or MRTR, above) | tool error |
| `POST /api/tools/execute` | 403 `{"error", "policy": {...}}` | 202 `{"success": false, "approval_id", ...}` | 429 with `Retry-After` |
| Ask SAJHA | step `refused` with the reason | `approver: caller`: step `needs_confirmation` (Confirm button); `admin`: step `refused` naming the approval id | step `refused` |
| A2A, async tasks | failed task with the reason | failed task naming the approval id | failed task |

---

## 6. Decisions are logged and counted

| Metric | Labels |
|---|---|
| `sajha_policy_decisions_total` | `decision` (`allow`, `deny`, `approval_required`, `approved`, `rate_limited`, `constraint`, `blocked`), `rule` |
| `sajha_policy_redactions_total` | `kind` |
| `sajha_policy_output_flags_total` | `mode` |
| `sajha_audit_records_total` | — |
| `sajha_audit_export_total` | `sink`, `outcome` (`sent`, `failed`, `dropped`) |

Every non-allow decision, every redaction or screening action and every approval state
change is an audit record (`policy.deny`, `policy.approval_required`, `policy.approved`,
`policy.rate_limited`, `policy.redacted`, `policy.output_flagged`, `approval.approve`,
`approval.deny`). Plain allows are counted but not audited unless `policy.audit_allow` is
true: a busy server would otherwise write one row per call.

---

## 7. The tamper-evident audit

### 7.1 Records and the hash chain

`sajha.audit.record(event, actor=..., resource=..., outcome=..., details=...)` is the one
way to write an audit record. `AuditLogger.log` (sign-ins, users, API keys, config changes,
federation, connected accounts, the shell) calls it, and still writes its `audit_log` row,
which the existing audit API reads.

A record is a JSON object:

```json
{"v": 1, "chain": "web-1-4711-1a2b3c", "seq": 42, "ts": "2026-10-06T09:15:02.123456Z",
 "prev": "<sha256 of record 41>", "event": "policy.deny",
 "actor": {"user": "alice", "roles": ["user"], "auth": "session"},
 "resource": {"type": "tool", "id": "payments_send"}, "outcome": "deny",
 "details": {"rule": "finance-guardrails/approve-large-payments", "source": "rest"}}
```

Its **canonical form** is `json.dumps(record, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` in UTF-8, and its hash is `sha256(canonical form)`. Because `prev` is
inside the hashed record, each hash commits to every record before it. Record 0 of a chain
is `chain.open` with `prev` = 64 zeros and the host, process id and SAJHA version; a clean
shutdown appends `chain.close`.

Rows go to `audit_chain` (`chain_id`, `seq`, `ts`, `event`, `actor`, `resource`,
`outcome`, `record_json`, `prev_hash`, `hash`; unique `(chain_id, seq)`). `record_json` is
the canonical text exactly as hashed; the other columns are copies for querying, and
verification checks they agree with it.

### 7.2 Several workers: one chain per process

A single global chain would need every worker to read the previous hash and insert the next
record under one database lock (`SELECT ... FOR UPDATE` on PostgreSQL, a write lock on the
whole SQLite file), on every audit event, in every worker. Instead **each process is the
only writer of its own chain** (`chain_id` = host, pid and start time): appends are ordered
by an in-process lock, with no cross-process coordination, and they cannot interleave.
Verification checks each chain independently; the Audit page and `python -m sajha.audit
show` merge them by timestamp for reading. A record that fails to insert (database
unavailable) is kept in memory and retried on the next append, so a transient failure does
not leave a gap; records still unwritten when the process dies are lost, and verification
reports the chain as not closed.

### 7.3 Anchors

Every `audit.chain.anchor_every` records (default 100), every
`audit.chain.anchor_interval_seconds` (default 300) when there is something new, and at
shutdown, the writer signs a checkpoint of its chain:

```json
{"chain": "...", "seq": 141, "hash": "<hash of record 141>", "ts": "...", "kid": "<key id>"}
```

with the server's RS256 key (the built-in OAuth signing key, `sajha/auth/oauth/keys.py`;
its public half is at `/oauth/jwks`, so anyone holding the JWKS can verify an anchor
without SAJHA). The anchor is stored in `audit_anchors` and also appended to the chain as an
`audit.anchor` record, so each protects the other, and it is exported to the SIEM sinks
like every record, which puts a signed copy of the chain head outside the database.

### 7.4 Verification

`python -m sajha.audit verify` (exit 0 intact, 1 tampered or broken, 2 cannot check), the
Audit page's Verify button and `GET /api/audit/verify` all run `sajha/audit/verify.py`. For
each chain it checks:

| Check | Detects |
|---|---|
| `sha256(record_json) == hash` | an edited record |
| `record.prev == previous record's hash` and `prev_hash` column agrees | a record replaced with a re-hashed forgery, re-ordering |
| `seq` contiguous from 0, record 0 is `chain.open` | deleted or inserted records |
| the copied columns equal the canonical record | edited query columns |
| every anchor's signature verifies with the server key | a forged anchor |
| every anchor's hash equals the hash of the record at its `seq` | a chain rewritten from some record onwards (re-hashing cannot reproduce the signed head) |
| an anchor points past the last record | truncation |

It reports, per chain, `ok` or the first problem (with the `seq`), plus warnings: records
after the last anchor (`unanchored`), a chain with no `chain.close` (`open`: a running or
crashed process), and anchors signed by a key the verifier does not have (`--public-key`
takes a PEM or JWKS file, for keys rotated since).

**What it cannot detect.** Someone who can write to the database can delete an entire chain,
or the unanchored tail of one, without leaving a trace in what remains. That is why anchors
are signed with a key the database does not hold and why the SIEM export exists: the copy
outside the database is the witness. Keep the signing key off the database host's backups
and point at least one sink at a store the SAJHA operators cannot edit.

---

## 8. SIEM export

`audit.export.sinks` is a list (raw YAML, or the JSON list in `SAJHA_AUDIT_EXPORT_SINKS`).
Each sink has its own bounded queue (`queue_size`, default 10000) and thread; a full queue
drops (counted) rather than block a tool call. Records are sent in batches (`batch_size`,
default 100, or after `flush_seconds`, default 2); a failed batch is retried with
exponential backoff up to `max_retries` (default 5), then dropped and counted. The database
chain is the record of authority; the export is best-effort with visible loss.

| `type` | Transport |
|---|---|
| `syslog` | RFC 5424 messages, RFC 6587 octet-counted framing, over TCP or TLS (`tls: true`, `ca_file`, `verify`); `facility` default 13 (log audit); structured data `[sajha@32473 chain= seq= hash=]` |
| `http` | `flavor: splunk_hec` (one `{"time","host","source","sourcetype","event"}` object per record, `Authorization: Splunk <token>`), `datadog` (a JSON array to the logs intake, `DD-API-KEY`), or `generic` (a JSON array, optional `Authorization: Bearer`). Tokens are secret references (`env:NAME`, `file:/path`), never literal. The URL must match `audit.export.allowed_urls` when that list is set; it is resolved once, private addresses are refused unless the sink sets `allow_private_networks: true`, and the request goes to the pinned address with no redirects |
| `file` | JSON Lines, rotated at `max_bytes` (default 10 MiB) keeping `backups` (default 10); `{pid}` and `{host}` in `path` give each worker its own file |

`format` is `json` (the record itself), `cef` (ArcSight Common Event Format:
`CEF:0|SAJHA|SAJHA MCP Server|<version>|<event>|<name>|<severity>|...` with `suser`, `act`,
`outcome`, `rt` and the chain, sequence and hash as custom fields) or `ocsf` (an
OCSF-style object: API Activity, Authentication or Account Change class, `metadata.uid` =
the record hash). The Audit page shows each sink's sent, failed and dropped counts and last
error.

---

## 9. Admin pages and API

| Page | What |
|---|---|
| `/admin/policies` | every policy file, enabled or not, its rules and any parse error; the **test bench**: tool, arguments, caller (user, roles, API key, anonymous), source and time, answered with the decision, the matching rules and the obligations, without running the tool or touching counters |
| `/admin/approvals` | pending approvals (tool, arguments, caller, rule, reason, age) with Approve and Deny; recent decisions |
| `/admin/audit` | chain integrity per chain (Verify), recent records merged across chains, anchors, sink status; Anchor now |

JSON API (admin): `GET /api/policy/policies`, `POST /api/policy/reload`,
`POST /api/policy/test`, `GET /api/policy/approvals`, `POST /api/policy/approvals/{id}/approve`,
`POST /api/policy/approvals/{id}/deny`, `GET /api/audit/records`, `GET /api/audit/verify`,
`POST /api/audit/anchor`, `GET /api/audit/sinks`. Session callers send the page's CSRF
token (`X-CSRF-Token`).

---

## 10. Security notes

* The engine fails closed on its own errors: an exception inside policy evaluation denies the
  call (`policy.fail_closed`, default true) and is logged; a broken file follows
  `policy.on_error`.
* Policy files are configuration: whoever can write `config/policies/` (or its bucket) can
  change what is allowed. Protect it as you protect `config/tools/`.
* Approvals hold the call's arguments so the approver sees what they approve; they are
  visible to administrators only. Policy audit records carry argument *names* (approval records also the call
  fingerprint), never values, unless `policy.audit_arguments` is true.
* Redaction is pattern matching: it reduces accidental disclosure, it does not prove
  absence. Prefer not returning the data at all.

## 11. Limits

* Rate-limit and quota counters on `state.backend: memory` are per worker.
* Approvals live in the state store: on `memory` they are lost on restart and not shared.
* A call that MRTR confirms on 2026-07-28 is confirmed by the client's user, not verified by
  SAJHA: use `approver: admin` when the approver must be someone else.
* Per-process chains: whole-chain deletion and unanchored tails are detectable only against
  an external copy (section 7.4).
* Syslog over UDP is not offered (no delivery guarantee).

## 12. Tests

`tests/test_policy.py` (each effect and condition, choke-point coverage on every path,
approvals across a shared store, redaction, quotas across two stores sharing a database,
injection screening, the admin pages) and `tests/test_audit_chain.py` (chain integrity,
tamper detection for each row of 7.4, anchors and key mismatch, the CLI, each SIEM sink
against a local fake receiver, CEF/OCSF rendering).
