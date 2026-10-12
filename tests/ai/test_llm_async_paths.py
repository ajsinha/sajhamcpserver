# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The last synchronous LLM paths (Roadmap X9): native async embeddings on the HTTP providers
(httpx.AsyncClient, no worker thread), a native async Bedrock path when aiobotocore is installed
(an async fake client stands in for it here; the worker-thread path stays when it is not), and
``reasoning_effort`` on Bedrock through ``additionalModelRequestFields`` per model family. No live
calls: httpx.MockTransport and fake bedrock-runtime clients.
"""

import anyio
import pytest

from sajha.ai.llm import registry
from sajha.ai.llm.errors import RateLimited, UnsupportedFeature
from sajha.ai.llm.providers.bedrock import model_family, reasoning_fields
from tests.ai.fakes import FakeBedrockClient
from tests.ai.test_provider_contract import CASES, Harness

HTTP_EMBEDDERS = [n for n, c in CASES.items() if c[5] and n != "bedrock"]


@pytest.fixture
def no_worker_threads(monkeypatch):
    """Fail if anything is pushed to a worker thread: the path must be natively async."""
    async def refuse(*a, **kw):
        raise AssertionError("a worker thread was used on a path that should be native async")
    monkeypatch.setattr(anyio.to_thread, "run_sync", refuse)


# ── HTTP providers: native async embeddings ─────────────────────────

@pytest.mark.parametrize("name", HTTP_EMBEDDERS)
def test_http_embeddings_are_native_async(name, no_worker_threads):
    h = Harness(name)
    em = h.provider.embedding_model(h.embedding)

    async def main():
        return await em.aembeddings_create(input=["alpha", "beta"])

    resp = anyio.run(main)
    assert len(resp.vectors) == 2 and all(resp.vectors)
    assert resp.sajha.provider == h.provider.name


@pytest.mark.parametrize("name", HTTP_EMBEDDERS)
def test_http_embeddings_async_matches_sync(name):
    h = Harness(name)
    em = h.provider.embedding_model(h.embedding)
    sync = em.embeddings_create(input=["alpha", "beta"], dimensions=None)
    sync_body = h.last()["body"]
    resp = anyio.run(lambda: em.aembeddings_create(input=["alpha", "beta"]))
    assert resp.vectors == sync.vectors
    assert h.last()["body"] == sync_body                    # the same wire request either way


def test_http_embeddings_async_errors_are_mapped():
    h = Harness("openai")
    h.set_mode("rate")
    em = h.provider.embedding_model(h.embedding)
    with pytest.raises(RateLimited):
        anyio.run(lambda: em.aembeddings_create(input=["x"]))


def test_governed_async_embeddings_do_not_use_a_worker_thread(no_worker_threads):
    from sajha.ai.llm.factory import build_llm_factory
    from tests.ai.fakes import FakeVendor
    fake = FakeVendor("openai")
    f = build_llm_factory({"gateway": {"load_entry_points": False, "use_db_providers": False},
                           "providers": [{"name": "openai", "config": {"enabled": True, "api_key": "k"}}]},
                          environ={}, transports={"openai": fake.transport})
    f.provider_health("openai")                 # warm the health cache outside the no-thread check
    resp = anyio.run(lambda: f.model("openai/text-embedding-3-small").aembeddings_create(input=["a", "b"]))
    assert len(resp.vectors) == 2 and resp.sajha.provider == "openai"
    vecs = anyio.run(lambda: f.aembed(["a"], model="openai/text-embedding-3-small"))
    assert len(vecs) == 1 and fake.last["path"].endswith("/embeddings")


# ── Bedrock: native async when the async client is there ───────────

class FakeAsyncBedrockClient(FakeBedrockClient):
    """The aiobotocore client's shape: awaitable calls, an async event stream, an async body."""

    async def converse(self, **kw):
        return FakeBedrockClient.converse(self, **kw)

    async def converse_stream(self, **kw):
        events = FakeBedrockClient.converse_stream(self, **kw)["stream"]

        async def gen():
            for e in events:
                yield e
        return {"stream": gen()}

    async def invoke_model(self, modelId, body, contentType, accept):
        data = FakeBedrockClient.invoke_model(self, modelId, body, contentType, accept)["body"].read()

        class Body:
            async def read(self):
                return data
        return {"body": Body()}


def _bedrock(fake, **cfg):
    cls = registry.provider_class("bedrock")
    return cls.from_settings("bedrock", {"enabled": True, "region": "us-east-1", **cfg}, environ={},
                             transport=fake)


def test_bedrock_async_chat_stream_and_embeddings_are_native(no_worker_threads):
    fake = FakeAsyncBedrockClient()
    p = _bedrock(fake)
    assert p.async_native()
    cm = p.chat_model("anthropic.claude-haiku-4-5")

    async def main():
        comp = await cm.achat_completions_create(messages=[{"role": "user", "content": "hi"}])
        chunks = [c async for c in cm.achat_completions_stream(messages=[{"role": "user", "content": "hi"}])]
        titan = await p.embedding_model("amazon.titan-embed-text-v2:0").aembeddings_create(input=["a", "b"])
        cohere = await p.embedding_model("cohere.embed-english-v3").aembeddings_create(
            input=["a", "b"], sajha={"input_purpose": "query"})
        return comp, chunks, titan, cohere

    comp, chunks, titan, cohere = anyio.run(main)
    assert comp.text == "Hello there" and comp.usage.prompt_tokens == 11
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert text == "Hello there"
    assert titan.vectors == [[0.9, 0.1], [0.9, 0.1]]
    assert cohere.vectors == [[0.2, 0.2], [0.2, 0.2]]
    assert fake.requests[-1]["input_type"] == "search_query"


