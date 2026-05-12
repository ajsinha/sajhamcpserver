"""
SAJHA MCP Server — Composite Tool Engine
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A composite tool orchestrates multiple MCP tools in one call.
Definitions are purely declarative (stored in DB), and input/output
schemas are built dynamically at boot/reload time.

Two arrangement patterns:

  SIBLING (parallel): All steps run concurrently with shared/mapped inputs.
    market_snapshot = yahoo_quote ∥ fred_vix ∥ fred_fed_rate
    Output: {stock_quote: {...}, vix: {...}, fed_rate: {...}}

  PARENT_CHILD (fan-out): Master runs first, then child runs once per record.
    portfolio_dive = duckdb_query → for each row: fmp_profile(row.ticker)
    Output: {positions: [...], profiles: [{record: {...}, profile: {...}}]}
"""

import json
import copy
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)


def _resolve_path(data: Any, path: str) -> Any:
    """Resolve a dot-path like 'rows' or 'result.data' into nested data."""
    if not path:
        return data
    for key in path.split('.'):
        if isinstance(data, dict):
            data = data.get(key, data)
        elif isinstance(data, list) and key.isdigit():
            data = data[int(key)]
        else:
            return data
    return data


def _map_params(record: Dict, mapping: Dict, static: Dict, master_input: Dict) -> Dict:
    """Build child tool params from a parent record + mapping + static values.

    Mapping syntax:
      {"symbol": "$.ticker"}        → record['ticker']
      {"symbol": "$input.symbol"}   → master_input['symbol']
      {"limit": 5}                  → static value
    """
    params = dict(static) if static else {}
    for target_key, source_expr in (mapping or {}).items():
        if isinstance(source_expr, str) and source_expr.startswith('$.'):
            field = source_expr[2:]
            if field.startswith('input.'):
                params[target_key] = master_input.get(field[6:], '')
            else:
                params[target_key] = record.get(field, '') if record else ''
        else:
            params[target_key] = source_expr
    return params


