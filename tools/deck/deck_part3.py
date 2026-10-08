"""
The deck, as data. Section 4: agents, composition and workflows (agents, a worked analysis,
several agents on one server, composite tools and the Composition Framework, workflows and a
run, how tool, composite, workflow and published tool fit, extending the server, hot reload,
and how a tool is made, step by step); and section 6: data and analytics (search, DuckDB and
OLAP, the financial calculators, the connector guard, and search combined with analytics).
Section 5, SAJHA Net, is ``deck_net``; ``sajha_deck`` puts them in order.

Every tool named on these slides is checked against the live registry while the deck is
built; the worked workflows are marked illustrative.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from diagrams import layered, row
from evidence import SourceChanged, require_tools, short_description
from prose import listing

# How each workflow step kind is drawn; a kind the engine defines and this map does not fails the build.
STEP_LOOK = {
    "tool": ("white", "round"),
    "composite": ("line", "round"),
    "ask": ("soft", "round"),
    "condition": ("gold", "diamond"),
    "foreach": ("box", "hex"),
    "wait": ("box", "oval"),
    "approval": ("warn", "round"),
}
# Words for each trigger type on the workflow slide; an unknown type fails the build.
TRIGGER_WORDS = {
    "cron": "cron schedule",
    "webhook": "signed webhook",
    "file": "file arrives",
    "event": "change-bus event",
    "manual": "by hand: page, CLI, API",
}


def _composition(F: dict[str, Any]) -> list[dict[str, Any]]:
    """Composite tools, the Composition Framework, workflows, a run, and how they fit."""
    cp, wf, nt = F["compose"], F["workflows"], F["net"]
    sep = nt["sep"]
    master, rest = cp["master"], cp["rest"]
    conf = cp["conf"]
    missing = [k for k in wf["steps"] if k not in STEP_LOOK] + [t for t in wf["all_triggers"] if t not in TRIGGER_WORDS]
    if missing:
        raise SourceChanged(f"workflow step kinds or triggers with no drawing on the deck: {missing}")
    if set(wf["active"]) | set(wf["done"]) != {"queued", "running", "waiting", "succeeded", "failed", "cancelled"}:
        raise SourceChanged(f"workflow run states changed: {wf['active'] + wf['done']}")
    ex = wf["example"]

    # The composite: one sibling lane and one parent-child lane inside one governed call.
    composite = {
        "kind": "canvas",
        "kicker": "Composite tools",
        "title": "A composite chains tools, and the whole chain is one governed call",
        "groups": [
            {"id": "g", "label": "ONE GOVERNED CALL: THE COMPOSITE IS A REGISTRY TOOL", "x": 0.11, "y": 0.0,
             "w": 0.72, "h": 1.0},
            {"id": "rec", "label": "FOR EACH RECORD", "x": 0.335, "y": 0.6, "w": 0.235, "h": 0.36, "dash": True,
             "line": "SLATE", "size": 9.5, "color": "SLATE"},
        ],
        "texts": [
            {"x": 0.13, "y": 0.1, "w": 0.2, "h": 0.07, "text": "SIBLING: steps side by side", "bold": True,
             "color": "CRIMSON_D", "size": 10.5},
            {"x": 0.13, "y": 0.54, "w": 0.2, "h": 0.07, "text": "PARENT-CHILD: per record", "bold": True,
             "color": "CRIMSON_D", "size": 10.5},
        ],
        "nodes": [
            {"id": "caller", "text": "Caller", "sub": "any client", "x": 0.0, "y": 0.38, "w": 0.085, "h": 0.24,
             "style": "white", "shape": "oval", "size": 12},
            {"id": "ms", "text": "master", "sub": master, "x": 0.13, "y": 0.2, "w": 0.17, "h": 0.2, "style": "accent",
             "size": 13},
            *[{"id": f"s{i}", "text": t, "x": 0.35, "y": 0.155 + i * 0.105, "w": 0.2, "h": 0.085, "style": "white",
               "size": 11, "bold": False} for i, t in enumerate(rest)],
            {"id": "js", "text": "Weakest link", "sub": "master × min(steps)", "x": 0.61, "y": 0.2, "w": 0.19,
             "h": 0.2, "style": "soft", "size": 13},
            {"id": "mp", "text": "master", "sub": "returns records", "x": 0.13, "y": 0.68, "w": 0.17, "h": 0.2,
             "style": "accent", "size": 13},
            {"id": "ca", "text": rest[0], "x": 0.35, "y": 0.69, "w": 0.2, "h": 0.09, "style": "white", "size": 11,
             "bold": False},
            {"id": "cb", "text": rest[2], "x": 0.35, "y": 0.83, "w": 0.2, "h": 0.09, "style": "white", "size": 11,
             "bold": False},
            {"id": "jp", "text": "Chained", "sub": "master × min(children)", "x": 0.61, "y": 0.68, "w": 0.19,
             "h": 0.2, "style": "soft", "size": 13},
            {"id": "res", "text": "Result", "sub": "+ _composition: confidence, entropy, trace", "x": 0.865,
             "y": 0.34, "w": 0.135, "h": 0.32, "style": "dark", "size": 13},
        ],
        "edges": [
            {"a": "caller", "b": "ms", "mode": "c"}, {"a": "caller", "b": "mp", "mode": "c"},
            *[{"a": "ms", "b": f"s{i}", "mode": "c"} for i in range(3)],
            *[{"a": f"s{i}", "b": "js", "mode": "c"} for i in range(3)],
            {"a": "mp", "b": "rec"}, {"a": "rec", "b": "jp"},
            {"a": "js", "b": "res", "mode": "c", "color": "CRIMSON"}, {"a": "jp", "b": "res", "mode": "c", "color": "CRIMSON"},
        ],
        "items": [
            ("Defined, not coded", "Saved in the database and registered as an ordinary MCP tool, callable in both eras."),
            ("Mapped, not leaked", "$input.x reads the composite's input and $.field the master's record; a step sees "
             "only the fields mapped to it."),
            ("Governed inside too", "Every step runs as the caller, so a step the caller may not run is refused; "
             "nesting is bounded by tools.max_call_depth."),
        ],
        "items_h": 1.45,
        "size": 14,
        "source": "docs/architecture/Composition Framework.md (status, mapping syntax); sajha/tools/composite_tool.py "
        "(arrangements 'sibling' and 'parent_child'; every step runs as the caller through sajha/core/inner_calls.py); "
        "tables composite_tools and composite_tool_steps in db/scripts/*/schema.sql. Tool names checked against the "
        "live registry at build time; the arrangement is illustrative.",
        "talk": "A composite is the smallest unit of orchestration in SAJHA. In a sibling composite the master tool "
        "runs once and the steps run side by side on its output; in a parent-child composite the master returns "
        "records and the children run once per record. Either way the caller sees one tool and gets one result, "
        "with a _composition block that says how confident the result is, how much entropy the chain carries, and "
        "a trace of every step with its time. Because the composite is itself a registry tool, the access check, "
        "schema validation, policy rules, cache and the audit record wrap the whole chain, and each inner step is "
        "checked again as the caller.",
    }

    seq_x = row(len(rest) + 1, 0.18, 0.81, 0.135)
    framework = {
        "kind": "canvas",
        "kicker": "The Composition Framework",
        "title": "Confidence through a chain: multiplied in sequence, weakest link in parallel",
        "nodes": [
            {"id": "p1", "text": "StepResult envelope", "sub": "an error short-circuits; confidence and trace "
             "accumulate", "x": 0.0, "y": 0.0, "w": 0.235, "h": 0.24, "style": "box", "size": 14},
            {"id": "p2", "text": "Lenses", "sub": "a step sees only the parameters mapped to it", "x": 0.255, "y": 0.0,
             "w": 0.235, "h": 0.24, "style": "box", "size": 14},
            {"id": "p3", "text": "EntropyGuard", "sub": f"refuses a chain above {cp['max_bits']:.1f} bits before it "
             "runs", "x": 0.51, "y": 0.0, "w": 0.235, "h": 0.24, "style": "box", "size": 14},
            {"id": "p4", "text": "Transport equivalence", "sub": "the client SDK's transports behave alike",
             "x": 0.765, "y": 0.0, "w": 0.235, "h": 0.24, "style": "box", "size": 14},
            *[{"id": f"q{i}", "text": t, "sub": f"{conf[t]:.2f}", "x": seq_x[i], "y": 0.34, "w": 0.135, "h": 0.15,
               "style": "accent" if i == 0 else "white", "size": 11} for i, t in enumerate([master, *rest])],
            {"id": "qr", "text": f"{cp['sequential']:.3f}", "sub": f"{cp['seq_bits']:.2f} bits", "x": 0.85, "y": 0.32,
             "w": 0.15, "h": 0.19, "style": "dark", "size": 18},
            {"id": "m", "text": master, "sub": f"{conf[master]:.2f}", "x": 0.18, "y": 0.73, "w": 0.15, "h": 0.15,
             "style": "accent", "size": 11},
            *[{"id": f"r{i}", "text": t, "sub": f"{conf[t]:.2f}", "x": 0.45, "y": 0.6 + i * 0.135, "w": 0.18,
               "h": 0.115, "style": "white", "size": 11} for i, t in enumerate(rest)],
            {"id": "pr", "text": f"{cp['parallel']:.3f}", "sub": f"{cp['par_bits']:.2f} bits", "x": 0.85, "y": 0.715,
             "w": 0.15, "h": 0.19, "style": "dark", "size": 18},
        ],
        "texts": [
            {"x": 0.0, "y": 0.33, "w": 0.17, "h": 0.18, "text": "SEQUENTIAL\nparent-child: multiply", "bold": True,
             "color": "CRIMSON_D", "size": 12},
            {"x": 0.0, "y": 0.72, "w": 0.17, "h": 0.18, "text": "PARALLEL\nsibling: master × min", "bold": True,
             "color": "CRIMSON_D", "size": 12},
        ],
        "edges": [
            *[{"a": f"q{i}", "b": f"q{i + 1}"} for i in range(len(rest))],
            {"a": f"q{len(rest)}", "b": "qr", "color": "CRIMSON"},
            *[{"a": "m", "b": f"r{i}", "mode": "c"} for i in range(len(rest))],
            *[{"a": f"r{i}", "b": "pr", "mode": "c", "color": "CRIMSON"} for i in range(len(rest))],
        ],
        "note": "The same four tools, arranged two ways, computed by sajha.core.composition while this deck was built. "
        "A calculator adds no doubt (1.00); a web search adds the most.",
        "source": "Run at build time (evidence.composition_compare): EntropyGuard.record_step, begin_parallel and "
        "end_parallel over get_tool_confidence for four registry tools; nothing is called. Pillars: "
        "docs/architecture/Composition Framework.md (StepResult, ParamLens, EntropyGuard in sajha/core/composition.py; "
        "TransportCoalgebra in clientsdk/sajhaclient/mcp_client.py).",
        "talk": "The framework borrows four ideas from category theory and keeps them practical. The StepResult "
        "envelope is Kleisli composition: once a step fails, nothing downstream runs, and the trace and timing "
        "accumulate. Lenses isolate parameters, so a field renamed in a master tool cannot silently feed a child. "
        "The EntropyGuard is a simplified Giry monad: it turns the chain's confidence into bits of entropy and "
        "refuses a composite that would pass the limit, before it runs. Sequential steps multiply, because each "
        "depends on the last; parallel steps take the weakest link, because they are independent. The fourth "
        "pillar is on the client side: the SDK's HTTP, SSE and WebSocket transports are checked to behave alike. "
        "Ask SAJHA uses the same priors for the confidence it attaches to an answer.",
    }

    # The workflow: triggers, a run, and the guide's example DAG laid out from its dependencies.
    trig = wf["all_triggers"]
    pos = layered(ex["steps"], 0.31, 0.82, 0.02, 0.8, 0.1, 0.17, ex["order"])
    kinds = {st["id"]: st for st in ex["steps"]}
    dag_nodes = []
    for sid, (x, yy) in pos.items():
        st = kinds[sid]
        style, shape = STEP_LOOK[st["kind"]]
        big = shape == "diamond"
        dag_nodes.append({"id": f"w_{sid}", "text": sid, "sub": st["kind"] + (f" · {st['join']}"
                          if st["join"] != wf["joins"][0] else ""),
                          "x": x - (0.01 if big else 0), "y": yy - (0.025 if big else 0), "w": 0.1 + (0.02 if big else 0),
                          "h": 0.17 + (0.05 if big else 0), "style": style, "shape": shape, "size": 12})
    dag_edges = []
    for st in ex["steps"]:
        deps = st["depends_on"] or []
        for d in deps:
            src = kinds[d]
            # A branch is drawn as the branch; a dependency another dependency already implies is not drawn.
            if src["kind"] == "condition" and sid_in(st["id"], src):
                continue
            if any(d in (kinds[o]["depends_on"] or []) for o in deps if o != d):
                continue
            dag_edges.append({"a": f"w_{d}", "b": f"w_{st['id']}", "mode": "c"})
        for branch in ("then", "else"):
            for t in st.get(branch) or []:
                dag_edges.append({"a": f"w_{st['id']}", "b": f"w_{t}", "mode": "c", "label": branch, "lsize": 11,
                                  "color": "CRIMSON", "lcolor": "CRIMSON_D", "lbold": True, "litalic": False,
                                  "loff": (-0.12, -0.04) if branch == "then" else (-0.3, 0.34)})
    last = ex["order"][-1]
    ty = row(len(trig), 0.02, 0.8, 0.1)
    workflow = {
        "kind": "canvas",
        "kicker": "Workflows",
        "title": "A workflow is a DAG of steps, started by a trigger and run as its owner",
        "nodes": [
            *[{"id": f"t_{t}", "text": TRIGGER_WORDS[t], "x": 0.0, "y": ty[i], "w": 0.13, "h": 0.1,
               "style": "white", "size": 11, "bold": False} for i, t in enumerate(trig)],
            {"id": "run", "text": "Run", "sub": "one per slot", "x": 0.16, "y": 0.31, "w": 0.115,
             "h": 0.2, "style": "dark", "shape": "hex", "size": 14},
            *dag_nodes,
            {"id": "pub", "text": "Published tool", "sub": f"{ex['publish'].get('tool_name', ex['name'])}: a call "
             "starts a run", "x": 0.865, "y": 0.3, "w": 0.135, "h": 0.22, "style": "accent", "shape": "pent",
             "size": 12},
        ],
        "edges": [
            *[{"a": f"t_{t}", "b": "run", "mode": "c", "width": 1.2} for t in trig],
            {"a": "run", "b": f"w_{ex['order'][0]}", "mode": "c", "color": "CRIMSON"},
            *dag_edges,
            {"a": f"w_{last}", "b": "pub", "mode": "c", "dash": True, "label": "output", "lsize": 10},
        ],
        "legend": {"x": 0.0, "y": 0.88, "w": 1.0, "cols": len(wf["steps"]), "size": 11,
                   "items": [(STEP_LOOK[k][0], k, STEP_LOOK[k][1]) for k in wf["steps"]]},
        "note": f"Joins: {listing(wf['joins'])}. The graph is the Workflows guide's own example ({ex['name']}), parsed "
        "and ordered by the engine when this deck was built.",
        "source": "sajha/workflows/model.py STEP_KINDS, TRIGGER_TYPES and JOINS, and the example definition in "
        "section 2 of docs/architecture/Workflows.md parsed by model.normalize and ordered by model.topo_order, all "
        "at build time; its tool names checked against the registry. docs/architecture/Workflows.md §4 (triggers), "
        "§5 (run as the owner), §6 (published as a tool).",
        "talk": f"The example on the slide is {ex['name']} from the Workflows guide: it reads the ten-year yield, "
        "checks whether it moved, asks Ask SAJHA to explain a move or waits quietly, and then finishes with any "
        "branch that succeeded. Step kinds: a tool, a composite, an Ask SAJHA question, a condition with branches, "
        "a loop over a list (foreach, whose body is a tool, composite or ask call), a wait, and a human approval. "
        "Triggers: a five-field cron in an IANA timezone, a webhook signed with HMAC-SHA256 and a timestamp, a "
        "file appearing on the storage backend, a change-bus event, or a person. A cron slot fires once across "
        "every worker, claimed in the state store. Every step runs as the workflow's owner, with the owner's "
        "current roles, so policy, usage and audit see the owner. Only an administrator may publish a workflow "
        "as a tool, because callers of the tool would run its steps with the owner's rights.",
    }

    run = {
        "kind": "canvas",
        "kicker": "A workflow run",
        "title": "A run is stored step by step, so it survives a worker that dies",
        "side": {"w": 0.34, "size": 15, "items": [
            ("Retries", "Backoff between attempts; a policy denial is never retried."),
            ("Timeouts", "Per step and per run; a late result is ignored."),
            ("Resume", "Finished steps are reused; an interrupted step runs again only if it is idempotent."),
            ("Re-run", "From the step that failed, with the same input."),
        ]},
        "nodes": [
            {"id": "queued", "text": "queued", "x": 0.0, "y": 0.4, "w": 0.17, "h": 0.18, "style": "white",
             "shape": "oval", "size": 14},
            {"id": "running", "text": "running", "x": 0.3, "y": 0.39, "w": 0.2, "h": 0.2, "style": "accent",
             "shape": "oval", "size": 15},
            {"id": "waiting", "text": "waiting", "sub": "worker freed", "x": 0.3, "y": 0.02, "w": 0.2, "h": 0.2,
             "style": "soft", "shape": "oval", "size": 14},
            {"id": "takeover", "text": "another worker", "sub": "claims a stale run", "x": 0.3, "y": 0.77,
             "w": 0.2, "h": 0.2, "style": "ghost", "shape": "oval", "size": 13},
            {"id": "succeeded", "text": "succeeded", "x": 0.75, "y": 0.06, "w": 0.25, "h": 0.17, "style": "ok",
             "size": 14},
            {"id": "failed", "text": "failed", "x": 0.75, "y": 0.405, "w": 0.25, "h": 0.17, "style": "bad",
             "size": 14},
            {"id": "cancelled", "text": "cancelled", "x": 0.75, "y": 0.75, "w": 0.25, "h": 0.17, "style": "box",
             "size": 14},
        ],
        "edges": [
            {"a": "queued", "b": "running", "label": "under the limit", "lsize": 10},
            {"a": "running", "b": "waiting", "ports": ("t", "b"), "at": (0.35, 0.35), "label": "wait, approval",
             "lsize": 10, "loff": (-1.45, 0)},
            {"a": "waiting", "b": "running", "ports": ("b", "t"), "at": (0.65, 0.65), "label": "woken", "lsize": 10},
            {"a": "running", "b": "takeover", "ports": ("b", "t"), "at": (0.35, 0.35), "dash": True,
             "label": "worker dies", "lsize": 10, "loff": (-1.3, 0)},
            {"a": "takeover", "b": "running", "ports": ("t", "b"), "at": (0.65, 0.65), "dash": True,
             "label": "resumes", "lsize": 10},
            {"a": "running", "b": "succeeded", "mode": "c", "color": "OK"},
            {"a": "running", "b": "failed", "color": "BAD"},
            {"a": "running", "b": "cancelled", "mode": "c"},
        ],
        "note": "Each step's status, attempts, input, output and timing are written as they change; the executing "
        "worker's heartbeat tells the others whether it is alive.",
        "source": "sajha/workflows/store.py RUN_ACTIVE and RUN_DONE (the run states, read at build time); "
        "sajha/workflows/engine.py (RunExecutor: retries, timeouts, parking, resume); docs/architecture/Workflows.md §3.",
        "talk": "A new run is queued and starts when the workflow has fewer active runs than its concurrency limit, "
        "counted across workers. A wait longer than the inline limit, an approval step, or a tool call a policy "
        "holds for approval parks the run as waiting and frees the worker; the scheduler wakes it. If a worker "
        "dies mid-run, its heartbeat stops; another worker claims the run with a conditional update, so exactly one "
        "wins, reuses every finished step and re-runs an interrupted step only if it is idempotent. Cancel sets a "
        "flag that any worker's executor sees within half a second. Re-run from a step starts a new run that copies "
        "the results before the chosen step.",
    }

    fit_x = row(4, 0.0, 1.0, 0.235)
    stages = [("Tool", "one entry in the registry", "accent"), ("Composite", "tools chained into one call", "dark"),
              ("Workflow", "a DAG of tools, composites, questions", "accent"),
              ("Published tool", "the workflow, called like any tool", "dark")]
    fit = {
        "kind": "canvas",
        "kicker": "How they fit",
        "title": "Four levels of building, and one governed path to every tool, local or remote",
        "nodes": [
            *[{"id": f"f{i}", "text": h, "sub": sub, "x": fit_x[i], "y": 0.12, "w": 0.235, "h": 0.2, "style": st,
               "shape": "pent", "size": 15} for i, (h, sub, st) in enumerate(stages)],
            {"id": "gov", "text": "Every call, at every level, goes through the same path",
             "sub": "access · schema · policy and approvals · cache · circuit breaker · audit", "x": 0.0, "y": 0.43,
             "w": 1.0, "h": 0.14, "style": "box", "size": 14},
            {"id": "loc", "text": "A local tool", "sub": "this server's registry", "x": 0.0, "y": 0.66, "w": 0.28,
             "h": 0.17, "style": "white", "size": 14},
            {"id": "fed", "text": "A proxied MCP server", "sub": f"vendor{sep}tool, through federation",
             "x": 0.36, "y": 0.66, "w": 0.28, "h": 0.17, "style": "white", "size": 14},
            {"id": "net", "text": "A SAJHA Net member", "sub": f"net{sep}instance{sep}tool, signed; the host decides "
             "again", "x": 0.72, "y": 0.66, "w": 0.28, "h": 0.17, "style": "white", "size": 14},
            {"id": "deep", "text": f"which may proxy others: outer{sep}inner{sep}tool", "x": 0.36, "y": 0.89, "w": 0.28,
             "h": 0.11, "style": "ghost", "size": 11, "bold": False},
        ],
        "edges": [
            {"a": "f3", "b": "f0", "ports": ("t", "t"), "via": [(0.8825, 0.04), (0.1175, 0.04)], "color": "CRIMSON",
             "label": "a published workflow is a tool again", "lsize": 10, "lseg": 1},
            *[{"a": f"f{i}", "b": "gov", "width": 1.2} for i in range(4)],
            {"a": "gov", "b": "loc"}, {"a": "gov", "b": "fed"}, {"a": "gov", "b": "net"},
            {"a": "fed", "b": "deep", "dash": True},
        ],
        "source": "docs/architecture/Workflows.md §1 and §6 (step kinds tool, composite, ask; published as a tool, usable "
        "from Ask SAJHA and composites); docs/architecture/Composition Framework.md; docs/architecture/SAJHA Net.md "
        "§2 (a remote tool is called like a local one by composites and workflows) and §5.6; docs/architecture/"
        "Federation.md §4 (names, proxies all the way down). The separator is sajha/tools/naming.py SEPARATOR, read "
        "at build time.",
        "talk": "The four levels nest. A tool is one registry entry. A composite chains tools into one call. A "
        "workflow is a graph whose steps are tools, composites and Ask SAJHA questions, with conditions, loops, "
        "waits and approvals. An administrator can publish a workflow as a tool, and then it is a tool again: a "
        "composite or another workflow or Ask SAJHA can call it. At every level each call takes the same governed "
        "path, so it makes no difference whether the tool is local, belongs to a proxied MCP server (published "
        "with its vendor prefix), or lives on another SAJHA Net member (reached by its qualified name, where the "
        "host checks the call again). A proxied server may proxy others; the names compose and one call-chain "
        "budget bounds the nesting, so cycles are refused rather than followed.",
    }
    return [composite, framework, workflow, run, fit]


def sid_in(target: str, cond: dict[str, Any]) -> bool:
    """Whether a step is named in a condition's branches (its edge is drawn as the branch)."""
    return target in (cond.get("then") or []) + (cond.get("else") or [])


