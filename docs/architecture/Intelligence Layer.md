# SAJHA MCP Server — Intelligence Layer

The intelligence layer lets SAJHA answer a question itself: it picks tools from its own
catalog, runs them under the caller's permissions, and returns an answer with the tool
calls it relied on and a confidence score. This document describes the layer as built:
the abstractions, the providers, the gateway, the ask loop and its event stream. Every
configuration key and its default is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#ai); endpoint
summaries are in the [API Reference](../protocol/API%20Reference.md); the confidence
mathematics is the [Composition Framework](Composition%20Framework.md). How to extend the
layer (a new provider, model or planner, step by step, with tested examples) is
[Extending the Intelligence Layer](Extending%20the%20Intelligence%20Layer.md).

---

## 1. Shape

```
 consumers      POST /api/ai/ask (and the Ask SAJHA page, /ask) · sajha_ask MCP tool · /api/ai/*
                                   │
 service        IntelligenceService (sajha/ai/intelligence.py): memory → shortlist → planner → synthesis
                planners (react | plan_execute | recipes | router) · conversation memory · RAG index
                                   │
 gateway        LLMGateway (sajha/ai/gateway.py): aliases, capability match, policy, budgets,
                retries + fallback, circuit breaker, response cache, OpenTelemetry span
                                   │
 abstractions   sajha/ai/llm/: Message/ChatRequest/ChatResponse, ChatModel, EmbeddingModel,
                LLMProvider + pydantic config_model, registry, SecretStore, errors
                                   │
 providers      native: anthropic, openai, azure_openai, gemini, bedrock, mistral, cohere,
                ollama, OpenAI-compatible presets · mock · LegacyProviderAdapter
```

Everything above the provider row codes only against SAJHA's own types, so adding or
swapping a provider never touches the gateway, the service or its consumers. Nothing in
`sajha/ai/llm/` imports a vendor SDK: the native providers speak each vendor's REST API with
`httpx`; Bedrock alone needs SigV4 signing and imports `boto3` lazily (an optional
dependency; without it the Bedrock provider reports itself down with an install hint).

| Code | What |
|---|---|
| `sajha/ai/llm/types.py` | `Message` and its parts (`TextPart`, `ImagePart`, `ToolCallPart`, `ToolResultPart`), `ToolSpec`, `ChatRequest`, `ChatResponse`, `Usage`, `RequestContext`, stream events (`TextDelta`, `ToolCallDelta`, `UsageEvent`, `Done`) |
| `sajha/ai/llm/model.py` | `ModelCapabilities`, `ChatModel`, `EmbeddingModel`, `ModelDescriptor`, `HealthStatus`, `Needs` |
| `sajha/ai/llm/provider.py` | `LLMProvider`: credentials, HTTP client, catalogue, model factory, health |
| `sajha/ai/llm/settings.py` | every config model, the layered resolution, effective-config description |
| `sajha/ai/llm/registry.py` | `register_provider`, `register_model`, class paths, entry points |
| `sajha/ai/llm/catalog.py` | curated model ids, context windows and list prices (data only) |
| `sajha/ai/llm/secrets.py` | `SecretStore` (`env:`, `file:`, `db:` references) and redaction |
| `sajha/ai/llm/http.py` | httpx client construction, error mapping, SSE and NDJSON parsing |
| `sajha/ai/llm/providers/` | the native providers |
| `sajha/ai/llm/mock.py` | `MockProvider` and its models |
| `sajha/ai/llm/legacy.py` | `LegacyProviderAdapter` for providers written against the old ABC |
| `sajha/ai/gateway.py` | `LLMGateway`, `build_gateway`, `init_gateway`, `get_gateway` |
| `sajha/ai/intelligence.py` | `IntelligenceService`, `AskResult`, `AskStep`, the event stream |
| `sajha/ai/planners.py` | the `Planner` protocol (`PlanState`, `CallTools`, `Answer`, `Emit`), its registry, and the `react`, `plan_execute`, `recipes` and `router` strategies |
| `sajha/ai/memory.py` | conversation memory: `ConversationStore` (tables `ai_conversations`, `ai_conversation_turns`), `ConversationMemory` |
| `sajha/ai/rag/` | document retrieval: `chunking.py`, `stores.py` (in process, pgvector), `index.py` (`DocIndex`), `tool.py` (`sajha_search_docs`) |
| `sajha/ai/ask_tool.py` | the optional `sajha_ask` MCP tool |
| `sajha/routes/ai_routes.py` | `POST /api/ai/ask`, `GET /api/ai/config` and the older `/api/ai/*` routes |

