# SAJHA MCP Server — Intelligence Layer

The intelligence layer lets SAJHA answer a question itself: it picks tools from its own
catalog, runs them under the caller's permissions, and returns an answer with the tool
calls it relied on and a confidence score. This document describes the layer as built:
the public LLM API, the providers, the factory and its governed models, the ask loop and its
event stream. Every
configuration key and its default is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#ai); endpoint
summaries are in the [API Reference](../protocol/API%20Reference.md); the confidence
mathematics is the [Composition Framework](Composition%20Framework.md). How to extend the
layer (a new provider, model or planner, step by step, with tested examples) is
[Extending the Intelligence Layer](Extending%20the%20Intelligence%20Layer.md).

---

## 1. Shape

```
 consumers      POST /api/ai/ask (and the Ask SAJHA page, /ask) · sajha_ask MCP tool · /api/ai/* ·
                LLM tools · memory · RAG · Describe a tool · /v1 (OpenAI-compatible endpoint) · ...
                                   │
 service        IntelligenceService (sajha/ai/intelligence.py): memory → shortlist → planner → synthesis
                planners (config/planners files: react, plan_execute, router, auto, ...) · memory · RAG index
                                   │
 ══════════════ the boundary: sajha.ai.llm (public API) ═══════════════════════════════════════════
                                   │
 factory        LLMFactory (sajha/ai/llm/factory.py): builds providers from ai.providers / ai.aliases
                and the registry, resolves secrets, caches instances; model(name) → GovernedModel
                                   │
 proxy          GovernedModel (sajha/ai/llm/governed.py), an LLMModel: aliases, capability match,
                policy, budgets, retries + fallback, circuit breaker, response cache, audit, usage,
                OpenTelemetry span; then delegates to a provider's model
                                   │
 abstractions   LLMProvider and LLMModel (sajha/ai/llm/base.py, abstract) and their shared
                implementations ProviderBase, ChatModel, EmbeddingModel; the canonical format
                (OpenAI Chat Completions, typed); registry, SecretStore, errors
                                   │
 adapters       each provider module translates the canonical format to its vendor at the edge
                                   │
 providers      sajha/ai/llm/providers/: anthropic, openai, azure_openai, gemini, bedrock, mistral,
                cohere, ollama, OpenAI-compatible presets · mock · LegacyProviderAdapter
```

Every LLM is reached through OpenAI-style signatures, and every provider and model specific
lives inside `sajha/ai/llm/`, one module per provider, each implementing the same abstract
classes. Code outside the package uses only the public API (below); it never imports a vendor
SDK, a provider module or another private module, never constructs a provider or model, and
never sees which provider is behind a model. `tests/test_llm_boundary.py` enforces all of this
and checks that every registered provider implements the abstract classes. Adding or swapping
a provider never touches the factory, the service or its consumers. Nothing in `sajha/ai/llm/`
imports a vendor SDK either: the native providers speak each vendor's REST API with `httpx`;
Bedrock alone needs SigV4 signing and imports `boto3` lazily (an optional dependency; without
it the Bedrock provider reports itself down with an install hint).

**The public API** is what `sajha.ai.llm` exports (its package docstring lists it):

| Name | What |
|---|---|
| `llm_factory()` | the process-wide `LLMFactory`, or `None` before the intelligence layer starts; `init_llm_factory`, `build_llm_factory`, `set_llm_factory` create or install one |
| `LLMFactory.model(name, context=, needs=)` | a `GovernedModel` for an alias or `provider/model` |
| `LLMFactory.provider(name)` | a provider, for admin and catalog pages (health, configuration, models) |
| `LLMModel`, `LLMProvider` | the abstract classes every provider module implements |
| canonical types | `ChatMessage`, `ChatCompletionRequest`, `ChatCompletion`, `ChatCompletionChunk`, `ToolDefinition`, `ToolCall`, `ResponseFormat`, `EmbeddingsRequest`, `EmbeddingsResponse`, `SajhaRequest`, `ResponseSajha`, ...; `RequestContext` (the caller) and `Usage` |
| errors | `LLMError` and its subclasses (table in section 2) |
| catalog values | `ModelInfo`, `ModelCapabilities`, `HealthStatus` |

Public submodules: `canonical` (the types and their helpers), `errors`, `settings` (the
`ai.*` sections) and `secrets`. Code that adds a provider or a model outside the package uses
the provider SPI, `sajha.ai.llm.spi` (section 3). Everything else is internal.

```python
from sajha.ai.llm import ChatMessage, RequestContext, llm_factory

ctx = RequestContext(user_id="alice", roles=["analyst"])
m = llm_factory().model("reasoning", context=ctx)               # a GovernedModel
c = m.chat_completions_create(messages=[ChatMessage.user("Summarise Q3")])
c.text, c.sajha.provider, c.sajha.cost_usd                      # which provider answered, what it cost
v = llm_factory().model("embedding").embeddings_create(input=["a", "b"]).vectors
```

