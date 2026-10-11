# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""bi_chart (sajha/tools/impl/bi_chart_tools.py; docs/architecture/Business Intelligence.md §5): the spec and
the SVG of every kind against golden files, escaping of text from the data, the refusals, rows from a
bi_* call made as the caller and from a SELECT over the caller's loaded tables, and the MCP Apps view.

Golden files are in tests/fixtures/bi_chart/; after an intended change to the renderer regenerate them
with ``SAJHA_UPDATE_GOLDEN=1 .venv/bin/python -m pytest tests/test_bi_chart.py`` and look at the SVGs."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from sajha.core.inner_calls import InnerCallRefused
from sajha.observability.caller import Caller, reset as reset_caller, set_caller
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.impl.bi_chart_tools import (BIChartTool, ChartError, KINDS, VIEW_URI, build_spec, esc,
                                             nice_ticks, render_svg)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / 'fixtures' / 'bi_chart'
SVGNS = '{http://www.w3.org/2000/svg}'

MONTHS = [{'month': f'2025-{i:02d}-01', 'region': r, 'sales': v}
          for i, (e, w) in enumerate([(10, 5), (14, 3), (9, 7), (20, 8), (18, 12), (25, 6)], 1)
          for r, v in (('East', e), ('West', w))]
CASES = {
    'line': (MONTHS, dict(x='month', y='sales', series='region', title='Sales by month')),
    'bar': (MONTHS, dict(x='month', y='sales', series='region')),
    'area': (MONTHS, dict(x='month', y='sales', series='region')),
    'scatter': ([{'price': p, 'units': (p * 7) % 11} for p in range(1, 13)], dict(x='price', y='units')),
    'heatmap': (MONTHS, dict(x='month', y='region', value='sales')),
    'waterfall': ([{'step': s, 'change': c} for s, c in [('Q2', 100), ('Price', 20), ('Volume', -35), ('Mix', 8)]],
                  dict(x='step', y='change', title='Revenue bridge')),
    'pareto': ([{'cause': c, 'count': n} for c, n in [('A', 5), ('B', 30), ('C', 12), ('D', 3), ('E', 50)]],
               dict(x='cause', y='count')),
}


def _tool(registry=None):
    cfg = json.loads((ROOT / 'config/tools/bi/bi_chart.json').read_text())
    t = BIChartTool(cfg)
    t.registry = registry
    return t


@pytest.mark.parametrize('kind', KINDS)
def test_spec_and_svg_match_the_golden_files(kind):
    rows, kw = CASES[kind]
    spec, _ = build_spec(rows, kind, **kw)
    svg = render_svg(spec)
    ET.fromstring(svg)                                        # well-formed XML
    got_spec = json.dumps(spec, indent=1, sort_keys=True) + '\n'
    if os.environ.get('SAJHA_UPDATE_GOLDEN'):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        (GOLDEN / f'{kind}.spec.json').write_text(got_spec)
        (GOLDEN / f'{kind}.svg').write_text(svg + '\n')
    assert got_spec == (GOLDEN / f'{kind}.spec.json').read_text()
    assert svg + '\n' == (GOLDEN / f'{kind}.svg').read_text()
    assert spec['usermeta']['kind'] == kind and spec['data']['values']


