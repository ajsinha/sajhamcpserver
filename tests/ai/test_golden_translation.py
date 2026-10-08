# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Golden translation tests: canonical Chat Completions requests -> each vendor's wire format, and
recorded vendor replies and stream events -> canonical, compared with stored expectations.
No network: the adapters' translation functions are pure (LLM Tools.md §13.5).

    tests/ai/golden/recorded/<vendor>.json   recorded vendor payloads (replies, stream events)
    tests/ai/golden/expected/<provider>.json the translations this code produces, reviewed

A change in translation shows up as a diff of the expected file. After reviewing it, regenerate:

    SAJHA_UPDATE_GOLDEN=1 python -m pytest tests/ai/test_golden_translation.py
"""

import base64
import json
import os

import pytest

from sajha.ai.llm import registry
from sajha.ai.llm.canonical import ChatCompletionRequest, ChunkAccumulator
from sajha.ai.llm.errors import LLMError

HERE = os.path.dirname(__file__)
RECORDED = os.path.join(HERE, "golden", "recorded")
EXPECTED = os.path.join(HERE, "golden", "expected")
UPDATE = os.environ.get("SAJHA_UPDATE_GOLDEN") == "1"

PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
QUOTE = {"type": "function", "function": {"name": "get_quote", "description": "Latest price for a ticker",
                                          "parameters": {"type": "object", "properties": {"symbol": {"type": "string"}},
                                                         "required": ["symbol"]}}}
FX = {"type": "function", "function": {"name": "get_fx", "description": "FX rate",
                                       "parameters": {"type": "object", "properties": {"pair": {"type": "string"}}}}}
SCHEMA = {"type": "object", "properties": {"symbol": {"type": "string"}, "price": {"type": "number"}},
          "required": ["symbol", "price"], "additionalProperties": False}
Q = "What did AAPL and MSFT close at?"

# One canonical request per feature; each provider translates it, or refuses it with a named error.
REQUESTS = {
    "plain": {"messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": Q}],
              "temperature": 0.2, "max_completion_tokens": 300, "stop": ["END"]},
    "developer_role": {"messages": [{"role": "developer", "content": "Answer in one line."},
                                    {"role": "user", "content": Q}]},
    "tools": {"messages": [{"role": "user", "content": Q}], "tools": [QUOTE, FX]},
    "tool_required": {"messages": [{"role": "user", "content": Q}], "tools": [QUOTE, FX], "tool_choice": "required"},
    "tool_named": {"messages": [{"role": "user", "content": Q}], "tools": [QUOTE, FX],
                   "tool_choice": {"type": "function", "function": {"name": "get_quote"}}},
    "tool_named_only_tool": {"messages": [{"role": "user", "content": Q}], "tools": [QUOTE],
                             "tool_choice": {"type": "function", "function": {"name": "get_quote"}}},
    "tool_none": {"messages": [{"role": "user", "content": Q}], "tools": [QUOTE], "tool_choice": "none"},
    "parallel_off": {"messages": [{"role": "user", "content": Q}], "tools": [QUOTE], "parallel_tool_calls": False},
    "tool_round_trip": {"messages": [
        {"role": "user", "content": Q},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_q1", "type": "function", "function": {"name": "get_quote", "arguments": "{\"symbol\":\"AAPL\"}"}},
            {"id": "call_q2", "type": "function", "function": {"name": "get_quote", "arguments": "{\"symbol\":\"MSFT\"}"}}]},
        {"role": "tool", "tool_call_id": "call_q1", "content": "{\"price\": 231.4}", "sajha": {"structured": True}},
        {"role": "tool", "tool_call_id": "call_q2", "content": "upstream timeout", "sajha": {"is_error": True}}],
        "tools": [QUOTE]},
    "structured": {"messages": [{"role": "user", "content": "AAPL quote as JSON"}],
                   "response_format": {"type": "json_schema", "json_schema": {"name": "quote", "schema": SCHEMA,
                                                                              "strict": True}}},
    "json_object": {"messages": [{"role": "user", "content": "AAPL quote as JSON"}],
                    "response_format": {"type": "json_object"}},
    "image": {"messages": [{"role": "user", "content": [
        {"type": "text", "text": "What is in this chart?"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG}"}}]}]},
    "image_http_url": {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://example.com/chart.png"}}]}]},
    "sampling": {"messages": [{"role": "user", "content": Q}], "top_p": 0.9, "seed": 7},
    "reasoning": {"messages": [{"role": "user", "content": Q}], "reasoning_effort": "low"},
    "passthrough": {"messages": [{"role": "user", "content": Q}], "presence_penalty": 0.5, "logprobs": True},
    "n2": {"messages": [{"role": "user", "content": Q}], "n": 2},
}

GOLDEN_MODEL = {"tools": True, "structured_output": True, "vision": True, "tags": ["reasoning"]}

# provider instance -> (provider type, model id, config, recorded vendor file)
PROVIDERS = {
    "openai": ("openai", "gpt-golden", {}, "openai"),
    "azure_openai": ("azure_openai", "gpt-golden", {"base_url": "https://res.openai.azure.com",
                                                    "deployments": {"gpt-golden": "golden-dep"}}, None),
    "mistral": ("mistral", "mistral-golden", {}, None),
    "groq": ("groq", "groq-golden", {}, None),
    "anthropic": ("anthropic", "claude-golden", {}, "anthropic"),
    "anthropic_vertex": ("anthropic", "claude-golden@20260901",
                         {"platform": "vertex", "vertex_project": "acme-prj", "vertex_location": "us-east5"}, None),
    "gemini": ("gemini", "gemini-golden", {}, "gemini"),
    "gemini_vertex": ("gemini", "gemini-golden", {"platform": "vertex", "vertex_project": "acme-prj",
                                                  "vertex_location": "europe-west4"}, None),
    "cohere": ("cohere", "command-golden", {}, "cohere"),
    "bedrock": ("bedrock", "bedrock-golden", {"region": "us-east-1"}, "bedrock"),
    "ollama": ("ollama", "ollama-golden", {"live_models": False}, "ollama"),
}


def _model(name):
    kind, model_id, extra, _ = PROVIDERS[name]
    caps = dict(GOLDEN_MODEL)
    if kind == "bedrock":
        caps["structured_output"] = False
    cfg = {"enabled": True, "api_key": "k", **extra, "models": [{"id": model_id, **caps}]}
    if kind == "bedrock":
        cfg.pop("api_key")
    provider = registry.provider_class(kind).from_settings(name, cfg, environ={})
    return provider.chat_model(model_id)


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=lambda b: {"bytes_b64": base64.b64encode(b).decode()}
                                 if isinstance(b, (bytes, bytearray)) else str(b)))


def _wire(model, request: ChatCompletionRequest, stream: bool = False):
    try:
        prep = model.prepare(request, stream=stream)
        if hasattr(model, "request_kwargs"):          # Bedrock: boto3 keyword arguments
            out = {"converse": _jsonable(model.request_kwargs(prep.request))}
            if prep.ignored:
                out["ignored"] = prep.ignored
            return out
        call = model.wire(prep.request, stream)
        out = {"path": call.path, "body": _jsonable(call.body)}
        if call.params:
            out["params"] = call.params
        if prep.ignored:
            out["ignored"] = prep.ignored
        if prep.structured == "emulated":
            out["structured_output"] = "emulated"
        return out
    except LLMError as e:
        return {"error": e.code, "message": str(e)}


def _completion(comp):
    d = comp.to_dict()
    d.pop("id", None)
    d.pop("created", None)
    for ch in comp.choices:                       # provider state is private; record that it is kept
        if ch.message.sajha and ch.message.sajha.provider_state:
            d["choices"][ch.index]["message"]["sajha"]["provider_state"] = _jsonable(ch.message.sajha.provider_state)
    return d


def _parse(model, request, payload):
    try:
        if hasattr(model, "request_kwargs"):
            from sajha.ai.llm.providers.bedrock import parse_bedrock
            return _completion(parse_bedrock(payload, model.id))
        return _completion(model.parse(payload, request))
    except LLMError as e:
        return {"error": e.code, "message": str(e)}


def _translator(model, request):
    if hasattr(model, "request_kwargs"):
        from sajha.ai.llm.providers.bedrock import BedrockStreamTranslator
        return BedrockStreamTranslator(model, request)
    return model.translator(request)


def _stream(model, request, events):
    tr = _translator(model, request)
    chunks = []
    try:
        for ev in events:
            event, data = (ev if isinstance(ev, list) else ("", ev))
            chunks += tr.feed(event, data)
        chunks += tr.close()
    except LLMError as e:
        return {"error": e.code, "message": str(e)}
    acc = ChunkAccumulator()
    for c in chunks:
        acc.add(c)
    out = []
    for c in chunks:
        d = c.to_dict()
        d.pop("id", None)
        d.pop("created", None)
        out.append(d)
    return {"chunks": out, "completion": _completion(acc.result())}


def translate(name):
    model = _model(name)
    out = {"requests": {case: _wire(model, ChatCompletionRequest.model_validate(r)) for case, r in REQUESTS.items()},
           "stream_request": _wire(model, ChatCompletionRequest.model_validate(REQUESTS["tools"]), stream=True)}
    recorded = PROVIDERS[name][3]
    if recorded:
        with open(os.path.join(RECORDED, f"{recorded}.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        req = ChatCompletionRequest.model_validate(REQUESTS["tools"])
        out["replies"] = {case: _parse(model, req, payload) for case, payload in rec["replies"].items()}
        out["streams"] = {case: _stream(model, req, events) for case, events in rec["streams"].items()}
    return out


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_golden_translation(name):
    got = translate(name)
    path = os.path.join(EXPECTED, f"{name}.json")
    if UPDATE or not os.path.exists(path):
        os.makedirs(EXPECTED, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=1, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        if not UPDATE:
            pytest.fail(f"{path} did not exist; written now — review it and run again")
    with open(path, encoding="utf-8") as fh:
        expected = json.load(fh)
    flat_e, flat_g = _flatten(expected), _flatten(got)
    for key in sorted(set(flat_e) | set(flat_g)):
        assert flat_g.get(key) == flat_e.get(key), f"{name}: {key} differs from {path}"


def _flatten(d):
    out = {}
    for section, value in d.items():
        if section in ("requests", "replies", "streams"):
            out.update({f"{section}/{case}": v for case, v in value.items()})
        else:
            out[section] = value
    return out
