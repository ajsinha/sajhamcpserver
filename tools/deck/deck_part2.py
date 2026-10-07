"""
The deck, as data. Parts 3 and 4: one question end to end, captured from a real run on
the offline mock model while the deck is built; and speaking every client's language.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from prose import js, listing, wrap


def _part3(F: dict[str, Any]) -> list[dict[str, Any]]:
    ask, cat, conf, ev = F["ask"], F["catalog"], F["confidence"], F["evals"]
    name, args, summary, latency, step_conf = ask["steps"][0]
    shown = ask["shortlist"][:12]
    run_src = (
        "A real run captured while the deck was built (tools/deck/evidence.py, ask_run): "
        f"IntelligenceService.stream_ask over the full registry ({cat['tools']} tools) on the offline "
        f"mock provider ({ask['model']}), planner {ask['planner']}, question {ask['question']!r}."
    )
    bits = 0.0 if step_conf >= 1 else None
    react, plan = ev["runs"]["react"], ev["runs"]["plan_execute"]
    return [
        {
            "kind": "divider",
            "num": "3",
            "title": "One question, end to end",
            "sub": "Before any architecture, one question carried through SAJHA, captured from a real run "
            "when this deck was built: on the offline mock model, over the whole catalog, with nothing "
            "staged.",
            "points": [
                "Four moves: shortlist, plan, call, answer",
                "The shortlist",
                "The governed call",
                "The answer, its source and its confidence",
                "What the run does not show",
            ],
        },
        {
            "kind": "flow",
            "kicker": "Ask SAJHA",
            "title": "Ask SAJHA answers in four moves, and the browser draws each one",
            "intro": "Open /ask and the catalog is drawn as a night sky, the constellation: one star per "
            "tool, clustered by group. As a question is answered, the stars it shortlists light up and a "
            "line is drawn to each tool it calls, with the result beside it.",
            "box_h": 2.25,
            "steps": [
                (
                    "1  Shortlist",
                    "A search over every tool's name and description ranks the catalog; tools the caller "
                    "may not run are dropped before any model sees them.",
                ),
                (
                    "2  Plan",
                    "A planner asks the model what to do next: answer, or call which shortlisted tools "
                    "with which arguments.",
                ),
                (
                    "3  Governed call",
                    "Each call takes the path every client's call takes: schema, access, policy, cache, "
                    "circuit breaker, audit.",
                ),
                (
                    "4  Answer",
                    "A final call writes the answer and cites the calls it rests on; SAJHA attaches a "
                    "confidence it computed itself.",
                ),
            ],
            "items": [
                "The page animates a stream of events, here in the order the run emitted them: "
                + " → ".join(ask["events"])
                + ".",
            ],
            "source": "sajha/ai/intelligence.py (stream_ask and its event schema); the constellation is "
            "sajha/web/templates (Ask SAJHA page) fed by live_tool_groups(with_names=True). " + run_src,
        },
        {
            "kind": "split",
            "kicker": "Move 1, captured",
            "title": f"{cat['tools']} tools in, {len(ask['shortlist'])} offered to the model",
            "left_w": 0.5,
            "left": {
                "head": "The shortlist event",
                "lines": [f"# question: {ask['question']}", "# score  tool"]
                + [f"{s:.3f}  {n}" for n, s in shown]
                + ([f"# … {len(ask['shortlist']) - len(shown)} more"] if len(ask["shortlist"]) > len(shown) else []),
            },
            "right": {
                "head": "What happened",
                "items": [
                    f"No model chose these. The resolver ranked all {cat['tools']} tool descriptions "
                    "against the question by word overlap (BM25), because no embedding model is configured.",
                    "The calculator ranks first; market-data tools that mention “percentage change” follow. "
                    "The model, not the shortlist, makes the final choice.",
                    "Tools the caller may not run are removed first, by the same check the REST API applies: "
                    "a model cannot be talked into a tool its user cannot call.",
                    f"Only the top {ask['shortlist_setting']} (ai.ask.shortlist) reach the model, so a large "
                    "catalog does not become a large prompt.",
                ],
                "size": 16,
            },
            "source": run_src + " Shortlist size: AskSettings().shortlist. Ranking: sajha/ai/tool_resolver.py "
            "and sajha/ai/lexical.py (BM25 when no embedder).",
        },
        {
            "kind": "split",
            "kicker": "Moves 2 and 3, captured",
            "title": "The model asked for one call, and SAJHA ran it as it runs any client's",
            "left_w": 0.5,
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
                    ("Checked", "The arguments against the schema, the caller's access, and the policy "
                     "rules in force (none, in the shipped default)."),
                    ("Ran", "Through the tool's cache and its provider's circuit breaker, counted in the "
                     "metrics."),
                    ("Refused what was not offered", "A call to a tool outside the shortlist is refused; a "
                     "tool marked destructive waits for the user's confirmation."),
                    ("Treated the result as data", "It returns to the model as data; the system prompt "
                     "says tool output is never an instruction."),
                ],
                "size": 16,
            },
            "source": run_src + " The safeguards: IntelligenceService._run_call and SYSTEM_PROMPT "
            "(sajha/ai/intelligence.py); BaseMCPTool.execute_with_tracking; config/policies/00-default.yaml "
            "(no rules).",
        },
        {
            "kind": "split",
            "kicker": "Move 4, captured",
            "title": "The answer cites its source, and SAJHA sets the confidence",
            "left_w": 0.5,
            "left": {
                "head": "The answer",
                "lines": [
                    "→ answer",
                    *wrap(ask["answer"], 50),
                    "",
                    f"→ citations {', '.join(ask['citations'])}",
                    f"→ confidence {ask['confidence']:.2f}",
                    f"  basis: {name} {step_conf:.2f}"
                    + (f", {bits:.1f} bits of entropy" if bits is not None else ""),
                    "",
                    f"# {ask['tokens']} tokens, {ask['duration_ms']} ms end to end",
                ],
            },
            "right": {
                "head": "How the number is made",
                "items": [
                    ("Sources", "Citations name the tool calls the answer rests on; a citation to a "
                     "failed call is dropped."),
                    ("Confidence", f"Each cited step contributes its tool's confidence ({conf['calc']:.2f} "
                     f"for a calculator, {conf['fred']:.2f} for a FRED series, {conf['web']:.2f} for a web "
                     "fetch), chained through the entropy guard (Part 6)."),
                    ("Not an opinion", f"A failed call contributes {conf['failed']}, an incomplete loop "
                     f"{conf['incomplete']}, an answer resting on no tool {conf['unverified']}. The model is "
                     "never asked how sure it is."),
                ],
                "size": 16,
            },
            "source": run_src + " Confidence rules: IntelligenceService._confidence and UNVERIFIED_CONFIDENCE "
            "(sajha/ai/intelligence.py), get_tool_confidence (sajha/core/composition.py), read at build time.",
        },
        {
            "kind": "bullets",
            "kicker": "Honesty about the run",
            "title": "What this run shows, and what it does not",
            "items": [
                (
                    "It shows the mechanism",
                    "Shortlisting, access checks, the governed call, citations and confidence are SAJHA's "
                    "code, and they behave the same whichever model plans.",
                ),
                (
                    "It does not show reasoning",
                    "The mock model is a deterministic pattern-matcher, shipped so that everything works "
                    "offline with no keys. Planning a multi-part question well needs a real model (Part 7).",
                ),
                (
                    "It is measured, not asserted",
                    f"The shipped eval set “{ev['set']}” ({ev['questions']} golden questions) passed "
                    f"{react['passed']}/{react['questions']} with the react planner and "
                    f"{plan['passed']}/{plan['questions']} with plan_execute on the mock, when this deck was "
                    "built. The same set measures a real model before anyone trusts it.",
                ),
                (
                    "It is reproducible",
                    "Rebuilding the deck asks the question again; if the run stops answering, the build fails.",
                ),
            ],
            "source": "Eval runs: sajha.quality.evals.run_set over config/evals/calculators.yaml on "
            "mock/mock-planner with planners react and plan_execute, run by tools/deck/evidence.py "
            f"(react: pass rate {react['pass_rate']}, tool-selection accuracy {react['tool_selection_accuracy']}; "
            f"plan_execute: pass rate {plan['pass_rate']}). Mock provider: sajha/ai/llm/mock.py.",
        },
    ]


def _part4(F: dict[str, Any]) -> list[dict[str, Any]]:
    eras, ci, cf = F["eras"], F["ci"], F["conformance"]
    matrix = listing(f"{spec} (suite {suite})" for spec, suite in ci["matrix"])
    return [
        {
            "kind": "divider",
            "num": "4",
            "title": "Speaking every client's language",
            "sub": "A catalog is only shared if every client can reach it. The clients in use today speak "
            "two eras of MCP over four transports; SAJHA serves all of them on one address, and runs the "
            "official conformance suite against itself on every push.",
            "points": [
                "Two eras on one endpoint",
                "Four transports",
                "The conformance suite, in CI",
                "Streaming, input mid-call, tasks, views",
            ],
        },
        {
            "kind": "table",
            "kicker": "Eras",
            "title": "Two eras on one endpoint, recognised request by request",
            "col_w": [1.3, 1.7, 3.2, 1.8],
            "rows": [
                ["Era", "Versions", "How SAJHA recognises it", "Who sends it"],
                [
                    "Stateless",
                    listing(eras["modern"]),
                    "The request names its protocol version in _meta (or a non-handshake "
                    "MCP-Protocol-Version header); there is no session.",
                    "Clients on current SDKs",
                ],
                [
                    "Session-based",
                    listing(eras["handshake"]),
                    "An initialize handshake opens a session (Mcp-Session-Id) that later requests carry.",
                    "Most clients in the field",
                ],
                [
                    "Either",
                    "—",
                    "Decided per request on POST /mcp, so one deployment serves a mixed fleet; the Python "
                    "client probes server/discover and adopts the newest.",
                    "Mixed estates",
                ],
            ],
            "note": "Session state (and task records, rate limits and OAuth codes) goes through a shared "
            "store, so either era works across several workers (Part 8).",
            "source": "sajha/core/mcp_modern.py (MODERN_PROTOCOL_VERSIONS, HANDSHAKE_PROTOCOL_VERSIONS, read "
            "at build time), sajha/core/mcp_2025_11_25.py; GLOSSARY.md 'Era detection', 'Client SDK'.",
        },
        {
            "kind": "table",
            "kicker": "Transports",
            "title": "Four transports, with the same catalog and the same rules on each",
            "col_w": [1.6, 2.1, 3.3],
            "rows": [
                ["Transport", "Where", "Typical client"],
                ["Streamable HTTP", "POST /mcp", "Remote clients of both eras; a JSON or a streamed (SSE) "
                 "response"],
                ["HTTP+SSE (legacy)", "/mcp/sse", "Older clients that predate Streamable HTTP"],
                ["WebSocket", "/mcp/ws", "Browsers and long-lived connections"],
                [
                    "stdio",
                    "sajha serve --stdio, or run_server.py --stdio",
                    "Desktop clients such as Claude Desktop and Claude Code; one caller per process, set by "
                    "--user or --api-key",
                ],
            ],
            "note": "From outside, SAJHA also ships sajhaclient (Python, on the official MCP SDK), REST and "
            "A2A clients, and the sajha command line.",
            "source": "sajha/routes/mcp_routes.py, sajha/routes/ws_routes.py, sajha/cli/stdio.py; the SAJHA "
            "column of sajha/web/competitive.py (remote_transports, stdio, client_sdk).",
        },
        {
            "kind": "stats",
            "kicker": "Evidence",
            "title": f"The official conformance suite: {cf['passed']} checks passed, {cf['failed']} failed",
            "intro": "The CI workflow starts a live SAJHA and runs the official MCP conformance suite once per "
            f"era, {matrix}, on every push to {listing(ci['branches'])}. The compliance report records those "
            "runs and two more suites run against the same server, for tasks and for the built-in "
            "authorization server:",
            "stats": [
                (str(cf["passed"]), "checks passed, over the four suites below"),
                (str(cf["failed"]), "checks failed"),
                (str(len(ci["matrix"])), "eras in the CI matrix, each with a pinned suite"),
            ],
            "rows": [["Suite", "Scenarios", "Checks passed", "Failed"]]
            + [[r["suite"], r["scenarios"], str(r["passed"]), str(r["failed"])] for r in cf["rows"]],
            "col_w": [4.2, 1.0, 1.1, 0.8],
            "note": "A release is only as compliant as the last green run of the workflow.",
            "source": "Results: the table in section 5 of docs/protocol/MCP 2026-07-28 Compliance.md, parsed "
            f"at build time ({cf['legacy']['scenarios']} scenarios on the 2025-11-25 path agree with "
            "docs/protocol/MCP 2025-11-25 Compliance.md). Matrix and branches: "
            ".github/workflows/mcp-conformance.yml, parsed at build time.",
        },
        {
            "kind": "cards",
            "kicker": "Beyond list and call",
            "title": "Streaming, cancellation, input mid-call, long tasks and views",
            "cols": 3,
            "cards": [
                ("STREAMING", "Progress and logs while a tool runs",
                 "A tool reports progress and log lines; a client that asked for them receives them over "
                 "the streamed response."),
                ("CANCELLATION", "A client can stop a call",
                 "A cancelled request is visible to the running tool (is_cancelled), which can stop early."),
                ("MRTR", "Multi Round-Trip Requests",
                 "A stateless server asks for input mid-call (a form, a confirmation) by answering "
                 "input_required; the client retries with the answers."),
                ("TASKS", "Long calls become tasks",
                 "A task-capable tool returns a task id; the client polls tasks/get, answers input with "
                 "tasks/update, or cancels."),
                ("MCP APPS", "A tool can ship its own view",
                 "An interactive HTML view (ui://) the client renders beside the result, such as the loan "
                 "schedule chart of calc_loan_amortization."),
                ("HEADERS", "Routing without reading the body",
                 "Mcp-Method, Mcp-Name and Mcp-Param-* headers let a gateway route and filter "
                 "2026-07-28 traffic."),
            ],
            "source": "GLOSSARY.md §3 (MRTR, Tasks extension, MCP Apps, Mcp-Param-{Name}) and "
            "mcp_tool_context; sajha/core/mcp_mrtr.py, mcp_tasks.py, mcp_apps.py, mcp_tool_context.py; "
            "docs/protocol/MCP 2026-07-28 Compliance.md §4.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _part3(F) + _part4(F)
