"""
SAJHA MCP Server — Data Connectors: ConnectorTool, the one implementation of every generated tool.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A generated tool's config (written by sajha/connectors/service.py) carries only
``"connector": {"connection": <id>, "op": <operation>, "view"?: <name>}``; the connection's
settings (limits, allowlist, masking, credentials) are read from its record when the tool
runs, so an edit reaches every worker without regenerating tools. ``BaseMCPTool`` has
already applied policy, the connected-account binding, argument validation and the cache.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sajha.tools.base_mcp_tool import BaseMCPTool


class ConnectorTool(BaseMCPTool):
    """A governed, read-only tool over one data connection."""
    namespaced_name = True          # <connector prefix>__<operation> (sajha/tools/naming.py)

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config or {})
        self._spec = dict(self.config.get('connector') or {})

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema') or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema') or {}

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.connectors import engine, settings, store, vector
        from sajha.connectors.drivers import ConnectorError
        args = dict(arguments or {})
        if not settings.enabled():
            raise ConnectorError('data connectors are turned off on this server (connectors.enabled)')
        cid = str(self._spec.get('connection') or '')
        conn, err = store.get(cid)
        if conn is None:
            raise ConnectorError(err or f'connection {cid} is not available')
        if not conn.enabled:
            raise ConnectorError(f'connection {cid} is disabled')
        op = self._spec.get('op')
        if op == 'list_tables':
            return engine.list_tables(conn, args.get('schema'), args.get('pattern'), bool(args.get('refresh')),
                                      tool=self.name)
        if op == 'describe_table':
            return engine.describe_table(conn, args.get('table'), args.get('samples'), bool(args.get('refresh')),
                                         tool=self.name)
        if op == 'query':
            return engine.query(conn, args.get('sql'), args.get('params'), args.get('max_rows'), tool=self.name)
        if op == 'view':
            return engine.run_view(conn, str(self._spec.get('view') or ''), args, tool=self.name)
        if op == 'search':
            return vector.search(conn, args, tool=self.name)
        if op == 'list_collections':
            return vector.list_collections(conn, bool(args.get('refresh')), tool=self.name)
        if op == 'describe_collection':
            return vector.describe_collection(conn, args.get('collection'), tool=self.name)
        raise ConnectorError(f'unknown connector operation {op!r}')