class CompositeTool(BaseMCPTool):
    """
    A dynamically-constructed tool that orchestrates multiple MCP tools.
    Created by CompositeToolEngine from a DB definition.
    Registered in ToolsRegistry just like any other tool.
    """

    def __init__(self, definition: Dict, tools_registry):
        self._definition = definition
        self._registry = tools_registry
        self._input_schema = None
        self._output_schema = None
        config = {
            'name': definition['name'],
            'description': definition.get('description', ''),
            'metadata': {
                'category': 'Composite',
                'tags': ['composite', definition.get('arrangement', 'sibling')],
            },
        }
        super().__init__(config)
        self._build_schemas()

    def _build_schemas(self):
        """Dynamically build input and output schemas from component tools."""
        d = self._definition
        master_name = d['master_tool']
        master_tool = self._registry.get_tool(master_name)

        # ── Input schema: start with master's schema ─────────
        if master_tool and hasattr(master_tool, 'get_input_schema'):
            self._input_schema = copy.deepcopy(master_tool.get_input_schema())
        else:
            self._input_schema = {'type': 'object', 'properties': {}, 'required': []}

        # Add optional params from sibling steps that need extra inputs
        for step in d.get('steps', []):
            mapping = step.get('param_mapping') or {}
            for target, source in mapping.items():
                if isinstance(source, str) and source.startswith('$input.'):
                    field = source[7:]
                    if field not in self._input_schema.get('properties', {}):
                        self._input_schema.setdefault('properties', {})[field] = {
                            'type': 'string',
                            'description': f'Parameter for {step["tool_name"]}',
                        }

        # ── Output schema: built from arrangement ────────────
        output_props = {}
        master_key = d.get('master_output_key', 'master')

        if master_tool and hasattr(master_tool, 'get_output_schema'):
            output_props[master_key] = copy.deepcopy(master_tool.get_output_schema())
        else:
            output_props[master_key] = {'type': 'object'}

        if d.get('arrangement') == 'parent_child':
            children_items = {}
            for step in d.get('steps', []):
                child_tool = self._registry.get_tool(step['tool_name'])
                child_schema = {'type': 'object'}
                if child_tool and hasattr(child_tool, 'get_output_schema'):
                    child_schema = copy.deepcopy(child_tool.get_output_schema())
                children_items[step['output_key']] = child_schema

            output_props['children'] = {
                'type': 'array',
                'description': 'One entry per record from master tool',
                'items': {
                    'type': 'object',
                    'properties': {
                        '_record': {'type': 'object', 'description': 'Parent record'},
                        **children_items,
                    },
                },
            }
        else:  # sibling
            for step in d.get('steps', []):
                sibling_tool = self._registry.get_tool(step['tool_name'])
                if sibling_tool and hasattr(sibling_tool, 'get_output_schema'):
                    output_props[step['output_key']] = copy.deepcopy(sibling_tool.get_output_schema())
                else:
                    output_props[step['output_key']] = {'type': 'object'}

        self._output_schema = {
            'type': 'object',
            'properties': output_props,
        }

    def get_input_schema(self) -> Dict:
        return self._input_schema

    def get_output_schema(self) -> Dict:
        return self._output_schema

    def execute(self, arguments: Dict) -> Dict:
        """
        Execute the composite tool with Kleisli composition semantics.
        Returns result dict with _composition metadata (confidence, entropy, trace).
        """
        from sajha.core.composition import (
            StepResult, PipelineResult, ParamLens, EntropyGuard,
            execute_step, get_tool_confidence,
        )

        d = self._definition
        arrangement = d.get('arrangement', 'sibling')
        max_entropy = d.get('entropy_threshold', 3.0)
        guard = EntropyGuard(max_entropy_bits=max_entropy)

        # ── Execute master tool (wrapped in StepResult) ──
        master_name = d['master_tool']
        master_tool = self._registry.get_tool(master_name)
        if not master_tool:
            return PipelineResult(error=f'Master tool not found: {master_name}').to_dict()

        master_result = execute_step(master_tool, arguments, master_name)
        guard.record_step(master_name, master_result.confidence)

        if not master_result.is_success:
            return PipelineResult(
                error=master_result.error,
                trace=master_result.trace,
                duration_ms=master_result.duration_ms,
                confidence=0.0,
                step_results=[master_result],
            ).to_dict()

        master_key = d.get('master_output_key', 'master')
        output = {master_key: master_result.value}
        all_step_results = [master_result]
        all_traces = list(master_result.trace)
        total_duration = master_result.duration_ms

        steps = d.get('steps', [])
        if not steps:
            pr = PipelineResult(
                value=output, trace=all_traces, duration_ms=total_duration,
                confidence=guard.cumulative_confidence,
                entropy_bits=guard.cumulative_entropy,
                step_results=all_step_results, guard_passed=True,
            )
            return pr.to_dict()

        # ── Execute steps based on arrangement ──
        if arrangement == 'parent_child':
            child_output = self._execute_parent_child_composed(
                arguments, master_result.value, steps, d, guard)
            output.update(child_output)
        else:
            # Sibling = parallel: use weakest-link confidence model
            guard.begin_parallel()
            sibling_output, sibling_results = self._execute_sibling_composed(
                arguments, steps, guard)
            guard.end_parallel()
            output.update(sibling_output)
            all_step_results.extend(sibling_results)
            for sr in sibling_results:
                all_traces.extend(sr.trace)
                total_duration += sr.duration_ms

        # ── Entropy guard check ──
        guard_status = guard.check_safe(d['name'])

        pr = PipelineResult(
            value=output,
            trace=all_traces,
            duration_ms=total_duration,
            confidence=guard.cumulative_confidence,
            entropy_bits=guard.cumulative_entropy,
            step_results=all_step_results,
            guard_passed=guard_status['passed'],
            guard_message=guard_status.get('message', ''),
        )
        return pr.to_dict()

    def _execute_sibling_composed(self, master_input: Dict, steps: List[Dict],
                                    guard) -> tuple:
        """Run sibling steps in parallel with composition tracking."""
        from sajha.core.composition import execute_step, ParamLens

        result = {}
        step_results = []

        def _run_step(step):
            tool = self._registry.get_tool(step['tool_name'])
            if not tool:
                from sajha.core.composition import StepResult
                return step['output_key'], StepResult.fail(
                    f'Tool not found: {step["tool_name"]}', step['tool_name'])
            lens = ParamLens.from_step_definition(step)
            params = lens.view(master_input, master_input=master_input)
            merged = {**master_input, **params}
            return step['output_key'], execute_step(tool, merged, step['tool_name'])

        with ThreadPoolExecutor(max_workers=min(len(steps), 8)) as pool:
            futures = {pool.submit(_run_step, s): s for s in steps}
            for future in as_completed(futures):
                key, sr = future.result()
                result[key] = sr.value if sr.is_success else {'error': sr.error}
                step_results.append(sr)
                guard.record_step(sr.step_name, sr.confidence)

        return result, step_results

    def _execute_parent_child_composed(self, master_input: Dict, master_result: Dict,
                                        steps: List[Dict], definition: Dict, guard) -> Dict:
        """Fan-out with composition tracking."""
        from sajha.core.composition import execute_step, ParamLens

        record_path = definition.get('record_path', '')
        records = _resolve_path(master_result, record_path)
        if not isinstance(records, list):
            records = [records] if records else []

        children = []

        def _run_child(record, step):
            tool = self._registry.get_tool(step['tool_name'])
            if not tool:
                from sajha.core.composition import StepResult
                return step['output_key'], StepResult.fail(
                    f'Tool not found: {step["tool_name"]}', step['tool_name'])
            lens = ParamLens.from_step_definition(step)
            params = lens.view({}, master_input=master_input, record=record)
            return step['output_key'], execute_step(tool, params, step['tool_name'])

        with ThreadPoolExecutor(max_workers=min(len(records) * len(steps), 16)) as pool:
            for record in records:
                entry = {'_record': record}
                guard.begin_parallel()
                futures = {pool.submit(_run_child, record, s): s for s in steps}
                for future in as_completed(futures):
                    key, sr = future.result()
                    entry[key] = sr.value if sr.is_success else {'error': sr.error}
                    guard.record_step(sr.step_name, sr.confidence)
                guard.end_parallel()
                children.append(entry)

        return {'children': children}


