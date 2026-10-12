"""
SAJHA MCP Server — the report run engine.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

:func:`run_report` runs a definition **as the caller**: every section's tool call is an ordinary
``execute_with_tracking`` call made with the caller context of the request (so tool access,
policy rules, approvals, budgets, rate limits, per-user credentials and connected accounts apply
section by section, and the usage ledger and audit chain see the caller). A section the caller
may not call renders "not permitted"; a tool the server lacks renders "unavailable"; a failing
tool renders its error. None of these fails the report: its status is then ``partial``.

The run then computes the quantities a narrator may cite (values, changes against the previous
run with the same parameters, shares and ranks), stores the report data and renders the
requested formats (sajha/reports/render.py). The report data shape is documented in
sajha/reports/__init__.py.
"""

from __future__ import annotations

import concurrent.futures as cf
import copy
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sajha.reports import history, settings
from sajha.reports.model import (CLASSIFICATIONS, ReportDefinition, higher_classification, section_call)
from sajha.reports.values import decimals_for, display, displayed_value, is_number, to_number

logger = logging.getLogger(__name__)

_pool = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix='report-section')
_REF_RE = re.compile(r'^\$(params|sections|run)\.(.+)$')
_INTERP_RE = re.compile(r'\$\{(params|run)\.([A-Za-z0-9_]+)\}')
ATTRIBUTION_KEYS = ('source', 'attribution', 'licence', 'license', 'citation')
AS_OF_KEYS = ('as_of', 'asof', 'as_of_date', 'last_updated', 'updated', 'retrieved_at', 'timestamp', 'date')
OK_STATES = ('ok', 'empty', 'text', 'pending_narration')
#: classification a result gets when its tool marks data classes on its results (residency marks)
DATA_CLASS_FLOOR = 'confidential'
#: tests may replace the registry lookup: name -> tool or None
_registry_override = None


class ReportRunError(RuntimeError):
    """A run that could not start (disabled report, bad parameters, no access)."""


def set_registry(registry) -> None:
    global _registry_override
    _registry_override = registry


def _registry():
    if _registry_override is not None:
        return _registry_override
    from sajha.tools.tools_registry import get_tools_registry
    return get_tools_registry()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── access ──────────────────────────────────────────────────────────

def may_run(defn: ReportDefinition, caller) -> Optional[str]:
    """Why the caller may not run the report (None: it may)."""
    if not settings.enabled():
        return 'reports are turned off on this server (reports.enabled)'
    if not defn.enabled:
        return f'report {defn.name} is disabled'
    if defn.roles and not getattr(caller, 'is_admin', False) \
            and not set(defn.roles) & set(getattr(caller, 'roles', ()) or ()):
        return f'report {defn.name} is for the roles {", ".join(defn.roles)}'
    ok = caller.can_execute(defn.tool_name) if hasattr(caller, 'can_execute') else None
    if ok is False:
        return f'the caller {getattr(caller, "user_id", "?")!r} may not run {defn.tool_name}'
    return None


# ── parameters and references ───────────────────────────────────────

def _run_values(started: datetime) -> Dict[str, Any]:
    return {'date': started.date().isoformat(), 'year': started.year,
            'time': started.isoformat(timespec='seconds')}


def resolve_parameters(defn: ReportDefinition, given: Dict[str, Any], started: datetime) -> Dict[str, Any]:
    """Defaults filled (``$run.*`` defaults resolved), then validated against the parameters' schema."""
    params = {k: v for k, v in dict(given or {}).items() if k not in ('formats', 'deliver')}
    runv = _run_values(started)
    for k, spec in defn.parameters.items():
        if k not in params and 'default' in spec:
            d = copy.deepcopy(spec['default'])
            if isinstance(d, str) and d.startswith('$run.') and d[5:] in runv:
                d = runv[d[5:]]
            params[k] = d
    schema = {'type': 'object', 'properties': defn.parameters, 'additionalProperties': False}
    if defn.required:
        schema['required'] = defn.required
    try:
        import jsonschema
        errs = sorted(jsonschema.Draft202012Validator(schema).iter_errors(params), key=lambda e: list(e.path))
    except ImportError:
        errs = []
    if errs:
        e = errs[0]
        where = '.'.join(str(x) for x in e.path)
        raise ReportRunError(f'invalid parameters for {defn.name}: {(where + ": ") if where else ""}{e.message}')
    return params


