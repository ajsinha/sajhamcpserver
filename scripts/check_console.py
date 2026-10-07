#!/usr/bin/env python3
"""
Console end-to-end flows and accessibility check for SAJHA's web UI (Playwright, headless
Chromium). Roadmap X15; the layout check at phone widths is scripts/check_mobile.py.

  flows (each a failure when it does not complete)
    sign-in      the login form signs the admin in and lands on the dashboard
    ask          Ask SAJHA answers an example question (the mock model, no keys)
    llm-tool     the Studio LLM tool creator builds a classify tool, the check says it loads,
                 it runs on the mock model, deploys, and is deleted again
    planner      the planner editor opens a planner, the check is clean and a dry run shows
                 a stage path
    conversations  the Conversations page lists the conversation the ask flow made

  accessibility (on PAGES, or every check_mobile.py route with --all)
    With axe-core (``--axe path/to/axe.min.js`` or SAJHA_AXE_JS; https://github.com/dequelabs/axe-core):
    the WCAG 2.x A and AA rules; a violation of impact serious or critical fails, others warn.
    Without it, a built-in subset of the same rules runs (documented in RULES below): document
    language and title, one main landmark, image alternative text, form-control labels, button and
    link names, unique ids, ARIA references, heading order, a positive tabindex.

Run it against a running server whose admin does not need a forced password change (a scratch
database: SAJHA_DB_PATH=/tmp/x.db), for example on another port than the dev server:

    SAJHA_DB_PATH=/tmp/c.db SERVER_PORT=3087 python run_server.py &
    python scripts/check_console.py --base http://127.0.0.1:3087 --axe /path/to/axe.min.js
    python scripts/check_console.py --only-a11y --all --theme dark

The flows create one tool (``zz_e2e_triage``) and delete it. Exit status 1 on any failure.
Needs ``pip install playwright`` and ``playwright install chromium``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent

#: Pages the accessibility check covers by default: the pages wave 3 added and the main flows.
PAGES = ['/dashboard', '/ask', '/conversations', '/studio', '/studio/llm', '/studio/planners', '/studio/describe']

#: The built-in rule subset (used when axe-core is not available): (id, what it checks).
RULES = [
    ('html-has-lang', '<html> has a lang attribute'),
    ('document-title', 'the page has a non-empty <title>'),
    ('landmark-one-main', 'exactly one <main> (or role=main) landmark'),
    ('image-alt', 'every <img> has alt text (or alt="" / role=presentation when decorative)'),
    ('label', 'every visible input, select and textarea has an accessible name'),
    ('button-name', 'every visible button has an accessible name'),
    ('link-name', 'every visible link has an accessible name'),
    ('duplicate-id', 'ids are unique'),
    ('aria-valid-ref', 'aria-labelledby / aria-describedby / aria-controls point at existing ids'),
    ('heading-order', 'heading levels increase by at most one'),
    ('tabindex', 'no positive tabindex'),
]

_SUBSET = r"""
() => {
  const out = [];
  const vis = (el) => { const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
  const label = (el) => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id;
    const c = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    if (c.length) s += '.' + c.join('.'); return s; };
  const add = (id, impact, el, msg) => out.push({id, impact, target: el ? label(el) : 'document', help: msg});
  const name = (el) => {
    const t = (el.getAttribute('aria-label') || '').trim(); if (t) return t;
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const s = lb.split(/\s+/).map(i => (document.getElementById(i) || {}).textContent || '').join(' ').trim(); if (s) return s; }
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l && l.textContent.trim()) return l.textContent.trim(); }
    const wrap = el.closest('label'); if (wrap && wrap.textContent.trim()) return wrap.textContent.trim();
    if (el.getAttribute('title')) return el.getAttribute('title');
    if (['BUTTON', 'A'].includes(el.tagName)) { const tx = (el.innerText || el.textContent || '').trim(); if (tx) return tx;
      const img = el.querySelector('img[alt]'); if (img && img.alt.trim()) return img.alt; }
    if (el.tagName === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type) && el.value) return el.value;
    if (el.getAttribute('placeholder')) return el.getAttribute('placeholder');   // axe accepts it too
    return '';
  };
  if (!document.documentElement.getAttribute('lang')) add('html-has-lang', 'serious', null, '<html> has no lang');
  if (!document.title.trim()) add('document-title', 'serious', null, 'no <title>');
  const mains = document.querySelectorAll('main, [role=main]');
  if (mains.length !== 1) add('landmark-one-main', 'moderate', null, mains.length + ' main landmarks');
  document.querySelectorAll('img').forEach(i => { if (!i.hasAttribute('alt') && i.getAttribute('role') !== 'presentation' && vis(i))
    add('image-alt', 'critical', i, 'image without alt'); });
  document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(el => { if (vis(el) && !name(el))
    add('label', 'critical', el, 'form control without a label'); });
  document.querySelectorAll('button, [role=button]').forEach(el => { if (vis(el) && !name(el))
    add('button-name', 'critical', el, 'button without a name'); });
  document.querySelectorAll('a[href]').forEach(el => { if (vis(el) && !name(el))
    add('link-name', 'serious', el, 'link without a name'); });
  const seen = {};
  document.querySelectorAll('[id]').forEach(el => { if (seen[el.id]) add('duplicate-id', 'minor', el, 'duplicate id ' + el.id); seen[el.id] = 1; });
  document.querySelectorAll('[aria-labelledby], [aria-describedby], [aria-controls]').forEach(el => {
    ['aria-labelledby', 'aria-describedby', 'aria-controls'].forEach(a => { const v = el.getAttribute(a); if (!v) return;
      v.split(/\s+/).forEach(i => { if (i && !document.getElementById(i)) add('aria-valid-ref', 'serious', el, a + ' -> missing #' + i); }); }); });
  let last = 0;
  document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => { if (!vis(h)) return; const n = +h.tagName[1];
    if (last && n > last + 1) add('heading-order', 'moderate', h, 'h' + last + ' then h' + n); last = n; });
  document.querySelectorAll('[tabindex]').forEach(el => { if (+el.getAttribute('tabindex') > 0) add('tabindex', 'serious', el, 'positive tabindex'); });
  return out;
}
"""

FAIL_IMPACTS = ('serious', 'critical')


def _check_mobile_routes() -> List[str]:
    spec = importlib.util.spec_from_file_location('check_mobile', ROOT / 'scripts' / 'check_mobile.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [p for p, auth in mod.ROUTES if auth]


def _axe_source(path: Optional[str]) -> Optional[str]:
    for p in (path, os.environ.get('SAJHA_AXE_JS')):
        if p and Path(p).is_file():
            return Path(p).read_text(encoding='utf-8')
    return None


def accessibility(page, base: str, paths: List[str], axe: Optional[str], report: Dict) -> None:
    for path in paths:
        try:
            page.goto(base + path, wait_until='load', timeout=30000)
        except Exception as e:  # noqa: BLE001
            report['failures'].append(f'a11y {path}: did not load ({e.__class__.__name__})')
            continue
        page.wait_for_timeout(700)
        if axe:
            page.add_script_tag(content=axe)
            res = page.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag',
                values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}, resultTypes: ['violations']});
                return r.violations.map(v => ({id: v.id, impact: v.impact, help: v.help,
                                               target: v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | '),
                                               count: v.nodes.length})); }""")
        else:
            res = page.evaluate(_SUBSET)
        report['a11y_pages'] += 1
        for v in res:
            line = f"a11y {path}: {v['id']} ({v.get('impact')}): {v.get('help')} [{v.get('target')}]" + \
                   (f" x{v['count']}" if v.get('count', 1) > 1 else '')
            (report['failures'] if v.get('impact') in FAIL_IMPACTS else report['warnings']).append(line)


