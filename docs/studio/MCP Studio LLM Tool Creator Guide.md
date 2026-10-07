# MCP Studio LLM Tool Creator Guide

The LLM Tool Creator writes an **LLM tool**: a tool whose work a language model does (an
assistant over chosen tools, a summariser, a classifier, an extractor, a judge, a question
answerer over document search). There is no code: the page writes one config file in
`config/tools/` whose `implementation` is `sajha.ai.llm_tools.LLMTool` and which carries an
`llm` block. What each key means, how a call runs and how it is governed is owned by
[LLM Tools](../architecture/LLM%20Tools.md) (section 5 for the block, section 6 for the modes);
this guide covers only the form.

Where Studio lives, deploying, permissions and ownership are covered once in the
[MCP Studio User Guide](MCP%20Studio%20User%20Guide.md). The page is `/studio/llm`
(**MCP Studio → LLM tool**) and needs the `studio:llm` permission (or `studio:*`).

---

## Form reference

### 1. The tool

| Field | Notes |
|---|---|
| Name | 3-64 characters: a lowercase letter, then lowercase letters, digits or underscores. Read-only when editing. |
| Version | Written to the config's `version`. |
| Category, Tags | `metadata.category` (default `Intelligence`) and `metadata.tags`. |
| Description | What callers and models read to choose the tool: say what it does and when to use it. |
| Enabled | `enabled` in the config. |

### 2. Mode and model

| Field | Key | Notes |
|---|---|---|
| Mode | `llm.mode` | `answer`, `grounded`, `complete`, `extract`, `classify`, `judge` or `narrate`. The mode decides which fields below apply and which inputs and outputs are generated. |
| Model | `llm.model` | A gateway alias (preferred: operators can re-point it) or `provider/model`; empty means `ai.llm_tools.default_model`. The list offers the configured aliases. |
| Temperature | `llm.temperature` | 0 to 2; empty leaves the model's own. |

### 3. Instructions

One of: a **system prompt** written here (`llm.system_prompt`), a **prompt from the library**
with its arguments as JSON (`llm.prompt`; argument values may use `{{input.<field>}}`), or none.
The two are mutually exclusive, as the loader requires. The **template** (`llm.template`) is the
user message of the template modes (`complete`, `extract`, `classify`, `judge`, `narrate`); each
`{{input.<field>}}` in it becomes an input of the tool.

### 4. Inputs and what the mode needs

The inputs the mode needs are generated: `question` for `answer` and `grounded`, plus
`conversation_id` (conversation memory), `messages` (client history) and `confirm` (an `answer`
tool that may call destructive tools and asks first), and one string input per template
placeholder. **Add an input** adds others (name, type, description, required). Then, by mode:

| Mode | Fields | Output generated |
|---|---|---|
| `answer`, `grounded` | (sections 5 and 6 for `answer`; document sources and passages for `grounded`) | `answer`, `confidence`, `citations`, `caveats`, `stopped_by` (and `conversation_id`, `pending`, `error` where they apply) |
| `complete` | none | `text`, `stopped_by` |
| `classify` | Labels | `label` with an `enum` of the labels, `reason`, `confidence`, `stopped_by` |
| `extract` | Fields to extract (name, type, description, required) | those fields and `stopped_by` |
| `judge` | Rubric criteria, one per line `name \| description \| min \| max \| weight`, and a pass score | `scores`, `overall`, `verdict`, `reasons`, `summary`, `stopped_by` |
| `narrate` | The source composite or workflow and its arguments | `text`, `data`, `stopped_by` |

To write the schemas yourself, use **Edit the config JSON directly** (section 8): an
`inputSchema` or `outputSchema` with properties there replaces the generated one.

### 5. Tools it may call (`answer`)

