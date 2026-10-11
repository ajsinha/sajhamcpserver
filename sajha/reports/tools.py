"""
SAJHA MCP Server — the report tools (tool folder ``reports``; docs/architecture/Reports.md §3).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* :class:`ReportTool`         every generated ``report_<name>`` tool (config written by
  sajha/reports/service.py; it carries only ``"report": {"name": ...}``)
* :class:`ReportListTool`     ``report_list``
* :class:`ReportDescribeTool` ``report_describe``
* :class:`ReportRunTool`      ``report_run``
* :class:`ReportHistoryTool`  ``report_history``
* :class:`ReportRenderTool`   ``report_render``
* :class:`ReportCompareTool`  ``report_compare``

The fixed tools ship as configs in ``config/tools/reports/``. ``BaseMCPTool`` has already applied
policy, validation and the cache before ``execute``; each section's call inside a run is again a
full ``execute_with_tracking`` call as the caller.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sajha.tools.base_mcp_tool import BaseMCPTool

INLINE_ROWS = 50


def _caller():
    from sajha.observability.caller import current
    return current()


def _definition(name: str):
    from sajha.reports import settings, store
    if not settings.enabled():
        raise RuntimeError('reports are turned off on this server (reports.enabled)')
    d = store.get(str(name or ''))
    if d is None:
        raise ValueError(f'no report named {name!r} (report_list lists the reports you may run)')
    return d


def _runnable(name: str):
    """The definition, if the caller may run it (else the same error as a missing one, plus why)."""
    from sajha.reports import engine
    d = _definition(name)
    why = engine.may_run(d, _caller())
    if why:
        raise PermissionError(why)
    return d


def compact(data: Dict[str, Any]) -> Dict[str, Any]:
    """What a report tool returns: the run, the Markdown, links to the files and the sections
    (tables cut to INLINE_ROWS rows; the stored run keeps every row)."""
    from sajha.reports import history
    sections = []
    for s in data.get('sections') or []:
        d = {k: s[k] for k in ('id', 'title', 'kind', 'status', 'error', 'text') if s.get(k) not in (None, '')}
        if s.get('kpis'):
            d['kpis'] = [{k: v for k, v in x.items() if k in ('label', 'value', 'display', 'change', 'pct_change',
                                                             'previous')} for x in s['kpis']]
        t = s.get('table')
        if t:
            d['table'] = {'columns': [c['key'] for c in t.get('columns') or []], 'rows': (t.get('rows') or [])[:INLINE_ROWS],
                          'row_count': t.get('row_count'),
                          'truncated': bool(t.get('truncated')) or len(t.get('rows') or []) > INLINE_ROWS}
        if (s.get('source') or {}).get('attribution'):
            d['source'] = s['source']['attribution']
        sections.append(d)
    md = None
    try:
        raw = history.file_bytes(data['run_id'], 'markdown')
        md = raw.decode('utf-8') if raw is not None else None
    except Exception:
        md = None
    if md is None:
        from sajha.reports import render
        md = render.to_markdown(data)
    return {'run_id': data['run_id'], 'report': data['report'], 'title': data.get('title'),
            'status': data['status'], 'classification': data.get('classification'),
            'parameters': data.get('parameters'), 'started_at': data.get('started_at'),
            'files': data.get('files') or {}, 'files_unavailable': data.get('files_unavailable') or {},
            'previous_run_id': data.get('previous_run_id'), 'warnings': data.get('warnings') or [],
            'sections': sections, 'markdown': md}


class _ReportBase(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema') or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema') or {}


class ReportTool(_ReportBase):
    """A generated ``report_<name>`` tool: runs its report as the caller."""

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config or {})
        self.report_name = str((self.config.get('report') or {}).get('name') or '')

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.reports import engine
        args = dict(arguments or {})
        formats = args.pop('formats', None)
        args.pop('deliver', None)
        d = _runnable(self.report_name)
        return compact(engine.run_report(d, args, formats=formats))


class ReportRunTool(_ReportBase):
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.reports import engine
        d = _runnable(arguments.get('report'))
        params = dict(arguments.get('parameters') or {})
        return compact(engine.run_report(d, params, formats=arguments.get('formats')))


def _last_run(name: str, caller) -> Optional[Dict[str, Any]]:
    from sajha.reports import history
    runs = history.runs(name, caller, limit=1)
    return runs[0] if runs else None


class ReportListTool(_ReportBase):
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.reports import engine, settings, store
        if not settings.enabled():
            return {'reports': [], 'count': 0, 'note': 'reports are turned off on this server (reports.enabled)'}
        caller = _caller()
        q = str(arguments.get('search') or '').strip().lower()
        tag = str(arguments.get('tag') or '').strip().lower()
        out = []
        for name, d in sorted(store.definitions().items()):
            if engine.may_run(d, caller):
                continue
            if q and q not in f'{d.name} {d.title} {d.description}'.lower():
                continue
            if tag and tag not in [t.lower() for t in d.tags]:
                continue
            out.append({'name': d.name, 'tool': d.tool_name, 'title': d.title, 'description': d.description,
                        'owner': d.owner, 'tags': d.tags, 'parameters': d.input_schema()['properties'],
                        'required': d.required, 'formats': d.formats, 'classification': d.classification,
                        'schedule': d.schedule, 'last_run': _last_run(d.name, caller)})
        for r in out:
            r['parameters'].pop('formats', None)
        return {'reports': out, 'count': len(out)}


class ReportDescribeTool(_ReportBase):
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.reports import history, render, store
        d = _runnable(arguments.get('report'))
        caller = _caller()
        privileged = bool(getattr(caller, 'is_admin', False)) or (d.owner and d.owner == caller.user_id)
        return {'name': d.name, 'tool': d.tool_name, 'title': d.title, 'description': d.description,
                'owner': d.owner, 'tags': d.tags, 'classification': d.classification,
                'definition': d.public(redact_recipients=not privileged), 'definition_hash': d.digest,
                'sources': d.calls(), 'sub_reports': d.sub_reports(),
                'missing_tools': store.missing().get(d.name, []),
                'formats': d.formats,
                'formats_unavailable': {f: render.unavailable(f) for f in d.formats if render.unavailable(f)},
                'schedule': d.schedule, 'last_runs': history.runs(d.name, caller, limit=5)}


class ReportHistoryTool(_ReportBase):
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.reports import history
        name = str(arguments.get('report') or '')
        _runnable(name)
        runs = history.runs(name, _caller(), since=arguments.get('from'), until=arguments.get('to'),
                            status=arguments.get('status'), limit=int(arguments.get('limit') or 50))
        return {'report': name, 'runs': runs, 'count': len(runs)}


def _visible_run(run_id: str) -> Dict[str, Any]:
    from sajha.reports import history
    run = history.load(str(run_id or ''))
    if run is None or not history.may_see(run, _caller()):
        raise ValueError(f'no run {run_id!r} that you may see (you see the runs you made; administrators see all)')
    return run


class ReportRenderTool(_ReportBase):
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.reports import engine, history
        run = _visible_run(arguments.get('run_id'))
        fmt = str(arguments.get('format') or 'markdown')
        engine.render_and_store(run, [fmt])
        if fmt in run.get('files_unavailable', {}):
            raise RuntimeError(run['files_unavailable'][fmt])
        history.save(run)
        engine._audit('report.render', _caller(), run, {'format': fmt})
        out = {'run_id': run['run_id'], 'format': fmt, 'path': run['files'][fmt]}
        raw = history.file_bytes(run['run_id'], fmt) or b''
        out['bytes'] = len(raw)
        if fmt == 'markdown':
            out['content'] = raw.decode('utf-8')
        return out


class ReportCompareTool(_ReportBase):
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.reports import compare, history
        name = str(arguments.get('report') or '')
        _definition(name)
        caller = _caller()
        runs = []
        for key in ('run_a', 'run_b'):
            ref = str(arguments.get(key) or '')
            run = history.resolve(name, ref, caller)
            if run is None:
                raise ValueError(f'{key}: no run {ref!r} of {name} that you may see (a run id, or a date YYYY-MM-DD)')
            runs.append(run)
        return compare.compare_runs(runs[0], runs[1])
