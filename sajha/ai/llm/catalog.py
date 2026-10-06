"""
SAJHA Intelligence Layer — curated model catalogue (DATA ONLY).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The one place where vendor model ids, context windows and list prices live. Curated
2026-10 from the vendors' public model and pricing pages; ids and prices change often, so:

  * a deployment overrides or extends any entry with ``ai.providers[].config.models``
    (or SAJHA_AI_<PROVIDER>_MODELS as JSON), so a new model id never needs a code change;
  * Ollama lists the models actually pulled on the host (live ``/api/tags``) on top of this;
  * prices are USD per million tokens; 0 means "unknown/free" (usage is still counted).

Row format: (id, kind, context_window, max_output, in_$/MTok, out_$/MTok, flags, tags)
flags: t=tools s=structured output v=vision n=no temperature f=no forced tool choice
       e=embedding (context_window column holds the dimensions)
"""

from typing import Dict, List, Tuple

Row = Tuple[str, str, int, int, float, float, str, str]

CATALOG: Dict[str, List[Row]] = {
    "anthropic": [
        ("claude-opus-5-5",   "chat", 1_000_000, 128_000, 4.00, 20.00, "tsvnf", "reasoning"),
        ("claude-sonnet-5-5", "chat", 1_000_000, 128_000, 2.00, 10.00, "tsvnf", ""),
        ("claude-fable-5-1",  "chat", 1_000_000, 128_000, 10.00, 50.00, "tsvnf", "reasoning"),
        ("claude-opus-5",     "chat", 1_000_000, 128_000, 5.00, 25.00, "tsvn", "reasoning"),
        ("claude-sonnet-5",   "chat", 1_000_000, 128_000, 2.00, 10.00, "tsvn", ""),
        ("claude-sonnet-4-6", "chat", 1_000_000, 64_000, 3.00, 15.00, "tsv", ""),
        ("claude-haiku-4-5",  "chat", 200_000, 64_000, 1.00, 5.00, "tsv", "fast,cheap"),
    ],
    "openai": [
        ("gpt-6.1-sol",  "chat", 1_050_000, 128_000, 2.00, 10.00, "tsv", ""),
        ("gpt-6-astra",  "chat", 1_050_000, 128_000, 10.00, 50.00, "tsv", "reasoning"),
        ("gpt-6-luna",   "chat", 1_050_000, 128_000, 0.10, 0.50, "tsv", "fast,cheap"),
        ("gpt-5.5",      "chat", 272_000, 128_000, 5.00, 30.00, "tsv", ""),
        ("gpt-5.4-mini", "chat", 272_000, 128_000, 0.75, 4.50, "tsv", "fast"),
        ("gpt-4o-mini",  "chat", 128_000, 16_384, 0.15, 0.60, "tsv", "fast,cheap"),
        ("text-embedding-3-small", "embedding", 1536, 0, 0.02, 0.0, "e", ""),
        ("text-embedding-3-large", "embedding", 3072, 0, 0.13, 0.0, "e", ""),
    ],
    "azure_openai": [],      # deployments are per resource: list them in config (models[].deployment)
    "gemini": [
        ("gemini-3.1-pro-preview", "chat", 1_000_000, 64_000, 2.00, 12.00, "tsv", "reasoning"),
        ("gemini-3.8-flash",       "chat", 1_000_000, 64_000, 0.75, 3.75, "tsv", "fast"),
        ("gemini-3.5-flash-lite",  "chat", 1_000_000, 64_000, 0.30, 2.50, "tsv", "fast,cheap"),
        ("gemini-2.5-pro",         "chat", 1_000_000, 64_000, 1.25, 10.00, "tsv", ""),
        ("gemini-2.5-flash",       "chat", 1_000_000, 64_000, 0.30, 2.50, "tsv", "fast"),
        ("gemini-embedding-2",     "embedding", 3072, 0, 0.20, 0.0, "e", ""),
    ],
    "bedrock": [
        ("anthropic.claude-sonnet-5-5", "chat", 1_000_000, 128_000, 2.00, 10.00, "tvnf", ""),
        ("anthropic.claude-opus-5-5",   "chat", 1_000_000, 128_000, 4.00, 20.00, "tvnf", "reasoning"),
        ("anthropic.claude-haiku-4-5",  "chat", 200_000, 64_000, 1.00, 5.00, "tv", "fast"),
        ("us.amazon.nova-pro-v1:0",     "chat", 300_000, 10_000, 0.80, 3.20, "tv", ""),
        ("us.amazon.nova-lite-v1:0",    "chat", 300_000, 10_000, 0.06, 0.24, "tv", "fast,cheap"),
        ("us.meta.llama3-3-70b-instruct-v1:0", "chat", 128_000, 8_192, 0.72, 0.72, "t", ""),
        ("amazon.titan-embed-text-v2:0", "embedding", 1024, 0, 0.02, 0.0, "e", ""),
        ("cohere.embed-english-v3",      "embedding", 1024, 0, 0.10, 0.0, "e", ""),
    ],
    "mistral": [
        ("mistral-large-4-0",  "chat", 512_000, 256_000, 0.0, 0.0, "tsv", ""),
        ("mistral-medium-2504", "chat", 128_000, 32_000, 0.0, 0.0, "ts", ""),
        ("mistral-small-2603", "chat", 128_000, 32_000, 0.0, 0.0, "ts", "fast"),
        ("ministral-8b-2512",  "chat", 128_000, 32_000, 0.0, 0.0, "tsv", "fast,cheap"),
        ("codestral-2508",     "chat", 256_000, 32_000, 0.0, 0.0, "ts", ""),
        ("mistral-embed",      "embedding", 1024, 0, 0.10, 0.0, "e", ""),
    ],
    "cohere": [
        ("command-a-03-2025",           "chat", 256_000, 8_000, 2.50, 10.00, "ts", ""),
        ("command-a-plus-05-2026",      "chat", 128_000, 64_000, 0.0, 0.0, "ts", ""),
        ("command-a-reasoning-08-2025", "chat", 256_000, 32_000, 0.0, 0.0, "ts", "reasoning"),
        ("command-r7b-12-2024",         "chat", 128_000, 4_000, 0.0375, 0.15, "ts", "fast,cheap"),
        ("embed-v4.0",                  "embedding", 1536, 0, 0.12, 0.0, "e", ""),
        ("embed-english-v3.0",          "embedding", 1024, 0, 0.10, 0.0, "e", ""),
    ],
    "ollama": [              # shown when the host has them; the live /api/tags list wins
        ("llama3.3",          "chat", 128_000, 8_192, 0, 0, "ts", "local"),
        ("qwen3",             "chat", 40_000, 8_192, 0, 0, "ts", "local"),
        ("gpt-oss:20b",       "chat", 128_000, 8_192, 0, 0, "ts", "local"),
        ("llama3.2",          "chat", 128_000, 8_192, 0, 0, "ts", "local,fast"),
        ("nomic-embed-text",  "embedding", 768, 0, 0, 0, "e", "local"),
        ("mxbai-embed-large", "embedding", 1024, 0, 0, 0, "e", "local"),
    ],
    "groq": [
        ("llama-3.3-70b-versatile", "chat", 131_072, 32_768, 0.59, 0.79, "t", "fast"),
        ("llama-3.1-8b-instant",    "chat", 131_072, 8_192, 0.05, 0.08, "t", "fast,cheap"),
        ("openai/gpt-oss-120b",     "chat", 131_072, 32_768, 0.15, 0.60, "ts", "fast"),
        ("openai/gpt-oss-20b",      "chat", 131_072, 32_768, 0.075, 0.30, "ts", "fast,cheap"),
    ],
    "together": [
        ("deepseek-ai/DeepSeek-V4-Flash-0731", "chat", 1_000_000, 32_000, 0.14, 0.28, "ts", "fast,cheap"),
        ("deepseek-ai/DeepSeek-V4-Pro-0813",   "chat", 1_000_000, 32_000, 1.32, 3.96, "ts", "reasoning"),
        ("moonshotai/Kimi-K3",                 "chat", 1_000_000, 32_000, 3.00, 15.00, "ts", ""),
        ("Qwen/Qwen3.5-9B",                    "chat", 262_000, 32_000, 0.17, 0.25, "ts", "cheap"),
    ],
    "fireworks": [
        ("accounts/fireworks/models/llama-v3p3-70b-instruct", "chat", 131_072, 16_384, 0.90, 0.90, "ts", ""),
        ("accounts/fireworks/models/deepseek-v3", "chat", 131_072, 16_384, 0.90, 0.90, "ts", ""),
    ],
    "deepseek": [
        ("deepseek-v4-pro", "chat", 1_000_000, 384_000, 1.32, 3.96, "t", "reasoning"),
        ("deepseek-flash",  "chat", 1_000_000, 384_000, 0.30, 1.20, "tv", "fast,cheap"),
    ],
    "xai": [
        ("grok-4.7", "chat", 500_000, 64_000, 2.00, 6.00, "tsv", "reasoning"),
        ("grok-4.3", "chat", 1_000_000, 64_000, 1.25, 2.50, "ts", "fast"),
    ],
    "openrouter": [
        ("openai/gpt-6.1-sol",          "chat", 1_050_000, 128_000, 2.00, 10.00, "tsv", ""),
        ("anthropic/claude-sonnet-5.5", "chat", 1_000_000, 128_000, 2.00, 10.00, "tsv", ""),
        ("mistralai/mistral-large-4",   "chat", 512_000, 256_000, 0.0, 0.0, "ts", ""),
    ],
    "perplexity": [
        ("sonar",               "chat", 127_000, 8_000, 1.00, 1.00, "sv", "search"),
        ("sonar-pro",           "chat", 200_000, 8_000, 3.00, 15.00, "sv", "search"),
        ("sonar-reasoning-pro", "chat", 127_000, 8_000, 2.00, 8.00, "s", "search,reasoning"),
    ],
    "vllm": [],
    "lmstudio": [],
    "openai_compatible": [],
}

