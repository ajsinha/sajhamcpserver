"""
The one SAJHA deck, as data: the title slide and the executive summary here, and seven
numbered sections in order in ``deck_part1`` to ``deck_part4``.

Its arc teaches before it sells: what MCP is, from nothing, and why every AI application
should speak it; how applications integrate with it; then SAJHA itself (its tools, how
tools are made, its architecture, who may call it and how each caller proves it, step by
step, its rules and its record, and where it runs); agents and workflows; data and
analytics; the intelligence layer and the operational deep dives; and, last, what is not
built yet, how it compares, and where to start.

Every number comes from ``evidence``, which derives it from the code, the configuration,
the CI workflow or the compliance reports while the deck is built; each slide's notes
name the source. Statements about MCP and the quotations cite public pages with the date
they were read.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

import deck_part1
import deck_part2
import deck_part3
import deck_part4
import evidence

CHAPTER = "SAJHA MCP Server"
TITLE = "SAJHA MCP Server — One Protocol, Infinite Possibilities"
SUBJECT = "The Model Context Protocol from first principles, and SAJHA: one governed catalog of tools for every agent"

SECTIONS = [
    "The Model Context Protocol",
    "MCP integration with AI applications",
    "The SAJHA MCP server",
    "Agent and workflow integration",
    "Data and analytics integration",
    "Intelligence and operations",
    "Where it's going, and how it compares",
]


def opening(F: dict[str, Any]) -> list[dict[str, Any]]:
    cat = F["catalog"]
    eras = F["eras"]
    return [
        {
            "kind": "title",
            "kicker": "साझा  ·  shared",
            "title": "SAJHA MCP Server",
            "sub": "One Protocol, Infinite Possibilities",
            "sub2": "One governed catalog of tools for every agent",
            "date": "October 2026",
            "version": f"SAJHA {F['version']} (app.version)",
        },
        {
            "kind": "tldr",
            "kicker": "TL;DR",
            "title": "Executive summary: five questions, five answers",
            "rows": [
                ("What is MCP?", "An open standard, now under the Linux Foundation's Agentic AI Foundation, that lets "
                 "AI applications connect to any tool or data source through one protocol instead of one integration "
                 "per pair."),
                ("What is the SAJHA MCP server?", f"A self-hosted MCP server with {cat['tools']} built-in tools, browser "
                 "tool builders, an intelligence layer (LLM gateway, Ask SAJHA, planners, memory, document search) and "
                 "governance: access control, OAuth 2.1, policy rules, approvals and a tamper-evident audit."),
                ("Why does it matter?", "It removes bespoke integration code: any agent discovers and calls tools at "
                 "run time, and every call, whoever makes it, passes one set of identities, rules and records."),
                ("What can it do today?", f"Serve both MCP eras ({eras['modern'][0]} and {eras['handshake'][0]}) on one "
                 f"endpoint over four transports; {len(F['studio_pages'])} ways to make a tool; data connectors, "
                 f"federation, workflows; {F['conformance']['passed']} conformance checks passed, "
                 f"{F['conformance']['failed']} failed."),
                ("Where is it going?", "Enforced multi-tenancy, finer Studio permissions, a TypeScript client, more "
                 "connectors and document sources (Section 7)."),
            ],
            "source": "MCP governance: https://www.anthropic.com/news/donating-the-model-context-protocol-and-"
            "establishing-of-the-agentic-ai-foundation (9 Dec 2025, read 2026-10-06). Tool count: the live registry; "
            "eras: sajha.core.mcp_modern; creators: the Studio routes; conformance: docs/protocol/MCP 2026-07-28 "
            "Compliance.md §5; all read at build time. Not built yet: Section 7's sources.",
        },
    ]


def slides() -> list[dict[str, Any]]:
    F = evidence.facts()
    out = opening(F)
    for part in (deck_part1, deck_part2, deck_part3, deck_part4):
        out += part.slides(F)
    return out
