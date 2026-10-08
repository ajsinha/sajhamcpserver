# Tutorial 29: The Local Test Lab

Three SAJHA instances on one laptop, in one SAJHA Net, answering questions with a model running on the
same laptop. One command starts them; this tutorial walks through what you can do with them: watch the
net form, call a tool on another instance, ask a question that a local Qwen model answers with a remote
tool, run an LLM tool and a planner across the net, use the OpenAI-compatible endpoint, take a server
down, provoke a contract conflict, block an instance, keep data in its region, and call a vendor's tools
through the instance that proxies them. The later SAJHA Net tutorials (30 to 39) start from this lab.
The design is [SAJHA Net](../architecture/SAJHA%20Net.md); the launcher is described in its
[README](../../deployment/local-lab/README.md).

## What you'll learn

- How to start, inspect, stop and reset three instances with separate configurations, databases and logs
- How a net in open admission forms by itself, and where the console shows it: the navbar badge, the
  Instances page, the Net overview and its topology map
- How a call by plain name finds a remote host, and what happens when that host crashes
- How Ask SAJHA, an LLM tool and a planner use a local Ollama model and tools on other instances
- How contract conflicts, blocks and residency rules change what a caller may use
- How a proxied external MCP server's tools reach the other members as `<vendor>__<tool>`

## Prerequisites

- A SAJHA checkout and its Python environment ([Tutorial 1](TUTORIAL_01_getting_started.md)), with the
  MCP SDK, which federation uses to talk to proxied MCP servers: `pip install "mcp>=2.3,<3"` (it is in
  `requirements-dev.txt`)
- [Ollama](https://ollama.com) with three models: `qwen3:8b`, `qwen2.5:3b` and `nomic-embed-text`
- Free ports 3002, 3003 and 3004 (stop a development server you run on 3002 first, or move the lab with
  `SAJHA_LAB_PORT`, step 2)
- Linux, or the macOS note in the lab's README (each instance listens on its own loopback address)

**This is a lab.** Plain HTTP, open admission, the test admin key and a known password. Never copy its
settings to a server anyone else can reach.

## Steps

### 1. Start Ollama

```bash
ollama serve &                      # skip if it already runs (a desktop install starts it)
ollama pull qwen3:8b
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
curl -s http://127.0.0.1:11434/api/tags | python3 -m json.tool | grep '"name"'
```

The lab makes `qwen3:8b` the `default` and `reasoning` model aliases, `qwen2.5:3b` the `fast` alias and
`nomic-embed-text` the `embedding` alias, through the `ai.*` keys of each instance's generated
configuration ([Intelligence Layer](../architecture/Intelligence%20Layer.md)). It turns thinking off
(`think: false` on the Ollama provider): `qwen3:8b` then answers a short prompt in about a second on a
laptop CPU instead of most of a minute.

### 2. Start the lab

```bash
deployment/local-lab/lab.sh start
```

`lab.sh` runs `lab.py` with `$PYTHON` if you set it, else the checkout's `.venv/bin/python`, else
`python3`, and starts every instance with that Python through `run_sajha_web.py`. The first start writes
each instance's folder under `run/` in the lab's folder ([`deployment/local-lab`](../../deployment/local-lab/README.md); every
`run/...` path in the SAJHA Net tutorials is there): a configuration generated from
`config/application.yml`, a copy of the tools and policies folders, the keys files from the `.example`
files, an empty SQLite database. It starts `risk-eu` first, waits until it answers, starts the other two
and prints:

```text
risk-eu      http://127.0.0.1:3002    healthy   pid 4097935  lab-net: cust-na alive, treasury-eu alive
cust-na      http://127.0.0.2:3003    healthy   pid 4098754  lab-net: risk-eu alive, treasury-eu alive
treasury-eu  http://127.0.0.3:3004    healthy   pid 4098778  lab-net: cust-na alive, risk-eu alive

Sign in at any URL as testadmin / testadmin-dev-1 (while the test admin key is on) or admin / admin123.
API key on all three: sja_test_admin_dev_key_0001   (header X-API-Key; the test admin key)
```

It warns before starting if Ollama does not answer, a model is missing or the MCP SDK is not installed.
To use other ports: `SAJHA_LAB_PORT=3102 deployment/local-lab/lab.sh start` (use the same variable with
every later command).

What the lab set up:

| Instance | Region | Seeds | What only it has |
|---|---|---|---|
| `risk-eu` | `eu` | none: the net's founder, a net of one until the others join | the proxied MCP server `units`; the LLM tools `llm_summarise` and `llm_docs_qa`; no `calc_loan_amortization` or `calc_retirement` |
| `cust-na` | `na` | `risk-eu` | the LLM tool `llm_triage_ticket`; no `calc_retirement` |
| `treasury-eu` | `eu` | `risk-eu` | the only `calc_retirement` |

All three are in the net `lab-net` in **open admission**, the shipped setting: each made itself a
self-signed certificate, `cust-na` and `treasury-eu` joined through their seed, and every member
remembered the key it first saw for each name. Each exports its `calc_*`, `llm_*` and `units__*` tools
and imports what the others export.

### 3. Look around the console

Open http://127.0.0.1:3002 and sign in as `testadmin` / `testadmin-dev-1`. Then open
http://127.0.0.2:3003 and http://127.0.0.3:3004 in other tabs and sign in there too: each instance has
its own address so the three sessions do not overwrite each other's cookie.

- The navbar badge reads **Net · risk-eu** with a green dot; hover it for "lab-net: risk-eu (joined; 3
  instances)".
