"""
SAJHA MCP Server — a small petstore API for Tutorial 19 (Import an OpenAPI spec).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Standard library only. Serves its OpenAPI description at /openapi.yaml (servers pointing at
itself) and the API under /v1, with pets kept in memory:

    GET /v1/pets[?limit=N&status=...]   POST /v1/pets   GET|PUT|DELETE /v1/pets/{petId}

When PETSTORE_KEY is set, every /v1 call must send it in the X-API-Key header.

    python sajha/examples/api_import/petstore_server.py --port 8766
"""

from __future__ import annotations

import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SPEC = Path(__file__).with_name('petstore.yaml')


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.next_id = 4
        self.pets = {1: {'id': 1, 'name': 'Rex', 'tag': 'dog'}, 2: {'id': 2, 'name': 'Tom', 'tag': 'cat'},
                     3: {'id': 3, 'name': 'Polly', 'tag': None}}


def make_handler(store: Store, port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print(f'{self.command} {self.path} -> {args[1] if len(args) > 1 else ""}')

        def _send(self, status, body=None, ctype='application/json'):
            raw = b'' if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
            self.send_response(status)
            if raw:
                self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, status, message):
            self._send(status, {'code': status, 'message': message})

        def _body(self):
            n = int(self.headers.get('Content-Length') or 0)
            try:
                return json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                return None

        def _route(self):
            u = urlsplit(self.path)
            if u.path == '/openapi.yaml':
                text = SPEC.read_text(encoding='utf-8').replace(
                    'http://petstore.swagger.io/{basePath}', f'http://127.0.0.1:{port}/{{basePath}}')
                return self._send(200, text.encode(), 'application/yaml')
            if not u.path.startswith('/v1/pets'):
                return self._error(404, 'not found')
            key = os.environ.get('PETSTORE_KEY')
            if key and self.headers.get('X-API-Key') != key:
                return self._error(401, 'missing or wrong X-API-Key')
            parts = [p for p in u.path.split('/') if p][1:]          # ['pets'] or ['pets', '<id>']
            with store.lock:
                if len(parts) == 1:
                    if self.command == 'GET':
                        q = parse_qs(u.query)
                        pets = list(store.pets.values())
                        limit = int((q.get('limit') or ['100'])[0])
                        return self._send(200, pets[:limit])
                    if self.command == 'POST':
                        body = self._body()
                        if not isinstance(body, dict) or not body.get('name'):
                            return self._error(400, 'a pet needs a name')
                        pet = {'id': store.next_id, 'name': body['name'], 'tag': body.get('tag')}
                        store.pets[store.next_id] = pet
                        store.next_id += 1
                        return self._send(201, pet)
                    return self._error(405, 'method not allowed')
                if not parts[1].isdigit() or int(parts[1]) not in store.pets:
                    return self._error(404, f'pet {parts[1]} not found')
                pid = int(parts[1])
                if self.command == 'GET':
                    return self._send(200, store.pets[pid])
                if self.command == 'PUT':
                    body = self._body() or {}
                    store.pets[pid] = {'id': pid, 'name': body.get('name', ''), 'tag': body.get('tag')}
                    return self._send(200, store.pets[pid])
                if self.command == 'DELETE':
                    del store.pets[pid]
                    return self._send(204)
                return self._error(405, 'method not allowed')

        do_GET = do_POST = do_PUT = do_DELETE = _route

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8766)
    a = ap.parse_args()
    server = ThreadingHTTPServer((a.host, a.port), make_handler(Store(), a.port))
    print(f'petstore on http://{a.host}:{a.port}  (spec: /openapi.yaml, API: /v1)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
