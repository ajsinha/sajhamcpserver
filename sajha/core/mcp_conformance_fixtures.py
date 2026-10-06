"""
MCP conformance-suite fixtures (opt-in, off by default).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The official MCP conformance suite (@modelcontextprotocol/conformance) checks
server behaviour by calling a fixed set of test tools, prompts and resources
(``test_simple_text``, ``test_simple_prompt``, ``test://static-text`` ...).
This module provides exactly those fixtures so SAJHA's protocol layer can be
verified end to end.  They are NOT business tools and are only exposed when

    mcp:
      conformance_fixtures: true          # or SAJHA_MCP_CONFORMANCE_FIXTURES=true

is set.  Leave it off in production.
"""

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional

# 1x1 red PNG and an 8-sample silent 8 kHz WAV
RED_PIXEL_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
TINY_WAV = "UklGRiwAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQgAAACAgICAgICAgA=="

_EMPTY_SCHEMA = {"type": "object", "properties": {}}


def _text(t: str) -> Dict:
    return {"type": "text", "text": t}


# ── synchronous tools ─────────────────────────────────────────────

def _simple_text(args):
    return {"content": [_text("This is a simple text response for testing.")]}


def _image(args):
    return {"content": [{"type": "image", "data": RED_PIXEL_PNG, "mimeType": "image/png"}]}


def _audio(args):
    return {"content": [{"type": "audio", "data": TINY_WAV, "mimeType": "audio/wav"}]}


def _embedded_resource(args):
    return {"content": [{"type": "resource", "resource": {
        "uri": "test://embedded-resource", "mimeType": "text/plain",
        "text": "This is an embedded resource content."}}]}


def _mixed(args):
    return {"content": [
        _text("Multiple content types test:"),
        {"type": "image", "data": RED_PIXEL_PNG, "mimeType": "image/png"},
        {"type": "resource", "resource": {
            "uri": "test://mixed-content-resource", "mimeType": "application/json",
            "text": json.dumps({"test": "data", "value": 123})}},
    ]}


def _error(args):
    raise RuntimeError("This tool intentionally returns an error for testing")


def _json_schema_tool(args):
    return {"content": [_text(f"Received: {json.dumps(args)}")]}


# ── asynchronous tools (need the streaming ToolCallContext) ──────

async def _with_logging(args, ctx):
    await ctx.log("info", "Tool execution started")
    await asyncio.sleep(0.05)
    await ctx.log("info", "Tool processing data")
    await asyncio.sleep(0.05)
    await ctx.log("info", "Tool execution completed")
    return {"content": [_text("Tool with logging executed successfully")]}


async def _with_progress(args, ctx):
    await ctx.progress(0, 100)
    await asyncio.sleep(0.05)
    await ctx.progress(50, 100)
    await asyncio.sleep(0.05)
    await ctx.progress(100, 100)
    return {"content": [_text("Tool with progress executed successfully")]}


async def _sampling(args, ctx):
    if not ctx.client_supports("sampling"):
        raise RuntimeError("Client does not support sampling")
    result = await ctx.request("sampling/createMessage", {
        "messages": [{"role": "user", "content": _text(args.get("prompt", ""))}],
        "maxTokens": 100,
    })
    content = result.get("content") or {}
    if isinstance(content, list):
        content = content[0] if content else {}
    text = content.get("text", "") if isinstance(content, dict) else str(content)
    return {"content": [_text(f"LLM response: {text}")]}


async def _elicit(ctx, message: str, schema: Dict) -> Dict:
    if not ctx.client_supports("elicitation"):
        raise RuntimeError("Client does not support elicitation")
    return await ctx.request("elicitation/create", {"message": message, "requestedSchema": schema})


async def _elicitation(args, ctx):
    result = await _elicit(ctx, args.get("message", ""), {
        "type": "object",
        "properties": {
            "username": {"type": "string", "description": "User's response"},
            "email": {"type": "string", "description": "User's email address"},
        },
        "required": ["username", "email"],
    })
    return {"content": [_text(
        f"User response: action={result.get('action')}, content={json.dumps(result.get('content', {}))}")]}


