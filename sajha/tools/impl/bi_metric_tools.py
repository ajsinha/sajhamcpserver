"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Business Intelligence metric tools (tool folder ``bi``; Business Intelligence §4):
bi_list_metrics, bi_describe_metric, bi_query_metric, bi_compare, bi_top_n, bi_crosstab and
bi_explain_change. The metrics layer, compiler and arithmetic are in ``sajha/bi/``.

Every tool is read-only and takes no SQL: a metric is named, dimensions are the metric's
declared ones, values are bound parameters, and the query runs through the metric's source's
own path (connector guard, allowlist, masking and audit; the DuckDB sandbox; the OLAP layer).
A metric the caller may not query (its ``roles``, or the caller's access to its connection) is
absent from bi_list_metrics and answered as unknown everywhere else. Results depend on the
caller, so the configs set no cache.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sajha.bi import analysis as A
from sajha.bi import compiler as C
from sajha.bi import metrics as M
from sajha.bi import periods as P
from sajha.tools.base_mcp_tool import BaseMCPTool


class BiBaseTool(BaseMCPTool):
    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    @staticmethod
    def _metric(arguments: Dict[str, Any]) -> M.Metric:
        return M.require(arguments.get('metric'))

    @staticmethod
    def _period(m: M.Metric, value: Any, required: bool = False) -> Optional[P.Period]:
        if value in (None, ''):
            if required:
                raise P.PeriodError('period is required')
            return None
        return P.parse(value, m.fiscal_year_start)

    @staticmethod
    def _head(m: M.Metric, res: C.Result, period: Optional[P.Period]) -> Dict[str, Any]:
        return {'metric': m.name, 'title': m.title or m.name, 'unit': m.format.get('unit', ''),
                **({'currency': m.format['currency']} if m.format.get('currency') else {}),
                'period': period.as_dict() if period else None, 'as_of': res.as_of}

    @staticmethod
    def _total(m: M.Metric, period: Optional[P.Period], filters: Any, tool: str) -> C.Result:
        return C.run(m, None, filters, None, period, tool=tool, with_as_of=False)


def _value(res: C.Result) -> Optional[float]:
    return res.rows[0].get('value') if res.rows else None


def _by(arguments: Dict[str, Any], key: str = 'by') -> List[str]:
    v = arguments.get(key) or []
    return [v] if isinstance(v, str) else list(v)


class BiListMetricsTool(BiBaseTool):
    """bi_list_metrics: the metrics the caller may query."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        tag = (arguments.get('tag') or '').strip().lower()
        search = (arguments.get('search') or '').strip().lower()
        out = []
        for m in M.visible():
            if tag and tag not in [t.lower() for t in m.tags]:
                continue
            if search and search not in f'{m.name} {m.title} {m.description}'.lower():
                continue
            out.append(m.summary())
        return {'count': len(out), 'metrics': out}


class BiDescribeMetricTool(BiBaseTool):
    """bi_describe_metric: one metric's definition, source and freshness."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        m = self._metric(arguments)
        owner = M.is_owner(m)
        src = {k: v for k, v in m.source.items()}
        out: Dict[str, Any] = {
            **m.summary(), 'format': dict(m.format),
            'source': {'kind': m.source_kind, **src},
            'time': {'column': m.time_column, 'grains': list(m.grains), 'fiscal_year_start': m.fiscal_year_start},
            'dimensions': [{'name': d.name, **({'values': list(d.values)} if d.values else {}),
                            **({'description': d.description} if d.description else {})} for d in m.dimensions],
            'fixed_filter_count': len(m.filters), 'additive': m.additive,
        }
        if m.type == 'ratio':
            out['ratio'] = {'numerator': m.numerator, 'denominator': m.denominator}
        else:
            out['measure'] = m.measure_sql
        if owner:
            out['fixed_filters'] = list(m.filters)
            out['roles'] = list(m.roles)
        try:
            src_obj = C.open_source(m)
            C.check_columns(m, src_obj)
            a = src_obj.run(C.compile_as_of(m, src_obj).sql, {}, 1, 'bi_describe_metric')
            out['as_of'] = C._plain(a['rows'][0].get('bi_as_of')) if a['rows'] else None
            out['status'] = 'ok'
        except Exception as e:                       # the definition is shown even when its source fails
            out['as_of'] = None
            out['status'] = f'source unavailable: {str(e)[:300]}'
        return out


class BiQueryMetricTool(BiBaseTool):
    """bi_query_metric: a metric's values by grain and dimension members."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        m = self._metric(arguments)
        period = self._period(m, arguments.get('period'))
        by = _by(arguments)
        grain = arguments.get('grain') or None
        res = C.run(m, by, arguments.get('filters'), grain, period, limit=arguments.get('limit'))
        rows = res.rows
        if arguments.get('cumulative'):
            A.cumulative(rows, by, str(arguments['cumulative']).lower(), grain or '', m)
        roll = arguments.get('rolling')
        if roll:
            if not grain:
                raise M.MetricError('rolling needs a grain')
            if not isinstance(roll, dict):
                raise M.MetricError('rolling is {window, fn}')
            A.rolling(rows, by, int(roll.get('window') or 3), str(roll.get('fn') or 'avg'))
        return {**self._head(m, res, period), 'grain': grain, 'by': by, 'rows': rows, 'row_count': len(rows),
                'truncated': res.truncated, 'fingerprint': res.fingerprint}


class BiCompareTool(BiBaseTool):
    """bi_compare: a metric in one period against another."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        m = self._metric(arguments)
        period = self._period(m, arguments.get('period'), required=True)
        other = P.against(period, arguments.get('against'), m.fiscal_year_start)
        by, filters = _by(arguments), arguments.get('filters')
        cur = C.run(m, None, filters, None, period, tool=self.name)
        prev = self._total(m, other, filters, self.name)
        v, w = _value(cur), _value(prev)
        change = (v or 0) - (w or 0) if (v is not None or w is not None) else None
        out = {**self._head(m, cur, period), 'against': other.as_dict(), 'by': by,
               'total': {'value': A._r(v), 'comparison': A._r(w), 'change': A._r(change),
                         'pct_change': A.pct(change, w)},
               'rows': [], 'truncated': False, 'fingerprint': cur.fingerprint}
        if by:
            a = C.run(m, by, filters, None, period, tool=self.name, with_as_of=False)
            b = C.run(m, by, filters, None, other, tool=self.name, with_as_of=False)
            out['rows'] = A.compare(a.rows, b.rows, by)
            out['truncated'] = a.truncated or b.truncated
        return out


class BiTopNTool(BiBaseTool):
    """bi_top_n: the top members of a dimension with share and cumulative share."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        m = self._metric(arguments)
        period = self._period(m, arguments.get('period'))
        dim = m.dimension(arguments.get('dimension')).name
        n = int(arguments.get('n') or 10)
        pareto = arguments.get('pareto')
        threshold = None
        if pareto is True:
            threshold = 80.0
        elif isinstance(pareto, (int, float)) and not isinstance(pareto, bool):
            threshold = float(pareto)
        filters = arguments.get('filters')
        res = C.run(m, [dim], filters, None, period, order_by_value=True, tool=self.name)
        total = _value(self._total(m, period, filters, self.name))
        members, pset = A.top_n(res.rows, dim, n, total, m.additive, threshold)
        out = {**self._head(m, res, period), 'dimension': dim, 'total': A._r(total), 'members': members,
               'member_count': len(res.rows), 'truncated': res.truncated, 'fingerprint': res.fingerprint}
        if threshold is not None:
            out['pareto'] = {'threshold_pct': threshold, 'members': pset or [], 'count': len(pset or []),
                             **({} if pset is not None else
                                {'note': f'shares need an additive metric; {m.name} is {m.type}'})}
        if not m.additive:
            out['note'] = f'{m.name} is a {m.type} metric: shares of the total are not given'
        return out


class BiCrosstabTool(BiBaseTool):
    """bi_crosstab: a two-way table of a metric by two dimensions."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        m = self._metric(arguments)
        period = self._period(m, arguments.get('period'))
        rd, cd = m.dimension(arguments.get('rows')).name, m.dimension(arguments.get('columns')).name
        if rd == cd:
            raise M.MetricError('rows and columns must be different dimensions')
        normalize = arguments.get('normalize') or None
        if normalize not in (None, 'row', 'column', 'total'):
            raise M.MetricError('normalize is row, column or total')
        totals = arguments.get('totals', True) is not False
        filters = arguments.get('filters')
        res = C.run(m, [rd, cd], filters, None, period, tool=self.name)
        rt = ct = grand = None
        if totals or normalize:
            rt = {r[rd]: r['value'] for r in C.run(m, [rd], filters, None, period, tool=self.name,
                                                    with_as_of=False).rows}
            ct = {r[cd]: r['value'] for r in C.run(m, [cd], filters, None, period, tool=self.name,
                                                    with_as_of=False).rows}
            grand = _value(self._total(m, period, filters, self.name))
        table = A.crosstab(res.rows, rd, cd, rt if totals else None, ct if totals else None, grand, normalize)
        if normalize and not totals:
            table.pop('row_totals', None)
        return {**self._head(m, res, period), **table, 'normalize': normalize, 'truncated': res.truncated,
                'fingerprint': res.fingerprint}


class BiExplainChangeTool(BiBaseTool):
    """bi_explain_change: which members of which dimensions explain a metric's change."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        m = self._metric(arguments)
        period = self._period(m, arguments.get('period'), required=True)
        other = P.against(period, arguments.get('against'), m.fiscal_year_start)
        dims = _by(arguments, 'dimensions')
        if not 1 <= len(dims) <= 3 or len(set(dims)) != len(dims):
            raise M.MetricError('dimensions names one to three different dimensions')
        dims = [m.dimension(d).name for d in dims]
        top = int(arguments.get('top') or 10)
        filters = arguments.get('filters')
        cur = C.run(m, None, filters, None, period, tool=self.name)
        prev = self._total(m, other, filters, self.name)
        v, w = _value(cur), _value(prev)
        change = (v or 0) - (w or 0)
        result, truncated = [], False
        for d in dims:
            a = C.run(m, [d], filters, None, period, tool=self.name, with_as_of=False)
            b = C.run(m, [d], filters, None, other, tool=self.name, with_as_of=False)
            truncated = truncated or a.truncated or b.truncated
            result.append(A.explain_change(m, d, a.rows, b.rows, v, w, top))
        return {**self._head(m, cur, period), 'against': other.as_dict(), 'type': m.type,
                'total': {'value': A._r(v), 'comparison': A._r(w), 'change': A._r(change),
                          'pct_change': A.pct(change, w)},
                'by_dimension': result, 'truncated': truncated, 'fingerprint': cur.fingerprint}
