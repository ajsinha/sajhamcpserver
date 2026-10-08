# LLM Tools

> **Status: built (Implementation Plan waves 2 and 3), with the gaps each section names.** This
> note owns LLM tools: tools whose work is done by a language model, defined and governed like
> every other SAJHA tool, the configuration-driven planners they run, and the memory tiers that
> keep them within bounds. **Built:** the `LLMTool` type (`sajha/ai/llm_tools/`) with all seven
> modes, load-time validation, derived annotations and lint rules; running as the caller with
> depth and shared budgets; conversation memory; resource safety (working set, spool, admission,
> memory guard, caches); caching of deterministic modes; `sajha_ask` on the type; shipped example
> tools (disabled) with eval sets; sampling for `complete`, `extract`, `classify` and `judge`
> (section 12); SAJHA as an OpenAI-compatible endpoint (section 13.4); configurable planners
> (section 9: `sajha/ai/planners_engine/`, the shipped files in `config/planners/`, the
> [Planner Reference](Planner%20Reference.md)); the Studio LLM tool creator, the planner editor
> with dry run, Describe-a-tool LLM proposals and the Conversations page; and, in wave 5, remote
> LLM tools across a SAJHA Net. **Not built yet:** sampling for the other modes, and the other
> items sections mark *Not built yet*. A walk-through is
> [Tutorial 26](../tutorials/TUTORIAL_26_build_an_llm_tool.md).

> **Across SAJHA servers.** [SAJHA Net](SAJHA%20Net.md) builds on this design: LLM tools are
> shared between instances like any tool and run, plan and spend model budget on the instance
> that hosts them; conversation memory always stays on the caller's own instance; and planners
> see remote tools with their location, health and data classes (SAJHA Net, section 13).

An **LLM tool** is an ordinary MCP tool (a name, a description, an input schema, an output
schema, a config file in `config/tools/`) whose `execute()` runs a language model instead of
a fixed piece of code. Depending on its *mode*, the model may use SAJHA's other tools, read
document search, keep a conversation, or only fill in a prompt. A caller (an MCP client, a
script over REST, a workflow, an A2A agent, the CLI) asks one question and gets back one
governed, structured answer.

