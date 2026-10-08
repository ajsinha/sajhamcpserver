# Tutorial 36: Planners and LLM Tools Across the Net

Ask SAJHA, LLM tools and planners choose tools for a model, and in a SAJHA Net some of those tools run
elsewhere. This tutorial shows how SAJHA ranks local and remote tools for a model and why, how to keep a
question to this server or to one net, how an LLM tool on another instance runs on that instance's model
and budget, and how one budget bounds a chain of calls that crosses servers and nests tools. It runs on
the [local test lab](TUTORIAL_29_local_test_lab.md) with its Ollama models. The design is
[SAJHA Net](../architecture/SAJHA%20Net.md) sections 13 and 14; planners are in the
[Planner Reference](../architecture/Planner%20Reference.md), LLM tools in
[LLM Tools](../architecture/LLM%20Tools.md).

## What you'll learn

- What a shortlist entry records about where a tool runs, and how locality nudges the ranking
- How to restrict a question to local tools or to one net, from the ask, a planner or configuration
- How a remote LLM tool is run and charged, and how to stop exporting LLM tools
- What the combined call-chain limit counts, and what a refusal looks like

## Prerequisites

- The local test lab running ([Tutorial 29](TUTORIAL_29_local_test_lab.md)) with Ollama and its models
- Patience: on a CPU a question with tools takes a minute or more (Tutorial 29, step 6)

## Steps

### 1. Where each shortlisted tool runs

Ask with streaming and read only the first event, the shortlist (it arrives before any model call):

```bash
timeout 20 curl -sN -X POST 'http://127.0.0.1:3002/api/ai/ask?stream=1' \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"question": "What is the monthly payment on a 300000 loan at 5% a year over 360 months?", "model": "fast"}' \
  | head -c 1500; echo
```

```text
event: shortlist
data: {"type": "shortlist", "seq": 1, "tools": [
  {"name": "calc_loan_amortization", "score": 0.7778, "locality": {"where": "remote", "net": "lab-net", "instance": "treasury-eu", "region": "eu", "why": "runs on treasury-eu in lab-net; same region (eu)"}},
  {"name": "lab-net__cust-na__calc_loan_amortization", "score": 0.767, "locality": {"where": "remote", ..., "why": "runs on cust-na in lab-net; another region (na; this server eu)"}},
  {"name": "av_stock_monthly", ..., "locality": {"where": "local", "why": "runs on this server"}}, ...
```

Every entry says where the tool runs (`local`, `remote` with net and host, or `federated`) and why it
ranked where it did. Local tools rank first; among remote hosts, those named in `sajhanet.preferences`
for the tool, in this server's region, healthy and faster get small nudges of the resolver's score, so a
remote tool that is the right tool is still offered. Proxies of a host that is not active are left out.
The same reasons show in the Ask page's "Servers and tools" log.

### 2. Keep a question local, or to one net