## 2. Core abstractions

**Messages and requests** are plain dataclasses. A `ChatRequest` carries messages, a system
prompt, offered `ToolSpec`s (built from an MCP tool's name, description and input schema),
`tool_choice` (`auto`, `none`, `required` or a tool name), an optional `response_schema`
(structured output), sampling and length limits, and a `RequestContext` (user, roles,
trace id, budget key, and the RBAC check the ask loop uses). A `ChatResponse` holds the
assistant `Message` (text and/or tool calls), a finish reason (`stop`, `tool_calls`,
`length`, `content_filter`, `error`), `Usage` (tokens and cost) and latency.
`Message.meta` keeps provider round-trip state that must be echoed on the next turn
(Anthropic thinking blocks, Gemini thought signatures); it is never sent to a different
provider and never logged.

**Models** are objects: one `ChatModel` or `EmbeddingModel` per configured model, carrying
`ModelCapabilities` (chat, tools, structured output, vision, streaming, embedding, context
window, output cap, per-million-token prices, whether it accepts a temperature or a forced
tool choice, and tags such as `fast`, `reasoning`, `local`, `deterministic`).
`ChatModel.generate` is the one required method; `stream` defaults to a single `Done`
event, `agenerate` wraps `generate` in a worker thread (sync first, async wrappers), and
`validate` raises `UnsupportedFeature` for a request the model cannot serve.

**Providers** are factories. `LLMProvider` declares a registry `name` and a pydantic
`config_model`; it owns the API key, the `httpx` client (base URL, headers, proxy, TLS,
timeouts) and a concurrency limit, lists its models (curated catalogue, live discovery
where the vendor offers it, `@register_model` classes, then database and config
overrides), and creates `ChatModel`/`EmbeddingModel` objects.

**Errors** are SAJHA's, so the gateway can react without knowing the vendor:

| Error | Meaning | Gateway reaction |
|---|---|---|
| `RateLimited(retry_after)` | 429 or quota | retry after the delay, then fall back |
| `ProviderUnavailable` | 5xx, timeout, connection | retry with backoff, then fall back |
| `AuthenticationFailed` | bad or missing key | no retry; mark the provider down |
| `ContextTooLong` | prompt over the window | next candidate |
| `UnsupportedFeature` | e.g. tools on a model without them, unknown model | next candidate |
| `ContentFiltered` | refused by provider safety | no retry, no fallback; raised |
| `InvalidRequest` | malformed request | no retry; raised |
| `PolicyDenied`, `BudgetExceeded` | role policy or token budget | no call |
| `NoModelAvailable` | no candidate left | raised, naming each candidate and why it was skipped |

## 3. Providers

| Name | Wire API | Tools | Structured output | Streaming | Embeddings | Key variables (vendor) |
|---|---|---|---|---|---|---|
| `anthropic` | Messages API | yes | `output_config.format` | SSE | — | `ANTHROPIC_API_KEY` |
| `openai` | Chat Completions | yes | `response_format` json_schema | SSE | `/embeddings` | `OPENAI_API_KEY` |
| `azure_openai` | Chat Completions, GA `v1` path or deployments + `api-version` | yes | yes | SSE | yes | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` |
| `gemini` | `generateContent` (AI Studio) | yes | `responseJsonSchema` | SSE | `batchEmbedContents` | `GEMINI_API_KEY`, `GOOGLE_API_KEY` |
| `bedrock` | Converse / ConverseStream (boto3) | yes | no | event stream | Titan, Cohere (InvokeModel) | AWS credential chain |
| `mistral` | Chat Completions shape | yes (`any` for required) | yes | SSE | `mistral-embed` | `MISTRAL_API_KEY` |
| `cohere` | v2 Chat / Embed | yes | `json_object` + schema | SSE | yes | `COHERE_API_KEY` |
| `ollama` | native chat and embed endpoints | yes | `format` (JSON Schema) | NDJSON | yes | none (`OLLAMA_HOST`) |
| `groq`, `together`, `fireworks`, `deepseek`, `xai`, `openrouter`, `perplexity` | OpenAI-compatible presets | per model | per model | SSE | where offered | the vendor's `*_API_KEY` |
| `vllm`, `lmstudio`, `openai_compatible` | any `/chat/completions` server via `base_url` | yes | per server | SSE | yes | optional |
| `mock` | in process | yes | yes | yes | `mock-embed` | none |

Each provider maps the neutral types onto its wire format (tool definitions, tool-call ids,
tool results, images) and maps its errors onto the taxonomy above: 429 →
`RateLimited` with `Retry-After`/`retry-after-ms`; 401/403 → `AuthenticationFailed`;
context-length messages and 413 → `ContextTooLong`; safety blocks → `ContentFiltered`;
404 (unknown model or deployment) → `UnsupportedFeature`; 5xx, timeouts and connection
failures → `ProviderUnavailable`. Cost is computed from the model's declared prices.

The curated model lists live only in `sajha/ai/llm/catalog.py`. A deployment adds a model
or overrides a catalogue entry's capabilities and prices with `models:` in the provider's
config (or `SAJHA_AI_<PROVIDER>_MODELS` as JSON), so a new model id never needs code.

**Ollama** is local and keyless. `list_models()` merges the catalogue with the models
actually pulled on the host (Ollama's `tags` endpoint), with capabilities read from its
`show` endpoint (tools, vision, embedding, context length) unless config overrides them.
`health()` probes the `tags` endpoint with a short timeout and caches the answer, so an absent Ollama costs one quick
probe per health TTL. A model that is not pulled is skipped as a candidate. `keep_alive`,
`num_ctx`, `think` and any runtime `options` pass through; `OLLAMA_HOST` is honoured.

**Legacy providers.** A class written against the pre-6.x ABC in `sajha/ai/providers/` and
registered with `register_provider_class()` is wrapped by `LegacyProviderAdapter` and served
like any other provider (text only: the old interface parsed no tool calls). The six old
vendor modules were removed; the native providers replace them.

### Adding a provider or a model

A provider is a subclass of `LLMProvider` with `name` and `config_model` (a subclass of
`ProviderConfig`), and one registration, validated at startup:

1. the `@register_provider` decorator on a class imported at startup;
2. a class path in `ai.providers[].class` (`package.module:Class`);
3. a pip package exposing an entry point in the `sajha.llm_providers` group.

`@register_model(provider=..., model_id=...)` injects one model class into an existing
provider (a fine-tune or a custom route), inheriting the vendor's wire code. Every field of
the new `config_model` is configurable in YAML and overridable from the environment with no
further code (section 4). The step-by-step guide, with a worked provider, model and
planning strategy and the tests they pass, is
[Extending the Intelligence Layer](Extending%20the%20Intelligence%20Layer.md).

## 4. Configuration

Each provider's settings are its pydantic `config_model`; the gateway sections (`aliases`,
`policy`, `budgets`, `cache`, `retry`, `breaker`, `gateway`, `ask`) are pydantic models too.
Unknown keys fail at startup with the list of valid ones. A value is taken from the first
of:

1. `SAJHA_AI_<SECTION>_<FIELD>`, where `<SECTION>` is the provider's name upper-cased with
   non-alphanumerics as `_` (`SAJHA_AI_OPENAI_BASE_URL`, `SAJHA_AI_AZURE_OPENAI_API_VERSION`,
   `SAJHA_AI_OLLAMA_NUM_CTX`) or a gateway section (`SAJHA_AI_ASK_MAX_STEPS`,
   `SAJHA_AI_RETRY_MAX_RETRIES`, `SAJHA_AI_ALIASES_DEFAULT`). Lists take JSON or a comma
   list; dictionaries and lists of objects take JSON;
2. the vendor's own variable (`OPENAI_API_KEY`, `OLLAMA_HOST`, `AWS_REGION`, ...);
3. `config/application.yml` under `ai:` (`${VAR:default}` substituted);
4. the `llm_providers` and `llm_models` tables written by the AI settings page;
5. the code default.

`api_key_ref` points at a secret instead of holding one: `env:NAME`, `file:/path` or
`db:llm_providers/<type>`. Secrets are redacted in logs and in the effective configuration.

**Out of the box the mock serves every alias.** Every real provider ships with
`enabled: false` and is used only when enabled explicitly; a key in the environment never
enables a provider on its own. To switch to a real provider:

```bash
export SAJHA_AI_OPENAI_ENABLED=true                         # 1. enable it
export OPENAI_API_KEY=...                                   # 2. give it a key (never in application.yml)
export SAJHA_AI_ALIASES_DEFAULT="openai,mock/mock-planner"  # 3. point an alias at it, mock as fallback
```

For a local model: `SAJHA_AI_OLLAMA_ENABLED=true` and
`SAJHA_AI_ALIASES_DEFAULT="ollama,mock/mock-planner"` (a bare provider name means its
`default_model`). `GET /api/ai/config` (admin) returns the effective configuration of every
provider and section, each value with its source (`default`, `config`, `env:NAME`, `db`,
`ref:...`), the alias each name resolves to now, and `mock_active: true` with a note while
the mock is serving every alias.

## 5. The gateway

`LLMGateway` is the only thing consumers call: `chat(request, model=)`, `stream(request,
model=)`, `embed(texts, model="embedding")` and `resolve(model, needs, ctx)`.

- **Resolution.** `model` is an alias (ordered candidates), `provider/model`, or a bare
  provider. A user's saved preference goes first, then the system default set from the
  settings page, then the alias list. A candidate is used if its provider is enabled and
  healthy (health cached for `ai.gateway.health_ttl_s`), its circuit is closed, the model is
  available, its capabilities cover what the request needs (tools, structured output, vision
  are inferred from the request) and the caller's role policy allows it.
- **Policy** (`ai.policy.roles`): allowed `provider/model` globs, whether tools may be
  offered, an output-token cap, a daily token allowance. A caller with several roles gets
  the most permissive combination; a role with no entry (and no `ai.policy.default`) is
  unrestricted.
- **Reliability.** `RateLimited` and `ProviderUnavailable` are retried (`ai.retry`, or the
  provider's own `max_retries` / `backoff_*`) with exponential backoff and jitter, honouring
  `Retry-After` up to a cap; then the next candidate is tried. Each provider has a
  `CircuitBreaker` (`sajha/core/circuit_breaker.py`) that opens after repeated failures.
  `AuthenticationFailed` marks the provider down for the health TTL. Streams fall back only
  before their first event.
- **Budgets** come from the token tracker, per user and per role per UTC day
  (`ai.budgets`, and a role's `daily_tokens`); over budget is `BudgetExceeded`, not a call.
- **Cache.** Responses are cached on the canonical request (messages, tools, schema,
  temperature, limits, model) when the temperature is 0, or unset on a deterministic model,
  or when `ai.cache.cache_nonzero_temperature` is set.
- **Observability.** One OpenTelemetry span (`llm.chat`) per call with provider, model,
  alias, tokens, latency and outcome; prompts are attached only with
  `ai.gateway.trace_prompts`. The tracer is the observability module's when its SDK is
  installed, otherwise the OpenTelemetry API's (a no-op without an SDK).

The pre-6.x API remains as shims over `chat()`/`embed()`: `complete`,
`complete_messages`, `embed(texts, provider=, model=)` (its result is a list of vectors that
also has `.embeddings`), `list_all_models`, `health_check_all`, the user-preference
methods, `get_stats`, `get_token_usage` and `get_total_cost`.

## 6. The intelligence service

`IntelligenceService.ask(question, ctx)` is a bounded tool-use loop. With a `conversation_id` it
first loads the conversation (below); then:

1. **Shortlist.** The tool resolver (vector search when an embedder is configured, lexical
   BM25 otherwise) ranks tools; disabled tools and tools the caller may not run
   (`AuthContext.has_tool_access`, the same check as `POST /api/tools/execute`) are dropped;
   the top `ai.ask.shortlist` go to the model as `ToolSpec`s. Role policy without tools
   means no shortlist.
2. **Plan and act.** The planner (`ai.ask.planner`, section "Planners" below) answers or asks
   for tool calls; by default (`react`) that is one model call per step. Each call runs through
   `tool.execute_with_tracking` (enabled check, validation, cache, circuit breaker,
   metrics). A call to a tool that was not offered is refused. A tool marked destructive
   (`annotations.destructiveHint: true`, or `metadata.destructive: true`) is not run while
   `ai.ask.confirm_destructive` is on (the default): the ask stops with
   `stopped_by: needs_confirmation` and a fingerprint per pending call; re-asking with
   `confirm: [fingerprint]` runs it. Results are capped at `ai.ask.max_result_chars` and
   returned as `ToolResultPart` data; the system prompt states that tool output is data,
   never instructions.
3. **Synthesize.** A final structured-output call (`ai.ask.synthesize`) produces
   `{answer, citations, caveats}`; citations are filtered to successful tool calls. If no
   capable model is available, the loop's own answer is used.

What the model is sent at each step, and exactly when the loop stops, is laid out for
planner authors in
[Extending the Intelligence Layer §4.1](Extending%20the%20Intelligence%20Layer.md#41-how-planning-works-today).

### Planners

The planner decides only what happens next: answer, or which calls to make. Everything that
protects the caller stays in the service and applies to every planner: the RBAC-filtered
shortlist, refusing calls to tools that were not offered, destructive-tool confirmation,
running tools through `execute_with_tracking`, result caps, the limits, synthesis, confidence,
audit and the event schema. A planner reaches a model only through the gateway (so policy,
budgets, fallback and the `model` event apply) and never touches a tool.

| Planner | What it does | Model calls for a two-tool question |
|---|---|---|
| `react` (default; `model` is an alias) | one model call per step: answer, or call which offered tools | one per step, plus synthesis |
| `plan_execute` | one structured-output planning call returns a plan: steps with a tool, arguments and dependencies (`{{s1.field}}` passes a result forward); independent steps run together in one step; after a failed step it re-plans once (`max_replans`); an empty plan hands the ask to `fallback` | one, plus synthesis |
| `recipes` | regular-expression or keyword recipes from config (`ai.ask.planner_config.recipes`) map a question to a tool and its arguments, and optionally an answer template; anything else goes to `fallback` | none when the recipe has an answer template |
| `router` | chooses per question: configured `rules`, then `recipes` when one matches, then `plan_execute` for questions with several parts (compare, and then, versus, two questions), else `react` | as the chosen planner |

`ai.ask.planner` sets the default; an admin may pass `planner` on one `POST /api/ai/ask`. The
chosen chain is reported as `planner` in the result (`router>plan_execute`). `GET /api/ai/planners`
lists the registered planners. Writing one, the protocol and its tests:
[Extending the Intelligence Layer §4.5](Extending%20the%20Intelligence%20Layer.md#45-a-planner-extension-point).

**Limits**: `max_steps`, `max_tool_calls`, `max_tokens` (all model calls of one ask) and
`timeout_s`; the reason the loop stopped is reported as `stopped_by`: `answer`,
`step_limit`, `tool_limit`, `budget`, `timeout`, `needs_confirmation` or `error`.

**Confidence** is not the model's opinion. Each cited, successful step contributes its
tool's confidence (`get_tool_confidence`, by tool-name prefix) chained through the
composition framework's `EntropyGuard`; a failed call contributes 0.9 and an incomplete
loop 0.8; an answer resting on no tool result is 0.5; no answer is 0. The `confidence`
event carries the guard's per-step basis. Freshness and cross-source agreement are not yet
scored.

**Audit**: each ask writes an `ai_ask` audit-log entry (question, tools, models, planner,
tokens, outcome, confidence) unless `ai.ask.audit` is false.

### Conversation memory

An ask that sends `conversation_id` is a turn of a conversation: `"new"` starts one, and the
id the result returns continues it. Without `conversation_id` an ask is answered on its own and
nothing is kept. For a turn of a conversation the service:

1. loads the conversation, only if it belongs to the caller (another user's id, or an expired
   one, is "not found": the route answers 404);
2. sends the last `ai.memory.history_turns` turns (question and answer) as earlier messages,
   and a summary of the older ones in the system prompt; the summary is written through the
   gateway (`ai.memory.model`) once turns leave the verbatim window, and kept;
3. rewrites the question as a standalone question (`ai.memory.condense`), so "and from 100 to
   150?" after a percentage-change question shortlists the right tool; the rewrite is
   `standalone_question` in the result;
4. records the turn (question, rewrite, answer, tools, outcome, confidence) after the answer.

Memory is per user and is never shared: every read, write and delete is filtered by the
caller's user id. It is stored in the `ai_conversations` and `ai_conversation_turns` tables
(SQLite creates them; on PostgreSQL they come from `db/scripts/postgresql/schema.sql`).
Conversations idle for `ai.memory.retention_days` are deleted, as are a user's oldest beyond
`ai.memory.max_conversations_per_user`. A user lists, reads and deletes their own with
`GET /api/ai/conversations`, `GET` and `DELETE /api/ai/conversations/{id}`, and deletes all of
them with `DELETE /api/ai/conversations`. The mock answers the summary and rewrite calls
deterministically (an extractive summary; a follow-up with no topic of its own takes the
previous question's wording with its new numbers or symbols).

### Document search (RAG)

`sajha_search_docs` is an ordinary tool (`config/tools/sajha_search_docs.json`, so it is in
`tools/list`, its access follows role permissions, and any planner can call it) over a document
index (`sajha/ai/rag/`):

- **Sources.** SAJHA's own guides (every guide the help pages serve), each passage citing
  `/help/guides/<name>#<section>`; each `ai.rag.sources` entry (files matching a pattern in a
  folder of the storage backend: local, S3, Azure or GCS); and files an admin uploads
  (`POST /api/ai/docs/uploads`, kept under `ai.rag.uploads_dir`). Text formats only: Markdown,
  text, reStructuredText and HTML.