def _step(report: Dict, name: str, fn) -> bool:
    try:
        fn()
        report['flows'].append(name)
        return True
    except Exception as e:  # noqa: BLE001 — report and go on
        report['failures'].append(f'flow {name}: {e.__class__.__name__}: {str(e).splitlines()[0][:300]}')
        return False


def flows(page, base: str, user: str, password: str, report: Dict) -> None:
    page.on('dialog', lambda d: d.accept())

    def sign_in():
        page.goto(base + '/login', wait_until='load')
        page.fill('input[name=user_id]', user)
        page.fill('input[name=password]', password)
        page.click('button[type=submit], input[type=submit]')
        page.wait_for_url('**/dashboard*', timeout=15000)

    def ask():
        page.goto(base + '/ask', wait_until='load')
        page.click('#askNew') if page.query_selector('#askNew') else None
        page.fill('#askInput', 'What is the percentage change from 80 to 100?')
        page.keyboard.press('Enter')
        page.wait_for_function("() => /25/.test((document.querySelector('.ask-turn:last-of-type .ask-bubble-sajha') || {}).innerText || '')",
                               timeout=30000)

    def llm_tool():
        name = 'zz_e2e_triage'
        page.request.post(base + '/admin/studio/delete', data=json.dumps({'tool_name': name}),
                          headers={'Content-Type': 'application/json'})
        page.goto(base + '/studio/llm', wait_until='load')
        page.fill('#ltName', name)
        page.fill('#ltDescription', 'Classifies a support message into billing or technical.')
        page.select_option('#ltMode', 'classify')
        page.fill('#ltSystem', 'billing: money, invoices. technical: errors, bugs.')
        page.fill('#ltTemplate', 'Classify this message:\n\n{{input.message}}')
        page.fill('#ltLabels', 'billing, technical')
        page.wait_for_function("() => document.getElementById('ltValidBadge').textContent === 'loads'", timeout=15000)
        page.fill('#ltArgs', json.dumps({'message': 'my invoice charged me twice'}))
        page.click('#ltTest')
        page.wait_for_function("() => /billing/.test(document.getElementById('ltTestResult').innerText)", timeout=20000)
        page.click('#ltDeploy')
        page.wait_for_function("() => /callable now/.test(document.getElementById('ltDeployResult').innerText)", timeout=20000)
        r = page.request.post(base + '/admin/studio/delete', data=json.dumps({'tool_name': name}),
                              headers={'Content-Type': 'application/json'})
        if not r.ok:
            raise RuntimeError(f'could not delete {name}: HTTP {r.status}')

    def planner():
        page.goto(base + '/studio/planners?open=react', wait_until='load')
        page.wait_for_function("() => document.getElementById('peBadge').textContent === 'valid'", timeout=15000)
        if not page.query_selector('#peGraph g.node'):
            raise RuntimeError('the graph has no stages')
        page.click('#peDry')
        page.wait_for_function("() => document.querySelectorAll('#peDryResult .pe-path code').length > 0", timeout=30000)

    def conversations():
        page.goto(base + '/conversations', wait_until='load')
        page.wait_for_function("() => document.querySelectorAll('#cvList .cv-view').length > 0", timeout=15000)

    if not _step(report, 'sign-in', sign_in):
        return
    _step(report, 'ask', ask)
    _step(report, 'llm-tool', llm_tool)
    _step(report, 'planner', planner)
    _step(report, 'conversations', conversations)