# The model a provider uses when an alias names just the provider.
DEFAULT_MODELS: Dict[str, Tuple[str, str]] = {      # provider -> (chat, embedding)
    "anthropic": ("claude-sonnet-5-5", ""),
    "openai": ("gpt-6.1-sol", "text-embedding-3-small"),
    "azure_openai": ("", ""),
    "gemini": ("gemini-3.8-flash", "gemini-embedding-2"),
    "bedrock": ("anthropic.claude-sonnet-5-5", "amazon.titan-embed-text-v2:0"),
    "mistral": ("mistral-large-4-0", "mistral-embed"),
    "cohere": ("command-a-03-2025", "embed-v4.0"),
    "ollama": ("llama3.2", "nomic-embed-text"),
    "groq": ("llama-3.3-70b-versatile", ""),
    "together": ("deepseek-ai/DeepSeek-V4-Flash-0731", ""),
    "fireworks": ("accounts/fireworks/models/llama-v3p3-70b-instruct", ""),
    "deepseek": ("deepseek-flash", ""),
    "xai": ("grok-4.3", ""),
    "openrouter": ("openai/gpt-6.1-sol", ""),
    "perplexity": ("sonar", ""),
    "vllm": ("", ""),
    "lmstudio": ("", ""),
    "openai_compatible": ("", ""),
}