| Code | What |
|---|---|
| `sajha/ai/llm/__init__.py` | the public API (above) |
| `sajha/ai/llm/base.py` | the abstract classes `LLMModel` and `LLMProvider` |
| `sajha/ai/llm/factory.py` | `LLMFactory` (construction from configuration and the registry, `model()`, `provider()`), `build_llm_factory`, `init_llm_factory`, `llm_factory`, `set_llm_factory` |
| `sajha/ai/llm/governed.py` | `GovernedModel` (the proxy) and `Governor`, its engine: resolution, policy, budgets, cache, retries, breakers, fallback, audit, usage, tracing; `TokenTracker`, `ResponseCache` |
| `sajha/ai/llm/spi.py` | the provider SPI for extension code: `ProviderBase`, `ChatModel`, `EmbeddingModel`, `HTTPChatModel`, `register_provider`, `register_model`, the HTTP helpers, the legacy interface |
| `sajha/ai/llm/canonical.py` | the canonical format: `ChatCompletionRequest`, `ChatMessage`, `ToolDefinition`, `ResponseFormat`, `ChatCompletion`, `ChatCompletionChunk`, `ChunkAccumulator`, `EmbeddingsRequest`, `EmbeddingsResponse`, the `sajha` fields, and the provider-independent refusals (`check_request`) |
| `sajha/ai/llm/convert.py` | internal: lossless converters between the original types and the canonical ones |
| `sajha/ai/llm/adapter.py` | `HTTPChatModel` (sync and native async I/O over `wire` / `parse` / `translator`) and `StreamTranslator` |
| `sajha/ai/llm/cloud_auth.py` | short-lived credentials: `GoogleTokenSource` (Vertex AI), `EntraTokenSource` (Azure OpenAI) |
| `sajha/ai/llm/types.py` | `RequestContext` and `Usage` (public through the package), and the original types used only inside the package: `Message` and its parts (`TextPart`, `ImagePart`, `ToolCallPart`, `ToolResultPart`), `ToolSpec`, `ChatRequest`, `ChatResponse`, `Usage`, `RequestContext`, stream events (`TextDelta`, `ToolCallDelta`, `UsageEvent`, `Done`) |
| `sajha/ai/llm/model.py` | `ModelCapabilities`, `ModelInfo`, `ChatModel`, `EmbeddingModel`, `ModelDescriptor`, `HealthStatus`, `Needs` |
| `sajha/ai/llm/provider.py` | `ProviderBase`, the shared implementation of `LLMProvider`: credentials, HTTP client, catalogue, model construction, health |
| `sajha/ai/llm/settings.py` | every config model, the layered resolution, effective-config description |
| `sajha/ai/llm/registry.py` | `register_provider`, `register_model`, class paths, entry points |
| `sajha/ai/llm/catalog.py` | curated model ids, context windows and list prices (data only) |
| `sajha/ai/llm/secrets.py` | `SecretStore` (`env:`, `file:`, `db:` references) and redaction |
| `sajha/ai/llm/http.py` | httpx client construction (sync and async), error mapping, SSE and NDJSON parsing |
| `sajha/ai/llm/providers/` | the native providers |
| `sajha/ai/llm/mock.py` | `MockProvider` and its models |
| `sajha/ai/llm/legacy.py` | internal: the pre-6.x provider interface (`LegacyLLMProvider`, `register_provider_class`) and `LegacyProviderAdapter`, which serves it |
| `sajha/ai/intelligence.py` | `IntelligenceService`, `AskResult`, `AskStep`, the event stream |
| `sajha/ai/planners.py` | the Python `Planner` protocol (`PlanState`, `CallTools`, `Answer`, `Emit`, on canonical types), its registry, and the Python classes of `react`, `plan_execute`, `recipes` and `router` |
| `sajha/ai/planners_engine/` | planner files (`config/planners/*.yaml`): validation, the stage library, the expression language, the graph runtime, the registry and the dry run ([Planner Reference](Planner%20Reference.md)) |
| `sajha/ai/memory.py` | conversation memory: `ConversationStore` (tables `ai_conversations`, `ai_conversation_turns`), `ConversationMemory`, the scheduled purge |
| `sajha/ai/rag/` | document retrieval: `chunking.py`, `extract.py` (PDF, Word), `stores.py` (the store contract, the memory and pgvector stores), `sqlite_vec.py` (the default store), `registry.py` (`ai.rag.store` selection), `index.py` (`DocIndex`), `tool.py` (`sajha_search_docs`) |
| `sajha/ai/ask_tool.py` | the optional `sajha_ask` MCP tool: a shim over the LLM-tool type ([LLM Tools](LLM%20Tools.md)), defined in `config/tools/sajha_ask.json` |
| `sajha/ai/llm_tools/` | LLM tools: the `LLMTool` type and its modes, the `llm` block's validation, resource safety ([LLM Tools](LLM%20Tools.md)) |
| `sajha/routes/ai_routes.py` | `POST /api/ai/ask`, `GET /api/ai/config` and the older `/api/ai/*` routes |

## 2. Core abstractions