A **locality restriction** is `any` (the default), `local` (this server's own tools) or `net:<name>`
(this server's own and that net's). It comes from, in order: the ask (`"locality": "local"` in the body of
`POST /api/ai/ask`), the planner's `settings.locality` (in a planner file under `config/planners`, or an
LLM tool's `planner_config` overlay), else `ai.ask.locality` in configuration. The `shortlist` event names
the restriction and where it came from.

```bash
curl -s -X POST http://127.0.0.1:3002/api/ai/ask -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is the monthly payment on a 300000 loan at 5% a year over 360 months?", "locality": "local", "model": "fast"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['shortlist']); print(d['steps'])"
```

The shortlist now holds only `risk-eu`'s own tools, none of which computes a loan, so the model answers
without a tool (and, in the run behind this tutorial, wrongly). That is the trade: a restriction keeps data
and calls at home at the cost of the tools elsewhere. To set it for every question on one instance, put
`ai: {ask: {locality: local}}` in that instance's `run/<instance>/local.yml` and restart it.

### 3. A planner with remote tools

Planners decide the stages a question goes through. With the remote loan tool in reach, the
`verify_then_answer` planner gathers data, drafts an answer and checks each figure against the tool
results:

```bash
curl -s -X POST http://127.0.0.1:3002/api/ai/ask -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is the monthly payment on a 300000 loan at 5% a year over 360 months?", "planner": "verify_then_answer"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['answer']); print(d['planner_path']); print([(s['name'], s['net']['instance']) for s in d['steps']])"
```

```text
The monthly payment on a $300,000 loan at 5% annual interest over 360 months is $1,610.46.
['act', 'act', 'draft', 'verify', 'answer']
[('calc_loan_amortization', 'cust-na')]
```

On a small local model, planners that plan every call up front from tool names (`plan_execute`,
`rewoo`) may guess argument names wrong; in the run behind this tutorial `plan_execute` on `qwen3:8b`
sent `loan_amount` for `principal` and gave up after a re-plan. The ReAct-based planners (`react`, the
default, and `verify_then_answer`) see each tool's schema in the model's tool list and did not.

### 4. A remote LLM tool runs on its host's model

`llm_summarise` is enabled on `risk-eu` only. Call it from `cust-na`:

```bash
curl -s -X POST http://127.0.0.2:3003/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"tool": "lab-net__risk-eu__llm_summarise", "arguments": {"text": "The quarterly report shows revenue up 25% to 100 million euros, costs flat at 60 million, and a new office in Lisbon opening in March.", "max_sentences": 1}}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['structuredContent']['text']); print(r['_meta']['io.sajha/net']['usage'])"
```

```text
The quarterly report indicates a 25% increase in revenue to 100 million euros ...
{'tokens': 148, 'cost_usd': 0.0, 'models': ['ollama/qwen2.5:3b'], 'charged_by': 'host'}
```

An LLM tool is exported like any tool, marked `llm_tool: true` in its net metadata. Called from another
instance it runs on its host as the mapped user, on the host's models and budgets; the host reports the
spend in `_meta["io.sajha/net"].usage`, the home records it in its `net.call_attempt` audit record and
never charges it again. To keep this server's LLM tools to its own users, set
`sajhanet.allow_remote_llm_tools: false`.

### 5. One budget for a whole chain

A call that crosses servers and nests tools (a composite, an LLM tool, `sajha_ask`, a planner's tools) is
bounded end to end: **hops** (servers passed) plus **depth** (tools running inside one another, on every
instance passed) may not exceed `sajhanet.max_call_chain` (default 8, at most 32). Make the budget tiny on
all three to see it. Create `run/local.yml`:

```yaml
sajhanet:
  max_call_chain: 1
```

restart the lab (`lab.sh stop`, `lab.sh start`), and call a plain remote tool and a remote LLM tool from
`risk-eu`:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
for t in lab-net__cust-na__calc_percentage_change lab-net__cust-na__llm_triage_ticket; do
  curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H "$K" -H 'Content-Type: application/json' \
    -d "{\"tool\": \"$t\", \"arguments\": {\"old_value\": 80, \"new_value\": 100, \"message\": \"refund please\"}}" | head -c 230; echo
done
```

```text
{"success":true,"result":{"content":[{"type":"text","text":"{\n  \"old_value\": 80, ... \"percentage_change\": 25.0\n}"}] ...
{"success":true,"result":{"content":[{"type":"text","text":"cust-na refused the call to lab-net__cust-na__llm_triage_ticket: the call chain is too long (servers passed plus tools nested in one another)."}],"isError":true, ... "reason":"chain_limit" ...
```

The plain tool is one hop. The LLM tool is one hop plus the LLM tool's own run, which is over a budget of
one, so `cust-na` refused it on receipt (`chain_limit`). A home refuses before sending when it can tell
(`-32016`: `loop` when the host is already on the visited list, `hop_limit`, `chain_limit` with `hops`,
`depth` and `limit`). The Net overview lists these under Call-chain refusals.
`ai.llm_tools.max_depth` and `tools.max_call_depth` still apply per instance; the combined budget is what
bounds a chain across instances. Delete `run/local.yml` and restart to undo.

## What you learned

- Shortlists record where each tool runs and why it ranked there; local first, then nudges by
  preference, region, health and latency
- A locality restriction (`any`, `local`, `net:<name>`) comes from the ask, the planner or configuration
- A remote LLM tool runs and is charged on its host, and says so in `_meta`
- Hops plus nesting depth share one budget, `sajhanet.max_call_chain`, enforced by home and host

## Next

- [Tutorial 37: Re-export and Bridges](TUTORIAL_37_reexport_and_bridges.md)
- Write a planner of your own: [Tutorial 27](TUTORIAL_27_write_a_planner.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
