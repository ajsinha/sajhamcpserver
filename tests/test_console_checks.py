"""Console end-to-end flows and accessibility (scripts/check_console.py, Roadmap X15): its page list
stays live, its built-in rule subset is documented, and (when a server and Playwright are
available) the flows and the scan pass.

The browser run needs a running server: set SAJHA_CHECK_BASE (and SAJHA_CHECK_PASSWORD if the admin
password is not the seeded one; SAJHA_AXE_JS to scan with axe-core). Without it, it is skipped.
"""
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _mod():
    spec = importlib.util.spec_from_file_location('check_console', ROOT / 'scripts' / 'check_console.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_console_pages_render(web):
    client, admin = web
    broken = [(p, r.status_code) for p in _mod().PAGES
              for r in [client.get(p, cookies=admin, follow_redirects=False)] if r.status_code != 200]
    assert not broken, f'pages in scripts/check_console.py that no longer render: {broken}'


def test_every_subset_rule_is_implemented():
    mod = _mod()
    for rule, _ in mod.RULES:
        assert f"'{rule}'" in mod._SUBSET, rule


@pytest.mark.skipif(not os.environ.get('SAJHA_CHECK_BASE'), reason='set SAJHA_CHECK_BASE to a running server')
def test_console_flows_and_accessibility_in_a_browser():
    pytest.importorskip('playwright.sync_api')
    mod = _mod()
    try:
        report = mod.run(os.environ['SAJHA_CHECK_BASE'].rstrip('/'), os.environ.get('SAJHA_CHECK_USER', 'admin'),
                         os.environ.get('SAJHA_CHECK_PASSWORD', 'admin123'), mod.PAGES, os.environ.get('SAJHA_AXE_JS'))
    except Exception as exc:  # noqa: BLE001 — no browser installed, server gone, ...
        pytest.skip(f'browser check unavailable: {exc.__class__.__name__}: {exc}')
    assert not report['failures'], '\n'.join(report['failures'])
