# SAJHA MCP Server — Changelog

Newest first. The current version is `app.version` in `config/application.yml`.

## Unreleased

Wave 4 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md), phase 4.1: stream A,
SAJHA Net membership ([SAJHA Net](docs/architecture/SAJHA%20Net.md) §5.5 says what is built), and
stream B, changes to existing code that SAJHA Net builds on (§21.1 items 2, 5, 6, 9, 12 and 13).

### Upgrading

- **Federated tool names:** a `.` in an upstream tool's name now becomes `_`
  (`v1.convert` is exposed as `<prefix>__v1_convert`), so the name is valid for every LLM
  provider. Update API-key allowlists or role patterns that named such a tool with its dot.
  Two upstream names that map to one exposed name are both refused (before, the first won).
- **Federated annotations** are corrected rather than copied: `openWorldHint` is always
  `true`, non-boolean hints and unknown keys are dropped, and `destructiveHint` is dropped for
  a read-only tool.
- **Federated schemas** must be valid JSON Schema (2020-12) object schemas: a tool whose
  `inputSchema` or `outputSchema` is not is listed as `invalid`, with the reason, and is not
  exposed.

### Added

- **SAJHA Net membership** (off by default, `sajhanet.enabled`): servers join named nets, several
  per server, kept apart on the normal port by the signed `Sajha-Net-Name` header. The protocol
  core is `sajha/net/` (it imports nothing else from SAJHA): names and qualified names, RFC 9421
  request and response signatures with RFC 9530 digests and replay protection in the state store,
  JSON Schemas of every `/sajhanet/v1/` message, RFC 8785 record signatures, the plug-in
  interfaces of the design with a registry, `package.module:Class` and the entry-point group
  `sajha.net.plugins`, and a contract check per interface. Membership is SWIM gossip (ping,
  ping-req, suspicion, refutation, dissemination, anti-entropy, leave, dead probing) with required
  seeds (`founder` exempt), restarts through the saved peer list (`peers.json`, local disk), and one
  gossip agent per net and instance through the renewing state-store lease. Names are configured or
  `<ip>:<port>`; a name belongs to its certificate lineage and a different key claiming it is
  refused with `409 name_conflict`, an error notice and the `sajha_net_name_conflict` metric. The
  CA is run by SAJHA, one per net: `sajha net ca init | enroll | revoke | show`, enrollment with
  single-use tokens refused for held names, renewal with a new key, a signed revocation list spread
  by gossip; manual mode pins self-signed certificates. Administrators add a peer by address
  (`/admin/sajhanet`, `POST /api/sajhanet/nets/{net}/peers`, `sajha net peers add`), optionally kept
  as a runtime seed. Notices for not joined, name conflicts, member state, certificates, renewal,
  stale revocation lists, peers added and plain HTTP. Keys: `sajhanet.*` in the
  [Configuration Reference](docs/getting-started/Configuration%20Reference.md#sajha-net); routes in
  the [API Reference](docs/protocol/API%20Reference.md) §4.24. No schema change.
- **SAJHA Net Protocol fixes** found while building it: a join sync to a seed or an operator-given
  address carries `Sajha-Net-To: *` (its name is not known yet); a renewed certificate carries the
  renewed serial in an extension so members can follow a name's lineage; the enrollment answer
  omits `"signature";req` (the request is unsigned) and is bound by the CSR's key; §8.9 says the
  emptied `_meta` objects stay; the §21.2 example covers `sajha-net-name`.
- **`io.sajha/net` on both eras:** with `sajhanet.enabled` the extension is advertised in
  `server/discover` (`capabilities.extensions`) and in the 2025-11-25 `initialize` result
  (`capabilities.experimental`), reduced for requests not signed by a participant; clients'
  declarations are read from either place (`sajha/core/net_extension.py`).
- **Federation `on_change: hold`:** per upstream, the previously approved version keeps
  serving while a changed definition waits for review (default `withdraw`, as before).
- **Schema validation of imported tools:** new status `invalid` on the federation page and in
  its API (`items[].reason`); approving such a tool is refused.
- **Cancellation reaches the upstream from the 2025-11-25 era:** `notifications/cancelled`
  cancels the named in-flight `tools/call` (HTTP with a session, and stdio), relayed between
  workers through a shared state store; a federated call then cancels its upstream request
  (`sajha/core/mcp_cancellation.py`). `is_cancelled()` reports it to any tool.
- **SAJHA Net peer URL guard:** `check_peer_url` and `sajhanet.allowed_networks` (CIDRs),
  separate from `federation.allow_private_networks`; loopback and link-local are never allowed.
- **Helm:** `sajhanet` values (nets, instance names, advertise addresses, Secrets for
  certificates and keys, allowed networks, NetworkPolicy rules); the chart refuses several pods
  with a net that has no instance name or advertise address.

## v7.3.0 (October 2026) — planners, authoring and the OpenAI endpoint

Wave 3 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md). Planning
strategies become configuration files with bounded loops; authors get an LLM tool creator, a
planner editor and per-creator permissions; SAJHA can serve any OpenAI-style client; every LLM
call in SAJHA goes through one package, one factory and one governed proxy.

### Upgrading from 7.2.0

- **Custom LLM providers:** `sajha/ai/gateway.py` and `sajha/ai/providers/` are gone. Build
  providers on `ProviderBase` from `sajha.ai.llm.spi`; application code uses
  `llm_factory().model(...)` only (enforced by `tests/test_llm_boundary.py`).
- **Planners:** the built-in names (`react`, `plan_execute`, `recipes`, `router`) now resolve to
  the shipped planner files in `config/planners/`, with the same behaviour; set
  `ai.planners.python_builtins: true` to keep the Python classes. LLM tools without
  `llm.planner` use `ai.planners.default`.
- **Studio permissions:** permissions per creator (`studio:<creator>`, `studio:*`); an existing
  `studio` permission still means every creator. New installs seed an `llm_author` role.
- **OpenAI-compatible endpoint:** off unless `ai.openai_api.enabled` is set.

### Added

- **Studio LLM tool creator** (`/studio/llm`, LLM Tools build step 10): a form for the `llm` block
  (mode, model alias, system prompt or library prompt, template, allowed and denied tools with a
  live matching preview, limits within the `ai.llm_tools.limits` ceilings, memory, planner and
  `planner_choices`, sampling, output, cache) with input and output schemas generated per mode;
  the config is checked by the loader's own rules (`parse_llm_block`, catalog and lint), run once
  on the mock model, and deployed or edited as `config/tools/<name>.json`.
  [Guide](docs/studio/MCP%20Studio%20LLM%20Tool%20Creator%20Guide.md).