**Allow** and **Deny** are glob patterns, one per line (`llm.tools.allow`, `llm.tools.deny`).
**Matching now** shows, as you type, what each pattern matches in the live catalog and the tools
the model may call, before the caller's own access narrows them further at run time. Tools that
match but are left out are listed with the reason: denied, another LLM tool (unless **May call
other LLM tools**, `llm.nesting.allow`), or destructive with **never run them**
(`llm.confirm: refuse`; the default `ask` stops for the caller's confirmation instead). A
pattern that matches no tool is shown in red; the check reports it too, because the loader lint
does.

### 6. Planner (`answer`)

**Strategy** is `llm.planner`: a planner name (its newest version), `name@version` (pinned), or
empty for the server default (`ai.planners.default`). **Callers may choose among** sets
`llm.planner_choices`, which adds an optional `planner` argument limited to those names; without
it the tool's owner decides the strategy. An inline planner or an overlay object is edited in the
config JSON. Planner files themselves are edited in the planner editor (administrators;
[Planner Reference](../architecture/Planner%20Reference.md#141-the-planner-editor)).

### 7. Limits, memory and output

| Field | Key | Notes |
|---|---|---|
| `max_steps` … `max_cost_usd` | `llm.limits.*` | Each may ask for less than the server ceiling `ai.llm_tools.limits.*` (shown as the placeholder), never more: a higher value is clamped, and the check says so. Empty means the ceiling. |
| Memory | `llm.memory.mode` | `none`, `conversation` (kept by SAJHA, per user) or `client` (the caller sends the history); `answer` and `grounded` only. |
| Idle expiry, Turns kept, accept client history | `llm.memory.ttl_minutes`, `max_turns`, `accept_client_history` | |
| Sampling | `llm.sampling` | `never`, `prefer` or `require`: the model call goes to the calling MCP client's model ([LLM Tools](../architecture/LLM%20Tools.md) §12). The loader accepts `prefer` and `require` for `complete`, `extract`, `classify` and `judge` only. |
| citations, step trace | `llm.output.citations`, `llm.output.steps` | |
| cache repeated calls | `llm.cache` | Deterministic modes only. |

### 8. Check

Every change rebuilds the config (`POST /admin/studio/llm/build`) and checks it with the
loader's own code: the `llm` block rules (`parse_llm_block`), the catalog rules and the lint
rules `llm-config`, `llm-catalog` and `llm-annotations` ([Tool Quality](../architecture/Tool%20Quality.md)).
The messages are the loader's, word for word, so a config that passes here loads. The panel also
shows the effective limits, the derived annotations (never trusted from the config), the inputs
and outputs, and the config file itself. **Edit the config JSON directly** checks a hand-edited
config (`POST /admin/studio/llm/check`); Run and Deploy then use that JSON until you change the
form again.

### 9. Try it on the mock model

**Run** sends the arguments (prefilled from the input schema) to `POST /admin/studio/llm/test`,
which runs the unsaved tool once against `ai.planners.dry_run_model` (the offline mock model):
no key, no cost, nothing remembered or audited. Every tool the tool and you may call is offered;
only read-only ones run, the others answer "not run" as in the planner dry run, unless you tick
**Also run allowed tools that are not marked read-only** (then those you may run yourself run).
The result shows how it ended (`stopped_by`), the planner and its stage path, the tool calls and
the result object.

### 10. Deploy, or save the changes

**Deploy** (`POST /admin/studio/llm/deploy`) writes `config/tools/<name>.json` through the storage
layer and loads it: it is in `tools/list` and callable at once, under the same tool permissions,
policies, audit and quality checks as every tool. It refuses a config with errors and a name in
use. The config records `metadata.created_by` and `metadata.studio_creator: llm`.

**Edit an existing LLM tool** from **LLM tools on this server** at the top of the page, or open
`/studio/llm?edit=<name>`. You may save the tools you created; an administrator may save any,
including the shipped examples. Saving replaces the config, keeps its creator, and if the new
config does not load, puts the old file back. **Start a new tool** clears the form. Delete a
Studio-made LLM tool with Studio's ordinary delete (`POST /admin/studio/delete`).

---

## Other ways in

- **Describe a tool** can propose an LLM tool from a sentence ("classify a support message into
  billing, technical or other", "summarise a news article in two sentences", "an assistant that
  answers questions using the yahoo and fred tools"); it goes through the same review, tests on
  the mock model and deploy gate ([Tool Generation](../architecture/Tool%20Generation.md)).
- **By hand:** write the config file yourself; [Tutorial 26](../tutorials/TUTORIAL_26_build_an_llm_tool.md)
  walks through one.

## Related documentation

- [LLM Tools](../architecture/LLM%20Tools.md): the tool type, modes, running as the caller, memory, limits
- [Planner Reference](../architecture/Planner%20Reference.md): planner files and the planner editor
- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md): permissions, ownership, deploy and delete
- [API Reference](../protocol/API%20Reference.md): the endpoints this page uses