def _resolve(value: Any, ctx: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        m = _REF_RE.match(value)
        if not m:
            return _INTERP_RE.sub(lambda mm: str(ctx[mm.group(1)].get(mm.group(2), mm.group(0))), value)
        kind, rest = m.groups()
        if kind == 'params':
            return copy.deepcopy(ctx['params'].get(rest))
        if kind == 'run':
            return ctx['run'].get(rest)
        sid, _, path = rest.partition('.')
        result = ctx['results'].get(sid)
        if not path:
            return copy.deepcopy(result)
        from sajha.quality.jsonpath import find
        found = find(result, '$.' + path if not path.startswith('[') else '$' + path)
        return copy.deepcopy(found[0]) if len(found) == 1 else copy.deepcopy(found) if found else None
    if isinstance(value, dict):
        return {k: _resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve(v, ctx) for v in value]
    return value


# ── a tool's result ─────────────────────────────────────────────────

def unwrap(result: Any) -> Tuple[Any, Optional[str]]:
    """(structured value, error) of a tool result: CallToolResult-shaped results are opened."""
    if isinstance(result, dict):
        if result.get('isError') is True:
            texts = [c.get('text', '') for c in result.get('content') or [] if isinstance(c, dict)]
            return None, ' '.join(t for t in texts if t) or 'the tool reported an error'
        if set(result) == {'error'} or (result.get('success') is False and result.get('error')):
            return None, str(result.get('error'))
        if isinstance(result.get('structuredContent'), (dict, list)):
            return result['structuredContent'], None
        if 'content' in result and isinstance(result.get('content'), list) and set(result) <= {'content', '_meta', 'isError'}:
            import json
            for c in result['content']:
                if isinstance(c, dict) and c.get('type') == 'text':
                    try:
                        return json.loads(c.get('text') or ''), None
                    except ValueError:
                        return {'text': c.get('text')}, None
    return result, None


def attribution_of(value: Any) -> str:
    if not isinstance(value, dict):
        return ''
    parts = []
    for k in ATTRIBUTION_KEYS:
        v = value.get(k)
        if isinstance(v, str) and v.strip() and v.strip() not in parts:
            parts.append(v.strip())
        elif isinstance(v, dict):
            s = v.get('name') or v.get('title') or v.get('citation')
            if isinstance(s, str) and s.strip():
                parts.append(s.strip())
    return '; '.join(parts)[:500]


def as_of_of(value: Any) -> str:
    if isinstance(value, dict):
        for k in AS_OF_KEYS:
            v = value.get(k)
            if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip():
                return str(v)
    return ''


def _data_classes(tool) -> List[str]:
    try:
        from sajha.net.integration.residency import catalog_summary
        return sorted(set(catalog_summary(tool).get('results') or []))
    except Exception:
        return []


# ── presenting a result ─────────────────────────────────────────────

def _find(value: Any, path: str) -> List[Any]:
    from sajha.quality.jsonpath import find
    try:
        return find(value, path)
    except Exception:
        return []


def _slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(s).lower()).strip('_')[:48] or 'value'


