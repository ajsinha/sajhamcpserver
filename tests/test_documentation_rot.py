"""
The documentation is checked against the code, mechanically.

Docs rot in a particular way: not by becoming ungrammatical, but by continuing to describe
a system that has moved. A guide citing a file that was renamed, a link to a document that
moved, a URL the server no longer serves, "MCP 2025-11-25 (latest)" a release after
2026-07-28 shipped: each still reads correctly and each is wrong. CLAUDE.md states the
rules; this file enforces the mechanical ones.

Every check was calibrated against the tree until it produced **no false positives**, and
each exclusion below is a judgement recorded rather than hidden. A checker that cries
wolf is worse than none: it trains the next person to skip the whole file.

Scope: docs/**/*.md, excluding docs/archive/ (point-in-time, not maintained) and the
CHANGELOG (history is allowed to describe the past).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import glob
import os
import re
from urllib.parse import unquote

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOCS = sorted(
    p for p in glob.glob(os.path.join(REPO, 'docs', '**', '*.md'), recursive=True)
    if os.sep + 'archive' + os.sep not in p and os.path.basename(p) != 'CHANGELOG.md')
IDS = [os.path.relpath(p, os.path.join(REPO, 'docs')) for p in DOCS]


def _read(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def _strip_code_blocks(text):
    """Fenced code is an example (output, a shell session), not a claim about the tree."""
    return re.sub(r'```.*?```', '', text, flags=re.S)


# ── 1. Relative links resolve ────────────────────────────────────────────────

_LINK = re.compile(r'\]\(([^)\s]+)\)')


@pytest.mark.parametrize('doc', DOCS, ids=IDS)
def test_relative_links_resolve(doc):
    """A relative link must resolve from the file's own folder (CLAUDE.md, rule 3)."""
    missing = []
    for target in _LINK.findall(_strip_code_blocks(_read(doc))):
        if re.match(r'^[a-z][a-z0-9+.-]*:', target) or target.startswith('#'):
            continue                                    # http(s), mailto, in-page anchor
        path = unquote(target.split('#', 1)[0])
        if not path:
            continue
        if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(doc), path))):
            missing.append(target)
    assert not missing, f'{os.path.basename(doc)} links to files that do not exist: {missing}'


# ── 2. Phrases that were true once and are not now ──────────────────────────

#: phrase -> why it is banned
STALE = {
    '2025-11-25 (latest)': '2026-07-28 is the newest protocol version SAJHA speaks',
    'fully compliant': 'compliance is stated requirement by requirement, with evidence',
    '497 tools': 'tool counts are derived (tools/list, the Tools page), never written',
}
#: SAJHA is not an OpenID Connect provider. The path may be named only to say so: on a
#: line that also says it is 404 (OAuth Guide; the 2025-11-25 report's removal row).
OIDC_PATH = '/.well-known/openid-configuration'


@pytest.mark.parametrize('doc', DOCS, ids=IDS)
def test_no_stale_claims(doc):
    text = _read(doc)
    found = [f'{p!r} ({why})' for p, why in STALE.items() if p.lower() in text.lower()]
    for line in text.splitlines():
        if OIDC_PATH in line and '404' not in line:
            found.append(f'{OIDC_PATH} presented as served: {line.strip()[:90]}')
    assert not found, f'{os.path.basename(doc)}: {found}'


# ── 3. Repository paths cited in backticks exist ────────────────────────────

