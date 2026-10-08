"""
The deck, as data. Section 3: the SAJHA MCP server itself -- what it is, what is in the
box, how tools are made, how it is built, who may call it and how each caller proves who
it is (step by step), the rules and the record, and where it runs.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from evidence import ROOT, SourceChanged
from diagrams import row, seq
from prose import js, listing, plain, wrap

# Tool groups, by what they are for. A group the live registry has and this map does not
# fails the build, so a new provider cannot silently drop off the slide.
CATEGORIES = [
    ("Markets and equities", ("fmp", "openbb", "av", "yf", "yahoo", "cg"), "Quotes, statements, crypto, indices"),
    ("Central banks", ("fred", "fed", "ecb", "boc", "boj", "pboc", "rbi", "bdf"),
     "Policy rates, yields, money supply"),
    ("International bodies", ("imf", "wb", "un"), "Outlooks, development and trade data"),
    ("Filings and reports", ("edgar", "sec", "ir"), "Filings, facts, insider trades, reports"),
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


# Studio creators by family; a creator the Studio has and this map does not fails the build.
FAMILIES = [
    ("Code", ("python", "script")),
    ("Services", ("rest", "api_import")),
    ("Data and BI", ("dbquery", "olap", "powerbi", "powerbidax")),
    ("Documents", ("sharepoint", "livelink")),
    ("A sentence", ("describe",)),
]


def _overview_canvas(F: dict[str, Any], catalog_src: str, n_versions: int) -> dict[str, Any]:
    """Many ways in, one catalog, one address, one set of rules, every caller."""
    cat, eras = F["catalog"], F["eras"]
    srcs = ["Built-in tools", f"{len(F['studio_pages'])} MCP Studio creators", "API import, data connectors",
            "Proxied MCP servers", "SAJHA Net members"]
    callers = ["MCP clients, both eras", "Console and Ask SAJHA", "Agents, workflows, A2A"]
    nodes = [{"id": f"s{i}", "text": t, "x": 0.0, "y": 0.02 + i * 0.2, "w": 0.19, "h": 0.15, "style": "white",
              "size": 13} for i, t in enumerate(srcs)]
    nodes += [{"id": f"c{i}", "text": t, "x": 0.84, "y": 0.12 + i * 0.27, "w": 0.16, "h": 0.2, "style": "white",
               "shape": "oval", "size": 12} for i, t in enumerate(callers)]
    nodes += [
        {"id": "cat", "text": "One catalog", "sub": f"{cat['tools']} tools in {cat['groups']} groups when this deck "
         "was built", "x": 0.26, "y": 0.27, "w": 0.18, "h": 0.4, "style": "accent", "size": 18},
        {"id": "rules", "text": "One set of rules", "sub": "identity, access, policy, approvals, audit", "x": 0.49,
         "y": 0.27, "w": 0.15, "h": 0.4, "style": "dark", "shape": "hex", "size": 15},
        {"id": "mcp", "text": "One address", "sub": f"/mcp: {n_versions} protocol versions, four transports",
         "x": 0.68, "y": 0.27, "w": 0.12, "h": 0.4, "style": "navy", "size": 15},
    ]
    edges = [{"a": f"s{i}", "b": "cat", "ports": ("r", "l"), "at": (0.5, 0.1 + 0.2 * i)} for i in range(len(srcs))]
    edges += [{"a": "cat", "b": "rules", "color": "CRIMSON", "width": 2.2},
              {"a": "rules", "b": "mcp", "color": "CRIMSON", "width": 2.2}]
    edges += [{"a": "mcp", "b": f"c{i}", "ports": ("r", "l"), "at": (0.2 + 0.3 * i, 0.5), "both": True}
              for i in range(len(callers))]
    return {
        "kind": "canvas",
        "kicker": "Overview",
        "title": "One catalog of tools, one address, one set of rules",
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.22, "y": 0.8, "w": 0.6, "h": 0.18, "size": 12, "color": "SLATE", "text":
                   "A production Python MCP server on FastAPI, with its own intelligence layer and browser tool "
                   f"builders; {F['tests']} automated tests in the suite."}],
        "source": catalog_src + f" Protocol versions: sajha.core.mcp_modern ({listing(eras['modern'])}; "
        f"{listing(eras['handshake'])}). Tests: pytest --collect-only over tests and clientsdk/tests at build time.",
        "talk": "SAJHA is one shared catalog. Tools arrive from many places: the built-in set, the browser creators, "
        "imported APIs and data connectors, other MCP servers it proxies, and other SAJHA servers in a net. Whatever "
        "their origin, they sit in one catalog behind one set of rules, identity, access, policy, approvals and "
        "audit, and are served at one address, /mcp, to every kind of caller. Shared means a tool is built, governed "
        "and recorded once; governed means every call passes the same checks; self-hosted means it runs where your "
        "data is, from one process on a laptop to several pods on Kubernetes.",
    }


def _tools_bars(F: dict[str, Any], catalog_src: str) -> dict[str, Any]:
    """Tools per category as native bars, longest first as the registry has them."""
    rows = _categories(F)[1:]
    top = max(int(r[2]) for r in rows)
    rh = 1.0 / len(rows)
    nodes, texts = [], []
    for i, (name, groups, n, what) in enumerate(rows):
        y = i * rh
        texts.append({"x": 0.0, "y": y + rh * 0.08, "w": 0.235, "h": rh * 0.84, "text": name, "bold": True,
                      "color": "INK", "size": 14, "floor": 11})
        nodes.append({"id": f"b{i}", "text": n, "x": 0.24, "y": y + rh * 0.14, "w": max(0.04, 0.32 * int(n) / top),
                      "h": rh * 0.72, "style": "accent", "size": 12})
        texts.append({"x": 0.59, "y": y + rh * 0.08, "w": 0.41, "h": rh * 0.84, "text": f"{what}  ·  {groups}",
                      "size": 11.5, "floor": 11, "color": "SLATE"})
    cat = F["catalog"]
    return {
        "kind": "canvas",
        "kicker": "Tools in the box",
        "title": f"{cat['tools']} built-in tools, from market data to calculators",
        "nodes": nodes,
        "texts": texts,
        "note": "The live list is tools/list or the Tools page; a caller sees only the tools it may run.",
        "source": catalog_src + " Grouping into categories: tools/deck/deck_part2.py CATEGORIES; a group it "
        "does not name fails the build. Bar lengths are proportional to the tool counts.",
        "talk": "Each bar is a category of built-in tools, with its length the number of tools, counted from the "
        "registry when this deck was built. Market and equity data and central banks are the largest families; "
        "filings, international bodies, analytics, search, documents and connected accounts follow. All of them are "
        "ordinary MCP tools with JSON Schemas, and a caller only ever sees the ones its role or key allows.",
    }


def _studio(F: dict[str, Any], creators: list[str]) -> dict[str, Any]:
    """Every creator, by family, converging on one preview, one deploy and one catalog."""
    known = {c for _f, cs in FAMILIES for c in cs}
    if set(creators) - known:
        raise SourceChanged(f"Studio creators with no family on the deck: {sorted(set(creators) - known)}")
    groups, nodes, edges = [], [], []
    live = [(f, [c for c in cs if c in creators]) for f, cs in FAMILIES]
    live = [(f, cs) for f, cs in live if cs]
    rh = 1.0 / len(live)
    for i, (fam, cs) in enumerate(live):
        y = i * rh
        groups.append({"id": f"g{i}", "x": 0.0, "y": y + 0.01, "w": 0.124 + len(cs) * 0.109, "h": rh - 0.03,
                       "line": "RULE"})
        nodes.append({"id": f"f{i}", "text": fam, "x": 0.008, "y": y + 0.025, "w": 0.1, "h": rh - 0.06,
                      "style": "soft", "size": 12})
        for k, c in enumerate(cs):
            nodes.append({"id": f"n{i}_{k}", "text": CREATORS[c][0], "x": 0.118 + k * 0.109, "y": y + 0.025,
                          "w": 0.103, "h": rh - 0.06, "style": "white", "size": 11})
        edges.append({"a": f"g{i}", "b": "pre", "ports": ("r", "l"), "at": (0.5, (i + 0.5) / len(live)),
                      "width": 1.2})
    nodes += [
        {"id": "pre", "text": "Preview", "sub": "the JSON Schema generated; drafts tested and reviewed", "x": 0.64,
         "y": 0.3, "w": 0.15, "h": 0.36, "style": "dark", "size": 15},
        {"id": "dep", "text": "Deploy", "sub": "into the running server; no restart", "x": 0.85, "y": 0.06, "w": 0.15,
         "h": 0.3, "style": "accent", "shape": "hex", "size": 15},
        {"id": "cl", "text": "tools/list", "sub": "under each caller's access", "x": 0.85, "y": 0.62, "w": 0.15,
         "h": 0.3, "style": "white", "shape": "oval", "size": 14},
    ]
    edges += [{"a": "pre", "b": "dep", "mode": "c", "color": "CRIMSON"}, {"a": "dep", "b": "cl", "color": "CRIMSON"}]
    return {
        "kind": "canvas",
        "kicker": "MCP Studio",
        "title": f"MCP Studio: {len(creators)} ways to create a tool in the browser",
        "groups": groups,
        "nodes": nodes,
        "edges": edges,
        "note": "Each creator deploys into the running server, with no restart; generated code and scripts run "
        "in the sandbox.",
        "source": "The Studio pages served by sajha/routes/studio_routes.py (@pages.get), plus Describe a tool "
        "(describe_routes.py) and Import an API (api_import_routes.py), read at build time; the decorator is "
        "sajha/studio/decorator.py (sajhamcptool). docs/studio/MCP Studio User Guide.md. Families: "
        "tools/deck/deck_part2.py FAMILIES (a creator it does not name fails the build).",
        "talk": " ".join(f"{name}: {what}" for name, what in (CREATORS[c] for c in creators)) + " Whichever creator "
        "is used, the result is previewed with its generated schema, deployed into the running server, and listed "
        "to every caller allowed to see it.",
    }


def _console(F: dict[str, Any]) -> dict[str, Any]:
    """The console as a browser window: the menus as the template defines them, and what every page has."""
    menus = F["menus"]
    xs = row(len(menus), 0.13, 0.99, 0.135)
    nodes = [{"id": "brand", "text": "SAJHA", "x": 0.012, "y": 0.1, "w": 0.1, "h": 0.12, "style": "accent",
              "size": 14}]
    edges = []
    for i, (m, cols) in enumerate(menus):
        nodes += [
            {"id": f"m{i}", "text": m, "x": xs[i], "y": 0.1, "w": 0.135, "h": 0.12, "style": "dark", "size": 13},
            {"id": f"c{i}", "text": "\n".join(cols), "x": xs[i], "y": 0.32, "w": 0.135, "h": 0.3, "style": "white",
             "size": 12, "bold": False},
        ]
        edges.append({"a": f"m{i}", "b": f"c{i}", "dash": True})
    nodes += [
        {"id": "pg", "text": f"{F['pages']} pages", "sub": "each with an About this page panel", "x": 0.03, "y": 0.72,
         "w": 0.22, "h": 0.2, "style": "accent", "size": 16},
        {"id": "hp", "text": "Help in the app", "sub": "every guide in docs/, the glossary, page help", "x": 0.28,
         "y": 0.72, "w": 0.22, "h": 0.2, "style": "soft", "size": 14},
        {"id": "rl", "text": "Menus follow the role", "sub": "Admin for administrators; Studio for those with "
         "Studio rights", "x": 0.53, "y": 0.72, "w": 0.22, "h": 0.2, "style": "soft", "size": 14},
        {"id": "th", "text": "Any screen", "sub": "works on a phone; light, dark, blue and green themes", "x": 0.78,
         "y": 0.72, "w": 0.2, "h": 0.2, "style": "soft", "size": 14},
    ]
    return {
        "kind": "canvas",
        "kicker": "Web console",
        "title": f"A web console of {F['pages']} pages, each with its own help",
        "groups": [{"id": "win", "label": "", "x": 0.0, "y": 0.0, "w": 1.0, "h": 0.66, "line": "RULE", "fill": "PARCH"}],
        "nodes": nodes,
        "edges": edges,
        "source": "Page count: sajha.web.page_help.PAGE_HELP (pages with an 'About this page' panel, the error page "
        "excluded), read at build time. Menus and their columns: the menu data in "
        "sajha/web/templates/common/_nav.html, parsed at build time (evidence.console_menus); the Admin menu needs "
        "the admin role and MCP Studio Studio rights. Themes: sajha/web/static/css/tokens.css. "
        "docs/architecture/Architecture.md §10.",
        "talk": "The console's top menu is drawn here as the template defines it, with each menu's columns beneath. "
        "Tools is where people browse, run and monitor tools; AI holds Ask SAJHA, conversations, models and prompts; "
        "SAJHA Net shows the instances and remote tools a user may reach; MCP Studio holds every creator, the "
        "composite builder and workflows; Admin manages users, keys, proxied servers, connectors, policies, "
        "approvals, the audit and operations; Help renders every guide and the glossary inside the app. Every page "
        "has an About this page panel whose terms come from the glossary.",
    }


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
        _overview_canvas(F, catalog_src, n_versions),
        {
            "kind": "bullets",
            "kicker": "Why SAJHA",
            "title": "What makes SAJHA different from a plain tool server",
            "talk": "A plain MCP server is a pipe from a client to some functions. SAJHA adds governance on "
                "every call, a large catalog from day one, ways to build tools from zero code to full "
                "code, its own intelligence layer, both protocol eras and four transports with "
                "conformance evidence, a net of servers across boundaries, and it runs wherever your data"
                " is.",
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
        _tools_bars(F, catalog_src),
        _studio(F, creators),
        {
            "kind": "flow",
            "kicker": "Describe a tool",
            "title": "A sentence becomes a proposal, and nothing deploys without a person",
            "talk": "Describe a tool turns a sentence into a proposal. The toolsmith model drafts the kind, "
                "name, schemas, implementation and test cases. SAJHA treats the draft as untrusted: SQL "
                "must be read-only, hosts are checked, credentials are refused and risky imports are "
                "flagged. The tests run in the sandbox, bound to the draft's hash, and an administrator "
                "approves that exact hash; policy can require a second approver. Out of the box the "
                "toolsmith is an offline mock that knows a few shapes; real designs need a real model.",
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
            "talk": "Read top to bottom as a request travels. Clients of every kind come in over the "
                "transports. Every call then crosses the governance layer: authentication, the tool "
                "access policy, the policy engine and the audit. Below it sit the intelligence layer and "
                "the tools layer, with composites, workflows, federation, connectors and the sandbox, and"
                " at the bottom the platform: FastAPI, the database, the state store, storage, metrics "
                "and traces.",
            "nodes": nodes,
            "source": f"sajha/app.py (FastAPI application), sajha/routes/ ({F['routes']} route modules), sajha/auth/, "
            "sajha/policy/, sajha/audit/, sajha/ai/, sajha/tools/, sajha/workflows/, sajha/federation/, "
            "sajha/connectors/, sajha/sandbox/; state, storage and schema lists read at build time. "
            "docs/architecture/Architecture.md.",
        },
        _console(F),
        {
            "kind": "diagram",
            "kicker": "Parallel SDLC",
            "title": "Tool developers and AI developers ship independently",
            "talk": "Two teams, two release cycles. Tool developers build, test and deploy tools, and hot "
                "reload puts them live. AI developers design agents, evaluate them on golden questions "
                "and iterate. The tool's schema is the contract between them, held by SAJHA, so neither "
                "team waits for the other.",
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
        _rbac(role_rows),
        _layers(),
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


def _rbac(role_rows: list[list[str]]) -> dict[str, Any]:
    """Every kind of caller, its rights, one policy, the tools."""
    callers = role_rows[1:]
    rh = 1.0 / len(callers)
    nodes = []
    for i, (who, rights, what) in enumerate(callers):
        nodes.append({"id": f"r{i}", "text": f"{who}: {what}", "sub": rights, "x": 0.0, "y": i * rh + 0.012,
                      "w": 0.46, "h": rh - 0.024, "style": "white" if who.startswith("Role") else "box", "size": 12})
    nodes += [
        {"id": "ap", "text": "One access policy", "sub": "sajha/auth/access.py: read lets a caller see a tool, "
         "execute lets it run one; fnmatch patterns such as fred_*", "x": 0.55, "y": 0.25, "w": 0.22, "h": 0.5,
         "style": "accent", "size": 15},
        {"id": "t", "text": "tools", "sub": "tools/list shows only what may be seen", "x": 0.85, "y": 0.35, "w": 0.15,
         "h": 0.3, "style": "white", "shape": "oval", "size": 15},
    ]
    edges = [{"a": f"r{i}", "b": "ap", "ports": ("r", "l"), "at": (0.5, (i + 0.5) / len(callers)), "width": 1.2}
             for i in range(len(callers))]
    edges.append({"a": "ap", "b": "t", "color": "CRIMSON", "width": 2.2})
    return {
        "kind": "canvas",
        "kicker": "Role-based access control",
        "title": "Tool-level permissions, checked on every call, on every path",
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.55, "y": 0.8, "w": 0.45, "h": 0.2, "size": 12, "text": "The same policy on REST, MCP in "
                   "both eras, SSE, WebSocket, stdio and A2A."}],
        "source": "Seeded roles and permissions: db/scripts/sqlite/seed.sql, parsed at build time. API key modes and "
        "anonymous policy: sajha/auth/access.py; docs/security/Security Model.md §1 'Tool access'.",
        "talk": "On the left is every kind of caller SAJHA knows: the roles the database is seeded with, with their "
        "rights, then API keys and anonymous callers. A role's permissions name a resource type, a pattern and "
        "actions: read lets a caller see a tool, execute lets it run one. An API key carries its own tool access "
        "mode, all, an allowlist, a denylist or a regular expression, and is never an administrator. Anonymous "
        "callers get nothing unless an operator lists tools for them. One module applies this policy on every path "
        "into the server.",
    }


def _layers() -> dict[str, Any]:
    """Eight layers a call meets, each with the threat it answers."""
    layers = [
        ("Transport", "Origin allow-list on /mcp; HTTPS at the proxy; HSTS, CSP", "DNS rebinding, interception"),
        ("Sign-in", "Per-IP throttling and account lockout", "Password guessing"),
        ("Authentication", "Cookie, single sign-on, revocable JWT, API keys, OAuth 2.1", "Unknown callers"),
        ("Authorization", "Role permissions and key modes, per tool, every path", "Privilege escalation"),
        ("Input", "JSON Schema on every call; SQL guards; SSRF guard", "Injection, internal-network access"),
        ("Policy", "Deny, approval, argument limits, rate limits, quotas, redaction", "Unsafe or excessive calls"),
        ("Code", "Studio code and scripts in a per-call sandbox", "Untrusted code"),
        ("Record", "Hash-chained, signed audit; SIEM export", "Undetected tampering"),
    ]
    xs = row(4, 0.0, 1.0, 0.22)
    nodes, edges = [], []
    for i, (name, how, threat) in enumerate(layers):
        first = i < 4
        x = xs[i] if first else xs[7 - i]  # the second row runs back, right to left
        ly, ty = (0.12, 0.0) if first else (0.58, 0.88)
        nodes += [
            {"id": f"l{i}", "text": name, "sub": how, "x": x, "y": ly, "w": 0.22, "h": 0.28,
             "style": "dark" if i % 2 else "accent", "size": 16},
            {"id": f"t{i}", "text": "answers: " + threat, "x": x + 0.02, "y": ty, "w": 0.18, "h": 0.1, "style": "warn",
             "size": 12, "bold": False},
        ]
        if i:
            edges.append({"a": f"l{i - 1}", "b": f"l{i}", "color": "CRIMSON", "width": 2.0})
    return {
        "kind": "canvas",
        "kicker": "Enterprise security",
        "title": "Security in layers, each with the threat it answers",
        "nodes": nodes,
        "edges": edges,
        "note": "Rate limits on tool calls come from policy rules; /mcp itself has no built-in request rate limit.",
        "source": "docs/security/Security Model.md §1–§3 (credentials, tool access, transport protections, rate "
        "limiting: 'per-user and per-key limits exist but are not called'), §5, §7; "
        "docs/architecture/Policy and Audit.md.",
        "talk": "Read left to right as a call travels. The transport layer refuses browsers from unknown origins and "
        "relies on TLS at the proxy. Sign-in throttles guesses and locks accounts. Authentication establishes who is "
        "calling, by cookie, single sign-on, a revocable SAJHA token, an API key or OAuth. Authorization decides per "
        "tool. Input is checked against the tool's schema, SQL is guarded and outbound requests pass an SSRF guard. "
        "Policy rules can deny, require approval, limit arguments and rates, and redact. User code runs in a "
        "sandbox. And everything is recorded in a hash-chained, signed audit. Note the honest limit: request rate "
        "limits come from policy rules, not from /mcp itself.",
    }


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


def _seq_slide(title: str, actors: list[tuple[str, str]], steps: list[Any], source: str, talk: str,
               lane_w: float = 0.17, size: float = 12.5, lsize: float = 11.5) -> dict[str, Any]:
    groups, nodes, edges = seq(actors, steps, 0.0, 1.0, lane_w, top=0.08, size=size, lsize=lsize)
    return {"kind": "canvas", "kicker": "Step by step", "title": title, "groups": groups, "nodes": nodes,
            "edges": edges, "source": source, "talk": talk}


def _flows(F: dict[str, Any]) -> list[dict[str, Any]]:
    bad = {"color": "BAD"}
    cookie = _seq_slide(
        "Authentication: the session cookie (web console)",
        [("b", "Browser"), ("s", "SAJHA server"), ("d", "Users table")],
        [
            {"a": "b", "b": "s", "label": "1  GET /login"},
            {"a": "s", "b": "b", "label": "the sign-in form"},
            {"a": "b", "b": "s", "label": "2  POST /login {user_id, password}"},
            {"on": "s", "text": "per-IP throttle: too many failures → 429", "w": 0.42},
            {"a": "s", "b": "d", "label": "check the password"},
            {"on": "s", "text": "repeated failures lock the account → 423", "style": "warn", "w": 0.42},
            {"a": "s", "b": "b", "label": "Set-Cookie sajha_token; 302", "color": "CRIMSON"},
            {"a": "b", "b": "s", "label": "3  every later request, with the cookie"},
            {"on": "s", "text": "checked: signature, algorithm, expiry", "w": 0.42},
            {"a": "s", "b": "d", "label": "reload the user every time"},
        ],
        "sajha/routes/auth_routes.py (login_form, _set_session_cookie); sajha/auth/password.py "
        "(verify_password accepts plain or bcrypt; auth.credential_storage); "
        "sajha/security.py (login throttle); docs/security/Security Model.md §1 'Web login', 'Session cookie'.",
        "The browser asks for the sign-in form and posts a user id and password. Before checking, SAJHA throttles "
        "by address: too many failures answer 429. The password is compared with the stored value, plain by "
        "default or a bcrypt hash under hashed storage, and repeated failures lock the account, answering 423. On "
        "success SAJHA issues a SAJHA JWT, 60 minutes and HS256 by default, sets it as the sajha_token cookie, "
        "HttpOnly, SameSite=Lax and Secure on https, and redirects to the dashboard, only ever to a local path. On "
        "every later request the cookie is read last, after a Bearer token and an API key; its signature, algorithm "
        "and expiry are checked, and the user is reloaded from the database, so a disabled user is out at once.",
    )
    jwt = _seq_slide(
        "Authentication: the SAJHA JWT (API clients)",
        [("c", "API client"), ("a", "SAJHA: authenticate"), ("p", "Access policy and tools")],
        [
            {"a": "c", "b": "a", "label": "1  POST /api/auth/login"},
            {"on": "a", "text": "throttle and lockout, as for the web form", "w": 0.42},
            {"a": "a", "b": "c", "label": "invalid → 401; locked → 423", **bad, "dash": True},
            {"a": "a", "b": "c", "label": "2  {token: eyJ…, user: {roles …}}", "color": "CRIMSON"},
            {"a": "c", "b": "a", "label": "3  Authorization: Bearer eyJ…"},
            {"on": "a", "text": "signature, allowed algorithm, exp", "w": 0.42},
            {"on": "a", "text": "claims: sub, roles, iss sajha-mcp-server", "w": 0.42},
            {"a": "a", "b": "p", "label": "4  the caller's tool access"},
            {"on": "p", "text": "REST, /mcp, and /mcp/ws?token=…", "style": "soft", "w": 0.34},
        ],
        "sajha/routes/auth_routes.py api_login; sajha/auth/jwt_handler.py; sajha/auth/__init__.py "
        "authenticate_request; docs/security/Security Model.md §1 'SAJHA JWT'.",
        "A script posts a user id and password to /api/auth/login. The same throttle and lockout as the web form "
        "apply: invalid credentials answer 401, a locked account 423. A valid login returns a token and the user "
        "with their roles. The client then sends the token as a Bearer header on every request; SAJHA checks its "
        "signature, that its algorithm is the allowed one, its expiry, and its claims: subject, roles and the "
        "issuer sajha-mcp-server. Then the caller's tool access applies, the same on REST, /mcp, and the WebSocket "
        "endpoint, which takes the token as a query parameter.",
    )
    key = _seq_slide(
        "Authentication: the API key (automation)",
        [("g", "Script or agent"), ("s", "SAJHA server"), ("ad", "Administrator")],
        [
            {"a": "ad", "b": "s", "label": "1  create a key, in the console"},
            {"on": "s", "text": "sja_ + 48 hex; its SHA-256 and prefix stored (raw too under plain storage)", "w": 0.42},
            {"on": "s", "text": "tool access mode: all, allowlist, denylist or regex", "w": 0.42},
            {"a": "g", "b": "s", "label": "2  X-API-Key: sja_…"},
            {"on": "s", "text": "keys file, then database, then dump; unknown, disabled or expired → refused", "style": "warn", "w": 0.42},
            {"on": "s", "text": "signs in as its owner (owner's roles; key's tool list as a ceiling)", "w": 0.42},
            {"a": "g", "b": "s", "label": "3  tools/call fred_gdp"},
            {"a": "s", "b": "g", "label": "allowlist fred_*, calc_*: the result", "color": "CRIMSON"},
            {"a": "g", "b": "s", "label": "tools/call yf_fast_info"},
            {"a": "s", "b": "g", "label": "403: not listed", **bad},
        ],
        "sajha/routes/apikeys_routes.py; sajha/auth/__init__.py AuthManager.authenticate_apikey; "
        "sajha/db/dao/__init__.py ApiKeyDAO.hash_key (SHA-256); sajha/auth/access.py apikey_policy; docs/security/Security Model.md §1 'API keys'. "
        "The allowlist example is illustrative; fred_gdp and yf_fast_info are registry tools.",
        "An administrator creates a key in the console. The key is sja_ followed by 48 hexadecimal characters; SAJHA "
        "stores its SHA-256 for lookup and an 8-character prefix for display, and under plain storage, the default, "
        "the raw key too. The key carries a tool access mode: all tools, an allowlist, a denylist or a regular "
        "expression. A script sends it as X-API-Key, or as an Authorization header starting sja_. An unknown, "
        "disabled or expired key is refused. SAJHA looks the key up in the administrators' keys file first, then the "
        "database, then the database dump. A key with an owner signs in as that user, with the user's roles and the "
        "key's tool list as a ceiling; an older key without an owner becomes the identity apikey: and its name, with "
        "the role api_consumer. With an allowlist of fred_* and calc_*, fred_gdp runs and "
        "yf_fast_info is refused with 403. Usage is recorded and every call audited.",
    )
    oauth = _seq_slide(
        "Authorization: OAuth 2.1 with PKCE on /mcp",
        [("as", "Authorization server"), ("c", "MCP client"), ("r", "SAJHA /mcp")],
        [
            {"a": "c", "b": "r", "label": "1  POST /mcp, no token"},
            {"a": "r", "b": "c", "label": "401, WWW-Authenticate: resource_metadata", **bad, "dash": True},
            {"a": "c", "b": "r", "label": "2  GET protected-resource metadata"},
            {"a": "r", "b": "c", "label": "names the authorization server"},
            {"a": "c", "b": "as", "label": "3  /oauth/authorize, PKCE S256, resource"},
            {"on": "as", "text": "the user signs in and consents", "style": "soft", "w": 0.3},
            {"a": "as", "b": "c", "label": "an authorization code"},
            {"a": "c", "b": "as", "label": "4  /oauth/token {code, code_verifier}"},
            {"a": "as", "b": "c", "label": "access token for /mcp; refresh token", "color": "CRIMSON"},
            {"a": "c", "b": "r", "label": "5  POST /mcp, Bearer token", "color": "CRIMSON"},
            {"on": "r", "text": "signature, issuer, audience, expiry, scope; then tool access", "w": 0.42},
        ],
        "docs/protocol/OAuth Guide.md §1; sajha/routes/oauth_routes.py (PRM_PATH, /oauth/authorize, "
        "/oauth/token, /oauth/register, /oauth/jwks); sajha/auth/oauth/resource_server.py (WWW-Authenticate "
        "challenge).",
        "A client that calls /mcp without a token gets 401 with a WWW-Authenticate header pointing at the "
        "protected-resource metadata, at /.well-known/oauth-protected-resource/mcp, which names the authorization "
        "server: SAJHA's own or yours. The client starts the authorization-code flow with a PKCE S256 challenge and "
        "the resource indicator for SAJHA's /mcp; the user signs in and consents, and the client receives a code. It "
        "exchanges the code and its verifier for a JWT access token whose audience is SAJHA's /mcp, and a rotating "
        "refresh token. Then it calls /mcp with the Bearer token; SAJHA checks signature, issuer, audience, expiry "
        "and scope, and the user's tool access applies as for any caller.",
        lane_w=0.15,
    )
    stages = [
        ("req", "tools/call", "duckdb_sql, arguments", "white", "round"),
        ("who", "Who is calling?", "JWT, API key, cookie, OAuth token or anonymous", "box", "round"),
        ("may", "Access?", "roles' patterns or the key's mode", "gold", "diamond"),
        ("val", "Valid?", "arguments against the JSON Schema", "gold", "diamond"),
        ("pol", "Policy?", "config/policies", "gold", "diamond"),
        ("run", "Run", "cache, circuit breaker, metrics", "accent", "round"),
        ("res", "Result", "redaction and screening if a rule says so", "dark", "round"),
    ]
    xs = row(len(stages), 0.0, 1.0, 0.125)
    nodes = []
    for k, (i, t, sub, style, shape) in enumerate(stages):
        dia = shape == "diamond"
        nodes.append({"id": i, "text": t, "sub": "" if dia else sub, "x": xs[k], "y": 0.12 if dia else 0.17,
                      "w": 0.125, "h": 0.36 if dia else 0.26, "style": style, "shape": shape,
                      "size": 12 if dia else 13})
        if dia:
            nodes.append({"id": f"{i}_s", "text": sub, "x": xs[k], "y": 0.0, "w": 0.125, "h": 0.1, "style": "white",
                          "size": 10, "bold": False, "shape": "rect"})
    exits = [("may", "access denied, recorded"), ("val", "error -32602"),
             ("pol", "deny with a reason, or wait for approval; audited")]
    for i, t in exits:
        k = [s[0] for s in stages].index(i)
        nodes.append({"id": f"{i}_x", "text": t, "x": xs[k], "y": 0.62, "w": 0.125, "h": 0.17, "style": "bad",
                      "size": 11, "bold": False})
    nodes.append({"id": "aud", "text": "one hash-chained audit record, whatever happened", "x": 0.43, "y": 0.86,
                  "w": 0.57, "h": 0.12, "style": "line", "size": 13})
    edges = [{"a": stages[k][0], "b": stages[k + 1][0], "color": "CRIMSON"} for k in range(len(stages) - 1)]
    edges += [{"a": i, "b": f"{i}_x", "label": "no", "lsize": 10, "lcolor": "BAD", "litalic": False, "lbold": True}
              for i, _t in exits]
    edges.append({"a": "res", "b": "aud"})
    check = {
        "kind": "canvas",
        "kicker": "Step by step",
        "title": "Authorization: the access and policy check on tools/call",
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.0, "y": 0.86, "w": 0.42, "h": 0.12, "size": 11, "italic": True, "text": "Any client: "
                   "HTTP, SSE, WebSocket, stdio, A2A. deny wins over allow."}],
        "source": "sajha/core/mcp_handler.py (has_tool_access before tools/call; -32602 on schema failure); "
        "sajha/tools/base_mcp_tool.py execute_with_tracking (policy enforce, validate_arguments, cache, circuit "
        "breaker); docs/architecture/Policy and Audit.md.",
        "talk": "Every tools/call takes this path, whichever transport it came on. First SAJHA establishes who is "
        "calling: a Bearer JWT, an API key, the cookie, an OAuth token, or nobody. Then the access policy decides "
        "whether that caller may run this tool; if not, access is denied and recorded. The arguments are validated "
        "against the tool's JSON Schema, and a failure answers -32602. The policy engine then applies the rules: "
        "deny wins, require_approval waits for a person, and argument constraints, rate limits and quotas apply; "
        "any decision other than allow is audited. Only then does the tool run, through its cache and circuit "
        "breaker, and the result can be redacted or screened if a rule says so.",
    }
    return [cookie, jwt, key, oauth, check]


def _policy(F: dict[str, Any]) -> list[dict[str, Any]]:
    pol, aud, siem, fixes = F["policy"], F["audit"], F["siem"], F["fixes"]
    shortest = sorted((plain(f) for f in fixes), key=len)[:8]
    policy_src = (
        "Evaluated while the deck was built (tools/deck/evidence.py, policy_example): "
        "sajha.policy.engine.PolicyEngine.evaluate over the shipped files in config/policies, disabled examples "
        "included (include_disabled=True, as the Policies page's test bench offers); nothing was run."
    )
    return [
        _rule_slide(),
        _evaluated(pol, policy_src),
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
            "talk": "The Security Model keeps a table of every issue found and fixed since the last major "
                "release, each with the file that fixes it, and a list of known limitations, so a "
                "deployment can compensate. The counts here are parsed from that document at build time, "
                "and the rows shown are simply the shortest entries.",
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


def _rule_slide() -> dict[str, Any]:
    """The shipped rule beside the decision it makes."""
    return {
        "kind": "canvas",
        "kicker": "Policy",
        "title": "A rule is a few lines of YAML, and it decides before the tool runs",
        "panels": [{"x": 0.0, "y": 0.0, "w": 0.42, "h": 1.0, "size": 13, "lines": ["# config/policies/"
                    "example-guardrails.yaml"] + _rule("sql-read-only")
                    + ["", "# deny wins over allow; a violated", "# constraint denies with the rule's name"]}],
        "nodes": [
            {"id": "call", "text": "A call", "sub": "tool, group, annotations, caller, path, time, arguments",
             "x": 0.47, "y": 0.0, "w": 0.24, "h": 0.2, "style": "white", "size": 14},
            {"id": "m", "text": "Match", "sub": "every rule whose conditions fit", "x": 0.76, "y": 0.0, "w": 0.24,
             "h": 0.2, "style": "soft", "shape": "hex", "size": 14},
            {"id": "d", "text": "Decide", "sub": "deny overrides", "x": 0.77, "y": 0.28, "w": 0.22, "h": 0.3,
             "style": "gold", "shape": "diamond", "size": 14},
            {"id": "al", "text": "allow", "sub": "obligations: argument limits, rate limits and quotas, redaction, "
             "screening", "x": 0.47, "y": 0.3, "w": 0.24, "h": 0.26, "style": "ok", "size": 14},
            {"id": "dn", "text": "deny", "sub": "with a reason; audited", "x": 0.47, "y": 0.68, "w": 0.24, "h": 0.18,
             "style": "bad", "size": 14},
            {"id": "ap", "text": "require_approval", "sub": "waits for a person; audited", "x": 0.76, "y": 0.68,
             "w": 0.24, "h": 0.18, "style": "warn", "size": 14},
        ],
        "edges": [
            {"a": "call", "b": "m"}, {"a": "m", "b": "d"},
            {"a": "d", "b": "al", "color": "OK"}, {"a": "d", "b": "dn", "mode": "c", "color": "BAD"},
            {"a": "d", "b": "ap", "color": "WARN"},
        ],
        "texts": [{"x": 0.47, "y": 0.9, "w": 0.53, "h": 0.1, "size": 11, "italic": True, "text": "default_effect: "
                   "deny makes it an allowlist. Files reload on change; the Policies page has a test bench."}],
        "source": "The rule is read verbatim from config/policies/example-guardrails.yaml at build time (disabled in "
        "the shipped configuration). docs/architecture/Policy and Audit.md §3; sajha/policy/model.py, engine.py.",
        "talk": "On the left is a real rule from the shipped example policy, read from the file when this deck was "
        "built. A rule matches on tool names and groups, annotations such as destructiveHint, the caller, the path, "
        "a time window and argument values. The engine collects the matching rules and decides: deny overrides "
        "allow, require_approval sends the call to a person, and setting default_effect to deny turns the policy "
        "into an allowlist. An allowed call can still carry obligations: argument constraints, rate limits and "
        "quotas shared by every worker, redaction and screening of results. Files reload when they change, every "
        "decision other than allow is audited, and the Policies page has a test bench.",
    }


def _evaluated(pol: list[dict[str, Any]], policy_src: str) -> dict[str, Any]:
    """Each evaluated call as a row: caller, call, decision, why."""
    look = {"allow": "ok", "deny": "bad", "require_approval": "warn"}
    rh = 0.9 / len(pol)
    nodes, edges, texts = [], [], []
    for i, p in enumerate(pol):
        y = 0.1 + i * rh
        h = rh - 0.04
        nodes += [
            {"id": f"c{i}", "text": p["caller"], "x": 0.0, "y": y, "w": 0.115, "h": h, "style": "white", "shape": "oval",
             "size": 12},
            {"id": f"t{i}", "text": p["tool"], "sub": js(p["args"]), "x": 0.15, "y": y, "w": 0.33, "h": h,
             "style": "box", "size": 13, "font": "Consolas"},
            {"id": f"d{i}", "text": p["effect"], "sub": ("+ " + ", ".join(p["obligations"])) if p["obligations"]
             else "", "x": 0.53, "y": y, "w": 0.14, "h": h, "style": look.get(p["effect"], "white"), "size": 14},
        ]
        edges += [{"a": f"c{i}", "b": f"t{i}"}, {"a": f"t{i}", "b": f"d{i}", "color": "CRIMSON"}]
        texts.append({"x": 0.69, "y": y, "w": 0.31, "h": h, "size": 12, "text":
                      (p["rule"].split("/")[-1] + ": " if p["rule"] else "no deciding rule: ")
                      + (p["reason"] or "allowed; obligations still apply")})
    for t, x in (("CALLER", 0.0), ("TOOL AND ARGUMENTS", 0.15), ("DECISION", 0.53), ("RULE AND REASON", 0.69)):
        texts.append({"x": x, "y": 0.0, "w": 0.3, "h": 0.07, "text": t, "bold": True, "color": "CRIMSON_D",
                      "size": 11})
    return {
        "kind": "canvas",
        "kicker": "Policy, evaluated",
        "title": "The shipped example policy, evaluated on four calls",
        "nodes": nodes,
        "edges": edges,
        "texts": texts,
        "note": "The same engine sits in BaseMCPTool.execute_with_tracking, so these decisions are the same over "
        "MCP, REST, the command line or Ask SAJHA.",
        "source": policy_src,
        "talk": "These four decisions were computed by the policy engine over the shipped example files while this "
        "deck was built; nothing was run. A plain read-only query is allowed, with a redaction obligation still "
        "attached. A query that smuggles a DROP TABLE is denied by the read-only SQL rule, which names itself in the "
        "reason. An anonymous caller is refused a tool that changes data. And a signed-in user calling the same "
        "destructive tool is sent for approval: a person must agree before it runs.",
    }


def _deploy(F: dict[str, Any]) -> list[dict[str, Any]]:
    cf = F["conformance"]
    storage = [s.replace("AzureBlob", "Azure Blob").replace("Local", "local disk") for s in F["storage"]]
    return [
        {
            "kind": "cards",
            "kicker": "Deploy anywhere",
            "title": "On premises, in a private cloud or a public one: the same server",
            "talk": "The same server runs on a VM with systemd and nginx, in Docker, on Kubernetes with the "
                "Helm chart, or on managed cloud services. Air-gapped works too, with the offline mock "
                "model, local tools and local data. Data leaves only when a tool calls an outside "
                "service, nothing phones home, and the same configuration file is used everywhere.",
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
            "talk": "This is what the AWS recipe creates, and nothing more. An application load balancer "
                "terminates TLS in front of one to six Fargate tasks running the non-root SAJHA image. "
                "Secrets come from Secrets Manager, tool and prompt configs from S3, logs and metrics go "
                "to CloudWatch, and shared state lives in RDS PostgreSQL, whose schema an operator runs "
                "once. Bedrock is an optional model provider.",
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
            "talk": "On premises, nginx terminates TLS and proxies to SAJHA on localhost, with streaming "
                "unbuffered. Files sit on local disk, Redis holds shared state when there are several "
                "workers, PostgreSQL holds the database from the schema and seed files an operator runs, "
                "Prometheus and Grafana watch it, and the audit streams to your SIEM. Nothing external is"
                " required.",
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
            "talk": "No load-test figures are claimed, because none has been measured and recorded. Instead "
                "these are facts the build counts: the automated tests, the conformance checks, the "
                "schema tables and the Helm templates. The chart includes autoscaling, a disruption "
                "budget, a network policy and a ServiceMonitor; several replicas need the redis or "
                "database state backend.",
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
