# Adversarial QA Plan

How to attack SAJHA on purpose before someone else does: what to try, what safe behaviour looks
like, how to automate it and what already covers it. Functional testing asks "does it work?"; this
plan asks "how does it fail, and does it fail safely?". It complements [Tool Quality](Tool%20Quality.md)
(testing tools themselves) and the [Security Model](../security/Security%20Model.md) (what the
defences are); it owns neither topic, only the plan of attack.

## 1. How to use this plan

Each item names an **attack**, the **safe behaviour** SAJHA must show, how to **automate** it, a
**priority** and the **existing coverage** (test files under `tests/`). Work top-down by priority:

| Priority | Meaning |
|---|---|
| **P0** | A failure would expose data, run code or act as another user, or take a whole server or net down. Automate first; run on every change. |
| **P1** | A failure would corrupt state, disable a feature for everyone, leak metadata or bypass a limit. Automate; run on every release. |
| **P2** | A failure would degrade service or mislead an operator. Exploratory first, automate when cheap. |

A finding is reported with a reproduction, its severity, the fix and a **regression test that fails
without the fix**; the item's coverage column then names that test. An item is closed only by a test.

**Rules of engagement.** Attack only your own instances: the three-instance local lab
(`deployment/local-lab/`, [Tutorial 29](../tutorials/TUTORIAL_29_local_test_lab.md)) or scratch servers
with scratch databases (`SAJHA_DB_PATH`). Never point an attack at a shared server, a real upstream
MCP server or a third-party API.

## 2. What this cycle taught us

The bugs found while building waves 4 to 6 are the best guide to where the next ones hide. Each theme
below is now a standing line of attack:

| Theme | What went wrong | Standing attack |
|---|---|---|
| **Identity confused with labels** | A key's *name* was forwarded where the key belonged; a home's key could be read as the host's own key | Send every credential-shaped field with a label, a stale value or another server's value |
| **Trust learnt too early** | Open admission remembered a name's key before the message verified | For every "learn on first sight" rule, send a message that fails a later check and confirm nothing was learnt |
| **Paths normalised away** | The tool registry reduced every path to its base name, so editing a folder tool would have written a root copy | Exercise every write path for objects that live outside the default location |
| **Order and time dependence** | A test passed alone and failed after another; another failed once the calendar moved on | Run the suite in random order and with a shifted clock; treat any order or date dependence as a bug |
| **Configuration resolved once** | A `${ENV:default}` placeholder was resolved at first load, so one test could pin a mode for the whole run | Change every switch at run time and confirm the next read sees it |
| **Lifecycles not closed** | A dropped caller left the host's stream open, so cancellation did not reach the tool | Drop every connection at every stage and confirm downstream work stops |
| **Event loop blocked** | A WebSocket call ran a slow tool on the event loop | Run slow and remote tools on every transport concurrently |
| **Flags cleared before the work** | The tool search marked its vector index fresh before the re-sync finished | Query during every background rebuild |
| **Text edited naively** | Redaction replaced digits inside other numbers | Feed redaction and screening values that overlap, repeat and nest |
| **Coverage silently skipped** | Deck tests were skipped for weeks because a package was missing from the test environment | Fail the gate when an expected test module is skipped for a missing dependency |
| **Dependency pins drifted** | `pip install -r requirements.txt` failed on conflicting pins | Install from a clean environment on every release |

## 3. Attack surfaces

### 3.1 The MCP endpoint, both eras

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Malformed JSON-RPC: wrong types, missing id, batch of thousands, deeply nested params | Spec error codes, no traceback, bounded memory | Property-based fuzzing (Hypothesis) against `/mcp` | P1 | `test_mcp_2026_07_28.py`, `test_mcp_2025_11_25.py` |
| Oversized and chunked bodies without `Content-Length` | 413 at `server.max_request_bytes` | Streaming client that never stops sending | P0 | `test_browser_hardening.py` |
| Protocol-version downgrade or mismatch between header and `_meta` | Refused with the spec error; no silent fallback to an older era | Matrix of header and meta combinations | P1 | MCP conformance suites |
| Session hijack: reuse or guess `Mcp-Session-Id`, fixation across users | Session bound to its user; another user's id refused | Two users, swapped ids | P0 | `test_mcp_2025_11_25.py` |
| MRTR `requestState` tampering, replay, replay by another user | Refused (`state_invalid`), nothing executed | Mutate signed state byte by byte | P0 | `test_net_mrtr.py` |
| Task ids guessed or read by another user; `tasks/cancel` on someone else's task | Not found for the other user | Enumerate ids as a second user | P1 | `test_mcp_2026_07_28.py` (tasks) |
| `notifications/cancelled` for another caller's request id | Ignored | Two clients, crossed ids | P1 | `test_transport_progress.py` |
| DNS rebinding and foreign `Origin` | Refused | Conformance `dns-rebinding-protection`, custom Origin matrix | P0 | conformance, `test_browser_hardening.py` |

