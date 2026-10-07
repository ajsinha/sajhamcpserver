"""
Slide layouts, each drawn from a plain dictionary.

A deck is data: a list of slide specs, each naming its ``kind``. Keeping the
content out of the drawing code is what lets one deck be assembled from four
modules that share one set of layouts, and what keeps every layout short enough to read — and to fit.

Kinds: ``title``, ``divider``, ``tldr`` (question and answer rows), ``principles``
(numbered items in columns), ``quotes``, ``steps`` (numbered rows), ``bullets``, ``table``,
``cards``, ``stats``, ``split`` (either column may be ``lines``: a captured run in a
monospaced panel), ``flow``, ``context``, ``diagram`` (groups, boxes and arrows), ``mono``
(a step-by-step exchange in monospace) and ``thanks``.

Every slide but the title and the dividers carries a ``source``: it becomes the slide's
speaker notes and names where each number and claim on the slide comes from. A content
slide without one fails the build, as a slide that does not fit does.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

from pptx.enum.shapes import MSO_SHAPE
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
    """The opening slide: the mark and साझा, the name, the tagline, the author and date."""
    T._state["n"] = 1
    sl = T.blank()
    T.rect(sl, 0, 0, SW, SH, fill=T.CRIMSON)
    T.rect(sl, 0, 0, 0.22, SH, fill=T.CRIMSON_D)
    T.mark(sl, T.ML + 0.2, 0.75, 0.85, T.WHITE, 2.2)
    tf = T.txt(sl, T.ML + 1.25, 0.78, 6.0, 0.5)
    T.para(tf, "SAJHA", size=26, color=T.WHITE, bold=True, font="Georgia", first=True, space_after=0)
    tf = T.txt(sl, T.ML + 1.25, 1.25, 6.0, 0.4)
    T.para(tf, s["kicker"], size=14, color=T.PINK, first=True, space_after=0)

    def head(tf: Any, size: float) -> None:
        T.para(tf, s["title"], size=size, color=T.WHITE, font="Georgia", first=True, space_after=0, line=1.1)

    T.fitted(sl, T.ML + 0.2, 2.25, T.CW * 0.9, 1.0, head, 44, 30)
    tf = T.txt(sl, T.ML + 0.2, 3.25, T.CW * 0.9, 0.6)
    T.para(tf, s["sub"], size=24, color=T.PINK_L, italic=True, font="Georgia", first=True, space_after=0)
    tf = T.txt(sl, T.ML + 0.2, 3.9, T.CW * 0.9, 0.45)
    T.para(tf, s["sub2"], size=16, color=T.PINK, first=True, space_after=0)
    T.rect(sl, T.ML + 0.2, 4.55, 1.7, 0.035, fill=T.PINK)
    tf = T.txt(sl, T.ML + 0.2, 4.8, T.CW * 0.5, 1.3)
    T.para(tf, "Ashutosh Sinha", size=20, color=T.WHITE, bold=True, font="Georgia", first=True, space_after=4)
    T.para(tf, s["date"], size=13, color=T.PINK_L, space_after=2)
    T.para(tf, s["version"], size=11, color=T.PINK, space_after=0)
    T.footer(sl, T.PINK)


def tldr(s: dict[str, Any]) -> None:
    """Question and answer rows: a question in a tinted label, its answer beside it."""
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    rows = s["rows"]
    gap = 0.12
    rh = (bottom - y - gap * (len(rows) - 1)) / len(rows)
    qw = s.get("q_w", 2.9)
    for i, (q, a) in enumerate(rows):
        ry = y + i * (rh + gap)
        T.rect(sl, T.ML, ry, T.CW, rh, fill=T.PARCH)
        T.rect(sl, T.ML, ry, 0.06, rh, fill=T.CRIMSON)
        T.fitted(sl, T.ML + 0.22, ry + 0.08, qw - 0.3, rh - 0.16,
                 lambda tf, z, q=q: T.para(tf, q, size=z, color=T.CRIMSON_D, bold=True, font="Georgia",
                                           first=True, space_after=0, line=1.12), 18, 10)
        T.fitted(sl, T.ML + qw, ry + 0.08, T.CW - qw - 0.2, rh - 0.16,
                 lambda tf, z, a=a: T.para(tf, a, size=z, color=T.INK, first=True, space_after=0, line=1.18),
                 s.get("size", 18), 9.5)


def principles(s: dict[str, Any]) -> None:
    """Numbered items in two columns: a numbered circle, a bold head, a sentence."""
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    items = s["items"]
    cols = s.get("cols", 2)
    per = (len(items) + cols - 1) // cols
    cw = (T.CW - 0.4 * (cols - 1)) / cols
    rh = (bottom - y) / per
    d = min(0.42, rh - 0.12)
    for i, (head, body) in enumerate(items):
        c, r = divmod(i, per)
        x = T.ML + c * (cw + 0.4)
        ry = y + r * rh
        T.numdot(sl, x, ry + 0.04, d, str(i + 1))

        def write(tf: Any, z: float, head: str = head, body: str = body) -> None:
            T.para(tf, head, size=z, color=T.INK, bold=True, first=True, space_after=1, line=1.1)
            T.para(tf, body, size=z - 2, color=T.SLATE, space_after=0, line=1.15)

        T.fitted(sl, x + d + 0.18, ry, cw - d - 0.2, rh - 0.08, write, s.get("size", 18), 10)


def quotes(s: dict[str, Any]) -> None:
    """Quotations in tinted cards: the words, then who said them, where and when."""
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    qs = s["quotes"]
    cols = s.get("cols", 2)
    rows = (len(qs) + cols - 1) // cols
    cw = (T.CW - GAP * (cols - 1)) / cols
    ch = (bottom - y - GAP * (rows - 1)) / rows
    for i, (quote, who, where) in enumerate(qs):
        r, c = divmod(i, cols)
        x, yy = T.ML + c * (cw + GAP), y + r * (ch + GAP)
        T.rect(sl, x, yy, cw, ch, fill=T.PARCH)
        T.rect(sl, x, yy, 0.06, ch, fill=T.CRIMSON)
        att = 0.58
        T.fitted(sl, x + 0.3, yy + 0.16, cw - 0.55, ch - att - 0.3,
                 lambda tf, z, q=quote: T.para(tf, "\u201c" + q + "\u201d", size=z, color=T.INK, italic=True,
                                               font="Georgia", first=True, space_after=0, line=1.2), 17, 10)

        def who_where(tf: Any, z: float, who: str = who, where: str = where) -> None:
            T.para(tf, "\u2014 " + who, size=z, color=T.CRIMSON_D, bold=True, first=True, space_after=0)
            T.para(tf, where, size=z - 1.5, color=T.SLATE, space_after=0)

        T.fitted(sl, x + 0.3, yy + ch - att - 0.08, cw - 0.55, att, who_where, 12, 8.5)


def steps(s: dict[str, Any]) -> None:
    """Numbered rows: a circle, a head, and what happens at that step."""
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    rows = s["steps"]
    gap = 0.1
    rh = (bottom - y - gap * (len(rows) - 1)) / len(rows)
    d = min(0.5, rh - 0.1)
    hw = s.get("head_w", 2.6)
    for i, row in enumerate(rows):
        num, head, body = (row if len(row) == 3 else (str(i + 1), *row))
        ry = y + i * (rh + gap)
        T.rect(sl, T.ML + d / 2, ry, T.CW - d / 2, rh, fill=T.PARCH)
        T.numdot(sl, T.ML, ry + (rh - d) / 2, d, num)
        T.fitted(sl, T.ML + d + 0.2, ry + 0.06, hw - 0.1, rh - 0.12,
                 lambda tf, z, h=head: T.para(tf, h, size=z, color=T.CRIMSON_D, bold=True, first=True,
                                              space_after=0, line=1.1, font=s.get("head_font", "Calibri")),
                 s.get("head_size", 18), 9)
        T.fitted(sl, T.ML + d + 0.2 + hw, ry + 0.06, T.CW - d - hw - 0.4, rh - 0.12,
                 lambda tf, z, b=body: T.para(tf, b, size=z, color=T.INK, first=True, space_after=0, line=1.15),
                 s.get("size", 18), 9)


STYLES = {
    # fill, text colour, outline
    "box": ("PARCH", "INK", "RULE"),
    "accent": ("CRIMSON", "WHITE", None),
    "dark": ("CRIMSON_D", "WHITE", None),
    "navy": ("NAVY", "WHITE", None),
    "soft": ("PINK_L", "INK", None),
    "white": ("WHITE", "INK", "RULE"),
    "ok": ("WHITE", "INK", "OK"),
}


def _c(name: Any) -> Any:
    return getattr(T, name) if isinstance(name, str) else name


def diagram(s: dict[str, Any]) -> None:
    """A box diagram on the content area. Groups are outlined regions with a label at
    the top; boxes are filled shapes with their own text; edges are straight arrows that
    leave the side facing their target. Positions are fractions of the diagram area."""
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    items_h = s.get("items_h", 0.0) if s.get("items") else 0.0
    dh = bottom - y - (items_h + GAP if items_h else 0)
    x0, w0 = T.ML, T.CW
    box: dict[str, tuple[float, float, float, float]] = {}
    for n in s.get("groups", []) + s["nodes"]:
        box[n["id"]] = (x0 + n["x"] * w0, y + n["y"] * dh, n["w"] * w0, n["h"] * dh)
    for g in s.get("groups", []):
        bx, by, bw, bh = box[g["id"]]
        T.rect(sl, bx, by, bw, bh, fill=_c(g.get("fill")) if g.get("fill") else None,
               line=_c(g.get("line", "CRIMSON")), lw=1.25)
        tf = T.txt(sl, bx + 0.12, by + 0.06, bw - 0.24, 0.26, align=g.get("align", PP_ALIGN.LEFT))
        T.para(tf, g["label"], size=g.get("size", 11), color=_c(g.get("color", "CRIMSON_D")), bold=True,
               first=True, space_after=0)
    for e in s.get("edges", []):
        ax, ay, aw, ah = box[e[0]]
        bx, by, bw, bh = box[e[1]]
        gap = 0.04
        xlo, xhi = max(ax, bx), min(ax + aw, bx + bw)
        ylo, yhi = max(ay, by), min(ay + ah, by + bh)
        if xhi - xlo > 0.15:
            mid = (xlo + xhi) / 2
            down = by + bh / 2 > ay + ah / 2
            p1 = (mid, (ay + ah + gap) if down else (ay - gap))
            p2 = (mid, (by - gap) if down else (by + bh + gap))
        elif yhi - ylo > 0.15:
            right = bx + bw / 2 > ax + aw / 2
            mid = (ylo + yhi) / 2
            p1 = ((ax + aw + gap) if right else (ax - gap), mid)
            p2 = ((bx - gap) if right else (bx + bw + gap), mid)
        else:
            raise T.DoesNotFit(f"edge {e[0]} -> {e[1]} shares neither a row nor a column")
        both = len(e) > 3 and e[3] == "both"
        T.arrow(sl, p1[0], p1[1], p2[0], p2[1], T.CRIMSON if both else T.SLATE, 1.6)
        if both:
            T.arrow(sl, p2[0], p2[1], p1[0], p1[1], T.CRIMSON, 1.6)
        if len(e) > 2 and e[2]:
            label = e[2]
            lw = min(2.2, len(label) * 7.5 * 0.56 / 72 + 0.12)
            if p1[0] == p2[0]:
                lx, ly = p1[0] + 0.07, (p1[1] + p2[1]) / 2 - 0.09
            else:
                lx, ly = (p1[0] + p2[0]) / 2 - lw / 2, p1[1] - 0.22
            tf = T.txt(sl, lx, ly, lw, 0.17, align=PP_ALIGN.LEFT if p1[0] == p2[0] else PP_ALIGN.CENTER)
            T.para(tf, label, size=7.5, color=T.SLATE, italic=True, space_after=0, first=True)
    for n in s["nodes"]:
        bx, by, bw, bh = box[n["id"]]
        fill, color, line = STYLES[n.get("style", "box")]
        T.boxed(sl, bx, by, bw, bh, n["text"], fill=_c(fill), color=_c(color), line=_c(line) if line else None,
                start=n.get("size", 15), sub=n.get("sub", ""), bold=n.get("bold", True))
    if s.get("items"):
        top = bottom - items_h
        T.fitted(sl, T.ML, top, T.CW, items_h, lambda tf, size: _items(tf, s["items"], size),
                 s.get("size", 17), 9)


def mono(s: dict[str, Any]) -> None:
    """A step-by-step exchange in monospace (1. Client → ... with ├─ and └─), under a band
    naming the two parties; optionally a column of points beside it."""
    sl, y = T.content(s["title"], s.get("kicker"))
    y = _intro(sl, y, s.get("intro"))
    bottom = _note(sl, s.get("note"))
    pw = T.CW * s.get("left_w", 0.62) if s.get("items") else T.CW
    T.boxed(sl, T.ML, y, pw, 0.4, s["band"], fill=T.CRIMSON, color=T.WHITE, start=12.5,
            shape=MSO_SHAPE.RECTANGLE)
    T.panel(sl, T.ML, y + 0.5, pw, bottom - y - 0.5, s["lines"], s.get("mono_size", 16))
    if s.get("items"):
        x = T.ML + pw + 0.35
        T.fitted(sl, x, y, T.CW - pw - 0.35, bottom - y, lambda tf, size: _items(tf, s["items"], size),
                 s.get("size", 18), 9)


def thanks(s: dict[str, Any]) -> None:
    T._state["n"] += 1
    sl = T.blank()
    T.rect(sl, 0, 0, SW, SH, fill=T.CRIMSON)
    T.rect(sl, 0, 0, 0.22, SH, fill=T.CRIMSON_D)
    T.mark(sl, (SW - 1.0) / 2, 0.9, 1.0, T.WHITE, 2.4)
    tf = T.txt(sl, T.ML, 2.25, T.CW, 1.0, align=PP_ALIGN.CENTER)
    T.para(tf, s["title"], size=48, color=T.WHITE, font="Georgia", first=True, space_after=0)
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    T.rect(sl, (SW - 1.6) / 2, 3.45, 1.6, 0.035, fill=T.PINK)
    tf = T.txt(sl, T.ML, 3.7, T.CW, 2.4, align=PP_ALIGN.CENTER)
    for i, (line, size, color, bold) in enumerate(s["lines"]):
        p = T.para(tf, line, size=size, color=_c(color), bold=bold, first=i == 0, space_after=6)
        p.alignment = PP_ALIGN.CENTER
    T.footer(sl, T.PINK)


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
        s.get("size", 20),
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
        start=s.get("size", 16.5),
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
    if s.get("items"):
        below = s.get("items_h", 1.6)
        T.fitted(sl, T.ML, bottom - below, T.CW, below, lambda tf, size: _items(tf, s["items"], size),
                 s.get("size", 18), 9)
        bottom = bottom - below - GAP
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
            sl, s["rows"], T.ML, y, T.CW, bottom - y, s.get("col_w"), start=s.get("size", 16),
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
            s.get("size", 19),
            9.5,
        )


def _column(sl: Any, x: float, y: float, w: float, h: float, col: dict[str, Any]) -> None:
    T.rect(sl, x, y, w, 0.42, fill=T.PARCH)
    T.rect(sl, x, y, 0.045, 0.42, fill=T.CRIMSON)
    tf = T.txt(sl, x + 0.18, y + 0.08, w - 0.3, 0.3)
    T.para(tf, col["head"], size=13, color=T.CRIMSON_D, bold=True, first=True, space_after=0)
    top = y + 0.42 + 0.14
    if col.get("lines"):
        T.panel(sl, x, top, w, y + h - top, col["lines"], col.get("size", 15))
    elif col.get("rows"):
        T.fitted_table(
            sl, col["rows"], x, top, w, y + h - top, col.get("col_w"), start=col.get("size", 16)
        )
    else:
        T.fitted(
            sl,
            x,
            top,
            w,
            y + h - top,
            lambda tf, size: _items(tf, col["items"], size),
            col.get("size", 19),
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
            s.get("size", 18),
            9,
        )
    elif s.get("rows"):
        T.fitted_table(
            sl, s["rows"], T.ML, top, T.CW, bottom - top, s.get("col_w"), start=s.get("size", 16)
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
    "tldr": tldr,
    "principles": principles,
    "quotes": quotes,
    "steps": steps,
    "diagram": diagram,
    "mono": mono,
    "thanks": thanks,
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


UNSOURCED = ("title", "divider", "thanks")


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
