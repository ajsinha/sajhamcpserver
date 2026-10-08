# Tutorial 20: Policies, Approvals and a Tamper-Evident Audit

Put rules on tool calls without touching a tool: deny one, constrain another's arguments,
hold a third for an administrator's approval, rate-limit it, and preview what redaction
does to a result. Then prove the audit trail of all that has not been edited, catch a
tampered record, and stream the records to a SIEM. The design (the rule language, the
hash chain, anchors, sinks) is in [Policy and Audit](../architecture/Policy%20and%20Audit.md).

## What you'll learn

- Where policy files live, how they reload, and why a fresh SAJHA has no rules
- How to try a rule on the test bench before it affects anyone
- What a denied, held and rate-limited call looks like to a REST caller
- How an approval works: request, decision, one run
- How `python -m sajha.audit verify` detects an edited audit record
- How to send every audit record to a file and to a syslog receiver

## Prerequisites

- A SAJHA checkout with its virtual environment, running on `http://localhost:3002`, and an
  admin sign-in ([Tutorial 1](TUTORIAL_01_getting_started.md))
- An API key for a caller other than you, so you can approve its calls: create one on
  **Admin → API keys** and `export SAJHA_KEY=sja_...`
- `sqlite3` for step 7 (the default development database is SQLite)

## Steps

### 1. Look at what is enforced now

Open **Admin → Governance → Policies** (`/admin/policies`). It lists every file in
`config/policies/`:

- `00-default.yaml`, enforced, with **no rules**: that is why nothing changed when policies
  arrived;
- `example-guardrails.yaml` and `example-business-hours.yaml`, **disabled**: every effect and
  obligation, to copy from.

The tiles say how many rules are enforced and that the default effect is `allow`.

### 2. Write a policy

Create `config/policies/50-tutorial.yaml`:

```yaml
name: tutorial
description: Tutorial 20 rules.
rules:
  - id: no-anonymous-calc
    match:
      tools: ["calc_*"]
      callers: {anonymous: true}
    effect: deny
    reason: Sign in to use the calculators.

  - id: sane-percentages
    match: {tools: [calc_percentage_change]}
    constraints:
      old_value: {type: number, min: 0, max: 1000000}

  - id: approve-big-compounding
    match:
      tools: [calc_compound_interest]
      arguments: {principal: {gt: 100000}}
    effect: require_approval
    reason: Compounding over 100,000 needs a second look
    approval: {approver: admin, ttl: 1h}

  - id: calc-rate-limit
    match: {tools: ["calc_*"], callers: {api_keys: ["*"]}}
    rate_limit: {limit: 5, window: 1m, per: [api_key]}
```

You do not restart anything: the directory is rechecked at most every
`policy.reload_seconds` (5) on the next call. Reload the Policies page, or press
**Reload now**; the new file shows four rules and the tiles count them as enforced. A
typo (an unknown key, a bad regex) marks the file **broken** with the reason, and a broken
file is not enforced.

### 3. Try it on the test bench

On the same page, in **Test bench**, enter tool `calc_compound_interest`, arguments
`{"principal": 250000, "rate": 5, "years": 10}` and press **Evaluate**. The answer is
`require approval` with the matching rules `tutorial/approve-big-compounding` and
`tutorial/calc-rate-limit` (when an API key name is filled in). Change `principal` to `1000`:
`allow`. Tick **Anonymous caller**: `deny`, "Sign in to use the calculators."

Paste `Contact jane@example.com, card 4111 1111 1111 1111` into **Sample result** and enable
the disabled example policies with **Include disabled policies**, using tool `crm_lookup`:
the result comes back masked (`j***@example.com`, `**** **** **** 1111`) by the example's
`no-pii-out` rule. The bench never runs the tool, never creates an approval and never moves
a rate-limit counter.

### 4. Call the tools as an API key

```bash
X=(-H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json')
curl -s "${X[@]}" localhost:3002/api/tools/execute \
  -d '{"tool":"calc_percentage_change","arguments":{"old_value":80,"new_value":100}}'
# 200 {"success": true, "result": {...}}

curl -s -w ' %{http_code}\n' "${X[@]}" localhost:3002/api/tools/execute \
  -d '{"tool":"calc_percentage_change","arguments":{"old_value":-5,"new_value":100}}'
# 403  "Denied by policy: argument constraint: 'old_value' must be at least 0 (rule tutorial/sane-percentages)"

curl -s -w ' %{http_code}\n' "${X[@]}" localhost:3002/api/tools/execute \
  -d '{"tool":"calc_compound_interest","arguments":{"principal":250000,"rate":5,"years":10}}'
# 202  {"success": false, "approval_id": "3f2c...", "error": "Approval required: ..."}
```

