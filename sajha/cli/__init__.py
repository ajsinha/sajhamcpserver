"""
SAJHA MCP Server — command-line entry points that run inside the server process.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* ``sajha.cli.stdio`` — the MCP stdio transport (``sajha serve --stdio``,
  ``python run_sajha_web.py --stdio``, ``python -m sajha.cli.stdio``).

The ``sajha`` command itself (login, tools, ask, prompts, studio, ...) is an HTTP
client and lives in the client SDK: ``sajhaclient.cli``.
"""
