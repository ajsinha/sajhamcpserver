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
        _ask_moves(F, run_src),
        _ask_shortlist(F, run_src),
        _ask_call(F, run_src),
        _ask_answer(F, run_src),
    ]


def _ask_moves(F: dict[str, Any], run_src: str) -> dict[str, Any]:
    """The four moves as a pipeline, and the captured run's events in order beneath."""
    ask, cat = F["ask"], F["catalog"]
    nodes = [
        {"id": "q", "text": "a question", "x": 0.0, "y": 0.06, "w": 0.11, "h": 0.24, "style": "white", "shape": "oval",
         "size": 14},
        {"id": "sh", "text": "1  Shortlist", "sub": f"all {cat['tools']} ranked against the question; tools the "
         "caller may not run dropped first", "x": 0.16, "y": 0.02, "w": 0.19, "h": 0.32, "style": "soft", "size": 15},
        {"id": "pl", "text": "2  Plan", "sub": "the planner asks the model: answer, or call which tools", "x": 0.4,
         "y": 0.02, "w": 0.18, "h": 0.32, "style": "white", "size": 15},
        {"id": "gc", "text": "3  Governed call", "sub": "schema, access, policy, cache, audit: every client's path",
         "x": 0.63, "y": 0.02, "w": 0.18, "h": 0.32, "style": "accent", "size": 15},
        {"id": "an", "text": "4  Answer", "sub": "cites its calls; SAJHA sets the confidence", "x": 0.86, "y": 0.02,
         "w": 0.14, "h": 0.32, "style": "dark", "size": 15},
    ]
    edges = [{"a": "q", "b": "sh"}, {"a": "sh", "b": "pl"}, {"a": "pl", "b": "gc", "color": "CRIMSON"},
             {"a": "gc", "b": "an", "color": "CRIMSON"},
             {"a": "gc", "b": "pl", "ports": ("b", "b"), "via": [(0.72, 0.42), (0.49, 0.42)], "dash": True,
              "label": "the next step", "lseg": 1, "lsize": 11}]
    ev = ask["events"]
    half = (len(ev) + 1) // 2
    look = {"tool_call": "accent", "tool_result": "accent", "answer": "dark", "confidence": "dark", "done": "dark",
            "shortlist": "soft"}
    for r, chunk in enumerate((ev[:half], ev[half:])):
        xs = row(half, 0.0, 1.0, 0.12)
        for k, e in enumerate(chunk):
            nodes.append({"id": f"e{r}_{k}", "text": e, "x": xs[k], "y": 0.64 + r * 0.19, "w": 0.12, "h": 0.13,
                          "style": look.get(e, "white"), "size": 10, "floor": 8.5, "bold": False,
                          "font": "Consolas"})
    return {
        "kind": "canvas",
        "kicker": "Semantic discovery and Ask SAJHA",
        "title": "Ask SAJHA answers in four moves, and the browser draws each one",
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.0, "y": 0.53, "w": 1.0, "h": 0.08, "bold": True, "color": "CRIMSON_D", "size": 11,
                   "text": "THE CAPTURED RUN'S EVENTS, IN THE ORDER EMITTED; THE PAGE ANIMATES EACH ONE"}],
        "source": "sajha/ai/intelligence.py (stream_ask), sajha/ai/tool_resolver.py and lexical.py (BM25 without an "
        "embedder). " + run_src,
        "talk": "On the Ask page the catalog is drawn as a constellation, one star per tool, clustered by group. A "
        "question is answered in four moves. First a shortlist: every tool's name and description is ranked against "
        "the question, by embeddings or by BM25 when none is configured, after dropping tools the caller may not "
        "run. Then a planner asks the model what to do next. Each call the model asks for takes the governed path "
        "any client's call takes. Finally the answer cites the calls it rests on, with a confidence SAJHA computes "
        "itself. The lower strip is the real event stream of the run captured for this deck; the page lights up "
        "the shortlisted stars and draws a line to each tool called as these events arrive.",
    }