- **Passages.** Markdown is split at headings (each passage keeps its section path and anchor),
  then into passages of about `ai.rag.chunk_chars` characters at paragraph boundaries.
- **Embeddings** come from the gateway's `ai.rag.embedding_model` alias (`embedding`, which is
  `mock/mock-embed` out of the box); `none` means lexical search only.
- **Stores.** In process by default (pure Python, persisted through the storage backend, so a
  restart re-embeds only changed documents); pgvector when the database is PostgreSQL with the
  `vector` extension and the `rag_chunks` table, which is an optional section of
  `db/scripts/postgresql/schema.sql` that a DBA runs (SAJHA runs no DDL there).
- **Search** fuses the vector ranking with a BM25 ranking of the same passages (reciprocal rank
  fusion, the vector side weighted `ai.rag.vector_weight`). Each result has a citation number,
  source, document, title, section, link (for guides), a relative score and the passage.
- **Syncing.** The index is built in the background at startup and re-synced by content hash
  (`POST /api/ai/docs/reindex`, admin); `GET /api/ai/docs/status` (admin) reports it.

The help page's **Ask the docs** box (signed-in users) calls `POST /api/ai/docs/search`; a
caller who may not run `sajha_search_docs` searches SAJHA's guides only.

### `POST /api/ai/ask`