#: `sajha/...`, `tests/...`, `config/...` etc. in inline code, optionally followed by
#: ::symbol or :line. Placeholders (<tool_name>, your_tool) are templates, not paths.
_CITED = re.compile(r'`((?:sajha|tests|clientsdk|config|deployment|db|scripts)/[^`\s]*)')
#: '<name>', '{name}', '*', '...' and 'your_...' stand for a name the reader chooses.
_PLACEHOLDER = re.compile(r'<[^>]+>|\{[^}]+\}|\*|\.\.\.|your_')
#: Files a guide tells the reader to CREATE (a tutorial's tool, Studio's output, an
#: example), not files it claims exist. Exact paths, each checked by hand.
WRITTEN_BY_READER = {
    'config/tools/x.json',                                   # Storage Guide: an example key
    'config/tools/get_weather_forecast.json',                # REST creator: its example output
    'sajha/tools/impl/rest_get_weather_forecast.py',
    'config/tools/text_word_count.json',                     # Tutorial 2 builds these
    'sajha/tools/impl/word_count_tool.py',
    'config/plugins/demo-plugin/plugin.json',                # Tutorial 4 builds these
    'config/plugins/demo-plugin/tools/demo_pct_change.json',
    'config/policies/50-tutorial.yaml',                      # Tutorial 20 writes this policy
    'config/tools/my_priority.json',                         # Tutorial 26 builds these
    'config/evals/my_priority.yaml',
}
#: Git-ignored files the server itself writes at run time (no template exists), so a clean
#: checkout lacks them although guides describe them.
WRITTEN_BY_SERVER = {
    'config/apikeys_db.json',                                # the database's keys, dumped every 10 minutes
}
#: Default directories the server reads but does not ship (created on first use), and
#: so anything a guide puts in them.
RUNTIME_DIRS = {
    'config/apps',          # mcp.apps.dir (sajha/core/mcp_apps.py)
    'config/scripts',       # the Script creator's scripts (sajha/studio/script_tool_generator.py)
    'config/federation',    # federation.state_path, written by the Federation admin page (sajha/federation/store.py)
}


def _cited_path(raw):
    path = re.split(r'::|:\d|[ ,;)(]', raw, maxsplit=1)[0].rstrip('.,:')
    return path


def _git_files():
    import subprocess
    try:
        out = subprocess.run(['git', 'ls-files'], cwd=REPO, capture_output=True, text=True, check=True).stdout
    except Exception:                                 # not a git checkout: fall back to the file system
        return None
    return set(out.splitlines())


_GIT_FILES = _git_files()
#: a git-ignored file an administrator creates from a tracked template, e.g. config/users.json
#: from config/users.json.example: a guide may cite it although a clean checkout lacks it
_TRACKED_EXAMPLES = {f[:-len('.example')] for f in (_GIT_FILES or ()) if f.endswith('.example')}


def _is_untracked_file(path):
    full = os.path.join(REPO, path)
    return _GIT_FILES is not None and os.path.isfile(full) and path not in _GIT_FILES


@pytest.mark.parametrize('doc', DOCS, ids=IDS)
def test_cited_repository_paths_exist(doc):
    missing = []
    for raw in _CITED.findall(_read(doc)):
        path = _cited_path(raw)
        if _PLACEHOLDER.search(path):
            continue
        if path in WRITTEN_BY_READER or any(path.rstrip('/') == d or path.startswith(d + '/') for d in RUNTIME_DIRS):
            continue
        if path.rstrip('/') in _TRACKED_EXAMPLES or path in WRITTEN_BY_SERVER:   # git-ignored by design
            continue
        full = os.path.join(REPO, path)
        if _is_untracked_file(path):                  # exists only on this machine: a clean checkout lacks it
            missing.append(path)
            continue
        if os.path.exists(full) or os.path.exists(full.rstrip('/') + '.py'):   # module path
            continue
        missing.append(path)
    assert not missing, (f'{os.path.basename(doc)} cites repository paths that do not exist: '
                         f'{sorted(set(missing))}')


# ── 4. App URLs in guides are served ────────────────────────────────────────

def _route_patterns():
    """Every registered route path, as a regex ({param} matches one segment, {p:path} any)."""
    from sajha.app import create_app
    app = create_app()
    paths = set()

    def walk(routes):
        for r in routes:
            if hasattr(r, 'original_router'):
                walk(r.original_router.routes)
            elif hasattr(r, 'path'):
                paths.add(r.path)
    walk(app.routes)
    pats = []
    for p in paths:
        rx = re.sub(r'\{[^}:]+:path\}', '.+', p)
        rx = re.sub(r'\{[^}]+\}', '[^/]+', rx)
        pats.append(re.compile('^' + rx.rstrip('/') + '/?$'))
    return paths, pats