async def _elicitation_defaults(args, ctx):
    result = await _elicit(ctx, "Please review and update the form fields with defaults", {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "User name", "default": "John Doe"},
            "age": {"type": "integer", "description": "User age", "default": 30},
            "score": {"type": "number", "description": "User score", "default": 95.5},
            "status": {"type": "string", "description": "User status",
                       "enum": ["active", "inactive", "pending"], "default": "active"},
            "verified": {"type": "boolean", "description": "Verification status", "default": True},
        },
    })
    return {"content": [_text(
        f"Elicitation completed: action={result.get('action')}, content={json.dumps(result.get('content', {}))}")]}


async def _elicitation_enums(args, ctx):
    result = await _elicit(ctx, "Please select options from the enum fields", {
        "type": "object",
        "properties": {
            "untitledSingle": {"type": "string", "description": "Untitled single-select",
                               "enum": ["option1", "option2", "option3"]},
            "titledSingle": {"type": "string", "description": "Titled single-select", "oneOf": [
                {"const": "value1", "title": "First Option"},
                {"const": "value2", "title": "Second Option"},
                {"const": "value3", "title": "Third Option"}]},
            "legacyEnum": {"type": "string", "description": "Legacy titled enum",
                           "enum": ["opt1", "opt2", "opt3"],
                           "enumNames": ["Option One", "Option Two", "Option Three"]},
            "untitledMulti": {"type": "array", "description": "Untitled multi-select",
                              "items": {"type": "string", "enum": ["option1", "option2", "option3"]}},
            "titledMulti": {"type": "array", "description": "Titled multi-select", "items": {"anyOf": [
                {"const": "value1", "title": "First Choice"},
                {"const": "value2", "title": "Second Choice"},
                {"const": "value3", "title": "Third Choice"}]}},
        },
    })
    return {"content": [_text(
        f"Elicitation completed: action={result.get('action')}, content={json.dumps(result.get('content', {}))}")]}


def _logging_tool(args):
    # 2026-07-28: the server MUST NOT emit notifications/message unless the
    # request carried _meta["io.modelcontextprotocol/logLevel"].  The modern
    # path has no response stream in Wave 1, so this never logs to the client.
    return {"content": [_text("Logging tool executed")]}


def _missing_capability(args):
    # Only reached when the client declared `sampling`; see `requires`.
    return {"content": [_text("Client declared the sampling capability")]}


def _custom_header(args):
    return {"content": [_text(f"Region: {args.get('region')}; query: {args.get('query')}")]}


def _tool(name, description, fn, schema=None, is_async=False, era="both", requires=None):
    """era: "both", "legacy" (needs server -> client requests) or "modern" (2026-07-28 only).
    requires: client capabilities the tool needs, as a ClientCapabilities object."""
    return {"definition": {"name": name, "description": description,
                           "inputSchema": schema or dict(_EMPTY_SCHEMA)},
            "fn": fn, "async": is_async, "era": era, "requires": requires or {}}


