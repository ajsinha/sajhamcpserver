"""
ASGI guard for the SAJHA Net paths: net endpoints are not for browsers (protocol §7.3), so a
request under ``/sajhanet/`` reaches the CORS middleware without its ``Origin`` header and its
response never carries CORS headers (a pre-flight gets the participant's bare 404).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations


class NoCorsForNetPaths:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'http' and str(scope.get('path', '')).startswith('/sajhanet/'):
            scope = dict(scope)
            scope['headers'] = [(k, v) for k, v in scope.get('headers', []) if k.lower() != b'origin']
        await self.app(scope, receive, send)