Authentication as for the other `/api` routes (session cookie, JWT or API key). Body:
`{"question": "...", "model": "<alias or provider/model>", "confirm": ["<fingerprint>"],
"conversation_id": "new" | "<id>", "planner": "<name>"}` (only `question` is required;
`planner` is for admins). The response is the `AskResult` as JSON, or, when the
request sends `Accept: text/event-stream` or `?stream=1`, a Server-Sent Events stream: each
event is `event: <type>` with `data:` the JSON below. Every event has `type` and an
increasing `seq`; the order is fixed: `shortlist` first, `done` last, a `tool_call` before
its `tool_result`, all tool results before the answer.

| `type` | Fields |
|---|---|
| `shortlist` | `tools: [{name, description, score}]` |
| `model` | `model` (`provider/model`), `step` |
| `plan` (optional) | `planner`, `revision`, `steps: [{id, tool, arguments, depends_on, why, status, call_id}]`: sent by planners that plan ahead, after the `model` event of the call that made the plan and before the `tool_call`s it schedules; `call_id` is the id of the step's `tool_call` |
| `tool_call` | `id`, `name`, `arguments`, `step` |
| `tool_result` | `id`, `name`, `ok`, `summary`, `latency_ms` |
| `needs_confirmation` | `id`, `name`, `arguments`, `fingerprint`, `reason` |
| `answer_delta` | `text` (display chunks; their concatenation is the answer) |
| `answer` | `text` |
| `confidence` | `value` (0..1), `basis` |
| `error` | `code`, `message` (followed by `done`) |
| `done` | `result`: the `AskResult` |

