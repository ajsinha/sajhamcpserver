# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Ask SAJHA shows a figure's lineage (docs/architecture/Quantitative Planners.md §2.1, Roadmap L60):
the page loads static/js/ask_lineage.js; POST /api/ai/ask streams a ``workspace`` event (the answer's
figures and their lineage) on a mock-provider calc_graph run and returns ``figures`` in a JSON reply;
and in a browser (Playwright, skipped when Chromium is missing) each figure is a keyboard-reachable
button with an accessible name, aria-expanded and aria-controls, whose panel shows the operation and
its inputs down to the tool call (tool, arguments, JSON path, as-of, unit and who declared it), and
Escape closes it. The script builds the page with textContent only (no innerHTML from data)."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / 'sajha' / 'web' / 'static' / 'js'
CAGR_Q = 'What is the CAGR of revenue that grew from 120 to 180 over 5 years?'


def _events(text):
    out = []
    for block in text.split('\n\n'):
        data = [ln[5:].lstrip() for ln in block.split('\n') if ln.startswith('data:')]
        if data:
            out.append(json.loads('\n'.join(data)))
    return out


def test_the_ask_page_loads_the_lineage_script_before_ask_js(web):
    c, admin = web
    c.cookies.clear()
    t = c.get('/ask', cookies=admin).text
    assert 'js/ask_lineage.js' in t and t.index('js/ask_lineage.js') < t.index('js/ask.js')
    js = c.get('/static/js/ask_lineage.js')
    assert js.status_code == 200 and 'SajhaLineage' in js.text


def test_the_scripts_never_build_markup_from_data():
    src = (JS / 'ask_lineage.js').read_text()
    assert 'innerHTML' not in src and 'insertAdjacentHTML' not in src and 'outerHTML' not in src
    ask = (JS / 'ask.js').read_text()
    assert 'innerHTML' not in ask
    assert "case 'workspace'" in ask and 'SajhaLineage.render' in ask and 'SajhaLineage.fromWorkspace' in ask


def _ask(c, admin, stream):
    c.cookies.clear()
    headers = {'Accept': 'text/event-stream'} if stream else {}
    return c.post('/api/ai/ask', json={'question': CAGR_Q, 'planner': 'calc_graph', 'model': 'mock/mock-planner',
                                       'conversation_id': 'new'}, cookies=admin, headers=headers)


def test_the_ask_stream_sends_the_answer_figures_and_their_lineage(web):
    c, admin = web
    r = _ask(c, admin, stream=True)
    assert r.status_code == 200, r.text
    evs = _events(r.text)
    kinds = [e['type'] for e in evs]
    assert 'workspace' in kinds and kinds.index('answer') < kinds.index('workspace') < kinds.index('done')
    ws = evs[kinds.index('workspace')]
    answer = evs[kinds.index('answer')]['text']
    fig = ws['figures'][0]
    assert answer[fig['start']:fig['end']] == fig['text'] and fig['text'].startswith('8.447')
    q = ws['quantities'][fig['quantity']]
    assert q['op'] == 'cagr' and q['unit'] == 'percent' and set(q['inputs']) <= set(ws['quantities'])
    done = evs[-1]['result']
    assert done['figures'] == ws['figures'] and done['workspace']['quantities']


def test_a_json_reply_carries_the_figures_too(web):
    c, admin = web
    r = _ask(c, admin, stream=False)
    assert r.status_code == 200
    j = r.json()
    assert j['figures'] and j['figures'][0]['quantity'] in {q['name'] for q in j['workspace']['quantities']}


# ── the page behaviour, in a browser ─────────────────────────────

FIGURES = [{'start': 21, 'end': 26, 'text': '2.96%', 'quantity': 'inflation'}]
QUANTITIES = {
    'inflation': {'value': 2.9649, 'cells': 1, 'unit': 'percent', 'as_of': '2026-09',
                  'source': {'kind': 'operation', 'op': 'pct_change'}, 'op': 'pct_change', 'args': {},
                  'inputs': ['cpi_then', 'cpi_now']},
    'cpi_now': {'value': 319.5, 'cells': 1, 'unit': 'index', 'as_of': '2026-09',
                'source': {'kind': 'tool', 'call_id': 'compute_ab12', 'tool': 'fred_cpi', 'version': '',
                           'arguments': {'limit': 13}, 'path': '$.data.observations[0].value',
                           'unit_from': 'schema'}},
    'cpi_then': {'value': 310.3, 'cells': 1, 'unit': 'index', 'as_of': None,
                 'source': {'kind': 'tool', 'call_id': 'compute_ab12', 'tool': 'fred_cpi', 'version': '',
                            'arguments': {'limit': 13}, 'path': '$.data.observations[12].value',
                            'unit_from': 'declared'}}}
ANSWER = 'Consumer prices rose 2.96% over the twelve months <b>bold</b>.'