def build_kpis(value: Any, specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for spec in specs:
        found = _find(value, spec['path'])
        v = found[0] if found else None
        if spec.get('format') not in ('text', 'date') and not is_number(v) and to_number(v) is not None:
            v = to_number(v)
        out.append({'label': spec['label'], 'key': _slug(spec['label']), 'path': spec['path'],
                    'format': spec.get('format', 'number'), 'decimals': decimals_for(spec, v),
                    **({'currency': spec['currency']} if spec.get('currency') else {}),
                    'value': v, 'display': display(v, spec) if v is not None else 'n/a'})
    return out


def _columns(spec_cols: Optional[List[Any]], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if spec_cols:
        out = []
        for c in spec_cols:
            if isinstance(c, str):
                out.append({'key': c, 'label': c})
            else:
                key = c.get('key') or _slug(c.get('label') or c.get('path'))
                out.append({k: v for k, v in dict(c, key=key, label=c.get('label') or key).items()})
        return out
    keys: List[str] = []
    for r in rows[:20]:
        for k, v in r.items():
            if k not in keys and not isinstance(v, (dict, list)):
                keys.append(k)
    return [{'key': k, 'label': k} for k in keys[:12]]


def build_table(value: Any, s: Dict[str, Any]) -> Dict[str, Any]:
    rows_raw = _find(value, s['rows'])
    if len(rows_raw) == 1 and isinstance(rows_raw[0], list):
        rows_raw = rows_raw[0]
    rows_in = [r if isinstance(r, dict) else {'value': r} for r in rows_raw]
    cols = _columns(s.get('columns'), rows_in)
    limit = min(int(s.get('limit') or settings.max_table_rows()), settings.max_table_rows())
    rows = []
    for r in rows_in[:limit]:
        row = {}
        for c in cols:
            if c.get('path'):
                f = _find(r, c['path'])
                v = f[0] if f else None
            else:
                v = r.get(c['key'])
            if c.get('format') in ('number', 'integer', 'percent', 'ratio', 'currency', 'bps') and not is_number(v):
                n = to_number(v)
                v = n if n is not None else v
            row[c['key']] = v
        rows.append(row)
    table = {'columns': [{'key': c['key'], 'label': c['label'], 'format': c.get('format'),
                          **({'decimals': c['decimals']} if isinstance(c.get('decimals'), int) else {}),
                          **({'currency': c['currency']} if c.get('currency') else {})} for c in cols],
             'rows': rows, 'row_count': len(rows_in), 'truncated': len(rows_in) > len(rows)}
    hl = s.get('highlight')
    if isinstance(hl, dict):
        marked = []
        for i, r in enumerate(rows):
            v = to_number(r.get(hl['column']))
            if v is None:
                continue
            if (is_number(hl.get('above')) and v > hl['above']) or (is_number(hl.get('below')) and v < hl['below']):
                marked.append(i)
        table['highlight'] = {'column': hl['column'], 'rows': marked,
                              **{k: hl[k] for k in ('above', 'below') if k in hl}}
    if s.get('key'):
        table['key'] = s['key']
    return table


def _auto(value: Any) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """A metric tile with no presentation given: top-level numbers as KPIs, the first list of rows as a table."""
    kpis, table = [], None
    if isinstance(value, dict):
        for k, v in value.items():
            if is_number(v) and len(kpis) < 12:
                kpis.append({'label': k, 'path': f'$.{k}' if re.match(r'^[A-Za-z_]\w*$', k) else f"$['{k}']"})
        for k, v in value.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                table = build_table(value, {'rows': f"$['{k}'][*]"})
                break
    elif isinstance(value, list) and value and isinstance(value[0], dict):
        table = build_table(value, {'rows': '$[*]'})
    return (build_kpis(value, kpis) if kpis else []), table


def _present(sec: Dict[str, Any], s: Dict[str, Any], value: Any) -> None:
    kind = s['kind']
    if kind == 'kpis':
        sec['kpis'] = build_kpis(value, s['values'])
    elif kind in ('table', 'chart'):
        sec['table'] = build_table(value, s)
    elif kind == 'metric':
        if s.get('values'):
            sec['kpis'] = build_kpis(value, s['values'])
        if s.get('rows'):
            sec['table'] = build_table(value, s)
        if not s.get('values') and not s.get('rows'):
            kpis, table = _auto(value)
            if kpis:
                sec['kpis'] = kpis
            if table:
                sec['table'] = table
        visual = (s.get('tile') or {}).get('visual')
        if visual in ('bar', 'line') and sec.get('table'):
            cols = sec['table']['columns']
            numeric = [c['key'] for c in cols[1:] if any(is_number(r.get(c['key'])) for r in sec['table']['rows'])]
            if cols and numeric:
                sec['chart'] = {'type': visual, 'x': cols[0]['key'], 'y': numeric[:4]}
    if kind == 'chart':
        y = s['y'] if isinstance(s['y'], list) else [s['y']]
        sec['chart'] = {'type': s.get('type', 'bar'), 'x': s['x'], 'y': y}
    has_kpis = any(k.get('value') is not None for k in sec.get('kpis') or [])
    has_rows = bool((sec.get('table') or {}).get('rows'))
    if not has_kpis and not has_rows:
        sec['status'] = 'empty'


# ── one section ─────────────────────────────────────────────────────

def _call(tool, args: Dict[str, Any]) -> Tuple[Any, Dict[str, Any]]:
    from sajha.quality.versions import collect_meta
    with collect_meta() as meta:
        result = tool.execute_with_tracking(args)
    return result, dict(meta)


def _section_call(sec: Dict[str, Any], s: Dict[str, Any], ctx: Dict[str, Any], deadline: float) -> Any:
    from sajha.core import inner_calls
    call = section_call(s)
    name = call['tool']
    try:
        args = _resolve(call.get('arguments') or {}, ctx)
    except Exception as e:
        sec.update(status='error', error=f'arguments could not be resolved: {e}')
        return None
    called_at = _now().isoformat(timespec='seconds')
    sec['source'] = {'tool': name, 'arguments': args, 'called_at': called_at}
    tool = ctx['registry'].get_tool(name)
    if tool is None:
        sec.update(status='unavailable', error=f'the tool {name} is not available on this server')
        return None
    sec['source']['version'] = str(getattr(tool, 'version', '') or '')
    if not inner_calls.caller_may_run(name):
        sec.update(status='not_permitted', error=f'the caller may not run {name}')
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        sec.update(status='skipped', error=f'the run passed reports.max_run_seconds ({settings.max_run_seconds()}s)')
        return None
    from sajha.policy.errors import PolicyError
    fut = _pool.submit(inner_calls.in_context(_call, tool, dict(args)))
    try:
        result, meta = fut.result(timeout=remaining)
    except cf.TimeoutError:
        sec.update(status='error', error=f'{name} did not answer within the run budget '
                                         f'(reports.max_run_seconds {settings.max_run_seconds()}s)')
        return None
    except PolicyError as e:
        kind = getattr(e, 'kind', 'denied')
        sec.update(status='not_permitted', error=f'blocked by policy ({kind}): {e}')
        return None
    except inner_calls.InnerCallRefused as e:
        sec.update(status='not_permitted', error=str(e))
        return None
    except Exception as e:
        sec.update(status='error', error=f'{e.__class__.__name__}: {e}'[:1000])
        return None
    ver = meta.get('io.sajha/tool-version')
    if isinstance(ver, dict):
        ver = ver.get('version') or ver.get('served') or ''
    if ver:
        sec['source']['version'] = str(ver)
    value, err = unwrap(result)
    if err:
        sec.update(status='error', error=err[:1000])
        return None
    sec['source']['as_of'] = as_of_of(value) or called_at
    sec['source']['attribution'] = attribution_of(value)
    classes = _data_classes(tool)
    if classes:
        sec['source']['data_classes'] = classes
    return value


def _run_sections(defn: ReportDefinition, ctx: Dict[str, Any], deadline: float, prefix: str = '',
                  title_prefix: str = '') -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in defn.sections:
        sid = prefix + s['id']
        sec: Dict[str, Any] = {'id': sid, 'kind': s['kind'], 'title': title_prefix + (s.get('title') or s['id']),
                               'status': 'ok'}
        if s.get('description'):
            sec['description'] = str(s['description'])
        if s['kind'] == 'text':
            if isinstance(s.get('narrate'), dict):
                sec.update(status='pending_narration', text='',
                           narrate={**s['narrate'], 'sections': [prefix + x for x in s['narrate'].get('sections') or []]})
            else:
                sec.update(status='text', text=_resolve(s['text'], ctx))
            out.append(sec)
            continue
        if s['kind'] == 'report':
            sub = ctx['definitions'].get(s['report']['name'])
            if sub is None:
                sec.update(status='unavailable', error=f'sub-report {s["report"]["name"]} is not available')
                out.append(sec)
                continue
            try:
                sub_params = resolve_parameters(sub, _resolve(s['report'].get('parameters') or {}, ctx),
                                                ctx['started'])
            except ReportRunError as e:
                sec.update(status='error', error=str(e))
                out.append(sec)
                continue
            sub_ctx = dict(ctx, params=sub_params, results={})
            sec.update(status='text', text=f'Sub-report {sub.title}', report={'name': sub.name, 'parameters': sub_params})
            out.append(sec)
            out.extend(_run_sections(sub, sub_ctx, deadline, prefix=f'{sid}.', title_prefix=f'{sub.title}: '))
            continue
        value = _section_call(sec, s, ctx, deadline)
        if sec['status'] == 'ok':
            ctx['results'][s['id']] = value
            try:
                _present(sec, s, value)
            except Exception as e:
                sec.update(status='error', error=f'the result could not be presented: {e}')
        out.append(sec)
    return out


# ── quantities ──────────────────────────────────────────────────────

def _q(qid: str, section: str, label: str, kind: str, value: float, spec: Dict[str, Any], **extra) -> Dict[str, Any]:
    d = decimals_for(spec, value)
    return {'id': qid, 'section': section, 'label': label, 'kind': kind, 'value': value,
            'display': display(value, spec), 'decimals': d, 'format': spec.get('format') or 'number', **extra}


def quantities(sections: List[Dict[str, Any]], previous: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every figure the report shows, and the comparisons it computed (Reports.md §5)."""
    out: List[Dict[str, Any]] = []
    prev_kpis: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for ps in (previous or {}).get('sections') or []:
        for k in ps.get('kpis') or []:
            prev_kpis[(ps['id'], k.get('key') or _slug(k['label']))] = k
    for sec in sections:
        sid = sec['id']
        for k in sec.get('kpis') or []:
            v = k.get('value')
            if not is_number(v):
                continue
            spec = {'format': k.get('format'), 'decimals': k.get('decimals'), 'currency': k.get('currency')}
            out.append(_q(f'{sid}.{k["key"]}', sid, k['label'], 'value', v, spec))
            p = prev_kpis.get((sid, k['key']))
            if p and is_number(p.get('value')):
                pv = p['value']
                against = previous.get('run_id')
                out.append(_q(f'{sid}.{k["key"]}.previous', sid, k['label'], 'previous', pv, spec, against=against))
                out.append(_q(f'{sid}.{k["key"]}.change', sid, k['label'], 'change', v - pv, spec, against=against))
                if pv:
                    pct = (v - pv) / abs(pv) * 100.0
                    out.append(_q(f'{sid}.{k["key"]}.pct_change', sid, k['label'], 'pct_change', pct,
                                  {'format': 'percent'}, against=against))
        table = sec.get('table') or {}
        rows = table.get('rows') or []
        for c in table.get('columns') or []:
            key = c['key']
            spec = {'format': c.get('format'), 'decimals': c.get('decimals'), 'currency': c.get('currency')}
            nums = [(i, r.get(key)) for i, r in enumerate(rows) if is_number(r.get(key))]
            for i, v in nums:
                out.append(_q(f'{sid}.r{i}.{key}', sid, f'{c["label"]} (row {i + 1})', 'value', v, spec, row=i,
                              column=key))
            if 1 < len(nums) <= 50:
                total = sum(v for _, v in nums)
                if total > 0 and all(v >= 0 for _, v in nums):
                    for i, v in nums:
                        out.append(_q(f'{sid}.r{i}.{key}.share', sid, f'{c["label"]} share (row {i + 1})', 'share',
                                      v / total * 100.0, {'format': 'percent'}, row=i, column=key))
                ranked = sorted(nums, key=lambda t: -t[1])
                for rank, (i, v) in enumerate(ranked, 1):
                    out.append(_q(f'{sid}.r{i}.{key}.rank', sid, f'{c["label"]} rank (row {i + 1})', 'rank', rank,
                                  {'format': 'integer'}, row=i, column=key))
    return out


def _attach_changes(sections: List[Dict[str, Any]], qs: List[Dict[str, Any]]) -> None:
    by_id = {q['id']: q for q in qs}
    for sec in sections:
        for k in sec.get('kpis') or []:
            base = f'{sec["id"]}.{k["key"]}'
            for kind in ('previous', 'change', 'pct_change'):
                q = by_id.get(f'{base}.{kind}')
                if q:
                    k[kind] = q['value']
                    k[f'{kind}_display'] = q['display']


# ── the run ─────────────────────────────────────────────────────────

def _runner(caller) -> Dict[str, Any]:
    return {'user_id': getattr(caller, 'user_id', 'anonymous'), 'roles': list(getattr(caller, 'roles', ()) or ()),
            'auth_type': getattr(caller, 'auth_type', ''), 'api_key': getattr(caller, 'api_key', '') or '',
            'is_admin': bool(getattr(caller, 'is_admin', False))}


def _status(sections: List[Dict[str, Any]]) -> str:
    calls = [s for s in sections if s['kind'] in ('kpis', 'table', 'chart', 'metric')]
    bad = [s for s in calls if s['status'] not in OK_STATES]
    if calls and len(bad) == len(calls):
        return 'failed'
    return 'partial' if bad else 'succeeded'


def _audit(event: str, caller, data: Dict[str, Any], details: Dict[str, Any]) -> None:
    try:
        from sajha import audit
        from sajha.observability import tracing
        trace = ''
        try:
            trace = tracing.current_trace_id() or ''
        except Exception:
            trace = ''
        audit.record(event, actor={'user': getattr(caller, 'user_id', '') or 'anonymous',
                                   'api_key': getattr(caller, 'api_key', '') or '',
                                   'roles': list(getattr(caller, 'roles', ()) or ()),
                                   'auth': getattr(caller, 'auth_type', '') or ''},
                     resource={'type': 'report', 'id': data.get('report'), 'run_id': data.get('run_id')},
                     outcome=data.get('status') or 'ok', details={**details, 'trace_id': trace})
    except Exception as e:
        logger.debug(f'report audit: {e}')


def run_report(defn: ReportDefinition, parameters: Optional[Dict[str, Any]] = None, caller=None,
               formats: Optional[List[str]] = None, definitions: Optional[Dict[str, ReportDefinition]] = None,
               store: bool = True) -> Dict[str, Any]:
    """Run ``defn`` as ``caller`` (default: the current caller); returns the stored report data."""
    from sajha.core import inner_calls
    from sajha.observability import caller as caller_mod
    caller = caller or caller_mod.current()
    why = may_run(defn, caller)
    if why:
        raise ReportRunError(why)
    started = _now()
    params = resolve_parameters(defn, parameters or {}, started)
    if definitions is None:
        from sajha.reports import store as defs_store
        definitions = defs_store.definitions()
    run_id = history.new_run_id(defn.name, started)
    ctx = {'params': params, 'run': _run_values(started), 'results': {}, 'registry': _registry(),
           'definitions': definitions, 'started': started}
    deadline = time.monotonic() + settings.max_run_seconds()
    token = caller_mod.set_caller(caller) if caller is not caller_mod.current() else None
    try:
        with inner_calls.entered(defn.tool_name):
            sections = _run_sections(defn, ctx, deadline)
        prev = history.previous(defn.name, params, caller, run_id) if store else None
    finally:
        if token is not None:
            caller_mod.reset(token)
    qs = quantities(sections, prev)
    _attach_changes(sections, qs)
    classification = defn.classification
    for sec in sections:
        if (sec.get('source') or {}).get('data_classes'):
            classification = higher_classification(classification, DATA_CLASS_FLOOR)
    finished = _now()
    data: Dict[str, Any] = {
        'schema': 'sajha.report.run/1', 'run_id': run_id, 'report': defn.name, 'title': defn.title,
        'description': defn.description, 'definition_hash': defn.digest, 'definition_source': defn.source,
        'owner': defn.owner, 'runner': _runner(caller), 'parameters': params,
        'started_at': started.isoformat(timespec='seconds'), 'finished_at': finished.isoformat(timespec='seconds'),
        'duration_ms': int((finished - started).total_seconds() * 1000),
        'declared_classification': defn.classification, 'classification': classification,
        'status': _status(sections), 'sections': sections, 'quantities': qs,
        'previous_run_id': (prev or {}).get('run_id'), 'narration': None, 'files': {}, 'files_unavailable': {},
        'warnings': [f'{s["id"]}: {s.get("error")}' for s in sections
                                       if s['status'] not in OK_STATES],
    }
    wanted = list(dict.fromkeys(['markdown'] + list(formats if formats is not None else defn.formats)))
    if store:
        render_and_store(data, wanted)
        history.save(data)
        try:
            history.prune(defn.name, keep=run_id)
        except Exception as e:
            logger.debug(f'reports prune: {e}')
    _audit('report.run', caller, data, {'parameters': params, 'formats': sorted(data['files']),
                                        'definition_hash': data['definition_hash'],
                                        'sections': {s['id']: s['status'] for s in sections}})
    return data


def render_and_store(data: Dict[str, Any], formats: List[str]) -> None:
    """Render each format of ``formats`` into the run's folder; a format that cannot be made is
    recorded in ``files_unavailable`` with the reason."""
    from sajha.reports import render
    for fmt in formats:
        why = render.unavailable(fmt)
        if why:
            data['files_unavailable'][fmt] = why
            continue
        try:
            content = render.render(data, fmt)
            data['files'][fmt] = history.write_file(data['run_id'], fmt, content)
            data['files_unavailable'].pop(fmt, None)
        except Exception as e:
            logger.warning(f'report {data["run_id"]}: {fmt} failed: {e}', exc_info=True)
            data['files_unavailable'][fmt] = f'{fmt} rendering failed: {e}'


def classification_options() -> List[str]:
    return list(CLASSIFICATIONS)
