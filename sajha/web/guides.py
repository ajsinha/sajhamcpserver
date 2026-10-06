"""
Where the guides live, how a guide is found by name, and how it is rendered.

Every guide is a markdown file under ``docs/`` in a topic folder (``docs/protocol/``,
``docs/tools/market-data/`` ...). A guide's file NAME is unique across ``docs/``
(CLAUDE.md, rule 3), so the app addresses a guide by name alone:
``/help/guides/<name>.md`` keeps working whichever folder the file is in, and a guide
can move without breaking a link into it.

Excluded: every ``README.md`` (folder indexes; ``docs/README.md`` is the library page
itself) and ``docs/archive/`` (point-in-time reports, not maintained, never served).

Files are read through the storage backend (``sajha.core.storage``), as the old /docs
viewer did, so a deployment whose docs live in S3, Azure or GCS keeps working.

Markdown is rendered on the server with Python-Markdown (tables, fenced code, toc).
Raw HTML in a guide is escaped, not passed through, and only http(s), mailto, in-page
and app-relative links survive; relative ``.md`` links are rewritten to the app's
by-name URLs, and links to other repository files point at the GitHub repository.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import html as _html
import posixpath
import re
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, unquote

DOCS = 'docs'
EXCLUDED_DIRS = ('archive',)

#: Folder under docs/ -> heading in the guide library, in display order. Adding a
#: folder to docs/ means adding it here (tests/test_help_catalog.py checks).
FOLDERS: Dict[str, str] = {
    'getting-started': 'Getting started',
    'protocol': 'MCP protocol',
    'architecture': 'Architecture',
    'studio': 'MCP Studio',
    'tools/market-data': 'Tools: market data',
    'tools/central-banks': 'Tools: central banks',
    'tools/public-data': 'Tools: public data',
    'tools/filings': 'Tools: filings',
    'tools/search': 'Tools: search',
    'tools/analytics': 'Tools: analytics',
    'tools/enterprise': 'Tools: enterprise',
    'tools/prompts': 'Prompts',
    'tutorials': 'Tutorials',
    'clients': 'Clients',
    'security': 'Security',
}

GUIDE_URL = '/help/guides/'
_TTL = 30.0                     # seconds a listing is reused (cloud listings cost a call)
_lock = threading.Lock()
_index_cache: Tuple[float, Optional[Dict[str, str]]] = (0.0, None)


def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


# ── Finding guides ───────────────────────────────────────────────────────────

def guide_files() -> List[str]:
    """Storage paths of every guide ('docs/protocol/OAuth Guide.md'), sorted by folder
    then name; README.md files and docs/archive/ excluded."""
    out = []
    for rel in _storage().list_files(DOCS, '*.md'):
        rel = rel.replace('\\', '/')
        parts = rel.split('/')
        if parts[-1] == 'README.md' or len(parts) < 3:
            continue                        # folder indexes and docs/*.md at the root
        if parts[1] in EXCLUDED_DIRS:
            continue
        out.append(rel)
    return sorted(out, key=lambda r: (r.split('/')[1:-1], r.rsplit('/', 1)[-1]))


def guide_index(fresh: bool = False) -> Dict[str, str]:
    """name -> storage path. Raises if two guides share a name: names are the address."""
    global _index_cache
    now = time.monotonic()
    with _lock:
        ts, cached = _index_cache
        if cached is not None and not fresh and now - ts < _TTL:
            return cached
    seen: Dict[str, str] = {}
    for rel in guide_files():
        name = rel.rsplit('/', 1)[-1]
        if name in seen:
            raise RuntimeError(f'two guides are both named {name!r}: {seen[name]} and {rel}')
        seen[name] = rel
    with _lock:
        _index_cache = (now, seen)
    return seen


def find_guide(name: str) -> Optional[str]:
    """The storage path of the guide called ``name`` (a bare file name, or any path
    ending in one), or None."""
    return guide_index().get(posixpath.basename(unquote(name or '')))


def folder_of(rel: str) -> str:
    """'docs/tools/market-data/FRED Tool Reference Guide.md' -> 'tools/market-data'."""
    return '/'.join(rel.split('/')[1:-1])


def guide_url(name: str, anchor: str = '') -> str:
    return GUIDE_URL + quote(name) + (('#' + anchor) if anchor else '')


def title_of(text: str, name: str) -> str:
    """A guide's title: its first '# ' heading, else its file name."""
    for line in text.split('\n')[:15]:
        if line.startswith('# '):
            return line[2:].strip()
    return name[:-3] if name.endswith('.md') else name


def read_guide(name: str) -> Optional[Tuple[str, str]]:
    """(storage path, markdown text) of a guide, or None."""
    rel = find_guide(name)
    if rel is None:
        return None
    try:
        return rel, _storage().read_text(rel)
    except (FileNotFoundError, IsADirectoryError, OSError):
        return None


