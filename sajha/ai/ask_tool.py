"""
SAJHA MCP Server — the ``sajha_ask`` MCP tool (off by default: ai.ask.mcp_tool_enabled).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Lets a thin MCP client delegate a whole question to SAJHA's intelligence layer. The ask runs
as the MCP caller (the caller context, sajha/observability/caller.py): its inner tool calls are
limited to what that caller may execute, narrowed further by ``ai.ask.mcp_allowed_tools`` when
that list is set, so the tool never gives a caller more than the caller already has
(sajha/core/inner_calls.py). Only where no entry point recorded the caller (code that runs the
tool directly) does the older rule apply: the anonymous MCP policy plus ``ai.ask.mcp_allowed_tools``.
``sajha_ask`` never calls itself. Destructive tools still need confirmation
(``stopped_by: needs_confirmation`` with fingerprints to pass back in ``confirm``).
"""

from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool

TOOL_NAME = "sajha_ask"

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The question to answer with SAJHA's tools."},
        "model": {"type": "string", "description": "Model alias or provider/model (default: ai.ask.model)."},
        "confirm": {"type": "array", "items": {"type": "string"},
                    "description": "Fingerprints of destructive tool calls the user has confirmed."},
    },
    "required": ["question"],
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"}, "confidence": {"type": "number"},
        "citations": {"type": "array", "items": {"type": "string"}},
        "stopped_by": {"type": "string"}, "steps": {"type": "array"}, "models": {"type": "array"},
    },
}


class SajhaAskTool(BaseMCPTool):
    def __init__(self, config: Dict = None):
        cfg = {
            "name": TOOL_NAME,
            "description": ("Answer a natural-language question by letting SAJHA pick and run its own tools; "
                            "returns the answer with the tool calls it relied on and a confidence score."),
            "version": "1.0.0", "enabled": True,
            "inputSchema": INPUT_SCHEMA, "outputSchema": OUTPUT_SCHEMA,
            "metadata": {"category": "Intelligence", "tags": ["ai", "ask", "agent"]},
            "annotations": {"readOnlyHint": False, "openWorldHint": True},
        }
        cfg.update(config or {})
        super().__init__(cfg)

    def get_input_schema(self) -> Dict:
        return INPUT_SCHEMA

    def get_output_schema(self) -> Dict:
        return OUTPUT_SCHEMA

    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.ai.intelligence import get_intelligence
        from sajha.ai.llm.types import RequestContext
        svc = get_intelligence()
        if svc is None:
            raise RuntimeError("SAJHA intelligence service is not initialised")
        question = str(arguments.get("question") or "").strip()
        if not question:
            raise ValueError("question is required")
        from sajha.core import inner_calls
        from sajha.observability.caller import current
        who = current()
        ctx = RequestContext(user_id=who.user_id if who.access is not None else "mcp:sajha_ask",
                             roles=list(who.roles) if who.access is not None else ["mcp"],
                             is_admin=bool(who.is_admin and who.access is not None),
                             can_use_tool=inner_access(svc.settings, who))
        with inner_calls.entered(TOOL_NAME):
            result = svc.ask(question, ctx, model=arguments.get("model") or None,
                             confirm=list(arguments.get("confirm") or []))
        return result.to_dict()


def inner_access(settings, caller=None):
    """name -> bool for the tools sajha_ask may run for ``caller`` (default: the current caller).

    A caller whose access an entry point recorded: that access, narrowed to
    ``ai.ask.mcp_allowed_tools`` when the list is set. A caller with no recorded access (code
    running the tool directly): the anonymous MCP policy plus ``ai.ask.mcp_allowed_tools``."""
    import fnmatch
    if caller is None:
        from sajha.observability.caller import current
        caller = current()
    patterns = list(getattr(settings, "mcp_allowed_tools", []) or [])

    def listed(name: str) -> bool:
        return any(p == "*" or fnmatch.fnmatchcase(name, p) for p in patterns)

    if caller.access is not None:
        def can_use(name: str) -> bool:
            if name == TOOL_NAME:
                return False
            if patterns and not listed(name):
                return False
            return bool(caller.can_execute(name))
        return can_use

    try:
        from sajha.auth.access import anonymous_policy
        anon = anonymous_policy()
    except Exception:
        anon = None

    def can_use_unrecorded(name: str) -> bool:
        if name == TOOL_NAME:
            return False
        if listed(name):
            return True
        return bool(anon is not None and anon.can_execute(name))
    return can_use_unrecorded


def register_if_enabled(tools_registry, settings) -> bool:
    if not getattr(settings, "mcp_tool_enabled", False) or tools_registry is None:
        return False
    tools_registry.register_tool(SajhaAskTool())
    return True
