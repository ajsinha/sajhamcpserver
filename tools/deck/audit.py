"""
Geometry audit for the generated decks.

    python tools/deck/audit.py docs/publications/SAJHA-One-Governed-Catalog-of-Tools.pptx

It re-derives the geometry of every shape on every slide and reports:

* a shape outside the slide;
* a table taller than its frame (PowerPoint treats a row height as a minimum
  and grows the row, so the frame's declared height is a floor);
* an opaque shape drawn over something drawn earlier, which does not crowd the
  reader but deletes content from the page;
* anything printed over a table;
* text that escapes a visible container (a filled or outlined shape), or a card
  its unfilled textbox sits inside;
* content crossing the footer rule or leaving the slide;
* a free textbox whose overflow lands on another shape.

A plain textbox overflowing into empty space is not reported: invisible
overflow is not a defect, and an audit that cries wolf is an audit somebody
stops reading. It must print ``no geometry issues detected`` before a deck
ships; ``tests/test_deck_geometry.py`` makes that a test.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx import Presentation  # noqa: E402

from metrics import EMU, FOOTER_Y, SH, SW, text_extent  # noqa: E402

Box = tuple[Any, float, float, float, float]
TOL = 0.06


def is_container(sh: Any) -> bool:
    """A visible border or fill: overflow past it is visible, so it is a defect."""
    for fill in (lambda: sh.fill, lambda: sh.line.fill):
        try:
            kind = fill().type
        except Exception:
            continue
        if kind is not None and kind != 5:  # 5 == background / none
            return True
    return False


def is_opaque(sh: Any) -> bool:
    try:
        return bool(sh.fill.type == 1)  # 1 == solid
    except Exception:
        return False


def table_height(sh: Any) -> float | None:
    """A table's real height, summed from its rows."""
    if not getattr(sh, "has_table", False):
        return None
    return sum((row.height or 0) / EMU for row in sh.table.rows) or None


def has_text(sh: Any) -> bool:
    return bool(getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip())


def covers(a: Box, b: Box) -> bool:
    """Whether b covers most of what a actually occupies (its ink, for text)."""
    sh_a, al, at, aw, ah = a
    _, bl, bt, bw, bh = b
    if has_text(sh_a):
        ah = min(ah, text_extent(sh_a))
    if aw <= 0 or ah <= 0:
        return False
    wide = min(al + aw, bl + bw) - max(al, bl)
    tall = min(at + ah, bt + bh) - max(at, bt)
    return wide > 0 and tall > 0 and (wide * tall) / (aw * ah) > 0.30


def describe(sh: Any) -> str:
    if getattr(sh, "has_table", False):
        first = sh.table.cell(0, 0).text.strip().replace("\n", " ")[:28]
        return f"table({len(sh.table.rows)}x{len(sh.table.columns)}, {first!r})"
    if has_text(sh):
        return repr(sh.text_frame.text.strip().replace("\n", " ")[:40])
    return f"<{sh.shape_type}>"


def boxes_of(slide: Any, idx: int, issues: list[str]) -> list[Box]:
    boxes: list[Box] = []
    for sh in slide.shapes:
        if sh.left is None or sh.top is None:
            continue
        x, y = sh.left / EMU, sh.top / EMU
        w, h = (sh.width or 0) / EMU, (sh.height or 0) / EMU
        real = table_height(sh)
        if real is not None:
            if real > h + 0.02:
                issues.append(
                    f"S{idx:02d} TABLE TALLER THAN ITS FRAME rows {real:.2f} frame {h:.2f}"
                )
            h = max(h, real)
        boxes.append((sh, x, y, w, h))
        if x < -0.02 or y < -0.02 or x + w > SW + 0.02 or y + h > SH + 0.02:
            issues.append(f"S{idx:02d} OFF-SLIDE ({x:.2f},{y:.2f}) {w:.2f}x{h:.2f}")
    return boxes