def test_bedrock_async_errors_are_mapped():
    fake = FakeAsyncBedrockClient()
    fake.mode = "rate"
    cm = _bedrock(fake).chat_model("anthropic.claude-haiku-4-5")
    with pytest.raises(RateLimited):
        anyio.run(lambda: cm.achat_completions_create(messages=[{"role": "user", "content": "hi"}]))


def test_bedrock_with_a_synchronous_client_keeps_the_worker_thread_path():
    fake = FakeBedrockClient()
    p = _bedrock(fake)
    assert not p.async_native()
    cm = p.chat_model("anthropic.claude-haiku-4-5")
    comp = anyio.run(lambda: cm.achat_completions_create(messages=[{"role": "user", "content": "hi"}]))
    assert comp.text == "Hello there"
    vecs = anyio.run(lambda: p.embedding_model("amazon.titan-embed-text-v2:0").aembeddings_create(input=["a"]))
    assert vecs.vectors == [[0.9, 0.1]]


def test_bedrock_async_native_follows_aiobotocore_availability(monkeypatch):
    import sys
    p = registry.provider_class("bedrock").from_settings("bedrock", {"enabled": True}, environ={})
    monkeypatch.setitem(sys.modules, "aiobotocore", None)
    monkeypatch.setitem(sys.modules, "aiobotocore.session", None)
    assert p.async_native() is False


# ── Bedrock: reasoning_effort per model family ─────────────────────

@pytest.mark.parametrize("model,family", [
    ("anthropic.claude-opus-5-5", "anthropic"), ("us.anthropic.claude-opus-5-5", "anthropic"),
    ("global.anthropic.claude-opus-5-5", "anthropic"), ("us.amazon.nova-2-lite-v1:0", "amazon.nova-2"),
    ("arn:aws:bedrock:us-east-1:123:inference-profile/eu.amazon.nova-2-lite-v1:0", "amazon.nova-2"),
    ("us.amazon.nova-pro-v1:0", "amazon"), ("us.meta.llama3-3-70b-instruct-v1:0", "meta")])
def test_model_family(model, family):
    assert model_family(model) == family


def test_reasoning_fields_per_family():
    assert reasoning_fields("anthropic.claude-opus-5-5", "high") == {"output_config": {"effort": "high"}}
    assert reasoning_fields("us.amazon.nova-2-lite-v1:0", "xhigh") == {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "high"}}
    assert reasoning_fields("us.amazon.nova-2-lite-v1:0", "minimal")["reasoningConfig"]["maxReasoningEffort"] == "low"
    assert reasoning_fields("us.amazon.nova-2-lite-v1:0", "none") == {"reasoningConfig": {"type": "disabled"}}
    with pytest.raises(UnsupportedFeature, match="Anthropic Claude .* Amazon Nova 2"):
        reasoning_fields("us.meta.llama3-3-70b-instruct-v1:0", "low")


def test_bedrock_sends_reasoning_effort_for_claude_and_merges_operator_fields():
    fake = FakeBedrockClient()
    p = _bedrock(fake, additional_model_request_fields={"output_config": {"other": 1}, "top_k": 5})
    cm = p.chat_model("anthropic.claude-opus-5-5")             # tagged reasoning in the catalogue
    cm.chat_completions_create(messages=[{"role": "user", "content": "hi"}], reasoning_effort="medium",
                               extra_body={"top_k": 7})
    fields = fake.requests[-1]["additionalModelRequestFields"]
    assert fields == {"output_config": {"effort": "medium", "other": 1}, "top_k": 7}


def test_bedrock_sends_reasoning_config_for_nova_2_declared_in_config():
    fake = FakeBedrockClient()
    p = _bedrock(fake, models=[{"id": "us.amazon.nova-2-lite-v1:0", "tags": ["reasoning"], "tools": True}])
    p.chat_model("us.amazon.nova-2-lite-v1:0").chat_completions_create(
        messages=[{"role": "user", "content": "hi"}], reasoning_effort="low")
    assert fake.requests[-1]["additionalModelRequestFields"] == {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "low"}}


def test_bedrock_refuses_reasoning_effort_for_other_families_with_a_clear_error():
    fake = FakeBedrockClient()
    p = _bedrock(fake, models=[{"id": "us.meta.llama3-3-70b-instruct-v1:0", "tags": ["reasoning"],
                                "tools": True}])
    with pytest.raises(UnsupportedFeature, match="Anthropic Claude"):
        p.chat_model("us.meta.llama3-3-70b-instruct-v1:0").chat_completions_create(
            messages=[{"role": "user", "content": "hi"}], reasoning_effort="low")
    with pytest.raises(UnsupportedFeature, match="Anthropic Claude"):     # untagged too: the family speaks
        p.chat_model("us.amazon.nova-pro-v1:0").chat_completions_create(
            messages=[{"role": "user", "content": "hi"}], reasoning_effort="low")
    assert fake.requests == []                                  # refused before any call


def test_untagged_claude_still_refuses_reasoning_effort():
    fake = FakeBedrockClient()
    with pytest.raises(UnsupportedFeature, match="reasoning_effort"):
        _bedrock(fake).chat_model("anthropic.claude-haiku-4-5").chat_completions_create(
            messages=[{"role": "user", "content": "hi"}], reasoning_effort="low")
