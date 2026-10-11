# Tutorial 43: Connect and Configure LLM Providers

Ask SAJHA, LLM tools, Describe a tool and every other model call go through one factory
(`sajha/ai/llm/`). Out of the box only the in-process `mock` provider is on, so nothing leaves the
machine. This tutorial connects real providers: each built-in one with its YAML, its environment
variables and a check; aliases and fallback; an OpenAI-compatible vendor with no code; and, last, a
provider class of your own, registered by class path and by entry point. The design is
[Intelligence Layer](../architecture/Intelligence%20Layer.md); every key is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#ai); writing a provider in
depth is [Extending the Intelligence Layer](../architecture/Extending%20the%20Intelligence%20Layer.md).

**What was verified.** Every key, environment variable and default below was checked against
`sajha/ai/llm/` (the providers' `config_model` and `vendor_env`). Step 9 (the Acme provider against its
fake server) and the offline configuration check of step 8 were run as written. The vendor steps need
accounts and keys and were not run for this tutorial; the same code is covered offline by
`tests/ai/test_provider_contract.py`.

## What you'll learn

- Where a provider's settings come from, and in what order
- The YAML and environment for OpenAI, Azure OpenAI, Anthropic (direct and on Vertex AI), Bedrock,
  Gemini, Mistral, Cohere and Ollama
- How aliases choose a model, and how fallback moves to the next candidate
- How to add an OpenAI-compatible vendor without code (Hugging Face, Together, Groq, vLLM)
- How to write a small provider class and register it two ways
- How to check a provider: the LLM page, a test ask, and usage and cost

## Prerequisites

- SAJHA running from a checkout ([Quick Start](../getting-started/Quick%20Start.md)) and an administrator
  account (the LLM page and `GET /api/ai/config` are for administrators)
- For each vendor you want: an account and a key. Keys go in the environment, never in
  `config/application.yml` (it is tracked)

## 1. How a provider is configured

Each provider is one entry of `ai.providers` in `config/application.yml`. The shipped file lists every
built-in provider, all `enabled: false`:

```yaml
ai:
  providers:
    - { name: openai,    config: { enabled: false } }
    - { name: bedrock,   config: { enabled: false, region: us-east-1 } }
    # ...
```

Every field of a provider's `config` resolves in this order (first wins):

1. `SAJHA_AI_<PROVIDER>_<FIELD>`, for example `SAJHA_AI_OPENAI_ENABLED=true`;
2. the vendor's own variable, for example `OPENAI_API_KEY` (the provider's `vendor_env`);
3. `config/application.yml`;
4. a value saved on the LLM page (stored in the database);
5. the code default.

A key alone never turns a provider on: set `enabled: true` (or `SAJHA_AI_<PROVIDER>_ENABLED=true`).
A key can also be a reference instead of a value: `api_key_ref: env:NAME`, `file:/path` or
`db:llm_providers/<type>`.

Fields every provider has: `enabled`, `api_key`, `api_key_ref`, `base_url`, `default_model`,
`default_embedding_model`, `models` (add a model or change a catalogue entry), `proxy`, `verify_tls`,
`ca_bundle`, `connect_timeout_s`, `read_timeout_s`, `max_retries`, `max_concurrency`,
`default_max_output_tokens`, `streaming`.

## 2. OpenAI

```bash
export OPENAI_API_KEY=sk-...                  # or SAJHA_AI_OPENAI_API_KEY
export SAJHA_AI_OPENAI_ENABLED=true
```

Optional: `OPENAI_BASE_URL` (a proxy or gateway), `OPENAI_ORG_ID` and `OPENAI_PROJECT_ID` (the
`organization` and `project` fields). The default model is the catalogue's (`gpt-6.1-sol`); set
`default_model` to change it.

## 3. Azure OpenAI

```yaml
    - name: azure_openai
      config:
        enabled: true
        api_style: v1                 # the GA /openai/v1 path; "deployments" for /openai/deployments/<name>
        deployments:                  # model id -> your deployment name
          gpt-6.1-sol: chat-prod
        default_model: gpt-6.1-sol
```

```bash
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
export AZURE_OPENAI_API_KEY=...
```

