# Planner Reference

> **Status: design, not built.** This is the file-format reference for the configurable
> planners designed in [LLM Tools](LLM%20Tools.md) section 9. Nothing here exists in the code
> yet: there is no `config/planners/<name>.yaml` loader, no stage library and no expression
> evaluator. What exists today is the four Python planners in `sajha/ai/planners.py`
> (`react`, `plan_execute`, `recipes`, `router`), chosen by `ai.ask.planner`; the
> [Intelligence Layer](Intelligence%20Layer.md) and
> [Extending the Intelligence Layer](Extending%20the%20Intelligence%20Layer.md) own them.
> When the planner registry is built, this file becomes the as-built reference.

[LLM Tools](LLM%20Tools.md) section 9 owns *why* planners are configuration and how they fit LLM
tools (what a planner is, the stage library in outline, loops and bounds, resolution, automatic
selection). This reference owns *the file*: every key, every stage, every transition rule, the
`when` expression language, the verify checks, the validation errors, a JSON Schema, and a full
file for each shipped strategy. It is meant to be precise enough to build the loader, the stage
library and the evaluator from, and to write a planner without reading code.

Where the design said nothing, this reference decides; every such decision is listed in
[section 15](#15-decisions-made-in-this-reference). Places where the design disagreed with
itself or with today's code, and how each was resolved, are listed in
[section 16](#16-where-the-design-disagrees-with-itself-or-the-code).

---

## Contents

1. [Conventions](#1-conventions)
2. [Files, names, versions and resolution](#2-files-names-versions-and-resolution)
3. [Top-level keys](#3-top-level-keys)
4. [Templates and settings references](#4-templates-and-settings-references)
5. [State](#5-state)
6. [Stages](#6-stages)
7. [Transitions](#7-transitions)
8. [The `when` expression language](#8-the-when-expression-language)
9. [Verify checks](#9-verify-checks)
10. [How a planner runs](#10-how-a-planner-runs)
11. [Limits and ceilings](#11-limits-and-ceilings)
12. [Validation rules and messages](#12-validation-rules-and-messages)
13. [Shipped planners](#13-shipped-planners)
14. [Writing your own planner](#14-writing-your-own-planner)
15. [Decisions made in this reference](#15-decisions-made-in-this-reference)
16. [Where the design disagrees with itself or the code](#16-where-the-design-disagrees-with-itself-or-the-code)
17. [Appendix A: JSON Schema for planner files](#appendix-a-json-schema-for-planner-files)

---

## 1. Conventions

- **Planner file**: one YAML document (JSON is accepted, being YAML) describing one planner at
  one version.
- **Stage id**: the key of a stage under `stages`. **Stage type**: its `type` (`act`, `plan`, ...).
- **Outcome**: the word a stage ends with (`called`, `pass`, a rule name, a label).
- **Edge**: one transition from a stage to another stage. **Bounded edge**: an edge with
  `max_visits`.
- **Run**: one execution of a planner for one call of an LLM tool (or one Ask SAJHA question).
  **Sub-run**: a planner executed by a `planner`, `sample` or `foreach` stage inside a run.
- **The service**: the part of SAJHA that owns enforcement (today `IntelligenceService` in
  `sajha/ai/intelligence.py`): the access-filtered shortlist, refusing tools that were not
  offered, destructive-call confirmation, running calls as the caller, result caps, limits,
  budgets, synthesis, confidence, audit and events. Stages *ask* the service to do these things;
  no stage does them itself.
- **Step**: one tool-calling round (the model or a plan asked for one or more tool calls and the
  service ran them). This is what `max_steps` counts, exactly as today.
- Types in tables: `string`, `integer`, `number`, `boolean`, `list<T>`, `map<K,V>`, `expr` (a
  `when` expression, section 8), `template` (a string with `{{...}}` references, section 4),
  `ref` (a state reference, section 8.4), `stage` (a stage id), `role` (a model role, section 3.6).
- Identifiers (planner names, stage ids, role names, custom slot names) match
  `^[a-z][a-z0-9_]{0,63}$`. Outcome names match `^[A-Za-z0-9_.@-]{1,64}$` (labels and planner
  names are outcomes), or are the wildcard `*`.

---

## 2. Files, names, versions and resolution

### 2.1 Layout

```
config/planners/
  react.yaml                 # current version of "react"
  plan_execute.yaml
  reflect.yaml
  reflect@1.0.0.yaml         # an older version kept so tools can stay pinned to it
  ...
```

- A planner's current file is `config/planners/<name>.yaml`; older versions that tools still
  pin are kept as `config/planners/<name>@<version>.yaml`. The registry indexes every file by
  the `name` and `version` *inside* it; the file name must agree (`name` equals the stem, and for
  the `@` form, `version` equals the suffix), or the file is refused (P002).
- Files are read with plain `yaml.safe_load`, like SAJHA's other YAML files, so standard YAML
  tools and editors read them the same way the loader does. That loader follows YAML 1.1, where
  the bare words `yes`, `no`, `on`, `off`, `true` and `false` (lower, Title or UPPER case) load
  as booleans. The format is shaped around it:
  - The transition map of a stage is the key `outcomes`, never `on` (a bare `on:` key would load
    as the boolean `true`).
  - An outcome name, rule `name` or `classify` label that is one of those words, or a number,
    must be quoted (`"yes": { next: run }`, `labels: ["yes", "no"]`). The loader never guesses: any
    key, rule name or label that did not load as a string is refused (P006).
- Files are read through the storage backend, like tool configs, so the directory is wherever
  the backend puts `config/`.
- The registry reloads on change. A changed file that fails validation does not replace the last
  good version of that `name@version`: the error is logged, `sajha_planner_load_errors_total`
  is incremented and running tools keep the old one (LLM Tools 9.12).
- Two valid files with the same `name@version` are a load error for the second one found, in
  sorted file-name order (P005).

### 2.2 Versions

`version` is a semantic version `MAJOR.MINOR.PATCH` (pre-release and build suffixes are
allowed and order per SemVer 2.0.0). It is required. Editing a planner without changing
`version` changes what every tool resolving that version runs; lint warns when a file's content
changes and its `version` does not (P070).

### 2.3 Name resolution

A planner reference is one of:

| Form | Resolves to |
|---|---|
| `name` | The highest valid version of `name` in the registry. |
| `name@latest` | The same as `name`. |
| `name@1.2.0` | Exactly that version; missing is an error (P033). Ranges (`^1.2`, `1.x`) are not supported. |
| an inline definition (an object) | That definition, for the referencing tool only (section 2.5). |

Which reference a call uses (version route, caller choice, tool config, server default) is the
resolution order of LLM Tools 9.12; it is not repeated here. References inside a planner file
(`planner` stages, `choices`, `rules_from`) use the same forms and are resolved when the file
loads; a file that pins nothing follows the newest version of each sub-planner, and lint lists
these unpinned references (P071, a warning).

### 2.4 Python planners

A file may name a Python planner instead of a graph (LLM Tools 9.10):

```yaml
name: my_strategy
version: 1.0.0
kind: python
class: mypackage.planners:MyStrategy      # a subclass of sajha.ai.planners.Planner
description: ...
use_when: ...
settings: { ... }                          # validated by the class's config_model
```

Only `name`, `version`, `kind`, `class`, `description`, `use_when` and `settings` are allowed
with `kind: python`. The class runs inside the service's enforcement exactly as today
(`next_action` returns `CallTools`, `Answer` or `Emit`). A Python planner can be used as a
`planner` stage's sub-planner; its end maps to the outcome `answered`.

### 2.5 Inline planners and overlays in a tool config

`llm.planner` (LLM Tools 5.1) may be an object of one of two shapes:

- **An inline planner**: a full planner definition (every key in section 3). `name` defaults to
  `<tool name>__inline` and `version` to the tool's `version`. It is validated when the tool loads.
- **An overlay**: `{ "use": "<reference>", "settings": {...}, "models": {...} }`. The referenced
  planner runs with `settings` keys replaced (shallow, per top-level key) and `models` roles
  re-pointed. Overlays cannot add stages or change limits upward. This is how one shared
  `recipes` file serves many tools, each with its own recipe list. An optional
  `"planners": { "<name>": { "settings": {...}, "models": {...} } }` overlays sub-planners by name
  for this tool's runs (for example the `recipes` rules a `router` reads), just as
  `ai.ask.planner_config` is keyed by planner name.

Overlays apply wherever the named planner is used in the run: as the top planner, as a `planner`
stage's sub-planner, and as the source of `rules_from` (section 6.5).

### 2.6 Today's `ai.ask.*` keys

`ai.ask.planner` keeps naming the Ask SAJHA page's planner and resolves against this registry
(LLM Tools 19). `ai.ask.planner_config.<name>` becomes an overlay on the Ask SAJHA page: its keys
replace that planner's `settings` wherever that planner is used. The shipped files declare `settings` with exactly the keys and defaults
of today's config models (`PlanExecuteConfig`, `RecipesConfig`, `RouterConfig`), so existing
`planner_config` blocks keep working unchanged (section 13).

---

## 3. Top-level keys

| Key | Type | Default | Constraints |
|---|---|---|---|
| `name` | string | required | Identifier; equals the file stem (section 2.1). |
| `version` | string | required | SemVer. |
| `kind` | string | `graph` | `graph` or `python`. |
| `class` | string | none | Required with `kind: python`, forbidden otherwise: `package.module:Class`. |
| `description` | string | required | 1 to 500 characters. Shown in the planner editor and the audit record. |
| `use_when` | string | required | 1 to 300 characters, one sentence. Read by automatic selection (section 6.6, `menu: planners`). |
| `models` | `map<role, string or null>` | `{}` | Roles used by stages, each mapped to a gateway alias, `provider/model`, `null` (the tool's model) or a settings reference. |
| `prompts` | `map<string, prompt>` | `{}` | Named prompts stages can refer to (section 3.7). |
| `settings` | `map<string, any>` | `{}` | Values the file exposes for overlays; read-only during a run. |
| `limits` | object | ceilings | Section 3.4. |
| `state` | `map<slot, slot declaration>` | `{}` | Custom state slots (section 5.3). At most 32. |
| `start` | stage | required | The first stage. |
| `stages` | `map<stage id, stage>` | required | 1 to 100 stages. |

Unknown top-level keys are an error (P004): a typo must not silently change behaviour.

### 3.1 `name`, `version`, `description`, `use_when`

Described above. `use_when` is a planner's advertisement to automatic selection: write what
questions it suits, not how it works ("Numeric questions where every figure must match the
data", not "verify then revise").

### 3.2 `kind`, `class`

Section 2.4.

### 3.3 `settings`

Any JSON value per key. Stages read settings in two ways: whole-value settings references
resolved at load (section 4.2), and `settings.<key>` in expressions and templates at run time
(the `settings` slot, section 5.1). Overlays (section 2.5) and `ai.ask.planner_config.<name>`
replace top-level keys of `settings` before validation, so a planner is always validated with the
values it will run with.

### 3.4 `limits`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `max_stages_run` | integer ≥ 1 | `ai.planners.limits.max_stages_run` | Stage executions in the whole run, sub-runs included. Exceeding it ends the run with `stopped_by: stage_limit`. |
| `max_steps` | integer ≥ 1 | the tool's | May only tighten the tool's `llm.limits.max_steps`. |
| `max_tool_calls` | integer ≥ 1 | the tool's | May only tighten. |
| `timeout_s` | number > 0 | the tool's | May only tighten. |
| `max_cost_usd` | number > 0 | the tool's | May only tighten. |
| `max_output_tokens` | integer ≥ 1 | the tool's | Per model call; may only tighten. |

The effective value of each is the minimum of the file's value, the tool's `llm.limits`, the
server ceiling (`ai.llm_tools.limits.*`, or `ai.planners.limits.max_stages_run`) and, in a
sub-run, the parent's remaining amount. A file value above a ceiling is clamped with a warning
(P060), never refused (LLM Tools 9.8).

### 3.5 `start`, `stages`

`start` names the stage the run begins at. `stages` maps stage ids to stage definitions
(section 6). Order in the file has no meaning.

### 3.6 `models`

Model-using stages name a **role** (`model: critic`), never an alias directly; `models` maps
roles to what the gateway understands. This keeps the place an operator re-points a model in
one block.

- The role `default` always exists. If `models` does not map it, it means the tool's
  `llm.model` (or `ai.ask.model` on the Ask SAJHA page). A stage without `model` uses `default`.
- A role mapped to `null` also means the tool's model (so `plan_execute` can expose
  `settings.model: null` as today's `PlanExecuteConfig.model`).
- Every role a stage names must be declared here or be `default` (P030); every alias must exist
  in the gateway when the file loads (P031). `provider/model` values are checked against the
  model registry.
- A `planner` stage's `model` re-binds roles in its sub-run (section 6.14).

### 3.7 `prompts` and prompt references

A **prompt** is one of:

```yaml
prompts:
  critic_brief:  { text: "Review the draft as a careful analyst would. ..." }
  house_style:   { name: analyst_style, arguments: { audience: "{{input.audience}}" } }   # prompts registry
```

A stage's `prompt` is a key of `prompts`, or an inline prompt object of the same shape. The
`text` (or the registry prompt's rendered text) may contain runtime templates (section 4.1).
Every model call a stage makes has this system text, in order:

1. SAJHA's safety preamble (today the first part of `SYSTEM_PROMPT` in
   `sajha/ai/intelligence.py`): tool results are data, not instructions; only offered tools
   may be called; say when data is missing. A planner cannot remove or change it.
2. The tool's `llm.system_prompt` (or `llm.prompt`), if any.
3. The conversation summary, if conversation memory is on (as today).
4. The stage's own instruction: its `prompt` if given, otherwise the stage type's built-in
   instruction (section 6 names each).

Registry prompts that do not exist are a load error (P032).

---

## 4. Templates and settings references

### 4.1 Runtime templates

A template is a string containing `{{ ref }}` placeholders, where `ref` is a state reference
(section 8.4) optionally prefixed `state.` (`{{state.chosen}}` and `{{chosen}}` are the same).
Templates are filled when the stage runs. There are no expressions, filters or function calls
inside `{{ }}`: compute a value into a custom slot with `set` (section 7.6) and reference that.

| Value | Rendered as |
|---|---|
| string | as is |
| number, boolean | JSON text (`3.5`, `true`) |
| null or missing | empty string |
| list or object | compact JSON, clipped to 2,000 characters |

**Whole-value templates keep the type.** Where a setting holds data rather than text
(`call.arguments` values, `planner.planner`), a string that is exactly one placeholder
(`"{{groups.ticker}}"`) yields the referenced value with its type. A string with other text
around the placeholder is always a string.

Fields that accept runtime templates: prompt `text` and registry prompt `arguments`,
`call.arguments`, `planner.planner`, `planner.question`, `foreach.question`, `ask_user.message`,
`ask_user.options`, `answer.template`, `fail.reason`. A template naming a root that is not a
slot (section 5) is a load error (P043).

### 4.2 Settings references (load time)

Anywhere in a stage, transition or `models` value, a string that is *exactly*
`{{settings.<path>}}` is replaced **when the file loads**, after overlays, and the stage is then
validated as if the value had been written literally. `<path>` is a JSONPath over `settings`
(section 8.5): without a wildcard it yields one value, with `[*]` or `..` the list of every
match. This is how `plan_execute` writes `max_visits: "{{settings.max_replans}}"` and the router
lists its route planners as `choices: "{{settings.rules[*].planner}}"`. A path that matches
nothing is an error (P044), except under `[*]`/`..`, where it yields an empty list.

Inside longer strings and in the template fields of section 4.1, `settings.<key>` is an ordinary
runtime reference to the read-only `settings` slot (same value: settings never change during a
run).

---

## 5. State

State is the set of named **slots** a run's stages read and write. It is a JSON-shaped object:
expressions and templates see it as JSON; stages read and write it through their declared inputs
and outputs. Every slot has a size bound (section 5.4); state lives in the run's working set and
spills to the run's spool like any other working-set item (LLM Tools 10.4).

### 5.1 Built-in slots

R means read-only to every stage (written by the service); stage names list who writes a slot.

| Slot | Type | Written by | Meaning and bound |
|---|---|---|---|
| `input` | object | R | The tool's validated arguments. Bounded by `max_input_chars`. |
| `original_question` | string | R | The question as asked. |
| `question` | string | `condense`, `ask_user` | The question stages work on: the standalone rewrite of a follow-up, plus any clarification. ≤ `max_input_chars`. In a `foreach` item or a `planner` stage with `question`, the rendered sub-question. |
| `history` | `list<{role, content}>` | R | The earlier turns loaded from memory (at most `ai.memory.history_turns` pairs), each clipped to `ai.memory.max_turn_chars`. Empty without memory. |
| `summary` | string | R | The conversation summary, or empty. |
| `shortlist` | `list<{name, description, score}>` | R (recomputed by `condense`) | The access-filtered tools offered to this run. At most `ai.ask.shortlist` entries (descriptions clipped to 300 characters). |
| `results` | `list<result>` | `act`, `execute`, `call`, and sub-runs | Every tool call of the run, in order (section 5.2). At most `max_tool_calls` entries. |
| `plan` | `list<plan step>` | `plan`, `execute`, `vote` | The current plan (section 5.2). At most `max_plan_steps × (1 + re-plans)` steps. |
| `plan_revision` | integer | `plan` | 0 for the first plan, +1 per re-plan. |
| `draft` | string | `act`, `draft`, `revise`, `vote`, `answer` | The answer text so far. ≤ 4 × the effective `max_output_tokens` characters. |
| `draft_json` | object or null | `draft` | The structured reply of the last `draft`/`revise` (with the default schema: `{answer, citations, caveats}`). |
| `draft_source` | string | as `draft` | Which stage type produced `draft`: `none`, `act`, `draft`, `revise`, `vote`, `template`, `subrun`. Decides synthesis (section 6.17). |
| `citations` | `list<string>` | `draft`, `revise`, `vote` | Call ids the draft relies on; always filtered to successful results. |
| `caveats` | `list<string>` | many stages | Limitations to report with the answer. At most 20, each ≤ 300 characters. |
| `critique` | `{verdict, issues}` or null | `critique`; cleared by `revise` | Section 6.8. At most 20 issues. |
| `findings` | `list<{check, message, value}>` | `verify`; cleared by `revise` and by `verify` ok | Section 9. At most 50. |
| `candidates` | `list<candidate>` | `sample` | Section 6.11. At most `ai.planners.limits.max_samples`. |
| `vote` | object or null | `vote` | `{method, winner, counts, agreement}`. |
| `chosen` | string or null | `classify`, `vote` (labels) | The most recent label. |
| `choice` | object or null | `classify` | `{label, confidence, by, reason}`; `by` is `rule`, `model` or `default`. |
| `groups` | `map<string,string>` | `match` | Named groups of the matching rule (values ≤ 500 characters). |
| `rule` | object or null | `match` | The matching rule as written, including extra fields (`tool`, `arguments`, `answer`, `planner`, ...). |
| `matched` | string or null | `match` | The matching rule's name. |
| `items` | list | any stage via `into`, or `draft` with a schema | Conventional input for `foreach`. At most `ai.planners.limits.max_foreach_items`. |
| `item` | any | R (in a `foreach` item sub-run) | The current item. |
| `outputs` | `list<output>` | `foreach` | Section 6.13. |
| `user_reply` | any | `ask_user` | The caller's reply (string, chosen option, or boolean for `confirm`). |
| `confidence` | number | R | Provisional confidence: the composition-framework calculation of today's `_confidence` over the results gathered so far (0.5 with no tool results). Recomputed after every stage. |
| `subrun` | object or null | `planner` | The last sub-run: `{planner, version, outcome, stopped_by, stages_run, reason}`. |
| `last` | object | R | `{stage, type, outcome}` of the previous stage. |
| `counters` | object | R | `{stages_run, steps, tool_calls, tokens, cost_usd, elapsed_s, model_calls}` for the whole run. |
| `remaining` | object | R | `{steps, tool_calls, tokens, cost_usd, seconds, stages}` left for this run or sub-run. |
| `settings` | object | R | The file's settings after overlays. |
| `planner` | object | R | `{name, version, chain, path}`: this planner, the chain of planners (`router>react`) and the stage path so far (≤ the last 200 entries). |

A `result` and a `plan step` have these shapes:

```yaml
result:
  id: plan_s1                 # the call id; citations name it
  tool: fred_series
  arguments: { series_id: GDP }
  ok: true
  status: ok                  # ok | error | refused | needs_confirmation | needs_connection | not_run
  summary: "GDP: 28,269.2 (2024-Q4) ..."     # the service's one-line summary, ≤ 300 characters
  preview: "{...}"            # the result text the model sees, ≤ ai.ask.max_result_chars
  data: { ... }               # the parsed structured result when held in memory; null when spilled
  spilled: false              # true when the full result is in the run's spool
  stage: execute              # the stage that made the call
  planner: plan_execute

plan step:
  id: s1                      # re-plans prefix ids: r1_s1
  tool: fred_series
  arguments: { series_id: GDP }          # may contain {{s1.field}} step references
  depends_on: []
  why: "Latest GDP level"
  status: pending             # pending | running | ok | failed | skipped
  call_id: plan_s1
```

These are today's shapes (the `AskStep` record and `_PlanStep.public()` in
`sajha/ai/planners.py`), so the plan event and the Ask SAJHA page do not change.

### 5.2 How stages read and write

- Each stage type has fixed **inputs** (slots it reads) and **outputs** (slots it writes),
  listed with the stage in section 6. A stage never writes a slot that is not among its outputs.
- Stages that produce one primary value (`match`, `classify`, `draft` with a schema, `sample`,
  `foreach`, `ask_user`, `call`) accept `into: <slot>` to write that value to a custom slot
  instead of (for `call`, in addition to) the built-in one. The custom slot's declared type must
  accept the value (P051).
- `set` (section 7.6) assigns expression values to custom slots after a stage ends.
- Read-only slots (R) are never written by a stage, including through `into` and `set` (P052).
- The model sees state only through prompts: the transcript (question, history, tool calls and
  results as today), plus whatever the stage's prompt template references.

### 5.3 Custom slots

```yaml
state:
  tickers:    { type: array, items: string, max_items: 20, default: [] }
  plan_size:  { type: integer, default: 0 }
  notes:      { type: string, max_chars: 2000 }
```

| Key | Type | Default | Constraints |
|---|---|---|---|
| `type` | string | required | `string`, `number`, `integer`, `boolean`, `array`, `object`, `any`. |
| `items` | string | `any` | For `array`: the element type. |
| `default` | any | `null` | Must match `type`. |
| `max_chars` | integer | 4,000 | For `string`; longer values are clipped with a caveat. |
| `max_items` | integer | 100 | For `array`; extra items are dropped with a caveat. |
| `max_kb` | integer | 64 | For `object`/`any`: the serialised size; a larger value spills to the spool. |
| `description` | string | none | ≤ 300 characters. |

Names must be identifiers and must not be a built-in slot name (P050). A custom slot is private
to the planner that declares it: a sub-run's custom slots are fresh and invisible to its parent.

### 5.4 Size bounds, forks and sharing

- Every write is measured. A value over its bound is clipped (strings, lists) with a caveat, or
  spilled to the spool (results, objects), never refused.
- **`planner` stage sub-runs share** the parent's built-in slots (they see and extend the same
  `results`, `plan`, `draft`, transcript), which is how the router hands an ask to another
  strategy today. Custom slots are not shared.
- **`sample` and `foreach` sub-runs fork**: each gets a copy-on-write view of the parent's state
  at the fork; only its candidate or output, its results and its caveats come back (section 6.11,
  6.13). Results from forks are merged into the parent's `results` (deduplicated by call
  fingerprint) so citations and verification can use them.

---

## 6. Stages

### 6.0 Keys every stage accepts

| Key | Type | Default | Meaning |
|---|---|---|---|
| `type` | string | required | The stage type (sections 6.1 to 6.18), or a custom type registered in code (LLM Tools 9.10). |
| `description` | string | none | ≤ 300 characters; shown in the editor and in stage events. |
| `when` | expr | none | **Guard.** Evaluated before the stage runs. True: the stage runs. False: it does not run, and the `else` transition is taken. |
| `else` | transition | required with `when` | Section 7. |
| `next` | stage | none | Shorthand for `outcomes: { "*": { next: <stage> } }`. Not with `outcomes`. |
| `outcomes` | `map<outcome, transition or list<transition>>` | required for non-terminal stages unless `next` | Section 7. |
| `set` | `map<custom slot, expr>` | none | Section 7.6. |

Model-using stages (`act`, `plan`, `classify`, `draft`, `critique`, `revise`, `vote` with
`method: judge`, `condense`) also accept:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `model` | role | `default` | Section 3.6. |
| `prompt` | prompt reference | the type's built-in instruction | Section 3.7. |
| `temperature` | number 0 to 2 | the tool's, else `ai.ask.temperature` | Per call. |
| `max_output_tokens` | integer ≥ 1 | the effective limit | Clamped to it. |
| `stop` | `list<string>` | none | At most 4, each ≤ 32 characters. |
| `retry` | integer 0 to 2 | 1 for structured stages, 0 for `act` | Structured stages: re-ask once with the validation errors when the reply does not match the stage's schema (LLM Tools 9.6). |

Every model call goes through the gateway bound to the caller, so role policy, per-user
budgets, fallback, the response cache and a `model` event per call apply to every stage. A
model error that is not a schema mismatch ends the run unless the stage says otherwise below:
`stopped_by: refused` for a refusal or content filter (LLM Tools 13.6), `budget` when a token
budget is used up, otherwise `error` with the gateway's error code.

Each stage subsection gives: settings, reads, writes, outcomes, model calls, how it meets the
service's enforcement, and errors.

### 6.1 `act`

One model call with the offered tools: the model answers or asks for tool calls, which the
service runs as the caller. A ReAct step; today's `ReactPlanner.next_action`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `tools.allow` / `tools.deny` | `list<glob>` | all offered | Narrows the shortlist for this stage only. Can never widen it. |
| `tool_choice` | string | `auto` | `auto`, `required` or `none`. With no tools offered it is always `none`. |
| `parallel` | boolean | `false` | Whether the service may run the model's several calls of one turn together (today's react: `false`). |

- **Reads:** the transcript (history, question, earlier calls and results), `shortlist`.
- **Writes:** on `called`, the transcript, `results`, `counters.steps` (+1); on `answered`,
  `draft` (the model's text), `draft_source: act`, `citations: []`.
- **Outcomes:** `called` when the reply requests at least one tool call (even if the service then
  refuses some); `answered` otherwise.
- **Model calls:** 1.
- **Enforcement:** a call to a tool that was not offered is refused and recorded as a `refused`
  result; destructive calls without confirmation, and calls the policy engine sends for approval
  by the caller, end the run with `needs_confirmation`; a call needing a connected account that
  is not linked ends it with `needs_connection`; calls beyond `max_tool_calls` are not run and end
  the run with `tool_limit`; each `called` visit is one step against `max_steps`. All exactly
  as today.
- **Errors:** invalid tool-call arguments become an `error` result (the outcome is still
  `called`).

### 6.2 `plan`

One structured-output call that returns a plan of tool steps with dependencies, validated
against today's `PLAN_SCHEMA`. Today's `PlanExecutePlanner._request_plan`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `context` | string | `transcript` | `transcript`: the model sees the conversation and every result so far (plan-and-execute). `question`: it sees only the question and the offered tools' specs (ReWOO: planning without observations). |
| `max_plan_steps` | integer 1 to 32 | 8 | Steps kept from one reply. |
| `replan_note` | template | today's `REPLAN_NOTE` | The note added on a re-plan. |
| `retry` | integer | 1 | See 6.0. |

- **Built-in instruction:** today's `PLAN_PROMPT`.
- **Re-plan:** a visit is a re-plan when `plan` holds at least one `failed` step. The model is
  told which steps failed (`replan_note` plus the original question), new step ids are prefixed
  `r<revision>_` and the steps are **appended** to `plan`; `plan_revision` increases. Any other
  visit **replaces** `plan`.
- **Reads:** transcript or question, `shortlist`, `plan`.
- **Writes:** `plan`, `plan_revision`; emits a `plan` event (today's shape).
- **Outcomes:** `planned` when at least one step with a `tool` was returned; `invalid` when the
  reply did not validate after `retry`, or returned no usable steps, or nothing is offered (the
  model is then not called).
- **Model calls:** 1, plus `retry`.
- **Enforcement:** steps naming tools that were not offered are kept and refused when executed
  (as today). Argument strings that are not JSON objects become `{}`.

### 6.3 `execute`

Runs the plan's steps through the service, independent steps together, until nothing more can
run. Today's `PlanExecutePlanner.next_action` and `_refresh`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `max_parallel` | integer ≥ 1 | 4 | Calls per round; clamped to `ai.planners.limits.max_parallel`. |
| `from` | ref | `plan` | The slot holding the plan (a custom slot of plan steps is allowed). |

**Algorithm.** Repeat: (1) mark `running` steps `ok` or `failed` from their results; (2) mark
`skipped`, repeatedly, every `pending` step with a dependency that is `failed`, `skipped` or
unknown; (3) the ready steps are `pending` steps whose dependencies are all `ok`; if none, stop;
(4) take the first `max_parallel` in plan order; resolve `{{<step id>.<field>}}` references in
their arguments from earlier results (today's `resolve_references`: a whole-value reference keeps
its type, `.result` is unwrapped, a missing field marks the step `skipped`); (5) ask the service
to run them as one round (`parallel` when more than one). Each round is one step.

- **Reads:** `plan` (or `from`), `results`. **Writes:** `plan[*].status`, `results`, the
  transcript, `counters.steps`.
- **Outcomes:** `failed_steps` when any step of the plan has status `failed` after the loop;
  `done` otherwise (including an empty plan). Skipped steps alone do not make `failed_steps`
  (as today: only failures trigger a re-plan).
- **Model calls:** 0.
- **Enforcement:** as `act`: refusals, confirmation, connections, tool-call and step limits.

### 6.4 `call`

One fixed tool call with templated arguments: a recipe's call. Today's `RecipesPlanner.start`
and its first `next_action`.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `tool` | string | required unless `from_rule` | An exact tool name. Must match `llm.tools.allow` at load (P036). |
| `arguments` | `map<string, any>` | `{}` | Values may be runtime templates; whole-value templates keep the type. |
| `from_rule` | boolean | `false` | Take `tool` and `arguments` from the matched rule (`rule.tool`, `rule.arguments`), with today's recipe semantics: rule arguments use `{group}` placeholders filled from `groups` (unknown placeholders are left as written); with no rule arguments, the named groups that are properties of the tool's input schema. |
| `coerce` | boolean | `true` | Convert string values to the input schema's `integer`/`number` types (thousands separators removed), as today's `_coerce`. |
| `emit_plan` | boolean | `false` | Emit a one-step `plan` event (today's recipes do). |

- **Call id:** `<stage id>_<first 8 hex of sha1(canonical arguments)>`; with `from_rule`,
  `recipe_<rule name>_<digest>` as today.
- **Reads:** `groups`, `rule`, any slot the templates name. **Writes:** `results` (and `into`,
  when given, receives that result's `data`), the transcript, `counters.steps` (+1).
- **Outcomes:** `done` when the call succeeded; `error` when it failed, was refused, or the tool
  is not offered to this run (no call is made then; the result is recorded `not_run`).
- **Model calls:** 0.
- **Enforcement:** the call goes through the same path as a model's call, so access, policy,
  confirmation and limits apply; a `call` stage can never reach a tool the caller cannot.

### 6.5 `match`

Deterministic matching of regular expressions or keywords against the question; no model.
Today's `match_recipe` and the router's rules.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `rules` | `list<rule>` | required unless `rules_from` | At most 200. May be a settings reference. |
| `rules_from` | string | none | `<planner reference>.<stage id>`: reuse another planner's `match` rules (after its overlays). |
| `against` | ref | `question` | The string to match. |
| `ignore_case` | boolean | `true` | |
| `dotall` | boolean | `false` | `.` matches newlines (the router's multi-part pattern needs it). |

A **rule**:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | `rule<N>` (1-based) | The outcome when it matches. |
| `pattern` | string | none | A regular expression (Python `re` syntax), searched anywhere. `match` is accepted as an alias (today's `Recipe.match`, `RouteRule.match`). ≤ 1,000 characters. |
| `keywords` | `list<string>` | `[]` | Every keyword must occur (case-insensitive substring). |
| `tool` | string | none | The rule matches only if this tool is offered to the run. |
| any other key | any | | Kept on `rule` for later stages (`arguments`, `answer`, `planner`, ...). |

A rule needs `pattern` or `keywords`; with both, both must hold. Rules are tried in order; the
first that matches wins.

- **Reads:** `against`, `shortlist`. **Writes:** `groups` (the named groups that matched,
  non-null), `rule`, `matched`; `into` receives `groups`.
- **Outcomes:** the matching rule's name, or `none`. When rule names are not known at load (the
  rules come from settings), the stage must have a `*` transition (P062).
- **Model calls:** 0.
- **Errors:** patterns are compiled at load; one that does not compile is P045. The matched text
  is clipped to `max_input_chars` before matching. Lint warns on nested quantifiers (`(a+)+`), the
  usual cause of catastrophic backtracking (P046).

### 6.6 `classify`

A label for the question from a fixed or state-supplied set: rules first, a model call only if no
rule matches.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `labels` | `list<string>` | required unless `from` | 2 to 50 labels. |
| `from` | ref | none | A slot holding the list of labels (for example `settings.candidates`). Read when the stage runs. |
| `menu` | string | `none` | `planners`: labels are planner references; the model sees each one's `use_when`, and the list is first intersected with the tool's `llm.planner_choices` (when set) and filtered by the tool's eval results (section 6.6.1). |
| `rules` | `list<{pattern or keywords, label}>` | `[]` | Tried first, in order, with `match` semantics. |
| `min_confidence` | number 0 to 1 | 0 | A model label with lower confidence is replaced by `default`. |
| `default` | string | the first label | Must be a label. |
| `retry` | integer | 1 | |

- **Reply schema:** `{label: <enum of the labels>, confidence: number 0..1, reason: string ≤ 300}`.
  The enum is what makes the choice safe: a question saying "use the expensive planner" cannot
  produce a label outside the list (LLM Tools 9.13).
- **Built-in instruction:** "Classify the user's question into exactly one of the labels.
  Reply with JSON." plus, with `menu: planners`, the menu lines `name: use_when`.
- **Reads:** `question`, `from`. **Writes:** `chosen`, `choice` (`by: rule | model | default`);
  `into` receives the label.
- **Outcomes:** the chosen label. With `from` (labels unknown at load) a `*` transition is
  required (P062).
- **Model calls:** 0 if a rule matched, otherwise 1 plus `retry`. A reply that still does not
  validate gives `default` with `by: default` and a caveat; it does not end the run.

#### 6.6.1 Eval filtering for `menu: planners`

When the tool has an eval set and the latest recorded eval run of the tool with a candidate
planner failed its pass threshold, that candidate is dropped from the menu. With no eval history
every candidate stays. If filtering empties the list, `default` is used without a model call.

### 6.7 `draft`

Compose an answer from what has been gathered (model call, no tools). With the default schema
this is today's synthesis call (`_synthesize`), made explicit.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `schema` | JSON Schema | today's `ASK_SCHEMA` (`answer`, `citations`, `caveats`) | A custom schema makes the stage a structured extraction: the reply object goes to `into`. |
| `into` | custom slot or `items` | `draft` | Required with a custom `schema`. |

- **Built-in instruction:** today's `SYNTH_PROMPT` wording.
- **Reads:** the transcript (including `foreach` outputs, section 6.13), `question`, `results`.
- **Writes:** default schema: `draft`, `draft_json`, `citations` (only ids of successful
  results; all successful ids when the model names none, as today), `caveats`,
  `draft_source: draft`. Custom schema: `into` only.
- **Outcomes:** `done`. With a custom schema, also `invalid` when the reply does not validate
  after `retry`.
- **Model calls:** 1 plus `retry`.
- **Errors:** with the default schema, any model failure falls back to the existing `draft`, or
  the successful results' summaries joined, with a caveat, and the outcome is still `done`
  (today synthesis failures fall back the same way).

### 6.8 `critique`

A model reviews the draft against the question, the results and a rubric.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `rubric` | `list<string>` | `[answers every part of the question, no claim without a tool result, says what is missing]` | 1 to 20 criteria, each ≤ 200 characters. |

- **Reply schema:** `{verdict: "pass" | "revise", issues: [{criterion, problem, suggestion}]}`,
  at most 20 issues.
- **Reads:** `question`, `draft`, `citations`, the results' previews, `findings`.
- **Writes:** `critique`.
- **Outcomes:** `pass`, or `revise`. A `revise` verdict with no issues counts as `pass`.
- **Model calls:** 1 plus `retry`. A reply that still does not validate gives `pass` with the
  caveat "self-review could not run", so a broken critic cannot loop a run.

### 6.9 `revise`

Rewrite the draft to address the critique and verification findings.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `address` | string | `all` | `critique`, `findings` or `all`: which issues the model is given. |

- **Reply schema:** today's `ASK_SCHEMA`.
- **Reads:** `question`, `draft`, `critique`, `findings`, the transcript.
- **Writes:** `draft`, `draft_json`, `citations`, `caveats`, `draft_source: revise`; clears
  `critique` and `findings`.
- **Outcomes:** `done`.
- **Model calls:** 1 plus `retry`. On failure the draft is unchanged, a caveat is added and the
  outcome is still `done`.

### 6.10 `verify`

Deterministic checks of the draft, no model.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `checks` | `list<check name or {check, ...settings}>` | required | 1 to 20 checks from section 9. |
| `stop_at_first` | boolean | `false` | Stop after the first failing check. |

- **Reads:** `draft`, `draft_json`, `citations`, `question`, `results` (full results, streamed
  back from the spool when spilled).
- **Writes:** `findings` (replaced each visit; empty on `ok`).
- **Outcomes:** `ok` when every check passes; `mismatch` otherwise.
- **Model calls:** 0.
- **Errors:** a check that cannot run (for example `schema_valid` with no structured draft) is a
  failing check with that reason.

### 6.11 `sample`

Run one sub-step `n` times in parallel at varied temperature, collecting candidates.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `of` | inline stage | required | One stage of type `draft`, `plan`, `classify`, or `planner` (no `outcomes`, `next`, `when` or `set`). |
| `n` | integer ≥ 2 | 3 | Clamped to `ai.planners.limits.max_samples`. |
| `temperature` | `{from, to}` | `{from: 0.2, to: 1.0}` | Sample *i* of *n* uses `from + (to − from) × i / (n − 1)`. |
| `concurrency` | integer ≥ 1 | `ai.planners.limits.max_parallel` | Clamped to it. |

- Each sample runs in a fork (section 5.4). A `planner` sample is a whole sub-run (for example
  `react`), so tools may be called *n* times; the tool output cache makes repeats cheap where
  tools allow caching.
- **Writes:** `candidates`: `[{id: c1.., kind: draft | plan | label | answer, value, temperature,
  ok, citations}]`; merged `results`; `into` receives the list.
- **Outcomes:** `done` (also when every sample failed: `candidates` then holds only failures and
  `vote` ends `tie`).
- **Model calls:** `n` × the sub-step's calls.

### 6.12 `vote`

Pick one candidate: majority on a normalised value (self-consistency) or a judge model.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `method` | string | `majority` | `majority` or `judge`. |
| `normalise` | string | `text` | `majority` only: `text` (lower case, whitespace collapsed, punctuation removed), `numbers` (the ordered list of numbers in the text, parsed as in section 9.1, rounded to 3 significant digits; a candidate with no numbers is compared by `text`), `json` (canonical JSON, sorted keys) or `label`. |
| `rubric` | `list<string>` | as `critique` | `judge` only. |
| `tie_break` | string | `none` | `none` (outcome `tie`), `first` (lowest candidate id among the tied) or `judge` (one judge call over the tied). |

- **Judge reply schema:** `{winner: <enum of candidate ids>, reason: string}`.
- **Reads:** `candidates`, `question`, results' previews (judge).
- **Writes:** `vote`; the winner's value to `draft` (+ `citations`, `draft_source: vote`), `plan`
  (and a `plan` event) or `chosen`, by the candidates' kind.
- **Outcomes:** `done`; `tie` when no single winner and `tie_break: none`, or when there is no
  successful candidate.
- **Model calls:** 0 for `majority` (1 if `tie_break: judge` fires), 1 plus `retry` for `judge`.

### 6.13 `foreach`

Map a sub-graph over a list, with bounded concurrency; collect the outputs (the "map" of
map-reduce; a following `draft` is the "reduce").

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `items` | ref | `items` | A list slot. |
| `as` | identifier | `item` | The slot name of the current item inside the sub-run (always readable as `item` too). |
| `do` | `{start, stages}` | required unless `planner` | An inline sub-graph with the same rules as a file's graph. |
| `planner` | planner reference | none | Instead of `do`: run this planner per item. |
| `question` | template | `{{question}}` | The sub-run's `question`, for example `"{{original_question}} (for {{item}})"`. |
| `max_items` | integer | `ai.planners.limits.max_foreach_items` | Clamped to it; further items are dropped. |
| `concurrency` | integer ≥ 1 | 2 | Clamped to `ai.planners.limits.max_parallel`. |
| `item_answer_chars` | integer | 2,000 | Each output's `answer` is clipped to this. |

- Each item runs in a fork; a `do` graph or `planner` counts one level of sub-planner depth.
- **Writes:** `outputs`: `[{index, item, answer, citations, ok, stopped_by}]` (or `into`);
  merged `results` and `caveats`; one delimited data message summarising the outputs is added to
  the transcript so a following `draft` sees them.
- **Outcomes:** `done` when every item's sub-run ended `answered` and none was dropped; `partial`
  otherwise. An item whose sub-run fails is recorded `ok: false` and does not stop the others.
- **Model calls:** whatever the sub-runs make.
- Run-wide limits (steps, tool calls, cost, time, stages) are shared by all items; reaching one
  ends the whole run.

### 6.14 `planner`

Run another planner as a sub-graph (LLM Tools 9.7): the router's hand-over, a fallback, an
escalation.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `planner` | planner reference or template | required | A name, `name@version`, an overlay object (section 2.5), or a runtime template (`"{{chosen}}"`). |
| `choices` | `list<planner reference>` | required with a runtime template | Every value the template may take; each is resolved and validated at load. A runtime value outside the list makes the outcome `failed` with reason `planner not in choices`. |
| `model` | role | none | Re-bind every role of the sub-run (and its sub-runs) to this role's model in the parent. |
| `question` | template | unchanged | A different `question` for the sub-run. |
| `limits` | object | the parent's remaining | A sub-budget: any of `max_steps`, `max_tool_calls`, `max_cost_usd`, `timeout_s`, `max_stages_run`; each is clamped to the parent's remaining amount. |

- **Sharing:** the sub-run shares the parent's built-in slots (section 5.4). Its `answer` and
  `fail` stages end the *sub-run*, not the run.
- **Writes:** `subrun`; whatever the sub-run's stages write; `planner.chain` gains the
  sub-planner (`auto>react`), as today's `chosen` chain does.
- **Outcomes:** `answered` (the sub-run reached an `answer` stage, or a Python planner returned
  `Answer`), `failed` (it reached `fail`, or the runtime choice was not allowed), `stopped` (its
  own sub-budget ran out; `subrun.stopped_by` names which limit). Run-wide limits still end the
  whole run.
- **Errors:** a planner that includes itself directly or through others is refused at load
  (P034); nesting deeper than `ai.planners.limits.max_subplanner_depth` is refused (P035).

### 6.15 `ask_user`

Ask the caller for missing information or a choice.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `message` | template | required | What to ask, ≤ 1,000 characters after rendering. |
| `kind` | string | `text` | `text`, `choice` or `confirm`. |
| `options` | `list<string>` or template | required for `choice` | 2 to 20 options. |
| `append_to_question` | boolean | `true` for `text` and `choice`, `false` for `confirm` | Append `"\nClarification: <reply>"` to `question`. |

- **On 2026-07-28** with a client that supports form elicitation, the call returns an MRTR input
  request (`elicitation/create`, the mapping in `sajha/core/mcp_mrtr.py`); the run's state is
  saved in the state store and the run resumes at this stage's outcome when the client answers.
- **Elsewhere** (2025-11-25, REST, CLI, workflows, A2A, clients without elicitation, anonymous
  callers) the run ends with `stopped_by: needs_input`; the result carries
  `input_request: {message, kind, options}` and the best answer so far. With conversation memory,
  the caller's next question in the same conversation is the reply.
- **Writes:** `user_reply` (or `into`); `question` per `append_to_question`.
- **Outcomes:** `answered` (a reply, including "no" to a `confirm`, which gives
  `user_reply: false`), `declined` (the client declined or cancelled).
- **Model calls:** 0. At most 3 `ask_user` visits per run; a fourth ends the run with
  `needs_input`.

### 6.16 `condense`

Rewrite a follow-up into a standalone question using conversation memory.

- **Settings:** the model keys of 6.0 only.
- **Implicit condensing:** if a planner graph (including its sub-planners) has no `condense`
  stage, the service condenses before the graph starts, exactly as today. If it has one, the
  service does not, and the stage decides.
- **Reads:** `original_question`, `history`, `summary`. **Writes:** `question`; `shortlist` is
  recomputed for the new question.
- **Outcomes:** `done`.
- **Model calls:** 1, or 0 when there is no history.

### 6.17 `answer` (terminal)

Finish with the current draft.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `synthesize` | string | `auto` | `auto`: run the service's synthesis when `results` is not empty and `draft_source` is `none` or `act` (today: react answers and plan_execute ends are synthesised; drafted answers need no second pass). `always`, `never`. |
| `template` | template | none | Render this into `draft` (`draft_source: template`) before finishing. |
| `template_from` | string | none | `rule`: use the matched rule's `answer` field with today's recipe semantics (single-brace `{field}` placeholders over `groups` and the last result's top-level and `result` fields), only when the last call succeeded and the field is not empty. |
| `caveats_from_findings` | boolean | `true` | Unresolved `findings` become caveats. |

- **At the top level:** the run ends `stopped_by: answer`; the service then (as today)
  synthesises if required, computes confidence and citations, records memory, writes the audit
  record and streams the answer.
- **In a sub-run:** ends the sub-run with outcome `answered`. No synthesis happens there; the
  parent's `answer` decides.
- **Model calls:** 0, or 1 for synthesis (made by the service).
- A guard on an `answer` stage (`when` with `else`) is how a planner says "answer if good enough,
  otherwise go on" (section 13.12).

### 6.18 `fail` (terminal)

Finish with a stated reason.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `reason` | template | required | ≤ 500 characters after rendering. |

- **At the top level:** the run ends `stopped_by: failed`, `isError: true`, with the reason as
  the answer text and any partial findings as caveats.
- **In a sub-run:** ends the sub-run with outcome `failed` and `subrun.reason`.

---

## 7. Transitions

### 7.1 Forms

```yaml
outcomes:
  answered: { next: verify }                                   # one transition
  called:   { next: act, max_visits: 6, on_exhausted: draft }  # a bounded edge
  mismatch:                                                    # conditional alternatives, tried in order
    - { next: split,   when: "'parts_answered' in $.findings[*].check", max_visits: 1, on_exhausted: answer }
    - { next: reflect, max_visits: 1, on_exhausted: answer }
  "*":      { next: answer }                                   # every other outcome
next: answer                                                   # shorthand: outcomes: { "*": { next: answer } }
```

A **transition** has:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `next` | stage | required | The stage to go to. |
| `when` | expr | none (always) | The transition applies only if this holds (section 8). |
| `max_visits` | integer 0 to `max_visits_per_edge`, `"steps"`, or a settings reference | none (unbounded) | How many times this edge may be taken in one run or sub-run (section 7.3). |
| `on_exhausted` | stage | required with an integer `max_visits` | Where to go instead once the edge has been taken `max_visits` times. |

Each key under `outcomes` is an outcome name or `*`. Its value is one transition or a list of 1 to 10
transitions.

### 7.2 Choosing the transition

After a stage ends with outcome *o* (or its guard was false, which uses `else` directly):

1. Let *L* be `outcomes[o]` if present, otherwise `outcomes["*"]`. A one-transition value is a list of one.
2. Take the first transition in *L* whose `when` is absent or evaluates to `true`. An
   expression error counts as `false` (section 8.8).
3. If none applies and *L* was `outcomes[o]`, repeat step 2 with `outcomes["*"]` if present.
4. If still none applies, the run ends with `stopped_by: error`, error code `no_transition` ("no
   transition for outcome *o* at stage *s*"); lint warns of any outcome whose alternatives all carry `when` and
   that has no unconditional `*` (P016).
5. Apply the bound of the chosen transition (section 7.3), then run `set` (section 7.6), then
   move.

### 7.3 Bounded edges

- An **edge** is identified by (stage, outcome key, position in the list) and the `else` of a
  guard is the edge (stage, `else`). Each edge has a visit counter, per run and per sub-run
  (a sub-run's counters start at zero; a `foreach` item's are its own).
- Taking an edge with integer `max_visits` *m*: if it has been taken *m* times already, go to
  `on_exhausted` instead, emit a `loop_exhausted` event and increment
  `sajha_planner_loops_exhausted_total{planner,edge}`. Otherwise go to `next` and count. So
  `max_visits: 2` allows two traversals, and `max_visits: 0` means "always go to
  `on_exhausted`" (a switch a setting can turn off).
- `max_visits: "steps"` is a bound by the step limit rather than a count: it is allowed only on
  an `act` stage's `called` outcome and an `execute` stage's outcomes, where every traversal has
  just spent at least one step, so `max_steps` is guaranteed to end the loop. It needs no
  `on_exhausted`; the run ends with `stopped_by: step_limit` as today's step limit does. This is
  how the shipped `react` keeps today's behaviour exactly (section 13.1).
- `on_exhausted` is an ordinary edge for cycle analysis and is not itself bounded.

### 7.4 Cycles must be bounded

At load: remove every bounded edge (integer or `"steps"` `max_visits`) from the graph of all
edges (every `next`, every `on_exhausted`, every `else`); what remains must be acyclic. A
remaining cycle is P020, and the message lists it (`act -> verify -> act`). This is LLM Tools 9.5
rule 1, made exact: every cycle crosses at least one bounded edge.

### 7.5 Reachability and termination

- Every stage must be reachable from `start` (P013).
- From every stage, some terminal stage (`answer` or `fail`) must be reachable (P063). With
  bounded cycles, every run then ends: each loop can only repeat a bounded number of times, and
  `max_stages_run` ends it regardless.
- Terminal stages have no `outcomes` or `next` (P017). A non-terminal stage needs `outcomes` or
  `next` (P014).

### 7.6 `set`

```yaml
plan:
  type: plan
  set: { plan_size: "len(plan)" }
  outcomes: { planned: { next: gate } }
```

`set` maps custom slots to expressions. After the stage ends (or its guard fails) and before the
transition's `when` is evaluated, each expression is evaluated against the state and assigned,
in the order written. Only custom slots may be set (P052); the value must match the slot's type,
otherwise the assignment is skipped with an `expression_error` event.

### 7.7 Guards

`when` and `else` on a *stage* form a guard: when the expression is false the stage does not run,
no outcome is produced and `else` (a transition, which may be bounded) is followed. A guarded-out
stage still counts towards `max_stages_run`. Guards make "skip planning when nothing is offered"
and "answer only if confident enough" one line each.

---

## 8. The `when` expression language

Expressions decide transitions, guards, `set` values and the `expression` verify check. They are
parsed once at load into a tree; evaluating one reads state and calls a fixed set of pure
functions. There is no assignment, no loop, no attribute access beyond data, no import, no
`eval`, and no way to call a tool or a model: an expression cannot execute code.

### 8.1 Grammar (EBNF)

```ebnf
expression   = or_expr ;
or_expr      = and_expr , { "or" , and_expr } ;
and_expr     = not_expr , { "and" , not_expr } ;
not_expr     = "not" , not_expr | comparison ;
comparison   = operand , [ comp_op , operand ] ;              (* no chaining: a < b < c is an error *)
comp_op      = "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not" , "in" ;
operand      = literal | list | call | jsonpath | reference | "(" , expression , ")" ;
list         = "[" , [ expression , { "," , expression } ] , "]" ;
call         = function , "(" , [ expression , { "," , expression } ] , ")" ;
function     = "len" | "exists" | "empty" | "lower" | "number" | "matches" | "visits" | "offered" ;
reference    = root , { "." , name | "[" , integer , "]" | "[" , quoted , "]" } ;
root         = name ;                                         (* a slot: built-in, custom, settings or input *)
jsonpath     = "$" , { "." , ( name | "*" ) | ".." , ( name | "*" ) | "[" , ( integer | quoted | "*" ) , "]" } ;
literal      = number | quoted | "true" | "false" | "null" ;
number       = [ "-" ] , digits , [ "." , digits ] , [ ( "e" | "E" ) , [ "+" | "-" ] , digits ] ;
integer      = [ "-" ] , digits ;
digits       = digit , { digit } ;
quoted       = "'" , { character - "'" | "\'" } , "'" | '"' , { character - '"' | '\"' } , '"' ;
name         = ( letter | "_" ) , { letter | digit | "_" } ;  (* not a keyword *)
```

Keywords (`and`, `or`, `not`, `in`, `true`, `false`, `null`) are reserved and case-sensitive.
Whitespace separates tokens and is otherwise ignored. A function name followed by `(` is a call;
a slot cannot be named like a function. `state.` may prefix a reference (`state.draft`), and is
dropped.

### 8.2 Precedence and evaluation order

From loosest to tightest binding: `or`, `and`, `not`, comparison, operand. `and` and `or`
short-circuit left to right, so `exists(plan) and len(plan) > 0` never evaluates `len` on a
missing plan. Parentheses group.

### 8.3 Types

Values are JSON: `null`, boolean, number (all numbers are 64-bit floating point; `1 == 1.0`),
string, list, object. There is no truthiness: the whole expression of a `when` must evaluate to a
boolean (a non-boolean result is a type error), and `and`, `or`, `not` take booleans only.
Booleans are not numbers (`true == 1` is `false`, `true < 1` is a type error).

| Operator | Operands | Result |
|---|---|---|
| `==`, `!=` | any | Deep equality (lists by order, objects by keys and values; numbers numerically). Never a type error. |
| `<`, `<=`, `>`, `>=` | number and number, or string and string | Numeric, or by Unicode code point. Any other pair (including `null`) is a type error. |
| `in`, `not in` | *x* `in` list | Some element deep-equals *x*. |
| | string `in` string | Substring (case-sensitive; use `lower()`). |
| | string `in` object | Key membership. |
| | anything else | Type error. |

### 8.4 References

A reference names a slot and walks into it: `results[-1].ok`, `choice.confidence`,
`settings.escalate_below`, `input.region`, `groups['ticker']`. Its root must be a built-in slot
(section 5.1), a declared custom slot, `settings` or `input` (P041). Walking a key that is
absent, an index out of range, or into a non-container yields `null`: a reference is never an
error. Negative indexes count from the end. A reference returns one value.

### 8.5 JSONPath

An operand starting with `$` is a JSONPath over the whole state, in exactly the subset that the
tool-quality assertions use (`sajha/quality/jsonpath.py`): `$` the root, `.name` and
`['name']`, `[n]` and negative `[-1]`, `[*]` and `.*` (every child), `..name` (recursive
descent) and `..*`. Filters (`[?()]`), slices (`[1:3]`) and script expressions are not supported
(P040). **A JSONPath always evaluates to the list of every match**, in document order (empty when
nothing matches):

| Expression | Means |
|---|---|
| `'parts_answered' in $.findings[*].check` | some finding is from `parts_answered` |
| `len($.results[*].ok) > 0` | at least one result |
| `false in $.results[*].ok` | some call failed |
| `len($..citations) > 0` | some `citations` key exists anywhere in state |

Use a reference (no `$`) for one value and a JSONPath for many.

### 8.6 Functions

| Function | Arguments | Returns | Notes |
|---|---|---|---|
| `len(x)` | string, list, object or null | number | Characters, elements or keys; `len(null)` is 0. Other types: type error. |
| `exists(x)` | any | boolean | `x` is not `null`; for a JSONPath list, the list is not empty. |
| `empty(x)` | any | boolean | `x` is `null`, `""`, `[]` or `{}`. |
| `lower(s)` | string | string | Unicode lower case. |
| `number(x)` | number or string | number | Parses a string (`"1,234.5"` gives 1234.5; thousands separators removed); unparseable is a type error. |
| `matches(s, pattern)` | string, string literal | boolean | Regular-expression search. `pattern` must be a literal (compiled at load, ≤ 1,000 characters); `s` is clipped to `max_input_chars`. |
| `visits(stage)` | string literal | number | How many times that stage has run in this run or sub-run. Unknown stage id: P041. |
| `offered(tool)` | string | boolean | The tool is in `shortlist`. |

There are no user-defined functions and no arithmetic; compute a derived value with `set` on an
earlier stage when a comparison needs one.

### 8.7 Static checks at load

The parser rejects syntax errors (P040, with the character position), unknown roots and
functions and wrong argument counts (P041), and literal-only type errors such as
`len(3)` or `'a' < 1` (P042). Expressions are at most 1,000 characters and 64 nodes deep.

### 8.8 Evaluation errors

A type error at run time (comparing a string with a number, `len` of a number, a non-boolean
result) makes that `when` false, emits an `expression_error` event with the stage, the
expression and the message, and increments `sajha_planner_expression_errors_total{planner}`.
The run continues by the rules of section 7.2. For `set`, the assignment is skipped. For the
`expression` verify check, the check fails with the message. A guard whose expression errors is
false: the stage is skipped and `else` is taken.

---

## 9. Verify checks

Each check reads the draft and the state and adds findings `{check, message, value}` when it
fails. A check is written as its name (defaults) or an object with settings:

```yaml
checks:
  - numbers_in_results
  - { check: numbers_in_results, tolerance: 0.01, ignore: [question, years] }
  - { check: schema_valid, schema: output }
```

### 9.1 `numbers_in_results`

Every number in the draft appears in some tool result.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `tolerance` | number ≥ 0 | 0.005 | Relative tolerance. |
| `ignore` | `list<string>` | `[question, years, ordinals, small_integers]` | Numbers not checked: those that occur in the question; integers 1900 to 2100; list numbering (`1.`, `2)` at a line start); integers 0 to 10. |
| `max_numbers` | integer | 200 | Numbers checked per draft; later ones are not checked. |

**Extraction.** Numbers are matched by `-?\d{1,3}(,\d{3})+(\.\d+)?|-?\d+(\.\d+)?` followed by
an optional `%` or scale word (`k`, `thousand`, `m`, `mn`, `million`, `bn`, `billion`, `tn`,
`trillion`, case-insensitive). Thousands separators are removed; a scale word multiplies the
value. From results, every number in the full structured result (JSON numbers, and numbers found
by the same pattern in its strings) is collected, streamed from the spool when spilled.

**Match.** A draft number *d* matches a result number *r* when any holds:
`|d − r| ≤ tolerance × max(|d|, |r|)`; *r* rounded to *d*'s decimal places equals *d*; for a
percentage, *d* / 100 matches *r* by either rule; with a scale word, the unscaled mantissa
matches *r* (so "1.2 billion" matches 1200000000 and 1.2).

**Finding:** one per unmatched number: `{check: numbers_in_results, message: "12.7 does not
appear in any tool result", value: 12.7}`. With no results, every non-ignored number fails.

### 9.2 `citations_present`

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `per` | string | `answer` | `answer` or `paragraph`. |

- `answer`: when `results` holds at least one successful result, `citations` is not empty, and
  every citation is the id of a successful result.
- `paragraph`: in addition, every paragraph of the draft (blocks separated by a blank line) that
  contains a digit carries an inline marker `[<call id>]` naming a successful result.

### 9.3 `parts_answered`

The question's parts are each addressed by the draft. Deterministic and approximate by design.

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `min_overlap` | number 0 to 1 | 0.5 | Share of a part's content words the draft must contain. |

**Parts** are: each sentence of `question` that ends in `?`; each item of an enumeration
(lines starting `1.`, `1)`, `a)`, `-`, `*`). If that yields fewer than two parts, the check
passes. A part's **content words** are its lower-cased words of three or more letters, minus a
fixed English stop-word list, with a trailing `s` removed. A part is answered when at least
`min_overlap` of its content words occur in the lower-cased draft. Finding per unanswered part:
`{message: "no answer to: <part>", value: <part>}`.

### 9.4 `schema_valid`

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `schema` | JSON Schema or `output` | `output` | `output`: the tool's `outputSchema`. |
| `from` | ref | `draft_json` | The value to validate; a string is parsed as JSON first. |

Validates with JSON Schema 2020-12; each error is a finding with its instance path.

### 9.5 Further checks

| Check | Settings | Passes when |
|---|---|---|
| `results_present` | `min` (integer, default 1) | At least `min` successful results. |
| `no_failed_citations` | none | No citation names a failed, refused or skipped call. |
| `length` | `min_chars`, `max_chars` | The draft's length is within bounds. |
| `contains` | `patterns` (list of regex) | Every pattern matches the draft. |
| `not_contains` | `patterns` (list of regex) | No pattern matches the draft (for example `as an AI`). |
| `expression` | `expr`, `message` | The expression (section 8) is true; otherwise one finding with `message`. |

Custom checks can be registered in code with a name, a settings schema and a pure function of
(draft, state) to findings; planner files then use them like the built-in ones.

---

## 10. How a planner runs

### 10.1 The loop

```text
run(planner, call):
  state  <- built-in slots (input, question after implicit condense, history, shortlist, ...)
  stage  <- planner.start
  loop:
    if a run-wide limit is reached (steps, tool calls, tokens, cost, time, stages, memory guard):
        finish(stopped_by = that limit)                    # 10.3
    emit stage_start {stage, type, visit}
    if stage.when is set and evaluates false:
        transition <- stage.else
    else:
        outcome <- stage.run(state)                        # may ask the service to call tools or models
        if the service stopped the run (needs_confirmation, needs_connection, needs_input, cancelled,
           budget, refused, error):
            finish(stopped_by = that reason)
        emit stage_end {stage, outcome, ms}
        if stage is terminal: finish(answer | failed)      # in a sub-run: return to the parent
        transition <- choose(stage.outcomes, outcome)      # 7.2
    apply bound, set, then stage <- transition target       # 7.3, 7.6
    recompute state.confidence
```

### 10.2 What the service does around the loop

Unchanged from today and outside the planner's reach: building the shortlist from the caller's
access, loading conversation memory, the safety preamble, running every call through the
normal tool path as the caller, confirmation, policy, result caps and spill, limits and budgets,
synthesis, confidence, citations, memory recording, audit and the event stream. A planner file
only chooses the order of stages and the transitions between them.

### 10.3 Finishing and `stopped_by`

When the run ends for any reason other than `answer`/`fail`, the service finishes with the best
answer so far, as today: if `draft_source` is `draft`, `revise`, `vote` or `template`, the draft
is the answer; otherwise synthesis runs over the transcript when there are results (and
`ai.ask.synthesize` is on); without synthesis the answer is the draft, or, if that is empty, the
successful results' summaries joined (today's `plan_execute` fallback text).

`stopped_by` takes only the values listed in [LLM Tools](LLM%20Tools.md) section 15, which owns
the list, their `isError` and which are new; today's names (`STOP_REASONS` in
`sajha/ai/intelligence.py`) are kept. A planner run sets them as follows:

| `stopped_by` | Set when |
|---|---|
| `answer` | An `answer` stage ended the run (section 6.17) |
| `failed` (new) | A `fail` stage ended the run (section 6.18) |
| `needs_confirmation`, `needs_connection` | As today (destructive or approval-gated call; account not linked) |
| `needs_input` (new) | `ask_user` cannot ask in-band (section 6.15) |
| `step_limit`, `tool_limit`, `timeout` | As today: `max_steps`, `max_tool_calls` or `timeout_s` reached (section 11) |
| `stage_limit` (new), `cost_limit` (new) | `max_stages_run` or `max_cost_usd` reached (section 11) |
| `budget` | As today: the run's token cap (`ai.ask.max_tokens` on the Ask page) or the caller's token budget |
| `refused` (new) | A model call was refused or filtered and the stage has no fallback for it (section 6.0) |
| `memory_pressure` (new), `busy` (new) | The memory guard (LLM Tools 10.4) |
| `cancelled` (new) | The client cancelled |
| `error` | As today: a model error that is not a schema mismatch, or a stage failed unexpectedly (code `planner_error`, as today), or no transition applied (code `no_transition`, section 7.2) |

A sub-run's own end is not a `stopped_by` of the run: it is the `planner` stage's outcome
(`answered`, `failed` or `stopped`), and `subrun.stopped_by` names the sub-budget limit for
`stopped` with the same names (`step_limit`, `tool_limit`, `timeout`, `stage_limit`,
`cost_limit`).

### 10.4 Events, audit and metrics

- **Events** on the ask event stream, in addition to today's (`shortlist`, `model`, `plan`,
  `tool_call`, `tool_result`, `answer`, `confidence`, ...): `stage_start {stage, type, visit,
  planner}`, `stage_end {stage, outcome, ms, planner}`, `loop_exhausted {stage, edge, to}`,
  `expression_error {stage, expression, message}`, `planner_chosen {planner, version, by,
  reason}` (by `version route`, `caller choice`, `tool config`, `server default`, `rule`,
  `label <confidence>`, `default`, `escalation`).
- **Audit:** the LLM-tool call's record carries `planner` (`name@version`), `planner_chain`
  (`auto>react`), `planner_path` (the stage ids taken, at most 200, with `…` when longer),
  `loops_exhausted` (edge ids) and `stopped_by`.
- **Metrics** (LLM Tools 9.11): `sajha_planner_stages_total{planner,stage,outcome}`,
  `sajha_planner_loops_exhausted_total{planner,edge}`,
  `sajha_planner_run_seconds{planner}`, `sajha_planner_expression_errors_total{planner}`,
  `sajha_planner_load_errors_total{planner}`, `sajha_planner_chosen_total{tool,planner,by}`.

---

## 11. Limits and ceilings

Server ceilings are `ai.planners.limits.*` (LLM Tools 19) for graph shape and
`ai.llm_tools.limits.*` for spending. A file or a stage may ask for less, never more; a larger
value is clamped with a warning (P060).

| Ceiling | Default | What it caps | Where it bites |
|---|---|---|---|
| `ai.planners.limits.max_stages_run` | 40 | `limits.max_stages_run` | Run-wide stage executions, sub-runs included; `stopped_by: stage_limit`. |
| `ai.planners.limits.max_visits_per_edge` | 10 | Every integer `max_visits` | At load (clamp). |
| `ai.planners.limits.max_subplanner_depth` | 2 | Nesting of `planner` stages, `sample` of `planner`, `foreach` (`do` or `planner`) | At load (P035). Depth 0 is the top planner. |
| `ai.planners.limits.max_parallel` | 4 | `execute.max_parallel`, `sample.concurrency`, `foreach.concurrency` | At load (clamp). |
| `ai.planners.limits.max_samples` | 5 | `sample.n` | At load (clamp). |
| `ai.planners.limits.max_foreach_items` | 50 | `foreach.max_items` | At load (clamp) and at run time (items beyond are dropped; outcome `partial`). |
| `ai.llm_tools.limits.max_steps` | 8 | `limits.max_steps`, sub-run `limits.max_steps` | Run-wide; `stopped_by: step_limit`. |
| `ai.llm_tools.limits.max_tool_calls` | 16 | `limits.max_tool_calls` | Run-wide. |
| `ai.llm_tools.limits.timeout_s` | 120 | `limits.timeout_s`, stage `timeout_s` | Run-wide. |
| `ai.llm_tools.limits.max_cost_usd` | 1.00 | `limits.max_cost_usd` | Run-wide; estimated from model prices. |
| `ai.llm_tools.limits.max_output_tokens` | 4000 | Stage `max_output_tokens` | Per model call. |

Fixed limits, not configurable: 100 stages per file; 32 custom slots; 200 rules per `match`;
50 labels per `classify`; 20 rubric items; 20 checks per `verify`; 10 alternatives per outcome;
1,000 characters per expression or regular expression; 3 `ask_user` visits per run; 32 plan
steps per `plan` reply.

On the Ask SAJHA page, which is not a tool, `ai.ask.max_steps`, `ai.ask.max_tool_calls`,
`ai.ask.timeout_s` and `ai.ask.max_tokens` play the part of the tool's limits, as today.

---

## 12. Validation rules and messages

A planner file is validated when it loads, when a tool referencing it loads, and by
`python -m sajha.quality lint`. Every message has the form
`planner <name>@<version>: <location>: <message>`, where `<location>` is a key path such as
`stages.verify.outcomes.mismatch[0].next`. Errors refuse the file (the last good version stays in
use, section 2.1); warnings load it.

| Code | Level | Rule | Message |
|---|---|---|---|
| P001 | error | The document is a mapping | `not a planner file (expected a mapping, got <type>)` |
| P002 | error | `name` is an identifier and agrees with the file name | `name "<n>" does not match the file name "<file>"` |
| P003 | error | `version` is SemVer | `version "<v>" is not MAJOR.MINOR.PATCH` |
| P004 | error | No unknown top-level key | `unknown key "<k>" (allowed: name, version, ...)` |
| P005 | error | `name@version` is unique | `<name>@<version> is also defined in <file>` |
| P006 | error | Every key in a planner file, and every rule name and label, loaded as a string (section 2.1) | `stage "<s>": <location> loaded as <type> <value>; quote it` / `stage "<s>": key true is not allowed (a bare on: loads as true; transitions go under "outcomes")` |
| P010 | error | Stage type exists | `stage "<s>": unknown type "<t>"` |
| P011 | error | Stage settings match the type's schema | `stage "<s>": <JSON Schema error at path>` |
| P012 | error | `start` names a stage | `start "<s>" is not a stage` |
| P013 | error | Every stage is reachable from `start` | `stage "<s>" is unreachable from "<start>"` |
| P014 | error | Every outcome a stage can produce has a transition (or `*`) | `stage "<s>": outcome "<o>" has no transition (add it or "*")` |
| P015 | error | Every `next`, `else` and `on_exhausted` names a stage | `stage "<s>": "<target>" is not a stage` |
| P016 | warning / error | An `outcomes` key the stage cannot produce (error); alternatives all conditional with no `*` (warning) | `stage "<s>": "<o>" is not an outcome of <type> (outcomes: ...)` / `stage "<s>": outcome "<o>" may find no transition` |
| P017 | error | Terminal stages have no `outcomes`/`next`; `next` and `outcomes` are not both given | `stage "<s>": <type> is terminal and takes no transitions` / `stage "<s>": give "next" or "outcomes", not both` |
| P020 | error | Every cycle has a bounded edge | `unbounded cycle: <a> -> <b> -> <a> (add max_visits to an edge of it)` |
| P021 | error | An integer `max_visits` has `on_exhausted` | `stage "<s>": bounded edge "<o>" has no on_exhausted` |
| P022 | error | `max_visits: steps` only where every traversal spends a step | `stage "<s>": max_visits "steps" is allowed only on act.called and execute outcomes` |
| P023 | warning | `max_visits` above `max_visits_per_edge` | `stage "<s>": max_visits <n> clamped to <ceiling>` |
| P030 | error | Model roles are declared | `stage "<s>": model role "<r>" is not in models` |
| P031 | error | Aliases and `provider/model` exist | `models.<r>: "<alias>" is not a gateway alias or a known model` |
| P032 | error | Prompts exist | `stage "<s>": prompt "<p>" is not in prompts or the prompts registry` |
| P033 | error | Sub-planners exist (at the version given) | `stage "<s>": planner "<ref>" not found` |
| P034 | error | No planner includes itself | `planner cycle: <a> -> <b> -> <a>` |
| P035 | error | Nesting within `max_subplanner_depth` | `stage "<s>": sub-planner depth <d> exceeds <max> (<a> > <b> > <c>)` |
| P036 | error | Tool names and patterns match a tool the tool's `tools.allow` permits | `stage "<s>": tool "<t>" matches no allowed tool` |
| P037 | error | A runtime-templated `planner` has `choices` | `stage "<s>": planner "<template>" needs choices` |
| P040 | error | Expression syntax, JSONPath subset | `stage "<s>": when: <message> at column <c>` |
| P041 | error | Expression names: roots, functions, arity, `visits` stage ids | `stage "<s>": when: unknown name "<n>"` |
| P042 | error | Static type errors in expressions | `stage "<s>": when: <op> cannot compare <type> and <type>` |
| P043 | error | Template references name slots | `stage "<s>": template references unknown slot "<n>"` |
| P044 | error | Settings references resolve | `stage "<s>": {{settings.<path>}} matches nothing` |
| P045 | error | Regular expressions compile and are ≤ 1,000 characters | `stage "<s>": rule "<r>": pattern does not compile: <error>` |
| P046 | warning | Nested quantifiers in a pattern | `stage "<s>": rule "<r>": pattern may backtrack catastrophically` |
| P050 | error | Custom slot names are identifiers, not built-in, ≤ 32 slots | `state.<n>: "<n>" is a built-in slot` |
| P051 | error | `into` names a custom slot (or the stage's allowed built-in) of a compatible type | `stage "<s>": into "<slot>" is not a declared slot of type <type>` |
| P052 | error | `set` and `into` never write read-only or built-in slots (except the stage's own) | `stage "<s>": cannot write read-only slot "<slot>"` |
| P060 | warning | A limit above its ceiling | `limits.<k> <v> clamped to <ceiling>` |
| P061 | error | `kind: python`: class importable, a `Planner` subclass, settings valid for its `config_model` | `class "<c>": <error>` |
| P062 | error | `match` with rules from settings, `classify` with `from`, need `*` | `stage "<s>": outcomes are not known at load; add a "*" transition` |
| P063 | error | A terminal stage is reachable from every stage | `stage "<s>": no answer or fail stage is reachable from here` |
| P070 | warning | Content changed without a version change | `content changed but version is still <v>` |
| P071 | warning | Unpinned sub-planner references | `stage "<s>": planner "<n>" is not pinned (resolves to <n>@<v>)` |

A tool that references a planner which fails validation does not load (LLM Tools 9.12).

---

## 13. Shipped planners

SAJHA ships these files in `config/planners/<name>.yaml`. They are the strategies of LLM Tools
9.4, and they double as examples. The first four re-express today's Python planners; section
13.13 lists every place where the file form differs from today's behaviour.

### 13.1 `react`

```yaml
# config/planners/react.yaml
name: react
version: 1.0.0
description: One model call per step; the model answers or calls offered tools, and the results feed the next step.
use_when: General questions that need one or a few tool calls; the default.
start: act
stages:
  act:
    type: act                                   # today's ReactPlanner.next_action
    outcomes:
      called:   { next: act, max_visits: steps }   # bounded by max_steps, exactly as today
      answered: { next: answer }
  answer:
    type: answer                                # synthesize: auto -> synthesised when tools were called
```

Model calls: one per step, plus synthesis when tools were called. Same as today.

### 13.2 `plan_execute`

```yaml
# config/planners/plan_execute.yaml
name: plan_execute
version: 1.0.0
description: One structured-output call plans the tool steps with dependencies; independent steps run together; one re-plan after a failure.
use_when: Questions with several parts or several independent lookups that can run in parallel.
settings:                          # today's PlanExecuteConfig: same keys, same defaults
  max_replans: 1
  max_parallel: 4
  max_plan_steps: 8
  fallback: react
  model: null                      # null: the tool's (or the ask's) model
models:
  planner: "{{settings.model}}"
start: plan
stages:
  plan:
    type: plan
    model: planner
    when: "len(shortlist) > 0"     # today: no tools offered -> hand the ask to the fallback
    else: { next: fallback }
    max_plan_steps: "{{settings.max_plan_steps}}"
    retry: 0                       # today's planner does not re-ask on an invalid plan
    outcomes:
      planned: { next: execute }
      invalid:
        - { next: fallback, when: "len(plan) == 0" }   # first plan unusable -> fallback
        - { next: answer }                              # a re-plan added nothing -> answer
  execute:
    type: execute
    max_parallel: "{{settings.max_parallel}}"
    outcomes:
      done:         { next: answer }
      failed_steps: { next: plan, max_visits: "{{settings.max_replans}}", on_exhausted: answer }
  fallback:
    type: planner
    planner: "{{settings.fallback}}"
    next: answer
  answer:
    type: answer                   # synthesised over the results, as today
```

### 13.3 `rewoo`

ReWOO plans once without seeing any observation, runs the plan, and has a solver write the
answer: one planning call and one solver call, whatever the results say.

```yaml
# config/planners/rewoo.yaml
name: rewoo
version: 1.0.0
description: Plans every tool call up front from the question alone, runs the plan, then writes the answer in one call.
use_when: Questions whose lookups are clear from the wording, where a predictable number of model calls matters.
models: { planner: reasoning, solver: null }
settings: { max_parallel: 4, max_plan_steps: 8 }
start: plan
stages:
  plan:
    type: plan
    model: planner
    context: question              # no observations: the planner sees only the question and the tools
    when: "len(shortlist) > 0"
    else: { next: fallback }
    max_plan_steps: "{{settings.max_plan_steps}}"
    outcomes:
      planned: { next: execute }
      invalid: { next: fallback }
  execute:
    type: execute
    max_parallel: "{{settings.max_parallel}}"
    next: solve                    # failed steps are reported as caveats, not re-planned
  solve:
    type: draft
    model: solver
    next: answer
  fallback:
    type: planner
    planner: react
    next: answer
  answer:
    type: answer
```

### 13.4 `reflect`

```yaml
# config/planners/reflect.yaml
name: reflect
version: 1.0.0
description: Gathers data with ReAct, drafts an answer, then a critic reviews the draft and it is revised until it passes or the bound is reached.
use_when: High-stakes answers where quality matters more than latency.
models: { act: reasoning, critic: fast }
start: act
stages:
  act:
    type: act
    model: act
    outcomes:
      called:   { next: act, max_visits: 6, on_exhausted: draft }
      answered: { next: draft }
  draft:
    type: draft
    model: act
    next: critique
  critique:
    type: critique
    model: critic
    rubric:
      - answers every part of the question
      - no claim without a tool result
      - says what is missing
    outcomes:
      pass:   { next: answer }
      revise: { next: revise, max_visits: 2, on_exhausted: answer }
  revise:
    type: revise
    model: act
    next: critique
  answer:
    type: answer                   # the draft is final: no second synthesis
```

### 13.5 `verify_then_answer`

```yaml
# config/planners/verify_then_answer.yaml
name: verify_then_answer
version: 1.0.0
description: Gathers data with ReAct, drafts an answer, checks every figure and citation against the tool results, and revises on a mismatch.
use_when: Numeric answers where every figure must match the data.
start: act
stages:
  act:
    type: act
    outcomes:
      called:   { next: act, max_visits: 6, on_exhausted: draft }
      answered: { next: draft }
  draft:
    type: draft
    next: verify
  verify:
    type: verify
    checks: [numbers_in_results, citations_present, no_failed_citations]
    outcomes:
      ok:       { next: answer }
      mismatch: { next: revise, max_visits: 2, on_exhausted: answer }
  revise:
    type: revise
    address: findings
    next: verify
  answer:
    type: answer                   # unresolved findings become caveats
```

### 13.6 `self_consistency`

```yaml
# config/planners/self_consistency.yaml
name: self_consistency
version: 1.0.0
description: Gathers data once, drafts several answers at different temperatures, and keeps the one most drafts agree on.
use_when: Ambiguous or reasoning-heavy questions where agreement between independent drafts signals the right answer.
models: { judge: fast }
settings: { samples: 5 }
start: act
stages:
  act:
    type: act
    outcomes:
      called:   { next: act, max_visits: 6, on_exhausted: drafts }
      answered: { next: drafts }
  drafts:
    type: sample
    n: "{{settings.samples}}"
    temperature: { from: 0.3, to: 1.0 }
    of: { type: draft }            # or { type: planner, planner: react } to sample whole runs
    next: pick
  pick:
    type: vote
    method: majority
    normalise: numbers             # use "text" for questions without figures
    tie_break: judge
    model: judge
    outcomes:
      done: { next: answer }
      tie:  { next: answer }       # no successful draft: the act answer is synthesised
  answer:
    type: answer
```

### 13.7 `branch_and_judge`

```yaml
# config/planners/branch_and_judge.yaml
name: branch_and_judge
version: 1.0.0
description: Drafts several plans, has a judge pick the best before any tool runs, then executes it and writes the answer.
use_when: Questions with several plausible approaches, where choosing well before spending on tools matters.
models: { planner: reasoning, judge: reasoning }
settings: { branches: 3 }
start: branch
stages:
  branch:
    type: sample
    when: "len(shortlist) > 0"
    else: { next: fallback }
    n: "{{settings.branches}}"
    of: { type: plan, model: planner }
    next: judge
  judge:
    type: vote
    method: judge
    model: judge
    rubric:
      - uses the fewest tool calls that fully answer the question
      - covers every part of the question
      - calls only tools whose descriptions fit the step
    outcomes:
      done: { next: execute }      # the winning plan is now "plan"; a plan event is emitted
      tie:  { next: fallback }
  execute:
    type: execute
    next: draft
  draft:
    type: draft
    next: answer
  fallback:
    type: planner
    planner: react
    next: answer
  answer:
    type: answer
```

### 13.8 `map_reduce`

```yaml
# config/planners/map_reduce.yaml
name: map_reduce
version: 1.0.0
description: Finds the list of items a question is about, answers for each item with its own ReAct run, then writes one answer from the per-item answers.
use_when: Per-item analysis over a list the tools can produce, such as each holding, each filing or each region.
models: { reduce: reasoning }
settings: { max_items: 20, concurrency: 2 }
state:
  listed: { type: object, default: { items: [] } }
start: gather
stages:
  gather:
    type: act
    prompt: { text: "First find the list of items the question is about, using the tools offered. Reply with the list when you have it." }
    outcomes:
      called:   { next: gather, max_visits: 3, on_exhausted: list }
      answered: { next: list }
  list:
    type: draft
    prompt: { text: "Return the items the question should be answered for. Use only items that appear in the tool results." }
    schema:
      type: object
      properties: { items: { type: array, items: { type: string }, maxItems: 50 } }
      required: [items]
      additionalProperties: false
    into: listed
    outcomes:
      done:    { next: each, when: "len(listed.items) > 0" }
      "*":     { next: direct }    # no list (invalid reply, or empty): answer directly
  each:
    type: foreach
    items: listed.items
    planner: react
    question: "{{original_question}} Answer only for: {{item}}"
    max_items: "{{settings.max_items}}"
    concurrency: "{{settings.concurrency}}"
    outcomes:
      done:    { next: reduce }
      partial: { next: reduce }
  reduce:
    type: draft
    model: reduce
    prompt: { text: "Combine the per-item answers above into one answer. Keep each item's figures as given and say which items are missing." }
    next: answer
  direct:
    type: draft
    next: answer
  answer:
    type: answer
```

### 13.9 `router`

```yaml
# config/planners/router.yaml
name: router
version: 1.0.0
description: Chooses a strategy per question - configured rules, then recipes, then plan_execute for questions with several parts, otherwise react.
use_when: Mixed traffic where cheap deterministic rules can route most questions.
settings:                          # today's RouterConfig: same keys, same defaults
  rules: []                        # [{match: <regex>, planner: <name>}], checked first, in order
  use_recipes: true
  multi_step: plan_execute
  default: react
  multi_step_pattern: '\b(and then|then|after that|compare|comparison|versus|vs\.?|both|each of|as well as|respectively)\b|\?.+\?'
start: rules
stages:
  rules:
    type: match
    rules: "{{settings.rules}}"
    outcomes:
      none: { next: recipes_check }
      "*":  { next: routed }
  routed:
    type: planner
    planner: "{{rule.planner}}"
    choices: "{{settings.rules[*].planner}}"
    next: answer
  recipes_check:
    type: match
    when: "settings.use_recipes"
    else: { next: shape }
    rules_from: recipes.match      # the recipes planner's rules: a recipe whose tool is offered
    outcomes:
      none: { next: shape }
      "*":  { next: to_recipes }
  to_recipes:
    type: planner
    planner: recipes
    next: answer
  shape:
    type: match
    dotall: true
    rules:
      - { name: multi_step, pattern: "{{settings.multi_step_pattern}}" }
    outcomes:
      multi_step: { next: multi }
      none:       { next: simple }
  multi:
    type: planner
    planner: "{{settings.multi_step}}"
    next: answer
  simple:
    type: planner
    planner: "{{settings.default}}"
    next: answer
  answer:
    type: answer
```

### 13.10 `recipes`

```yaml
# config/planners/recipes.yaml
name: recipes
version: 1.0.0
description: Deterministic regex or keyword recipes answer known question shapes with one tool call and no model; anything else goes to the fallback planner.
use_when: Known, frequent questions that map to one tool call.
settings:                          # today's RecipesConfig: same keys, same defaults
  recipes: []                      # [{name, tool, match, keywords, arguments, answer}]
  fallback: react
start: match
stages:
  match:
    type: match
    rules: "{{settings.recipes}}"  # a recipe matches only if its tool is offered (rule.tool)
    outcomes:
      none: { next: fallback }
      "*":  { next: call }
  call:
    type: call
    from_rule: true                # tool, arguments, {group} filling and coercion as today
    emit_plan: true
    next: finish
  finish:
    type: answer
    template_from: rule            # the recipe's answer template, when the call succeeded
  fallback:
    type: planner
    planner: "{{settings.fallback}}"
    next: done
  done:
    type: answer
```

A recipe in `settings.recipes` (or `ai.ask.planner_config.recipes.recipes`) keeps today's shape:

```yaml
- name: fx_rate
  tool: calc_currency_converter
  match: '(?P<amount>[\d,.]+)\s*(?P<from>[A-Z]{3})\s+(?:to|in)\s+(?P<to>[A-Z]{3})'
  answer: "{amount} {from} is {converted} {to}."   # {converted} is a field of the tool's result
```

### 13.11 `human_in_the_loop`

```yaml
# config/planners/human_in_the_loop.yaml
name: human_in_the_loop
version: 1.0.0
description: Asks the caller to clarify an ambiguous question, and to approve a large plan before running it.
use_when: Questions that may need the caller's choice, or where many tool calls should be approved first.
models: { chooser: fast }
settings: { confirm_above_steps: 4 }
state:
  plan_size: { type: integer, default: 0 }
start: clarity
stages:
  clarity:
    type: classify
    model: chooser
    labels: [clear, ambiguous]
    default: clear
    min_confidence: 0.7
    prompt: { text: "Label the question ambiguous only if it cannot be answered without a choice the user must make (which entity, which period, which measure); otherwise clear." }
    outcomes:
      clear:     { next: plan }
      ambiguous: { next: clarify }
  clarify:
    type: ask_user
    kind: text
    message: "Your question could mean several things. Which entity, period or measure should I use?"
    outcomes:
      answered: { next: plan }     # the reply is appended to the question
      declined: { next: plan }
  plan:
    type: plan
    when: "len(shortlist) > 0"
    else: { next: fallback }
    set: { plan_size: "len(plan)" }
    outcomes:
      planned: { next: run_small }
      invalid: { next: fallback }
  run_small:
    type: execute
    when: "plan_size <= settings.confirm_above_steps"
    else: { next: approve }
    next: draft
  approve:
    type: ask_user
    kind: confirm
    message: "Answering needs {{plan_size}} tool calls. Run them?"
    outcomes:
      answered:
        - { next: run, when: "user_reply == true" }
        - { next: stopped }
      declined: { next: stopped }
  run:
    type: execute
    next: draft
  draft:
    type: draft
    next: answer
  fallback:
    type: planner
    planner: react
    next: answer
  stopped:
    type: answer
    template: "Stopped before running {{plan_size}} tool calls, as you asked."
    synthesize: never
  answer:
    type: answer
```

### 13.12 `auto`

The full form of the abridged file in LLM Tools 9.13: deterministic rules first, then a cheap
classifier over the allowed planners, a cheap first try, checks, and one escalation per kind.

```yaml
# config/planners/auto.yaml
name: auto
version: 1.0.0
description: Picks a strategy per question (known patterns first, then a cheap classifier over the allowed planners), checks the answer, and escalates once only when a check fails.
use_when: Mixed traffic; pick a strategy per question and upgrade only when checks fail.
models: { chooser: fast, act: fast, strong: reasoning }
settings:
  candidates: [react, plan_execute, reflect, map_reduce]
  default: react
  min_label_confidence: 0.5
  escalate_below: 0.6
  first_try: { max_steps: 4 }      # sub-budget of the first attempt
start: known
stages:
  known:
    type: match
    rules_from: recipes.match      # recipes and known patterns: no model call
    outcomes:
      none: { next: choose }
      "*":  { next: recipe }
  recipe:
    type: planner
    planner: recipes
    next: answer                   # deterministic answers are not re-checked
  choose:
    type: classify
    model: chooser
    from: settings.candidates
    menu: planners                 # labels are planner names; the model sees each use_when
    default: "{{settings.default}}"
    min_confidence: "{{settings.min_label_confidence}}"
    outcomes: { "*": { next: run } }
  run:
    type: planner
    planner: "{{chosen}}"
    choices: "{{settings.candidates}}"
    model: act                     # every role of the first try runs on the fast alias
    limits: "{{settings.first_try}}"
    outcomes: { "*": { next: verify } }
  verify:
    type: verify
    checks: [numbers_in_results, parts_answered]
    outcomes:
      ok: { next: gate }
      mismatch:
        - { next: split,   when: "'parts_answered' in $.findings[*].check", max_visits: 1, on_exhausted: answer }
        - { next: reflect, max_visits: 1, on_exhausted: answer }
  gate:
    type: answer
    when: "confidence >= settings.escalate_below and subrun.stopped_by != 'step_limit'"
    else: { next: deeper, max_visits: 1, on_exhausted: answer }
  reflect:
    type: planner
    planner: reflect
    model: strong
    next: answer
  split:
    type: planner
    planner: plan_execute
    model: strong
    next: answer
  deeper:
    type: planner
    planner: plan_execute
    model: strong
    next: answer
  answer:
    type: answer
```

The escalation table of LLM Tools 9.13 maps onto this file: a figure no result contains →
`verify` mismatch → `reflect`; parts not answered → `split` (`plan_execute`); low confidence or
the first try hit its step budget → `deeper` (`plan_execute` on the reasoning alias); otherwise
`gate` answers. The deepest nesting is `auto > recipes > react` and `auto > plan_execute > react`
(depth 2), within the default `max_subplanner_depth`.

### 13.13 Fidelity of the four built-ins

The shipped `react`, `plan_execute`, `recipes` and `router` make the same model calls, the same
tool calls in the same order and the same plan events as today's classes in
`sajha/ai/planners.py`, and their settings keep today's names and defaults. Their tests run
against both forms during the transition (LLM Tools 9.4). The differences, and how each is
handled:

| Planner | Today | File form | Handling |
|---|---|---|---|
| all | `res.planner` is the delegation chain (`router>plan_execute`) | `planner.chain`, same text | None needed. |
| all | `Emit(event)` lets a planner publish any event | Stages publish fixed events only | Python planners keep `Emit`; files get `stage_*` and `plan` events. |
| all | `ai.ask.planner` accepts `package.module:Class`; entry points in `sajha.planners` register classes | Same, as `kind: python` planners in the registry | A name defined both by a file and by a Python registration is P005. |
| all | The alias `model` means `react` | Kept as a registry alias | None needed. |
| `react` | Ends `step_limit` when `max_steps` is reached | `max_visits: steps` ends `step_limit` | Identical (section 16, item 1). |
| `plan_execute` | No retry on an unusable plan | `retry: 0` in the file | Identical. |
| `plan_execute` | When synthesis is off and no step succeeded, the answer is "The plan's tool calls returned no usable result." | The answer is empty | Accepted; synthesis is on by default. |
| `recipes` | A recipe with neither `match` nor `keywords` silently never matches | Refused at load (P011) | Lint finds it before deploy. |
| `router` | A rule naming `router` is silently replaced by `default` | Refused at load (P034, planner cycle) | Lint finds it. |
| `router` | Reads the recipes config on every ask | `rules_from` reads it at load, and again on every reload | The same, since the config only changes on reload. |

Nothing in the four built-ins needs a capability the file form lacks.

---

## 14. Writing your own planner

A worked example: answer "price of MSFT"-style questions with one deterministic call, check the
figures, and let ReAct handle everything else.

**1. Start from the shape.** Decide the stages and outcomes before writing YAML:
`match` (known shape?) → `call` the quote tool → `answer`; anything else → `react`; and verify
the answer when ReAct wrote it.

**2. Write the file** as `config/planners/<name>.yaml`, here `quote_desk.yaml`:

```yaml
name: quote_desk
version: 1.0.0
description: Answers stock-price questions with one quote call; other questions go to ReAct and are checked against the data.
use_when: Desks that mostly ask for a current stock price.
start: shape
stages:
  shape:
    type: match
    rules:
      - name: price
        pattern: '\b(?:price|quote) (?:of|for) (?P<symbol>[A-Z]{1,5})\b'
        tool: av_stock_quote              # matches only if the caller may use this tool
    outcomes:
      price: { next: quote }
      none:  { next: general }
  quote:
    type: call
    tool: av_stock_quote
    arguments: { symbol: "{{groups.symbol}}" }
    outcomes:
      done:  { next: answer }
      error: { next: general }            # the quote failed: let ReAct try
  general:
    type: planner
    planner: react@1.0.0                  # pinned: a new react version will not change this desk
    next: check
  check:
    type: verify
    checks: [numbers_in_results]
    outcomes:
      ok:       { next: answer }
      mismatch: { next: fix, max_visits: 1, on_exhausted: answer }
  fix:
    type: revise
    address: findings
    next: check
  answer:
    type: answer
```

**3. Lint it.** `python -m sajha.quality lint` reports any P-code from section 12 with its
location. Here the `fix -> check -> fix` cycle passes because the `mismatch` edge is bounded.

**4. Dry-run it.** The planner editor's dry run (LLM Tools 9.11) runs the file against the mock
model and prints the stage path, for example `shape → quote → answer` for "price of MSFT" and
`shape → general → check → answer` for "why did MSFT move?".

**5. Use it from a tool.** In `config/tools/<name>.json`, set `"planner": "quote_desk@1.0.0"` in
the `llm` block. To let callers choose between it and `react`, add
`"planner_choices": ["quote_desk", "react"]`.

**6. Change it safely.** Copy the file to `quote_desk@1.0.0.yaml`, edit `quote_desk.yaml`, bump
`version` to `1.1.0`, and route a share of traffic to it with a tool version (LLM Tools 9.12)
before moving the pin. Add eval questions to the tool's eval set (`config/evals/`) so
`python -m sajha.quality eval` compares the two versions.

Tips: put deterministic stages (`match`, `call`, `verify`) before model stages; give every loop
the smallest `max_visits` that works; prefer `revise` targeted at `findings` over a second
`critique`; and keep `use_when` honest, because automatic selection reads it.

---

## 15. Decisions made in this reference

LLM Tools section 9 does not settle these; this reference does. Each can be revisited before
the build.

1. **Files and versions.** The current version is `<name>.yaml`; kept older versions are
   `<name>@<version>.yaml`; a bare name resolves to the highest valid version; pins are exact
   (`name@1.2.0`) or `@latest`, with no ranges (section 2).
2. **Inline planners and overlays.** `llm.planner` may be a full definition or an overlay
   (`use`, `settings`, `models`, `planners`); `ai.ask.planner_config.<name>` is an overlay on the
   Ask page (sections 2.5, 2.6).
3. **Python planners** are registry entries with `kind: python`; a name defined both by a file and
   by a Python registration is an error (section 2.4).
4. **Model roles only.** Stages name roles, never aliases; the `default` role and `null` mean the
   tool's model; a `planner` stage's `model` re-binds every role of its sub-run (sections 3.6,
   6.14).
5. **Prompt assembly order**: safety preamble, tool system prompt, conversation summary, stage
   instruction (section 3.7).
6. **Templates hold references only**, no expressions; whole-value templates keep the type; the
   `state.` prefix is optional (section 4.1).
7. **Settings references** (`{{settings.<jsonpath>}}` as a whole value) are resolved at load,
   after overlays, so files are validated with their real values (section 4.2).
8. **The built-in slot list**, its shapes and bounds (draft ≤ 4 × `max_output_tokens`
   characters; 20 caveats; 50 findings), and a **provisional `confidence`** recomputed after every
   stage with today's composition-framework formula (section 5.1).
9. **Writing state**: stage outputs are fixed; `into` redirects a primary output to a custom slot;
   `set` assigns expressions to custom slots; custom slots are private to their planner
   (sections 5.2, 5.3, 7.6).
10. **Sharing and forking**: `planner` sub-runs share built-in slots; `sample` and `foreach` fork
    and merge results back, deduplicated (section 5.4).
11. **Stage guards**: `when` and `else` on a stage (the shape LLM Tools 9.13's `gate` uses), in
    addition to `when` on transitions; a guarded-out stage counts as a stage run (section 7.7).
12. **Transition selection**: a list of conditional alternatives per outcome, falling through to
    `*`; no applicable transition ends the run with `stopped_by: error`, code `no_transition`
    (section 7.2).
13. **Edge counters** per (stage, outcome, position), per run or sub-run; `max_visits: 0` is
    allowed (section 7.3).
14. **`max_visits: steps`**, a bound by the step limit for `act` and `execute` loops, so `react`
    keeps today's exact behaviour (section 7.3).
15. **The cycle rule made exact** (remove bounded edges; the rest must be acyclic) and a
    terminal stage must be reachable from every stage (sections 7.4, 7.5).
16. **Expression language**: no arithmetic, strict booleans, null-safe references, JSONPath
    always yields a list, a fixed function set (`len`, `exists`, `empty`, `lower`, `number`,
    `matches`, `visits`, `offered`), and run-time type errors make a condition false with an event
    (section 8).
17. **`plan`**: `context: question` gives ReWOO; a visit after a failure appends a re-plan,
    any other visit replaces the plan; `invalid` includes "no usable steps" and "nothing offered"
    (section 6.2).
18. **`execute`** ends `failed_steps` only for failed steps, not skipped ones (today's re-plan
    rule) (section 6.3).
19. **`call`**: call ids, `from_rule` with today's recipe semantics, and `error` without a call
    when the tool is not offered (section 6.4).
20. **`match`** accepts today's `Recipe` and `RouteRule` objects (`match` as an alias of
    `pattern`, extra fields kept on `rule`), `rules_from` to reuse another planner's rules, and a
    `tool` precondition (section 6.5).
21. **`classify`**: the reply schema, `from`, `menu: planners`, eval filtering of the menu, and
    an invalid reply falling back to `default` rather than ending the run (section 6.6).
22. **`draft`** with the default schema *is* today's synthesis; a custom schema turns it into an
    extraction with an extra `invalid` outcome (section 6.7).
23. **A broken critic passes**: an invalid critique reply gives `pass` with a caveat, so it cannot
    loop a run (section 6.8).
24. **The verify catalogue** and exact semantics of each check, including number parsing and the
    deterministic `parts_answered` heuristic, plus `results_present`, `no_failed_citations`,
    `length`, `contains`, `not_contains` and `expression` (section 9).
25. **`sample`** allows `draft`, `plan`, `classify` and `planner` sub-steps (not a single `act`),
    with a linear temperature spread (section 6.11).
26. **`vote`** normalisations and tie-breaking (section 6.12).
27. **`foreach`** outputs, the transcript data message, and `partial` (section 6.13).
28. **Sub-budgets**: a `planner` stage may give its sub-run `limits`; exhausting them ends the
    sub-run with outcome `stopped`, which is how `auto` can escalate when its first try hit its
    step budget (`subrun.stopped_by == 'step_limit'`) while the run still has steps left
    (section 6.14).
29. **`ask_user`** uses MRTR form elicitation on 2026-07-28 and `needs_input` everywhere else;
    replies are appended to the question; at most 3 per run (section 6.15).
30. **Implicit condensing** stays unless a graph contains a `condense` stage, which then also
    recomputes the shortlist (section 6.16).
31. **Synthesis**: `answer.synthesize: auto` synthesises only undrafted answers with results;
    nested `answer` stages never synthesise (section 6.17).
32. **`fail`** ends with `stopped_by: failed` and `isError: true` (section 6.18).
33. **`stopped_by` values** are the one list in LLM Tools section 15: today's names from
    `STOP_REASONS` (`answer`, `step_limit`, `tool_limit`, `budget`, `timeout`,
    `needs_confirmation`, `needs_connection`, `error`) are kept, and planners add `failed`,
    `needs_input`, `stage_limit` and `cost_limit`; a missing transition is `error` with code
    `no_transition` rather than a new value (section 10.3).
34. **Events and metrics** added: `stage_start`, `stage_end`, `loop_exhausted`,
    `expression_error`, `planner_chosen`; `sajha_planner_expression_errors_total`,
    `sajha_planner_load_errors_total`, `sajha_planner_chosen_total` (section 10.4).
35. **Fixed limits** not exposed as configuration (section 11) and the **validation codes**
    P001 to P071 with their messages (section 12).
36. **Shipped names**: the Reflect strategy ships as `reflect` (LLM Tools uses `reflect_analyst`
    as an example name); `auto` handles recipes in its first `match` stage instead of listing
    `recipes` as a candidate, and does not list `router` (it would exceed the default depth).
37. **Plain `yaml.safe_load`, and `outcomes` instead of `on`.** Planner files load with the same
    YAML 1.1 loader as SAJHA's other YAML, so operators can edit them with standard tools; the
    transition map is named `outcomes` because YAML 1.1 reads a bare `on:` key as `true`; outcome
    keys, rule names and labels that YAML 1.1 would load as booleans or numbers must be quoted,
    and are refused otherwise (P006) (section 2.1).
38. **No glossary rows yet.** Like LLM Tools section 3, the new terms (stage, outcome, bounded
    edge, guard, sub-run, overlay) go into `GLOSSARY.md` when the feature is built.

---

## 16. Where the design disagrees with itself or the code

These are the disagreements found while writing this reference, between
[LLM Tools](LLM%20Tools.md) section 9 (which owns the design) and itself or today's code. Each is
now resolved; the resolution is stated here so the history of the decision is not lost.

1. **`stopped_by` names.** LLM Tools section 15 used `answered`, `max_steps`, `max_tool_calls`,
   `max_cost`, `budget_exhausted` and `model_unavailable`, while today's code (`STOP_REASONS` in
   `sajha/ai/intelligence.py`) reports `answer`, `step_limit`, `tool_limit`, `budget`, `timeout`,
   `needs_confirmation`, `needs_connection` and `error`, and the list lacked `needs_connection`.
   **Resolved in LLM Tools.md:** section 15 is now the one list; it keeps every name the code
   reports today, marks the rest new (`failed`, `needs_input`, `stage_limit`, `cost_limit`,
   `no_sources`, `refused`, `invalid_output`, `busy`, `memory_pressure`, `cancelled`), and folds
   `model_unavailable` and `planner_error` into today's `error` with a code. Sections 9.5 and
   15 and this reference (sections 3.4, 6.0, 6.1, 7.2, 7.3, 10.3, 11, 13) use only that list, so no
   rename note is needed when it is built (decision 33).
2. **Template namespaces.** Section 9.3 wrote `{{question.groups.ticker}}` (but `question` is a
   string), 9.6 `{{state.slot}}` and 9.13 `{{state.chosen}}`. **Resolved in LLM Tools.md:**
   9.3 writes `{{groups.ticker}}`, 9.6 `{{slot}}` with `state.` optional, 9.13 `{{chosen}}`,
   as in section 4.1.
3. **Where `when` goes.** Section 9.3 put `when` only on transitions, while the 9.13 `auto`
   example put `when` and `else` on a terminal `answer` stage. **Resolved in LLM Tools.md:** 9.3
   now describes both places, a condition on a transition and a guard (`when` with `else`) on a
   stage, as sections 7.1 and 7.7 do (decision 11).
4. **Escalation on `max_steps` could not fire.** 9.13 escalated when "the run hit `max_steps`",
   but 9.5 rule 3 says global limits end the run whatever the graph says. **Resolved in LLM
   Tools.md:** 9.5 rule 4 introduces sub-budgets, and 9.13 escalates when the first try used up
   its *step sub-budget* (`subrun.stopped_by` is `step_limit`) while the run still has steps
   (decision 28, section 13.12).
5. **The `auto` example was unsafe as written.** Its `run` stage took `planner:
   "{{state.chosen}}"` with no `choices` to validate at load; its candidates named
   `reflect_analyst` (the 9.2 example, not a shipped planner) and `recipes` (which 9.13's text
   says the first `match` stage handles); and `model: strong` on a `planner` stage had no stated
   meaning. **Resolved in LLM Tools.md:** the abridged example now follows section 13.12: a
   `known` `match` stage first, candidates `react`, `plan_execute`, `reflect` and `map_reduce`,
   `choices` on the templated `planner` stage, and a paragraph stating that `model` on a
   `planner` stage re-binds every role of the sub-run (decision 4).
6. **The 9.2 example always revised once.** `act` `answered` went straight to `verify` with
   `citations_present`, but an `act` answer carries no citations, so the first check failed
   whenever tools were called. **Resolved in LLM Tools.md:** `answered` now goes to a `draft`
   stage first, as `reflect` and `verify_then_answer` do, with a sentence saying why.
7. **`sample` of `act`.** 9.4's self-consistency sampled "`act` or `draft`", but one `act` call
   may request tools, which a sample cannot complete in one call. **Resolved in LLM Tools.md:**
   9.3's `sample` row and 9.4's self-consistency row sample `draft` (after an `act` loop gathers
   data) or whole sub-planner runs, and say why a single `act` is not allowed (decision 25).
8. **Map-reduce's list.** 9.4 had `act` "list the items" feed `foreach`, but `act` produces free
   text. **Resolved in LLM Tools.md:** the map-reduce row is now `act` (find the items) →
   `draft` (the list, structured, into a slot) → `foreach` → `draft`, as in section 13.8.
9. **Retry on invalid structured replies.** 9.6 said structured stages retry once, but today's
   `plan_execute` does not. **Resolved in LLM Tools.md:** 9.6 says they retry once *by default*,
   that a stage's `retry` (0 to 2) changes it, and that the shipped `plan_execute` sets
   `retry: 0` to stay faithful to today (section 6.0, section 13.2).
10. **9.8's list of refusals** included "a limit exceeds its ceiling", then said it is clamped
    rather than refused. **Resolved in LLM Tools.md:** the item is out of the refusal list; 9.8
    and 9.5 rule 3 say a limit above its ceiling is clamped with a lint warning (P060).
11. **`on:` under YAML 1.1.** Every YAML example used `on:` as the transition key, which
    `yaml.safe_load` (YAML 1.1 rules, used for SAJHA's other YAML files) loads as the boolean
    `true`, so those files would fail. An earlier draft of this reference required a YAML 1.2
    resolver instead. **Resolved in both documents by renaming the key to `outcomes`**, so plain
    `yaml.safe_load` and standard YAML tools read planner files correctly; outcome names and
    labels that YAML 1.1 reads as booleans or numbers must be quoted and are otherwise refused
    (P006). Every example, the stage keys (section 6.0), the transition rules (section 7), the
    validation messages (section 12) and the JSON Schema (Appendix A) use `outcomes`
    (decision 37; section 2.1). The `next` shorthand and the `on_exhausted` transition key are
    unaffected.
12. **Python classes as stage implementations.** 9.4 said the Python classes "remain as the
    implementation of the `act`, `plan`, `match` and routing stages", but their boundaries do not
    line up (`PlanExecutePlanner` plans, executes and re-plans). **Resolved in LLM Tools.md:**
    9.4 now says the stages reuse the classes' functions (`resolve_references`, `match_recipe`,
    `PLAN_SCHEMA`, `PLAN_PROMPT`), not the classes, and points to section 13.13 for the few
    behaviour differences.

---

## Appendix A: JSON Schema for planner files

The schema below validates a planner file's structure (JSON Schema 2020-12). It covers the
built-in stage types; a custom stage type registered in code adds its own branch. Rules a schema
cannot express (reachability, cycles, roles, references, expression parsing, ceilings) are the
validation rules of section 12.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sajha:planner-file",
  "title": "SAJHA planner file",
  "oneOf": [ { "$ref": "#/$defs/graphPlanner" }, { "$ref": "#/$defs/pythonPlanner" } ],
  "$defs": {
    "identifier": { "type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$" },
    "outcome":    { "type": "string", "pattern": "^([A-Za-z0-9_.@-]{1,64}|\\*)$" },
    "semver":     { "type": "string", "pattern": "^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(-[0-9A-Za-z.-]+)?(\\+[0-9A-Za-z.-]+)?$" },
    "settingsRef": { "type": "string", "pattern": "^\\{\\{\\s*settings([.\\[].*)?\\s*\\}\\}$" },
    "template":   { "type": "string", "maxLength": 8000 },
    "expr":       { "type": "string", "minLength": 1, "maxLength": 1000 },
    "ref":        { "type": "string", "minLength": 1, "maxLength": 300 },
    "plannerRef": { "type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}(@([0-9][0-9A-Za-z.+-]*|latest))?$" },
    "intOrRef":   { "oneOf": [ { "type": "integer", "minimum": 0 }, { "$ref": "#/$defs/settingsRef" } ] },
    "numOrRef":   { "oneOf": [ { "type": "number" }, { "$ref": "#/$defs/settingsRef" } ] },
    "boolOrRef":  { "oneOf": [ { "type": "boolean" }, { "$ref": "#/$defs/settingsRef" } ] },
    "strListOrRef": { "oneOf": [ { "type": "array", "items": { "type": "string" } }, { "$ref": "#/$defs/settingsRef" } ] },

    "prompt": {
      "oneOf": [
        { "type": "object", "required": ["text"], "additionalProperties": false,
          "properties": { "text": { "$ref": "#/$defs/template" } } },
        { "type": "object", "required": ["name"], "additionalProperties": false,
          "properties": { "name": { "type": "string" }, "arguments": { "type": "object" } } }
      ]
    },
    "promptRef": { "oneOf": [ { "$ref": "#/$defs/identifier" }, { "$ref": "#/$defs/prompt" } ] },

    "limits": {
      "type": "object", "additionalProperties": false,
      "properties": {
        "max_stages_run":    { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
        "max_steps":         { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
        "max_tool_calls":    { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
        "timeout_s":         { "oneOf": [ { "type": "number", "exclusiveMinimum": 0 }, { "$ref": "#/$defs/settingsRef" } ] },
        "max_cost_usd":      { "oneOf": [ { "type": "number", "exclusiveMinimum": 0 }, { "$ref": "#/$defs/settingsRef" } ] },
        "max_output_tokens": { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] }
      }
    },

    "slot": {
      "type": "object", "required": ["type"], "additionalProperties": false,
      "properties": {
        "type":        { "enum": ["string", "number", "integer", "boolean", "array", "object", "any"] },
        "items":       { "enum": ["string", "number", "integer", "boolean", "array", "object", "any"] },
        "default":     {},
        "max_chars":   { "type": "integer", "minimum": 1 },
        "max_items":   { "type": "integer", "minimum": 1 },
        "max_kb":      { "type": "integer", "minimum": 1 },
        "description": { "type": "string", "maxLength": 300 }
      }
    },

    "transition": {
      "type": "object", "required": ["next"], "additionalProperties": false,
      "properties": {
        "next":         { "$ref": "#/$defs/identifier" },
        "when":         { "$ref": "#/$defs/expr" },
        "max_visits":   { "oneOf": [ { "type": "integer", "minimum": 0 }, { "const": "steps" }, { "$ref": "#/$defs/settingsRef" } ] },
        "on_exhausted": { "$ref": "#/$defs/identifier" }
      },
      "if":   { "required": ["max_visits"], "properties": { "max_visits": { "not": { "const": "steps" } } } },
      "then": { "required": ["on_exhausted"] }
    },
    "transitions": {
      "oneOf": [
        { "$ref": "#/$defs/transition" },
        { "type": "array", "minItems": 1, "maxItems": 10, "items": { "$ref": "#/$defs/transition" } }
      ]
    },

    "stageCommon": {
      "type": "object", "required": ["type"],
      "properties": {
        "type":        { "type": "string" },
        "description": { "type": "string", "maxLength": 300 },
        "when":        { "$ref": "#/$defs/expr" },
        "else":        { "$ref": "#/$defs/transition" },
        "next":        { "$ref": "#/$defs/identifier" },
        "outcomes":    { "type": "object", "propertyNames": { "$ref": "#/$defs/outcome" },
                         "additionalProperties": { "$ref": "#/$defs/transitions" } },
        "set":         { "type": "object", "propertyNames": { "$ref": "#/$defs/identifier" },
                         "additionalProperties": { "$ref": "#/$defs/expr" } }
      },
      "dependentRequired": { "when": ["else"], "else": ["when"] },
      "not": { "required": ["next", "outcomes"] }
    },
    "flows": { "anyOf": [ { "required": ["outcomes"] }, { "required": ["next"] } ] },
    "terminal": { "not": { "anyOf": [ { "required": ["outcomes"] }, { "required": ["next"] } ] } },
    "modelCommon": {
      "type": "object",
      "properties": {
        "model":             { "$ref": "#/$defs/identifier" },
        "prompt":            { "$ref": "#/$defs/promptRef" },
        "temperature":       { "oneOf": [ { "type": "number", "minimum": 0, "maximum": 2 }, { "$ref": "#/$defs/settingsRef" } ] },
        "max_output_tokens": { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
        "stop":              { "type": "array", "maxItems": 4, "items": { "type": "string", "maxLength": 32 } },
        "retry":             { "oneOf": [ { "type": "integer", "minimum": 0, "maximum": 2 }, { "$ref": "#/$defs/settingsRef" } ] }
      }
    },
    "toolFilter": {
      "type": "object", "additionalProperties": false,
      "properties": { "allow": { "type": "array", "items": { "type": "string" } },
                      "deny":  { "type": "array", "items": { "type": "string" } } }
    },
    "matchRule": {
      "type": "object",
      "properties": {
        "name":     { "$ref": "#/$defs/outcome" },
        "pattern":  { "type": "string", "maxLength": 1000 },
        "match":    { "type": "string", "maxLength": 1000 },
        "keywords": { "type": "array", "items": { "type": "string" } },
        "tool":     { "type": "string" },
        "label":    { "type": "string" }
      },
      "anyOf": [ { "required": ["pattern"] }, { "required": ["match"] }, { "required": ["keywords"] } ]
    },
    "check": {
      "anyOf": [
        { "enum": ["numbers_in_results", "citations_present", "parts_answered", "schema_valid", "results_present",
                   "no_failed_citations", "length", "contains", "not_contains"] },
        { "type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$" },
        { "type": "object", "required": ["check"],
          "properties": {
            "check":       { "type": "string" },
            "tolerance":   { "type": "number", "minimum": 0 },
            "ignore":      { "type": "array", "items": { "enum": ["question", "years", "ordinals", "small_integers"] } },
            "max_numbers": { "type": "integer", "minimum": 1 },
            "per":         { "enum": ["answer", "paragraph"] },
            "min_overlap": { "type": "number", "minimum": 0, "maximum": 1 },
            "schema":      { "oneOf": [ { "const": "output" }, { "type": "object" } ] },
            "from":        { "$ref": "#/$defs/ref" },
            "min":         { "type": "integer", "minimum": 0 },
            "min_chars":   { "type": "integer", "minimum": 0 },
            "max_chars":   { "type": "integer", "minimum": 1 },
            "patterns":    { "type": "array", "items": { "type": "string", "maxLength": 1000 } },
            "expr":        { "$ref": "#/$defs/expr" },
            "message":     { "type": "string", "maxLength": 300 }
          } }
      ]
    },
    "subGraph": {
      "type": "object", "required": ["start", "stages"], "additionalProperties": false,
      "properties": {
        "start":  { "$ref": "#/$defs/identifier" },
        "stages": { "type": "object", "minProperties": 1, "maxProperties": 100,
                    "propertyNames": { "$ref": "#/$defs/identifier" },
                    "additionalProperties": { "$ref": "#/$defs/stage" } }
      }
    },
    "overlay": {
      "type": "object", "required": ["use"], "additionalProperties": false,
      "properties": {
        "use":      { "$ref": "#/$defs/plannerRef" },
        "settings": { "type": "object" },
        "models":   { "type": "object" },
        "planners": { "type": "object", "additionalProperties": {
                        "type": "object", "additionalProperties": false,
                        "properties": { "settings": { "type": "object" }, "models": { "type": "object" } } } }
      }
    },

    "act": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "act" }, "tools": { "$ref": "#/$defs/toolFilter" },
                      "tool_choice": { "enum": ["auto", "required", "none"] }, "parallel": { "$ref": "#/$defs/boolOrRef" } },
      "unevaluatedProperties": false },
    "plan": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "plan" }, "context": { "enum": ["transcript", "question"] },
                      "max_plan_steps": { "oneOf": [ { "type": "integer", "minimum": 1, "maximum": 32 }, { "$ref": "#/$defs/settingsRef" } ] },
                      "replan_note": { "$ref": "#/$defs/template" } },
      "unevaluatedProperties": false },
    "execute": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "execute" },
                      "max_parallel": { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
                      "from": { "$ref": "#/$defs/ref" } },
      "unevaluatedProperties": false },
    "call": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "call" }, "tool": { "type": "string" }, "arguments": { "type": "object" },
                      "from_rule": { "type": "boolean" }, "coerce": { "type": "boolean" }, "emit_plan": { "type": "boolean" },
                      "into": { "$ref": "#/$defs/identifier" } },
      "oneOf": [ { "required": ["tool"], "not": { "properties": { "from_rule": { "const": true } }, "required": ["from_rule"] } },
                 { "required": ["from_rule"], "properties": { "from_rule": { "const": true } }, "not": { "required": ["tool"] } } ],
      "unevaluatedProperties": false },
    "match": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "match" },
                      "rules": { "oneOf": [ { "type": "array", "maxItems": 200, "items": { "$ref": "#/$defs/matchRule" } }, { "$ref": "#/$defs/settingsRef" } ] },
                      "rules_from": { "type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}(@[0-9A-Za-z.+-]+)?\\.[a-z][a-z0-9_]{0,63}$" },
                      "against": { "$ref": "#/$defs/ref" }, "ignore_case": { "type": "boolean" }, "dotall": { "type": "boolean" },
                      "into": { "$ref": "#/$defs/identifier" } },
      "oneOf": [ { "required": ["rules"] }, { "required": ["rules_from"] } ],
      "unevaluatedProperties": false },
    "classify": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "classify" },
                      "labels": { "oneOf": [ { "type": "array", "minItems": 2, "maxItems": 50, "uniqueItems": true, "items": { "$ref": "#/$defs/outcome" } }, { "$ref": "#/$defs/settingsRef" } ] },
                      "from": { "$ref": "#/$defs/ref" }, "menu": { "enum": ["none", "planners"] },
                      "rules": { "type": "array", "maxItems": 200, "items": { "allOf": [ { "$ref": "#/$defs/matchRule" } ], "required": ["label"] } },
                      "min_confidence": { "oneOf": [ { "type": "number", "minimum": 0, "maximum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
                      "default": { "type": "string" }, "into": { "$ref": "#/$defs/identifier" } },
      "oneOf": [ { "required": ["labels"] }, { "required": ["from"] } ],
      "unevaluatedProperties": false },
    "draft": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "draft" }, "schema": { "type": "object" }, "into": { "$ref": "#/$defs/identifier" } },
      "dependentRequired": { "schema": ["into"] },
      "unevaluatedProperties": false },
    "critique": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "critique" },
                      "rubric": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "maxLength": 200 } } },
      "unevaluatedProperties": false },
    "revise": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "revise" }, "address": { "enum": ["critique", "findings", "all"] } },
      "unevaluatedProperties": false },
    "verify": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "verify" },
                      "checks": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "$ref": "#/$defs/check" } },
                      "stop_at_first": { "type": "boolean" } },
      "required": ["checks"],
      "unevaluatedProperties": false },
    "sample": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "sample" },
                      "of": { "type": "object", "required": ["type"],
                              "properties": { "type": { "enum": ["draft", "plan", "classify", "planner"] } },
                              "not": { "anyOf": [ { "required": ["outcomes"] }, { "required": ["next"] }, { "required": ["when"] }, { "required": ["set"] } ] } },
                      "n": { "oneOf": [ { "type": "integer", "minimum": 2 }, { "$ref": "#/$defs/settingsRef" } ] },
                      "temperature": { "type": "object", "additionalProperties": false, "required": ["from", "to"],
                                       "properties": { "from": { "type": "number", "minimum": 0, "maximum": 2 }, "to": { "type": "number", "minimum": 0, "maximum": 2 } } },
                      "concurrency": { "$ref": "#/$defs/intOrRef" }, "into": { "$ref": "#/$defs/identifier" } },
      "required": ["of"],
      "unevaluatedProperties": false },
    "vote": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "vote" }, "method": { "enum": ["majority", "judge"] },
                      "normalise": { "enum": ["text", "numbers", "json", "label"] },
                      "rubric": { "type": "array", "minItems": 1, "maxItems": 20, "items": { "type": "string", "maxLength": 200 } },
                      "tie_break": { "enum": ["none", "first", "judge"] } },
      "unevaluatedProperties": false },
    "foreach": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "foreach" }, "items": { "$ref": "#/$defs/ref" }, "as": { "$ref": "#/$defs/identifier" },
                      "do": { "$ref": "#/$defs/subGraph" }, "planner": { "oneOf": [ { "$ref": "#/$defs/plannerRef" }, { "$ref": "#/$defs/overlay" } ] },
                      "question": { "$ref": "#/$defs/template" },
                      "max_items": { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
                      "concurrency": { "oneOf": [ { "type": "integer", "minimum": 1 }, { "$ref": "#/$defs/settingsRef" } ] },
                      "item_answer_chars": { "type": "integer", "minimum": 100 }, "into": { "$ref": "#/$defs/identifier" } },
      "oneOf": [ { "required": ["do"] }, { "required": ["planner"] } ],
      "unevaluatedProperties": false },
    "plannerStage": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "planner" },
                      "planner": { "oneOf": [ { "$ref": "#/$defs/plannerRef" }, { "$ref": "#/$defs/overlay" },
                                              { "type": "string", "pattern": "^\\{\\{.+\\}\\}$" } ] },
                      "choices": { "oneOf": [ { "type": "array", "items": { "$ref": "#/$defs/plannerRef" } }, { "$ref": "#/$defs/settingsRef" } ] },
                      "model": { "$ref": "#/$defs/identifier" }, "question": { "$ref": "#/$defs/template" },
                      "limits": { "oneOf": [ { "$ref": "#/$defs/limits" }, { "$ref": "#/$defs/settingsRef" } ] } },
      "required": ["planner"],
      "unevaluatedProperties": false },
    "askUser": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "ask_user" }, "message": { "$ref": "#/$defs/template" },
                      "kind": { "enum": ["text", "choice", "confirm"] },
                      "options": { "oneOf": [ { "type": "array", "minItems": 2, "maxItems": 20, "items": { "type": "string" } }, { "$ref": "#/$defs/template" } ] },
                      "append_to_question": { "type": "boolean" }, "into": { "$ref": "#/$defs/identifier" } },
      "required": ["message"],
      "if": { "properties": { "kind": { "const": "choice" } }, "required": ["kind"] }, "then": { "required": ["options"] },
      "unevaluatedProperties": false },
    "condense": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/modelCommon" }, { "$ref": "#/$defs/flows" } ],
      "properties": { "type": { "const": "condense" } },
      "unevaluatedProperties": false },
    "answer": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/terminal" } ],
      "properties": { "type": { "const": "answer" }, "synthesize": { "enum": ["auto", "always", "never"] },
                      "template": { "$ref": "#/$defs/template" }, "template_from": { "const": "rule" },
                      "caveats_from_findings": { "type": "boolean" } },
      "unevaluatedProperties": false },
    "fail": { "allOf": [ { "$ref": "#/$defs/stageCommon" }, { "$ref": "#/$defs/terminal" } ],
      "properties": { "type": { "const": "fail" }, "reason": { "$ref": "#/$defs/template" } },
      "required": ["reason"],
      "unevaluatedProperties": false },

    "stage": {
      "type": "object", "required": ["type"],
      "properties": { "type": { "enum": ["act", "plan", "execute", "call", "match", "classify", "draft", "critique", "revise",
                                         "verify", "sample", "vote", "foreach", "planner", "ask_user", "condense", "answer", "fail"] } },
      "allOf": [
        { "if": { "properties": { "type": { "const": "act" } } },      "then": { "$ref": "#/$defs/act" } },
        { "if": { "properties": { "type": { "const": "plan" } } },     "then": { "$ref": "#/$defs/plan" } },
        { "if": { "properties": { "type": { "const": "execute" } } },  "then": { "$ref": "#/$defs/execute" } },
        { "if": { "properties": { "type": { "const": "call" } } },     "then": { "$ref": "#/$defs/call" } },
        { "if": { "properties": { "type": { "const": "match" } } },    "then": { "$ref": "#/$defs/match" } },
        { "if": { "properties": { "type": { "const": "classify" } } }, "then": { "$ref": "#/$defs/classify" } },
        { "if": { "properties": { "type": { "const": "draft" } } },    "then": { "$ref": "#/$defs/draft" } },
        { "if": { "properties": { "type": { "const": "critique" } } }, "then": { "$ref": "#/$defs/critique" } },
        { "if": { "properties": { "type": { "const": "revise" } } },   "then": { "$ref": "#/$defs/revise" } },
        { "if": { "properties": { "type": { "const": "verify" } } },   "then": { "$ref": "#/$defs/verify" } },
        { "if": { "properties": { "type": { "const": "sample" } } },   "then": { "$ref": "#/$defs/sample" } },
        { "if": { "properties": { "type": { "const": "vote" } } },     "then": { "$ref": "#/$defs/vote" } },
        { "if": { "properties": { "type": { "const": "foreach" } } },  "then": { "$ref": "#/$defs/foreach" } },
        { "if": { "properties": { "type": { "const": "planner" } } },  "then": { "$ref": "#/$defs/plannerStage" } },
        { "if": { "properties": { "type": { "const": "ask_user" } } }, "then": { "$ref": "#/$defs/askUser" } },
        { "if": { "properties": { "type": { "const": "condense" } } }, "then": { "$ref": "#/$defs/condense" } },
        { "if": { "properties": { "type": { "const": "answer" } } },   "then": { "$ref": "#/$defs/answer" } },
        { "if": { "properties": { "type": { "const": "fail" } } },     "then": { "$ref": "#/$defs/fail" } }
      ]
    },

    "graphPlanner": {
      "type": "object",
      "required": ["name", "version", "description", "use_when", "start", "stages"],
      "additionalProperties": false,
      "properties": {
        "name":        { "$ref": "#/$defs/identifier" },
        "version":     { "$ref": "#/$defs/semver" },
        "kind":        { "const": "graph" },
        "description": { "type": "string", "minLength": 1, "maxLength": 500 },
        "use_when":    { "type": "string", "minLength": 1, "maxLength": 300 },
        "models":      { "type": "object", "propertyNames": { "$ref": "#/$defs/identifier" },
                         "additionalProperties": { "oneOf": [ { "type": "string", "minLength": 1 }, { "type": "null" } ] } },
        "prompts":     { "type": "object", "propertyNames": { "$ref": "#/$defs/identifier" },
                         "additionalProperties": { "$ref": "#/$defs/prompt" } },
        "settings":    { "type": "object" },
        "limits":      { "$ref": "#/$defs/limits" },
        "state":       { "type": "object", "maxProperties": 32, "propertyNames": { "$ref": "#/$defs/identifier" },
                         "additionalProperties": { "$ref": "#/$defs/slot" } },
        "start":       { "$ref": "#/$defs/identifier" },
        "stages":      { "type": "object", "minProperties": 1, "maxProperties": 100,
                         "propertyNames": { "$ref": "#/$defs/identifier" },
                         "additionalProperties": { "$ref": "#/$defs/stage" } }
      }
    },
    "pythonPlanner": {
      "type": "object",
      "required": ["name", "version", "kind", "class", "description", "use_when"],
      "additionalProperties": false,
      "properties": {
        "name":        { "$ref": "#/$defs/identifier" },
        "version":     { "$ref": "#/$defs/semver" },
        "kind":        { "const": "python" },
        "class":       { "type": "string", "pattern": "^[A-Za-z_][\\w.]*:[A-Za-z_]\\w*$" },
        "description": { "type": "string", "minLength": 1, "maxLength": 500 },
        "use_when":    { "type": "string", "minLength": 1, "maxLength": 300 },
        "settings":    { "type": "object" }
      }
    }
  }
}
```