_TOOLS: Dict[str, Dict] = {t["definition"]["name"]: t for t in [
    _tool("test_simple_text", "Returns simple text content", _simple_text),
    _tool("test_image_content", "Returns image content", _image),
    _tool("test_audio_content", "Returns audio content", _audio),
    _tool("test_embedded_resource", "Returns an embedded resource", _embedded_resource),
    _tool("test_multiple_content_types", "Returns text, image and resource content", _mixed),
    _tool("test_error_handling", "Always fails", _error),
    _tool("json_schema_2020_12_tool", "Tool with JSON Schema 2020-12 features", _json_schema_tool, {
        # SEP-1613 ($schema, $defs, additionalProperties) plus the SEP-2106
        # vocabulary checked from 2026-07-28 ($anchor, allOf/anyOf, if/then/else)
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "$defs": {"address": {"$anchor": "addressDef", "type": "object", "properties": {
            "street": {"type": "string"}, "city": {"type": "string"}}}},
        "properties": {
            "name": {"type": "string"},
            "address": {"$ref": "#/$defs/address"},
            "contactMethod": {"type": "string", "enum": ["phone", "email"]},
            "phone": {"type": "string"},
            "email": {"type": "string"},
        },
        "allOf": [{"anyOf": [{"required": ["phone"]}, {"required": ["email"]}]}],
        "if": {"properties": {"contactMethod": {"const": "phone"}}, "required": ["contactMethod"]},
        "then": {"required": ["phone"]},
        "else": {"required": ["email"]},
        "additionalProperties": False,
    }),
    _tool("test_tool_with_logging", "Sends log notifications while running", _with_logging, is_async=True),
    _tool("test_tool_with_progress", "Sends progress notifications while running", _with_progress, is_async=True),
    _tool("test_sampling", "Requests LLM sampling from the client", _sampling, {
        "type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}, is_async=True,
          era="legacy"),
    _tool("test_elicitation", "Requests user input from the client", _elicitation, {
        "type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}, is_async=True,
          era="legacy"),
    _tool("test_elicitation_sep1034_defaults", "Elicitation with defaults (SEP-1034)",
          _elicitation_defaults, is_async=True, era="legacy"),
    _tool("test_elicitation_sep1330_enums", "Elicitation with enum variants (SEP-1330)",
          _elicitation_enums, is_async=True, era="legacy"),
    # ── 2026-07-28 diagnostics (conformance scenarios server-stateless and
    #    http-custom-header-server-validation) ──
    _tool("test_logging_tool", "Would log only when the request sets a logLevel", _logging_tool,
          era="modern"),
    _tool("test_missing_capability", "Requires the client's sampling capability",
          _missing_capability, era="modern", requires={"sampling": {}}),
    _tool("test_custom_header", "Mirrors its region argument into the Mcp-Param-Region header",
          _custom_header, {
              "type": "object",
              "properties": {
                  "region": {"type": "string", "description": "Region to route to",
                             "x-mcp-header": "Region"},
                  "query": {"type": "string", "description": "Free text"},
              },
              "required": ["region"],
          }, era="modern"),
]}


# ── prompts ──────────────────────────────────────────────────────

_PROMPTS: Dict[str, Dict] = {
    "test_simple_prompt": {"name": "test_simple_prompt", "description": "A simple prompt without arguments",
                           "arguments": []},
    "test_prompt_with_arguments": {"name": "test_prompt_with_arguments",
                                   "description": "A prompt with required arguments",
                                   "arguments": [
                                       {"name": "arg1", "description": "First test argument", "required": True},
                                       {"name": "arg2", "description": "Second test argument", "required": True}]},
    "test_prompt_with_embedded_resource": {"name": "test_prompt_with_embedded_resource",
                                           "description": "A prompt with an embedded resource",
                                           "arguments": [{"name": "resourceUri",
                                                          "description": "URI of the resource to embed",
                                                          "required": True}]},
    "test_prompt_with_image": {"name": "test_prompt_with_image", "description": "A prompt with image content",
                               "arguments": []},
}


def _prompt_messages(name: str, args: Dict) -> Dict:
    if name == "test_simple_prompt":
        msgs = [{"role": "user", "content": _text("This is a simple prompt for testing.")}]
    elif name == "test_prompt_with_arguments":
        msgs = [{"role": "user", "content": _text(
            f"Prompt with arguments: arg1='{args.get('arg1')}', arg2='{args.get('arg2')}'")}]
    elif name == "test_prompt_with_embedded_resource":
        msgs = [
            {"role": "user", "content": {"type": "resource", "resource": {
                "uri": args.get("resourceUri", "test://example-resource"), "mimeType": "text/plain",
                "text": "Embedded resource content for testing."}}},
            {"role": "user", "content": _text("Please process the embedded resource above.")},
        ]
    else:
        msgs = [
            {"role": "user", "content": {"type": "image", "data": RED_PIXEL_PNG, "mimeType": "image/png"}},
            {"role": "user", "content": _text("Please analyze the image above.")},
        ]
    return {"messages": msgs}


# ── resources ────────────────────────────────────────────────────

_RESOURCES: List[Dict] = [
    {"uri": "test://static-text", "name": "Static Text", "description": "Static text resource",
     "mimeType": "text/plain"},
    {"uri": "test://static-binary", "name": "Static Binary", "description": "Static binary (PNG) resource",
     "mimeType": "image/png"},
    {"uri": "test://watched-resource", "name": "Watched Resource",
     "description": "Resource used by subscribe tests", "mimeType": "text/plain"},
]

_TEMPLATES: List[Dict] = [
    {"uriTemplate": "test://template/{id}/data", "name": "Template Data",
     "description": "Templated test resource", "mimeType": "application/json"},
]
_TEMPLATE_RE = re.compile(r"^test://template/([^/]+)/data$")


class ConformanceFixtures:
    """Facade used by MCPHandler / routes when fixtures are enabled."""

    # tools
    def tool_definitions(self, era: str = "legacy") -> List[Dict]:
        """Fixture tools visible to a client of the given era ("legacy" or "modern")."""
        return [dict(t["definition"]) for t in _TOOLS.values() if t["era"] in ("both", era)]

    def has_tool(self, name: str, era: str = "legacy") -> bool:
        return name in _TOOLS and _TOOLS[name]["era"] in ("both", era)

    def required_client_capabilities(self, name: str) -> Dict:
        return dict(_TOOLS[name]["requires"]) if name in _TOOLS else {}

    def tool_input_schema(self, name: str) -> Optional[Dict]:
        return _TOOLS[name]["definition"]["inputSchema"] if name in _TOOLS else None

    def is_async_tool(self, name: str) -> bool:
        return name in _TOOLS and _TOOLS[name]["async"]

    def call_tool(self, name: str, args: Dict) -> Dict:
        try:
            return _TOOLS[name]["fn"](args or {})
        except Exception as e:  # tool execution errors are results, not protocol errors
            return {"content": [_text(str(e))], "isError": True}

    async def call_tool_async(self, name: str, args: Dict, ctx) -> Dict:
        try:
            return await _TOOLS[name]["fn"](args or {}, ctx)
        except Exception as e:
            return {"content": [_text(str(e))], "isError": True}

    # prompts
    def prompt_definitions(self) -> List[Dict]:
        return [dict(p) for p in _PROMPTS.values()]

    def has_prompt(self, name: str) -> bool:
        return name in _PROMPTS

    def get_prompt(self, name: str, args: Dict) -> Dict:
        for a in _PROMPTS[name]["arguments"]:
            if a.get("required") and not (args or {}).get(a["name"]):
                raise ValueError(f"Missing required argument: {a['name']}")
        return _prompt_messages(name, args or {})

    # resources
    def resources(self) -> List[Dict]:
        return [dict(r) for r in _RESOURCES]

    def resource_templates(self) -> List[Dict]:
        return [dict(t) for t in _TEMPLATES]

    def read_resource(self, uri: str) -> Optional[Dict]:
        if uri == "test://static-text":
            return {"contents": [{"uri": uri, "mimeType": "text/plain",
                                  "text": "This is the content of the static text resource."}]}
        if uri == "test://static-binary":
            return {"contents": [{"uri": uri, "mimeType": "image/png", "blob": RED_PIXEL_PNG}]}
        if uri == "test://watched-resource":
            return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": "Watched resource content."}]}
        m = _TEMPLATE_RE.match(uri)
        if m:
            rid = m.group(1)
            return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(
                {"id": rid, "templateTest": True, "data": f"Data for ID: {rid}"})}]}
        return None


_fixtures: Optional[ConformanceFixtures] = None


def get_conformance_fixtures() -> Optional[ConformanceFixtures]:
    """Return the fixtures facade when enabled in config, else None."""
    global _fixtures
    from sajha.core.config import _bool
    if not _bool('mcp.conformance_fixtures', False):
        return None
    if _fixtures is None:
        _fixtures = ConformanceFixtures()
    return _fixtures
