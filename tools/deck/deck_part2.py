"""
The deck, as data. Section 3: the SAJHA MCP server itself -- what it is, what is in the
box, how tools are made, how it is built, who may call it and how each caller proves who
it is (step by step), the rules and the record, and where it runs.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from evidence import ROOT, SourceChanged
from prose import js, listing, plain, wrap

# Tool groups, by what they are for. A group the live registry has and this map does not
# fails the build, so a new provider cannot silently drop off the slide.
CATEGORIES = [
    ("Markets and equities", ("fmp", "openbb", "av", "yf", "yahoo", "cg"), "Quotes, statements, crypto, indices"),
    ("Central banks", ("fred", "fed", "ecb", "boc", "boj", "pboc", "rbi", "bdf"),
     "Policy rates, yields, money supply"),
    ("International bodies", ("imf", "wb", "un"), "Outlooks, development and trade data"),
    ("Filings and investor relations", ("edgar", "sec", "ir"), "Filings, facts, insider trades, reports"),
    ("Analytics and SQL", ("duckdb", "olap", "sqlselect", "customer", "calc"),
     "SQL over files, pivots, financial calculators"),
    ("Search and the web", ("tavily", "wiki", "crawl", "extract", "check", "get"),
     "Web and news search, extraction, crawling"),
    ("Documents", ("msdoc", "sharepoint", "sajha"), "Word and Excel, SharePoint, SAJHA's own guides"),
    ("Connected accounts", ("github", "google", "ms365", "slack", "connected"), "Act as the user in SaaS apps"),
    ("Public statistics", ("fbi",), "Crime statistics"),
    ("LLM tools", ("llm",), "Example LLM tools: assistant, summariser, triage, docs Q&A (disabled by default)"),
]

CREATORS = {
    "python": ("Python code", "Write a function with the @sajhamcptool decorator; the schema comes from its "
               "type hints. Runs sandboxed."),
    "rest": ("REST service", "Wrap an HTTP endpoint: method, URL template, headers, auth, response mapping."),
    "dbquery": ("Database query", "A parameterised SQL template becomes a tool."),
    "script": ("Script", "A shell or Python script, arguments passed in; runs sandboxed."),
    "olap": ("OLAP dataset", "Define a dataset, dimensions and measures for pivot-style analysis."),
    "powerbi": ("Power BI report", "Export reports as PDF, PPTX or PNG."),
    "powerbidax": ("Power BI DAX", "Run DAX queries against a dataset."),
    "sharepoint": ("SharePoint", "Documents, lists and search on a SharePoint site."),
    "livelink": ("OpenText LiveLink", "Browse and fetch documents from a LiveLink repository."),
    "describe": ("Describe a tool", "One sentence becomes a proposed, tested tool for review."),
    "api_import": ("Import an API", "OpenAPI 3, Swagger 2 or GraphQL becomes reviewed tools."),
}


def _rule(rule_id: str, path: str = "config/policies/example-guardrails.yaml") -> list[str]:
    """One rule of a shipped policy file, verbatim."""
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == f"- id: {rule_id}")
    out = [lines[start]]
    for ln in lines[start + 1 :]:
        if ln.strip().startswith("- id:") or not ln.strip():
            break
        out.append(ln)
    lines = [ln[2:] if ln.startswith("  ") else ln for ln in out]
    wrapped: list[str] = []
    for ln in lines:
        lead = ln[: len(ln) - len(ln.lstrip())]
        wrapped += wrap(ln, 44, lead + "    ") if len(ln) > 44 else [ln]
    return wrapped


def _categories(F: dict[str, Any]) -> list[list[str]]:
    groups = {g: (n, ex) for g, n, ex in F["catalog"]["top"]}
    known = {g for _c, gs, _w in CATEGORIES for g in gs}
    unknown = sorted(set(groups) - known)
    if unknown:
        raise SourceChanged(f"tool groups with no category on the built-in tools slide: {unknown}")
    rows = [["Category", "Groups", "Tools", "What for"]]
    for name, gs, what in CATEGORIES:
        live = [g for g in gs if g in groups]
        if live:
            rows.append([name, ", ".join(live), str(sum(groups[g][0] for g in live)), what])
    return rows


def _overview(F: dict[str, Any]) -> list[dict[str, Any]]:
    cat, eras = F["catalog"], F["eras"]
    n_versions = len(eras["modern"]) + len(eras["handshake"])
    catalog_src = (
        "Tool and group counts: the tools registry loaded from config/tools at build time "
        "(sajha.tools.tools_registry.ToolsRegistry, counted by sajha.web.help_catalog.live_tool_groups): "
        f"{cat['tools']} tools in {cat['groups']} groups, {cat['errors']} load errors."
    )
    creators = F["studio_pages"]
    missing = [c for c in creators if c not in CREATORS]
    if missing:
        raise SourceChanged(f"Studio creators with no description on the deck: {missing}")
    return [
        {
            "kind": "divider",
            "title": "The SAJHA MCP server",
            "sub": "SAJHA (साझा, Hindi for “shared”): one self-hosted server that holds the tools an organisation's "
            "agents use, serves them to any MCP client, and applies one set of identities, permissions, rules and "
            "records to every call.",
            "points": ["Overview", "Tools in the box", "MCP Studio", "Federation", "Architecture", "Web console",
                       "Access and authentication", "Credentials", "Policy and audit", "Deploy anywhere"],
        },
        {
            "kind": "stats",
            "kicker": "Overview",
            "title": "One catalog of tools, one address, one set of rules",
            "intro": "A production Python MCP server on FastAPI, serving both protocol eras on /mcp, with its own "
            "intelligence layer, browser tool builders and governance.",
            "stats": [
                (str(cat["tools"]), "tools in the catalog when this deck was built"),
                (str(cat["groups"]), f"tool groups, the largest {cat['top'][0][0]} ({cat['top'][0][1]} tools)"),
                (str(n_versions), "protocol versions served on one endpoint"),
                (str(F["tests"]), "automated tests in the suite"),
            ],
            "items": [
                ("Shared", "One catalog for every team and agent framework: a tool is built, governed and recorded once."),
                ("Governed", "Every call, from any client or SAJHA's own assistant, passes the same access check, "
                 "rules and tamper-evident record."),
                ("Self-hosted", "One Python process on a laptop or several pods on Kubernetes; data leaves only when "
                 "a tool sends it."),
            ],
            "source": catalog_src + f" Protocol versions: sajha.core.mcp_modern ({listing(eras['modern'])}; "
            f"{listing(eras['handshake'])}). Tests: pytest --collect-only over tests and clientsdk/tests at build time.",
        },
        {
            "kind": "bullets",
            "kicker": "Why SAJHA",
            "title": "What makes SAJHA different from a plain tool server",
            "items": [
                ("A governed server, not a pipe", "Access policy, declarative rules, human approval and a "
                 "hash-chained audit apply to every call on every path."),
                (f"{cat['tools']} tools from day one", "Markets, central banks, filings, public statistics, search, "
                 "documents and calculators, ready to call."),
                ("Zero code to full code", f"{len(creators)} ways to make a tool in the browser, or a Python class; "
                 "the same MCP tool either way."),
                ("An intelligence layer inside", f"{len(F['providers'])} provider types behind one gateway, "
                 "planners, memory, document search and evals; the offline mock is the default."),
                ("Every client's language", "Both MCP eras, four transports, its own OAuth 2.1 server, and the "
                 "official conformance suite in CI."),
                ("Many servers, one net", "SAJHA Net joins servers across boundaries; each keeps its own data, rules "
                 "and models, and only governed calls cross."),
                ("Runs where your data is", "Laptop, VM, Docker, Kubernetes; SQLite or PostgreSQL; local disk or an "
                 "object store."),
            ],
            "source": catalog_src + " Creators: the MCP Studio pages in sajha/routes/studio_routes.py plus "
            "describe_routes.py and api_import_routes.py, read at build time. Providers: "
            "sajha.ai.llm.registry.registered_providers().",
        },
        {
            "kind": "table",
            "kicker": "Tools in the box",
            "title": f"{cat['tools']} built-in tools, from market data to calculators",
            "col_w": [2.1, 2.9, 0.7, 2.6],
            "rows": _categories(F),
            "note": "The live list is tools/list or the Tools page; a caller sees only the tools it may run.",
            "source": catalog_src + " Grouping into categories: tools/deck/deck_part2.py CATEGORIES; a group it "
            "does not name fails the build.",
        },
        {
            "kind": "principles",
            "kicker": "MCP Studio",
            "title": f"MCP Studio: {len(creators)} ways to create a tool in the browser",
            "items": [CREATORS[c] for c in creators],
            "note": "Each creator deploys into the running server, with no restart; generated code and scripts run "
            "in the sandbox.",
            "source": "The Studio pages served by sajha/routes/studio_routes.py (@pages.get), plus Describe a tool "
            "(describe_routes.py) and Import an API (api_import_routes.py), read at build time; the decorator is "
            "sajha/studio/decorator.py (sajhamcptool). docs/studio/MCP Studio User Guide.md. The earlier deck's "
            "creator list is replaced by this derived one.",
        },
        {
            "kind": "flow",
            "kicker": "Describe a tool",
            "title": "A sentence becomes a proposal, and nothing deploys without a person",
            "box_h": 3.0,
            "steps": [
                ("Describe", "“Fetch today's FX rate for a currency pair from our rates API.”"),
                ("Propose", "The toolsmith model drafts the kind, name, schemas, implementation and test cases."),
                ("Check", "Treated as untrusted: read-only SQL, host checks, no credentials, risky imports flagged."),
                ("Test", "Cases run in the sandbox, offline where possible, bound to the draft's SHA-256."),
                ("Approve", "An administrator approves that hash; policy can require a second one."),
            ],
            "items": [
                "Out of the box the toolsmith alias points at an offline mock that knows a few shapes; real designs "
                "need a real model. Generated Python tools always run sandboxed.",
            ],
            "source": "docs/architecture/Tool Generation.md; sajha/studio/describe.py; sajha/ai/llm/mock_toolsmith.py. "
            "The example sentence is illustrative.",
        },
        {
            "kind": "canvas",
            "kicker": "APIs and databases",
            "title": "An API description or a database becomes governed, read-only tools",
            "groups": [
                {"id": "ga", "label": "IMPORT AN API", "x": 0.0, "y": 0.0, "w": 1.0, "h": 0.46},
                {"id": "gd", "label": "DATA CONNECTORS", "x": 0.0, "y": 0.52, "w": 1.0, "h": 0.48},
            ],
            "nodes": [
                {"id": "a1", "text": "OpenAPI 3, Swagger 2 or GraphQL", "x": 0.02, "y": 0.12, "w": 0.18, "h": 0.26,
                 "style": "white", "shape": "doc", "size": 14},
                {"id": "a2", "text": "Preview", "sub": "every operation: name, schemas, read-only and destructive hints",
                 "x": 0.25, "y": 0.11, "w": 0.22, "h": 0.26, "style": "soft", "size": 14},
                {"id": "a3", "text": "Choose and test", "sub": "one live call; credentials only as secret references",
                 "x": 0.52, "y": 0.11, "w": 0.2, "h": 0.26, "style": "soft", "size": 14},
                {"id": "a4", "text": "Deployed tools", "sub": "every call through an SSRF guard; re-import shows a diff",
                 "x": 0.77, "y": 0.11, "w": 0.21, "h": 0.26, "style": "accent", "size": 14},
                {"id": "d1", "text": "Your database", "sub": "SQL: " + listing(F["connectors"]["sql"][:4]) + ", ...",
                 "x": 0.02, "y": 0.64, "w": 0.18, "h": 0.28, "style": "white", "shape": "can", "size": 14},
                {"id": "d2", "text": "Read-only three times", "sub": "statement guard, read-only session, the login's "
                 "own grants", "x": 0.25, "y": 0.65, "w": 0.22, "h": 0.26, "style": "dark", "size": 14},
                {"id": "d3", "text": "Curated views", "sub": "become typed tools", "x": 0.52, "y": 0.65, "w": 0.2,
                 "h": 0.26, "style": "soft", "size": 14},
                {"id": "d4", "text": f"prefix{F['net']['sep']}operation", "sub": listing(F["connectors"]["per_user"])
                 + " can sign in as each user", "x": 0.77, "y": 0.65, "w": 0.21, "h": 0.26, "style": "accent",
                 "size": 14},
            ],
            "edges": [{"a": "a1", "b": "a2"}, {"a": "a2", "b": "a3"}, {"a": "a3", "b": "a4", "color": "CRIMSON"},
                      {"a": "d1", "b": "d2"}, {"a": "d2", "b": "d3"}, {"a": "d3", "b": "d4", "color": "CRIMSON"}],
            "source": "Connector kinds: sajha/connectors/model.py KINDS and PER_USER_KINDS, read at build time. "
            "docs/architecture/API Import.md and Data Connectors.md.",
            "talk": f"Import an API: an OpenAPI 3.x, Swagger 2.0 or GraphQL description becomes a preview of every "
            "operation, with its name, JSON Schema in and out, and read-only and destructive hints; an administrator "
            "chooses, tests one call and deploys. Credentials are kept only as secret references, every call passes "
            "an SSRF guard, and a re-import shows a diff. Data connectors: SQL databases ("
            f"{listing(F['connectors']['sql'])}) and search stores ({listing(F['connectors']['search'])}) are read "
            "through a statement guard, a read-only session and the login's own grants; curated views become typed "
            "tools, named with the connector's prefix.",
        },
        {
            "kind": "canvas",
            "kicker": "Federation",
            "title": "Other MCP servers' tools join the catalog under SAJHA's rules",
            "groups": [{"id": "sj", "label": "SAJHA" + (" (FEDERATION SHIPS OFF)" if not F["net"]["federation_shipped"]
                                                        else ""), "x": 0.2, "y": 0.0, "w": 0.6, "h": 1.0}],
            "nodes": [
                {"id": "u1", "text": "weather MCP server", "sub": "Streamable HTTP", "x": 0.0, "y": 0.06, "w": 0.16,
                 "h": 0.17, "style": "white", "size": 13},
                {"id": "u2", "text": "fetch MCP server", "sub": "stdio", "x": 0.0, "y": 0.35, "w": 0.16, "h": 0.17,
                 "style": "white", "size": 13},
                {"id": "mf", "text": "mcpServers file", "sub": "the JSON desktop clients use", "x": 0.0, "y": 0.68,
                 "w": 0.16, "h": 0.22, "style": "box", "shape": "doc", "size": 13},
                {"id": "g1", "text": "SSRF guard", "sub": "on upstream and token addresses", "x": 0.23, "y": 0.18,
                 "w": 0.165, "h": 0.24, "style": "soft", "shape": "hex", "size": 13},
                {"id": "g2", "text": "Approval", "sub": "each tool waits for an administrator; a change waits again",
                 "x": 0.42, "y": 0.18, "w": 0.165, "h": 0.24, "style": "soft", "size": 13},
                {"id": "g3", "text": "Screening", "sub": "descriptions and results checked for injected instructions",
                 "x": 0.61, "y": 0.18, "w": 0.165, "h": 0.24, "style": "soft", "size": 13},
                {"id": "cat", "text": f"weather{F['net']['sep']}get_forecast", "sub": "in the catalog, under access, "
                 "policy, cache, breakers and audit", "x": 0.3, "y": 0.62, "w": 0.4, "h": 0.2, "style": "accent",
                 "size": 15},
                {"id": "cl", "text": "MCP clients", "sub": "and Ask SAJHA", "x": 0.85, "y": 0.6, "w": 0.15, "h": 0.24,
                 "style": "white", "shape": "oval", "size": 13},
            ],
            "edges": [
                {"a": "u1", "b": "g1", "mode": "c"}, {"a": "u2", "b": "g1", "mode": "c"},
                {"a": "mf", "b": "u2", "dash": True, "label": "defines", "lsize": 10},
                {"a": "g1", "b": "g2"}, {"a": "g2", "b": "g3"},
                {"a": "g3", "b": "cat", "mode": "c", "color": "CRIMSON"}, {"a": "cat", "b": "cl", "color": "CRIMSON"},
            ],
            "note": "Not isolated: an upstream runs where it runs; SAJHA governs the calls, not its process. A user's own "
            "token can be passed through instead of a shared one.",
            "source": "docs/architecture/Federation.md (§4 names, §6 approval, §9 security, §10 the mcpServers file); "
            "sajha/federation/; GLOSSARY.md 'Federation', 'Tool poisoning'. federation.enabled read from the shipped "
            "config/application.yml at build time. The upstream names are illustrative.",
            "talk": "SAJHA can front another MCP server, a proxied MCP server: its tools appear as prefix, two "
            "underscores, tool, and every call to them passes SAJHA's access policy, rules, cache, circuit breakers "
            "and audit. Upstreams come from application.yml, the console, or the mcpServers file that Claude Desktop, "
            "Cursor and VS Code use, so an administrator can paste a block they already have; secrets come from the "
            "environment. An upstream's tools wait for an administrator's approval, and a changed definition waits "
            "again. Descriptions and results are screened for injected instructions; flagged items wait for a person. "
            "Section 5 shows how an external server's tools enter a SAJHA Net under its vendor's prefix.",
        },
    ]


def _architecture(F: dict[str, Any]) -> list[dict[str, Any]]:
    bands = [
        ("Clients", "dark", "MCP clients (both eras) · browser console · sajha CLI · Python SDK · A2A agents · workflows"),
        ("Transports", "accent", "Streamable HTTP /mcp · legacy SSE /mcp/sse · WebSocket /mcp/ws · stdio · REST API"),
        ("Governance", "dark", "Authentication · tool access policy · policy engine (deny, approve, limit, redact) · "
                               "hash-chained audit and SIEM export"),
        ("Intelligence", "accent", "LLM gateway · Ask SAJHA and planners · memory and document search · evals · "
                                   "Describe a tool"),
        ("Tools", "dark", "Tools registry · composites · workflows · federation · data connectors · sandbox · "
                          "cache and circuit breakers"),
        ("Platform", "accent", f"FastAPI on uvicorn · {listing(F['schemas'], 'or')} · state store "
                               f"({'/'.join(F['state'])}) · storage ({'/'.join(F['storage'])}) · metrics and traces"),
    ]
    nodes = []
    n = len(bands)
    h = 1.0 / n
    for i, (label, style, body) in enumerate(bands):
        nodes.append({"id": f"l{i}", "text": label, "x": 0.0, "y": i * h + 0.01, "w": 0.16, "h": h - 0.03,
                      "style": style, "size": 17})
        nodes.append({"id": f"b{i}", "text": body, "x": 0.175, "y": i * h + 0.01, "w": 0.825, "h": h - 0.03,
                      "style": "box", "size": 16, "bold": False})
    return [
        {
            "kind": "diagram",
            "kicker": "Server architecture",
            "title": "Six layers, and every call crosses the governance layer",
            "nodes": nodes,
            "source": f"sajha/app.py (FastAPI application), sajha/routes/ ({F['routes']} route modules), sajha/auth/, "
            "sajha/policy/, sajha/audit/, sajha/ai/, sajha/tools/, sajha/workflows/, sajha/federation/, "
            "sajha/connectors/, sajha/sandbox/; state, storage and schema lists read at build time. "
            "docs/architecture/Architecture.md.",
        },
        {
            "kind": "bullets",
            "kicker": "Web console",
            "title": f"A web console of {F['pages']} pages, each with its own help",
            "items": [
                ("Tools", "Browse and search the catalog, view a schema, run a tool, see reports and monitoring."),
                ("AI", "Ask SAJHA with its live constellation of tools, a Python playground, models and providers, "
                 "prompts."),
                ("MCP Studio", "Every creator, Describe a tool, Import an API, and the composite builder."),
                ("Admin", "Users, roles and API keys; federation, connectors and connected accounts; policies, "
                 "approvals and the audit; workflows; tool health, versions and evals."),
                ("Help", "Every guide in docs/ rendered in the app, the glossary, and an “About this page” panel on "
                 "each page."),
            ],
            "note": "It works on a phone, and offers light, dark, blue and green themes.",
            "source": "Page count: sajha.web.page_help.PAGE_HELP (pages with an 'About this page' panel, the error page "
            "excluded), read at build time. Menus: sajha/web/templates/common/_nav.html. Themes: "
            "sajha/web/static/css/tokens.css. docs/architecture/Architecture.md §10.",
        },
        {
            "kind": "diagram",
            "kicker": "Parallel SDLC",
            "title": "Tool developers and AI developers ship independently",
            "groups": [
                {"id": "td", "label": "TOOL DEVELOPERS", "x": 0.0, "y": 0.0, "w": 0.3, "h": 0.8},
                {"id": "ad", "label": "AI DEVELOPERS", "x": 0.7, "y": 0.0, "w": 0.3, "h": 0.8},
            ],
            "nodes": [
                {"id": "b", "text": "Build", "sub": "Studio or a Python tool", "x": 0.03, "y": 0.1, "w": 0.24,
                 "h": 0.18},
                {"id": "t", "text": "Test", "sub": "tool tests, schema lint", "x": 0.03, "y": 0.34, "w": 0.24,
                 "h": 0.18},
                {"id": "d", "text": "Deploy", "sub": "drop a config; hot reload", "x": 0.03, "y": 0.58, "w": 0.24,
                 "h": 0.18},
                {"id": "s", "text": "SAJHA", "sub": "the schema is the contract", "x": 0.38, "y": 0.28, "w": 0.24,
                 "h": 0.28, "style": "accent"},
                {"id": "de", "text": "Design", "sub": "agent logic and prompts", "x": 0.73, "y": 0.1, "w": 0.24,
                 "h": 0.18},
                {"id": "ev", "text": "Evaluate", "sub": "golden questions (evals)", "x": 0.73, "y": 0.34, "w": 0.24,
                 "h": 0.18},
                {"id": "it", "text": "Iterate", "sub": "tune prompts and planners", "x": 0.73, "y": 0.58, "w": 0.24,
                 "h": 0.18},
                {"id": "int", "text": "Integration: agents discover and call tools from both pipelines", "x": 0.0,
                 "y": 0.87, "w": 1.0, "h": 0.13, "style": "soft"},
            ],
            "edges": [("b", "t", ""), ("t", "d", ""), ("de", "ev", ""), ("ev", "it", ""),
                      ("t", "s", "register"), ("s", "ev", "discover, invoke")],
            "source": "Tool tests and lint: docs/architecture/Tool Quality.md; hot reload: ToolsRegistry file monitor "
            "(sajha/tools/tools_registry.py); evals: sajha/quality/evals.py. After the earlier deck's SDLC slide.",
        },
    ]


def _access(F: dict[str, Any]) -> list[dict[str, Any]]:
    roles = F["roles"]
    role_rows = [["Who", "Rights", "What it may see and run"]]
    for name, desc, perms in roles:
        rights = "; ".join(
            ("everything" if t == "*" else f"{t} {'(any)' if r == '*' else r}")
            + ": " + ("all actions" if a == "*" else a.replace(",", ", "))
            for t, r, a in perms
        )
        role_rows.append([f"Role {name}", rights, desc])
    role_rows += [
        ["An API key", "all, allowlist, denylist or regex", "The key's tool access mode; never an admin"],
        ["Anonymous", "mcp.anonymous.tools (empty by default)", "Nothing, unless an operator allows it"],
    ]
    return [
        {
            "kind": "table",
            "kicker": "Role-based access control",
            "title": "Tool-level permissions, checked on every call, on every path",
            "col_w": [1.6, 3.0, 3.0],
            "rows": role_rows,
            "note": "read lets a caller see a tool, execute lets it run one; patterns are fnmatch globs such as "
            "fred_*. One policy (sajha/auth/access.py) serves REST, MCP in both eras, SSE, WebSocket, stdio and A2A.",
            "source": "Seeded roles and permissions: db/scripts/sqlite/seed.sql, parsed at build time. API key modes and "
            "anonymous policy: sajha/auth/access.py; docs/security/Security Model.md §1 'Tool access'.",
        },
        {
            "kind": "table",
            "kicker": "Enterprise security",
            "title": "Security in layers, each with the threat it answers",
            "col_w": [1.5, 3.9, 2.3],
            "rows": [
                ["Layer", "Mechanism", "Protects against"],
                ["Authentication", "Session cookie, single sign-on, revocable SAJHA JWT, API keys, OAuth 2.1 on /mcp",
                 "Unknown callers"],
                ["Authorization", "Role permissions and API-key modes, per tool, on every path", "Privilege escalation"],
                ["Policy", "Deny, require approval, constrain arguments, rate limits and quotas, redaction",
                 "Unsafe or excessive calls"],
                ["Input", "JSON Schema on every call; SQL guards; an SSRF guard on outbound requests",
                 "Injection, internal-network access"],
                ["Transport", "Origin allow-list on /mcp; HTTPS at the proxy or ingress; HSTS, CSP and other headers",
                 "DNS rebinding, interception"],
                ["Sign-in", "Per-IP throttling and account lockout", "Password guessing"],
                ["Code", "Studio code and scripts in a per-call sandbox", "Untrusted code"],
                ["Record", "Hash-chained, signed audit; SIEM export", "Undetected tampering"],
            ],
            "note": "Rate limits on tool calls come from policy rules; /mcp itself has no built-in request rate limit.",
            "source": "docs/security/Security Model.md §1–§3 (credentials, tool access, transport protections, rate "
            "limiting: 'per-user and per-key limits exist but are not called'), §5, §7; "
            "docs/architecture/Policy and Audit.md.",
        },
        {
            "kind": "canvas",
            "kicker": "Authentication",
            "title": "Four ways to prove who is calling, and one access policy behind them",
            "nodes": [
                {"id": "p", "text": "A person in the console", "sub": "sign-in form or single sign-on: the "
                 "sajha_token cookie", "x": 0.0, "y": 0.0, "w": 0.27, "h": 0.18, "style": "white", "size": 13},
                {"id": "s", "text": "A script with a password", "sub": "POST /api/auth/login: a SAJHA JWT",
                 "x": 0.0, "y": 0.26, "w": 0.27, "h": 0.18, "style": "white", "size": 13},
                {"id": "k", "text": "An automation", "sub": "an API key sja_… from an administrator or its owner",
                 "x": 0.0, "y": 0.52, "w": 0.27, "h": 0.18, "style": "white", "size": 13},
                {"id": "o", "text": "An OAuth client", "sub": "an access token, MCP endpoints only", "x": 0.0,
                 "y": 0.78, "w": 0.27, "h": 0.18, "style": "white", "size": 13},
                {"id": "ar", "text": "authenticate_request", "sub": "tried in order: 1 Bearer JWT, 2 X-API-Key, "
                 "3 Authorization: sja_…, 4 the cookie", "x": 0.36, "y": 0.06, "w": 0.24, "h": 0.58, "style": "dark",
                 "size": 14},
                {"id": "rs", "text": "Resource server on /mcp", "sub": "issuer, audience, expiry, scope", "x": 0.36,
                 "y": 0.76, "w": 0.24, "h": 0.22, "style": "soft", "size": 13},
                {"id": "ap", "text": "One access policy", "sub": "sajha/auth/access.py: roles' patterns or the key's "
                 "mode", "x": 0.69, "y": 0.3, "w": 0.15, "h": 0.4, "style": "accent", "size": 14},
                {"id": "t", "text": "tools", "x": 0.89, "y": 0.4, "w": 0.11, "h": 0.2, "style": "white",
                 "shape": "oval", "size": 14},
            ],
            "edges": [
                {"a": "p", "b": "ar", "mode": "c"}, {"a": "s", "b": "ar", "mode": "c"}, {"a": "k", "b": "ar", "mode": "c"},
                {"a": "o", "b": "rs"},
                {"a": "ar", "b": "ap", "mode": "c", "color": "CRIMSON"}, {"a": "rs", "b": "ap", "mode": "c",
                                                                          "color": "CRIMSON"},
                {"a": "ap", "b": "t", "color": "CRIMSON"},
            ],
            "note": "A credential that fails is refused, never treated as anonymous. Every SAJHA JWT can be revoked "
            "before it expires: sign out, or sign out everywhere.",
            "source": "sajha/auth/__init__.py AuthManager.authenticate_request; sajha/routes/auth_routes.py; "
            "sajha/auth/sso.py; sajha/auth/revocation.py; sajha/core/config.py (auth.jwt.algorithm, "
            "auth.jwt.expiry_minutes); docs/security/Security Model.md §1–§2.",
            "talk": "A person signs in with the form, or with an OpenID Connect provider when single sign-on is on, and "
            "gets the sajha_token cookie (HttpOnly, SameSite=Lax). A script posts a user id and password to "
            "/api/auth/login and gets a SAJHA JWT (default HS256, 60 minutes). An automation uses an API key that an "
            "administrator issued or a user created for themselves. An OAuth client brings an access token from "
            "SAJHA's own authorization server or yours, accepted on the MCP endpoints only. Whichever way, the same "
            "access policy decides which tools the caller may see and run, on REST, MCP in both eras, SSE, "
            "WebSocket, stdio and A2A. Sign-out records the token id in the state store; sign out everywhere raises "
            "the user's token version, which every token carries.",
        },
        {
            "kind": "canvas",
            "kicker": "OAuth 2.1",
            "title": "OAuth 2.1 on /mcp: SAJHA's own authorization server, or yours",
            "nodes": [
                {"id": "c", "text": "MCP client", "x": 0.0, "y": 0.36, "w": 0.16, "h": 0.24, "style": "white",
                 "shape": "oval", "size": 15},
                {"id": "as", "text": "Authorization server", "sub": "SAJHA's own, or your identity provider: PKCE S256, "
                 "rotating refresh tokens", "x": 0.36, "y": 0.0, "w": 0.3, "h": 0.24, "style": "dark", "size": 14},
                {"id": "rs", "text": "Resource server: SAJHA /mcp", "sub": "audience-bound tokens; scopes mcp:read, "
                 "mcp:tools", "x": 0.36, "y": 0.7, "w": 0.3, "h": 0.24, "style": "accent", "size": 14},
                {"id": "u", "text": "the user", "sub": "signs in and consents", "x": 0.82, "y": 0.02, "w": 0.16,
                 "h": 0.2, "style": "soft", "shape": "oval", "size": 13},
                {"id": "pol", "text": "then the user's tool access", "sub": "as for any caller", "x": 0.79, "y": 0.72,
                 "w": 0.21, "h": 0.2, "style": "box", "size": 13},
            ],
            "edges": [
                {"a": "rs", "b": "c", "ports": ("l", "b"), "at": (0.5, 0.5), "via": [(0.08, 0.82)], "dash": True,
                 "label": "1  no token: 401 and metadata", "lsize": 10.5, "lseg": 0},
                {"a": "c", "b": "as", "mode": "c", "color": "CRIMSON", "label": "2  authorize with PKCE; 3  code for token",
                 "lsize": 10.5, "loff": (-0.6, -0.05)},
                {"a": "as", "b": "u", "both": True},
                {"a": "c", "b": "rs", "ports": ("r", "t"), "at": (0.5, 0.25), "color": "CRIMSON",
                 "label": "4  Bearer token", "lsize": 10.5, "loff": (0.95, 0.1)},
                {"a": "rs", "b": "pol"},
            ],
            "note": f"Off by default (mcp.auth.mode: off, optional or required); API keys and SAJHA's own tokens work in "
            "every mode. OAuth here controls who may call /mcp; console sign-in is separate.",
            "source": "docs/protocol/OAuth Guide.md §1–§2; sajha/auth/oauth/settings.py (DEFAULT_SCOPES), "
            "resource_server.py, authorization_server.py; sajha/routes/oauth_routes.py.",
            "talk": "An authorization server issues tokens; a resource server accepts them. SAJHA can be both, or only "
            "the resource server behind your identity provider. A client that calls /mcp without a token gets 401 with "
            "a pointer to the protected-resource metadata (RFC 9728), which names the authorization server. The client "
            "runs the authorization-code flow with PKCE S256 and the resource indicator (RFC 8707), so the token's "
            "audience is SAJHA's /mcp and a token issued for another API is refused. SAJHA's built-in server supports "
            "client ID metadata documents, optional dynamic registration, and rotating refresh tokens with reuse "
            "detection. After the token checks, the user's own tool access applies as for any caller.",
        },
        _credentials(F),
    ]


def _credentials(F: dict[str, Any]) -> dict[str, Any]:
    """Where credentials live and which copy wins, how they are stored, sign-in, and the browser's guards."""
    nt = F["net"]
    store = nt["credential_storage"]
    col = lambda i, t, sub, x, y, st="white", h=0.15: {"id": i, "text": t, "sub": sub, "x": x, "y": y, "w": 0.17,
                                                      "h": h, "style": st, "size": 12}
    nodes = [
        col("uf", "config/users.json", "wins: applied at start and on change", 0.015, 0.1),
        col("ut", "users table", "everything else", 0.015, 0.33),
        col("kf", "config/apikeys.json", "wins: checked first", 0.205, 0.1),
        col("kd", "database", "validated on every request", 0.205, 0.33),
        col("kj", "config/apikeys_db.json", "last: only if the database cannot answer", 0.205, 0.56, h=0.17),
        {"id": "plain", "text": f"Stored {store} by default" if store == "plain" else f"Stored {store}",
         "sub": "the owner's decision for intranet use; set hashed and run python -m sajha.auth rehash to switch",
         "x": 0.015, "y": 0.79, "w": 0.36, "h": 0.19, "style": "warn", "size": 13},
        col("sso", "Single sign-on", "OpenID Connect, beside passwords", 0.43, 0.1),
        col("rev", "Revocable sessions", "sign out; sign out everywhere", 0.43, 0.3),
        col("lock", "Throttle and lockout", "per address and per account", 0.43, 0.5),
        {"id": "tak", "text": "Test admin key", "sub": "ships " + ("on" if nt["test_admin_shipped"] else "off") +
         ": a critical notice shows while it is active", "x": 0.43, "y": 0.72, "w": 0.17, "h": 0.2, "style": "warn",
         "size": 12},
        col("csp", "Content-Security-Policy", "scripts only with a per-response nonce", 0.81, 0.1),
        col("csrf", "Cross-site check", "cookie requests from another site refused", 0.81, 0.3),
        col("org", "Origin allow-list", "on /mcp, against DNS rebinding", 0.81, 0.5),
        col("tls", "TLS at the proxy", "plus HSTS and other headers", 0.81, 0.7),
    ]
    edges = [{"a": "uf", "b": "ut", "label": "else", "lsize": 10}, {"a": "kf", "b": "kd", "label": "else", "lsize": 10},
             {"a": "kd", "b": "kj", "label": "else", "lsize": 10}]
    return {
        "kind": "canvas",
        "kicker": "Credentials, sign-in and the browser",
        "title": "Where credentials live, and how sign-in and the browser are guarded",
        "groups": [
            {"id": "g1", "label": "CREDENTIALS: USERS / API KEYS", "x": 0.0, "y": 0.0, "w": 0.39, "h": 1.0},
            {"id": "g2", "label": "SIGN-IN", "x": 0.415, "y": 0.0, "w": 0.2, "h": 1.0},
            {"id": "g3", "label": "BROWSER AND TRANSPORT", "x": 0.795, "y": 0.0, "w": 0.205, "h": 1.0},
        ],
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.635, "y": 0.1, "w": 0.15, "h": 0.8, "size": 12,
                   "text": "Every SAJHA JWT\ncarries an id and\nthe user's token\nversion, so it can\nbe withdrawn "
                   "before\nit expires.\n\nAn API key is not\na session: revoke\nor rotate it."}],
        "source": "docs/security/Security Model.md §1 ('Credential storage and files', 'Test admin key', 'Console single "
        "sign-on', 'Revocable sign-in'), §3 (security headers and CSP, CSRF, Origin allow-list), §8 (known "
        "limitations: plain storage by default, the test admin key ships on). auth.credential_storage and "
        "sajhanet.test_admin_key.enabled read from the shipped config/application.yml at build time.",
        "talk": "Users and API keys live in the database, and administrators can also keep them in two credential "
        "files beside it. config/users.json wins: it is applied to the users table at start-up and whenever it "
        "changes. For an API key, config/apikeys.json is checked first and wins for every key it holds; then the "
        "database, read on every request so a revoked key stops at once; and only when the database does not know "
        "the key or does not answer, the periodic dump config/apikeys_db.json. Passwords and API keys are stored "
        "plain by default: that is the owner's decision for intranet use, and a warning notice stays up while it "
        "is on. Setting auth.credential_storage to hashed and running the rehash command switches every stored "
        "value to a hash; both forms keep working across the switch. The test admin key ships on for development "
        "and testing and shows a critical notice while active; turn it off before production. Single sign-on with "
        "an OpenID Connect provider works beside passwords. In the browser, a Content-Security-Policy with a nonce "
        "per response, a cross-site check on every state-changing cookie request, and an Origin allow-list on /mcp; "
        "TLS ends at the proxy or ingress.",
    }