def _ask_shortlist(F: dict[str, Any], run_src: str) -> dict[str, Any]:
    """The captured shortlist as bars, beside the funnel that made it."""
    ask, cat = F["ask"], F["catalog"]
    shown = ask["shortlist"][:12]
    top = max(sc for _n, sc in shown)
    rh = 0.9 / len(shown)
    nodes, texts = [], [{"x": 0.0, "y": 0.0, "w": 0.56, "h": 0.08, "size": 12, "italic": True,
                         "text": f"“{ask['question']}”: the shortlist event, score by tool"}]
    for i, (n, sc) in enumerate(shown):
        y = 0.1 + i * rh
        texts.append({"x": 0.0, "y": y, "w": 0.27, "h": rh, "text": n, "size": 12, "font": "Consolas",
                      "color": "INK"})
        nodes.append({"id": f"b{i}", "text": f"{sc:.3f}", "x": 0.28, "y": y + rh * 0.12, "w": 0.27 * sc / top,
                      "h": rh * 0.76, "style": "accent" if i == 0 else "soft", "size": 11, "bold": i == 0})
    funnel = [(f"{cat['tools']} tools", "every description in the catalog", "white", 0.36),
              ("the caller's tools", "tools it may not run are removed first", "box", 0.32),
              ("ranked by BM25", "word overlap: no embedding model is configured", "soft", 0.28),
              (f"top {ask['shortlist_setting']} offered", "ai.ask.shortlist", "accent", 0.24),
              ("the model chooses", "not the shortlist", "dark", 0.2)]
    edges = []
    for k, (t, sub, style, w) in enumerate(funnel):
        nodes.append({"id": f"f{k}", "text": t, "sub": sub, "x": 0.81 - w / 2, "y": 0.02 + k * 0.2, "w": w,
                      "h": 0.14, "style": style, "size": 14})
        if k:
            edges.append({"a": f"f{k - 1}", "b": f"f{k}", "color": "CRIMSON"})
    return {
        "kind": "canvas",
        "kicker": "Captured: the shortlist",
        "title": f"{cat['tools']} tools in, {len(ask['shortlist'])} offered to the model",
        "nodes": nodes,
        "edges": edges,
        "texts": texts,
        "source": run_src + " Shortlist size: AskSettings().shortlist. Bar lengths are proportional to the scores.",
        "talk": f"No model chose these. The resolver ranked all {cat['tools']} descriptions against the question by "
        "word overlap, BM25, because no embedding model is configured on the offline build. The calculator ranks "
        "first, as the bars show, but the model, not the shortlist, makes the final choice. Tools the caller may not "
        "run were removed before ranking, so a model cannot be talked into a tool its user cannot call. Only the top "
        f"{ask['shortlist_setting']}, the ai.ask.shortlist setting, reach the model.",
    }


def _ask_call(F: dict[str, Any], run_src: str) -> dict[str, Any]:
    ask = F["ask"]
    name, args, summary, latency, _c = ask["steps"][0]
    return {
        "kind": "canvas",
        "kicker": "Captured: the call",
        "title": "The model asked for one call, and SAJHA ran it as it runs any client's",
        "panels": [{"x": 0.0, "y": 0.0, "w": 0.44, "h": 0.62, "size": 13, "lines": [
            f"# model {ask['model']}, planner {ask['planner']}", f"→ tool_call {name}",
            *wrap(f"arguments {js(args)}", 44), "", f"→ tool_result ok, {latency} ms", *wrap(summary, 44)]}],
        "nodes": [
            {"id": "tc", "text": "tool_call", "sub": name, "x": 0.5, "y": 0.0, "w": 0.24, "h": 0.14, "style": "white",
             "size": 14},
            {"id": "of", "text": "Offered?", "x": 0.54, "y": 0.19, "w": 0.16, "h": 0.2, "style": "gold",
             "shape": "diamond", "size": 13},
            {"id": "ck", "text": "Checked", "sub": "schema, the caller's access, the policy rules", "x": 0.5, "y": 0.44,
             "w": 0.24, "h": 0.14, "style": "soft", "size": 14},
            {"id": "rn", "text": "Ran", "sub": "the tool's cache, its provider's breaker, metrics", "x": 0.5, "y": 0.64,
             "w": 0.24, "h": 0.14, "style": "accent", "size": 14},
            {"id": "tr", "text": f"tool_result ok, {latency} ms", "sub": "treated as data, never as an instruction",
             "x": 0.5, "y": 0.85, "w": 0.24, "h": 0.15, "style": "dark", "size": 13},
            {"id": "rf", "text": "refused", "sub": "a call outside the shortlist", "x": 0.8, "y": 0.21, "w": 0.2,
             "h": 0.16, "style": "bad", "size": 13},
            {"id": "cf", "text": "waits for the user", "sub": "a destructive tool needs confirmation", "x": 0.8,
             "y": 0.53, "w": 0.2, "h": 0.18, "style": "warn", "size": 13},
        ],
        "edges": [
            {"a": "tc", "b": "of"}, {"a": "of", "b": "ck", "label": "yes", "lsize": 10},
            {"a": "of", "b": "rf", "color": "BAD", "label": "no", "lsize": 10}, {"a": "ck", "b": "rn"},
            {"a": "rn", "b": "tr"}, {"a": "ck", "b": "cf", "mode": "c", "dash": True},
        ],
        "source": run_src + " Safeguards: IntelligenceService._run_call and SYSTEM_PROMPT (sajha/ai/intelligence.py); "
        "BaseMCPTool.execute_with_tracking.",
        "talk": f"On the left is the captured call: the mock model asked for {name} with the arguments shown, and the "
        f"result came back in {latency} milliseconds. On the right is what SAJHA did on the way. A call for a tool "
        "that was not offered is refused. The arguments are checked against the schema, then the caller's access and "
        "the policy rules in force; a destructive tool waits for the user's confirmation. The tool runs through its "
        "cache and its provider's circuit breaker and is counted in the metrics. Its output goes back to the model as "
        "data, never as an instruction.",
    }


