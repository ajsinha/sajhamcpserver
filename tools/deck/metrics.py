"""
Text metrics shared by the deck builder and the geometry audit.

``python-pptx`` does not measure or wrap text, and PowerPoint shapes do not clip
overflow: text simply spills out of its box. So the builder estimates, and the
audit re-estimates. Both use the functions in this module, so the builder can
never believe a box fits that the audit will then report.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any

EMU = 914400.0
SW, SH = 13.333, 7.5
FOOTER_Y = SH - 0.55
SANS, SERIF, MONO = "Calibri", "Georgia", "Consolas"
INTRINSIC = 1.10  # line_spacing multiplies the intrinsic line box, not the point size
SAFETY = 0.94  # treat boxes as slightly narrower than they are


def est_lines(text: str, width_in: float, fs: float, bold: bool = False, font: str = SANS) -> int:
    """Greedy word-wrap simulation: the number of rendered lines."""
    text = str(text)
    if not text:
        return 1
    frac = 0.545 if font == SERIF else 0.505
    if font in (MONO, "Courier New"):
        frac = 0.620
    if bold:
        frac += 0.022
    cpl = max(4, int(width_in / (fs * frac / 72.0)))
    lines, cur = 1, 0
    for word in text.split():
        need = len(word) + (1 if cur else 0)
        if cur + need > cpl:
            lines += 1
            cur = len(word)
            while cur > cpl:
                lines += 1
                cur -= cpl
        else:
            cur += need
    return lines


def text_h(
    text: str, width_in: float, fs: float, bold: bool = False, font: str = SANS, line: float = 1.22
) -> float:
    """Rendered height in inches of one paragraph."""
    return est_lines(text, width_in, fs, bold, font) * fs * max(line, 1.15) * INTRINSIC / 72.0


def usable_width(sh: Any) -> float:
    """The width text may occupy inside a shape, its own margins removed."""
    tf = sh.text_frame
    margins = ((tf.margin_left or 0) + (tf.margin_right or 0)) / EMU
    return (sh.width or 0) / EMU - margins


def paragraph_h(p: Any, width: float) -> float:
    """Estimated height of one python-pptx paragraph, spacing included."""
    ptxt = "".join(r.text for r in p.runs)
    spacing = (
        (p.space_before.pt if p.space_before else 0) + (p.space_after.pt if p.space_after else 0)
    ) / 72.0
    if not ptxt:
        return 6 / 72.0 + spacing
    r0 = max(p.runs, key=lambda r: r.font.size.pt if r.font.size else 12)
    fs = r0.font.size.pt if r0.font.size else 12
    font = p.runs[0].font.name or SANS
    ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.22
    indent = 0.35 if p.level else 0.0
    bold = any(bool(r.font.bold) for r in p.runs) and len(p.runs) == 1
    return text_h(ptxt, max(0.4, width - indent), fs, bold, font, ls) + spacing


def text_extent(sh: Any) -> float:
    """Estimated rendered height of a shape's text, in inches."""
    width = usable_width(sh) * SAFETY
    return sum(paragraph_h(p, width) for p in sh.text_frame.paragraphs)
