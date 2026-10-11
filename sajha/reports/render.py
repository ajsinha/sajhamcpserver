"""
SAJHA MCP Server — rendering report data to files (docs/architecture/Reports.md §4).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``render(data, fmt)`` turns stored report data into Markdown or HTML (always available), PDF
(the HTML printed by headless Chromium through Playwright), XLSX (openpyxl), PPTX (python-pptx)
or DOCX (python-docx). A format whose package is missing is not offered: :func:`unavailable`
gives the reason, and nothing else is affected. Rendering never calls a tool: it reads only the
stored data, so a past run can be rendered again (``report_render``).

Every format carries the classification marking in its header and footer (and, at
``confidential`` and above, a diagonal watermark in HTML and PDF) and ends with the provenance
appendix: run id, runner, times, parameters, and for each section the tool, its version, the
arguments, the as-of time and the source's attribution line. Chart sections are inline SVG in
HTML and PDF; the other file formats show the chart's data table and say so.
"""

from __future__ import annotations

import html as _html
import importlib.util
import io
import json
import threading
from typing import Any, Dict, List, Optional, Tuple

from sajha.reports.model import FORMATS, classification_rank
from sajha.reports.values import display, is_number

STATUS_TEXT = {
    'not_permitted': 'Not permitted', 'unavailable': 'Unavailable', 'error': 'Error', 'skipped': 'Skipped',
    'empty': 'No data', 'pending_narration': 'Commentary not generated yet (report_narrate)',
}
CHART_NOTE = 'Chart shown as its data table in this format.'
_PACKAGES = {'xlsx': ('openpyxl', 'openpyxl'), 'pptx': ('pptx', 'python-pptx'), 'docx': ('docx', 'python-docx')}
_pdf_state: Dict[str, Any] = {}
_pdf_lock = threading.Lock()


# ── availability ────────────────────────────────────────────────────

