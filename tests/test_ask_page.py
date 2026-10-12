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


@pytest.fixture
def without_qlrisk_tools():
    """The mock planner scores tools by keyword overlap; with qlrisk installed, its per-product pricing
    tools (qlrisk_price_<product>: bond, future, ...) outscore the calculators on these examples. The
    examples are about the calculators, so the qlrisk tools are out of the catalog for this test."""
    from sajha.app import tools_registry
    held = {n: t for n, t in tools_registry.tools.items() if n.startswith('qlrisk_')}
    for n in held:
        tools_registry.unregister_tool(n)
    yield
    for t in held.values():
        tools_registry.register_tool(t)


@pytest.mark.parametrize('question', ASK_EXAMPLES)
def test_every_example_is_answered_by_the_default_model(web, question, without_qlrisk_tools):
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


def _landing_groups(c):
    t = _get(c, '/').text
    m = re.search(r'<script type="application/json" id="lpData">(.*?)</script>', t, re.S)
    assert m
    return json.loads(m.group(1))['groups']


def test_landing_sky_names_only_tools_anonymous_callers_may_see(web, monkeypatch):
    """The public landing page draws every group from its count, but names a star only when
    an anonymous MCP caller could see that tool (mcp.anonymous.tools; empty by default)."""
    c, _ = web
    groups = _landing_groups(c)
    assert groups and all(len(g) == 4 and g[1] > 0 and g[3] for g in groups)       # [domain, count, names, label]
    assert not any(g[2] for g in groups)            # default policy: no tool names leak
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_TOOLS', 'calc_*')
    names = {n for g in _landing_groups(c) for n in g[2]}
    assert 'calc_percentage_change' in names
    assert names and all(n.startswith('calc_') for n in names)


def test_server_name_is_the_per_net_instance_name(monkeypatch):
    # sajhanet.instance_name is not a key: the instance name is per net (sajhanet.nets[].instance_name)
    import socket
    import sajha.net.integration as net
    from sajha.routes.ai_routes import _local_server_name
    monkeypatch.setattr(net, 'get_service', lambda: None)
    monkeypatch.setenv('SAJHA_SAJHANET_NETS', json.dumps([{'name': 'acme', 'instance_name': 'risk-eu'}]))
    assert _local_server_name() == 'risk-eu'
    monkeypatch.setenv('SAJHA_SAJHANET_NETS', json.dumps([{'name': 'a', 'instance_name': 'risk-eu'},
                                                          {'name': 'b', 'instance_name': 'risk-eu'},
                                                          {'name': 'c', 'instance_name': 'risk-us'}]))
    assert _local_server_name() == 'risk-eu, risk-us'
    monkeypatch.setenv('SAJHA_SAJHANET_NETS', '[]')
    assert _local_server_name() == socket.gethostname()

    class Rt:
        def __init__(self, n):
            self.cfg = type('C', (), {'instance_name': n})()
    monkeypatch.setattr(net, 'get_service', lambda: type('S', (), {'runtimes': {'acme': Rt('10.0.0.5:3002')}})())
    assert _local_server_name() == '10.0.0.5:3002'          # the running net's resolved name
