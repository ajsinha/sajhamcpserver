"""
The deck, as data. Section 5: SAJHA Net and proxied MCP servers -- many SAJHA servers, and
other MCP servers, joined into a net in which each server's tools can be called from every
other while each keeps its own data, credentials, policy, AI layer and memory.

Every slide here is a diagram of native shapes (the ``canvas`` layout); the detail is in the
speaker notes. Plug-in names, admission modes, shipped settings and the name separator are read
from the code and the shipped configuration while the deck is built (``evidence.net``); instance
and vendor names (risk-eu, cust-na, acme, ...) are the illustrative ones of the SAJHA Net guide.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from diagrams import ring
from evidence import SourceChanged
from prose import listing

GUIDE = "docs/architecture/SAJHA Net.md"


def _why(F: dict[str, Any]) -> dict[str, Any]:
    nt = F["net"]
    doms = [("risk-eu", "EU risk"), ("treasury-na", "US treasury"), ("cust-na", "NA customers")]
    nodes, groups, edges = [], [], []
    for i, (inst, label) in enumerate(doms):
        x = 0.0 + i * 0.36
        groups.append({"id": f"d{i}", "label": f"{label.upper()} BOUNDARY", "x": x, "y": 0.16, "w": 0.28, "h": 0.84,
                       "fill": "PARCH", "line": "RULE"})
        nodes.append({"id": f"s{i}", "text": f"SAJHA {inst}", "x": x + 0.025, "y": 0.27, "w": 0.23, "h": 0.15,
                      "style": "accent", "size": 14})
        for k, (t, st) in enumerate([("its data", "white"), ("its credentials", "white"),
                                     ("its policy and audit", "white"), ("its models and memory", "white")]):
            r, c = divmod(k, 2)
            nodes.append({"id": f"o{i}{k}", "text": t, "x": x + 0.015 + c * 0.13, "y": 0.52 + r * 0.22, "w": 0.12,
                          "h": 0.17, "style": st, "size": 12, "bold": False})
    edges += [{"a": "s0", "b": "s1", "both": True, "color": "CRIMSON", "label": "call, result", "lsize": 10.5},
              {"a": "s1", "b": "s2", "both": True, "color": "CRIMSON", "label": "call, result", "lsize": 10.5}]
    nodes.append({"id": "q", "text": "“How exposed is the EU book to the rate move the US desk is forecasting?”",
                  "x": 0.0, "y": 0.0, "w": 0.64, "h": 0.1, "style": "ghost", "size": 13, "bold": False})
    edges.append({"a": "q", "b": "s0", "ports": ("b", "t"), "at": (0.18, 0.5), "dash": True})
    return {
        "kind": "canvas",
        "kicker": "Why a net",
        "title": "Each boundary keeps its data; only a governed call crosses it",
        "groups": groups,
        "nodes": nodes,
        "edges": edges,
        "note": f"Off by default (sajhanet.enabled: {str(nt['enabled_shipped']).lower()}); turned off, every /sajhanet/ "
        "path answers 404 and a server behaves exactly as without it.",
        "source": f"{GUIDE} §1 (why), §2 (what it guarantees and what it does not do); sajhanet.enabled read from the "
        "shipped config/application.yml at build time. Instance names are the guide's illustrative ones.",
        "talk": "Large organisations rarely have one place where all data may live: business lines, legal entities "
        "and regions own their data and the rules for it. A net puts a SAJHA server inside each boundary. Each one "
        "holds the tools that touch its data and the credentials those tools use, applies its own access rules, "
        "policy, approvals and audit, runs its own models, budgets and planners, and keeps its own users' memory. "
        "What crosses is a tool call and its result, and only when both sides' rules allow it. A question that "
        "spans domains is answered by a planner on one server using tools on several, without copying either "
        "domain's data. SAJHA Net does not share state between servers, elect a leader, move data in bulk, or join "
        "nets together except through a bridge an administrator turns on.",
    }


def _ring(F: dict[str, Any]) -> dict[str, Any]:
    nt = F["net"]
    members = [("risk-eu", "accent", "SAJHA"), ("treasury-na", "accent", "SAJHA"), ("vendor-search", "navy", "agent"),
               ("cust-na", "accent", "SAJHA"), ("saas-crm", "ghost", "sponsored by cust-na"),
               ("risk-apac", "accent", "SAJHA")]
    pts = ring(len(members), 0.42, 0.43, 0.3, 0.33)
    w, h = 0.2, 0.15
    nodes = [{"id": f"m{i}", "text": n, "sub": kind, "x": cx - w / 2, "y": cy - h / 2, "w": w, "h": h, "style": st,
              "shape": "oval", "size": 13} for i, ((n, st, kind), (cx, cy)) in enumerate(zip(members, pts))]
    edges = [{"a": f"m{i}", "b": f"m{(i + 1) % len(members)}", "mode": "c", "dash": True, "arrow": False,
              "width": 1.3} for i in range(len(members))]
    edges += [{"a": "m0", "b": "m3", "mode": "c", "color": "CRIMSON", "width": 2.0, "label": "catalog pull, then calls",
               "lsize": 10.5}]
    return {
        "kind": "canvas",
        "kicker": "Membership",
        "title": "Members find each other by gossip, then pull each other's catalogs",
        "nodes": nodes,
        "edges": edges,
        "legend": {"x": 0.0, "y": 0.9, "w": 1.0, "cols": 4, "size": 10.5,
                   "items": [("accent", "SAJHA instance", "oval"), ("navy", "agent-fronted", "oval"),
                             ("ghost", "sponsored", "oval"), ("edge:dash", "gossip")]},
        "side": {"w": 0.36, "size": 15, "items": [
            ("Gossip", "SWIM from one or two seeds: pings, indirect probes, suspect, dead; only digests travel."),
            ("Catalogs", "A changed digest makes a peer pull that catalog; every allowed tool becomes a proxy tool."),
            ("Leaving", "A member that leaves or dies takes its tools off every peer at once."),
            ("Workers", "One gossip agent per net holds a lease; the list lives in the state store."),
        ]},
        "source": f"{GUIDE} §5.1 (three kinds of participant), §6.2–6.3 (coming and going, gossip), §7 (catalogs), "
        f"§8.1 (proxies). Membership plug-ins registered at build time: {listing(nt['plugins']['membership'])} "
        "(sajha/net/plugins.py).",
        "talk": "Every member pings one other at random every second; if there is no answer it asks three others to "
        "try, so one broken link does not condemn a healthy member. A member that does not answer becomes suspect "
        "and, after a timeout without refuting, dead, and its tools are removed everywhere. Gossip carries only "
        "digests of catalogs, key directories, blocks, conflicts and revocations; a changed digest makes peers pull "
        "that part point to point. Gossip never carries tools, schemas or keys. All of it is small signed HTTP on "
        "SAJHA's normal port, no UDP and no second port. A member may be a SAJHA instance, any MCP server with the "
        "SAJHA Net agent beside it, or an MCP server a SAJHA server sponsors; callers cannot tell them apart.",
    }


def _admission(F: dict[str, Any]) -> dict[str, Any]:
    nt = F["net"]
    modes = nt["plugins"]["admission"]
    if set(modes) != {"open", "builtin_ca", "manual"}:
        raise SourceChanged(f"SAJHA Net admission modes changed: {modes}")
    lanes = [
        ("open", "Any server that can reach a member and knows the net's name",
         "The first key seen for a name is remembered", "No revocation: an administrator forgets a key"),
        ("builtin_ca", "A server an administrator enrolled",
         "A single-use enrollment token; the net's own CA issues a certificate", "Signed revocation list, by gossip"),
        ("manual", "A peer whose thumbprint each side pinned", "Self-signed certificates, pinned thumbprints",
         "Remove the pin"),
    ]
    nodes, edges = [], []
    for i, (mode, who, gate, revoke) in enumerate(lanes):
        y = 0.04 + i * 0.33
        tag = " (shipped)" if mode == nt["admission_shipped"] else (" (code default)" if mode == nt["admission_code"]
                                                                      else "")
        nodes += [
            {"id": f"l{i}", "text": mode, "sub": tag.strip(" ()"), "x": 0.0, "y": y, "w": 0.13, "h": 0.24,
             "style": "accent" if mode == nt["admission_shipped"] else "dark", "size": 15},
            {"id": f"w{i}", "text": who, "x": 0.17, "y": y + 0.02, "w": 0.2, "h": 0.2, "style": "white", "size": 12,
             "bold": False},
            {"id": f"g{i}", "text": gate, "x": 0.41, "y": y + 0.01, "w": 0.27, "h": 0.22, "style": "soft",
             "shape": "hex", "size": 12},
            {"id": f"n{i}", "text": "member", "x": 0.72, "y": y + 0.04, "w": 0.1, "h": 0.16, "style": "white",
             "shape": "oval", "size": 12},
            {"id": f"r{i}", "text": revoke, "x": 0.85, "y": y + 0.02, "w": 0.15, "h": 0.2, "style": "box", "size": 11,
             "bold": False},
        ]
        edges += [{"a": f"w{i}", "b": f"g{i}"}, {"a": f"g{i}", "b": f"n{i}"},
                  {"a": f"n{i}", "b": f"r{i}", "dash": True, "arrow": False}]
    return {
        "kind": "canvas",
        "kicker": "Admission",
        "title": f"Who may join: open is shipped, {nt['admission_code']} is the code's default",
        "nodes": nodes,
        "edges": edges,
        "note": "Open mode trusts whoever first claims a name: use it only where every machine that can reach a member "
        f"is yours. Switch to {nt['admission_code']} before a net spans machines you do not control.",
        "source": f"{GUIDE} §6.4 (admission modes), §6.5 (the built-in CA, manual mode), §21.3. Modes: the admission "
        "plug-ins registered in sajha/net/plugins.py and sajha/net/trust.py; the code default from "
        "sajha/net/integration/config.py Shared.admission; the shipped mode from config/application.yml "
        "sajhanet.plugins.admission; all read at build time.",
        "talk": "Whatever the mode, every request between participants is signed (RFC 9421 HTTP message signatures "
        "with a body digest, a creation time and a nonce), names are held to a key, and the host still authorizes "
        "every user it is sent. Open mode: each server makes a self-signed certificate per net at first start; "
        "the first key seen for an instance name is remembered and later held to it, so another key claiming the "
        "name is refused as a name conflict; there is no revocation, an administrator forgets a remembered key. "
        "Built-in CA: SAJHA runs the CA for the net; a single-use, short-lived token enrolls a named server, "
        "certificates are short-lived and renew themselves, and revocation spreads by gossip. The CA is not on "
        "the call path. Manual: self-signed certificates whose thumbprints each administrator pins.",
    }


def _contract(F: dict[str, Any]) -> dict[str, Any]:
    sep = F["net"]["sep"]
    hosts = [("risk-eu", "A", "ok"), ("treasury-na", "A", "ok"), ("risk-apac", "A", "ok"), ("cust-na", "B", "bad")]
    nodes = [{"id": f"h{i}", "text": f"{n} offers var_calc", "sub": f"contract hash {hsh}", "x": 0.02,
              "y": 0.12 + i * 0.215, "w": 0.19, "h": 0.17, "style": st, "size": 12}
             for i, (n, hsh, st) in enumerate(hosts)]
    nodes += [
        {"id": "qz", "text": "var_calc quarantined", "sub": "on every member, hosts included, until the hosts agree",
         "x": 0.26, "y": 0.36, "w": 0.19, "h": 0.3, "style": "bad", "size": 14},
        {"id": "acme", "text": "acme MCP server", "sub": "offers search", "x": 0.53, "y": 0.14, "w": 0.15, "h": 0.17,
         "style": "ghost", "size": 12},
        {"id": "glx", "text": "globex MCP server", "sub": "offers search", "x": 0.53, "y": 0.67, "w": 0.15,
         "h": 0.17, "style": "ghost", "size": 12},
        {"id": "mem", "text": "risk-eu", "sub": "proxies both as external servers", "x": 0.71, "y": 0.37, "w": 0.13,
         "h": 0.28, "style": "accent", "size": 13},
        {"id": "n1", "text": f"acme{sep}search", "x": 0.875, "y": 0.2, "w": 0.125, "h": 0.15, "style": "white",
         "size": 12},
        {"id": "n2", "text": f"globex{sep}search", "x": 0.875, "y": 0.66, "w": 0.125, "h": 0.15, "style": "white",
         "size": 12},
    ]
    edges = [{"a": f"h{i}", "b": "qz", "mode": "c", "color": "BAD" if i == 3 else "SLATE"} for i in range(4)]
    edges += [{"a": "acme", "b": "mem", "mode": "c"}, {"a": "glx", "b": "mem", "mode": "c"},
              {"a": "mem", "b": "n1", "mode": "c", "color": "CRIMSON"}, {"a": "mem", "b": "n2", "mode": "c",
                                                                        "color": "CRIMSON"}]
    return {
        "kind": "canvas",
        "kicker": "One name, one contract",
        "title": "Within a net a tool name means one contract; vendors keep unrelated tools apart",
        "groups": [
            {"id": "gl", "label": "SAME NAME, DIFFERENT CONTRACT", "x": 0.0, "y": 0.0, "w": 0.47, "h": 1.0},
            {"id": "gr", "label": "UNRELATED VENDORS, ONE NAME", "x": 0.51, "y": 0.0, "w": 0.49, "h": 1.0},
        ],
        "nodes": nodes,
        "edges": edges,
        "note": "The quarantine names the differing host and the first place it differs (a JSON Pointer into a schema, "
        "or an annotation); a description or title difference is only a warning.",
        "source": f"{GUIDE} §8.7 (one name, one contract: quarantine, -32018 and -32011, lifting, escape hatch) and "
        f"§5.6 (vendors and external servers); separator sajha/tools/naming.py SEPARATOR, read at build time.",
        "talk": "A contract is the tool's name, input and output schemas and annotations, compared by hash. When hosts "
        "in a net offer one name with different hashes there is no winner: every member logs an error, raises a "
        "notice, audits it and evicts the name, so no copy is listed, callable or a fallback target anywhere, "
        "including on the hosts that offer it. The quarantine lifts by itself when every host offers one contract "
        "again. To change a contract, change every host together or ship it under a new name. Servers from unrelated "
        "organisations that happen to share a name are kept apart by defining them as external servers: a member "
        "proxies each one and publishes its tools under the vendor's prefix, so acme's search and globex's search "
        "never meet.",
    }


def _call(F: dict[str, Any]) -> dict[str, Any]:
    home = ["resolve the name", "access, schema, policy", "import rules", "residency on the arguments",
            "breaker, rate limit, hops, chain", "identity: key, assertion or token"]
    host = ["verify the signature", "blocks on the sender", "hops and loops", "verify the user", "map the user; blocks",
            "export rules", "its own access, policy, approvals", "execute; audit", "residency on the result"]
    nodes = [{"id": "caller", "text": "caller", "x": 0.0, "y": 0.08, "w": 0.1, "h": 0.1, "style": "white",
              "shape": "oval", "size": 12}]
    hh = 0.085
    for i, t in enumerate(home):
        nodes.append({"id": f"a{i}", "text": t, "x": 0.12, "y": 0.08 + i * 0.105, "w": 0.27, "h": hh,
                      "style": "white", "size": 12, "bold": False})
    nodes.append({"id": "afin", "text": "verify the answer; residency on arrival; audit", "x": 0.12, "y": 0.87,
                  "w": 0.27, "h": 0.11, "style": "accent", "size": 12})
    for i, t in enumerate(host):
        nodes.append({"id": f"b{i}", "text": t, "x": 0.69, "y": 0.08 + i * 0.1, "w": 0.31, "h": 0.08,
                      "style": "soft" if i != 7 else "dark", "size": 12, "bold": i == 7})
    edges = [{"a": "caller", "b": "a0", "mode": "c"}]
    edges += [
        {"a": f"a{len(home) - 1}", "b": "b0", "ports": ("r", "l"), "color": "CRIMSON", "width": 2.0,
         "label": "signed request, trace id, hop", "lsize": 11, "lcolor": "CRIMSON_D", "litalic": False, "lbold": True,
         "lpos": 0.5, "loff": (0.75, 0.3)},
        {"a": f"b{len(host) - 1}", "b": "afin", "mode": "c", "color": "CRIMSON", "width": 2.0,
         "label": "signed answer", "lsize": 11, "lcolor": "CRIMSON_D", "litalic": False, "lbold": True},
    ]
    return {
        "kind": "canvas",
        "kicker": "What happens on a call",
        "title": "On every remote call the home and the host both decide; neither trusts the other",
        "texts": [
            {"x": 0.12, "y": 0.0, "w": 0.27, "h": 0.07, "text": "HOME: where the caller is", "bold": True,
             "color": "CRIMSON_D", "size": 12},
            {"x": 0.69, "y": 0.0, "w": 0.31, "h": 0.07, "text": "HOST: where the tool runs", "bold": True,
             "color": "CRIMSON_D", "size": 12},
        ],
        "nodes": nodes,
        "edges": edges,
        "source": f"{GUIDE} §9 (what happens on a call; the host's order is protocol §15.4), §11.1 (both sides decide). "
        "Every refusal before execution carries executed: false.",
        "talk": "The home resolves the name, runs the call through execute_with_tracking like any tool (access, "
        "schema, policy), checks its import rules for this user and tool, checks residency on the arguments, then "
        "the per-peer breaker, rate limit, hop and call-chain budget, and attaches the user's identity. The request "
        "is signed and carries a trace id, the hop count and the visited list. The host verifies the signature, "
        "checks blocks on the sender, hops and loops, verifies the user, maps the user to its own account, checks "
        "blocks on the user and the tool, applies its export rules and its own access, policy and approvals, "
        "executes and audits, and checks residency on the result. The answer is signed too. A refusal reaches the "
        "caller as an ordinary tool result with isError, saying which side refused and why. Forwarded calls use the "
        "2026-07-28 era; proxy results are never cached; a destructive remote tool still needs confirmation at home.",
    }


def _routing(F: dict[str, Any]) -> dict[str, Any]:
    nt = F["net"]
    strategies = nt["plugins"]["routing"]
    nodes = [
        {"id": "r1", "text": "1  The local tool", "sub": "if this server has one by that name", "x": 0.0, "y": 0.05,
         "w": 0.3, "h": 0.17, "style": "accent", "size": 14},
        {"id": "r2", "text": "2  The tool's preference list", "sub": "a named host, or a net's hosts", "x": 0.0,
         "y": 0.33, "w": 0.3, "h": 0.17, "style": "dark", "size": 14},
        {"id": "r3", "text": "3  The nets in configured order", "sub": "hosts ordered by " + listing(strategies, "or"),
         "x": 0.0, "y": 0.61, "w": 0.3, "h": 0.17, "style": "dark", "size": 14},
        {"id": "home", "text": "home", "sub": "plain name var_calc", "x": 0.41, "y": 0.36, "w": 0.12, "h": 0.2,
         "style": "accent", "shape": "oval", "size": 13},
        {"id": "hA", "text": "host A", "sub": "breaker open: never sent", "x": 0.64, "y": 0.02, "w": 0.2, "h": 0.17,
         "style": "warn", "size": 13},
        {"id": "hB", "text": "host B", "sub": "-32019 overloaded, executed: false", "x": 0.64, "y": 0.37, "w": 0.2,
         "h": 0.17, "style": "warn", "size": 13},
        {"id": "hC", "text": "host C", "sub": "runs it; the result returns", "x": 0.64, "y": 0.72, "w": 0.2,
         "h": 0.17, "style": "ok", "size": 13},
        {"id": "rf", "text": "A refusal is a decision", "sub": "access, policy, identity, a block: returned, no "
         "fallback", "x": 0.87, "y": 0.3, "w": 0.13, "h": 0.32, "style": "box", "size": 12},
    ]
    edges = [
        {"a": "r1", "b": "r2", "label": "none here", "lsize": 10}, {"a": "r2", "b": "r3", "label": "none listed",
                                                                      "lsize": 10},
        {"a": "home", "b": "hA", "mode": "c", "label": "1st", "lsize": 10.5},
        {"a": "home", "b": "hB", "mode": "c", "label": "2nd", "lsize": 10.5},
        {"a": "home", "b": "hC", "mode": "c", "color": "OK", "label": "3rd", "lsize": 10.5},
        {"a": "r3", "b": "home", "mode": "c", "dash": True},
    ]
    return {
        "kind": "canvas",
        "kicker": "Routing and fallback",
        "title": "A plain name resolves in order, and falls back only when nothing ran",
        "nodes": nodes,
        "edges": edges,
        "note": f"At most {nt['max_fallbacks']} fallbacks after the first attempt (sajhanet.max_fallbacks, shipped), "
        "within one deadline; every attempt is audited under one trace id. A qualified name goes exactly where it says "
        "and never falls back.",
        "source": f"{GUIDE} §8.2 (names and resolution order), §9.1 (waterfall fallback). Routing strategies: the "
        "plug-ins registered in sajha/net/plugins.py; max_fallbacks from the shipped config/application.yml; both "
        "read at build time.",
        "talk": f"A qualified name, net{nt['sep']}instance{nt['sep']}tool, always reaches exactly the tool it names. A "
        "plain name goes first to a local tool of that name, then to the tool's preference list, then to the nets in "
        "configured order, where the routing strategy orders the hosts. A host is eligible when it offers the tool, "
        "is not suspect or blocked, the name is not quarantined, and this caller's import and residency rules allow "
        "it; why each host ranked where it did is recorded. Fallback moves to the next eligible host only after a "
        "failure that certainly did not run the tool, or, for read-only or idempotent non-destructive tools, after a "
        "failure that may have. A refusal by a host's access, policy, identity or block is that host's decision and "
        "is returned. A residency refusal at the home for one host is the exception: the call moves to a host that "
        "may receive the data.",
    }


def _identity(F: dict[str, Any]) -> dict[str, Any]:
    nt = F["net"]
    res = [r for r in nt["plugins"]["identity"] if r != "none"]
    if set(res) != {"api_key", "assertion", "token_exchange"}:
        raise SourceChanged(f"SAJHA Net identity resolvers changed: {res}")
    lanes = [
        ("api_key", "the API key, first hop only, over HTTPS",
         "hash it; find it in the net key directory; accept it only from its own home"),
        ("assertion", "a signed user assertion: only the key id crosses",
         "check signature, audience, time (at most 60 s) and one use of its id"),
        ("token_exchange", "a host-scoped token, exchanged once for an assertion",
         "keep it hashed; re-check the key, blocks and mapping on every call"),
    ]
    nodes, edges = [], []
    for i, (name, what, check) in enumerate(lanes):
        y = 0.0 + i * 0.23
        tag = " (shipped)" if name == nt["identity_shipped"] else ""
        nodes += [
            {"id": f"n{i}", "text": name + tag, "x": 0.0, "y": y, "w": 0.15, "h": 0.17,
             "style": "accent" if tag else "dark", "size": 13},
            {"id": f"w{i}", "text": what, "x": 0.19, "y": y, "w": 0.27, "h": 0.17, "style": "white", "size": 12,
             "bold": False},
            {"id": f"c{i}", "text": check, "x": 0.5, "y": y, "w": 0.27, "h": 0.17, "style": "soft", "size": 12,
             "bold": False},
        ]
        edges += [{"a": f"n{i}", "b": f"w{i}"}, {"a": f"w{i}", "b": f"c{i}", "color": "CRIMSON"}]
    nodes += [
        {"id": "map", "text": "The host maps the user", "sub": f"an explicit link, else the same login name, else "
         f"{nt['unknown_users']} (shipped)", "x": 0.81, "y": 0.0, "w": 0.19, "h": 0.63, "style": "dark", "size": 14},
        {"id": "tak", "text": "Test admin key: ships on, for development and testing", "sub": "While on, every forwarded "
         "call carries it, and a host that holds the same record runs the call as an administrator. Turn it off "
         "before production.", "x": 0.0, "y": 0.74, "w": 1.0, "h": 0.24, "style": "warn", "size": 14},
    ]
    edges += [{"a": f"c{i}", "b": "map", "mode": "c", "width": 1.2} for i in range(3)]
    if not nt["test_admin_shipped"]:
        nodes[-1] = {**nodes[-1], "text": "Test admin key: off in the shipped configuration", "style": "box"}
    return {
        "kind": "canvas",
        "kicker": "Identity across servers",
        "title": "The host verifies which user is calling, and applies its own rules to that user",
        "nodes": nodes,
        "edges": edges,
        "source": f"{GUIDE} §10.2 (identity resolvers; the home's key order; the test admin key), §10.3 (the net key "
        "directory), §11.3 (users across instances); docs/security/Security Model.md 'Test admin key'. Resolvers: the "
        "identity plug-ins registered by sajha/net/integration/authz.py and identity.py; shipped resolver, "
        "unknown-user rule and test admin key switch from config/application.yml; all read at build time.",
        "talk": "Without the user, a host could authorize only the server, and any user of that server would get "
        "whatever it may do: the confused deputy. So the user travels with every call. With api_key the home sends "
        "a key, only over HTTPS and only on the first hop; the host hashes it, finds its signed record in the net "
        "key directory (hashes only, never keys), and refuses it unless it came from its own home. With assertion "
        "only a key id crosses, in an assertion the home signs with its net certificate, valid for seconds and used "
        "once. With token_exchange the home swaps an assertion for an opaque token bound to the net and the home. "
        "Every server has its own users; the net never merges accounts. The host decides who alice@risk-eu is "
        "there: an explicit link, else the same login name, else refuse or a guest with mapped roles. The test "
        "admin key ships on by owner decision for development and testing; a critical notice shows on every page "
        "while it is active.",
    }


def _proxied(F: dict[str, Any]) -> dict[str, Any]:
    nt = F["net"]
    sep = nt["sep"]
    nodes = [
        {"id": "acme", "text": "acme MCP server", "sub": "external: never a member", "x": 0.0, "y": 0.06, "w": 0.17,
         "h": 0.19, "style": "ghost", "size": 13},
        {"id": "pricing", "text": "pricing MCP server", "sub": "internal: \"external\": false", "x": 0.0, "y": 0.62,
         "w": 0.17, "h": 0.19, "style": "white", "size": 13},
        {"id": "eu", "text": "risk-eu", "sub": "proxies both through federation", "x": 0.31, "y": 0.33, "w": 0.16,
         "h": 0.22, "style": "accent", "size": 15},
        {"id": "na", "text": "treasury-na", "sub": "a member", "x": 0.8, "y": 0.33, "w": 0.16, "h": 0.22,
         "style": "accent", "size": 15},
        {"id": "pub", "text": f"acme{sep}search", "sub": "vendor{0}tool, offered into the net".format(sep), "x": 0.56,
         "y": 0.1, "w": 0.18, "h": 0.17, "style": "white", "size": 13},
        {"id": "seen", "text": f"lists acme{sep}search", "sub": "external, via risk-eu", "x": 0.8, "y": 0.66,
         "w": 0.16, "h": 0.17, "style": "box", "size": 12},
        {"id": "loc", "text": f"pricing{sep}quote", "sub": "internal: keeps its name, offered like risk-eu's own tools", "x": 0.31,
         "y": 0.7, "w": 0.16, "h": 0.17, "style": "box", "size": 12},
    ]
    edges = [
        {"a": "acme", "b": "eu", "mode": "c"},
        {"a": "pricing", "b": "eu", "mode": "c"},
        {"a": "eu", "b": "pub", "mode": "c", "color": "CRIMSON"},
        {"a": "pub", "b": "na", "mode": "c", "color": "CRIMSON"},
        {"a": "eu", "b": "na", "both": True, "label": "signed calls", "lsize": 10},
        {"a": "na", "b": "seen", "dash": True, "arrow": False},
        {"a": "eu", "b": "loc", "dash": True, "arrow": False},
    ]
    return {
        "kind": "canvas",
        "kicker": "Proxied MCP servers",
        "title": "A member proxies other MCP servers; external ones enter the net under their vendor",
        "groups": [{"id": "net", "label": "NET acme-net", "x": 0.26, "y": 0.0, "w": 0.74, "h": 1.0, "dash": True}],
        "nodes": nodes,
        "edges": edges,
        "note": f"{sep} is reserved for namespaced tools: the registry refuses any other tool that uses it. Proxies nest: "
        f"outer{sep}inner{sep}tool, each level applying its own governance, bounded by 128 characters and one "
        "call-chain budget.",
        "source": f"{GUIDE} §5.6 (vendors and external servers, proxies all the way down); docs/architecture/Federation.md "
        "§4 (names, proxies all the way down) and §10 (the mcpServers file, config/mcp_servers.json, external by "
        f"default); separator sajha/tools/naming.py SEPARATOR, read at build time. Federation ships "
        f"{'on' if nt['federation_shipped'] else 'off'} (federation.enabled).",
        "talk": "A proxied MCP server is one a SAJHA server embeds through federation and offers as its own tools. In "
        "the mcpServers file, the same JSON Claude Desktop, Cursor and VS Code use, an entry is external unless it "
        "says external false. An external server is not a member: it has no member record, certificate or instance "
        "name and never gossips. The SAJHA server that defines it is its proxy; its tools are published as "
        f"vendor{sep}tool, its endpoint and credentials never leave that server, and every call runs with that "
        "server's full governance before federation calls the upstream. Every member lists the tool as external, "
        "via risk-eu. An internal proxied server's tools stay local. Members themselves are always internal and keep "
        "their tool names. A proxied server may itself proxy others; names compose and each level governs its own "
        "calls.",
    }


def _residency(F: dict[str, Any]) -> dict[str, Any]:
    nodes = [
        {"id": "home", "text": "home: risk-eu", "sub": "region eu-west", "x": 0.0, "y": 0.06, "w": 0.15, "h": 0.22,
         "style": "accent", "size": 14},
        {"id": "ga", "text": "arguments", "sub": "classes of the fields sent vs the host's region and labels",
         "x": 0.2, "y": 0.04, "w": 0.2, "h": 0.26, "style": "gold", "shape": "hex", "size": 13},
        {"id": "host", "text": "host: cust-na", "sub": "region na-east", "x": 0.45, "y": 0.06, "w": 0.15, "h": 0.22,
         "style": "dark", "size": 14},
        {"id": "gr", "text": "results", "sub": "classes of the fields returned vs the home's region", "x": 0.65,
         "y": 0.04, "w": 0.2, "h": 0.26, "style": "gold", "shape": "hex", "size": 13},
        {"id": "arr", "text": "on arrival", "sub": "the home's own rules", "x": 0.88, "y": 0.06, "w": 0.12, "h": 0.22,
         "style": "soft", "size": 13},
        {"id": "deny", "text": "deny: -32012, not executed", "sub": "a plain name moves to a host that may receive it",
         "x": 0.17, "y": 0.42, "w": 0.26, "h": 0.17, "style": "warn", "size": 12},
        {"id": "deny2", "text": "deny: -32012, executed", "sub": "a class marked for the whole result cannot be "
         "redacted", "x": 0.62, "y": 0.42, "w": 0.26, "h": 0.17, "style": "warn", "size": 12},
    ]
    edges = [
        {"a": "home", "b": "ga"}, {"a": "ga", "b": "host", "color": "CRIMSON"}, {"a": "host", "b": "gr"},
        {"a": "gr", "b": "arr", "color": "CRIMSON"},
        {"a": "ga", "b": "deny", "dash": True}, {"a": "gr", "b": "deny2", "dash": True},
    ]
    return {
        "kind": "canvas",
        "kicker": "Residency and redaction",
        "title": "Data classes decide where data may flow, in arguments and in results",
        "nodes": nodes,
        "edges": edges,
        "panels": [
            {"x": 0.0, "y": 0.68, "w": 0.48, "h": 0.32, "size": 13, "lines": [
                "# inputSchema marks a field's class",
                '"portfolio": {"type": "string",',
                '  "x-sajha-data-class": "confidential"}']},
            {"x": 0.52, "y": 0.68, "w": 0.48, "h": 0.32, "size": 13, "lines": [
                "# a redact rule sends the call anyway",
                '{"portfolio": "[REDACTED:confidential]",',
                ' "horizon": 10}']},
        ],
        "source": f"{GUIDE} §12 (data classes, residency rules, arguments, results, on arrival, residency-aware "
        "shortlists, audit, memory); docs/architecture/Policy and Audit.md §3.5 (residency rule conditions). The "
        "field and values are illustrative.",
        "talk": "Data classes come from x-sajha-data-class marks on schema properties (they are part of the contract "
        "hash), a tool's own data_classes, or classification by configuration. Residency rules are policy rules "
        "with conditions on data classes, the flow (arguments or results) and the destination (net, instance, "
        "region, labels). Before a call leaves, the home checks the classes of the fields present against the "
        "host's region and labels; the host checks its result against the home's; the home applies its own rules "
        "on arrival. A rule can deny or redact: redaction replaces the fields with [REDACTED:class] in structured "
        "content, JSON text and wherever a removed value is quoted. A remote tool whose host may not receive the "
        "classes every call sends is left out of tools/list and Ask SAJHA's shortlist for that caller. Every "
        "decision is a net.residency audit record, never with values. Conversation memory can keep an answer "
        "that used remote results with every figure replaced by [remote figure].",
    }


def _planners(F: dict[str, Any]) -> dict[str, Any]:
    nt = F["net"]
    budget = int(nt["max_call_chain"])
    chain = ["hop", "composite", "LLM tool", "hop"]
    cells = []
    cw = 1.0 / budget
    for i in range(budget):
        used = i < len(chain)
        cells.append({"id": f"c{i}", "text": chain[i] if used else "free", "x": i * cw + 0.004, "y": 0.84,
                      "w": cw - 0.008, "h": 0.14, "style": "accent" if used else "white", "size": 12,
                      "bold": used})
    rank = [("local tools", 0.4, "accent"), ("remote, in the tool's preferences", 0.36, "dark"),
            ("remote, same region, healthy", 0.32, "dark"), ("remote, lower latency", 0.28, "soft")]
    nodes = [{"id": f"k{i}", "text": t, "x": 0.0, "y": 0.06 + i * 0.15, "w": w, "h": 0.12, "style": st, "size": 12}
             for i, (t, w, st) in enumerate(rank)]
    nodes += [
        {"id": "pl", "text": "planner at home", "sub": "risk-eu", "x": 0.5, "y": 0.06, "w": 0.15, "h": 0.2,
         "style": "accent", "size": 13},
        {"id": "lt", "text": "remote LLM tool", "sub": "runs on the host as the mapped user", "x": 0.78, "y": 0.06,
         "w": 0.22, "h": 0.2, "style": "dark", "size": 13},
        {"id": "mem", "text": "memory stays home", "sub": "the remote tool gets its arguments only", "x": 0.5,
         "y": 0.42, "w": 0.15, "h": 0.22, "style": "soft", "size": 12},
        {"id": "bud", "text": "host's models and budget", "sub": "spend reported back, never charged twice",
         "x": 0.78, "y": 0.42, "w": 0.22, "h": 0.22, "style": "box", "size": 12},
    ]
    edges = [{"a": "pl", "b": "lt", "color": "CRIMSON", "label": "call", "lsize": 10},
             {"a": "lt", "b": "bud", "dash": True, "arrow": False}, {"a": "pl", "b": "mem", "dash": True,
                                                                     "arrow": False}]
    return {
        "kind": "canvas",
        "kicker": "Planners and LLM tools across the net",
        "title": "Planners see where each tool runs; one budget bounds the whole call chain",
        "nodes": nodes + cells,
        "edges": edges,
        "texts": [
            {"x": 0.0, "y": 0.0, "w": 0.45, "h": 0.06, "text": "SHORTLIST ORDER (small nudges to the score)",
             "bold": True, "color": "CRIMSON_D", "size": 11},
            {"x": 0.0, "y": 0.73, "w": 1.0, "h": 0.08,
             "text": f"CALL-CHAIN BUDGET: hops plus nesting on every instance passed, at most {budget} "
             "(sajhanet.max_call_chain, shipped)", "bold": True, "color": "CRIMSON_D", "size": 11},
        ],
        "source": f"{GUIDE} §13 (locality-aware shortlists, remote LLM tools, memory, budgets) and §14 (hops, the "
        "call-chain budget); max_call_chain and max_hops read from the shipped config/application.yml at build time. "
        "The chain shown is illustrative.",
        "talk": "Every shortlist entry records where the tool runs and why it ranked where it did. Local tools rank "
        "first, then remote hosts named in the tool's preferences, in this server's region, healthy, and with lower "
        "latency, as small nudges so the right remote tool is still offered. An ask can be restricted to local "
        "tools or one net. An LLM tool is exported like any tool; called from another instance it runs on its host "
        "as the mapped user, on the host's models and budgets, and the host reports the spend, which the home "
        "records and never charges again. Conversation memory lives only on the server the user talks to. A chain "
        "that crosses instances and nests planners, LLM tools, composites and sajha_ask is bounded end to end: "
        f"each forwarded call is one hop (at most {nt['max_hops']} by default), and the depth travels with the call.",
    }


def _reexport(F: dict[str, Any]) -> dict[str, Any]:
    nodes = [
        {"id": "A", "text": "home A", "sub": "the caller", "x": 0.0, "y": 0.1, "w": 0.16, "h": 0.2, "style": "white",
         "size": 13},
        {"id": "B", "text": "intermediary B", "sub": "re-exports C's tool", "x": 0.38, "y": 0.1, "w": 0.2, "h": 0.2,
         "style": "dark", "size": 13},
        {"id": "C", "text": "origin C", "sub": "hosts the tool", "x": 0.82, "y": 0.1, "w": 0.18, "h": 0.2,
         "style": "accent", "size": 13},
        {"id": "M", "text": "member of net M", "x": 0.03, "y": 0.66, "w": 0.18, "h": 0.17, "style": "white",
         "size": 12},
        {"id": "br", "text": "bridge", "sub": "a server in both nets", "x": 0.41, "y": 0.62, "w": 0.18, "h": 0.25,
         "style": "dark", "shape": "hex", "size": 13},
        {"id": "N", "text": "member of net N", "x": 0.79, "y": 0.66, "w": 0.18, "h": 0.17, "style": "white",
         "size": 12},
    ]
    edges = [
        {"a": "A", "b": "B", "color": "CRIMSON", "label": "assertion, audience = C", "lsize": 10.5},
        {"a": "B", "b": "C", "color": "CRIMSON", "label": "relayed unchanged, hop + 1", "lsize": 10.5},
        {"a": "N", "b": "br", "color": "CRIMSON", "label": "runs as the mapped local account", "lsize": 10.5},
        {"a": "br", "b": "M", "color": "CRIMSON", "label": "a new assertion signed in M", "lsize": 10.5},
    ]
    return {
        "kind": "canvas",
        "kicker": "Re-export and bridges",
        "title": "A tool can travel one more hop, within a net or across a bridge, only when turned on",
        "groups": [
            {"id": "g1", "label": "RE-EXPORT WITHIN ONE NET", "x": 0.0, "y": -0.02, "w": 1.0, "h": 0.42, "dash": True,
             "line": "SLATE", "color": "SLATE"},
            {"id": "gM", "label": "NET M", "x": 0.0, "y": 0.52, "w": 0.6, "h": 0.46, "line": "CRIMSON"},
            {"id": "gN", "label": "NET N", "x": 0.4, "y": 0.56, "w": 0.6, "h": 0.38, "line": "NAVY", "color": "NAVY"},
        ],
        "nodes": nodes,
        "edges": edges,
        "note": "One hop by default: a server exports only its own tools. Every instance on a longer chain must accept the "
        "extra hop (max_hops 2 for one intermediary), and the call-chain budget still applies on every step.",
        "source": f"{GUIDE} §14 (re-export within one net, bridges between nets) and §10.2 (a call to a re-exported tool "
        "and a bridge's call always use assertion); tests/net/test_net_reexport_identity.py.",
        "talk": "With re-export on for a net, an imported tool goes onward only when a re-export rule names it. It keeps "
        "its origin and contract, is never offered back to its host or origin, and the home ranks direct offers "
        "first. The home sends an assertion whose audience is the origin, never a key. The intermediary verifies it, "
        "maps and authorizes the caller under its re-export rules, and relays the assertion unchanged with the hop "
        "count raised, so residency, hops and the chain budget apply on every step. A bridge is a server in two "
        "nets that offers one net's tools in the other, only when re-export is on for the net it offers into. A call "
        "from N runs as the local account the caller maps to, which calls into M with an assertion the bridge signs "
        "there; a guest mapping cannot cross a bridge, and loops through several nets are caught by the visited list.",
    }


def _kinds(F: dict[str, Any]) -> dict[str, Any]:
    nodes = [
        {"id": "s", "text": "SAJHA instance", "sub": "kind sajha: enforces its own rules", "x": 0.0, "y": 0.04,
         "w": 0.26, "h": 0.2, "style": "accent", "size": 14},
        {"id": "a", "text": "SAJHA Net agent", "sub": "kind agent: a sidecar beside any MCP server", "x": 0.0,
         "y": 0.34, "w": 0.26, "h": 0.2, "style": "navy", "size": 14},
        {"id": "am", "text": "any MCP server", "sub": "stdio or Streamable HTTP", "x": 0.0, "y": 0.7, "w": 0.26,
         "h": 0.15, "style": "white", "size": 12},
        {"id": "sp", "text": "sponsor: a SAJHA server", "sub": "kind sponsored: runs a node for it", "x": 0.33,
         "y": 0.34, "w": 0.26, "h": 0.2, "style": "accent", "size": 14},
        {"id": "sm", "text": "vendor or SaaS MCP server", "sub": "knows nothing of SAJHA Net", "x": 0.33, "y": 0.7,
         "w": 0.26, "h": 0.15, "style": "ghost", "size": 12},
        {"id": "run", "text": "conformance runner", "sub": "python -m sajha.net.conformance", "x": 0.72, "y": 0.04,
         "w": 0.28, "h": 0.2, "style": "dark", "size": 14},
        {"id": "tS", "text": "S", "sub": "a SAJHA instance", "x": 0.72, "y": 0.37, "w": 0.085, "h": 0.2,
         "style": "white", "size": 16},
        {"id": "tA", "text": "A", "sub": "the agent", "x": 0.8175, "y": 0.37, "w": 0.085, "h": 0.2, "style": "white",
         "size": 16},
        {"id": "tL", "text": "L", "sub": "the library", "x": 0.915, "y": 0.37, "w": 0.085, "h": 0.2, "style": "white",
         "size": 16},
    ]
    edges = [
        {"a": "a", "b": "am", "dash": True, "both": True},
        {"a": "sp", "b": "sm", "dash": True, "label": "federation", "lsize": 10},
        {"a": "run", "b": "tS", "mode": "c"}, {"a": "run", "b": "tA"}, {"a": "run", "b": "tL", "mode": "c"},
    ]
    return {
        "kind": "canvas",
        "kicker": "Three ways to take part",
        "title": "Any MCP server can join: natively, through the agent, or sponsored",
        "nodes": nodes,
        "edges": edges,
        "texts": [{"x": 0.72, "y": 0.62, "w": 0.28, "h": 0.36, "size": 12,
                   "text": "Each case passes, fails or is skipped\nfrom outside, as a participant that\nnever joins; a "
                   "mixed net test runs\nall three targets in one net."}],
        "note": "Callers and planners cannot tell the kinds apart; only the member record (kind, and sponsor) says which "
        "is which.",
        "source": f"{GUIDE} §5.1 (three ways to take part), §5.7 (sponsored servers), §5.8 (the agent and the reference "
        "library), §5.9 (conformance; tests/net/test_net_mixed_conformance.py); docs/clients/SAJHA Net Agent.md.",
        "talk": "The agent, python -m sajhanet_agent, puts any MCP server, over stdio or Streamable HTTP, into a net as "
        "a member of kind agent: it holds the certificate, gossips, publishes the server's tools, verifies forwarded "
        "keys against the net key directory, applies a small export policy and passes allowed calls on. It only "
        "hosts. The reference library is the same participant inside a Python server. A sponsored server is one "
        "that cannot have anything beside it, a vendor's or SaaS endpoint: a SAJHA server runs a node for it under "
        "its own instance name and enforces everything for it. The conformance runner checks any target from "
        "outside and runs the library cases against the protocol's vectors; SAJHA's own suite covers the S cases. "
        "The agent is part of SAJHA, which is proprietary: running or redistributing it needs a written agreement.",
    }


def _console(F: dict[str, Any]) -> dict[str, Any]:
    from diagrams import ring as _ring_pts

    pts = _ring_pts(5, 0.25, 0.55, 0.2, 0.33)
    states = [("risk-eu", "accent"), ("treasury-na", "accent"), ("cust-na", "warn"), ("risk-apac", "accent"),
              ("vendor-search", "navy")]
    w, h = 0.13, 0.13
    nodes = [{"id": "me", "text": "this server", "x": 0.25 - 0.07, "y": 0.55 - 0.08, "w": 0.14, "h": 0.16,
              "style": "dark", "shape": "oval", "size": 13}]
    nodes += [{"id": f"p{i}", "text": n, "sub": "suspect" if st == "warn" else "", "x": cx - w / 2, "y": cy - h / 2,
               "w": w, "h": h, "style": st, "shape": "oval", "size": 11}
              for i, ((n, st), (cx, cy)) in enumerate(zip(states, pts))]
    edges = [{"a": "me", "b": f"p{i}", "mode": "c", "width": 1.2 if i != 0 else 3.0,
              "color": "CRIMSON" if i == 0 else "SLATE", "dash": i == 4} for i in range(5)]
    blocks = ["an instance, entirely", "inbound calls only", "outbound calls only", "one tool", "one remote user"]
    nodes += [{"id": f"b{i}", "text": t, "x": 0.56, "y": 0.1 + i * 0.17, "w": 0.18, "h": 0.13, "style": "white",
               "size": 12, "bold": False} for i, t in enumerate(blocks)]
    pages = ["Instances", "Your net access", "Net overview (topology)", "Remote tools", "SAJHA Net admin"]
    nodes += [{"id": f"g{i}", "text": t, "x": 0.8, "y": 0.1 + i * 0.17, "w": 0.2, "h": 0.13,
               "style": "soft" if i < 2 else "box", "size": 12} for i, t in enumerate(pages)]
    return {
        "kind": "canvas",
        "kicker": "Blocks and the console",
        "title": "Each server blocks on its own terms, and the console draws the net",
        "nodes": nodes,
        "edges": edges,
        "texts": [
            {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.07, "text": "TOPOLOGY: solid offers, dashed re-exports, thick calls",
             "bold": True, "color": "CRIMSON_D", "size": 11},
            {"x": 0.56, "y": 0.0, "w": 0.2, "h": 0.07, "text": "BLOCK", "bold": True, "color": "CRIMSON_D", "size": 11},
            {"x": 0.8, "y": 0.0, "w": 0.2, "h": 0.07, "text": "PAGES", "bold": True, "color": "CRIMSON_D", "size": 11},
        ],
        "note": "Blocks are local decisions and shared information: each server publishes its blocks, so any console "
        "can draw them, but only the server that set a block enforces it. Problems reach administrators as system "
        "notices.",
        "source": f"{GUIDE} §11.4 (blocking) and §17 (the console: pages, topology map, admission panel, notices). "
        "Tinted pages are for every signed-in user, the others for administrators.",
        "talk": "An administrator blocks, per net, at five levels: an instance entirely (stop calling it, refuse its "
        "calls, ignore its updates), inbound only, outbound only, one tool, or one remote user. A block takes effect "
        "on the next request, may expire, carries a reason and is audited. Removing a server from the whole net is "
        "a revocation or a removed pin, not a block. The topology map draws this server in the centre and the others "
        "on a ring, coloured by state and labelled in words when not alive, with edges for offers, re-exports and "
        "observed calls; a table under it lists the same. Instances and Your net access are for every signed-in "
        "user; Net overview, Remote tools and the admin page for administrators. Every page has JSON behind it and "
        "the sajha net commands do the same over HTTP.",
    }


def slides(F: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "divider",
            "title": "SAJHA Net and proxied MCP servers",
            "sub": "Many SAJHA servers, and other MCP servers, joined into one net: each keeps its own data, "
            "credentials, policy, models and memory, and only a governed tool call crosses a boundary.",
            "points": ["Why a net", "Membership", "Admission", "One name, one contract", "A call", "Routing",
                       "Identity", "Proxied MCP servers", "Residency", "Planners", "Re-export", "Taking part",
                       "Console"],
        },
        _why(F),
        _ring(F),
        _admission(F),
        _contract(F),
        _call(F),
        _routing(F),
        _identity(F),
        _proxied(F),
        _residency(F),
        _planners(F),
        _reexport(F),
        _kinds(F),
        _console(F),
    ]
