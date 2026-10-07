"""
SAJHA MCP Server — a workflow published as an MCP tool.

``publish: {enabled: true}`` registers a tool (named ``publish.tool_name``, default the
workflow's name) whose call starts a run, waits for it (``publish.timeout_seconds``) and
returns the run's output. It is an ordinary registry tool: it appears in ``tools/list`` in
both protocol eras, follows tool RBAC and policies for who may call it, and federates like
any other tool. The steps still run as the workflow's owner (the run-as identity), which
is why only administrators may publish a workflow.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool


class WorkflowTool(BaseMCPTool):
    def __init__(self, service, wf: Dict[str, Any]):
        defn = wf['definition']
        pub = defn.get('publish') or {}
        self.workflow_name = defn['name']
        self._service = service
        self._timeout = float(pub.get('timeout_seconds', 300))
        schema = defn.get('input_schema') or {'type': 'object', 'properties': {}}
        super().__init__({
            'name': pub.get('tool_name') or defn['name'],
            'description': pub.get('description') or defn.get('description') or f'Run the workflow {defn["name"]}',
            'inputSchema': schema,
            'metadata': {'category': 'Workflow', 'tags': ['workflow'], 'workflow': defn['name']},
            'annotations': {'title': f'Workflow {defn["name"]}', 'readOnlyHint': False, 'openWorldHint': True},
        })

    def get_input_schema(self) -> Dict:
        return self._input_schema

    def get_output_schema(self) -> Dict:
        return {}

    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.observability.caller import current
        from sajha.workflows.engine import CHAIN
        if self.workflow_name in CHAIN.get():
            raise RuntimeError(f'workflow {self.workflow_name} cannot call itself (through its published tool)')
        run = self._service.start_run(self.workflow_name, dict(arguments or {}), trigger_type='tool',
                                      trigger_id=self.name, started_by=current().user_id,
                                      trigger_detail={'chain': list(CHAIN.get())})
        run = self._service.wait_for(run['id'], self._timeout)
        status = run['status']
        result = {'run_id': run['id'], 'status': status, 'output': run.get('output')}
        if status == 'succeeded':
            return result
        if status in ('queued', 'running', 'waiting'):
            result['note'] = (f'still {status} after {self._timeout:g}s; follow it with '
                              f'GET /api/workflows/runs/{run["id"]}')
            return result
        raise RuntimeError(f'workflow {self.workflow_name} {status}: {run.get("error") or ""} (run {run["id"]})')
