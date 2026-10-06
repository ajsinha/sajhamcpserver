"""
Ask SAJHA (/ask): the page renders for a signed-in user with the sky's data and the example
questions, refuses anonymous callers, is wired into the menu and the dashboard, and every
example chip is answered by the default (mock) model from a real tool.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import json
import re

import pytest

from sajha.routes.ai_routes import ASK_EXAMPLES


def _get(c, url, cookies=None, **kw):
    c.cookies.clear()
    return c.get(url, cookies=cookies, **kw)


def _ask_data(html):
    m = re.search(r'<script type="application/json" id="askData">(.*?)</script>', html, re.S)
    assert m, 'askData missing'
    return json.loads(m.group(1))


def test_ask_page_renders_for_a_signed_in_user(web):
    c, admin = web
    r = _get(c, '/ask', cookies=admin)
    assert r.status_code == 200
    t = r.text
    for needle in ('id="askLog"', 'id="askInput"', 'id="askSend"', 'id="askStop"', 'id="askModel"',
                   'id="askSkyCanvas"', 'aria-live="polite"', 'js/constellation.js', 'js/ask.js'):
        assert needle in t, needle
    data = _ask_data(t)
    assert data['examples'] == ASK_EXAMPLES
    assert data['groups'] and data['total'] == sum(g[1] for g in data['groups'])
    assert all(len(g[2]) == g[1] for g in data['groups'])          # one named star per tool
    names = {n for g in data['groups'] for n in g[2]}
    assert 'calc_percentage_change' in names
    # "About this page" names the owning guide
    assert 'class="page-help"' in t and 'Intelligence Layer' in t


def test_ask_page_refuses_anonymous_callers(web):
    c, _ = web
    r = _get(c, '/ask', follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'] == '/'
    r = _get(c, '/ask', headers={'Accept': 'application/json'}, follow_redirects=False)
    assert r.status_code == 401


def test_ask_is_in_the_menu_and_on_the_dashboard(web):
    c, admin = web
    t = _get(c, '/dashboard', cookies=admin).text
    assert t.count('href="/ask"') >= 2                             # the AI menu and a quick action
    ai_menu = t[t.index('<i class="bi bi-cpu" aria-hidden="true"></i> AI'):]
    assert ai_menu.index('Ask SAJHA') < ai_menu.index('>LLM<')      # first item of the AI menu


def test_landing_and_ask_share_the_constellation(web):
    c, _ = web
    assert 'js/constellation.js' in _get(c, '/').text
    js = _get(c, '/static/js/constellation.js')
    assert js.status_code == 200 and 'SajhaConstellation' in js.text


@pytest.mark.parametrize('question', ASK_EXAMPLES)
def test_every_example_is_answered_by_the_default_model(web, question):
    c, admin = web
    c.cookies.clear()
    r = c.post('/api/ai/ask', json={'question': question}, cookies=admin)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res['stopped_by'] == 'answer'
    assert res['steps'] and all(s['ok'] for s in res['steps']), res['steps']
    assert all(s['name'].startswith('calc_') for s in res['steps'])
    assert res['citations'] and res['confidence'] > 0.9


def test_ask_sky_has_tooltips_and_a_labelled_cosmetic_filter(web):
    c, admin = web
    t = _get(c, '/ask', cookies=admin).text
    data = _ask_data(t)
    # the hover tooltip's one-liners: a name -> description map for named stars, clipped short
    desc = data['descriptions']
    names = {n for g in data['groups'] for n in g[2]}
    assert desc and set(desc) <= names
    assert desc.get('calc_percentage_change')
    assert all(len(d) <= 120 and '\n' not in d for d in desc.values())
    # the filter: labelled, described, and says it does not change the ask
    assert '<label class="ask-filter-label" for="askFilter">' in t
    assert 'id="askFilterMsg"' in t and 'aria-describedby="askFilterMsg askFilterErr askFilterHelp"' in t
    assert 'does not change which tools SAJHA uses' in t
    js = _get(c, '/static/js/constellation.js').text
    assert 'function tips(' in js and 'aria-live' in js and 'S.nearest' in js


def test_landing_sky_names_every_star(web):
    c, _ = web
    t = _get(c, '/').text
    m = re.search(r'<script type="application/json" id="lpData">(.*?)</script>', t, re.S)
    assert m
    groups = json.loads(m.group(1))['groups']
    assert groups and all(len(g) == 3 and len(g[2]) == g[1] for g in groups)
    assert 'calc_percentage_change' in {n for g in groups for n in g[2]}