def _ask_answer(F: dict[str, Any], run_src: str) -> dict[str, Any]:
    ask, conf, ev = F["ask"], F["confidence"], F["evals"]
    name, _a, _s, _l, step_conf = ask["steps"][0]
    react, plan = ev["runs"]["react"], ev["runs"]["plan_execute"]
    tools = [("a calculator", conf["calc"]), ("FRED", conf["fred"]), ("a web fetch", conf["web"])]
    cases = [("a failed call", conf["failed"]), ("an incomplete loop", conf["incomplete"]),
             ("an answer on no tool", conf["unverified"])]
    nodes = [{"id": f"t{i}", "text": f"{v:.2f}", "sub": t, "x": 0.5 + i * 0.105, "y": 0.0, "w": 0.095, "h": 0.17,
              "style": "white", "size": 16} for i, (t, v) in enumerate(tools)]
    nodes += [
        {"id": "ch", "text": "chained", "sub": "over the cited steps", "x": 0.85, "y": 0.0, "w": 0.15, "h": 0.17,
         "style": "soft", "shape": "hex", "size": 14},
        {"id": "ans", "text": f"confidence {ask['confidence']:.2f}", "sub": f"basis: {name} {step_conf:.2f}",
         "x": 0.78, "y": 0.3, "w": 0.22, "h": 0.2, "style": "accent", "size": 16},
    ]
    nodes += [{"id": f"c{i}", "text": f"{v}", "sub": t, "x": 0.5 + i * 0.17, "y": 0.62, "w": 0.15, "h": 0.17,
               "style": "warn", "size": 15} for i, (t, v) in enumerate(cases)]
    return {
        "kind": "canvas",
        "kicker": "Captured: the answer",
        "title": "The answer cites its source, and SAJHA sets the confidence",
        "panels": [{"x": 0.0, "y": 0.0, "w": 0.44, "h": 0.72, "size": 13, "lines": [
            "→ answer", *wrap(ask["answer"], 44), "", f"→ citations {', '.join(ask['citations'])}",
            f"→ confidence {ask['confidence']:.2f}", f"  (basis: {name} {step_conf:.2f})", "",
            f"# {ask['tokens']} tokens, {ask['duration_ms']} ms end to end"]}],
        "nodes": nodes,
        "edges": [{"a": "t2", "b": "ch"}, {"a": "ch", "b": "ans", "color": "CRIMSON"}],
        "texts": [
            {"x": 0.5, "y": 0.22, "w": 0.27, "h": 0.1, "size": 11, "bold": True, "color": "CRIMSON_D",
             "text": "EACH TOOL'S CONFIDENCE"},
            {"x": 0.5, "y": 0.53, "w": 0.5, "h": 0.08, "size": 11, "bold": True, "color": "CRIMSON_D",
             "text": "WHAT THE OTHER CASES CONTRIBUTE; THE MODEL IS NEVER ASKED"},
            {"x": 0.5, "y": 0.84, "w": 0.5, "h": 0.16, "size": 11, "italic": True, "text":
             f"The mock shows the mechanism, not reasoning: the shipped eval set passed {react['passed']}/"
             f"{react['questions']} with react and {plan['passed']}/{plan['questions']} with plan_execute on it."},
        ],
        "source": run_src + " Confidence rules: IntelligenceService._confidence, UNVERIFIED_CONFIDENCE, "
        "get_tool_confidence, read at build time. Evals: sajha.quality.evals.run_set over "
        "config/evals/calculators.yaml.",
        "talk": "The captured answer on the left names the calculator call it rests on, by its citation id. The "
        "confidence is not the model's opinion. Each cited step contributes its tool's confidence, one for a "
        f"calculator, {conf['fred']:.2f} for FRED, {conf['web']:.2f} for a web fetch, and the steps are chained. "
        f"Other cases have fixed contributions: a failed call {conf['failed']}, an incomplete loop "
        f"{conf['incomplete']}, an answer that rests on no tool {conf['unverified']}. The offline mock demonstrates "
        "the mechanism, not reasoning; real questions need a real model.",
    }


def _intel(F: dict[str, Any]) -> list[dict[str, Any]]:
    ev = F["evals"]
    react, plan = ev["runs"]["react"], ev["runs"]["plan_execute"]
    rows = [["Planner", "What it does", "Model calls, two-tool question"]]
    rows += [[p, *PLANNERS.get(p, ("A registered planner (GET /api/ai/planners)", "—"))] for p in F["planners"]]
    return [
        _planners(F),
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
        _evals(F),
        _quality(),
        _observability(),
        _sandbox(F),
    ]