def _flows(F: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "mono",
            "kicker": "Step by step",
            "title": "Authentication: the session cookie (web console)",
            "band": "Browser  →  SAJHA server",
            "lines": [
                "1. Browser → GET /login",
                "   └─ Server returns the sign-in form",
                "2. Browser → POST /login { user_id, password }",
                "   ├─ Per-IP throttle: too many failures → 429",
                "   ├─ Password check (stored plain by default,",
                "   │    or a bcrypt hash under hashed storage)",
                "   ├─ Repeated failures lock the account → 423",
                "   └─ If valid:",
                "      ├─ Issue a SAJHA JWT (auth.jwt.*, default HS256, 60 min)",
                "      ├─ Set-Cookie: sajha_token (HttpOnly, SameSite=Lax,",
                "      │    Secure on https, Max-Age 3600)",
                "      └─ 302 → /dashboard (local paths only, no open redirect)",
                "3. Every later request",
                "   ├─ Cookie read last, after Bearer and API key",
                "   ├─ Signature, algorithm and expiry checked",
                "   └─ User reloaded from the database: a disabled user",
                "      is out at once",
            ],
            "source": "sajha/routes/auth_routes.py (login_form, _set_session_cookie); sajha/auth/password.py "
            "(verify_password accepts plain or bcrypt; auth.credential_storage); "
            "sajha/security.py (login throttle); docs/security/Security Model.md §1 'Web login', 'Session cookie'.",
        },
        {
            "kind": "mono",
            "kicker": "Step by step",
            "title": "Authentication: the SAJHA JWT (API clients)",
            "band": "API client  →  SAJHA server",
            "lines": [
                "1. Client → POST /api/auth/login",
                '   └─ Body: { "user_id": "alice", "password": "…" }',
                "2. Server checks the credentials",
                "   ├─ Throttle and lockout, as for the web form",
                "   ├─ Invalid → 401; locked → 423",
                '   └─ Valid → { "token": "eyJ…", "user": { roles … } }',
                "3. Client sends the token on every request",
                "   └─ Authorization: Bearer eyJ…",
                "4. Server validates it",
                "   ├─ Signature, allowed algorithm, exp",
                "   ├─ Claims: sub, roles, iss sajha-mcp-server",
                "   └─ Then the caller's tool access applies",
                "      (REST, /mcp, and /mcp/ws?token=…)",
            ],
            "source": "sajha/routes/auth_routes.py api_login; sajha/auth/jwt_handler.py; sajha/auth/__init__.py "
            "authenticate_request; docs/security/Security Model.md §1 'SAJHA JWT'.",
        },
        {
            "kind": "mono",
            "kicker": "Step by step",
            "title": "Authentication: the API key (automation)",
            "band": "Script or agent  →  SAJHA server",
            "lines": [
                "1. An administrator creates a key (console, POST /admin/apikeys/create)",
                "   ├─ Key: sja_ + 48 hex characters",
                "   ├─ Stored: SHA-256 (for lookup), 8-character prefix,",
                "   │    and the raw key under plain storage (default)",
                "   └─ Tool access mode: all | allowlist | denylist | regex",
                "2. Client → any request with",
                "   └─ X-API-Key: sja_…   (or Authorization: sja_…)",
                "3. Server authenticates",
                "   ├─ Unknown, disabled or expired → refused",
                "   └─ Identity apikey:<name>, role api_consumer, never admin",
                "4. Server authorizes the tool",
                '   ├─ allowlist ["fred_*", "calc_*"]: fred_gdp → allowed',
                "   ├─ yf_fast_info → 403 (not listed)",
                "   └─ Usage recorded; the call audited",
            ],
            "source": "sajha/routes/apikeys_routes.py; sajha/db/dao/__init__.py ApiKeyDAO.hash_key (SHA-256) and "
            "validate_key; sajha/auth/access.py apikey_policy; docs/security/Security Model.md §1 'API keys'. "
            "The allowlist example is illustrative; fred_gdp and yf_fast_info are registry tools.",
        },
        {
            "kind": "mono",
            "kicker": "Step by step",
            "title": "Authorization: OAuth 2.1 with PKCE on /mcp",
            "band": "MCP client  →  SAJHA /mcp  +  authorization server",
            "lines": [
                "1. Client → POST /mcp without a token",
                "   └─ 401, WWW-Authenticate: Bearer resource_metadata=…",
                "2. Client → GET /.well-known/oauth-protected-resource/mcp",
                "   └─ Names the authorization server (SAJHA's or yours)",
                "3. Client → GET /oauth/authorize",
                "   ├─ code_challenge (PKCE S256), resource=<…/mcp>",
                "   └─ User signs in and consents → authorization code",
                "4. Client → POST /oauth/token { code, code_verifier }",
                "   └─ JWT access token, audience = SAJHA's /mcp;",
                "      a rotating refresh token",
                "5. Client → POST /mcp, Authorization: Bearer …",
                "   ├─ Signature, issuer, audience, expiry, scope",
                "   └─ Then the user's tool access, as for any caller",
            ],
            "source": "docs/protocol/OAuth Guide.md §1; sajha/routes/oauth_routes.py (PRM_PATH, /oauth/authorize, "
            "/oauth/token, /oauth/register, /oauth/jwks); sajha/auth/oauth/resource_server.py (WWW-Authenticate "
            "challenge).",
        },
        {
            "kind": "mono",
            "kicker": "Step by step",
            "title": "Authorization: the access and policy check on tools/call",
            "band": "Any client (HTTP, SSE, WebSocket, stdio, A2A)  →  SAJHA",
            "lines": [
                '1. Request: tools/call { name: "duckdb_sql", arguments }',
                "2. Who is calling",
                "   └─ Bearer JWT | X-API-Key | cookie | OAuth token | anonymous",
                "3. May they run it (sajha/auth/access.py)",
                "   ├─ Roles' execute patterns, or the key's mode",
                "   └─ No → access denied, recorded",
                "4. Arguments against the tool's JSON Schema → -32602 if not",
                "5. Policy engine (config/policies)",
                "   ├─ deny wins; require_approval waits for a person",
                "   ├─ Argument constraints, rate limits, quotas",
                "   └─ Not allow → an audit record",
                "6. Run: cache, circuit breaker, metrics",
                "7. Result: redaction and screening if a rule says so;",
                "   one hash-chained audit record",
            ],
            "source": "sajha/core/mcp_handler.py (has_tool_access before tools/call; -32602 on schema failure); "
            "sajha/tools/base_mcp_tool.py execute_with_tracking (policy enforce, validate_arguments, cache, circuit "
            "breaker); docs/architecture/Policy and Audit.md.",
        },
    ]