- **SAJHA Net > Instances** lists `risk-eu` first, marked THIS SERVER, then `cust-na` and `treasury-eu`
  as alive, with region, labels, last seen and how many of their tools you may use from here. Open
  `cust-na`: its `calc_*` tools and `llm_triage_ticket`, each with a **Try it** button.
- **SAJHA Net > Net overview** shows the membership (healthy), the admission mode (open, two first-use
  keys remembered), the topology map with the three instances and the offers between them (the same as
  a table under the map), notices, blocks, recent forwarded calls, call-chain refusals and residency
  decisions.
- **SAJHA Net > Remote tools** is the host and tool table: every remote tool with its host, state, trust,
  contract hash and place in the resolution order.

The command line view is `lab.sh status`, and the JSON is
`GET /api/sajhanet/status` on any instance.

### 4. Remote tools appear

```bash
curl -s http://127.0.0.1:3002/api/tools/list -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; print([t['name'] for t in json.load(sys.stdin)['tools'] if 'calc_loan' in t['name']])"
```

```text
['lab-net__cust-na__calc_loan_amortization', 'lab-net__treasury-eu__calc_loan_amortization', 'calc_loan_amortization']
```

Each remote tool is in `risk-eu`'s catalog under its qualified name `<net>__<instance>__<tool>`, and
because `risk-eu` has no `calc_loan_amortization` of its own, the plain name is an alias that resolves to
a remote host. Each entry's `_meta["io.sajha/net"]` names the net, instance, region, labels, version and
contract hash. A plain name may take a few seconds after a start to appear in `tools/list`; a call by
plain name resolves at once.

### 5. Call a tool on another instance

```bash
curl -s -X POST http://127.0.0.1:3002/api/tools/execute \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "calc_loan_amortization", "arguments": {"principal": 300000, "annual_rate": 5, "months": 360}}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['structuredContent']['monthly_payment'], r['_meta'])"
```

```text
1610.46 {'io.sajha/net': {'instance': 'cust-na', 'net': 'lab-net', 'qualified_name': 'lab-net__cust-na__calc_loan_amortization', 'trace_id': '6cb2...'}}
```

`risk-eu` (the home) signed the call and sent it to `cust-na` (the host) with the test admin key, which
the lab's instances all hold ([Tutorial 30](TUTORIAL_30_credentials_and_test_keys.md) explains it).
`cust-na` checked the signature and its own rules and ran the tool. Both sides audited the call under
one trace id: **Admin > Audit** on `cust-na` shows a `net.host_call` record with the identity
`test_admin_key`.