def _planners(F: dict[str, Any]) -> dict[str, Any]:
    """The router's choice drawn as a decision; each planner with what it costs in model calls."""
    if set(F["planners"]) != set(PLANNERS):
        raise SourceChanged(f"registered planners {F['planners']} differ from the slide's {sorted(PLANNERS)}")
    order = ["recipes", "plan_execute", "react"]
    nodes = [
        {"id": "q", "text": "a question", "x": 0.0, "y": 0.3, "w": 0.11, "h": 0.2, "style": "white", "shape": "oval",
         "size": 14},
        {"id": "rt", "text": "router", "sub": "chooses per question", "x": 0.16, "y": 0.25, "w": 0.15, "h": 0.3,
         "style": "gold", "shape": "hex", "size": 15},
        {"id": "ru", "text": "a configured rule's planner", "x": 0.5, "y": 0.0, "w": 0.2, "h": 0.12, "style": "ghost",
         "size": 13},
    ]
    labels = {"recipes": "else, a recipe matches", "plan_execute": "else, a multi-part question", "react": "otherwise"}
    edges = [{"a": "q", "b": "rt"},
             {"a": "rt", "b": "ru", "via": [(0.235, 0.06)], "dash": True, "label": "a rule's pattern matches",
              "lseg": 1, "lsize": 11}]
    for i, p in enumerate(order):
        y = 0.18 + i * 0.27
        what, calls = PLANNERS[p]
        nodes += [
            {"id": p, "text": p, "x": 0.5, "y": y, "w": 0.16, "h": 0.2, "style": "accent" if p == "react" else "dark",
             "size": 15, "font": "Consolas"},
            {"id": f"{p}_d", "text": what, "sub": "model calls: " + calls, "x": 0.69, "y": y - 0.02, "w": 0.31,
             "h": 0.24, "style": "white", "size": 12, "bold": False},
        ]
        edges.append({"a": "rt", "b": p, "via": [(0.36, y + 0.1)], "label": labels[p], "lseg": 1, "lsize": 10})
    return {
        "kind": "canvas",
        "kicker": "Planners",
        "title": "The planner decides the next step; the service keeps every safeguard",
        "nodes": nodes,
        "edges": edges,
        "note": "Whatever the planner: the access-filtered shortlist, refusal of tools not offered, confirmation "
        "of destructive tools, limits, citations, confidence and audit. A planner never touches a tool.",
        "source": "sajha.ai.planners.registered_planners() at build time; RouterPlanner.choose in sajha/ai/planners.py "
        "(configured rules, then recipes, then the multi-step planner, else the default); "
        "docs/architecture/Intelligence Layer.md §6.",
        "talk": "A planner only decides the next step; the service around it keeps every safeguard. react is the "
        "default: one model call per step, answering or calling which offered tools. plan_execute makes one planning "
        "call that returns steps with dependencies, runs independent steps together, and re-plans once after a "
        "failure. recipes maps a question to a tool and its arguments with configured patterns, and can answer from a "
        "template with no model call at all. The router chooses per question: a configured rule first, then a "
        "matching recipe, then plan_execute for a multi-part question, otherwise react.",
    }


def _evals(F: dict[str, Any]) -> dict[str, Any]:
    ev = F["evals"]
    runs = ev["runs"]
    nodes = [
        {"id": "set", "text": f"Eval set “{ev['set']}”", "sub": "golden questions: tools that must and must not be "
         "called, answer checks, limits on steps, tokens, cost and latency", "x": 0.0, "y": 0.1, "w": 0.24, "h": 0.5,
         "style": "white", "shape": "doc", "size": 15},
        {"id": "run", "text": "run_set", "sub": "per model and planner", "x": 0.31, "y": 0.2, "w": 0.15, "h": 0.3,
         "style": "dark", "shape": "hex", "size": 15},
    ]
    edges = [{"a": "set", "b": "run"}]
    for i, (p, r) in enumerate(runs.items()):
        y = 0.02 + i * 0.36
        nodes += [
            {"id": f"r{i}", "text": p, "sub": f"{r['passed']}/{r['questions']} passed", "x": 0.54, "y": y, "w": 0.16,
             "h": 0.26, "style": "accent", "size": 15},
            {"id": f"m{i}", "text": f"tool selection {r['tool_selection_accuracy']:.0%}", "sub":
             f"answers {r['answer_accuracy']:.0%}; {r['total_tokens']} tokens; cost ${r['total_cost_usd']:.2f}; "
             f"p95 {r['p95_latency_ms']} ms", "x": 0.75, "y": y, "w": 0.25, "h": 0.26, "style": "soft", "size": 13},
        ]
        edges += [{"a": "run", "b": f"r{i}", "mode": "c"}, {"a": f"r{i}", "b": f"m{i}"}]
    nodes.append({"id": "cmp", "text": "two runs compared, question by question", "x": 0.54, "y": 0.8, "w": 0.46,
                  "h": 0.16, "style": "line", "size": 14})
    return {
        "kind": "canvas",
        "kicker": "Evals",
        "title": "Evals measure a model on golden questions before anyone trusts it",
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.0, "y": 0.7, "w": 0.46, "h": 0.28, "size": 12, "italic": True, "text": "Run at this build "
                   "on the offline mock, at zero cost. The mock shows the harness, not a model's quality; the same "
                   "set measures a real model before it is trusted."}],
        "source": "Run at build time (evidence.eval_runs) with sajha.quality.evals over config/evals/calculators.yaml; "
        "docs/architecture/Tool Quality.md.",
        "talk": "An eval set is a file of golden questions. Each names the tools that must and must not be called, "
        "checks on the answer, and limits on steps, tokens, cost and latency. The harness runs the set per model and "
        "planner and measures pass rate, tool-selection and answer accuracy, tokens, cost, and mean and p95 latency; "
        "two runs can be compared question by question. The numbers here were produced while the deck was built, on "
        "the offline mock, so they show the harness working, not how good a real model is.",
    }


