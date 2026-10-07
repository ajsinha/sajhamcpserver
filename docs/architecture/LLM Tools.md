# LLM Tools

> **Status: design, not built.** This note is the design for LLM tools: tools whose work is
> done by a language model, defined and governed like every other SAJHA tool, the
> configuration-driven planners they run, and the memory tiers that keep them within bounds. When it is
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
| Implementation | One generic class, `sajha.ai.llm_tools.LLMTool` (a `BaseMCPTool`), named in `implementation`. Like the generic REST and database tools, the behaviour comes from config. |
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
| `planner` | string or object | `ai.planners.default` | `answer` and `grounded` modes: a planner from the planner registry (`name` or `name@version`, section 9), or an inline planner definition. |
| `system_prompt` | string | none | Instructions for the model. Mutually exclusive with `prompt`. |
| `prompt` | object | none | `{ "name": "<prompt in the prompts registry>", "arguments": { "<arg>": "{{input.field}}" } }`. Reuses SAJHA prompts instead of inline text. |
| `template` | string | none | `complete`, `extract`, `classify`, `judge`: the user message, with `{{input.<field>}}` placeholders filled from validated arguments. |
| `tools.allow` / `tools.deny` | string[] | `[]` / `[]` | Glob patterns of tools the model may call. Empty `allow` means no tools. Intersected with the caller's own access (section 8). |
| `rag.sources` | string[] | none | `grounded` mode (optional elsewhere): document-search sources to read. |
| `limits.*` | numbers | `ai.llm_tools.*` | `max_steps`, `max_tool_calls`, `timeout_s`, `max_input_chars`, `max_output_tokens`, `max_cost_usd`. Clamped to the server ceilings. |
| `memory.*` | object | `{ "mode": "none" }` | Section 10. |
| `sampling` | string | `never` | `never`, `prefer`, `require` (section 12). |
| `output.citations` / `output.steps` | bool | `true` / `false` | Whether the result carries citations and a step trace. |
| `confirm` | string | `ask` | `ask` (stop and request confirmation for destructive inner calls) or `refuse` (never run them). |
| `nesting` | object | `{ "allow": false }` | Section 11. |
| `planner_choices` | string[] | none | Planners a caller may pick per call (section 9.12). Adds an optional `planner` enum to the input schema; absent means the caller cannot choose. |

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
shortlisted from those allowed, the configured planner (section 9) decides calls, results are composed
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
get no stored memory (section 10) and the tightest limits (`ai.llm_tools.anonymous.*`).

**Destructive inner calls.** With `confirm: ask`, a destructive call stops the run and returns
`stopped_by: needs_confirmation` with the call's fingerprint. On the 2026-07-28 path this is an
MRTR round trip (the tool raises `InputRequired`, the client answers, the call is retried with
the answer); on the older era and REST, the caller passes the fingerprint back in `confirm`.
With `confirm: refuse`, destructive tools are removed from the allowed set entirely.

---

## 9. Planners

A planner is the *strategy* an LLM tool follows: how many model calls, in what order, when to
call tools, when to check its own work, when to loop and when to stop. The model does the
reasoning inside each step; the planner decides the shape of the steps. This section makes
planners configuration, so a new strategy (ReAct, Reflect, plan-and-execute, self-consistency,
map-reduce, routing, a domain-specific flow) is a file, not code.

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
  `critique` ends `pass` or `revise`), and **transitions** map outcomes to the next stage;
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
models:                      # aliases used by stages; operators re-point aliases, not files
  act: reasoning
  critic: fast
limits:                      # clamped to ai.planners.limits and the tool's own limits
  max_stages_run: 30
