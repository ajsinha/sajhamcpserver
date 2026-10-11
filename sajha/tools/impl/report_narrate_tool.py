"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``report_narrate`` (tool folder ``reports``; docs/architecture/Reports.md §5): commentary over a
stored report run, written by a model and checked against the run's data before it is returned.
The work is in sajha/reports/narrate.py.
"""

from __future__ import annotations

from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool


class ReportNarrateTool(BaseMCPTool):

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        from sajha.reports.narrate import narrate
        return narrate(str(arguments.get('run_id') or ''), sections=arguments.get('sections') or None,
                       length=arguments.get('length') or None, audience=arguments.get('audience') or '')
