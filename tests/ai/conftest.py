"""Fixtures for the intelligence-layer tests: real offline calc_* tools, mock-only gateways."""

import glob
import importlib
import json

import pytest

from sajha.tools.base_mcp_tool import BaseMCPTool


class FakeTool(BaseMCPTool):
    """A configurable tool: returns ``output`` (or calls it) and counts executions."""

    def __init__(self, name, description, schema=None, output=None, destructive=False):
        cfg = {"name": name, "description": description,
               "inputSchema": schema or {"type": "object", "properties": {}},
               "outputSchema": {"type": "object"}}
        if destructive:
            cfg["annotations"] = {"destructiveHint": True}
        super().__init__(cfg)
        self.output = output
        self.calls = []

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {"type": "object"}

    def execute(self, arguments):
        self.calls.append(dict(arguments))
        return self.output(arguments) if callable(self.output) else self.output


class ToolBox:
    """Minimal ToolsRegistry stand-in (tools dict + get_tool), loaded with the real calc_* tools."""

    def __init__(self, with_calc=True):
        self.tools = {}
        if with_calc:
            for f in sorted(glob.glob("config/tools/calc_*.json")):
                cfg = json.load(open(f))
                mod, cls = cfg["implementation"].rsplit(".", 1)
                self.tools[cfg["name"]] = getattr(importlib.import_module(mod), cls)(cfg)

    def add(self, tool):
        self.tools[tool.name] = tool
        return tool

    def register_tool(self, tool):
        self.add(tool)

    def get_tool(self, name):
        return self.tools.get(name)


@pytest.fixture
def toolbox():
    return ToolBox()


def make_gateway(raw=None, environ=None, **kw):
    """A gateway built only from the given ai: dict (no YAML file, no DB, no process env)."""
    from sajha.ai.llm import build_llm_factory as build_gateway
    raw = dict(raw or {})
    raw.setdefault("gateway", {"load_entry_points": False, "use_db_providers": False})
    providers = raw.setdefault("providers", [])
    if not any(p.get("name") == "mock" for p in providers):
        providers.insert(0, {"name": "mock", "config": {"enabled": True, "scripts_dir": ""}})
    gw = build_gateway(raw, environ=environ if environ is not None else {}, **kw)
    gw.sleeps = []
    gw.sleep = gw.sleeps.append
    return gw


@pytest.fixture
def gateway():
    return make_gateway()