start: act
stages:
  act:
    type: act                # one model call with the offered tools (a ReAct step)
    model: act
    on:
      called:   { next: act, max_visits: 6, on_exhausted: draft }   # the ReAct loop
      answered: { next: verify }
  draft:
    type: draft              # compose an answer from the results gathered so far
    on: { done: { next: verify } }
  verify:
    type: verify             # deterministic: every number in the draft appears in a result
    checks: [numbers_in_results, citations_present]
    on:
      ok:       { next: critique }
      mismatch: { next: revise, max_visits: 2, on_exhausted: answer }
  critique:
    type: critique           # a model reviews the draft against the question and results
    model: critic
    rubric: [answers every part of the question, no unsupported claims, says what is missing]
    on:
      pass:   { next: answer }
      revise: { next: revise, max_visits: 2, on_exhausted: answer }
  revise:
    type: revise             # rewrite the draft using the critique or verify findings
    model: act
    on: { done: { next: verify } }
  answer:
    type: answer             # finish; the service synthesises confidence and citations
```

### 9.3 The stage library

Stages are implemented in code once, tested once, and combined in configuration. Each declares
its inputs, its outputs (state slots it writes) and its outcomes, which the loader checks.

| Stage | What it does | Outcomes |
|---|---|---|
| `act` | One model call with the offered tools; the model either requests tool calls (the service runs them as the caller) or answers. A ReAct step. | `called`, `answered` |
| `plan` | One structured-output call that returns a plan (steps, tools, arguments, dependencies), validated against the plan schema. | `planned`, `invalid` |
| `execute` | Runs the plan's steps through the service, independent steps in parallel up to `max_parallel`; failed steps are recorded, not fatal. | `done`, `failed_steps` |
| `call` | One fixed tool call with arguments templated from state (`{{question.groups.ticker}}`); a recipe. | `done`, `error` |
| `match` | Deterministic: regular expressions or keywords over the question, setting named groups in state. | one outcome per rule, `none` |
| `classify` | A label for the question from a fixed set, by rules first and a model call only if no rule matches. | one outcome per label |
| `draft` | Compose an answer from the gathered results (model call, no tools). | `done` |
| `critique` | A model reviews the draft against the question, the results and a rubric; returns `pass` or a list of issues. | `pass`, `revise` |
| `revise` | Rewrite the draft to address the critique or verification findings. | `done` |
| `verify` | Deterministic checks, no model: numbers in the draft appear in tool results, every claim has a citation, structured output validates, required parts of the question are answered. | `ok`, `mismatch` |
| `sample` | Run a sub-step (a draft, a plan) `n` times in parallel with varied temperature. | `done` |
| `vote` | Pick among samples: majority on a normalised answer (self-consistency) or a judge model with a rubric. | `done`, `tie` |
| `foreach` | Map a sub-graph over a list in state (for example each holding), with bounded concurrency, collecting results; then continue (reduce). | `done`, `partial` |
| `planner` | Run another planner as a sub-graph (section 9.7). | the sub-planner's end |
| `ask_user` | Ask the caller for missing information or a choice: MRTR input on 2026-07-28, `stopped_by: needs_input` elsewhere. | `answered`, `declined` |
| `condense` | Rewrite a follow-up into a standalone question using conversation memory (today done implicitly; made explicit so a planner can skip it). | `done` |
| `answer` | Finish with the current draft or the model's answer. | terminal |
| `fail` | Finish with a stated reason. | terminal |

Transitions can also carry a `when` condition over state, written in a small expression
language with no code execution: comparisons, `and`/`or`/`not`, `len()`, `in`, and JSONPath
lookups (the same JSONPath the tool-quality assertions use). Example:
`when: "len(results) == 0"`.

### 9.4 Strategies are configurations

Every common strategy is a short graph. SAJHA ships these as files (`config/planners/<name>.yaml`),
so they double as examples:

| Strategy | Graph | Use when |
|---|---|---|
| **ReAct** | `act` ⟲ (`called` → `act`, bounded) → `answer` | general questions; the default |
| **Plan-and-execute** | `plan` → `execute` → `draft` → `answer`; on `failed_steps` → `plan` once | multi-part questions; independent calls in parallel |
| **ReWOO** | `plan` (no observations) → `execute` → `draft` | fewer model calls; predictable cost |
| **Reflect** (self-refine, Reflexion-style) | … → `draft` → `critique` ⟲ `revise` (bounded) → `answer` | high-stakes answers; quality over latency |
| **Verify-then-answer** | … → `draft` → `verify` ⟲ `revise` (bounded) → `answer` | numeric answers that must match the data |
| **Self-consistency** | `sample`(n × `act` or `draft`) → `vote` → `answer` | ambiguous questions where agreement signals correctness |
| **Branch and judge** (tree-of-thought, one level) | `sample`(n × `plan`) → `vote`(judge) → `execute` → `draft` | several plausible approaches; pick the best before spending on tools |
| **Map-reduce** | `act` (list the items) → `foreach` (sub-graph per item) → `draft` | per-item analysis: each holding, each filing, each region |
| **Router** | `match`/`classify` → `planner`(chosen strategy) | mixed traffic; cheap path for easy questions |
| **Recipes** | `match` → `call` → `answer`; `none` → `planner`(fallback) | known questions answered with no model call |
| **Human in the loop** | … → `ask_user` (when ambiguous or before a costly branch) → … | questions that need the caller's choice |

The four built-in planners are re-expressed as configuration files with the same behaviour, and
their existing tests run against both forms during the transition; the Python classes remain as
the implementation of the `act`, `plan`, `match` and routing stages.

### 9.5 Loops and bounds

Looping is what makes ReAct and Reflect work, and what can make a planner run away. The rules:

1. **Every cycle has a bounded edge.** At load time the graph's cycles are found; each must
   contain at least one transition with `max_visits`. A planner with an unbounded cycle does not
   load.
2. **Exhaustion has a destination.** A bounded edge names `on_exhausted` (usually `draft` or
   `answer`), so reaching the bound ends with the best result so far, never an error loop.
3. **Global ceilings apply on top.** `limits.max_stages_run` for the whole graph, and the
   tool's and caller's step, tool-call, time and cost limits (section 12) end the run with the
   matching `stopped_by` whatever the graph says.
4. **Sub-planners share the budget.** A `planner` stage spends from the parent's remaining
   limits; depth is limited by `ai.planners.limits.max_subplanner_depth`, and a planner cannot
   include itself, directly or through others.
5. **Fan-out is bounded.** `sample.n`, `foreach` item count and concurrency, and `execute`
   parallelism are capped by `ai.planners.limits`.

### 9.6 Models and prompts per stage

- Each model-using stage names a model *role* (`act`, `critic`, `planner`), mapped in the file's
  `models` block to gateway aliases. Cheap aliases for classification and critique, a reasoning
  alias for planning and acting: cost-aware strategies without code.
- Prompts come from the prompts registry (`prompt: {name: ...}`) or inline text, with
  `{{state.slot}}` placeholders. Structured stages (`plan`, `critique`, `vote`, `classify`)
  validate the model's reply against their schema and retry once with the errors.
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
- a limit exceeds its ceiling (it is clamped, with a warning, rather than refused).

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
- **Dry run.** A new admin endpoint and a button in the planner editor run a planner against the mock model and
  returns the stage path, without calling tools that are not read-only.
- **Tests.** The mock model gets scripted replies per stage type; each shipped strategy has
  path tests (question → expected stage path) and bound tests (a critic that never passes
  exhausts at `max_visits` and still answers); eval sets compare strategies on the same
  questions.


### 9.12 Which planner runs

SAJHA never guesses: the planner for a call is resolved in this order, first match wins.

1. **A routed tool version.** If the tool has an active versions file (canary, user or role pin,
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

**Escalation on evidence.** The chosen strategy starts as cheaply as it can (recipes, or `react`
on a fast alias). Bounded edges then upgrade the run only when a check says so:

| Trigger | Escalates to |
|---|---|
| `verify` finds a figure in the draft that no tool result contains | Reflect (critique and revise) |
| confidence below `escalate_below`, or the run hit `max_steps` | `plan_execute` on the reasoning alias |
| the question has several parts that the draft does not all answer | `plan_execute` or map-reduce |
| otherwise | answer |

```yaml
# config/planners/<name>.yaml for the shipped "auto" planner (abridged)
name: auto
use_when: Mixed traffic; pick a strategy per question and upgrade only when checks fail.
models: { chooser: fast, act: fast, strong: reasoning }
settings: { candidates: [recipes, react, plan_execute, reflect_analyst], escalate_below: 0.6 }
start: choose
stages:
  choose:   { type: classify, model: chooser, from: candidates, on: { "*": { next: run } } }
  run:      { type: planner, planner: "{{state.chosen}}", on: { "*": { next: verify } } }
  verify:   { type: verify, checks: [numbers_in_results, parts_answered],
              on: { ok: { next: gate }, mismatch: { next: reflect, max_visits: 1, on_exhausted: answer } } }
  gate:     { type: answer, when: "confidence >= settings.escalate_below",
              else: { next: deeper, max_visits: 1, on_exhausted: answer } }
  reflect:  { type: planner, planner: reflect_analyst, on: { "*": { next: answer } } }
  deeper:   { type: planner, planner: plan_execute, model: strong, on: { "*": { next: answer } } }
  answer:   { type: answer }
