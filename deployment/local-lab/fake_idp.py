#!/usr/bin/env python3
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
A fake OpenID Connect identity provider for the local test lab: enough of the authorization code flow
with PKCE for SAJHA's console single sign-on (auth.sso) to run on one laptop, offline.

    python deployment/local-lab/fake_idp.py                 # http://127.0.0.1:3010, client_id sajha-lab
    python deployment/local-lab/fake_idp.py --port 3010 --client-id sajha-lab

It signs ID tokens with an RSA key it makes at start (RS256, published at /jwks), asks for a user name
and groups on a plain form (no password: anyone at the keyboard is anyone they type), remembers the
person in its own cookie so a second SAJHA instance signs in without the form, and ends that on
/logout. Everything is kept in memory. Never use it for anything but a lab.

Endpoints: /.well-known/openid-configuration, /authorize, /token, /jwks, /logout.
The walkthrough is docs/tutorials/TUTORIAL_39_console_single_sign_on.md.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import secrets
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = uuid.uuid4().hex[:16]
CODES: dict = {}          # code -> {client_id, redirect_uri, nonce, challenge, user, groups, at}
SESSIONS: dict = {}       # idp session id -> {user, groups}
LOCK = threading.Lock()
ARGS = argparse.Namespace()


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def jwk() -> dict:
    n = KEY.public_key().public_numbers()
    return {'kty': 'RSA', 'use': 'sig', 'alg': 'RS256', 'kid': KID,
            'n': b64url(n.n.to_bytes((n.n.bit_length() + 7) // 8, 'big')), 'e': b64url(n.e.to_bytes(3, 'big'))}


def issuer() -> str:
    return f'http://127.0.0.1:{ARGS.port}'


FORM = """<!doctype html><html><head><meta charset="utf-8"><title>Lab identity provider</title>
<style>body{{font-family:sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem}}input{{width:100%;padding:.4rem;margin:.2rem 0 .8rem}}
button{{padding:.5rem 1rem}}small{{color:#666}}</style></head><body>
<h2>Lab identity provider</h2><p>Signing in to <b>{client}</b>. No password: this provider believes what you type.</p>
<form method="post" action="/authorize">{hidden}
<label>User name (the <code>preferred_username</code> claim)<input name="user" value="alice" autofocus></label>
<label>Groups, comma separated (the <code>groups</code> claim)<input name="groups" value="staff"></label>
<button type="submit">Sign in</button></form>
<p><small>Try <code>testadmin</code> to link an existing SAJHA account, or groups <code>sajha-admins</code> for the admin role.</small></p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = 'LabIdP/1'

    def log_message(self, fmt, *a):
        print(f'{self.address_string()} {fmt % a}', flush=True)

    # helpers
    def _json(self, code: int, doc: dict, headers: dict | None = None):
        body = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, cookie: str | None = None):
        self.send_response(302)
        self.send_header('Location', location)
        if cookie is not None:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()

    def _html(self, text: str):
        body = text.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _session(self):
        c = SimpleCookie(self.headers.get('Cookie', ''))
        sid = c['lab_idp'].value if 'lab_idp' in c else ''
        return sid, SESSIONS.get(sid)

    def _form(self) -> dict:
        n = int(self.headers.get('Content-Length') or 0)
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

    def _issue_code(self, p: dict, user: str, groups: list) -> None:
        code = secrets.token_urlsafe(24)
        with LOCK:
            CODES[code] = {'client_id': p.get('client_id'), 'redirect_uri': p.get('redirect_uri'),
                           'nonce': p.get('nonce'), 'challenge': p.get('code_challenge'),
                           'user': user, 'groups': groups, 'at': time.time()}
        q = {'code': code}
        if p.get('state'):
            q['state'] = p['state']
        sep = '&' if '?' in p['redirect_uri'] else '?'
        self._redirect(p['redirect_uri'] + sep + urlencode(q))

    # routes
    def do_GET(self):
        u = urlsplit(self.path)
        p = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == '/.well-known/openid-configuration':
            i = issuer()
            return self._json(200, {
                'issuer': i, 'authorization_endpoint': i + '/authorize', 'token_endpoint': i + '/token',
                'jwks_uri': i + '/jwks', 'end_session_endpoint': i + '/logout',
                'response_types_supported': ['code'], 'subject_types_supported': ['public'],
                'id_token_signing_alg_values_supported': ['RS256'], 'code_challenge_methods_supported': ['S256'],
                'token_endpoint_auth_methods_supported': ['client_secret_basic', 'client_secret_post', 'none'],
                'scopes_supported': ['openid', 'profile', 'email']})
        if u.path == '/jwks':
            return self._json(200, {'keys': [jwk()]})
        if u.path == '/authorize':
            if p.get('client_id') != ARGS.client_id or not p.get('redirect_uri') or p.get('response_type') != 'code':
                return self._json(400, {'error': 'invalid_request', 'error_description': 'unknown client or bad request'})
            _, sess = self._session()
            if sess:                                    # already signed in here: no form (single sign-on)
                return self._issue_code(p, sess['user'], sess['groups'])
            hidden = ''.join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                             for k, v in p.items())
            return self._html(FORM.format(client=html.escape(p.get('client_id', '')), hidden=hidden))
        if u.path == '/logout':
            sid, _ = self._session()
            SESSIONS.pop(sid, None)
            back = p.get('post_logout_redirect_uri') or '/'
            return self._redirect(back, 'lab_idp=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax')
        if u.path == '/':
            return self._html('<p>Lab identity provider. Signed-in people: '
                              + html.escape(', '.join(s['user'] for s in SESSIONS.values()) or 'none') + '</p>')
        self._json(404, {'error': 'not_found'})

    def do_POST(self):
        u = urlsplit(self.path)
        f = self._form()
        if u.path == '/authorize':
            user = (f.get('user') or '').strip()
            groups = [g.strip() for g in (f.get('groups') or '').split(',') if g.strip()]
            if not user or f.get('client_id') != ARGS.client_id:
                return self._json(400, {'error': 'invalid_request'})
            sid = secrets.token_urlsafe(24)
            SESSIONS[sid] = {'user': user, 'groups': groups}
            self.send_response(302)
            self.send_header('Set-Cookie', f'lab_idp={sid}; Path=/; HttpOnly; SameSite=Lax')
            code = secrets.token_urlsafe(24)
            with LOCK:
                CODES[code] = {'client_id': f.get('client_id'), 'redirect_uri': f.get('redirect_uri'),
                               'nonce': f.get('nonce'), 'challenge': f.get('code_challenge'),
                               'user': user, 'groups': groups, 'at': time.time()}
            q = {'code': code, **({'state': f['state']} if f.get('state') else {})}
            self.send_header('Location', f['redirect_uri'] + ('&' if '?' in f['redirect_uri'] else '?') + urlencode(q))
            self.end_headers()
            return
        if u.path == '/token':
            auth = self.headers.get('Authorization', '')
            client = f.get('client_id')
            if auth.startswith('Basic '):
                client = base64.b64decode(auth[6:]).decode().split(':', 1)[0]
            with LOCK:
                rec = CODES.pop(f.get('code', ''), None)
            if not rec or time.time() - rec['at'] > 120:
                return self._json(400, {'error': 'invalid_grant', 'error_description': 'unknown or expired code'})
            if client != rec['client_id'] or f.get('redirect_uri') != rec['redirect_uri']:
                return self._json(400, {'error': 'invalid_grant', 'error_description': 'client or redirect_uri differs'})
            verifier = f.get('code_verifier') or ''
            if rec['challenge'] and b64url(hashlib.sha256(verifier.encode()).digest()) != rec['challenge']:
                return self._json(400, {'error': 'invalid_grant', 'error_description': 'PKCE verifier does not match'})
            now = int(time.time())
            access = secrets.token_urlsafe(32)
            claims = {'iss': issuer(), 'aud': rec['client_id'], 'sub': 'lab-' + rec['user'], 'iat': now,
                      'exp': now + 600, 'nonce': rec['nonce'], 'preferred_username': rec['user'],
                      'name': rec['user'].title(), 'email': f'{rec["user"]}@lab.example', 'email_verified': True,
                      'groups': rec['groups'],
                      'at_hash': b64url(hashlib.sha256(access.encode()).digest()[:16])}
            token = jwt.encode(claims, KEY, algorithm='RS256', headers={'kid': KID})
            return self._json(200, {'access_token': access, 'token_type': 'Bearer', 'expires_in': 600,
                                    'id_token': token, 'scope': 'openid profile email'})
        self._json(404, {'error': 'not_found'})


def main() -> None:
    ap = argparse.ArgumentParser(description='A fake OpenID Connect provider for the SAJHA local test lab')
    ap.add_argument('--port', type=int, default=3010)
    ap.add_argument('--client-id', default='sajha-lab')
    global ARGS
    ARGS = ap.parse_args()
    srv = ThreadingHTTPServer(('127.0.0.1', ARGS.port), Handler)
    print(f'Lab identity provider on {issuer()} (client_id {ARGS.client_id}); Ctrl+C stops it', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