def _quality() -> dict[str, Any]:
    stages = [("Tests", "cases with HTTP cassettes, replayed offline; JUnit for CI", "white"),
              ("Lint", "JSON Schema 2020-12, descriptions, examples, names, annotations", "white"),
              ("Versions", "several behind one name: pin, user, role", "soft"),
              ("Canary", "a percentage of calls to the new version", "accent"),
              ("Released", "sunset dates retire old versions", "dark")]
    xs = row(len(stages), 0.0, 1.0, 0.17)
    nodes = [{"id": f"s{i}", "text": t, "sub": sub, "x": xs[i], "y": 0.1, "w": 0.17, "h": 0.32, "style": st,
              "size": 16} for i, (t, sub, st) in enumerate(stages)]
    nodes += [
        {"id": "rb", "text": "Automatic rollback", "sub": "a canary that errors or slows down", "x": xs[2], "y": 0.62,
         "w": 0.38, "h": 0.17, "style": "bad", "size": 14},
        {"id": "pr", "text": "Probes", "sub": "call tools on a schedule; one worker claims each slot", "x": xs[4] - 0.03,
         "y": 0.6, "w": 0.2, "h": 0.22, "style": "box", "size": 14},
        {"id": "ev", "text": "Evals", "sub": "the same harness for models and planners", "x": 0.0, "y": 0.62,
         "w": 0.3, "h": 0.17, "style": "line", "size": 14},
    ]
    edges = [{"a": f"s{i}", "b": f"s{i + 1}", "color": "CRIMSON"} for i in range(len(stages) - 1)]
    edges += [{"a": "s3", "b": "rb", "color": "BAD", "label": "fails", "lsize": 10},
              {"a": "rb", "b": "s2", "color": "BAD", "label": "back", "lsize": 10},
              {"a": "pr", "b": "s4", "dash": True, "label": "watch", "lsize": 10}]
    return {
        "kind": "canvas",
        "kicker": "Tool quality",
        "title": "Tools are tested, linted, probed, versioned and released by canary",
        "nodes": nodes,
        "edges": edges,
        "source": "docs/architecture/Tool Quality.md; sajha/quality/; sajha/core/tool_versioning.py.",
        "talk": "A tool's life runs left to right. Its test cases replay recorded HTTP cassettes offline and report "
        "JUnit for CI. A static linter checks the schema is valid JSON Schema 2020-12 and that descriptions, "
        "examples, names and annotations are good enough for a model to use. Several versions can live behind one "
        "name, routed by pin, user or role, and a new one starts as a canary on a percentage of calls; a canary that "
        "errors or slows down is rolled back automatically, and sunset dates retire old versions. Probes call tools "
        "on a schedule, one worker per slot, and the same harness evaluates models and planners.",
    }


