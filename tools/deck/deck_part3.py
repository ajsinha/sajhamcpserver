"""
The deck, as data. Sections 4 and 5: agent and workflow integration (agents, a worked
analysis, several agents on one server, workflows, extending the server, hot reload, and
how a tool is made, step by step), and data and analytics (search, DuckDB and OLAP, the
financial calculators, the connector guard, and search combined with analytics).

Every tool named on these slides is checked against the live registry while the deck is
built; the worked workflows are marked illustrative.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from evidence import require_tools, short_description
from prose import listing


def _section4(F: dict[str, Any]) -> list[dict[str, Any]]:
    wf = F["workflows"]
    risk = require_tools(["fred_fed_funds_rate", "fred_2yr_treasury", "fred_10yr_treasury", "duckdb_sql",
                          "olap_pivot_table", "tavily_news_search", "calc_bond_price"])
    return [
        {
            "kind": "divider",
            "num": "4",
            "title": "Agent and workflow integration",
            "sub": "How agents use SAJHA, alone and together; how a schedule or an event runs a governed graph of "
            "steps; and how the server is extended while it runs.",
            "points": ["Agent architecture", "A worked analysis", "Several agents", "Workflows", "Extending",
                       "Hot reload", "Making a tool, step by step"],
        },
        {
            "kind": "diagram",
            "kicker": "Agent architecture",
            "title": "The agent reasons; SAJHA executes, authorizes and records",
            "groups": [
                {"id": "rt", "label": "AI AGENT RUNTIME", "x": 0.0, "y": 0.0, "w": 0.36, "h": 0.62},
                {"id": "sv", "label": "SAJHA MCP SERVER", "x": 0.52, "y": 0.0, "w": 0.48, "h": 0.62},
            ],
            "nodes": [
                {"id": "llm", "text": "LLM", "x": 0.03, "y": 0.13, "w": 0.3, "h": 0.12, "style": "soft"},
                {"id": "orc", "text": "Orchestrator", "sub": "multi-step reasoning, retries", "x": 0.03, "y": 0.29,
                 "w": 0.3, "h": 0.13, "style": "accent"},
                {"id": "cl", "text": "MCP client", "x": 0.03, "y": 0.46, "w": 0.3, "h": 0.12, "style": "dark"},
                {"id": "gov", "text": "Access · policy · audit", "x": 0.55, "y": 0.46, "w": 0.42, "h": 0.12,
                 "style": "accent"},
                {"id": "t1", "text": "FRED", "x": 0.55, "y": 0.13, "w": 0.13, "h": 0.12, "style": "white", "size": 11},
                {"id": "t2", "text": "EDGAR", "x": 0.695, "y": 0.13, "w": 0.13, "h": 0.12, "style": "white", "size": 11},
                {"id": "t3", "text": "Central banks", "x": 0.84, "y": 0.13, "w": 0.13, "h": 0.12, "style": "white",
                 "size": 11},
                {"id": "t4", "text": "DuckDB", "x": 0.55, "y": 0.29, "w": 0.13, "h": 0.12, "style": "white", "size": 11},
                {"id": "t5", "text": "OLAP", "x": 0.695, "y": 0.29, "w": 0.13, "h": 0.12, "style": "white", "size": 11},
                {"id": "t6", "text": "Tavily", "x": 0.84, "y": 0.29, "w": 0.13, "h": 0.12, "style": "white", "size": 11},
                {"id": "data", "text": "Databases and lake", "x": 0.52, "y": 0.78, "w": 0.22, "h": 0.14},
                {"id": "web", "text": "Public APIs and the web", "x": 0.78, "y": 0.78, "w": 0.22, "h": 0.14},
            ],
            "edges": [("llm", "orc", ""), ("orc", "cl", ""), ("cl", "gov", "MCP", "both")],
            "items": [
                "The agent lists tools at start (tools/list) and puts their schemas in the model's prompt; the "
                "orchestrator handles multi-step reasoning and retries.",
                "SAJHA handles execution, authentication, policy and records: a clean separation of concerns.",
            ],
            "items_h": 1.0,
            "source": "Tool families shown are live groups (fred, edgar, the central-bank groups, duckdb, olap, tavily). "
            "Governance path: sajha/tools/base_mcp_tool.py execute_with_tracking. After the earlier deck's agent slide.",
        },
        {
            "kind": "table",
            "kicker": "Illustrative workflow",
            "title": "A worked analysis: interest-rate exposure, one tool at a time",
            "intro": "Illustrative. “How exposed is our Treasury portfolio to a move in rates?” An agent might chain "
            "these real tools; the holdings table is your own data in DuckDB.",
            "col_w": [0.5, 2.6, 2.0, 2.6],
            "rows": [
                ["#", "Agent action", "SAJHA tool", "Output"],
                ["1", "Fetch the policy rate", risk[0], "Rate and its history"],
                ["2", "Fetch the 2-year and 10-year yields", f"{risk[1]}, {risk[2]}", "The curve's short and long end"],
                ["3", "Read portfolio holdings", risk[3], "Positions, coupons, maturities"],
                ["4", "Bucket exposure by maturity", risk[4], "Exposure per bucket"],
                ["5", "Reprice a bond after +100 bp", risk[6], "Price change per position"],
                ["6", "Search for central-bank guidance", risk[5], "Recent statements, with links"],
                ["7", "Synthesise", "the model", "Exposure summary, citing each call"],
            ],
            "note": "Each output becomes context for the next step; the model chooses the path from what it sees. "
            "Section 6 shows a real run, captured when this deck was built.",
            "source": "Illustrative: no run is claimed. Every tool name is checked against the live registry at build "
            "time (evidence.require_tools). After the earlier deck's risk-analysis table, with names that exist.",
        },
        {
            "kind": "diagram",
            "kicker": "Multi-agent coordination",
            "title": "Several agents share one server, each with its own identity and rights",
            "nodes": [
                {"id": "ra", "text": "Research agent", "sub": "API key: tavily_*, edgar_*, fed_*", "x": 0.0,
                 "y": 0.0, "w": 0.3, "h": 0.22},
                {"id": "aa", "text": "Analytics agent", "sub": "API key: duckdb_*, olap_*, calc_*", "x": 0.35,
                 "y": 0.0, "w": 0.3, "h": 0.22},
                {"id": "pa", "text": "Reporting agent", "sub": "role: user, prompts, Ask SAJHA", "x": 0.7, "y": 0.0,
                 "w": 0.3, "h": 0.22},
                {"id": "s", "text": "SAJHA MCP server", "sub": "one catalog · one policy · one audit", "x": 0.0,
                 "y": 0.42, "w": 1.0, "h": 0.2, "style": "accent"},
            ],
            "edges": [("ra", "s", "MCP"), ("aa", "s", "MCP"), ("pa", "s", "MCP")],
            "items": [
                "Each agent gets its own credentials (an API key in allowlist mode, or a role), so least privilege is "
                "enforced per agent and the audit names which agent called what.",
                "Agents hand work to each other over A2A (/.well-known/agent.json, POST /a2a); MCP carries tool access. "
                "Several workers with a shared state store serve more agents without changing the server.",
            ],
            "items_h": 1.45,
            "source": "Tool access per API key: sajha/auth/access.py apikey_policy; A2A: sajha/routes/a2a_routes.py; "
            "workers: docs/architecture/Scaling and State.md. The key patterns are illustrative.",
        },
        {
            "kind": "cards",
            "kicker": "Workflows",
            "title": "A schedule or an event runs a governed graph of steps",
            "cols": 3,
            "cards": [
                ("STEPS", "Tools, composites, questions, decisions", f"Step kinds: {listing(wf['steps'])}."),
                ("TRIGGERS", "Started by time or by events",
                 f"{listing(t if t != 'cron' else 'cron schedules' for t in wf['triggers'])}, or by hand; one fire "
                 "per slot across workers."),
                ("DURABLE", "A run survives a crash", "Every step is stored; another worker takes over a dead "
                 "worker's run and re-runs only idempotent steps."),
                ("AS THE OWNER", "Runs with the owner's rights", "Steps run with the owner's current roles, seen by "
                 "policy, usage and audit as that caller."),
                ("RE-RUN", "From the step that failed", "Finished steps are reused; a run can be cancelled."),
                ("PUBLISHED", "A workflow can be a tool", "An administrator can publish it to the catalog, callable "
                 "from both eras."),
            ],
            "source": "sajha/workflows/model.py STEP_KINDS and TRIGGER_TYPES, read at build time; "
            "docs/architecture/Workflows.md.",
        },
        {
            "kind": "split",
            "kicker": "Extending the server",
            "title": "Two ways to add a tool, and agents cannot tell them apart",
            "left": {
                "head": "No code: MCP Studio",
                "items": [
                    "REST, database query, script, Power BI, SharePoint, LiveLink and OLAP creators, or describe the "
                    "tool in a sentence.",
                    "Import an OpenAPI or GraphQL description; connect a database.",
                    "Deploy with one click; the tool is live without a restart.",
                ],
            },
            "right": {
                "head": "Full code: a Python tool",
                "items": [
                    "Subclass BaseMCPTool and implement execute(); declare the input schema.",
                    "The whole Python ecosystem: numpy, pandas, scipy.",
                    "A JSON config in config/tools loads it; a plugin (plugin.json and tools/) packages several.",
                ],
            },
            "note": "Both produce ordinary MCP tools with schemas, governed and audited the same way.",
            "source": "sajha/tools/base_mcp_tool.py (BaseMCPTool); sajha/core/plugins.py (plugin.json manifest, "
            "discover, load_plugin; /api/plugins in sajha/routes/ops_routes.py); Studio pages in "
            "sajha/routes/studio_routes.py.",
        },
        {
            "kind": "bullets",
            "kicker": "Hot reload",
            "title": "Tools, rules and permissions change without a restart",
            "items": [
                ("Tools", "A JSON config added or changed in config/tools is picked up by the registry's file monitor; "
                 "with an object store, its poller does the same."),
                ("Studio and imports", "Deploying from Studio, an import or a connector registers the tool in the "
                 "running server at once."),
                ("Policies", "Policy files reload when they change."),
                ("Users, roles and keys", "Changed in the console; the next request uses them, because the user is "
                 "reloaded on every request."),
                ("Clients notice", "Clients on SSE or WebSocket, and 2026-07-28 clients through subscriptions/listen, "
                 "receive list-changed notifications; Ask SAJHA's shortlist sees a new tool without a reload."),
            ],
            "source": "sajha/tools/tools_registry.py (start_monitoring, _monitor_files); sajha/core/reload_manager.py "
            "(object-store polling); sajha/policy/loader.py (policy.reload_seconds); sajha/core/mcp_handler.py (listChanged on push channels; subscriptions/listen in mcp_modern); docs/security/Security "
            "Model.md §1 (user reloaded per request); docs/architecture/Intelligence Layer.md (tool index sync).",
        },
        {
            "kind": "mono",
            "kicker": "Step by step",
            "title": "Tool creation: MCP Studio, zero code",
            "band": "Developer or admin  →  MCP Studio",
            "lines": [
                "1. Open /studio and choose a creator",
                "   └─ Python | REST | DB query | Script | OLAP | Power BI |",
                "      SharePoint | LiveLink | Describe | Import an API",
                "2. Fill the form: name, parameters, source",
                '   ├─ name: "fx_rate"',
                '   ├─ parameters: { "pair": "string" }',
                "   └─ source: URL template, SQL, code or script",
                "3. Preview: the JSON Schema is generated",
                "   └─ inputSchema with types and required fields",
                "4. Deploy",
                "   ├─ Config written under config/tools",
                "   ├─ Registered in the running server",
                "   └─ Code and scripts will run in the sandbox",
                "5. Any MCP client sees it in tools/list,",
                "   under its caller's access policy",
            ],
            "source": "sajha/routes/studio_routes.py (pages, /preview and /deploy actions per creator); "
            "docs/studio/MCP Studio User Guide.md. The tool name and parameters are illustrative.",
        },
        {
            "kind": "mono",
            "kicker": "Step by step",
            "title": "Tool creation: a Python tool, full code",
            "band": "Developer  →  SAJHA tools registry",
            "lines": [
                "1. Write the class",
                "   ├─ class FxRateTool(BaseMCPTool):",
                "   ├─     def execute(self, arguments): ...",
                "   └─ input schema with types, ranges, required",
                "2. Describe it: a JSON config in config/tools",
                "   └─ name, description, implementation class, cache_ttl",
                "3. Or package several as a plugin",
                "   ├─ config/plugins/my-tools/plugin.json",
                "   └─ tools/ with configs or classes; a checksum",
                "4. Test",
                "   ├─ Tool tests with recorded HTTP cassettes",
                "   └─ The schema linter",
                "5. Deploy: the registry loads the config;",
                "   the tool appears in tools/list",
            ],
            "source": "sajha/tools/base_mcp_tool.py; sajha/tools/tools_registry.py; sajha/core/plugins.py (manifest "
            "format in its docstring); docs/architecture/Tool Quality.md (tests, cassettes, lint). The class name is "
            "illustrative.",
        },
    ]


def _pairs(tools: list[tuple[str, str]]) -> list[list[str]]:
    """Two (tool, description) pairs per row, filled down the left column first."""
    half = (len(tools) + 1) // 2
    tools = [(n, short_description(d)) for n, d in tools]
    left, right = tools[:half], tools[half:] + [("", "")] * (2 * half - len(tools))
    return [["Tool", "What it does", "Tool", "What it does"]] + [[a, b, c, d] for (a, b), (c, d) in zip(left, right)]


def _section5(F: dict[str, Any]) -> list[dict[str, Any]]:
    search = [(n, d) for n, d in F["search_tools"] if n.startswith(("tavily_", "wiki_", "crawl_", "extract_"))]
    ir = [n for n, _d in F["search_tools"] if n.startswith("ir_")]
    analytics = F["analytics_tools"]
    calc = F["calc_tools"]
    combo = require_tools(["tavily_news_search", "duckdb_sql", "olap_pivot_table", "calc_correlation"])
    return [
        {
            "kind": "divider",
            "num": "5",
            "title": "Data and analytics integration",
            "sub": "Search for what the world says, SQL and pivots for what your data says, calculators for the "
            "arithmetic, and guards so that none of it can write.",
            "points": ["Search and the web", "DuckDB and OLAP", "Financial calculators", "The connector guard",
                       "Search plus analytics"],
        },
        {
            "kind": "table",
            "kicker": "Search and the web",
            "title": f"{len(search)} search, extraction and crawling tools",
            "col_w": [1.55, 2.4, 1.55, 2.4],
            "rows": _pairs(search),
            "note": "Results come back as structured text for a model, not raw HTML; Tavily calls need a Tavily key. "
            f"For filings, {len(ir)} investor-relations tools (ir_*) find reports and presentations.",
            "source": "Names and first sentences of the descriptions from the live registry at build time "
            "(evidence.describe_tools, cut by evidence.short_description over tavily_, wiki_, crawl_, extract_; ir_ counted).",
        },
        {
            "kind": "table",
            "kicker": "DuckDB and OLAP",
            "title": "SQL over your files, pivots and statistics, read-only by construction",
            "col_w": [1.55, 2.4, 1.55, 2.4],
            "rows": _pairs(analytics),
            "note": "duckdb_sql accepts one read-only statement and cannot read arbitrary files or URLs; the OLAP "
            "tools bind values instead of pasting them into SQL.",
            "source": "Names and descriptions from the live registry at build time (duckdb_, olap_, sqlselect_). "
            "Guards: the 'Fixes since' table of docs/security/Security Model.md (duckdb_sql, OLAP SQL injection).",
        },
        {
            "kind": "table",
            "kicker": "Financial calculators",
            "title": f"{len(calc)} calculators: pure arithmetic, no network, confidence 1.0",
            "col_w": [1.55, 2.4, 1.55, 2.4],
            "rows": _pairs(calc),
            "source": "Names and descriptions from the live registry at build time (calc_). Confidence: "
            "sajha.core.composition.get_tool_confidence for the calc group, "
            f"{F['confidence']['calc']:.1f}.",
        },
        {
            "kind": "diagram",
            "kicker": "The connector guard",
            "title": "A query to your database passes three read-only checks",
            "items_h": 1.9,
            "nodes": [
                {"id": "q", "text": "Tool call", "sub": "query or curated view", "x": 0.0, "y": 0.08, "w": 0.15,
                 "h": 0.7, "style": "white"},
                {"id": "g1", "text": "1  Statement guard", "sub": "one SELECT; table allowlist; no procedures",
                 "x": 0.205, "y": 0.08, "w": 0.18, "h": 0.7, "style": "accent"},
                {"id": "g2", "text": "2  Read-only session", "sub": "the connection itself refuses writes",
                 "x": 0.44, "y": 0.08, "w": 0.18, "h": 0.7, "style": "accent"},
                {"id": "g3", "text": "3  The login's grants", "sub": "the database's own control",
                 "x": 0.675, "y": 0.08, "w": 0.18, "h": 0.7, "style": "dark"},
                {"id": "db", "text": "Your database", "x": 0.91, "y": 0.08, "w": 0.09, "h": 0.7, "style": "box",
                 "size": 11},
            ],
            "edges": [("q", "g1", ""), ("g1", "g2", ""), ("g2", "g3", ""), ("g3", "db", "")],
            "items": [
                ("Limits", "Row, byte and time limits on every query; masking per column."),
                ("Per-user sign-in", f"{listing(F['connectors']['per_user'])} can run as each user, so the database "
                 "applies that user's own rights."),
                ("Honest limit", "SAJHA's guard works on query text it can analyse; database-native grants, views "
                 "and masking are stronger and should back anything sensitive."),
            ],
                        "source": "docs/architecture/Data Connectors.md (the guard, limits, masking, §14 'Limits of this design'); "
            "sajha/connectors/model.py PER_USER_KINDS, read at build time.",
        },
        {
            "kind": "steps",
            "kicker": "Search plus analytics",
            "title": "One session blends outside intelligence with inside data",
            "intro": "Illustrative. “What is the market saying about credit spreads, and how are we positioned?”",
            "head_w": 2.6,
            "head_font": "Consolas",
            "head_size": 13,
            "steps": [
                (combo[0], "News on the credit-spread outlook: the market's view, with links."),
                (combo[1], "SELECT sector, rating, spread, duration FROM portfolio: our positions."),
                (combo[2], "Exposure by sector and rating: where we are concentrated."),
                (combo[3], "How our spreads have moved with the market's: correlation of two series."),
                ("the model", "A synthesis that cites each call, with SAJHA's confidence attached."),
            ],
            "note": "Same server, same identity, same rules and the same audit for every step.",
            "source": "Illustrative: no run is claimed. Tool names checked against the live registry at build time. "
            "After the earlier deck's combined-workflow slide.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _section4(F) + _section5(F)
