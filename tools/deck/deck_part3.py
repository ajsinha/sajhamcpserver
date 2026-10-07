"""
The deck, as data. Parts 5 and 6: governance an enterprise can sign off (with a policy
evaluated and an audit chain tampered with while the deck is built), and every tool you
have.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from evidence import ROOT
from prose import js, listing, plain, wrap


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


def _part5(F: dict[str, Any]) -> list[dict[str, Any]]:
    pol, aud, siem, fixes = F["policy"], F["audit"], F["siem"], F["fixes"]
    shortest = sorted((plain(f) for f in fixes), key=len)[:9]
    cf = {r["suite"].split(" ")[0]: r for r in F["conformance"]["rows"]}
    auth = cf.get("authorization")
    policy_src = (
        "Evaluated while the deck was built (tools/deck/evidence.py, policy_example): "
        "sajha.policy.engine.PolicyEngine.evaluate over the shipped files in config/policies, disabled "
        "examples included (include_disabled=True, as the Policies page's test bench offers); nothing was "
        "run."
    )
    return [
        {
            "kind": "divider",
            "num": "5",
            "title": "Governance an enterprise can sign off",
            "sub": "A security review asks five things: who is calling, what may they do, what stops a bad "
            "call, what record is left, and what happens to code and credentials SAJHA did not write. Each "
            "answer here is code, and two of them were exercised while this deck was built.",
            "points": [
                "Identities and one access policy",
                "OAuth 2.1 on the MCP endpoint",
                "Rules before every call, evaluated",
                "A tamper-evident audit, tampered with",
                "Sandbox and connected accounts",
                "Fixes, listed as evidence",
            ],
        },
        {
            "kind": "table",
            "kicker": "Who is calling",
            "title": "Four kinds of caller, one access policy on every path",
            "col_w": [1.5, 3.2, 2.6],
            "rows": [
                ["Caller", "How it proves who it is", "What it may see and run"],
                ["A user", "Web sign-in (lockout, throttling, password policy), then a session or a SAJHA JWT",
                 "Its roles' tool permissions: read to see a tool, execute to run it"],
                ["An API key", "A key issued by an administrator, optionally with an expiry",
                 "Its tool access mode: all, allowlist, denylist or regex"],
                ["An OAuth client", "An access token for /mcp from SAJHA's authorization server or yours",
                 "Its scopes for methods, then the user's tool access on top"],
                ["Anonymous", "Nothing", "No tools, prompts or data files by default (mcp.anonymous.*)"],
            ],
            "note": "One policy (sajha/auth/access.py) applies to REST, MCP in both eras, SSE, WebSocket, "
            "stdio, A2A and asynchronous calls; tools/list shows a caller only what it may run.",
            "source": "docs/security/Security Model.md §1 (Identities and credentials, Tool access); "
            "GLOSSARY.md 'Tool access', 'Tool access mode', 'mcp.auth.mode'; sajha/auth/access.py.",
        },
        {
            "kind": "bullets",
            "kicker": "The MCP endpoint",
            "title": "OAuth 2.1 on /mcp: SAJHA's own authorization server, or yours",
            "intro": "An authorization server issues the tokens; a resource server accepts them. SAJHA can be "
            "both, or only the second behind your identity provider. It is off by default (mcp.auth.mode: "
            "off, optional or required); API keys and SAJHA's own tokens work in every mode.",
            "items": [
                ("Resource server", "Protected-resource metadata (RFC 9728), audience-bound tokens: a token "
                 "issued for another API is refused."),
                ("Built-in authorization server", "Authorization code with PKCE S256, client ID metadata "
                 "documents, optional dynamic registration, rotating refresh tokens with reuse detection."),
                ("Tested by the suite", (f"The official authorization scenarios: {auth['scenarios']} scenarios, "
                 f"{auth['passed']} checks passed, {auth['failed']} failed (Part 4)." if auth else
                 "The official authorization scenarios are recorded in the compliance report.")),
            ],
            "source": "docs/protocol/OAuth Guide.md; sajha/auth/oauth/resource_server.py and "
            "authorization_server.py; the authorization row of the conformance table in "
            "docs/protocol/MCP 2026-07-28 Compliance.md §5, parsed at build time.",
        },
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
                    ("Match", "Tool names and groups, annotations such as destructiveHint, the caller "
                     "(anonymous, user, role, API key), the path, a time window, argument values."),
                    ("Decide", "allow, deny with a reason, or require_approval by the caller or an "
                     "administrator; deny overrides; default_effect: deny turns it into an allowlist."),
                    ("Oblige", "Argument constraints, rate limits and quotas shared by every worker, "
                     "redaction of personal data, screening of results for injected instructions."),
                    ("Operate", "Files reload on change; every decision that is not allow is audited; the "
                     "Policies page has a test bench."),
                ],
                "size": 16,
            },
            "source": "The rules shown are read verbatim from config/policies/example-guardrails.yaml at build "
            "time (disabled in the shipped configuration). Rule language: docs/architecture/Policy and "
            "Audit.md §3; sajha/policy/model.py and engine.py.",
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
            "note": "The same engine sits in BaseMCPTool.execute_with_tracking, so these decisions would be the "
            "same over MCP, REST, the command line or Ask SAJHA.",
            "source": policy_src,
        },
        {
            "kind": "split",
            "kicker": "Audit, tampered with",
            "title": "Change one stored field and the audit says which record and which field",
            "left_w": 0.5,
            "left": {
                "head": "Captured while building this deck",
                "lines": [
                    "# write a short chain, signed every 5 records",
                    f"✓ verify: {aud['records']} records, {aud['anchors']} signed anchors, ok={aud['ok_before']}",
                    "",
                    "# change one stored outcome, deny -> ok",
                    f"UPDATE audit_chain SET outcome='ok' WHERE seq={aud['seq']}",
                    "",
                    f"✗ verify: ok={aud['ok_after']}",
                    *[ln for p in aud["problems"] for ln in wrap(p, 48)],
                ],
            },
            "right": {
                "head": "How",
                "items": [
                    ("Chained", "Each record's SHA-256 covers the previous record's hash, so an edit, "
                     "deletion, insertion or reordering breaks the chain."),
                    ("Signed", "The head is signed (RS256) every N records, every few minutes and at "
                     "shutdown, with the key published at /oauth/jwks."),
                    ("Checked", "python -m sajha.audit verify, or the Audit page."),
                    ("Exported", f"To {listing(siem['types'])} sinks ({listing(siem['flavors'])}) as "
                     f"{listing(f.upper() if f != 'ocsf' else 'OCSF' for f in siem['formats'])}."),
                ],
                "size": 16,
            },
            "source": "Run while the deck was built (tools/deck/evidence.py, audit_example): "
            "sajha.audit.chain.ChainWriter on a temporary SQLite file with a throwaway RSA key, then "
            "sajha.audit.verify.verify before and after one UPDATE. SIEM sinks and formats: sajha/audit/sinks.py "
            "TYPES and FLAVORS, sajha/audit/formats.py FORMATS.",
        },
        {
            "kind": "cards",
            "kicker": "Code and credentials SAJHA did not write",
            "title": "User code runs in a sandbox; a user's tokens stay in a vault",
            "cols": 2,
            "cards": [
                ("SANDBOX", "Every call of user code in its own process",
                 "Python and script tools made in Studio, and the admin shell, run per call with no server "
                 "environment, no view of its files and no network unless allowed. Backends: "
                 f"{listing(F['sandbox'], 'or')}; on Linux the default adds Landlock, seccomp and "
                 "namespaces."),
                ("WHAT IT DOES NOT COVER", "Built-in tools are not sandboxed",
                 "Shipped tools and tools of other servers run in-process or remotely. On macOS and Windows "
                 "the default sandbox gives only a clean environment and limits; where kernel exploits "
                 "matter, use docker with gVisor."),
                ("CONNECTED ACCOUNTS", "A tool acts as the user, not as a shared key",
                 f"A user links an account once ({listing(F['accounts'])}, or any OAuth 2.0 service); "
                 "tools that declare it call the service with that user's token."),
                ("THE VAULT", "Tokens encrypted, bound and fenced",
                 "AES-256-GCM, bound to user and provider, refreshed by one worker at a time, sent only to "
                 "the provider's listed hosts; per-user results are never cached."),
            ],
            "source": "Sandbox backends: sajha/sandbox/backends.py BACKENDS; limits: docs/architecture/Sandbox.md "
            "and Security Model §8 'Sandboxing'. Account templates: sajha/accounts/providers.py TEMPLATES; "
            "vault: docs/architecture/Connected Accounts.md, sajha/accounts/vault.py.",
        },
        {
            "kind": "stats",
            "kicker": "Evidence",
            "title": "Security fixes are listed, with where each one lives in the code",
            "intro": "The Security Model keeps a table of issues found and fixed since the last major release, "
            "each with the file that fixes it. A list kept in the open is worth more than a claim of none.",
            "stats": [
                (str(len(fixes)), "issues found and fixed, each named with its fix and its file"),
                (str(len(F["limitations"])), "known limitations, listed so a deployment can compensate"),
            ],
            "rows": [["The shortest entries in the fixes table"]] + [[f] for f in shortest],
            "size": 12,
            "bold_col0": False,
            "source": "docs/security/Security Model.md, the 'Fixes since …' table and the 'Known limitations' "
            "section, both parsed at build time (tools/deck/evidence.py security_fixes, limitations). The rows "
            "shown are the nine shortest, chosen mechanically.",
        },
    ]


def _part6(F: dict[str, Any]) -> list[dict[str, Any]]:
    cat, conn, wf, comp = F["catalog"], F["connectors"], F["workflows"], F["composition"]
    rows = [["Group", "Tools", "For example"]] + [[g, str(n), ex] for g, n, ex in cat["top"][:10]]
    rest = sum(n for _g, n, _e in cat["top"][10:])
    rows.append([f"{cat['groups'] - 10} more groups", str(rest), "search, central banks, documents, …"])
    creators = [c.replace("powerbidax", "Power BI DAX").replace("powerbi", "Power BI")
                .replace("dbquery", "SQL query").replace("rest", "REST").replace("livelink", "LiveLink")
                .replace("sharepoint", "SharePoint") for c in F["studio"]]
    ways = [
        ["Way", "You give", "You get"],
        ["MCP Studio creators", listing(creators),
         "A generated tool, deployed into the running server; code tools run sandboxed"],
        ["Describe a tool", "A sentence", "A proposed, tested tool an administrator reviews and approves"],
        ["Import an API", "An OpenAPI 3, Swagger 2 or GraphQL description",
         "Reviewed tools on one generic executor; no code generated"],
        ["Data connectors", "A database, warehouse or vector store connection",
         "Read-only list, describe, query and search tools, and curated views"],
        ["Federation", "Another MCP server's address", "Its tools in the catalog, under SAJHA's rules"],
        ["Composite tool", "Steps that chain existing tools", "One tool, with confidence tracking"],
        ["Workflow", "A graph of steps and a trigger", "A scheduled or triggered run, optionally a tool"],
    ]
    n_ways = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight",
              9: "Nine"}.get(len(ways) - 1, str(len(ways) - 1))
    comp_lines = ["# confidence through a three-step composite", "# step                      conf  chain  bits"]
    for s, c, cum, bits in comp["rows"]:
        comp_lines.append(f"{s[:25]:<25} {c:.2f}  {cum:.3f}  {bits:.2f}")
    comp_lines += ["", f"# refused above {comp['max_bits']:.1f} bits (max_entropy_bits)"]
    return [
        {
            "kind": "divider",
            "num": "6",
            "title": "Every tool you have",
            "sub": "A catalog is shared only if it holds the tools people need. SAJHA ships a large one, and "
            f"gives {n_ways.lower()} ways to add more without writing a server: browser creators, a sentence, an API "
            "description, a database connection, another MCP server, a composite and a workflow.",
            "points": [
                "The catalog in the box",
                "Studio, and describing a tool in a sentence",
                "API import and data connectors",
                "Federation",
                "Composition and confidence",
                "Workflows",
            ],
        },
        {
            "kind": "table",
            "kicker": "In the box",
            "title": f"{cat['tools']} tools in {cat['groups']} groups ship with the server",
            "col_w": [1.6, 0.8, 3.0],
            "rows": rows,
            "size": 12,
            "note": "Market data, central banks, filings, public statistics, search and calculators. The live "
            "list is tools/list or the Tools page; a caller sees only what it may run.",
            "source": "The tools registry loaded from config/tools at build time, grouped by "
            "live_tool_groups (sajha/web/help_catalog.py); 'for example' is each group's first tool by name.",
        },
        {
            "kind": "table",
            "kicker": "Adding tools",
            "title": f"{n_ways} ways to make a tool without writing an MCP server",
            "col_w": [1.7, 2.6, 3.0],
            "rows": ways,
            "source": "Studio creators: sajha/studio/*_tool_generator.py, listed at build time; "
            "docs/studio/MCP Studio User Guide.md; docs/architecture/Tool Generation.md, API Import.md, "
            "Data Connectors.md, Federation.md, Composition Framework.md, Workflows.md.",
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
                "Out of the box the toolsmith alias points at an offline mock that knows a few shapes; real "
                "designs need a real model. Generated Python tools always run sandboxed.",
            ],
            "source": "docs/architecture/Tool Generation.md; sajha/studio/describe.py; "
            "sajha/ai/llm/mock_toolsmith.py; CHANGELOG 'Describe a tool'. The example sentence is illustrative.",
        },
        {
            "kind": "split",
            "kicker": "APIs and databases",
            "title": "An API description or a database becomes governed, read-only tools",
            "left": {
                "head": "Import an API",
                "items": [
                    "OpenAPI 3.x, Swagger 2.0 or a GraphQL endpoint becomes a preview of every operation: "
                    "name, JSON Schema in and out, read-only and destructive hints.",
                    "Choose, test one call, deploy; credentials only as secret references.",
                    "Every call passes an SSRF guard; re-import shows a diff. Multipart bodies are not "
                    "supported.",
                ],
                "size": 16,
            },
            "right": {
                "head": "Data connectors",
                "items": [
                    f"SQL: {listing(conn['sql'])}. Search: {listing(conn['search'])}.",
                    "Read-only three times over: a statement guard, a read-only session, and the login's own "
                    "grants. Row, byte and time limits; masking per column.",
                    f"Curated views become typed tools; {listing(conn['per_user'])} can sign in as each user.",
                ],
                "size": 16,
            },
            "source": "Connector kinds: sajha/connectors/model.py KINDS, read at build time. "
            "docs/architecture/API Import.md and Data Connectors.md; CHANGELOG 'Data connectors' and "
            "'API Import'.",
        },
        {
            "kind": "bullets",
            "kicker": "Federation",
            "title": "Other MCP servers' tools join the catalog under SAJHA's rules",
            "intro": "Federation means SAJHA fronting another MCP server: its tools appear in the catalog as "
            "<prefix>__<tool> and every call to them passes SAJHA's access policy, rules, cache, circuit "
            "breakers and audit. It is off by default.",
            "items": [
                ("Approval before exposure", "An upstream's tools wait for an administrator; a changed "
                 "definition waits again."),
                ("Screened text", "Descriptions and results are screened for injected instructions; flagged "
                 "items always wait for a person."),
                ("Fenced network", "Upstream and token addresses pass an SSRF guard; each user's own token "
                 "can be passed through instead of a shared one."),
                ("Not isolated", "An upstream server runs where it runs; SAJHA governs the calls, not the "
                 "server's process."),
            ],
            "source": "docs/architecture/Federation.md; sajha/federation/; GLOSSARY.md 'Federation', "
            "'Tool poisoning'; the federation and isolation cells of sajha/web/competitive.py.",
        },
        {
            "kind": "split",
            "kicker": "Composition",
            "title": "Confidence falls as uncertain steps chain, and SAJHA computes by how much",
            "left_w": 0.52,
            "left": {"head": "Computed while building this deck", "lines": comp_lines},
            "right": {
                "head": "Why it matters",
                "items": [
                    "Sequential steps multiply confidence; parallel steps take the lowest.",
                    "Entropy in bits measures the doubt that has built up; a composite whose predicted "
                    "entropy passes the limit is refused before it runs.",
                    "A deterministic step (a calculator) adds no doubt, so it does not lower the chain.",
                    "Composite tools are ordinary catalog tools, so every rule of Part 5 applies to them.",
                ],
                "size": 16,
            },
            "source": "sajha.core.composition.EntropyGuard and get_tool_confidence, run at build time on "
            "three tool names (tools/deck/evidence.py, composition_example). GLOSSARY.md 'EntropyGuard'.",
        },
        {
            "kind": "cards",
            "kicker": "Workflows",
            "title": "A schedule or an event runs a governed graph of steps",
            "cols": 3,
            "cards": [
                ("STEPS", "Tools, composites, questions, decisions", f"Step kinds: {listing(wf['steps'])}."),
                ("TRIGGERS", "Started by time or by events",
                 f"{listing(t if t != 'cron' else 'cron schedules' for t in wf['triggers'])}, or by hand; "
                 "one fire per slot across workers."),
                ("DURABLE", "A run survives a crash",
                 "Every step is stored; another worker takes over a dead worker's run and re-runs only "
                 "idempotent steps."),
                ("AS THE OWNER", "Runs with the owner's rights",
                 "Steps run with the owner's current roles, seen by policy, usage and audit as that caller."),
                ("RE-RUN", "From the step that failed", "Finished steps are reused; a run can be cancelled."),
                ("PUBLISHED", "A workflow can be a tool",
                 "An administrator can publish it to the catalog, callable from both eras."),
            ],
            "source": "sajha/workflows/model.py STEP_KINDS and TRIGGER_TYPES, read at build time; "
            "docs/architecture/Workflows.md; CHANGELOG 'Workflows'.",
        },
    ]


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return _part5(F) + _part6(F)