With `api_style: deployments`, `api_version` (default `2024-10-21`, or `OPENAI_API_VERSION`) is sent.
For Microsoft Entra ID instead of a key, set `auth: entra` and `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and
either `AZURE_CLIENT_SECRET` or (on AKS) `AZURE_FEDERATED_TOKEN_FILE`; with none of them a managed
identity is used (`entra_mode: auto`).

## 4. Anthropic, direct and on Vertex AI

Direct:

```bash
export ANTHROPIC_API_KEY=...
export SAJHA_AI_ANTHROPIC_ENABLED=true
```

On Vertex AI, the same provider with `platform: vertex`:

```yaml
    - name: anthropic
      config:
        enabled: true
        platform: vertex
        vertex_location: global        # or a region, e.g. us-east5
```

```bash
export ANTHROPIC_VERTEX_PROJECT_ID=my-gcp-project
export CLOUD_ML_REGION=global                        # the vertex_location field
export GOOGLE_APPLICATION_CREDENTIALS=/secure/sa.json  # omit on GKE workload identity or Cloud Run
```

No API key is used on Vertex; a Google access token is obtained and refreshed
(`sajha/ai/llm/cloud_auth.py`).

## 5. AWS Bedrock

Bedrock signs requests with boto3, an optional dependency: `pip install boto3` in SAJHA's environment.

```yaml
    - name: bedrock
      config:
        enabled: true
        region: us-east-1
        default_model: us.amazon.nova-pro-v1:0
```

Credentials come from `aws_access_key_id` / `aws_secret_access_key` / `aws_session_token`
(`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`), a `profile` (`AWS_PROFILE`), or, with
none of them, boto3's default chain (SSO, an instance or task role). The region is `region`
(`AWS_REGION` or `AWS_DEFAULT_REGION`); `AWS_ENDPOINT_URL_BEDROCK_RUNTIME` points at a VPC endpoint.

The model id is passed to Converse as `modelId` unchanged, so a **cross-region inference profile** is
just a model id: the catalogue's `us.amazon.nova-pro-v1:0` is one. Add one that is not in the catalogue
with `models` (an ARN works too):

```yaml
        models:
          - { id: "eu.anthropic.claude-haiku-4-5", tools: true, context_window: 200000 }
```

Optional: `guardrail_identifier` and `guardrail_version` apply a Bedrock guardrail to every call.

## 6. Gemini, Mistral, Cohere

```bash
export GEMINI_API_KEY=...        && export SAJHA_AI_GEMINI_ENABLED=true     # or GOOGLE_API_KEY
export MISTRAL_API_KEY=...       && export SAJHA_AI_MISTRAL_ENABLED=true
export COHERE_API_KEY=...        && export SAJHA_AI_COHERE_ENABLED=true     # or CO_API_KEY
```

Gemini on Vertex AI is `platform: vertex` with `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` and
`GOOGLE_APPLICATION_CREDENTIALS`, as for Anthropic.

## 7. Ollama (local, no key)

```bash
ollama pull llama3.2
export SAJHA_AI_OLLAMA_ENABLED=true
export OLLAMA_HOST=http://localhost:11434      # the default; or OLLAMA_BASE_URL
```

SAJHA lists the models actually pulled on the host and skips a candidate that is not pulled. `num_ctx`,
`keep_alive`, `think` and `options` pass through to Ollama.

## 8. Aliases and fallback

Callers never name a vendor. They ask for an **alias**, and the alias is an ordered list of candidates;
Ask SAJHA uses `ai.ask.model`, which is `default`. A bare provider name means its default model;
`provider/model` names one model.

```yaml
ai:
  aliases:
    default:   [anthropic, openai/gpt-6.1-sol, ollama, mock/mock-planner]
    fast:      [groq/llama-3.1-8b-instant, ollama/llama3.2]
    embedding: [openai/text-embedding-3-small, ollama/nomic-embed-text]
