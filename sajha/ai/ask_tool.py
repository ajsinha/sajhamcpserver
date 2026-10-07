"""
SAJHA MCP Server — ``sajha_ask``: a compatibility shim over the LLM-tool type.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

``sajha_ask`` is an LLM tool (docs/architecture/LLM Tools.md §18): its definition is
``config/tools/sajha_ask.json`` (mode ``answer``, conversation memory, every tool allowed), loaded
by the tool registry like any tool and disabled there. ``ai.ask.mcp_tool_enabled`` stays its on/off
switch: :func:`register_if_enabled` turns the tool on or off from it at start-up and after each
reload.

What this class keeps from the hand-coded tool it replaces:

* ``ai.ask.mcp_allowed_tools``, when set, narrows the tools it may call (the config allows ``*``);
* the ``model`` argument picks the model alias for one call;
* a call with no recorded caller (code running the tool directly) may use what the anonymous MCP
  policy allows plus ``ai.ask.mcp_allowed_tools`` (:func:`inner_access`).

Every recorded caller's inner calls run as that caller, never with more access (sajha/core/inner_calls.py).
"""

from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from sajha.ai.llm_tools.tool import LLMTool

logger = logging.getLogger(__name__)

TOOL_NAME = "sajha_ask"
CONFIG_REL = f"config/tools/{TOOL_NAME}.json"


def load_config() -> Dict[str, Any]:
    """The tool's definition: through the storage backend, else the file shipped in the repository."""
    try:
        from sajha.core.storage import get_storage
        return dict(get_storage().read_json(CONFIG_REL))
    except Exception:
        root = Path(__file__).resolve().parents[2]
        return json.loads((root / CONFIG_REL).read_text(encoding="utf-8"))


class SajhaAskTool(LLMTool):
    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config if config is not None else load_config())

    def _ask_settings(self):
        try:
            return self._service().settings
        except Exception:
            from sajha.ai.llm.settings import AskSettings
            return AskSettings()

    def allowed_tools(self) -> List[str]:
        names = super().allowed_tools()
        patterns = list(getattr(self._ask_settings(), "mcp_allowed_tools", []) or [])
        if patterns:
            names = [n for n in names if any(p == "*" or fnmatch.fnmatchcase(n, p) for p in patterns)]
        return names

    def unrecorded_access(self, name: str) -> bool:
        return inner_access(self._ask_settings())(name)

    def _planner_for(self, args: Dict[str, Any]):
        """sajha_ask is Ask SAJHA over MCP: with no llm.planner it follows ai.ask.planner (and its
        planner_config), not ai.planners.default."""
        ref, info = super()._planner_for(args)
        if self.spec.planner is None and info.get("by") == "server default":
            ref, info["by"] = None, "server default"
        return ref, info

    def run(self, arguments: Dict[str, Any], *, ctx: Any = None, model: Optional[str] = None, remember: bool = True,
            audit: bool = True):
        return super().run(arguments, ctx=ctx, model=model or (arguments or {}).get("model") or None,
                           remember=remember, audit=audit)


def inner_access(settings, caller=None):
    """name -> bool for the tools sajha_ask may run for ``caller`` (default: the current caller).

    A caller whose access an entry point recorded: that access, narrowed to
    ``ai.ask.mcp_allowed_tools`` when the list is set. A caller with no recorded access (code
    running the tool directly): the anonymous MCP policy plus ``ai.ask.mcp_allowed_tools``."""
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
    """Apply ``ai.ask.mcp_tool_enabled`` to the registry's ``sajha_ask`` (registering it from its config
    file when the registry has not loaded it). True when the tool is on."""
    if tools_registry is None:
        return False
    tool = tools_registry.get_tool(TOOL_NAME)
    if not getattr(settings, "mcp_tool_enabled", False):
        if tool is not None and tool.enabled:
            tool.disable()
        return False
    if not isinstance(tool, SajhaAskTool):
        try:
            tool = SajhaAskTool()
        except Exception as e:
            logger.warning(f"sajha_ask: cannot load {CONFIG_REL}: {e}")
            return False
        tools_registry.register_tool(tool)
    if not tool.enabled:
        tool.enable()
    return True
