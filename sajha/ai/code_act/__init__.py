"""
SAJHA MCP Server — code_act: model-written Python run in the Sandbox (Quantitative Planners §3.5).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

    sandboxed.py  run_code(code, input_json) -> CodeRun; parse_output(stdout); build_input(...)
    stage.py      the ``code_act`` stage type (registered with the planner engine on first use)

The planner file is ``config/planners/code_act.yaml``. Only roles in ``ai.quant.code_act.roles``
(default none) may run it.
"""

from sajha.ai.code_act.sandboxed import CodeOutputError, CodeRun, build_input, parse_output, run_code

__all__ = ["CodeOutputError", "CodeRun", "build_input", "parse_output", "run_code"]