```

or, for one alias, `SAJHA_AI_ALIASES_DEFAULT=anthropic,ollama,mock/mock-planner`.

**Fallback.** A candidate is skipped when its provider is disabled or unhealthy, or the model lacks a
capability the request needs (tools, structured output). A call that fails with a rate limit or an
unavailable provider is retried with backoff and then moves to the next candidate; a prompt too long for
the context window moves on at once; a bad key marks the provider down. A content-filter refusal never
falls back. When no candidate is left, the error names each one and why it was skipped
([Intelligence Layer §2](../architecture/Intelligence%20Layer.md)).

**Check it.** `GET /api/ai/config` (administrator) shows `active_providers`, `resolved_aliases` and
`build_errors`, with each setting's source:

```bash
curl -s http://localhost:3002/api/ai/config -H "X-API-Key: $SAJHA_ADMIN_KEY" | python -m json.tool | head -40
```

The same check runs offline, without a server, from a configuration dict (this one was run):

```python
from sajha.ai.llm import build_llm_factory
f = build_llm_factory({"providers": [{"name": "huggingface", "config": {"enabled": True}}],
                       "aliases": {"default": ["huggingface/openai/gpt-oss-120b:cheapest", "mock/mock-planner"]}},
                      environ={"HF_TOKEN": "hf_dummy"})
c = f.describe_config()
print(c["active_providers"], c["resolved_aliases"]["default"], c["build_errors"])
# ['mock', 'huggingface'] huggingface/openai/gpt-oss-120b:cheapest []
```

## 9. An OpenAI-compatible vendor, no code

Any server that speaks `/chat/completions` is either a **preset** (a built-in name with its base URL and
key variable) or the generic `openai_compatible` provider.

| Vendor | Name | Base URL (default) | Key variable |
|---|---|---|---|
| Hugging Face Inference Providers | `huggingface` | `https://router.huggingface.co/v1` | `HF_TOKEN` (or `HUGGING_FACE_HUB_TOKEN`) |
| Together AI | `together` | `https://api.together.xyz/v1` | `TOGETHER_API_KEY` |
| Groq | `groq` | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| vLLM (yours) | `vllm` | `http://localhost:8000/v1` | none, or `VLLM_API_KEY` |

The other presets are `fireworks`, `deepseek`, `xai`, `openrouter`, `perplexity` and `lmstudio`.

**Hugging Face.** One token reaches many hosts; the router picks one per model. A model id may end
with `:fastest` (the default), `:cheapest`, `:preferred` or a provider name (`:groq`). The endpoint is
chat only, so use another provider for embeddings.

```bash
export HF_TOKEN=hf_...            # a fine-grained token allowed to "Make calls to Inference Providers"
export SAJHA_AI_HUGGINGFACE_ENABLED=true
export SAJHA_AI_ALIASES_DEFAULT="huggingface/openai/gpt-oss-120b,mock/mock-planner"
```

The catalogue lists `openai/gpt-oss-120b` (the default) and `deepseek-ai/DeepSeek-R1` with prices of 0,
because the price is the serving host's; set `input_cost_per_mtok` and `output_cost_per_mtok` under
`models` if you want cost figures. `live_models: true` asks the router's `GET /v1/models` for the full
list. A self-hosted **Text Generation Inference** server is not this preset: it is `openai_compatible`
with its own `base_url`, as below.

**vLLM or TGI on your own host.** The generic provider is used only when you point it somewhere:

```yaml
    - name: openai_compatible
      config:
        enabled: true
        base_url: http://tgi.internal:8080/v1
        default_model: tgi
        live_models: true                    # GET /models for the list
```

A second server of the same kind is another entry with its own `name` and `type: openai_compatible`.
When a vendor needs `max_tokens` instead of `max_completion_tokens`, or another spelling, the
`max_tokens_param`, `tool_choice_required` and `seed_param` fields declare it.

## 10. Your own provider class