`AskResult` fields: `question`, `answer`, `confidence`, `steps` (`id`, `name`, `arguments`,
`ok`, `status`, `summary`, `latency_ms`, `confidence`, `fingerprint`), `citations`,
`caveats`, `usage`, `models`, `stopped_by`, `shortlist`, `pending`, `connections`,
`duration_ms`, `error`, `planner`, `plan` (the last plan, each step with its final status),
`conversation_id` and `turn` (for a turn of a conversation) and `standalone_question` (when the
question was rewritten).

### Using Ask SAJHA

The console's **Ask SAJHA** page (`/ask`, signed-in users; the first item of the AI menu)
is a chat over this endpoint. It is built from `sajha/web/templates/ai/ask.html`,
`sajha/web/static/js/ask.js` and `sajha/web/static/js/constellation.js` (the sky drawing it
shares with the landing page).

- **Asking.** Type a question and press Enter (Shift+Enter for a new line), or pick an
  example chip. The page keeps a conversation: the first question sends
  `conversation_id: "new"` and later ones the id the server returned, so a follow-up ("and
  from 100 to 150?") is answered with the earlier turns as context. The model picker sends `model`: admins see the gateway's aliases
  (from `GET /api/ai/config`), other users the enabled tool-capable models from
  `GET /api/ai/models`; "default" sends none.
- **Streaming.** The page posts with `Accept: text/event-stream` and reads the stream with
  `fetch` (EventSource cannot POST), using the session cookie like the other console
  pages. Stop (or Escape) aborts the request, which ends the server's stream.
- **What it shows.** Each answer lists the shortlist ("Considered N tools", with scores),
  the plan when the planner made one ("Plan: N steps", each step ticking off as its call
  returns),
  one chip per tool call with its result summary and latency (open a chip for its
  arguments and result), the answer, its confidence, the cited calls as sources, and the
  caveats. A `needs_confirmation` event becomes a card with Confirm and Cancel; Confirm
  asks again with `confirm: [fingerprint]`. An `error` event is shown in the answer.
- **The sky.** Beside the chat (above it on a phone) every loaded tool is a star, grouped
  by provider. The shortlist lights its tools and their groups; each `tool_call` draws a
  link from the question to that tool's star with its name, and its `tool_result` puts the
  summary there, green for success and red for failure. The events are played a few
  hundred milliseconds apart so each step is visible even when, as with the mock, the
  whole answer arrives at once. With reduced motion nothing moves and the final chain is
  drawn at once.
- **The mock.** While the mock serves the default alias the page shows a *Mock model
  active* pill (admins: `mock_active` from `/api/ai/config`; others: a `model` event naming
  `mock/...`). The mock planner answers from keywords and numbers in the question, so the
  example chips are calculator questions it can fill in; anything else needs a real
  provider (section 4).
- **History.** The bubbles are kept per browser tab in `sessionStorage`; the conversation the
  server remembers is the one in "Conversation memory" above. *New chat* clears the tab and
  starts a new conversation; an expired conversation is reported and the next question starts
  a new one.

A walkthrough is [Tutorial 10: Ask SAJHA](../tutorials/TUTORIAL_10_ask_sajha.md).

### `sajha_ask` (MCP)

With `ai.ask.mcp_tool_enabled: true` the service is also registered as the MCP tool
`sajha_ask` (`question`, optional `model` and `confirm`). A tool's `execute` does not see
the MCP caller, so its inner calls are limited to what an anonymous MCP caller may run
(`mcp.anonymous.*`) plus the `ai.ask.mcp_allowed_tools` patterns.

## 7. The mock provider

`mock` needs no network and no keys and passes the same contract tests as the real
providers. `mock-echo` replies with the last user message; `mock-scripted` plays a script
(ordered replies or regex rules; text, tool calls, JSON, errors) set in a test with
`set_script()` or loaded from `<scripts_dir>/<name>.yml` as `mock-scripted:<name>`;
`mock-planner` scores the offered tools against the question's keywords, calls the best
one or two with arguments filled from the schema (defaults, numbers near the parameter's
name, ticker symbols) and answers from the results, planning only from the question,
never from tool output; `mock-embed` hashes word n-grams into normalised vectors. Fault
injection (`latency_ms`, `fail_every`, `fail_with`, `seed`) exercises the gateway's
reliability paths. Calls are priced at zero but report token usage.

## 8. Tests

`tests/ai/`: a provider contract suite run against every provider family offline
(recorded-shape fake APIs on `httpx.MockTransport`; a fake boto3 client for Bedrock), with
live runs when a vendor key is present; gateway tests for resolution, retries, fallback,
breaker, budgets, policy, cache, configuration precedence, registry loading, secrets and
the legacy shims; ask-loop tests over the real offline `calc_*` tools, including step
limits, confirmation, injected instructions in tool output, RBAC and the event order; and
the HTTP route in JSON and SSE. `tests/ai/test_planners.py` runs every built-in planner through
the same safety tests (RBAC, tools not offered, confirmation, limits, injection, event order)
and tests each strategy; `tests/ai/test_memory.py` covers multi-turn asks, summaries, privacy
between users, retention and the conversation routes; `tests/ai/test_rag.py` the chunking,
the index, uploads, the stores and the search route; `tests/ai/test_tool_index_sync.py` that a
tool registered by any path is shortlisted without a reload.

## 9. Not built yet

- Native async providers (the layer is sync with thread-pool async wrappers).
- Vertex AI for Gemini and Claude; Entra ID token acquisition for Azure (a bearer token can
  be supplied as the key with `auth: bearer`).
- Over MCP 2026-07-28, destructive-tool confirmation inside `sajha_ask` as a Multi
  Round-Trip Request (it is returned as `needs_confirmation` today).
- Freshness and agreement in the confidence score; trimming history on `ContextTooLong`.
- Document connectors (SharePoint, Drive, Confluence) as RAG sources, and binary formats
  (PDF, Word); today a source is a folder of text files in the storage backend, or an upload.
- Conversation memory for `sajha_ask` over MCP (its caller has no user identity), and a page
  for browsing past conversations (the API exists).