def _policy(F: dict[str, Any]) -> list[dict[str, Any]]:
    pol, aud, siem, fixes = F["policy"], F["audit"], F["siem"], F["fixes"]
    shortest = sorted((plain(f) for f in fixes), key=len)[:8]
    policy_src = (
        "Evaluated while the deck was built (tools/deck/evidence.py, policy_example): "
        "sajha.policy.engine.PolicyEngine.evaluate over the shipped files in config/policies, disabled examples "
        "included (include_disabled=True, as the Policies page's test bench offers); nothing was run."
    )
    return [
        {
            "kind": "split",
            "kicker": "Policy",
            "title": "A rule is a few lines of YAML, and it decides before the tool runs",
            "left_w": 0.46,
            "left": {"head": "config/policies/example-guardrails.yaml", "lines": _rule("sql-read-only")
                     + ["", "# deny wins over allow; a violated constraint", "# denies with the rule's name"]},
            "right": {
                "head": "The rule language",
                "items": [
                    ("Match", "Tool names and groups, annotations such as destructiveHint, the caller, the path, a "
                     "time window, argument values."),
                    ("Decide", "allow, deny with a reason, or require_approval; deny overrides; default_effect: deny "
                     "makes it an allowlist."),
                    ("Oblige", "Argument constraints, rate limits and quotas shared by every worker, redaction, "
                     "screening of results."),
                    ("Operate", "Files reload on change; every decision that is not allow is audited; the Policies "
                     "page has a test bench."),
                ],
            },
            "source": "The rule is read verbatim from config/policies/example-guardrails.yaml at build time (disabled in "
            "the shipped configuration). docs/architecture/Policy and Audit.md §3; sajha/policy/model.py, engine.py.",
        },
        {
            "kind": "table",
            "kicker": "Policy, evaluated",
            "title": "The shipped example policy, evaluated on four calls",
            "col_w": [1.0, 2.9, 1.3, 3.0],
            "rows": [["Caller", "Tool and arguments", "Decision", "Rule and reason"]]
            + [
                [
                    p["caller"],
                    f"{p['tool']} {js(p['args'])}",
                    p["effect"] + (f" + {', '.join(p['obligations'])}" if p["obligations"] else ""),
                    (p["rule"].split("/")[-1] + ": " if p["rule"] else "no deciding rule: ")
                    + (p["reason"] or "allowed; obligations still apply"),
                ]
                for p in pol
            ],
            "note": "The same engine sits in BaseMCPTool.execute_with_tracking, so these decisions are the same over "
            "MCP, REST, the command line or Ask SAJHA.",
            "source": policy_src,
        },
        {
            "kind": "canvas",
            "kicker": "Audit, tampered with",
            "title": "Change one stored field and the audit says which record and which field",
            "panels": [{"x": 0.0, "y": 0.0, "w": 0.47, "h": 1.0, "size": 13, "lines": [
                "# captured while building this deck",
                "# write a short chain, signed every 5 records",
                f"✓ verify: {aud['records']} records, {aud['anchors']} signed anchors, ok={aud['ok_before']}",
                "",
                "# change one stored outcome, deny -> ok",
                f"UPDATE audit_chain SET outcome='ok' WHERE seq={aud['seq']}",
                "",
                f"✗ verify: ok={aud['ok_after']}",
                *[ln for p in aud["problems"] for ln in wrap(p, 44)],
            ]}],
            "nodes": [
                *[{"id": f"r{i}", "text": f"record {n}", "sub": "hash over its fields and the previous hash" if i == 0 else
                   ("changed: its hash no longer matches" if n == aud["seq"] else "carries the previous record's hash"),
                   "x": 0.52, "y": 0.02 + i * 0.2, "w": 0.24, "h": 0.15, "style": "bad" if n == aud["seq"] else "white",
                   "size": 13} for i, n in enumerate(range(max(1, aud["seq"] - 1), max(1, aud["seq"] - 1) + 4))],
                {"id": "an", "text": "signed anchor", "sub": "the head, RS256, every N records, every few minutes, "
                 "at shutdown", "x": 0.81, "y": 0.38, "w": 0.19, "h": 0.25, "style": "dark", "size": 13},
                {"id": "vf", "text": "verify", "sub": "python -m sajha.audit verify, or the Audit page", "x": 0.81,
                 "y": 0.02, "w": 0.19, "h": 0.24, "style": "accent", "size": 13},
                {"id": "sx", "text": "SIEM export", "sub": f"{listing(siem['types'])} sinks, as "
                 f"{listing(f.upper() if f != 'ocsf' else 'OCSF' for f in siem['formats'])}", "x": 0.81, "y": 0.74,
                 "w": 0.19, "h": 0.25, "style": "box", "size": 13},
            ],
            "edges": [
                *[{"a": f"r{i}", "b": f"r{i + 1}", "color": "CRIMSON"} for i in range(3)],
                {"a": "r3", "b": "an", "mode": "c", "dash": True},
                {"a": "an", "b": "vf"},
            ],
            "note": "An edit, a deletion, an insertion or a reordering breaks the chain at the record where it happened.",
            "source": "Run while the deck was built (tools/deck/evidence.py, audit_example): sajha.audit.chain.ChainWriter "
            "on a temporary SQLite file with a throwaway RSA key, then sajha.audit.verify.verify before and after one "
            "UPDATE. SIEM: sajha/audit/sinks.py TYPES and FLAVORS, sajha/audit/formats.py FORMATS. The tampered record is "
            "drawn in red.",
            "talk": "Each record's SHA-256 covers its fields and the previous record's hash, so changing any stored field "
            "makes that record's hash wrong, and deleting, inserting or reordering records breaks the links. The head of the chain is signed with RS256 every "
            "N records, every few minutes and at shutdown. The verifier names the "
            "record and the field that changed, as the captured run on the left shows. Records stream to a SIEM over "
            f"{listing(siem['types'])} ({listing(siem['flavors'])}).",
        },
        {
            "kind": "stats",
            "kicker": "Evidence",
            "title": "Security fixes are listed, with where each one lives in the code",
            "intro": "The Security Model keeps a table of issues found and fixed since the last major release, each "
            "with the file that fixes it, and a list of known limitations.",
            "stats": [
                (str(len(fixes)), "issues found and fixed, each named with its fix and its file"),
                (str(len(F["limitations"])), "known limitations, listed so a deployment can compensate"),
            ],
            "rows": [["The shortest entries in the fixes table"]] + [[f] for f in shortest],
            "bold_col0": False,
            "source": "docs/security/Security Model.md, the 'Fixes since …' table and 'Known limitations', parsed at "
            "build time (evidence.security_fixes, limitations). The rows shown are the eight shortest, chosen "
            "mechanically.",
        },
    ]


