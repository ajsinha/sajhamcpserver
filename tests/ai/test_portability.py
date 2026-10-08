# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Portability suite: one set of canonical Chat Completions requests through the mock and through
every provider adapter, offline (recorded-shape fake vendors from fakes.py), checking that the
responses are well-formed Chat Completions and that each model's declared capabilities are
honoured: a feature it declares works, one it does not is refused with UnsupportedFeature,
never silently dropped (LLM Tools.md §13.5).
"""

import json

import anyio
import pytest

from sajha.ai.llm import UnsupportedFeature
from sajha.ai.llm.canonical import (FINISH_REASONS, ChatCompletion, ChatCompletionChunk, ChatMessage,
                                    ChunkAccumulator, ResponseFormat, ToolDefinition)
from tests.ai.fakes import TOOL_ARGS, TOOL_NAME
from tests.ai.test_provider_contract import PROVIDERS, QUESTION, SCHEMA, SPEC, Harness

TOOL = ToolDefinition.of(SPEC.name, SPEC.description, SPEC.input_schema)
HTTP = [p for p in PROVIDERS if p not in ("mock", "bedrock")]


@pytest.fixture(params=PROVIDERS)
def h(request):
    return Harness(request.param)


def well_formed(c: ChatCompletion, provider: str) -> None:
    """A valid Chat Completions response once ``sajha`` is stripped, with SAJHA's markers set."""
    d = c.to_dict()
    assert d["object"] == "chat.completion" and d["id"] and isinstance(d["created"], int) and d["model"]
    sajha = d.pop("sajha")
    assert ChatCompletion.model_validate(d).to_dict() == d          # round-trips through the typed model
    assert d["choices"] and all(ch["finish_reason"] in FINISH_REASONS for ch in d["choices"])
    for ch in d["choices"]:
        m = ch["message"]
        assert m["role"] == "assistant"
        for tc in m.get("tool_calls") or []:
            assert tc["type"] == "function" and tc["id"] and isinstance(tc["function"]["arguments"], str)
            json.loads(tc["function"]["arguments"])
    u = d["usage"]
    assert u["total_tokens"] == u["prompt_tokens"] + u["completion_tokens"]
    assert sajha["provider"] == provider and sajha["qualified_model"].startswith(provider + "/")
    assert "provider_state" not in json.dumps(d)                   # private state never serialised


def test_plain_chat(h):
    cm = h.chat_model()
    c = cm.chat_completions_create(messages=[ChatMessage.system("Be brief."), ChatMessage.user(QUESTION)],
                                   max_completion_tokens=200)
    well_formed(c, h.name)
    assert c.finish_reason == "stop" and c.text and c.usage.prompt_tokens > 0


def test_tool_call_round_trip(h):
    cm = h.chat_model()
    first = cm.chat_completions_create(messages=[ChatMessage.user(QUESTION)], tools=[TOOL])
    well_formed(first, h.name)
    assert first.finish_reason == "tool_calls"
    call = first.tool_calls[0]
    assert call.function.name == TOOL_NAME and call.function.args() == TOOL_ARGS
    second = cm.chat_completions_create(messages=[
        ChatMessage.user(QUESTION), first.message,
        ChatMessage.tool(call.id, {"percentage_change": 25.0}, tool_name=call.function.name)], tools=[TOOL])
    well_formed(second, h.name)
    assert second.finish_reason == "stop" and second.text and not second.tool_calls


def test_structured_output_native_emulated_or_refused(h):
    cm = h.chat_model()
    rf = ResponseFormat.of_schema(SCHEMA)
    caps = cm.capabilities
    if not (caps.structured_output or caps.json_mode):
        with pytest.raises(UnsupportedFeature):
            cm.chat_completions_create(messages=[ChatMessage.user("x")], response_format=rf)
        return
    c = cm.chat_completions_create(messages=[ChatMessage.user(QUESTION)], response_format=rf)
    well_formed(c, h.name)
    assert "answer" in c.parsed()
    assert c.sajha.structured_output == ("native" if caps.structured_output else "emulated")