### 3.2 Transports

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Slow tool on WebSocket with many concurrent calls on one socket | Calls overlap; the loop never blocks | Concurrency test with a sleeping tool | P0 | `test_transport_progress.py` |
| Disconnect at every stage (before, during, after the tool starts) on SSE, WebSocket, Streamable HTTP, stdio | The tool is cancelled, resources freed, no orphan threads | Kill the client at random points; count live threads after | P1 | `test_transport_progress.py` |
| Slowloris and idle connections, SSE reconnect storms | Bounded by timeouts and limits | Many idle sockets | P2 | none |
| stdio fed garbage, partial lines, binary | Error responses, process survives | Fuzz stdin | P2 | `test_stdio_transport.py` |

### 3.3 Credentials and sign-in

Plain credential storage and the shipped test admin key are owner decisions for intranet use (see the
Security Model); these attacks check that the switches and files behave exactly as documented, not
whether the decisions are wise.

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Precedence: the same key in `config/apikeys.json`, the database and `config/apikeys_db.json` with different states | The keys file wins, then the database, then the dump, exactly | Matrix of states across the three stores | P0 | `test_credential_files.py`, `test_api_keys_identity.py` |
| Test admin key with `sajhanet.test_admin_key.enabled: false` on the host but on at the home | Refused at the host; never published to the key directory | Two instances, mixed switches | P0 | `test_credential_files.py`, `test_net_three_instances.py` |
| `config/users.json` hand edit with an unknown role, a duplicate id, invalid JSON | Reported as a notice; never applied half-way | Mutation set | P1 | `test_credential_files.py` |
| Password brute force and lockout across several workers | Lockout holds across workers with a shared state store | Parallel attempts against two workers | P1 | `test_auth.py` |
| JWT `alg: none`, wrong key, expired, revoked after sign-out | Refused | Token mutation set | P0 | `test_auth.py`, `test_api_keys_identity.py` |
| SSO: replayed `state`, wrong `nonce`, `at_hash` mismatch, email-claim account takeover, open redirect on return | Refused; linking only as configured | Fake identity provider (as in `tests/test_sso.py`) | P0 | `test_sso.py` |
| CSRF on every state-changing console and JSON route | 403 for a foreign Origin or missing token | Route enumeration | P0 | `test_browser_hardening.py` |
| Credential file pages: reveal without being admin, reveal not audited | Refused; every reveal audited | As a user and an admin | P0 | `test_credential_files.py` |

### 3.4 Authorization and policy

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Reach a denied tool through another name: plain alias, qualified `net__instance__tool`, published `vendor__tool`, renamed name, a composite or workflow that wraps it | The same decision under every name | Generate every name form for each denied tool | P0 | `test_net_vendors.py` (either name), `test_policy.py` |
| An API key's tool list bypassed through Ask SAJHA, planners, LLM tools or the OpenAI-compatible endpoint | The key's ceiling applies inside every inner call | Key limited to one tool asks for another | P0 | `tests/ai/` |
| Approval bypass by retrying, by another worker, by a forwarded call | Approval required every time; forwarded calls refused | Retry loop, two workers | P1 | `test_policy.py` |
| Rate limits and quotas split across workers on the `memory` state backend | Documented as per process; exact with `redis` or `database` | Two workers each backend | P1 | `test_state_multiworker.py` |

