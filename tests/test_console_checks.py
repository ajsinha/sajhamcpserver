# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Console end-to-end flows and accessibility (scripts/check_console.py, Roadmap X15): its page list
stays live, its built-in rule subset is documented, and (when a server and Playwright are
available) the flows and the scan pass.

The browser runs need a running server: set SAJHA_CHECK_BASE (and SAJHA_CHECK_PASSWORD if the admin
password is not the seeded one; SAJHA_AXE_JS to scan with axe-core; SAJHA_CHECK_THEME for the
every-page accessibility scan). Without it, they are skipped. A static scan of every template and page
script for unnamed controls and keyboard-unreachable click handlers always runs.
"""
import importlib.util
import os
import re
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


# ── Accessibility, statically: every template and page script (fast, no browser) ─────────────────
# The browser scan above only sees what a page shows when it loads; these catch the same faults in
# the markup itself, including rows, dialogs and panels a script builds later.

WEB = ROOT / 'sajha' / 'web'
_NAMED = re.compile(r'\b(aria-label|aria-labelledby|title|placeholder)\s*=', re.I)
_CONTROL = re.compile(r'<(input|select|textarea)\b((?:[^>"\']|"[^"]*"|\'[^\']*\')*)>', re.I | re.S)
_CLICKABLE = re.compile(r'<(button|a)\b((?:[^>"\']|"[^"]*"|\'[^\']*\')*)>(.*?)</\1\s*>', re.I | re.S)
_ICON = re.compile(r'<(i|span)\b[^>]*\bclass="[^"]*\b(bi|spinner-border)\b[^"]*"[^>]*>\s*</\1>')
#: A click handler on an element the keyboard cannot reach unless it is made a control.
_CLICK_ONLY = re.compile(r'<(span|div|i|td|li|p|small|strong|img|tr|th|h[1-6]|code|section|article)\b'
                         r'((?:[^>"\']|"[^"]*"|\'[^\']*\')*)\bdata-on(?:click|dblclick)=', re.I | re.S)


def _sources():
    return sorted(list((WEB / 'templates').rglob('*.html')) + list((WEB / 'static' / 'js').glob('*.js')))


def _unnamed(text: str):
    """(line, snippet) for each form control without an accessible name and each button or link
    with no text, no image alternative, no aria-label and no title."""
    text = re.sub(r'(?m)^[ \t]*//.*$', '', text)                       # page-script line comments
    out = []
    labelled = set(re.findall(r'<label\b[^>]*\bfor\s*=\s*"([^"]+)"', text))
    for m in _CONTROL.finditer(text):
        attrs = m.group(2)
        kind = re.search(r'\btype\s*=\s*["\']?(\w+)', attrs)
        if m.group(1).lower() == 'input' and kind and kind.group(1).lower() in ('hidden', 'submit', 'button', 'reset', 'image'):
            continue
        if _NAMED.search(attrs):
            continue
        ident = re.search(r'\bid\s*=\s*"([^"]+)"', attrs)
        if ident and ident.group(1) in labelled:
            continue
        line = text[text.rfind('\n', 0, m.start()) + 1:m.start()]
        if 'field(' in line:                     # static/js/workflows.js field(): a <label for> a fresh id
            continue
        before = text[:m.start()]
        if before.rfind('<label') > before.rfind('</label'):           # wrapped in its <label>
            continue
        out.append((text.count('\n', 0, m.start()) + 1, m.group(0)[:100]))
    for m in _CLICKABLE.finditer(text):
        tag, attrs, inner = m.group(1).lower(), m.group(2), m.group(3)
        if (tag == 'a' and 'href' not in attrs) or _NAMED.search(attrs):
            continue
        inner = re.sub(r'<img\b[^>]*\balt="[^"]+"[^>]*>', 'img', _ICON.sub('', inner))
        if not re.sub(r'<[^>]+>', '', inner).strip():
            out.append((text.count('\n', 0, m.start()) + 1, m.group(0)[:100]))
    return out


def test_every_control_in_the_console_has_an_accessible_name():
    bad = [f'{p.relative_to(WEB)}:{line}: {snip}' for p in _sources() for line, snip in _unnamed(p.read_text(encoding='utf-8'))]
    assert not bad, ('controls without an accessible name (add <label for>, aria-label or, for an icon-only '
                     'button or link, aria-label plus title):\n' + '\n'.join(bad))


def test_the_static_scan_catches_what_it_should():
    found = _unnamed('<select id="a"></select>\n<button><i class="bi bi-x"></i></button>\n'
                     '<a href="/x"><i class="bi bi-x"></i></a>\n<label for="b">B</label><input id="b">\n'
                     '<button title="t"><i class="bi bi-x"></i></button><label>x <input></label><input type="hidden">')
    assert [line for line, _ in found] == [1, 2, 3]


def test_click_handlers_on_plain_elements_are_keyboard_reachable():
    """A div, span or header with a click handler is a custom control: it needs role="button" and
    tabindex="0" (static/js/csp-actions.js then gives it Enter and Space), or, for a sortable <th>,
    tabindex="0"."""
    bad = []
    for p in _sources():
        text = p.read_text(encoding='utf-8')
        for m in _CLICK_ONLY.finditer(text):
            attrs = m.group(0)
            if 'tabindex="0"' in attrs and ('role="button"' in attrs or m.group(1).lower() == 'th'):
                continue
            bad.append(f'{p.relative_to(WEB)}:{text.count(chr(10), 0, m.start()) + 1}: {attrs[:100]}')
    assert not bad, 'click handlers the keyboard cannot reach:\n' + '\n'.join(bad)


@pytest.mark.skipif(not os.environ.get('SAJHA_CHECK_BASE'), reason='set SAJHA_CHECK_BASE to a running server')
def test_accessibility_on_every_console_page_in_a_browser():
    """The accessibility half of scripts/check_console.py --all (every signed-in route of
    scripts/check_mobile.py), in the theme of SAJHA_CHECK_THEME (default light). About a minute."""
    pytest.importorskip('playwright.sync_api')
    mod = _mod()
    try:
        report = mod.run(os.environ['SAJHA_CHECK_BASE'].rstrip('/'), os.environ.get('SAJHA_CHECK_USER', 'admin'),
                         os.environ.get('SAJHA_CHECK_PASSWORD', 'admin123'), mod._check_mobile_routes(),
                         os.environ.get('SAJHA_AXE_JS'), os.environ.get('SAJHA_CHECK_THEME', 'light'),
                         do_flows=False)
    except Exception as exc:  # noqa: BLE001 — no browser installed, server gone, ...
        pytest.skip(f'browser check unavailable: {exc.__class__.__name__}: {exc}')
    assert report['a11y_pages'] == len(mod._check_mobile_routes())
    assert not report['failures'], '\n'.join(report['failures'])
