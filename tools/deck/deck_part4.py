"""
The deck, as data. Parts 7 to 9: the intelligence layer, how it runs, and how SAJHA
compares (from sajha/web/competitive.py, including where others are stronger), what it
does not do, and where to start.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from prose import listing, plain

PLANNERS = {
    "react": ("The default: one model call per step, answer or call which offered tools",
              "One per step, plus the answer"),
    "plan_execute": ("One planning call returns steps with dependencies; independent steps run together; "
                     "one re-plan after a failure", "One, plus the answer"),
    "recipes": ("Regular-expression or keyword recipes from configuration map a question to a tool and "
                "its arguments", "None when the recipe has an answer template"),
    "router": ("Chooses per question: rules, then a matching recipe, then plan_execute for multi-part "
               "questions, else react", "As the planner it chose"),
}
SHORT = {"Yes": "Yes", "Partial": "Part", "No": "No", "Unknown": "?"}
HEADS = {"spec_2026": "2026 era", "conformance_ci": "Suite in CI", "oauth_as": "Own OAuth server",
         "builtin_tools": "Tools in the box", "nocode": "No-code tools", "llm": "LLM and chat",
         "isolation": "Isolation", "integrations": "SaaS apps", "open_source": "Open source",
         "managed": "Managed"}
MATRIX = ["spec_2026", "conformance_ci", "oauth_as", "builtin_tools", "nocode", "llm", "isolation",
          "integrations", "open_source", "managed"]


def _part7(F: dict[str, Any]) -> list[dict[str, Any]]:
    prov, ev = F["providers"], F["evals"]
    real = [p for p in prov if p != "mock"]
    react, plan = ev["runs"]["react"], ev["runs"]["plan_execute"]
    rows = [["Planner", "What it does", "Model calls for a two-tool question"]]
    rows += [[p, *PLANNERS.get(p, ("A registered planner (see GET /api/ai/planners)", "—"))] for p in F["planners"]]
    return [
        {
            "kind": "divider",
            "num": "7",
            "title": "The intelligence layer",
            "sub": "SAJHA does not need a language model to serve tools; clients bring their own. It has one "
            "anyway, for Ask SAJHA, for describing tools and for workflows, and it is built so that no "
            "provider is required and none is privileged.",
            "points": [
                "Providers behind one gateway",
                "Planners",
                "Memory and document search",
                "Evals, and what the mock cannot do",
            ],
        },
        {
            "kind": "stats",
            "kicker": "Providers",
            "title": f"{len(prov)} provider types behind one gateway, and none is required",
            "intro": "A provider is a source of models (a vendor's API or a local server); an alias such as "
            "“default” names an ordered list of models to try. Everything that asks a model goes through "
            "the gateway.",
            "stats": [
                (str(len(real)), "real provider types, hosted and local"),
                ("1", "offline mock, the default: works with no keys"),
                (str(len(F["planners"])), "planners for Ask SAJHA"),
            ],
            "items": [
                ("Built in", listing(real) + "."),
                ("The gateway applies", "Per-role policy (which models, whether tools may be offered, token "
                 "caps), daily budgets per user and role, retries with backoff, a circuit breaker per "
                 "provider, fallback to the next candidate, a response cache, one trace span per call."),
                ("Extensible", "A provider, a model or a planner is a registered class or a package entry "
                 "point; the extension guide has worked examples."),
            ],
            "size": 15,
            "source": "sajha.ai.llm.registry.registered_providers() after ensure_builtins(), read at build time; "
            "planners: sajha.ai.planners.registered_planners(). Gateway: docs/architecture/Intelligence "
            "Layer.md §5; extension: Extending the Intelligence Layer.md.",
        },
        {
            "kind": "table",
            "kicker": "Planners",
            "title": "The planner decides the next step; the service keeps every safeguard",
            "col_w": [1.3, 4.3, 2.0],
            "rows": rows,
            "note": "Whatever the planner, the service keeps the access-filtered shortlist, refusal of tools "
            "not offered, confirmation of destructive tools, limits, citations, confidence and audit. A "
            "planner reaches a model only through the gateway and never touches a tool.",
            "source": "Planner names: sajha.ai.planners.registered_planners() at build time; descriptions: "
            "docs/architecture/Intelligence Layer.md §6 'Planners'.",
        },
        {
            "kind": "split",
            "kicker": "Context",
            "title": "Memory is per user and deletable; document search cites its passages",
            "left": {
                "head": "Conversation memory",
                "items": [
                    "A follow-up gets the recent turns, a summary of older ones, and is rewritten to stand "
                    "on its own (“and from 100 to 120?”).",
                    "Per user, never shared; expires after ai.memory.retention_days; a user lists and "
                    "deletes their own history.",
                    "Off unless the ask names a conversation.",
                ],
                "size": 16,
            },
            "right": {
                "head": "Document search",
                "items": [
                    "sajha_search_docs searches SAJHA's own guides, folders an administrator names, and "
                    "uploads, and answers with document, section and link.",
                    "Vector and word rankings fused; in-process store by default, pgvector on PostgreSQL.",
                    "Text formats only; no PDF, Word or SharePoint sources yet.",
                ],
                "size": 16,
            },
            "source": "docs/architecture/Intelligence Layer.md §6 'Conversation memory', 'Document search "
            "(RAG)' and §9 'Not built yet'; sajha/ai/memory.py, sajha/ai/rag/.",
        },
        {
            "kind": "bullets",
            "kicker": "Before you trust a model",
            "title": "Evals measure a model on golden questions before anyone trusts it",
            "items": [
                ("Golden questions", "An eval set names questions, the tools that must and must not be "
                 "called, checks on the answer, and limits on steps, tokens, cost and latency."),
                ("Measured", "Pass rate, tool-selection accuracy, answer accuracy, tokens, cost, mean and p95 "
                 "latency, per model and planner; two runs can be compared question by question."),
                ("On the mock, today", f"“{ev['set']}”: {react['passed']}/{react['questions']} with react, "
                 f"{plan['passed']}/{plan['questions']} with plan_execute, tool-selection accuracy "
                 f"{react['tool_selection_accuracy']:.0%}, at zero cost."),
                ("Not built yet", "Native async providers; Vertex AI and Entra ID token acquisition; "
                 "freshness and cross-source agreement in the confidence score."),
            ],
            "source": "Eval runs at build time (tools/deck/evidence.py, eval_runs) with sajha.quality.evals over "
            "config/evals/calculators.yaml. Not built yet: docs/architecture/Intelligence Layer.md §9; "
            "docs/architecture/Tool Quality.md §5.",
        },
    ]


def _part8(F: dict[str, Any]) -> list[dict[str, Any]]:
    storage = [s.replace("AzureBlob", "Azure Blob").replace("Local", "local disk") for s in F["storage"]]
    return [
        {
            "kind": "divider",
            "num": "8",
            "title": "How it runs",
            "sub": "The same code runs as one process on a laptop and as several pods behind a load "
            "balancer. What changes is configuration: where files live, where shared state lives, which "
            "database, and what is watched.",
            "points": [
                "From one process to a cluster",
                "Shared state across workers",
                "Kubernetes and Helm",
                "Metrics, traces, cost and alerts",
                "The schema, and tool quality",
            ],
        },
        {
            "kind": "table",
            "kicker": "Shapes",
            "title": "One process on a laptop, or several pods in a cluster",
            "col_w": [1.7, 2.6, 3.4],
            "rows": [
                ["Concern", "Choices", "Default, and when to change it"],
                ["Configuration and tool files", listing(storage, "or"),
                 "Local disk; an object store when pods share files, with hot reload"],
                ["Shared protocol state", listing(F["state"], "or"),
                 "memory, for one worker; redis or database for several"],
                ["Database", listing(F["schemas"], "or"),
                 "SQLite for development; PostgreSQL from one schema file an operator runs"],
                ["Packaging", "A non-root container image, a Helm chart, Kustomize manifests",
                 "Plus recipes: " + listing(r for r in F["recipes"] if r not in ("k8s", "observability"))],
            ],
            "source": "Storage backends: StorageBackend subclasses in sajha/core/storage.py; state backends: "
            "sajha.core.state.BACKENDS; schema dialects: db/scripts/*/schema.sql; recipes: deployment/*/, "
            "all listed at build time.",
        },
        {
            "kind": "bullets",
            "kicker": "Several workers",
            "title": "Workers share protocol state through one store; caches stay local on purpose",
            "items": [
                ("Shared", "Sessions, task records, OAuth codes and refresh tokens, rate-limit and budget "
                 "counters, approvals, and the change events behind subscriptions, through redis or the "
                 "database."),
                ("Local by design", "Caches, circuit breakers and metrics stay per process; Prometheus adds "
                 "the workers up."),
                ("Durable tasks", "With a shared store, task records live in the database and survive a "
                 "restart."),
                ("One secret, everywhere", "Every worker needs the same signing and session secrets; the "
                 "guide lists them."),
            ],
            "source": "docs/architecture/Scaling and State.md §2–§5; sajha/core/state/; CLAUDE.md 'Code facts'.",
        },
        {
            "kind": "bullets",
            "kicker": "Kubernetes",
            "title": "A Helm chart with the pieces a production namespace expects",
            "intro": "The chart's templates, as shipped: " + listing(F["helm"]) + ".",
            "items": [
                ("Scales", "A horizontal pod autoscaler and a disruption budget; several replicas need the "
                 "redis or database state backend, which the chart can provide."),
                ("Locked down", "A non-root image and a network policy; secrets from Kubernetes secrets, "
                 "never from the tracked configuration file."),
                ("Watched", "A ServiceMonitor for Prometheus; ingress settings that keep streamed responses "
                 "unbuffered."),
            ],
            "source": "charts/sajha/templates/*.yaml, listed at build time; docs/getting-started/Kubernetes "
            "Deployment.md.",
        },
        {
            "kind": "cards",
            "kicker": "Operations",
            "title": "Metrics, traces, cost and alerts, out of the box",
            "cols": 2,
            "cards": [
                ("METRICS", "Prometheus at /metrics, protected",
                 "HTTP, MCP and tool calls and latency, cache hits, LLM tokens and spend, sandbox runs, "
                 "policy decisions, audit export."),
                ("TRACES", "OpenTelemetry over OTLP, opt-in",
                 "A span per request, tool call and model call, with the caller attached."),
                ("COST", "A usage and cost dashboard",
                 "Calls, errors, tokens and spend by user, API key, role, model, tool and day; budgets "
                 "against today's use; CSV export."),
                ("ALERTS", "Rules on rates, latency and spend",
                 "Error rates, p95 latency, LLM spend, open circuit breakers; sent to a log, an email or a "
                 "webhook that passes the SSRF guard."),
            ],
            "source": "docs/architecture/Observability.md §2–§5; sajha/observability/metrics.py, tracing.py, "
            "usage.py, alerts.py.",
        },
        {
            "kind": "split",
            "kicker": "Change, safely",
            "title": "Two schema files and no migrations; tools tested and released by canary",
            "left": {
                "head": "The database schema",
                "items": [
                    f"One schema file per database ({listing(F['schemas'])}) in db/scripts; a test keeps "
                    "them in step with the models.",
                    "SAJHA never runs DDL on PostgreSQL: an operator runs the file, which creates only "
                    "what is missing. SQLite creates its own tables.",
                    "A start-up check names any missing table.",
                ],
                "size": 16,
            },
            "right": {
                "head": "Tool quality",
                "items": [
                    "Test cases with recorded HTTP cassettes replayed offline; JUnit output.",
                    "A schema linter; health probes on a schedule.",
                    "Tool versions behind one name, routed by pin, user, role or canary percentage, with "
                    "automatic rollback on errors or slowness, and sunset dates.",
                ],
                "size": 16,
            },
            "source": "docs/getting-started/Database Setup.md; tests/test_db_schema.py; db/scripts/*/schema.sql; "
            "docs/architecture/Tool Quality.md; sajha/quality/.",
        },
    ]


def _part9(F: dict[str, Any]) -> list[dict[str, Any]]:
    c = F["competition"]
    labels = dict(c["dims"])
    tally = [["Product", "Kind", "Yes", "Partial", "No", "Unknown"]] + [
        [name, kind, str(t["Yes"]), str(t["Partial"]), str(t["No"]), str(t["Unknown"])]
        for name, kind, t, _cells in c["products"]
    ]
    matrix = [["Product"] + [HEADS.get(d, labels[d]) for d in MATRIX]] + [
        [name] + [SHORT[cells[d]["verdict"]] for d in MATRIX] for name, _k, _t, cells in c["products"]
    ]
    gateways = [comp["name"] for comp in c["competitors"] if comp["kind"] == "Gateway"]
    hosted = [comp["name"] for comp in c["competitors"] if comp["kind"] == "Hosted platform"]
    isolators = [comp["name"] for comp in c["competitors"] if comp["cells"]["isolation"]["verdict"] == "Yes"]
    managed = [comp["name"] for comp in c["competitors"] if comp["cells"]["managed"]["verdict"] == "Yes"]
    opens = [comp["name"] for comp in c["competitors"] if comp["cells"]["open_source"]["verdict"] == "Yes"]
    comp_src = (
        f"sajha/web/competitive.py (the data behind /comparison), read at build time; competitor verdicts are "
        f"from each vendor's own public pages as of {c['as_of']}, each with a source URL; "
        "tests/test_competitive.py checks the data."
    )
    not_yes = [(label, verdict) for label, verdict, _n in c["not_yes"]]
    lims = [plain(x).rstrip(".") for x in F["limitations"]]
    return [
        {
            "kind": "divider",
            "num": "9",
            "title": "How it compares, honestly",
            "sub": "SAJHA sits among frameworks, gateways and hosted platforms. Each column of the comparison "
            "is the vendor's own documentation on a stated date; where another product is stronger, this "
            "part says so, and then says what SAJHA does not do.",
            "points": [
                "Ten products, one set of questions",
                "Where SAJHA stands",
                "Where others are stronger",
                "What SAJHA does not do",
                "Where to start",
            ],
        },
        {
            "kind": "table",
            "kicker": "The comparison",
            "title": f"{len(c['products'])} products, {len(c['dims'])} questions, verdicts from vendors' own pages",
            "intro": "Each cell is Yes, Partial, No or Unknown (could not be verified), with a note and a "
            "dated source. The questions are the ones a buyer of a tool server asks; a gateway buyer would "
            "ask others, so read the counts as a profile, not a score.",
            "col_w": [2.6, 1.7, 0.8, 0.8, 0.8, 0.9],
            "rows": tally,
            "size": 12,
            "source": comp_src,
        },
        {
            "kind": "table",
            "kicker": "Where SAJHA stands",
            "title": "Ten of the questions, product by product",
            "col_w": [2.3] + [1.0] * len(MATRIX),
            "rows": matrix,
            "size": 10.5,
            "bold_col0": True,
            "note": "Part = partial: limited, preview, a paid tier, or part of the row; ? = not verifiable "
            "from public documentation on the date.",
            "source": comp_src + " The ten columns are chosen to show differences; the full table is at "
            "/comparison.",
        },
        {
            "kind": "cards",
            "kicker": "Where others are stronger",
            "title": "Gateways, containers, SaaS breadth and a hosted service: others do these better",
            "cols": 2,
            "cards": [
                ("SCALE OF FEDERATION", f"Gateways: {listing(gateways)}",
                 "Built to put many MCP servers behind one endpoint at scale. SAJHA federates upstreams too, "
                 "off by default, as one process."),
                ("ISOLATION", f"Containers per server: {listing(isolators) or 'none listed'}",
                 "They run each server in its own container. SAJHA sandboxes only the code users add in "
                 "Studio, and the shell."),
                ("SAAS BREADTH", f"Hosted catalogs: {listing(hosted)}",
                 "Thousands of SaaS apps with per-user sign-in, run for you. SAJHA links a handful of "
                 "services as each user."),
                ("LICENCE AND HOSTING", "Open source, or run for you",
                 f"Open source: {listing(opens)}. Managed: {listing(managed)}. SAJHA has neither."),
            ],
            "source": comp_src + " Groupings are computed from each competitor's 'kind' and its isolation, "
            "managed and open_source verdicts; the wording follows SHORT_VERSION in the same file.",
        },
        {
            "kind": "split",
            "kicker": "Limits",
            "title": "What SAJHA does not do, from its own documents",
            "left_w": 0.42,
            "left": {
                "head": "Not a Yes in the comparison",
                "items": [(f"{label}: {verdict}", plain(note).rstrip(".").split(". ")[-1] + ".")
                          for label, verdict, note in c["not_yes"]],
                "size": 15,
            },
            "right": {
                "head": "Known limitations (Security Model)",
                "items": lims,
                "size": 16,
            },
            "source": f"Left: the last sentence of each SAJHA cell of sajha/web/competitive.py whose verdict is not Yes ({len(not_yes)}). "
            "Right: the bold heads of 'Known limitations' in docs/security/Security Model.md, parsed at build "
            "time.",
        },
        {
            "kind": "table",
            "kicker": "Where to start",
            "title": "Where to start, by who you are",
            "col_w": [1.6, 3.2, 2.6],
            "rows": [
                ["You are", "Do this first", "Then read"],
                ["Trying it", "pip install -r requirements.txt; python run_server.py; open localhost:3002",
                 "Quick Start; the tutorials in order"],
                ["Connecting a client", "Point it at /mcp, or run python run_server.py --stdio for a desktop "
                 "client", "MCP Protocol Guide; Command Line"],
                ["Reviewing security", "Read the access policy, then try a rule on the Policies test bench",
                 "Security Model; Policy and Audit; OAuth Guide"],
                ["Adding tools", "Describe one, import an API, or connect a database in Studio",
                 "MCP Studio User Guide; Tool Generation"],
                ["Running it", "Install the Helm chart with a redis or database state backend",
                 "Kubernetes Deployment; Scaling and State"],
                ["Choosing", "Open /comparison and read the sources", "How SAJHA Fits Together"],
            ],
            "note": "Every guide named here is in docs/ and is also served inside the app under Help.",
            "source": "README.md 'Quick start'; docs/README.md reading order; guide names as in docs/.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _part7(F) + _part8(F) + _part9(F)