def test_spec_details_per_kind():
    spec, info = build_spec(*CASES['waterfall'][:1], 'waterfall', **CASES['waterfall'][1])
    vals = spec['data']['values']
    assert [v['_kind'] for v in vals] == ['increase', 'increase', 'decrease', 'increase', 'total']
    assert vals[-1]['step'] == 'Total' and vals[-1]['_end'] == 93 and info['rows'] == 4
    assert spec['encoding']['y2'] == {'field': '_end'}
    spec, _ = build_spec(*CASES['pareto'][:1], 'pareto', **CASES['pareto'][1])
    vals = spec['data']['values']
    assert [v['cause'] for v in vals] == ['E', 'B', 'C', 'A', 'D'] and vals[-1]['_cumulative_pct'] == 100
    assert spec['resolve'] == {'scale': {'y': 'independent'}} and len(spec['layer']) == 2
    spec, _ = build_spec(MONTHS, 'line', 'month', 'sales', 'region')
    assert spec['encoding']['x']['type'] == 'temporal'
    assert spec['encoding']['color']['scale']['domain'] == ['East', 'West']
    spec, _ = build_spec(MONTHS, 'bar', 'month', 'sales', 'region')
    assert spec['encoding']['xOffset']['field'] == 'region' and spec['encoding']['x']['type'] == 'nominal'
    # duplicates at one x are summed for bars, and counted
    spec, info = build_spec([{'k': 'a', 'v': 1}, {'k': 'a', 'v': 2}, {'k': 'b', 'v': None}], 'bar', 'k', 'v')
    assert spec['data']['values'] == [{'k': 'a', 'v': 3.0}] and info['combined'] == 1 and info['skipped'] == 1


EVIL = '</text><script>alert(1)</script><a href="javascript:x()">&\x00'


@pytest.mark.parametrize('kind', KINDS)
def test_text_from_the_data_is_escaped(kind):
    rows = [{'c': EVIL, 'y2': 'East " onload="x()', 'v': 3}, {'c': 'ok', 'y2': 'West', 'v': 4}]
    kw = dict(x='c', y='y2', value='v') if kind == 'heatmap' else dict(x='c', y='v')
    if kind == 'line':
        kw['series'] = 'y2'
    spec, _ = build_spec(rows, kind, title=EVIL, **kw)
    svg = render_svg(spec)
    root = ET.fromstring(svg)                                  # still well-formed: nothing broke out
    tags = {el.tag.replace(SVGNS, '') for el in root.iter()}
    assert tags <= {'svg', 'style', 'title', 'rect', 'text', 'g', 'line', 'path', 'circle'}
    assert '<script' not in svg and '<a ' not in svg and 'onload=' not in svg.replace('onload=&quot;', '')
    for el in root.iter():
        for name, value in el.attrib.items():
            assert not name.lower().startswith('on') and 'href' not in name
            assert name == 'aria-label' or 'javascript:' not in value     # aria-label is the escaped title
    texts = [el.text for el in root.iter(SVGNS + 'text')]
    assert any('</text><script>' in (t or '') for t in texts)     # shown as text, escaped in the markup


def test_esc():
    assert esc('<a & "b" \'c\'>\x07') == '&lt;a &amp; &quot;b&quot; &#39;c&#39;&gt;'


def test_nice_ticks():
    assert nice_ticks(0, 93) == [0, 20, 40, 60, 80, 100]
    assert nice_ticks(-35, 120) == [-50, 0, 50, 100, 150]
    assert nice_ticks(5, 5)[0] <= 5 <= nice_ticks(5, 5)[-1]
    assert nice_ticks(0, 0) == [0, 0.2, 0.4, 0.6, 0.8, 1]


@pytest.mark.parametrize('rows,kind,kw,fragment', [
    ([], 'bar', dict(x='a', y='b'), 'no rows'),
    ([{'a': 1, 'b': 2}], 'pie', dict(x='a', y='b'), 'kind must be'),
    ([{'a': 1, 'b': 2}], 'bar', dict(x='zz', y='b'), "'zz' is not a column"),
    ([{'a': 'x', 'b': 'lots'}], 'bar', dict(x='a', y='b'), 'must be numbers'),
    ([{'a': 'x', 'b': -1}], 'pareto', dict(x='a', y='b'), 'zero or more'),
    ([{'a': 'x', 'b': 1, 's': 'q'}], 'waterfall', dict(x='a', y='b', series='s'), 'one series'),
    ([{'a': 'x', 'b': 'y'}], 'heatmap', dict(x='a', y='b'), 'value'),
    ([{'a': 1, 'b': 1, 's': i} for i in range(13)], 'line', dict(x='a', y='b', series='s'), 'more than 12'),
    ([{'a': i, 'b': 1} for i in range(5001)], 'line', dict(x='a', y='b'), 'more than 5000'),
])
def test_refusals_say_why(rows, kind, kw, fragment):
    with pytest.raises(ChartError, match=fragment):
        build_spec(rows, kind, **kw)