### 3.5 SAJHA Net

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Open admission: claim an unused name from a rogue process on the network | Joins (documented trust of open mode); switch to `builtin_ca` closes it — confirm the console and Security Model say so | Rogue member script | P0 | `test_net_plugin_loading.py` (open mode) |
| Claim a held name with another key; forge, replay or reorder signed requests | `name_conflict`; signature, nonce and clock checks refuse | Mutation harness on `httpsig` | P0 | `test_net_signatures.py`, `test_net_identity.py` |
| Gossip poisoning: fake members, a dead record that re-teaches a forgotten key, records naming this server's own URL or key | Not added; self-recognition notice; forget means forgotten | Rogue gossip peer | P0 | `test_net_membership.py`, `test_net_vendors.py` |
| **Quarantine as denial of service**: publish a different contract for a popular tool name to quarantine it net-wide | Quarantine names the differing host; blocks and admission remove it; consider weighting (open item) | Rogue member offers a conflicting contract | P0 | `test_net_catalog.py` |
| Key directory poisoning: publish another home's key hash, expired or revoked keys | `key_not_from_home`, expiry and revocation hold | Directory mutation | P0 | `test_net_identity.py`, `test_net_keys.py` |
| Re-export and bridges: loops, hop and chain limits, identity escalation across nets | `loop`, `hop_limit`, `chain_limit`; a guest mapping never crosses | Three nets, cycles | P0 | `test_net_reexport_identity.py`, `test_net_planners_llm.py` |
| Assertion forgery, audience swap, token-exchange replay, unlisted identity on a bridge | `assertion_invalid`, `token_invalid`, refused | Mutation set | P0 | `test_net_reexport_identity.py` |
| Streamed events: inject, drop, reorder, duplicate, re-sign with another key, splice from another call, truncate, flood | Refused with the right reason; nothing after the bad event reaches the caller; stream closed | Man-in-the-middle connector | P0 | `test_net_stream_attacks.py` |
| Residency bypass through progress text, log events, input responses, redaction gaps, a re-export hop | Classified data never leaves; numbers-only progress | Classified tools on every path | P0 | `test_net_residency.py`, `test_transport_progress.py` |
| Per-member keys misused: a key sent to the wrong member, a key the member does not know | Refused; never replaced silently | Wrong targets | P1 | `test_net_three_instances.py` |

### 3.6 Proxied MCP servers

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Malicious upstream: prompt injection in tool descriptions, schema bombs, huge or slow-drip results, protocol violations | Descriptions screened and flagged; limits and timeouts hold; the breaker opens | A deliberately hostile fake MCP server | P0 | `test_federation.py` |
| Name games: an upstream naming its tools with `__`, a prefix equal to a local tool or another upstream | Prefix clash notice; names namespaced; nothing shadowed | Hostile configs | P1 | `test_federation_mcp_servers.py` |
| Proxy cycles through a server that is not SAJHA (it ignores the chain budget) | Bounded by timeouts (documented) | Two proxies pointing at each other through a plain server | P1 | `test_federation.py` (SAJHA cycle) |
| stdio command injection through `config/mcp_servers.json` arguments or environment | No shell interpretation; `allow_stdio` required | Hostile argument strings | P0 | `test_federation_mcp_servers.py` |
| Credentials in headers leaking into logs, audit, errors or the console | Never logged; raw secrets only raise a notice | Grep every output channel for a canary secret | P0 | none — add |

### 3.7 Tool folders and configuration loading

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| **Disable a tool by dropping a duplicate file** anywhere under `config/tools/` | Both copies disabled with a critical notice (owner rule): confirm the notice reaches operators and who may write the folder is controlled | Write a duplicate, watch the notice and the catalog | P1 | `test_tool_folders.py` |
| Folder names with `..`, symlinks, absolute paths, deeper nesting, unusual Unicode | Never loaded outside `config/tools`; deeper files ignored with a notice | Hostile tree in a temp dir | P0 | `test_tool_folders.py` (nesting) — add traversal and symlinks |
| Malformed, huge or endlessly nested JSON in a tool file | That tool fails with an error; the rest load | Mutation set | P1 | `test_tool_folders.py` |
| Hot reload during a write, object stores with delayed listing | No half-loaded tool; converges on the next check | Concurrent writer | P2 | `test_tool_folders.py` |
| A failing tool retried forever | Back-off up to the cap; no log flood | Permanently broken tool for an hour | P2 | `test_tool_folders.py` |

