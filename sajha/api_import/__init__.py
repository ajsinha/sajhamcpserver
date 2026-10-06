"""
SAJHA MCP Server — API Import: OpenAPI 3.x, Swagger 2.0 and GraphQL → reviewed tools.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  fetch.py     the SSRF-guarded HTTP client (spec URLs, remote $refs, every tool call)
  refs.py      $ref resolution (local, relative, remote; cycles cut)
  schema.py    OpenAPI schema objects → JSON Schema 2020-12
  swagger2.py  Swagger 2.0 → OpenAPI 3.0
  openapi.py   operations of an OpenAPI document
  graphql.py   operations of a GraphQL schema (introspection)
  naming.py    tool, prefix and argument names
  executor.py  ImportedAPITool, the one implementation every imported tool uses
  service.py   plan (preview + diff), test call, deploy, delete
  store.py     import records (config/api_imports/<api_id>.json, storage backend)

Design: docs/architecture/API Import.md.
"""