```

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
each tool's conversations are separate and each can expire on its own schedule.

### 10.4 Bounding RAM and protecting the process

The goal is that no amount of traffic, conversation length or tool output can take the SAJHA
process down: under pressure, work slows down or is refused, it does not crash.

1. **Load only the window.** A call reads the conversation row and at most `history_turns` turn
   rows; older turns are represented by the summary and never loaded.
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
6. **Hot cache stays small and optional.** T1 is off by default; when on, it is bounded by
   measured bytes, has a TTL, and is the first thing given up under pressure.
7. **State store.** Short-lived shared state (MRTR request state, Describe drafts, approvals,
   tasks) lives in the state store. Production with several workers uses `state.backend:
   database` or `redis`, which keep it out of process memory; the design adds a count and byte
   cap per kind to the `memory` backend so that even a single-worker setup cannot grow without
   bound.

### 10.5 Bounding disk

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
| Spool: a run's folder is deleted when the run ends; a janitor deletes folders older than `spool.orphan_minutes` (crashed runs) at start-up and periodically; total size capped by `spool.max_mb` | `ai.llm_tools.memory.spool.*` | new |
| SQLite file size: deleted rows' pages are reused; an optional `VACUUM` in the purge window returns space to the file system. PostgreSQL relies on autovacuum (operator) | `ai.llm_tools.memory.sqlite_vacuum` | new |
| No storage for anonymous callers | design rule | new |
| Users delete their own history | `DELETE /api/ai/conversations` | today |

Worst case per user is therefore *conversations per user × (summary + max_turns × 2 × clip
size)*, and worst case spool is `spool.max_mb`: numbers an operator can compute from config.

### 10.6 Visibility

- Metrics: stored conversations and turns per tool, purged per run, summarisations
  (`sajha_llm_tool_conversations`, `sajha_llm_tool_turns_total`, `sajha_llm_tool_purged_total`).
- Resource metrics: working-set bytes and spills per run (`sajha_llm_tool_spilled_total`), spool
  bytes in use (`sajha_llm_tool_spool_bytes`), hot-cache bytes and evictions, queued and refused
  runs (`sajha_llm_tool_runs_refused_total{reason}`), and the memory guard's state (`ok`, `soft`,
  `hard`) with the resident memory it measured. An alert rule on `soft` gives operators warning
  before refusals start.
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

---

## 12. Models, sampling, budgets and limits

**Model choice.** Through the gateway only, so provider policy (`ai.policy`), per-user daily
token budgets (`ai.budgets`), retries, circuit breakers, fallback across an alias's candidates
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

---

## 13. The model interface: OpenAI-style, for portability

Every model call an LLM tool, a planner stage or Ask SAJHA makes goes through one interface. This
design makes that interface the **OpenAI Chat Completions format**: the request and response shapes
that OpenAI defined and that most providers, open-source model servers and client libraries now
accept or emulate. Code written against SAJHA's provider and model abstraction then reads like
code written against any OpenAI-compatible SDK, and moves between providers, and in and out of
SAJHA, without rewriting.

### 13.1 Today

The intelligence layer ([Intelligence Layer](Intelligence%20Layer.md)) has its own neutral types
in `sajha/ai/llm/types.py`: a `ChatRequest` with `messages` made of typed parts, a separate
`system` field, `tools` as `ToolSpec` objects with `input_schema`, `response_schema` for
structured output, and a `ChatResponse` whose `Usage` counts `input_tokens` and `output_tokens`.
Each provider in `sajha/ai/llm/providers/` translates those types to its vendor's API; the
`openai_compat` provider covers the many servers that already speak the OpenAI format. The
types are sound, but they are SAJHA's own: a planner or provider written for SAJHA does not look
like anything a developer already knows, and nothing outside SAJHA can call its gateway.

### 13.2 The canonical format

SAJHA's request and response types become typed models of the Chat Completions format:

| Concept | OpenAI-style field | Replaces today's |
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
| Finish reasons | `stop`, `length`, `tool_calls`, `content_filter` | free-form `finish_reason` |
| Usage | `usage: {prompt_tokens, completion_tokens, total_tokens, prompt_tokens_details: {cached_tokens}}` | `Usage(input_tokens, output_tokens, cached_tokens)` |
| Streaming | `chat.completion.chunk` events with `choices[].delta` (content and tool-call fragments), usage in the last chunk | `TextDelta`, `ToolCallDelta` |
| Embeddings | `{model, input}` → `{data: [{embedding, index}], usage}` | `embed(texts)` |

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

- **The gateway exposes the same interface.** `gateway.chat_completions_create(model="reasoning",
  messages=[...], tools=[...])` resolves the alias, applies policy, budgets, cache, retries,
  breakers and fallback, and returns a `ChatCompletion`. Planner stages and LLM tools call only
  the gateway.
- **Providers translate at the edge, once.** Each provider adapter converts the canonical format to
  its vendor's API and back (Anthropic Messages, Gemini, Bedrock Converse, Cohere, Mistral, and so
  on). For every OpenAI-compatible server (OpenAI, Azure OpenAI, Groq, Together, Fireworks,
  DeepSeek, xAI, OpenRouter, Perplexity, vLLM, LM Studio, Ollama's compatible endpoint) the adapter
  is a pass-through with only authentication and base URL differing.
- **Differences are declared, not hidden.** Each model's `ModelInfo` states what it supports
  (tools, parallel tool calls, `json_schema` output, vision, streaming usage, seeds, maximum
  context). The gateway refuses a request a model cannot honour (for example `response_format`
  with `strict` on a model without structured output) with a clear error, or uses the declared
  fallback (for example JSON mode plus validation and one retry), never a silent downgrade.
- **The mock follows the same format.** The mock provider and its scripted replies speak Chat
  Completions, so tests and the offline default exercise exactly the shapes real providers return.

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

---

## 14. Safety

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

## 15. Results and errors

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

---

## 19. Schema and configuration changes

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

---

## 21. Decisions for the owner

All decided by the owner:

1. **Default state.** The LLM tool type is on; the shipped example LLM tools are off until an
   administrator enables them. `sajha_ask` stays off by default as today.
2. **Anonymous access.** Off (`ai.llm_tools.anonymous.enabled: false`): every call spends model
   budget.
3. **Sampling.** Later: build step 11, after the core, planners and memory work.
4. **Modes.** The seven in section 6; presets such as `translate` (of `complete`) or `compare`
   (of `judge`) only when asked for.
5. **Who may create LLM tools.** Users with the `studio` permission; limits and budgets bound
   what a tool can spend.
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
