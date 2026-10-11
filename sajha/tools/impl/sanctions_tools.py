"""
SAJHA MCP Server — the sanctions_* tools: screening against the official lists in the local index.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The four read tools never leave the machine (openWorldHint false). ``sanctions_refresh`` downloads
the lists (administrators only; run by the shipped ``sanctions_refresh`` workflow). A shipped policy
rule (config/policies/10-sanctions.yaml) keeps every ``sanctions_*`` tool from Ask SAJHA and the
LLM tools. Guide: docs/tools/public-data/Sanctions Tool Reference Guide.md.
"""

from __future__ import annotations

from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool


class _SanctionsTool(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return self._input_schema or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self._output_schema or {'type': 'object'}


class SanctionsScreenTool(_SanctionsTool):
    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.sanctions import service
        a = arguments or {}
        return service.screen(a.get('name', ''), type=a.get('type'), date_of_birth=a.get('date_of_birth'),
                              country=a.get('country'), lists=a.get('lists'), threshold=a.get('threshold', 85))


class SanctionsEntryTool(_SanctionsTool):
    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.sanctions import service
        a = arguments or {}
        return service.entry(a.get('list', ''), a.get('entry_id', ''))


class SanctionsChangesTool(_SanctionsTool):
    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.sanctions import service
        a = arguments or {}
        return service.changes(a.get('since', ''), a.get('list'))


class SanctionsListsStatusTool(_SanctionsTool):
    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.sanctions import service
        return service.lists_status()


class SanctionsRefreshTool(_SanctionsTool):
    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.observability.caller import current
        if not current().is_admin:
            raise PermissionError('sanctions_refresh is for administrators (it downloads the official lists)')
        from sajha.sanctions import refresh
        a = arguments or {}
        try:
            out = refresh.refresh(a.get('lists'), force=bool(a.get('force', False)))
        except refresh.RefreshBusy as e:
            raise ValueError(str(e))
        if not out['ok']:          # a failed step, so the workflow run shows it; the other lists were refreshed
            raise ValueError('sanctions refresh failed for ' + '; '.join(
                f"{r['list']}: {r.get('error')}" for r in out['lists'] if r['status'] == 'error') +
                ' (' + ', '.join(f"{r['list']} {r['status']}" for r in out['lists']) + ')')
        return out