def _observability() -> dict[str, Any]:
    lanes = [("Metrics", "Prometheus at /metrics, protected", "HTTP, MCP and tool calls, latency, cache hits, tokens "
              "and spend, sandbox runs, policy decisions"),
             ("Traces", "OpenTelemetry over OTLP, opt-in", "a span per request, tool call and model call, with the "
              "caller attached"),
             ("Usage and cost", "a dashboard in the console", "calls, errors, tokens and spend by user, key, role, "
              "model, tool and day; budgets; CSV export"),
             ("Alerts", "rules on rates, latency and spend", "error rates, p95 latency, LLM spend, open breakers: to a "
              "log, an email or a guarded webhook")]
    nodes = [{"id": "sj", "text": "SAJHA", "sub": "every worker", "x": 0.0, "y": 0.25, "w": 0.13, "h": 0.5,
              "style": "dark", "size": 18}]
    edges = []
    for i, (t, where, what) in enumerate(lanes):
        y = 0.01 + i * 0.25
        nodes += [
            {"id": f"k{i}", "text": t, "x": 0.2, "y": y, "w": 0.15, "h": 0.2, "style": "accent", "size": 15},
            {"id": f"w{i}", "text": where, "x": 0.41, "y": y, "w": 0.2, "h": 0.2, "style": "soft", "size": 13},
            {"id": f"d{i}", "text": what, "x": 0.66, "y": y, "w": 0.34, "h": 0.2, "style": "white", "size": 12,
             "bold": False},
        ]
        edges += [{"a": "sj", "b": f"k{i}", "ports": ("r", "l"), "at": (0.2 + 0.2 * i, 0.5)},
                  {"a": f"k{i}", "b": f"w{i}", "color": "CRIMSON"}, {"a": f"w{i}", "b": f"d{i}", "dash": True,
                                                                     "arrow": False}]
    return {
        "kind": "canvas",
        "kicker": "Observability",
        "title": "Metrics, traces, cost and alerts, out of the box",
        "nodes": nodes,
        "edges": edges,
        "source": "docs/architecture/Observability.md §2–§5; sajha/observability/metrics.py, tracing.py, usage.py, "
        "alerts.py; deployment/observability/.",
        "talk": "Four signals leave every worker. Prometheus metrics at /metrics, protected, count HTTP, MCP and tool "
        "calls, latency, cache hits, model tokens and spend, sandbox runs, policy decisions and audit export. "
        "OpenTelemetry traces, when turned on, give a span per request, tool call and model call with the caller "
        "attached. A usage and cost dashboard breaks calls, errors, tokens and spend down by user, key, role, model, "
        "tool and day, with budgets and CSV export. Alert rules watch error rates, p95 latency, spend and open "
        "circuit breakers, and notify a log, an email or a guarded webhook. deployment/observability ships the "
        "Prometheus, Grafana and alert configuration.",
    }


def _sandbox(F: dict[str, Any]) -> dict[str, Any]:
    bx = row(len(F["sandbox"]), 0.02, 0.47, 0.1)
    ax = row(len(F["accounts"]), 0.535, 0.985, 0.07)
    nodes = [
        {"id": "uc", "text": "User code", "sub": "Studio Python and script tools, the admin shell", "x": 0.02,
         "y": 0.08, "w": 0.2, "h": 0.24, "style": "white", "size": 14},
        {"id": "sp", "text": "A process per call", "sub": "no server environment; no network unless allowed",
         "x": 0.27, "y": 0.08, "w": 0.2, "h": 0.24, "style": "accent", "size": 14},
        *[{"id": f"b{i}", "text": b, "x": bx[i], "y": 0.42, "w": 0.1, "h": 0.1, "style": "soft", "size": 12,
           "font": "Consolas", "bold": False} for i, b in enumerate(F["sandbox"])],
        {"id": "bi", "text": "Built-in tools run in-process", "sub": "not sandboxed; on macOS and Windows the default "
         "gives only a clean environment and limits", "x": 0.02, "y": 0.66, "w": 0.45, "h": 0.22, "style": "warn",
         "size": 13},
        *[{"id": f"a{i}", "text": a, "x": ax[i], "y": 0.08, "w": 0.07, "h": 0.1, "style": "white", "size": 10,
           "bold": False} for i, a in enumerate(F["accounts"])],
        {"id": "vt", "text": "The vault", "sub": "AES-256-GCM, bound to user and provider", "x": 0.535, "y": 0.34,
         "w": 0.2, "h": 0.22, "style": "dark", "shape": "can", "size": 14},
        {"id": "tc", "text": "A tool acts as the user", "sub": "with that user's token, only to the provider's listed "
         "hosts", "x": 0.785, "y": 0.34, "w": 0.2, "h": 0.22, "style": "accent", "size": 13},
        {"id": "nc", "text": "per-user results never cached", "x": 0.785, "y": 0.68, "w": 0.2, "h": 0.14,
         "style": "box", "size": 12},
    ]
    edges = [{"a": "uc", "b": "sp", "color": "CRIMSON"}, {"a": "vt", "b": "tc", "color": "CRIMSON"},
             {"a": "tc", "b": "nc", "dash": True, "arrow": False}]
    edges += [{"a": "acc", "b": "vt", "label": "links once", "lsize": 10.5}, {"a": "sp", "b": "bk", "dash": True}]
    return {
        "kind": "canvas",
        "kicker": "Sandbox and connected accounts",
        "title": "User code runs in a sandbox; a user's tokens stay in a vault",
        "groups": [
            {"id": "g1", "label": "SANDBOX", "x": 0.0, "y": 0.0, "w": 0.49, "h": 1.0},
            {"id": "g2", "label": "CONNECTED ACCOUNTS", "x": 0.515, "y": 0.0, "w": 0.485, "h": 1.0},
            {"id": "acc", "x": 0.527, "y": 0.065, "w": 0.465, "h": 0.135, "line": "RULE", "dash": True},
            {"id": "bk", "x": 0.012, "y": 0.39, "w": 0.466, "h": 0.16, "line": "RULE", "dash": True},
        ],
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.535, "y": 0.62, "w": 0.23, "h": 0.3, "size": 12, "text": "Or any OAuth 2.0 service; tools "
                   "that declare it call with the linking user's token."}],
        "source": "sajha/sandbox/backends.py BACKENDS and sajha/accounts/providers.py TEMPLATES, read at build time; "
        "docs/architecture/Sandbox.md, Connected Accounts.md; Security Model §8.",
        "talk": "User code, the Studio's Python and script tools and the admin shell, runs one process per call, with "
        f"no server environment and no network unless allowed, on one of the backends {listing(F['sandbox'])}. "
        "Built-in tools are not sandboxed: they run in the server process, and on macOS and Windows the default "
        f"backend gives only a clean environment and limits. On the right, a user links {listing(F['accounts'])} or "
        "any OAuth 2.0 service once; the token is kept in a vault encrypted with AES-256-GCM and bound to that user "
        "and provider, sent only to the provider's listed hosts, and results made with it are never cached.",
    }


