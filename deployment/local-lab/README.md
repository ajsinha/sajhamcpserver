# SAJHA local test lab

Three SAJHA instances in one SAJHA Net on one laptop, with a local Ollama as their LLM. Each instance
has its own configuration, database, data folder, tools folder, policies folder, keys files and log;
nothing in the checkout's own `config/` or `data/` is touched. The walkthrough is
[Tutorial 29: The Local Test Lab](../../docs/tutorials/TUTORIAL_29_local_test_lab.md); the later SAJHA
Net tutorials (30 to 39) build on it.

**This is a lab.** Plain HTTP on loopback addresses, open admission, the test admin key, a known
password. Never copy these settings to a server anyone else can reach.

## Commands

```bash
deployment/local-lab/lab.sh start              # generate what is missing, start the three, wait until healthy
deployment/local-lab/lab.sh status             # PIDs, health, who each instance sees, URLs and credentials
deployment/local-lab/lab.sh stop               # stop the three (and the MCP server risk-eu proxies)
deployment/local-lab/lab.sh kill cust-na       # a crash (SIGKILL): the others find out by gossip
deployment/local-lab/lab.sh reset              # stop, delete the instances' folders: the next start is a new net
deployment/local-lab/lab.sh stop cust-na       # every command takes instance names
```

`lab.sh` runs `lab.py` with `$PYTHON` if set, else the checkout's `.venv/bin/python`, else
`python3`. The instances run with the same Python, through `run_sajha_web.py`.

## The layout

| Instance | URL | Region | Seeds | What only it has |
|---|---|---|---|---|
| `risk-eu` | http://127.0.0.1:3002 | `eu` | none (the founder: a net of one until the others join) | the proxied MCP server `units` (its tools `units__celsius_to_fahrenheit`, `units__kilometres_to_miles`), the LLM tools `llm_summarise` and `llm_docs_qa` (document search over this folder); no `calc_loan_amortization` or `calc_retirement` |
| `cust-na` | http://127.0.0.2:3003 | `na` | `risk-eu` | the LLM tool `llm_triage_ticket`; no `calc_retirement` |
| `treasury-eu` | http://127.0.0.3:3004 | `eu` | `risk-eu` | the only `calc_retirement` |

All three are in the net `lab-net`, export their `calc_*`, `llm_*` and `units__*` tools, and import
everything the others export. Missing tools are left out of an instance's copy of `config/tools`, so a
call for them there must cross the net: `calc_loan_amortization` on `risk-eu` goes to `cust-na` or
`treasury-eu`.

Each instance listens on its own loopback address because browser cookies ignore the port: on one
address, signing in to one instance would sign you out of the others. Linux answers on all of
127.0.0.0/8. On macOS, either add the addresses (`sudo ifconfig lo0 alias 127.0.0.2 up`, and `.3`)
or set `SAJHA_LAB_ONE_HOST=1` and use one browser profile or private window per instance.

| Sign in | |
|---|---|
| Console | `testadmin` / `testadmin-dev-1` (the test administrator), or `admin` / `admin123` |
| API key | `sja_test_admin_dev_key_0001`, on all three (header `X-API-Key`) |

The LLM is Ollama on http://127.0.0.1:11434: `qwen3:8b` is the `default` and `reasoning` alias,
`qwen2.5:3b` the `fast` alias, `nomic-embed-text` the `embedding` alias, with thinking off
(`think: false`) and the models kept loaded for 30 minutes.

## Files

Everything the lab writes is under `run/` beside this file (git-ignored):

| Path | What |
|---|---|
| `run/<instance>/application.yml` | the instance's configuration, generated from `config/application.yml` at every start; edits are lost |
| `run/<instance>/local.yml` | your settings for one instance, merged last (create it; a list such as `sajhanet.nets` replaces the generated one whole); a `lab_env:` map sets environment variables for the instance |
| `run/local.yml` | the same for all three |
| `run/<instance>/config/` | its copies of `tools/` and `policies/`, `apikeys.json` and `users.json` (from the `.example` files), `mcp_servers.json` (risk-eu), federation state |
| `run/<instance>/sajha.db`, `data/` | its database, SAJHA Net keys and certificates, document index, snapshots and caches |
| `run/<instance>/server.log` | its log (the checkout's `logs/server.log` also receives every instance's lines) |

`reset` deletes the instances' folders and keeps `run/local.yml`.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `PYTHON` | `.venv/bin/python`, else `python3` | the Python that runs the lab and the instances (`lab.sh` only) |
| `SAJHA_LAB_PORT` | `3002` | `risk-eu`'s port; the others take the next two |
| `SAJHA_LAB_ONE_HOST` | off | every instance on 127.0.0.1 |
| `SAJHA_LAB_OLLAMA` | `http://127.0.0.1:11434` | the Ollama server |
| `SAJHA_LAB_MODEL`, `SAJHA_LAB_FAST_MODEL`, `SAJHA_LAB_EMBED_MODEL` | `qwen3:8b`, `qwen2.5:3b`, `nomic-embed-text` | the models behind the aliases |
| `SAJHA_LAB_DIR` | `run/` beside this file | where the lab writes |

The lab does not pass your shell's `SAJHA_*` variables to the instances; use `lab_env:` in a
`local.yml` instead.

## Also here

[`fake_idp.py`](fake_idp.py): a fake OpenID Connect provider for trying console single sign-on offline
([Tutorial 39](../../docs/tutorials/TUTORIAL_39_console_single_sign_on.md)).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
