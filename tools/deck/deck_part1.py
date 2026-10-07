"""
The deck, as data. Parts 1 and 2: why agents stall at the tools layer, and the
vocabulary from nothing.

One deck split across four modules only to keep each file readable; read them in order
(see GUIDE.md). Every number comes from ``F``, the facts ``evidence`` derived at build time.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from prose import listing


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    cat, eras, conf = F["catalog"], F["eras"], F["confidence"]
    n_versions = len(eras["modern"]) + len(eras["handshake"])
    top = cat["top"]
    catalog_src = (
        f"Tool and group counts: the tools registry loaded from config/tools when the deck was built "
        f"(sajha.tools.tools_registry.ToolsRegistry; counted by sajha.web.help_catalog.live_tool_groups, "
        f"the function the landing page and /help/tools use): {cat['tools']} tools in {cat['groups']} groups, "
        f"{cat['errors']} load errors."
    )
    return [
        # ── Part 1 ─────────────────────────────────────────────────────
        {
            "kind": "divider",
            "num": "1",
            "title": "Why agents stall at the tools layer",
            "sub": "An agent can reason about anything and act on nothing until somebody connects it to "
            "the systems that hold the data. This part says where that connection breaks in most "
            "organisations, and what SAJHA is in one sentence: one shared, governed catalog of "
            "tools that every agent uses.",
            "points": [
                "An agent is only as useful as its tools",
                "Four failures that appear in production",
                "The questions this deck answers",
                "SAJHA, in one slide",
            ],
        },
        {
            "kind": "bullets",
            "kicker": "The situation",
            "title": "An agent is only as useful as the tools it can reach",
            "intro": "Here a tool means one thing an agent can do outside itself: fetch a price, read a "
            "filing, query a table, compute a net present value. Three teams in one firm want agents "
            "that do these things this quarter.",
            "items": [
                (
                    "Each team wires its own tools",
                    "The research desk writes a market-data wrapper, risk writes another, operations a "
                    "third: each with its own error handling, its own cache and its own idea of a ticker.",
                ),
                (
                    "Each wrapper holds its own credentials",
                    "API keys sit in notebooks, environment files and agent settings. Revoking one key "
                    "means finding every copy of it.",
                ),
                (
                    "Nobody can say who called what",
                    "When a number in a report is questioned, there is no record of which agent called "
                    "which tool, with which arguments, on whose behalf.",
                ),
                (
                    "Every new agent framework starts again",
                    "The wrappers were written for one framework; the next one the firm adopts cannot use them.",
                ),
            ],
            "note": "The difficulty is not intelligence. It is plumbing nobody owns, and plumbing nobody "
            "owns is plumbing nobody governs.",
            "source": "The problem SAJHA states in README.md (one governed catalog of tools that every "
            "client and agent shares). No figures on this slide.",
        },
        {
            "kind": "cards",
            "kicker": "Where it breaks",
            "title": "Four failures that appear only once agents are in production",
            "cols": 2,
            "cards": [
                (
                    "DUPLICATION",
                    "The same tool, built five times",
                    "Five wrappers around one data vendor drift apart: different defaults, different "
                    "retries, different bugs. Fixing one fixes one.",
                ),
                (
                    "CREDENTIALS",
                    "Secrets spread to every agent",
                    "Every agent that calls a vendor carries the vendor's key. An agent that is "
                    "compromised, or merely misconfigured, leaks it.",
                ),
                (
                    "ACCOUNTABILITY",
                    "No record that survives a question",
                    "Logs live in each agent's process, if anywhere. They can be edited, and they do not "
                    "say whom the agent was acting for.",
                ),
                (
                    "CONTROL",
                    "No single place to say no",
                    "There is no point at which a rule such as “no anonymous writes” or “approval above "
                    "10,000” can be enforced before the call runs.",
                ),
            ],
            "source": "The failure modes SAJHA's design answers: docs/security/Security Model.md (tool "
            "access, audit logging), docs/architecture/Policy and Audit.md. The 10,000 threshold is the "
            "shipped example policy config/policies/example-business-hours.yaml.",
        },
        {
            "kind": "table",
            "kicker": "The reader's questions",
            "title": "The questions this deck answers, in the order they are asked",
            "col_w": [3.2, 1.6, 0.6],
            "rows": [
                ["Question", "Usually asked by", "Part"],
                ["What is SAJHA, and which words do I need to discuss it?", "Everyone", "1–2"],
                ["Show me one question answered, with its sources", "A desk head, an analyst", "3"],
                ["Will it work with the clients we already use?", "An engineer", "4"],
                ["Can my security team sign it off?", "A CISO, an auditor", "5"],
                ["Which tools does it have, and how do I add mine?", "A platform owner", "6"],
                ["Does it need a language model, and whose?", "An architect", "7"],
                ["How do we run it, at what scale?", "Operations", "8"],
                ["Why this, rather than a gateway or a hosted platform?", "A buyer", "9"],
            ],
            "source": "The structure of this deck (tools/deck/sajha_deck.py, PARTS). No figures.",
        },
        {
            "kind": "stats",
            "kicker": "SAJHA in one slide",
            "title": "One catalog of tools, one address, one set of rules",
            "intro": "SAJHA (साझा, Hindi for “shared”) is a server that holds the tools an organisation's "
            "agents use, serves them to any agent through one address, and applies one set of "
            "identities, permissions, rules and records to every call, whoever makes it.",
            "stats": [
                (str(cat["tools"]), "tools in the catalog when this deck was built"),
                (str(cat["groups"]), f"tool groups, the largest {top[0][0]} ({top[0][1]} tools)"),
                (str(n_versions), "versions of the tool-calling protocol served on one address (Part 4)"),
                (str(F["tests"]), "automated tests in the suite"),
            ],
            "items": [
                (
                    "Shared",
                    "One catalog for every team and every agent framework: a tool is built once, governed "
                    "once and recorded once.",
                ),
                (
                    "Governed",
                    "Every call, from any client or from SAJHA's own assistant, passes the same access "
                    "check, the same rules and the same tamper-evident record.",
                ),
                (
                    "Self-hosted",
                    "One Python process on a laptop or several workers on Kubernetes; data leaves your "
                    "infrastructure only when a tool sends it.",
                ),
            ],
            "source": catalog_src
            + f" Protocol versions: sajha.core.mcp_modern MODERN_PROTOCOL_VERSIONS ({listing(eras['modern'])})"
            f" and HANDSHAKE_PROTOCOL_VERSIONS ({listing(eras['handshake'])}). Tests: pytest --collect-only "
            "over tests and clientsdk/tests, run by tools/deck/evidence.py while building.",
        },
        # ── Part 2 ─────────────────────────────────────────────────────
        {
            "kind": "divider",
            "num": "2",
            "title": "The vocabulary, from nothing",
            "sub": "Fourteen words carry the rest of the deck. Each is defined here before it is used, in "
            "plain terms first and then as SAJHA implements it. The definitions are the glossary's "
            "(GLOSSARY.md), shortened.",
            "points": [
                "Tool, schema, tool group, catalog",
                "MCP, client, server, transport, era",
                "Composition, confidence, policy, audit chain",
                "The path every call follows",
            ],
        },
        {
            "kind": "table",
            "kicker": "Words 1–4",
            "title": "A tool is a named function with a contract; the schema is the contract",
            "col_w": [1.1, 3.3, 2.6],
            "rows": [
                ["Word", "What it means", "In SAJHA"],
                [
                    "Tool",
                    "A function an agent can call: a name, a description a model reads to decide when to "
                    "use it, and the arguments it takes.",
                    f"One JSON file per tool in config/tools; {cat['tools']} load at start-up.",
                ],
                [
                    "Schema",
                    "The contract for a tool's arguments and its result, in JSON Schema: types, required "
                    "fields, allowed values and ranges.",
                    "Arguments are validated against it before the tool runs; a mismatch is refused, "
                    "not passed on.",
                ],
                [
                    "Tool group",
                    "Tools that share a name prefix and usually a data provider: fred_*, edgar_*, calc_*.",
                    f"{cat['groups']} groups; the largest are {listing(f'{g} ({n})' for g, n, _ in top[:3])}.",
                ],
                [
                    "Catalog",
                    "Every tool a server has loaded, with its schema, for a caller to discover.",
                    "Each caller sees only the tools it may use (Part 5).",
                ],
            ],
            "source": "GLOSSARY.md §6 (Tool, Input Schema, Tool group, Tool configuration). "
            + catalog_src
            + " Validation: BaseMCPTool.execute_with_tracking (sajha/tools/base_mcp_tool.py).",
        },
        {
            "kind": "table",
            "kicker": "Words 5–9",
            "title": "MCP is how agents find and call tools; a client is what speaks it",
            "col_w": [1.1, 3.6, 2.3],
            "rows": [
                ["Word", "What it means", "In SAJHA"],
                [
                    "MCP",
                    "Model Context Protocol: the open standard by which an application lists a server's "
                    "tools (tools/list) and calls one (tools/call), as JSON messages.",
                    "SAJHA is an MCP server; every tool in its catalog is an MCP tool.",
                ],
                [
                    "Client",
                    "The program that speaks MCP for an agent or a person: a desktop assistant, an IDE, an "
                    "agent framework, a script.",
                    "Any MCP client; SAJHA also ships a Python client and a command line.",
                ],
                ["Server", "The program that answers: it holds the tools and runs them.", "SAJHA, at /mcp."],
                [
                    "Transport",
                    "How the messages travel: HTTP request and response, a long-lived stream (SSE or "
                    "WebSocket), or a local pipe between two processes (stdio).",
                    "Four transports (Part 4).",
                ],
                [
                    "Era",
                    "MCP has two generations in use: revisions up to "
                    f"{eras['handshake'][0]}, where a client first opens a session, and the stateless "
                    f"{eras['modern'][0]}, where every request stands alone.",
                    "Both, on the same address, recognised request by request.",
                ],
            ],
            "source": "GLOSSARY.md §2 (MCP, Tool, Era detection) and §4 (Streamable HTTP, stdio transport). "
            "Era versions: sajha.core.mcp_modern MODERN_PROTOCOL_VERSIONS and HANDSHAKE_PROTOCOL_VERSIONS.",
        },
        {
            "kind": "table",
            "kicker": "Words 10–14",
            "title": "Composition, confidence and policy make a catalog fit to trust",
            "col_w": [1.25, 3.5, 2.25],
            "rows": [
                ["Word", "What it means", "In SAJHA"],
                [
                    "Composition",
                    "Calling tools in sequence or in parallel, the output of one feeding the next, to make "
                    "a larger tool or one answer.",
                    "Composite tools, workflows, and Ask SAJHA's tool-use loop.",
                ],
                [
                    "Confidence",
                    f"How far a result can be relied on, from 0 to 1: {conf['calc']:.2f} for a calculator, "
                    f"{conf['web']:.2f} for a web fetch. It falls as steps chain.",
                    "Set per tool group in code and chained by an entropy guard; never chosen by a model.",
                ],
                [
                    "Policy",
                    "Declarative rules evaluated before a call runs: allow, deny, require approval, "
                    "constrain arguments, limit the rate, redact the output.",
                    "YAML files in config/policies, applied on every path a tool runs through.",
                ],
                [
                    "Audit chain",
                    "A log in which each record carries the hash of the one before, with signed "
                    "checkpoints, so an edit, deletion or insertion is detectable.",
                    "Every audit record and every policy decision.",
                ],
                [
                    "Ask SAJHA",
                    "SAJHA's own assistant: a question in; an answer, its sources and a confidence out.",
                    "/ask in the browser, POST /api/ai/ask, or the sajha_ask tool.",
                ],
            ],
            "source": "GLOSSARY.md §5 (Policy engine), §7 (Composite tool, EntropyGuard, Confidence score), "
            "§9. Confidences: sajha.core.composition.get_tool_confidence('calc_…') and ('web_…') "
            "evaluated at build time.",
        },
        {
            "kind": "flow",
            "kicker": "One sentence that uses every word",
            "title": "Every call follows the same path, whoever makes it",
            "box_h": 2.55,
            "steps": [
                ("Client", "Any MCP client, the Python client, the browser, a workflow or Ask SAJHA"),
                ("Transport and era", "HTTP, SSE, WebSocket or stdio; either era, recognised per request"),
                ("Identity and access", "Who is calling, and may they see and run this tool?"),
                ("Policy", "Deny, approve, constrain, rate-limit or redact"),
                ("Tool", "Arguments checked against the schema; cache, circuit breaker, metrics"),
                ("Audit", "One hash-chained record, exportable to a SIEM"),
            ],
            "items": [
                "The single place is BaseMCPTool.execute_with_tracking: MCP in both eras, stdio, "
                "WebSocket, REST, agent-to-agent (A2A) calls, the browser playground, Ask SAJHA, "
                "asynchronous tasks and tools fronted from other MCP servers all run a tool through it, "
                "so a rule written once applies to all of them.",
                "A SIEM is the security team's log platform (Splunk, Datadog, a syslog collector); "
                "Part 5 shows the export.",
            ],
            "source": "sajha/tools/base_mcp_tool.py (execute_with_tracking); the list of paths is the "
            "CHANGELOG entry 'Policy engine, tamper-evident audit and SIEM export' and "
            "docs/architecture/Policy and Audit.md.",
        },
    ]