### 6. Ask SAJHA on Qwen, with a tool on another instance

Open **AI > Ask SAJHA** on `risk-eu` and ask:

> What is the monthly payment on a 300000 loan at 5% a year over 360 months?

Or from the shell:

```bash
curl -s -X POST http://127.0.0.1:3002/api/ai/ask -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is the monthly payment on a 300000 loan at 5% a year over 360 months?"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['answer']); print([(s['name'], s['net']) for s in d['steps']]); print(d['models'])"
```

```text
The monthly payment on a $300,000 loan at 5% annual interest over 360 months is $1,610.46.
[('calc_loan_amortization', {'net': 'lab-net', 'instance': 'cust-na', 'qualified_name': 'lab-net__cust-na__calc_loan_amortization'})]
['ollama/qwen3:8b']
```

The model picked `calc_loan_amortization` from the shortlist, SAJHA ran it on `cust-na`, and the model
wrote the answer from its result. On the Ask page the "Servers and tools" log shows the net and host of
the call. **Expect minutes, not seconds, on a CPU**: every offered tool is part of the prompt, and a laptop
CPU reads a few dozen prompt tokens a second. The lab offers six tools per question
(`ai.ask.shortlist: 6`) and allows ten minutes (`ai.ask.timeout_s: 600`); on the laptop this tutorial was
written on, this question took between one and a half and six minutes on `qwen3:8b`, depending on what else the
machine was doing. Add `"model": "fast"` to the body to use `qwen2.5:3b` instead.

To keep a question to this server's own tools, add `"locality": "local"`: the shortlist then holds no
remote tool, and the `shortlist` event names the restriction. `risk-eu` has no loan tool of its own, so
the model then answers without one (in the run behind this tutorial, with a wrong figure): read the
answer's `steps` before trusting a figure.

### 7. An LLM tool and a planner across the net

`llm_triage_ticket` is an LLM tool (its work is done by a model) that only `cust-na` has enabled. Call it
from `risk-eu`:

```bash
curl -s -X POST http://127.0.0.1:3002/api/tools/execute \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "lab-net__cust-na__llm_triage_ticket", "arguments": {"message": "I was charged twice this month, please refund one."}}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['structuredContent'], r['_meta']['io.sajha/net']['usage'])"
```

```text
{'label': 'billing', 'stopped_by': 'answer'} {'tokens': 147, 'cost_usd': 0.0, 'models': ['ollama/qwen2.5:3b'], 'charged_by': 'host'}
```

It ran on `cust-na`'s model and budget, and the result says so (`charged_by: host`); `risk-eu` records
that spend and never charges it again. Use the qualified name here: `risk-eu` has its own copy of the
example tool, disabled, which holds the plain name.

A planner decides how a question is worked through. Ask the same loan question with the
`verify_then_answer` planner, which gathers data, drafts an answer and checks every figure against the
tool results before answering (administrators may choose the planner):

```bash
curl -s -X POST http://127.0.0.1:3002/api/ai/ask -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is the monthly payment on a 300000 loan at 5% a year over 360 months?", "planner": "verify_then_answer"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['answer']); print(d['planner_path'])"
```

```text
The monthly payment on a $300,000 loan at 5% annual interest over 360 months is $1,610.46.
['act', 'act', 'draft', 'verify', 'answer']
```

[Tutorial 36](TUTORIAL_36_planners_and_llm_tools_across_the_net.md) goes further: locality restrictions
in planner files, remote LLM tools and the call-chain limit.

### 8. The OpenAI-compatible endpoint

The lab turns on `ai.openai_api` on every instance, so any OpenAI client can use SAJHA's models and LLM
tools with a SAJHA API key as the bearer token:

