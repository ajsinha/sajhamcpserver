# Tutorial 26: Build an LLM Tool

Build tools whose work is done by a language model, as config files: a classifier that routes
messages, then an assistant that calls other tools and remembers the conversation. Everything
runs offline on the mock model. The design and every key are in
[LLM Tools](../architecture/LLM%20Tools.md); the server-wide ceilings are under `ai.llm_tools`
in the [Configuration Reference](../getting-started/Configuration%20Reference.md).

## What you'll learn

- How an `llm` block turns an ordinary tool config into an LLM tool, and what the loader checks
- How the modes differ: `classify` returns one label, `answer` plans and calls tools
- Why an LLM tool can never reach more than its caller can
- How to measure a tool with an eval set before you enable it

## Prerequisites

- A SAJHA checkout with its virtual environment, and an admin sign-in
  ([Tutorial 1](TUTORIAL_01_getting_started.md))
- No model key: the mock provider answers every LLM-tool mode offline
  ([Tutorial 21](TUTORIAL_21_planners_memory_and_rag.md) shows how to switch to a real model)

## Steps

### 1. Read a shipped example

SAJHA ships four example LLM tools, all disabled: `llm_markets_assistant` (mode `answer`),
`llm_summarise` (`complete`), `llm_triage_ticket` (`classify`) and `llm_docs_qa` (`grounded`).
Open `config/tools/llm_triage_ticket.json`. It is an ordinary tool config (name, description,
`inputSchema`, `outputSchema`) whose `implementation` is `sajha.ai.llm_tools.LLMTool`, plus:

```json
"llm": {"mode": "classify", "model": "fast",
        "system_prompt": "billing: invoices, charges, refunds, payment. technical: errors, ...",
        "template": "Classify this support message:\n\n{{input.message}}",
        "cache": true}
```

The labels are the `enum` of the output schema's `label`; `{{input.message}}` is filled from
the validated arguments; `cache: true` answers a repeated call from the result cache.

### 2. Write your own classifier

Create `config/tools/my_priority.json`:

```json
{
  "name": "my_priority",
  "implementation": "sajha.ai.llm_tools.LLMTool",
  "description": "Sets the priority of an incident report: urgent, normal or low, with a short reason.",
  "version": "1.0.0",
  "enabled": true,
  "inputSchema": {"type": "object", "required": ["report"],
                  "properties": {"report": {"type": "string", "description": "The incident report."}}},
  "outputSchema": {"type": "object", "required": ["label", "stopped_by"], "properties": {
      "label": {"type": "string", "enum": ["urgent", "normal", "low"]},
      "reason": {"type": "string"}, "stopped_by": {"type": "string"}}},
  "llm": {"mode": "classify",
          "system_prompt": "urgent: outage, down, broken, security, data loss. normal: question, request, change. low: typo, cosmetic, suggestion.",
          "template": "Set the priority of this report:\n\n{{input.report}}"}
}
```

The registry picks the file up (hot reload, or `POST /api/admin/tools/reload`). Lint it:

```bash
python -m sajha.quality lint --tool my_priority
```

### 3. Call it

```bash
curl -s -X POST http://localhost:3002/api/tools/execute -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"tool": "my_priority", "arguments": {"report": "The payment service is down for every customer"}}'
```

The result is `{"label": "urgent", "reason": ..., "stopped_by": "answer"}`. The model must pick
one of the enum values; SAJHA validates the reply and asks once more with the errors if it does
not, and a second failure is an error result with `stopped_by: invalid_output`, never a guess.
Try `"There is a typo on the pricing page"`: the label is `low`.

(Use the port your server listens on; the token comes from `POST /api/auth/login`. Over MCP the
same call is `tools/call` with `name: my_priority`.)

### 4. Watch the loader refuse a broken block

Remove the `enum` from `label` and save. The tool no longer loads (it disappears from the
catalog and the registry records its load error), and lint says why:

