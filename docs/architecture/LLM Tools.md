# LLM Tools

> **Status: design, not built.** This note is the design for LLM tools: tools whose work is
> done by a language model, defined and governed like every other SAJHA tool. When it is
> built, this file becomes the as-built owner and the [Roadmap](Roadmap.md) item X7
> (Ask SAJHA over MCP, finished) is closed by it.

An **LLM tool** is an ordinary MCP tool (a name, a description, an input schema, an output
schema, a config file in `config/tools/`) whose `execute()` runs a language model instead of
a fixed piece of code. Depending on its *mode*, the model may use SAJHA's other tools, read
document search, keep a conversation, or only fill in a prompt. A caller (an MCP client, a
script over REST, a workflow, an A2A agent, the CLI) asks one question and gets back one
governed, structured answer.

`sajha_ask` already does a narrow version of this. This design generalises it into a tool
*type*, so an administrator can configure many LLM tools (an assistant, a summariser, a
classifier, an extractor, a grounded policy Q&A, a report writer) without writing code, and
every one of them goes through the same access rules, policy, audit, budgets, tests and
versions as any other tool.

---

## Contents

1. [Why build this](#1-why-build-this)
2. [Goals and non-goals](#2-goals-and-non-goals)
3. [Vocabulary](#3-vocabulary)
4. [How it fits SAJHA's tool framework](#4-how-it-fits-sajhas-tool-framework)
5. [The tool config](#5-the-tool-config)
6. [Modes](#6-modes)
7. [What happens on a call](#7-what-happens-on-a-call)
8. [Identity and access](#8-identity-and-access)
9. [Conversation memory](#9-conversation-memory)
10. [Recursion and composition](#10-recursion-and-composition)
11. [Models, sampling, budgets and limits](#11-models-sampling-budgets-and-limits)
12. [Safety](#12-safety)
13. [Results and errors](#13-results-and-errors)
14. [Observability and audit](#14-observability-and-audit)
15. [Testing and quality](#15-testing-and-quality)
16. [Moving `sajha_ask` onto the new type](#16-moving-sajha_ask-onto-the-new-type)
17. [Schema and configuration changes](#17-schema-and-configuration-changes)
18. [Build plan](#18-build-plan)
19. [Decisions for the owner](#19-decisions-for-the-owner)
20. [Alternatives considered](#20-alternatives-considered)

---

## 1. Why build this

**What MCP assumes.** In MCP the client owns the model and the server supplies tools. The
client's model reads the catalog, picks tools, calls them and writes the answer. That works
well for a capable desktop client. It works badly for:

- **thin callers**: a script, a scheduled workflow, a REST integration or another agent that
  has no model of its own, or only a weak one;
- **governed answers**: an organisation that wants one tested way of answering a class of
  question (which tools, which model, which prompt, which limits) rather than each client
  improvising;
- **key custody**: callers that must not hold model-provider keys;
- **cost control**: a model choice, budget and cache decided centrally, per tool.

**What other servers do.** Most MCP servers are tool providers only; reasoning stays in the
client. MCP itself has the opposite direction built in: *sampling* lets a server borrow the
client's model. Agent frameworks commonly offer "an agent as a tool". Some gateways and
hosted products expose a single "ask" or "agent" endpoint. This note makes no claim about
any specific product; the comparison page (`sajha/web/competitive.py`) is where such a
claim would go, with a source, once checked.

**What SAJHA already has.** The intelligence layer ([Intelligence Layer](Intelligence%20Layer.md))
has a model gateway with aliases, fallback, budgets, cache and policy; four planners;
semantic tool shortlisting; conversation memory; document search; and the `sajha_ask` tool
(`sajha/ai/ask_tool.py`, off by default through `ai.ask.mcp_tool_enabled`). The gap is that
`sajha_ask` is hand-coded, runs as a fixed identity, has no memory over MCP and is the only
one of its kind.

**The cost of the idea.** When an MCP client with its own model calls an LLM tool, two models
run in sequence. That costs latency and money, and the two can disagree. Section 11 answers
this with sampling (use the client's model when it offers one) and with modes that need no
tool planning at all.

---

## 2. Goals and non-goals

**Goals**

- G1. One generic tool type, configured in JSON like every other tool; no Python per tool.
- G2. A small set of *modes* that cover the common kinds of model interaction.
- G3. Every inner tool call runs as the caller, with the caller's access, never more.
- G4. Optional conversation memory addressed by an explicit handle, bounded in RAM and disk.
- G5. The same governance as other tools: access rules, policy engine and approvals,
  tamper-evident audit, budgets, metrics, tool quality tests, evals, versions and canary.
- G6. Works offline on the mock model, so tests and demos need no key.
- G7. Works on both protocol eras and for non-MCP callers (REST, CLI, workflows, A2A).

**Non-goals**

- A general agent runtime with long-running autonomous loops. LLM tools are bounded calls;
  long multi-step processes belong in [Workflows](Workflows.md).
- Fine-tuning, model hosting or a prompt marketplace.
- Replacing the client's model. An LLM tool is an option a client chooses to call.
- Writing data through a model without confirmation. Destructive inner calls always stop
  for confirmation (section 8).

---

## 3. Vocabulary

These terms go into `GLOSSARY.md` when the feature is built (the glossary is the only place
definitions live).

| Term | Meaning |
|---|---|
| LLM tool | A tool whose `execute()` runs a model according to an `llm` block in its config. |
| Mode | What kind of model interaction an LLM tool performs (section 6). |
| Inner call | A call an LLM tool makes to another tool while answering. |
| Conversation handle | The `conversation_id` an LLM tool returns and accepts, naming stored context. |
| Client history | Earlier turns the caller sends in the `messages` argument instead of a handle. |
| Sampling | MCP's mechanism for a server to ask the client's model for a completion. |
| Depth | How many LLM tools are nested in the current call chain. |

---

## 4. How it fits SAJHA's tool framework

An LLM tool is a normal entry in the tool registry:

| Framework piece | How an LLM tool uses it |
|---|---|
| Config file | `config/tools/<name>.json`, same top-level shape as any tool, plus an `llm` block. |
| Implementation | One generic class, `sajha.ai.llm_tools.LLMTool` (a `BaseMCPTool`), named in `implementation`. Like the generic REST and database tools, the behaviour comes from config. |
| Schemas | `inputSchema` and `outputSchema` are JSON Schema 2020-12, authored per tool. Each mode adds the fields it needs (section 6) and the loader checks they are present. |
| Annotations | Derived, never trusted from config: `readOnlyHint` is true only if every tool the LLM tool may call is read-only; `destructiveHint` is true if any may be destructive; `openWorldHint` is true if any reaches outside the server. A config that claims less is corrected and the lint flags it. |
| Registry and reload | Loaded by `ToolsRegistry`; hot reload picks up edits; a broken `llm` block fails that tool's load only. |
| Access | Visible and callable under the same rules as any tool (roles, API-key tool patterns, `mcp.anonymous.*`). |
| Policy engine | Every call to the LLM tool and every inner call is evaluated (allow, deny, redact, require approval, rate limit). |
| Audit and metrics | The LLM tool call is one record; each inner call is its own record linked to it (section 14). |
| Tool quality | Test cases, cassettes, lint, probes, evals, versions and canary apply unchanged ([Tool Quality](Tool%20Quality.md)). |
| Studio | A new creator, "LLM tool", writes the config file; Describe a tool can propose one ([Tool Generation](Tool%20Generation.md)). |
| Composition and workflows | Composites and workflow steps can call an LLM tool like any other tool, subject to the depth rule (section 10). |

Server-wide settings live under a new `ai.llm_tools.*` section (section 17). They are
**ceilings**: a tool config can ask for less, never more.

---

## 5. The tool config

A complete example, an assistant over market and macro tools with memory:

```json
{
  "name": "markets_assistant",
  "implementation": "sajha.ai.llm_tools.LLMTool",
  "description": "Answers questions about markets and the economy using SAJHA's market-data and central-bank tools. Cites the tools it used. Pass conversation_id from a previous answer to ask a follow-up.",
  "version": "1.0.0",
  "enabled": true,
  "inputSchema": {
    "type": "object",
    "properties": {
      "question":        {"type": "string", "description": "The question, in plain words."},
      "conversation_id": {"type": "string", "description": "From a previous answer, to continue that conversation."},
      "confirm":         {"type": "array", "items": {"type": "string"}, "description": "Fingerprints of destructive calls the user confirmed."}
    },
    "required": ["question"]
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "answer":          {"type": "string"},
      "confidence":      {"type": "number"},
      "citations":       {"type": "array", "items": {"type": "string"}},
      "conversation_id": {"type": "string"},
      "stopped_by":      {"type": "string"}
    },
    "required": ["answer", "stopped_by"]
  },
  "llm": {
    "mode": "answer",
    "model": "reasoning",
    "planner": "react",
    "system_prompt": "You answer questions about markets for analysts. Prefer primary sources. Say when data is missing.",
    "tools": { "allow": ["fred_*", "yahoo_*", "calc_*", "sajha_search_docs"], "deny": ["*_delete*"] },
    "limits": { "max_steps": 6, "max_tool_calls": 10, "timeout_s": 60, "max_output_tokens": 1200, "max_cost_usd": 0.20 },
    "memory": { "mode": "conversation", "ttl_minutes": 1440, "max_turns": 20, "on_overflow": "summarise" },
    "sampling": "never",
    "output": { "citations": true, "steps": false }
  },
  "annotations": {},
  "metadata": { "category": "Intelligence", "tags": ["assistant", "markets"] }
}
```

### 5.1 The `llm` block

| Key | Type | Default | Meaning |
|---|---|---|---|
| `mode` | string | required | `answer`, `complete`, `extract`, `classify`, `grounded`, `narrate`, `judge` (section 6). |
| `model` | string | `ai.llm_tools.default_model` | A gateway alias (`default`, `fast`, `reasoning`, ...) or `provider/model`. Aliases are preferred so operators can re-point them. |
| `planner` | string | `ai.ask.planner` | `answer` mode only: `react`, `plan_execute`, `recipes`, `router`. |
| `system_prompt` | string | none | Instructions for the model. Mutually exclusive with `prompt`. |
| `prompt` | object | none | `{ "name": "<prompt in the prompts registry>", "arguments": { "<arg>": "{{input.field}}" } }`. Reuses SAJHA prompts instead of inline text. |
| `template` | string | none | `complete`, `extract`, `classify`, `judge`: the user message, with `{{input.<field>}}` placeholders filled from validated arguments. |
| `tools.allow` / `tools.deny` | string[] | `[]` / `[]` | Glob patterns of tools the model may call. Empty `allow` means no tools. Intersected with the caller's own access (section 8). |
| `rag.sources` | string[] | none | `grounded` mode (optional elsewhere): document-search sources to read. |
| `limits.*` | numbers | `ai.llm_tools.*` | `max_steps`, `max_tool_calls`, `timeout_s`, `max_input_chars`, `max_output_tokens`, `max_cost_usd`. Clamped to the server ceilings. |
| `memory.*` | object | `{ "mode": "none" }` | Section 9. |
| `sampling` | string | `never` | `never`, `prefer`, `require` (section 11). |
| `output.citations` / `output.steps` | bool | `true` / `false` | Whether the result carries citations and a step trace. |
| `confirm` | string | `ask` | `ask` (stop and request confirmation for destructive inner calls) or `refuse` (never run them). |
| `nesting` | object | `{ "allow": false }` | Section 10. |

### 5.2 Load-time validation

The loader refuses a tool (and lint reports it) when:

- `mode` is unknown, or a key belongs to another mode (for example `planner` on `classify`);
- the input schema lacks a field the mode needs (`question` for `answer` and `grounded`,
  the fields referenced by `template` placeholders for the others);
- the output schema is incompatible with the mode (for example `classify` without an enum
  `label` field);
- a `prompt.name` does not exist in the prompts registry;
- `tools.allow` matches no tool at all (a typo would otherwise silently give the model nothing);
- a limit is not a positive number.

---

## 6. Modes

Each mode is a small, testable strategy. All share the pipeline in section 7.

### 6.1 `answer`: plan, call tools, compose

The general assistant. The question is condensed with conversation context (if any), tools are
shortlisted from those allowed, the configured planner decides calls, results are composed
into an answer with confidence and citations. This is what `sajha_ask` does today.

- Input: `question` (required), `conversation_id`, `messages`, `confirm`.
- Output: `answer`, `confidence`, `citations`, `stopped_by`, `conversation_id`, optional `steps`.

### 6.2 `complete`: a prompt, no tools

Fill a template or registry prompt from the arguments and return the model's text. For
summarise, rewrite, translate, draft.

- Input: whatever fields the template names.
- Output: `text` (and `stopped_by`).
- `tools.allow` must be empty; the loader enforces it.

### 6.3 `extract`: structured output

The model must return JSON that validates against the tool's `outputSchema`. SAJHA asks for
structured output where the provider supports it, validates the reply, and on failure retries
once with the validation errors in the prompt. A second failure returns an error result; SAJHA
never returns unvalidated JSON as structured content.

- Input: the text or fields to extract from.
- Output: the schema's fields.

### 6.4 `classify`: one label from a fixed set

The output schema's `label` is an enum; the model must choose one of its values (plus an
optional `reason` and `confidence`). An answer outside the enum is a failure, not a guess.
Suitable for routing, tagging, triage.

### 6.5 `grounded`: answer only from documents

Retrieve passages from the configured document-search sources, answer only from them, cite each
claim's passage, and say "not found in the sources" rather than use model knowledge. No other
tools. The answer is checked: a sentence without a citation lowers confidence; no retrieved
passage means `stopped_by: no_sources`.

### 6.6 `narrate`: fixed data, model-written prose

Run a named composite or workflow (deterministic), then give its result to the model only to
write the narrative. The model cannot choose tools, so the numbers are reproducible and the
model's role is limited to wording.

- Config: `llm.source: { "composite": "<name>" }` or `{ "workflow": "<id>" }`, plus `template`.
- Output: `text`, and the source's structured result unchanged under `data`.

### 6.7 `judge`: score against a rubric

Given inputs and a rubric (from config), return per-criterion scores and an overall verdict,
validated against the output schema. Used for review, quality gates and evals. A judge never
calls tools.

---

## 7. What happens on a call

```
caller ── tools/call markets_assistant {question, conversation_id?}
   │
   ├─ 1. Normal tool path: access check, policy (call), argument validation
   ├─ 2. Resolve the caller (sajha/observability/caller.py) and the depth (section 10)
   ├─ 3. Load context: conversation (by handle, owned by caller) or client messages
   ├─ 4. Budget pre-check: caller's token budget, tool's max_cost_usd
   ├─ 5. Mode strategy:
   │       answer   → condense → shortlist(allowed ∩ caller-visible) → planner loop
   │                     └─ each inner call: normal tool path as the caller
   │       complete/extract/classify/judge → render template → model → validate
   │       grounded → document search → model → citation check
   │       narrate  → run composite/workflow as caller → model writes text
   ├─ 6. Validate the result against outputSchema
   ├─ 7. Store the turn (if memory is on), return conversation_id
   └─ 8. Audit + metrics + usage ledger; return structuredContent (+ text for older clients)
```

Progress (`notifications/progress`) is reported at each planner step when the request asked
for it, and cancellation stops the loop between steps, through the existing per-call tool
context (`sajha/core/mcp_tool_context.py`).

---

## 8. Identity and access

**Run as the caller.** The tool reads the caller from the context variable in
`sajha/observability/caller.py`, which the MCP handlers, the REST execute endpoint and the
ask service already set, and which follows the call into worker threads. Every inner call is
made through the normal tool path *as that caller*, so:

- the tools the model can call are `tools.allow − tools.deny`, **intersected** with what the
  caller may see and call (roles, API-key tool patterns, anonymous policy);
- policy rules for the caller apply to each inner call (deny, redact, approval, rate limit);
- connected-account tokens injected into inner calls are the caller's own.

An LLM tool can therefore never give a caller more than the caller already has. This replaces
today's fixed `mcp:sajha_ask` identity.

**Anonymous callers.** Allowed only if the anonymous policy lets them see the LLM tool. They
get no stored memory (section 9) and the tightest limits (`ai.llm_tools.anonymous.*`).

**Destructive inner calls.** With `confirm: ask`, a destructive call stops the run and returns
`stopped_by: needs_confirmation` with the call's fingerprint. On the 2026-07-28 path this is an
MRTR round trip (the tool raises `InputRequired`, the client answers, the call is retried with
the answer); on the older era and REST, the caller passes the fingerprint back in `confirm`.
With `confirm: refuse`, destructive tools are removed from the allowed set entirely.

---

## 9. Conversation memory

### 9.1 Modes

| `memory.mode` | Who keeps the context | Use for |
|---|---|---|
| `none` (default) | Nobody; each call stands alone | classify, extract, judge, narrate |
| `conversation` | SAJHA, addressed by `conversation_id` | assistants, chat front-ends, thin clients |
| `client` | The caller, in `messages: [{role, content}]` | clients that keep their own history or must not leave data on the server |

`conversation` and `client` can both be enabled (`accept_client_history: true`); if a call
carries both, the stored conversation wins and `messages` is ignored, with a note in the result.

### 9.2 The handle

- No `conversation_id` in the call: SAJHA creates a conversation and returns its id.
- A valid id the caller owns: SAJHA continues it.
- An id that does not exist, has expired, belongs to someone else or to another tool: the
  same answer every time, `conversation not found` (never "forbidden", which would confirm it
  exists). The caller can start again without one.
- The id is a random UUID; it grants nothing by itself, because every read is filtered by the
  owner.

Why a handle and not the MCP session: the 2026-07-28 era has no sessions, sessions do not
survive several workers without shared state, and REST, CLI, workflow and A2A callers have no
MCP session at all. An explicit argument works for all of them.

### 9.3 Where it is stored

The existing conversation store (`sajha/ai/memory.py`), used today by the Ask SAJHA page:

- `ai_conversations`: one row per conversation: owner, title, running summary, turn count,
  timestamps;
- `ai_conversation_turns`: one row per turn: question, standalone rewrite, answer (clipped),
  tool *names* used, `stopped_by`, confidence.

Each call builds the model's context from the summary plus the last `ai.memory.history_turns`
turns verbatim, and condenses a follow-up into a standalone question so tool shortlisting
works. LLM tools add a `tool_name` and an `expires_ts` to the conversation row (section 17), so
each tool's conversations are separate and each can expire on its own schedule.

### 9.4 Bounding RAM

Nothing is held in process memory between calls. A call reads one conversation row and at most
`history_turns` turn rows, uses them, writes one turn row, and lets them go. Memory use is per
request and bounded by the clip sizes below; it does not grow with the number of users or
conversations. With the database as the store, several workers and restarts see the same
conversations.

### 9.5 Bounding disk

| Bound | Where it is set | Status |
|---|---|---|
| Store words, not data: question, answer and tool names only; raw tool results are never written to the conversation tables (the audit log records the calls) | design rule | already true today |
| Each stored answer clipped to `max_turn_chars`; questions clipped likewise | `ai.memory.max_turn_chars` | answers today; questions added |
| Summary clipped to `summary_max_chars` | `ai.memory.summary_max_chars` | today |
| Turns per conversation: beyond `memory.max_turns`, older turns are folded into the summary and their rows deleted, so a conversation is at most summary + N turns | per tool, ceiling `ai.llm_tools.memory.max_turns` | new |
| Idle expiry per tool: `memory.ttl_minutes` sets `expires_ts`; renewed on each turn | per tool, ceiling `ai.memory.retention_days` | new |
| Conversations per user (oldest deleted first) | `ai.memory.max_conversations_per_user` | today |
| Conversations per user per tool | `ai.llm_tools.memory.max_conversations_per_tool` | new |
| Scheduled purge: expired conversations deleted by a periodic job that fires once across workers (the same claim mechanism workflow cron and probes use), instead of only opportunistically when someone writes | `ai.llm_tools.memory.purge_interval_minutes` | new (today: at most hourly, on write) |
| No storage for anonymous callers | design rule | new |
| Users delete their own history | `DELETE /api/ai/conversations` | today |

Worst case per user is therefore *conversations per user × (summary + max_turns × 2 × clip
size)*, a number an operator can compute from config.

### 9.6 Visibility

- Metrics: stored conversations and turns per tool, purged per run, summarisations
  (`sajha_llm_tool_conversations`, `sajha_llm_tool_turns_total`, `sajha_llm_tool_purged_total`).
- The existing conversations API and a page listing a user's own conversations per tool
  (roadmap X7 asks for that page).
- Retention appears in the Configuration Reference; the Security Model records that stored
  answers can contain data from tool results and how long they are kept.

---

## 10. Recursion and composition

An LLM tool may call another LLM tool only if both allow it:

- the caller's config has `nesting.allow: true` and lists the callee in `tools.allow`;
- the current depth is below `ai.llm_tools.max_depth` (default 2).

Depth is a context variable, like the workflow engine's `CHAIN` (`sajha/workflows/engine.py`):
it holds the names of the LLM tools in the current chain. A tool already in the chain is never
called again (no cycles). Composites and workflows that call LLM tools carry the same context,
so the rule holds through every path. Budgets are shared down the chain: an inner LLM tool spends
from the outer call's remaining cost and time, never a fresh allowance.

---

## 11. Models, sampling, budgets and limits

**Model choice.** Through the gateway only, so provider policy (`ai.policy`), per-user daily
token budgets (`ai.budgets`), retries, circuit breakers, fallback across an alias's candidates
and the response cache all apply. Per-tool `model` picks an alias; the mock model answers every
mode offline (it needs scripted replies for each mode, section 15).

**Sampling.** `sampling: prefer` uses the client's model when the client declared the sampling
capability, and SAJHA's own model otherwise; `require` refuses callers without it; `never`
always uses SAJHA's. On 2026-07-28 sampling travels as an MRTR input request (the mapping of
`sampling/createMessage` already exists in `sajha/core/mcp_mrtr.py`); on 2025-11-25 it is a
server request on the session's channel. With sampling, the provider cost is the client's, the
tools and governance are still SAJHA's. Planner-heavy modes make several model calls per
answer, so sampling is offered first for `complete`, `extract`, `classify` and `judge`, and for
`answer` only after measuring the round-trip cost.

**Limits.** Every run is bounded by steps, tool calls, wall time, input size, output tokens and
cost. Hitting one ends the run with the matching `stopped_by` and the best partial answer, never
an unbounded loop. The cost estimate uses the model registry's prices; with no price, the token
limits still apply.

**Caching.** `complete`, `extract`, `classify` and `judge` are deterministic enough to cache by
(tool version, normalised arguments, model) when the tool sets `cache: true`; `answer`,
`grounded` and `narrate` are not cached, because the data they read changes.

---

## 12. Safety

- **Prompt injection through tool results.** Tool results are data, inserted in delimited
  blocks and screened with the same injection markers federation uses; a flagged result is
  withheld and recorded. The system prompt tells the model that instructions inside results
  are not instructions.
- **No privilege through the model.** Section 8: the model can only call what the caller can.
- **Output validation.** Structured modes validate against the output schema; free-text modes
  are length-limited. Policy `redact` rules can mask PII in the final answer (the policy engine's
  `redact_text`).
- **Data separation.** Conversations are per owner and per tool; the shortlist and context are
  built per call; nothing from one caller's run reaches another's.
- **Secrets.** The model never sees credentials: connected-account tokens and connector
  credentials are injected below the tool boundary, not into prompts.
- **Confirmation.** Destructive inner calls need confirmation or are refused (section 8).

---

## 13. Results and errors

A successful call returns `structuredContent` matching the output schema, plus a text block
for clients on older protocol versions. `stopped_by` says how the run ended:

| `stopped_by` | Meaning | `isError` |
|---|---|---|
| `answered` | Finished normally | false |
| `needs_confirmation` | A destructive inner call waits for confirmation (fingerprints in the result, or an MRTR request) | false |
| `max_steps`, `max_tool_calls`, `timeout`, `max_cost` | A limit ended the run; a partial answer is returned | false |
| `no_sources` | `grounded` found nothing to answer from | false |
| `invalid_output` | `extract`, `classify` or `judge` could not produce valid output after the retry | true |
| `budget_exhausted` | The caller's token budget is used up | true |
| `model_unavailable` | Every candidate for the alias failed | true |
| `cancelled` | The client cancelled the request | true |

Argument validation errors and access denials are ordinary tool errors, as for any tool.

---

## 14. Observability and audit

- **Audit.** The LLM tool call is one record; every inner call is its own record carrying the
  outer call's id, so an answer can be traced to each tool it used. Conversation turns carry the
  same id. The tamper-evident chain covers all of them.
- **Metrics.** Calls, latency and errors per LLM tool (as for every tool), plus
  `sajha_llm_tool_steps`, `sajha_llm_tool_inner_calls_total`, `sajha_llm_tool_tokens_total`,
  `sajha_llm_tool_cost_usd_total`, `sajha_llm_tool_stopped_total{reason}`, and the memory
  metrics in section 9.6.
- **Usage ledger.** Tokens and cost per caller, per LLM tool, per model, in the existing usage
  and cost pages.
- **Tracing.** One span per call with child spans per model call and inner tool call (OTLP).

---

## 15. Testing and quality

- **Mock scripts per mode.** The mock model gets scripted replies for each mode (plan steps,
  extraction JSON, labels, rubric scores), so every mode is tested offline and in CI.
- **Unit tests per mode**: validation, retries, enum enforcement, citation checks, limits,
  stop reasons.
- **Identity tests**: a caller without access to a tool cannot reach it through an LLM tool; an
  API key restricted to a pattern stays restricted; anonymous callers store nothing.
- **Memory tests**: handle lifecycle, cross-owner and cross-tool isolation, `max_turns` folding,
  expiry, purge firing once across two workers, `client` history.
- **Recursion tests**: depth limit, cycle refusal, budget sharing.
- **Tool-quality cases**: each shipped LLM tool has test cases in its config, runnable with
  `python -m sajha.quality test`.
- **Evals**: an eval set per shipped LLM tool (`config/evals/`), so a model or prompt change is
  measured before it is promoted, and a canary version can be compared with the stable one.
- **Conformance**: both suites stay green; LLM tools are ordinary tools to the protocol.

---

## 16. Moving `sajha_ask` onto the new type

`sajha_ask` becomes a config file in `config/tools/` (to be added) with `mode: answer`, the current input and
output fields, and `memory.mode: conversation`. `sajha/ai/ask_tool.py` is reduced to a
compatibility shim and then removed. Behaviour changes, listed in the CHANGELOG as operator
notes:

- it runs as the caller instead of a fixed identity, so it can reach exactly what the caller
  can (often more than before for signed-in users, never more than they have);
- `ai.ask.mcp_allowed_tools` becomes the tool's `tools.allow`;
- `ai.ask.mcp_tool_enabled` keeps working as the on/off switch for this one tool until the next
  major release, then becomes the tool's `enabled`.

The Ask SAJHA page keeps using the intelligence service directly; the tool and the page share
the same pipeline.

---

## 17. Schema and configuration changes

**Database** (no migrations: both schema files change together, `tests/test_db_schema.py`
enforces it; SAJHA runs no DDL on PostgreSQL):

- `ai_conversations`: add `tool_name VARCHAR(200)` (null for Ask SAJHA page conversations) and
  `expires_ts REAL` (null means the global retention applies); add an index on
  `(user_id, tool_name, updated_ts)` and one on `expires_ts`.
- Operator action for existing databases, in the CHANGELOG: run the two `ALTER TABLE ... ADD
  COLUMN` statements and the two `CREATE INDEX` statements from the schema file (PostgreSQL by
  the operator; SQLite likewise, since the start-up check refuses a database with missing
  columns, as in roadmap item N2).

**Configuration** (`config/application.yml`, documented in the Configuration Reference):

```yaml
ai:
  llm_tools:
    enabled: true                 # the tool type; each tool still has its own "enabled"
    default_model: default
    max_depth: 2
    limits:                       # ceilings; a tool may ask for less
      max_steps: 8
      max_tool_calls: 16
      timeout_s: 120
      max_input_chars: 20000
      max_output_tokens: 4000
      max_cost_usd: 1.00
    anonymous:
      enabled: false              # anonymous callers may call LLM tools at all
      max_steps: 3
      max_cost_usd: 0.02
    memory:
      max_turns: 50
      max_conversations_per_tool: 50
      purge_interval_minutes: 15
```

---

## 18. Build plan

Each step ends green: full suite, both conformance suites, mobile check for any page.

| Step | Scope | Gate |
|---|---|---|
| 1 | Caller identity for inner calls and the depth context; `sajha_ask` runs as the caller | identity and recursion tests |
| 2 | `LLMTool`, config validation, modes `answer`, `complete`, `extract`, `classify`; derived annotations; lint rules | mode tests on the mock |
| 3 | Memory: handle, `tool_name`/`expires_ts` columns in both schema files, turn folding, scheduled purge, `client` history, metrics | memory tests incl. two workers |
| 4 | Modes `grounded`, `narrate`, `judge`; caching for deterministic modes | mode tests |
| 5 | `sajha_ask` moved onto the type; shipped examples (an assistant, a summariser, a classifier, a grounded docs Q&A); eval sets | evals pass on the mock |
| 6 | Studio "LLM tool" creator and Describe-a-tool proposals; conversations page | page tests, mobile check |
| 7 | Sampling (`prefer`, `require`) on both eras, starting with non-planner modes | protocol tests, conformance |
| 8 | Docs: this note becomes as-built; glossary terms; tutorial; Configuration and API Reference; Security Model; help card; CHANGELOG | doc-rot tests |

---

## 19. Decisions for the owner

1. **Default state.** Ship the type enabled with no LLM tools except `sajha_ask` (still off by
   default), or ship the examples enabled? Recommended: type on, examples off.
2. **Anonymous access.** Off by default (recommended), since every call spends model budget.
3. **Sampling.** In this build (step 7) or later?
4. **Modes.** The seven in section 6, or others to add (for example a `translate` preset of
   `complete`, or a `compare` preset of `judge`)?
5. **Who may create LLM tools.** Studio users (the `studio` permission), or administrators only,
   given they spend model budget?

---

## 20. Alternatives considered

| Alternative | Why not |
|---|---|
| One `sajha_ask` tool with many optional parameters | Every caller re-specifies the prompt, tools and limits; nothing is governed or tested per use; the schema becomes vague. |
| A Python class per LLM tool | Contradicts the config-driven framework; every change needs a deploy; Studio cannot create them. |
| Memory keyed by the MCP session | No sessions on 2026-07-28; breaks across workers; useless to REST, CLI, workflow and A2A callers. |
| Memory held in process RAM | Lost on restart, wrong with several workers, unbounded under load. |
| Store full tool results with each turn | Disk grows with data volume; results may hold data the audit log already records under its own retention. |
| Always use the client's model (sampling only) | Thin callers have no model; servers cannot rely on clients declaring sampling; governance of the model choice is lost. |
