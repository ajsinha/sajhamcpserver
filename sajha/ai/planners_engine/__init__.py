"""
SAJHA MCP Server — the configurable planner engine.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Planners as configuration: ``config/planners/<name>.yaml`` files describe a bounded graph of
stages from a fixed library; the service still enforces everything (planners only propose).

    model.py      the file format, validation (P001–P071) and the compiled form
    expr.py       the ``when`` expression language and templates
    stages.py     the stage library (and custom stage types registered in code)
    checks.py     the deterministic checks of the ``verify`` stage
    runtime.py    the graph runtime (``GraphPlanner``)
    registry.py   loading, reload with last-good fallback, versions and resolution
    dryrun.py     a run against the mock model that returns the stage path
    settings.py   ``ai.planners.*``

Design: docs/architecture/LLM Tools.md §9. File format: docs/architecture/Planner Reference.md.
"""

from sajha.ai.planners_engine.model import Diagnostic, PlannerDef, PlannerError, compile_planner, planner_schema
from sajha.ai.planners_engine.registry import (PlannerRegistry, UnknownPlanner, ask_overlays, get_registry,
                                               set_registry, validate_ask)
from sajha.ai.planners_engine.stages import StageType, register_stage_type, stage_types, unregister_stage_type
from sajha.ai.planners_engine.checks import register_check

__all__ = ["Diagnostic", "PlannerDef", "PlannerError", "PlannerRegistry", "StageType", "UnknownPlanner",
           "ask_overlays", "compile_planner", "get_registry", "planner_schema", "register_check",
           "register_stage_type", "set_registry", "stage_types", "unregister_stage_type", "validate_ask"]
