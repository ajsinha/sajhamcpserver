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
    # request carried _meta["io.modelcontextprotocol/logLevel"].  Without one
    # the modern path does not even open a response stream for tools/call
    # (test_tool_with_logging shows the logLevel-gated stream).
    return {"content": [_text("Logging tool executed")]}


def _missing_capability(args):
    # Only reached when the client declared `sampling`; see `requires`.
    return {"content": [_text("Client declared the sampling capability")]}


def _custom_header(args):
    return {"content": [_text(f"Region: {args.get('region')}; query: {args.get('query')}")]}


# ── 2026-07-28 fixtures: streaming, subscriptions, MRTR (SEP-2322), tasks (SEP-2663) ──

def _trigger_tool_change(args):
    from sajha.core.change_bus import get_change_bus
    get_change_bus().tools_changed()
    return {"content": [_text("Published notifications/tools/list_changed")]}


def _trigger_prompt_change(args):
    from sajha.core.change_bus import get_change_bus
    get_change_bus().prompts_changed()
    return {"content": [_text("Published notifications/prompts/list_changed")]}


_NAME_FORM = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}


def _elicit_req(message, schema):
    return {"method": "elicitation/create", "params": {"message": message, "requestedSchema": schema}}


def _sampling_req(text, max_tokens=100):
    return {"method": "sampling/createMessage", "params": {
        "messages": [{"role": "user", "content": _text(text)}], "maxTokens": max_tokens}}


_ROOTS_REQ = {"method": "roots/list", "params": {}}


def _accepted(ctx, key):
    """Content of an accepted ElicitResult for key, {} for decline/cancel, None when absent/invalid."""
    resp = ctx.input_responses.get(key)
    if not isinstance(resp, dict):
        return None
    if resp.get("action") == "accept":
        return resp.get("content") if isinstance(resp.get("content"), dict) else {}
    if resp.get("action") in ("decline", "cancel"):
        return {}
    return None


def _sampled_text(resp):
    content = (resp or {}).get("content") if isinstance(resp, dict) else None
    if isinstance(content, list):
        content = content[0] if content else {}
    return content.get("text", "") if isinstance(content, dict) else ""


