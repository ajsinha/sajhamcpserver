"""
SAJHA MCP Server — FederatedTool: an upstream server's tool as a SAJHA registry tool.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A ``FederatedTool`` is registered in the ToolsRegistry under its namespaced name
(``<prefix>__<tool>``). Everything that runs tools (MCP on both eras, REST, A2A, Ask SAJHA,
composites) calls ``execute_with_tracking`` as for any tool, so access control, the cache,
the circuit breaker, metrics and the replay store apply unchanged; ``execute`` routes the
call to the upstream through the FederationManager.

``passthrough_result`` tells MCPHandler to return the upstream's CallToolResult as is
(content blocks and structuredContent) instead of re-wrapping it.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool

META_KEY = 'sajha/federation'


class FederatedToolError(RuntimeError):
    """The upstream tool answered with isError: true."""

    def __init__(self, message: str, result: Dict[str, Any]):
        super().__init__(message)
        self.result = result


class FederatedTool(BaseMCPTool):
    passthrough_result = True

    namespaced_name = True          # <prefix>__<tool>: '__' is reserved for namespaced tools (sajha/tools/naming.py)

    def __init__(self, manager, upstream_id: str, upstream_name: str, definition: Dict[str, Any],
                 config_extra: Dict[str, Any] = None):
        cfg = {
            'name': definition['name'],
            'description': definition.get('description') or '',
            'inputSchema': definition.get('inputSchema') or {'type': 'object', 'properties': {}},
            'outputSchema': definition.get('outputSchema') or {},
            'metadata': {'category': 'federated', 'upstream': upstream_id, 'tags': ['federated', upstream_id]},
            'version': definition.get('version') or '1.0.0',
            'enabled': True,
        }
        for key in ('title', 'annotations', 'icons'):
            if definition.get(key):
                cfg[key] = definition[key]
        cfg.update(config_extra or {})
        super().__init__(cfg)
        self.manager = manager
        self.upstream_id = upstream_id
        self.upstream_name = upstream_name
        self.definition = definition

    # ── BaseMCPTool contract ───────────────────────────────────────
    def get_input_schema(self) -> Dict:
        return self._input_schema or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self._output_schema or {}

    def get_description(self) -> str:
        return self.description

    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.core.mcp_tool_context import current_context
        return self.manager.call_tool(self, dict(arguments or {}), current_context())

    def to_mcp_format(self) -> Dict:
        d = self.definition
        tool = {'name': self.name, 'description': self.description, 'inputSchema': self.input_schema}
        for key in ('title', 'outputSchema', 'annotations', 'icons'):
            value = d.get(key)
            if value:
                tool[key] = copy.deepcopy(value)
        if isinstance(tool.get('outputSchema'), dict) and tool['outputSchema'].get('type') != 'object':
            tool.pop('outputSchema')
        tool['_meta'] = {META_KEY: {'upstream': self.upstream_id, 'tool': self.upstream_name}}
        return tool

    def format_mcp_result(self, result: Any, advertise_output_schema: bool = True) -> Dict[str, Any]:
        """The CallToolResult to give an MCP caller: the upstream's own, unchanged."""
        if isinstance(result, dict) and isinstance(result.get('content'), list):
            out = {'content': result['content']}
            if advertise_output_schema and 'structuredContent' in result:
                out['structuredContent'] = result['structuredContent']
            return out
        return {'content': [{'type': 'text', 'text': str(result)}]}
