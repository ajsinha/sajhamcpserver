"""
SAJHA MCP Server — worked examples for extending the intelligence layer.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

The code of docs/architecture/Extending the Intelligence Layer.md, runnable and tested
(tests/ai/test_extension_examples.py), so the guide's excerpts cannot rot:

    acme_provider.py     a provider for a fictional in-house HTTP LLM ("Acme"): chat, tools,
                         structured output, streaming, embeddings, health, error mapping
    acme_fake_server.py  Acme's API, faked: an httpx MockTransport for tests, and a small
                         HTTP server for trying the provider in the Ask SAJHA page
    custom_models.py     @register_model: a fine-tuned OpenAI model with its own behaviour
    recipe_planner.py    a planning strategy written as a model: fixed question -> tool
                         recipes, deferring to the next model in the alias when none matches

Importing a module registers what it defines (``@register_provider`` / ``@register_model``).
Nothing here is imported by the server unless a deployment names it in ``ai.providers[].class``.
"""