class CompositeToolEngine:
    """
    Reads composite tool definitions from DB, builds CompositeTool instances,
    and registers them in the ToolsRegistry.

    Called at boot and on hot-reload.
    """

    def __init__(self, tools_registry):
        self._registry = tools_registry
        self._composite_tools: Dict[str, CompositeTool] = {}

    def load_from_db(self, db_session) -> int:
        """Load all enabled composite tools from DB, build and register them."""
        from sajha.db.models import CompositeToolRecord, CompositeToolStepRecord

        records = db_session.query(CompositeToolRecord).filter(
            CompositeToolRecord.enabled == True
        ).all()

        count = 0
        for rec in records:
            steps = db_session.query(CompositeToolStepRecord).filter(
                CompositeToolStepRecord.composite_tool_id == rec.id
            ).order_by(CompositeToolStepRecord.step_order).all()

            definition = {
                'name': rec.name,
                'description': rec.description or '',
                'arrangement': rec.arrangement,
                'master_tool': rec.master_tool,
                'master_output_key': rec.master_output_key or 'master',
                'record_path': rec.record_path or '',
                'steps': [],
            }

            for step in steps:
                step_def = {
                    'tool_name': step.tool_name,
                    'output_key': step.output_key,
                    'execution_mode': step.execution_mode,
                    'param_mapping': json.loads(step.param_mapping) if step.param_mapping else {},
                    'static_params': json.loads(step.static_params) if step.static_params else {},
                }
                if step.condition:
                    step_def['condition'] = step.condition
                definition['steps'].append(step_def)

            try:
                tool = CompositeTool(definition, self._registry)
                self._registry.register_tool(rec.name, tool)
                self._composite_tools[rec.name] = tool
                count += 1
                logger.info(f"Composite tool registered: {rec.name} ({rec.arrangement}, {len(definition['steps'])} steps)")
            except Exception as e:
                logger.warning(f"Failed to build composite tool {rec.name}: {e}", exc_info=True)

        return count

    def get_definition(self, name: str) -> Optional[Dict]:
        tool = self._composite_tools.get(name)
        return tool._definition if tool else None

    def reload(self, db_session) -> int:
        """Unregister existing composites and reload from DB."""
        for name in list(self._composite_tools.keys()):
            self._registry.unregister_tool(name)
        self._composite_tools.clear()
        return self.load_from_db(db_session)
