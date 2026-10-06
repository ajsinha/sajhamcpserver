# Tutorial 21: Planners, Conversation Memory and Document Search

Make Ask SAJHA plan a two-part question up front and run both tools at once, follow up on
an earlier answer, and answer questions from SAJHA's own documentation with citations, all
with the built-in mock model and no API key. How these parts work is in the
[Intelligence Layer](../architecture/Intelligence%20Layer.md#planners) guide; every key is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#ai).

## What you'll learn

- How to switch the planning strategy, and what `plan_execute`, `recipes` and `router` do
- How a follow-up question uses the earlier turns, and how to delete your history
- How to search the documentation from the help page, from Ask SAJHA and over HTTP
- How to add your own documents to the index

## Prerequisites

- [Tutorial 10: Ask SAJHA](TUTORIAL_10_ask_sajha.md): you have asked a question on `/ask`
- An admin account and an API key for the HTTP steps (`sja_...`, from **Admin → API Keys**)

## Steps

### 1. Choose a planner

The planner decides each step of an ask. The default, `react`, makes one model call per step.
Start the server with plan-and-execute instead:

```bash
export SAJHA_AI_ASK_PLANNER=plan_execute
python run_server.py
```

`GET /api/ai/planners` lists every registered planner and the configured default.

### 2. Watch a plan run

On **Ask SAJHA** (`/ask`), ask:

> Compare the Sharpe ratio and Sortino ratio for a return of 12 with risk free rate 4 and volatility 15

Before any tool runs, the answer shows **Plan: 2 steps (plan_execute)**. Open it: one step
calls `calc_sharpe_ratio`, the other `calc_sortino_ratio`, neither depends on the other, so
both tool calls start together, and each step is marked *done* as its result returns. One
planning call replaced a model call per step.

From code, an admin can choose the planner for one ask:

```bash
curl -s -X POST http://localhost:3002/api/ai/ask -H "X-API-Key: sja_..." \
     -H "Content-Type: application/json" \
     -d '{"question": "Compare the Sharpe ratio and Sortino ratio for a return of 12 with risk free rate 4 and volatility 15", "planner": "plan_execute"}'
```

The result's `planner` names the strategy and `plan` lists the steps with their final status.

### 3. Add a recipe, then let the router choose

A recipe answers a known question shape with no planning call at all. Add to your local
`config/application.yml`:

```yaml
ai:
  ask:
    planner: router
    planner_config:
      recipes:
        recipes:
          - name: pct
            tool: calc_percentage_change
            match: 'percentage change from (?P<old_value>[\d.,]+) to (?P<new_value>[\d.,]+)'
            answer: 'From {old_value} to {new_value} is a change of {percentage_change}%.'
```

Unset `SAJHA_AI_ASK_PLANNER` (the environment wins over the file) and restart. With `router`:

- "What is the percentage change from 80 to 100?" goes to **recipes**: the answer is the
  template, filled from the tool's result, and no model was called;
- the comparison question from step 2 goes to **plan_execute** (it has several parts);
- "What is the future value of 5000 at 7 percent for 20 years?" goes to **react**.

Each answer's `planner` field shows the route, for example `router>recipes`.

### 4. Ask a follow-up

Click **New chat**, then ask:

> What is the percentage change from 80 to 100?

and then:

> And from 100 to 150?

The second answer is 50%. The page sent the conversation id the first answer returned, so the
server rewrote the follow-up as "What is the percentage change from 100 to 150?" (the result's
`standalone_question`) and gave the planner the earlier turn as context. With a real model the
rewrite and the summary of older turns are written by the model `ai.memory.model` names;
the mock does both deterministically.

Over HTTP, start with `"conversation_id": "new"` and pass back the `conversation_id` you get:

```bash
curl -s -X POST http://localhost:3002/api/ai/ask -H "X-API-Key: sja_..." -H "Content-Type: application/json" \
     -d '{"question": "What is the percentage change from 80 to 100?", "conversation_id": "new"}'
# -> {..., "conversation_id": "7c4e...", "turn": 1}
curl -s -X POST http://localhost:3002/api/ai/ask -H "X-API-Key: sja_..." -H "Content-Type: application/json" \
     -d '{"question": "And from 100 to 150?", "conversation_id": "7c4e..."}'
```

### 5. See and delete your history

Conversations are yours alone: another user asking with your conversation id gets
*conversation not found*. List, read and delete them:

```bash
curl -s http://localhost:3002/api/ai/conversations -H "X-API-Key: sja_..."
curl -s http://localhost:3002/api/ai/conversations/7c4e... -H "X-API-Key: sja_..."
curl -s -X DELETE http://localhost:3002/api/ai/conversations -H "X-API-Key: sja_..."   # all of yours
```

Conversations idle for `ai.memory.retention_days` (30) are deleted on their own.

### 6. Ask the docs

Open **Help** (`/help`). Under **Ask the docs**, ask "how do I run SAJHA on several
workers?". The answer is the passages of the guides that match best, each with the guide and
section it came from; click one to open the guide at that section.

The same index is the `sajha_search_docs` tool, so Ask SAJHA's planner can call it. On `/ask`:

> Search the docs: how do I set a daily token budget per user?

The tool chain shows `sajha_search_docs`, and the answer quotes the best passage (from the
Intelligence Layer guide's section on the gateway). The mock may also try a second tool whose
name matches "search"; a real model chooses better.

### 7. Add your own documents

Admins can upload a text document (Markdown, text, reStructuredText or HTML) into the index:

```bash
curl -s -X POST http://localhost:3002/api/ai/docs/uploads -H "X-API-Key: sja_..." \
     -H "Content-Type: application/json" \
     -d '{"filename": "oncall.md", "content": "# On-call\n\n## Escalation\n\nPage the data team after 15 minutes."}'
curl -s -X POST http://localhost:3002/api/ai/docs/search -H "X-API-Key: sja_..." \
     -H "Content-Type: application/json" -d '{"query": "when do I page the data team?"}'
```

For a folder of documents, add a source (a folder in the storage backend, so it can be on
S3, Azure or GCS too) and re-index:

```yaml
ai:
  rag:
    sources:
      - {name: runbooks, path: data/runbooks, pattern: "*.md"}
```

```bash
curl -s -X POST http://localhost:3002/api/ai/docs/reindex -H "X-API-Key: sja_..." \
     -H "Content-Type: application/json" -d '{}'
curl -s http://localhost:3002/api/ai/docs/status -H "X-API-Key: sja_..."
```

Only changed documents are embedded again. Users who may not run `sajha_search_docs` search
SAJHA's own guides only.

## What next

- Write your own planner: [Extending the Intelligence Layer §4.5](../architecture/Extending%20the%20Intelligence%20Layer.md#45-a-planner-extension-point)
- Put the index in PostgreSQL with pgvector: the optional section at the end of
  `db/scripts/postgresql/schema.sql`, then `ai.rag.store: pgvector`
- Use a real model for planning, rewrites and summaries:
  [Intelligence Layer §4](../architecture/Intelligence%20Layer.md#4-configuration)