When a service is not OpenAI-compatible, write a provider. The worked example ships with SAJHA:
`sajha/examples/intelligence/acme_provider.py` (a fictional "Acme LLM" with its own wire format) and a
fake Acme server, `acme_fake_server.py`. The guide explains each part
([Extending the Intelligence Layer §2–3](../architecture/Extending%20the%20Intelligence%20Layer.md#2-writing-a-provider));
here is the short, runnable version.

The class has a pydantic `config_model` (each field is a YAML key and a `SAJHA_AI_ACME_<FIELD>`
variable), `vendor_env` for the vendor's own variables, and a chat model that translates the canonical
(OpenAI-style) request to Acme's body and back:

```python
@register_provider
class AcmeProvider(ProviderBase):
    name = "acme"
    config_model = AcmeConfig            # tenant, safety, default_model, live_models, ...
    requires_key = True
    default_base_url = "https://llm.acme.internal"
```

**Run it against the fake server.** In one terminal:

```bash
python -m sajha.examples.intelligence.acme_fake_server --port 8765
```

In another, build a factory with the provider registered **by class path**, exactly as YAML would, and
call the `default` alias (this was run; the fake answers "Hello there"):

```python
from sajha.ai.llm import build_llm_factory, ChatMessage

ai = {
    "providers": [
        {"name": "acme", "class": "sajha.examples.intelligence.acme_provider:AcmeProvider",
         "config": {"enabled": True, "base_url": "http://127.0.0.1:8765", "tenant": "risk"}},
    ],
    "aliases": {"default": ["acme", "mock/mock-planner"]},
}
factory = build_llm_factory(ai, environ={"ACME_LLM_KEY": "k"})
cfg = factory.describe_config()
print("active:", cfg["active_providers"], "default ->", cfg["resolved_aliases"]["default"])
reply = factory.model("default").chat_completions_create(messages=[ChatMessage.user("Say hello")])
print(reply.choices[0].message.content, reply.usage.prompt_tokens, reply.usage.completion_tokens)
# active: ['mock', 'acme'] default -> acme/acme-large
# Hello there 17 5
```

In the server, the same thing is YAML, with the key in the environment (`ACME_LLM_KEY`, from the
class's `vendor_env`, or `SAJHA_AI_ACME_API_KEY`):

```yaml
ai:
  providers:
    - name: acme
      class: sajha.examples.intelligence.acme_provider:AcmeProvider
      config: { enabled: true, base_url: "http://127.0.0.1:8765", tenant: risk }
  aliases:
    default: [acme, mock/mock-planner]
```

**By entry point**, for a provider shipped as its own package: declare it in the package's
`pyproject.toml` and install the package into SAJHA's environment. SAJHA loads the
`sajha.llm_providers` group at start-up (unless `ai.gateway.load_entry_points` is false); the entry
point's name is the provider's name, and `SAJHA_AI_ACME_ENABLED=true` alone turns it on.

```toml
[project.entry-points."sajha.llm_providers"]
acme = "acme_sajha.provider:AcmeProvider"
```

`GET /api/ai/registry` (administrator) lists every registered provider, whichever way it came. Before
you ship one, run it through the provider contract suite as `tests/ai/test_extension_examples.py` does
([Extending §5](../architecture/Extending%20the%20Intelligence%20Layer.md#5-testing-your-extension)).

## 11. Check it in the console

1. **AI > Models & prompts > LLM** (`/ai/settings`) lists each provider with its state and models.
   The health button there is `POST /api/ai/providers/<name>/health`; it answers `healthy`, `active`,
   `status` and `detail`.
2. **A test ask.** **AI > Ask > Ask SAJHA**, or over HTTP:

   ```bash
   curl -s -X POST http://localhost:3002/api/ai/ask -H "X-API-Key: $SAJHA_KEY" \
        -H 'Content-Type: application/json' -d '{"question": "What is the percentage change from 80 to 100?"}'
   ```

   The result's `models` lists the models that served it. Pass `"model": "fast"` (an alias) or
   `"model": "ollama/llama3.2"` to try another.
3. **Usage and cost.** **Monitor > Usage & cost** (`/monitoring/usage`) shows tokens and spend by
   provider, model, user and tool; `GET /api/ai/usage` returns the caller's own tokens and
   `total_cost_usd`. Cost uses the catalogue's
   prices, or the `models` overrides you set.

## Recap

- One entry per provider in `ai.providers`; settings from `SAJHA_AI_<PROVIDER>_<FIELD>`, the vendor's
  variable, YAML, the LLM page, then the default; keys never in the YAML
- Aliases are ordered candidates; fallback moves on for rate limits, outages and context length
- OpenAI-compatible vendors are presets (`huggingface`, `together`, `groq`, `vllm`, ...) or
  `openai_compatible` with a `base_url`
- A provider class registers by `class:` in YAML or by a `sajha.llm_providers` entry point

## Next

- Every provider, alias, policy and budget setting: [Intelligence Layer](../architecture/Intelligence%20Layer.md)
- Writing providers, models and planners in depth: [Extending the Intelligence Layer](../architecture/Extending%20the%20Intelligence%20Layer.md)
- Next tutorial: [Tutorial 44: Tool Health and Domain Descriptions](TUTORIAL_44_tool_health.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