def library() -> List[dict]:
    """[{folder, label, guides: [{name, title, url}]}] in FOLDERS order; a folder that
    FOLDERS does not name is listed last under its own path, so a new folder can never
    make its guides vanish."""
    groups: Dict[str, List[dict]] = {}
    store = _storage()
    for name, rel in guide_index().items():
        try:
            title = title_of(store.read_text(rel), name)
        except OSError:
            title = name[:-3]
        groups.setdefault(folder_of(rel), []).append(
            {'name': name, 'title': title, 'url': guide_url(name)})
    order = list(FOLDERS) + sorted(f for f in groups if f not in FOLDERS)
    out = []
    for f in order:
        if f in groups:
            guides = groups[f]
            if f == 'tutorials':
                guides.sort(key=lambda g: g['name'])
            else:
                guides.sort(key=lambda g: g['title'].lower())
            out.append({'folder': f, 'label': FOLDERS.get(f, f), 'guides': guides})
    return out


# ── Rendering ────────────────────────────────────────────────────────────────

def _markdown(extensions):
    import markdown
    md = markdown.Markdown(extensions=extensions, extension_configs={
        'toc': {'permalink': False, 'toc_depth': '2-3'}})
    # Raw HTML is escaped rather than passed through: a guide is text, never markup
    # that runs in the console's origin (docs can come from a shared bucket).
    md.preprocessors.deregister('html_block')
    md.inlinePatterns.deregister('html')
    return md


def render_inline(text: str) -> str:
    """One line of markdown (a glossary cell) as inline HTML, raw HTML escaped."""
    try:
        out = _markdown([]).convert(text)
    except ImportError:
        return _html.escape(text)
    if out.startswith('<p>') and out.endswith('</p>'):
        out = out[3:-4]
    return _safe_links(out)


_HREF = re.compile(r'href="([^"]*)"')
_SAFE_SCHEMES = ('http://', 'https://', 'mailto:')
_SCHEME = re.compile(r'^[a-z][a-z0-9+.-]*:')


def _safe_links(html: str) -> str:
    """Drop any link whose scheme is not http(s)/mailto (javascript:, data: ...)."""
    def fix(m):
        href = _html.unescape(m.group(1)).strip()
        low = href.lower()
        if _SCHEME.match(low) and not low.startswith(_SAFE_SCHEMES):
            return 'href="#"'
        return m.group(0)
    return _HREF.sub(fix, html)


def app_links(html: str, source: str, repo_url: str = '') -> str:
    """Point a rendered guide's relative links at the app.

    In the repository a guide links to another by relative path
    (``../protocol/OAuth%20Guide.md``), which is right on GitHub and in an editor. The
    app serves every guide at /help/guides/<name>, so the name alone is the address.
    ``GLOSSARY.md`` becomes /glossary, ``docs/README.md`` the guide library, and any
    other repository file (CHANGELOG, CLAUDE.md, deployment/README.md, source files)
    a link to it in the GitHub repository. ``source`` is the guide's storage path.
    """
    index = guide_index()
    base = posixpath.dirname(source)

    def to_app(m):
        raw = _html.unescape(m.group(1))
        low = raw.lower()
        if not raw or raw.startswith('#') or raw.startswith('/') or low.startswith(_SAFE_SCHEMES):
            return m.group(0)
        if _SCHEME.match(low):
            return 'href="#"'
        path, _, anchor = raw.partition('#')
        target = posixpath.normpath(posixpath.join(base, unquote(path)))
        name = posixpath.basename(target)
        if target == 'GLOSSARY.md':
            url = '/glossary' + ('#' + anchor if anchor else '')
        elif target in ('docs/README.md', 'docs'):
            url = '/help/guides'
        elif name in index and index[name] == target:
            url = guide_url(name, anchor)
        elif target.startswith('docs/archive/'):
            url = (repo_url.rstrip('/') + '/blob/main/' + quote(target)) if repo_url else '#'
        elif repo_url and not target.startswith('..'):
            url = repo_url.rstrip('/') + '/blob/main/' + quote(target) + ('#' + anchor if anchor else '')
        else:
            url = '#'
        return 'href="' + _html.escape(url, quote=True) + '"'

    return _HREF.sub(to_app, html)


_TABLE = re.compile(r'<table>')


def render_guide(text: str, source: str, repo_url: str = '') -> Tuple[str, List[dict]]:
    """(body HTML, toc tokens) for a guide's markdown."""
    md = _markdown(['tables', 'fenced_code', 'toc', 'sane_lists'])
    # the title is shown in the page hero; drop the leading '# ' heading from the body
    lines = text.split('\n')
    for i, line in enumerate(lines[:15]):
        if line.startswith('# '):
            del lines[i]
            break
    body = md.convert('\n'.join(lines))
    body = _TABLE.sub('<div class="table-responsive guide-table"><table class="table table-sm">', body)
    body = body.replace('</table>', '</table></div>')
    body = app_links(_safe_links(body), source, repo_url)
    toc = [t for t in getattr(md, 'toc_tokens', [])]
    return body, toc
