"""
The deck, as data. Sections 6 and 7: the intelligence layer and the operational deep
dives (with one Ask SAJHA question captured end to end while the deck is built), then
where SAJHA is going, how it compares (from sajha/web/competitive.py), where to start,
and the close.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from evidence import SourceChanged
from prose import js, listing, plain, wrap

PLANNERS = {
    "react": ("The default: one model call per step, answer or call which offered tools",
              "One per step, plus the answer"),
    "plan_execute": ("One planning call returns steps with dependencies; independent steps run together; one "
                     "re-plan after a failure", "One, plus the answer"),
    "recipes": ("Regular-expression or keyword recipes from configuration map a question to a tool and its "
                "arguments", "None when the recipe has an answer template"),
    "router": ("Chooses per question: rules, then a matching recipe, then plan_execute for multi-part questions, "
               "else react", "As the planner it chose"),
}
SHORT = {"Yes": "Yes", "Partial": "Part", "No": "No", "Unknown": "?"}
HEADS = {"spec_2026": "2026 era", "conformance_ci": "Suite in CI", "oauth_as": "Own OAuth server",
         "builtin_tools": "Tools in the box", "nocode": "No-code tools", "llm": "LLM and chat",
         "isolation": "Isolation", "integrations": "SaaS apps", "open_source": "Open source", "managed": "Managed"}
MATRIX = ["spec_2026", "conformance_ci", "oauth_as", "builtin_tools", "nocode", "llm", "isolation", "integrations",
          "open_source", "managed"]

# Schema tables by purpose; a table the schema file has and this map does not fails the build.
TABLE_GROUPS = [
    ("Identity and access", ("users", "roles", "user_roles", "permissions", "api_keys", "user_sessions", "tenants")),
    ("Audit and usage", ("audit_log", "audit_chain", "audit_anchors", "tool_usage_events", "obs_usage_events")),
    ("Prompts", ("prompts", "prompt_tags")),
    ("Intelligence", ("llm_providers", "llm_models", "ai_conversations", "ai_conversation_turns")),
    ("Composition and workflows", ("composite_tools", "composite_tool_steps", "workflows", "workflow_runs",
                                   "workflow_run_steps")),
    ("Protocol and shared state", ("a2a_tasks", "sajha_state", "sajha_state_events")),
    ("Accounts and quality", ("connected_accounts", "quality_runs")),
]


def _ask(F: dict[str, Any]) -> list[dict[str, Any]]:
    ask, cat, conf, ev = F["ask"], F["catalog"], F["confidence"], F["evals"]
    name, args, summary, latency, step_conf = ask["steps"][0]
    shown = ask["shortlist"][:12]
    react, plan = ev["runs"]["react"], ev["runs"]["plan_execute"]
    run_src = (
        "A real run captured while the deck was built (tools/deck/evidence.py, ask_run): "
        f"IntelligenceService.stream_ask over the full registry ({cat['tools']} tools) on the offline mock provider "
        f"({ask['model']}), planner {ask['planner']}, question {ask['question']!r}."
    )
    prov = F["providers"]
    real = [p for p in prov if p != "mock"]
    return [
        {
            "kind": "divider",
            "num": "6",
            "title": "Intelligence and operations",
            "sub": "SAJHA needs no language model to serve tools; it has one anyway, for Ask SAJHA, for describing "
            "tools and for workflows. Then the deep dives an operator asks for.",
            "points": ["Providers", "Ask SAJHA, captured", "Planners", "Memory and RAG", "Composition", "Evals",
                       "Tool quality", "Observability", "Sandbox and accounts", "Storage and state",
                       "Clients", "Configuration", "Schema"],
        },
        {
            "kind": "stats",
            "kicker": "LLM providers",
            "title": f"{len(prov)} provider types behind one gateway, and none is required",
            "intro": "A provider is a source of models (a vendor's API or a local server such as Ollama); an alias "
            "such as “default” names an ordered list of models to try. Out of the box the alias points at the "
            "offline mock.",
            "stats": [
                (str(len(real)), "real provider types, hosted and local"),
                ("1", "offline mock, the default: works with no keys"),
                (str(len(F["planners"])), "planners for Ask SAJHA"),
            ],
            "items": [
                ("Built in", listing(real) + "."),
                ("The gateway applies", "Per-role model policy and token caps, daily budgets, retries with backoff, a "
                 "circuit breaker per provider, fallback, a response cache, one trace span per call."),
            ],
            "source": "sajha.ai.llm.registry.registered_providers() after ensure_builtins(), read at build time; "
            "config/application.yml ai.aliases (default: mock/mock-planner); docs/architecture/Intelligence Layer.md §5.",
        },
        {
            "kind": "flow",
            "kicker": "Semantic discovery and Ask SAJHA",
            "title": "Ask SAJHA answers in four moves, and the browser draws each one",
            "intro": "On /ask the catalog is drawn as a constellation: one star per tool, clustered by group. As a "
            "question is answered, the shortlisted stars light up and a line is drawn to each tool called.",
            "box_h": 2.2,
            "steps": [
                ("1  Shortlist", "Every tool's name and description is ranked against the question (embeddings, or "
                 "BM25 when none is configured); tools the caller may not run are dropped first."),
                ("2  Plan", "A planner asks the model what to do next: answer, or call which shortlisted tools."),
                ("3  Governed call", "Each call takes the path every client's call takes: schema, access, policy, "
                 "cache, audit."),
                ("4  Answer", "The answer cites the calls it rests on; SAJHA attaches a confidence it computed itself."),
            ],
            "items": ["The page animates the run's events, in the order emitted: " + " → ".join(ask["events"]) + "."],
            "source": "sajha/ai/intelligence.py (stream_ask), sajha/ai/tool_resolver.py and lexical.py (BM25 without an "
            "embedder). " + run_src,
        },
        {
            "kind": "split",
            "kicker": "Captured: the shortlist",
            "title": f"{cat['tools']} tools in, {len(ask['shortlist'])} offered to the model",
            "left": {
                "head": "The shortlist event",
                "lines": [f"# question: {ask['question']}", "# score  tool"]
                + [f"{s:.3f}  {n}" for n, s in shown],
            },
            "right": {
                "head": "What happened",
                "items": [
                    f"No model chose these: the resolver ranked all {cat['tools']} descriptions by word overlap (BM25), "
                    "because no embedding model is configured.",
                    "The calculator ranks first; the model, not the shortlist, makes the final choice.",
                    "Tools the caller may not run were removed first: a model cannot be talked into a tool its user "
                    "cannot call.",
                    f"Only the top {ask['shortlist_setting']} (ai.ask.shortlist) reach the model.",
                ],
            },
            "source": run_src + " Shortlist size: AskSettings().shortlist.",
        },
        {
            "kind": "split",
            "kicker": "Captured: the call",
            "title": "The model asked for one call, and SAJHA ran it as it runs any client's",
            "left": {
                "head": "The plan and the call",
                "lines": [
                    f"# model {ask['model']}, planner {ask['planner']}",
                    f"→ tool_call {name}",
                    *wrap(f"arguments {js(args)}", 50),
                    "",
                    f"→ tool_result ok, {latency} ms",
                    *wrap(summary, 50),
                ],
            },
            "right": {
                "head": "On the way, SAJHA",
                "items": [
                    ("Checked", "Arguments against the schema, the caller's access, and the policy rules in force."),
                    ("Ran", "Through the tool's cache and its provider's circuit breaker, counted in the metrics."),
                    ("Refused what was not offered", "A call outside the shortlist is refused; a destructive tool waits "
                     "for the user's confirmation."),
                    ("Treated the result as data", "Tool output is never an instruction to the model."),
                ],
            },
            "source": run_src + " Safeguards: IntelligenceService._run_call and SYSTEM_PROMPT (sajha/ai/intelligence.py); "
            "BaseMCPTool.execute_with_tracking.",
        },
        {
            "kind": "split",
            "kicker": "Captured: the answer",
            "title": "The answer cites its source, and SAJHA sets the confidence",
            "left": {
                "head": "The answer",
                "lines": [
                    "→ answer",
                    *wrap(ask["answer"], 50),
                    "",
                    f"→ citations {', '.join(ask['citations'])}",
                    f"→ confidence {ask['confidence']:.2f}  (basis: {name} {step_conf:.2f})",
                    "",
                    f"# {ask['tokens']} tokens, {ask['duration_ms']} ms end to end",
                ],
            },
            "right": {
                "head": "How the number is made",
                "items": [
                    ("Confidence", f"Each cited step contributes its tool's confidence ({conf['calc']:.2f} for a "
                     f"calculator, {conf['fred']:.2f} for FRED, {conf['web']:.2f} for a web fetch), chained."),
                    ("Not an opinion", f"A failed call contributes {conf['failed']}, an incomplete loop "
                     f"{conf['incomplete']}, an answer on no tool {conf['unverified']}; the model is never asked."),
                    ("What the mock shows", f"The mechanism, not reasoning. The shipped eval set passed "
                     f"{react['passed']}/{react['questions']} with react and {plan['passed']}/{plan['questions']} with "
                     "plan_execute on it; real questions need a real model."),
                ],
            },
            "source": run_src + " Confidence rules: IntelligenceService._confidence, UNVERIFIED_CONFIDENCE, "
            "get_tool_confidence, read at build time. Evals: sajha.quality.evals.run_set over "
            "config/evals/calculators.yaml.",
        },
    ]


def _intel(F: dict[str, Any]) -> list[dict[str, Any]]:
    ev, comp = F["evals"], F["composition"]
    react, plan = ev["runs"]["react"], ev["runs"]["plan_execute"]
    rows = [["Planner", "What it does", "Model calls, two-tool question"]]
    rows += [[p, *PLANNERS.get(p, ("A registered planner (GET /api/ai/planners)", "—"))] for p in F["planners"]]
    comp_lines = ["# confidence through a three-step composite", "# step                      conf  chain  bits"]
    for s, c, cum, bits in comp["rows"]:
        comp_lines.append(f"{s[:25]:<25} {c:.2f}  {cum:.3f}  {bits:.2f}")
    comp_lines += ["", f"# refused above {comp['max_bits']:.1f} bits (max_entropy_bits)"]
    return [
        {
            "kind": "table",
            "kicker": "Planners",
            "title": "The planner decides the next step; the service keeps every safeguard",
            "col_w": [1.3, 4.3, 2.0],
            "rows": rows,
            "note": "Whatever the planner: the access-filtered shortlist, refusal of tools not offered, confirmation "
            "of destructive tools, limits, citations, confidence and audit. A planner never touches a tool.",
            "source": "sajha.ai.planners.registered_planners() at build time; docs/architecture/Intelligence Layer.md §6.",
        },
        {
            "kind": "split",
            "kicker": "Memory and RAG",
            "title": "Memory is per user and deletable; document search cites its passages",
            "left": {
                "head": "Conversation memory",
                "items": [
                    "A follow-up gets the recent turns and a summary of older ones, and is rewritten to stand alone.",
                    "Per user, never shared; expires after ai.memory.retention_days; users delete their own history.",
                    "Off unless the ask names a conversation.",
                ],
            },
            "right": {
                "head": "Document search (RAG)",
                "items": [
                    "sajha_search_docs searches SAJHA's guides, folders an administrator names, and uploads, and "
                    "answers with document, section and link.",
                    "Vector and word rankings fused; in-process store by default, pgvector on PostgreSQL.",
                    "Text formats only today.",
                ],
            },
            "source": "docs/architecture/Intelligence Layer.md §6 'Conversation memory', 'Document search (RAG)', §9; "
            "sajha/ai/memory.py, sajha/ai/rag/.",
        },
        {
            "kind": "split",
            "kicker": "Composite tools",
            "title": "Confidence falls as uncertain steps chain, and SAJHA computes by how much",
            "left_w": 0.52,
            "left": {"head": "Computed while building this deck", "lines": comp_lines},
            "right": {
                "head": "Composites",
                "items": [
                    "Sibling (parallel) or parent-child (fan-out per record) steps, defined declaratively, registered "
                    "as ordinary MCP tools.",
                    "Sequential steps multiply confidence; parallel steps take the lowest.",
                    "A composite whose predicted entropy passes the limit is refused before it runs.",
                    "A calculator adds no doubt, so it does not lower the chain.",
                ],
            },
            "source": "sajha.core.composition.EntropyGuard and get_tool_confidence, run at build time on three registry "
            "tools (evidence.composition_example); arrangements: sajha/tools/composite_tool.py ('sibling', "
            "'parent_child'); GLOSSARY.md 'EntropyGuard'.",
        },
        {
            "kind": "bullets",
            "kicker": "Evals",
            "title": "Evals measure a model on golden questions before anyone trusts it",
            "items": [
                ("Golden questions", "A set names questions, the tools that must and must not be called, checks on the "
                 "answer, and limits on steps, tokens, cost and latency."),
                ("Measured", "Pass rate, tool-selection accuracy, answer accuracy, tokens, cost, mean and p95 latency, "
                 "per model and planner; two runs compared question by question."),
                ("On the mock, at this build", f"“{ev['set']}”: {react['passed']}/{react['questions']} with react, "
                 f"{plan['passed']}/{plan['questions']} with plan_execute, tool-selection accuracy "
                 f"{react['tool_selection_accuracy']:.0%}, at zero cost."),
            ],
            "source": "Run at build time (evidence.eval_runs) with sajha.quality.evals over config/evals/calculators.yaml; "
            "docs/architecture/Tool Quality.md.",
        },
        {
            "kind": "cards",
            "kicker": "Tool quality",
            "title": "Tools are tested, linted, probed, versioned and released by canary",
            "cols": 3,
            "cards": [
                ("TESTS", "Recorded, replayable", "Test cases with HTTP cassettes replayed offline; JUnit output for CI."),
                ("LINT", "Schemas that models can use", "A static linter: valid JSON Schema 2020-12, descriptions, "
                 "examples, MCP names, annotations."),
                ("PROBES", "Health on a schedule", "Probes call tools periodically; one worker claims each slot."),
                ("VERSIONS", "Several behind one name", "Routed by pin, user, role or canary percentage."),
                ("ROLLBACK", "Automatic", "A canary that errors or slows down is rolled back; sunset dates retire "
                 "versions."),
                ("EVALS", "For the model too", "The same harness measures models and planners (previous slide)."),
            ],
            "source": "docs/architecture/Tool Quality.md; sajha/quality/; sajha/core/tool_versioning.py.",
        },
        {
            "kind": "cards",
            "kicker": "Observability",
            "title": "Metrics, traces, cost and alerts, out of the box",
            "cols": 2,
            "cards": [
                ("METRICS", "Prometheus at /metrics, protected", "HTTP, MCP and tool calls and latency, cache hits, LLM "
                 "tokens and spend, sandbox runs, policy decisions, audit export."),
                ("TRACES", "OpenTelemetry over OTLP, opt-in", "A span per request, tool call and model call, with the "
                 "caller attached."),
                ("COST", "A usage and cost dashboard", "Calls, errors, tokens and spend by user, key, role, model, tool "
                 "and day; budgets; CSV export."),
                ("ALERTS", "Rules on rates, latency and spend", "Error rates, p95 latency, LLM spend, open circuit "
                 "breakers; to a log, an email or a guarded webhook."),
            ],
            "source": "docs/architecture/Observability.md §2–§5; sajha/observability/metrics.py, tracing.py, usage.py, "
            "alerts.py; deployment/observability/.",
        },
        {
            "kind": "cards",
            "kicker": "Sandbox and connected accounts",
            "title": "User code runs in a sandbox; a user's tokens stay in a vault",
            "cols": 2,
            "cards": [
                ("SANDBOX", "Every call of user code in its own process", "Studio Python and script tools, and the "
                 "admin shell, run with no server environment and no network unless allowed. Backends: "
                 f"{listing(F['sandbox'], 'or')}."),
                ("WHAT IT DOES NOT COVER", "Built-in tools are not sandboxed", "Shipped tools run in-process; on macOS "
                 "and Windows the default gives only a clean environment and limits."),
                ("CONNECTED ACCOUNTS", "A tool acts as the user", f"A user links {listing(F['accounts'])} or any OAuth "
                 "2.0 service once; tools that declare it call with that user's token."),
                ("THE VAULT", "Encrypted, bound, fenced", "AES-256-GCM, bound to user and provider, sent only to the "
                 "provider's listed hosts; per-user results never cached."),
            ],
            "source": "sajha/sandbox/backends.py BACKENDS and sajha/accounts/providers.py TEMPLATES, read at build time; "
            "docs/architecture/Sandbox.md, Connected Accounts.md; Security Model §8.",
        },
    ]


def _ops(F: dict[str, Any]) -> list[dict[str, Any]]:
    storage = [s.replace("AzureBlob", "Azure Blob").replace("Local", "local disk") for s in F["storage"]]
    tables = F["tables"]
    known = {t for _g, ts in TABLE_GROUPS for t in ts}
    unknown = sorted(set(tables) - known)
    if unknown:
        raise SourceChanged(f"schema tables with no group on the schema slide: {unknown}")
    trows = [["Group", "Tables"]] + [[g, ", ".join(t for t in ts if t in tables)] for g, ts in TABLE_GROUPS
                                      if any(t in tables for t in ts)]
    return [
        {
            "kind": "table",
            "kicker": "Storage and state",
            "title": "One process on a laptop, or several pods in a cluster",
            "col_w": [1.7, 2.6, 3.4],
            "rows": [
                ["Concern", "Choices", "Default, and when to change it"],
                ["Configuration and tool files", listing(storage, "or"),
                 "Local disk; an object store when pods share files, with hot reload"],
                ["Shared protocol state", listing(F["state"], "or"),
                 "memory for one worker; redis or database for several"],
                ["Database", listing(F["schemas"], "or"),
                 "SQLite for development; PostgreSQL from one schema file an operator runs"],
                ["Packaging", "A non-root container image, a Helm chart, Kustomize",
                 "Plus recipes: " + listing(r for r in F["recipes"] if r not in ("k8s", "observability"))],
            ],
            "note": "Shared through the store: sessions, tasks, OAuth codes, rate-limit and budget counters, approvals. "
            "Per process on purpose: caches, circuit breakers and metrics.",
            "source": "StorageBackend subclasses in sajha/core/storage.py; sajha.core.state.BACKENDS; db/scripts/*/; "
            "deployment/*/, all listed at build time; docs/architecture/Scaling and State.md.",
        },
        {
            "kind": "cards",
            "kicker": "Clients",
            "title": "A Python client, a command line, and agent-to-agent",
            "cols": 3,
            "cards": [
                ("CLIENT SDK", "sajhaclient", "Built on the official MCP SDK; adopts the newest era the server offers; "
                 "REST and A2A clients; API key, JWT and OAuth auth."),
                ("COMMAND LINE", "sajha", f"Commands: {listing(F['cli'])}; profiles per server; JSON output."),
                ("A2A", "Agent to agent", "An agent card at /.well-known/agent.json; POST /a2a (JSON-RPC) with "
                 "tasks/send, tasks/get and tasks/cancel, under the same tool access."),
            ],
            "items": [
                ("Desktop clients", "sajha serve --stdio runs SAJHA as a stdio server for Claude Desktop, Claude Code and "
                 "other local clients; the caller is set by --user or --api-key."),
            ],
            "items_h": 1.0,
            "source": "clientsdk/sajhaclient (standard.py SajhaMCPClient, a2a_client.py, auth.py); CLI commands parsed "
            "from clientsdk/sajhaclient/cli/main.py at build time; sajha/routes/a2a_routes.py; docs/clients/Command "
            "Line.md.",
        },
        {
            "kind": "bullets",
            "kicker": "Configuration",
            "title": "One YAML file, overridden by the environment, with no secrets in it",
            "items": [
                ("Order", "A key resolves SAJHA_<DOTTED_KEY> from the environment, then config/application.yml (with "
                 "${ENV:default}), then the code's default."),
                ("The intelligence layer", "ai.* keys resolve SAJHA_AI_<SECTION>_<FIELD>, then the vendor's own "
                 "variable, then YAML, then the database, then the default."),
                ("Secrets", "Never in application.yml, which is tracked: environment variables; the OAuth signing key "
                 "in data/oauth/; a known placeholder secret stops start-up."),
                ("Same file everywhere", "Laptop, Docker, Kubernetes and the cloud recipes all start from it; the "
                 "Configuration Reference lists every key."),
            ],
            "source": "sajha/core/config.py _get; CLAUDE.md 'Code facts'; docs/getting-started/Configuration Reference.md; "
            "docs/security/Security Model.md §6.",
        },
        {
            "kind": "table",
            "kicker": "Database schema",
            "title": f"{len(tables)} tables in two schema files, and no migrations",
            "col_w": [2.2, 5.6],
            "rows": trows,
            "note": "SAJHA never runs DDL on PostgreSQL: an operator runs schema.sql (safe to re-run) and seed.sql. "
            "SQLite creates its own tables. A test keeps both files in step with the models.",
            "source": "db/scripts/postgresql/schema.sql and db/scripts/sqlite/schema.sql, parsed at build time (the same "
            "set in both); grouping: tools/deck/deck_part4.py TABLE_GROUPS (an unknown table fails the build); "
            "tests/test_db_schema.py; docs/getting-started/Database Setup.md.",
        },
    ]


def _future(F: dict[str, Any]) -> list[dict[str, Any]]:
    c = F["competition"]
    labels = dict(c["dims"])
    matrix = [["Product"] + [HEADS.get(d, labels[d]) for d in MATRIX]] + [
        [name] + [SHORT[cells[d]["verdict"]] for d in MATRIX] for name, _k, _t, cells in c["products"]
    ]
    gateways = [comp["name"] for comp in c["competitors"] if comp["kind"] == "Gateway"]
    hosted = [comp["name"] for comp in c["competitors"] if comp["kind"] == "Hosted platform"]
    isolators = [comp["name"] for comp in c["competitors"] if comp["cells"]["isolation"]["verdict"] == "Yes"]
    managed = [comp["name"] for comp in c["competitors"] if comp["cells"]["managed"]["verdict"] == "Yes"]
    opens = [comp["name"] for comp in c["competitors"] if comp["cells"]["open_source"]["verdict"] == "Yes"]
    comp_src = (
        f"sajha/web/competitive.py (the data behind /comparison), read at build time; competitor verdicts come from "
        f"each vendor's public pages as of {c['as_of']}, each with a source URL; tests/test_competitive.py checks it."
    )
    lims = [plain(x).rstrip(".") for x in F["limitations"]]
    pick = [x for x in lims if x.startswith(("Tenant", "Studio access", "JWTs", "No SSO", "Prompts have",
                                            "Sandbox strength", "The WebSocket"))]
    return [
        {
            "kind": "divider",
            "num": "7",
            "title": "Where it's going, and how it compares",
            "sub": "What is not built yet and what is known to be limited, from SAJHA's own documents; then the "
            "comparison, with where others are stronger.",
            "points": ["Not built yet", "Known limitations", "The comparison", "Where others are stronger",
                       "Where to start"],
        },
        {
            "kind": "split",
            "kicker": "Where it's going",
            "title": "Not built yet, and what is known to be limited",
            "left": {
                "head": "Not built yet (from the guides)",
                "items": [
                    "Enforced multi-tenancy: tenant records are stored, but no request path consults them.",
                    "Finer Studio permissions: the studio permission opens every creator.",
                    "A TypeScript client SDK: the client SDK is Python only.",
                    "Weaviate and Chroma connectors.",
                    "Document connectors (SharePoint, Drive, Confluence) and PDF or Word as RAG sources.",
                    "Native async providers; Vertex AI; Entra ID token acquisition.",
                    "Push-based cloud reload instead of polling.",
                ],
            },
            "right": {
                "head": "Known limitations (Security Model)",
                "items": pick,
            },
            "source": "Tenancy and Studio: docs/security/Security Model.md 'Known limitations'. TypeScript: clientsdk/ "
            "is Python only. Weaviate, Chroma: docs/architecture/Data Connectors.md §14. Document sources, async, "
            "Vertex, Entra: docs/architecture/Intelligence Layer.md §9. Push reload: docs/getting-started/Storage "
            "Guide.md 'Planned'. Right column: bold heads of 'Known limitations', parsed at build time and filtered "
            "by name. Built features are on the capability slides, not here. Every item, with size and dependencies: "
            "docs/architecture/Roadmap.md.",
        },
        {
            "kind": "table",
            "kicker": "Competitive analysis",
            "title": f"SAJHA beside {len(c['products']) - 1} alternatives, on vendors' own documentation",
            "col_w": [2.3] + [1.0] * len(MATRIX),
            "rows": matrix,
            "note": "Part = partial (limited, preview, a paid tier); ? = not verifiable from public documentation on "
            f"{c['as_of']}. The full table, with a note and a source for every cell, is at /comparison.",
            "source": comp_src + " The ten columns are chosen to show differences.",
        },
        {
            "kind": "cards",
            "kicker": "Where others are stronger",
            "title": "Gateways, containers, SaaS breadth and a hosted service: others do these better",
            "cols": 2,
            "cards": [
                ("SCALE OF FEDERATION", f"Gateways: {listing(gateways)}", "Built to put many MCP servers behind one "
                 "endpoint at scale. SAJHA federates too, off by default."),
                ("ISOLATION", f"Containers per server: {listing(isolators) or 'none listed'}", "They run each server "
                 "in its own container; SAJHA sandboxes only user code and the shell."),
                ("SAAS BREADTH", f"Hosted catalogs: {listing(hosted)}", "Thousands of SaaS apps with per-user sign-in, "
                 "run for you. SAJHA links a handful of services."),
                ("LICENCE AND HOSTING", "Open source, or run for you", f"Open source: {listing(opens)}. Managed: "
                 f"{listing(managed)}. SAJHA has neither."),
            ],
            "source": comp_src + " Groupings computed from each competitor's kind and its isolation, managed and "
            "open_source verdicts.",
        },
        {
            "kind": "table",
            "kicker": "Where to start",
            "title": "Where to start, by who you are",
            "col_w": [1.6, 3.2, 2.6],
            "rows": [
                ["You are", "Do this first", "Then read"],
                ["Trying it", "pip install -r requirements.txt; python run_server.py; open localhost:3002",
                 "Quick Start; the tutorials"],
                ["Connecting a client", "Point it at /mcp, or run sajha serve --stdio", "MCP Protocol Guide; Command Line"],
                ["Reviewing security", "Read the access policy; try a rule on the Policies test bench",
                 "Security Model; Policy and Audit; OAuth Guide"],
                ["Adding tools", "Describe one, import an API, or connect a database", "MCP Studio User Guide"],
                ["Running it", "Install the Helm chart with a redis or database state backend",
                 "Kubernetes Deployment; Scaling and State"],
                ["Choosing", "Open /comparison and read the sources", "How SAJHA Fits Together"],
            ],
            "note": "Every guide named here is in docs/ and is also served inside the app under Help.",
            "source": "README.md 'Quick start'; docs/README.md reading order; guide names as in docs/.",
        },
        {
            "kind": "thanks",
            "title": "Thank you",
            "lines": [
                (f"SAJHA MCP Server {F['version']}", 20, "WHITE", True),
                ("Ashutosh Sinha", 16, "PINK_L", False),
                (F["email"], 14, "PINK", False),
                (F["repo"], 12, "PINK", False),
            ],
            "source": "config/application.yml app.version, app.author, app.email and app.github.repo, read at build time.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _ask(F) + _intel(F) + _ops(F) + _future(F)