```bash
curl -s http://127.0.0.1:3002/v1/models -H 'Authorization: Bearer sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; print([m['id'] for m in json.load(sys.stdin)['data']])"
curl -s http://127.0.0.1:3002/v1/chat/completions -H 'Authorization: Bearer sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"model": "sajha:llm_summarise", "messages": [{"role": "user", "content": "SAJHA Net joins SAJHA servers into a net: they find each other by gossip, prove who they are with certificates, and offer each other their tools."}]}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```

The models are the aliases (`default`, `fast`, ...), the provider models, and every enabled LLM tool of
this instance as `sajha:<tool>`. The design is in [LLM Tools](../architecture/LLM%20Tools.md).

### 9. Document search with nomic-embed-text

`risk-eu` indexes the lab's README with `nomic-embed-text` at start (embedding all of SAJHA's guides
would take the better part of an hour on a CPU, so the lab indexes one folder; set
`ai.rag.index_sajha_docs: true` in `run/risk-eu/local.yml`, step 15, for all of them). Its
`llm_docs_qa` tool answers from that index only, citing the passages it used:

```bash
curl -s http://127.0.0.1:3002/api/ai/docs/status -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['embedder'], d['documents'], d['chunks'])"
curl -s -X POST http://127.0.0.1:3002/api/tools/execute \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "llm_docs_qa", "arguments": {"question": "How do I start the lab on other ports?"}}' \
  | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['answer']); print(r['citations'])"
```

```text
ollama/nomic-embed-text 1 7
To start the lab on other ports, you can modify the `SAJHA_LAB_PORT` environment variable. ... [2].
['[2] deployment/local-lab/README.md']
```

The question was embedded with `nomic-embed-text`, the closest passages were found by vector and keyword
search together, and `qwen3:8b` answered from them only (it says "Not found in the sources" rather than
guess).

### 10. A server goes down

Crash `cust-na` (SIGKILL: it cannot say goodbye) and call the plain name again:

```bash
deployment/local-lab/lab.sh kill cust-na
curl -s -X POST http://127.0.0.1:3002/api/tools/execute \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "calc_loan_amortization", "arguments": {"principal": 300000, "annual_rate": 5, "months": 360}}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['_meta']['io.sajha/net'])"
```

```text
{'instance': 'treasury-eu', ..., 'attempts': [{'attempt': 1, 'host': 'cust-na', 'outcome': 'unreachable', 'executed': False}, {'attempt': 2, 'host': 'treasury-eu', 'outcome': 'answered', 'executed': True}]}
```

The first attempt went to `cust-na`, which did not answer; the call had certainly not run, so `risk-eu`
moved on to the next host offering the same tool (the waterfall fallback). Within seconds gossip marks
`cust-na` suspect and then dead (`lab.sh status`, the Instances page, a notice), and later calls go to
`treasury-eu` directly. A call by qualified name never moves on. A clean stop (`lab.sh stop cust-na`)
tells the others it is leaving: they show it as left at once.

Bring it back with `lab.sh start cust-na`. It rejoins through its seed; give the
others a few seconds before its tools answer again (a call meanwhile is refused as `unavailable`).

### 11. A contract conflict is quarantined

One name, one contract: every host offering a tool under one name must offer the same inputs and
outputs. Give `treasury-eu`'s copy of `calc_loan_amortization` an extra input, then reload its tools:

```bash
python3 - <<'EOF'
import json
p = 'deployment/local-lab/run/treasury-eu/config/tools/calc_loan_amortization.json'
t = json.load(open(p))
t['inputSchema']['properties']['extra_payment'] = {'type': 'number', 'description': 'An extra payment each month'}
json.dump(t, open(p, 'w'), indent=2)
EOF
curl -s -X POST http://127.0.0.3:3004/api/admin/tools/reload -H 'X-API-Key: sja_test_admin_dev_key_0001'
```

Within seconds every member sees two contracts for `calc_loan_amortization` and quarantines the name,
on every host:

```bash
curl -s http://127.0.0.1:3002/api/sajhanet/conflicts -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['nets']['lab-net']['quarantined']['calc_loan_amortization']['text'])"
```

