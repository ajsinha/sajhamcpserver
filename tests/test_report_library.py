"""
The report library page (docs/architecture/Reports.md §9; sajha/routes/report_library_routes.py):
who sees which report, the run and history links, the runs and their downloads, on the live app.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import uuid

import pytest

from sajha.reports import history
from sajha.reports.model import parse
from sajha.routes import report_library_routes as L

DEFS = {
    'daily_risk': parse({'name': 'daily_risk', 'title': 'Daily risk report', 'description': 'VaR and stress.',
                         'owner': 'admin', 'tags': ['risk'],
                         'parameters': {'as_of': {'type': 'string', 'description': 'Business date'}},
                         'required': ['as_of'],
                         'sections': [{'id': 'headline', 'kind': 'kpis', 'title': 'Headline',
                                       'call': {'tool': 'calc_npv', 'arguments': {}},
                                       'values': [{'label': 'NPV', 'path': '$.npv'}]}],
                         'formats': ['markdown', 'html']}),
    'desk_only': parse({'name': 'desk_only', 'title': 'Desk only report', 'roles': ['risk_desk'],
                        'sections': [{'id': 't', 'kind': 'text', 'text': 'hi'}]}),
    'switched_off': parse({'name': 'switched_off', 'title': 'Switched off report', 'enabled': False,
                           'sections': [{'id': 't', 'kind': 'text', 'text': 'hi'}]}),
}
RUN_ADMIN = 'daily_risk-20261009T073000-abc123'
RUN_USER = 'daily_risk-20261010T073000-def456'


def _run(rid, runner):
    return {'run_id': rid, 'report': 'daily_risk', 'status': 'succeeded', 'runner': {'user_id': runner},
            'started_at': f'2026-10-{rid[15:17]}T07:30:00Z', 'parameters': {'as_of': '2026-10-09'},
            'files': {'markdown': 'x', 'html': 'y'}, 'warnings': []}


@pytest.fixture
def app(web, monkeypatch):
    c, admin = web
    if not any(getattr(r, 'path', '') == '/reports/library' for r in c.app.routes):
        c.app.include_router(L.router)                # until the router is registered in sajha/app.py
    uid = None
    runs = {}
    monkeypatch.setattr(L, '_enabled', lambda: True)
    monkeypatch.setattr(L, '_definitions', lambda: dict(DEFS))
    monkeypatch.setattr(L, '_tool_registered', lambda name: name == 'report_daily_risk')
    monkeypatch.setattr(history, 'load', lambda rid: runs.get(rid))
    monkeypatch.setattr(history, 'run_ids', lambda report: sorted((r for r in runs if r.startswith(report + '-')),
                                                                  reverse=True))
    monkeypatch.setattr(history, 'file_bytes', lambda rid, fmt: f'# {rid} as {fmt}'.encode()
                        if rid in runs and fmt in ('markdown', 'html') else None)
    # a plain user (role "user"), signed in through the form
    uid = f'rep_{uuid.uuid4().hex[:8]}'
    tok = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'}).json()['token']
    c.cookies.clear()
    r = c.post('/api/admin/users/create', headers={'Authorization': f'Bearer {tok}'},
               json={'user_id': uid, 'user_name': 'Rep', 'password': 'pass-12345', 'roles': ['user']})
    assert r.status_code == 200, r.text
    user = dict(c.post('/login', data={'user_id': uid, 'password': 'pass-12345'}, follow_redirects=False).cookies)
    c.cookies.clear()
    runs[RUN_ADMIN] = _run(RUN_ADMIN, 'admin')
    runs[RUN_USER] = _run(RUN_USER, uid)
    return c, admin, user, uid


def test_the_page_needs_sign_in(app):
    c, *_ = app
    assert c.get('/reports/library', follow_redirects=False).status_code in (302, 303, 401)


def test_admins_see_every_enabled_report_with_run_and_history_links(app):
    c, admin, *_ = app
    r = c.get('/reports/library', cookies=admin)
    assert r.status_code == 200
    page = r.text
    assert 'Daily risk report' in page and 'Desk only report' in page and 'Switched off report' not in page
    assert 'href="/tools/report_daily_risk/execute"' in page          # Run: the report tool's execute page
    assert 'href="/reports/library/daily_risk"' in page and 'href="/reports/library/desk_only"' in page
    assert 'href="/tools/report_desk_only/execute"' not in page       # its tool is not registered
    assert 'href="/reports"' in page                                   # the usage dashboard, "Usage"
    assert 'last run 2026-10-10 07:30' in page


def test_users_see_only_reports_they_may_run(app):
    c, _admin, user, _uid = app
    page = c.get('/reports/library', cookies=user).text
    assert 'Daily risk report' in page and 'Desk only report' not in page
    assert c.get('/reports/library/desk_only', cookies=user).status_code == 404
    assert 'No report you may run matches' in c.get('/reports/library?q=nothing', cookies=user).text


def test_detail_lists_the_callers_runs_and_files(app):
    c, admin, user, uid = app
    page = c.get('/reports/library/daily_risk', cookies=user).text
    assert f'/api/reports/library/runs/{RUN_USER}/html' in page and RUN_ADMIN not in page
    assert '<code>as_of</code>' in page and 'required' in page and 'Headline' in page
    page = c.get('/reports/library/daily_risk', cookies=admin).text
    assert RUN_ADMIN in page and RUN_USER in page and uid in page
    assert c.get('/reports/library/nope', cookies=admin).status_code == 404


def test_downloads_are_attachments_for_the_runner_and_admins_only(app):
    c, admin, user, _uid = app
    r = c.get(f'/api/reports/library/runs/{RUN_USER}/html', cookies=user)
    assert r.status_code == 200 and r.content == f'# {RUN_USER} as html'.encode()
    assert r.headers['content-disposition'] == f'attachment; filename="{RUN_USER}.html"'
    assert r.headers['x-content-type-options'] == 'nosniff'
    assert c.get(f'/api/reports/library/runs/{RUN_ADMIN}/html', cookies=user).status_code == 404
    assert c.get(f'/api/reports/library/runs/{RUN_ADMIN}/markdown', cookies=admin).status_code == 200
    assert c.get(f'/api/reports/library/runs/{RUN_ADMIN}/pdf', cookies=admin).status_code == 404     # not rendered
    assert c.get(f'/api/reports/library/runs/{RUN_ADMIN}/exe', cookies=admin).status_code == 404
    assert c.get(f'/api/reports/library/runs/{RUN_USER}/html', follow_redirects=False).status_code in (302, 303, 401)


def test_reports_turned_off(app, monkeypatch):
    c, admin, *_ = app
    monkeypatch.setattr(L, '_enabled', lambda: False)
    assert 'Reports are turned off' in c.get('/reports/library', cookies=admin).text
    assert c.get('/reports/library/daily_risk', cookies=admin).status_code == 404