```
my_priority
  ERROR   llm-config           mode classify needs an outputSchema label property with an enum of the labels
```

Put the `enum` back. The loader also refuses unknown modes, keys that belong to another mode,
template fields missing from the input schema and limits that are not positive numbers.

### 5. An assistant that calls tools and remembers

Enable the shipped assistant:

```bash
curl -s -X POST http://localhost:3002/api/admin/tools/llm_markets_assistant/enable -H "Authorization: Bearer $TOKEN"
```

Ask it something its allowed tools (`calc_*`, `yahoo_*`, `fred_*`, `boc_*`) can answer:

```bash
curl -s -X POST http://localhost:3002/api/tools/execute -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"tool": "llm_markets_assistant", "arguments": {"question": "What is the percentage change from 80 to 100?"}}'
```

The answer cites the `calc_percentage_change` call it rests on and returns a
`conversation_id`. Pass it back with a follow-up:

```bash
  -d '{"tool": "llm_markets_assistant", "arguments": {"question": "and from 100 to 150?", "conversation_id": "<id>"}}'
```

The follow-up is rewritten as a standalone question and answered (50%). The conversation
belongs to you and to this tool: anyone else who sends the id, or another tool, gets
`conversation not found`.

### 6. It runs as you

Every inner call runs as the caller, through the normal tool path: access rules, policy and the
audit chain apply to each one, and each is its own `tool.call` audit record with the same trace
id as the `llm_tool_run` record of the run. The tools the model is offered are the tool's
`tools.allow` minus `tools.deny`, intersected with what the caller may execute. Create an API key
whose tool patterns allow only `llm_*` and call the assistant with it: no calculator is offered,
so the answer rests on no tool result. An LLM tool never gives a caller more than the caller has.

### 7. Evaluate before you enable

Create `config/evals/my_priority.yaml`:

```yaml
name: my_priority
tool: my_priority
models: [mock/mock-planner]
questions:
  - id: outage
    question: An outage is urgent.
    arguments: {report: "The login page is down and returns an error for everyone"}
    answer: [{equals: urgent}]
  - id: typo
    question: A typo is low.
    arguments: {report: "Small typo in the footer"}
    answer: [{equals: low}]
```

```bash
python -m sajha.quality eval my_priority
```

An eval set with `tool:` calls that LLM tool (enabled or not) once per question with its
`arguments`, and checks the label, text or answer. The shipped examples have theirs in
`config/evals/llm_*.yaml`; run them after changing a model alias or a prompt.

### 8. See the limits

A run is bounded by its steps, tool calls, time, input size, output tokens and cost (each
capped by `ai.llm_tools.limits`), and the process protects itself: at most
`ai.llm_tools.runtime.max_concurrent_runs` runs at once, a bounded queue, then `stopped_by: busy`
(REST answers 503 with `Retry-After`). Large tool results spill to `data/spool/llm_tools/`, and
the memory guard sheds caches, then refuses runs as resident memory nears the container's limit,
raising System Notices as it does. `GET /metrics` shows `sajha_llm_tool_stopped_total`,
`sajha_llm_tool_runs_refused_total` and `sajha_llm_tool_memory_guard_state`.

## What you learned

- An LLM tool is a config file: the `llm` block picks the mode, model, prompt, tools and limits,
  and the loader refuses a block that cannot work
- Structured modes validate the model's output against the schema and retry once
- Inner calls run as the caller, so the tool can never widen anyone's access
- Eval sets measure an LLM tool on the mock before anyone relies on it

## Next

- Ground answers in your own documents: `llm_docs_qa` and `ai.rag.sources`
  ([Tutorial 21](TUTORIAL_21_planners_memory_and_rag.md))
- Constrain who may call your tool and what it may run: [Tutorial 20](TUTORIAL_20_policies_approvals_and_audit.md)
- This is the last tutorial; the [documentation index](../README.md) lists every guide