def run(base: str, user: str, password: str, paths: List[str], axe_path: Optional[str] = None,
        theme: Optional[str] = None, do_flows: bool = True, do_a11y: bool = True) -> Dict:
    from playwright.sync_api import sync_playwright
    report: Dict = {'failures': [], 'warnings': [], 'flows': [], 'a11y_pages': 0,
                    'engine': 'axe-core' if _axe_source(axe_path) else 'built-in subset'}
    axe = _axe_source(axe_path)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900})
        if theme:
            ctx.add_init_script("try{localStorage.setItem('sajha.theme', %s)}catch(e){}" % json.dumps(theme))
        page = ctx.new_page()
        if do_flows:
            flows(page, base, user, password, report)
        else:
            r = ctx.request.post(base + '/login', form={'user_id': user, 'password': password}, max_redirects=0)
            if r.status not in (302, 303):
                report['failures'].append(f'sign-in failed (HTTP {r.status})')
        if do_a11y and 'sign-in' not in [f.split(':')[0] for f in report['failures']]:
            accessibility(page, base, paths, axe, report)
        browser.close()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--base', default=os.environ.get('SAJHA_CHECK_BASE', 'http://127.0.0.1:3002'))
    ap.add_argument('--user', default=os.environ.get('SAJHA_CHECK_USER', 'admin'))
    ap.add_argument('--password', default=os.environ.get('SAJHA_CHECK_PASSWORD', 'admin123'))
    ap.add_argument('--axe', help='path to axe.min.js (else SAJHA_AXE_JS; else the built-in rule subset)')
    ap.add_argument('--all', action='store_true', help='check every signed-in route of scripts/check_mobile.py')
    ap.add_argument('--only', nargs='+', help='check only these paths')
    ap.add_argument('--theme', help='light, dark, blue or green')
    ap.add_argument('--only-a11y', action='store_true', help='skip the flows')
    ap.add_argument('--only-flows', action='store_true', help='skip the accessibility check')
    ap.add_argument('--warnings', action='store_true', help='print the warnings too')
    a = ap.parse_args(argv)
    paths = a.only or (_check_mobile_routes() if a.all else PAGES)
    rep = run(a.base.rstrip('/'), a.user, a.password, paths, a.axe, a.theme, not a.only_a11y, not a.only_flows)
    print(f"Console check ({rep['engine']}): flows passed {', '.join(rep['flows']) or 'none'}; "
          f"{rep['a11y_pages']} pages scanned; {len(rep['failures'])} failures, {len(rep['warnings'])} warnings")
    for f in rep['failures']:
        print('  FAIL ' + f)
    if a.warnings:
        for w in rep['warnings']:
            print('  warn ' + w)
    return 1 if rep['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
