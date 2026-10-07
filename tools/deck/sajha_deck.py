"""
The one SAJHA deck, as data: the title slide here, and the nine parts in order in
``deck_part1`` to ``deck_part4``.

It is written for the people who must trust SAJHA with their tools and their data -- a
platform owner, a security reviewer, a head of a desk whose agents need data, an
engineer asked to connect a client -- and it answers their questions in the order they
ask them: why agents stall at the tools layer, the words needed to talk about it, one
question carried end to end, which clients it can serve, whether its governance can be
signed off, which tools it has, what its intelligence layer does, how it runs, and how
it compares, including where others are stronger.

Every number comes from ``evidence``, which derives it from the code, the configuration,
the CI workflow or the compliance reports while the deck is built; each slide's notes
name the source.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

import deck_part1
import deck_part2
import deck_part3
import deck_part4
import evidence

CHAPTER = "SAJHA · One governed catalog of tools"
TITLE = "SAJHA — One Governed Catalog of Tools for Every Agent"
SUBJECT = "Why agents stall at the tools layer, what SAJHA does about it, and the evidence"

PARTS = [
    "Why agents stall at the tools layer",
    "The vocabulary, from nothing",
    "One question, end to end",
    "Speaking every client's language",
    "Governance an enterprise can sign off",
    "Every tool you have",
    "The intelligence layer",
    "How it runs",
    "How it compares, honestly",
]


def opening(F: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "title",
            "kicker": "साझा  ·  SHARED",
            "title": ["SAJHA: one governed catalog", "of tools for every agent"],
            "sub": "Shared tools, shared rules, one record.",
            "date": "October 2026",
            "version": f"SAJHA {F['version']} (app.version)",
            "agenda": PARTS,
        },
    ]


def slides() -> list[dict[str, Any]]:
    F = evidence.facts()
    out = opening(F)
    for part in (deck_part1, deck_part2, deck_part3, deck_part4):
        out += part.slides(F)
    return out
