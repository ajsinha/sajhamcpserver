"""
SAJHA MCP Server — planner dry run: run a planner against the mock model and report the path.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

LLM Tools §9.11. Every model call of the run goes to ``ai.planners.dry_run_model`` (the mock
model by default), whatever roles the file maps. Tools are offered as usual (the caller's access
applies), but only tools whose annotations say ``readOnlyHint: true``, and tools the admin names
in ``run_tools``, are actually run; every other call returns an error result "not run in a dry
run", so the path still shows where the planner would go. The answer is
``POST /api/ai/planners/dry-run``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

NOT_RUN = "not run in a dry run: the tool is not marked read-only (name it in run_tools to run it)"


def read_only(tool: Any) -> bool:
    cfg = getattr(tool, "config", None) or {}
    ann = cfg.get("annotations") or {}
    return bool(isinstance(ann, dict) and ann.get("readOnlyHint") is True)


class _Stub:
    """A tool the dry run offers but does not run."""

    def __init__(self, tool: Any):
        self._tool = tool
        self.name = tool.name
        self.description = getattr(tool, "description", "")
        self.config = getattr(tool, "config", {})
        self.enabled = getattr(tool, "enabled", True)

    @property
    def input_schema(self):
        return self._tool.input_schema

    def execute_with_tracking(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"error": NOT_RUN}


class _DryRegistry:
    def __init__(self, registry: Any, run: List[str]):
        self._registry = registry
        self._run = set(run)
        self.tools = {n: self._wrap(t) for n, t in (getattr(registry, "tools", {}) or {}).items()}

    def _wrap(self, tool: Any):
        return tool if (tool is None or read_only(tool) or tool.name in self._run) else _Stub(tool)

    def get_tool(self, name: str):
        return self.tools.get(name) or self._wrap(self._registry.get_tool(name))


def dry_run(service: Any, planner: Any, question: str, ctx: Any, *, tools: Optional[List[str]] = None,
            run_tools: Optional[List[str]] = None, input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run ``planner`` (a reference, an overlay or an inline definition) on ``question``."""
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.planners_engine.settings import planner_settings
    reg = _DryRegistry(service.tools_registry, list(run_tools or []))
    names = list(tools) if tools else sorted(n for n in reg.tools if n != "sajha_ask")
    allowed = [n for n in names if reg.get_tool(n) is not None and (ctx.can_use_tool is None or ctx.can_use_tool(n))]
    allowed = [t["name"] for t in service.shortlist(question, ctx, among=allowed)]   # rank with the real catalog
    model = planner_settings().dry_run_model
    svc = IntelligenceService(service.gateway, reg, settings=service.settings, audit=lambda e: None,
                              memory=getattr(service, "_memory", None))
    events: List[Dict[str, Any]] = []
    result = None
    info = {"by": "dry run", "force_model": model, "input": dict(input or {}), "tool": "",
            "inline_defaults": {"name": "dry_run__inline", "version": "0.0.0"}}
    for ev in svc.stream_ask(question, ctx, model=model, planner=planner, tools=allowed, audit=False,
                             planner_info=info, _objects=True):
        if ev["type"] == "done":
            result = ev["result"]
        elif ev["type"] in ("stage_start", "stage_end", "loop_exhausted", "expression_error", "planner_chosen",
                            "plan", "tool_call", "tool_result", "error"):
            events.append({k: v for k, v in ev.items() if k != "seq"})
    top = result.planner.split(">")[0]
    return {"planner": result.planner, "version": result.planner_version,
            "path": [e["stage"] for e in events if e["type"] == "stage_start" and e.get("planner") == top],
            "trace": list(result.planner_path), "stopped_by": result.stopped_by, "answer": result.answer,
            "loops_exhausted": list(result.loops_exhausted), "tools_offered": list(result.shortlist),
            "tool_calls": [{"name": s.name, "ok": s.ok, "run": s.summary.find("not run in a dry run") < 0}
                           for s in result.steps], "error": result.error, "events": events[:400]}
