#!/usr/bin/env python3
"""
Mobile layout check for SAJHA's web UI (Playwright, headless Chromium).

Opens every page in ROUTES at phone and tablet widths and checks, per page:

  hard failures (exit status 1)
    * horizontal page scroll: document scrollWidth > viewport width
    * elements that stick out of the viewport and are not inside a horizontal-scroll
      container (the outermost offenders are listed)
    * on phones, the navigation: the hamburger opens the menu, every menu panel opens
      inside the viewport, and the hamburger closes it again

  warnings (reported, never fail the run)
    * tap targets under 40 px for primary controls (buttons, inputs, selects, nav items)
    * text under 12 px
    * fixed or sticky elements taller than a third of the viewport (they cover content)

It signs in through the login form, so run it against a server whose admin account does
not need a forced password change (use a scratch database: SAJHA_DB_PATH=/tmp/x.db).

Usage:
    python scripts/check_mobile.py --base http://127.0.0.1:3002 --user admin --password ...
    python scripts/check_mobile.py --only /dashboard /ask --viewports 375x812
    python scripts/check_mobile.py --shots /tmp/sajha-mobile        # one PNG per page/viewport
    python scripts/check_mobile.py --theme dark                       # light|dark|blue|green
    python scripts/check_mobile.py --notices --only /dashboard /tools # with system notices shown

The password can also come from SAJHA_CHECK_PASSWORD. Needs ``pip install playwright`` and
``playwright install chromium``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

# (path, needs sign-in). Paths with a sample tool/prompt use ones shipped in config/.
ROUTES: List[Tuple[str, bool]] = [
    ('/', False),
    ('/login', False),
    ('/dashboard', True),
    ('/tools', True),
    ('/tools/wiki_search/schema', True),
    ('/tools/wiki_search/execute', True),
    ('/tools/wiki_search/config', True),
    ('/prompts', True),
    ('/prompts/code_review', True),
    ('/prompts/create', True),
    ('/prompts/code_review/test', True),
    ('/ask', True),
    ('/conversations', True),
    ('/playground', True),
    ('/comparison', True),
    ('/help', True),
    ('/help/c/start', True),
    ('/help/guides', True),
    ('/help/guides/Architecture.md', True),
    ('/glossary', True),
    ('/help/tools', True),
    ('/about', True),
    ('/ai/settings', True),
    ('/monitoring/tools', True),
    ('/monitoring/users', True),
    ('/monitoring/usage', True),
    ('/reports', True),
    ('/admin/system-monitor', True),
    ('/admin/async-tasks', True),
    ('/admin/users', True),
    ('/admin/users/create', True),
    ('/admin/tools', True),
    ('/admin/prompts', True),
    ('/admin/apikeys', True),
    ('/admin/apikeys/file', True),
    ('/admin/users/file', True),
    ('/admin/apikeys/create', True),
    ('/admin/federation', True),
    ('/admin/sajhanet', True),
    ('/admin/sajhanet/tools', True),
    ('/net/instances', True),
    ('/net/instances/this', True),
    ('/admin/sajhanet/overview', True),
    ('/net/access', True),
    ('/admin/connectors', True),
    ('/admin/policies', True),
    ('/admin/approvals', True),
    ('/admin/audit', True),
    ('/admin/connections', True),
    ('/account/connections', True),
    ('/account/apikeys', True),
    ('/studio', True),
    ('/studio/rest', True),
    ('/studio/api-import', True),
    ('/studio/describe', True),
    ('/studio/dbquery', True),
    ('/studio/script', True),
    ('/studio/livelink', True),
    ('/studio/olap', True),
    ('/studio/powerbi', True),
    ('/studio/powerbidax', True),
    ('/studio/sharepoint', True),
    ('/studio/examples', True),
    ('/studio/llm', True),
    ('/studio/planners', True),
    ('/composite/builder', True),
    ('/workflows', True),
    ('/admin/tool-health', True),
    ('/admin/tool-versions', True),
    ('/admin/evals', True),
    ('/account/password', True),
]

VIEWPORTS = ['375x812', '390x844', '768x1024']

# --notices: render a sample of system notices (banner, navbar badge, dashboard panel) on every
# signed-in page before measuring, through static/js/notices.js (window.SajhaNotices).
_LONG = 'Federated server analytics-warehouse-eu-west-1.internal.example.com is unreachable'
NOTICES_SAMPLE = {
    'enabled': True, 'is_admin': True, 'badge': 3, 'others': 3,
    'banner': {'id': 'federation.upstream_down:analytics', 'severity': 'critical', 'title': _LONG},
    'notices': [
        {'id': 'federation.upstream_down:analytics', 'severity': 'critical', 'source': 'federation',
         'title': _LONG, 'detail': 'Connection refused. Its tools fail until it reconnects.',
         'link': '/admin/federation', 'since': 1, 'last_seen': 2, 'state': 'acknowledged',
         'acknowledged_by': 'admin', 'acknowledged_at': 2},
        {'id': 'db.schema', 'severity': 'error', 'source': 'db', 'title': 'Database schema is out of date',
         'detail': 'SQL to run:\nALTER TABLE api_keys ADD COLUMN secret_ciphertext_with_a_long_name TEXT;',
         'link': '/help/guides/Database%20Setup.md', 'since': 1, 'last_seen': 2, 'state': 'active'},
        {'id': 'resilience.breaker_open:FMP', 'severity': 'warning', 'source': 'resilience',
         'title': 'Circuit breaker open: FMP (financialmodelingprep.com) (tool provider)', 'detail': '5 failures.',
         'link': '/admin/system-monitor', 'since': 1, 'last_seen': 2, 'state': 'active'},
        {'id': 'federation.approvals:x', 'severity': 'info', 'source': 'federation', 'title': '2 tools held',
         'detail': '', 'link': '/admin/federation', 'since': 1, 'last_seen': 2, 'state': 'active'}]}
_NOTICES_JS = r"""
(view) => {
  if (!window.SajhaNotices || !document.getElementById('sajha-notice-banner')) return {skipped: true};
  const now = Date.now() / 1000;
  view.notices.forEach((n, i) => { n.since = now - 3600 * (i + 1); n.last_seen = now - 60;
                                   if (n.acknowledged_at) n.acknowledged_at = now - 600; });
  window.SajhaNotices.stop(); window.SajhaNotices.apply(view);
  const vis = (id) => { const el = document.getElementById(id); if (!el) return null;
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return {shown: !el.hidden && cs.display !== 'none' && r.width > 0 && r.height > 0,
            text: el.textContent.replace(/\s+/g, ' ').trim()}; };
  return {banner: vis('sajha-notice-banner'), badge: vis('sajha-notice-badge'), panel: vis('system-status'),
          items: document.querySelectorAll('#ssp-body .ssp-item').length};
}
"""
PHONE_MAX = 991  # below Bootstrap's lg breakpoint the nav collapses behind the hamburger

# One pass over the page in the browser. Returns the measurements; Python decides.
_MEASURE = r"""
() => {
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  const out = { vw, scrollWidth: document.documentElement.scrollWidth,
                bodyScrollWidth: document.body ? document.body.scrollWidth : 0,
                offenders: [], smallTargets: [], smallText: [], covering: [] };
  const label = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 3);
    if (cls.length) s += '.' + cls.join('.');
    return s;
  };
  const visible = (el, cs) => {
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    if (cs.position === 'absolute' && cs.clip && cs.clip !== 'auto') return false;  // visually-hidden
    if (cs.clipPath && cs.clipPath.startsWith('inset(50%')) return false;
    return true;
  };
  // An ancestor that scrolls horizontally contains the overflow: not a page problem. One that
  // clips it hides content instead, which counts, except for decorative positioned elements.
  const contained = (el, cs) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ps = getComputedStyle(p);
      if (/(auto|scroll)/.test(ps.overflowX)) return true;
      if (/(hidden|clip)/.test(ps.overflowX)) {
        if (cs.position === 'absolute' || cs.position === 'fixed') return true;
        const pr = p.getBoundingClientRect();
        if (pr.right <= vw + 1 && pr.left >= -1) return false;  // clipped inside the screen: content lost
        return true;
      }
      if (ps.position === 'fixed') return false;
    }
    return false;
  };
  const all = document.body ? document.body.querySelectorAll('*') : [];
  const off = new Set();
  for (const el of all) {
    if (['SCRIPT', 'STYLE', 'TEMPLATE', 'svg', 'path', 'use', 'BR', 'OPTION', 'SYMBOL'].includes(el.tagName)) continue;
    if (el.closest('svg')) continue;
    const cs = getComputedStyle(el);
    if (!visible(el, cs)) continue;
    const r = el.getBoundingClientRect();
    if ((r.right > vw + 1 || r.left < -1) && !contained(el, cs)) {
      // Elements wholly off screen on purpose (closed off-canvas, skip links) are fine.
      if (r.left >= vw || r.right <= 0) continue;
      off.add(el);
    }
  }
  for (const el of off) {
    let p = el.parentElement, nested = false;
    while (p) { if (off.has(p)) { nested = true; break; } p = p.parentElement; }
    if (!nested) {
      const r = el.getBoundingClientRect();
      out.offenders.push({ el: label(el), left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width) });
    }
  }
  // Tap targets: primary controls only (inline links in running text are exempt).
  const sel = 'button, .btn, input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, .nav-link, .navbar-toggler, .dropdown-item, .mega-item, .page-link, [role=button]';
  for (const el of document.querySelectorAll(sel)) {
    const cs = getComputedStyle(el);
    if (!visible(el, cs)) continue;
    if (el.closest('.CodeMirror, .jsoneditor, .cm-editor, .ace_editor, pre, code')) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom < 0 || r.top > document.documentElement.scrollHeight) continue;
    if (r.height < 40 || r.width < 40) {
      out.smallTargets.push({ el: label(el), w: Math.round(r.width), h: Math.round(r.height),
                              text: (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 30) });
    }
  }
  // Text under 12px (only elements that own visible text).
  for (const el of all) {
    if (!el.firstChild) continue;
    let own = '';
    for (const n of el.childNodes) if (n.nodeType === 3) own += n.textContent;
    own = own.trim();
    if (!own) continue;
    const cs = getComputedStyle(el);
    if (!visible(el, cs)) continue;
    const fs = parseFloat(cs.fontSize);
    if (fs < 12) out.smallText.push({ el: label(el), px: fs, text: own.slice(0, 30) });
  }
  // Fixed/sticky elements that cover a large part of the screen.
  for (const el of all) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (!visible(el, cs)) continue;
    const r = el.getBoundingClientRect();
    if (el.closest('.modal, .offcanvas, .dropdown-menu, .toast-container')) continue;
    if (r.height > vh / 3 && r.width > vw / 2 && cs.position === 'fixed') {
      out.covering.push({ el: label(el), h: Math.round(r.height), pos: cs.position });
    }
  }
  return out;
}
"""

_NAV = r"""
async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  const res = { problems: [], panels: 0 };
  const tog = document.querySelector('.sajha-nav .navbar-toggler');
  const menu = tog ? document.querySelector(tog.getAttribute('data-bs-target') || '#sajha-menu') : null;
  if (!tog || !menu) { res.problems.push('no hamburger/menu'); return res; }
  const tr = tog.getBoundingClientRect();
  if (tr.width < 40 || tr.height < 40) res.problems.push(`hamburger ${Math.round(tr.width)}x${Math.round(tr.height)} < 40px`);
  tog.click(); await sleep(450);
  if (!menu.classList.contains('show')) { res.problems.push('hamburger did not open the menu'); return res; }
  const mr = menu.getBoundingClientRect();
  if (mr.right > vw + 1) res.problems.push('open menu wider than the viewport');
  for (const t of document.querySelectorAll('.sajha-nav .mega > .nav-link')) {
    t.click(); await sleep(250);
    const panel = t.parentElement.querySelector('.mega-panel');
    if (!panel || !panel.classList.contains('show')) { res.problems.push(`panel "${t.innerText.trim()}" did not open`); continue; }
    res.panels++;
    const pr = panel.getBoundingClientRect();
    if (pr.right > vw + 1 || pr.left < -1) res.problems.push(`panel "${t.innerText.trim()}" outside the viewport`);
    for (const it of panel.querySelectorAll('.mega-item')) {
      const r = it.getBoundingClientRect();
      if (r.height < 40) { res.problems.push(`menu item "${it.innerText.trim().split('\n')[0]}" ${Math.round(r.height)}px tall`); break; }
    }
    // The open menu must scroll when it is taller than the screen.
    const cs = getComputedStyle(menu);
    if (menu.scrollHeight > menu.clientHeight + 2 && !/(auto|scroll)/.test(cs.overflowY))
      res.problems.push('open menu taller than the screen but not scrollable');
    if (menu.getBoundingClientRect().bottom > vh + 2 && !/(auto|scroll)/.test(cs.overflowY))
      res.problems.push('open menu runs past the bottom of the screen');
    t.click(); await sleep(200);
  }
  tog.click(); await sleep(450);
  if (menu.classList.contains('show')) res.problems.push('hamburger did not close the menu');
  return res;
}
"""


def _vp(spec: str) -> Tuple[int, int]:
    w, h = spec.lower().split('x')
    return int(w), int(h)


def _slug(path: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '_', path).strip('_') or 'root'


def run(base: str, user: str, password: str, routes: List[Tuple[str, bool]], viewports: List[str],
        shots: Optional[str] = None, theme: Optional[str] = None, verbose: bool = False,
        notices: bool = False) -> Dict:
    """Run the check; returns {'failures': [...], 'warnings': [...], 'pages': n}."""
    from playwright.sync_api import sync_playwright
    report = {'failures': [], 'warnings': [], 'pages': 0}
    if shots:
        os.makedirs(shots, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for spec in viewports:
            w, h = _vp(spec)
            # Public pages in a signed-out browser (signed in, "/" and "/login" redirect away)
            for signed in (False, True):
                todo = [p for p, auth in routes if auth == signed]
                if not todo:
                    continue
                ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=2,
                                          is_mobile=w < 900, has_touch=w < 900)
                if theme:
                    ctx.add_init_script(
                        "try{localStorage.setItem('sajha.theme', %s)}catch(e){}" % json.dumps(theme))
                if signed:
                    r = ctx.request.post(base + '/login', form={'user_id': user, 'password': password},
                                         max_redirects=0)
                    if r.status not in (302, 303):
                        report['failures'].append(f'{spec}: sign-in failed (HTTP {r.status})')
                        ctx.close()
                        continue
                page = ctx.new_page()
                for path in todo:
                    _check_page(page, base, path, spec, w, report, shots, theme, verbose,
                                notices=notices and signed)
                ctx.close()
        browser.close()
    return report


def _check_page(page, base: str, path: str, spec: str, w: int, report: Dict,
                shots: Optional[str], theme: Optional[str], verbose: bool, notices: bool = False) -> None:
    where = f'{spec} {path}'
    try:
        resp = page.goto(base + path, wait_until='load', timeout=30000)
    except Exception as exc:  # noqa: BLE001 — report and go on
        report['failures'].append(f'{where}: did not load ({exc.__class__.__name__})')
        return
    page.wait_for_timeout(600)
    if notices:
        shown = page.evaluate(_NOTICES_JS, NOTICES_SAMPLE)
        if not shown.get('skipped'):
            page.wait_for_timeout(150)
            if not (shown['banner'] or {}).get('shown') or 'Critical' not in shown['banner']['text']:
                report['failures'].append(f'{spec} {path}: notices: the banner is not shown with its severity word')
            if not (shown['badge'] or {}).get('shown'):
                report['failures'].append(f'{spec} {path}: notices: the navbar badge is not shown')
            if shown['panel'] is not None and shown['items'] != len(NOTICES_SAMPLE['notices']):
                report['failures'].append(f"{spec} {path}: notices: the panel shows {shown['items']} notices")
    report['pages'] += 1
    status = resp.status if resp else 0
    if status >= 400:
        report['warnings'].append(f'{where}: HTTP {status}')
    if not page.evaluate("!!document.querySelector('meta[name=viewport]')"):
        report['failures'].append(f'{where}: no <meta name=viewport>')
    m = page.evaluate(_MEASURE)
    if m['scrollWidth'] > m['vw'] + 1:
        report['failures'].append(f"{where}: horizontal scroll (scrollWidth {m['scrollWidth']} > {m['vw']})")
    for o in m['offenders'][:12]:
        report['failures'].append(f"{where}: off-viewport {o['el']} [{o['left']}..{o['right']}]")
    if m['smallTargets']:
        ex = ', '.join(f"{t['el']}({t['w']}x{t['h']} '{t['text']}')" for t in m['smallTargets'][:4])
        report['warnings'].append(f"{where}: {len(m['smallTargets'])} tap targets < 40px: {ex}")
    if m['smallText']:
        ex = ', '.join(f"{t['el']}({t['px']}px)" for t in m['smallText'][:4])
        report['warnings'].append(f"{where}: {len(m['smallText'])} text runs < 12px: {ex}")
    for c in m['covering']:
        report['warnings'].append(f"{where}: fixed {c['el']} {c['h']}px tall covers content")
    if shots:
        try:
            page.screenshot(path=os.path.join(shots, f'{w}_{_slug(path)}{"_" + theme if theme else ""}.png'),
                            full_page=True)
        except Exception:  # noqa: BLE001 — a screenshot is a convenience
            pass
    if w <= PHONE_MAX and page.query_selector('.sajha-nav .navbar-toggler'):
        nav = page.evaluate(_NAV)
        for p in nav['problems']:
            report['failures'].append(f'{where}: nav: {p}')
        if verbose:
            print(f'  nav {where}: {nav["panels"]} panels opened')
    if verbose:
        print(f'  checked {where}')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--base', default=os.environ.get('SAJHA_CHECK_BASE', 'http://127.0.0.1:3002'))
    ap.add_argument('--user', default=os.environ.get('SAJHA_CHECK_USER', 'admin'))
    ap.add_argument('--password', default=os.environ.get('SAJHA_CHECK_PASSWORD', 'admin123'))
    ap.add_argument('--viewports', nargs='+', default=VIEWPORTS, help='WxH, e.g. 375x812')
    ap.add_argument('--only', nargs='+', help='check only these paths')
    ap.add_argument('--extra', nargs='+', default=[], help='extra signed-in paths to check')
    ap.add_argument('--shots', help='folder for full-page screenshots')
    ap.add_argument('--theme', help='theme to set before each page loads (light, dark, blue, green)')
    ap.add_argument('--notices', action='store_true',
                    help='show sample system notices (banner, badge, dashboard panel) on signed-in pages')
    ap.add_argument('--warnings', action='store_true', help='print the warnings too')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args(argv)
    routes = ROUTES + [(p, True) for p in a.extra]
    if a.only:
        known = dict(routes)
        routes = [(p, known.get(p, True)) for p in a.only]
    rep = run(a.base.rstrip('/'), a.user, a.password, routes, a.viewports, a.shots, a.theme, a.verbose,
              notices=a.notices)
    print(f"Mobile check: {rep['pages']} page views, {len(rep['failures'])} failures, {len(rep['warnings'])} warnings")
    for f in rep['failures']:
        print('  FAIL ' + f)
    if a.warnings:
        for w in rep['warnings']:
            print('  warn ' + w)
    return 1 if rep['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