- **Planner editor** (`/studio/planners`, administrators only): the registry's planners and the
  files it refused (with the last good version in use), a planner file checked as you type
  (JSON Schema and P-rules, each finding with its rule and location), a graph of stages and
  transitions with bounded edges marked, a dry run through `POST /api/ai/planners/dry-run` that
  highlights the stage path, and saving new versions (the replaced one kept as `name@version`).
  [Planner Reference §14.1](docs/architecture/Planner%20Reference.md#141-the-planner-editor).
- **Describe a tool proposes LLM tools** (kind `llm`): summarise, classify, extract, an assistant
  over named tools, or questions answered from document search; the `llm` block is checked by the
  LLM-tool loader, its tests run on the mock model, and it goes through the same review and
  deploy gate. [Tool Generation](docs/architecture/Tool%20Generation.md).
- **Conversations page** (`/conversations`, **AI → Ask**): a user's own conversations with Ask
  SAJHA and each LLM tool that remembers: open, continue in Ask (`/ask?conversation=<id>`),
  delete one or all. Administrators also see stored conversations per scope, counts only
  (`GET /api/ai/conversation-counts`).
- **Console end-to-end and accessibility checks** (Roadmap X15): `scripts/check_console.py` signs
  in, asks, builds and deploys an LLM tool, dry-runs a planner and opens the Conversations page in
  Chromium, then scans the pages with axe-core (WCAG 2.x A and AA) or a documented rule subset.
  Fixed what it found: the "About this page" guide link no longer sits inside its `<summary>`, the
  table's rows-per-page select has a label, scrollable regions on the new pages take focus.

- **SAJHA as an OpenAI-compatible endpoint** (opt-in, `ai.openai_api.enabled`):
  `POST /v1/chat/completions` (JSON or SSE chunks), `GET /v1/models`, `GET /v1/models/{model}` and
  `POST /v1/embeddings`, authenticated with a SAJHA API key as the bearer token. Calls run as the
  key's owner through the gateway (role policy, budgets, cache, fallback, usage and cost), the
  policy engine sees them as `openai_api.chat_completions` / `openai_api.embeddings` (source
  `openai_api`) so rules can rate-limit them, errors are OpenAI-shaped, and each enabled LLM tool
  the caller may run is the model `sajha:<tool>` (conversation handle in the `sajha` field).
  Tested with the official `openai` SDK. [LLM Tools §13.4](docs/architecture/LLM%20Tools.md#134-sajha-as-an-openai-compatible-endpoint).
- **MCP sampling for LLM tools:** `llm.sampling: prefer | require` on `complete`, `extract`,
  `classify` and `judge` tools sends the model call to a client that declared sampling: an MRTR
  input request on 2026-07-28, a server request on the session's SSE stream on 2025-11-25.
  Without one, `prefer` uses SAJHA's model and `require` refuses (`code: sampling_required`).
  Sampled calls cost SAJHA nothing (usage ledger provider `client`) and skip the result cache.
  [LLM Tools §12](docs/architecture/LLM%20Tools.md#12-models-sampling-budgets-and-limits).
- **Configurable planners** (LLM Tools build steps 4 and 5): a planner is a file,
  `config/planners/<name>.yaml`, a versioned graph of stages from a fixed library (`act`, `plan`,
  `execute`, `call`, `match`, `classify`, `draft`, `critique`, `revise`, `verify`, `sample`,
  `vote`, `foreach`, `planner`, `ask_user`, `condense`, `answer`, `fail`) with conditional and
  bounded transitions and a small `when` expression language. Files load with plain
  `yaml.safe_load`, are validated against rules P001–P071 and the JSON Schema of the Planner
  Reference, reload on change and keep their last good version when an edit fails. The service
  still enforces everything; planners only propose. Twelve strategies ship as files: the four
  built-ins (`react`, `plan_execute`, `recipes`, `router`, behaving as before) plus `rewoo`,
  `reflect`, `verify_then_answer`, `self_consistency`, `branch_and_judge`, `map_reduce`,
  `human_in_the_loop` and `auto` (a cheap classifier over the allowed planners that escalates
  once when a check fails). LLM tools take `llm.planner` as `name`, `name@version`, an inline
  definition or an overlay, and `llm.planner_choices` (an enum on an optional `planner`
  argument); resolution is version route, caller choice, tool config, `ai.planners.default`.
  `ask_user` asks over MRTR on 2026-07-28 and ends `needs_input` elsewhere; new `stopped_by`
  values `failed`, `needs_input` and `stage_limit`. Per-stage events on the ask stream (the Ask
  SAJHA page shows the path), metrics `sajha_planner_*`, the planner, version and stage path in the
  audit record, `kind: python` files and custom stage types registered in code, and an admin dry
  run on the mock model (`POST /api/ai/planners/dry-run`). Lint reports planner files.
  [Planner Reference](docs/architecture/Planner%20Reference.md), [Tutorial 27](docs/tutorials/TUTORIAL_27_write_a_planner.md).

### Changed

- **Studio permissions per creator, and ownership** (Roadmap X2). A role's `studio` permission now
  names the creator it opens (`studio:python`, `studio:rest`, `studio:api_import`, `studio:dbquery`,
  `studio:script`, `studio:powerbi`, `studio:powerbidax`, `studio:livelink`, `studio:sharepoint`,
  `studio:olap`, `studio:composite`, `studio:describe`, `studio:llm`); `studio:*`, which the
  existing `studio` rows already are, keeps opening all of them. The planner editor is admin only.
  A Describe a tool deploy also needs the permission of the kind deployed. Every Studio deploy
  records its creator (`metadata.created_by`; composites and API imports their `created_by`), and
  a non-admin may change or delete only what they created. The Studio menu shows only the
  creators a caller may use. New installs also get an `llm_author` role (`studio:llm`).
  [MCP Studio User Guide](docs/studio/MCP%20Studio%20User%20Guide.md#permissions).

- **One LLM package boundary** (wave 3, phase 3.2). Every LLM is reached through `sajha.ai.llm`
  behind OpenAI-style signatures, and all provider and model specifics live in `sajha/ai/llm/`,
  one module per provider. `LLMProvider` and `LLMModel` are abstract base classes every provider
  implements (the shared implementations are `ProviderBase`, `ChatModel`, `EmbeddingModel`).
  `llm_factory()` returns the `LLMFactory`, which builds providers from `ai.providers`,
  `ai.aliases` and the registry; `factory.model(alias)` returns a `GovernedModel` proxy that
  applies policy, budgets, cache, retries, breakers, fallback, audit, usage and tracing (the
  former gateway) before delegating to the provider's model; `factory.provider(name)` serves the
  admin pages. Every caller outside the package moved to the factory and the canonical types
  (memory, document search, embedders, the tool resolver, connectors, LLM tools, Describe a tool,
  the OpenAI-compatible endpoint, quality evals, the AI routes); `tests/test_llm_boundary.py`
  fails on a vendor SDK, a private module, direct construction or a pre-canonical type outside
  the package. [Intelligence Layer](docs/architecture/Intelligence%20Layer.md), [LLM Tools §13.7](docs/architecture/LLM%20Tools.md#137-one-package-boundary).
- LLM tools' derived `readOnlyHint` is false when a tool they may call cannot be found in the
  registry (it was treated as read-only).
- The `Planner` protocol (`sajha/ai/planners.py`) and `IntelligenceService` speak the canonical
  Chat Completions types: `PlanState.messages` are `ChatMessage`s, `ShortlistEntry.tool` is a
  `ToolDefinition`, `CallTools` carries `ToolCall`s (`ToolCall.of(id, name, arguments)`),
  `state.chat` takes a `ChatCompletionRequest` (`state.request(...)` builds one) and returns a
  `ChatCompletion`. A Python planner written against the old types needs those edits;
  `CallTools` still accepts objects with `id`, `name` and `arguments`.

### Upgrading

- **Studio permissions:** nothing to do; existing `studio` rows (`resource_name` `*`) keep opening
  every creator. To give a role one creator, add a `permissions` row (`studio`, `<creator>`, `use`).
  Studio tools deployed before this record no creator, so only administrators may change or
  delete them. The `llm_author` role is seeded on new databases only; add it to an existing one
  with the two rows in `db/scripts/<dialect>/seed.sql` if you want it.

- **Import paths for LLM code changed.** `sajha.ai.gateway` and `sajha.ai.providers` are gone:
  `get_gateway()` / `init_gateway()` / `build_gateway()` are `llm_factory()` /
  `init_llm_factory()` / `build_llm_factory()` in `sajha.ai.llm`, and a call is
  `llm_factory().model(alias).chat_completions_create(...)` (the factory also takes
  `model=` like an OpenAI client). The gateway's `complete`, `complete_messages` and
  `list_all_models` are removed (use `chat_completions_create` and `models()`). `sajha.ai.llm`
  no longer exports the pre-canonical types (`ChatRequest`, `Message`, `ToolSpec`, ...) or the
  registry helpers.
- **Custom providers:** subclass `ProviderBase` and import it, `ChatModel`, `EmbeddingModel`,
  `HTTPChatModel`, `register_provider`, `register_model`, `ModelCapabilities`, `ProviderConfig`
  and the HTTP helpers from `sajha.ai.llm.spi`. `sajha.ai.llm.LLMProvider` is now the abstract
  base class, so a class that subclassed it for its implementation must switch to
  `ProviderBase`; a class that leaves an abstract method unimplemented is refused at
  registration. Pre-6.x providers import `LegacyLLMProvider` (formerly
  `sajha.ai.providers.LLMProvider`) and `register_provider_class` from `sajha.ai.llm.spi`.
  Class paths in `ai.providers[].class` and entry points are unchanged.
- New configuration section `ai.openai_api` (`enabled: false`, `llm_tools`, `cookie_auth`,
  `max_body_bytes`). Nothing changes until it is turned on.
- The policy source list gains `openai_api`.
- New configuration section `ai.planners` (`dir`, `default`, `python_builtins`, `limits.*`, ...).
  `ai.ask.planner` and `ai.ask.planner_config` keep working: the names resolve to the shipped
  files, whose settings have the same keys and defaults. `ai.planners.python_builtins: true`
  runs the four built-ins' Python classes instead.
- An `answer`-mode LLM tool that names no `llm.planner` now runs `ai.planners.default` (`react`)
  rather than `ai.ask.planner`, as LLM Tools §9.12 specifies; `sajha_ask` still follows
  `ai.ask.planner`.
- The ask event stream gains `planner_chosen`, `stage_start`, `stage_end`, `loop_exhausted` and
  `expression_error` events; clients that switch on event types and ignore unknown ones are
  unaffected. The `AskResult` gains `planner_version`, `planner_path`, `loops_exhausted`,
  `planner_by` and `input_request`.

## v7.2.0 (October 2026) — the model interface and LLM tools

Wave 2 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md). SAJHA's model
interface becomes the OpenAI Chat Completions format end to end; LLM tools (tools whose work is
done by a model, configured like any tool) arrive with seven modes, per-tool memory and resource
safety; `sajha_ask` becomes one of them; document search gets a pluggable, disk-based store with
sqlite-vec as the default and reads PDF and Word.

### Upgrading from 7.1.0

- **Database:** `ai_conversations` gains `tool_name` and `expires_ts` plus two indexes.
  PostgreSQL: run what `python -m sajha.db upgrade-sql` prints. SQLite for development: recreate
  the database.
- **Document search store:** `ai.rag.store: auto` now means sqlite-vec (its own file,
  `data/rag/vectors.db`) when the `sqlite-vec` package loads, otherwise the in-memory store with a
  notice; it no longer picks pgvector by itself — set `ai.rag.store: pgvector` to keep using it.
  Install `sqlite-vec` (in `requirements.txt`). The index rebuilds itself on first start.
- **LLM tools:** the type is on; the shipped example tools are disabled; `sajha_ask` is now
  `config/tools/sajha_ask.json` and still switched by `ai.ask.mcp_tool_enabled`.
- **Optional packages:** `pypdf` and `python-docx` to index PDF and Word files.

### Upgrading

- **Database:** new columns `ai_conversations.tool_name` and `ai_conversations.expires_ts`, and
  indexes `ix_ai_conversations_user_tool_updated` and `ix_ai_conversations_expires`.
  PostgreSQL: run the statements `python -m sajha.db upgrade-sql` prints (SAJHA never runs DDL
  there). SQLite for development: recreate the database (the start-up check prints the
  statements if you prefer to add the columns).
- **Document search store:** `ai.rag.store: auto` (the default) now means the new sqlite_vec
  store (`data/rag/vectors.db`, created on first build; `pip install -r requirements.txt` brings
  `sqlite-vec`), else the memory store. It no longer picks pgvector by itself: a deployment that
  used pgvector sets `ai.rag.store: pgvector`.

### Document search: pluggable stores, sqlite-vec by default

- `ai.rag.store` chooses the store by configuration alone: `sqlite_vec`, `memory`, `pgvector`, a
  store registered through the new `sajha.rag.stores` entry-point group, or
  `package.module:Class`; per-store settings live under `ai.rag.stores.<name>` (env
  `SAJHA_AI_RAG_STORES_<STORE>_<KEY>`). The store contract (`VectorStore`, now with
  `keyword_search`, `create`, `probe` and `close`) has a contract test suite every shipped store
  passes (`tests/ai/test_rag_store_contract.py`; pgvector with `SAJHA_TEST_POSTGRES_URL`).
- New `sqlite_vec` store (`sajha/ai/rag/sqlite_vec.py`): a SQLite file of its own, never SAJHA's
  database, in WAL mode; sqlite-vec `vec0` for the vectors, FTS5 for the keywords, so both halves
  of the hybrid search run on disk and only the top k rows reach Python. The embedder and
  dimension are recorded: a new embedding model rebuilds the index cleanly. When the extension
  cannot load, `auto` uses the memory store and raises the System Notice `rag.store_fallback`
  with the reason.
- pgvector keyword search runs in PostgreSQL (full-text search) instead of an in-process BM25
  index over every row; the optional schema section shows a GIN index for it.
- Leaner indexing: documents are read one at a time and passages are embedded
  `ai.rag.embed_batch_size` (default 64) at a time while the store consumes them. The memory
  store keeps vectors as float32 arrays (about half the memory of before).
- Queries are embedded with the `query` purpose (passages keep `document`).
- `GET /api/ai/docs/status` adds `chunks`, `dimensions`, `store_configured` and `store_fallback`.

### LLM tools: the tool type, seven modes, resource safety; `sajha_ask` moved onto it

- **The LLM-tool type** (`sajha/ai/llm_tools/`, [LLM Tools](docs/architecture/LLM%20Tools.md)): a
  tool config with `implementation: sajha.ai.llm_tools.LLMTool` and an `llm` block is a tool whose
  work a model does. Modes `answer` (the intelligence service's planner loop over the allowed
  tools), `complete`, `extract` (output validated against the schema, one retry with the errors),
  `classify` (one enum label), `grounded` (answers only from document-search passages, with
  citations; `no_sources` when nothing is found), `narrate` (runs a composite or published
  workflow as the caller; the model writes the text) and `judge` (rubric scores, verdict computed
  by SAJHA). The loader refuses a block that cannot work and lint reports why (`llm-config`,
  `llm-catalog`, `llm-annotations`); annotations are derived from the tools the model may call.
- **Runs as the caller:** the model is offered the tool's `tools.allow − tools.deny` intersected
  with what the caller may execute; every inner call goes through the normal tool path. Nesting
  needs `nesting.allow`, is capped by `ai.llm_tools.max_depth` and shares the outer run's time and
  cost. Anonymous callers are refused unless `ai.llm_tools.anonymous.enabled`.
- **Conversation memory** per the tool's `memory` block (`conversation_id` in and out, or client
  history); **caching** of deterministic modes with `cache: true`.
- **Resource safety:** at most `ai.llm_tools.runtime.max_concurrent_runs` runs per process and a
  bounded queue, then `stopped_by: busy` (REST 503 with `Retry-After`); tool results larger than
  `spill_threshold_kb`, or past a run's `working_set_max_kb`, spill to `data/spool/llm_tools/<run>/`
  (deleted at run end; a janitor removes orphans); a memory guard (cgroup-aware) sheds caches and
  spills at the soft limit, refuses runs and ends running ones at their next step
  (`memory_pressure`) at the hard limit. System Notices `llm_tools.memory`, `llm_tools.busy`,
  `llm_tools.spool_full`; new `sajha_llm_tool_*` metrics ([Observability](docs/architecture/Observability.md)).
- **Results and errors** follow LLM Tools §15: error `stopped_by` values return `isError: true`
  over MCP and `success: false` over REST. Each run writes an `llm_tool_run` audit record with the
  trace id its inner `tool.call` records share.
- **Shipped examples, disabled:** `llm_markets_assistant`, `llm_summarise`, `llm_triage_ticket`,
  `llm_docs_qa`, with eval sets `config/evals/llm_*.yaml`; an eval set can now name an LLM tool
  (`tool:` and per-question `arguments`). The mock answers every mode offline.
- New `ai.llm_tools.*` settings (ceilings; [Configuration Reference](docs/getting-started/Configuration%20Reference.md)).
- [Tutorial 26: Build an LLM Tool](docs/tutorials/TUTORIAL_26_build_an_llm_tool.md).
- **Operator notes for `sajha_ask`:** it is now the LLM tool `config/tools/sajha_ask.json`
  (disabled in the file; `ai.ask.mcp_tool_enabled` still turns it on, at start-up and after each
  reload). It still runs as the caller and `ai.ask.mcp_allowed_tools` still narrows it. Its result
  adds `conversation_id` and `caveats`; pass `conversation_id` back to continue. Not built yet:
  configurable planners and sampling (wave 3).

### Conversation memory for LLM tools

- `ConversationMemory.open()`, `record()` and `from_client()` (`sajha/ai/memory.py`): the
  conversation handle of [LLM Tools](docs/architecture/LLM%20Tools.md) §10 (create when absent,
  continue when owned, `conversation not found` for an unknown, expired, another user's or another
  tool's id), per-tool scoping, idle expiry (`ttl_minutes`, renewed each turn), turns beyond
  `max_turns` folded into the summary and deleted, and `client` history mode. Anonymous callers
  get nothing stored.
- Questions are now clipped to `ai.memory.max_turn_chars` like answers, and a turn reads only the
  verbatim window instead of every turn of the conversation.
- A scheduled purge (`ai.llm_tools.memory.purge_interval_minutes`, default 15) runs on one worker
  per interval; it also enforces `ai.llm_tools.memory.max_conversations_per_tool` and can
  `VACUUM` SQLite (`sqlite_vacuum`). New metrics `sajha_llm_tool_conversations`,
  `sajha_llm_tool_turns_total`, `sajha_llm_tool_purged_total`.
- `GET /api/ai/conversations` takes `?tool=<name>` (or `*`); without it, it lists the Ask SAJHA
  page's conversations as before.

### Documents as RAG sources

- PDF and Word (`.docx`) files in `ai.rag.sources` folders and uploads, read through the
  optional packages `pypdf` and `python-docx` (commented in `requirements.txt`); without them
  those files are skipped and the index build names the package to install. Uploads take
  `content_base64` for them. A PDF or Word file is hashed on its bytes, so an unchanged one is
  not even extracted on re-index.

### The canonical model interface: OpenAI Chat Completions

Wave 2 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md), stream A:
[LLM Tools](docs/architecture/LLM%20Tools.md) §13 (except 13.4, the outward endpoint) and the
Roadmap's X9.

- **One format.** `sajha/ai/llm/canonical.py` types the Chat Completions request, response,
  stream chunk and embeddings shapes; SAJHA-only data rides in a `sajha` field (the caller's
  identity, cost, cache hit, fallback attempts, trace id, and the markers `ignored`,
  `usage_estimated`, `structured_output`). Fields are supported, passed through to
  OpenAI-compatible servers only, or refused with `invalid_request` naming the field, as §13.6
  settles.
- **OpenAI-style interfaces.** Models: `chat_completions_create`, `chat_completions_stream`,
  `achat_completions_create`, `achat_completions_stream`, `embeddings_create`, `info()`.
  Providers: `models()` (`ModelInfo`, today's `ModelCapabilities` extended with JSON mode, strict
  tools, named tool choice, parallel-call control, seed, stop sequences, reasoning effort, native
  `n` and variable embedding size) and `model(name)`. The gateway: the same methods plus
  `models(ctx)`, with policy, budgets, cache, retries, breakers and fallback as before. The
  original `chat` / `stream` / `achat` / `embed` and `generate` / `stream` / `embed` keep working
  through lossless converters (`sajha/ai/llm/convert.py`).
- **Adapters at the edge.** Every built-in provider translates the canonical format (OpenAI,
  Azure OpenAI, Mistral and the presets as a pass-through; Anthropic, Gemini, Bedrock, Cohere,
  Ollama natively), and the mock speaks it. New request fields: `developer` role, `top_p`,
  `seed`, `n`, `reasoning_effort`, per-request `parallel_tool_calls` and `strict`,
  `response_format: json_object`, `stream_options.include_usage`, `user` and `metadata` (audit
  only), and embeddings `dimensions`, `encoding_format: base64` and `sajha.input_purpose`.
- **Nothing dropped silently.** OpenAI's `refusal` is kept (refusals from every vendor become
  `finish_reason: content_filter` with `message.refusal`); a forced or named `tool_choice` on a
  model that cannot honour it (Ollama, catalogue flag `f`) is refused instead of becoming `auto`;
  Cohere takes a named choice only when it is the one tool offered; a temperature left out is
  named in `sajha.ignored`; a vendor's `error` finish (Gemini `MALFORMED_FUNCTION_CALL`, Cohere
  `ERROR`/`TIMEOUT`) raises the new `ModelFailed` and the gateway tries the next candidate;
  query embeddings use the query input type (Cohere `search_query`, Gemini `RETRIEVAL_QUERY`) —
  tool search and vector connectors pass it. A model with JSON mode but no schema output gets
  `json_schema` emulated (validated, one retry), marked `structured_output: "emulated"`.
- **Native async** for every HTTP provider (`httpx.AsyncClient` per event loop); the gateway's
  `achat_completions_create` / `achat_completions_stream` retry and fall back without threads.
- **Vertex AI** for Gemini and Claude (`platform: vertex`), and **Entra ID** for Azure OpenAI
  (`auth: entra`: client secret, AKS workload identity or managed identity), with tokens cached
  and refreshed before expiry (`sajha/ai/llm/cloud_auth.py`); new keys in the
  [Configuration Reference](docs/getting-started/Configuration%20Reference.md#aiproviders), and
  `ai.gateway.max_samples` caps `n`.
- **Tests.** Golden translation tests per provider against recorded vendor payloads
  (`tests/ai/test_golden_translation.py`, `tests/ai/golden/`), a portability suite through the
  mock and every adapter offline (`tests/ai/test_portability.py`), and `tests/ai/test_canonical.py`.
- **Extending.** [Extending the Intelligence Layer](docs/architecture/Extending%20the%20Intelligence%20Layer.md)
  is rewritten around the new interfaces; a provider over HTTP implements `wire`, `parse` and a
  `StreamTranslator` on `HTTPChatModel` and gets sync, streaming and native async I/O. The Acme
  example, the risk-model example and the recipe planner example moved to the canonical format.

## v7.1.0 (October 2026) — foundations

Wave 1 of the [Implementation Plan](docs/architecture/Implementation%20Plan.md): the groundwork
LLM tools and SAJHA Net build on, and the release hygiene the Roadmap listed as "Now". API keys
belong to users and every user has one; tools called from inside other tools run as the caller;
every tool call is in the tamper-evident audit chain; the console shows what needs attention;
sign-ins can be revoked; snapshots record users, keys and tools; the test suite runs in CI.

### Upgrading from 7.0.0

- **Database:** new columns `users.token_version` and, on `api_keys`, `is_default`, `persistent`,
  `created_by`, `rotated_at`, `revoked_at`, `revoked_by`, `secret_ciphertext`, `secret_key_id`.
  PostgreSQL: run the statements `python -m sajha.db upgrade-sql` prints (SAJHA never runs DDL
  there). SQLite for development: recreate the database; the start-up check prints the statements
  if you prefer to add the columns.
- **API keys:** existing keys keep working exactly as before until an administrator assigns them
  an owner; an owned key then signs in as its owner with the owner's roles, its own tool list as a
  ceiling. Every user gets a default key at start-up.
- **Files:** `config/users.json` is removed (users live only in the database).
  `config/apikeys.json` is now hashed persistent keys only and git-ignored; a plaintext file in
  the old format is ignored with a warning; see `config/apikeys.json.example`.
- **Audit volume:** every tool call is now an audit record (about 0.9 KB each); review
  `audit.tool_calls.*` sampling and your SIEM routing and retention.
- **Snapshots** are on by default (`snapshots.*`, every 10 minutes, last 20 kept, in
  `data/snapshots`).
- **Rate limiting:** the unused per-user and per-key limiters are removed; use policy
  `rate_limit` rules.
- **Federation cache:** federated tools cache per user by default
  (`cache.per_user_federated`).

### System notices

- **System notices**: one service (`sajha/notices/`) every subsystem reports conditions into,
  each under a stable id with a severity, an audience (`admin` or `everyone`) and a ttl. Notices
  live in the state store, so every worker sees the same set; every transition (raised,
  escalated, acknowledged, cleared) is an audit event; `notices.max_active` bounds them.
- **In the console**: a banner on every page (the most severe unacknowledged error or critical
  notice the viewer may see), a **System status** panel on the dashboard (grouped by severity,
  acknowledge for administrators, recently cleared on demand) and a navbar badge that also shows
  on phones; kept live by server-sent events.
- **API**: `GET /api/notices`, `GET /api/notices/stream`, `GET /api/admin/notices`,
  `POST /api/admin/notices/{id}/acknowledge` and `/clear`.
- **First sources**: the database schema check, open circuit breakers (tool providers, federated
  upstreams, LLM providers), workflows whose scheduled runs keep failing, LLM model aliases with
  no available model and failing providers, federated servers down and tools held for approval,
  and alert rules through the new `notice` channel. `notices.forward` also sends notices through
  the alert channels (log, webhook, email).
- Configuration: `notices.*` (enabled by default; nothing to do on upgrade). Guide:
  [System Notices](docs/architecture/System%20Notices.md).

### Audit, tracing, cache and leases

- **Every tool call is in the tamper-evident audit chain** as a `tool.call` record: caller, API
  key, roles and auth type, tool, outcome, duration, trace id, source surface (and MCP era), and
  a SHA-256 of the arguments, not their values (`audit.tool_calls.arguments: redacted` stores
  them with secrets and personal data masked; `none` stores neither). SIEM sinks receive the
  records like any other. Volume control: failures, policy outcomes and destructive tools are
  always recorded; successful calls can be filtered (`include_tools`, `exclude_tools`) and
  sampled (`success_sample_rate`, per-tool `sample_rates`); skipped calls are counted in
  `sajha_audit_tool_calls_skipped_total`. Design and as-built:
  [Policy and Audit §13](docs/architecture/Policy%20and%20Audit.md#13-tool-calls-in-the-audit-chain).
  The record is hashed on the calling thread and stored by a background flusher
  (`audit.chain.flush_interval_ms`, `flush_batch`), so the call does not wait for the database:
  about 38 µs per call measured on SQLite (about 120 µs if stored synchronously). Chain
  verification is unchanged and passes.
- **Outbound W3C `traceparent`** on the HTTP calls SAJHA makes: federated `tools/call`
  (`params._meta.traceparent`), API-import tools, REST-creator tools (newly generated), LLM
  providers, connected-account requests, HTTP vector-store connectors and webhooks. It works
  without the OpenTelemetry SDK: SAJHA continues an inbound context or starts one per request
  ([Observability §3.3](docs/architecture/Observability.md#33-outbound-trace-context)).
- **Per-user tool cache keys:** `"cache_per_user": true` in a tool's config adds the caller to
  the cache key. Federated tools default to it (`cache.per_user_federated: true`; an upstream's
  `cache_per_user` overrides it).
- **Renewing state-store lease:** `lease_claim`, `lease_renew`, `lease_release` and
  `lease_holder` on every state backend, and `sajha.core.state.lease.Lease`, which renews in the
  background and reports loss
  ([Scaling and State §4.7](docs/architecture/Scaling%20and%20State.md#47-leases)). The one-slot
  claims of workflow cron and quality probes are unchanged.

**Operator notes**
- **Audit volume grows.** Each tool call adds one `audit_chain` row (about 0.9 KB on SQLite),
  so a million calls a day is about 1 GB a day, and the same number of records goes to each SIEM
  sink. Before upgrading a busy server, decide on sampling or exclusions for high-volume
  read-only tools (`audit.tool_calls.*`), size SIEM sink `queue_size` for the call rate, and plan
  retention: SAJHA never deletes chain rows; remove whole old chains once they are safe in the
  SIEM (Policy and Audit §13.4). `audit.tool_calls.enabled: false` restores the old volume.
- Tool-call records not yet flushed when a process is killed are lost (at most one flush
  interval); verification then reports that chain as not closed, as for any crash.
- **Federated tools with `cache_ttl` now cache per calling user** (a lower hit rate when many
  users ask the same thing). Set `cache_per_user: false` on an upstream whose answers do not
  depend on the caller to share results as before.
- No schema change.

### Release hygiene and snapshots

- **The schema check prints the SQL to run.** When tables, columns or indexes are missing, the
  start-up message lists the statements taken from the dialect's `schema.sql`: `CREATE TABLE`
  (with its indexes), `ALTER TABLE ... ADD COLUMN` (PostgreSQL: `... IF NOT EXISTS`) and
  `CREATE INDEX`. Missing indexes alone only warn. With `db.schema_check: warn` the same SQL is
  in the `db.schema` system notice. SAJHA prints the statements; it never runs them. An older
  SQLite file whose tables break `schema.sql` as a whole still gets its missing tables (the
  statements are retried one by one). For a development SQLite database the advice stays:
  recreate it.
- **`python -m sajha.db upgrade-sql`** (also `sql --missing`) compares the configured database
  with its `schema.sql` and prints the DDL an operator reviews and runs; exit 3 when there is
  something to run ([Database Setup §4](docs/getting-started/Database%20Setup.md#4-upgrades)).
- **The test suite runs in CI** (`.github/workflows/tests.yml`): `tests` and `clientsdk/tests`
  on every push and pull request to develop and main, with a PostgreSQL service so the schema
  tests apply the real PostgreSQL file. `requirements-dev.txt` lists the test-only packages.
- **Snapshots of users, API keys and tools.** Every `snapshots.interval_minutes` (default 10)
  one worker writes a signed, chained JSON snapshot to `snapshots.dir` (default
  `data/snapshots`, owner-only, git-ignored) and keeps the last `snapshots.keep` (default 20):
  users without password hashes, roles, API key records (hashes only for persistent keys) and
  local tools with a hash of their schemas. Writes, rotations, failures and restores are audit
  records. `python -m sajha.snapshots list|verify|diff|show|restore`; `restore` re-creates
  missing roles, users (each with a new default key) and persistent key records after confirmation
  ([Policy and Audit §7.5](docs/architecture/Policy%20and%20Audit.md#75-snapshots-of-users-api-keys-and-tools)).

**Operator notes**
- **`config/users.json` is retired.** Nothing read it (users live in the database), but it was
  hot-reload watched and held a plaintext `admin123`. The watch, the `config.users.path` key and
  the unused users importer are gone; delete any copy you made from it.
- **One rate limiter.** The unused per-user and per-key limiters in `sajha/security.py`
  (`check_user_rate_limit`, `check_key_rate_limit`) were removed: they were never called, so no
  limit changes. Tool calls are limited only by policy `rate_limit` rules;
  `config/policies/00-default.yaml` now carries a commented per-user and per-API-key example
  ([Security Model](docs/security/Security%20Model.md#rate-limiting-and-lockout)).
- **Snapshots are on by default** and write a file every 10 minutes under `data/snapshots/`;
  `snapshots.enabled: false` turns them off. With several workers on `state.backend: memory`
  every worker writes its own; use `redis` or `database`.
- No schema change from this section.

### Identity and API keys

- **Tools called from tools run as the caller.** `sajha_ask` and composite steps now run their
  inner tool calls as the original caller, with no more than the caller's tool access: a step or
  inner call the caller may not execute is refused. The caller context
  (`sajha/observability/caller.py`) now carries the caller's tool access; a call chain
  (`sajha/core/inner_calls.py`) refuses cycles and chains deeper than `tools.max_call_depth`
  (default 8). `sajha_ask` no longer runs as the fixed identity `mcp:sajha_ask`.
- **API keys belong to users.** A key with an owner signs in as that user, with the user's
  roles (an administrator's key is an administrator); its tool access mode and list are an extra
  ceiling. Keys are created with an owner. Users manage their own keys on the new **My API keys**
  page (`/account/apikeys`, user menu): create, rotate, revoke, and **sign out everywhere**.
  Administrators manage every key on a rebuilt **API keys** page (`/admin/apikeys`, new key and
  key detail pages): owner, rotate, disable, revoke, persistent, delete; new JSON routes under
  `/api/account/apikeys` and `/api/admin/apikeys`. Key management needs a signed-in user, never
  an API key; browser requests carry a CSRF token.
- **Revocation record:** revoking a key sets `revoked_at` and `revoked_by`; the key never works
  again and the row stays.
- **A default key for every user**, created with the account and, at start-up, for every
  account without one. It can be rotated (by the user or an administrator) or disabled (by an
  administrator), never revoked or deleted. Its value is kept encrypted with the connected-accounts
  vault key (AES-256-GCM), so the server can act for the user with it later; the user sees it
  once after each rotation.
- **Persistent API keys:** keys an administrator marks persistent are also kept, as SHA-256
  records, in `config.apikeys.path` (default `config/apikeys.json`), which is checked after the
  database (the database wins for a key it knows), rewritten atomically with mode 0600 and
  re-read when it changes on disk. The format is in `config/apikeys.json.example`.
- **Revocable sign-in:** signing out (`GET /logout`, new `POST /api/auth/logout`) revokes that
  token (its `jti`, in the state store); every SAJHA JWT and built-in OAuth access token carries
  the user's token version (`tv`), so "sign out everywhere" (`POST /api/auth/sessions/revoke`), a
  password change (other sessions), an administrator's password reset and the new
  `POST /api/admin/users/{uid}/sessions/revoke` (Users page) end every session, and the user's
  OAuth refresh tokens stop refreshing.
- Configuration: `auth.api_keys.max_per_user` (default 25), `tools.max_call_depth` (default 8);
  `config.apikeys.path` is now the persistent key file. Guide:
  [Security Model](docs/security/Security%20Model.md#api-keys).

**Operator notes**
- **Database (both dialects): new columns.** PostgreSQL: run before starting this release
  (`python -m sajha.db upgrade-sql` prints the same):
  ```sql
  ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0;
  ALTER TABLE api_keys ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT FALSE;
  ALTER TABLE api_keys ADD COLUMN persistent BOOLEAN NOT NULL DEFAULT FALSE;
  ALTER TABLE api_keys ADD COLUMN created_by VARCHAR(100);
  ALTER TABLE api_keys ADD COLUMN rotated_at TIMESTAMPTZ;
  ALTER TABLE api_keys ADD COLUMN revoked_at TIMESTAMPTZ;
  ALTER TABLE api_keys ADD COLUMN revoked_by VARCHAR(100);
  ALTER TABLE api_keys ADD COLUMN secret_ciphertext TEXT;
  ALTER TABLE api_keys ADD COLUMN secret_key_id VARCHAR(64);
  ```
  An existing SQLite database needs the same columns (`BOOLEAN NOT NULL DEFAULT 0`, `TIMESTAMP`);
  start-up stops and prints the statements until they are added.
- **How existing API keys behave.** Every key that exists today has no owner, so it keeps
  exactly its current behaviour (identity `apikey:<name>`, role `api_consumer`, its own tool
  access mode) until an administrator assigns an owner on the API keys page, which lists and
  counts the keys without one. From then on the key signs in as that user, with the user's
  roles, its mode as a ceiling: check the owner's roles before assigning. Workflows owned by
  `apikey:<name>` keep running as that key; once the key is revoked they stop, as for a disabled one.
- **Default keys appear** for every existing account at the first start-up (they need the vault
  key: `accounts.vault.key`, `SAJHA_ACCOUNTS_VAULT_KEY`, a `key_provider`, or the key SAJHA
  generates into the server secrets file; several hosts must share it). Nobody has seen their
  values; users rotate a default key to get one.
- **`config/apikeys.json` is no longer tracked.** Its four plaintext demo keys were never read
  (and are not carried over); it is now git-ignored and holds only hashed records. An old
  plaintext file left in place is ignored with a warning and replaced on the first persistent-key
  change.
- **`ai.ask.mcp_allowed_tools` now narrows instead of widening** what `sajha_ask` may run for a
  caller: it can no longer give an anonymous MCP caller tools the anonymous policy does not.
- **Signing out now revokes the token.** With `state.backend: memory`, only the process that
  handled the sign-out knows; run `redis` or `database` with several workers. Tokens issued
  before the upgrade carry no token version and count as version 0, so nobody is signed out by
  the upgrade.

## v7.0.0 (October 2026) — governance, intelligence and operations

Everything since 6.0.0. It finishes the items 6.0.0 deferred (MCP
authorization with OAuth 2.1, MCP Apps, `x-mcp-header`), closes the security gaps a full audit
found, and adds what running a shared tool catalog for real needs: governance (policy engine,
tamper-evident audit, connected accounts), new ways to build tools (API import, Describe a tool,
data connectors, federation, workflows), tool quality, an intelligence layer with planners,
memory and document search, horizontal scale, observability, Kubernetes, and a console that
works on phones. The map of what owns what is
[How SAJHA Fits Together](docs/getting-started/How%20SAJHA%20Fits%20Together.md).

### Breaking changes and operator actions

Read this list before upgrading from 6.0.0.

**Database**
- **PostgreSQL: SAJHA never creates or alters tables.** Before starting this release, run
  `db/scripts/postgresql/schema.sql`, then `db/scripts/postgresql/seed.sql`, with `psql`
  (`python -m sajha.db sql --dialect postgresql` prints them). At start-up SAJHA checks every
  table and column it uses and refuses to start, naming what is missing and the command
  (`db.schema_check: strict`; `warn` starts anyway). 6.0.0's PostgreSQL scripts never worked, so
  there is nothing to migrate. Re-running `schema.sql` is safe (`CREATE ... IF NOT EXISTS`) and is
  how the tables this release adds are created ([Database Setup](docs/getting-started/Database%20Setup.md)).
- **SQLite database from 6.0.0:** new tables are created at start-up, but one column is new on an
  existing table and must be added by hand, or start-up stops at the schema check:
  `ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0;`
  (`python -m sajha.db check` lists anything else missing).
- New tables in both schema files: `sajha_state`, `sajha_state_events`, `obs_usage_events`,
  `connected_accounts`, `audit_chain`, `audit_anchors`, `ai_conversations`,
  `ai_conversation_turns`, `workflows`, `workflow_runs`, `workflow_run_steps`, `quality_runs`;
  the optional pgvector `rag_chunks` table is a commented section at the end of the PostgreSQL
  file. `db/scripts/*/001_schema.sql` and `002_seed.sql` are gone. The never-used tables
  `tenant_users`, `rate_limit_log`, `llm_usage` and `user_ai_preferences` are no longer created
  (existing ones are left alone).
- **`tool_versions` table removed** from both schema files and the ORM models: nothing ever read
  or wrote it (tool versions live in `config/tool_versions/*.yaml`). Existing databases may keep
  it; it is unused and can be dropped by hand (`DROP TABLE tool_versions;`). SAJHA never drops it.
- **Tenancy removed.** Tenant records were stored but never enforced (no request path consulted
  their tool patterns or quotas), so they are gone rather than half working: `sajha/core/tenancy.py`,
  the `TenantRecord` model, the `tenants` table in both schema files and the admin routes
  `GET`/`POST /api/tenants` and `GET`/`PUT`/`DELETE /api/tenants/{tenant_id}` (now 404). Roles,
  API-key tool access and policy rules separate teams
  ([Security Model](docs/security/Security%20Model.md#tool-access)). Existing databases may keep
  the `tenants` table; it is unused and can be dropped by hand (`DROP TABLE tenants;`). SAJHA
  never drops it.

**Secrets and sign-in**
- `config/application.yml` ships no JWT or session secret. Empty secrets are generated once into
  `data/secrets/server_secrets.json` (`auth.secrets_file`, mode 0600, git-ignored); JWTs signed
  with the old placeholder stop working, so users sign in again. A secret (or
  `mcp.mrtr.state_secret`) equal to any placeholder SAJHA ever shipped stops start-up; the MRTR
  secret derives from the persisted session secret, so `requestState` survives restarts. Several
  hosts must share the secrets file or set the variables, and share the OAuth signing key
  (`mcp.auth.builtin.signing_key_pem` for hosts without a shared data directory).
- The seed `admin`/`admin123`, admin-set passwords and default passwords are flagged
  `must_change_password` and show a banner until changed. `POST /api/admin/users/create` now
  requires a password that passes the policy (8+ characters, no well-known defaults).
- Sign-in: account lockout (423) and a per-IP failure limit (429) on the web form,
  `POST /api/auth/login` and the OAuth sign-in replace the old 5-per-minute limit on the JSON login.

**Who can see and run what**
- **Anonymous MCP and A2A callers see and run no registry tools, prompts or data resources by
  default.** List what they may use in `mcp.anonymous.tools`, `mcp.anonymous.prompts` and
  `mcp.anonymous.resources` (fnmatch), grant a role with `mcp.anonymous.role`, or refuse them with
  `mcp.anonymous.enabled: false`. The anonymous agent card has no skills.
- **Credentials that are sent but do not authenticate are rejected** (401 on `/mcp` and
  `POST /a2a`, close code 1008 on `/mcp/ws`) instead of running as anonymous, in every
  `mcp.auth.mode`. A stale web cookie alone still counts as no credentials.
- **The REST catalog and the REST mirrors of MCP methods need credentials:** `GET /api/tools/list`,
  `/api/tools/{tool}/schema`, `/api/tool-groups/*`, `GET /api/prompts/list`,
  `GET /api/prompts/{name}`, `POST /api/resources/list|read` and `POST /api/completion/complete`
  answer 401 where `/mcp` would, and list only what the caller may see.
- One tool-access policy (`sajha/auth/access.py`) for REST, MCP (both eras, SSE, WebSocket, stdio),
  A2A and async: API-key allowlist, denylist and regex modes are now enforced; external OAuth
  identities without an account get the role named `api_consumer` (none exists by default).
- Unauthenticated API/JSON requests (`/api`, `/mcp`, `/a2a`, `/admin/studio`, `/oauth`, any
  non-GET, or `Accept: application/json`) get a JSON 401 instead of a redirect; 403s there are JSON.
- Admin only now: `POST /api/logging/setLevel`, `GET /api/ws/sessions`, `GET /api/replay/recent`,
  `GET /api/replay/tool/{tool}`, `GET /api/reports/users/activity`, the tool configuration page and
  a tool schema page's resolved configuration; the shell endpoints need admin or `shell:execute`;
  MCP `logging/setLevel` changes the server log level only for admins.
- Async execution needs admin or `async:execute` plus tool access; file delivery only inside
  `async.delivery.file.base_dir`; webhooks only to `async.delivery.webhook.allowed_urls` (empty,
  the default, refuses every webhook).
- **MCP Studio is open to the `developer` role.** Every Studio page and endpoint (`/studio/*`,
  `/admin/studio/*` including Describe a tool and Import an API, `/api/studio/*`) and creating a
  composite now need the admin role or the `studio` permission (`require_studio`); the seeded
  `developer` role's `studio` row, never checked before, now grants it, and the navigation shows
  Studio to those users. Developers can deploy and delete Studio tools and deploy Describe a tool
  proposals through the same policy-engine gate (add a `studio.deploy` rule to narrow it); they see
  only their own Describe drafts and change or delete only composites they created. Admin only
  still: deploying Python code or script tools while `sandbox.enforce_for_generated_tools` is
  `false`, sandbox configuration, federation, connectors, policies, approvals, audit and users.
  Remove the `studio` row from `developer` (or the role from users) to keep Studio admin-only.

**Tools behave differently**
- **Tool arguments are validated against the tool's JSON Schema** before it runs: a mismatch is
  `-32602` on 2026-07-28, an `isError` result on 2025-11-25, 400 on `POST /api/tools/execute`.
- **Studio Python code tools and script tools run in the sandbox**, not in the server: no server
  environment, no network unless the tool's `sandbox` block allowlists hosts, a script's
  `working_directory` is ignored. `sandbox.enforce_for_generated_tools: false` restores in-process
  loading.
- **OLAP tools** accept only dimensions and measures declared on the dataset in
  `config/olap/datasets.json` (raw column names are refused); each OLAP tool runs only its own
  operation (`_tool_name` is refused).
- **`duckdb_*` tools** run one parser-checked `SELECT`/`EXPLAIN` on in-memory copies of the data
  files with external access off; table and column names must exist; `having` is
  `<name> <op> <value>` conditions; `duckdb_analytics.db` is no longer written.
- **FBI tools** call the current Crime Data Explorer API with new input and output schemas
  (`fbi_search_agencies` needs `state`). **FRED** tools return the newest observations first.

**Configuration and removals**
- Storage environment variables (`SAJHA_STORAGE_BACKEND`, `SAJHA_S3_BUCKET`,
  `AZURE_STORAGE_CONNECTION_STRING`, ...) now override `application.yml`. `.env` names that are
  not settings no longer stop start-up. `async.*` and `shell.*` keys now take effect.
- Several workers on `state.backend: memory` get a start-up warning: shared state needs `redis`
  or `database` ([Scaling and State](docs/architecture/Scaling%20and%20State.md)).
- Removed: the top-level `oauth:` block in `config/application.yml` (never read; MCP authorization
  is `mcp.auth`), `sajha/core/auth_manager.py` and `sajha/core/apikey_manager.py`, the legacy SSE
  `Last-Event-ID` replay, a second unreachable `GET /health`.

### Protocol and clients

- **OAuth 2.1 for `/mcp`** (`mcp.auth.mode`: `off`, the default, `optional` or `required`).
  Resource server: RFC 9728 protected-resource metadata, `WWW-Authenticate` with
  `resource_metadata` and `scope`, audience-bound RS256 access tokens, scopes `mcp:read` /
  `mcp:tools`. Authorization server built in (SAJHA users; authorization code + PKCE S256, RFC 9207
  `iss`, Client ID Metadata Documents with SSRF guards, rotating refresh tokens with reuse
  detection, CSRF-protected consent) or an external issuer through its JWKS. API keys and SAJHA
  JWTs keep working in every mode; the signing key is generated under `data/oauth/`. Conformance
  `authorization` suite 3/3 for both spec versions; the server suites unchanged (43/43, 152/152);
  the official SDK completes the flow end to end. [OAuth Guide](docs/protocol/OAuth%20Guide.md).
- **MCP Apps** (`io.modelcontextprotocol/ui`): tools bind `ui://` views served by `resources/read`
  as `text/html;profile=mcp-app` (`mcp.apps.enabled`, default on); example view for
  `calc_loan_amortization`. **`x-mcp-header`** is validated when a schema loads (invalid
  annotations dropped with a warning); `Mcp-Param-Symbol` on the quote tools.
  [MCP Apps and Headers Guide](docs/protocol/MCP%20Apps%20and%20Headers%20Guide.md),
  [MCP 2026-07-28 Compliance §4](docs/protocol/MCP%202026-07-28%20Compliance.md).
- **MCP over stdio** (`sajha/cli/stdio.py`; `python run_server.py --stdio`, `sajha serve --stdio`)
  for Claude Desktop, Claude Code and IDEs: both eras on one connection, nothing but protocol on
  stdout, `notifications/cancelled` honoured, `list_changed` pushed; one caller per process
  (`--user` / `SAJHA_STDIO_USER`, `--api-key` / `SAJHA_API_KEY`, else anonymous); the LLM gateway
  only with `--with-ai`. Tested with the official SDK client in `legacy` and `auto` modes.
- **The `sajha` command line** (`pip install './clientsdk[cli]'`): `login` (token stored 0600 in
  `~/.config/sajha`), profiles, `tools list|show|call`, `prompts list|get`, a streamed `ask`,
  `studio deploy|delete|import-openapi|describe`, `federation list|add|refresh|remove`,
  `workflows list|run|runs|show`, `db check|sql`, `health`, `config show`, `completion`, `serve`;
  exit codes 0-6. [Command Line](docs/clients/Command%20Line.md),
  [Tutorial 15](docs/tutorials/TUTORIAL_15_sajha_cli_and_claude_desktop.md).
- **Per-era argument validation** is stated in the MCP Protocol Guide ("Argument validation").

### Security fixes

Each is described with its code location in [Security Model §4](docs/security/Security%20Model.md#4-fixes-since-600).
- **SQL injection in the OLAP tools** (pivot, rollup, window, time series, statistics, cohort,
  `olap_top_n`, `olap_contribution`, `customer_olap_pivot`, `OLAPQueryBuilder`): filter values and
  dates are bound parameters, names resolve only through the dataset's declarations, operators,
  aggregations, directions, time grains and numbers are allowlisted or coerced
  (`sajha/olap/sql_safety.py`). `sales_analysis` and `financial_metrics` declare the columns the
  shipped examples use.
- **`duckdb_sql`** ran every statement after a `SELECT` and could read any file or URL; the other
  `duckdb_*` tools pasted table and column names (and `having`) into SQL. All now run on locked,
  in-memory sandboxes (see Breaking changes).
- **Catalog visibility:** prompts, the `sajha://tools/catalog` and `sajha://prompts/catalog`
  resources, `completion/complete`, the MCP `tool/schema`-style methods, the A2A agent card, the
  REST catalog, the console's tool pages and the tool names on public pages follow the caller's
  access; `sajha://data/*` resources follow `mcp.anonymous.resources`; `tool/description` no longer
  fails with an internal error.
- **Invalid credentials** ran as anonymous on MCP and A2A; **A2A** ran tools anonymously and showed
  every task (tasks are now visible only to their creator).
- **Async execution** wrote to any path and posted to any URL (now the CIMD SSRF guard and the
  allow-lists).
- Enabling or disabling a tool wrote its resolved configuration, API keys included, back to its
  config file (now only `enabled` changes); a tool's schema page showed that configuration to every
  signed-in user.
- `/login?next=` open redirect; path traversal in `sajha://data` resources; WebSocket
  authentication called a method that did not exist (an invalid token now closes the connection
  with 1008); security headers overwrote stricter per-route values.
- `sajha/auth/password.py` raised `NameError` on an invalid hash; an API key with an expiry date
  failed on SQLite (naive and aware datetimes compared).
- nginx (`deployment/baremetal/nginx.conf`) proxies `/mcp`, `/api/mcp` and `POST /api/ai/ask`
  unbuffered; compose files no longer pass placeholder secrets.

### Governance

- **Policy engine** (`sajha/policy/`): declarative rules (YAML or JSON in `config/policies/`,
  through the storage backend, hot-reloaded) evaluated in `BaseMCPTool.execute_with_tracking`, the
  one place MCP (both eras, stdio, WebSocket), REST, the playground bridge, A2A, Ask SAJHA, async
  tasks, workflows and federated tools run a tool; composite steps too. Matches on tool globs,
  groups, annotations, caller, source, time window and argument values. Effects `allow`, `deny`,
  `require_approval`; argument constraints; rate limits and calendar quotas in the state store;
  output redaction (emails, phone numbers, Luhn-valid cards, US SSN, UK NINO, Aadhaar, PAN,
  Canadian SIN, custom regexes); prompt-injection screening of results (`flag`, `strip`, `block`).
  Deny-overrides; `policy.default_effect: deny` is an allowlist mode. REST answers 403, 202
  (approval pending) or 429 with `Retry-After`; MCP a tool error with `_meta["io.sajha/policy"]`.
  Default unchanged: the shipped `00-default.yaml` has no rules and the two examples are disabled.
- **Approvals:** `approver: caller` asks the user (an MRTR form on 2026-07-28 clients with
  elicitation; Confirm in Ask SAJHA); `approver: admin` queues the call on the **Approvals** page
  (`/admin/approvals`); an approved call runs once for the same caller; no self-approval by
  default; optional webhook or Slack notification. **Policies** page (`/admin/policies`) with a test
  bench. Metrics `sajha_policy_decisions_total`, `sajha_policy_redactions_total`,
  `sajha_policy_output_flags_total`; every non-allow decision is audited.
- **Tamper-evident audit** (`sajha/audit/`): every audit record and policy decision is hash-chained
  (one chain per process), anchored every `audit.chain.anchor_every` records, every
  `anchor_interval_seconds` and at shutdown with an RS256 signature from the OAuth key (public
  half at `/oauth/jwks`). `python -m sajha.audit verify` and the **Audit** page (`/admin/audit`)
  detect edited, deleted, inserted or reordered records, rewritten tails and truncation.
  `audit_log` is still written for the existing audit API.
- **SIEM export** (`audit.export.sinks`): syslog (RFC 5424, TCP or TLS), HTTP (Splunk HEC, Datadog,
  generic; SSRF-guarded) and rotated JSON Lines files, as JSON, CEF or OCSF-style JSON; batched,
  retried, bounded queues with counted drops (`sajha_audit_export_total`).
  [Policy and Audit](docs/architecture/Policy%20and%20Audit.md),
  [Tutorial 20](docs/tutorials/TUTORIAL_20_policies_approvals_and_audit.md).
- **Connected accounts** (`sajha/accounts/`): users link their own account at a third-party service
  once on `/account/connections` (OAuth 2.0 authorization code, PKCE S256 where supported, exact
  redirect URI, single-use `state` bound to the user and browser, CSRF-protected Connect and
  Disconnect; Disconnect revokes where the provider can). Provider templates `github`, `slack`,
  `google`, `microsoft`, `atlassian`, `notion` (or any OAuth 2.0 service) under
  `accounts.providers`, each limited to its `api_hosts`. Token vault: AES-256-GCM in
  `connected_accounts`, key from `SAJHA_ACCOUNTS_VAULT_KEY` or the secrets file, rotation with
  `accounts.vault.previous_keys`, a KMS hook; refresh one worker at a time. A tool config's
  `"auth": {"connected_account": ...}` runs every call with the caller's token, never cached; new
  tools `github_list_my_repos`, `github_create_issue`, `slack_post_message`, `google_drive_search`,
  `ms365_list_my_events`, `connected_http_request`, listed only while their provider is configured.
  "Connect your account": an MRTR URL elicitation (2026-07-28), `-32042` (2025-11-25), a tool error
  with the URL, 428 on REST, a **Connect** card in Ask SAJHA. Federated upstreams can receive each
  caller's own token. `/admin/connections` shows who linked what (never a token).
  [Connected Accounts](docs/architecture/Connected%20Accounts.md),
  [Tutorial 18](docs/tutorials/TUTORIAL_18_connect_your_accounts.md).

### Building and composing tools

- **Sandboxed user code** (`sajha/sandbox/`): Studio Python code tools, script tools and the admin
  shell run per call in a sandbox with no server environment (secrets only by name through
  `sandbox.secrets_allowlist`), a temp work dir, CPU/memory/file/process/output/time limits and no
  network unless allowlisted. Backends (`sandbox.default_backend`): `subprocess` (default; on Linux
  user/PID/network namespaces, rlimits, Landlock and seccomp, each reported), `bwrap`, `nsjail`,
  `docker` (`runtime: runsc` for gVisor), `auto`. `GET /api/sandbox/status`, `sandbox` in
  `GET /health`; the creator pages show the policy a new tool gets. Built-in tools and Studio's
  template creators stay in-process. [Sandbox](docs/architecture/Sandbox.md),
  [Tutorial 14](docs/tutorials/TUTORIAL_14_sandboxed_studio_tools.md).
- **Federation** (off by default; `sajha/federation/`): other MCP servers' tools (and optionally
  prompts and resources) as registry tools named `<prefix>__<tool>`, under the same access policy,
  cache, one circuit breaker and rate-limit window per upstream, metrics and usage events.
  Upstreams over Streamable HTTP (either era), legacy SSE or stdio (`federation.allow_stdio`, off);
  credentials by secret reference. Discovery at start-up, periodically, on change notifications
  and on demand; results, progress, cancellation and MRTR pass through. Approval before exposure
  and on change, injection screening, SSRF guard, admin page `/admin/federation`.
  [Federation](docs/architecture/Federation.md), [Tutorial 11](docs/tutorials/TUTORIAL_11_federate_an_mcp_server.md).
- **API Import** (`sajha/api_import/`, Studio → Import an API, `/studio/api-import`): an OpenAPI
  3.x or Swagger 2.0 spec (URL, upload or paste) or a GraphQL endpoint becomes a preview of every
  operation with generated names, JSON Schema 2020-12 input and output (`$ref` inlined, cycles
  cut), annotations and flags; credentials as secret references (API key, bearer, basic, OAuth 2.0
  client credentials, the caller's connected account); test-call; deploy the selection, live at
  once. One generic executor, no generated code; SSRF guard on every fetch and call; a re-import
  shows a diff (`config/api_imports/<api_id>.json`). CLI `sajha studio import-openapi`.
  [API Import](docs/architecture/API%20Import.md), [Tutorial 19](docs/tutorials/TUTORIAL_19_import_an_openapi_spec.md).
- **Describe a tool** (`/studio/describe`, `sajha studio describe "<text>"`): the model behind the
  new `toolsmith` alias proposes a tool (`python`, `rest`, `dbquery`, `composite` or `openapi`)
  with schemas, implementation and test cases. The proposal is checked as untrusted input (SQL
  read-only and on listed tables, SSRF host checks, no generated credentials, risky imports and
  unmentioned hosts flagged), rendered into the files Studio's generators write, and bound to a
  SHA-256. Tests run before deploy (Python in the sandbox, REST against fixtures, DB queries on
  the listed database); a deploy needs `approve: true`, the reviewed hash, tests on that hash and
  the policy engine's consent to `studio.deploy`. Generated Python tools are always sandboxed; the
  cases become the tool's `tests`. Works offline with `mock-toolsmith`. New keys `studio.describe.*`.
  [Tool Generation](docs/architecture/Tool%20Generation.md), [Tutorial 24](docs/tutorials/TUTORIAL_24_describe_a_tool.md).
- **Data connectors** (`sajha/connectors/`, the **Data Connectors** page `/admin/connectors`):
  PostgreSQL, Redshift, MySQL/MariaDB, SQL Server, Oracle, Snowflake, BigQuery, Databricks SQL,
  SQLite and DuckDB files; pgvector, Qdrant, Elasticsearch/OpenSearch. One record per connection at
  `config/connectors/<id>.json` with secret references only. Generated tools
  `<id>__list_tables`, `__describe_table`, `__query` (one read-only SELECT with bound `:name`
  parameters), curated views as typed tools, and `__search` / `__list_collections` /
  `__describe_collection` for vector and search kinds. Read-only behind three walls (the statement
  guard, a read-only session where the database has one, the login's privileges); row, byte and
  time limits; column masking (`hide`, `null`, `redact`, `hash`, `partial`, `pii`); per-user
  credentials for Snowflake, BigQuery and Databricks through connected accounts; audit records
  `connector.query` / `connector.rejected` and metrics. No connection ships.
  [Data Connectors](docs/architecture/Data%20Connectors.md),
  [Data Connectors Reference Guide](docs/tools/enterprise/Data%20Connectors%20Reference%20Guide.md),
  [Tutorial 25](docs/tutorials/TUTORIAL_25_connect_a_database.md).
- **Workflows** (`sajha/workflows/`, the **Workflows** page `/workflows`): DAGs of `tool`,
  `composite`, `ask`, `condition`, `foreach`, `wait` and `approval` steps with `$steps.<id>`
  mapping, joins, retries, timeouts. Triggers: timezone-aware cron (one fire per slot across
  workers), HMAC-signed webhooks (`POST /api/workflows/{name}/hooks/{trigger}`), file arrival on
  the storage backend, change-bus events, manual runs with `Idempotency-Key`. Durable runs: every
  step stored, another worker resumes a run whose worker died, waits and approvals park the run,
  cancel, re-run from a failed step, concurrency limits, delivery through the async router. Steps
  run as the owner, under policy (source `workflow`), audited. Administrators can publish a
  workflow as a tool. New keys `workflows.*`.
  [Workflows](docs/architecture/Workflows.md), [Tutorial 22](docs/tutorials/TUTORIAL_22_schedule_a_workflow.md).
- **Tool quality** (`sajha/quality/`): a test harness (`python -m sajha.quality test`; cases in
  `config/tool_tests/*.yaml` or a tool's `tests`; JSON Schema and JSONPath assertions, latency
  budgets; text, JSON and JUnit output) with HTTP cassettes that record once and replay offline;
  a schema linter (`lint`); opt-in health probes on intervals or cron (`quality.probes.enabled`),
  **Tool Health** page; evals for Ask SAJHA (`config/evals/*.yaml`, `eval|compare|runs`;
  tool-selection and answer accuracy, steps, tokens, cost, latency), **Evals** page; tool versions
  (`config/tool_versions/<tool>.yaml`) routed per call by API-key pin, user, role, sticky canary
  percentage, then stable, with automatic rollback shared through the state store and sunset
  dates, **Tool Versions** page. `GET /api/tool-versions` and
  `POST /api/tool-versions/{tool}/deprecate`, placeholders until now, read and write the versions
  files. Probes are off and no tool has a versions file by default.
  [Tool Quality](docs/architecture/Tool%20Quality.md), [Tutorial 23](docs/tutorials/TUTORIAL_23_test_and_canary_your_tools.md).

### Intelligence layer

- **Ask SAJHA** (`/ask`): a chat over `POST /api/ai/ask` that streams each step (shortlist, tool
  calls and results, answer, confidence), shows the tool chain as expandable chips, asks before a
  destructive call and draws the chain on the tool sky; model picker, a *Mock model active* pill,
  Stop. [Tutorial 10](docs/tutorials/TUTORIAL_10_ask_sajha.md).
- **Planners** (`ai.ask.planner`): `react` (the previous loop, default), `plan_execute` (one
  planning call, independent steps in parallel, one re-plan), `recipes` and `router`; register more
  with `@register_planner`, a class path or a `sajha.planners` entry point. The service keeps RBAC,
  confirmation, limits, synthesis, confidence, audit and the event schema. New `plan` event;
  `GET /api/ai/planners`.
- **Conversation memory:** an ask with `conversation_id` gets recent turns, a summary of older
  ones and a standalone rewrite of its question; per user, `ai.memory.retention_days` and a
  per-user cap; `GET`/`DELETE /api/ai/conversations[/{id}]`. Ask SAJHA keeps a conversation.
- **Document search (RAG):** the `sajha_search_docs` tool and the help page's **Ask the docs** box
  search SAJHA's own guides, `ai.rag.sources` folders and admin uploads (`/api/ai/docs/*`), with
  citations; vector and BM25 rankings fused; an in-process store by default, pgvector when
  available.
- **Tools reach Ask SAJHA at once:** `ToolsRegistry.add_change_listener` fires on every register,
  unregister, enable and disable, so tools from Studio, composites, federation, API import,
  connectors or the file watcher are searchable without a reload.
- [Extending the Intelligence Layer](docs/architecture/Extending%20the%20Intelligence%20Layer.md):
  a provider, a model and a planner, with tested examples in `sajha/examples/intelligence/`.
  [Intelligence Layer](docs/architecture/Intelligence%20Layer.md),
  [Tutorial 21](docs/tutorials/TUTORIAL_21_planners_memory_and_rag.md).

### Operations

- **Several workers and hosts** (`state.backend`: `memory`, the default, `redis` or `database`;
  `sajha/core/state/`): OAuth consents, codes, refresh tokens and DCR clients, 2025-11-25 sessions
  (relayed to the worker holding the stream), legacy SSE queues, 2026-07-28 task records, rate
  limits, the sign-in throttle, LLM budgets and async task records are shared; change-bus events
  reach subscribers on every worker. Durable MCP tasks (`state.tasks.durable: auto`) survive a
  restart. `GET /health` has a `state` object; `run_server.py --workers N`. Conformance unchanged
  (43/43 for 2025-11-25 with 0.1.16, 152/152 for 2026-07-28 with 0.2.0-alpha.12) on the memory,
  redis and database backends. [Scaling and State](docs/architecture/Scaling%20and%20State.md),
  [Tutorial 13](docs/tutorials/TUTORIAL_13_run_sajha_on_several_workers.md).
- **Observability:** `GET /metrics` in the Prometheus text format (HTTP, MCP, tool, LLM, ask, auth,
  sandbox, federation, process metrics; `observability.metrics.auth`, admin by default; optional
  separate listener; cardinality caps; merged across workers); OpenTelemetry traces and metrics
  over OTLP (opt-in) with `traceparent` continued from HTTP and MCP `_meta`; the **Usage & cost**
  page (`/monitoring/usage`) on a usage ledger; alert rules to a log, an allow-listed webhook or
  email; Prometheus rules and a Grafana dashboard in `deployment/observability/`. `/api/metrics`
  and `/api/metrics/tools`, always empty before, are fed.
  [Observability](docs/architecture/Observability.md), [Tutorial 16](docs/tutorials/TUTORIAL_16_metrics_costs_and_alerts.md).
- **Database:** one schema file per database (`db/scripts/<dialect>/schema.sql` + `seed.sql`),
  no migrations, `tests/test_db_schema.py` keeps both in step with every model; the start-up
  check; the helper `python -m sajha.db check|sql`. 6.0.0's PostgreSQL scripts failed on every
  statement and its runner hid it; SQLite's `prompt_tags` was never created.
  [Database Setup](docs/getting-started/Database%20Setup.md).
- **Kubernetes:** a root `Dockerfile` (multi-stage, UID 10001 under `tini`, read-only-root ready;
  build args `EXTRAS`, `WITH_OPENBB`, `PLAYGROUND_ASSETS`), the Helm chart `charts/sajha` (seed
  init container, streaming Ingress, HPA, PDB, optional Redis, NetworkPolicies, ServiceMonitor,
  one shared Secret, refusal of settings that would split state) and Kustomize overlays rendered
  from it. Verified on kind: three pods on Redis and PostgreSQL passed 43/43 (2025-11-25, 0.1.16),
  152/152 (2026-07-28, 0.2.0-alpha.12) and the tasks-extension scenarios (44/44).
  [Kubernetes Deployment](docs/getting-started/Kubernetes%20Deployment.md),
  [Tutorial 17](docs/tutorials/TUTORIAL_17_deploy_sajha_on_kubernetes.md).
- **Deployment recipes:** the AWS CDK stack creates and passes the JWT and session secrets (and
  optionally the OAuth signing key), sets `SAJHA_STATE_BACKEND=database` and synthesizes again;
  its Dockerfile and compose file build from the repository root. The Hetzner and local AWS
  compose files have a `scale` profile with Redis, and the Hetzner one passes the session secret
  (`SESSION_SECRET`). Bare metal: `sajha.service`
  makes `logs/`, `temp/` and `sajha/tools/impl/` writable. Each recipe prints the PostgreSQL schema
  step.
- Start-up is faster; loading N tools publishes at most one change event instead of 3·N.

### Web console

- **Phones and tablets:** no sideways page scroll at 375, 390 or 768px (wide tables scroll in their
  own box, user and API-key lists become cards), a hamburger menu with an accordion, 40px touch
  targets, 16px inputs, 12px minimum text, a "Contents" disclosure on guides, readable charts.
  `scripts/check_mobile.py` checks every page; `tests/test_mobile_layout.py` keeps its routes live.
  [Architecture §10](docs/architecture/Architecture.md).
- **Python Playground** (`/playground`): Python in the browser with Pyodide (cells, CodeMirror,
  pandas tables, matplotlib inline, `.py`/`.ipynb` upload), `import sajha` to call tools and ask
  with the user's session, vendored assets checked against published hashes
  (`scripts/fetch_pyodide.py`) or the CDN; COOP/COEP and a `'wasm-unsafe-eval'` CSP on that route
  only. [Python Playground](docs/getting-started/Python%20Playground.md),
  [Tutorial 12](docs/tutorials/TUTORIAL_12_python_playground.md).
- **How SAJHA compares** (`/comparison`): SAJHA next to MCP frameworks, gateways and hosted
  platforms, each cell a verdict with a note, a source and a date; one data module,
  `sajha/web/competitive.py`, checked by `tests/test_competitive.py`.
- New admin pages: Approvals, Policies, Audit, Connections, Data Connectors, Federation, Tool
  Health, Tool Versions, Evals; new user pages: Connected accounts, Workflows, change password.
- Fixed: a table with both `data-enhance` and automatic controls got two search bars and pagers;
  the user and API-key tables had broken `class` attributes; landing-page counts come from the
  running server; star tooltips and a regex filter on the tool sky; guide pages render without the
  `markdown` package.

### Tools

- **FBI tools rewritten** for the current Crime Data Explorer API (every call returned 404): all
  nine `fbi_` tools keep their names (config `version` 3.0.0); key and rate-limit errors name
  `FBI_API_KEY`; per-tool `timeout`. [FBI Tool Reference Guide](docs/tools/public-data/FBI%20Tool%20Reference%20Guide.md).
- **FRED:** every `fred_*` tool, `fed_get_latest` and `fed_get_common_indicators` returned the
  oldest observations; they ask for the newest first and skip missing values.
- **OLAP datasets:** `customer_olap` failed on every query, `customer_analytics` and
  `inventory_analysis` lacked their data (`customer_data`, `inventory_data` added); a dataset's own
  dimension or measure wins over the shared definition; filters on a joined dataset apply over the
  joined row; weighted pivot totals; saving `datasets.json` keeps `${data.duckdb.dir}`.
  [OLAP Analytics Tool Reference Guide](docs/tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md).
- **SharePoint tools** use Microsoft Graph throughout; new `sharepoint.*` and `azure.tenant.id`
  keys from the environment; unconfigured tools say so; the Studio creator writes a valid schema
  and appears in the menu.
- Schema fixes so valid calls pass validation: Yahoo symbols (`BRK-A`, `BTC-USD`, `7203.T`,
  `EURUSD=X`, `^GSPC`), World Bank country and Wikipedia language codes.
- `${key:default}` is honoured by `PropertiesConfigurator`, so the DuckDB, SQL-select and OLAP tools
  resolve their data directory (no more directories named `${data.duckdb.dir:.`).
- New key `alpha_vantage.api.key` (`ALPHA_VANTAGE_API_KEY`); `ai.tool_search.enabled`/`persist`
  parsed as booleans.
- **Plugins:** `.py` tools in a plugin now register; `min_sajha_version` is compared as a version.

### Other fixes

- `/api/reports/audit` answered 500.
- Federation upstreams shared one rate-limit window; each has its own.
- Change events relayed to other workers are coalesced within 0.5 s.
- The SDK no longer installs an OpenTelemetry tracer provider with no exporter when tracing is off.
- The test suite is independent of test order (engine and registry state restored; a SQLite WAL
  start-up race between workers fixed) and no longer touches tracked data.

### Documentation

- Reorganised under `docs/` by topic with one owning document per topic (the map:
  [How SAJHA Fits Together](docs/getting-started/How%20SAJHA%20Fits%20Together.md)), a root
  `GLOSSARY.md` that the console's glossary and "About this page" panels read, `CLAUDE.md`
  conventions, and point-in-time reports moved to `docs/archive/`. The numbered tutorials in
  `docs/tutorials/` are new.
- The in-app help is one catalog (`sajha/web/help_catalog.py`) rendering the guides at
  `/help/guides/<name>`; `tests/test_documentation_rot.py` checks links, cited paths, app URLs and
  that every registered route is in the [API Reference](docs/protocol/API%20Reference.md).

## v6.0.0 (October 2026) — MCP 2026-07-28, dual-era

SAJHA now serves the stateless **MCP 2026-07-28** protocol and the session-based **2025-11-25**
protocol on the same `/mcp` endpoint. The request's `_meta` decides which: a protocol version
there means stateless, `initialize` means a 2025-11-25 session. Both are verified in CI by the
official conformance suite (`.github/workflows/mcp-conformance.yml`):
- **2026-07-28:** 40/40 scenarios, 152/152 checks; tasks extension 44/44.
- **2025-11-25:** 32/32 scenarios, 43/43 checks.

### 2026-07-28 (new)
- `server/discover`.
- Version, capabilities and log level read from `_meta` on every request.
- Required `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers (-32020); version errors are -32022.
- `resultType` and `ttlMs`/`cacheScope` on results.
- `GET`/`DELETE /mcp` return 405 for these clients.
- Streamed `tools/call` with progress and log notifications. Closing the stream cancels the call.
- `subscriptions/listen`, fed by a change bus over the tool and prompt registries. The legacy `/mcp/sse` and `/mcp/ws` streams receive the same events.
- Multi Round-Trip Requests with an HMAC-signed `requestState`, and elicitation through them. Optional confirmation for destructive tools: `mcp.confirm_destructive_tools`.
- Tasks extension `io.modelcontextprotocol/tasks`. Tools opt in with `execution.taskSupport`.
- Tool context API (`report_progress`, `report_log`, `is_cancelled`) for long-running tools.

### Client SDK
- `SajhaMCPClient` / `SajhaMCPSyncClient` (from 5.4.0) negotiate 2026-07-28 automatically through the official SDK (`pip install sajhaclient[mcp]`).

### Compatibility
- 2025-11-25 clients are unaffected.
- `v5.4.0` (also tagged `mcp-2025-11-25`) remains the last 2025-only release.

## v5.4.0 (October 2026) — MCP 2025-11-25, verified

This release makes SAJHA's MCP 2025-11-25 support match what it claims, proven by the official
MCP conformance suite 0.1.16: **32/32 server scenarios, 43 checks passed, 0 failed**, plus the
official Python SDK 2.3.0 client. It is tagged `v5.4.0` and `mcp-2025-11-25`.

### Protocol and transport
- `initialize` negotiates the version (2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05) instead of ignoring the client's.
- Streamable HTTP on `/mcp`:
  - `Mcp-Session-Id` sessions; `DELETE /mcp` ends a session.
  - The `MCP-Protocol-Version` header is validated.
  - Notifications get 202 with no body; JSON-RPC batches get 400.
  - `GET /mcp` returns 405 to Streamable HTTP clients.
- `Origin` allow-list (`mcp.allowed_origins`, env `SAJHA_MCP_ALLOWED_ORIGINS`) with 403 for other origins.
- The legacy 2024-11-05 HTTP+SSE flow now delivers responses over its stream.
- MCP tool calls run off the event loop. They now use the same path as the REST API: disabled tools are refused, and arguments, cache, circuit breaker and metrics all apply.

### Tools, prompts, resources
- `tools/list` emits `title`, `outputSchema`, `annotations` and `icons[]`.
- `tools/call` returns JSON text plus `structuredContent`. Turn this off with `mcp.tools.advertise_output_schema: false`.
- `prompts/list` includes arguments, and prompts responses carry their `id`.
- `prompts/get` returns real messages.
- Errors are proper JSON-RPC errors, not error objects inside `result`.

### Honesty fixes (breaking)
- Server capabilities no longer advertise client-only `elicitation`/`sampling`, or a `tasks` shape that never ran. `listChanged` and `subscribe` are `false` until notifications exist. Custom keys moved under `experimental.sajha`.
- Removed `/.well-known/openid-configuration`, `/.well-known/oauth-protected-resource` and `/.well-known/oauth-client/{id}`. They advertised OAuth endpoints that did not exist.
- `ping` returns `{}`. Unknown resources return `-32002`. Tool icons are `icons[]`.

### Also
- Opt-in conformance fixtures: `mcp.conformance_fixtures` / `SAJHA_MCP_CONFORMANCE_FIXTURES=true`.
- Client SDK: `SajhaMCPClient`, a wrapper over the official `mcp` SDK v2 (`pip install sajhaclient[mcp]`), with SAJHA's REST, A2A and WebSocket extras.
- Fixed: `POST /api/auth/login` 500; prompt pages' Save/Delete/Test endpoints; prompt detail 500.
- WCAG AA contrast pass across all screens and themes.

### Design: MAYA design language and themes

SAJHA now uses MAYA's look and MAYA's four themes, with the same names and the same colour values.

- **Themes:** Crimson (stored as `light`), Dark, Blue and Green replace Light / Dark / Wall Street / Ubuntu.
  - The palette menu matches MAYA's: a swatch and a name for each theme.
  - With nothing stored, the page follows the system's light/dark setting.
  - A stored Light or Dark choice carries over; a stored Wall Street or Ubuntu choice resets to the default.
- **Tokens:** `static/css/tokens.css` is MAYA's token set, renamed from `--maya-*` to `--sajha-*`. It is the only place colours are defined.
  - `style.css` maps its `--t-*` roles onto these tokens once and re-points Bootstrap's variables at them.
- **Chrome:**
  - A fixed gradient top bar with mega-menu panels (`common/_nav.html`).
  - Gradient `h1`s, soft-shadow 14px cards, alerts with a left rule, gradient primary buttons.
  - Hero banners and MAYA's footer.
  - The system-ui font at 14px.
- **Pages:**
  - Sign-in stands on the theme gradient.
  - The landing page is laid out with MAYA's `lp2-*` sections.
  - The Studio pages share `_studio_theme.html`.
  - Help and About use MAYA's hero, card and box classes.
  - Charts read their colours from the tokens (`window.SajhaChartTheme`) and re-colour when the theme changes.

## v5.3.0 (June 2026) — Storage-Backed Registries, Studio & Cloud Hot-Reload

Builds on the v5.2.0 multi-cloud storage abstraction by routing the live subsystems
through it: tool configs, prompts, and Studio output can now live on local disk, S3,
Azure Blob, or GCS, with cloud hot-reload. Default backend remains **local**.

### Tool registry → storage backend
- **`tools_registry` reads migrated.** `load_all_tools()` enumerates via
  `get_storage().list_files('config/tools', '*.json')` and reads each config through
  `get_storage().read_json()`. The loader (`load_tool_from_config`) now accepts a logical
  path (storage-relative string, `Path`, or filename) instead of a filesystem `Path`, and
  is normalized internally — so **tool configs can live in S3/Azure/GCS**. Verified end to
  end: real tool configs uploaded to a mocked S3 bucket load and instantiate correctly.
- **`register_tool_from_dict(config, source)` extracted** as the shared register path for
  the file loader and the plugin loader. This fixes a latent bug where `plugins.py` called
  `load_tool_from_config(name, config)` with two arguments against a one-arg method.
- **Implementation classes stay package-local.** Tool `.py` implementations are resolved by
  dotted module path via `importlib` and ship with the package, so they import locally
  regardless of where the JSON config lives.
- **Config writes migrated** (`_save_tool_config`) to `get_storage().write_json()`; the
  admin reload route (`api_routes`) uses the storage-backed path.

### Prompts registry → storage backend
- **Reads and writes migrated.** `_load_all_prompts_internal` lists/reads through storage;
  `create_prompt` / `update_prompt` write via `write_json()`; `delete_prompt` via
  `delete()`. Time-based auto-refresh now reloads from whichever backend is active.

### MCP Studio → storage backend
- **All eight tool generators** (code, REST, DB-query, script, SharePoint, LiveLink,
  PowerBI, PowerBI-DAX) write their JSON config through a shared
  `write_tool_config()` storage helper. Generated `.py` implementations are still written
  locally because `importlib` needs a real module on the path — on multi-instance cloud
  deployments, place that directory on shared EFS.

### Cloud hot-reload (no inotify on object stores)
- **`S3SyncManager` activated for cloud backends** at startup: it polls the bucket every
  `sync_interval` seconds, mirrors changed objects into the local cache, and fires the same
  reload paths (`tools_registry.reload_all_tools`, `prompts_registry.reload`). On the
  `local` backend the registry's filesystem poller is used and the sync manager is skipped,
  so exactly one mechanism runs per deployment. Verified via mocked S3: initial sync
  materializes the cache and a new object triggers the reload callback.

### Semantic tool search (pluggable embedder)
- **Natural-language tool discovery** at `/api/ai/resolve-tool`: a query like "discount future
  cash flows to today" returns the top-k matching tools by vector similarity. The index
  embeds each tool's name + description + parameter names + tags + an optional `literature`
  field.
- **Configurable ranking** via `ai.tool_search.embedder`:
  - `bm25` (default) — a dependency-free lexical BM25/TF-IDF ranker (no model, no key, no
    network), built over the same rich text (name + description + parameters + tags + literature).
  - `gateway` — optional API-driven vector similarity via the LLM gateway's embedding provider
    (e.g. OpenAI) for paraphrase matching. Switch with one config value; no code change.
  - Decoupled from the LLM gateway — semantic search needs no provider in the default mode.
- **Accurate on change.** The index does incremental, content-hash-based sync: only tools
  whose embedding text changed are re-embedded, removed tools are dropped, unchanged tools
  keep their vectors. It hooks the registry's reload path (`add_reload_listener`), so adds /
  edits / deletes — local or via the cloud sync manager — keep embeddings current.
- **Persisted via the storage backend** (local | s3 | azure | gcs) with a header recording the
  embedder + dimension; a restart reloads vectors (no re-embedding) and a changed embedder
  forces a clean rebuild (vectors from different models aren't comparable).
- **Non-blocking + graceful.** The initial index builds in a background thread so startup is
  never blocked; until it's ready (or if no embedder is available) search falls back to
  keyword matching. In-memory numpy cosine search — a `VectorIndex` seam is left for FAISS /
  Chroma if scale ever demands it.

### Database scripts cleanup
- **Fixed a critical regression where the file monitor unloaded all tools every 5s.** The
  storage migration changed `load_tool_from_config` to key `_file_timestamps` by
  storage-relative paths (`config/tools/foo.json`), but the registry's `_monitor_files`
  poller still compared against absolute paths — so every tool looked simultaneously "new"
  and "deleted" each cycle and the delete branch unregistered them all, leaving the registry
  empty. The monitor now keys on the same relative paths (`_config_rel`), so new/modified/
  deleted detection works correctly and legitimate hot-reload is preserved. Semantic tool
  search was also made fully non-blocking on reload, so the optional feature can never affect
  core tool loading.
- **Fixed SharePoint tools failing to load.** `SharePointBaseTool` never implemented the
  `get_input_schema` / `get_output_schema` abstract methods from `BaseMCPTool`, so all three
  SharePoint tools (documents, lists, search) raised "Can't instantiate abstract class …" at
  load. Added both getters to the base (returning the config's `inputSchema` / `outputSchema`,
  matching every other tool), making all four SharePoint classes concrete. Tool count
  496 → 499.
- **Removed obsolete top-level `db/scripts/001_schema.sql` + `002_seed.sql`.** The engine runs
  the dialect-specific `db/scripts/<db.type>/` directory; the top-level scripts were bypassed
  for SQLite and only reached as a buggy fallback (below).
- **Renamed `db/scripts/postgres/` → `db/scripts/postgresql/`** to match `db.type: postgresql`.
  Previously the engine looked for `db/scripts/postgresql/` (the `db.type` value), didn't find
  it, and silently fell back to the top-level scripts — so a Postgres deployment never used its
  own schema. Now `db/scripts/sqlite/` and `db/scripts/postgresql/` are the single source of
  truth per dialect.
- **Reconciled schema drift:** `llm_usage` and `user_ai_preferences` (previously only in the
  top-level file) are now defined in **both** dialect schemas alongside `rate_limit_log` and
  `tenant_users`, so SQLite and Postgres create an identical table set. Verified: SQLite boot
  creates all tables; both `db.type` values select the correct script directory.

### Documentation
- **New Storage Management help page** (`/help/storage`) with sections on local, EFS, S3,
  Azure Blob, and GCS — backend selection, auth, the read-mostly-vs-mutable-state rule, and
  how hot-reload works. Linked from the Help index.
- **README, ARCHITECTURE, and STORAGE_ROADMAP updated** to describe the storage-backed
  registries and cloud hot-reload. Version bumped to **5.3.0**.

## v5.2.0 (June 2026) — Offline Assets, Self-Only CSP & UI Polish

### Front-End Vendoring (offline-capable, no CDNs)

- **All third-party assets vendored** to `sajha/web/static/vendor/`: jQuery 3.7.1, Bootstrap 5.3.0 (CSS + bundle JS), Bootstrap Icons 1.10.0 (+ fonts), Socket.IO 4.5.4, marked 4.3.0 (pinned — preserves the `marked.setOptions({highlight})` API the docs viewer relies on), highlight.js 11.9.0 (+ 7 language packs + github-dark theme), Chart.js 4.4.0, jsoneditor 9.10.4 (+ icons), and three webfonts (Ubuntu, Plus Jakarta Sans, JetBrains Mono).
- **Zero external resource loads** remain across all 52 templates — the app renders fully offline / air-gapped.

### Security — Content-Security-Policy

- **Docs viewer fixed**: the markdown viewer previously spun forever because jQuery and Socket.IO were loaded from CDNs that the CSP `script-src` did not whitelist, so `$` was undefined and `$(document).ready()` threw before the render path. With everything vendored, this class of failure is gone.
- **CSP tightened to self-only**: `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; connect-src 'self' ws: wss:`. No third-party origins to drift out of sync with.
- **CORS** default aligned with the `0.0.0.0` bind: localhost / 127.0.0.1 / 0.0.0.0 on :3002 (override via `SAJHA_CORS_ORIGINS`).

### Config Substitution Fix

- **`${data.duckdb.dir}` / `${data.sqlselect.dir}` now resolve correctly.** Root cause: `tools_registry` constructed `PropertiesConfigurator()` with no `yaml_file`, so it loaded nothing and every `${key}` fell through to its literal text — which created directories literally named `${data.duckdb.dir}`. The registry now loads the same config the app uses (respecting `SAJHA_CONFIG_FILE` / `--config`).
- `app.py` PropertiesConfigurator load also respects `SAJHA_CONFIG_FILE` instead of hardcoding the path.
- All 15 affected tool configs given `:default` fallbacks (e.g. `${data.duckdb.dir:./data/duckdb}`) as defense-in-depth.

### Storage Abstraction (on-prem ↔ cloud)

- **Pluggable storage backend** wired into startup: `storage:` config block (`backend: local|s3|azure|gcs`), `init_storage()` called before tools/prompts load, `get_storage()` available app-wide. Default `local` is a transparent filesystem wrapper — no behaviour change on-prem, and it needs none of the cloud SDKs.
- **Four backends behind one `StorageBackend` interface**: `LocalStorageBackend` (default) plus three object stores — **S3** (boto3, now with `endpoint_url` for MinIO/R2/Wasabi), **Azure Blob** (azure-storage-blob; connection-string or managed-identity auth), and **GCS** (google-cloud-storage; ADC/workload-identity auth). The three object stores share an `_ObjectStorageBackend` base (app-prefix namespacing, local read-through cache, recursive listing, `get_local_path` materialization); each implements only six small primitives. Cloud SDKs are lazy-imported, so only the selected backend's SDK is required.
- **Docs viewer migrated** to read through the backend (listing + content), so docs can be served from any backend; added a path-traversal guard.
- **`list_files` contract aligned** across local and object backends (recursive listing, filename-pattern match).
- Validated: S3 against a `moto`-mocked bucket; Azure + GCS against the real SDK surfaces (API-method introspection) plus injected-client logic tests; and the local default proven to boot with all cloud SDKs blocked. Remaining adoption (tools/prompts/studio, mutable-state placement, cloud hot-reload) tracked in `docs/STORAGE_ROADMAP.md`.

### Config-Driven UI Metadata

- Version, author, copyright, email, and GitHub URL/repo-name are all surfaced on the UI from `application.yml` via Jinja globals. Closed the two remaining hardcoded spots (About-page email, an Enterprise help version literal) and added a GitHub link to the About page.

### UI / Theming

- **About page rewritten**: 1384 → 314 lines. The old page duplicated its marketing cards 7–14× with malformed closing tags (causing visual overlap); the rewrite renders each section exactly once, is structurally valid, and is fully theme-driven via `var(--t-*)` surfaces and `card-header-*` helpers.
- **Theme sweep**: 113 `card-header` elements using fixed `bg-*`/`text-white` across 28 templates converted to the theme-aware `card-header-*` helpers (no more colour bleed in Dark / Wall Street / Ubuntu themes). Intentional fixed colours (code-editor surfaces, provider/brand accents, status badges, landing-page gradients) deliberately preserved.
- **Landing page**: added a `<canvas>` "living intelligence mesh" behind the hero — a pulsing SAJHA hub routing animated data packets between AI-agent nodes (Claude, GPT-4o, Bedrock, Together, Ollama, Azure) and data-provider nodes (FMP, OpenBB, FRED, Yahoo, SEC EDGAR, CoinGecko). Vanilla JS, theme-matched, DPR/resize-aware, pointer-interactive, and respects `prefers-reduced-motion` (renders a single static frame).
- Dead duplicate templates removed: `help/docs_list.html`, `help/docs_view.html` (the live versions live under `docs/`).

### Dependencies

- **`requirements.txt` pinned** with next-major ceilings on all dependencies (0 unbounded) to keep fresh installs reproducible. A `pip freeze` lockfile from a tested environment remains the gold standard for full reproducibility.

---

## v5.1.0 (May 2026) — Security hardening, System Monitor, Composition Framework, MCP 2025-11-25

Three bodies of work were released under 5.1.0. Several MCP claims below were later found to be inaccurate and were corrected in v5.4.0 (see its "Honesty fixes").

### Security hardening and System Monitor

#### Configuration System Overhaul

- **YAML-only config**: `config/application.yml` is the single source of truth. No `.properties` files.
- **`--config` CLI argument**: `python run_server.py --config /path/to/custom.yml` — override config file path.
- **`SAJHA_CONFIG_FILE` env var**: Set config path via environment for containerized deployments.
- **PropertiesConfigurator enhanced**: Native YAML loading via `yaml_file` param. Properly flattens nested keys (`a.b.c.d`). No more `_properties.update(_CFG)` hack.
- **Config `get()` semantics fixed**: Default kicks in if and only if key is NOT defined. Empty string IS a valid value. `None` values excluded from flattened dict.
- **`_int()` / `_bool()` safe**: Handle empty strings gracefully — no more `int('')` crashes.
- **Gateway config fixed**: Receives `_CFG` directly instead of broken `getattr` mapping.

#### Competitive Positioning Update

- **18 competitive advantages** identified and documented — no other MCP server has more than 2 of these.
- **AI/LLM Gateway**: Highlighted as unique — 6 providers via official SDKs, DB-managed models, registry factory. No other MCP server has embedded LLM access.
- **Semantic Tool Discovery**: Highlighted as unique — vector embeddings of 497 tool descriptions, cosine similarity search from natural language. No other MCP server has this.
- **Enterprise features**: Multi-tenancy, plugin system, tool versioning, OpenTelemetry — all unique to SAJHA.
- Updated About page with AI Gateway + Semantic Discovery cards.
- README competitive table expanded from 12 to 18 rows, organized into 5 categories.

#### MCP Studio + Composite Builder — Competitive Differentiators

- **MCP Studio**: Highlighted as unique competitive advantage. 9 visual tool creator types (Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, SharePoint, OLAP). No other MCP server has visual tool creation.
- **Composite Builder**: Highlighted as unique competitive advantage. Visual pipeline designer with live SVG flow diagram, drag-and-drop step ordering, ParamLens param mapping, EntropyGuard confidence preview, auto-generated schemas, zero-restart deployment.
- Updated README competitive analysis table: MCP Studio and Composite Builder now top-2 differentiators.
- Added detailed sections in README: MCP Studio (9 creator types table), Composite Builder (7-step workflow).
- Updated About page with dedicated MCP Studio + Composite Builder cards.

#### Sandboxed Shell Tools (NEW)

- **ShellExecutor** (`sajha/core/shell_executor.py`, 420 lines): Three-tier execution model. Python sandbox (restricted imports, subprocess isolation, 30s/256MB limits), Bash sandbox (allowlisted commands, no write/network), Unrestricted (admin-only, disabled).
- **SecurityValidator**: Pre-execution code analysis. Python: blocks 30+ dangerous imports (os, subprocess, socket, ctypes, pickle), 10+ dangerous builtins (exec, eval, open, __import__), filesystem access patterns. Bash: allowlist of 30 safe commands, 25+ blocked patterns (rm, sudo, ssh, pipe-to-shell, command chaining, backtick substitution).
- **Audit logging**: Every execution recorded to audit_log DB table regardless of outcome. Code preview, user_id, result status, duration.
- **MCP tool schemas**: `shell_python` and `shell_bash` registered as MCP tools for agent use.
- **API endpoints**: `POST /api/shell/python`, `POST /api/shell/bash`, `GET /api/shell/capabilities`, `GET /api/shell/history`.
- **Configuration**: Disabled by default. `shell.enabled: false` in application.yml. Python sandbox enabled when master switch is on; Bash requires additional `shell.bash.enabled: true`.
- **Security first**: No tool has both network and filesystem access. No command chaining. No shell metacharacter injection. Every blocked attempt logged.

#### Async Tool Execution (NEW)

- **AsyncExecutor** (`sajha/core/async_executor.py`, 320 lines): Background execution engine with bounded work queue (`queue.Queue(maxsize=1000)`) and daemon worker pool (default 8 threads). Workers reuse `execute_with_tracking()` for cache/circuit/replay integration.
- **DeliveryRouter**: Three delivery backends — webhook (POST with 3 retries + exponential backoff), Kafka (lazy import, produce to topic with key), filesystem (atomic write via temp file + rename).
- **Task lifecycle**: queued → running → completed/failed → delivered/cancelled. All state tracked in memory with configurable TTL cleanup.
- **Backpressure**: Bounded queue returns HTTP 503 when full — prevents memory exhaustion.
- **API endpoints**: `POST /api/tools/{name}/execute-async`, `GET /api/async/tasks`, `GET /api/async/tasks/{id}`, `POST .../cancel`, `POST .../retry`, `GET /api/async/stats`.
- **Admin UI page**: `/admin/async-tasks` — stats cards (queued/running/completed/failed/delivered/cancelled), filterable task table, cancel/retry/view actions, detail panel with arguments + result, auto-refresh (3s/10s/30s).
- **Configuration**: `config/application.yml` → `async:` section with workers, queue_size, task_ttl_hours, delivery config per backend.
- **Competitive advantage**: No other MCP server offers async execution with delivery routing.

#### Production Enhancements

- **Tool Output Caching** (`sajha/core/cache.py`): LRU cache with configurable TTL per tool. Default TTLs: FRED 3600s, FMP 300s, Yahoo 30s, calculators disabled. Cache key = tool_name + MD5(sorted args). Max 10,000 entries. APIs: GET /api/cache/stats, POST /api/cache/invalidate.
- **Circuit Breakers** (`sajha/core/circuit_breaker.py`): Per-provider failure tracking. CLOSED → OPEN (5 failures) → HALF_OPEN (probe after 60s recovery). 16 providers mapped. API: GET /api/circuits.
- **Webhook Notifications** (`sajha/core/webhooks.py`): Event-driven callbacks. Events: tool.completed, tool.failed, task.completed, circuit.opened. 3 retries with exponential backoff. APIs: POST /api/webhooks/subscribe, GET /api/webhooks.
- **Tool Health Dashboard** (`sajha/core/tool_health.py`): Dependency graph (497 tools → 16 providers → API endpoints). Per-provider health aggregating circuit breaker state. APIs: GET /api/providers/health, GET /api/providers/graph.
- **Execution Replay** (`sajha/core/tool_health.py`): Last 20 executions stored per tool with arguments, result preview, duration, success/failure. APIs: GET /api/replay/recent, GET /api/replay/tool/{name}.
- **Structured Audit Log** (`sajha/core/audit.py`): Security events to DB audit_log table: login, logout, user/key CRUD, permission changes, account lockout. API: GET /api/audit with action/user_id/limit filters.
- **Per-User API Rate Limiting**: 100 calls/min per user, 200 calls/min per API key (on top of existing 5/min/IP auth rate limit).
- **Startup Schema Validation**: Lightweight contract test on boot — validates all tool input schemas without making API calls. Failed tools logged as warnings.
- **Base tool execute_with_tracking**: Now integrates cache check → circuit breaker check → execute → cache put → replay record → circuit breaker update in a single execution flow.

#### Cybersecurity Overhaul

- **bcrypt password hashing** (12 rounds) — replaces plaintext comparison
- **SHA-256 API key hashing** — keys stored as hashes, never plaintext
- **DB-persisted sessions** — user_sessions table with hashed tokens
- **Account lockout** — 5 failed attempts → 15 minute lock
- **Rate limiting** — 5 login attempts per minute per IP (HTTP 429)
- **Security headers middleware** — X-Frame-Options, CSP, HSTS, XSS-Protection, Referrer-Policy, Permissions-Policy
- **CORS restricted** — configurable via SAJHA_CORS_ORIGINS env var (no more wildcard)
- **Cookie hardening** — HttpOnly + SameSite=lax + Secure (auto-detect HTTPS)
- **Request body limit** — 10 MB via RequestSizeLimitMiddleware
- **DuckDB SQL allowlist** — only SELECT/WITH/EXPLAIN permitted (comment-stripping)
- **Passwords never returned** — get_all_users() excludes password_hash
- **No hardcoded credentials** — admin password is bcrypt hash in seed SQL

#### Database

- **Dual schema files** — db/scripts/sqlite/ and db/scripts/postgres/
- **SQLite**: auto-created on startup (IF NOT EXISTS)
- **PostgreSQL**: schema must pre-exist (TIMESTAMPTZ, BOOLEAN, DOUBLE PRECISION)
- **Engine auto-selects** script directory based on db.type config
- **SQLAlchemy ORM** for all user/role/apikey/session operations
- **Account lockout columns** — users.failed_attempts + users.locked_until

#### System Monitor

- **Admin page** at /admin/system-monitor with auto-refresh
- **CPU** — usage %, model, cores, load avg, context switches, interrupts
- **Memory** — total/used/available/cached/buffers, swap
- **Disk** — mount point, filesystem, total/used/free, DB file size
- **Network** — bytes/packets sent/received, errors, active connections
- **SAJHA Process** — PID, CPU%, memory%, RSS, VMS, threads, open FDs
- **Runtime** — Python version, platform, hostname, SAJHA version, MCP protocol, tools loaded, DB type
- **Top Processes** — top 15 by CPU with PID, user, status, command
- **psutil** for comprehensive metrics, /proc fallback for basic Linux

#### Documentation

- **docs/Cybersecurity_Assessment.md** (491 lines) — 31 controls across 7 categories with OWASP mapping
- **docs/MCP_2025_11_25_Compliance.md** (293 lines) — 18 items with code evidence and curl verification
- **Logout redirects to landing page** (not login page)

### Composition Framework and UX overhaul

Category-theory-inspired composition, 4 UI themes, full UX redesign, CSS rewrite.

#### Composition Framework (from "On the Composability of Intelligence")

- **Kleisli Composition** (`sajha/core/composition.py`): Every tool execution wrapped in `StepResult` envelope carrying value, error, trace, duration, and confidence. Errors short-circuit the pipeline. Traces accumulate across steps. Confidences compound via Giry bind.
- **ParamLens**: Lens-based parameter projection. Child tools receive ONLY mapped fields via `$.field` / `$input.field` syntax. Prevents accidental coupling to upstream output structure.
- **EntropyGuard**: Cumulative confidence tracking with parallel-aware model. Sequential steps multiply (Giry bind). Parallel steps use weakest-link (min). Mixed pipelines combine both. `entropy_threshold` per composite — refuses execution if uncertainty exceeds limit.
- **Tool Confidence Registry**: 497 tools classified by reliability — calculators 1.0, FRED 0.95, FMP 0.93, web crawlers 0.80. Composite results include `_composition.confidence` and `_composition.entropy_bits`.
- **CompositeTool.execute()** rewritten to use composition framework. All composites now return `_composition` metadata block with confidence, entropy, trace, and guard status.

#### Client SDK Enhancements

- **Transport Coalgebra**: `TransportCoalgebra` abstract class with `step(input) → (output, new_state)`. `HTTPTransport`, `SSETransport`, `WSTransport` implementations. Enables runtime transport hot-swap.
- **bisimilar()**: Behavioral equivalence testing. Runs same operation sequence against two transports, verifies identical output structure. Proves transport interchangeability.
- **ClientPipeline**: Client-side tool composition. `add_step()` with `$input.` / `$.` param mapping. `execute()` with confidence tracking and entropy guard. Works without server-side composite definitions.

#### UX Overhaul (22 recommendations implemented)

- **4 UI Themes**: Light, Dark (landing-page glass-morphism), Wall Street (Bloomberg terminal amber-on-black, Consolas font), Ubuntu (aubergine + orange, Ubuntu font). Variable-driven CSS — 545 lines replaces 4,441.
- **CSS rewrite**: Clean architecture — design tokens → theme definitions (var(--t-*)) → components. Zero hardcoded colors. Every Bootstrap color class overridden for all themes. WCAG AA contrast verified.
- **Landing page**: Standalone dark-navy theme, gradient hero, 9 feature cards, code snippet, stats bar.
- **Login page**: Standalone dark theme matching landing page. Glass-morphism card.
- **Dashboard**: Welcome bar with transport badges, 4 metric cards, quick actions panel, platform stats, status panel, onboarding wizard.
- **Tools list**: Card-grid view toggle, category filter chips (auto-generated from tool data).
- **AI → LLM**: 5 Bootstrap tabs (Providers, Models, Preferences, Semantic Search, Usage). Add Provider form with type-specific fields (Bedrock: region+AWS keys, Azure: deployment+endpoint, Ollama: host+model, Custom: class+JSON).
- **Composite Builder**: Visual SVG flow diagram (updates live), drag-and-drop step reorder.
- **Studio sub-navigation**: Horizontal chip bar across all 10 studio pages.
- **Help page**: Search-within-help, 6 tutorial cards, 5 v4 feature sections.
- **Active nav highlighting**, button press feedback, loading skeletons, keyboard shortcuts (/ = search, Shift+? = help), skip-to-content link, focus-visible outlines, empty state CTAs with action buttons.
- **0 modals** — all replaced with inline forms/banners.
- **table-enhance.js**: Reusable component — search, pagination, rows-per-page for any table via `data-enhance="true"`.
- **Custom SVG icon set**: 8 icons (sajha, mcp, tool, composite, provider, transport, plugin, agent) as inline sprite.

#### Infrastructure

- **Deployment restructured**: `aws/` → `deployment/aws/`, added `deployment/hetzner/` (Docker+Caddy+auto-SSL), `deployment/baremetal/` (systemd+Nginx+certbot).
- **AWS CDK** replaces Terraform: `deployment/aws/cdk/sajha_stack.py` (238 lines Python) — VPC, ECS Fargate, RDS, S3, Secrets Manager, CloudWatch dashboard, auto-scaling.
- **Property-driven configuration**: Version, email, author, github, copyright, all paths (data.dir, logging.dir, config.plugins.dir) — all from `config/application.yml`. Footer shows `© {{ app_copyright_years }} {{ app_name }} | {{ app_author }} · Version {{ app_version }}`.
- **PostgreSQL config**: 3 commented-out examples in application.yml (local, AWS RDS, Hetzner managed).
- **Two SQL scripts only**: `001_schema.sql` (19 tables, CREATE IF NOT EXISTS), `002_seed.sql` (INSERT OR IGNORE). No migrations.

#### Bug Fixes

- `tool_schema.html` 500 error: `schema_json` passed as separate pre-serialized string, not mutating MCP format dict.
- `tool_enabled` / `tool_version` passed as separate template variables — MCP `to_mcp_format()` dict never modified.
- Help/About/Docs pages made public (`get_current_user` instead of `require_auth`).
- Login POST indentation bug fixed.
- All `ToolsRegistry.get_instance()` calls replaced with `from sajha.app import tools_registry` (6 occurrences across composite_routes.py and ops_routes.py).
- Theme switcher Chrome fix: `<button>` elements replace `<a href="#">`, event delegation via `addEventListener`.
- Navbar dropdown z-index: `z-index: 1050` prevents dropdown hiding behind page content.
- `color-scheme: dark` for dark themes fixes native `<select>` dropdown colors.

### MCP 2025-11-25 upgrade

Upgraded from MCP protocol version 2025-06-18 to 2025-11-25. All 19 spec changes implemented.

#### Major Features (from MCP 2025-11-25)

- **Tasks (SEP-1686)**: Async task tracking for long-running MCP requests. `TaskManager` with create/get/list/cancel. States: working → input_required → completed/failed/cancelled. Polling-based result retrieval. MCP methods: `tasks/get`, `tasks/list`, `tasks/cancel`.
- **Elicitation (SEP-1330, SEP-1036)**: Server-initiated user input requests. Two modes: Form (structured JSON Schema) and URL (redirect to OAuth/consent page). `ElicitationManager` with create_form/create_url/respond/cancel. MCP method: `elicitation/respond`.
- **Sampling with Tools (SEP-1577)**: Server-initiated LLM calls with tool definitions. `SamplingManager` supports `tools` and `toolChoice` parameters per spec. Enables server-side agent loops.
- **Tool Icons (SEP-973)**: Icon metadata in tools/list responses. Supports `{"type":"url","url":"..."}` and `{"type":"emoji","emoji":"📊"}`. Configured per-tool in JSON config.
- **Origin Validation (Minor 3)**: Streamable HTTP endpoints respond with HTTP 403 for invalid Origin headers. `validate_origin()` in SSE route.
- **Tool Execution Errors (Minor 5)**: Input validation and execution errors now return `{"isError": true}` in tool result content (Tool Execution Error) instead of JSON-RPC Protocol Errors. Enables model self-correction.
- **Server Description (Minor 2)**: `description` field added to `serverInfo` in initialize response.
- **notifications/cancelled**: Client can cancel pending requests via `notifications/cancelled` method.
- **JSON Schema 2020-12 (Minor 10)**: Declared as default dialect for schema definitions.

#### Updated Capabilities Declaration

```json
{
  "protocolVersion": "2025-11-25",
  "capabilities": {
    "tools": {"listChanged": true},
    "prompts": {"listChanged": true},
    "resources": {"subscribe": true, "listChanged": true},
    "logging": {},
    "completions": {},
    "elicitation": {"form": {}, "url": {}},
    "sampling": {"tools": true},
    "tasks": {"experimental": true}
  }
}
```

#### Exception Handling Overhaul

- 42 bare `except:` blocks → `except Exception as e:` + logging
- 21 swallowed exceptions → added logging with `exc_info=True`
- 280+ `exc_info=True` additions for full stack traces in log files
- Before: 11 good / 304 issues. After: 308 good / 102 issues.

#### Files Added

- `sajha/core/mcp_2025_11_25.py` — Tasks, Elicitation, Sampling, Icons, Origin validation

---

## v4.0.0 (May 2026) — Production Hardening

WebSocket transport, OpenTelemetry, tool versioning, multi-tenancy, plugin system. See git history.

## v3.1.0 (May 2026) — FastAPI Migration

Complete rewrite from Flask to FastAPI. See git history.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
