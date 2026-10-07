"""
Slide layouts, each drawn from a plain dictionary.

A deck is data: a list of slide specs, each naming its ``kind``. Keeping the
content out of the drawing code is what lets one deck be assembled from four
modules that share one set of layouts, and what keeps every layout short enough to read — and to fit.

Kinds: ``title``, ``divider``, ``bullets``, ``table``, ``cards``, ``stats``,
``split`` (either column may be ``lines``: a captured run in a monospaced panel),
``flow``, ``context``.

Every slide but the title and the dividers carries a ``source``: it becomes the slide's
speaker notes and names where each number and claim on the slide comes from. A content
slide without one fails the build, as a slide that does not fit does.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from pptx.enum.text import PP_ALIGN

import theme as T
from metrics import SH, SW, text_h

GAP = 0.18


def _items(tf: Any, items: list[Any], size: float) -> None:
    """Bulleted items; a tuple is ``(head, body)``."""
    for i, it in enumerate(items):
        first = i == 0
        if isinstance(it, tuple):
            T.runs(
                tf,
                [("▪  ", T.CRIMSON, True), (it[0], T.INK, True)],
                size=size,
                space_after=1,
                first=first,
                space_before=0 if first else 5,
            )
            T.runs(tf, [(it[1], T.SLATE, False)], size=size - 1.5, space_after=0, level=1)
        else:
            T.runs(
                tf,
                [("▪  ", T.CRIMSON, True), (it, T.INK, False)],
                size=size,
                space_after=0,
                first=first,
                space_before=0 if first else 6,
            )


def _intro(sl: Any, y: float, text: str | None) -> float:
    if not text:
        return y
    used = T.fitted(
        sl,
        T.ML,
        y,
        T.CW,
        1.0,
        lambda tf, s: T.para(tf, text, size=s, color=T.INK, first=True, space_after=0, line=1.25),
        14,
        11,
    )
    return y + used + GAP


def _note(sl: Any, text: str | None) -> float:
    """A crimson-ruled note pinned above the footer; returns its top."""
    if not text:
        return T.BODY_BOTTOM
    size = 12.0
    width = T.CW - 0.3
    while size > 9 and text_h(text, width * 0.94, size, False, "Calibri", 1.2) > 0.9:
        size -= 0.5
    h = text_h(text, width * 0.94, size, False, "Calibri", 1.2)
    top = T.BODY_BOTTOM - h
    T.rect(sl, T.ML, top, 0.045, h, fill=T.CRIMSON)
    T.fitted(
        sl,
        T.ML + 0.25,
        top,
        width,
        h + 0.02,
        lambda tf, s: T.para(
            tf, text, size=s, color=T.SLATE, italic=True, first=True, space_after=0, line=1.2
        ),
        size,
        8.5,
    )
    return top - GAP


def title(s: dict[str, Any]) -> None:
    T._state["n"] = 1
    sl = T.blank()
    T.rect(sl, 0, 0, SW, SH, fill=T.WHITE)
    T.rect(sl, 0, 0, SW, 4.3, fill=T.CRIMSON)
    T.rect(sl, 0, 4.3, SW, 0.06, fill=T.NAVY)
    T.rect(sl, 0, 0, 0.20, 4.3, fill=T.NAV_FROM)
    tf = T.txt(sl, T.ML + 0.3, 0.9, T.CW, 0.34)
    T.para(tf, s["kicker"], size=11, color=T.PINK, bold=True, first=True, space_after=0)

    def head(tf: Any, size: float) -> None:
        for i, line in enumerate(s["title"]):
            T.para(
                tf,
                line,
                size=size,
                color=T.WHITE,
                font="Georgia",
                first=i == 0,
                space_after=0,
                line=1.1,
            )

    T.fitted(sl, T.ML + 0.3, 1.4, T.CW * 0.9, 1.75, head, 38, 26)
    T.rect(sl, T.ML + 0.3, 3.25, 1.7, 0.035, fill=T.PINK)
    # The slogan, set to be read rather than noticed in passing: the serif face the titles
    # use, in italic, large enough to be the second thing on the page and not the fifth.
    tf = T.txt(sl, T.ML + 0.3, 3.42, T.CW * 0.85, 0.8)
    T.para(
        tf,
        s["sub"],
        size=25,
        color=T.WHITE,
        italic=True,
        font="Georgia",
        first=True,
        space_after=0,
    )
    tf = T.txt(sl, T.ML + 0.3, 4.75, T.CW * 0.5, 1.2)
    T.para(
        tf,
        "Ashutosh Sinha",
        size=20,
        color=T.INK,
        bold=True,
        font="Georgia",
        first=True,
        space_after=3,
    )
    T.para(tf, s["date"], size=12, color=T.CRIMSON, space_after=1)
    T.para(
        tf,
        s["version"],
        size=11,
        color=T.SLATE,
        space_after=0,
    )
    x0 = T.ML + T.CW * 0.56

    def agenda(tf: Any, size: float) -> None:
        T.para(tf, "IN THIS DECK", size=9.5, color=T.CRIMSON, bold=True, first=True, space_after=6)
        for i, c in enumerate(s["agenda"], 1):
            T.runs(
                tf, [(f"{i}   ", T.CRIMSON, True), (c, T.SLATE, False)], size=size, space_after=3
            )

    T.fitted(sl, x0, 4.62, T.CW * 0.44, 2.12, agenda, 11.5, 9)
    T.footer(sl)


def divider(s: dict[str, Any]) -> None:
    T.divider(s["num"], s["title"], s["sub"], s["points"])


def bullets(s: dict[str, Any]) -> None:
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    T.fitted(
        sl,
        T.ML,
        y,
        T.CW,
        bottom - y,
        lambda tf, size: _items(tf, s["items"], size),
        s.get("size", 17),
        9.5,
    )


def table(s: dict[str, Any]) -> None:
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    T.fitted_table(
        sl,
        s["rows"],
        T.ML,
        y,
        T.CW,
        bottom - y,
        s.get("col_w"),
        start=s.get("size", 14),
        bold_col0=s.get("bold_col0", True),
    )


def cards(s: dict[str, Any]) -> None:
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    items = s["cards"]
    cols = s.get("cols", 3)
    rows = (len(items) + cols - 1) // cols
    cw = (T.CW - GAP * (cols - 1)) / cols
    ch = (bottom - y - GAP * (rows - 1)) / rows
    for i, (num, head, body) in enumerate(items):
        r, c = divmod(i, cols)
        T.card(sl, T.ML + c * (cw + GAP), y + r * (ch + GAP), cw, ch, num, head, body)


def stats(s: dict[str, Any]) -> None:
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    T.statbar(sl, y, s["stats"])
    y += 1.25 + GAP + 0.05
    bottom = _note(sl, s.get("note"))
    if s.get("rows"):
        T.fitted_table(
            sl, s["rows"], T.ML, y, T.CW, bottom - y, s.get("col_w"), start=s.get("size", 13.5),
            bold_col0=s.get("bold_col0", True),
        )
    elif s.get("items"):
        T.fitted(
            sl,
            T.ML,
            y,
            T.CW,
            bottom - y,
            lambda tf, size: _items(tf, s["items"], size),
            s.get("size", 16),
            9.5,
        )


def _column(sl: Any, x: float, y: float, w: float, h: float, col: dict[str, Any]) -> None:
    T.rect(sl, x, y, w, 0.42, fill=T.PARCH)
    T.rect(sl, x, y, 0.045, 0.42, fill=T.CRIMSON)
    tf = T.txt(sl, x + 0.18, y + 0.08, w - 0.3, 0.3)
    T.para(tf, col["head"], size=13, color=T.CRIMSON_D, bold=True, first=True, space_after=0)
    top = y + 0.42 + 0.14
    if col.get("lines"):
        T.panel(sl, x, top, w, y + h - top, col["lines"], col.get("size", 12.5))
    elif col.get("rows"):
        T.fitted_table(
            sl, col["rows"], x, top, w, y + h - top, col.get("col_w"), start=col.get("size", 13)
        )
    else:
        T.fitted(
            sl,
            x,
            top,
            w,
            y + h - top,
            lambda tf, size: _items(tf, col["items"], size),
            col.get("size", 15),
            9,
        )


def split(s: dict[str, Any]) -> None:
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    lw = (T.CW - 0.4) * s.get("left_w", 0.5)
    rw = (T.CW - 0.4) - lw
    _column(sl, T.ML, y, lw, bottom - y, s["left"])
    _column(sl, T.ML + lw + 0.4, y, rw, bottom - y, s["right"])


def flow(s: dict[str, Any]) -> None:
    """Boxes in a row, joined by straight arrows; then optional items beneath."""
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    steps = s["steps"]
    arrow = 0.28
    bw = (T.CW - arrow * (len(steps) - 1)) / len(steps)
    bh = s.get("box_h", 1.9)
    for i, (head, body) in enumerate(steps):
        x = T.ML + i * (bw + arrow)
        T.card(sl, x, y, bw, bh, "", head, body)
        if i:
            T.connect(sl, x - arrow + 0.03, y + bh / 2, x - 0.03, y + bh / 2, T.CRIMSON, 2.0)
    top = y + bh + GAP + 0.05
    if s.get("items"):
        T.fitted(
            sl,
            T.ML,
            top,
            T.CW,
            bottom - top,
            lambda tf, size: _items(tf, s["items"], size),
            s.get("size", 15),
            9,
        )
    elif s.get("rows"):
        T.fitted_table(
            sl, s["rows"], T.ML, top, T.CW, bottom - top, s.get("col_w"), start=s.get("size", 13)
        )


def context(s: dict[str, Any]) -> None:
    """A system context diagram: boxes placed on the content area, joined by arrows.

    Positions are fractions of the content box rather than inches, so a diagram keeps its
    proportions if the theme's margins move. Anchors are chosen from the relative position
    of the two boxes -- an arrow leaves the side that faces its target -- because an elbow
    connector routes itself into the nodes it joins.
    """
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    x0, w0, h0 = T.ML, T.CW, bottom - y

    box: dict[str, tuple[float, float, float, float]] = {}
    for n in s["nodes"]:
        bx, by = x0 + n["x"] * w0, y + n["y"] * h0
        bw, bh = n["w"] * w0, n["h"] * h0
        box[n["id"]] = (bx, by, bw, bh)

    # Arrows first, so that a box always sits on top of the line that reaches it.
    for e in s.get("edges", []):
        ax, ay, aw, ah = box[e[0]]
        bx, by, bw, bh = box[e[1]]
        acx, acy, bcx, bcy = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
        # Which sides the arrow leaves and enters. Comparing centres is the obvious rule and
        # the wrong one: a wide box can have its centre far to the right of a small box while
        # its left edge is still to the left of it, and the arrow then doubles back on itself.
        # Overlap is the rule that holds -- if the two boxes share a column, the arrow is
        # vertical; if they share a row, it is horizontal -- and a shared column is drawn as
        # a true vertical, down the middle of the overlap rather than slanting between centres.
        #
        # The small gap at each end keeps the connector's bounding box off the card it points
        # at: without it the geometry audit reports a line hidden behind an opaque shape, which
        # from the audit's side is indistinguishable from a line drawn underneath one.
        gap = 0.04
        xlo, xhi = max(ax, bx), min(ax + aw, bx + bw)
        ylo, yhi = max(ay, by), min(ay + ah, by + bh)
        if xhi - xlo > 0.2:
            mid = (xlo + xhi) / 2
            down = bcy > acy
            p1 = (mid, (ay + ah + gap) if down else (ay - gap))
            p2 = (mid, (by - gap) if down else (by + bh + gap))
        elif yhi - ylo > 0.2:
            right = bcx > acx
            mid = (ylo + yhi) / 2
            p1 = ((ax + aw + gap) if right else (ax - gap), mid)
            p2 = ((bx - gap) if right else (bx + bw + gap), mid)
        else:
            down = bcy > acy
            p1 = (acx, (ay + ah + gap) if down else (ay - gap))
            p2 = (bcx, (by - gap) if down else (by + bh + gap))
        T.connect(sl, p1[0], p1[1], p2[0], p2[1], T.SLATE, 1.5)
        # A label only where the arrow has room for one. The gap between two ranks of boxes
        # can be narrower than a line of text, and a label that spills into the card below is
        # worse than no label: the arrow's direction already carries most of the meaning.
        span = abs(p2[1] - p1[1]) if p1[0] == p2[0] else abs(p2[0] - p1[0])
        if len(e) > 2 and e[2] and span > 0.30:
            tf = T.txt(
                sl,
                (p1[0] + p2[0]) / 2 - 0.85,
                (p1[1] + p2[1]) / 2 - 0.085,
                1.7,
                0.17,
                align=PP_ALIGN.CENTER,
            )
            T.para(tf, e[2], size=7.5, color=T.SLATE, space_after=0, first=True)

    for n in s["nodes"]:
        bx, by, bw, bh = box[n["id"]]
        T.card(sl, bx, by, bw, bh, n.get("num", ""), n["head"], n.get("body", ""))


KINDS = {
    "context": context,
    "title": title,
    "divider": divider,
    "bullets": bullets,
    "table": table,
    "cards": cards,
    "stats": stats,
    "split": split,
    "flow": flow,
}


UNSOURCED = ("title", "divider")


class Unsourced(Exception):
    """A content slide that does not say where its content comes from."""


def render(slides: list[dict[str, Any]]) -> None:
    for i, spec in enumerate(slides, 1):
        if spec["kind"] not in UNSOURCED and not str(spec.get("source", "")).strip():
            raise Unsourced(f"slide {i} ({spec.get('title')!r}) has no source for its notes")
        try:
            KINDS[spec["kind"]](spec)
        except T.DoesNotFit as exc:
            raise T.DoesNotFit(f"slide {i} ({spec.get('title')!r}): {exc}") from exc
        if spec.get("source"):
            T.notes(T._state["prs"].slides[-1], "Source: " + spec["source"])