# ── the tool: its three sources of rows ─────────────────────────────

class _Rows(BaseMCPTool):
    def __init__(self, name):
        super().__init__({'name': name, 'description': 'test rows', 'inputSchema': {'type': 'object', 'properties': {}}})
        self.calls = []

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {}

    def execute(self, arguments):
        from sajha.observability.caller import current
        self.calls.append(current().user_id)
        return {'as_of': '2025-06-30', 'rows': [{'region': 'East', 'sales': 1}, {'region': 'West', 'sales': 2}]}


class _Reg:
    def __init__(self, *tools):
        self.tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self.tools.get(name)


def _as(user, allowed=None):
    access = None if allowed is None else (lambda n: n in allowed)
    return set_caller(Caller(user, '', ('user',), 'session', access))


def test_execute_with_rows_returns_spec_svg_and_view():
    out = _tool().execute({'kind': 'bar', 'x': 'region', 'y': 'sales',
                           'data': [{'region': 'East', 'sales': 120}, {'region': 'West', 'sales': 95}]})
    assert out['view'] == VIEW_URI and out['rows'] == 2 and out['source'] == {'from': 'rows'}
    assert out['svg'].startswith('<svg ') and out['spec']['mark']['type'] == 'bar'
    cfg = json.loads((ROOT / 'config/tools/bi/bi_chart.json').read_text())
    assert cfg['_meta']['ui']['resourceUri'] == VIEW_URI
    assert cfg['annotations']['readOnlyHint'] is True and cfg['annotations']['openWorldHint'] is False


def test_data_from_a_bi_tool_runs_as_the_caller_and_only_if_they_may():
    src = _Rows('bi_fake_rows')
    tool = _tool(_Reg(src))
    t = _as('alice', allowed={'bi_chart', 'bi_fake_rows'})
    try:
        out = tool.execute({'kind': 'bar', 'x': 'region', 'y': 'sales', 'data': {'tool': 'bi_fake_rows', 'arguments': {}}})
    finally:
        reset_caller(t)
    assert out['rows'] == 2 and out['source']['tool'] == 'bi_fake_rows' and src.calls == ['alice']
    t = _as('bob', allowed={'bi_chart'})
    try:
        with pytest.raises(InnerCallRefused, match='no such tool, or you may not call it'):
            tool.execute({'kind': 'bar', 'x': 'region', 'y': 'sales', 'data': {'tool': 'bi_fake_rows'}})
        with pytest.raises(InnerCallRefused, match='no such tool, or you may not call it'):
            tool.execute({'kind': 'bar', 'x': 'region', 'y': 'sales', 'data': {'tool': 'bi_missing'}})
    finally:
        reset_caller(t)
    assert src.calls == ['alice']
    with pytest.raises(ChartError, match='bi_\\* analysis tool'):
        tool.execute({'kind': 'bar', 'x': 'a', 'y': 'b', 'data': {'tool': 'fred_get_series'}})


def test_mcp_app_view_is_bundled_self_contained_and_never_uses_innerhtml():
    from sajha.core import mcp_apps
    views = mcp_apps.ui_views()
    assert VIEW_URI in views
    html = (ROOT / 'sajha/core/mcp_app_views/bi_chart.html').read_text()
    assert len(html.encode()) < 2 * 1024 * 1024
    assert 'innerHTML' not in html.replace('never innerHTML', '') and 'outerHTML' not in html
    assert '<script src' not in html and 'fetch(' not in html and 'XMLHttpRequest' not in html
    assert 'http://' not in html.replace('http://www.w3.org/2000/svg', '') and 'https://' not in html
    meta = mcp_apps.tool_ui_meta(json.loads((ROOT / 'config/tools/bi/bi_chart.json').read_text()), 'bi_chart')
    assert meta and meta['resourceUri'] == VIEW_URI
