"""
Example upstream MCP server for federation: unit conversions, on the official MCP Python SDK.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Tutorial 11 (docs/tutorials/TUTORIAL_11_federate_an_mcp_server.md) runs this server and
federates it into SAJHA; tests/test_federation.py builds its upstream from ``build_server``.
It speaks Streamable HTTP on both protocol eras (2026-07-28 and 2025-11-25), or stdio::

    python sajha/examples/federation/units_server.py --port 8765        # http://127.0.0.1:8765/mcp
    python sajha/examples/federation/units_server.py --stdio

Tools: ``celsius_to_fahrenheit``, ``kilometres_to_miles`` (read-only), ``countdown``
(reports progress) and ``reset_counter`` (asks the user to confirm: an MRTR
InputRequiredResult on 2026-07-28, elicitation on 2025-11-25). One prompt
(``explain_conversion``) and one resource (``units://table``).
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.server.mcpserver import Context, MCPServer
from mcp_types import (ElicitRequest, ElicitRequestFormParams, InputRequiredResult, TextContent,
                       ToolAnnotations)

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

TABLE = """unit,to,factor
km,mile,0.621371
mile,km,1.609344
kg,lb,2.204623
celsius,fahrenheit,x*9/5+32
"""


def build_server(name: str = 'units') -> MCPServer:
    server = MCPServer(name, title='Units', version='1.0.0',
                       instructions='Unit conversions: temperature and distance.')
    counters = {'visits': 0}

    @server.tool(description='Convert a temperature in degrees Celsius to degrees Fahrenheit.',
                 annotations=READ_ONLY)
    def celsius_to_fahrenheit(celsius: float) -> float:
        return round(celsius * 9 / 5 + 32, 4)

    @server.tool(description='Convert a distance in kilometres to miles.', annotations=READ_ONLY)
    def kilometres_to_miles(km: float) -> float:
        return round(km * 0.621371, 4)

    @server.tool(description='Count down from a number of steps, reporting progress at each step.')
    async def countdown(steps: int, ctx: Context) -> str:
        steps = max(1, min(int(steps), 20))
        for i in range(steps):
            await ctx.report_progress(i + 1, steps, f'{steps - i - 1} to go')
            await asyncio.sleep(0.05)
        return 'lift-off'

    @server.tool(description='Reset a named counter to zero, after the user confirms.')
    async def reset_counter(counter: str, ctx: Context) -> str | InputRequiredResult:
        if ctx.protocol_version and ctx.protocol_version >= '2026-07-28':
            answer = (ctx.input_responses or {}).get('confirm')
            if answer is None:
                return InputRequiredResult(input_requests={'confirm': ElicitRequest(params=ElicitRequestFormParams(
                    message=f'Reset counter {counter!r} to zero?',
                    requested_schema={'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                                      'required': ['ok']}))})
            content = getattr(answer, 'content', None) or {}
            accepted = getattr(answer, 'action', '') == 'accept' and content.get('ok') is True
        else:
            from pydantic import BaseModel

            class Confirm(BaseModel):
                ok: bool

            result = await ctx.elicit(f'Reset counter {counter!r} to zero?', Confirm)
            accepted = result.action == 'accept' and bool(result.data and result.data.ok)
        if not accepted:
            return f'counter {counter} left as it was'
        counters[counter] = 0
        return f'counter {counter} reset'

    @server.prompt(description='Ask for an explanation of one unit conversion.')
    def explain_conversion(unit_from: str, unit_to: str) -> str:
        return f'Explain how to convert {unit_from} to {unit_to}, with one worked example.'

    @server.resource('units://table', name='conversion table', description='Conversion factors, as CSV.',
                     mime_type='text/csv')
    def table() -> str:
        return TABLE

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description='Example upstream MCP server (unit conversions)')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--stdio', action='store_true', help='serve on stdin/stdout instead of HTTP')
    args = parser.parse_args()
    server = build_server()
    if args.stdio:
        server.run('stdio')
        return
    import uvicorn
    uvicorn.run(server.streamable_http_app(host=args.host), host=args.host, port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