**The canonical format** is OpenAI Chat Completions, as typed pydantic models
(`sajha/ai/llm/canonical.py`): a `ChatCompletionRequest` of `messages` (roles `system`,
`developer`, `user`, `assistant`, `tool`; content as a string or `text` / `image_url` parts),
`tools` (functions), `tool_choice`, `parallel_tool_calls`, `response_format` (`json_schema`
or `json_object`), sampling and length fields, `stream_options`, `user` and `metadata`; a
`ChatCompletion` of `choices` (each a `message` with `content`, `tool_calls` whose
`arguments` are a JSON string, `refusal`) with a standard `finish_reason` (`stop`,
`length`, `tool_calls`, `content_filter`) and `usage` (`prompt_tokens`,
`completion_tokens`, cached and reasoning token details); `chat.completion.chunk` objects
for streams, with usage in the last chunk; and `EmbeddingsRequest` / `EmbeddingsResponse`.
Which fields are supported, passed through to OpenAI-compatible servers only, or refused is
settled in [LLM Tools §13.6](LLM%20Tools.md#136-field-coverage).

SAJHA's own data travels in one `sajha` field, so a request stripped of it is a valid
OpenAI request and a response stripped of it a valid OpenAI response. On a request:
`sajha.context` (a `RequestContext`: user, roles, trace id, budget key and the RBAC check
the ask loop uses), capability `needs`, and for embeddings `input_purpose` (`query` or
`document`). On a response: `provider`, `qualified_model`, `cost_usd`, `cached`,
`latency_ms`, the fallback `attempts`, `trace_id`, and the markers that say what SAJHA did on
the caller's behalf: `ignored` (sampling parameters left out for a model without them),
`usage_estimated`, `structured_output` (`native` or `emulated`). Provider round-trip state
(Anthropic thinking blocks, Gemini thought signatures) rides on an assistant message as
`sajha.provider_state`: echoed only to the provider that wrote it, excluded from every dump,
never logged. `user` and `metadata` are recorded in the audit record and never sent to a
vendor.

The original types (`ChatRequest`, `ChatResponse` with `refusal` and `notes`, the stream
events `TextDelta`, `ToolCallDelta`, `UsageEvent`, `Done`) remain inside the package only,
for models written against the original interface; `sajha/ai/llm/convert.py` converts both
ways without loss for everything they can express. Every caller outside the package (the ask
service, planners, memory, RAG, LLM tools, Describe a tool, the OpenAI-compatible endpoint,
the tool resolver, connectors, quality evals, the AI routes) uses the canonical types.

**Models** implement the abstract `LLMModel` (`sajha/ai/llm/base.py`): one `ChatModel` or
`EmbeddingModel` per configured model (the shared implementations), carrying
`ModelCapabilities` (chat, tools, structured output, vision, streaming, embedding, context
window, output cap, per-million-token prices, sampling controls, forced and named tool
choice, JSON mode, strict tools, parallel-call control, seed, stop sequences, reasoning
effort, native `n`, variable embedding size, and tags such as `fast`, `reasoning`,
`local`, `deterministic`). Their interface is shaped like an OpenAI-style client:
`chat_completions_create`, `chat_completions_stream`, `achat_completions_create`,
`achat_completions_stream`, `embeddings_create` and `aembeddings_create` (a chat model
refuses embeddings and an embedding model refuses chat with `UnsupportedFeature`); `info()` returns
the `ModelInfo` (id, provider, kind, capabilities) that `provider.models()` lists like
`GET /v1/models`. Every call first runs `prepare`: the provider-independent refusals
(`InvalidRequest` naming the field), then the declared capabilities — an undeclared feature
raises `UnsupportedFeature`, `temperature`/`top_p` on a model without sampling controls are
left out and named in `sajha.ignored`, and `json_schema` on a model with JSON mode but no
schema output is emulated (JSON mode, the schema in the instructions, validation, one
retry). Nothing is downgraded silently. `n` > 1 on a model without native `n` becomes `n`
calls with the choices merged. Models written against the original interface (`generate`,
`stream`, `embed`) keep working through the converters.

**Providers** implement the abstract `LLMProvider`: `from_settings`, `active`, `models`,
`model`, `chat_model`, `embedding_model`, `health`, `describe_config`, `close`. The shared
implementation, `ProviderBase`, declares a registry `name` and a pydantic
`config_model`; it owns the API key, the `httpx` client (base URL, headers, proxy, TLS,
timeouts) and a concurrency limit, lists its models (curated catalogue, live discovery
where the vendor offers it, `@register_model` classes, then database and config
overrides), and creates `ChatModel`/`EmbeddingModel` objects (`provider.models()` and
`provider.model(name)` are the OpenAI-style face). Credentials that expire are served per
request (`request_headers()`), from cached token sources that refresh before expiry.

**Errors** are SAJHA's, so the governed model can react without knowing the vendor:

| Error | Meaning | Reaction |
|---|---|---|
| `RateLimited(retry_after)` | 429 or quota | retry after the delay, then fall back |
| `ProviderUnavailable` | 5xx, timeout, connection | retry with backoff, then fall back |
| `AuthenticationFailed` | bad or missing key | no retry; mark the provider down |
| `ContextTooLong` | prompt over the window | next candidate |
| `UnsupportedFeature` | e.g. tools on a model without them, unknown model | next candidate |
| `ModelFailed` | the vendor answered but the generation failed (Gemini `MALFORMED_FUNCTION_CALL`, Cohere `ERROR`/`TIMEOUT`) | next candidate; not counted toward the breaker |
| `ContentFiltered` | refused by provider safety | no retry, no fallback; raised |
| `InvalidRequest` | malformed request | no retry; raised |
| `PolicyDenied`, `BudgetExceeded` | role policy or token budget | no call |
| `NoModelAvailable` | no candidate left | raised, naming each candidate and why it was skipped |

## 3. Providers

| Name | Wire API | Tools | Structured output | Streaming | Embeddings | Key variables (vendor) |
|---|---|---|---|---|---|---|
| `anthropic` | Messages API, or Vertex AI (`platform: vertex`, `rawPredict`) | yes | `output_config.format` | SSE | — | `ANTHROPIC_API_KEY`; on Vertex `ANTHROPIC_VERTEX_PROJECT_ID`, `CLOUD_ML_REGION`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `openai` | Chat Completions | yes | `response_format` json_schema | SSE | `/embeddings` | `OPENAI_API_KEY` |
| `azure_openai` | Chat Completions, GA `v1` path or deployments + `api-version`; api-key, bearer or Entra ID (`auth: entra`) | yes | yes | SSE | yes | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`; Entra `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_FEDERATED_TOKEN_FILE` |
| `gemini` | `generateContent` (AI Studio), or Vertex AI (`platform: vertex`) | yes | `responseJsonSchema` | SSE | `batchEmbedContents` (Vertex: `predict`) | `GEMINI_API_KEY`, `GOOGLE_API_KEY`; on Vertex `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_APPLICATION_CREDENTIALS` |
| `bedrock` | Converse / ConverseStream (boto3) | yes | no | event stream | Titan, Cohere (InvokeModel) | AWS credential chain |
| `mistral` | Chat Completions shape | yes (`any` for required) | yes | SSE | `mistral-embed` | `MISTRAL_API_KEY` |
| `cohere` | v2 Chat / Embed | yes | `json_object` + schema | SSE | yes | `COHERE_API_KEY` |
| `ollama` | native chat and embed endpoints | yes | `format` (JSON Schema) | NDJSON | yes | none (`OLLAMA_HOST`) |
| `groq`, `together`, `fireworks`, `deepseek`, `xai`, `openrouter`, `perplexity` | OpenAI-compatible presets | per model | per model | SSE | where offered | the vendor's `*_API_KEY` |
| `vllm`, `lmstudio`, `openai_compatible` | any `/chat/completions` server via `base_url` | yes | per server | SSE | yes | optional |
| `mock` | in process | yes | yes | yes | `mock-embed` | none |

Each provider is an adapter: it translates the canonical format to its vendor's API and back,
once, at the edge (tool definitions and choice, tool-call ids, tool results, images,
structured output, sampling, refusals, usage, stream events). For the OpenAI-compatible
servers (OpenAI, Azure OpenAI, Mistral and the presets) the adapter is a pass-through; what
differs is authentication, base URL and path, and the declared spellings `max_tokens_param`,
`tool_choice_required` (Mistral's `any`) and `seed_param` (Mistral's `random_seed`). Role
`developer` goes unchanged to OpenAI and Azure OpenAI and as `system` elsewhere. Refusals
are kept: OpenAI's `refusal`, Anthropic `stop_reason: refusal`, Gemini safety finishes and
Bedrock `guardrail_intervened` become `finish_reason: content_filter` with
`message.refusal`. Embedding purpose maps to Cohere `input_type` (`search_query` /
`search_document`) and Gemini `taskType` (`RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT`). Every
HTTP provider has a native async path on `httpx.AsyncClient`; Bedrock's runs boto3 in a
worker thread. Each provider maps its errors onto the taxonomy above: 429 →
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

**Vertex AI** (`platform: vertex` on `gemini` and `anthropic`) authenticates with a Google
access token from a service-account file (`credentials_file`, or
`GOOGLE_APPLICATION_CREDENTIALS`: a signed JWT exchanged for a token), an authorized-user
file, or, with no file, the metadata server (GKE workload identity, Cloud Run, Compute
Engine); workload identity federation files use `google-auth` when it is installed. Claude
on Vertex is called at `publishers/anthropic/models/<model>:rawPredict` with
`anthropic_version: vertex-2023-10-16` in the body. **Entra ID** (`auth: entra` on
`azure_openai`) acquires tokens by client secret, by AKS workload identity (the federated
token file as client assertion) or by managed identity (the App Service identity endpoint,
else IMDS); `entra_mode: auto` picks the first that is configured. Tokens are cached and
refreshed five minutes before they expire (`sajha/ai/llm/cloud_auth.py`).

**Legacy providers.** A class written against the pre-6.x ABC (`LegacyLLMProvider`, formerly
`sajha.ai.providers.LLMProvider`; import it and `register_provider_class` from
`sajha.ai.llm.spi`) is wrapped by `LegacyProviderAdapter` and served like any other provider
(text only: the old interface parsed no tool calls). The `sajha.ai.providers` package is
gone; the native providers replaced its vendor modules. New providers subclass
`ProviderBase`.

### Adding a provider or a model

A provider is a module with a subclass of `ProviderBase` (from `sajha.ai.llm.spi`; it
implements the abstract `LLMProvider`) with `name` and `config_model` (a subclass of
`ProviderConfig`), and one registration, validated at startup (a class that leaves an abstract
method unimplemented is refused):

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

Each provider's settings are its pydantic `config_model`; the factory's sections (`aliases`,
`policy`, `budgets`, `cache`, `retry`, `breaker`, `gateway`, `ask`) are pydantic models too.
Unknown keys fail at startup with the list of valid ones. A value is taken from the first
of:

1. `SAJHA_AI_<SECTION>_<FIELD>`, where `<SECTION>` is the provider's name upper-cased with
   non-alphanumerics as `_` (`SAJHA_AI_OPENAI_BASE_URL`, `SAJHA_AI_AZURE_OPENAI_API_VERSION`,
   `SAJHA_AI_OLLAMA_NUM_CTX`) or a factory section (`SAJHA_AI_ASK_MAX_STEPS`,
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

## 5. The factory and governed models

`LLMFactory` is the only way consumers reach a model. It builds every provider once, from
`ai.providers` (a built-in name, a `type`, or a `class: package.module:Class`), the legacy
per-vendor keys, the registry (built-ins, class paths, `sajha.llm_providers` entry points),
the `llm_providers` / `llm_models` tables and the secret store, and keeps the instances.
`model(name)` returns a `GovernedModel`: a proxy implementing `LLMModel` that runs the
governance below and then delegates to the provider's own model object (which delegates the
wire work to its adapter functions). The factory is also an OpenAI-style client, with the
model as a field:

```python
f = llm_factory()
m = f.model("reasoning", context=ctx)      # GovernedModel; context binds the caller
m.chat_completions_create(messages=[...], tools=[...])          # -> ChatCompletion
m.chat_completions_stream(...)             # -> chat.completion.chunk objects
await m.achat_completions_create(...)      # native async
m.achat_completions_stream(...)            # async iterator of chunks
f.model("embedding").embeddings_create(input=[...], sajha=SajhaRequest(input_purpose="query"))
m.info()                                   # the ModelInfo that would answer now for this caller
f.chat_completions_create(model="fast", messages=[...], sajha=SajhaRequest(context=ctx))   # same, client style
f.models(ctx)                              # -> ModelInfo the caller's role may use
f.provider("openai")                       # admin and catalog pages only
```

- **Resolution.** `model` is an alias (ordered candidates), `provider/model`, or a bare
  provider. A user's saved preference goes first, then the system default set from the
  settings page, then the alias list. A candidate is used if its provider is enabled and
  healthy (health cached for `ai.gateway.health_ttl_s`), its circuit is closed, the model is
  available, its capabilities cover what the request needs (tools and vision are inferred
  from the request) and the caller's role policy allows it. A candidate whose model refuses
  the request (`UnsupportedFeature`: forced tool choice, structured output, seed, ...) or
  whose generation fails (`ModelFailed`) is recorded in `sajha.attempts` and the next one
  is tried. Requests refused for every provider (`InvalidRequest`) fail before any call;
  `n` is capped by `ai.gateway.max_samples`.
- **Policy** (`ai.policy.roles`): allowed `provider/model` globs, whether tools may be
  offered, an output-token cap, a daily token allowance. A caller with several roles gets
  the most permissive combination; a role with no entry (and no `ai.policy.default`) is
  unrestricted.
- **Reliability.** `RateLimited` and `ProviderUnavailable` are retried (`ai.retry`, or the
  provider's own `max_retries` / `backoff_*`) with exponential backoff and jitter, honouring
  `Retry-After` up to a cap; then the next candidate is tried (sync and async alike). Each provider has a
  `CircuitBreaker` (`sajha/core/circuit_breaker.py`) that opens after repeated failures.
  `AuthenticationFailed` marks the provider down for the health TTL. Streams fall back only
  before their first event.
- **Budgets** come from the token tracker, per user and per role per UTC day
  (`ai.budgets`, and a role's `daily_tokens`); over budget is `BudgetExceeded`, not a call.
- **Cache.** Responses are cached on the canonical request (messages, tools, schema,
  temperature, limits, model) when the temperature is 0, or unset on a deterministic model,
  or when `ai.cache.cache_nonzero_temperature` is set. Refusals and truncated answers are
  never cached; a cached answer reports `sajha.cached: true` and zero usage.
- **Streams.** The final usage chunk is returned when `stream_options.include_usage` is set;
  usage is always recorded.
- **Observability.** One OpenTelemetry span (`llm.chat`) per call with provider, model,
  alias, tokens, latency and outcome; prompts are attached only with
  `ai.gateway.trace_prompts`. The tracer is the observability module's when its SDK is
  installed, otherwise the OpenTelemetry API's (a no-op without an SDK).

Admin and catalog pages use the factory's own methods: `qualify(provider, model)` (a target
from a provider/model pair, as `/api/ai/complete` takes them), `provider_health`,
`describe_config`, the user-preference methods, `set_system_default`, `get_stats`,
`cache_stats`, `get_token_usage`, `get_total_cost`, `breaker_states` and
`LLMFactory.provider_types()`. The pre-6.x `complete`, `complete_messages` and
`list_all_models` are gone (use `model(...).chat_completions_create` and `models()`).

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
audit and the event schema. A planner reaches a model only through a governed model (so policy,
budgets, fallback and the `model` event apply) and never touches a tool.

| Planner | What it does | Model calls for a two-tool question |
|---|---|---|
| `react` (default; `model` is an alias) | one model call per step: answer, or call which offered tools | one per step, plus synthesis |
| `plan_execute` | one structured-output planning call returns a plan: steps with a tool, arguments and dependencies (`{{s1.field}}` passes a result forward); independent steps run together in one step; after a failed step it re-plans once (`max_replans`); an empty plan hands the ask to `fallback` | one, plus synthesis |
| `recipes` | regular-expression or keyword recipes from config (`ai.ask.planner_config.recipes`) map a question to a tool and its arguments, and optionally an answer template; anything else goes to `fallback` | none when the recipe has an answer template |
| `router` | chooses per question: configured `rules`, then `recipes` when one matches, then `plan_execute` for questions with several parts (compare, and then, versus, two questions), else `react` | as the chosen planner |

These four ship as planner files in `config/planners/` (with the same settings and behaviour as
their Python classes, which `ai.planners.python_builtins: true` brings back), next to the other shipped
strategies (`rewoo`, `reflect`, `verify_then_answer`, `self_consistency`, `branch_and_judge`,
`map_reduce`, `human_in_the_loop`, `auto`); the [Planner Reference](Planner%20Reference.md) owns
the file format and every shipped file. `ai.ask.planner` sets the default; an admin may pass
`planner` on one `POST /api/ai/ask`. The chosen chain is reported as `planner` in the result
(`router>plan_execute`), the stages taken as `planner_path`. `GET /api/ai/planners` lists every
planner. Writing one: a file ([Tutorial 27](../tutorials/TUTORIAL_27_write_a_planner.md)), or in
Python, [Extending the Intelligence Layer §4.5](Extending%20the%20Intelligence%20Layer.md#45-a-planner-extension-point).

**Planners across SAJHA Net.** The shortlist holds this server's own tools, SAJHA Net proxies and
federated tools together, and records for each where it runs and why it ranked there
(`sajha/ai/locality.py`; the `locality` field of each `shortlist` event entry): local tools first,
then remote hosts by `sajhanet.preferences`, same region, health and indicative latency, as small
nudges of the resolver's score. A **locality restriction** keeps a planner to `local` tools or to
one net (`net:<name>`, this server's tools plus that net's): `locality` on `POST /api/ai/ask`, else
the planner's `settings.locality` (in a planner file or a `planner_config` overlay), else
`ai.ask.locality` (default `any`). A remote tool, including another instance's LLM tool, runs on its
host as the user with the host's models and budgets; it counts here as one tool call, and its model
spend is reported back but charged only there. A chain that crosses instances and nests planners'
tools, LLM tools and composites is bounded by `sajhanet.max_call_chain`. [SAJHA Net](SAJHA%20Net.md)
sections 13 and 14 own the rules.

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

1. loads the conversation, only if it belongs to the caller and to the Ask SAJHA page (another
   user's id, an LLM tool's, or an expired one, is "not found": the route answers 404);
2. sends the last `ai.memory.history_turns` turns (question and answer) as earlier messages,
   and a summary of the older ones in the system prompt; the summary is written through the
   factory (`ai.memory.model`) once turns leave the verbatim window, and kept. Only the
   window's rows (and any turns that just left it, for the summary) are read, never the
   whole conversation;
3. rewrites the question as a standalone question (`ai.memory.condense`), so "and from 100 to
   150?" after a percentage-change question shortlists the right tool; the rewrite is
   `standalone_question` in the result;
4. records the turn (question, rewrite, answer, tools, outcome, confidence) after the answer;
   the question and the answer are each clipped to `ai.memory.max_turn_chars`.

Memory is per user and is never shared: every read, write and delete is filtered by the
caller's user id. It is stored in the `ai_conversations` and `ai_conversation_turns` tables
(SQLite creates them; on PostgreSQL they come from `db/scripts/postgresql/schema.sql`).
A conversation row also has a scope, `tool_name` (null for the Ask SAJHA page, else the LLM
tool that owns it), and an optional `expires_ts`; a conversation is only ever continued in
its own scope.

**For LLM tools** (the design is [LLM Tools](LLM%20Tools.md) §10) `ConversationMemory` offers
a small API, documented in the `sajha/ai/memory.py` docstring: `open()` implements the handle
(no id: a new conversation; an id the caller owns for that tool and that has not expired:
continued; anything else: `conversation not found`, never "forbidden"), `record()` stores a
turn, renews `expires_ts` from the tool's `ttl_minutes` (capped by `ai.memory.retention_days`)
and, beyond the tool's `max_turns` (capped by `ai.llm_tools.memory.max_turns`), folds the
oldest turns into the summary and deletes their rows; `from_client()` builds the context from
history the caller sends (`messages: [{role, content}]`, user and assistant only), storing
nothing. Anonymous callers get no stored conversation. The Ask SAJHA page keeps every turn.

**Purging.** A job deletes conversations idle for `ai.memory.retention_days`, past their own
`expires_ts`, a user's oldest beyond `ai.memory.max_conversations_per_user`, and a user's oldest
of one tool beyond `ai.llm_tools.memory.max_conversations_per_tool`. It runs every
`ai.llm_tools.memory.purge_interval_minutes` on exactly one worker: every worker wakes in the
same slot and the first to claim the slot in the state store runs it (with `0`, the old
behaviour: at most hourly, when a turn is written). `ai.llm_tools.memory.sqlite_vacuum` runs
`VACUUM` after a purge that deleted rows. Metrics: `sajha_llm_tool_conversations{tool}`,
`sajha_llm_tool_turns_total{tool}` and `sajha_llm_tool_purged_total` (`tool="ask"` is the Ask
SAJHA page).

A user lists, reads and deletes their own conversations with `GET /api/ai/conversations` (the
Ask SAJHA page's; `?tool=<name>` one tool's, `?tool=*` all), `GET` and
`DELETE /api/ai/conversations/{id}`, and deletes all of them with `DELETE /api/ai/conversations`. The mock answers the summary and rewrite calls
deterministically (an extractive summary; a follow-up with no topic of its own takes the
previous question's wording with its new numbers or symbols).

### Document search (RAG)

`sajha_search_docs` is an ordinary tool (`config/tools/sajha_search_docs.json`, so it is in
`tools/list`, its access follows role permissions, and any planner can call it) over a document
index (`sajha/ai/rag/`):

- **Sources.** SAJHA's own guides (every guide the help pages serve), each passage citing
  `/help/guides/<name>#<section>`; each `ai.rag.sources` entry (files matching a pattern in a
  folder of the storage backend: local, S3, Azure or GCS); and files an admin uploads
  (`POST /api/ai/docs/uploads`, kept under `ai.rag.uploads_dir`). Formats: Markdown, text,
  reStructuredText and HTML; and PDF (`.pdf`, needs the optional package `pypdf`) and Word
  (`.docx`, needs `python-docx`), read by `sajha/ai/rag/extract.py`. Without the package such a
  file is skipped and the build's `errors` say which package to install (an upload answers 400
  with the same message); everything else indexes as usual. Word headings become sections like
  Markdown headings; a PDF is split by paragraphs. A scanned PDF has no text layer and is
  reported as having no text (there is no OCR).