`sajha_ask` was the first, narrow version of this. This design generalises it into a tool
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
9. [Planners](#9-planners)
10. [Conversation memory](#10-conversation-memory)
11. [Recursion and composition](#11-recursion-and-composition)
12. [Models, sampling, budgets and limits](#12-models-sampling-budgets-and-limits)
13. [The model interface: OpenAI-style, for portability](#13-the-model-interface-openai-style-for-portability)
14. [Safety](#14-safety)
15. [Results and errors](#15-results-and-errors)
16. [Observability and audit](#16-observability-and-audit)
17. [Testing and quality](#17-testing-and-quality)
18. [Moving `sajha_ask` onto the new type](#18-moving-sajha_ask-onto-the-new-type)
19. [Schema and configuration changes](#19-schema-and-configuration-changes)
20. [Build plan](#20-build-plan)
21. [Decisions for the owner](#21-decisions-for-the-owner)
22. [Alternatives considered](#22-alternatives-considered)

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
run in sequence. That costs latency and money, and the two can disagree. Section 12 answers
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
- G8. Planners are configuration: ReAct, Reflect, plan-and-execute, self-consistency, map-reduce,
  routing and loops are expressed as bounded graphs of stages, not code.
- G9. No load can take the process down: memory is bounded per call and per process, large data
  spills to disk, and excess work is queued or refused.
- G10. Portable model interface: providers, models and the gateway speak the OpenAI Chat
  Completions format, and SAJHA can offer that API outward (section 13).

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
| Planner | The strategy an LLM tool follows: a bounded graph of stages defined in configuration (section 9). |
| Stage | One unit of planner work from a fixed library (act, plan, critique, verify, ...), ending in a typed outcome. |
| Bounded edge | A planner transition that may loop back, with a maximum number of visits and a destination when it is reached. |
| Spool | Per-run files on local disk that hold large in-flight payloads instead of process memory. |
| Canonical format | The OpenAI Chat Completions request and response shapes that every SAJHA model call uses (section 13). |
| Memory guard | The watchdog that slows, refuses or ends LLM-tool runs before the process runs out of memory. |

---

## 4. How it fits SAJHA's tool framework

An LLM tool is a normal entry in the tool registry:

| Framework piece | How an LLM tool uses it |
|---|---|
| Config file | `config/tools/<name>.json`, same top-level shape as any tool, plus an `llm` block. |
| Implementation | One generic class, `sajha.ai.llm_tools.LLMTool` (a `BaseMCPTool`), named in `implementation`. Like imported API tools (`ImportedAPITool`) and data-connector tools (`ConnectorTool`), the behaviour comes from config. |
| Schemas | `inputSchema` and `outputSchema` are JSON Schema 2020-12, authored per tool. Each mode adds the fields it needs (section 6) and the loader checks they are present. |
| Annotations | Derived, never trusted from config: `readOnlyHint` is true only if every tool the LLM tool may call is read-only; `destructiveHint` is true if any may be destructive; `openWorldHint` is true if any reaches outside the server. A config that claims less is corrected and the lint flags it. |
| Registry and reload | Loaded by `ToolsRegistry`; hot reload picks up edits; a broken `llm` block fails that tool's load only. |
| Access | Visible and callable under the same rules as any tool (roles, API-key tool patterns, `mcp.anonymous.*`). |
| Policy engine | Every call to the LLM tool and every inner call is evaluated (allow, deny, redact, require approval, rate limit). |
| Audit and metrics | The LLM tool call is one record; each inner call is its own record linked to it (section 16). |
| Tool quality | Test cases, cassettes, lint, probes, evals, versions and canary apply unchanged ([Tool Quality](Tool%20Quality.md)). |
| Studio | A new creator, "LLM tool", writes the config file; Describe a tool can propose one ([Tool Generation](Tool%20Generation.md)). |
| Planners | A planner registry loads planner files from `config/planners/<name>.yaml` with the same loading, reload, lint and versioning as tools (section 9). |
| Composition and workflows | Composites and workflow steps can call an LLM tool like any other tool, subject to the depth rule (section 11). |

Server-wide settings live under a new `ai.llm_tools.*` section (section 19). They are
**ceilings**: a tool config can ask for less, never more.

*Built, with these differences from the table.* The modules are `sajha/ai/llm_tools/config.py`
(settings, the `llm` block, validation, derived annotations, lint), `tool.py` (`LLMTool` and the
modes) and `runtime.py` (resource safety). Annotations are derived each time the tool is listed
(`to_mcp_format`), because the tools an LLM tool may call can load after it; a tool with no
catalog yet reports read-only for the modes that call no tools. The Studio creator
([its guide](../studio/MCP%20Studio%20LLM%20Tool%20Creator%20Guide.md)) and Describe proposals
([Tool Generation](Tool%20Generation.md)) are built (step 10), and so are planner files (section 9). `sajha_ask` uses a subclass,
`sajha.ai.ask_tool.SajhaAskTool`, which lint accepts as an LLM-tool implementation.

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
| `planner` | string or object | `ai.planners.default` | `answer` mode: a planner from the planner registry (`name` or `name@version`, section 9), an inline planner definition, or an overlay `{use, settings, models, planners}` ([Planner Reference](Planner%20Reference.md) §2.5). *Built.* (`grounded` runs a fixed retrieval graph and refuses a planner.) |
| `system_prompt` | string | none | Instructions for the model. Mutually exclusive with `prompt`. |
| `prompt` | object | none | `{ "name": "<prompt in the prompts registry>", "arguments": { "<arg>": "{{input.field}}" } }`. Reuses SAJHA prompts instead of inline text. |
| `template` | string | none | `complete`, `extract`, `classify`, `judge`: the user message, with `{{input.<field>}}` placeholders filled from validated arguments. |
| `tools.allow` / `tools.deny` | string[] | `[]` / `[]` | Glob patterns of tools the model may call. Empty `allow` means no tools. Intersected with the caller's own access (section 8). |
| `rag.sources` | string[] | none | `grounded` mode (optional elsewhere): document-search sources to read. |
| `limits.*` | numbers | `ai.llm_tools.*` | `max_steps`, `max_tool_calls`, `timeout_s`, `max_input_chars`, `max_output_tokens`, `max_cost_usd`. Clamped to the server ceilings. |
| `memory.*` | object | `{ "mode": "none" }` | Section 10. |
| `sampling` | string | `never` | `never`, `prefer`, `require` (section 12); `prefer`/`require` on `complete`, `extract`, `classify`, `judge`. *Built.* |
| `output.citations` / `output.steps` | bool | `true` / `false` | Whether the result carries citations and a step trace. |
| `confirm` | string | `ask` | `ask` (stop and request confirmation for destructive inner calls) or `refuse` (never run them). |
| `nesting` | object | `{ "allow": false }` | Section 11. |
| `planner_choices` | string[] | none | Planners a caller may pick per call (section 9.12). Adds an optional `planner` enum to the input schema; absent means the caller cannot choose. *Built.* |
| `source` | object | none | `narrate`: `{"composite": "<name>"}` or `{"workflow": "<name>"}`, optionally with `"arguments"` (values may be `{{input.<field>}}`; exactly one placeholder keeps the argument's type). *Built.* |
| `rubric` | object | none | `judge`: `{"criteria": [{"name", "description", "min" (1), "max" (5), "weight" (1)}], "pass_score": n}`; `pass_score` is on the criteria's own scale (default their midpoint). *Built.* |
| `rag.top_k` | integer | `5` | `grounded`: passages retrieved (1–20). *Built.* |
| `cache` | bool | `false` | `complete`, `extract`, `classify`, `judge`: answer a repeated call from the result cache (section 12). *Built.* |
| `temperature` | number | the model's | Sampling temperature of the tool's own model calls (0–2). *Built.* |

*Built:* every key above except `planner` as an object and `planner_choices`, which the loader
refuses with a message naming the wave that brings them; `sampling` other than `never` is refused
on `answer`, `grounded` and `narrate` (section 12).
`planner` takes the names of the existing planners (`react`, `plan_execute`, `recipes`,
`router`); `name@version` is accepted and the version ignored until planner files exist.
`confirm` and `tools` apply to `answer` only; `rag` to `grounded`; `memory` modes other than
`none` to `answer` and `grounded`. The token cap of an `answer` run is `ai.ask.max_tokens`
(`stopped_by: token_limit`); `limits.max_output_tokens` caps each model call of the other modes.

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

*Built,* with one difference: whether `tools.allow` matches a tool depends on the whole catalog,
and tools load in any order, so the loader does not check it. Lint reports every pattern that
matches nothing (`llm-catalog`, an error), and a call refuses to run when no pattern matches
anything. A refused tool is not registered; its error is recorded like any tool's load error and
lint still reports it from the stored config (`llm-config`).

---

## 6. Modes

Each mode is a small, testable strategy. All share the pipeline in section 7. *All seven are
built* (`sajha/ai/llm_tools/tool.py`, `_mode_<name>`); every model call carries
`metadata.sajha_llm_tool` and `metadata.sajha_llm_mode`, which the gateway's audit records and
the mock uses to answer each mode offline.

### 6.1 `answer`: plan, call tools, compose

The general assistant. The question is condensed with conversation context (if any), tools are
shortlisted from those allowed, the configured planner (section 9) decides calls, results are composed
into an answer with confidence and citations. This is what `sajha_ask` does today.

*Built* on the intelligence service: `IntelligenceService.ask` with the tool's system prompt
(after SAJHA's own), its limits, the allowed set as the shortlist pool (all of it offered when it
is no larger than `ai.ask.shortlist`), its planner, and a stop check before each step (memory
pressure, cancellation, time, cost). The planner is resolved as section 9.12 says.

- Input: `question` (required), `conversation_id`, `messages`, `confirm`.
- Output: `answer`, `confidence`, `citations`, `stopped_by`, `conversation_id`, optional `steps`.

### 6.2 `complete`: a prompt, no tools

Fill a template or registry prompt from the arguments and return the model's text. For
summarise, rewrite, translate, draft.

- Input: whatever fields the template names.
- Output: `text` (and `stopped_by`).
- `tools.allow` must be empty; the loader enforces it.
- *Built.* A refusal returns the refusal text with `stopped_by: refused`; a reply cut by the token
  limit returns the partial text with `stopped_by: token_limit`.

### 6.3 `extract`: structured output

The model must return JSON that validates against the tool's `outputSchema`. SAJHA asks for
structured output where the provider supports it, validates the reply, and on failure retries
once with the validation errors in the prompt. A second failure returns an error result; SAJHA
never returns unvalidated JSON as structured content.

- Input: the text or fields to extract from.
- Output: the schema's fields.
- *Built.* The schema asked of the model is the output schema without the run's own fields
  (`stopped_by`, `conversation_id`, `error`, ...); `stopped_by` is added to the result when the
  output schema declares it.

### 6.4 `classify`: one label from a fixed set

The output schema's `label` is an enum; the model must choose one of its values (plus an
optional `reason` and `confidence`). An answer outside the enum is a failure, not a guess.
Suitable for routing, tagging, triage. *Built:* like `extract`, one retry with the errors, then
`invalid_output`.

### 6.5 `grounded`: answer only from documents

Retrieve passages from the configured document-search sources, answer only from them, cite each
claim's passage, and say "not found in the sources" rather than use model knowledge. No other
tools. The answer is checked: a sentence without a citation lowers confidence; no retrieved
passage means `stopped_by: no_sources`.

*Built.* Retrieval is the document index's search (`sajha/ai/rag/index.py`, the index behind
`sajha_search_docs`), and the caller must be allowed to execute `sajha_search_docs`. Confidence is
0.4 + 0.6 × the share of sentences carrying a `[n]` marker, 0.3 when no passage is cited, and 0
for "Not found in the sources."; `citations` are `"[n] <link or document>"`. `grounded` runs its
fixed retrieval graph; it does not take a configurable planner.

### 6.6 `narrate`: fixed data, model-written prose

Run a named composite or workflow (deterministic), then give its result to the model only to
write the narrative. The model cannot choose tools, so the numbers are reproducible and the
model's role is limited to wording.

- Config: `llm.source: { "composite": "<name>" }` or `{ "workflow": "<id>" }`, plus `template`.
- Output: `text`, and the source's structured result unchanged under `data`.
- *Built.* The source runs through the normal tool path as the caller (the caller must be allowed
  to execute it). A workflow must be published as a tool (`publish.enabled`); like every published
  workflow its steps run as the workflow's owner, so "as the caller" means the caller must be
  allowed to run the published tool. The model sees a preview of the data (large results spill);
  `data` in the result is read back in full.

### 6.7 `judge`: score against a rubric

Given inputs and a rubric (from config), return per-criterion scores and an overall verdict,
validated against the output schema. Used for review, quality gates and evals. A judge never
calls tools.

*Built.* The model returns `scores` (an integer per rubric criterion, within its range; the
schema enforces it), optionally `reasons` and `summary`; SAJHA computes `overall` (the weighted
mean, scaled 0 to 1) and `verdict` (`pass` or `fail` against `pass_score`) itself.

---

## 7. What happens on a call

```
caller ── tools/call markets_assistant {question, conversation_id?}
   │
   ├─ 1. Normal tool path: access check, policy (call), argument validation
   ├─ 2. Resolve the caller (sajha/observability/caller.py) and the depth (section 11)
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
context (`sajha/core/mcp_tool_context.py`). That context exists today on the 2026-07-28 path
only; on 2025-11-25 the run reports progress and checks cancellation through the equivalent
the build adds there.

*Built:* the pipeline above, with admission (section 10.4) before step 2. Progress is reported at
the start and end of a run, and cancellation is checked before each step, on the 2026-07-28 path
(`report_progress`, `is_cancelled`); per-step progress and the 2025-11-25 equivalent are not
built yet. Argument validation and access failures raise as for any tool.

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
get no stored memory (section 10) and the tightest limits (`ai.llm_tools.anonymous.*`).

**Destructive inner calls.** With `confirm: ask`, a destructive call stops the run and returns
`stopped_by: needs_confirmation` with the call's fingerprint. On the 2026-07-28 path this is an
MRTR round trip (the tool raises `InputRequired`, the client answers, the call is retried with
the answer); on the older era and REST, the caller passes the fingerprint back in `confirm`.
With `confirm: refuse`, destructive tools are removed from the allowed set entirely.

*Built,* except the MRTR round trip: on every path the run stops with `needs_confirmation` and
the fingerprints (`pending` in the result), and the caller passes them back in `confirm`.
Anonymous callers (a recorded caller named `anonymous`) are refused unless
`ai.llm_tools.anonymous.enabled`. Code that runs a tool with no recorded caller (tests, evals)
may use the tool's allowed set; `sajha_ask` keeps its older rule there (the anonymous MCP policy
plus `ai.ask.mcp_allowed_tools`).

---

## 9. Planners

*Status: built (Implementation Plan wave 3, build steps 4 and 5).* The engine is
`sajha/ai/planners_engine/` and the shipped strategies are files in `config/planners/`; the
[Planner Reference](Planner%20Reference.md) is the as-built reference, and its section 17 lists
where the code settles what this design left open. Every model call a stage makes is a canonical
Chat Completions request through the gateway bound to the caller (section 13). A walk-through
is [Tutorial 27](../tutorials/TUTORIAL_27_write_a_planner.md).

A planner is the *strategy* an LLM tool follows: how many model calls, in what order, when to
call tools, when to check its own work, when to loop and when to stop. The model does the
reasoning inside each step; the planner decides the shape of the steps. This section makes
planners configuration, so a new strategy (ReAct, Reflect, plan-and-execute, self-consistency,
map-reduce, routing, a domain-specific flow) is a file, not code.

The [Planner Reference](Planner%20Reference.md) owns the planner file itself: every key and
stage setting, transitions, the `when` expression grammar, the verify checks, validation
messages, a JSON Schema, and a complete file for each shipped strategy.

### 9.1 What a planner is, and what it is not

The division of responsibility that exists today (`sajha/ai/planners.py`) stays:

- **The planner proposes.** Before each step it decides the next move: call these tools,
  answer with this text, publish an event, or (new) ask the user.
- **The service enforces.** `IntelligenceService` owns everything that protects the caller:
  the access-filtered shortlist, refusing tools that were not offered, destructive-call
  confirmation, running every call through the normal tool path as the caller, result caps,
  limits and budgets, synthesis, confidence, audit and the event stream.

A planner reaches a model only through the gateway bound to the caller and never touches a
tool directly. Nothing in a planner file can widen what the caller may do, raise a limit above
its ceiling, or remove the safety instructions (section 9.6). That is what makes it safe to let
configuration, rather than reviewed code, define strategies.

**Today.** Four strategies exist as Python classes: `react`, `plan_execute`, `recipes` and
`router`. They are chosen by name in `ai.ask.planner`, and some take settings
(`ai.ask.planner_config.<name>`: recipes, routing rules). A new strategy needs a Python class
registered with `@register_planner`. This design keeps that escape hatch (section 9.10) and adds
a declarative form that covers the common strategies.

### 9.2 The model: a bounded graph of stages

A planner is a **directed graph of stages** with named **state**, defined in
`config/planners/<name>.yaml`:

- a **stage** is one unit of work from a fixed library (section 9.3): a model call with tools,
  a structured plan, a critique, a deterministic check, a fixed tool call, a vote;
- every stage ends with a typed **outcome** (for example `act` ends `called` or `answered`,
  `critique` ends `pass` or `revise`), and **transitions**, under the stage's `outcomes` key, map
  outcomes to the next stage (the key is not `on`, which the YAML 1.1 rules of `yaml.safe_load`
  read as `true`, so planner files load with the same plain loader as SAJHA's other YAML);
- **state** is a set of named slots the stages read and write (`question`, `plan`, `results`,
  `draft`, `critique`, `candidates`, counters), all bounded in size (section 10.4);
- **loops are allowed and always bounded**: any edge that can return to an earlier stage must
  declare `max_visits`, and an `on_exhausted` target for when the bound is reached (section 9.5).

```yaml
# config/planners/<name>.yaml — the shape every planner file has
name: reflect_analyst
version: 1.0.0
description: ReAct to gather data, then check numbers and self-critique before answering.
use_when: Numeric or high-stakes questions where every figure must match the data.   # read by automatic selection (9.13)
models:                      # roles used by stages, each mapped to a gateway alias;
  act: reasoning             # operators re-point aliases, not files
  critic: fast
limits:                      # clamped to ai.planners.limits and the tool's own limits
  max_stages_run: 30
start: act
stages:
  act:
    type: act                # one model call with the offered tools (a ReAct step)
    model: act
    outcomes:
      called:   { next: act, max_visits: 6, on_exhausted: draft }   # the ReAct loop
      answered: { next: draft }
  draft:
    type: draft              # compose an answer from the results, citing the calls it used
    model: act
    outcomes: { done: { next: verify } }
  verify:
    type: verify             # deterministic: every number in the draft appears in a result
    checks: [numbers_in_results, citations_present]
    outcomes:
      ok:       { next: critique }
      mismatch: { next: revise, max_visits: 2, on_exhausted: answer }
  critique:
    type: critique           # a model reviews the draft against the question and results
    model: critic
    rubric: [answers every part of the question, no unsupported claims, says what is missing]
    outcomes:
      pass:   { next: answer }
      revise: { next: revise, max_visits: 2, on_exhausted: answer }
  revise:
    type: revise             # rewrite the draft using the critique or verify findings
    model: act
    outcomes: { done: { next: verify } }
  answer:
    type: answer             # finish; the service computes confidence and records the run
```

The `draft` stage between `act` and `verify` is needed: an `act` answer carries no citations, so
`citations_present` would fail, and force a revision, on every run that called tools.

### 9.3 The stage library

Stages are implemented in code once, tested once, and combined in configuration. Each declares
its inputs, its outputs (state slots it writes) and its outcomes, which the loader checks.

| Stage | What it does | Outcomes |
|---|---|---|
| `act` | One model call with the offered tools; the model either requests tool calls (the service runs them as the caller) or answers. A ReAct step. | `called`, `answered` |
| `plan` | One structured-output call that returns a plan (steps, tools, arguments, dependencies), validated against the plan schema. | `planned`, `invalid` |
| `execute` | Runs the plan's steps through the service, independent steps in parallel up to `max_parallel`; failed steps are recorded, not fatal. | `done`, `failed_steps` |
| `call` | One fixed tool call with arguments templated from state (`{{groups.ticker}}`, a named group set by `match`); a recipe. | `done`, `error` |
| `match` | Deterministic: regular expressions or keywords over the question, setting named groups in state. | one outcome per rule, `none` |
| `classify` | A label for the question from a fixed set, by rules first and a model call only if no rule matches. | one outcome per label |
| `draft` | Compose an answer from the gathered results (model call, no tools). | `done` |
| `critique` | A model reviews the draft against the question, the results and a rubric; returns `pass` or a list of issues. | `pass`, `revise` |
| `revise` | Rewrite the draft to address the critique or verification findings. | `done` |
| `verify` | Deterministic checks, no model: numbers in the draft appear in tool results, every claim has a citation, structured output validates, required parts of the question are answered. | `ok`, `mismatch` |
| `sample` | Run a sub-step (a draft, a plan, a label, or a whole sub-planner run) `n` times in parallel with varied temperature. Not a single `act`: its tool calls need further steps. | `done` |
| `vote` | Pick among samples: majority on a normalised answer (self-consistency) or a judge model with a rubric. | `done`, `tie` |
| `foreach` | Map a sub-graph over a list in state (for example each holding), with bounded concurrency, collecting results; then continue (reduce). | `done`, `partial` |
| `planner` | Run another planner as a sub-graph (section 9.7). | the sub-planner's end |
| `ask_user` | Ask the caller for missing information or a choice: MRTR input on 2026-07-28, `stopped_by: needs_input` elsewhere. | `answered`, `declined` |
| `condense` | Rewrite a follow-up into a standalone question using conversation memory (today done implicitly; made explicit so a planner can skip it). | `done` |
| `answer` | Finish with the current draft or the model's answer. | terminal |
| `fail` | Finish with a stated reason. | terminal |

Conditions over state are written in a small expression language with no code execution:
comparisons, `and`/`or`/`not`, `len()`, `in`, and JSONPath lookups (the same JSONPath the
tool-quality assertions use), for example `when: "len(results) == 0"`. A `when` goes in one of
two places: on a **transition**, which then applies only if the condition holds; or on a
**stage**, as a guard with an `else` transition, where a false condition skips the stage and
follows `else` (the `gate` stage in section 9.13 answers only if confident enough). Each stage's
settings, inputs, outputs and outcomes, templates (`{{slot}}`, with an optional `state.` prefix)
and the expression grammar are in the [Planner Reference](Planner%20Reference.md) (sections 4,
6, 7 and 8).

### 9.4 Strategies are configurations

Every common strategy is a short graph. SAJHA ships these as files (`config/planners/<name>.yaml`),
so they double as examples (each in full in the [Planner Reference](Planner%20Reference.md), section 13):

| Strategy | Graph | Use when |
|---|---|---|
| **ReAct** | `act` ⟲ (`called` → `act`, bounded) → `answer` | general questions; the default |
| **Plan-and-execute** | `plan` → `execute` → `draft` → `answer`; on `failed_steps` → `plan` once | multi-part questions; independent calls in parallel |
| **ReWOO** | `plan` (no observations) → `execute` → `draft` | fewer model calls; predictable cost |
| **Reflect** (self-refine, Reflexion-style) | … → `draft` → `critique` ⟲ `revise` (bounded) → `answer` | high-stakes answers; quality over latency |
| **Verify-then-answer** | … → `draft` → `verify` ⟲ `revise` (bounded) → `answer` | numeric answers that must match the data |
| **Self-consistency** | `act` ⟲ (gather data) → `sample`(n × `draft`, or n whole `react` runs) → `vote` → `answer` | ambiguous questions where agreement signals correctness |
| **Branch and judge** (tree-of-thought, one level) | `sample`(n × `plan`) → `vote`(judge) → `execute` → `draft` | several plausible approaches; pick the best before spending on tools |
| **Map-reduce** | `act` ⟲ (find the items) → `draft` (the item list, structured, into a slot) → `foreach` (a `react` run per item) → `draft` (reduce) | per-item analysis: each holding, each filing, each region |
| **Router** | `match`/`classify` → `planner`(chosen strategy) | mixed traffic; cheap path for easy questions |
| **Recipes** | `match` → `call` → `answer`; `none` → `planner`(fallback) | known questions answered with no model call |
| **Human in the loop** | … → `ask_user` (when ambiguous or before a costly branch) → … | questions that need the caller's choice |

The four built-in planners are re-expressed as configuration files with the same behaviour
(the few differences are listed in the Planner Reference, section 13.13), and their existing
tests run against both forms during the transition. The stages reuse the functions today's
classes are built from (`resolve_references`, `match_recipe`, `PLAN_SCHEMA`, `PLAN_PROMPT` in
`sajha/ai/planners.py`), not the classes themselves, whose boundaries do not match the stages:
`PlanExecutePlanner`, for example, plans, executes and re-plans in one class.

### 9.5 Loops and bounds

Looping is what makes ReAct and Reflect work, and what can make a planner run away. The rules:

1. **Every cycle has a bounded edge.** At load time the graph's cycles are found; each must
   contain at least one transition with `max_visits`. A planner with an unbounded cycle does not
   load.
2. **Exhaustion has a destination.** A bounded edge names `on_exhausted` (usually `draft` or
   `answer`), so reaching the bound ends with the best result so far, never an error loop.
3. **Global ceilings apply on top.** `limits.max_stages_run` for the whole graph, and the
   tool's and caller's step, tool-call, time and cost limits (section 12) end the run with the
   matching `stopped_by` (`stage_limit`, `step_limit`, `tool_limit`, `timeout`, `cost_limit`,
   section 15) whatever the graph says. A file can only tighten a limit: a value above its
   ceiling is clamped to the ceiling, with a lint warning, not refused.
4. **Sub-planners share the budget.** A `planner` stage spends from the parent's remaining
   limits, and may give its sub-run a smaller **sub-budget** (`limits` on the stage). Running out
   of a sub-budget ends only the sub-run (the stage's outcome is `stopped`), so the parent can
   react, for example by escalating (section 9.13); running out of the run's own limits ends the
   run. Depth is limited by `ai.planners.limits.max_subplanner_depth`, and a planner cannot
   include itself, directly or through others.
5. **Fan-out is bounded.** `sample.n`, `foreach` item count and concurrency, and `execute`
   parallelism are capped by `ai.planners.limits`.

### 9.6 Models and prompts per stage

- Each model-using stage names a model *role* (`act`, `critic`, `planner`), mapped in the file's
  `models` block to gateway aliases. Cheap aliases for classification and critique, a reasoning
  alias for planning and acting: cost-aware strategies without code.
- Prompts come from the prompts registry (`prompt: {name: ...}`) or inline text, with
  `{{slot}}` placeholders (`{{state.slot}}` means the same). Structured stages (`plan`,
  `classify`, `draft`, `critique`, `revise`, a judging `vote`) validate the model's reply against
  their schema and by default retry once with the errors; a stage's `retry` (0 to 2) changes
  that. The shipped `plan_execute` sets `retry: 0` on its `plan` stage, because today's planner
  does not re-ask on an invalid plan.
- **SAJHA's safety preamble is always prepended** to every model call (tool results are data,
  not instructions; only offered tools may be called; say when data is missing). A planner file
  cannot remove or override it.
- Temperature, max output tokens and stop sequences may be set per stage, within the tool's
  limits.

### 9.7 Composition with tools and memory

- An LLM tool names its planner: `llm.planner: reflect_analyst` (optionally `name@version`), or
  defines one inline for a one-off strategy. Without one, `ai.planners.default` applies.
- A `planner` stage runs another planner as a sub-graph, which is how the router works and how
  a strategy reuses another (map-reduce whose per-item step is ReAct).
- Conversation memory is loaded before the graph starts (section 10); the `condense` stage
  decides whether the follow-up is rewritten.
- Non-`answer` modes (section 6) use fixed internal graphs; only `answer` and `grounded` accept a
  configurable planner.

### 9.8 Validation at load

A planner file is refused (and `python -m sajha.quality lint` reports it) when:

- a stage type is unknown, or a stage's settings do not match its schema;
- `start` is missing, a stage is unreachable, or a declared outcome has no transition;
- a cycle has no bounded edge, or a bounded edge has no `on_exhausted`;
- a referenced model role, alias, prompt, sub-planner or tool pattern does not exist;
- sub-planners form a cycle or exceed the depth limit;
- a key, outcome name or label did not load as a string (for example a bare `on:` or `yes:`).

A limit above its ceiling is not a reason to refuse a file: it is clamped to the ceiling and
lint warns.

### 9.9 Registry, reload and versions

- A planner registry loads `config/planners/<name>.yaml` (through the storage backend, like
  tool configs), reloads on change, and keeps the previous good version if a new file fails
  validation.
- Each planner has a `version`. A tool can pin `name@version`; tool versions and canaries
  (section 17) can compare two planners on live traffic, and eval sets can compare them offline
  (`python -m sajha.quality eval`, per model and planner, already exists).
- The audit record of every LLM-tool call names the planner, its version and the path of stages
  taken.

### 9.10 The code escape hatch

For a strategy the stage library cannot express, two extension points remain, both
administrator-only and both still inside the service's enforcement:

- `kind: python` with `class: package.module:Class`, the existing planner interface;
- a custom **stage type** registered in code, which then becomes usable in planner files. A
  stage type declares its schema, inputs, outputs and outcomes, so planner files that use it are
  validated like any other.

### 9.11 Observability and testing

- **Events.** Every stage emits start and end events on the ask event stream, so the Ask SAJHA
  animation shows the path (act → act → verify → critique → revise → answer).
- **Metrics.** `sajha_planner_stages_total{planner,stage,outcome}`,
  `sajha_planner_loops_exhausted_total{planner,edge}`, run duration per planner.
- **Dry run.** An admin endpoint runs a planner against the mock model and returns the stage
  path, without running tools that are not read-only. *Built* as `POST /api/ai/planners/dry-run`
  ([API Reference](../protocol/API%20Reference.md)); the planner editor (`/studio/planners`,
  [Planner Reference](Planner%20Reference.md#141-the-planner-editor) §14.1) runs it from a button.
- **Tests.** The mock model gets scripted replies per stage type; each shipped strategy has
  path tests (question → expected stage path) and bound tests (a critic that never passes
  exhausts at `max_visits` and still answers); eval sets compare strategies on the same
  questions. *Built:* `tests/ai/test_planner_engine.py`; the mock-planner model answers every
  stage type deterministically and `mock-scripted` rules may name the `stage` they reply to.


### 9.12 Which planner runs

SAJHA never guesses: the planner for a call is resolved in this order, first match wins.

1. **A routed tool version.** If the tool has an active versions file (canary, or an API-key, user or role pin,
   [Tool Quality](Tool%20Quality.md)), the version chosen for this call may name a different
   planner, for example 10% of calls on `reflect_analyst@2.0.0`. This is how two planners are
   compared on live traffic.
2. **The caller's choice, only if the tool allows it.** A tool that sets `llm.planner_choices`
   gets an optional `planner` argument whose schema is an enum of exactly those names. A value
   outside the list fails argument validation. Without `planner_choices` the argument does not
   exist: by default the tool's owner, not the caller, decides the strategy, because the
   strategy decides cost and looping.
3. **The tool's `llm.planner`:** a name (the latest valid version), `name@version` (pinned), or
   an inline definition for that tool only.
4. **`ai.planners.default`** (`react` unless changed).

The Ask SAJHA page is not a tool; it resolves `ai.ask.planner` against the same registry.

**Resolution happens at load, not per call, wherever it can.** A tool whose named planner does
not exist or does not validate refuses to load, and lint reports it. If an edited planner file
later fails validation, the registry keeps the last good version, logs the error and raises a
metric, so running tools keep working. The resolved planner, its version and why it was chosen
(`version route`, `caller choice`, `tool config`, `server default`, or the automatic selection
below) are recorded in the audit record and the event stream.

### 9.13 Automatic planner selection

Choosing a planner is itself a planner: a graph whose first stages decide which strategy runs.
SAJHA ships one, `auto`, built from two mechanisms.

**Selection by the model, from a menu.** Every planner file carries a `use_when` sentence. The
`auto` planner's first stage tries the deterministic rules (`match`: recipes and known patterns),
then a `classify` stage on a cheap model alias that sees the question and the menu of the
tool's *allowed* planners (their names and `use_when` lines) and must return one name. The
reply is an enum: a question that says "use the expensive planner" cannot reach anything
outside the list. Below a confidence threshold, the tool's default planner runs.

**Escalation on evidence.** The chosen strategy starts as cheaply as it can: a matched recipe
answers with no model call, and anything else runs on the fast alias with a small step
sub-budget (section 9.5, rule 4), so a first try that runs out of steps ends only itself and the
run still has steps left to escalate. Bounded edges then upgrade the run only when a check says
so:

| Trigger | Escalates to |
|---|---|
| `verify` finds a figure in the draft that no tool result contains | Reflect (critique and revise) |
| the question has several parts that the draft does not all answer | `plan_execute` on the reasoning alias |
| confidence below `escalate_below`, or the first try used up its step sub-budget (`subrun.stopped_by` is `step_limit`) | `plan_execute` on the reasoning alias |
| otherwise | answer |

```yaml
# config/planners/auto.yaml, the shipped "auto" planner (abridged: version, description and
# some settings left out; the full file is in the Planner Reference, section 13.12)
name: auto
use_when: Mixed traffic; pick a strategy per question and upgrade only when checks fail.
models: { chooser: fast, act: fast, strong: reasoning }
settings: { candidates: [react, plan_execute, reflect, map_reduce], default: react,
            escalate_below: 0.6, first_try: { max_steps: 4 } }
start: known
stages:
  known:    { type: match, rules_from: recipes.match,           # recipes first: no model call
              outcomes: { none: { next: choose }, "*": { next: recipe } } }
  recipe:   { type: planner, planner: recipes, next: answer }
  choose:   { type: classify, model: chooser, from: settings.candidates, menu: planners,
              default: "{{settings.default}}", outcomes: { "*": { next: run } } }
  run:      { type: planner, planner: "{{chosen}}", choices: "{{settings.candidates}}",
              model: act, limits: "{{settings.first_try}}", outcomes: { "*": { next: verify } } }
  verify:   { type: verify, checks: [numbers_in_results, parts_answered],
              outcomes: { ok: { next: gate },
                          mismatch: [ { next: split, when: "'parts_answered' in $.findings[*].check",
                                        max_visits: 1, on_exhausted: answer },
                                      { next: reflect, max_visits: 1, on_exhausted: answer } ] } }
  gate:     { type: answer, when: "confidence >= settings.escalate_below and subrun.stopped_by != 'step_limit'",
              else: { next: deeper, max_visits: 1, on_exhausted: answer } }
  reflect:  { type: planner, planner: reflect, model: strong, next: answer }
  split:    { type: planner, planner: plan_execute, model: strong, next: answer }
  deeper:   { type: planner, planner: plan_execute, model: strong, next: answer }
  answer:   { type: answer }
```

Three things make this safe to load. A planner chosen at run time (`"{{chosen}}"`) must list every
value it may take in `choices`, each resolved and validated at load, and a value outside it
fails the stage instead of running. The candidates are shipped planners (`reflect` is the
shipped Reflect strategy; `reflect_analyst` in section 9.2 is only an example), and recipes are
not a candidate because the first `match` stage already handles them. And `model` on a
`planner` stage re-binds every model role of the sub-run to that role's alias, so `model: act`
runs the first try on the fast alias and `model: strong` the escalations on the reasoning alias.

Rules that keep automatic selection safe and predictable:

- **Allowlist only.** It chooses only among the tool's allowed planners that pass the tool's eval
  set; it never writes or edits planner files.
- **One budget.** Escalation spends from the same call's limits; trying again can never exceed
  the tool's cost or time ceiling.
- **Escalate at most once per kind**, through bounded edges, so a run cannot ping-pong between
  strategies.
- **Explained.** The choice and its reason (`rule`, `label 0.82`, `verify mismatch`) go to the
  audit record and the event stream; the Ask SAJHA animation shows "chose Reflect: verify
  mismatch".
- **Measured.** Metrics per tool: how often each planner is chosen and how often each escalation
  fires, so an operator can see whether the cheap path is good enough.

**Learning from results comes later.** A third mechanism, choosing planners from measured
outcomes (eval scores offline, and an opt-in bandit across allowed planners online), is on the
[Roadmap](Roadmap.md) as item L15. It needs history this design does not yet collect at scale,
and it would reuse the canary machinery for bounded, reversible exploration.

---

## 10. Conversation memory

### 10.1 Modes

| `memory.mode` | Who keeps the context | Use for |
|---|---|---|
| `none` (default) | Nobody; each call stands alone | classify, extract, judge, narrate |
| `conversation` | SAJHA, addressed by `conversation_id` | assistants, chat front-ends, thin clients |
| `client` | The caller, in `messages: [{role, content}]` | clients that keep their own history or must not leave data on the server |

`conversation` and `client` can both be enabled (`accept_client_history: true`); if a call
carries both, the stored conversation wins and `messages` is ignored, with a note in the result.

### 10.2 The handle

*Status: built (build step 6).* `ConversationMemory.open()` in `sajha/ai/memory.py` implements
the rules below, `record()` stores a turn, and `from_client()` the `client` mode; the module
docstring is the API an LLM tool calls. *Built (step 3):* `LLMTool` opens the conversation per its
`memory` block, records each turn and returns `conversation_id`; any id that is not the caller's
for this tool ends the call as an error result, `conversation not found`.

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

### 10.3 Where it is stored: four tiers

**Today.** The conversation store (`sajha/ai/memory.py`, used by the Ask SAJHA page) is already
on disk: every conversation and turn is a row in the database, which is a SQLite file under
`data/` by default, or PostgreSQL. Nothing is cached in process memory between calls:

- `ai_conversations`: one row per conversation: owner, title, running summary, turn count,
  timestamps;
- `ai_conversation_turns`: one row per turn: question, standalone rewrite, answer (clipped),
  tool *names* used, `stopped_by`, confidence.

What *does* live in RAM is the working set of each running call (the summary and recent turns
it loaded, the tool shortlist, tool results, plans and drafts), and that is what can hurt the
process under load: many concurrent runs, a planner that fans out, or a tool that returns a very
large result. LLM tools and configurable planners make that more likely, so the design defines
four tiers with an explicit bound and an explicit spill path for each:

| Tier | Where | Holds | Bound | Under pressure |
|---|---|---|---|---|
| **T0 working set** | process RAM, one running call | context being assembled: summary, recent turns, shortlist, tool results, plan, drafts, samples | per-call byte budget (`working_set_max_kb`) | large items spill to T3; the run keeps a reference and a clipped preview |
| **T1 hot cache** (optional, off by default) | process RAM, shared by calls | recently used conversations' summary and recent turns, to save a database read | `cache.max_mb` per process, LRU by measured size, TTL | evicted; emptied under memory pressure; write-through, so eviction never loses data |
| **T2 durable store** | database on disk (SQLite file or PostgreSQL) | conversations and turns: the source of truth | section 10.5 | not applicable |
| **T3 spool** | local disk, one folder per run under `data/spool/llm_tools/` (or the storage backend) | large in-flight payloads: big tool results, `foreach` partial results, plan artefacts, samples | `spool.max_mb` in total and a per-run cap | when full, a payload is truncated with a marker instead of spooled; the run continues |

Each call builds the model's context from the summary plus the last `ai.memory.history_turns`
turns verbatim, and condenses a follow-up into a standalone question so tool shortlisting
works. LLM tools add a `tool_name` and an `expires_ts` to the conversation row (section 19), so
each tool's conversations are separate and each can expire on its own schedule. *Built:* both
columns and their indexes are in both schema files. *Built (step 7):* T0 budgets, the optional
T1 cache (a write-through wrapper over the conversation store, `CachedConversationStore`) and the
T3 spool, in `sajha/ai/llm_tools/runtime.py`.

### 10.4 Bounding RAM and protecting the process

The goal is that no amount of traffic, conversation length or tool output can take the SAJHA
process down: under pressure, work slows down or is refused, it does not crash.

1. **Load only the window.** A call reads the conversation row and at most `history_turns` turn
   rows; older turns are represented by the summary and never loaded. *Built:* the only other
   rows read are turns that have just left the window and are not yet summarised.
2. **Per-call working-set budget.** Every item a run holds is measured when added. A tool result
   larger than `spill_threshold_kb` is written to the run's spool folder (T3) at once; the run
   keeps a reference and a preview of `ai.ask.max_result_chars` characters, which is all a model
   ever sees of a result anyway. Stages that need the full result (`verify`, `foreach`, `narrate`)
   stream it back from the spool. If the run's total still exceeds `working_set_max_kb`, the
   oldest spillable items go to T3 next.
3. **Bounded fan-out.** `sample`, `foreach` and parallel `execute` are capped (section 9.5), so a
   planner cannot multiply the working set without limit.
4. **Bounded concurrency.** At most `max_concurrent_runs` LLM-tool runs execute per process;
   up to `max_queued` more wait at most `queue_timeout_s`. Beyond that a call ends with
   `stopped_by: busy` (an error result; REST answers 503 with `Retry-After`).
5. **Memory guard.** A watchdog samples the process's resident memory every `interval_s`
   (the standard library on Linux, `psutil` if installed). Limits default to percentages of the
   container's memory limit (cgroup) when one is set, or to absolute values:
   - **soft limit** (default 70%): empty the hot cache, spill every spillable working-set item,
     stop admitting queued runs;
   - **hard limit** (default 85%): refuse new runs (`busy`), and end running ones at their next
     stage boundary with their best partial answer (`stopped_by: memory_pressure`). Running
     calls are never killed mid-step.

   *Built:* items 1–6. The guard reads `/proc/self/statm`, else `psutil`, else the peak RSS; the
   limit is the cgroup v2 `memory.max`, else cgroup v1 `memory.limit_in_bytes`, else physical
   memory. It samples on every admission and on a background thread while runs happen. At soft,
   new arrivals also wait in the queue. The working set holds tool results (the planner's own
   messages hold the clipped previews); `narrate` reads its spilled source back for `data`.
   Each condition raises a System Notice: `llm_tools.memory` (soft: warning, hard: error),
   `llm_tools.busy`, `llm_tools.spool_full`. Item 7's per-kind caps on the `memory` state
   backend are not built yet.
6. **Hot cache stays small and optional.** T1 is off by default; when on, it is bounded by
   measured bytes, has a TTL, and is the first thing given up under pressure.
7. **State store.** Short-lived shared state (MCP sessions, tasks, approvals, Describe drafts,
   OAuth codes) lives in the state store; MRTR request state does not, because SAJHA signs it
   and the client carries it (`sajha/core/mcp_mrtr.py`). Production with several workers uses `state.backend:
   database` or `redis`, which keep it out of process memory; the design adds a count and byte
   cap per kind to the `memory` backend so that even a single-worker setup cannot grow without
   bound.

### 10.5 Bounding disk

| Bound | Where it is set | Status |
|---|---|---|
| Store words, not data: question, answer and tool names only; raw tool results are never written to the conversation tables (the audit log records the calls) | design rule | built |
| Each stored answer clipped to `max_turn_chars`; questions clipped likewise | `ai.memory.max_turn_chars` | built (both) |
| Summary clipped to `summary_max_chars` | `ai.memory.summary_max_chars` | built |
| Turns per conversation: beyond `memory.max_turns`, older turns are folded into the summary and their rows deleted, so a conversation is at most summary + N turns | per tool, ceiling `ai.llm_tools.memory.max_turns` | built (LLM-tool conversations; the Ask SAJHA page keeps every turn) |
| Idle expiry per tool: `memory.ttl_minutes` sets `expires_ts`; renewed on each turn | per tool, ceiling `ai.memory.retention_days` | built |
| Conversations per user (oldest deleted first) | `ai.memory.max_conversations_per_user` | built |
| Conversations per user per tool | `ai.llm_tools.memory.max_conversations_per_tool` | built |
| Scheduled purge: expired conversations deleted by a periodic job that fires once across workers (a one-slot claim in the state store, as snapshots use), instead of only opportunistically when someone writes | `ai.llm_tools.memory.purge_interval_minutes` | built (`0` falls back to at most hourly, on write) |
| Spool: a run's folder is deleted when the run ends; a janitor deletes folders older than `spool.orphan_minutes` (crashed runs) at start-up and periodically; total size capped by `spool.max_mb` | `ai.llm_tools.memory.spool.*` | built (the cap counts this process's spool) |
| SQLite file size: deleted rows' pages are reused; an optional `VACUUM` in the purge window returns space to the file system. PostgreSQL relies on autovacuum (operator) | `ai.llm_tools.memory.sqlite_vacuum` | built |
| No storage for anonymous callers | design rule | built |
| Users delete their own history | `DELETE /api/ai/conversations` | built |

Worst case per user is therefore *conversations per user × (summary + max_turns × 2 × clip
size)*, and worst case spool is `spool.max_mb`: numbers an operator can compute from config.

### 10.6 Visibility

- Metrics: stored conversations and turns per tool, purged per run, summarisations
  (`sajha_llm_tool_conversations`, `sajha_llm_tool_turns_total`, `sajha_llm_tool_purged_total`).
  *Built:* these three (`tool="ask"` labels the Ask SAJHA page). `GET /api/ai/conversations?tool=<name>` lists one tool's conversations; the Conversations
  page (`/conversations`) lists, opens, continues in Ask and deletes a user's own, and shows
  administrators the counts per scope only (`GET /api/ai/conversation-counts`).
- Resource metrics: working-set bytes and spills per run (`sajha_llm_tool_spilled_total`), spool
  bytes in use (`sajha_llm_tool_spool_bytes`), hot-cache bytes and evictions, queued and refused
  runs (`sajha_llm_tool_runs_refused_total{reason}`), and the memory guard's state (`ok`, `soft`,
  `hard`) with the resident memory it measured. An alert rule on `soft` gives operators warning
  before refusals start. *Built* as `sajha_llm_tool_spilled_total`, `sajha_llm_tool_working_set_bytes`,
  `sajha_llm_tool_spool_bytes`, `sajha_llm_tool_cache_bytes{cache}`,
  `sajha_llm_tool_cache_evictions_total{cache}`, `sajha_llm_tool_runs{state}`,
  `sajha_llm_tool_runs_refused_total{reason}`, `sajha_llm_tool_memory_guard_state` and
  `sajha_llm_tool_memory_resident_bytes` ([Observability](Observability.md)).
- The existing conversations API and a page listing a user's own conversations per tool
  (roadmap X7 asks for that page).
- Retention appears in the Configuration Reference; the Security Model records that stored
  answers can contain data from tool results and how long they are kept.

---

## 11. Recursion and composition

An LLM tool may call another LLM tool only if both allow it:

- the caller's config has `nesting.allow: true` and lists the callee in `tools.allow`;
- the current depth is below `ai.llm_tools.max_depth` (default 2).

Depth is a context variable, like the workflow engine's `CHAIN` (`sajha/workflows/engine.py`):
it holds the names of the LLM tools in the current chain. A tool already in the chain is never
called again (no cycles). Composites and workflows that call LLM tools carry the same context,
so the rule holds through every path. Budgets are shared down the chain: an inner LLM tool spends
from the outer call's remaining cost and time, never a fresh allowance.

*Built:* the chain is `LLM_CHAIN` in `sajha/ai/llm_tools/tool.py` (context variables follow the
call through composites, workflow steps and the planner's parallel calls). An outer tool offers
other LLM tools only with `nesting.allow`; a callee already in the chain raises `CallCycle`, one
past `ai.llm_tools.max_depth` raises `CallTooDeep`; the general tool chain
(`tools.max_call_depth`, `sajha/core/inner_calls.py`) applies as well. A nested run's deadline and
cost cap are the outer run's remainder, and its spend is added to the outer run's.

---

## 12. Models, sampling, budgets and limits

**Model choice.** Through the gateway only, so provider policy (`ai.policy`), per-user and
per-role daily token budgets (`ai.budgets`), retries, circuit breakers, fallback across an alias's candidates
and the response cache all apply. Per-tool `model` picks an alias; the mock model answers every
mode offline (it needs scripted replies for each mode, section 17).

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

*Built:* limits, cost tracking (from the gateway's per-response cost) and caching. The result
cache is in process, bounded by `ai.llm_tools.result_cache.max_entries` and `ttl_s`, keyed also
by the caller (so one caller's cached result never answers another), filled only by runs that
ended with `answer`, and emptied under memory pressure.

*Built: sampling* (`sajha/ai/llm_tools/sampling.py`) for `complete`, `extract`, `classify` and
`judge`; the loader refuses `prefer`/`require` on the other modes. The client's model answers only
when the LLM tool is the MCP call's own target (the `tools/call` name; never an inner call of a
composite, a workflow or another LLM tool) and the client declared `sampling`:

- **2026-07-28.** The run raises an MRTR input request keyed `sajha_sample_<n>` (`n` counts the
  run's model calls); the client answers in `inputResponses` and calls again, and the run, started
  from scratch, finds each answer under its key. A structured mode whose first reply does not
  validate asks for `sajha_sample_2`, so the one retry is one more round.
- **2025-11-25.** When the session declared `sampling` and the request accepts
  `text/event-stream`, `POST /mcp` streams the call (`_stream_sampled_call` in
  `sajha/routes/mcp_routes.py`): the tool runs in a worker thread, its `sampling/createMessage`
  request goes out on the stream, and the client's JSON-RPC response (a separate POST) resumes it.
  An error from the client, or no answer within 120 seconds, ends the run with `stopped_by:
  error`, `code: sampling_failed`.

The request carries the tool's messages, its system text as `systemPrompt` (with the JSON Schema
spelled out, since sampling has no response format, for `extract`, `classify` and `judge`),
`maxTokens` from `limits.max_output_tokens`, the tool's `temperature` and
`metadata.sajha_llm_tool`. The reply is parsed and validated exactly like a gateway reply;
`stopReason: maxTokens` maps to `token_limit` and `refusal` to `refused`. Without a channel,
`prefer` uses SAJHA's model and `require` ends the call with `stopped_by: error`,
`code: sampling_required` (`isError: true`). A sampled call is recorded in the usage ledger
under provider `client` at no cost, appears in the run's `models` as `client/<model>`, marks the
`llm_tool_run` audit record `sampled: mrtr | session`, and never reads or fills the result cache.

---

## 13. The model interface: OpenAI-style, for portability

Every model call an LLM tool, a planner stage or Ask SAJHA makes goes through one interface. This
design makes that interface the **OpenAI Chat Completions format**: the request and response shapes
that OpenAI defined and that most providers, open-source model servers and client libraries now
accept or emulate. Code written against SAJHA's provider and model abstraction then reads like
code written against any OpenAI-compatible SDK, and moves between providers, and in and out of
SAJHA, without rewriting.

*Status: built (Implementation Plan wave 2); 13.4, the outward endpoint, and 13.7, the package
boundary, in wave 3.* The canonical types are `sajha/ai/llm/canonical.py`; the model,
provider and factory interfaces, the
adapters and the credentials for Vertex AI and Entra ID are described as built in the
[Intelligence Layer](Intelligence%20Layer.md#2-core-abstractions), and writing a provider or
model against them in [Extending the Intelligence Layer](Extending%20the%20Intelligence%20Layer.md#3-writing-a-model).

### 13.1 Before

Before wave 2 the intelligence layer had its own neutral types (`ChatRequest` of typed parts,
`ChatResponse`, `ToolSpec`, the stream events `TextDelta`, `ToolCallDelta`, `UsageEvent`, `Done`).
They were sound but SAJHA's own: a planner or provider written for SAJHA looked like nothing a
developer already knew, and nothing outside SAJHA could call its gateway. They remain only inside
`sajha/ai/llm/` (section 13.7); the "Replaces" column below names them.

### 13.2 The canonical format

SAJHA's request and response types are typed models of the Chat Completions format:

| Concept | OpenAI-style field | Replaces (before wave 2) |
|---|---|---|
| Conversation | `messages: [{role: system \| user \| assistant \| tool, content, name?}]` | `messages` of parts plus a separate `system` |
| Multimodal content | `content` as a string or a list of `{type: "text"}` / `{type: "image_url"}` parts | `TextPart`, `ImagePart` |
| Tool definitions | `tools: [{type: "function", function: {name, description, parameters, strict?}}]` | `ToolSpec(name, description, input_schema)` |
| Tool choice | `tool_choice: "auto" \| "none" \| "required" \| {type: "function", function: {name}}`, `parallel_tool_calls` | `tool_choice` string |
| Tool calls | assistant `tool_calls: [{id, type: "function", function: {name, arguments}}]`, `arguments` a JSON string | `ToolCallPart(id, name, arguments: dict)` |
| Tool results | `{role: "tool", tool_call_id, content}` | `ToolResultPart` |
| Structured output | `response_format: {type: "json_schema", json_schema: {name, schema, strict}}` or `{type: "json_object"}` | `response_schema` |
| Sampling controls | `temperature`, `top_p`, `max_completion_tokens` (accepting `max_tokens`), `stop`, `seed`, `n` | same ideas, different names |
| Response | `{id, object: "chat.completion", created, model, choices: [{index, message, finish_reason}], usage}` | `ChatResponse` |
| Finish reasons | `stop`, `length`, `tool_calls`, `content_filter` | `finish_reason` normalised to the same values plus SAJHA's own `error` |
| Usage | `usage: {prompt_tokens, completion_tokens, total_tokens, prompt_tokens_details: {cached_tokens}}` | `Usage(input_tokens, output_tokens, cached_tokens)` |
| Streaming | `chat.completion.chunk` events with `choices[].delta` (content and tool-call fragments), usage in the last chunk | `TextDelta`, `ToolCallDelta`, `UsageEvent`, `Done` |
| Embeddings | `{model, input}` → `{data: [{embedding, index}], usage}` | `embed(texts)` |

Exactly which fields and values are supported, passed through or refused is settled in section
13.6.

**SAJHA's own information stays out of the standard fields.** What only SAJHA needs (the caller's
identity for budgets and policy, the trace id, the access check for tool calls, the cost it
computed, whether the cache answered, which provider and fallback served the call) travels in a
single namespaced field, `sajha` (request) and `sajha` (response), so a request stripped of it is
a valid OpenAI request and a response stripped of it is a valid OpenAI response. The equivalent of
the OpenAI SDKs' `extra_body` carries provider-specific options that have no standard field.

### 13.3 The provider and model interfaces

The interfaces mirror the shape developers know from OpenAI-style client libraries:

```python
class LLMModel(Protocol):                       # one model at one provider
    def chat_completions_create(self, **request) -> ChatCompletion: ...
    def chat_completions_stream(self, **request) -> Iterator[ChatCompletionChunk]: ...
    async def achat_completions_create(self, **request) -> ChatCompletion: ...
    def embeddings_create(self, **request) -> EmbeddingsResponse: ...    # embedding models only

class LLMProvider(Protocol):                    # a vendor or server, with its credentials
    def models(self) -> list[ModelInfo]: ...    # like GET /v1/models
    def model(self, name: str) -> LLMModel: ...
```

- **The governed model exposes the same interface.** `llm_factory().model("reasoning")
  .chat_completions_create(messages=[...], tools=[...])` resolves the alias, applies policy,
  budgets, cache, retries, breakers and fallback, and returns a `ChatCompletion`. Planner stages
  and LLM tools call only governed models (13.7).
- **Providers translate at the edge, once.** Each provider adapter converts the canonical format to
  its vendor's API and back (Anthropic Messages, Gemini, Bedrock Converse, Cohere v2 Chat,
  Ollama's native chat API). For every OpenAI-compatible server (OpenAI, Azure OpenAI,
  Mistral, Groq, Together, Fireworks, DeepSeek, xAI, OpenRouter, Perplexity, vLLM, LM Studio) the
  adapter is a pass-through; what differs is authentication, base URL and path (Azure's
  deployments) and a few declared spellings that exist today as provider settings (`max_tokens`
  instead of `max_completion_tokens`, Mistral's `any` for a required tool call).
- **Differences are declared, not hidden.** Each model's `ModelInfo` (today's
  `ModelCapabilities`, extended) states what it supports (tools, forced tool choice, parallel
  tool calls, `json_schema` output, vision, temperature, reasoning effort, streaming usage,
  seeds, maximum context). The gateway refuses a request a model cannot honour (for example `response_format`
  with `strict` on a model without structured output) with a clear error, or uses the declared
  fallback (for example JSON mode plus validation and one retry), never a silent downgrade.
- **The mock follows the same format.** The mock provider and its scripted replies speak Chat
  Completions, so tests and the offline default exercise exactly the shapes real providers return.

*Built as above,* with `LLMModel` and `LLMProvider` as abstract base classes
(`sajha/ai/llm/base.py`) rather than protocols. The model methods are `chat_completions_create`,
`chat_completions_stream`, `achat_completions_create`, `achat_completions_stream`,
`embeddings_create`, `aembeddings_create` and `info()`; the provider's are `models()`,
`model(name)`, `chat_model`, `embedding_model` and `health()`; the factory hands out
`GovernedModel` proxies with the model methods and has `models(ctx)`. Native async is built for every HTTP provider (Bedrock's boto3 runs in a
worker thread). The declared fallbacks built are JSON-mode emulation of `json_schema`, `n`
calls for `n` on models without native `n`, and `sajha.ignored` for sampling controls; a
vendor's error finish raises `ModelFailed`, which sends the governed model to the next candidate.

### 13.4 SAJHA as an OpenAI-compatible endpoint

Because SAJHA speaks the format internally, it can also offer it outward, opt-in
(`ai.openai_api.enabled`):

- `POST /v1/chat/completions`, `GET /v1/models` and `POST /v1/embeddings`, authenticated with a
  SAJHA API key as the bearer token, so any OpenAI SDK or tool can use SAJHA's gateway by changing
  only its base URL and key, and gets SAJHA's governance: model policy per role, budgets, caching,
  fallback across providers, audit and cost reporting.
- **LLM tools appear as models.** Each enabled LLM tool can be listed as a model
  (`sajha:markets_assistant`): a chat completion addressed to it runs the tool, with its planner,
  its tools, its limits and the caller's identity, and returns its answer as the assistant message
  (with the conversation handle in the `sajha` field). An OpenAI-style client can thus use a
  governed SAJHA assistant without knowing MCP.
- These endpoints follow the same access rules as everything else: a caller sees only the models
  and LLM tools their role allows.

*Built* (`sajha/ai/openai_api.py`, routes in `sajha/routes/openai_routes.py`; rows in the
[API Reference](../protocol/API%20Reference.md#423-openai-compatible-endpoint-openai_routespy)),
off by default (`ai.openai_api.enabled`; turned off, every `/v1` route answers 404):

- **Identity.** An API key as `Authorization: Bearer sja_...` (an owned key acts as its owner, its
  tool list a ceiling), or `X-API-Key`, or a SAJHA JWT as the bearer; the session cookie only with
  `ai.openai_api.cookie_auth`. The RequestContext comes from that AuthContext alone: a `sajha`
  object in the request may carry `conversation_id` and `arguments`, never an identity.
- **Governance.** Chat and embedding calls go through `chat_completions_create`,
  `chat_completions_stream` and `embeddings_create` with the caller's context, so role policy,
  budgets (checked for embeddings too), the response cache, retries, fallback, the usage ledger
  and cost apply. The policy engine sees each request as the pseudo-tool
  `openai_api.chat_completions` or `openai_api.embeddings` (arguments `{"model": ...}`, source
  `openai_api`), so a rule can deny or rate-limit the surface (429 with `Retry-After`). Each
  request writes an `openai_api.request` audit record.
- **Models.** `GET /v1/models` lists the aliases with at least one candidate the caller's role
  allows, every allowed `provider/model` (`gateway.models(ctx)`), and `sajha:<tool>` for each
  enabled LLM tool the caller may execute (`ai.openai_api.llm_tools`). An unknown model and a
  forbidden one both answer 404 `model_not_found`.
- **LLM tools as models.** A completion addressed to `sajha:<tool>` runs the tool through
  `execute_with_tracking` as the caller (tool access, policy, planner, limits, memory, audit).
  Its arguments are `sajha.arguments` when given; else the last user message: as `question` for
  `answer` and `grounded` tools, as the arguments when it is a JSON object of the tool's input
  properties, or as the tool's one required (or only) string input. A tool with `memory.mode:
  client` also gets the earlier user and assistant messages; `sajha.conversation_id` (`"new"` or
  an id) continues a stored conversation. The answer (`answer`, `text` or `label`; otherwise the
  structured result as JSON) is the assistant message; the response's `sajha` field carries
  `stopped_by`, `conversation_id`, `models`, cost and the run's other details, and usage is the
  run's tokens. A tool error is an OpenAI error (`busy` 503 with `Retry-After`, `budget` 429,
  `failed`/`invalid_output` 502). `tools`, `n` > 1 and `response_format` are refused for a tool
  model; sampling controls are ignored and listed in `sajha.ignored`. With `stream: true` the
  finished answer is replayed as chunks.
- **Streaming** answers `chat.completion.chunk` events and `data: [DONE]`; errors before the first
  chunk are ordinary HTTP errors, later ones a `data: {"error": ...}` event.
- **Embeddings** accept `encoding_format` `float` or `base64` (the OpenAI SDKs' default).
- **Not yet:** provider thinking state (13.6) is not returned on the outward endpoint, so a
  multi-turn tool loop through `/v1` sends earlier turns as plain history.

Tested with the official `openai` Python SDK (`tests/ai/test_openai_api.py`).

### 13.5 Moving to the new format

- The canonical models are added next to today's types, with lossless converters both ways, so
  providers, planners and the Ask SAJHA service move one at a time; the old types are removed once
  nothing uses them.
- Every provider gets **golden translation tests**: the same canonical requests (plain chat, tool
  definitions, a tool-call round trip, parallel tool calls, structured output, streaming with tool
  fragments, an image) translated to the vendor's format and the vendor's recorded replies
  translated back, compared with stored expectations.
- A **portability suite** runs one set of canonical requests through the mock and through every
  configured provider, and checks the responses are well-formed Chat Completions with the
  declared capabilities honoured.
- `docs/architecture/Extending the Intelligence Layer.md` is rewritten around the new interfaces,
  so a custom provider is written against the format its author already knows.

*Built:* the converters (`sajha/ai/llm/convert.py`, now internal); every built-in provider and
the mock moved to the canonical format, with the original `generate` / `stream` / `embed` kept
as shims on every model for models written against them; the golden tests
(`tests/ai/test_golden_translation.py`, recorded payloads in `tests/ai/golden/`) and the
portability suite (`tests/ai/test_portability.py`); the guide rewritten. In wave 3 every caller
outside `sajha/ai/llm/` moved to the factory and the canonical types (13.7): the ask service and
planners, conversation memory, document search (query embeddings with `purpose="query"`), LLM
tools, Describe a tool, the OpenAI-compatible endpoint, the tool resolver and embedders, vector
connectors, quality evals and the AI routes. The original types remain only inside the package.

### 13.6 Field coverage

This settles which parts of Chat Completions the canonical format carries. The rule: support
what the planners, the LLM-tool modes and today's providers need; pass through what only
OpenAI-compatible servers understand; refuse everything else with a clear error, never drop it
silently.

*Status: built as specified, including the six behaviours the tables mark as silent before
(OpenAI's refusal, a forced or named tool choice quietly made `auto`, Cohere's named choice
over every tool, a dropped temperature, the `error` finish reason, and the document input
type used for query embeddings). As-built notes: the provider-independent refusals raise
`InvalidRequest` before any candidate is tried (`check_request`); `user` and `metadata` reach
the gateway's audit record (not yet the usage ledger); `reasoning_effort` is refused on
Bedrock; a model always ends its stream with the usage chunk, and the gateway passes it on
only when `stream_options.include_usage` is set; text a vendor streamed before a safety stop
stays in `content` next to the `refusal`.*

| Status | Meaning |
|---|---|
| **Supported** | Part of the canonical types. Translated for every provider whose model declares the feature; a model that does not declare it refuses the request with `unsupported_feature`, and the gateway moves to the alias's next candidate, as it does today for tools, structured output and images. |
| **Passed through** | Accepted only when the model that serves the call is on an OpenAI-compatible provider (OpenAI, Azure OpenAI, Mistral, the presets, any `openai_compatible` server); sent and returned unchanged. On any other provider the request is refused, as above. |
| **Refused** | Always an `invalid_request` error naming the field, whatever the provider. |
| **Not in scope** | Not part of this design; refused like the row above, so a client never believes it worked. |

Fields that only one vendor has (Anthropic `thinking` budgets, Gemini safety settings, Bedrock
guardrails, Ollama `keep_alive`) stay in provider configuration or the request's `extra_body`,
as today. Fields outside these tables are refused. SAJHA's own markers on a response (below
`sajha`) say when it did something on the caller's behalf: `ignored` lists parameters it left
out, `usage_estimated` marks token counts it estimated, `structured_output: "emulated"` marks
JSON mode plus validation instead of a native schema.

**Request: messages and content**

| Field | Status | Notes |
|---|---|---|
| `role: "system"` | Supported | Anthropic, Gemini and Bedrock take one top-level system text; several system messages are joined with a blank line, as today. SAJHA's safety preamble is always the first system text. |
| `role: "developer"` | Supported | OpenAI and Azure OpenAI receive it unchanged; every other provider receives it as `system`, since most OpenAI-compatible servers reject the role. |
| `role: "user"` | Supported | Every provider. |
| `role: "assistant"` with `content` and `tool_calls` | Supported | History for tool loops. Anthropic thinking blocks and Gemini thought signatures from the same provider are echoed back verbatim (see reasoning models, below). A `refusal` in history is sent as assistant text. |
| `role: "tool"` with `tool_call_id`, `content` | Supported | Content as a string or text parts. An error result carries `sajha.is_error`, translated to Anthropic `is_error`, Bedrock `status: "error"`, Gemini `{"error": ...}`, and an `ERROR: ` prefix elsewhere (today's behaviour). Gemini and Ollama also receive the tool's name, looked up from the call. |
| `role: "function"`, `functions`, `function_call` | Refused | Deprecated by OpenAI; `tools` and `tool_choice` cover them. |
| `name` on a message | Passed through | Participant names have no equivalent at the other vendors. |
| Content part `text` | Supported | Every provider. |
| Content part `image_url` | Supported | Models that declare vision. A `data:` URL becomes the vendor's inline image (Anthropic base64 source, Gemini `inlineData`, Bedrock bytes, Ollama `images`). An `http(s)` URL is passed through to OpenAI-compatible servers and refused elsewhere: SAJHA does not fetch URLs on a model's behalf. `detail` other than `auto` is passed through. |
| Content part `input_audio` | Not in scope | No SAJHA path takes audio; see `modalities`. |
| Content part `file` | Not in scope | Documents reach a model through document search (`grounded` mode, `rag.sources`), where they are governed, cited and size-bounded. |

**Request: tools**

| Field | Status | Notes |
|---|---|---|
| `tools[].type: "function"` with `name`, `description`, `parameters` | Supported | `parameters` is the MCP tool's `inputSchema`. Anthropic `input_schema`, Gemini `functionDeclarations` (`parametersJsonSchema`, or the OpenAPI subset with `schema_mode: openapi`), Bedrock `toolSpec.inputSchema.json`, Cohere and Ollama the same shape as OpenAI. |
| `function.strict` | Supported | `true` only on models that declare strict tools; refused elsewhere. SAJHA's own planners do not set it, because the normal tool path validates every call's arguments against the input schema anyway. |
| Other tool types (`custom`, vendor-hosted tools such as web or file search) | Refused | A hosted tool runs at the vendor, outside SAJHA's access rules, policy, audit and budgets. SAJHA's tools are offered as functions. |
| `tool_choice: "auto"` | Supported | Every provider with tools. |
| `tool_choice: "none"` | Supported | Tools are not sent at all, as today (the planners' synthesis and memory calls use this). |
| `tool_choice: "required"` | Supported | Anthropic `{type: "any"}`, Gemini mode `ANY`, Bedrock `any`, Cohere `REQUIRED`, Mistral `any`. Refused on models that declare no forced tool choice (Ollama, and catalogue models flagged so); today those are quietly downgraded to `auto`. |
| `tool_choice: {type: "function", function: {name}}` | Supported | Anthropic `{type: "tool", name}`, Gemini `ANY` with `allowedFunctionNames`, Bedrock `{tool: {name}}`. Cohere has no named choice: accepted only when that function is the one offered (then `REQUIRED`), refused otherwise; today it becomes `REQUIRED` over every offered tool. |
| `tool_choice: {type: "allowed_tools", ...}` | Refused | SAJHA narrows the set by offering only the allowed tools. |
| `parallel_tool_calls` | Supported | `true` is every provider's default and the service runs independent calls in parallel. `false` is sent to OpenAI-compatible servers and as `disable_parallel_tool_use` to Anthropic; refused on providers with no such switch. Today it is a per-provider setting; it becomes per request, with the setting as default. |

**Request: output format and sampling**

| Field | Status | Notes |
|---|---|---|
| `response_format: {type: "text"}` | Supported | The default. |
| `response_format: {type: "json_object"}` | Supported | OpenAI-compatible as is, Gemini `responseMimeType` without a schema, Cohere `json_object`, Ollama `format: "json"`; Anthropic receives the schema `{"type": "object"}`. Refused on models without structured output (Bedrock Converse today). |
| `response_format: {type: "json_schema", json_schema: {name, description?, schema, strict?}}` | Supported | OpenAI-compatible as is, Anthropic `output_config.format`, Gemini `responseJsonSchema` (or `responseSchema` in `schema_mode: openapi`), Cohere `json_object` with `json_schema`, Ollama `format` set to the schema. `strict` becomes per request (today the provider setting `strict_schema`). A model that declares JSON mode but no schema output gets JSON mode, the schema in its instructions, validation and one retry, marked `structured_output: "emulated"`; a model with neither refuses. The `extract`, `classify` and `judge` modes validate every reply against the output schema regardless. |
| `temperature` | Supported | Anthropic, Gemini, Bedrock, Cohere, Ollama `options.temperature`. A model that declares no temperature (catalogue flag `n`, often reasoning models) is called without it and the response lists it in `sajha.ignored`; today it is left out without a trace. Not refused, because SAJHA's own callers send one by default (`ai.ask.temperature`). |
| `top_p` | Supported | New: Anthropic `top_p`, Gemini `topP`, Bedrock `topP`, Cohere `p`, Ollama `options.top_p`; treated like `temperature` on models without sampling controls. |
| `max_completion_tokens`, `max_tokens` | Supported | Both accepted; `max_completion_tokens` wins. Sent as each provider's own field (`max_tokens_param` for OpenAI-compatible servers, Anthropic `max_tokens`, Gemini `maxOutputTokens`, Bedrock `maxTokens`, Ollama `num_predict`), clamped by the role's `ai.policy` cap as today. On reasoning models it includes reasoning tokens. |
| `stop` | Supported | A string or a list. Anthropic and Cohere `stop_sequences`, Gemini and Bedrock `stopSequences`, Ollama `options.stop`. Refused on models that declare no stop sequences. |
| `seed` | Supported | Models that declare it: OpenAI-compatible servers, Gemini `seed`, Cohere `seed`, Mistral `random_seed`, Ollama `options.seed`. Refused elsewhere (Anthropic, Bedrock). Used by evals and tests for repeatable runs. |
| `n` | Supported | Sent natively where declared (OpenAI-compatible, Gemini `candidateCount`); elsewhere the gateway makes `n` calls and merges the choices, each counted against budgets. Capped by `ai.planners.limits.max_samples`. Needed by the `sample` stage. |
| `presence_penalty`, `frequency_penalty` | Passed through | No planner needs them. |
| `logit_bias` | Passed through | Token ids belong to one tokenizer. |
| `logprobs`, `top_logprobs` | Passed through | Returned unchanged in `choices[].logprobs`. |
| `stream` | Supported | Every provider. A model that declares no streaming answers in one content chunk followed by the final chunk, as `ChatModel.stream` does today. |
| `stream_options.include_usage` | Supported | The final chunk carries `usage` and empty `choices`. Usage comes from the vendor's stream events; where a vendor sends none, SAJHA estimates it (about four characters a token, as today) and sets `sajha.usage_estimated`. |
| `user` | Supported (SAJHA meaning) | Recorded in the audit record as the end user's label; never forwarded to a vendor. Identity for policy and budgets comes from the authenticated caller, not this field. |
| `metadata` | Supported (SAJHA meaning) | String pairs recorded in the audit record and usage ledger; never forwarded. |
| `store` | Refused when `true` | Storing completions at a vendor bypasses SAJHA's retention and audit. `false` is accepted. |
| `service_tier` | Passed through | The response's `service_tier` is returned unchanged; the cost estimate still uses the catalogue price. |
| `reasoning_effort` | Supported | Models that declare a reasoning control. OpenAI-compatible as is; Anthropic `output_config.effort`; Gemini `thinkingConfig`; Ollama `think`; Bedrock through `additionalModelRequestFields` where the model declares how. Refused on models without one. |
| `modalities`, `audio` | Not in scope | `modalities: ["text"]` is accepted; anything else is refused. |
| `prediction` | Passed through | Predicted outputs exist only on some OpenAI-compatible models. |
| `web_search_options` | Refused | Search at the vendor bypasses governance; SAJHA's own search and document-search tools are offered as functions instead. |

**Response**

| Field | Status | Notes |
|---|---|---|
| `id`, `object: "chat.completion"`, `created` | Supported | Generated by SAJHA when the vendor has none. |
| `model` | Supported | The vendor's model id that actually answered (after fallback); `sajha.provider` and the qualified id name where. |
| `choices[]` with `index`, `message`, `finish_reason` | Supported | One choice per `n`. |
| `message.content` | Supported | A string, or `null` when the message has only tool calls or a refusal. Several vendor text blocks are joined. |
| `message.refusal` | Supported | OpenAI's `refusal` is kept (today it is dropped, and a refusal looks like an empty answer). Anthropic `stop_reason: "refusal"`, Gemini safety finishes (`SAFETY`, `PROHIBITED_CONTENT`, `BLOCKLIST`, `SPII`, `RECITATION`, `IMAGE_SAFETY`) and Bedrock `guardrail_intervened` become `finish_reason: "content_filter"` with a `refusal` text naming the reason. A prompt the vendor blocks before generating (Gemini `promptFeedback`, a provider's content-filter HTTP error) stays a `content_filtered` error, as today: not retried on another candidate and never cached. An LLM tool reports either as `stopped_by: refused` (section 15). |
| `message.tool_calls[]` with `id`, `type`, `function.name`, `function.arguments` | Supported | `arguments` is a JSON string. Vendors that return objects (Anthropic, Gemini, Bedrock, Ollama) are serialised; vendors without call ids get generated ones, as today. |
| `message.annotations` | Passed through | URL citations from search-capable OpenAI-compatible models. SAJHA's own citations travel in `sajha.citations`. |
| `message.audio` | Not in scope | See `modalities`. |
| `finish_reason` | Supported | `stop`, `length`, `tool_calls`, `content_filter`. `function_call` becomes `tool_calls`; Anthropic `pause_turn` and Gemini `OTHER` become `stop`; a context-window stop becomes `length`. Today's extra value `error` (Gemini `MALFORMED_FUNCTION_CALL`, Cohere `ERROR` and `TIMEOUT`) becomes a gateway error instead, so the next candidate can be tried and responses carry only standard values. |
| `usage.prompt_tokens`, `completion_tokens`, `total_tokens` | Supported | Anthropic prompt tokens include cache reads and writes, Gemini completion tokens include thought tokens, as today. |
| `usage.completion_tokens_details.reasoning_tokens` | Supported | From OpenAI-compatible servers and Gemini `thoughtsTokenCount`; absent when a vendor does not report it separately (Anthropic, Bedrock, Cohere, Ollama), never guessed. Reasoning tokens are already inside `completion_tokens` and priced as output. |
| `usage.completion_tokens_details` other fields (`audio_tokens`, `accepted_prediction_tokens`, `rejected_prediction_tokens`) | Passed through | |
| `usage.prompt_tokens_details.cached_tokens` | Supported | OpenAI `cached_tokens`, Anthropic `cache_read_input_tokens`, Gemini `cachedContentTokenCount`, Bedrock `cacheReadInputTokens`; absent elsewhere. |
| `system_fingerprint` | Passed through | Returned when the vendor sends one. |
| `sajha` | SAJHA | Provider, qualified model, `cost_usd`, `cached` (gateway response cache), latency, fallback attempts, trace id, `ignored`, `usage_estimated`, `structured_output`. |

**Streaming chunks**

| Field | Status | Notes |
|---|---|---|
| `object: "chat.completion.chunk"`, `id`, `created`, `model` | Supported | Same values in every chunk of one response. |
| `choices[].delta.role` | Supported | On the first chunk. |
| `choices[].delta.content` | Supported | From Anthropic `text_delta`, Gemini text parts, Bedrock content deltas, Cohere `content-delta`, Ollama's NDJSON lines. |
| `choices[].delta.tool_calls[]` with `index`, `id`, `function.name`, `function.arguments` fragment | Supported | Anthropic `input_json_delta` and Cohere `tool-call-delta` stream fragments; Gemini and Ollama deliver each call whole, sent as one fragment. |
| `choices[].delta.refusal` | Supported | Streamed by OpenAI-compatible servers; for other vendors one delta when the refusal is known. |
| `choices[].finish_reason` | Supported | On the last content chunk, mapped as in the response. |
| `choices[].logprobs` | Passed through | |
| final `usage` chunk | Supported | With `stream_options.include_usage`. |
| Vendor reasoning text (Anthropic `thinking_delta`, `reasoning_content` from some compatible servers, Ollama `thinking`) | Not in scope | Not emitted as content. What a vendor needs echoed back on the next turn is kept as provider state (below). |

**Embeddings**

| Field | Status | Notes |
|---|---|---|
| `model` | Supported | An alias (`embedding`) or `provider/model`. |
| `input` as a string or an array of strings | Supported | OpenAI-compatible `input`, Gemini `batchEmbedContents`, Cohere `texts`, Bedrock one call per text (Titan) or a batch (Cohere Embed), Ollama's embed API. |
| `input` as token arrays | Passed through | Token ids belong to one tokenizer. |
| `encoding_format: "float"` | Supported | The default. |
| `encoding_format: "base64"` | Supported | SAJHA encodes the floats itself, since some vendors return only floats. |
| `dimensions` | Supported | Models that declare a variable size: OpenAI-compatible `dimensions`, Gemini `outputDimensionality`, Cohere `output_dimension`, Titan v2 `dimensions`, Ollama `dimensions`. Refused on fixed-size models. Per request instead of today's provider setting `embedding_dimensions`; a document index keeps one size for all its vectors. |
| `user` | Supported (SAJHA meaning) | Audit only, as for chat. |
| Response `data[]` with `object`, `embedding`, `index`; `model`; `usage.prompt_tokens`, `usage.total_tokens` | Supported | Usage is estimated and marked where a vendor reports none. |
| Query or document purpose | SAJHA | No standard field; `sajha.input_purpose: "query" \| "document"` maps to Cohere `input_type` and Gemini `taskType`. Today one configured value (`search_document`, `RETRIEVAL_DOCUMENT`) is used for both indexing and queries. |

**Reasoning and thinking models.**

- *Effort.* `reasoning_effort` is the one portable control, mapped per provider as in the table.
  A vendor-specific budget (Anthropic `thinking.budget_tokens`, Gemini `thinkingBudget`) stays in
  `extra_body` or provider configuration, as `extra_body` and Ollama's `think` setting carry it
  today.
- *Sampling.* Models that refuse sampling controls declare it, and SAJHA leaves `temperature`
  and `top_p` out and lists them in `sajha.ignored`, as above.
- *Tokens.* `max_completion_tokens` includes reasoning; reasoning tokens are reported in
  `completion_tokens_details.reasoning_tokens` where the vendor reports them, and are priced as
  output.
- *Thinking state.* Anthropic thinking blocks and Gemini thought signatures must be sent back on
  the next turn of a tool loop. Today they ride in `Message.meta` and are echoed only to the same
  provider, never logged; the canonical assistant message keeps them as private provider state
  in the same way. On SAJHA's outward endpoint (13.4) they are returned as an opaque
  `sajha.provider_state` on the assistant message for the client to send back; a turn without it
  is sent as plain history.
- *Thinking text* is never returned as content and never logged.

**Refusals and filters**, in one place: a model's refusal is a successful response with
`finish_reason: "content_filter"` and `message.refusal`; a request the vendor blocks outright is
a `content_filtered` error. Neither is retried on another candidate (the refusal is a property of
the request), neither is cached (today the cache keeps only `stop` and `tool_calls`), and both
are audited.

---


### 13.7 One package boundary

*Status: built (Implementation Plan wave 3, phase 3.2).* SAJHA reaches every LLM through
OpenAI-style signatures, and all provider and model specifics are confined to one package,
`sajha/ai/llm/`:

- **Abstract classes.** `LLMProvider` and `LLMModel` (`sajha/ai/llm/base.py`) are the common
  API every provider module implements. Each provider has its own module in
  `sajha/ai/llm/providers/` (out-of-tree providers are modules of their own package, loaded
  by class path or entry point) and builds on the shared implementations `ProviderBase`,
  `ChatModel`, `HTTPChatModel` and `EmbeddingModel`; delegation inside a provider stays as
  built (the adapter base plus per-provider request, parse and stream functions).
- **Factory.** `LLMFactory` (`sajha/ai/llm/factory.py`, reached as `llm_factory()`) builds the
  providers from `ai.providers` and `ai.aliases` and the registry (built-ins,
  `package.module:Class`, entry points), resolves secrets and caches the instances.
  `provider(name)` serves admin and catalog pages.
- **Proxy.** `factory.model(alias_or_provider/model)` returns a `GovernedModel`
  (`sajha/ai/llm/governed.py`) implementing `LLMModel`. It applies role policy, budgets, the
  cache, retries, breakers, fallback across the alias's candidates, audit, usage and cost, and
  tracing (the former gateway, now its engine), then delegates to the provider's model. The
  calling code never knows what is behind the instance.
- **Public API.** `sajha.ai.llm` exports the canonical types, `RequestContext` and `Usage`,
  the abstract classes, the factory and proxy, the errors and the catalog value types; its
  public submodules are `canonical`, `errors`, `settings` and `secrets`. Extension code uses
  the provider SPI, `sajha.ai.llm.spi`. Everything else is internal (`adapter`, `http`,
  `convert`, `legacy`, `registry`, `governed`, `providers/`, the mocks).
- **Enforced.** `tests/test_llm_boundary.py` fails when a module outside `sajha/ai/llm/`
  imports a vendor SDK (OpenAI, Anthropic, Google GenAI, Vertex AI, Cohere, Mistral, Ollama,
  Bedrock runtime clients, ...), imports a provider module or another private module,
  constructs a provider or model class, or uses the pre-canonical types; and it checks that
  every registered provider implements the abstract classes.

The former `sajha.ai.gateway` module moved into the package (as `factory.py` and `governed.py`) and the
pre-6.x `sajha.ai.providers` layer was retired: its provider interface lives on, deprecated,
in `sajha.ai.llm.spi` (`LegacyLLMProvider`, `register_provider_class`).

## 14. Safety

- **Prompt injection through tool results.** Tool results are data, inserted in delimited
  blocks and screened with the same injection markers federation uses; a flagged result is
  withheld and recorded. The system prompt tells the model that instructions inside results
  are not instructions.
- **No privilege through the model.** Section 8: the model can only call what the caller can.
- **Output validation.** Structured modes validate against the output schema; free-text modes
  are length-limited. Policy `redact` rules can mask PII in the final answer (the policy engine's
  `redact_text`, `sajha/policy/redact.py`).
- **Data separation.** Conversations are per owner and per tool; the shortlist and context are
  built per call; nothing from one caller's run reaches another's.
- **Secrets.** The model never sees credentials: connected-account tokens and connector
  credentials are injected below the tool boundary, not into prompts.
- **Confirmation.** Destructive inner calls need confirmation or are refused (section 8).

---

## 15. Results and errors

A successful call returns `structuredContent` matching the output schema, plus a text block
for clients on older protocol versions. `stopped_by` says how the run ended. This is the one
list of values: the Ask SAJHA page, every mode and every planner use it, and the
[Planner Reference](Planner%20Reference.md) section 10.3 says when a planner run sets each.
Values marked *today* are the ones the Ask SAJHA service already reports (`STOP_REASONS` in
`sajha/ai/intelligence.py`), with the same meaning; values marked **new** come with this design.

| `stopped_by` | | Meaning | `isError` |
|---|---|---|---|
| `answer` | today | Finished normally (in a planner, an `answer` stage ended the run) | false |
| `failed` | **new** | A planner's `fail` stage ended the run; its reason is the answer text | true |
| `needs_confirmation` | today | A destructive or approval-gated inner call waits for confirmation (fingerprints in the result, or an MRTR request) | false |
| `needs_connection` | today | An inner call needs a connected account the caller has not linked | false |
| `needs_input` | **new** | An `ask_user` stage waits for the caller's answer, on paths without MRTR (section 9.3) | false |
| `step_limit`, `tool_limit`, `timeout` | today | The step, tool-call or time limit ended the run; a partial answer is returned | false |
| `stage_limit`, `cost_limit` | **new** | The planner's stage-run limit or the run's cost limit ended the run; a partial answer is returned | false |
| `budget` | today | The caller's token budget (`ai.budgets`) is used up | true |
| `token_limit` | **new** | The run's own token cap is reached; the best partial answer is returned, like `step_limit` (today this case is reported as `budget`) | false |
| `no_sources` | **new** | `grounded` found nothing to answer from | false |
| `refused` | **new** | The model refused or the provider's filter blocked the request; the refusal text is returned (section 13.6). In `extract`, `classify` and `judge` it is `invalid_output` instead | false |
| `invalid_output` | **new** | `extract`, `classify` or `judge` could not produce valid output after the retry | true |
| `busy`, `memory_pressure` | **new** | The process refused or ended the run to protect itself (section 10.4); REST answers 503 with `Retry-After` for `busy` | true |
| `cancelled` | **new** | The client cancelled the request | true |
| `error` | today | The run failed unexpectedly. The `error` event and the result's `error` field carry the code: the gateway's error codes (for example `no_model_available` when every candidate for the alias failed) or `planner_error` as today, and the new `no_transition` (Planner Reference section 7.2) | true |

Renaming a today value is out of scope: clients and the Ask SAJHA page already read them.

*Built:* LLM tools report every value above; `failed`, `needs_input` and `stage_limit` come from
planner files (a `fail` stage, an `ask_user` stage that cannot ask in-band, the stage ceiling). The error values come back with `isError: true` over MCP
(the result's `stopped_by`, `error` and, for errors, `code`), and over REST as `success: false`;
`busy` answers 503 with `Retry-After` (`ai.llm_tools.runtime.retry_after_s`).

Argument validation errors and access denials are ordinary tool errors, as for any tool.

---

## 16. Observability and audit

- **Audit.** The LLM tool call is one record; every inner call is its own record carrying the
  outer call's id, so an answer can be traced to each tool it used. Conversation turns carry the
  same id. The tamper-evident chain covers all of them.
- **Metrics.** Calls, latency and errors per LLM tool (as for every tool), plus
  `sajha_llm_tool_steps`, `sajha_llm_tool_inner_calls_total`, `sajha_llm_tool_tokens_total`,
  `sajha_llm_tool_cost_usd_total`, `sajha_llm_tool_stopped_total{reason}`, and the memory
  metrics in section 10.6.
- **Usage ledger.** Tokens and cost per caller, per LLM tool, per model, in the existing usage
  and cost pages.
- **Tracing.** One span per call with child spans per model call and inner tool call (OTLP).

*Built:* each run writes one `llm_tool_run` audit record (mode, model, `stopped_by`, tokens, cost,
inner calls, spills, whether the cache answered, the trace id, the run id, the LLM-tool chain and
the conversation id). The tool call itself and every inner call are `tool.call` records of the
same trace (the tool span is created with a trace), and the model calls are the gateway's own
records. Metrics: `sajha_llm_tool_stopped_total{tool,reason}`, `sajha_llm_tool_steps{tool}`,
`sajha_llm_tool_inner_calls_total{tool}`, `sajha_llm_tool_tokens_total{tool}` and
`sajha_llm_tool_cost_usd_total{tool}`. The usage ledger and tracing need no change: the run's
model calls and inner calls are recorded as the caller already.

---

## 17. Testing and quality

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

*Built:* `tests/ai/test_llm_tools.py` (validation, every mode on the mock, the extract and classify
retry, caching, identity, anonymous refusal, annotations and lint, depth and cycles, memory, error
results, `sajha_ask`, eval sets) and `tests/ai/test_llm_tools_runtime.py` (the guard's states with
a simulated resident memory, admission and the queue, spill and read-back, spool caps and the
janitor, shedding under pressure, a run ended at its next step at the hard limit, and a soak test
that drives concurrent calls through the soft and hard limits without a crash). The mock answers
each mode offline (`sajha/ai/llm/mock_llm_tools.py`). Eval sets for the shipped tools are
`config/evals/llm_*.yaml`; an eval set names an LLM tool with `tool:`
([Tool Quality](Tool%20Quality.md) section 5).

---

## 18. Moving `sajha_ask` onto the new type

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

*Built.* `config/tools/sajha_ask.json` (version 2.0.0) is loaded like any tool and disabled there;
`register_if_enabled` in `sajha/ai/ask_tool.py` turns it on from `ai.ask.mcp_tool_enabled` at
start-up and after every reload. `sajha/ai/ask_tool.py` is a shim (`SajhaAskTool`, a subclass of
`LLMTool`) that keeps `ai.ask.mcp_allowed_tools` as a narrowing of `tools.allow: ["*"]`, the
per-call `model` argument and the rule for calls with no recorded caller. Its output adds
`conversation_id` and `caveats`; `steps`, `models`, `shortlist` and `planner` stay
(`output.steps: true`).

**Shipped examples** (all `enabled: false`): `llm_markets_assistant` (`answer` over `calc_*`,
`yahoo_*`, `fred_*`, `boc_*`, with conversation memory), `llm_summarise` (`complete`, cached),
`llm_triage_ticket` (`classify`, cached) and `llm_docs_qa` (`grounded` over `sajha_docs`, with
conversation memory), each with an eval set in `config/evals/` that passes on the mock.

---

## 19. Schema and configuration changes

**Database** (no migrations: both schema files change together, `tests/test_db_schema.py`
enforces it; SAJHA runs no DDL on PostgreSQL):

- `ai_conversations`: add `tool_name VARCHAR(200)` (null for Ask SAJHA page conversations) and
  `expires_ts` (`REAL` in SQLite, `DOUBLE PRECISION` in PostgreSQL, like the table's other
  timestamps; null means the global retention applies); add an index on
  `(user_id, tool_name, updated_ts)` and one on `expires_ts`.
- Operator action for existing databases, in the CHANGELOG: run the two `ALTER TABLE ... ADD
  COLUMN` statements and the two `CREATE INDEX` statements from the schema file (PostgreSQL by
  the operator; SQLite likewise, since SQLite creates only missing tables, not missing columns,
  and the start-up schema check (`db.schema_check: strict`, the default) refuses a database with
  missing columns; roadmap item N2 makes that message print the statements).

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
      working_set_max_kb: 2048    # per running call; larger items spill to the spool
      spill_threshold_kb: 256     # a tool result larger than this is spooled at once
      cache: { enabled: false, max_mb: 64, ttl_s: 300 }   # optional write-through hot cache
      spool: { dir: data/spool/llm_tools, max_mb: 1024, per_run_mb: 128, orphan_minutes: 60 }
      sqlite_vacuum: false        # VACUUM the SQLite file in the purge window
    runtime:
      max_concurrent_runs: 8      # per process
      max_queued: 32
      queue_timeout_s: 30
      memory_guard: { soft_pct: 70, hard_pct: 85, soft_mb: 0, hard_mb: 0, interval_s: 2 }
  planners:
    default: react                # used when an LLM tool names none
    limits:                       # ceilings for every planner file
      max_stages_run: 40
      max_visits_per_edge: 10
      max_subplanner_depth: 2
      max_parallel: 4
      max_samples: 5
      max_foreach_items: 50
```

Planner files live in `config/planners/<name>.yaml` (section 9.2); the built-in strategies ship
there. `ai.ask.planner` and `ai.ask.planner_config` keep working for the Ask SAJHA page and map
onto the registry.

*Built:* the `ai.llm_tools` and `ai.planners` keys above, plus
`runtime.retry_after_s` (`5`), `runtime.memory_guard.enabled` (`true`) and
`result_cache: { max_entries: 1000, ttl_s: 3600 }`. Each is documented in the
[Configuration Reference](../getting-started/Configuration%20Reference.md).

---

## 20. Build plan

Each step ends green: full suite, both conformance suites, mobile check for any page.

| Step | Scope | Gate |
|---|---|---|
| 1 | Caller identity for inner calls and the depth context; `sajha_ask` runs as the caller | identity and recursion tests |
| 2 | Canonical OpenAI-style model interface: Chat Completions types, gateway and model interfaces, provider adapters (pass-through for OpenAI-compatible servers), declared capabilities, the mock in the same format, golden translation tests and the portability suite; converters from today's types so callers move one at a time | translation and portability suites |
| 3 | `LLMTool`, config validation, modes `answer`, `complete`, `extract`, `classify`; derived annotations; lint rules | mode tests on the mock |
| 4 | Planner engine: stage library, graph validation (reachability, outcomes, bounded cycles), state slots, `when` expressions, registry and reload; the four built-ins re-expressed as files with their existing tests passing against both forms | path and bound tests |
| 5 | Strategies shipped as files: Reflect, verify-then-answer, self-consistency, branch and judge, map-reduce, human in the loop, and `auto` (selection plus escalation, section 9.13); planner resolution and `planner_choices`; dry run; per-stage events and metrics; eval sets comparing strategies | evals on the mock |
| 6 | Memory: handle, `tool_name`/`expires_ts` columns in both schema files, turn folding, scheduled purge, `client` history | memory tests incl. two workers |
| 7 | Resource safety: working-set budget, spool and janitor, concurrency limit and queue, memory guard, optional hot cache, state-store caps; load test that drives the process to its soft and hard limits without a crash | soak and pressure tests |
| 8 | Modes `grounded`, `narrate`, `judge`; caching for deterministic modes | mode tests |
| 9 | `sajha_ask` moved onto the type; shipped examples (an assistant, a summariser, a classifier, a grounded docs Q&A); eval sets | evals pass on the mock |
| 10 | Studio "LLM tool" creator and a planner editor with validation and dry run; Describe-a-tool proposals; conversations page | page tests, mobile check |
| 11 | Sampling (`prefer`, `require`) on both eras, starting with non-planner modes | protocol tests, conformance |
| 12 | SAJHA as an OpenAI-compatible endpoint (opt-in): chat completions, models and embeddings with API-key auth, LLM tools listed as models, access rules applied | client tests with an OpenAI SDK |
| 13 | Docs: this note becomes as-built, and `Intelligence Layer.md` and `Extending the Intelligence Layer.md` describe the new interfaces; glossary terms; tutorials (an LLM tool, a custom planner); Configuration and API Reference; Security Model; help card; CHANGELOG | doc-rot tests |

*Status:* every step is built. Wave 2 built steps 1, 2, 3, 6, 7, 8 and 9; wave 3 built steps 4
and 5 (the planner engine and the shipped planner files), 10 (the Studio LLM tool creator, the
planner editor, Describe-a-tool proposals and the Conversations page), 11 (sampling, for the
non-planner modes) and 12 (the OpenAI-compatible endpoint). Step 13 is done: Tutorial 26 is the
LLM-tool tutorial and Tutorial 27 the planner tutorial.

---

## 21. Decisions for the owner

All decided by the owner:

1. **Default state.** The LLM tool type is on; the shipped example LLM tools are off until an
   administrator enables them. `sajha_ask` stays off by default as today.
2. **Anonymous access.** Off (`ai.llm_tools.anonymous.enabled: false`): every call spends model
   budget.
3. **Sampling.** Build step 11, in wave 3: `complete`, `extract`, `classify` and `judge` first
   (section 12); `answer` after measuring the round-trip cost.
4. **Modes.** The seven in section 6; presets such as `translate` (of `complete`) or `compare`
   (of `judge`) only when asked for.
5. **Who may create LLM tools.** Users with the Studio permission `studio:llm` (or `studio:*`;
   the seeded `llm_author` role has `studio:llm` only); limits and budgets bound what a tool can
   spend.
6. **Who may author planners.** Administrators only: a planner decides how much a tool spends
   and how it loops, so it is closer to policy than to a tool definition.
7. **Default strategy.** `react` for `answer` tools, with Reflect or verify-then-answer chosen
   per tool where accuracy matters more than latency.

---

## 22. Alternatives considered

| Alternative | Why not |
|---|---|
| One `sajha_ask` tool with many optional parameters | Every caller re-specifies the prompt, tools and limits; nothing is governed or tested per use; the schema becomes vague. |
| A Python class per LLM tool | Contradicts the config-driven framework; every change needs a deploy; Studio cannot create them. |
| Memory keyed by the MCP session | No sessions on 2026-07-28; breaks across workers; useless to REST, CLI, workflow and A2A callers. |
| Memory held only in process RAM | Lost on restart, wrong with several workers, unbounded under load. RAM is used only as a bounded working set and an optional write-through cache in front of the disk store. |
| Planners only as Python classes | Every new strategy needs a deploy and code review; strategies cannot be compared or canaried as configuration; non-developers cannot adjust them. |
| Unbounded agent loops ("until done") | Cost and latency without limit, and runaway loops under prompt injection; every loop here has a bounded edge and global ceilings. |
| A general-purpose workflow language for planners | Workflows already exist for long-running processes; planners need a small, validated stage library that the service can enforce, not arbitrary code or expressions. |
| Store full tool results with each turn | Disk grows with data volume; results may hold data the audit log already records under its own retention. |
| Always use the client's model (sampling only) | Thin callers have no model; servers cannot rely on clients declaring sampling; governance of the model choice is lost. |