async def _streaming_elicitation(args, ctx):
    await ctx.progress(0, 1, "asking the user")
    answer = _accepted(ctx, "confirm")
    if answer is None:
        ctx.require_input({"confirm": _elicit_req("Continue?", {
            "type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})})
    await ctx.progress(1, 1, "done")
    return {"content": [_text(f"Confirmed: {bool(answer.get('ok'))}")]}


async def _irr_elicitation(args, ctx):
    answer = _accepted(ctx, "user_name")
    if answer is None:
        ctx.require_input({"user_name": _elicit_req("What is your name?", _NAME_FORM)})
    return {"content": [_text(f"Hello, {answer.get('name', 'anonymous')}!")]}


async def _irr_sampling(args, ctx):
    resp = ctx.input_responses.get("capital_question")
    if not isinstance(resp, dict):
        ctx.require_input({"capital_question": _sampling_req("What is the capital of France?")})
    return {"content": [_text(f"LLM response: {_sampled_text(resp)}")]}


async def _irr_list_roots(args, ctx):
    resp = ctx.input_responses.get("client_roots")
    if not isinstance(resp, dict) or not isinstance(resp.get("roots"), list):
        ctx.require_input({"client_roots": _ROOTS_REQ})
    uris = [r.get("uri") for r in resp["roots"] if isinstance(r, dict)]
    return {"content": [_text(f"Client roots: {', '.join(uris) or '(none)'}")]}


async def _irr_request_state(args, ctx):
    answer = _accepted(ctx, "confirm")
    if answer is None or not (ctx.state_verified and ctx.state.get("issued")):
        ctx.require_input({"confirm": _elicit_req("Please confirm", {
            "type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})},
            state={"issued": True})
    return {"content": [_text(f"state-ok: confirmed={bool(answer.get('ok'))}")]}


async def _irr_multiple_inputs(args, ctx):
    name = _accepted(ctx, "user_name")
    greeting = ctx.input_responses.get("greeting")
    roots = ctx.input_responses.get("client_roots")
    missing = {}
    if name is None:
        missing["user_name"] = _elicit_req("What is your name?", _NAME_FORM)
    if not isinstance(greeting, dict):
        missing["greeting"] = _sampling_req("Generate a greeting", 50)
    if not isinstance(roots, dict):
        missing["client_roots"] = _ROOTS_REQ
    if missing:
        ctx.require_input(missing)
    return {"content": [_text(f"{_sampled_text(greeting)} {name.get('name', '')}; "
                              f"{len(roots.get('roots') or [])} root(s)")]}


async def _irr_multi_round(args, ctx):
    step1 = _accepted(ctx, "step1")
    if step1 is None:
        ctx.require_input({"step1": _elicit_req("Step 1: What is your name?", _NAME_FORM)})
    step2 = _accepted(ctx, "step2")
    if step2 is None:
        ctx.require_input({"step2": _elicit_req("Step 2: What is your favorite color?", {
            "type": "object", "properties": {"color": {"type": "string"}}, "required": ["color"]})})
    return {"content": [_text(f"{step1.get('name')} likes {step2.get('color')}")]}


async def _irr_tampered_state(args, ctx):
    answer = _accepted(ctx, "confirm")
    if answer is None or not ctx.state_verified:
        ctx.require_input({"confirm": _elicit_req("Please confirm", {
            "type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]})},
            state={"issued": True})
    return {"content": [_text("state verified")]}


async def _irr_capabilities(args, ctx):
    wanted = {}
    if ctx.client_supports("sampling") and not isinstance(ctx.input_responses.get("sample"), dict):
        wanted["sample"] = _sampling_req("Say hello", 20)
    if ctx.client_supports("elicitation") and _accepted(ctx, "ask") is None:
        wanted["ask"] = _elicit_req("What is your name?", _NAME_FORM)
    if wanted:
        ctx.require_input(wanted)
    return {"content": [_text("Collected input for the declared client capabilities")]}


def _greet(args):
    return {"content": [_text(f"Hello, {args.get('name', 'World')}!")]}


async def _slow_compute(args, ctx):
    try:
        seconds = max(0.0, float(args.get("seconds", 1)))
    except (TypeError, ValueError):
        seconds = 1.0
    label = args.get("label", "job")
    waited = 0.0
    while waited < seconds:
        step = min(0.1, seconds - waited)
        await asyncio.sleep(step)
        waited += step
        await ctx.progress(round(waited, 3), seconds)
    return {"content": [_text(f"Computed {label} in {seconds:g}s")]}


async def _failing_job(args, ctx):
    await asyncio.sleep(1.0)
    return {"content": [_text("failing_job: the job ran and reported an error")], "isError": True}


async def _protocol_error_job(args, ctx):
    from sajha.core.mcp_2025_11_25 import MCPError
    await asyncio.sleep(0.2)
    raise MCPError(-32603, "protocol_error_job: simulated internal failure")


async def _confirm_delete(args, ctx):
    filename = args.get("filename", "file")
    answer = _accepted(ctx, "confirm")
    if answer is None:
        ctx.require_input({"confirm": _elicit_req(f"Delete {filename}?", {
            "type": "object", "properties": {"confirm": {"type": "boolean"}}, "required": ["confirm"]})})
    if answer.get("confirm"):
        return {"content": [_text(f"Deleted {filename}")]}
    return {"content": [_text(f"Deletion of {filename} cancelled")]}


async def _multi_input(args, ctx):
    first, second = _accepted(ctx, "first"), _accepted(ctx, "second")
    missing = {}
    if first is None:
        missing["first"] = _elicit_req("First input?", _NAME_FORM)
    if second is None:
        missing["second"] = _elicit_req("Second input?", _NAME_FORM)
    if missing:
        ctx.require_input(missing)
    return {"content": [_text(f"Got {first.get('name')} and {second.get('name')}")]}


async def _tool_with_task(args, ctx):
    answer = _accepted(ctx, "user_name")
    if answer is None:
        ctx.require_input({"user_name": _elicit_req("What is your name?", _NAME_FORM)})
    await asyncio.sleep(0.2)
    return {"content": [_text(f"Hello, {answer.get('name', 'anonymous')}! (computed in a task)")]}


def _tool(name, description, fn, schema=None, is_async=False, era="both", requires=None,
          task_support=None, task_after_input=False):
    """era: "both", "legacy" (needs server -> client requests) or "modern" (2026-07-28 only).
    requires: client capabilities the tool needs, as a ClientCapabilities object.
    task_support: None / "optional" / "required" (io.modelcontextprotocol/tasks, modern only).
    task_after_input: gather MRTR input synchronously first, create the task on the final round."""
    return {"definition": {"name": name, "description": description,
                           "inputSchema": schema or dict(_EMPTY_SCHEMA)},
            "fn": fn, "async": is_async, "era": era, "requires": requires or {},
            "task_support": task_support, "task_after_input": task_after_input}


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
    _tool("test_streaming_elicitation", "Needs a confirmation (MRTR) - never a request on the stream",
          _streaming_elicitation, is_async=True, era="modern", requires={"elicitation": {}}),
    _tool("test_trigger_tool_change", "Publishes notifications/tools/list_changed", _trigger_tool_change,
          era="modern"),
    _tool("test_trigger_prompt_change", "Publishes notifications/prompts/list_changed", _trigger_prompt_change,
          era="modern"),
    _tool("test_input_required_result_elicitation", "MRTR: one elicitation", _irr_elicitation,
          is_async=True, era="modern"),
    _tool("test_input_required_result_sampling", "MRTR: one sampling request", _irr_sampling,
          is_async=True, era="modern"),
    _tool("test_input_required_result_list_roots", "MRTR: one roots/list request", _irr_list_roots,
          is_async=True, era="modern"),
    _tool("test_input_required_result_request_state", "MRTR: requestState round trip", _irr_request_state,
          is_async=True, era="modern"),
    _tool("test_input_required_result_multiple_inputs", "MRTR: elicitation + sampling + roots at once",
          _irr_multiple_inputs, is_async=True, era="modern"),
    _tool("test_input_required_result_multi_round", "MRTR: two rounds", _irr_multi_round,
          is_async=True, era="modern"),
    _tool("test_input_required_result_tampered_state", "MRTR: rejects a tampered requestState",
          _irr_tampered_state, is_async=True, era="modern"),
    _tool("test_input_required_result_capabilities", "MRTR: asks only for declared capabilities",
          _irr_capabilities, is_async=True, era="modern"),
    # tasks extension (SEP-2663)
    _tool("greet", "Sync-only: returns Hello, {name}!", _greet, {
        "type": "object", "properties": {"name": {"type": "string"}}}, era="modern"),
    _tool("slow_compute", "Task-supporting: sleeps `seconds` then returns", _slow_compute, {
        "type": "object", "properties": {"seconds": {"type": "number"}, "label": {"type": "string"}}},
          is_async=True, era="modern", task_support="optional"),
    _tool("failing_job", "Task-required: reports a tool error after ~1s", _failing_job,
          is_async=True, era="modern", task_support="required"),
    _tool("protocol_error_job", "Task-supporting: fails with a protocol-level error", _protocol_error_job,
          is_async=True, era="modern", task_support="optional"),
    _tool("confirm_delete", "Task-supporting: asks for confirmation (elicitation) first", _confirm_delete, {
        "type": "object", "properties": {"filename": {"type": "string"}}},
          is_async=True, era="modern", task_support="optional"),
    _tool("multi_input", "Task-supporting: asks for two inputs in parallel", _multi_input,
          is_async=True, era="modern", task_support="optional"),
    _tool("test_tool_with_task", "MRTR then task: gathers user_name, then runs as a task", _tool_with_task,
          is_async=True, era="modern", task_support="required", task_after_input=True),
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
    "test_input_required_result_prompt": {"name": "test_input_required_result_prompt",
                                          "description": "MRTR on prompts/get: asks for context first",
                                          "arguments": []},
}
_MODERN_ONLY_PROMPTS = {"test_input_required_result_prompt"}


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
    elif name == "test_input_required_result_prompt":
        msgs = [{"role": "user", "content": _text(f"Use this context: {args.get('context', '')}")}]
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
        out = []
        for t in _TOOLS.values():
            if t["era"] not in ("both", era):
                continue
            d = dict(t["definition"])
            if era == "modern" and t["task_support"]:
                d["execution"] = {"taskSupport": t["task_support"]}
            out.append(d)
        return out

    def task_support(self, name: str) -> Optional[str]:
        return _TOOLS[name]["task_support"] if name in _TOOLS else None

    def task_after_input(self, name: str) -> bool:
        return name in _TOOLS and _TOOLS[name]["task_after_input"]

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
        from sajha.core.mcp_mrtr import InputRequired
        from sajha.core.mcp_2025_11_25 import MCPError
        try:
            return await _TOOLS[name]["fn"](args or {}, ctx)
        except (InputRequired, MCPError):
            raise                    # MRTR signal / protocol error: the transport handles these
        except Exception as e:
            return {"content": [_text(str(e))], "isError": True}

    # prompts
    def prompt_definitions(self, era: str = "legacy") -> List[Dict]:
        return [dict(p) for n, p in _PROMPTS.items() if era == "modern" or n not in _MODERN_ONLY_PROMPTS]

    def has_prompt(self, name: str, era: str = "legacy") -> bool:
        return name in _PROMPTS and (era == "modern" or name not in _MODERN_ONLY_PROMPTS)

    def get_prompt_mrtr(self, name: str, args: Dict, ctx) -> Dict:
        """prompts/get on the modern path: may raise InputRequired (SEP-2322)."""
        if name == "test_input_required_result_prompt":
            answer = _accepted(ctx, "user_context")
            if answer is None:
                ctx.require_input({"user_context": _elicit_req("What context should the prompt use?", {
                    "type": "object", "properties": {"context": {"type": "string"}}, "required": ["context"]})})
            return _prompt_messages(name, {"context": answer.get("context", "")})
        return self.get_prompt(name, args)

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
