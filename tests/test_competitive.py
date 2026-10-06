"""
The comparison page (/comparison) is rendered from sajha/web/competitive.py. These tests
hold that data honest:

  * every competitor cell has a verdict, every verdict but "Unknown" a source URL and an
    as-of date, and no date is in the future or older than the page's AS_OF;
  * SAJHA's own column names the code behind each claim, and the claims that map to code
    are checked against it: the protocol versions, the transports, the conformance
    workflow, OAuth, tasks, MCP Apps, the LLM routes and the tool count;
  * SAJHA's notes carry no hand-written numbers (they are filled from the registries);
  * the page renders signed out, with the legend, the date and every source.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import datetime
import os
import re

import pytest

from sajha.web import competitive as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _date(s):
    return datetime.date.fromisoformat(s)


# ── The data ─────────────────────────────────────────────────────────────────

def test_as_of_is_a_real_date_not_in_the_future():
    assert _date(C.AS_OF) <= datetime.date.today()


def test_dimension_ids_are_unique():
    assert len(C.DIMENSION_IDS) == len(set(C.DIMENSION_IDS))


def test_there_are_competitors_and_their_ids_are_unique():
    ids = [c['id'] for c in C.COMPETITORS]
    assert len(ids) >= 6 and len(ids) == len(set(ids))


@pytest.mark.parametrize('comp', C.COMPETITORS, ids=lambda c: c['id'])
def test_every_competitor_cell_has_a_verdict_and_non_unknown_verdicts_a_source(comp):
    for key in ('name', 'vendor', 'kind', 'homepage', 'licence', 'summary', 'best_for'):
        assert comp.get(key), (comp['id'], key)
    assert comp['homepage'].startswith('https://')
    assert set(comp['cells']) == set(C.DIMENSION_IDS), (
        comp['id'], sorted(set(C.DIMENSION_IDS) ^ set(comp['cells'])))
    for dim, cell in comp['cells'].items():
        where = f"{comp['id']}.{dim}"
        assert cell['verdict'] in C.VERDICTS, where
        assert cell['note'].strip(), where
        assert '|' not in cell['note'] and len(cell['note']) <= 140, where
        if cell['verdict'] != 'Unknown':
            assert cell['url'].startswith('https://'), f'{where}: a verdict needs a source'
            assert _date(cell['as_of']) <= _date(C.AS_OF), where


@pytest.mark.parametrize('dim', C.DIMENSION_IDS)
def test_every_sajha_cell_is_backed_by_code_that_exists(dim):
    cell = C.SAJHA['cells'][dim]
    assert cell['verdict'] in C.VERDICTS and cell['verdict'] != 'Unknown', dim
    if cell['verdict'] in ('Yes', 'Partial'):
        assert cell['code'], f'{dim}: a SAJHA "Yes" or "Partial" must name the code behind it'
    for path in cell['code']:
        assert os.path.exists(os.path.join(ROOT, path)), f'{dim}: {path} does not exist'


def test_sajha_notes_carry_no_hand_written_counts():
    for dim, cell in C.SAJHA['cells'].items():
        assert not re.search(r'\b\d{2,}\b(?![-:])', re.sub(r'\d{4}-\d{2}-\d{2}|RFC \d+|S256', '', cell['note'])), (
            f'{dim}: a number in a SAJHA note rots; use {{tools}}, {{groups}}, {{modern}} or {{handshake}}')


def test_sajha_guides_exist():
    from sajha.web.guides import guide_index
    idx = guide_index(fresh=True)
    for dim, cell in C.SAJHA['cells'].items():
        if cell['guide']:
            assert cell['guide'] in idx, (dim, cell['guide'])


def test_sources_are_numbered_once_each():
    src = C.sources()
    urls = [s['url'] for s in src]
    assert len(urls) == len(set(urls))
    assert [s['n'] for s in src] == list(range(1, len(src) + 1))
    cited = {comp['cells'][d]['url'] for comp in C.COMPETITORS for d in C.DIMENSION_IDS} - {''}
    assert set(urls) == cited


def test_the_short_version_agrees_with_the_cells():
    """The summary names who else serves both eras and runs the suite, and who is stronger
    where; each such name must be borne out by its column."""
    by = {c['id']: c['cells'] for c in C.COMPETITORS}
    both_and_suite = {cid for cid, cells in by.items()
                      if all(cells[d]['verdict'] == 'Yes' for d in ('spec_2026', 'spec_2025', 'conformance_ci'))}
    assert both_and_suite == {'fastmcp', 'cloudflare'}
    for cid in ('contextforge', 'docker', 'msgateway', 'kong', 'cloudflare'):
        assert by[cid]['federation']['verdict'] in ('Yes', 'Partial'), cid
    for cid in ('docker', 'msgateway'):
        assert by[cid]['isolation']['verdict'] == 'Yes', cid
    for cid in ('composio', 'zapier', 'smithery'):
        assert by[cid]['integrations']['verdict'] == 'Yes' and by[cid]['managed']['verdict'] == 'Yes', cid
    for cid in ('contextforge', 'docker', 'kong'):
        assert by[cid]['observability']['verdict'] == 'Yes', cid
    for dim in ('managed', 'open_source'):
        assert C.SAJHA['cells'][dim]['verdict'] == 'No', dim
    # User code is sandboxed (sajha/sandbox), but tool servers are not each in a container
    assert C.SAJHA['cells']['isolation']['verdict'] == 'Partial'
    if C.SAJHA['cells']['federation']['verdict'] != 'No':
        assert 'does neither' not in ' '.join(C.SHORT_VERSION), 'SHORT_VERSION still says SAJHA cannot federate'


# ── SAJHA's claims, checked against the code ────────────────────────────────

def test_spec_versions_match_the_mcp_handlers():
    from sajha.core.mcp_modern import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS
    assert '2026-07-28' in MODERN_PROTOCOL_VERSIONS and C.SAJHA['cells']['spec_2026']['verdict'] == 'Yes'
    assert '2025-11-25' in HANDSHAKE_PROTOCOL_VERSIONS and C.SAJHA['cells']['spec_2025']['verdict'] == 'Yes'
    live = C._live()
    assert live['modern'] in C.sajha_cell('spec_2026', live)['note']
    assert live['handshake'] in C.sajha_cell('spec_2025', live)['note']


def test_conformance_runs_in_ci_for_both_eras():
    wf = open(os.path.join(ROOT, '.github/workflows/mcp-conformance.yml'), encoding='utf-8').read()
    assert 'conformance' in wf and '2026-07-28' in wf and '2025-11-25' in wf


def test_claimed_routes_exist(web):
    c, _ = web
    paths = set()

    def walk(routes):
        for r in routes:
            if hasattr(r, 'original_router'):
                walk(r.original_router.routes)
            else:
                paths.add(getattr(r, 'path', None))
    walk(c.app.routes)
    for p in ('/mcp', '/mcp/sse', '/mcp/ws', '/api/ai/ask', '/ask'):
        assert p in paths, p
    assert C.SAJHA['cells']['remote_transports']['verdict'] == 'Yes'
    # stdio is not an HTTP route: it is sajha/cli/stdio.py (run_server.py --stdio)
    assert C.SAJHA['cells']['stdio']['verdict'] == 'Yes'
    assert os.path.isfile(os.path.join(ROOT, 'sajha/cli/stdio.py'))
    # Federation (sajha/federation/) was being built when this page was written: once its
    # routes are served, the "No" in SAJHA's federation cell (and SHORT_VERSION) is stale.
    if any(p and p.startswith('/api/federation') for p in paths):
        assert C.SAJHA['cells']['federation']['verdict'] != 'No', (
            'federation routes exist: update SAJHA federation cell and SHORT_VERSION in sajha/web/competitive.py')


def test_claimed_features_are_in_the_code():
    from sajha.ai.llm.mock import MockProvider          # noqa: F401  (mock provider)
    from sajha.ai.llm.providers.ollama import OllamaProvider  # noqa: F401
    from sajha.auth.oauth import authorization_server, resource_server  # noqa: F401
    from sajha.core import mcp_apps, mcp_tasks           # noqa: F401
    src = open(os.path.join(ROOT, 'sajha/core/mcp_tasks.py'), encoding='utf-8').read()
    assert 'io.modelcontextprotocol/tasks' in src


def test_no_open_source_licence_is_claimed():
    """SAJHA is "All rights reserved"; the page must not say otherwise until that changes."""
    has_licence = any(os.path.exists(os.path.join(ROOT, n)) for n in ('LICENSE', 'LICENSE.md', 'LICENSE.txt'))
    assert has_licence or C.SAJHA['cells']['open_source']['verdict'] == 'No'


def test_tool_count_comes_from_the_registry(web):
    c, _ = web
    from sajha.web.help_catalog import live_tool_groups
    live = live_tool_groups()
    assert '{tools}' in C.SAJHA['cells']['builtin_tools']['note']
    t = c.get('/comparison').text
    assert f"{live['total_tools']} tools in {live['total_groups']} groups" in t


# ── The page ────────────────────────────────────────────────────────────────

def test_page_renders_signed_out(web):
    c, _ = web
    c.cookies.clear()
    r = c.get('/comparison', follow_redirects=False)
    assert r.status_code == 200
    t = r.text
    assert 'url_for(' not in t and 'Traceback' not in t
    assert C.AS_OF in t
    for v in C.VERDICTS:
        assert f'>{v}</span>' in t, v                     # the legend names every verdict
    for comp in C.COMPETITORS:
        assert comp['name'] in t
    for s in C.sources():
        assert f'id="src-{s["n"]}"' in t and s['url'] in t
    assert 'class="cmp-scroll"' in t                     # the table scrolls in its own box


def test_page_is_in_the_help_menu_and_catalog(web):
    c, admin = web
    from sajha.web.help_catalog import CATALOG
    assert any(t.get('endpoint') == 'comparison_page' for cat in CATALOG for t in cat['topics'])
    assert 'href="/comparison"' in c.get('/dashboard', cookies=admin).text
    assert 'href="/comparison"' in c.get('/about').text