def _storage(F: dict[str, Any], storage: list[str]) -> dict[str, Any]:
    pods = [{"id": f"p{i}", "text": "SAJHA pod", "x": 0.56 + i * 0.15, "y": 0.1, "w": 0.13, "h": 0.17,
             "style": "accent", "size": 13} for i in range(3)]
    return {
        "kind": "canvas",
        "kicker": "Storage and state",
        "title": "One process on a laptop, or several pods in a cluster",
        "groups": [{"id": "g1", "label": "ON A LAPTOP: THE DEFAULTS", "x": 0.0, "y": 0.0, "w": 0.4, "h": 0.8},
                   {"id": "g2", "label": "IN A CLUSTER", "x": 0.44, "y": 0.0, "w": 0.56, "h": 0.8}],
        "nodes": [
            {"id": "one", "text": "One SAJHA process", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.17, "style": "accent",
             "size": 14},
            {"id": "ld", "text": "local disk", "sub": "config and tool files", "x": 0.02, "y": 0.45, "w": 0.115,
             "h": 0.24, "style": "white", "size": 12},
            {"id": "ms", "text": "memory", "sub": "protocol state", "x": 0.143, "y": 0.45, "w": 0.115, "h": 0.24,
             "style": "white", "size": 12},
            {"id": "sq", "text": "SQLite", "sub": "creates its own tables", "x": 0.266, "y": 0.45, "w": 0.115,
             "h": 0.24, "style": "white", "shape": "can", "size": 12},
            *pods,
            {"id": "os", "text": "object store", "sub": listing([x for x in storage if x != "local disk"], "or")
             + ", with hot reload", "x": 0.46, "y": 0.45, "w": 0.165, "h": 0.26, "style": "white", "size": 12},
            {"id": "st", "text": "state store", "sub": "redis or database: shared by every worker", "x": 0.645,
             "y": 0.45, "w": 0.165, "h": 0.26, "style": "white", "size": 12},
            {"id": "pg", "text": "PostgreSQL", "sub": "schema file run once by an operator", "x": 0.83, "y": 0.45,
             "w": 0.155, "h": 0.26, "style": "white", "shape": "can", "size": 12},
        ],
        "edges": [{"a": "one", "b": "ld", "mode": "c"}, {"a": "one", "b": "ms"}, {"a": "one", "b": "sq", "mode": "c"},
                  {"a": "p0", "b": "os", "mode": "c"}, {"a": "p1", "b": "st"}, {"a": "p2", "b": "pg", "mode": "c"}],
        "texts": [{"x": 0.0, "y": 0.84, "w": 1.0, "h": 0.16, "size": 12, "text":
                   "Packaging: a non-root container image, a Helm chart, Kustomize; recipes: "
                   + listing(r for r in F["recipes"] if r not in ("k8s", "observability")) + ". Caches, circuit "
                   "breakers and metrics stay per process on purpose."}],
        "source": "StorageBackend subclasses in sajha/core/storage.py; sajha.core.state.BACKENDS; db/scripts/*/; "
        "deployment/*/, all listed at build time; docs/architecture/Scaling and State.md.",
        "talk": f"On a laptop everything takes its default: files on local disk, protocol state in memory, and SQLite, "
        "which creates its own tables. In a cluster, several pods share their files through an object store "
        f"({listing([x for x in storage if x != 'local disk'], 'or')}) with hot reload, share sessions, tasks, OAuth "
        "codes, counters and approvals through a redis or database state store, and use PostgreSQL from one schema "
        "file an operator runs. Caches, circuit breakers and metrics stay per process on purpose. The image runs as a "
        "non-root user, and there is a Helm chart, Kustomize and deployment recipes.",
    }