def _section4(F: dict[str, Any]) -> list[dict[str, Any]]:
    wf = F["workflows"]
    risk = require_tools(["fred_fed_funds_rate", "fred_2yr_treasury", "fred_10yr_treasury", "duckdb_sql",
                          "olap_pivot_table", "tavily_news_search", "calc_bond_price"])
    return [
        {
            "kind": "divider",
            "title": "Agents, composition and workflows",
            "sub": "How agents use SAJHA, alone and together; how tools compose into one governed call; how a schedule "
            "or an event runs a governed graph of steps; and how the server is extended while it runs.",
            "points": ["Agent architecture", "A worked analysis", "Several agents", "Composite tools",
                       "The Composition Framework", "Workflows", "A run", "How they fit", "Extending", "Hot reload",
                       "Making a tool, step by step"],
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
            "Section 7 shows a real run, captured when this deck was built.",
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
        *_composition(F),
        {
            "kind": "canvas",
            "kicker": "Extending the server",
            "title": "Two ways to add a tool, and agents cannot tell them apart",
            "nodes": [
                {"id": "s1", "text": "No code: MCP Studio", "sub": "a creator form, or describe the tool in a sentence",
                 "x": 0.0, "y": 0.04, "w": 0.27, "h": 0.22, "style": "accent", "size": 15},
                {"id": "s2", "text": "Import an API; connect a database", "x": 0.0, "y": 0.32, "w": 0.27, "h": 0.15,
                 "style": "soft", "size": 13},
                {"id": "p1", "text": "Full code: a Python tool", "sub": "subclass BaseMCPTool, implement execute()",
                 "x": 0.0, "y": 0.58, "w": 0.27, "h": 0.22, "style": "dark", "size": 15},
                {"id": "p2", "text": "or a plugin: plugin.json and tools/", "x": 0.0, "y": 0.86, "w": 0.27, "h": 0.13,
                 "style": "box", "size": 13},
                {"id": "dep", "text": "Deploy", "sub": "a JSON config in config/tools; no restart", "x": 0.38,
                 "y": 0.36, "w": 0.2, "h": 0.26, "style": "white", "shape": "hex", "size": 15},
                {"id": "tool", "text": "An ordinary MCP tool", "sub": "with schemas, governed and audited the same way",
                 "x": 0.68, "y": 0.34, "w": 0.32, "h": 0.3, "style": "accent", "size": 16},
            ],
            "edges": [
                {"a": "s1", "b": "dep", "mode": "c"}, {"a": "s2", "b": "dep", "mode": "c"},
                {"a": "p1", "b": "dep", "mode": "c"}, {"a": "p2", "b": "dep", "mode": "c"},
                {"a": "dep", "b": "tool", "color": "CRIMSON", "width": 2.2},
            ],
            "source": "sajha/tools/base_mcp_tool.py (BaseMCPTool); sajha/core/plugins.py (plugin.json manifest, "
            "discover, load_plugin; /api/plugins in sajha/routes/ops_routes.py); Studio pages in "
            "sajha/routes/studio_routes.py.",
            "talk": "No code: the REST, database query, script, Power BI, SharePoint, LiveLink and OLAP creators, or "
            "describe the tool in a sentence; import an OpenAPI or GraphQL description; connect a database; deploy "
            "with one click and the tool is live without a restart. Full code: subclass BaseMCPTool, implement "
            "execute and declare the input schema, with the whole Python ecosystem available; a JSON config in "
            "config/tools loads it, and a plugin packages several. Both produce ordinary MCP tools.",
        },
        {
            "kind": "canvas",
            "kicker": "Hot reload",
            "title": "Tools, rules and permissions change without a restart",
            "nodes": [
                {"id": "f", "text": "Tool configs", "sub": "config/tools, or an object store", "x": 0.0, "y": 0.0,
                 "w": 0.22, "h": 0.16, "style": "white", "size": 13},
                {"id": "st", "text": "Studio, imports, connectors", "sub": "deploy registers at once", "x": 0.0,
                 "y": 0.24, "w": 0.22, "h": 0.16, "style": "white", "size": 13},
                {"id": "po", "text": "Policy files", "sub": "reload when they change", "x": 0.0, "y": 0.48, "w": 0.22,
                 "h": 0.16, "style": "white", "size": 13},
                {"id": "us", "text": "Users, roles and keys", "sub": "changed in the console", "x": 0.0, "y": 0.72,
                 "w": 0.22, "h": 0.16, "style": "white", "size": 13},
                {"id": "reg", "text": "Tools registry", "sub": "file monitor; object-store poller", "x": 0.36,
                 "y": 0.06, "w": 0.24, "h": 0.26, "style": "accent", "size": 15},
                {"id": "pe", "text": "Policy engine", "x": 0.36, "y": 0.47, "w": 0.24, "h": 0.18, "style": "dark",
                 "size": 14},
                {"id": "rq", "text": "The next request", "sub": "the user is reloaded on every request", "x": 0.36,
                 "y": 0.71, "w": 0.24, "h": 0.18, "style": "dark", "size": 14},
                {"id": "cl", "text": "Clients told", "sub": "list-changed on SSE, WebSocket and subscriptions/listen",
                 "x": 0.74, "y": 0.0, "w": 0.26, "h": 0.2, "style": "soft", "size": 13},
                {"id": "ask", "text": "Ask SAJHA's shortlist", "sub": "sees a new tool without a reload", "x": 0.74,
                 "y": 0.28, "w": 0.26, "h": 0.2, "style": "soft", "size": 13},
            ],
            "edges": [
                {"a": "f", "b": "reg", "mode": "c"}, {"a": "st", "b": "reg", "mode": "c"}, {"a": "po", "b": "pe"},
                {"a": "us", "b": "rq"}, {"a": "reg", "b": "cl", "mode": "c", "color": "CRIMSON"},
                {"a": "reg", "b": "ask", "mode": "c", "color": "CRIMSON"},
            ],
            "source": "sajha/tools/tools_registry.py (start_monitoring, _monitor_files); sajha/core/reload_manager.py "
            "(object-store polling); sajha/policy/loader.py (policy.reload_seconds); sajha/core/mcp_handler.py "
            "(listChanged on push channels; subscriptions/listen in mcp_modern); docs/security/Security Model.md §1 "
            "(user reloaded per request); docs/architecture/Intelligence Layer.md (tool index sync).",
            "talk": "A JSON config added or changed in config/tools is picked up by the registry's file monitor; with an "
            "object store, its poller does the same. Deploying from Studio, an import or a connector registers the "
            "tool in the running server at once. Policy files reload when they change. Users, roles and keys changed "
            "in the console apply to the next request, because the user is reloaded on every request. Clients on SSE "
            "or WebSocket, and 2026-07-28 clients through subscriptions/listen, receive list-changed notifications.",
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


def agents(F: dict[str, Any]) -> list[dict[str, Any]]:
    """Section 4: agents, composition and workflows."""
    return _section4(F)


def data(F: dict[str, Any]) -> list[dict[str, Any]]:
    """Section 6: data and analytics."""
    return _section5(F)
