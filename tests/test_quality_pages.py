"""The Tool Health, Evals and Tool Versions pages and their API: admin only, CSRF on forms, and
each action end to end on the live app."""

import re
import time

import pytest
from sqlalchemy import create_engine

from sajha.quality import versions as V
from sajha.quality.store import RunStore, set_run_store


@pytest.fixture
def isolated(tmp_path):
    set_run_store(RunStore(create_engine(f'sqlite:///{tmp_path / "q.db"}')))
    d = tmp_path / 'versions'
    d.mkdir()
    V.set_manager(V.VersionManager(str(d), reload_seconds=0))
    yield d
    V.set_manager(None)
    set_run_store(None)


def _csrf(html):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


@pytest.mark.parametrize('path', ['/admin/tool-health', '/admin/tool-health?lint=1&level=warning',
                                  '/admin/evals', '/admin/tool-versions', '/admin/tool-versions?new=calc_npv'])
def test_pages_render_for_admins_only(web, isolated, path):
    c, admin = web
    r = c.get(path, cookies=admin)
    assert r.status_code == 200 and 'About this page' in r.text
    assert c.get(path, follow_redirects=False).status_code in (302, 303, 401, 403)


def test_tool_health_runs_tests_and_probes(web, isolated):
    c, admin = web
    page = c.get('/admin/tool-health', cookies=admin).text
    assert 'calc_percentage_change' in page                     # the shipped probe
    r = c.post('/admin/tool-health/tests/run', cookies=admin,
               data={'csrf': _csrf(page), 'tool': 'calc_*', 'mode': 'replay'}, follow_redirects=False)
    assert r.status_code == 303 and 'run=' in r.headers['location']
    detail = c.get(r.headers['location'], cookies=admin).text
    assert 'calc_npv' in detail and 'small project' in detail
    r = c.post('/admin/tool-health/probes/calc_percentage_change/run', cookies=admin,
               data={'csrf': _csrf(page)}, follow_redirects=False)
    assert 'pass' in r.headers['location']
    bad = c.post('/admin/tool-health/tests/run', cookies=admin, data={'csrf': 'x'}, follow_redirects=False)
    assert 'error=' in bad.headers['location']
    assert c.get('/api/quality/probes', cookies=admin).json()['probes']
    assert c.get('/api/quality/lint?tool=calc_*', cookies=admin).json()['summary']['error'] == 0
    assert c.post('/api/quality/tests/run', cookies=admin, json={}).status_code == 403          # no CSRF header
    runs = c.get('/api/quality/runs?kind=test', cookies=admin).json()['runs']
    assert runs and c.get(f'/api/quality/runs/{runs[0]["id"]}', cookies=admin).json()['detail']


def test_evals_page_runs_and_compares(web, isolated):
    c, admin = web
    page = c.get('/admin/evals', cookies=admin).text
    assert 'calculators' in page
    ids = []
    for planner in ('react', 'plan_execute'):
        r = c.post('/admin/evals/run', cookies=admin, data={'csrf': _csrf(page), 'set_name': 'calculators',
                                                            'model': 'mock/mock-planner', 'planner': planner},
                   follow_redirects=False)
        assert r.status_code == 303 and 'run=' in r.headers['location'], r.headers['location']
        ids.append(re.search(r'run=([0-9a-f-]+)', r.headers['location']).group(1))
    for _ in range(200):
        runs = {x['id']: x for x in c.get('/api/quality/evals', cookies=admin).json()['runs']}
        if all(runs.get(i, {}).get('status') == 'done' for i in ids):
            break
        time.sleep(0.05)
    assert all(runs[i]['status'] == 'done' for i in ids), runs
    detail = c.get(f'/admin/evals?run={ids[0]}', cookies=admin).text
    assert 'pct-change' in detail
    cmp_ = c.get(f'/api/quality/evals/compare?a={ids[0]}&b={ids[1]}', cookies=admin).json()
    assert {m['metric'] for m in cmp_['metrics']} >= {'pass_rate', 'mean_tokens'}
    assert 'Comparison' in c.get(f'/admin/evals?a={ids[0]}&b={ids[1]}', cookies=admin).text
    bad = c.post('/admin/evals/run', cookies=admin, data={'csrf': _csrf(page), 'set_name': 'nope'}, follow_redirects=False)
    assert 'error=' in bad.headers['location']


def test_tool_versions_page_actions(web, isolated):
    c, admin = web
    page = c.get('/admin/tool-versions?new=calc_percentage_change', cookies=admin).text
    tok = _csrf(page)
    text = ('tool: calc_percentage_change\nversions:\n  "5.0.0":\n    overrides:\n'
            '      implementation: sajha.examples.quality.pct_change_v2.PercentChangeV2\n')
    r = c.post('/admin/tool-versions/calc_percentage_change/save', cookies=admin, data={'csrf': tok, 'text': text},
               follow_redirects=False)
    assert 'notice=' in r.headers['location'] and (isolated / 'calc_percentage_change.yaml').is_file()
    r = c.post('/admin/tool-versions/calc_percentage_change/canary', cookies=admin,
               data={'csrf': tok, 'version': '5.0.0', 'percent': '100'}, follow_redirects=False)
    assert 'notice=' in r.headers['location']
    # every caller is now on 5.0.0: the REST result says so, and the tool's own output shows it
    res = c.post('/api/tools/execute', cookies=admin, json={'tool': 'calc_percentage_change',
                                                            'arguments': {'old_value': 80, 'new_value': 90}}).json()
    assert res['result']['direction'] == 'up' and res['_meta'][V.META_VERSION]['version'] == '5.0.0'
    page = c.get('/admin/tool-versions', cookies=admin).text
    assert '5.0.0' in page and 'canary <strong>5.0.0</strong> at 100' in page
    r = c.post('/admin/tool-versions/calc_percentage_change/promote', cookies=admin,
               data={'csrf': tok, 'version': '5.0.0'}, follow_redirects=False)
    assert 'notice=' in r.headers['location'] and V.get_manager().get('calc_percentage_change').stable == '5.0.0'
    bad = c.post('/admin/tool-versions/calc_percentage_change/save', cookies=admin,
                 data={'csrf': tok, 'text': 'tool: calc_percentage_change\nrouting: {roles: {r: "9"}}\n'},
                 follow_redirects=False)
    assert 'error=' in bad.headers['location']
    api = c.get('/api/quality/versions', cookies=admin).json()
    assert api['tools'][0]['tool'] == 'calc_percentage_change'
    assert c.put('/api/quality/versions/calc_percentage_change', cookies=admin, content=text).status_code == 403
    assert c.put('/api/quality/versions/calc_percentage_change', cookies=admin, content=text,
                 headers={'X-CSRF-Token': tok}).status_code == 200
    assert c.post('/api/quality/versions/nope/promote', cookies=admin, json={'version': '1'},
                  headers={'X-CSRF-Token': tok}).status_code == 404
