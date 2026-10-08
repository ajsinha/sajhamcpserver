# SAJHA MCP Server — Extending the Intelligence Layer

This guide is for developers who want SAJHA's intelligence layer to use something it does
not ship with: a new LLM **provider** (a vendor or an in-house service), a new **model**
(a fine-tune, a custom route, a model with its own behaviour), a real **planner** in
place of the offline `mock-planner` that Ask SAJHA uses out of the box, or another
**document store** for document search (§6).

What the layer is and why it is built this way is the
[Intelligence Layer](Intelligence%20Layer.md) design document; every configuration key is
in the [Configuration Reference](../getting-started/Configuration%20Reference.md#ai). This
guide does not repeat them; it shows how to build on them, step by step.

**Where the code goes.** Every provider and model specific lives in `sajha/ai/llm/`: a
built-in provider is one module in `sajha/ai/llm/providers/`; an out-of-tree one is a module of
your own package, loaded by class path or entry point (section 2.7). Either way it implements
the two abstract classes of `sajha/ai/llm/base.py`: `LLMProvider` (a factory for its models,
its catalogue, health, configuration) and `LLMModel` (`chat_completions_create`,
`chat_completions_stream`, `achat_completions_create`, `achat_completions_stream`,
`embeddings_create`, `aembeddings_create`, `info`). You rarely implement them from scratch:
subclass the shared implementations `ProviderBase`, `ChatModel` / `HTTPChatModel` and
`EmbeddingModel`. Extension code imports them, and everything else it needs, from the provider
SPI, `sajha.ai.llm.spi`; the canonical types and errors come from `sajha.ai.llm`. Application
code never sees your classes: `llm_factory().model(alias)` returns a `GovernedModel` proxy that
delegates to your model after policy, budgets, cache, retries and fallback
(`tests/test_llm_boundary.py` checks that nothing outside the package constructs a provider or
model, and that every registered provider implements the abstract classes).

Every code block below that starts with a `# sajha/examples/intelligence/...` line is an
excerpt of a file in `sajha/examples/intelligence/` (`# ...` marks skipped lines).
`tests/ai/test_extension_examples.py` runs those files through the provider contract suite
and through `IntelligenceService.ask`, and fails if an excerpt here stops matching its file.

| Example | What it shows |
|---|---|
| `sajha/examples/intelligence/acme_provider.py` | A provider for a fictional in-house HTTP LLM ("Acme"): settings, credentials, chat, tool calls, structured output, streaming, embeddings, live model list, health, error mapping |
| `sajha/examples/intelligence/acme_fake_server.py` | Acme's API faked: an `httpx.MockTransport` for tests and a small local HTTP server for trying the provider in Ask SAJHA |
| `sajha/examples/intelligence/custom_models.py` | `@register_model`: a fine-tuned OpenAI model with its own behaviour, on the built-in `openai` provider |
| `sajha/examples/intelligence/recipe_planner.py` | A planning strategy written as a model: fixed question-to-tool recipes that defer to the next model in the alias |
| `sajha/examples/intelligence/docs_first_planner.py` | A `Planner`: search SAJHA's guides first for how-to questions, then hand the ask to `react` |

---

## 1. Concepts

```
 POST /api/ai/ask, the Ask SAJHA page (/ask), the sajha_ask MCP tool
        │
        ▼
 IntelligenceService.stream_ask (sajha/ai/intelligence.py)
   1 shortlist   ToolResolver ranks tools; RBAC and policy filter them      (not pluggable)
   2 loop        for each step: the PLANNER (ai.ask.planner, section 4.5) decides; the default,
                 react, calls llm_factory().model(ai.ask.model)
                   │                                      ▲
                   │                                      │ ChatCompletion: text and/or tool_calls
                   ▼                                      │
                 GovernedModel.chat_completions_create (the proxy): alias → candidates → policy,
                   │                                   budget, retries, fallback, cache, audit
                   ▼  delegates to
                 ChatModel.chat_completions_create  ◄── a MODEL (section 3); under react it plans too (section 4)
                   │  prepare (refusals, capabilities) → _create → wire / parse at the edge
                 ProviderBase: credentials, httpx clients, catalogue, health   ◄── a PROVIDER (section 2)
                 the loop runs each tool call (offered? destructive? execute_with_tracking)
                 and feeds the results back as role "tool" messages
   3 synthesis   one more call with response_format json_schema → {answer, citations, caveats}
   4 confidence  from the composition framework, not from the model
```

| You want | You write | Registered by | Section |
|---|---|---|---|
| SAJHA to talk to a new LLM service | a `ProviderBase` subclass (an `LLMProvider`) with a pydantic `config_model`, plus a `ChatModel` that translates the canonical (OpenAI Chat Completions) format to the service (and optionally an `EmbeddingModel`) | `@register_provider`, `ai.providers[].class`, or a `sajha.llm_providers` entry point | 2 |
| A model id the provider does not know, with different capabilities or prices | nothing: a `models:` entry in the provider's config | configuration | 3.6 |
| A model with its own behaviour on an existing provider | a `ChatModel` subclass (usually of that provider's model class) | `@register_model(provider=..., model_id=...)` | 3.6 |
| Real planning in Ask SAJHA | nothing: enable a tool-capable provider and point the `default` alias at it | configuration | 4.3 |
| Your own planning strategy | a `Planner` (or a `ChatModel` that decides tool calls) | `ai.ask.planner` (or an alias) | 4.4, 4.5 |

Terms used throughout (definitions in the [glossary](../../GLOSSARY.md)): a **provider**
owns credentials, the HTTP client and the model list, and creates models; a **model** does
the work and declares its **capabilities**; an **alias** (`default`, `fast`, `reasoning`,
`embedding`) is an ordered list of `provider/model` candidates; the **planner** decides at
each step of an ask whether to answer or which tools to call.

---

## 2. Writing a provider

A provider is a subclass of `ProviderBase` (`sajha/ai/llm/provider.py`, imported from
`sajha.ai.llm.spi`), the shared implementation of the abstract `LLMProvider`. The class
attributes are the whole declaration:

| Attribute | Meaning | Acme |
|---|---|---|
| `name` | Registry key, and the default config section and env prefix | `"acme"` |
| `config_model` | A subclass of `ProviderConfig` (pydantic); one field per setting | `AcmeConfig` |
| `requires_key` | `enabled: auto` turns on only when a key resolves; `health()` is down without one | `True` |
| `default_base_url` | Used when `base_url` is not configured | `https://llm.acme.internal` |
| `catalog_key` | Row set in `sajha/ai/llm/catalog.py` (built-in vendors only) | not used |
| `unknown_model_capabilities` | Capabilities assumed for a model id nobody described | tools, 32k context |
| `chat_model_class` / `embedding_model_class` | What `chat_model()` / `embedding_model()` build | `AcmeChatModel` / `AcmeEmbeddingModel` |
| `live_models_ttl_s` | How long `list_models()` is cached | default `60` |
| `openai_compatible` | The service speaks Chat Completions: passed-through fields (§13.6) are accepted | `False` |
| `developer_role` | The service takes role `developer` (else it is sent as `system`) | `False` |
| `feature_defaults` | Defaults for the canonical feature flags of its models (3.2) | none |

Its OpenAI-style face: `provider.models()` returns `ModelInfo` objects (like
`GET /v1/models`) and `provider.model(name)` the model object.

The provider is a factory: the governed model calls `chat_model(model_id)` (or
`embedding_model(model_id)`) on it and then delegates only to the model object. Steps 2.1 to 2.8
build the Acme provider in that order.

### 2.1 Settings: the `config_model`

Every setting is a pydantic field. `ProviderConfig` already has the common ones (`enabled`,
`api_key`, `api_key_ref`, `base_url`, `extra_headers`, `proxy`, TLS, timeouts, retries,
`max_concurrency`, `default_model`, `streaming`, `models`, ...; the full list with defaults
is in the [Configuration Reference](../getting-started/Configuration%20Reference.md#aiproviders)).
Add only what your service needs:

```python
# sajha/examples/intelligence/acme_provider.py
class AcmeConfig(ProviderConfig):
    """Inherits enabled, api_key, api_key_ref, base_url, timeouts, retries, models, ...
    Each field below is ai.providers[name=acme].config.<field> in application.yml and
    SAJHA_AI_ACME_<FIELD> in the environment, with no further code."""
    tenant: str = "default"                               # sent as X-Acme-Tenant
    safety: Literal["standard", "strict"] = "standard"    # Acme's own content policy level
    default_model: Optional[str] = "acme-large"
    default_embedding_model: Optional[str] = "acme-embed"
    live_models: bool = True                              # ask GET /v1/models for the model list

    # the vendor's own variables, read after SAJHA_AI_ACME_* and before application.yml
    vendor_env: ClassVar[Dict[str, List[str]]] = {"api_key": ["ACME_LLM_KEY"], "base_url": ["ACME_LLM_URL"]}
```

What you get for free (`resolve_layers` in `sajha/ai/llm/settings.py`):

- **An environment override per field.** The prefix is `SAJHA_AI_` plus the provider's
  configured name upper-cased with non-alphanumerics as `_`, so `tenant` is
  `SAJHA_AI_ACME_TENANT` and `live_models` is `SAJHA_AI_ACME_LIVE_MODELS`. A second
  instance configured as `{name: acme_eu, class: ...}` reads `SAJHA_AI_ACME_EU_TENANT`.
  Scalars are parsed by the field's type; `List[str]` takes JSON or a comma list;
  dictionaries and lists of objects (such as `models`) take JSON.
- **Precedence**, highest first: `SAJHA_AI_ACME_<FIELD>` → the variables in `vendor_env`
  → `application.yml` → the `llm_providers` / `llm_models` tables → the field's default.
- **Validation at startup.** A wrong type or an unknown key (`tenat:`) fails with the list
  of valid fields; the error is logged and reported under `build_errors` by
  `GET /api/ai/config`, and the provider is not created.
- **The effective configuration.** `GET /api/ai/config` (admin) shows every field with its
  source (`default`, `config`, `env:NAME`, `db`, `ref:...`); `api_key` and header values
  whose names contain key, auth, token or secret are redacted.

Keep secrets out of fields other than `api_key`: only `api_key` (and the Bedrock AWS keys)
are redacted by name. A field that must hold a secret should be a reference, resolved like
`api_key_ref` below.

### 2.2 Credentials

`self.api_key` returns `config.api_key` (a `SecretStr`) or, when only `api_key_ref` is set,
resolves it through the provider's `SecretStore` (`sajha/ai/llm/secrets.py`): `env:NAME`,
`file:/path` (the file's contents) or `db:llm_providers/<type>` (the key saved on the AI
settings page). Put the key into headers in `auth_headers()`:

```python
# sajha/examples/intelligence/acme_provider.py
    def auth_headers(self) -> Dict[str, str]:
        headers = {"X-Acme-Tenant": self.config.tenant}
        if self.api_key:                                   # api_key, or api_key_ref via the SecretStore
            headers["X-Acme-Key"] = self.api_key
        return headers
```

`auth_headers()` is read once, when the HTTP clients are first built, so a rotated key takes
effect when the factory is rebuilt (at the next start). If your service uses short-lived
tokens, return them from `request_headers()` (and `arequest_headers()` for the async path),
which `HTTPChatModel` calls on every request. `sajha/ai/llm/cloud_auth.py` has cached,
refresh-before-expiry token sources for Google (service-account files, workload identity)
and Microsoft Entra ID (client secret, workload identity, managed identity); the Gemini and
Anthropic providers use the first for Vertex AI and Azure OpenAI the second. Never log a
key: `SecretStore.redact()` masks key-shaped strings in any text you must log.

### 2.3 HTTP: `self.http` and the helpers

Do not import a vendor SDK. `self.http` is a lazily built `httpx.Client`
(`build_client` in `sajha/ai/llm/http.py`) with the provider's `base_url`, `auth_headers()`,
`extra_headers`, `proxy`, `verify_tls`/`ca_bundle` and timeouts, and with the `transport=`
that tests inject (section 5); `self.ahttp` is the `httpx.AsyncClient` for the running event
loop, built the same way. Wrap each call in `self.slot()` (or `async with self.aslot()`),
which enforces `max_concurrency`. A model built on `HTTPChatModel` (3.1) gets all of this
without calling the helpers itself. The helpers do the error handling for you:

| Helper (`sajha/ai/llm/http.py`) | Does |
|---|---|
| `post_json(client, url, payload, provider=, model=, classify=)` | POST, map transport failures and 4xx/5xx onto the taxonomy, return the JSON body |
| `get_json(client, url, provider=, timeout=)` | GET with the same mapping |
| `stream_post(...)` | A context manager yielding the streaming response, errors mapped before the first byte |
| `iter_sse(resp)` / `iter_ndjson(resp)` | Parse Server-Sent Events into `(event, data)` pairs / newline-delimited JSON |
| `safe_json_loads(s)` | Parse streamed argument fragments without raising |
| `map_http_error(resp, provider, model)` | The default status mapping (used when `classify` returns `None`) |
| `transport_errors(provider, model)` | Turn `httpx` timeouts and connection errors into `ProviderUnavailable` |
| `apost_json`, `astream_post`, `aiter_sse`, `aiter_ndjson`, `atransport_errors` | The async twins, for `self.ahttp` |

### 2.4 Errors: map onto the taxonomy

The governed model decides whether to retry, fall back or give up by the **type** of the error, so
every failure a model or provider raises must be one of SAJHA's (`sajha/ai/llm/errors.py`).
An exception that is not an `LLMError` is not caught by the governed model's fallback: it escapes
the governed model and ends the ask with an error instead of trying the next candidate.

`map_http_error` handles the common cases by status. Give the helpers a `classify` callable
for what only your service's body says:

```python
# sajha/examples/intelligence/acme_provider.py
FAULTS = {"quota": RateLimited, "auth": AuthenticationFailed, "too_long": ContextTooLong,
          "policy": ContentFiltered, "busy": ProviderUnavailable}


def fault_error(fault: Dict[str, Any], provider: str, model: str = "", status: Optional[int] = None,
                retry_after: Optional[float] = None) -> Optional[LLMError]:
    cls = FAULTS.get(str(fault.get("kind") or ""))
    if cls is None:
        return None                      # unknown kind: let map_http_error decide by status
    # ...
```

```python
# sajha/examples/intelligence/acme_provider.py
    def classify(self, resp: httpx.Response) -> Optional[LLMError]:
        """post_json/stream_post call this on a 4xx/5xx before the generic status mapping."""
        try:
            fault = (resp.json() or {}).get("fault") or {}
        except Exception:
            return None
        retry_in = resp.headers.get("x-acme-retry-in")
        return fault_error(fault, self.name, status=resp.status_code,
                           retry_after=float(retry_in) if retry_in else None)
```

| Acme says | Default status mapping | SAJHA error | Gateway reaction |
|---|---|---|---|
| 429, `quota` (+ `x-acme-retry-in`) | 429, or 400/403 mentioning rate limit or quota | `RateLimited(retry_after=...)` | retry after the delay (capped by `ai.retry.max_retry_after_s`), then the next candidate; counts toward the circuit breaker |
| 503, `busy`; timeouts; connection refused | 5xx, 408, 409, transport errors | `ProviderUnavailable` | retry with backoff, then the next candidate; counts toward the breaker |
| 401, `auth` | 401, 403 | `AuthenticationFailed` | no retry; the provider is marked down for `ai.gateway.health_ttl_s`; next candidate |
| 400, `too_long` | 413, or a 4xx mentioning context length | `ContextTooLong` | next candidate (one with a larger window, if listed) |
| 404 (unknown model) | 404 | `UnsupportedFeature` | next candidate |
| 451, `policy` | a 4xx mentioning a content filter, safety or guardrail | `ContentFiltered` | raised: no retry, no fallback |
| anything else 4xx | other 4xx | `InvalidRequest` | raised: no retry, no fallback |
| a 200 whose generation failed (Gemini `MALFORMED_FUNCTION_CALL`, Cohere `ERROR`) | — | `ModelFailed` | next candidate; not counted toward the breaker |

Rules: set `provider=` (and `model=` where known) on every error; set `retry_after` when the
service says how long to wait; never raise `RateLimited` or `ProviderUnavailable` for a
request that can never succeed (it would be retried). Inside a stream, the governed model falls back
only before the first event; an error after that reaches the caller, so map mid-stream faults
too (the `fault` event in `AcmeStreamTranslator.feed`).

### 2.5 Models and the catalogue

`list_models()` builds the provider's model list in this order, each later source
overriding the earlier for the same id:

1. the curated rows in `sajha/ai/llm/catalog.py` for `catalog_key` (built-in vendors; an
   out-of-tree provider leaves it empty);
2. `live_models()`, which you override to discover models from the service (and, as Acme
   does, to declare the models you know);
3. model classes registered with `@register_model` for this provider (section 3.6);
4. the `llm_models` table (the AI settings page);
5. the `models:` list in the provider's config (`SAJHA_AI_ACME_MODELS` as JSON), which can
   add a model, change its capabilities and prices, or hide it with `enabled: false`.

The result is cached for `live_models_ttl_s`. A model id found nowhere gets
`unknown_model_capabilities`. When an alias names only the provider (`acme`), the factory
uses `default_chat_model_id()`: `config.default_model`, else the catalogue's default, else the
first chat model listed.

```python
# sajha/examples/intelligence/acme_provider.py
    def live_models(self) -> List[ModelDescriptor]:
        """Merged by ProviderBase.list_models() under config `models:` overrides."""
        known = {d.id: d for d in KNOWN_MODELS}
        if not self.config.live_models:
            return list(known.values())
        try:
            data = get_json(self.http, "/v1/models", provider=self.name, timeout=self.config.health_timeout_s * 3)
        except Exception:
            return list(known.values())                    # unreachable: still list what we know
        out = dict(known)
        for m in data.get("models") or []:
            if m.get("id") in known:
                continue                                   # our curated capabilities and prices win
            flags = {FEATURES[f]: True for f in m.get("features") or [] if f in FEATURES}
            # ...
            out[m["id"]] = ModelDescriptor(m["id"], caps, kind=m.get("kind") or "chat", source="live")
        return list(out.values())
```

If some listed models may be absent at run time (Ollama lists only pulled models), also
define `model_available(model_id) -> bool`; the governed model skips a candidate for which it
returns `False`.

### 2.6 Health and lifecycle

`health()` returns a `HealthStatus` (`ok`, `degraded` or `down`). The governed model calls it when
choosing candidates and caches the answer for `ai.gateway.health_ttl_s`, so keep it bounded
by `health_timeout_s`. The base implementation reports disabled, not configured and missing
key without any I/O; call it first:

```python
# sajha/examples/intelligence/acme_provider.py
    def health(self) -> HealthStatus:
        """The factory caches this for ai.gateway.health_ttl_s; keep it cheap and bounded."""
        base = super().health()                            # disabled, not configured, no key
        if not base.ok:
            return base
        try:
            data = get_json(self.http, "/v1/health", provider=self.name, timeout=self.config.health_timeout_s)
        except Exception as e:
            return HealthStatus("down", f"{self.base_url} unreachable ({e.__class__.__name__})")
        status = data.get("status") if isinstance(data, dict) else None
        return HealthStatus("ok" if status == "ok" else "degraded", f"{self.base_url}: {status}")
```

A cloud API with no health endpoint can keep the default (configured or not); a probe that
costs tokens is never a good health check. `close()` closes `self.http`; override it (and
call `super().close()`) if the provider holds anything else, such as a session or a thread.
The factory closes every provider when it is rebuilt.

### 2.7 Registration: three ways

All three validate the class (a concrete `LLMProvider` subclass, usually of `ProviderBase`,
with a `name` and a pydantic `config_model`; a class that leaves an abstract method
unimplemented is refused) and fail at startup with a clear message. `GET /api/ai/registry` (admin)
lists what is registered.

**1. The decorator**, on a class in a module that is imported before the factory is built.
This is how the built-in providers register (`sajha/ai/llm/providers/__init__.py` imports each
one); for your own code it needs one of the other two ways to get imported.

```python
# sajha/examples/intelligence/acme_provider.py
@register_provider
class AcmeProvider(ProviderBase):
    name = "acme"                                          # the registry key and the config section
    config_model = AcmeConfig
    requires_key = True                                    # enabled: auto -> on when a key resolves
    default_base_url = "https://llm.acme.internal"
```

**2. A class path in `application.yml`** — no packaging, the module only has to be importable:

```yaml
ai:
  providers:
    - name: acme
      class: sajha.examples.intelligence.acme_provider:AcmeProvider   # or your_package.module:Class
      config:
        enabled: true
        tenant: risk
        # the key comes from ACME_LLM_KEY (vendor_env) or SAJHA_AI_ACME_API_KEY, never this file
```

The same class can be configured twice under different names (`name: acme_eu, class: ...`);
`type: acme` instead of `class:` reuses a provider that is already registered.

**3. An entry point** in the `sajha.llm_providers` group, for a provider shipped as its own
pip package. SAJHA loads the group at startup (unless `ai.gateway.load_entry_points` is
false); the entry point's name becomes the registry name.

```toml
# pyproject.toml of your package
[project.entry-points."sajha.llm_providers"]
acme = "acme_sajha.provider:AcmeProvider"
```

A provider registered by an entry point exists (disabled) without any YAML: enabling it is
`SAJHA_AI_ACME_ENABLED=true` alone.

### 2.8 Enabling it and pointing an alias at it

A provider is used only when it is enabled, healthy, and named by the alias the caller
asks for. Ask SAJHA uses `ai.ask.model`, which is `default`:

```bash
export SAJHA_AI_ACME_ENABLED=true                          # or enabled: true in its config
export ACME_LLM_KEY=...                                    # or SAJHA_AI_ACME_API_KEY, or api_key_ref
export SAJHA_AI_ALIASES_DEFAULT="acme,mock/mock-planner"   # Acme first; the mock if Acme is down
```

Then check `GET /api/ai/config`: `active_providers` includes `acme`, `resolved_aliases.default`
is `acme/acme-large`, `mock_active` is `false`, and `build_errors` is empty. A bare provider
name in an alias means its default model; `acme/acme-small` names one model.

---

## 3. Writing a model

A model is a subclass of `ChatModel` or `EmbeddingModel` (`sajha/ai/llm/model.py`, imported
from `sajha.ai.llm.spi`), the shared implementations of the abstract `LLMModel`. The
provider creates it with `(provider, model_id, capabilities, **options)`; the model reads its
provider's config and client through `self.provider`.

Models are written against the **canonical format**: the OpenAI Chat Completions request,
response, stream-chunk and embeddings shapes, as pydantic models in
`sajha/ai/llm/canonical.py` (`ChatCompletionRequest`, `ChatMessage`, `ToolDefinition`,
`ChatCompletion`, `ChatCompletionChunk`, `EmbeddingsResponse`, ...). A request stripped of
its `sajha` field is a valid OpenAI request; a response stripped of `sajha` is a valid OpenAI
response. Which fields are supported, passed through or refused is settled in
[LLM Tools §13.6](LLM%20Tools.md#136-field-coverage); a model only translates.

### 3.1 The `ChatModel` contract

Callers use the OpenAI-style methods, which the base class implements; a model implements
the hooks underneath them.

| Method | Who | Contract |
|---|---|---|
| `chat_completions_create(request=None, **fields) -> ChatCompletion` | base class | `prepare` (below), then `_create`, then SAJHA's markers on `sajha` (provider, qualified model, cost from the declared prices, latency, `ignored`, `usage_estimated`, `structured_output`). Makes `n` calls and merges the choices when the model has no native `n`. |
| `chat_completions_stream(...) -> Iterator[ChatCompletionChunk]` | base class | `_stream`, with one id and `created` on every chunk and a usage chunk (empty `choices`) last, estimated and marked when the vendor sends none. A model without streaming answers in one content chunk. |
| `achat_completions_create` / `achat_completions_stream` | base class | The async twins: `_acreate` / `_astream`. |
| `prepare(request) -> Prepared` | base class | The refusals of §13.6 (`InvalidRequest` naming the field), then the model's declared capabilities: an undeclared feature raises `UnsupportedFeature` (the governed model's next candidate); `temperature`/`top_p` on a model without sampling controls are left out and listed in `sajha.ignored`; `json_schema` on a model with JSON mode but no schema output is emulated (JSON mode, the schema in the instructions, validation, one retry). |
| `_create(request) -> ChatCompletion` | **you** | One call, one choice (or `n` when the model declares native `n`). Raise only SAJHA errors. |
| `_stream(request) -> Iterator[ChatCompletionChunk]` | you, optional | Default: the answer of `_create` replayed as chunks. |
| `_acreate` / `_astream` | you, optional | Default: `_create` / `_stream` on a worker thread. |
| `count_tokens(request)` | optional | About four characters per token; override if the service can count exactly. |

**Over HTTP, write three pure functions instead.** `HTTPChatModel`
(`sajha/ai/llm/adapter.py`) implements `_create`, `_stream`, `_acreate` and `_astream` — sync
and native async, Server-Sent Events or NDJSON (`stream_format`), `slot()` / `aslot()`,
per-request `request_headers()` — on top of:

| Hook | Translates |
|---|---|
| `wire(request, stream) -> WireCall(path, body, params)` | the canonical request to the vendor's request |
| `parse(data, request) -> ChatCompletion` | the vendor's reply to the canonical response |
| `translator(request) -> StreamTranslator` | the vendor's stream events to chunks: `feed(event, data)` returns chunks (helpers `text()`, `tool_start()`, `tool_args()`); set `finish`, `usage`, `refusal`, `state` as they arrive; `close()` emits the finishing chunk and the usage chunk |
| `classify(resp)` | optional: a vendor error body to a SAJHA error |

Because the three are pure, they can be checked against recorded vendor payloads with no
network (section 5.1). Acme's:

```python
# sajha/examples/intelligence/acme_provider.py
def to_acme_body(request: ChatCompletionRequest, *, model: str, safety: str, max_tokens: int,
                 temperature: Optional[float], stream: bool) -> Dict[str, Any]:
    """Pure translation (golden-testable): canonical request -> Acme's /v1/generate body."""
    turns: List[Dict[str, Any]] = []
    for m in request.messages:
        if m.role in ("system", "developer"):
            continue                                       # joined into "system" below
        if m.role == "user":
            turns.append({"speaker": "user", "text": m.text})
        elif m.role == "assistant":
            turns.append({"speaker": "assistant", "text": m.text or m.refusal or "",
                          "calls": [{"call_id": c.id, "function": c.function.name, "args": c.function.args()}
                                    for c in m.tool_calls or []]})
        elif m.role == "tool":                             # one turn per tool result
            turns.append({"speaker": "tool", "call_id": m.tool_call_id, "result": m.text, "error": m.is_error})
```

```python
# sajha/examples/intelligence/acme_provider.py
class AcmeStreamTranslator(StreamTranslator):
    """Acme's SSE events -> chat.completion.chunk objects (close() adds the finish and usage chunks)."""

    def feed(self, event: str, data: Any) -> List[ChatCompletionChunk]:
        ev = safe_json_loads(data)
        if event == "text":
            return self.text(ev.get("delta") or "")
        if event == "call":
            i = int(ev.get("index") or 0)
            if i not in self._calls:
                return self.tool_start(i, ev.get("call_id") or "", ev.get("function") or "",
                                       ev.get("args_fragment") or "")
            return self.tool_args(i, ev.get("args_fragment") or "")
        if event == "fault":                               # an error after the stream started
            raise (fault_error(ev, self.model.provider.name, self.model.id)
                   or ProviderUnavailable(f"acme: {ev}", provider=self.model.provider.name, model=self.model.id))
        # ...
```

```python
# sajha/examples/intelligence/acme_provider.py
class AcmeChatModel(HTTPChatModel):
    """wire / parse / translator; HTTPChatModel does the I/O (sync, native async, streaming)."""

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        return WireCall("/v1/generate", to_acme_body(request, model=self.id, safety=self.provider.config.safety,
                                                     max_tokens=self.effective_max_tokens(request),
                                                     temperature=self.effective_temperature(request),
                                                     stream=stream))
```

Helpers for subclasses: `effective_max_tokens(request)` (request, then provider default,
then the model's cap) and `effective_temperature(request)` (`None` when the model takes no
temperature; `prepare` has already recorded a dropped one in `sajha.ignored`).

**`EmbeddingModel`** implements `_embed(texts, purpose, dimensions)` and returns the vectors
(or `(vectors, prompt_tokens)` when the vendor reports usage); callers use
`embeddings_create(model=, input=, dimensions=, encoding_format=, sajha={input_purpose})`.
`purpose` is `query`, `document` or `None` — map it to the vendor's input type where it has
one (Cohere `input_type`, Gemini `taskType`). `dimensions` is refused before `_embed` unless
the model declares `variable_dimensions`; `base64` encoding is done by the base class.

**Models written against the original interface** (`generate(ChatRequest) -> ChatResponse`, optionally `stream`
yielding `TextDelta`/`ToolCallDelta`/`UsageEvent`/`Done`, and `embed(texts)`) keep working:
the base class converts at the boundary (`sajha/ai/llm/convert.py`, lossless for everything
the old types express).

### 3.2 Capabilities and how the governed model uses them

`ModelCapabilities` is a frozen dataclass declared per model (in a catalogue row, a
`ModelDescriptor`, a registered class or a `models:` override); `ModelInfo` (what
`provider.models()` and `llm_factory().models()` return, like `GET /v1/models`) carries it. The
governed model trusts it: a request a model cannot honour is refused by that model and goes to the
alias's next candidate, never sent with the feature quietly dropped.

| Field | Used for |
|---|---|
| `tools`, `vision` | Capability matching: the governed model's `request_needs` skips a candidate that lacks one ("lacks [...]" in the `NoModelAvailable` message). |
| `structured_output` | Native `response_format: json_schema`. |
| `json_mode` | `response_format: json_object`; with `structured_output` false, `json_schema` is emulated. Default: same as `structured_output`. |
| `forced_tool_choice` | `tool_choice: "required"`. `false`: refused (Ollama has no tool choice at all). |
| `named_tool_choice` | `tool_choice: {function: {name}}`. Default: same as `forced_tool_choice`. Without it, a named choice is accepted only when that tool is the only one offered (sent as "required"), as for Cohere. |
| `parallel_tool_control`, `strict_tools`, `seed`, `stop_sequences`, `reasoning_effort`, `native_n` | The request fields of the same names; refused when false (`n` > 1 without `native_n` becomes `n` calls). |
| `temperature` | `false`: the model takes no sampling controls; `temperature` and `top_p` are left out and listed in `sajha.ignored`. |
| `tags` | Matched by `needs=` (for example `needs="fast"`). `deterministic` makes a response cacheable without `temperature: 0`. |
| `context_window`, `max_output_tokens` | A caller's minimum context; the default output cap. |
| `input_cost_per_mtok`, `output_cost_per_mtok` | `sajha.cost_usd` and the usage ledger. |
| `streaming` | `false` (or the provider's `streaming: false`): one content chunk. |
| `embedding`, `dimensions`, `variable_dimensions` | Embedding models. |

The canonical-format flags (`json_mode` to `variable_dimensions`) left unset take the
provider's `feature_defaults` (`"tagged"` means: models tagged `reasoning`), then the
defaults above; a `models:` entry can set any of them per model. A provider can also
override `resolve_capabilities` to state what no model of it can do (Ollama does, for tool
choice).

Declare what the model really does. A model that claims `structured_output` but returns
prose breaks Ask SAJHA's synthesis step; one that claims `tools` but ignores them answers
from recall (confidence 0.5).

### 3.3 Tool calls, results, refusals and state

| Canonical | Direction | Acme wire form |
|---|---|---|
| `tools: [{type: function, function: {name, description, parameters}}]` | request | `functions: [{name, doc, params}]` |
| `tool_choice`: `auto`, `none`, `required`, `{type: function, function: {name}}` | request | `function_mode`: `auto`, (omit functions), `any`, the name |
| assistant `tool_calls: [{id, type: function, function: {name, arguments}}]` | response, and echoed in later requests | `output.calls: [{call_id, function, args}]`; history turn `{speaker: assistant, calls}` |
| `{role: tool, tool_call_id, content}` (`sajha.is_error`, `sajha.tool_name`) | request | one `{speaker: tool, call_id, result, error}` turn per result |
| `finish_reason: content_filter` with `message.refusal` | response | `stop: blocked` |

Rules the ask loop relies on:

- `function.arguments` is a **JSON string**, as in OpenAI. A service that returns objects is
  serialised (`ToolCall.of(id, name, arguments)` accepts either); `call.function.args()`
  parses it back (a broken string becomes `{"_raw": ...}` rather than raising).
- Every call has an **id**, unique within the response. If the service has none, synthesise
  a stable one (Ollama's adapter does: `ocall_<n>_<name>`); results are matched to calls by it.
- A tool result's `content` is text; `sajha.structured` marks JSON text of a structured value
  (Gemini and Bedrock send it as an object), `sajha.is_error` an error result (send it where
  the service has a place for it, else prefix `ERROR: `), `sajha.tool_name` the tool's name.
- `finish_reason` is one of `stop`, `length`, `tool_calls`, `content_filter` (`tool_calls`
  whenever there are tool calls). A refusal is `content_filter` with `message.refusal` set,
  never an empty answer; a vendor's "the generation failed" finish raises `ModelFailed`.
- State the service needs echoed on the next turn (Anthropic's thinking blocks, Gemini's thought
  signatures) goes on the assistant message as `sajha.provider_state` with
  `sajha.provider` set to your provider's name; `message.state_for(provider)` returns it only
  to the same provider. It is excluded from every dump and never logged.

### 3.4 Structured output

`response_format: {type: json_schema, json_schema: {name, schema, strict}}` asks for a reply
that matches a JSON Schema; `{type: json_object}` for any JSON object. Map them onto the
service's JSON mode (`json_schema` for Acme; `output_config.format` for Anthropic;
`responseJsonSchema` for Gemini; `format` for Ollama) and return the JSON as the message
text; `ChatCompletion.parsed()` parses it, tolerating code fences. Declare what the service
enforces: `structured_output` for a schema, `json_mode` for JSON without one (SAJHA then
emulates the schema and marks the response `sajha.structured_output: "emulated"`), neither
if it has no JSON mode (structured-output requests go to another candidate).

### 3.5 Usage and cost

Return the service's token counts as `usage` (`CompletionUsage.of(prompt, completion,
cached, reasoning)`); the base class applies the model's prices to `sajha.cost_usd`. The
governed model records usage per user, role, provider and model, enforces `ai.budgets` and each
role's `daily_tokens` from it, and Ask SAJHA enforces `ai.ask.max_tokens` per question from
it. When the service reports none, leave `usage` unset: the base class estimates it and sets
`sajha.usage_estimated`. Responses served from the response cache report zero usage.

### 3.6 Adding a model to an existing provider

**Without code.** A model id that only differs in capabilities or prices is configuration:

```yaml
ai:
  providers:
    - name: openai
      config:
        enabled: true
        models:
          - { id: "ft:gpt-6.1-sol:acme:risk:001", tools: true, structured_output: true,
              context_window: 1050000, input_cost_per_mtok: 3.0, output_cost_per_mtok: 12.0, tags: [risk] }
```

**With code**, when the model must behave differently: subclass the provider's model class
and register it for one `provider/model` id with `@register_model`. The provider's
`chat_model()` builds your class for that id, and `list_models()` lists it with the class's
`capabilities` (a `models:` entry can still override them).

```python
# sajha/examples/intelligence/custom_models.py
@register_model(provider="openai", model_id=RISK_MODEL)
class AcmeRiskModel(OpenAIChatModel):
    """The risk team's fine-tune: a house style prepended to every system prompt, a fixed seed."""

    capabilities = ModelCapabilities(
        tools=True, structured_output=True, vision=False, streaming=True,
        context_window=1_050_000, max_output_tokens=32_000,
        input_cost_per_mtok=3.00, output_cost_per_mtok=12.00,     # fine-tune prices, not the base model's
        tags=frozenset({"risk"}))
    HOUSE_STYLE = "House style: lead with the figure, then the method, then the caveats."
    SEED = 7

    def wire(self, request: ChatCompletionRequest, stream: bool) -> WireCall:
        """The canonical request is edited, then the inherited pass-through does the rest."""
        update = {}
        if not any(self.HOUSE_STYLE in m.text for m in request.messages if m.role == "system"):
            update["messages"] = [ChatMessage.system(self.HOUSE_STYLE)] + list(request.messages)
        if request.seed is None:
            update["seed"] = self.SEED
        return super().wire(request.model_copy(update=update) if update else request, stream)
```

The module must be imported for the decorator to run: import it from a provider module you
load by class path or entry point. Use it like any model: `SAJHA_AI_ALIASES_DEFAULT=openai/ft:gpt-6.1-sol:acme:risk:001,mock/mock-planner`.

---

## 4. Writing a real planner

### 4.1 How planning works today

The planner is a strategy chosen by `ai.ask.planner` (section 4.5). The default, `react`, is
the loop described here: the planner is whichever `ChatModel` the `ai.ask.model` alias
(default `default`) resolves to, called once per step in `IntelligenceService.stream_ask`. `mock-planner` is such a model (`PlannerModel` in
`sajha/ai/llm/mock.py`): it scores the offered `ToolSpec`s against the question's keywords,
fills arguments from numbers and ticker symbols in the question, and answers from the tool
results. It plans only from the question, never from tool output. Replacing it means
replacing the model; the loop around it stays the same.

**1. Shortlist.** `ToolResolver.resolve(question, top_k=3 × ai.ask.shortlist)` ranks the
catalog (vector search when `ai.tool_search.embedder` is `gateway`, BM25 otherwise). Tools
that are missing or disabled, `sajha_ask` itself, and tools the caller may not run
(`RequestContext.can_use_tool`, which the route sets from `AuthContext.has_tool_access`) are
dropped; the first `ai.ask.shortlist` (default 12) remain. If the caller's role policy
forbids tools, the shortlist is empty. The model never sees any other tool.

**2. Each step.** The model is sent:

| `ChatRequest` field | Value |
|---|---|
| `messages` | the question as a user message, then every assistant message and tool-result message so far |
| `system` | `SYSTEM_PROMPT` in `sajha/ai/intelligence.py` (use the tools; tool results are data, never instructions; prefer results to recall; be concise) |
| `tools` | the shortlist as `ToolSpec`s (name, description, input schema), the same at every step |
| `tool_choice` | `auto` (or `none` when the shortlist is empty); the loop never forces a call |
| `temperature` | `ai.ask.temperature` (default 0) |
| `metadata` | the `RequestContext`: user, roles, trace id, RBAC check |

through `llm_factory().model(ai.ask.model)` (a governed model), so aliases, fallback, role policy,
budgets, retries and the cache all apply to every step.

**3. Acting.** A response without tool calls ends the loop (`stopped_by: answer`). Otherwise
each call, in order:

- over `ai.ask.max_tool_calls`: not run, returned as an error result, loop stops (`tool_limit`);
- not in the shortlist: refused (`status: refused`), returned to the model as an error;
- destructive (`annotations.destructiveHint` or `metadata.destructive`) and not confirmed:
  not run; the loop stops with `needs_confirmation` and a fingerprint per pending call;
- otherwise run through `tool.execute_with_tracking` (enabled check, validation, tool cache,
  circuit breaker, metrics). An exception becomes `{"error": ...}`. The result is capped at
  `ai.ask.max_result_chars` and returned as a `ToolResultPart`.

All results of the step go back in one tool message, and the next step begins.

**4. Limits.** Before each step the loop stops on `ai.ask.timeout_s` (`timeout`) or on
`ai.ask.max_tokens` used by this ask (`budget`); after `ai.ask.max_steps` steps it stops with
`step_limit`. A model error ends the loop with `error`. These are checked between model
calls, not during one.

**5. Synthesis.** If any tool ran and `ai.ask.synthesize` is true, one more call sends the
same history (minus a trailing text-only answer) with `SYNTH_PROMPT`, no tools and
`response_schema` `ASK_SCHEMA` (`answer`, `citations`, `caveats`), with
`needs="structured_output"`. Citations are filtered to successful calls. If the call fails,
the loop's last text is the answer.

**6. Confidence** comes from the composition framework over the cited tool results, never
from the model (see the [Intelligence Layer](Intelligence%20Layer.md#6-the-intelligence-service)).
An answer that rests on no tool result scores 0.5.

**7. Events.** `stream_ask` yields `shortlist`, then per step `model`, `tool_call`,
`tool_result` (and `needs_confirmation`), then `answer_delta`, `answer`, `confidence` and
`done`. The schema is fixed and is what the Ask SAJHA page renders; a planner that plans ahead
adds an optional `plan` event.

With conversation memory (a `conversation_id` on the ask), `messages` starts with the earlier
turns and the question is the standalone rewrite; `system` carries the summary of older turns.

So "the planner" decides only one thing, at each step: answer now, or call which of the
offered tools with which arguments. There are three ways to make that decision real.

### 4.2 Choosing an approach

| | 4.3 A real tool-capable model | 4.4 A strategy written as a model | 4.5 A `Planner` |
|---|---|---|---|
| Code | none | a `ChatModel` (and a small provider) | a `Planner` class, or configuration of a built-in one |
| Plans | open questions, adaptively | the questions you wrote recipes for | anything: ReAct, plan-then-execute, recipes, routing, hybrids |
| Sees | the question, tool specs, results | the same, one step at a time | the whole ask state, scores, remaining limits |
| Status | works | works | built: `react`, `plan_execute`, `recipes`, `router` ship |

### 4.3 A real model as the planner

Any model with `tools` and `structured_output` can plan. Enable its provider, give it a key,
and put it first in the alias Ask SAJHA uses (keep `mock/mock-planner` last only if a
canned answer is better than an error when the vendor is down):

**Anthropic**

```bash
export SAJHA_AI_ANTHROPIC_ENABLED=true
export ANTHROPIC_API_KEY=...
export SAJHA_AI_ALIASES_DEFAULT="anthropic/claude-sonnet-5-5,anthropic/claude-haiku-4-5"
# harder questions: SAJHA_AI_ALIASES_REASONING="anthropic/claude-opus-5-5" and SAJHA_AI_ASK_MODEL=reasoning
```

**OpenAI**

```bash
export SAJHA_AI_OPENAI_ENABLED=true
export OPENAI_API_KEY=...
export SAJHA_AI_OPENAI_STRICT_SCHEMA=true          # strict json_schema: ASK_SCHEMA is strict-compatible
export SAJHA_AI_ALIASES_DEFAULT="openai/gpt-6.1-sol,openai/gpt-6-luna"
```

**Ollama** (local, keyless)

```bash
ollama pull qwen3                                   # a model Ollama reports as tool-capable
export SAJHA_AI_OLLAMA_ENABLED=true
export SAJHA_AI_OLLAMA_NUM_CTX=32768                # the shortlist's schemas and results need room
export SAJHA_AI_ASK_TIMEOUT_S=180                   # local models are slower per step
export SAJHA_AI_ALIASES_DEFAULT="ollama/qwen3,mock/mock-planner"
```

Model ids, context windows and prices are curated in `sajha/ai/llm/catalog.py` (rows tagged
`reasoning`, `fast` and `cheap` are the obvious picks for the `reasoning` and `fast` aliases);
they change often, and a `models:` entry overrides any of them. For Ollama the live list of
pulled models and their detected capabilities wins: pick one whose `GET /api/ai/models` entry
has tools. Then confirm with `GET /api/ai/config` that `resolved_aliases.default` names your
model and `mock_active` is `false`; the *Mock model active* pill disappears from Ask SAJHA.

What to watch:

| Concern | What happens | What to do |
|---|---|---|
| Role policy | The shipped `ai.policy.roles.viewer` allows only `mock/*` and no tools, so viewers keep getting the mock | Grant roles the models they may use in `ai.policy.roles` |
| Synthesis needs structured output | The synthesis call needs `structured_output`; if your model lacks it, the next candidate in the alias writes the final answer (which may be `mock-planner`) | Use a model with structured output, put another capable one second, or set `ai.ask.synthesize: false` |
| Tool-call reliability | Calls to tools not offered are refused; bad arguments come back as tool errors the model may correct within the step and call limits; a model that answers from recall scores 0.5 | Prefer models tagged for tool use; keep `max_steps` small; watch `stopped_by` and the `ai_ask` audit entries |
| Cost | Every step resends the system prompt, all shortlisted schemas and the history; synthesis is one more call | Tune `ai.ask.shortlist`, `max_result_chars`, `max_steps`, `max_tokens`; set `ai.budgets`; put a `fast`/`cheap` model in `default` and a `reasoning` one behind `ai.ask.model` only where needed |
| Latency | Steps and the tool calls inside a step run one after another; the answer is shown after synthesis, not token by token | A fast model for `default`; fewer steps; `synthesize: false` saves a call (citations become every successful call) |
| The response cache | Ask calls run at temperature 0, so the governed model caches each step for `ai.cache.ttl_seconds`; an identical question with identical tool results replays the cached decisions at zero token cost | Expected; disable `ai.cache` while comparing prompts or models |
| Prompt injection | A real model reads tool results, which may contain instructions. The system prompt says results are data; only shortlisted tools run; destructive tools wait for confirmation; RBAC filters the shortlist | Mark every write tool `destructiveHint: true`; keep tool permissions tight per role; keep `ai.ask.mcp_allowed_tools` narrow; review the tool-call chips and the audit log |
| Timeout | `timeout_s` is checked between steps, so one slow call can overrun it | Bound each call with the provider's `read_timeout_s` |

### 4.4 A custom strategy, written as a model (works today)

Because the loop only asks the model "answer, or call which tools?", a strategy can be a
`ChatModel` that decides without an LLM, or with one it calls itself. The example
`RecipePlannerModel` implements `_create` on the canonical request and answers known
question shapes with fixed recipes: a regular expression
over the question, a tool, and arguments from the expression's named groups. A question no
recipe matches raises `UnsupportedFeature`, which the governed model treats as "try the next
candidate", so a real LLM behind it handles everything else:

```python
# sajha/examples/intelligence/recipe_planner.py
        recipe, match = self.provider.find(question)
        if recipe is None:
            raise UnsupportedFeature("no recipe matches this question", provider=self.provider.name, model=self.id)
        calls, results = self._since_question(request)
        if not calls:                                  # step 1: plan
            offered = {t.name: t for t in request.tools or []} if request.wants_tools else {}
            spec = offered.get(recipe.tool)
            if spec is None:                           # not shortlisted, or the caller may not run it
                raise UnsupportedFeature(f"recipe {recipe.name}: {recipe.tool} was not offered",
                                         provider=self.provider.name, model=self.id)
```

```yaml
ai:
  providers:
    - name: recipes
      class: sajha.examples.intelligence.recipe_planner:RecipeProvider
      config:
        enabled: true
        recipes:
          - name: pct
            tool: calc_percentage_change
            match: 'percentage change from (?P<old_value>[\d.,]+) to (?P<new_value>[\d.,]+)'
            answer: 'From {old_value} to {new_value} is a change of {percentage_change}%.'
  aliases:
    default: [recipes, anthropic, mock/mock-planner]
```

Everything the loop guarantees still holds, because the strategy can only return tool calls
for the loop to run: it sees only the shortlist, so RBAC holds; destructive tools still wait
for confirmation; the limits, the synthesis, the confidence and the events are unchanged.
Its limits: it decides one step at a time, sees no shortlist scores or remaining budget, and
cannot add events of its own. Those are what 4.5 adds.

### 4.5 A `Planner` extension point

`ai.ask.planner` names the strategy that decides each step of an ask. Most strategies are
**planner files** (`config/planners/<name>.yaml`, a bounded graph of stages, section 4.6 and the
[Planner Reference](Planner%20Reference.md)); a strategy the stage library cannot express is a
Python `Planner`, described here. `sajha/ai/planners.py` holds the protocol and the Python
registry; `sajha/ai/planners_engine/registry.py` resolves a name to a file or a Python planner.
The four built-in strategies ship as files; their Python classes stay in `sajha/ai/planners.py`
and run instead when `ai.planners.python_builtins` is true (their behaviour is in the
[Intelligence Layer](Intelligence%20Layer.md#planners)).

**The split.** The service keeps everything that protects the caller; the planner only
decides.

| Stays in `IntelligenceService` | The planner's job |
|---|---|
| the shortlist and its RBAC filter; policy without tools | what to do next: answer, or which calls |
| refusing calls to tools not offered | whether to plan once, step by step, or by recipe |
| destructive-tool confirmation and fingerprints; policy approval | how to use a model (or several, or none) |
| running tools through `execute_with_tracking` (independent calls in parallel), result caps | re-planning after a failed call |
| `max_steps`, `max_tool_calls`, `max_tokens`, `timeout_s` | whether to synthesise the final answer |
| synthesis, confidence, audit, the event stream, conversation memory | |

**The protocol.** One planner instance serves one ask, so it may keep state:

| Piece | What it is |
|---|---|
| `Planner.start(state)` | called once before the first step; may plan up front |
| `Planner.next_action(state)` | called before every step; returns an action |
| `CallTools(calls, message=None, parallel=False)` | run these canonical `ToolCall`s (`ToolCall.of(id, name, arguments)`); `parallel=True` says they are independent, so the service runs them together |
| `Answer(text, synthesize=True, message=None, stopped_by="answer", citations=None, caveats=[])` | stop; synthesise the answer from the history, or use `text` as it is |
| `Emit(event)` | publish an event (a `plan`) and ask again |
| `PlanState` | `question` (the standalone question), `ctx`, `shortlist` (`ShortlistEntry`: name, `tool` as an OpenAI-style `ToolDefinition`, score), `messages` (canonical `ChatMessage`s: earlier turns, the question, every call and result), `steps` (the `AskStep`s so far), `remaining` (`Limits`: steps, tool calls, tokens, seconds), `system`, `temperature`, `chat`, `emit`, `data` (scratch space) |
| `state.request(messages=None, tools=None, schema=None, ...)` | a canonical `ChatCompletionRequest` with the system text first (tools as functions, structured output as `response_format: json_schema`) |
| `state.chat(request, needs=None, model=None)` | sends a canonical request through a governed model bound to the caller (`chat_completions_create`): aliases, role policy, budgets, fallback and the cache apply, tokens count toward the ask, each call emits a `model` event, and the reply is a `ChatCompletion` |
| `state.emit(event)` | queue an event; it is sent, in order, before the step's tool calls |
| `DelegatingPlanner.hand_to(name, state)` | give the rest of the ask to another planner (fallbacks, routing); the chain is reported as `planner` (`router>plan_execute`) |

The planner never touches a tool or a model directly: the service validates every
`CallTools` against the shortlist exactly as for a model's tool calls. A `plan` event has
`planner`, `revision` and `steps` (`id`, `tool`, `arguments`, `depends_on`, `why`, `status`,
`call_id`); give each step the id its `tool_call` will carry, and Ask SAJHA ticks the step off
when that call returns. Keep a callable or list of those dicts in `state.data["plan"]` and the
result's `plan` reports each step's final status.

**A worked example.** `DocsFirstPlanner` answers how-to questions by searching the guides
first and handing the rest of the ask to `react`, which then sees the passages:

```python
# sajha/examples/intelligence/docs_first_planner.py
class DocsFirstConfig(PlannerConfig):
    pattern: str = r"\b(how (do|can) i|configure|set up|enable|what is)\b"
    top_k: int = 3
    then: str = "react"                      # the planner that finishes the ask


@register_planner
class DocsFirstPlanner(DelegatingPlanner):
    name = "docs_first"
    description = "Searches SAJHA's documentation first for how-to questions, then hands over to react."
    config_model = DocsFirstConfig

    def start(self, state: PlanState) -> None:
        self.searched = False
        wants_docs = re.search(self.config.pattern, state.question, re.IGNORECASE) is not None
        if not wants_docs or SEARCH_TOOL not in state.offered:
            self.hand_to(self.config.then, state)        # not a how-to question, or not allowed
```

```python
# sajha/examples/intelligence/docs_first_planner.py
        if not self.searched:
            self.searched = True
            args = {"query": state.question, "top_k": self.config.top_k}
            call = ToolCall.of("docs_1", SEARCH_TOOL, args)
            # ...
            return CallTools([call])
        self.hand_to(self.config.then, state)            # the passages are in state.messages now
        return self.delegate.next_action(state)
```

It only proposes `sajha_search_docs` when the shortlist offered it, but even a planner that
forgot to check could not run it for a caller without access: the service refuses calls to
tools that were not offered.

**Configuration**, following the provider pattern:

```yaml
ai:
  ask:
    planner: router                # a planner file or registered name, or package.module:Class
    planner_config:                # per planner: a file's settings (overlay), or a class's config_model
      recipes:
        recipes:
          - name: pct
            tool: calc_percentage_change
            match: 'percentage change from (?P<old_value>[\d.,]+) to (?P<new_value>[\d.,]+)'
            answer: 'From {old_value} to {new_value} is a change of {percentage_change}%.'
      plan_execute: {max_parallel: 4, max_replans: 1}
      router: {rules: [{match: '\bcompare\b', planner: plan_execute}]}
```

`SAJHA_AI_ASK_PLANNER` overrides the name and `SAJHA_AI_ASK_PLANNER_CONFIG` (JSON) the
settings. An unknown planner or an invalid setting fails at startup. Registration, like
providers: the `@register_planner` decorator on a class imported at startup, a class path in
`ai.ask.planner`, or an entry point in the `sajha.planners` group. An admin can try a planner
on one ask with `"planner": "<name>"` in the `POST /api/ai/ask` body; `GET /api/ai/planners`
lists every planner file and registration. A name defined both by a file and by a Python
registration is refused (P005), except the four built-ins, whose files win unless
`ai.planners.python_builtins` is true.

**Tests.** `tests/ai/test_planners.py` runs every built-in planner through the same safety
tests (`test_contract_*`: answers and event order, RBAC, tools not offered, destructive
confirmation, injected instructions, limits). Add yours to `BUILT_IN` there, or copy the
pattern; the example above is tested in `tests/ai/test_extension_examples.py`.

### 4.6 Planner files and custom stage types

A new strategy is usually a file, not code: write `config/planners/<name>.yaml` from the stage
library (the [Planner Reference](Planner%20Reference.md) owns the format, and
[Tutorial 27](../tutorials/TUTORIAL_27_write_a_planner.md) walks through one), and name it in
`ai.ask.planner` or an LLM tool's `llm.planner`. Two code escape hatches remain, both for
whoever deploys SAJHA (an administrator), both inside the service's enforcement:

- **`kind: python`**: a planner file with `class: package.module:Class` names a Python `Planner`
  (section 4.5), so it gets a version and can be pinned, overlaid and used as a sub-planner.
- **A custom stage type**: a `StageType` subclass registered with `register_stage_type`
  (`sajha/ai/planners_engine/stages.py`). It declares its `name`, its outcomes, the JSON Schema
  of its own settings and whether it calls a model; planner files then use it like a built-in
  type and are validated the same way (P010, P011, P014, P016).

```python
from sajha.ai.planners_engine import StageType, register_stage_type


@register_stage_type
class Escalate(StageType):
    """Ends ``low`` when the provisional confidence is below a threshold, ``ok`` otherwise."""
    name = "confidence_gate"
    fixed_outcomes = ("ok", "low")
    settings_schema = {"type": "object", "properties": {"below": {"type": "number", "minimum": 0, "maximum": 1}}}

    def run(self, rc, frame, st):
        value = rc.lookup(frame)("confidence")
        return "low" if value < float(st.cfg.get("below", 0.6)) else "ok"
```

`run(rc, frame, st)` returns the outcome. It reads state through `rc.lookup(frame)` and writes
built-in slots through `frame.slots`; a stage that needs tool calls is a generator that yields
from `sajha.ai.planners_engine.runtime.run_calls(...)`, and one that needs a model calls
`sajha.ai.planners_engine.stages.model_call` or `structured` (canonical Chat Completions requests
through a governed model bound to the caller). Custom verify checks register with
`register_check(name)` (`sajha/ai/planners_engine/checks.py`) and are then usable in a `verify`
stage's `checks`. Register stage types and checks in a module imported at startup, before the
planner files that use them load.

---

## 5. Testing your extension

### 5.1 The provider contract suite

`tests/ai/test_provider_contract.py` holds every provider to the same behaviour, offline: it
lists models and resolves the default; plain chat with usage; a tool call round trip in the
provider's own wire format; structured output when declared (and `UnsupportedFeature` when
not); streaming in order (deltas, then `UsageEvent`, then `Done`); a streamed tool call;
error mapping for rate limits (with `retry_after`), bad keys, long contexts, server errors,
content filters, connection failures and unknown models, in `generate` and in `stream`;
embeddings where offered; and the key redacted in the effective configuration.

Two more suites hold the canonical format to account:

- **Golden translation tests** (`tests/ai/test_golden_translation.py`) send one set of
  canonical requests (plain chat, developer role, tools and every `tool_choice`, a tool-call
  round trip with parallel calls and an error result, `parallel_tool_calls: false`,
  structured output, JSON mode, images, sampling, reasoning effort, passed-through fields,
  `n`) through each built-in adapter's pure `wire`, and recorded vendor replies and stream
  events (`tests/ai/golden/recorded/`) through `parse` and the stream translator, and compare
  the results with `tests/ai/golden/expected/<provider>.json`. A refusal is recorded as the
  error it raises. After changing a translation, review the diff and regenerate with
  `SAJHA_UPDATE_GOLDEN=1`.
- **The portability suite** (`tests/ai/test_portability.py`) runs canonical requests through
  the mock and every adapter offline and checks that each response is a well-formed Chat
  Completion (it round-trips through the typed model with `sajha` removed), that streams
  have one id, a single finishing chunk and the usage chunk last, that native async works
  for the HTTP providers, and that every feature a model does not declare is refused with
  `UnsupportedFeature` rather than dropped.

**A built-in provider** joins the suite with two edits: a `_<kind>` method on `FakeVendor`
in `tests/ai/fakes.py` that answers like your service (or reuse `openai` if it speaks Chat
Completions), and an entry in `CASES` in `tests/ai/test_provider_contract.py`:
`(fake kind, extra config, model id, check of the chat request, check of the tool-result
request, embedding model or None)`.

**An out-of-tree provider** reuses the suite's test functions with its own harness, as
`tests/ai/test_extension_examples.py` does for Acme:

```python
# tests/ai/test_extension_examples.py
class AcmeHarness(contract.Harness):
    def __init__(self):
        from sajha.examples.intelligence.acme_fake_server import AcmeFakeServer
        self.name, self.model, self.embedding = "acme", "acme-large", "acme-embed"
        self.fake = AcmeFakeServer()
        self.chat_check = lambda r: (r["path"] == "/v1/generate" and r["headers"]["x-acme-key"] == "k"
                                     and r["headers"]["x-acme-tenant"] == "default" and r["body"]["system"] == "Be brief.")
        self.result_check = lambda r: any(t["speaker"] == "tool" and t["call_id"] == "acme_1"
                                          for t in r["body"]["turns"])
        self.provider = registry.provider_class("acme").from_settings(
            "acme", {"enabled": True, "api_key": "k"}, environ={}, transport=self.fake.transport)
```

then calls each `contract.test_*` function with it. Your fake must accept the suite's
question and tool (`calc_percentage_change` with `{"old_value": 80, "new_value": 100}`), reply
"Hello there" to plain chat, and fail on demand in the suite's modes (`rate`, `auth`,
`context`, `server`, `filter`, `notfound`, `connect`).

### 5.2 Offline fakes

- **`httpx.MockTransport`.** `from_settings(..., transport=fake.transport)` for one
  provider, `build_llm_factory(raw, transports={"acme": fake.transport})` for a factory. The
  handler sees every request (path, headers, JSON body), so a test can assert on the wire
  format; `tests/ai/fakes.py` and `sajha/examples/intelligence/acme_fake_server.py` are
  working examples.
- **`make_gateway`** in `tests/ai/conftest.py` builds a factory from an `ai:` dictionary
  alone (no YAML, no database, no process environment) with the mock enabled and retries'
  sleeps recorded instead of slept.
- **`mock-scripted`** plays a fixed sequence of replies, tool calls and errors
  (`gw.providers["mock"].set_script([...])`), for testing the loop's handling of a model
  without writing one.
- **`environ={...}`** and `SecretStore(environ={...})` test settings precedence and secret
  references without touching the real environment.

### 5.3 Through the ask loop

```python
# tests/ai/test_extension_examples.py
    gw = make_gateway({"providers": [{"name": "acme", "class": ACME_CLASS, "config": {"enabled": True}}],
                       "aliases": {"default": ["acme", "mock/mock-planner"]}},
                      environ={"ACME_LLM_KEY": "k"}, transports={"acme": fake.transport})
    r = ask_service(gw).ask(QUESTION, RequestContext(user_id="u"))
    assert r.stopped_by == "answer" and r.models == ["acme/acme-large"], r.to_dict()
```

`ask_service` there is `IntelligenceService(gw, ToolBox(), settings=AskSettings(...),
audit=...)`: `ToolBox` (in `tests/ai/conftest.py`) loads the real offline `calc_*` tools.
`tests/ai/test_ask.py` shows the loop's safety tests (limits, confirmation, injection,
RBAC, event order) to run against a new planner model.

### 5.4 Live tests

Live calls are opt-in. `LIVE` in `tests/ai/test_provider_contract.py` maps a provider to its
key variable; `test_live_provider_tool_round_trip` skips unless that variable is set. Add
yours there (or the same pattern in your package) and run it by exporting the key.

### 5.5 Trying it in Ask SAJHA and over HTTP

The fake Acme server runs as a real HTTP server, so the whole path can be tried without an
LLM:

```bash
python -m sajha.examples.intelligence.acme_fake_server --port 8765     # terminal 1
```

Add the provider to your local `config/application.yml` (2.7, way 2) with
`base_url: http://127.0.0.1:8765`, then:

```bash
export ACME_LLM_KEY=anything                                # the fake accepts any key
export SAJHA_AI_ALIASES_DEFAULT="acme,mock/mock-planner"
python run_sajha_web.py                                        # terminal 2
```

`GET /api/ai/config` should list `acme` as active with `default` resolved to
`acme/acme-large`. In **Ask SAJHA** (`/ask`) ask "What is the percentage change from 80 to
100?": the status line reads "Planning with acme/acme-large" and the tool chain shows
`calc_percentage_change`. Over HTTP:

```bash
curl -s -X POST http://localhost:3002/api/ai/ask -H "X-API-Key: sja_..." \
     -H "Content-Type: application/json" \
     -d '{"question": "What is the percentage change from 80 to 100?"}'
# add  -H "Accept: text/event-stream"  to watch the step events
```

The fake plans only the suite's question; for anything else it says "Hello there". It
proves the wiring, not the intelligence.

---

## 6. Writing a document store

Document search keeps its passages in a store that `ai.rag.store` names (the shipped ones,
`sqlite_vec`, `memory` and `pgvector`, are described in
[Intelligence Layer](Intelligence%20Layer.md#stores)). Another store (a vector database, a search
service) is a subclass of `VectorStore` in `sajha/ai/rag/stores.py`, whose docstrings are the
contract:

| Method | Must |
|---|---|
| `create(options, settings, engine)` (class method) | build the store from its `ai.rag.stores.<name>` options (its `defaults`, overlaid with configuration and `SAJHA_AI_RAG_STORES_<NAME>_<KEY>`; values from the environment arrive as strings) and the `ai.rag` settings; raise `StoreUnavailable` with a reason when it cannot run |
| `probe(options)` (class method) | return None, or why the store cannot run here (cheap; no side effects) |
| `documents()` | return `{(source, document): content hash}`, metadata only |
| `embedder()` | name the embedder of the stored vectors (`""` when empty or keyword-only) |
| `replace_document(source, document, doc_hash, embedder, chunks)` | replace one document's passages atomically; `chunks` may be a generator (the index embeds batch by batch while the store reads it), so read it once and keep no more of it than one write needs; clear the store when `embedder` differs from the stored one; raise `DimensionChanged` when a vector's length differs from the stored ones under the same embedder |
| `delete_document`, `clear` | remove one document, or everything |
| `search(vector, top_k, sources)` | return the `top_k` nearest passages by cosine similarity, best first, as `(StoredChunk, similarity)`, only from `sources` when given |
| `keyword_search(query, top_k, sources)` | the same for the query's words; the default is an in-process BM25 index over `chunks()`, so override it when the store can rank words itself |
| `chunks()` | iterate every passage (vectors may be omitted) |
| `stats()`, `save()`, `load(embedder)`, `close()` | report; persist where needed; release connections and files |

A store is used from the background build and from searches at once, so it must be thread
safe; it should return only the rows asked for, so SAJHA stays small whatever the corpus.

```python
# mypackage/rag_store.py
from sajha.ai.rag.registry import register_store
from sajha.ai.rag.stores import StoreUnavailable, VectorStore


@register_store
class AcmeVectorStore(VectorStore):
    name = "acme"
    defaults = {"url": "http://localhost:9200", "collection": "sajha"}

    @classmethod
    def create(cls, options, settings=None, engine=None):
        try:
            import acme_client
        except ImportError:
            raise StoreUnavailable("pip install acme-client") from None
        return cls(acme_client.connect(options["url"]), options["collection"])

    # documents, embedder, replace_document, delete_document, clear, search,
    # keyword_search, chunks: see the table above
```

Registration, any one of:

- `ai.rag.store: mypackage.rag_store:AcmeVectorStore` (the module is imported on start-up);
- the `@register_store` decorator, in a module SAJHA imports;
- an entry point, so installing the package is enough and `ai.rag.store: acme` selects it:

```toml
# pyproject.toml of your package
[project.entry-points."sajha.rag.stores"]
acme = "mypackage.rag_store:AcmeVectorStore"
```

Settings go under `ai.rag.stores.acme` in `config/application.yml`, secrets in the environment
(`SAJHA_AI_RAG_STORES_ACME_API_KEY`). If the store cannot start, document search falls back to
the memory store and the System Notice `rag.store_fallback` shows your `StoreUnavailable`
message.

**Testing.** `tests/ai/test_rag_store_contract.py` holds the cases every shipped store passes
(documents and hashes, cosine ranking, source filters, keyword ranking, replace, delete, clear,
a failed write leaving the document unchanged, embedder and dimension changes, keyword-only
mode). Add your store to its `make_store` and `STORES` (or copy the cases), and run it.

---

## 7. Checklist before shipping

**Provider**

- [ ] `name` is unique (check `GET /api/ai/registry`); `config_model` subclasses
      `ProviderConfig`; no field holds a secret except through `api_key` / `api_key_ref`.
- [ ] Every failure is a SAJHA error with `provider=` set; `RateLimited` carries
      `retry_after` when the service gives one; mid-stream faults are mapped.
- [ ] Every call goes through `self.http` / `self.ahttp` (so proxy, TLS, timeouts and test
      transports apply) inside `self.slot()` / `self.aslot()`; short-lived tokens come from
      `request_headers()`.
- [ ] `health()` is cheap, bounded by `health_timeout_s`, and never spends tokens.
- [ ] `list_models()` declares honest capabilities and prices for each model.
- [ ] It ships disabled; a key alone does not enable it.
- [ ] It implements the abstract `LLMProvider` / `LLMModel` (subclass `ProviderBase`,
      `ChatModel`, `EmbeddingModel` from `sajha.ai.llm.spi`) and imports nothing private;
      `tests/test_llm_boundary.py` passes.
- [ ] It passes the provider contract suite offline; a live test exists, gated on its key.

**Model**

- [ ] It translates the canonical format (`wire` / `parse` / `translator`, or `_create`);
      `finish_reason` is a standard value and `tool_calls` whenever there are tool calls;
      `arguments` are JSON strings; every call has an id; a refusal sets `message.refusal`.
- [ ] Nothing is dropped silently: every feature it cannot honour is left undeclared, so
      `prepare` refuses it (or, for sampling controls, names it in `sajha.ignored`).
- [ ] Streams end with the finishing chunk and then the usage chunk (`StreamTranslator.close`).
- [ ] Usage is reported where the service gives it, so budgets and costs work.
- [ ] Structured output is declared only if the service enforces the schema (`json_mode`
      if it only guarantees JSON).
- [ ] Golden translation tests exist for it (built-in providers: an entry in
      `tests/ai/test_golden_translation.py` and recorded payloads).

**Planner**

- [ ] With a real model: role policy grants it; synthesis has a structured-output model;
      limits and budgets are set for its cost and latency; write tools are marked destructive.
- [ ] With a strategy model: it only calls offered tools, defers with `UnsupportedFeature`,
      and passes the safety tests in `tests/ai/test_ask.py` when put first in the alias.
- [ ] With a `Planner`: it reaches models only through `state.chat`, proposes only offered
      tools, gives `plan` steps the ids of their tool calls, validates its settings with a
      `config_model`, and passes the `test_contract_*` tests in `tests/ai/test_planners.py`.

**Documentation** (one owner per topic)

- [ ] A built-in provider gets its row in the [Intelligence Layer](Intelligence%20Layer.md)
      provider table and its fields in the
      [Configuration Reference](../getting-started/Configuration%20Reference.md#ai); its
      models go in `sajha/ai/llm/catalog.py`; the change goes in the CHANGELOG.
- [ ] An out-of-tree provider documents its own fields; it needs no change here.

**Document store**

- [ ] `create` raises `StoreUnavailable` with a reason an operator can act on; no secret is
      read from `config/application.yml`.
- [ ] Both searches run where the data is and return only `top_k` rows; `replace_document`
      streams its chunks and is atomic.
- [ ] It is thread safe and passes the cases of `tests/ai/test_rag_store_contract.py`.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
