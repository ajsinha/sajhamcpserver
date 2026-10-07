"""
Build the deck.

    python tools/deck/build.py                 # into docs/publications/
    python tools/deck/audit.py docs/publications/SAJHA-MCP-Server.pptx

The deck is a list of slide specs across the part modules; ``layouts`` draws them with
the ``theme``, and ``evidence`` derives every number on them while the deck is built.
The document properties are set explicitly: python-pptx's default template carries a
comment naming the library, and a deck's metadata should say who wrote it and nothing
else.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parents[1]))

import layouts  # noqa: E402
import sajha_deck  # noqa: E402
import theme  # noqa: E402

DOCS = HERE.parents[1] / "docs" / "publications"
NAME = "SAJHA-MCP-Server"
AUTHOR = "Ashutosh Sinha"


def build(out_dir: Path = DOCS) -> tuple[Path, int]:
    prs = theme.new_deck(sajha_deck.CHAPTER)
    layouts.render(sajha_deck.slides())
    props = prs.core_properties
    props.title = sajha_deck.TITLE
    props.subject = sajha_deck.SUBJECT
    props.author = AUTHOR
    props.last_modified_by = AUTHOR
    props.comments = "Copyright All rights Reserved 2025-2030, Ashutosh Sinha."
    props.keywords = "SAJHA; MCP; Model Context Protocol; tools; governance"
    props.category = ""
    props.revision = 1
    stamp = dt.datetime(2026, 10, 6, 12, 0, 0)
    props.created = stamp
    props.modified = stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{NAME}.pptx"
    prs.save(str(out))
    return out, len(prs.slides)


def main() -> int:
    out, n = build()
    print(f"{n:3d} slides -> {out.relative_to(HERE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