- **Passages.** Markdown is split at headings (each passage keeps its section path and anchor),
  then into passages of about `ai.rag.chunk_chars` characters at paragraph boundaries.
- **Embeddings** come from the factory's `ai.rag.embedding_model` alias (`embedding`, which is
  `mock/mock-embed` out of the box); `none` means lexical search only. Passages are embedded
  with the `document` purpose and the query with the `query` purpose (models that embed the
  two differently get the right one), `ai.rag.embed_batch_size` passages per call.
- **Stores** (below) keep the passages and answer both halves of a search.
- **Search** fuses the store's vector ranking with its keyword (BM25) ranking of the same
  passages (reciprocal rank fusion, the vector side weighted `ai.rag.vector_weight`). Each
  result has a citation number, source, document, title, section, link (for guides), a relative
  score and the passage.
- **Syncing.** The index is built in the background at startup and re-synced by content hash
  (`POST /api/ai/docs/reindex`, admin); `GET /api/ai/docs/status` (admin) reports it, including
  which document readers are installed (`document_readers`). A PDF or Word file is hashed on its
  bytes, so an unchanged one is skipped before its text is extracted.

The help page's **Ask the docs** box (signed-in users) calls `POST /api/ai/docs/search`; a
caller who may not run `sajha_search_docs` searches SAJHA's guides only.

