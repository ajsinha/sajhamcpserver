"""
SAJHA MCP Server — comparing two stored runs of a report, section by section.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Compares what was stored (no tool is called): KPIs by label with their change and percent
change; table rows by key (the section's ``key`` column, else its first column) as added,
removed and changed (with the changed cells); and sections whose status differs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sajha.reports.values import display, is_number


def _kpis(sec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {k.get('key') or k['label']: k for k in sec.get('kpis') or []}


def _row_key(table: Dict[str, Any]) -> Optional[str]:
    if table.get('key'):
        return table['key']
    cols = table.get('columns') or []
    return cols[0]['key'] if cols else None


def _rows(table: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    key = _row_key(table)
    out: Dict[str, Dict[str, Any]] = {}
    for i, r in enumerate(table.get('rows') or []):
        k = str(r.get(key)) if key else str(i)
        if k in out:
            k = f'{k}#{i}'
        out[k] = r
    return out


def compare_sections(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {'id': b.get('id') or a.get('id'), 'title': b.get('title') or a.get('title')}
    if a.get('status') != b.get('status'):
        out['status'] = {'a': a.get('status'), 'b': b.get('status')}
    ka, kb = _kpis(a), _kpis(b)
    kpis = []
    for key in list(dict.fromkeys(list(ka) + list(kb))):
        x, y = ka.get(key), kb.get(key)
        item: Dict[str, Any] = {'label': (y or x)['label'], 'a': (x or {}).get('value'), 'b': (y or {}).get('value')}
        spec = {'format': (y or x).get('format'), 'decimals': (y or x).get('decimals'), 'currency': (y or x).get('currency')}
        if is_number(item['a']) and is_number(item['b']):
            ch = item['b'] - item['a']
            item['change'] = ch
            item['change_display'] = display(ch, spec)
            if item['a']:
                item['pct_change'] = ch / abs(item['a']) * 100.0
                item['pct_change_display'] = display(item['pct_change'], {'format': 'percent'})
        kpis.append(item)
    if kpis:
        out['kpis'] = kpis
    ta, tb = a.get('table') or {}, b.get('table') or {}
    if ta or tb:
        ra, rb = _rows(ta), _rows(tb)
        changed = []
        for k in ra:
            if k in rb and ra[k] != rb[k]:
                cells = {}
                for c in set(ra[k]) | set(rb[k]):
                    va, vb = ra[k].get(c), rb[k].get(c)
                    if va != vb:
                        cell: Dict[str, Any] = {'a': va, 'b': vb}
                        if is_number(va) and is_number(vb):
                            cell['change'] = vb - va
                        cells[c] = cell
                changed.append({'key': k, 'cells': cells})
        out['rows'] = {'key_column': _row_key(tb or ta), 'added': [rb[k] for k in rb if k not in ra],
                       'removed': [ra[k] for k in ra if k not in rb], 'changed': changed,
                       'unchanged': sum(1 for k in ra if k in rb and ra[k] == rb[k])}
    return out


def compare_runs(run_a: Dict[str, Any], run_b: Dict[str, Any]) -> Dict[str, Any]:
    sa = {s['id']: s for s in run_a.get('sections') or []}
    sb = {s['id']: s for s in run_b.get('sections') or []}
    sections: List[Dict[str, Any]] = []
    for sid in list(dict.fromkeys(list(sa) + list(sb))):
        if sid not in sa:
            sections.append({'id': sid, 'title': sb[sid].get('title'), 'only_in': 'b'})
        elif sid not in sb:
            sections.append({'id': sid, 'title': sa[sid].get('title'), 'only_in': 'a'})
        else:
            sections.append(compare_sections(sa[sid], sb[sid]))
    return {'report': run_b.get('report') or run_a.get('report'),
            'a': {'run_id': run_a.get('run_id'), 'started_at': run_a.get('started_at'),
                  'parameters': run_a.get('parameters')},
            'b': {'run_id': run_b.get('run_id'), 'started_at': run_b.get('started_at'),
                  'parameters': run_b.get('parameters')},
            'same_definition': run_a.get('definition_hash') == run_b.get('definition_hash'),
            'sections': sections}