```text
Tool calc_loan_amortization quarantined in lab-net: its hosts offer 2 different contracts (no majority).
Differs: inputSchema /properties/extra_payment (treasury-eu: {...}; others: (absent)).
...
```

A call to it now answers "Tool not found", and **SAJHA Net > Remote tools** lists the conflict with
every offer and its hash. Undo the change (delete the `extra_payment` property the same way, or copy
`config/tools/calc_loan_amortization.json` back over it) and reload again: a notice "Tool
calc_loan_amortization active again in lab-net" appears and the tool answers.

### 12. Block an instance

Blocks are local decisions of one instance. On `risk-eu`, stop calling `cust-na`:

```bash
curl -s -X POST http://127.0.0.1:3002/api/sajhanet/nets/lab-net/blocks \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"level": "outbound", "target_instance": "cust-na", "reason": "lab"}'
```

The answer's `effect` says "This server stops calling cust-na; its tools are hidden from local users".
`lab-net__cust-na__...` tools are gone from `risk-eu`'s catalog, and the plain name
`calc_loan_amortization` goes to `treasury-eu`. Remove the block with
`DELETE /api/sajhanet/nets/lab-net/blocks/<id>` (the id is in the answer) or on **SAJHA Net > SAJHA Net
admin**.

Now block the other way, on `cust-na`: refuse what `risk-eu` sends (`"level": "inbound", "target_instance":
"risk-eu"`, posted to http://127.0.0.2:3003). A call from `risk-eu` to a `cust-na` tool now comes back
with `isError: true` and `_meta["io.sajha/net"].refusal.reason` `inbound`, and a call by plain name does
**not** move on to `treasury-eu`: a host's refusal is a decision, not an outage. Remove that block too.

### 13. Keep data in its region

Residency rules decide which data may go to which instance. Mark the `principal` of
`calc_loan_amortization` as EU customer data on `risk-eu`, and refuse to send it outside the EU. Create
`run/risk-eu/local.yml` (the lab merges it into that instance's configuration at
every start):

```yaml
sajhanet:
  data_classes:
    tools:
      calc_loan_amortization: {arguments: {principal: eu-customer}}
```

and a policy file `run/risk-eu/config/policies/50-lab-residency.yaml`:

```yaml
name: lab-residency
description: EU customer data stays in the EU
enabled: true
rules:
  - id: eu-customer-stays-in-eu
    match: {data_classes: [eu-customer], flow: arguments, destination: {region: {ne: eu}}}
    effect: deny
    reason: EU customer data stays in the EU
```

Restart `risk-eu` (`lab.sh stop risk-eu`, then `lab.sh start risk-eu`; policies alone reload by
themselves). Now:

- the plain name `calc_loan_amortization` resolves to `treasury-eu` (region `eu`) only;
- the qualified `lab-net__cust-na__calc_loan_amortization` is refused before it leaves: "the arguments
  carry data that may not go to that server (data residency)", reason `residency_arguments`,
  `executed: false`;
- **SAJHA Net > Net overview** counts the classified call that went to `treasury-eu` under Residency
  decisions (flow `arguments`, allowed); each decision is a `net.residency` audit record.

[Tutorial 35](TUTORIAL_35_data_residency_across_instances.md) adds redaction of results at the host.
Delete the two files and restart `risk-eu` to undo.

### 14. An external server's vendor tools

`risk-eu` embeds an MCP server: the units example server (`sajha/examples/federation/units_server.py`),
started over stdio from the lab's `run/risk-eu/config/mcp_servers.json`. That file uses the `mcpServers`
shape of Claude Desktop, Cursor and VS Code, and its entries are **external** servers by default: their
tools appear on `risk-eu` as `units__celsius_to_fahrenheit` and `units__kilometres_to_miles` (vendor
`units`), and `risk-eu` offers them into the net as its own, so the other members see
`lab-net__risk-eu__units__celsius_to_fahrenheit` marked external, via `risk-eu`. The server is never a
member: it has no certificate and is not on the Instances page.

```bash
curl -s -X POST http://127.0.0.2:3003/api/tools/execute \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "units__celsius_to_fahrenheit", "arguments": {"celsius": 21}}' | head -c 200; echo
```

The call from `cust-na` went to `risk-eu`, which applied its own rules and called the server.
**Admin > Proxied MCP servers** on `risk-eu` shows the server, its state and its tools.
[Tutorial 33](TUTORIAL_33_proxied_mcp_servers.md) is the full story.

### 15. Change one instance's settings

Every start regenerates `run/<instance>/application.yml`; to change a setting, put it in
`run/<instance>/local.yml` (one instance) or `run/local.yml` (all three) and restart the instance. A list,
such as `sajhanet.nets`, replaces the generated one whole. A `lab_env:` map sets environment variables
for the instance; the lab does not pass on your shell's `SAJHA_*` variables. Tools and policies are
per-instance copies under `run/<instance>/config/`.

### 16. Stop and reset

```bash
deployment/local-lab/lab.sh stop      # stop the three; the next start resumes the same net
deployment/local-lab/lab.sh reset     # stop and delete the instances' folders: the next start is a new net
```

`reset` keeps `run/local.yml`. Ollama keeps running; stop it yourself if you started it.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Ask SAJHA takes minutes or times out | CPU inference. Use `"model": "fast"`, ask with fewer tools in play (`"locality": "local"`), keep the models loaded (the lab sets `keep_alive: 30m`; the first question after a pause loads the model again), close other heavy programs. `ollama ps` shows what is loaded and where. |
| `... is in use by another process` at start | Another server holds the port. `lsof -i :3002` names it; stop it, or start the lab elsewhere with `SAJHA_LAB_PORT=3102`. |
| An instance exits during start | Read its log: `run/<instance>/server.log`. |
| `units__` tools missing, notice "Federated server units is unreachable" | The MCP SDK is missing from the Python that runs the lab: `pip install "mcp>=2.3,<3"`, then `lab.sh stop risk-eu` and `lab.sh start risk-eu`. |
| An instance shows "not joined" and a notice "Name ... is held in lab-net" | `name_conflict`: another key already holds that instance name, typically after you reset one instance alone (it made a new key). [Tutorial 31](TUTORIAL_31_open_admission_and_the_ca.md) shows how to forget the old key; in a lab, `lab.sh reset` is quicker. |
| Remote tools answer `unavailable` right after a restart | The others re-pull its catalog within seconds; try again. |
| Signing in to one instance signs you out of another | They share a host name. Use the printed addresses (127.0.0.1, .2, .3), or one browser profile per instance with `SAJHA_LAB_ONE_HOST=1`. |
| "Add a peer by address" refuses 127.0.0.x | Peer addresses added by hand must not be loopback addresses (an SSRF guard); in the lab, instances join through their seeds instead. |
| Where are the logs? | One per instance under `run/<instance>/server.log`; the checkout's `logs/server.log` also receives every instance's lines. |

## What you learned

- One command runs three isolated SAJHA instances in one open-admission net, each with its own
  configuration, database and log, and a local Ollama model behind the `default`, `fast` and `embedding`
  aliases
- The console shows the net in the navbar badge, the Instances page, the Net overview's topology map and
  the Remote tools page
- A call by plain name resolves to a remote host and falls back to the next when a host is unreachable;
  a refusal by a host is final
- Ask SAJHA, LLM tools, planners and the OpenAI-compatible endpoint run on the local model and use remote
  tools; a remote LLM tool is charged by its host
- Conflicting contracts quarantine a name everywhere, blocks are local decisions, residency rules keep
  classified data from leaving its region
- A proxied external server's tools reach the net as `<vendor>__<tool>` through the instance that defines
  it

## Next

- [Tutorial 30: Credential Files and Test Keys](TUTORIAL_30_credentials_and_test_keys.md): which key a
  forwarded call carries, and how to stop using the test admin key
- The design behind every step: [SAJHA Net](../architecture/SAJHA%20Net.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
