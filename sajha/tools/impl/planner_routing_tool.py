"""
SAJHA MCP Server — ``sajha_planner_routing_propose``: the planner learning job as a tool, so a
workflow can run it on a schedule (the shipped ``planner_routing_learn``). Administrators only.
It writes a proposal; nothing changes until an administrator approves it on the Planner routing
page. Design: docs/architecture/LLM Tools.md §9.13.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool


class PlannerRoutingProposeTool(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return self._input_schema or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self._output_schema or {'type': 'object'}

    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.observability.caller import current
        who = current()
        if not who.is_admin:
            raise PermissionError('sajha_planner_routing_propose is for administrators (it writes routing proposals)')
        from sajha.ai.planners_engine import learning
        dry = bool((arguments or {}).get('dry_run', False))
        doc = learning.learn(created_by=who.user_id or 'workflow', source='tool', write=not dry)
        return {'id': doc.get('id', ''), 'status': doc['status'], 'hash': doc['hash'],
                'changes': len(doc.get('diff') or []), 'evidence': doc['evidence'], 'rules': doc['rules']}