HARNESS = """
window.__open = null;
window.__draw = function () {
  var c = document.getElementById('c'); c.textContent = '';
  SajhaLineage.render(c, %(answer)s, %(figures)s, %(quantities)s, { open: window.__open }, function (idx, from) {
    window.__open = idx; window.__draw();
    var b = c.querySelector('.ask-fig[data-fig="' + (idx != null ? idx : from) + '"]'); if (b) b.focus();
  });
};
window.__draw();
"""


@pytest.fixture(scope='module')
def page():
    sync = pytest.importorskip('playwright.sync_api')
    try:
        pw = sync.sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as exc:  # noqa: BLE001 — no browser installed
        pytest.skip(f'Chromium unavailable: {exc.__class__.__name__}')
    pg = browser.new_page()
    pg.set_content('<html lang="en"><body><article class="ask-turn" id="t1"><div id="c"></div></article>'
                   '<button id="before">before</button></body></html>')
    pg.add_script_tag(path=str(JS / 'i18n.js'))
    pg.add_script_tag(path=str(JS / 'ask_lineage.js'))
    pg.evaluate(HARNESS % {'answer': json.dumps(ANSWER), 'figures': json.dumps(FIGURES),
                           'quantities': json.dumps(QUANTITIES)})
    yield pg
    browser.close()
    pw.stop()


def test_figures_are_buttons_with_accessible_names(page):
    btn = page.locator('.ask-fig')
    assert btn.count() == 1 and btn.inner_text() == '2.96%'
    assert btn.evaluate('b => b.tagName') == 'BUTTON' and btn.get_attribute('type') == 'button'
    assert btn.get_attribute('aria-label') == '2.96%: show how it was computed'
    assert btn.get_attribute('aria-expanded') == 'false' and btn.get_attribute('aria-controls') == 't1-lineage'
    assert page.locator('#t1-lineage').is_hidden()
    # the answer's text stays text: markup in it is never parsed
    assert page.locator('#c b').count() == 0 and '<b>bold</b>' in page.locator('.ask-answer-text').inner_text()


def test_the_keyboard_opens_the_lineage_down_to_the_tool_call_and_escape_closes_it(page):
    page.focus('#before')
    page.keyboard.press('Shift+Tab')            # the figure is in the tab order, just before the next button
    assert page.evaluate('document.activeElement.className') == 'ask-fig'
    page.keyboard.press('Enter')
    panel = page.locator('#t1-lineage')
    assert panel.is_visible() and panel.get_attribute('role') == 'region'
    assert panel.get_attribute('aria-label') == 'How 2.96% was computed'
    assert page.locator('.ask-fig').get_attribute('aria-expanded') == 'true'
    assert page.evaluate('document.activeElement.className') == 'ask-fig is-open'
    text = panel.inner_text()
    for needle in ('pct_change', 'cpi_then', 'cpi_now', 'fred_cpi', 'call compute_ab12', '$.data.observations[0].value',
                   '$.data.observations[12].value', '{"limit":13}', '2026-09', 'not stated',
                   'declared by the tool (its output schema)', 'declared by the model', 'index'):
        assert needle in text, needle
    assert panel.locator('ul ul').count() >= 1            # the inputs are nested under the operation
    page.locator('.ask-lineage-close').focus()
    page.keyboard.press('Escape')
    assert page.locator('#t1-lineage').is_hidden()
    assert page.evaluate('document.activeElement.className') == 'ask-fig'
    assert page.locator('.ask-fig').get_attribute('aria-expanded') == 'false'


def test_offsets_are_code_points_and_bad_figures_are_ignored(page):
    segs = page.evaluate("""() => SajhaLineage.segments('📈 up 4.5% and 45 bp', [
        {start: 5, end: 9, text: '4.5%', quantity: 'a'}, {start: 14, end: 19, text: '45 bp', quantity: 'b'},
        {start: 7, end: 11, text: 'x', quantity: 'c'}, {start: 30, end: 40, quantity: 'd'}])""")
    marked = [s['text'] for s in segs if s.get('fig')]
    assert marked == ['4.5%', '45 bp'] and ''.join(s['text'] for s in segs) == '📈 up 4.5% and 45 bp'


def test_quantities_from_a_run_record_workspace(page):
    out = page.evaluate("""() => SajhaLineage.fromWorkspace({quantities: [
        {name: 'g', value: 8.4, unit: 'percent', source: {kind: 'operation'}, lineage: {op: 'cagr', inputs: ['s', 'e', 7], args: {}}},
        {name: 's', value: [1, 2, 3, 4], unit: 'USD', source: {kind: 'constant'}},
        {name: 'e', value: 180, unit: 'USD', source: {kind: 'constant'}},
        {name: 'other', value: 1, unit: 'unitless', source: {kind: 'constant'}}]}, ['g'], 2)""")
    assert set(out) == {'g', 's', 'e'} and out['s']['value'] == [1, 2] and out['s']['cells'] == 4
    assert out['g']['inputs'] == ['s', 'e', {'value': 7}]
    tree = page.evaluate("""() => { var u = SajhaLineage.tree('missing', {}); return u.textContent; }""")
    assert re.search(r'lineage of missing is not available', tree)