### 3.8 The intelligence layer

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Prompt injection through tool results, documents in RAG, remote tool results, web pages | Screening flags it; a destructive tool still needs confirmation; the answer cites sources | Poisoned fixtures | P0 | `tests/ai/` |
| Planner loops, step and tool-call budgets, cost exhaustion through LLM tools | Hard limits stop the run; budgets enforced | Adversarial mock model that never stops | P1 | `tests/ai/` |
| Conversation memory read or poisoned across users | Memory is per user | Two users | P0 | `tests/ai/` |
| OpenAI-compatible endpoint without a key, with another user's key, with a key limited to one tool | Refused or limited exactly as `/mcp` | Key matrix | P0 | `tests/ai/` |

### 3.9 MCP Studio and creators

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Import JSON naming an arbitrary Python class | Administrators only | As a creator role | P0 | `test_studio_access.py` |
| Script and Python tools escaping the sandbox (files, network, process limits) | Contained by the configured sandbox | Escape attempt suite | P0 | `test_sandbox.py` |
| SQL creators and OLAP: injection through arguments | Parameterised; refused | Injection corpus | P0 | `test_olap_sql_injection.py`, `test_duckdb_tools_sandbox.py` |
| API import: server URLs pointing at internal addresses (SSRF), a spec that reimports over another author's tools | Network guard; ownership enforced | Hostile specs | P0 | `tests/` api import tests |
| Editing a tool owned by another author | Refused | Two authors | P1 | `test_studio_access.py` |

### 3.10 The web console

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| XSS through tool names, descriptions, notice text, glossary, page help, upstream descriptions, remote catalogs | Escaped everywhere; CSP blocks inline script | Hostile strings in every field, Playwright looks for execution | P0 | `test_csp_handlers.py`, `test_browser_hardening.py` |
| Clickjacking, mixed content, cookie flags | `frame-ancestors`, Secure/HttpOnly/SameSite as configured | Header assertions | P1 | `test_browser_hardening.py` |
| Open redirects after sign-in or SSO | Only same-origin targets | Redirect corpus | P1 | `test_sso.py` |

### 3.11 Data connectors and outbound requests

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Fetch, crawler and REST tools pointed at the cloud metadata address, localhost, private ranges | Refused by the network guard where it applies; documented where it does not | URL corpus | P0 | `test_hardening.py` |
| Connector queries reading outside their allowlist | Refused | Hostile queries | P0 | connector tests |
| DuckDB reading local files | Refused | File path corpus | P0 | `test_duckdb_tools_sandbox.py` |

### 3.12 Resilience and exhaustion

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| The state store (Redis) disappears mid-call; the database goes away | Documented degradation; API keys still checked from the keys file and the dump | Kill the dependency during a load test | P1 | `test_state_multiworker.py` |
| Disk full while writing tool configs, audit or credential files | Atomic writes; no truncated files | Tiny tmpfs | P2 | none |
| Thousands of sessions, tasks or SSE listeners | Limits and expiry hold | Load script | P2 | none |

### 3.13 The test suite itself

| Attack | Safe behaviour | Automate | P | Existing coverage |
|---|---|---|---|---|
| Random test order | Same results | `pytest -p randomly` in a nightly job | P1 | none — add |
| Clock shifted by days and months | Same results | Freeze time at future dates | P1 | none — add |
| A dependency missing from the environment | The gate fails instead of skipping the area | Assert the expected test modules ran | P1 | none — add |
| Tests writing the developer's files | Never: tests use temporary paths | Watch `data/` and `config/` timestamps during the run | P1 | `tests/conftest.py` defaults |
| Clean install from `requirements.txt` | Resolves and starts | Fresh virtualenv in CI | P1 | none — add |

## 4. Execution

1. **Automate the P0 items first** in a dedicated test folder (an `adversarial` folder under the tests), reusing the harnesses
   that exist: the in-process nets of `tests/net/` (including the man-in-the-middle connector of
   `test_net_stream_attacks.py`), the fake identity provider of `test_sso.py`, and a new hostile MCP
   upstream server for 3.6.
2. **Add the suite-integrity checks of 3.13** to CI, so the next silently skipped area or
   date-dependent test fails loudly.
3. **Run exploratory sessions on the local lab** for each surface, one at a time, recording each finding
   as a reproduction and a failing test.
4. **Every release:** the P0 and P1 automated items, MCP conformance, the SAJHA Net conformance runner
   (`python -m sajha.net.conformance`), the console and mobile checks, and a clean install.

**Exit criteria for a release:** no open P0 finding; every P1 finding fixed or recorded in the
[Roadmap](Roadmap.md) with the owner's decision; every fixed finding has its regression test.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