def _deploy(F: dict[str, Any]) -> list[dict[str, Any]]:
    cf = F["conformance"]
    storage = [s.replace("AzureBlob", "Azure Blob").replace("Local", "local disk") for s in F["storage"]]
    return [
        {
            "kind": "cards",
            "kicker": "Deploy anywhere",
            "title": "On premises, in a private cloud or a public one: the same server",
            "cols": 3,
            "cards": [
                ("ON PREMISES", "Your data centre", "A VM with systemd and nginx, or Docker; air-gapped works with "
                 "the offline mock model, local tools and local data."),
                ("PRIVATE CLOUD", "Your VPC or VNet", "Kubernetes with the Helm chart, or containers; PostgreSQL and "
                 "an object store inside your network."),
                ("PUBLIC CLOUD", "Managed services", "ECS Fargate with RDS, S3 and Secrets Manager (a CDK recipe), "
                 "or any managed Kubernetes."),
            ],
            "items": [
                ("Data locality", "Data leaves your infrastructure only when a tool calls an outside service."),
                ("Sovereignty", "Run one instance per jurisdiction; nothing phones home."),
                ("Same configuration everywhere", f"Storage on {listing(storage, 'or')}; state in "
                 f"{listing(F['state'], 'or')}; environment over application.yml."),
            ],
            "items_h": 2.3,
            "source": f"Deployment recipes in deployment/ ({listing(F['recipes'])}, listed at build time); storage and "
            "state backends read at build time; docs/getting-started/Storage Guide.md; docs/architecture/Scaling "
            "and State.md.",
        },
        {
            "kind": "diagram",
            "kicker": "Reference architecture: public cloud",
            "title": "On AWS: Fargate tasks behind a load balancer, state in RDS",
            "groups": [
                {"id": "aws", "label": "AWS ACCOUNT · VPC", "x": 0.15, "y": 0.0, "w": 0.85, "h": 1.0},
                {"id": "ecs", "label": "ECS FARGATE · 1 TO 6 TASKS", "x": 0.41, "y": 0.1, "w": 0.32, "h": 0.5},
            ],
            "nodes": [
                {"id": "u", "text": "Users and AI agents", "x": 0.0, "y": 0.28, "w": 0.12, "h": 0.2, "style": "white"},
                {"id": "alb", "text": "Application load balancer", "sub": "TLS", "x": 0.18, "y": 0.28, "w": 0.19,
                 "h": 0.2, "style": "dark"},
                {"id": "app", "text": "SAJHA container", "sub": "non-root image, port 3002", "x": 0.43, "y": 0.28,
                 "w": 0.28, "h": 0.2, "style": "accent"},
                {"id": "sm", "text": "Secrets Manager", "sub": "JWT, session, DB, OAuth key", "x": 0.77, "y": 0.1,
                 "w": 0.21, "h": 0.17},
                {"id": "s3", "text": "S3", "sub": "tool and prompt configs", "x": 0.77, "y": 0.31, "w": 0.21,
                 "h": 0.17},
                {"id": "cw", "text": "CloudWatch", "sub": "logs, metrics, dashboard", "x": 0.77, "y": 0.52,
                 "w": 0.21, "h": 0.17},
                {"id": "rds", "text": "RDS PostgreSQL", "sub": "schema.sql run once; state.backend database",
                 "x": 0.41, "y": 0.72, "w": 0.32, "h": 0.2},
                {"id": "bed", "text": "Bedrock", "sub": "optional LLM provider", "x": 0.77, "y": 0.75,
                 "w": 0.21, "h": 0.17},
            ],
            "edges": [("u", "alb", "HTTPS"), ("alb", "app", ""), ("app", "s3", ""), ("ecs", "rds", "")],
            "note": "Several tasks share protocol state through RDS (or ElastiCache Redis); every task gets the same "
            "secrets from Secrets Manager. SAJHA never runs DDL on RDS: an operator runs the schema file once.",
            "source": "deployment/aws/README.md (architecture, 'Several tasks', 'What CDK Creates') and "
            "deployment/aws/cdk/sajha_stack.py (SAJHA_STATE_BACKEND=database). Drawn in the style of the earlier "
            "deck's AWS slide, with only what the recipe creates (no Cognito, API Gateway or WAF).",
        },
        {
            "kind": "diagram",
            "kicker": "Reference architecture: on premises",
            "title": "In your data centre: nginx in front, PostgreSQL behind, nothing external required",
            "groups": [
                {"id": "dc", "label": "YOUR DATA CENTRE", "x": 0.15, "y": 0.0, "w": 0.85, "h": 1.0},
                {"id": "host", "label": "VM (systemd) OR DOCKER", "x": 0.41, "y": 0.1, "w": 0.32, "h": 0.5},
            ],
            "nodes": [
                {"id": "u", "text": "Users and agents", "x": 0.0, "y": 0.28, "w": 0.12, "h": 0.2, "style": "white"},
                {"id": "ng", "text": "nginx", "sub": "TLS, proxy, streaming unbuffered", "x": 0.18, "y": 0.28,
                 "w": 0.19, "h": 0.2, "style": "dark"},
                {"id": "app", "text": "SAJHA", "sub": "127.0.0.1:3002", "x": 0.43, "y": 0.28, "w": 0.28,
                 "h": 0.2, "style": "accent"},
                {"id": "fs", "text": "Local disk", "sub": "config/, data/", "x": 0.77, "y": 0.1, "w": 0.21, "h": 0.17},
                {"id": "redis", "text": "Redis", "sub": "state, when several workers", "x": 0.77, "y": 0.31,
                 "w": 0.21, "h": 0.17},
                {"id": "obs", "text": "Prometheus · Grafana", "sub": "/metrics; OTLP traces", "x": 0.77, "y": 0.52,
                 "w": 0.21, "h": 0.17},
                {"id": "pg", "text": "PostgreSQL", "sub": "schema and seed files, run by an operator", "x": 0.41,
                 "y": 0.72, "w": 0.32, "h": 0.2},
                {"id": "siem", "text": "Your SIEM", "sub": "syslog or HTTP audit export", "x": 0.77, "y": 0.75,
                 "w": 0.21, "h": 0.17},
            ],
            "edges": [("u", "ng", "HTTPS"), ("ng", "app", ""), ("app", "redis", ""), ("host", "pg", "")],
            "note": "Air-gapped: the offline mock model, the calculators, DuckDB and your own databases all work "
            "without the internet; tools that call outside services are simply not used.",
            "source": "deployment/baremetal/README.md (nginx, systemd, PostgreSQL), deployment/baremetal/nginx.conf; "
            "deployment/observability/ (Prometheus, Grafana dashboard, alerts); sajha/audit/sinks.py; "
            "docs/architecture/Scaling and State.md. 'Your data centre' replaces the earlier deck's named data centre.",
        },
        {
            "kind": "stats",
            "kicker": "Production readiness",
            "title": "Production readiness, in facts the build can check",
            "intro": "No load-test figures are claimed here: none has been measured and recorded. These are counted "
            "from the repository when the deck is built.",
            "stats": [
                (str(F["tests"]), "automated tests"),
                (str(cf["passed"]), "conformance checks passed, 0 failed"),
                (str(len(F["tables"])), "tables in each of the two schema files"),
                (str(len(F["helm"])), "templates in the Helm chart"),
            ],
            "items": [
                ("Kubernetes", "HPA, disruption budget, network policy, ServiceMonitor; several replicas need the redis "
                 "or database state backend."),
                ("Several workers", "Sessions, tasks, OAuth codes, counters and approvals are shared; caches and "
                 "circuit breakers stay per process on purpose."),
                ("Operated", "Prometheus /metrics, OpenTelemetry traces, usage and cost dashboard, alert rules, "
                 "health at /health."),
            ],
            "source": "Tests: pytest --collect-only. Conformance: docs/protocol/MCP 2026-07-28 Compliance.md §5. Tables: "
            "db/scripts/postgresql/schema.sql and sqlite/schema.sql (same set, checked at build time). Helm: "
            "charts/sajha/templates/*.yaml. The earlier deck's '100+ users, 1,000+ rps, <200 ms p95' were never "
            "measured and are not carried over.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _overview(F) + _architecture(F) + _access(F) + _flows(F) + _policy(F) + _deploy(F)