The same calls over MCP (either protocol era, stdio, WebSocket), from Ask SAJHA, A2A or an
async task meet the same rules: the engine sits where every path runs a tool. Over MCP a
denial is a tool error (`isError: true`) whose text carries the reason and the approval id.

### 5. Approve the held call

Open **Admin → Governance → Approvals** (`/admin/approvals`). The pending row shows who asked
(`apikey:...`), through what (`rest`), the tool, the exact arguments, the rule and its
reason. Press **Approve**. Run the same `curl` again: `200`, the result. Run it a third
time: `202` with a new approval id, because an approval runs the call **once**, and only
for the same caller with the same arguments. You cannot approve your own calls
(`policy.approvals.allow_self_approval`).

### 6. Hit the rate limit

```bash
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w '%{http_code} ' "${X[@]}" localhost:3002/api/tools/execute \
    -d '{"tool":"calc_percentage_change","arguments":{"old_value":1,"new_value":2}}'
done; echo
# 200 200 ... 429   (a Retry-After header says when to try again)
```

The counters live in the state store, so with `state.backend: redis` or `database` every
worker shares the limit ([Scaling and State](../architecture/Scaling%20and%20State.md)).

### 7. Verify the audit chain, then tamper with a copy

Every decision above was audited. Open **Admin → Governance → Audit** (`/admin/audit`): the
records are there (`policy.deny`, `policy.approval_required`, `approval.approve`,
`policy.approved`, `policy.rate_limited`), merged across workers, each with its chain,
sequence number and hash. Press **Verify**: **Intact**.

From a terminal:

```bash
python -m sajha.audit verify
# OK      myhost-41237-18f3c2a9d10  records=57 anchors=1 last_anchored_seq=48 open
#     warning: 8 record(s) after the last anchor are not yet anchored
#     warning: no chain.close: the process is running, or stopped without a clean shutdown
# INTACT: 1 chain(s), 57 record(s)
```

Now play the attacker on a copy of the database: change who was denied.

```bash
cp data/sajha.db /tmp/audit-copy.db
sqlite3 /tmp/audit-copy.db \
  "UPDATE audit_chain SET record_json = replace(record_json, 'apikey:', 'someone-else:')
   WHERE event = 'policy.deny';"
python -m sajha.audit verify --db-url sqlite:////tmp/audit-copy.db
# BROKEN  myhost-...
#     problem: seq 23: hash does not match the record (record edited)
# TAMPERED OR BROKEN: ...
```

Re-hashing the edited record and every record after it does not help the attacker either:
the signed anchors (RS256, the server's key, public half at `/oauth/jwks`) still name the
original hashes, and `verify` reports "chain rewritten".

### 8. Stream the audit to a SIEM

Stop SAJHA, then start it with two sinks: a CEF file and a syslog receiver.

```bash
nc -lk 6601 &                             # a stand-in syslog receiver (prints what it gets)
export SAJHA_AUDIT_EXPORT_SINKS='[
  {"name": "file", "type": "file", "path": "logs/audit/audit-{pid}.cef", "format": "cef"},
  {"name": "syslog", "type": "syslog", "host": "127.0.0.1", "port": 6601, "format": "json"}]'
python run_sajha_web.py
```

Repeat a call from step 4. The `nc` window prints RFC 5424 messages
(`<108>1 2026-... sajha 4711 policy.deny [sajha@32473 chain="..." seq="..." hash="..."] {...}`),
and the file gets one `CEF:0|SAJHA|SAJHA MCP Server|...` line per record. The Audit page now
lists both sinks with their sent, failed and dropped counts. For Splunk use `type: http,
flavor: splunk_hec, token: env:SPLUNK_HEC_TOKEN`; for Datadog `flavor: datadog`
([Policy and Audit, section 8](../architecture/Policy%20and%20Audit.md#8-siem-export)).

When you are done, delete `config/policies/50-tutorial.yaml` (the rules go away within
seconds) and unset `SAJHA_AUDIT_EXPORT_SINKS`.

## What you learned

- Policies are files under `config/policies/`, reloaded on change; the shipped one has no rules.
- One engine governs every path, so a rule written once applies to MCP, REST, Ask SAJHA and the rest.
- The test bench answers "would this call be allowed?" without side effects.
- `require_approval` holds a call; an approval runs exactly that call, once, for that caller.
- The audit is a hash chain with signed anchors; `python -m sajha.audit verify` proves it intact.
- Sinks copy every record to a SIEM, the witness that survives a database someone can edit.

## Next

- The full rule language, redaction kinds and screening: [Policy and Audit](../architecture/Policy%20and%20Audit.md)
- Every `policy.*` and `audit.*` key: [Configuration Reference](../getting-started/Configuration%20Reference.md#policy-and-audit)
- The rest of the security model: [Security Model](../security/Security%20Model.md)
- Next tutorial: [Planners, Conversation Memory and Document Search](TUTORIAL_21_planners_memory_and_rag.md)

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
