"""
SAJHA MCP Server — LLM tools: tools whose work is done by a language model.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

An LLM tool is an ordinary config file in ``config/tools/`` whose ``implementation`` is
``sajha.ai.llm_tools.LLMTool`` and which carries an ``llm`` block (mode, model, prompt or template,
allowed tools, limits, memory). Design and as-built: docs/architecture/LLM Tools.md; a walk-through:
docs/tutorials/TUTORIAL_26_build_an_llm_tool.md.

    config.py    ai.llm_tools.* settings (ceilings), the llm block and its load-time validation,
                 derived annotations, lint findings
    tool.py      LLMTool and its modes: answer, complete, extract, classify, grounded, narrate, judge
    runtime.py   resource safety: admission and queue, working set and spool, memory guard, caches

API for code that runs an LLM tool directly (evals, tests)::

    from sajha.ai.llm_tools import LLMTool
    tool = LLMTool(config)                      # LLMConfigError when the llm block is refused
    info = tool.run({"question": "..."}, ctx=request_context, model="mock/mock-planner")
    info.result, info.stopped_by, info.usage, info.duration_ms
"""

from sajha.ai.llm_tools.config import (IMPLEMENTATION, MODES, LLMConfigError, LLMSpec, LLMToolSettings, is_llm_tool,
                                       load_settings, parse_llm_block, set_settings, settings)
from sajha.ai.llm_tools.tool import ERROR_STOPS, STOP_REASONS, LLMTool, LLMToolResult, RunInfo, build

__all__ = ["IMPLEMENTATION", "MODES", "LLMConfigError", "LLMSpec", "LLMToolSettings", "LLMTool", "LLMToolResult",
           "RunInfo", "ERROR_STOPS", "STOP_REASONS", "build", "is_llm_tool", "load_settings", "parse_llm_block",
           "set_settings", "settings"]