def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _in_thread(fn, timeout: float = 120.0):
    """Run ``fn`` in a fresh thread (Playwright's sync API refuses a thread with a running event loop)."""
    box: Dict[str, Any] = {}

    def target():
        try:
            box['v'] = fn()
        except BaseException as e:       # re-raised in the caller
            box['e'] = e
    t = threading.Thread(target=target, name='report-pdf', daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError('PDF rendering did not finish in time')
    if 'e' in box:
        raise box['e']
    return box.get('v')


def _pdf_problem() -> Optional[str]:
    with _pdf_lock:
        if 'problem' in _pdf_state:
            return _pdf_state['problem']
        if not _has('playwright'):
            problem = 'PDF needs Playwright and Chromium (pip install playwright; playwright install chromium)'
        else:
            def probe():
                import os
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    path = p.chromium.executable_path
                return path if path and os.path.exists(path) else ''
            try:
                path = _in_thread(probe, 60)
                problem = None if path else 'PDF needs Chromium for Playwright (playwright install chromium)'
            except Exception as e:
                problem = f'PDF is not available: Playwright could not start ({e.__class__.__name__}: {e})'
        _pdf_state['problem'] = problem
        return problem


def unavailable(fmt: str) -> Optional[str]:
    """Why ``fmt`` cannot be rendered on this server (None: it can)."""
    if fmt not in FORMATS:
        return f'unknown format {fmt!r}'
    if fmt in ('markdown', 'html'):
        return None
    if fmt == 'pdf':
        return _pdf_problem()
    module, package = _PACKAGES[fmt]
    return None if _has(module) else f'{fmt.upper()} needs the Python package {package}, which is not installed'


def available_formats() -> List[str]:
    return [f for f in FORMATS if unavailable(f) is None]


def reset_cache() -> None:
    with _pdf_lock:
        _pdf_state.clear()


# ── shared pieces ───────────────────────────────────────────────────

def marking(data: Dict[str, Any]) -> str:
    c = str(data.get('classification') or 'internal')
    return f'{c.upper()}: SAJHA report {data.get("report")} (run {data.get("run_id")})'


def provenance(data: Dict[str, Any]) -> Dict[str, Any]:
    """The provenance appendix as data: the run, then one entry per section with a source."""
    run = {'Run id': data.get('run_id'), 'Report': f'{data.get("title")} ({data.get("report")})',
           'Runner': (data.get('runner') or {}).get('user_id'), 'Started': data.get('started_at'),
           'Finished': data.get('finished_at'), 'Parameters': json.dumps(data.get('parameters') or {}, default=str),
           'Classification': data.get('classification'), 'Definition sha256': data.get('definition_hash')}
    nar = data.get('narration') or {}
    if nar.get('model'):
        run['Narrator model'] = nar['model']
    sources = []
    for s in data.get('sections') or []:
        src = s.get('source')
        if not src:
            continue
        sources.append({'section': s['id'], 'tool': src.get('tool'), 'version': src.get('version') or '',
                        'arguments': json.dumps(src.get('arguments') or {}, default=str),
                        'as_of': src.get('as_of') or src.get('called_at') or '',
                        'attribution': src.get('attribution') or '', 'status': s.get('status')})
    return {'run': run, 'sources': sources}


def _cell(v: Any, col: Dict[str, Any]) -> str:
    return display(v, col) if v is not None else ''


def _md_escape(s: Any) -> str:
    return str(s).replace('|', '\\|').replace('\n', ' ')


def _status_line(s: Dict[str, Any]) -> Optional[str]:
    st = s.get('status')
    if st in ('ok', 'text'):
        return None
    head = STATUS_TEXT.get(st, st)
    return f'{head}: {s["error"]}' if s.get('error') else head


def _kpi_rows(s: Dict[str, Any]) -> Tuple[List[str], List[List[str]]]:
    kpis = s.get('kpis') or []
    with_change = any('change' in k for k in kpis)
    head = ['Measure', 'Value'] + (['Previous', 'Change'] if with_change else [])
    rows = []
    for k in kpis:
        row = [k['label'], k.get('display') or '']
        if with_change:
            row += [k.get('previous_display', ''), k.get('change_display', '')]
        rows.append(row)
    return head, rows


def _table_rows(s: Dict[str, Any]) -> Tuple[List[str], List[List[str]]]:
    t = s.get('table') or {}
    cols = t.get('columns') or []
    return [c['label'] for c in cols], [[_cell(r.get(c['key']), c) for c in cols] for r in t.get('rows') or []]


def _params_text(data: Dict[str, Any]) -> str:
    return ', '.join(f'{k} = {v if isinstance(v, str) else json.dumps(v, default=str)}'
                     for k, v in (data.get('parameters') or {}).items())


def _sections(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(data.get('sections') or [])


# ── Markdown ────────────────────────────────────────────────────────

def _md_table(head: List[str], rows: List[List[str]]) -> List[str]:
    out = ['| ' + ' | '.join(_md_escape(h) for h in head) + ' |', '|' + '---|' * len(head)]
    out += ['| ' + ' | '.join(_md_escape(c) for c in r) + ' |' for r in rows]
    return out


def to_markdown(data: Dict[str, Any]) -> str:
    m = marking(data)
    L = [f'*{m}*', '', f'# {data.get("title")}', '']
    if data.get('description'):
        L += [data['description'], '']
    params = _params_text(data)
    L += [f'Run {data.get("run_id")} by {(data.get("runner") or {}).get("user_id")} at {data.get("started_at")}'
          + (f'; parameters: {params}' if params else '') + f'; status: {data.get("status")}.', '']
    for s in _sections(data):
        L += [f'## {s.get("title")}', '']
        line = _status_line(s)
        if line:
            L += [f'> {line}', '']
        if s.get('text'):
            L += [s['text'], '']
        if s.get('kpis'):
            L += _md_table(*_kpi_rows(s)) + ['']
        if (s.get('table') or {}).get('rows'):
            L += _md_table(*_table_rows(s))
            t = s['table']
            if t.get('truncated'):
                L += ['', f'*{len(t["rows"])} of {t["row_count"]} rows shown.*']
            L += ['']
    p = provenance(data)
    L += ['## Provenance', '']
    L += [f'- **{k}:** {_md_escape(v)}' for k, v in p['run'].items() if v not in (None, '')]
    if p['sources']:
        L += [''] + _md_table(['Section', 'Tool', 'Version', 'Arguments', 'As of', 'Source'],
                              [[x['section'], x['tool'], x['version'], x['arguments'], x['as_of'], x['attribution']]
                               for x in p['sources']])
    L += ['', f'*{m}*', '']
    return '\n'.join(L)


# ── HTML (and PDF) ──────────────────────────────────────────────────

_PALETTE = ['#2a6fdb', '#d9822b', '#3a9d5d', '#a347ba']


def chart_svg(s: Dict[str, Any], width: int = 640, height: int = 260) -> str:
    """A small inline SVG bar or line chart of a section's table (numbers only; escaped labels)."""
    ch, t = s.get('chart') or {}, s.get('table') or {}
    rows = (t.get('rows') or [])[:60]
    ys = [y for y in ch.get('y') or [] if any(is_number(r.get(y)) for r in rows)]
    if not rows or not ys:
        return ''
    vals = [r.get(y) for r in rows for y in ys if is_number(r.get(y))]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    if hi == lo:
        hi = lo + 1
    pad_l, pad_b, pad_t = 56, 40, 12
    pw, ph = width - pad_l - 10, height - pad_b - pad_t

    def ypos(v):
        return pad_t + ph - (float(v) - lo) / (hi - lo) * ph
    e = _html.escape
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
             f'height="{height}" role="img" aria-label="{e(str(s.get("title") or "chart"))}">',
             f'<line x1="{pad_l}" y1="{ypos(0):.1f}" x2="{width - 10}" y2="{ypos(0):.1f}" stroke="#888"/>',
             f'<text x="4" y="{pad_t + 10}" font-size="10">{e(display(hi))}</text>',
             f'<text x="4" y="{pad_t + ph}" font-size="10">{e(display(lo))}</text>']
    n = len(rows)
    step = pw / n
    for j, y in enumerate(ys):
        color = _PALETTE[j % len(_PALETTE)]
        if ch.get('type') == 'line':
            pts = [f'{pad_l + step * (i + .5):.1f},{ypos(r[y]):.1f}' for i, r in enumerate(rows) if is_number(r.get(y))]
            parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(pts)}"/>')
        else:
            bw = max(1.0, step * .8 / len(ys))
            for i, r in enumerate(rows):
                if not is_number(r.get(y)):
                    continue
                x = pad_l + step * i + step * .1 + bw * j
                y0, y1 = ypos(0), ypos(r[y])
                parts.append(f'<rect x="{x:.1f}" y="{min(y0, y1):.1f}" width="{bw:.1f}" height="{abs(y1 - y0):.1f}" '
                             f'fill="{color}"><title>{e(str(r.get(ch.get("x"))))}: {e(display(r[y]))}</title></rect>')
    every = max(1, n // 12)
    for i, r in enumerate(rows):
        if i % every == 0:
            parts.append(f'<text x="{pad_l + step * (i + .5):.1f}" y="{height - pad_b + 14}" font-size="9" '
                         f'text-anchor="middle">{e(str(r.get(ch.get("x")))[:12])}</text>')
    for j, y in enumerate(ys):
        parts.append(f'<text x="{pad_l + 120 * j}" y="{height - 6}" font-size="10" fill="{_PALETTE[j % 4]}">'
                     f'{e(str(y))}</text>')
    parts.append('</svg>')
    return ''.join(parts)


_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{{ data.title }}</title>
<style>
body{font-family:Helvetica,Arial,sans-serif;margin:24px 32px;color:#1d1d1f;font-size:13px}
.marking{text-align:center;font-weight:bold;letter-spacing:.05em;font-size:11px;color:#8a1c1c;padding:4px;border:1px solid #8a1c1c}
h1{font-size:22px;margin:18px 0 4px}h2{font-size:16px;margin:22px 0 6px;border-bottom:1px solid #ddd;padding-bottom:3px}
.meta{color:#555;font-size:12px}table{border-collapse:collapse;margin:6px 0;font-size:12px}
th,td{border:1px solid #ccc;padding:3px 7px;text-align:left;vertical-align:top}th{background:#f2f2f2}
td.num{text-align:right;font-variant-numeric:tabular-nums}tr.hl td{background:#fde8e8}
.status{background:#fff6e0;border-left:3px solid #d9822b;padding:4px 8px;margin:6px 0}
.kpis{display:flex;flex-wrap:wrap;gap:10px}.kpi{border:1px solid #ddd;border-radius:6px;padding:8px 12px;min-width:130px}
.kpi .l{font-size:11px;color:#555}.kpi .v{font-size:18px;font-weight:bold}.kpi .c{font-size:11px;color:#555}
.prov td,.prov th{font-size:11px}
{% if watermark %}.wm{position:fixed;top:40%;left:5%;width:90%;text-align:center;transform:rotate(-30deg);font-size:72px;color:rgba(160,0,0,.08);z-index:0;pointer-events:none}{% endif %}
</style></head><body>
{% if watermark %}<div class="wm">{{ data.classification|upper }}</div>{% endif %}
<div class="marking">{{ mark }}</div>
<h1>{{ data.title }}</h1>
{% if data.description %}<p>{{ data.description }}</p>{% endif %}
<p class="meta">Run {{ data.run_id }} by {{ data.runner.user_id }} at {{ data.started_at }}{% if params %}; parameters: {{ params }}{% endif %}; status: {{ data.status }}.</p>
{% for s in sections %}
<h2 id="s-{{ s.id }}">{{ s.title }}</h2>
{% if s.status_line %}<div class="status">{{ s.status_line }}</div>{% endif %}
{% if s.text %}<p>{{ s.text }}</p>{% endif %}
{% if s.kpis %}<div class="kpis">{% for k in s.kpis %}<div class="kpi"><div class="l">{{ k.label }}</div><div class="v">{{ k.display }}</div>{% if k.change_display %}<div class="c">change {{ k.change_display }} (previous {{ k.previous_display }})</div>{% endif %}</div>{% endfor %}</div>{% endif %}
{% if s.svg %}{{ s.svg|safe }}{% endif %}
{% if s.table_rows %}<table><tr>{% for h in s.table_head %}<th>{{ h }}</th>{% endfor %}</tr>
{% for r in s.table_rows %}<tr{% if loop.index0 in s.hl %} class="hl"{% endif %}>{% for c in r %}<td{% if s.numeric[loop.index0] %} class="num"{% endif %}>{{ c }}</td>{% endfor %}</tr>{% endfor %}</table>
{% if s.table.truncated %}<p class="meta">{{ s.table.rows|length }} of {{ s.table.row_count }} rows shown.</p>{% endif %}{% endif %}
{% endfor %}
<h2>Provenance</h2>
<table class="prov">{% for k, v in prov.run.items() %}{% if v %}<tr><th>{{ k }}</th><td>{{ v }}</td></tr>{% endif %}{% endfor %}</table>
{% if prov.sources %}<table class="prov"><tr><th>Section</th><th>Tool</th><th>Version</th><th>Arguments</th><th>As of</th><th>Source</th></tr>
{% for x in prov.sources %}<tr><td>{{ x.section }}</td><td>{{ x.tool }}</td><td>{{ x.version }}</td><td>{{ x.arguments }}</td><td>{{ x.as_of }}</td><td>{{ x.attribution }}</td></tr>{% endfor %}</table>{% endif %}
<div class="marking">{{ mark }}</div>
</body></html>
"""
_template = None


def to_html(data: Dict[str, Any]) -> str:
    global _template
    if _template is None:
        from jinja2 import Environment
        _template = Environment(autoescape=True).from_string(_HTML)
    secs = []
    for s in _sections(data):
        d = dict(s)
        d['status_line'] = _status_line(s)
        if s.get('table'):
            head, rows = _table_rows(s)
            d['table_head'], d['table_rows'] = head, rows
            d['numeric'] = [any(is_number(r.get(c['key'])) for r in s['table'].get('rows') or [])
                            for c in s['table'].get('columns') or []]
            d['hl'] = set((s['table'].get('highlight') or {}).get('rows') or [])
        d['svg'] = chart_svg(s) if s.get('chart') else ''
        secs.append(d)
    params = _params_text(data)
    return _template.render(data=data, sections=secs, prov=provenance(data), mark=marking(data), params=params,
                            watermark=classification_rank(str(data.get('classification'))) >= 2)


def to_pdf(data: Dict[str, Any]) -> bytes:
    page_html = to_html(data)
    mark = _html.escape(marking(data))
    tpl = f'<div style="font-size:8px;width:100%;text-align:center;color:#8a1c1c">{mark}</div>'
    foot = (f'<div style="font-size:8px;width:100%;text-align:center;color:#8a1c1c">{mark} &middot; page '
            f'<span class="pageNumber"></span> of <span class="totalPages"></span></div>')

    def make():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content(page_html, wait_until='load')
                return page.pdf(format='A4', print_background=True, display_header_footer=True,
                                header_template=tpl, footer_template=foot,
                                margin={'top': '18mm', 'bottom': '18mm', 'left': '12mm', 'right': '12mm'})
            finally:
                browser.close()
    return _in_thread(make, 120)


# ── XLSX ────────────────────────────────────────────────────────────

def _sheet_name(title: str, used: set) -> str:
    base = ''.join(ch for ch in str(title) if ch not in '[]:*?/\\')[:28] or 'Sheet'
    name, i = base, 2
    while name.lower() in used:
        name, i = f'{base[:25]} {i}', i + 1
    used.add(name.lower())
    return name


def to_xlsx(data: Dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    mark = marking(data)
    wb = Workbook()
    ws = wb.active
    used: set = set()
    ws.title = _sheet_name('Summary', used)
    bold = Font(bold=True)

    def marked(sheet):
        sheet.oddHeader.center.text = mark
        sheet.oddFooter.center.text = mark
    marked(ws)
    ws.append([mark])
    ws.append([data.get('title')])
    ws['A2'].font = Font(bold=True, size=14)
    ws.append([f'Run {data.get("run_id")} at {data.get("started_at")}; status {data.get("status")}'])
    for k, v in (data.get('parameters') or {}).items():
        ws.append([f'Parameter {k}', str(v)])
    ws.append([])
    for s in _sections(data):
        line = _status_line(s)
        if s.get('kpis') or line or s.get('text'):
            ws.append([s.get('title')])
            ws.cell(ws.max_row, 1).font = bold
        if line:
            ws.append([line])
        if s.get('text'):
            ws.append([s['text']])
        for k in s.get('kpis') or []:
            ws.append([k['label'], k.get('value') if is_number(k.get('value')) else k.get('display'), k.get('display'),
                       k.get('change') if 'change' in k else None])
    ws.column_dimensions['A'].width = 40
    ws.column_dimensions['B'].width = 22
    red = PatternFill('solid', fgColor='FDE8E8')
    for s in _sections(data):
        t = s.get('table')
        if not t or not t.get('rows'):
            continue
        sh = wb.create_sheet(_sheet_name(s.get('title') or s['id'], used))
        marked(sh)
        sh.append([mark])
        if s.get('chart'):
            sh.append([CHART_NOTE])
        cols = t.get('columns') or []
        sh.append([c['label'] for c in cols])
        for c in sh[sh.max_row]:
            c.font = bold
        hl = set((t.get('highlight') or {}).get('rows') or [])
        for i, r in enumerate(t['rows']):
            sh.append([r.get(c['key']) if is_number(r.get(c['key'])) or r.get(c['key']) is None
                       else str(r.get(c['key'])) for c in cols])
            if i in hl:
                for c in sh[sh.max_row]:
                    c.fill = red
    p = provenance(data)
    sh = wb.create_sheet(_sheet_name('Provenance', used))
    marked(sh)
    sh.append([mark])
    for k, v in p['run'].items():
        sh.append([k, str(v) if v is not None else ''])
    sh.append([])
    sh.append(['Section', 'Tool', 'Version', 'Arguments', 'As of', 'Source'])
    for c in sh[sh.max_row]:
        c.font = bold
    for x in p['sources']:
        sh.append([x['section'], x['tool'], x['version'], x['arguments'], x['as_of'], x['attribution']])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── PPTX ────────────────────────────────────────────────────────────

def to_pptx(data: Dict[str, Any], max_rows: int = 14) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    mark = marking(data)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    def stamp(slide):
        for top in (Inches(0.05), Inches(7.1)):
            tb = slide.shapes.add_textbox(Inches(0.3), top, Inches(12.7), Inches(0.3))
            tb.text_frame.text = mark
            tb.text_frame.paragraphs[0].runs[0].font.size = Pt(10)

    def titled(title):
        slide = prs.slides.add_slide(prs.slide_layouts[5])
        slide.shapes.title.text = str(title)[:120]
        stamp(slide)
        return slide

    def table(slide, head, rows, top=Inches(1.5)):
        rows = rows[:max_rows]
        shape = slide.shapes.add_table(len(rows) + 1, len(head), Inches(0.4), top, Inches(12.5),
                                       Inches(0.3) * (len(rows) + 1))
        tb = shape.table
        for j, h in enumerate(head):
            tb.cell(0, j).text = str(h)
        for i, r in enumerate(rows, 1):
            for j, c in enumerate(r):
                tb.cell(i, j).text = str(c)
        for row in tb.rows:
            for cell in row.cells:
                for para in cell.text_frame.paragraphs:
                    for run in para.runs:
                        run.font.size = Pt(10)
    first = prs.slides.add_slide(prs.slide_layouts[0])
    first.shapes.title.text = str(data.get('title'))
    first.placeholders[1].text = f'Run {data.get("run_id")}\n{data.get("started_at")}'
    stamp(first)
    for s in _sections(data):
        slide = titled(s.get('title') or s['id'])
        notes = [x for x in (_status_line(s), s.get('text'), CHART_NOTE if s.get('chart') else None) if x]
        top = Inches(1.4)
        if notes:
            tb = slide.shapes.add_textbox(Inches(0.4), top, Inches(12.5), Inches(0.6))
            tb.text_frame.word_wrap = True
            tb.text_frame.text = '\n'.join(notes)[:1500]
            top = Inches(2.1)
        if s.get('kpis'):
            table(slide, *_kpi_rows(s), top=top)
        elif (s.get('table') or {}).get('rows'):
            head, rows = _table_rows(s)
            table(slide, head, rows, top=top)
            if len(rows) > max_rows:
                tb = slide.shapes.add_textbox(Inches(0.4), Inches(6.7), Inches(12), Inches(0.3))
                tb.text_frame.text = f'{max_rows} of {len(rows)} rows shown; the XLSX has every row.'
    p = provenance(data)
    slide = titled('Provenance')
    table(slide, ['Section', 'Tool', 'Version', 'As of', 'Source'],
          [[x['section'], x['tool'], x['version'], x['as_of'], x['attribution']] for x in p['sources']] or
          [['', '', '', '', '']])
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ── DOCX ────────────────────────────────────────────────────────────

def to_docx(data: Dict[str, Any]) -> bytes:
    from docx import Document
    mark = marking(data)
    doc = Document()
    sec = doc.sections[0]
    sec.header.paragraphs[0].text = mark
    sec.footer.paragraphs[0].text = mark

    def table(head, rows):
        t = doc.add_table(rows=1, cols=len(head))
        t.style = 'Table Grid'
        for j, h in enumerate(head):
            t.rows[0].cells[j].text = str(h)
        for r in rows:
            cells = t.add_row().cells
            for j, c in enumerate(r):
                cells[j].text = str(c)
    doc.add_heading(str(data.get('title')), 0)
    if data.get('description'):
        doc.add_paragraph(data['description'])
    doc.add_paragraph(f'Run {data.get("run_id")} by {(data.get("runner") or {}).get("user_id")} at '
                      f'{data.get("started_at")}; status {data.get("status")}.')
    for s in _sections(data):
        doc.add_heading(str(s.get('title') or s['id']), 1)
        line = _status_line(s)
        if line:
            doc.add_paragraph(line)
        if s.get('text'):
            doc.add_paragraph(s['text'])
        if s.get('kpis'):
            table(*_kpi_rows(s))
        if (s.get('table') or {}).get('rows'):
            if s.get('chart'):
                doc.add_paragraph(CHART_NOTE)
            table(*_table_rows(s))
    p = provenance(data)
    doc.add_heading('Provenance', 1)
    table(['Item', 'Value'], [[k, str(v)] for k, v in p['run'].items() if v not in (None, '')])
    if p['sources']:
        doc.add_paragraph('')
        table(['Section', 'Tool', 'Version', 'Arguments', 'As of', 'Source'],
              [[x['section'], x['tool'], x['version'], x['arguments'], x['as_of'], x['attribution']]
               for x in p['sources']])
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


_RENDERERS = {'markdown': to_markdown, 'html': to_html, 'pdf': to_pdf, 'xlsx': to_xlsx, 'pptx': to_pptx,
              'docx': to_docx}


def render(data: Dict[str, Any], fmt: str):
    """``data`` as ``fmt``: str for Markdown and HTML, bytes otherwise. Raises ValueError when unavailable."""
    why = unavailable(fmt)
    if why:
        raise ValueError(why)
    return _RENDERERS[fmt](data)
