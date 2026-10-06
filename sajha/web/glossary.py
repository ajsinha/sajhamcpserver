"""
The glossary, read from GLOSSARY.md: the single source of every definition.

The web console used to carry its own definitions: a hand-written glossary page and a
"Page Glossary" block at the foot of 25 templates. They disagreed with GLOSSARY.md
(passwords "hashed with SHA-256", roles "admin/user/readonly", monitoring "via
WebSocket"), and nobody could keep 27 copies in step. Now /glossary renders this file,
and every page's "About this page" panel looks its terms up here.

Format (CLAUDE.md, rule 4): sections are ``## N. Title`` headings; each term is one row
``| **Term** | Meaning |``, optionally ``| **Term** (*Expansion*) | ... |`` or
``| **A** / **B** | ... |``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import html as _html
import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent.parent
GLOSSARY_PATH = REPO / 'GLOSSARY.md'

_SECTION = re.compile(r'^## ((?:\d+\.\s*)?(.+?))\s*$')
# The term cell starts bold and may carry a suffix: "**Prompt** (*MCP*)", "**A** / **B**".
_ROW = re.compile(r'^\| (\*\*.+?) \| (.+) \|\s*$')

_lock = threading.Lock()
_cache: Dict[str, object] = {}


def _md_inline(text: str) -> str:
    """Render one table cell's inline markdown (code, bold, italic, links); raw HTML escaped."""
    from sajha.web.guides import render_inline
    return render_inline(text)


def plain(text: str) -> str:
    """A term cell without its markup: '**Prompt** (*MCP*)' -> 'Prompt (MCP)'."""
    return re.sub(r'\s+', ' ', re.sub(r'[`*]', '', text)).strip()


def slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', plain(text).lower()).strip('-')


def _parse(text: str) -> List[dict]:
    sections: List[dict] = []
    cur: Optional[dict] = None
    for line in text.split('\n'):
        m = _SECTION.match(line)
        if m:
            # the id keeps the number, as GitHub's anchor does ('#1-sajha-and-the-platform')
            title = m.group(2)
            cur = {'title': title, 'id': slug(m.group(1)), 'terms': []}
            sections.append(cur)
            continue
        if cur is None:
            continue
        r = _ROW.match(line)
        if r:
            name, meaning = r.group(1), r.group(2)
            cur['terms'].append({
                'name': plain(name),
                'name_html': _md_inline(name),
                'html': _md_inline(meaning),
                'id': slug(name),
                'section': cur['title'],
                'text': plain(name + ' ' + meaning).lower(),
            })
    return sections


def load_glossary(path: Optional[Path] = None) -> List[dict]:
    """``[{title, id, terms: [{name, name_html, html, id, section, text}]}]``.

    Parsed once and cached; re-read only when the file's modification time changes, so
    an edit to GLOSSARY.md shows up without a restart and costs nothing otherwise.
    """
    p = Path(path) if path else GLOSSARY_PATH
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return []
    key = str(p)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    sections = _parse(p.read_text(encoding='utf-8'))
    with _lock:
        _cache[key] = (mtime, sections)
    return sections


def term_index(path: Optional[Path] = None) -> Dict[str, dict]:
    """Lower-cased term name -> term.

    Each row is indexed by its full plain name ('Arguments (tool)', 'Enabled / Tool
    Status') and by each of its bold names alone ('Enabled', 'Tool Status') when that
    name belongs to no other row, so a page may cite either form."""
    idx: Dict[str, dict] = {}
    parts_seen: Dict[str, List[dict]] = {}
    for sec in load_glossary(path):
        for t in sec['terms']:
            idx.setdefault(t['name'].lower(), t)
    # 'A / B' rows: each name alone, with any '(qualifier)' dropped
    for sec in load_glossary(path):
        for t in sec['terms']:
            base = re.sub(r'\s*\([^)]*\)', '', t['name'])
            for part in (p.strip() for p in base.split(' / ')):
                if part:
                    parts_seen.setdefault(part.lower(), []).append(t)
    for part, owners in parts_seen.items():
        if len({id(o) for o in owners}) == 1:
            idx.setdefault(part, owners[0])
    return idx


def lookup(name: str) -> Optional[dict]:
    """The glossary row for ``name`` (case-insensitive), or None."""
    return term_index().get((name or '').strip().lower())


def escape(text: str) -> str:
    return _html.escape(text or '')
