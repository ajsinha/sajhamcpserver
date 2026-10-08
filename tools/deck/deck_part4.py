"""
The deck, as data. Sections 7 and 8: the intelligence layer and the operational deep
dives (with one Ask SAJHA question captured end to end while the deck is built), then
where SAJHA is going, how it compares (from sajha/web/competitive.py), where to start,
and the close.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from evidence import SourceChanged
from diagrams import row
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
    ("Identity and access", ("users", "roles", "user_roles", "permissions", "api_keys", "user_sessions", "sajhanet_api_keys")),
    ("Audit and usage", ("audit_log", "audit_chain", "audit_anchors", "tool_usage_events", "obs_usage_events")),
    ("Prompts", ("prompts", "prompt_tags")),
    ("Intelligence", ("llm_providers", "llm_models", "ai_conversations", "ai_conversation_turns")),
    ("Composition and workflows", ("composite_tools", "composite_tool_steps", "workflows", "workflow_runs",
                                   "workflow_run_steps")),
    ("Protocol and shared state", ("a2a_tasks", "sajha_state", "sajha_state_events")),
    ("Accounts and quality", ("connected_accounts", "quality_runs")),
]


def _layer(F: dict[str, Any]) -> dict[str, Any]:
    """The intelligence layer as a stack: consumers, the public interface, the governed model, the providers."""
    prov = F["providers"]
    real = [p for p in prov if p != "mock"]
    cons = ["Ask SAJHA", "sajha_ask", "LLM tools", "Describe a tool", "Memory and RAG", "/v1 endpoint"]
    cx = row(len(cons), 0.0, 1.0, 0.155)
    per = (len(prov) + 2) // 3
    rows = [prov[k:k + per] for k in range(0, len(prov), per)]
    nodes = [{"id": f"c{i}", "text": t, "x": cx[i], "y": 0.0, "w": 0.155, "h": 0.12, "style": "white", "size": 12}
             for i, t in enumerate(cons)]
    nodes += [
        {"id": "api", "text": "sajha.ai.llm: llm_factory().model(alias)", "sub": "OpenAI-style chat_completions_create "
         "and embeddings_create; nothing outside imports a vendor SDK", "x": 0.0, "y": 0.2, "w": 1.0, "h": 0.14,
         "style": "dark", "size": 14},
        {"id": "gov", "text": "GovernedModel", "sub": "aliases, role policy and token caps, daily budgets, retries and "
         "fallback, a breaker per provider, a response cache, audit, usage, one trace span", "x": 0.0, "y": 0.41,
         "w": 1.0, "h": 0.15, "style": "accent", "size": 14},
    ]
    for r, names in enumerate(rows):
        xs = row(per, 0.0, 1.0, 0.125)
        nodes += [{"id": f"p{r}_{k}", "text": n, "x": xs[k], "y": 0.64 + r * 0.125, "w": 0.125, "h": 0.1,
                   "style": "gold" if n == "mock" else "box", "size": 11, "bold": n == "mock"}
                  for k, n in enumerate(names)]
    edges = [{"a": f"c{i}", "b": "api", "width": 1.2} for i in range(len(cons))]
    edges += [{"a": "api", "b": "gov", "color": "CRIMSON", "width": 2.0}]
    return {
        "kind": "canvas",
        "kicker": "The intelligence layer",
        "title": f"{len(real)} real provider types behind one OpenAI-style interface, and none is required",
        "nodes": nodes,
        "edges": edges,
        "note": "Out of the box every alias points at the offline mock (highlighted): no keys and no network for the "
        "model. Swapping a provider never touches the code that uses a model.",
        "source": "sajha.ai.llm.registry.registered_providers() after ensure_builtins(), read at build time; "
        "config/application.yml ai.aliases; docs/architecture/Intelligence Layer.md §1 (shape, the public API, the "
        "boundary), §5 (the factory and governed models); tests/test_llm_boundary.py.",
        "talk": "Everything LLM lives in one package. A consumer asks the factory for a model by alias (an ordered "
        "list of candidates) or provider/model and gets a GovernedModel, which speaks the OpenAI Chat Completions "
        "format as typed models. The governed model resolves the alias against the user's preference, the system "
        "default and the alias list, skipping providers that are down, circuits that are open and models the "
        "caller's role may not use; applies per-role policy and token caps and daily budgets; retries with backoff "
        "and falls back to the next candidate; caches deterministic answers; and records audit, usage, cost and one "
        "OpenTelemetry span per call. Each provider module translates the canonical format to its vendor at the "
        "edge, over HTTP; only Bedrock needs an SDK, loaded lazily. A test enforces the boundary.",
    }


def _llm_tools(F: dict[str, Any]) -> dict[str, Any]:
    modes = F["llm_modes"]
    mx = row(len(modes), 0.0, 1.0, 0.13)
    nodes = [{"id": f"m{i}", "text": m, "x": mx[i], "y": 0.5, "w": 0.13, "h": 0.13, "style": "soft", "size": 13}
             for i, m in enumerate(modes)]
    nodes += [
        {"id": "cfg", "text": "An LLM tool", "sub": "a config file in config/tools: name, schemas, a prompt, a mode",
         "x": 0.0, "y": 0.0, "w": 0.3, "h": 0.22, "style": "accent", "size": 15},
        {"id": "gov", "text": "governed like every tool", "sub": "access, policy, audit, budgets, tests, versions",
         "x": 0.35, "y": 0.0, "w": 0.3, "h": 0.22, "style": "box", "size": 14},
        {"id": "net", "text": "shared across a net", "sub": "runs on its host's models and budgets", "x": 0.7,
         "y": 0.0, "w": 0.3, "h": 0.22, "style": "box", "size": 14},
        {"id": "mcp", "text": "MCP clients", "sub": "tools/call", "x": 0.0, "y": 0.8, "w": 0.22, "h": 0.18,
         "style": "white", "size": 13},
        {"id": "wf", "text": "workflows, composites, A2A", "sub": "as a step", "x": 0.26, "y": 0.8, "w": 0.22,
         "h": 0.18, "style": "white", "size": 13},
        {"id": "oai", "text": "/v1/chat/completions", "sub": "the tool listed as model sajha:<tool>", "x": 0.52,
         "y": 0.8, "w": 0.24, "h": 0.18, "style": "white", "size": 13},
        {"id": "sdk", "text": "any OpenAI SDK", "sub": "base URL and a SAJHA key", "x": 0.8, "y": 0.8, "w": 0.2,
         "h": 0.18, "style": "ghost", "size": 13},
    ]
    edges = [{"a": "cfg", "b": "gov"}, {"a": "gov", "b": "net"}, {"a": "sdk", "b": "oai", "color": "CRIMSON"}]
    return {
        "kind": "canvas",
        "kicker": "LLM tools and the OpenAI-compatible endpoint",
        "title": f"An LLM tool is an ordinary tool whose work a model does, in one of {len(modes)} modes",
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.0, "y": 0.36, "w": 1.0, "h": 0.1, "text": "MODES", "bold": True, "color": "CRIMSON_D",
                   "size": 11},
                  {"x": 0.0, "y": 0.68, "w": 1.0, "h": 0.1, "text": "CALLED FROM", "bold": True, "color": "CRIMSON_D",
                   "size": 11}],
        "note": "The OpenAI-compatible endpoint ships " + ("on" if F["net"]["openai_api_shipped"] else "off") +
        " (ai.openai_api.enabled); when on, a caller sees only the models and LLM tools its role allows.",
        "source": "sajha/ai/llm_tools/config.py MODES, read at build time; docs/architecture/LLM Tools.md §6 (modes), "
        "§13.4 (SAJHA as an OpenAI-compatible endpoint; sajha/ai/openai_api.py, sajha/routes/openai_routes.py); "
        "docs/architecture/SAJHA Net.md §13 (remote LLM tools); ai.openai_api.enabled from the shipped "
        "config/application.yml.",
        "talk": "answer plans, calls tools and composes an answer with citations and confidence, which is what "
        "sajha_ask does. complete fills a prompt without tools; extract returns JSON validated against the output "
        "schema, retrying once; classify picks one label from a fixed set; grounded answers only from document search, citing each passage; "
        "narrate runs a named composite or workflow and has the model write only the prose; judge scores against a rubric. Each runs as the caller, with depth and "
        "budgets shared down the chain, so an LLM tool that calls another cannot escape its limits. The shipped "
        "examples are disabled by default. With the OpenAI-compatible endpoint on, any OpenAI SDK reaches SAJHA's "
        "gateway with a SAJHA API key as the bearer token, and each enabled LLM tool appears as a model.",
    }


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
            "title": "Intelligence and operations",
            "sub": "SAJHA needs no language model to serve tools; it has one anyway, for Ask SAJHA, for describing "
            "tools and for workflows. Then the deep dives an operator asks for.",
            "points": ["The intelligence layer", "LLM tools", "Ask SAJHA, captured", "Planners", "Memory and RAG", "Evals",
                       "Tool quality", "Observability", "Sandbox and accounts", "Storage and state",
                       "Clients", "Configuration", "Schema"],
        },
        _layer(F),
        _llm_tools(F),
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
    ev = F["evals"]
    react, plan = ev["runs"]["react"], ev["runs"]["plan_execute"]
    rows = [["Planner", "What it does", "Model calls, two-tool question"]]
    rows += [[p, *PLANNERS.get(p, ("A registered planner (GET /api/ai/planners)", "—"))] for p in F["planners"]]
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
            "kind": "canvas",
            "kicker": "Memory and RAG",
            "title": "Document search cites its passages; memory is per user and deletable",
            "groups": [
                {"id": "gr", "label": "DOCUMENT SEARCH (RAG)", "x": 0.0, "y": 0.0, "w": 1.0, "h": 0.6},
                {"id": "gm", "label": "CONVERSATION MEMORY", "x": 0.0, "y": 0.66, "w": 1.0, "h": 0.34},
            ],
            "nodes": [
                {"id": "src", "text": "Sources", "sub": "guides, named folders, uploads",
                 "x": 0.015, "y": 0.1, "w": 0.17, "h": 0.26, "style": "white", "size": 15},
                {"id": "fmt", "text": "Markdown, text, HTML, PDF, Word", "x": 0.015, "y": 0.42, "w": 0.17, "h": 0.14,
                 "style": "box", "size": 12, "bold": False},
                {"id": "ch", "text": "Passages", "sub": "split at headings", "x": 0.22, "y": 0.1,
                 "w": 0.15, "h": 0.26, "style": "white", "size": 15},
                {"id": "em", "text": "Embeddings", "sub": "the embedding alias", "x": 0.405, "y": 0.1,
                 "w": 0.15, "h": 0.26, "style": "white", "size": 15},
                {"id": "st", "text": "Store", "sub": listing(F["rag_stores"], "or"), "x": 0.59, "y": 0.08,
                 "w": 0.155, "h": 0.3, "style": "dark", "shape": "can", "size": 15},
                {"id": "se", "text": "Hybrid search", "sub": "vector and BM25, fused by rank", "x": 0.78, "y": 0.1,
                 "w": 0.205, "h": 0.26, "style": "accent", "size": 15},
                {"id": "out", "text": "sajha_search_docs", "sub": "document, section, link, citation",
                 "x": 0.78, "y": 0.41, "w": 0.205, "h": 0.16, "style": "soft", "size": 14},
                {"id": "q", "text": "follow-up question", "x": 0.015, "y": 0.76, "w": 0.16, "h": 0.18,
                 "style": "white", "size": 14},
                {"id": "ctx", "text": "recent turns + a summary of older ones", "x": 0.25, "y": 0.76, "w": 0.24,
                 "h": 0.18, "style": "soft", "size": 14},
                {"id": "rw", "text": "rewritten to stand alone", "x": 0.565, "y": 0.76, "w": 0.18, "h": 0.18,
                 "style": "white", "size": 14},
                {"id": "pu", "text": "per user; expires; deletable", "x": 0.805, "y": 0.76, "w": 0.18, "h": 0.18,
                 "style": "box", "size": 14},
            ],
            "edges": [
                {"a": "src", "b": "ch"}, {"a": "ch", "b": "em"}, {"a": "em", "b": "st"}, {"a": "st", "b": "se"},
                {"a": "se", "b": "out", "color": "CRIMSON"}, {"a": "src", "b": "fmt", "dash": True, "arrow": False},
                {"a": "q", "b": "ctx"}, {"a": "ctx", "b": "rw"}, {"a": "rw", "b": "pu", "dash": True, "arrow": False},
            ],
            "source": "docs/architecture/Intelligence Layer.md §6 'Document search (RAG)' and 'Stores' (sqlite_vec is the "
            "default when the extension loads, else memory; pgvector on PostgreSQL), 'Conversation memory', §9; "
            "sajha/ai/memory.py, sajha/ai/rag/ (stores: sajha.ai.rag.registry.registered_stores(), read at build time).",
            "talk": "sajha_search_docs is an ordinary tool over a document index: SAJHA's own guides, each passage citing "
            "its help page and section; folders of the storage backend an administrator names; and uploads. PDF and "
            "Word are read when their optional packages are installed; a scanned PDF has no text layer and is "
            "reported as such. Passages keep their section path. The default store, sqlite_vec, keeps passages, "
            "vectors and a full-text index in a SQLite file of its own; the memory store holds everything in the "
            "process; pgvector uses PostgreSQL. When the chosen store cannot run, the index falls back to memory and "
            "raises a system notice. Search fuses the vector ranking with a BM25 keyword ranking. Conversation memory "
            "is off unless an ask names a conversation: a follow-up gets the recent turns and a summary of older ones "
            "and is rewritten to stand alone; memory is per user, never shared, expires after "
            "ai.memory.retention_days, and users delete their own history.",
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
            "kind": "canvas",
            "kicker": "Configuration",
            "title": "One YAML file, overridden by the environment, with no secrets in it",
            "nodes": [
                {"id": "a1", "text": "SAJHA_<DOTTED_KEY>", "sub": "the environment", "x": 0.0, "y": 0.1, "w": 0.27,
                 "h": 0.24, "style": "accent", "size": 16},
                {"id": "a2", "text": "config/application.yml", "sub": "with ${ENV:default}", "x": 0.35, "y": 0.1,
                 "w": 0.27, "h": 0.24, "style": "dark", "size": 16},
                {"id": "a3", "text": "the code's default", "x": 0.7, "y": 0.1, "w": 0.22, "h": 0.24, "style": "white",
                 "size": 16},
                {"id": "b1", "text": "SAJHA_AI_<SECTION>_<FIELD>", "x": 0.0, "y": 0.5, "w": 0.27, "h": 0.22,
                 "style": "accent", "size": 15},
                {"id": "b2", "text": "the vendor's own variable", "x": 0.31, "y": 0.5, "w": 0.18, "h": 0.22,
                 "style": "dark", "size": 15},
                {"id": "b3", "text": "YAML", "x": 0.53, "y": 0.5, "w": 0.1, "h": 0.22, "style": "dark", "size": 15},
                {"id": "b4", "text": "the database", "x": 0.67, "y": 0.5, "w": 0.13, "h": 0.22, "style": "dark",
                 "size": 15},
                {"id": "b5", "text": "default", "x": 0.84, "y": 0.5, "w": 0.1, "h": 0.22, "style": "white", "size": 15},
                {"id": "sec", "text": "Secrets: never in application.yml", "sub": "it is tracked: environment "
                 "variables; the OAuth signing key in data/oauth/; a known placeholder secret stops start-up",
                 "x": 0.0, "y": 0.8, "w": 1.0, "h": 0.18, "style": "warn", "size": 14},
            ],
            "edges": [
                {"a": "a1", "b": "a2", "label": "else", "lsize": 10}, {"a": "a2", "b": "a3", "label": "else",
                                                                      "lsize": 10},
                {"a": "b1", "b": "b2"}, {"a": "b2", "b": "b3"}, {"a": "b3", "b": "b4"}, {"a": "b4", "b": "b5"},
            ],
            "texts": [
                {"x": 0.0, "y": 0.0, "w": 0.8, "h": 0.08, "text": "MOST KEYS", "bold": True, "color": "CRIMSON_D",
                 "size": 11},
                {"x": 0.0, "y": 0.38, "w": 0.8, "h": 0.08, "text": "THE INTELLIGENCE LAYER (ai.*)", "bold": True,
                 "color": "CRIMSON_D", "size": 11},
            ],
            "source": "sajha/core/config.py _get; CLAUDE.md 'Code facts'; docs/getting-started/Configuration Reference.md "
            "(which keys resolve how; storage and ${...} in tool configs use PropertiesConfigurator); "
            "docs/security/Security Model.md §6.",
            "talk": "Most keys resolve the environment variable SAJHA_ followed by the dotted key in capitals, then "
            "config/application.yml (which may itself say ${ENV:default}), then the code's default. Not every "
            "subsystem reads through that path: storage and the ${...} placeholders in tool configs use the "
            "properties configurator, and the Configuration Reference records which keys behave how. The intelligence "
            "layer resolves SAJHA_AI_<SECTION>_<FIELD>, then the vendor's own variable such as OPENAI_API_KEY, then "
            "YAML, then the database, then the default. application.yml is tracked, so secrets go in the environment. "
            "Laptop, Docker, Kubernetes and the cloud recipes all start from the same file.",
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
    pick = [x.split(", and while")[0] for x in lims if x.startswith((
        "Plain storage", "The test admin key", "Open admission", "Prompts have", "Studio template", "Sandbox strength"))]
    if len(pick) < 4:
        raise SourceChanged(f"the Security Model's known limitations changed shape: {lims}")
    nxt = [(i, t) for i, t in F["roadmap"] if i.startswith(("N", "X"))]
    later = [(i, t) for i, t in F["roadmap"] if i.startswith("L")]
    return [
        {
            "kind": "divider",
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
                "head": "Next, from the Roadmap",
                "items": [f"{i}: {t}" for i, t in nxt],
                "size": 15,
            },
            "right": {
                "head": "Known limitations (Security Model)",
                "items": pick,
                "size": 15,
            },
            "note": f"Later: {len(later)} larger items, among them {listing(t.lower() for _i, t in later[:3])}. Each row "
            "of the Roadmap links to the guide that owns it.",
            "source": "Left column and the note: the open items of docs/architecture/Roadmap.md sections 2 to 4, parsed at "
            "build time (evidence.roadmap). Right column: bold heads of 'Known limitations' in docs/security/Security "
            "Model.md, parsed at build time and filtered by name. Built features are on the capability slides, not here.",
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
                 f"{listing(managed)}. SAJHA is proprietary and self-hosted, by decision."),
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
                ["Trying it", "pip install -r requirements.txt; python run_sajha_web.py; open localhost:3002",
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
                ("Proprietary. © 2025-2030 Ashutosh Sinha. All rights reserved. No licence is granted.", 11, "PINK",
                 False),
                (f"Licensing and enquiries: {F['email']}", 11, "PINK", False),
            ],
            "source": "config/application.yml app.version, app.author and app.email, read at build time; the licence "
            "position: the LICENSE file and docs/architecture/Roadmap.md §6.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _ask(F) + _intel(F) + _ops(F) + _future(F)