def test_stream_is_well_formed_chunks(h):
    cm = h.chat_model() if h.name != "mock" else h.provider.chat_model("mock-echo")
    chunks = list(cm.chat_completions_stream(messages=[ChatMessage.user(QUESTION)]))
    assert all(isinstance(c, ChatCompletionChunk) and c.object == "chat.completion.chunk" for c in chunks)
    assert len({c.id for c in chunks}) == 1 and len({c.created for c in chunks}) == 1
    assert chunks[0].choices[0].delta.role == "assistant"
    assert chunks[-1].is_usage and chunks[-1].sajha.provider == h.name           # usage last
    finishing = [c for c in chunks if c.choices and c.choices[0].finish_reason]
    assert len(finishing) == 1 and finishing[0].choices[0].finish_reason == "stop"
    acc = ChunkAccumulator()
    for c in chunks:
        acc.add(c)
    whole = acc.result()
    assert whole.text and whole.usage.total_tokens > 0


def test_stream_tool_fragments_accumulate(h):
    chunks = list(h.chat_model().chat_completions_stream(messages=[ChatMessage.user(QUESTION)], tools=[TOOL]))
    acc = ChunkAccumulator()
    for c in chunks:
        acc.add(c)
    whole = acc.result()
    assert whole.finish_reason == "tool_calls"
    assert whole.tool_calls[0].function.name == TOOL_NAME and whole.tool_calls[0].function.args() == TOOL_ARGS


def test_undeclared_features_are_refused_not_dropped(h):
    cm = h.chat_model()
    caps = cm.capabilities
    q = [ChatMessage.user(QUESTION)]
    checks = [
        (caps.seed, dict(seed=7)),
        (caps.reasoning_effort, dict(reasoning_effort="low")),
        (caps.forced_tool_choice, dict(tools=[TOOL], tool_choice="required")),
        (caps.parallel_tool_control, dict(tools=[TOOL], parallel_tool_calls=False)),
        (caps.strict_tools, dict(tools=[ToolDefinition.of(SPEC.name, SPEC.description, SPEC.input_schema,
                                                          strict=True)])),
        (getattr(cm.provider, "openai_compatible", False), dict(presence_penalty=0.5)),
    ]
    for declared, extra in checks:
        if declared:
            continue
        with pytest.raises(UnsupportedFeature):
            cm.chat_completions_create(messages=q, **extra)


def test_temperature_on_a_model_without_sampling_controls_is_named_in_ignored(h):
    cm = h.chat_model()
    c = cm.chat_completions_create(messages=[ChatMessage.user(QUESTION)], temperature=0.3, top_p=0.5)
    if cm.capabilities.temperature:
        assert c.sajha.ignored == []
    else:
        assert c.sajha.ignored == ["temperature", "top_p"]
        if h.fake is not None:
            body = h.last()["body"]
            assert "temperature" not in json.dumps(body) and "top_p" not in json.dumps(body).lower()


@pytest.mark.parametrize("name", HTTP)
def test_native_async_create_and_stream(name):
    h = Harness(name)
    cm = h.chat_model()

    async def run():
        c = await cm.achat_completions_create(messages=[ChatMessage.user(QUESTION)], tools=[TOOL])
        chunks = [ch async for ch in cm.achat_completions_stream(messages=[ChatMessage.user(QUESTION)])]
        return c, chunks

    c, chunks = anyio.run(run)
    well_formed(c, name)
    assert c.finish_reason == "tool_calls"
    assert chunks[-1].is_usage and "".join(ch.choices[0].delta.content or "" for ch in chunks if ch.choices)
    assert h.provider._aclients is not None and len(h.fake.requests) >= 2   # served by the AsyncClient


def test_n_samples_without_native_n_makes_n_calls():
    h = Harness("mock")
    cm = h.provider.chat_model("mock-echo")
    c = cm.chat_completions_create(messages=[ChatMessage.user("hi")], n=3)
    assert [ch.index for ch in c.choices] == [0, 1, 2]
    assert h.provider.calls == 3
    single = cm.chat_completions_create(messages=[ChatMessage.user("hi")])
    assert c.usage.total_tokens == 3 * single.usage.total_tokens
