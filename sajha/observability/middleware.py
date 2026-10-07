"""
SAJHA MCP Server — the HTTP observability middleware.

A plain ASGI middleware (not BaseHTTPMiddleware), so streamed and SSE responses pass
through untouched. It counts every HTTP request by route template, method and status,
observes the latency to the response headers (a long SSE stream does not skew the
histogram), and opens the server span, continuing a ``traceparent`` request header (or
starting a trace, so outbound calls and audit records carry a trace id even without the SDK).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import time

from sajha.observability import metrics, tracing


def route_of(scope) -> str:
    route = scope.get('route')
    path = getattr(route, 'path', None) or getattr(route, 'path_format', None)
    return path or '<unmatched>'


class ObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        method = scope.get('method', 'GET')
        state = {'status': 500, 'ttfb': None}

        async def send_wrapper(message):
            if message.get('type') == 'http.response.start':
                state['status'] = int(message.get('status', 500))
                state['ttfb'] = time.perf_counter() - start
            await send(message)

        if tracing.tracer() is not None:
            carrier = {k.decode('latin-1'): v.decode('latin-1') for k, v in scope.get('headers') or []}
        else:       # no SDK: only the W3C headers (tracing.span continues them, or starts a trace)
            carrier = {k.decode('latin-1'): v.decode('latin-1') for k, v in scope.get('headers') or []
                       if k in (b'traceparent', b'tracestate')}
        with tracing.span(f'HTTP {method}', {'http.request.method': method, 'url.path': scope.get('path')},
                          carrier=carrier, kind='server') as sp:
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                route = route_of(scope)
                elapsed = state['ttfb'] if state['ttfb'] is not None else time.perf_counter() - start
                if sp is not None:
                    try:
                        sp.update_name(f'{method} {route}')
                    except Exception:
                        pass
                    tracing.set_attrs(sp, **{'http.route': route, 'http.response.status_code': state['status']})
                    if state['status'] >= 500:
                        tracing.set_error(sp, f'HTTP {state["status"]}')
                metrics.record_http(method, route, state['status'], elapsed)
