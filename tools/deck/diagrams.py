"""
Geometry helpers for the ``canvas`` slides: a layered layout for a DAG, points on a ring,
and a row of evenly spaced boxes. They return plain dictionaries in the canvas's fractional
coordinates, so the slide modules stay data and the drawing stays in ``layouts``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import math
from typing import Any


def levels(steps: list[dict[str, Any]]) -> dict[str, int]:
    """Each step's longest distance from a step with no dependencies."""
    by_id = {s["id"]: s for s in steps}
    memo: dict[str, int] = {}

    def depth(i: str) -> int:
        if i not in memo:
            deps = by_id[i].get("depends_on") or []
            memo[i] = 0 if not deps else 1 + max(depth(d) for d in deps)
        return memo[i]

    return {s["id"]: depth(s["id"]) for s in steps}


def layered(steps: list[dict[str, Any]], x0: float, x1: float, y0: float, y1: float, w: float, h: float,
            order: list[str] | None = None) -> dict[str, tuple[float, float]]:
    """Top-left corners for a left-to-right layered drawing of a DAG within [x0, x1] x [y0, y1]."""
    lv = levels(steps)
    n = max(lv.values()) + 1
    cols: dict[int, list[str]] = {}
    for s in order or [s["id"] for s in steps]:
        cols.setdefault(lv[s], []).append(s)
    step_x = (x1 - x0 - w) / max(1, n - 1)
    out = {}
    for c, ids in cols.items():
        gap = (y1 - y0 - h * len(ids)) / (len(ids) + 1)
        for k, i in enumerate(ids):
            out[i] = (x0 + c * step_x, y0 + gap * (k + 1) + h * k)
    return out


def ring(n: int, cx: float, cy: float, rx: float, ry: float, start_deg: float = -90.0) -> list[tuple[float, float]]:
    """Centres of n points on an ellipse, clockwise from ``start_deg`` (-90 is the top)."""
    return [(cx + rx * math.cos(math.radians(start_deg + 360.0 * k / n)),
             cy + ry * math.sin(math.radians(start_deg + 360.0 * k / n))) for k in range(n)]


def row(n: int, x0: float, x1: float, w: float) -> list[float]:
    """Left edges of n boxes of width w spread evenly across [x0, x1]."""
    if n == 1:
        return [x0 + (x1 - x0 - w) / 2]
    step = (x1 - x0 - w) / (n - 1)
    return [x0 + k * step for k in range(n)]
