# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Recorded-shape fake vendor APIs for the provider contract suite (httpx.MockTransport)."""

import json
from typing import Any, Dict, List, Optional

import httpx

TOOL_NAME = "calc_percentage_change"
TOOL_ARGS = {"old_value": 80, "new_value": 100}
STRUCT_TEXT = '{"answer": "ok", "citations": [], "caveats": []}'

ERRORS = {
    "rate": (429, {"error": {"type": "rate_limit_error", "message": "slow down"}}, {"retry-after": "3"}),
    "auth": (401, {"error": {"type": "authentication_error", "message": "invalid api key"}}, {}),
    "context": (400, {"error": {"type": "invalid_request_error",
                                "message": "prompt is too long: maximum context length exceeded"}}, {}),
    "server": (503, {"error": {"type": "overloaded_error", "message": "overloaded"}}, {}),
    "filter": (400, {"error": {"code": "content_filter",
                               "message": "The response was filtered: content management policy"}}, {}),
    "notfound": (404, {"error": {"message": "model not found"}}, {}),
}


def sse(events: List[Any], named: bool = False) -> bytes:
    out = []
    for e in events:
        if isinstance(e, str):
            out.append(f"data: {e}\n\n")
        elif named:
            out.append(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n")
        else:
            out.append(f"data: {json.dumps(e)}\n\n")
    return "".join(out).encode()


class FakeVendor:
    """One fake HTTP API. ``mode``: '' normal, an ERRORS key, or 'connect' (transport error)."""

    def __init__(self, kind: str):
        self.kind = kind
        self.mode = ""
        self.requests: List[Dict[str, Any]] = []

    @property
    def transport(self):
        return httpx.MockTransport(self.handle)

    @property
    def last(self) -> Dict[str, Any]:
        return self.requests[-1]

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = {}
        if request.content:
            try:
                body = json.loads(request.content)
            except Exception:
                body = {}
        rec = {"method": request.method, "url": str(request.url), "path": request.url.path,
               "params": dict(request.url.params), "headers": {k.lower(): v for k, v in request.headers.items()},
               "body": body}
        self.requests.append(rec)
        if self.mode == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if self.mode in ERRORS:
            status, payload, headers = ERRORS[self.mode]
            return httpx.Response(status, json=payload, headers=headers)
        return getattr(self, f"_{self.kind}")(rec)

    # ── OpenAI Chat Completions family ─────────────────────────
    def _openai(self, rec):
        b = rec["body"]
        if rec["method"] == "GET" and rec["path"].endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [{"id": "my-local-model"}, {"id": "bge-m3"}]})
        if rec["path"].endswith("/embeddings"):
            inputs = b["input"]
            return httpx.Response(200, json={"data": [{"index": i, "embedding": [0.1 * (i + 1), 0.2, 0.3]}
                                                      for i in range(len(inputs))], "model": b["model"]})
        has_result = any(m.get("role") == "tool" for m in b.get("messages", []))
        usage = {"prompt_tokens": 12, "completion_tokens": 5, "prompt_tokens_details": {"cached_tokens": 2}}
        if b.get("tools") and not has_result:
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [{"id": "call_abc", "type": "function",
                                   "function": {"name": TOOL_NAME, "arguments": json.dumps(TOOL_ARGS)}}]}
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": STRUCT_TEXT if b.get("response_format") else "Hello there"}
            finish = "stop"
        if b.get("stream"):
            chunks = []
            if msg.get("tool_calls"):
                args = json.dumps(TOOL_ARGS)
                chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [
                    {"index": 0, "id": "call_abc", "type": "function",
                     "function": {"name": TOOL_NAME, "arguments": args[:7]}}]}}]})
                chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [
                    {"index": 0, "function": {"arguments": args[7:]}}]}}]})
            else:
                text = msg["content"]
                chunks += [{"choices": [{"index": 0, "delta": {"content": text[:5]}}]},
                           {"choices": [{"index": 0, "delta": {"content": text[5:]}}]}]
            chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
            chunks.append({"choices": [], "usage": usage})
            return httpx.Response(200, content=sse(chunks + ["[DONE]"]),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "x", "model": b.get("model"), "usage": usage,
                                         "choices": [{"index": 0, "message": msg, "finish_reason": finish}]})

    # ── Anthropic Messages ─────────────────────────────────────
    def _anthropic(self, rec):
        b = rec["body"]
        has_result = any(isinstance(m.get("content"), list) and
                         any(c.get("type") == "tool_result" for c in m["content"]) for m in b.get("messages", []))
        usage = {"input_tokens": 20, "output_tokens": 6, "cache_read_input_tokens": 0}
        if b.get("tools") and not has_result:
            content = [{"type": "thinking", "thinking": "", "signature": "sig"},
                       {"type": "tool_use", "id": "toolu_1", "name": TOOL_NAME, "input": TOOL_ARGS}]
            stop = "tool_use"
        else:
            content = [{"type": "text", "text": STRUCT_TEXT if b.get("output_config") else "Hello there"}]
            stop = "end_turn"
        if b.get("stream"):
            ev = [{"type": "message_start", "message": {"model": b["model"], "usage": {"input_tokens": 20}}}]
            for i, c in enumerate(content):
                if c["type"] == "tool_use":
                    ev.append({"type": "content_block_start", "index": i,
                               "content_block": {"type": "tool_use", "id": c["id"], "name": c["name"], "input": {}}})
                    js = json.dumps(c["input"])
                    ev.append({"type": "content_block_delta", "index": i,
                               "delta": {"type": "input_json_delta", "partial_json": js[:6]}})
                    ev.append({"type": "content_block_delta", "index": i,
                               "delta": {"type": "input_json_delta", "partial_json": js[6:]}})
                elif c["type"] == "text":
                    ev.append({"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}})
                    ev.append({"type": "content_block_delta", "index": i,
                               "delta": {"type": "text_delta", "text": c["text"][:5]}})
                    ev.append({"type": "content_block_delta", "index": i,
                               "delta": {"type": "text_delta", "text": c["text"][5:]}})
                else:
                    ev.append({"type": "content_block_start", "index": i, "content_block": dict(c)})
                ev.append({"type": "content_block_stop", "index": i})
            ev.append({"type": "message_delta", "delta": {"stop_reason": stop}, "usage": {"output_tokens": 6}})
            ev.append({"type": "message_stop"})
            return httpx.Response(200, content=sse(ev, named=True), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "msg_1", "model": b["model"], "content": content,
                                         "stop_reason": stop, "usage": usage})

    # ── Gemini generateContent ─────────────────────────────────
    def _gemini(self, rec):
        b = rec["body"]
        path = rec["path"]
        if path.endswith(":batchEmbedContents"):
            return httpx.Response(200, json={"embeddings": [{"values": [0.5, 0.1]} for _ in b["requests"]]})
        has_result = any("functionResponse" in p for c in b.get("contents", []) for p in c.get("parts", []))
        usage = {"promptTokenCount": 15, "candidatesTokenCount": 4}
        if b.get("tools") and not has_result:
            parts = [{"functionCall": {"name": TOOL_NAME, "args": TOOL_ARGS}, "thoughtSignature": "abc"}]
        else:
            gc = b.get("generationConfig") or {}
            parts = [{"text": STRUCT_TEXT if gc.get("responseMimeType") == "application/json" else "Hello there"}]
        cand = {"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}
        if path.endswith(":streamGenerateContent"):
            if "text" in parts[0]:
                t = parts[0]["text"]
                chunks = [{"candidates": [{"content": {"role": "model", "parts": [{"text": t[:5]}]}}]},
                          {"candidates": [{"content": {"role": "model", "parts": [{"text": t[5:]}]},
                                           "finishReason": "STOP"}], "usageMetadata": usage}]
            else:
                chunks = [{"candidates": [cand], "usageMetadata": usage}]
            return httpx.Response(200, content=sse(chunks), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"candidates": [cand], "usageMetadata": usage, "modelVersion": "gm"})

    # ── Cohere v2 ──────────────────────────────────────────────
    def _cohere(self, rec):
        b = rec["body"]
        if rec["path"].endswith("/v2/embed"):
            return httpx.Response(200, json={"embeddings": {"float": [[0.3, 0.4] for _ in b["texts"]]}})
        has_result = any(m.get("role") == "tool" for m in b.get("messages", []))
        usage = {"tokens": {"input_tokens": 10, "output_tokens": 3}}
        if b.get("tools") and not has_result:
            message = {"role": "assistant", "tool_plan": "I will calculate.",
                       "tool_calls": [{"id": "co_1", "type": "function",
                                       "function": {"name": TOOL_NAME, "arguments": json.dumps(TOOL_ARGS)}}]}
            finish = "TOOL_CALL"
        else:
            message = {"role": "assistant", "content": [{"type": "text", "text": STRUCT_TEXT if b.get("response_format")
                                                         else "Hello there"}]}
            finish = "COMPLETE"
        if b.get("stream"):
            ev = [{"type": "message-start"}]
            if "tool_calls" in message:
                tc = message["tool_calls"][0]
                ev.append({"type": "tool-call-start", "index": 0, "delta": {"message": {"tool_calls": {
                    "id": tc["id"], "type": "function", "function": {"name": TOOL_NAME, "arguments": ""}}}}})
                args = tc["function"]["arguments"]
                ev.append({"type": "tool-call-delta", "index": 0,
                           "delta": {"message": {"tool_calls": {"function": {"arguments": args[:5]}}}}})
                ev.append({"type": "tool-call-delta", "index": 0,
                           "delta": {"message": {"tool_calls": {"function": {"arguments": args[5:]}}}}})
            else:
                t = message["content"][0]["text"]
                for frag in (t[:5], t[5:]):
                    ev.append({"type": "content-delta", "index": 0,
                               "delta": {"message": {"content": {"text": frag}}}})
            ev.append({"type": "message-end", "delta": {"finish_reason": finish, "usage": usage}})
            return httpx.Response(200, content=sse(ev, named=True), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "c1", "finish_reason": finish, "message": message, "usage": usage})

    # ── Ollama native ──────────────────────────────────────────
    def _ollama(self, rec):
        b = rec["body"]
        path = rec["path"]
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}, {"name": "nomic-embed-text:latest"},
                                                        {"name": "qwen3:8b"}]})
        if path == "/api/show":
            m = b.get("model", "")
            caps = ["embedding"] if "embed" in m else ["completion", "tools"]
            return httpx.Response(200, json={"capabilities": caps, "model_info": {"llama.context_length": 131072}})
        if path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[0.7, 0.1] for _ in b["input"]]})
        has_result = any(m.get("role") == "tool" for m in b.get("messages", []))
        if b.get("tools") and not has_result:
            message = {"role": "assistant", "content": "",
                       "tool_calls": [{"function": {"name": TOOL_NAME, "arguments": TOOL_ARGS}}]}
        else:
            message = {"role": "assistant", "content": STRUCT_TEXT if b.get("format") else "Hello there"}
        final = {"model": b["model"], "done": True, "done_reason": "stop", "prompt_eval_count": 9, "eval_count": 4}
        if b.get("stream"):
            lines = []
            if message.get("tool_calls"):
                lines.append({"model": b["model"], "message": message, "done": False})
            else:
                t = message["content"]
                lines += [{"message": {"role": "assistant", "content": t[:5]}, "done": False},
                          {"message": {"role": "assistant", "content": t[5:]}, "done": False}]
            lines.append({**final, "message": {"role": "assistant", "content": ""}})
            return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode(),
                                  headers={"content-type": "application/x-ndjson"})
        return httpx.Response(200, json={**final, "message": message})


