"""
The in-app help is rendered from sajha/web/help_catalog.py (topics), sajha/web/guides.py
(the guides under docs/) and sajha/web/page_help.py ("About this page"). These tests hold
the three to the docs and to the router:

  * every guide under docs/ is a card, and every card's guide exists and is served;
  * every help route is a card, an alias (a 301 to its owner) or has a companion guide;
  * every link resolves, every help page renders without signing in;
  * every console page says what it is ("About this page"), and the help footer appears
    only where intended.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import re
from urllib.parse import quote

import pytest

from sajha.web.help_catalog import (ALIASES, CATALOG, COMPANION_GUIDE, REDIRECTS, category,
                                    grouped, guide_files)
from sajha.web.guides import FOLDERS, folder_of, guide_index, render_guide
from sajha.web.page_help import NON_ROUTE_KEYS, PAGE_HELP


def _get(c, url, cookies=None, **kw):
    c.cookies.clear()                       # anonymous unless cookies are passed
    return c.get(url, cookies=cookies, **kw)


def _routes(app):
    out = []

    def walk(routes):
        for r in routes:
            if hasattr(r, 'original_router'):
                walk(r.original_router.routes)
            else:
                out.append(r)
    walk(app.routes)
    return out


def _catalog_endpoints():
    return {t['endpoint'] for c in CATALOG for t in c['topics'] if t['kind'] in ('page', 'browser')}


#: Help routes that are structure, not topics: the landing page, a category page, one
#: guide page (each guide is its own card), and the old /docs viewer's redirects.
STRUCTURAL = {'help_page', 'help_category', 'help_guide', 'docs_list', 'docs_view'}


# ── The catalog covers the docs, and the docs cover the catalog ──────────────

def test_every_guide_in_docs_has_exactly_one_card():
    on_disk = set(guide_index(fresh=True))
    carded = guide_files()
    assert len(carded) == len(set(carded)), 'a guide has two cards'
    assert on_disk - set(carded) == set(), f'guides with no help card: {sorted(on_disk - set(carded))}'
    assert set(carded) - on_disk == set(), f'cards for guides that do not exist: {sorted(set(carded) - on_disk)}'


def test_guide_index_excludes_the_archive_and_readmes():
    rels = guide_index(fresh=True).values()
    assert rels and not any('/archive/' in r or r.endswith('/README.md') for r in rels)


def test_every_docs_folder_is_named_in_FOLDERS():
    folders = {folder_of(r) for r in guide_index(fresh=True).values()}
    assert folders - set(FOLDERS) == set(), f'add these folders to guides.FOLDERS: {folders - set(FOLDERS)}'


def test_every_companion_guide_exists():
    idx = guide_index()
    missing = {ep: fn for ep, fn in COMPANION_GUIDE.items() if fn not in idx}
    assert not missing, f'companion guides that do not exist: {missing}'


def test_every_topic_sits_in_exactly_one_named_group():
    for cat in CATALOG:
        titles = [t['title'] for t in cat['topics']]
        assert len(titles) == len(set(titles)), f"{cat['id']}: two topics share a title"
        if not cat.get('groups'):
            continue
        named = [n for _t, names in cat['groups'] for n in names]
        assert len(named) == len(set(named)), f"{cat['id']}: a topic is in two groups"
        assert sorted(named) == sorted(titles), (
            f"{cat['id']}: groups and topics disagree: {sorted(set(titles) ^ set(named))}")
        assert all(g != 'More' for g, _m in grouped(cat))


# ── Every help route is covered, and every link resolves ────────────────────

def test_every_help_route_is_a_card_an_alias_or_has_a_companion(web):
    c, _ = web
    help_eps = {r.name for r in _routes(c.app)
                if getattr(r, 'endpoint', None) is not None
                and r.endpoint.__module__ == 'sajha.routes.help_routes'}
    covered = _catalog_endpoints() | ALIASES | set(COMPANION_GUIDE) | STRUCTURAL
    assert help_eps, 'no help routes found'
    assert help_eps - covered == set(), f'help routes missing from the catalog: {sorted(help_eps - covered)}'


def test_every_catalog_endpoint_resolves(web):
    c, _ = web
    for ep in _catalog_endpoints():
        assert str(c.app.url_path_for(ep)).startswith('/'), ep


def test_every_catalog_page_renders(web):
    c, _ = web
    for ep in _catalog_endpoints():
        r = _get(c, str(c.app.url_path_for(ep)))
        assert r.status_code == 200, (ep, r.status_code)


@pytest.mark.parametrize('path', ['/help', '/help/guides', '/glossary', '/help/tools', '/about']
                         + [f"/help/c/{cat['id']}" for cat in CATALOG])
def test_help_pages_render_without_signing_in(web, path):
    c, _ = web
    r = _get(c, path, follow_redirects=False)
    assert r.status_code == 200, f'{path} -> {r.status_code}'
    assert 'url_for(' not in r.text and 'Traceback' not in r.text


def test_every_guide_card_serves_its_guide(web):
    c, _ = web
    broken = []
    for fn in guide_files():
        r = _get(c, '/help/guides/' + quote(fn))
        if r.status_code != 200 or len(r.text) < 4000 or 'class="guide-body"' not in r.text:
            broken.append((fn, r.status_code, len(r.text)))
    assert not broken, f'guide cards that do not serve their guide: {broken}'


@pytest.mark.parametrize('path', [
    '/help/guides/SESSION_HANDOVER.md',              # docs/archive/ is never served
    '/help/guides/README.md',
    '/help/guides/..%2F..%2FCLAUDE.md',
    '/help/guides/No Such Guide.md',
    '/help/c/no-such-section',
])
def test_what_is_not_a_guide_is_404(web, path):
    c, _ = web
    assert _get(c, path).status_code == 404


def test_the_index_is_section_tiles_with_search(web):
    c, _ = web
    t = _get(c, '/help').text
    assert 'id="helpSearch"' in t
    assert len(re.findall(r'class="cat-tile"', t)) == len(CATALOG)
    assert 'help-item' not in t                      # cards live on the section pages
    for cat in CATALOG:
        assert f'href="/help/c/{cat["id"]}"' in t
    # every topic is searchable from the index
    assert t.count('class="list-group-item list-group-item-action help-hit"') == sum(
        len(cat['topics']) for cat in CATALOG)


def test_each_section_page_shows_exactly_its_cards(web):
    c, _ = web
    for cat in CATALOG:
        page = _get(c, f"/help/c/{cat['id']}").text
        assert len(re.findall(r'class="col-md-6 col-xl-4 mb-3 help-item"', page)) == len(cat['topics']), cat['id']


# ── Superseded pages redirect to their owners ───────────────────────────────

@pytest.mark.parametrize('endpoint', sorted(REDIRECTS))
def test_superseded_help_pages_redirect(web, endpoint):
    c, _ = web
    path, target = REDIRECTS[endpoint]
    r = _get(c, path, follow_redirects=False)
    assert r.status_code == 301 and r.headers['location'] == target
    assert _get(c, target).status_code == 200


def test_superseded_templates_are_gone():
    import os
    tdir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sajha', 'web', 'templates')
    for gone in ('help/help.html', 'help/help_ai.html', 'help/help_enterprise.html',
                 'help/help_glossary.html', 'help/help_storage.html', 'help/help_tutorials.html',
                 'docs/docs_list.html', 'docs/docs_view.html'):
        assert not os.path.exists(os.path.join(tdir, gone)), gone


@pytest.mark.parametrize('path,target', [
    ('/docs', '/help/guides'),
    ('/docs/view/protocol/OAuth Guide.md', '/help/guides/OAuth%20Guide.md'),
    ('/docs/view/archive/SESSION_HANDOVER.md', '/help/guides'),
])
def test_the_old_docs_viewer_redirects(web, path, target):
    c, _ = web
    r = _get(c, path, follow_redirects=False)
    assert r.status_code == 301 and r.headers['location'] == target


# ── Rendering is safe and links point at the app ────────────────────────────

def test_guide_markdown_is_sanitised_and_links_rewritten():
    md = ('# T\n\n## Part\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n'
          '[bad](javascript:alert(1)) [oauth](../protocol/OAuth%20Guide.md#2-choose-a-mode) '
          '[gloss](../../GLOSSARY.md) [index](../README.md) [log](../../CHANGELOG.md)\n')
    body, toc = render_guide(md, 'docs/security/Security Model.md', 'https://github.com/o/r')
    assert '<script' not in body and '<img' not in body and '&lt;script&gt;' in body
    assert 'javascript:' not in body
    assert 'href="/help/guides/OAuth%20Guide.md#2-choose-a-mode"' in body
    assert 'href="/glossary"' in body and 'href="/help/guides"' in body
    assert 'href="https://github.com/o/r/blob/main/CHANGELOG.md"' in body
    assert toc and toc[0]['name'] == 'Part'


# ── "About this page" and the help footer, only where intended ──────────────

def test_page_help_keys_are_real_routes(web):
    c, _ = web
    names = {r.name for r in _routes(c.app)}
    stale = set(PAGE_HELP) - names - NON_ROUTE_KEYS
    assert not stale, f'PAGE_HELP entries for routes that do not exist: {stale}'


#: GET routes that render a page but are not console pages with "About this page".
NOT_CONSOLE = {'login_page', 'logout', 'root', 'health', 'health_liveness', 'health_readiness',
               'openapi', 'swagger_ui_html', 'swagger_ui_redirect', 'redoc_html'}
API_PREFIXES = ('/api', '/mcp', '/a2a', '/oauth', '/.well-known', '/static', '/ws', '/admin/apikeys/{key_id}/',
                '/metrics')


def test_every_console_page_has_page_help(web):
    c, _ = web
    pages = set()
    for r in _routes(c.app):
        if 'GET' not in (getattr(r, 'methods', None) or ()) or getattr(r, 'endpoint', None) is None:
            continue
        if r.path.startswith(API_PREFIXES) and r.name != 'apikey_view':
            continue
        if r.endpoint.__module__ == 'sajha.routes.help_routes' or r.name in NOT_CONSOLE:
            continue
        pages.add(r.name)
    missing = pages - set(PAGE_HELP)
    assert not missing, f'console pages with no "About this page" entry in page_help.PAGE_HELP: {sorted(missing)}'


@pytest.mark.parametrize('path', ['/dashboard', '/tools', '/prompts', '/admin/users', '/admin/users/create',
                                  '/admin/apikeys', '/monitoring/tools', '/studio', '/studio/rest',
                                  '/composite/builder', '/ai/settings', '/admin/async-tasks', '/reports'])
def test_console_pages_say_what_they_are(web, path):
    c, admin = web
    r = _get(c, path, cookies=admin)
    assert r.status_code == 200
    assert 'class="page-help"' in r.text and 'class="ph-tile"' in r.text
    assert 'Full reference:' in r.text
    assert 'Page Glossary' not in r.text


def test_footer_only_where_intended(web):
    c, admin = web
    # help pages with an owning guide link to it
    for path in ('/help/tools', '/about'):
        assert 'Full reference:' in _get(c, path).text, path
    # the landing page of help, the glossary and a guide are their own reference
    for path in ('/help', '/glossary', '/help/guides/Quick%20Start.md'):
        assert 'Full reference:' not in _get(c, path).text, path
    # a guide shows the rest of its section
    assert 'class="help-related' in _get(c, '/help/guides/Quick%20Start.md').text
    # help pages are not console pages: no "About this page" panel
    for path in ('/help', '/glossary', '/help/guides', '/about', '/help/tools'):
        assert 'class="page-help"' not in _get(c, path, cookies=admin).text, path
    # an error page explains itself
    r = _get(c, '/tools/no_such_tool_xyz/execute', cookies=admin)
    assert 'class="page-help"' in r.text and 'HTTP status code' in r.text


def test_help_menu_points_at_the_help(web):
    c, admin = web
    t = _get(c, '/dashboard', cookies=admin).text
    for href in ('/help', '/help/guides', '/glossary', '/help/tools', '/about'):
        assert f'href="{href}"' in t, href
    for gone in ('href="/help/tutorials"', 'href="/help/glossary"', 'href="/docs"'):
        assert gone not in t, gone


#: Pre-existing dead links, outside the help: the API-key pages build URLs from these
#: legacy aliases (app.py _URL_MAP) for edit/delete/toggle/view pages, but the routes are
#: /admin/apikeys/{key_id}/view, POST .../toggle and DELETE .../delete, and there is no
#: edit page. Recorded so the test catches any NEW dead name; fix and remove.
KNOWN_DEAD_URL_FOR: set = set()


def test_every_url_for_in_a_template_resolves(web):
    """url_for() falls back to '/<name>' for a name it does not know, which renders a
    dead link instead of failing. Every name a template uses must be a route name (or
    one of app.py's legacy aliases) and must resolve to a different URL than the
    fallback would invent."""
    import glob
    import os
    c, _ = web
    from sajha.app import templates
    url_for = templates.env.globals['url_for']
    names = {r.name for r in _routes(c.app)}
    tdir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sajha', 'web', 'templates')
    bad = set()
    for path in glob.glob(os.path.join(tdir, '**', '*.html'), recursive=True):
        for name in re.findall(r"url_for\('([\w.]+)'", open(path, encoding='utf-8').read()):
            if name == 'static' or name in names or name in KNOWN_DEAD_URL_FOR:
                continue
            target = url_for(name).split('{')[0].rstrip('/') or '/'
            if not any(re.match('^' + re.sub(r'\{[^}]+\}', '[^/]+', r.path).rstrip('/') + '/?$', target)
                       or r.path.startswith(target + '/') for r in _routes(c.app) if hasattr(r, 'path')):
                bad.add((os.path.relpath(path, tdir), name, target))
    assert not bad, f'url_for names that resolve to no route: {sorted(bad)}'