#### Stores

`ai.rag.store` chooses where the passages live, by configuration alone; each store's settings
are under `ai.rag.stores.<name>` (keys in the
[Configuration Reference](../getting-started/Configuration%20Reference.md)):

| Store | Where the passages are | Vector search | Keyword search | Memory |
|---|---|---|---|---|
| `sqlite_vec` | a SQLite file of its own (`ai.rag.stores.sqlite_vec.path`) | sqlite-vec `vec0`, cosine | SQLite FTS5 (BM25, Porter stemming) | top k rows only |
| `memory` | the process; persisted through the storage backend as `ai.rag.index_path` | pure Python scan | in-process BM25 | every passage, its vector and its terms |
| `pgvector` | `rag_chunks` in PostgreSQL (SAJHA's database, or `ai.rag.stores.pgvector.dsn`) | pgvector `<=>` | PostgreSQL full-text search | top k rows only |

`auto`, the default, is `sqlite_vec` when the sqlite-vec extension loads and `memory`
otherwise. The registry (`sajha/ai/rag/registry.py`) also accepts a store registered by a
package (entry-point group `sajha.rag.stores`) or named as `package.module:Class`; writing one is
in [Extending the Intelligence Layer](Extending%20the%20Intelligence%20Layer.md#6-writing-a-document-store).
When the chosen store cannot run (the package is missing, this Python's `sqlite3` cannot load
extensions, PostgreSQL has no `vector` extension or `rag_chunks` table), the index uses the
memory store and raises the System Notice `rag.store_fallback` with the reason; the notice
clears once the store runs. The store in use, and any fallback reason, are in
`GET /api/ai/docs/status` (`store`, `store_configured`, `store_fallback`).

- **sqlite_vec** never touches SAJHA's own database: it opens its file with Python's `sqlite3`
  (refusing a path that is SAJHA's SQLite database), in WAL mode, with one writer connection
  and a reader connection per thread, so searches run while the index builds. The file holds
  `rag_documents`, `rag_chunks`, the FTS5 table `rag_fts` (kept in step by triggers), the
  `vec0` table `rag_vec` (created on the first vector with that embedder's dimension; never in
  keyword-only mode) and `rag_meta` (schema version, embedder, dimension). A different
  embedder clears the file; a different dimension under the same embedder name makes the build
  start again from scratch. With `ai.rag.persist: false` the store is a temporary file removed
  when it closes. The file is local even when the storage backend is S3, Azure or GCS: on a host
  without a persistent disk a restart re-embeds everything.
- **memory** holds every passage's text, its vector (float32, 4 bytes per dimension) and a BM25
  index of its words in the process, so its memory grows with the corpus, and a search scans
  every vector in Python. It suits small setups and tests; it is also the fallback.
- **pgvector** needs the optional section of `db/scripts/postgresql/schema.sql`, which a DBA
  runs (SAJHA runs no DDL there); that section also shows the optional HNSW and full-text
  indexes for large corpora.

Indexing streams: documents are read one at a time, and each document's passages are embedded
`ai.rag.embed_batch_size` at a time while the store consumes them, so a build never holds the
corpus in memory; only the memory store keeps it, by design.

### `POST /api/ai/ask`

Authentication as for the other `/api` routes (session cookie, JWT or API key). Body:
`{"question": "...", "model": "<alias or provider/model>", "confirm": ["<fingerprint>"],
"conversation_id": "new" | "<id>", "planner": "<name>", "locality": "any" | "local" | "net:<name>"}`
(only `question` is required; `planner` is for admins). The response is the `AskResult` as JSON, or, when the
request sends `Accept: text/event-stream` or `?stream=1`, a Server-Sent Events stream: each
event is `event: <type>` with `data:` the JSON below. Every event has `type` and an
increasing `seq`; the order is fixed: `shortlist` first, `done` last, a `tool_call` before
its `tool_result`, all tool results before the answer.

| `type` | Fields |
|---|---|
| `shortlist` | `tools: [{name, description, score, locality}]` (`locality`: `where` (`local`, `remote`, `federated`), for a remote tool its `net`, `instance`, `region`, `latency_ms_p50`, `health`, and `why` in words); `locality: {restrict, by}` when the ask is restricted |
| `model` | `model` (`provider/model`), `step` |
| `plan` (optional) | `planner`, `revision`, `steps: [{id, tool, arguments, depends_on, why, status, call_id}]`: sent by planners that plan ahead, after the `model` event of the call that made the plan and before the `tool_call`s it schedules; `call_id` is the id of the step's `tool_call` |
| `tool_call` | `id`, `name`, `arguments`, `step` |
| `tool_result` | `id`, `name`, `ok`, `summary`, `latency_ms` |
| `needs_confirmation` | `id`, `name`, `arguments`, `fingerprint`, `reason` |
| `answer_delta` | `text` (display chunks; their concatenation is the answer) |
| `answer` | `text` |
| `confidence` | `value` (0..1), `basis` |
| `planner_chosen` | `planner`, `version`, `by` (`server default`, `caller choice`, `tool config`, `version route`, `label <confidence>`, `rule`, `default`, `escalation`, `stage <id>`), `reason` |
| `stage_start` / `stage_end` (planner files) | `stage`, `stage_type`, `visit`, `planner` / `stage`, `outcome`, `ms`, `planner` |
| `loop_exhausted` / `expression_error` (planner files) | `stage`, `edge`, `to` / `stage`, `expression`, `message` |
| `error` | `code`, `message` (followed by `done`) |
| `done` | `result`: the `AskResult` |

`AskResult` fields: `question`, `answer`, `confidence`, `steps` (`id`, `name`, `arguments`,
`ok`, `status`, `summary`, `latency_ms`, `confidence`, `fingerprint`), `citations`,
`caveats`, `usage`, `models`, `stopped_by`, `shortlist`, `pending`, `connections`,
`duration_ms`, `error`, `planner`, `plan` (the last plan, each step with its final status),
`conversation_id` and `turn` (for a turn of a conversation), `standalone_question` (when the
question was rewritten), and from planner files `planner_version`, `planner_path`,
`loops_exhausted`, `planner_by` and `input_request` (`stopped_by: needs_input`).

### Using Ask SAJHA

The console's **Ask SAJHA** page (`/ask`, signed-in users; the first item of the AI menu)
is a chat over this endpoint. It is built from `sajha/web/templates/ai/ask.html`,
`sajha/web/static/js/ask.js` and `sajha/web/static/js/constellation.js` (the sky drawing it
shares with the landing page).

- **Asking.** Type a question and press Enter (Shift+Enter for a new line), or pick an
  example chip. The page keeps a conversation: the first question sends
  `conversation_id: "new"` and later ones the id the server returned, so a follow-up ("and
  from 100 to 150?") is answered with the earlier turns as context. The model picker sends `model`: admins see the factory's aliases
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

`sajha_ask` is an [LLM tool](LLM%20Tools.md) in mode `answer`, defined in
`config/tools/sajha_ask.json` (`question`, optional `model`, `conversation_id` and `confirm`;
conversation memory; every tool allowed). The file keeps it disabled; `ai.ask.mcp_tool_enabled:
true` turns it on, at start-up and after every reload of the catalog. The ask runs as the MCP
caller (the caller context of `sajha/observability/caller.py`): its user ID and roles, and only
the tools that caller may execute, narrowed further to the `ai.ask.mcp_allowed_tools` patterns
when they are set. `sajha_ask` never calls itself. Only when no entry point recorded a caller
(code that runs the tool directly) do its inner calls fall back to the anonymous MCP policy
(`mcp.anonymous.*`) plus `ai.ask.mcp_allowed_tools`
([Inner calls](../security/Security%20Model.md#inner-calls)). A signed-in caller gets a
`conversation_id` to continue the conversation; anonymous callers keep nothing.

## 7. The mock provider

`mock` needs no network and no keys and passes the same contract tests as the real
providers. It speaks the canonical format: its models return `ChatCompletion` objects and
stream `chat.completion.chunk` objects, so tests and the offline default exercise the shapes
real providers return. `mock-echo` replies with the last user message; `mock-scripted` plays a script
(ordered replies or regex rules; text, tool calls, JSON, refusals, errors) set in a test with
`set_script()` or loaded from `<scripts_dir>/<name>.yml` as `mock-scripted:<name>`;
`mock-planner` scores the offered tools against the question's keywords, calls the best
one or two with arguments filled from the schema (defaults, numbers near the parameter's
name, ticker symbols) and answers from the results, planning only from the question,
never from tool output; `mock-toolsmith` designs a tool for Studio's Describe a tool from
the description and the context it is sent ([Tool Generation](Tool%20Generation.md));
`mock-embed` hashes word n-grams into normalised vectors. Fault
injection (`latency_ms`, `fail_every`, `fail_with`, `seed`) exercises the governed model's
reliability paths. Calls are priced at zero but report token usage.

## 8. Tests

`tests/ai/`: a provider contract suite run against every provider family offline
(recorded-shape fake APIs on `httpx.MockTransport`; a fake boto3 client for Bedrock), with
live runs when a vendor key is present; golden translation tests
(`test_golden_translation.py`: canonical requests to each vendor's wire format, recorded
vendor replies and stream events back, against stored expectations in `tests/ai/golden/`);
a portability suite (`test_portability.py`: canonical requests through the mock and every
adapter, well-formed Chat Completions, declared capabilities honoured, native async);
`test_canonical.py` for the converters, the refusals, the behaviours that used to be silent,
the governed interface, Vertex AI and Entra ID credentials; factory tests for resolution, retries, fallback,
breaker, budgets, policy, cache, configuration precedence, registry loading, secrets and
the catalog methods; `tests/test_llm_boundary.py` for the package boundary and the abstract-class
contract of every registered provider; ask-loop tests over the real offline `calc_*` tools, including step
limits, confirmation, injected instructions in tool output, RBAC and the event order; and
the HTTP route in JSON and SSE. `tests/ai/test_planners.py` runs every built-in planner through
the same safety tests (RBAC, tools not offered, confirmation, limits, injection, event order)
and tests each strategy; `tests/ai/test_memory.py` covers multi-turn asks, summaries, privacy
between users, retention and the conversation routes, and `tests/ai/test_memory_tools.py` the
LLM-tool handle, scoping, expiry, folding, client history and the scheduled purge;
`tests/ai/test_rag.py` the chunking, the index, uploads, the stores and the search route,
`tests/ai/test_rag_store_contract.py` the store contract every shipped store passes (pgvector
when `SAJHA_TEST_POSTGRES_URL` names a PostgreSQL database), the registry and the index on
sqlite_vec, and `tests/ai/test_rag_documents.py` PDF and Word sources; `tests/ai/test_tool_index_sync.py` that a
tool registered by any path is shortlisted without a reload.

## 9. Not built yet

- Native async for Bedrock (boto3 is synchronous; it runs in a worker thread) and for
  embeddings (a worker thread).
- `reasoning_effort` on Bedrock (`additionalModelRequestFields` per model).
- Over MCP 2026-07-28, destructive-tool confirmation inside `sajha_ask` as a Multi
  Round-Trip Request (it is returned as `needs_confirmation` today).
- Freshness and agreement in the confidence score; trimming history on `ContextTooLong`.
- Document connectors (SharePoint, Drive, Confluence, or a connected account) as RAG sources;
  today a source is a folder in the storage backend, or an upload. No OCR for scanned PDFs.
