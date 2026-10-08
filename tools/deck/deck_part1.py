"""
The deck, as data. Sections 1 and 2: the Model Context Protocol from nothing, and how AI
applications integrate with it.

One deck split across four modules only to keep each file readable; read them in order
(see GUIDE.md). Every number comes from ``F``, the facts ``evidence`` derived at build time.
Statements about MCP itself and the quotations come from public sources named, with the
date they were read, in each slide's notes.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from evidence import require_tools
from prose import listing

READ = "read 2026-10-06"
ANTHROPIC_INTRO = "https://www.anthropic.com/news/model-context-protocol (25 Nov 2024)"
AAIF = (
    "https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation "
    f"(9 Dec 2025, {READ})"
)
BCG = f"https://www.bcg.com/publications/2025/put-ai-to-work-faster-using-model-context-protocol (1 Aug 2025, {READ})"
ALTMAN = (
    "https://techcrunch.com/2025/03/26/openai-adopts-rival-anthropics-standard-for-connecting-ai-models-to-data/ "
    f"(26 Mar 2025, {READ})"
)
HASSABIS = (
    "https://techcrunch.com/2025/04/09/google-says-itll-embrace-anthropics-standard-for-connecting-ai-models-to-data/ "
    f"(9 Apr 2025, {READ})"
)
SDKS = f"https://modelcontextprotocol.io/docs/sdk ({READ})"
SPEC = "https://modelcontextprotocol.io/specification (server features: tools, resources, prompts; transports)"


def _what_is_mcp(eras: dict[str, list[str]]) -> dict[str, Any]:
    """N x M integrations without a shared protocol, N + M with one: drawn, not described."""
    apps, tools = ["Chat app", "IDE", "Agent"], ["Database", "Search", "CRM", "Files"]
    ay, ty = [0.17, 0.42, 0.67], [0.12, 0.32, 0.52, 0.72]
    nodes, edges = [], []
    for side, x_app, x_tool in (("l", 0.03, 0.31), ("r", 0.56, 0.87)):
        for i, a in enumerate(apps):
            nodes.append({"id": f"{side}a{i}", "text": a, "x": x_app, "y": ay[i], "w": 0.12, "h": 0.14,
                          "style": "accent", "size": 13})
        for k, t in enumerate(tools):
            nodes.append({"id": f"{side}t{k}", "text": t, "x": x_tool, "y": ty[k], "w": 0.12, "h": 0.13,
                          "style": "white", "size": 13})
    nodes.append({"id": "hub", "text": "MCP", "sub": "one protocol", "x": 0.715, "y": 0.33, "w": 0.11, "h": 0.32,
                  "style": "dark", "shape": "oval", "size": 18})
    edges += [{"a": f"la{i}", "b": f"lt{k}", "mode": "c", "arrow": False, "width": 1.0, "gap": 0.03}
              for i in range(3) for k in range(4)]
    edges += [{"a": f"ra{i}", "b": "hub", "mode": "c", "arrow": False, "color": "CRIMSON", "width": 1.6} for i in range(3)]
    edges += [{"a": "hub", "b": f"rt{k}", "mode": "c", "arrow": False, "color": "CRIMSON", "width": 1.6}
              for k in range(4)]
    return {
        "kind": "canvas",
        "kicker": "What is MCP?",
        "title": "MCP is one open standard for connecting AI applications to tools and data",
        "groups": [
            {"id": "gl", "label": "WITHOUT A SHARED PROTOCOL: N × M INTEGRATIONS", "x": 0.0, "y": 0.0, "w": 0.46,
             "h": 0.92, "line": "RULE", "color": "SLATE"},
            {"id": "gr", "label": "WITH MCP: N + M", "x": 0.53, "y": 0.0, "w": 0.47, "h": 0.92},
        ],
        "nodes": nodes,
        "edges": edges,
        "items": [
            ("An open standard, neutrally governed", "Introduced by Anthropic in November 2024; in December 2025 donated "
             "to the Agentic AI Foundation under the Linux Foundation."),
            ("JSON-RPC 2.0 over a transport", "An application lists a server's tools, calls one, and reads its "
             "resources and prompts as JSON messages."),
            ("Two eras in use today", f"Session-based revisions up to {eras['handshake'][0]}, and the stateless "
             f"{eras['modern'][0]} revision (Section 2)."),
        ],
        "items_h": 1.55,
        "size": 14,
        "source": f"Introduction: {ANTHROPIC_INTRO}. Foundation, adopters and the server count: {AAIF}. Linear versus "
        f"quadratic integration effort: {BCG}. Eras: sajha.core.mcp_modern MODERN_PROTOCOL_VERSIONS and "
        "HANDSHAKE_PROTOCOL_VERSIONS, read at build time. Application and tool names in the drawing are generic.",
        "talk": "Think of MCP as one plug for every tool: write the server once, and every MCP-capable application can "
        "use it. Without a shared protocol every application needs its own integration with every tool, so the work "
        "grows with the product of the two; with one, each side implements the protocol once and the work grows "
        "with the sum. Anthropic introduced MCP in November 2024. In December 2025 it donated MCP to the Agentic AI "
        "Foundation, a directed fund under the Linux Foundation co-founded by Anthropic, Block and OpenAI; the "
        "announcement names ChatGPT, Cursor, Gemini, Microsoft Copilot and Visual Studio Code among the products "
        "using it, and more than 10,000 active public MCP servers.",
    }


def _patterns(single: list[str], chain: list[str], par: list[str], multi: list[str]) -> dict[str, Any]:
    """Four ways an agent calls tools, each drawn as the calls it makes."""
    def tool(i: str, name: str, x: float, y: float, w: float = 0.15) -> dict[str, Any]:
        return {"id": i, "text": name, "x": x, "y": y, "w": w, "h": 0.1, "style": "white", "size": 11, "bold": False}

    def agent(i: str, x: float, y: float, text: str = "agent") -> dict[str, Any]:
        return {"id": i, "text": text, "x": x, "y": y, "w": 0.08, "h": 0.14, "style": "accent", "shape": "oval",
                "size": 11}

    nodes = [
        agent("a1", 0.02, 0.15), tool("p1", single[0], 0.16, 0.16, 0.2),
        agent("a2", 0.53, 0.15), tool("c1", chain[0], 0.645, 0.08), tool("c2", chain[1], 0.645, 0.25),
        tool("c3", chain[2], 0.83, 0.165, 0.16),
        agent("a3", 0.02, 0.69), tool("q1", par[0], 0.2, 0.57), tool("q2", par[1], 0.2, 0.72), tool("q3", par[2], 0.2, 0.87),
        agent("a4", 0.53, 0.69, "turns"), tool("u1", multi[0], 0.66, 0.57), tool("u2", multi[1], 0.66, 0.72),
        tool("u3", multi[2], 0.66, 0.87),
    ]
    edges = [
        {"a": "a1", "b": "p1", "color": "CRIMSON", "both": True},
        {"a": "a2", "b": "c1", "mode": "c"}, {"a": "c1", "b": "c2", "label": "result feeds", "lsize": 9.5},
        {"a": "c2", "b": "c3", "mode": "c"},
        *[{"a": "a3", "b": f"q{i}", "mode": "c", "color": "CRIMSON"} for i in (1, 2, 3)],
        {"a": "a4", "b": "u1", "mode": "c"}, {"a": "u1", "b": "u2"}, {"a": "u2", "b": "u3"},
    ]
    return {
        "kind": "canvas",
        "kicker": "Interaction patterns",
        "title": "Four ways an agent calls tools, shown with tools SAJHA ships",
        "groups": [
            {"id": "g1", "label": "SINGLE CALL: one tool, keep reasoning", "x": 0.0, "y": 0.0, "w": 0.48, "h": 0.46},
            {"id": "g2", "label": "CHAINED: one result feeds the next", "x": 0.51, "y": 0.0, "w": 0.49, "h": 0.46},
            {"id": "g3", "label": "PARALLEL: independent calls at once", "x": 0.0, "y": 0.5, "w": 0.48, "h": 0.5},
            {"id": "g4", "label": "MULTI-TURN: explore, then refine", "x": 0.51, "y": 0.5, "w": 0.49, "h": 0.5},
        ],
        "texts": [
            {"x": 0.16, "y": 0.32, "w": 0.3, "h": 0.1, "text": "“What is the change from 80 to 100?”", "italic": True,
             "size": 12},
            {"x": 0.37, "y": 0.66, "w": 0.1, "h": 0.25, "text": "plan_execute\nruns them\nside by side", "size": 11},
        ],
        "nodes": nodes,
        "edges": edges,
        "source": "Tool names checked against the live registry at build time (evidence.require_tools). Parallel "
        "steps: docs/architecture/Intelligence Layer.md §6 (plan_execute).",
        "talk": f"Single call: one tool and one result, and the model keeps reasoning. Chained: {chain[0]} finds the "
        f"company, {chain[1]} reads its facts, {chain[2]} computes the growth. Parallel: {par[0]}, {par[1]} and "
        f"{par[2]} together; SAJHA's plan_execute planner runs independent steps side by side. Multi-turn: list the "
        "tables, describe one, then refine the query over several requests.",
    }


def _section1(F: dict[str, Any]) -> list[dict[str, Any]]:
    cat, eras = F["catalog"], F["eras"]
    return [
        {
            "kind": "divider",
            "title": "The Model Context Protocol",
            "sub": "MCP from nothing: what it is, why every AI application should speak it, and how a host, "
            "a client and a server divide the work.",
            "points": ["What MCP is", "Ten principles", "Industry voices", "Primitives", "Host, client, server",
                       "Five steps", "Benefits"],
        },
        _what_is_mcp(eras),
        {
            "kind": "principles",
            "kicker": "Why it matters",
            "title": "Ten principles: why every AI application should use MCP",
            "items": [
                ("Eliminate integration sprawl",
                 "N tools × M applications need N × M connectors; with MCP, N + M."),
                ("Reduce AI development cost",
                 "Build an integration once and reuse it everywhere; over 10,000 public servers already exist."),
                ("Separate the concerns",
                 "Tool developers and AI developers release independently; the tool's schema is the contract."),
                ("Future-proof the stack",
                 "An open standard under the Linux Foundation, used in products from OpenAI, Google and Microsoft."),
                ("Enable agentic workflows",
                 "Agents discover and call tools at run time, through one standard for discovery and results."),
                ("Govern at one point",
                 "Remote servers authorize with OAuth 2.1; a server can enforce per-tool access and argument schemas."),
                ("Accelerate time to value",
                 "Connect to servers for databases, APIs and SaaS instead of writing custom integrations."),
                ("Stay vendor-neutral",
                 "The same servers work with any model or client; change the model and the integrations survive."),
                ("Observe and audit",
                 "Every call is a structured message, so a server can record who called what, with which arguments."),
                ("Democratise integration",
                 "No-code creators let analysts publish their expertise as tools without waiting for engineers."),
            ],
            "source": f"Principles 1, 2, 4: {AAIF}; {BCG}. Principle 6: the MCP authorization specification "
            f"({SPEC}). Principles 3, 5, 7–10 follow from the protocol's design; principle 10 is what MCP Studio "
            "does in SAJHA (Section 3).",
        },
        {
            "kind": "quotes",
            "kicker": "Industry voices",
            "title": "Industry voices on MCP, each traced to its source",
            "quotes": [
                ("People love MCP and we are excited to add support across our products.",
                 "Sam Altman, CEO, OpenAI", "On X, 26 March 2025, as reported by TechCrunch"),
                ("MCP is a good protocol and it's rapidly becoming an open standard for the AI agentic era.",
                 "Demis Hassabis, CEO, Google DeepMind", "On X, 9 April 2025, as reported by TechCrunch"),
                ("The solution is a deceptively simple idea with outsized implications: the Model Context "
                 "Protocol (MCP).", "Boston Consulting Group", "Put AI Agents to Work Faster Using MCP, 1 August 2025"),
                ("There are now more than 10,000 active public MCP servers, covering everything from developer "
                 "tools to Fortune 500 deployments.", "Anthropic",
                 "Donating MCP and establishing the Agentic AI Foundation, 9 December 2025"),
            ],
            "note": "Each quotation was checked against the cited page; one the earlier deck carried could not be "
            "traced to a primary source and was left out.",
            "source": f"Altman: {ALTMAN}. Hassabis: {HASSABIS}. BCG: {BCG}. Anthropic: {AAIF}. Dropped as "
            "unverifiable: a quotation attributed to a security executive's interview, found only in secondary "
            "write-ups.",
        },
        {
            "kind": "table",
            "kicker": "Core primitives",
            "title": "Three primitives: tools act, resources inform, prompts guide",
            "col_w": [1.2, 3.0, 1.5, 3.0],
            "rows": [
                ["Primitive", "What it is", "Who decides", "In SAJHA"],
                ["Tools", "Functions the model can invoke: search, query a database, call an API",
                 "The model", f"{cat['tools']} tools in {cat['groups']} groups, each with a JSON Schema"],
                ["Resources", "Data the server makes readable by URI: files, records, schemas",
                 "The application", "sajha://tools/catalog, sajha://prompts/catalog, sajha://data/{filename}, "
                 "tool schemas"],
                ["Prompts", "Reusable prompt templates with arguments", "The user",
                 f"{F['prompts']} shipped templates in config/prompts, more from the console"],
                ["Utilities", "Completion, logging, progress, cancellation", "Either side",
                 "completion/complete, logging/setLevel, progress and cancellation"],
            ],
            "note": "Tools are the action layer, resources the data layer, prompts the guidance layer; all three "
            "are described with JSON Schema, so a model can discover them.",
            "source": f"Primitives and who controls them: {SPEC}. SAJHA: sajha/core/mcp_handler.py (resources/list, "
            "resources/templates/list, completion/complete, logging/setLevel); tool counts from the registry and "
            "prompt templates counted in config/prompts at build time.",
        },
        {
            "kind": "diagram",
            "kicker": "Architecture",
            "title": "A host runs one client per server; each server wraps capabilities",
            "groups": [{"id": "host", "label": "HOST: the AI application (chat app, IDE, agent)", "x": 0.0, "y": 0.0,
                        "w": 1.0, "h": 0.36}],
            "nodes": [
                {"id": "c1", "text": "MCP client 1", "x": 0.06, "y": 0.13, "w": 0.24, "h": 0.17, "style": "white"},
                {"id": "c2", "text": "MCP client 2", "x": 0.38, "y": 0.13, "w": 0.24, "h": 0.17, "style": "white"},
                {"id": "c3", "text": "MCP client N", "x": 0.70, "y": 0.13, "w": 0.24, "h": 0.17, "style": "white"},
                {"id": "s1", "text": "SAJHA", "sub": "a governed catalog of tools", "x": 0.06, "y": 0.58,
                 "w": 0.24, "h": 0.2, "style": "accent"},
                {"id": "s2", "text": "Search server", "sub": "web and news", "x": 0.38, "y": 0.58, "w": 0.24,
                 "h": 0.2, "style": "box"},
                {"id": "s3", "text": "Database server", "sub": "SQL over your data", "x": 0.70, "y": 0.58,
                 "w": 0.24, "h": 0.2, "style": "box"},
            ],
            "edges": [("c1", "s1", "JSON-RPC 2.0", "both"), ("c2", "s2", "JSON-RPC 2.0", "both"),
                      ("c3", "s3", "JSON-RPC 2.0", "both")],
            "items": [
                ("Host", "The application the user works in; it runs the model and coordinates its clients."),
                ("Client and server", "Each client holds one connection to one server; a server exposes tools, "
                 "resources and prompts."),
            ],
            "items_h": 1.25,
            "source": f"Host, client and server roles: {SPEC} (architecture overview). SAJHA is one such server.",
        },
        {
            "kind": "canvas",
            "kicker": "How AI applications use MCP",
            "title": "Five steps, from discovery to the next tool call",
            "groups": [
                {"id": "c1", "label": "HOST AND MODEL", "x": 0.0, "y": 0.0, "w": 0.3, "h": 1.0, "fill": "PARCH",
                 "line": None},
                {"id": "c2", "label": "MCP CLIENT", "x": 0.35, "y": 0.0, "w": 0.3, "h": 1.0, "fill": "PARCH",
                 "line": None},
                {"id": "c3", "label": "MCP SERVER", "x": 0.7, "y": 0.0, "w": 0.3, "h": 1.0, "fill": "PARCH",
                 "line": None},
            ],
            "nodes": [
                {"id": "d1", "text": "1  Discovery", "sub": "connect; ask for tools/list", "x": 0.38, "y": 0.09,
                 "w": 0.24, "h": 0.13, "style": "white", "size": 13},
                {"id": "d2", "text": "tools with JSON Schemas", "x": 0.73, "y": 0.09, "w": 0.24, "h": 0.13,
                 "style": "white", "size": 13, "bold": False},
                {"id": "s1", "text": "2  Selection", "sub": "the model picks the tool the request needs", "x": 0.03,
                 "y": 0.27, "w": 0.24, "h": 0.14, "style": "soft", "size": 13},
                {"id": "i1", "text": "3  Invocation", "sub": "tools/call as JSON-RPC", "x": 0.38, "y": 0.46,
                 "w": 0.24, "h": 0.13, "style": "white", "size": 13},
                {"id": "i2", "text": "validates and runs it", "x": 0.73, "y": 0.46, "w": 0.24, "h": 0.13,
                 "style": "accent", "size": 13},
                {"id": "r1", "text": "4  Result", "sub": "fed back into the model's context", "x": 0.03, "y": 0.64,
                 "w": 0.24, "h": 0.14, "style": "soft", "size": 13},
                {"id": "t1", "text": "5  Iteration", "sub": "another call, or the answer", "x": 0.03, "y": 0.84,
                 "w": 0.24, "h": 0.13, "style": "dark", "size": 13},
            ],
            "edges": [
                {"a": "d1", "b": "d2", "color": "CRIMSON"},
                {"a": "d2", "b": "s1", "mode": "c"},
                {"a": "s1", "b": "i1", "mode": "c"},
                {"a": "i1", "b": "i2", "color": "CRIMSON"},
                {"a": "i2", "b": "r1", "mode": "c"},
                {"a": "r1", "b": "t1"},
                {"a": "t1", "b": "i1", "ports": ("r", "b"), "via": [(0.5, 0.905)], "dash": True,
                 "label": "chain the next call", "lsize": 10, "lseg": 0, "loff": (0.1, 0.0)},
            ],
            "note": "The model discovers capabilities at run time; no tool knowledge is hard-coded in the application.",
            "source": f"The protocol flow in {SPEC} (lifecycle, tools/list, tools/call). SAJHA's own loop (Ask SAJHA, "
            "Section 7) follows the same five steps.",
            "talk": "Discovery: the host starts a client, the client connects, and the server lists its tools with JSON "
            "Schemas. Selection: the model sees the tools in its context and decides which one the request needs. "
            "Invocation: the model emits a structured call; the client sends it as JSON-RPC; the server validates and "
            "runs it. Result: the server returns a structured result and the host feeds it back into the model's "
            "context. Iteration: the model chains further calls, across tools and servers, until it can answer.",
        },
        {
            "kind": "table",
            "kicker": "Benefits",
            "title": "What MCP gives an application, and what SAJHA adds on top",
            "col_w": [1.9, 3.1, 3.0],
            "rows": [
                ["Benefit", "What it means", "In SAJHA"],
                ["Interoperability", "Any MCP client talks to any MCP server", "Both protocol eras on one endpoint"],
                ["Dynamic discovery", "Agents learn tools at run time, not at compile time",
                 "A caller sees only the tools it may run"],
                ["Transport choice", "Local (stdio) or remote (Streamable HTTP)",
                 "Also legacy SSE and WebSocket"],
                ["Decoupled evolution", "Servers add tools without changing clients",
                 "Tools added while it runs; clients told on push channels"],
                ["Ecosystem scale", "Over 10,000 public servers to connect to",
                 "Federation fronts other servers under its rules"],
                ["One control point", "Authentication and authorization at the server",
                 "Access policy, rules, approvals and a tamper-evident audit"],
            ],
            "source": f"MCP benefits: {SPEC}; server count: {AAIF}. SAJHA column: sajha/web/competitive.py (SAJHA "
            "cells), docs/architecture/Federation.md, docs/architecture/Policy and Audit.md.",
        },
    ]


def _section2(F: dict[str, Any]) -> list[dict[str, Any]]:
    eras, ci, cf = F["eras"], F["ci"], F["conformance"]
    matrix = listing(f"{spec} (suite {suite})" for spec, suite in ci["matrix"])
    single = require_tools(["calc_percentage_change"])
    chain = require_tools(["edgar_company_search", "edgar_company_facts", "calc_percentage_change"])
    par = require_tools(["fred_2yr_treasury", "fred_10yr_treasury", "yahoo_get_quote"])
    multi = require_tools(["duckdb_list_tables", "duckdb_describe_table", "duckdb_sql"])
    return [
        {
            "kind": "divider",
            "title": "MCP integration with AI applications",
            "sub": "Where MCP sits inside an AI application, how an application connects, the transports and "
            "the two eras in use today, and the patterns agents use to call tools.",
            "points": ["Indicative architecture", "Connecting", "Transports", "Two eras", "Conformance",
                       "Interaction patterns", "Beyond list and call", "LLM pipelines"],
        },
        {
            "kind": "diagram",
            "kicker": "Indicative architecture",
            "title": "An MCP-enabled application keeps its AI layer apart from its integrations",
            "groups": [
                {"id": "app", "label": "AI APPLICATION", "x": 0.0, "y": 0.0, "w": 0.44, "h": 1.0},
                {"id": "sa", "label": "MCP SERVER A: SAJHA", "x": 0.54, "y": 0.0, "w": 0.46, "h": 0.47},
                {"id": "sb", "label": "MCP SERVER B: SEARCH", "x": 0.54, "y": 0.53, "w": 0.46, "h": 0.47},
            ],
            "nodes": [
                {"id": "chat", "text": "Chat interface", "x": 0.02, "y": 0.10, "w": 0.19, "h": 0.12, "style": "white"},
                {"id": "orch", "text": "Agent orchestrator", "x": 0.23, "y": 0.10, "w": 0.19, "h": 0.12,
                 "style": "accent"},
                {"id": "llm", "text": "LLM", "x": 0.02, "y": 0.30, "w": 0.19, "h": 0.12, "style": "soft"},
                {"id": "ca", "text": "MCP client A", "x": 0.23, "y": 0.30, "w": 0.19, "h": 0.12, "style": "dark"},
                {"id": "wf", "text": "Workflow engine", "x": 0.02, "y": 0.55, "w": 0.19, "h": 0.12, "style": "soft"},
                {"id": "cb", "text": "MCP client B", "x": 0.23, "y": 0.70, "w": 0.19, "h": 0.12, "style": "dark"},
                {"id": "mem", "text": "Memory and context", "x": 0.02, "y": 0.80, "w": 0.19, "h": 0.12,
                 "style": "white"},
                {"id": "a1", "text": "FRED", "x": 0.555, "y": 0.12, "w": 0.1, "h": 0.12, "style": "white", "size": 11},
                {"id": "a2", "text": "OLAP", "x": 0.665, "y": 0.12, "w": 0.1, "h": 0.12, "style": "white", "size": 11},
                {"id": "a3", "text": "DuckDB", "x": 0.775, "y": 0.12, "w": 0.1, "h": 0.12, "style": "white", "size": 11},
                {"id": "a4", "text": "Yahoo", "x": 0.885, "y": 0.12, "w": 0.1, "h": 0.12, "style": "white", "size": 11},
                {"id": "a5", "text": "Access · policy · audit", "x": 0.555, "y": 0.30, "w": 0.21, "h": 0.12,
                 "style": "accent", "size": 11},
                {"id": "a6", "text": "Databases", "sub": "PostgreSQL, DuckDB", "x": 0.775, "y": 0.29, "w": 0.21,
                 "h": 0.14, "style": "box", "size": 11},
                {"id": "b1", "text": "Search", "x": 0.555, "y": 0.65, "w": 0.1, "h": 0.12, "style": "white", "size": 11},
                {"id": "b2", "text": "Extract", "x": 0.665, "y": 0.65, "w": 0.1, "h": 0.12, "style": "white", "size": 11},
                {"id": "b3", "text": "Crawl", "x": 0.775, "y": 0.65, "w": 0.1, "h": 0.12, "style": "white", "size": 11},
                {"id": "b4", "text": "Research", "x": 0.885, "y": 0.65, "w": 0.1, "h": 0.12, "style": "white",
                 "size": 11},
                {"id": "b5", "text": "External APIs", "sub": "REST, GraphQL", "x": 0.555, "y": 0.83, "w": 0.43,
                 "h": 0.13, "style": "box", "size": 11},
            ],
            "edges": [("chat", "orch", ""), ("chat", "llm", ""), ("orch", "ca", ""), ("llm", "wf", ""),
                      ("wf", "mem", ""), ("ca", "sa", "MCP", "both"), ("cb", "sb", "MCP", "both")],
            "note": "The application connects to several MCP servers at once. Agents, workflows and the model "
            "coordinate through the orchestrator; MCP clients carry all tool traffic.",
            "source": "Illustrative architecture (after the earlier deck). Server A's tool families are real groups "
            "in SAJHA's registry (fred, olap, duckdb, yahoo); policy and audit: docs/architecture/Policy and Audit.md.",
        },
        {
            "kind": "canvas",
            "kicker": "How applications connect",
            "title": "Connect, discover, invoke, iterate: the same four moves in either era",
            "groups": [
                {"id": "gs", "label": f"SESSION ERA (UP TO {eras['handshake'][0]})", "x": 0.0, "y": 0.0, "w": 0.48,
                 "h": 0.86},
                {"id": "gm", "label": f"STATELESS ERA ({eras['modern'][0]})", "x": 0.52, "y": 0.0, "w": 0.48,
                 "h": 0.86},
            ],
            "nodes": [
                {"id": "s1", "text": "initialize", "sub": "negotiates capabilities", "x": 0.03, "y": 0.11, "w": 0.2,
                 "h": 0.16, "style": "accent", "size": 14},
                {"id": "s1b", "text": "Mcp-Session-Id", "sub": "the server opens a session", "x": 0.26, "y": 0.11,
                 "w": 0.19, "h": 0.16, "style": "soft", "size": 13},
                {"id": "s2", "text": "tools/list", "sub": "on the session", "x": 0.03, "y": 0.38, "w": 0.2, "h": 0.14,
                 "style": "white", "size": 14},
                {"id": "s3", "text": "tools/call", "sub": "on the session", "x": 0.03, "y": 0.62, "w": 0.2, "h": 0.14,
                 "style": "white", "size": 14},
                {"id": "s4", "text": "iterate", "sub": "until the model can answer", "x": 0.26, "y": 0.62, "w": 0.19,
                 "h": 0.14, "style": "box", "size": 13},
                {"id": "m1", "text": "server/discover", "sub": "optional: what the server offers", "x": 0.55, "y": 0.11,
                 "w": 0.2, "h": 0.16, "style": "ghost", "size": 14},
                {"id": "m2", "text": "tools/list", "sub": "names its version in _meta", "x": 0.55, "y": 0.38,
                 "w": 0.2, "h": 0.14, "style": "white", "size": 14},
                {"id": "m3", "text": "tools/call", "sub": "every request stands alone", "x": 0.55, "y": 0.62,
                 "w": 0.2, "h": 0.14, "style": "white", "size": 14},
                {"id": "m4", "text": "iterate", "sub": "no session to keep", "x": 0.78, "y": 0.62, "w": 0.19,
                 "h": 0.14, "style": "box", "size": 13},
            ],
            "edges": [
                {"a": "s1", "b": "s1b"}, {"a": "s1", "b": "s2"}, {"a": "s2", "b": "s3"}, {"a": "s3", "b": "s4"},
                {"a": "s4", "b": "s1b", "dash": True, "arrow": False},
                {"a": "m1", "b": "m2", "dash": True}, {"a": "m2", "b": "m3"}, {"a": "m3", "b": "m4"},
            ],
            "items": [f"Official SDKs exist for {listing(F['sdks'])}, with the same pattern in each; one SAJHA endpoint "
                      "serves both eras."],
            "items_h": 0.75,
            "size": 14,
            "source": f"SDK languages: {SDKS}. Eras: sajha.core.mcp_modern (read at build time); "
            "docs/protocol/MCP Protocol Guide.md for how SAJHA recognises each.",
            "talk": "Session era: an initialize handshake negotiates capabilities and opens a session, whose id later "
            "requests carry. Stateless era: every request names its protocol version, and a client may ask "
            "server/discover first. Then, in both, the client asks for the tool catalog, each tool carrying a JSON "
            "Schema, so the model knows exactly what it can call and how; the model emits a structured call, the "
            "client sends it as JSON-RPC and receives a structured result; results return to the model's context and "
            "it chains further calls until it can answer.",
        },
        {
            "kind": "table",
            "kicker": "Transports",
            "title": "Four transports in SAJHA; two of them are the MCP standard",
            "col_w": [1.6, 2.8, 1.8, 2.4],
            "rows": [
                ["Transport", "How it works", "In the MCP spec", "In SAJHA"],
                ["Streamable HTTP", "HTTP POST, answered with JSON or a streamed (SSE) response",
                 "Yes: the remote transport", "POST /mcp, both eras"],
                ["stdio", "The server runs as a child process; messages on stdin and stdout",
                 "Yes: the local transport", "sajha serve --stdio, for desktop clients"],
                ["HTTP + SSE", "A long-lived event stream plus a POST endpoint",
                 "Replaced by Streamable HTTP", "/mcp/sse, for older clients"],
                ["WebSocket", "A full-duplex persistent connection", "No: an extension",
                 "/mcp/ws, for browsers and long-lived links"],
            ],
            "note": "Every transport reaches the same catalog through the same access policy, rules and audit.",
            "source": f"Standard transports: {SPEC} (Transports: stdio and Streamable HTTP; HTTP+SSE was the "
            "2024-11-05 transport). SAJHA: sajha/routes/mcp_routes.py, sajha/routes/ws_routes.py, sajha/cli/stdio.py; "
            "the SAJHA cells of sajha/web/competitive.py.",
        },
        {
            "kind": "table",
            "kicker": "Two eras",
            "title": "Two eras on one endpoint, recognised request by request",
            "col_w": [1.3, 1.7, 3.2, 1.8],
            "rows": [
                ["Era", "Versions", "How SAJHA recognises it", "Who sends it"],
                ["Stateless", listing(eras["modern"]),
                 "The request names its protocol version in _meta (or a non-handshake MCP-Protocol-Version "
                 "header); there is no session.", "Clients on current SDKs"],
                ["Session-based", listing(eras["handshake"]),
                 "An initialize handshake opens a session (Mcp-Session-Id) that later requests carry.",
                 "Most clients in the field"],
                ["Either", "—", "Decided per request on POST /mcp, so one deployment serves a mixed fleet; the "
                 "Python client probes server/discover and adopts the newest.", "Mixed estates"],
            ],
            "note": "Session state, task records, rate limits and OAuth codes go through a shared store, so "
            "either era works across several workers.",
            "source": "sajha/core/mcp_modern.py (MODERN_PROTOCOL_VERSIONS, HANDSHAKE_PROTOCOL_VERSIONS, read at "
            "build time), sajha/core/mcp_2025_11_25.py; GLOSSARY.md 'Era detection', 'Client SDK'.",
        },
        {
            "kind": "stats",
            "kicker": "Evidence",
            "title": f"The official conformance suite: {cf['passed']} checks passed, {cf['failed']} failed",
            "intro": "CI starts a live SAJHA and runs the official MCP conformance suite once per era, "
            f"{matrix}, on every push to {listing(ci['branches'])}. The compliance report records those runs and "
            "two more suites against the same server, for tasks and for the built-in authorization server.",
            "stats": [
                (str(cf["passed"]), "checks passed, over the suites below"),
                (str(cf["failed"]), "checks failed"),
                (str(len(ci["matrix"])), "eras in the CI matrix, each with a pinned suite"),
            ],
            "rows": [["Suite", "Scenarios", "Checks passed", "Failed"]]
            + [[r["suite"], r["scenarios"], str(r["passed"]), str(r["failed"])] for r in cf["rows"]],
            "col_w": [4.2, 1.0, 1.1, 0.8],
            "source": "Results: the table in section 5 of docs/protocol/MCP 2026-07-28 Compliance.md, parsed "
            f"at build time ({cf['legacy']['scenarios']} scenarios on the 2025-11-25 path agree with "
            "docs/protocol/MCP 2025-11-25 Compliance.md). Matrix and branches: .github/workflows/mcp-conformance.yml.",
        },
        _patterns(single, chain, par, multi),
        {
            "kind": "cards",
            "kicker": "Beyond list and call",
            "title": "Streaming, cancellation, input mid-call, long tasks and views",
            "cols": 3,
            "cards": [
                ("STREAMING", "Progress and logs while a tool runs",
                 "A tool reports progress and log lines; a client that asked receives them on the streamed response."),
                ("CANCELLATION", "A client can stop a call",
                 "A cancelled request is visible to the running tool (is_cancelled), which can stop early."),
                ("MRTR", "Multi Round-Trip Requests",
                 "A stateless server asks for input mid-call by answering input_required; the client retries "
                 "with the answers."),
                ("TASKS", "Long calls become tasks",
                 "A task-capable tool returns a task id; the client polls tasks/get, answers input or cancels."),
                ("MCP APPS", "A tool can ship its own view",
                 "An HTML view (ui://) rendered beside the result, such as calc_loan_amortization's schedule chart."),
                ("HEADERS", "Routing without reading the body",
                 "Mcp-Method, Mcp-Name and Mcp-Param-* headers let a gateway route 2026-07-28 traffic."),
            ],
            "source": "GLOSSARY.md §3 (MRTR, Tasks extension, MCP Apps, Mcp-Param-{Name}); sajha/core/mcp_mrtr.py, "
            "mcp_tasks.py, mcp_apps.py, mcp_tool_context.py; docs/protocol/MCP 2026-07-28 Compliance.md §4.",
        },
        {
            "kind": "diagram",
            "kicker": "MCP in LLM pipelines",
            "title": "The model decides when to call a tool; MCP carries the call and the result",
            "nodes": [
                {"id": "q", "text": "User query", "x": 0.0, "y": 0.0, "w": 0.15, "h": 0.24, "style": "white"},
                {"id": "llm", "text": "LLM agent", "x": 0.215, "y": 0.0, "w": 0.15, "h": 0.24, "style": "accent"},
                {"id": "cl", "text": "MCP client", "x": 0.43, "y": 0.0, "w": 0.15, "h": 0.24, "style": "dark"},
                {"id": "sv", "text": "MCP server", "sub": "SAJHA", "x": 0.645, "y": 0.0, "w": 0.15, "h": 0.24,
                 "style": "dark"},
                {"id": "ext", "text": "API · database · file", "x": 0.86, "y": 0.0, "w": 0.14, "h": 0.24,
                 "style": "box"},
                {"id": "res", "text": "Structured result", "x": 0.645, "y": 0.5, "w": 0.15, "h": 0.22,
                 "style": "soft"},
                {"id": "fin", "text": "LLM → final answer", "x": 0.215, "y": 0.5, "w": 0.15, "h": 0.22,
                 "style": "accent"},
            ],
            "edges": [("q", "llm", ""), ("llm", "cl", "tool call"), ("cl", "sv", "JSON-RPC"), ("sv", "ext", ""),
                      ("sv", "res", "result"), ("res", "fin", "")],
            "items": [
                "Tool schemas go into the model's context when the prompt is built; the model, not hard-coded logic, "
                "decides when and which tool to call.",
                "Results come back as structured data, not raw HTML; agent frameworks with an MCP client plug in "
                "the same way.",
            ],
            "items_h": 1.5,
            "source": f"The tool-use loop in {SPEC} (tools). SAJHA's own instance of this pipeline is Ask SAJHA "
            "(sajha/ai/intelligence.py), captured in Section 7.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _section1(F) + _section2(F)
