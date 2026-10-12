"""
SAJHA MCP Server — CORS for the OAuth endpoints, for browser-based MCP clients.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A browser-based MCP client on another origin must read the discovery documents
and call the token (and registration) endpoint with ``fetch``.  For an Origin
listed in ``mcp.auth.cors.allowed_origins`` (default: none; ``*`` = any), this
pure-ASGI middleware answers pre-flights itself and adds
``Access-Control-Allow-Origin`` to the responses of:

    GET  /.well-known/oauth-protected-resource[/mcp|/api/mcp]
    GET  /.well-known/oauth-authorization-server
    GET  /oauth/jwks
    POST /oauth/token
    POST /oauth/register

Never ``Access-Control-Allow-Credentials``: none of these endpoints uses the
console cookie (clients authenticate with an explicit Authorization header or
form fields), so a cross-origin page can never act with a signed-in user's
session.  ``/oauth/authorize`` is a top-level browser navigation (the consent
page), not a ``fetch``: it gets no CORS headers.  Origins not on the list are
passed through untouched to the application-wide CORS middleware.
"""

from __future__ import annotations

from typing import List, Optional

PATHS = ('/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp',
         '/.well-known/oauth-protected-resource/api/mcp', '/.well-known/oauth-authorization-server',
         '/oauth/jwks', '/oauth/token', '/oauth/register')
METHODS = 'GET, POST, OPTIONS'
ALLOW_HEADERS = 'Authorization, Content-Type, Accept, MCP-Protocol-Version'
MAX_AGE = '600'

_CORS_HEADERS = (b'access-control-allow-origin', b'access-control-allow-credentials',
                 b'access-control-allow-methods', b'access-control-allow-headers',
                 b'access-control-max-age', b'access-control-expose-headers')


def allowed_origins() -> List[str]:
    from sajha.core.config import _list
    return [o.strip().rstrip('/') for o in _list('mcp.auth.cors.allowed_origins', []) if o.strip()]


def allow_origin_for(origin: Optional[str], allowed: Optional[List[str]] = None) -> Optional[str]:
    """The Access-Control-Allow-Origin value for ``origin``, or None when it is not allowed."""
    if not origin or origin == 'null':
        return None
    allowed = allowed_origins() if allowed is None else allowed
    if '*' in allowed:
        return '*'
    return origin if origin.rstrip('/') in allowed else None


class OAuthCorsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or scope.get('path', '').rstrip('/') not in PATHS:
            return await self.app(scope, receive, send)
        origin = None
        preflight = False
        for k, v in scope.get('headers') or []:
            if k == b'origin':
                origin = v.decode('latin-1')
            elif k == b'access-control-request-method':
                preflight = True
        allow = allow_origin_for(origin)
        if allow is None:
            return await self.app(scope, receive, send)

        if scope.get('method') == 'OPTIONS' and preflight:
            headers = [(b'access-control-allow-origin', allow.encode('latin-1')),
                       (b'access-control-allow-methods', METHODS.encode()),
                       (b'access-control-allow-headers', ALLOW_HEADERS.encode()),
                       (b'access-control-max-age', MAX_AGE.encode()),
                       (b'vary', b'Origin'), (b'content-length', b'0')]
            await send({'type': 'http.response.start', 'status': 204, 'headers': headers})
            return await send({'type': 'http.response.body', 'body': b''})

        async def send_with_cors(message):
            if message['type'] == 'http.response.start':
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() not in _CORS_HEADERS]
                headers.append((b'access-control-allow-origin', allow.encode('latin-1')))
                headers.append((b'access-control-expose-headers', b'WWW-Authenticate'))
                if not any(k.lower() == b'vary' for k, _ in headers):
                    headers.append((b'vary', b'Origin'))
                message = {**message, 'headers': headers}
            await send(message)

        # the inner (application-wide) CORS middleware must not answer for this origin too
        inner = dict(scope)
        inner['headers'] = [(k, v) for k, v in scope.get('headers', []) if k != b'origin']
        return await self.app(inner, receive, send_with_cors)
