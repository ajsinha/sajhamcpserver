"""Mobile layout: the route list of scripts/check_mobile.py stays live, every page has a
viewport meta, and (when a server and Playwright are available) the browser check passes.

The browser check needs a running server: set SAJHA_CHECK_BASE (and SAJHA_CHECK_PASSWORD if
the admin password is not the seeded one). Without it, or without Playwright, it is skipped.
"""
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / 'sajha' / 'web' / 'templates'


def _check_mobile():
    spec = importlib.util.spec_from_file_location('check_mobile', ROOT / 'scripts' / 'check_mobile.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_full_page_template_has_a_viewport_meta():
    pages = [p for p in TEMPLATES.rglob('*.html') if '<html' in p.read_text(encoding='utf-8')]
    assert pages, 'no standalone templates found'
    missing = [str(p.relative_to(TEMPLATES)) for p in pages
               if 'name="viewport"' not in p.read_text(encoding='utf-8')]
    assert not missing, f'templates without <meta name="viewport">: {missing}'


def test_check_mobile_routes_all_render(web):
    client, admin = web
    broken = []
    for path, needs_auth in _check_mobile().ROUTES:
        r = client.get(path, cookies=admin if needs_auth else None, follow_redirects=False)
        if r.status_code != 200:
            broken.append((path, r.status_code))
    assert not broken, f'routes in scripts/check_mobile.py that no longer render: {broken}'


@pytest.mark.skipif(not os.environ.get('SAJHA_CHECK_BASE'), reason='set SAJHA_CHECK_BASE to a running server')
def test_mobile_layout_in_a_browser():
    pytest.importorskip('playwright.sync_api')
    mod = _check_mobile()
    try:
        report = mod.run(os.environ['SAJHA_CHECK_BASE'].rstrip('/'), os.environ.get('SAJHA_CHECK_USER', 'admin'),
                         os.environ.get('SAJHA_CHECK_PASSWORD', 'admin123'), mod.ROUTES, mod.VIEWPORTS)
    except Exception as exc:  # noqa: BLE001 — no browser installed, server gone, ...
        pytest.skip(f'browser check unavailable: {exc.__class__.__name__}: {exc}')
    assert not report['failures'], '\n'.join(report['failures'])