def overlap_issue(idx: int, a: Box, b: Box) -> str | None:
    """b is drawn after a: an opaque b hides a; anything over a table prints on it."""
    sh_a, al, at, aw, ah = a
    sh_b, bl, bt, bw, bh = b
    if min(aw, ah, bw, bh) < 0.2:
        return None  # accent bars and rules
    if is_opaque(sh_b) and covers(a, b) and not covers(b, a):
        return f"S{idx:02d} HIDDEN BEHIND AN OPAQUE SHAPE {describe(sh_a)} by {describe(sh_b)}"
    if getattr(sh_a, "has_table", False):
        tall = min(at + ah, bt + bh) - max(at, bt)
        wide = min(al + aw, bl + bw) - max(al, bl)
        if tall > 0.04 and wide > 0.25 * min(aw, bw):
            return f"S{idx:02d} PRINTS OVER A TABLE {describe(sh_b)} by {tall:.2f}"
    return None


def enclosing(box: Box, boxes: list[Box]) -> Box | None:
    """The smallest visible container this shape sits inside, if any."""
    sh, x, y, w, _ = box
    best: Box | None = None
    for o in boxes:
        osh, ox, oy, ow, oh = o
        if osh is sh or not is_container(osh) or ow < 0.2 or oh < 0.2:
            continue
        inside = (
            ox - 0.02 <= x and oy - 0.02 <= y and ox + ow + 0.02 >= x + w and oy + oh + 0.02 >= y
        )
        if inside and (best is None or ow * oh < best[3] * best[4]):
            best = o
    return best


def collides(box: Box, need: float, boxes: list[Box]) -> float | None:
    """Where a free textbox's overflow meets a shape below it, if it does."""
    sh, x, y, w, h = box
    for o in boxes:
        osh, ox, oy, ow, _ = o
        if osh is sh or not (is_container(osh) or has_text(osh)) or oy < y + h - 0.02:
            continue
        if min(x + w, ox + ow) - max(x, ox) < 0.25 * min(w, ow):
            continue
        if y + need > oy + 0.04:
            return oy
    return None


def text_issue(idx: int, box: Box, boxes: list[Box], has_footer: bool) -> str | None:
    sh, _, y, _, h = box
    need = text_extent(sh)
    label = sh.text_frame.text.strip().replace("\n", " ")[:54]
    if is_container(sh) and need > h + TOL:
        return f"S{idx:02d} OVERFLOWS BORDER need {need:.2f} have {h:.2f} :: {label!r}"
    host = enclosing(box, boxes)
    if host is not None and y + need > host[2] + host[4] + TOL:
        return (
            f"S{idx:02d} ESCAPES ITS CARD text to {y + need:.2f} card ends "
            f"{host[2] + host[4]:.2f} :: {label!r}"
        )
    bottom = y + max(need, h)
    if has_footer and y < FOOTER_Y - 0.02 and bottom > FOOTER_Y + 0.05:
        return f"S{idx:02d} HITS FOOTER bottom {bottom:.2f} :: {label!r}"
    if bottom > SH - 0.05:
        return f"S{idx:02d} PAST SLIDE bottom {bottom:.2f} :: {label!r}"
    if need > h + TOL:
        met = collides(box, need, boxes)
        if met is not None:
            return f"S{idx:02d} COLLIDES text to {y + need:.2f} meets {met:.2f} :: {label!r}"
    return None


def audit(path: str | Path) -> list[str]:
    issues: list[str] = []
    for idx, slide in enumerate(Presentation(str(path)).slides, 1):
        boxes = boxes_of(slide, idx, issues)
        has_footer = any(6.90 <= b[2] <= 7.00 and b[4] < 0.05 for b in boxes)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                found = overlap_issue(idx, a, b)
                if found:
                    issues.append(found)
        for box in boxes:
            if has_text(box[0]):
                found = text_issue(idx, box, boxes, has_footer)
                if found:
                    issues.append(found)
    return issues


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: audit.py DECK.pptx")
        return 2
    issues = audit(argv[1])
    if issues:
        print(f"{len(issues)} issue(s)")
        print("\n".join(issues))
        return 1
    print("no geometry issues detected")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