def _clients(F: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "canvas",
        "kicker": "Clients",
        "title": "A Python client, a command line, and agent-to-agent",
        "nodes": [
            {"id": "sdk", "text": "sajhaclient", "sub": "the Python client SDK, on the official MCP SDK: /mcp and REST; "
             "adopts the newest era; API key, JWT or OAuth", "x": 0.0, "y": 0.0, "w": 0.3, "h": 0.26, "style": "white",
             "size": 15},
            {"id": "cli", "text": "sajha", "sub": f"the command line: {listing(F['cli'])}", "x": 0.0, "y": 0.36,
             "w": 0.3, "h": 0.3, "style": "white", "size": 15, "font": "Consolas"},
            {"id": "dt", "text": "Desktop clients", "sub": "sajha serve --stdio, for Claude Desktop, Claude Code and others",
             "x": 0.0, "y": 0.76, "w": 0.3, "h": 0.22, "style": "white", "size": 14},
            {"id": "sj", "text": "SAJHA", "sub": "the same tool access on every path", "x": 0.42, "y": 0.25,
             "w": 0.18, "h": 0.5, "style": "dark", "size": 20},
            {"id": "ag", "text": "Other agents", "sub": "A2A: the agent card at /.well-known/agent.json", "x": 0.73,
             "y": 0.1, "w": 0.27, "h": 0.26, "style": "white", "shape": "oval", "size": 14},
            {"id": "a2a", "text": "POST /a2a", "sub": "JSON-RPC: tasks/send, tasks/get, tasks/cancel", "x": 0.73,
             "y": 0.58, "w": 0.27, "h": 0.26, "style": "soft", "size": 14},
        ],
        "edges": [
            {"a": "sdk", "b": "sj", "mode": "c"},
            {"a": "cli", "b": "sdk", "label": "built on", "lsize": 11},
            {"a": "cli", "b": "sj", "color": "CRIMSON", "label": "profiles; JSON", "lsize": 11},
            {"a": "dt", "b": "sj", "mode": "c"},
            {"a": "ag", "b": "a2a", "dash": True, "label": "discover", "lsize": 11},
            {"a": "a2a", "b": "sj", "mode": "c", "color": "CRIMSON"},
        ],
        "source": "clientsdk/sajhaclient (standard.py SajhaMCPClient, a2a_client.py, auth.py); CLI commands parsed "
        "from clientsdk/sajhaclient/cli/main.py at build time; sajha/routes/a2a_routes.py; docs/clients/Command "
        "Line.md.",
        "talk": "sajhaclient is SAJHA's Python client, built on the official MCP SDK; it adopts the newest protocol era "
        "the server offers, includes REST and A2A clients, and authenticates with an API key, a JWT or OAuth. The "
        "sajha command line is part of it, with profiles per server and JSON output. sajha serve --stdio runs SAJHA as "
        "a stdio server for desktop clients such as Claude Desktop and Claude Code, with the caller set by --user or "
        "--api-key. Other agents find SAJHA's agent card and send it tasks over A2A, under the same tool access as "
        "every other caller.",
    }


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
        _storage(F, storage),
        _clients(F),
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
            "talk": "The database schema is two files, one for PostgreSQL and one for SQLite, defining the "
                "same tables, grouped here by purpose. There are no migrations: SAJHA never runs DDL on "
                "PostgreSQL, where an operator runs the schema and seed files, which are safe to re-run; "
                "SQLite creates its own tables. A test keeps both files in step with the models.",
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
            "talk": "Built things are on the capability slides; this slide is only what is not built yet and "
                "what is known to be limited. The left column is the open items of the Roadmap, parsed "
                "when the deck is built. The right column is the known limitations from the Security "
                "Model, such as plain credential storage by default and the test admin key shipping on, "
                "so a deployment can compensate.",
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
            "talk": "The comparison comes from the data behind the /comparison page, where every cell has a "
                "note and a source URL from the vendor's own public documentation, dated. Part means "
                "partial, a preview or a paid tier; a question mark means public documentation did not "
                "say. The ten columns were chosen to show differences, not to flatter.",
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
            "talk": "Where others are stronger, said plainly. Gateways are built to put many MCP servers "
                "behind one endpoint at scale. Some products run each server in its own container, while "
                "SAJHA sandboxes only user code. Hosted catalogs connect thousands of SaaS apps with per-"
                "user sign-in. And some products are open source or run for you; SAJHA is proprietary and"
                " self-hosted by decision. The names are computed from the comparison data.",
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
            "talk": "Pick the row that fits. To try it, install the requirements, run the web server and open"
                " the console. To connect a client, point it at /mcp or run the stdio server. To review "
                "security, read the access policy and try a rule on the Policies test bench. To add "
                "tools, describe one, import an API or connect a database. To run it, install the Helm "
                "chart with a shared state backend. Every guide named is also served inside the app.",
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
            "talk": "Thank you. SAJHA is proprietary and no licence is granted by this deck; for licensing "
                "and enquiries, use the address on the slide.",
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