# ── Bedrock: a fake bedrock-runtime client ──────────────────────

class FakeClientError(Exception):
    def __init__(self, code, message="error"):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class FakeBedrockClient:
    def __init__(self):
        self.mode = ""
        self.requests: List[Dict[str, Any]] = []

    @property
    def last(self):
        return {"body": self.requests[-1], "headers": {}, "path": "", "url": ""}

    def _raise(self):
        codes = {"rate": ("ThrottlingException", "Too many requests"),
                 "auth": ("AccessDeniedException", "not authorized"),
                 "context": ("ValidationException", "Input is too long for requested model."),
                 "server": ("ServiceUnavailableException", "unavailable"),
                 "filter": ("ValidationException", "blocked by guardrail"),
                 "notfound": ("ResourceNotFoundException", "no such model")}
        if self.mode == "connect":
            raise type("EndpointConnectionError", (Exception,), {})("cannot connect")
        if self.mode in codes:
            raise FakeClientError(*codes[self.mode])

    def _reply(self, kw):
        has_result = any("toolResult" in c for m in kw["messages"] for c in m["content"])
        if kw.get("toolConfig") and not has_result:
            return [{"toolUse": {"toolUseId": "tu_1", "name": TOOL_NAME, "input": TOOL_ARGS}}], "tool_use"
        return [{"text": "Hello there"}], "end_turn"

    def converse(self, **kw):
        self.requests.append(kw)
        self._raise()
        content, stop = self._reply(kw)
        return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": stop,
                "usage": {"inputTokens": 11, "outputTokens": 4}}

    def converse_stream(self, **kw):
        self.requests.append(kw)
        self._raise()
        content, stop = self._reply(kw)
        events = [{"messageStart": {"role": "assistant"}}]
        for i, c in enumerate(content):
            if "toolUse" in c:
                events.append({"contentBlockStart": {"contentBlockIndex": i, "start": {"toolUse": {
                    "toolUseId": c["toolUse"]["toolUseId"], "name": c["toolUse"]["name"]}}}})
                js = json.dumps(c["toolUse"]["input"])
                events += [{"contentBlockDelta": {"contentBlockIndex": i, "delta": {"toolUse": {"input": js[:4]}}}},
                           {"contentBlockDelta": {"contentBlockIndex": i, "delta": {"toolUse": {"input": js[4:]}}}}]
            else:
                t = c["text"]
                events += [{"contentBlockDelta": {"contentBlockIndex": i, "delta": {"text": t[:5]}}},
                           {"contentBlockDelta": {"contentBlockIndex": i, "delta": {"text": t[5:]}}}]
        events += [{"messageStop": {"stopReason": stop}}, {"metadata": {"usage": {"inputTokens": 11, "outputTokens": 4}}}]
        return {"stream": events}

    def invoke_model(self, modelId, body, contentType, accept):
        self._raise()
        b = json.loads(body)
        self.requests.append({"modelId": modelId, **b})
        import io
        if "texts" in b:
            return {"body": io.BytesIO(json.dumps({"embeddings": [[0.2, 0.2] for _ in b["texts"]]}).encode())}
        return {"body": io.BytesIO(json.dumps({"embedding": [0.9, 0.1]}).encode())}
