#!/usr/bin/env python3
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
A fake OAuth-protected MCP server for the local test lab: an OAuth 2.1 authorization server and an MCP
server that accepts only the access tokens it issued, on one port, offline. It lets SAJHA's per-user
OAuth sign-in for proxied servers (``auth.type: oauth_user``) run end to end on one laptop.

    python deployment/local-lab/fake_oauth_mcp.py                  # http://127.0.0.1:3020
    python deployment/local-lab/fake_oauth_mcp.py --port 3020 --no-dcr --client-id lab --client-secret s3cret

What it serves (``<base>`` is ``http://127.0.0.1:<port>``):

* ``<base>/mcp``: the MCP server (Streamable HTTP). Without a valid bearer token it answers HTTP 401
  with ``WWW-Authenticate: Bearer resource_metadata="<base>/.well-known/oauth-protected-resource/mcp"``.
  A token must be unexpired, unrevoked and issued for this resource (RFC 8707 ``resource``).
  Tools: ``whoami`` (who the token belongs to and its scopes), ``list_notes`` and ``add_note`` (needs
  the ``notes:write`` scope; without it the server answers HTTP 403 ``insufficient_scope``).
* Protected-resource metadata (RFC 9728) at ``/.well-known/oauth-protected-resource/mcp``.
* The authorization server, issuer ``<base>/as``: metadata (RFC 8414) at
  ``/.well-known/oauth-authorization-server/as``; ``/as/authorize`` (a form asking for a user name: no
  password, anyone at the keyboard is anyone they type), ``/as/token`` (authorization code with PKCE S256
  required, refresh with rotation), ``/as/register`` (dynamic client registration, RFC 7591; off with
  ``--no-dcr``) and ``/as/revoke`` (RFC 7009).

Everything is kept in memory, so a restart forgets every token (as a vendor revoking them would). A
dynamically registered public client survives it: its client id carries its redirect URIs, so SAJHA's
stored registration keeps working (a lab convenience no real authorization server offers). Never use it
for anything but a lab or a test.
The walkthrough is docs/tutorials/TUTORIAL_42_per_user_sign_in.md; the tests use :class:`FakeOAuthMCP`.
"""


import argparse
import base64
import hashlib
import html
import json
import secrets
import socket
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

READ_SCOPES = ['notes:read']
WRITE_SCOPE = 'notes:write'


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _json(status: int, doc: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
    from starlette.responses import JSONResponse
    return JSONResponse(doc, status_code=status, headers=headers or {})


class FakeOAuthMCP:
    """The fake authorization server and protected MCP server (in-process, a thread of uvicorn)."""

    def __init__(self, port: int = 0, *, dcr: bool = True, clients: Optional[Dict[str, Dict[str, Any]]] = None,
                 access_ttl: int = 3600, require_resource: bool = True, host: str = '127.0.0.1'):
        self.host = host
        if not port:
            s = socket.socket()
            s.bind((host, 0))
            port = s.getsockname()[1]
            s.close()
        self.port = port
        self.base = f'http://{host}:{port}'
        self.issuer = self.base + '/as'
        self.resource = self.base + '/mcp'
        self.url = self.resource
        self.dcr = dcr
        self.access_ttl = access_ttl
        self.require_resource = require_resource
        self.fail_refresh = False                    # tests: every refresh answers invalid_grant
        self.lock = threading.Lock()
        self.clients: Dict[str, Dict[str, Any]] = dict(clients or {})    # id -> {secret, redirect_uris}
        self.codes: Dict[str, Dict[str, Any]] = {}
        self.access: Dict[str, Dict[str, Any]] = {}  # token -> {user, scopes, resource, exp, client_id}
        self.refresh: Dict[str, Dict[str, Any]] = {}
        self.revoked: List[str] = []
        self.events: List[tuple] = []                # (what, details) of every request worth checking
        self.notes: Dict[str, List[str]] = {}
        self.app = self._build()
        self._uv = None
        self._t = None

    # ── tokens ─────────────────────────────────────────────────────
    def _issue(self, user: str, scopes: List[str], resource: str, client_id: str) -> Dict[str, Any]:
        at = 'fat_' + secrets.token_urlsafe(24)
        rt = 'frt_' + secrets.token_urlsafe(24)
        rec = {'user': user, 'scopes': scopes, 'resource': resource, 'client_id': client_id,
               'exp': time.time() + self.access_ttl}
        self.access[at] = rec
        self.refresh[rt] = dict(rec, exp=None)
        return {'access_token': at, 'token_type': 'Bearer', 'expires_in': self.access_ttl, 'refresh_token': rt,
                'scope': ' '.join(scopes)}

    def expire(self, user: Optional[str] = None) -> int:
        """Make every access token (of ``user``) invalid at once, as a vendor may (tests: refresh on 401)."""
        with self.lock:
            gone = [t for t, r in self.access.items() if user is None or r['user'] == user]
            for t in gone:
                self.access.pop(t, None)
        return len(gone)

    def token_info(self, auth_header: str) -> Optional[Dict[str, Any]]:
        tok = auth_header[7:] if auth_header.lower().startswith('bearer ') else ''
        rec = self.access.get(tok)
        if rec is None or rec['exp'] < time.time():
            return None
        if self.require_resource and rec['resource'] != self.resource:
            return None
        return rec

    # ── the app ────────────────────────────────────────────────────
    def _build(self):
        from mcp.server.mcpserver import Context, MCPServer
        from mcp_types import ToolAnnotations
        from starlette.applications import Starlette
        from starlette.responses import HTMLResponse, RedirectResponse
        from starlette.routing import Route
        me = self
        ro = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
        server = MCPServer('fake-oauth-mcp', title='Lab notes (OAuth)', version='1.0.0')

        def who(ctx: Context) -> Dict[str, Any]:
            return me.token_info((ctx.headers or {}).get('authorization', '')) or {}

        @server.tool(description='Who the server thinks you are, and the scopes your token carries.',
                     annotations=ro)
        def whoami(ctx: Context) -> str:
            rec = who(ctx)
            return f'you are {rec.get("user", "nobody")} with scopes {" ".join(rec.get("scopes") or [])}'

        @server.tool(description='Your notes.', annotations=ro)
        def list_notes(ctx: Context) -> str:
            return json.dumps(me.notes.get(who(ctx).get('user', ''), []))

        @server.tool(description='Add a note (needs the notes:write scope).')
        def add_note(text: str, ctx: Context) -> str:
            user = who(ctx).get('user', '')
            me.notes.setdefault(user, []).append(text[:200])
            return f'added for {user}'

        mcp_app = server.streamable_http_app(json_response=True)

        async def gate(scope, receive, send):
            if scope['type'] != 'http':
                return await mcp_app(scope, receive, send)
            hdrs = {k.decode().lower(): v.decode() for k, v in scope.get('headers') or []}
            body, more = b'', True
            while more:
                msg = await receive()
                body += msg.get('body', b'')
                more = msg.get('more_body', False)
            try:
                rpc = json.loads(body) if body[:1] == b'{' else {}
            except ValueError:
                rpc = {}
            rec = me.token_info(hdrs.get('authorization', ''))
            me.events.append(('mcp', {'user': (rec or {}).get('user'), 'method': rpc.get('method'),
                                      'tool': (rpc.get('params') or {}).get('name'),
                                      'session': hdrs.get('mcp-session-id', ''),
                                      'token': hdrs.get('authorization', '')[7:]}))
            status, text, extra = 0, b'', ''
            if rec is None:
                status, text = 401, b'{"error": "invalid_token"}'
                extra = (f'Bearer resource_metadata="{me.base}/.well-known/oauth-protected-resource/mcp"'
                         + (', error="invalid_token"' if hdrs.get('authorization') else ''))
            elif (rpc.get('method') == 'tools/call' and (rpc.get('params') or {}).get('name') == 'add_note'
                  and WRITE_SCOPE not in rec['scopes']):
                status, text = 403, b'{"error": "insufficient_scope", "message": "needs notes:write"}'
                extra = f'Bearer error="insufficient_scope", scope="{WRITE_SCOPE}"'
            if status:
                await send({'type': 'http.response.start', 'status': status,
                            'headers': [(b'content-type', b'application/json'),
                                        (b'content-length', str(len(text)).encode()),
                                        (b'www-authenticate', extra.encode())]})
                await send({'type': 'http.response.body', 'body': text})
                return
            done = {'v': False}

            async def replay():
                if not done['v']:
                    done['v'] = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
                return await receive()
            await mcp_app(scope, replay, send)

        async def prm(request):
            return _json(200, {'resource': me.resource, 'authorization_servers': [me.issuer],
                               'scopes_supported': READ_SCOPES + [WRITE_SCOPE], 'bearer_methods_supported': ['header'],
                               'resource_name': 'Lab notes'})

        async def asm(request):
            doc = {'issuer': me.issuer, 'authorization_endpoint': me.issuer + '/authorize',
                   'token_endpoint': me.issuer + '/token', 'revocation_endpoint': me.issuer + '/revoke',
                   'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
                   'code_challenge_methods_supported': ['S256'], 'scopes_supported': READ_SCOPES + [WRITE_SCOPE],
                   'token_endpoint_auth_methods_supported': ['none', 'client_secret_post', 'client_secret_basic']}
            if me.dcr:
                doc['registration_endpoint'] = me.issuer + '/register'
            return _json(200, doc)

        async def register(request):
            if not me.dcr:
                return _json(404, {'error': 'not_found'})
            data = await request.json()
            uris = [u for u in data.get('redirect_uris') or [] if isinstance(u, str)]
            if not uris:
                return _json(400, {'error': 'invalid_redirect_uri'})
            method = data.get('token_endpoint_auth_method') or 'none'
            cid = ('dyn_' + _b64url(json.dumps(uris).encode())) if method == 'none' else 'dyn_' + secrets.token_hex(8)
            secret = secrets.token_urlsafe(16) if method != 'none' else ''
            me.clients[cid] = {'secret': secret, 'redirect_uris': uris}
            me.events.append(('register', {'client_id': cid, 'redirect_uris': uris}))
            out = {'client_id': cid, 'redirect_uris': uris, 'token_endpoint_auth_method': method,
                   'grant_types': ['authorization_code', 'refresh_token']}
            if secret:
                out['client_secret'] = secret
            return _json(201, out)

        page = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lab notes: sign in</title><style>body{{font-family:sans-serif;max-width:30rem;margin:3rem auto;padding:0 1rem}}
input[type=text]{{width:100%;padding:.4rem;margin:.2rem 0 .8rem}}button{{padding:.5rem 1rem;margin-right:.5rem}}</style></head>
<body><h1>Lab notes</h1><p><b>{client}</b> asks to act as you with: <code>{scope}</code></p>
<form method="post" action="/as/authorize">{hidden}
<label for="user">Your lab user name (no password; this is a lab)</label><input type="text" id="user" name="user" value="" required autofocus>
<button type="submit" name="decision" value="allow">Allow</button><button type="submit" name="decision" value="deny">Deny</button>
</form></body></html>"""

        def bad_request(why: str):
            return HTMLResponse(f'<p>Bad authorization request: {html.escape(why)}</p>', status_code=400)

        def known(cid: str) -> Optional[Dict[str, Any]]:
            c = me.clients.get(cid)
            if c is None and cid.startswith('dyn_'):         # a public client registered before a restart
                try:
                    uris = json.loads(base64.urlsafe_b64decode(cid[4:] + '=' * (-len(cid[4:]) % 4)))
                    if isinstance(uris, list) and uris:
                        c = me.clients[cid] = {'secret': '', 'redirect_uris': [str(u) for u in uris]}
                except ValueError:
                    c = None
            return c

        def check_params(q) -> Optional[str]:
            c = known(q.get('client_id', ''))
            if c is None:
                return 'unknown client_id'
            if q.get('redirect_uri') not in c['redirect_uris']:
                return 'redirect_uri is not registered for this client'
            if q.get('response_type') != 'code':
                return 'response_type must be code'
            if q.get('code_challenge_method') != 'S256' or not q.get('code_challenge'):
                return 'PKCE with S256 is required'
            if me.require_resource and q.get('resource') != me.resource:
                return 'resource must name this server'
            return None

        async def authorize(request):
            if request.method == 'GET':
                q = dict(request.query_params)
                why = check_params(q)
                if why:
                    return bad_request(why)
                hidden = ''.join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                                 for k, v in q.items())
                return HTMLResponse(page.format(client=html.escape(q['client_id']),
                                                scope=html.escape(q.get('scope', '')), hidden=hidden))
            q = {k: str(v) for k, v in (await request.form()).items()}
            why = check_params(q)
            if why:
                return bad_request(why)
            back = q['redirect_uri'] + ('&' if '?' in q['redirect_uri'] else '?')
            if q.get('decision') == 'deny':
                return RedirectResponse(back + urlencode({'error': 'access_denied', 'state': q.get('state', '')}),
                                        status_code=302)
            user = (q.get('user') or '').strip()[:64] or 'nobody'
            asked = [s for s in (q.get('scope') or '').split() if s in READ_SCOPES + [WRITE_SCOPE]] or READ_SCOPES
            code = 'fc_' + secrets.token_urlsafe(16)
            me.codes[code] = {'client_id': q['client_id'], 'redirect_uri': q['redirect_uri'], 'user': user,
                              'challenge': q['code_challenge'], 'scopes': asked, 'resource': q.get('resource', ''),
                              'exp': time.time() + 300}
            me.events.append(('authorize', {'user': user, 'scopes': asked, 'resource': q.get('resource')}))
            return RedirectResponse(back + urlencode({'code': code, 'state': q.get('state', '')}), status_code=302)

        def client_of(request, form) -> Optional[str]:
            cid, secret = form.get('client_id', ''), form.get('client_secret', '')
            basic = request.headers.get('authorization', '')
            if basic.lower().startswith('basic '):
                try:
                    cid, secret = base64.b64decode(basic[6:]).decode().split(':', 1)
                except ValueError:
                    return None
            c = known(cid)
            if c is None or (c['secret'] and not secrets.compare_digest(c['secret'], secret)):
                return None
            return cid

        async def token(request):
            form = {k: str(v) for k, v in (await request.form()).items()}
            cid = client_of(request, form)
            if cid is None:
                return _json(401, {'error': 'invalid_client'})
            grant = form.get('grant_type')
            with me.lock:
                if grant == 'authorization_code':
                    rec = me.codes.pop(form.get('code', ''), None)
                    if rec is None or rec['exp'] < time.time() or rec['client_id'] != cid:
                        return _json(400, {'error': 'invalid_grant'})
                    if form.get('redirect_uri') != rec['redirect_uri']:
                        return _json(400, {'error': 'invalid_grant', 'error_description': 'redirect_uri mismatch'})
                    verifier = form.get('code_verifier', '')
                    if not verifier or _b64url(hashlib.sha256(verifier.encode()).digest()) != rec['challenge']:
                        me.events.append(('pkce_refused', {'user': rec['user']}))
                        return _json(400, {'error': 'invalid_grant', 'error_description': 'PKCE verification failed'})
                    if me.require_resource and form.get('resource') != rec['resource']:
                        return _json(400, {'error': 'invalid_target'})
                    me.events.append(('token', {'user': rec['user'], 'grant': grant}))
                    return _json(200, me._issue(rec['user'], rec['scopes'], rec['resource'], cid))
                if grant == 'refresh_token':
                    rec = me.refresh.get(form.get('refresh_token', ''))
                    if me.fail_refresh or rec is None or rec['client_id'] != cid:
                        me.events.append(('refresh_refused', {}))
                        return _json(400, {'error': 'invalid_grant'})
                    if me.require_resource and form.get('resource') != rec['resource']:
                        return _json(400, {'error': 'invalid_target'})
                    me.refresh.pop(form['refresh_token'], None)            # rotation
                    me.events.append(('token', {'user': rec['user'], 'grant': grant}))
                    return _json(200, me._issue(rec['user'], rec['scopes'], rec['resource'], cid))
            return _json(400, {'error': 'unsupported_grant_type'})

        async def revoke(request):
            form = {k: str(v) for k, v in (await request.form()).items()}
            tok = form.get('token', '')
            with me.lock:
                rec = me.refresh.pop(tok, None) or me.access.pop(tok, None)
                if rec is not None:                 # revoking a refresh token ends its access tokens too
                    for t, r in list(me.access.items()):
                        if r['user'] == rec['user'] and r['client_id'] == rec['client_id']:
                            me.access.pop(t, None)
                    me.revoked.append(rec['user'])
            me.events.append(('revoke', {'user': (rec or {}).get('user')}))
            return _json(200, {})

        async def home(request):
            return HTMLResponse(f'<p>Fake OAuth-protected MCP server. MCP: <code>{me.resource}</code>; '
                                f'issuer: <code>{me.issuer}</code>.</p>')

        oauth_app = Starlette(routes=[
            Route('/', home),
            Route('/.well-known/oauth-protected-resource/mcp', prm),
            Route('/.well-known/oauth-authorization-server/as', asm),
            Route('/as/register', register, methods=['POST']),
            Route('/as/authorize', authorize, methods=['GET', 'POST']),
            Route('/as/token', token, methods=['POST']),
            Route('/as/revoke', revoke, methods=['POST']),
        ])

        async def app(scope, receive, send):         # /mcp to the MCP server (its lifespan too), the rest OAuth
            if scope['type'] == 'lifespan' or (scope['type'] == 'http' and scope['path'].rstrip('/') == '/mcp'):
                return await gate(scope, receive, send)
            return await oauth_app(scope, receive, send)
        return app

    # ── running ────────────────────────────────────────────────────
    def start(self) -> 'FakeOAuthMCP':
        import uvicorn

        self._uv = uvicorn.Server(uvicorn.Config(self.app, host=self.host, port=self.port, log_level='warning',
                                                 lifespan='on'))
        self._t = threading.Thread(target=self._uv.run, daemon=True)
        self._t.start()
        deadline = time.time() + 10
        while not self._uv.started and time.time() < deadline:
            time.sleep(0.02)
        if not self._uv.started:
            raise RuntimeError('the fake OAuth MCP server did not start')
        return self

    def stop(self) -> None:
        if self._uv is not None:
            self._uv.should_exit = True
            self._t.join(10)

    def mcp_events(self, method: Optional[str] = None) -> List[Dict[str, Any]]:
        return [d for w, d in self.events if w == 'mcp' and (method is None or d['method'] == method)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--port', type=int, default=3020)
    ap.add_argument('--no-dcr', action='store_true', help='no dynamic client registration (an operator client)')
    ap.add_argument('--client-id', default='', help='a pre-registered client id')
    ap.add_argument('--client-secret', default='', help='its secret (empty: a public client)')
    ap.add_argument('--redirect-uri', default='http://localhost:3002/account/server-connections/oauth/callback',
                    help='the pre-registered client\'s redirect URI')
    ap.add_argument('--access-ttl', type=int, default=3600, help='access token lifetime in seconds')
    a = ap.parse_args()
    clients = {a.client_id: {'secret': a.client_secret, 'redirect_uris': [a.redirect_uri]}} if a.client_id else {}
    srv = FakeOAuthMCP(a.port, dcr=not a.no_dcr, clients=clients, access_ttl=a.access_ttl).start()
    print(f'MCP server (OAuth-protected): {srv.resource}')
    print(f'Authorization server (issuer): {srv.issuer}  dynamic registration: {"on" if srv.dcr else "off"}')
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == '__main__':
    main()
