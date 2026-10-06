"""
Acme LLM's API, faked — for tests (an httpx MockTransport) and for trying the example
provider end to end in the Ask SAJHA page (a small local HTTP server).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

It is a wiring fake, not a model: when functions are offered and no tool result has come
back yet, it calls the first function named in ``plan`` (default: calc_percentage_change with
80 -> 100); after a tool result it answers from that result; otherwise it says "Hello there".

    python -m sajha.examples.intelligence.acme_fake_server --port 8765

``mode`` injects failures: rate, auth, context, server, filter, notfound, connect (the same
names the provider contract suite uses).
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_PLAN = {"calc_percentage_change": {"old_value": 80, "new_value": 100}}

#: mode -> (status, fault kind, headers)
FAULT_MODES = {
    "rate": (429, "quota", {"x-acme-retry-in": "3"}),
    "auth": (401, "auth", {}),
    "context": (400, "too_long", {}),
    "server": (503, "busy", {}),
    "filter": (451, "policy", {}),
    "notfound": (404, "no_such_model", {}),
}

MODELS = [
    {"id": "acme-large", "kind": "chat", "context": 128000, "max_out": 8192, "features": ["functions", "json", "stream"]},
    {"id": "acme-small", "kind": "chat", "context": 32000, "max_out": 4096, "features": ["functions", "stream"]},
    {"id": "acme-coder-preview", "kind": "chat", "context": 64000, "max_out": 8192, "features": ["functions"]},
    {"id": "acme-embed", "kind": "embedding", "dims": 768},
]


def _sse(events: List[tuple]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


class AcmeFakeServer:
    def __init__(self, plan: Optional[Dict[str, Dict[str, Any]]] = None):
        self.plan = dict(DEFAULT_PLAN if plan is None else plan)
        self.mode = ""
        self.requests: List[Dict[str, Any]] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def last(self) -> Dict[str, Any]:
        return self.requests[-1]

    def handle(self, request: httpx.Request) -> httpx.Response:
        try:
            body = json.loads(request.content) if request.content else {}
        except ValueError:
            body = {}
        rec = {"method": request.method, "url": str(request.url), "path": request.url.path,
               "headers": {k.lower(): v for k, v in request.headers.items()}, "body": body}
        self.requests.append(rec)
        if self.mode == "connect":
            raise httpx.ConnectError("connection refused", request=request)
        if self.mode in FAULT_MODES:
            status, kind, headers = FAULT_MODES[self.mode]
            return httpx.Response(status, json={"fault": {"kind": kind, "detail": "injected"}}, headers=headers)
        if not rec["headers"].get("x-acme-key"):
            return httpx.Response(401, json={"fault": {"kind": "auth", "detail": "X-Acme-Key missing"}})
        path = rec["path"]
        if path == "/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/v1/models":
            return httpx.Response(200, json={"models": MODELS})
        if path == "/v1/embed":
            return httpx.Response(200, json={"vectors": [[0.1 * (i + 1), 0.2, 0.3] for i in range(len(body["inputs"]))],
                                             "tokens": {"in": 4 * len(body["inputs"])}})
        if path == "/v1/generate":
            return self._generate(body)
        return httpx.Response(404, json={"fault": {"kind": "not_found", "detail": path}})

    def _generate(self, body: Dict[str, Any]) -> httpx.Response:
        turns = body.get("turns") or []
        last_user = max((i for i, t in enumerate(turns) if t.get("speaker") == "user"), default=-1)
        results = [t for t in turns[last_user + 1:] if t.get("speaker") == "tool"]
        offered = {f["name"] for f in body.get("functions") or []}
        calls = []
        if offered and not results:
            calls = [{"call_id": "acme_1", "function": name, "args": args}
                     for name, args in self.plan.items() if name in offered][:1]
        if calls:
            text, stop = "", "call"
        elif body.get("json_schema"):
            answer = self._answer(results) if results else "ok"
            text = json.dumps({"answer": answer, "caveats": [],
                               "citations": [t["call_id"] for t in results if not t.get("error")]})
            stop = "done"
        else:
            text, stop = (self._answer(results) if results else "Hello there"), "done"
        tokens = {"in": 14 + 3 * len(turns), "out": 5, "cached": 0}
        if body.get("stream"):
            events: List[tuple] = []
            if text:
                events += [("text", {"delta": text[:5]}), ("text", {"delta": text[5:]})]
            for i, c in enumerate(calls):
                args = json.dumps(c["args"])
                events.append(("call", {"index": i, "call_id": c["call_id"], "function": c["function"],
                                        "args_fragment": args[:7]}))
                events.append(("call", {"index": i, "args_fragment": args[7:]}))
            events.append(("end", {"stop": stop, "tokens": tokens}))
            return httpx.Response(200, content=_sse(events), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"model": body.get("model"), "stop": stop, "tokens": tokens,
                                         "output": {"text": text, "calls": calls}})

    @staticmethod
    def _answer(results: List[Dict[str, Any]]) -> str:
        r = results[-1]
        return ("The tool failed: " if r.get("error") else "From the tool result: ") + str(r.get("result"))[:300]


def serve(port: int = 8765, host: str = "127.0.0.1", fake: Optional[AcmeFakeServer] = None):
    """A ThreadingHTTPServer over the fake (call .serve_forever(); port 0 picks a free port)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    fake = fake or AcmeFakeServer()

    class Handler(BaseHTTPRequestHandler):
        def _relay(self):
            n = int(self.headers.get("content-length") or 0)
            req = httpx.Request(self.command, f"http://{host}{self.path}", headers=dict(self.headers.items()),
                                content=self.rfile.read(n) if n else b"")
            resp = fake.handle(req)
            body = resp.content
            self.send_response(resp.status_code)
            for k, v in resp.headers.items():
                if k.lower() not in ("content-length", "transfer-encoding"):
                    self.send_header(k, v)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = _relay

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.fake = fake
    return server


if __name__ == "__main__":       # pragma: no cover
    ap = argparse.ArgumentParser(description="A fake Acme LLM API for the extension examples")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"fake Acme LLM on http://{a.host}:{a.port} (any X-Acme-Key is accepted)")
    serve(a.port, a.host).serve_forever()