_ROUTE_CACHE = {}


def _routes():
    if not _ROUTE_CACHE:
        _ROUTE_CACHE['v'] = _route_patterns()
    return _ROUTE_CACHE['v']


#: An app URL in inline code: `/api/...`, `GET /mcp/sse`, `/admin/async-tasks`.
_APP_URL = re.compile(r'`(?:(?:GET|POST|PUT|PATCH|DELETE|WS)\s+)?(/(?:api|admin|help|mcp|oauth|a2a|'
                      r'studio|tools|prompts|monitoring|reports|composite|ai|glossary|about|docs|'
                      r'dashboard|login|logout|health|ready|\.well-known)[^`\s]*)`')
#: Shapes that are not one concrete URL: a path with '...', '*', '<x>' or '[a|b]' is a
#: family or a template, not a route. (Query strings and fragments are dropped first.)
_NOT_A_ROUTE = re.compile(r'\.\.\.|\*|<|…|\[')
#: A URL on a line that says it is not served is documented as absent, which is correct.
_SAYS_ABSENT = re.compile(r'404|not registered|no route|not served|Removed', re.I)
#: Known, documented gaps: URLs the docs name that the server does not serve. None at
#: present (the Studio action endpoints under /admin/studio/ are registered again).
KNOWN_UNSERVED = ()


@pytest.mark.parametrize('doc', DOCS, ids=IDS)
def test_app_urls_are_registered_routes(doc):
    paths, pats = _routes()
    bad = []
    for line in _read(doc).splitlines():
        for raw in _APP_URL.findall(line):
            url = raw.split('?', 1)[0].split('#', 1)[0].rstrip('.,:;')
            if _NOT_A_ROUTE.search(url) or _SAYS_ABSENT.search(line):
                continue
            if any(url.startswith(k) for k in KNOWN_UNSERVED):
                continue
            if url in paths or any(p.match(url) for p in pats):
                continue
            # a prefix ('/admin', '/api/prompts/') names the family of routes under it
            if any(p.startswith(url.rstrip('/') + '/') for p in paths):
                continue
            bad.append(url)
    assert not bad, f'{os.path.basename(doc)} names app URLs that no route serves: {sorted(set(bad))}'


# ── 5. Every registered route is in the API Reference ───────────────────────

API_REFERENCE = os.path.join(REPO, 'docs', 'protocol', 'API Reference.md')


def _param_blind(path):
    """'/api/x/{tool_name}' and '/api/x/{tool}' are the same route: compare shapes."""
    return re.sub(r'\{[^}]+\}', '{}', path).rstrip('/') or '/'


def test_every_route_is_in_the_api_reference():
    """The API Reference says it lists every route the server registers (CLAUDE.md: it owns
    "HTTP endpoints"). A route added without a row there fails here. Paths are compared by
    shape, so a parameter may be named differently ({tool} vs {tool_name})."""
    paths, _ = _routes()
    documented = {_param_blind(p) for p in
                  re.findall(r'`(?:(?:GET|POST|PUT|PATCH|DELETE|WS)\s+)?(/[^`\s?#]*)', _read(API_REFERENCE))}
    missing = sorted(p for p in paths if _param_blind(p) not in documented)
    assert not missing, f'routes missing from docs/protocol/API Reference.md: {missing}'


# ── The checker is honest ───────────────────────────────────────────────────

def test_there_are_documents_to_check():
    assert len(DOCS) > 40, f'only {len(DOCS)} documents discovered'
    assert not any('archive' in p for p in DOCS)


def test_the_router_is_actually_being_read():
    paths, _ = _routes()
    assert len(paths) > 100 and '/help/guides/{name:path}' in paths


def test_the_exclusions_are_narrow():
    assert len(WRITTEN_BY_READER) <= 10 and len(WRITTEN_BY_SERVER) <= 2 and len(RUNTIME_DIRS) <= 3 and len(KNOWN_UNSERVED) <= 1
    assert len(STALE) >= 3
