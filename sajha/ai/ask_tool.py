"""
SAJHA MCP Server — the ``sajha_ask`` MCP tool (off by default: ai.ask.mcp_tool_enabled).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Lets a thin MCP client delegate a whole question to SAJHA's intelligence layer. A tool's
execute() does not see the MCP caller, so the inner calls are limited to what an anonymous MCP
caller may run (``mcp.anonymous.*``, via sajha.auth.access) plus ``ai.ask.mcp_allowed_tools``
patterns; destructive tools still need confirmation (``stopped_by: needs_confirmation`` with
fingerprints to pass back in ``confirm``).
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
        ctx = RequestContext(user_id="mcp:sajha_ask", roles=["mcp"], can_use_tool=inner_access(svc.settings))
        result = svc.ask(question, ctx, model=arguments.get("model") or None,
                         confirm=list(arguments.get("confirm") or []))
        return result.to_dict()


def inner_access(settings):
    """name -> bool for the tools sajha_ask may run on behalf of an unidentified MCP caller."""
    import fnmatch
    patterns = list(getattr(settings, "mcp_allowed_tools", []) or [])
    try:
        from sajha.auth.access import anonymous_policy
        anon = anonymous_policy()
    except Exception:
        anon = None

    def can_use(name: str) -> bool:
        if name == TOOL_NAME:
            return False
        if any(p == "*" or fnmatch.fnmatchcase(name, p) for p in patterns):
            return True
        return bool(anon is not None and anon.can_execute(name))
    return can_use


def register_if_enabled(tools_registry, settings) -> bool:
    if not getattr(settings, "mcp_tool_enabled", False) or tools_registry is None:
        return False
    tools_registry.register_tool(SajhaAskTool())
    return True
