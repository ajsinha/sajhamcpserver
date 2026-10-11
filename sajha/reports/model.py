"""
SAJHA MCP Server — the report definition: parsing and load-time checks.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A definition is one YAML (or JSON) file in ``reports.dir`` (docs/architecture/Reports.md §2).
:func:`parse` turns its text into a :class:`ReportDefinition` or raises
:class:`ReportDefinitionError` naming every problem; tool existence is checked separately
(:func:`missing_tools`), because a missing tool is only a warning.

Section kinds: ``kpis`` (``values``), ``table`` (``rows``, ``columns``, ``highlight``, ``key``),
``chart`` (a table plus ``x``, ``y``, ``type``), ``metric`` (a ``tile`` tool call, usually a
``bi_*`` tool, presented as ``values`` / ``rows`` or automatically), ``text`` (static ``text``,
or ``narrate`` filled later by ``report_narrate``) and ``report`` (a sub-report, one level).

Argument references, whole string values only: ``$params.<name>``,
``$sections.<id>.<jsonpath>`` (an earlier section's result), ``$run.date``, ``$run.year``,
``$run.time``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

NAME_RE = re.compile(r'^[a-z][a-z0-9_]{0,47}$')
SECTION_ID_RE = re.compile(r'^[a-z][a-z0-9_]{0,47}$')
#: names of the fixed report tools: report_<name> would collide (Reports.md §3)
RESERVED = frozenset({'list', 'describe', 'run', 'render', 'compare', 'deliver', 'history', 'narrate'})
KINDS = ('kpis', 'table', 'chart', 'text', 'metric', 'report')
CALL_KINDS = ('kpis', 'table', 'chart', 'metric')
FORMATS = ('markdown', 'html', 'pdf', 'xlsx', 'pptx', 'docx')
RECIPIENT_KINDS = ('email', 'webhook', 'sharepoint', 'folder')
CLASSIFICATIONS = ('public', 'internal', 'confidential', 'restricted')
VALUE_FORMATS = ('number', 'integer', 'percent', 'ratio', 'currency', 'date', 'text', 'bps')
CHART_TYPES = ('bar', 'line')
#: argument names every report tool takes besides the definition's parameters
TOOL_ARGUMENTS = frozenset({'formats', 'deliver'})
_REF_RE = re.compile(r'^\$(params|sections|run)\.(.+)$')
_RUN_REFS = ('date', 'year', 'time')
_TOP_KEYS = {'name', 'title', 'description', 'owner', 'enabled', 'tags', 'roles', 'parameters', 'required',
             'sections', 'formats', 'recipients', 'classification', 'schedule'}


class ReportDefinitionError(ValueError):
    """A definition that cannot be loaded; ``problems`` lists every reason."""

    def __init__(self, problems: List[str], source: str = ''):
        self.problems = list(problems)
        self.source = source
        super().__init__('; '.join(self.problems))


def name_problem(name: Any) -> Optional[str]:
    """Why ``name`` cannot name a report (None: it can)."""
    if not isinstance(name, str) or not name:
        return 'name is missing'
    if '__' in name:
        return f'name {name!r} contains "__", which is reserved for namespaced tools'
    if not NAME_RE.match(name):
        return (f'name {name!r} must start with a lowercase letter and hold only lowercase letters, '
                f'digits and "_" (at most 48 characters)')
    if name in RESERVED:
        return f'name {name!r} is reserved: report_{name} is one of the fixed report tools'
    return None


def classification_rank(c: str) -> int:
    try:
        return CLASSIFICATIONS.index(c)
    except ValueError:
        return 1


def higher_classification(a: str, b: str) -> str:
    return a if classification_rank(a) >= classification_rank(b) else b


@dataclass
class ReportDefinition:
    name: str
    title: str
    description: str
    owner: str
    enabled: bool
    tags: List[str]
    roles: List[str]
    parameters: Dict[str, Dict[str, Any]]
    required: List[str]
    sections: List[Dict[str, Any]]
    formats: List[str]
    recipients: List[Dict[str, Any]]
    classification: str
    schedule: Optional[Dict[str, Any]]
    raw: Dict[str, Any] = field(default_factory=dict)
    source: str = ''

    @property
    def tool_name(self) -> str:
        return f'report_{self.name}'

    @property
    def digest(self) -> str:
        """sha256 of the canonical definition: recorded with every run."""
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True, default=str).encode()).hexdigest()

    def section(self, sid: str) -> Optional[Dict[str, Any]]:
        return next((s for s in self.sections if s['id'] == sid), None)

    def calls(self) -> List[Dict[str, Any]]:
        """Every tool call the definition makes: [{section, tool, arguments}] (metric tiles included)."""
        out = []
        for s in self.sections:
            c = section_call(s)
            if c:
                out.append({'section': s['id'], 'tool': c['tool'], 'arguments': c.get('arguments') or {}})
        return out

    def sub_reports(self) -> List[str]:
        return [s['report']['name'] for s in self.sections if s['kind'] == 'report']

    def input_schema(self) -> Dict[str, Any]:
        """The report tool's inputSchema: the definition's parameters plus ``formats``."""
        props = copy.deepcopy(self.parameters)
        props['formats'] = {'type': 'array', 'items': {'type': 'string', 'enum': list(FORMATS)},
                            'uniqueItems': True,
                            'description': f'Files to render besides Markdown (default: {", ".join(self.formats)})'}
        schema: Dict[str, Any] = {'type': 'object', 'properties': props, 'additionalProperties': False}
        if self.required:
            schema['required'] = list(self.required)
        example = {k: v['default'] for k, v in self.parameters.items() if 'default' in v}
        for k in self.required:
            ex = (self.parameters.get(k) or {}).get('examples')
            if isinstance(ex, list) and ex:
                example[k] = ex[0]
        if all(k in example for k in self.required):
            schema['examples'] = [example]
        return schema

    def public(self, redact_recipients: bool = True) -> Dict[str, Any]:
        """The definition as ``report_describe`` shows it (recipients redacted for non-owners)."""
        d = copy.deepcopy(self.raw)
        if redact_recipients and d.get('recipients'):
            kinds: Dict[str, int] = {}
            for r in d['recipients']:
                kinds[r.get('kind', '?')] = kinds.get(r.get('kind', '?'), 0) + 1
            d['recipients'] = [{'kind': k, 'count': n, 'redacted': True} for k, n in sorted(kinds.items())]
        return d


def section_call(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if s.get('kind') == 'metric':
        return s.get('tile')
    return s.get('call') if s.get('kind') in CALL_KINDS else None


def load_text(text: str, source: str = '') -> Any:
    import yaml
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ReportDefinitionError([f'not valid YAML: {str(e).splitlines()[0]}'], source)


def _jsonpath_problem(path: Any) -> Optional[str]:
    if not isinstance(path, str) or not path.strip():
        return 'is not a JSONPath string'
    from sajha.quality.jsonpath import JSONPathError, parse as jp_parse
    try:
        jp_parse(path)
    except JSONPathError as e:
        return str(e)
    return None


def _refs(value: Any) -> List[str]:
    """Every reference string inside an argument value."""
    if isinstance(value, str):
        return [value] if _REF_RE.match(value) else []
    if isinstance(value, dict):
        return [r for v in value.values() for r in _refs(v)]
    if isinstance(value, list):
        return [r for v in value for r in _refs(v)]
    return []


def _check_refs(where: str, value: Any, params: Set[str], earlier: Set[str], problems: List[str]) -> None:
    for ref in _refs(value):
        kind, rest = _REF_RE.match(ref).groups()
        if kind == 'params':
            if rest not in params:
                problems.append(f'{where}: {ref} names no declared parameter')
        elif kind == 'run':
            if rest not in _RUN_REFS:
                problems.append(f'{where}: {ref} is not one of $run.date, $run.year, $run.time')
        else:
            sid, _, path = rest.partition('.')
            if sid not in earlier:
                problems.append(f'{where}: {ref} does not name an earlier section')
            elif path:
                why = _jsonpath_problem('$.' + path if not path.startswith('[') else '$' + path)
                if why:
                    problems.append(f'{where}: {ref}: {why}')


def _str_list(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x for x in v)


def _check_values(where: str, values: Any, problems: List[str]) -> None:
    if not isinstance(values, list) or not values:
        problems.append(f'{where}.values must be a non-empty list of {{label, path, format?}}')
        return
    for i, v in enumerate(values):
        if not isinstance(v, dict) or not isinstance(v.get('label'), str) or not v.get('label'):
            problems.append(f'{where}.values[{i}] needs a label')
            continue
        why = _jsonpath_problem(v.get('path'))
        if why:
            problems.append(f'{where}.values[{i}].path {why}')
        if v.get('format', 'number') not in VALUE_FORMATS:
            problems.append(f'{where}.values[{i}].format must be one of {", ".join(VALUE_FORMATS)}')


def _check_table(where: str, s: Dict[str, Any], problems: List[str]) -> None:
    why = _jsonpath_problem(s.get('rows'))
    if why:
        problems.append(f'{where}.rows {why}')
    cols = s.get('columns')
    if cols is not None:
        if not isinstance(cols, list) or not cols:
            problems.append(f'{where}.columns must be a non-empty list')
        else:
            for i, c in enumerate(cols):
                if isinstance(c, str) and c:
                    continue
                if not isinstance(c, dict) or not (c.get('key') or c.get('path')):
                    problems.append(f'{where}.columns[{i}] must be a key or {{key?, label?, path?, format?}}')
                    continue
                if c.get('path') is not None:
                    w = _jsonpath_problem(c['path'])
                    if w:
                        problems.append(f'{where}.columns[{i}].path {w}')
                if c.get('format', 'number') not in VALUE_FORMATS:
                    problems.append(f'{where}.columns[{i}].format must be one of {", ".join(VALUE_FORMATS)}')
    hl = s.get('highlight')
    if hl is not None and (not isinstance(hl, dict) or not hl.get('column')
                           or not any(isinstance(hl.get(k), (int, float)) for k in ('above', 'below'))):
        problems.append(f'{where}.highlight must be {{column, above?, below?}} with a number')
    if s.get('limit') is not None and (not isinstance(s['limit'], int) or s['limit'] < 1):
        problems.append(f'{where}.limit must be a positive integer')


def parse(doc: Any, source: str = '', max_sections: int = 50) -> ReportDefinition:
    """A validated definition from parsed YAML/JSON (or its text); raises ReportDefinitionError."""
    if isinstance(doc, (str, bytes)):
        doc = load_text(doc.decode() if isinstance(doc, bytes) else doc, source)
    if not isinstance(doc, dict):
        raise ReportDefinitionError(['a report definition must be a mapping'], source)
    p: List[str] = []
    unknown = sorted(set(doc) - _TOP_KEYS)
    if unknown:
        p.append(f'unknown keys: {", ".join(unknown)}')
    name = doc.get('name')
    why = name_problem(name)
    if why:
        p.append(why)
    title = doc.get('title') or name or ''
    if not isinstance(title, str):
        p.append('title must be a string')
    params = doc.get('parameters') or {}
    if not isinstance(params, dict):
        p.append('parameters must be a mapping of name to JSON Schema')
        params = {}
    for pn, ps in params.items():
        if not isinstance(pn, str) or not re.match(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$', pn):
            p.append(f'parameter name {pn!r} is not valid')
        elif pn in TOOL_ARGUMENTS:
            p.append(f'parameter name {pn!r} is reserved (the report tools take it)')
        if not isinstance(ps, dict):
            p.append(f'parameter {pn!r} must be a JSON Schema mapping')
    if params:
        try:
            from jsonschema import Draft202012Validator
            Draft202012Validator.check_schema({'type': 'object', 'properties': params})
        except Exception as e:
            p.append(f'parameters are not valid JSON Schema: {str(e).splitlines()[0]}')
    required = doc.get('required') or []
    if not _str_list(required) and required != []:
        p.append('required must be a list of parameter names')
        required = []
    for r in required:
        if r not in params:
            p.append(f'required parameter {r!r} is not declared')
    formats = doc.get('formats') or ['markdown', 'html']
    if not _str_list(formats):
        p.append('formats must be a list')
        formats = ['markdown']
    for f in formats:
        if f not in FORMATS:
            p.append(f'unknown format {f!r} (known: {", ".join(FORMATS)})')
    recipients = doc.get('recipients') or []
    if not isinstance(recipients, list):
        p.append('recipients must be a list')
        recipients = []
    for i, r in enumerate(recipients):
        if not isinstance(r, dict) or r.get('kind') not in RECIPIENT_KINDS:
            p.append(f'recipients[{i}].kind must be one of {", ".join(RECIPIENT_KINDS)}')
    classification = doc.get('classification') or 'internal'
    if classification not in CLASSIFICATIONS:
        p.append(f'classification must be one of {", ".join(CLASSIFICATIONS)}')
    schedule = doc.get('schedule')
    if schedule is not None and (not isinstance(schedule, dict) or not isinstance(schedule.get('cron'), str)):
        p.append('schedule must be {cron, timezone?}')
    for key in ('tags', 'roles'):
        if doc.get(key) is not None and not _str_list(doc.get(key)):
            p.append(f'{key} must be a list of strings')
    sections = doc.get('sections')
    if not isinstance(sections, list) or not sections:
        p.append('sections must be a non-empty list')
        sections = []
    if len(sections) > max_sections:
        p.append(f'{len(sections)} sections is more than reports.max_sections ({max_sections})')
    seen: Set[str] = set()
    pnames = set(params)
    for i, s in enumerate(sections):
        where = f'sections[{i}]'
        if not isinstance(s, dict):
            p.append(f'{where} must be a mapping')
            continue
        sid = s.get('id')
        if not isinstance(sid, str) or not SECTION_ID_RE.match(sid):
            p.append(f'{where}.id must be lowercase letters, digits and "_"')
        elif sid in seen:
            p.append(f'{where}.id {sid!r} is used twice')
        else:
            where = f'section {sid}'
        kind = s.get('kind')
        if kind not in KINDS:
            p.append(f'{where}.kind must be one of {", ".join(KINDS)}')
        elif kind in CALL_KINDS:
            call = section_call(s)
            key = 'tile' if kind == 'metric' else 'call'
            if not isinstance(call, dict) or not isinstance(call.get('tool'), str) or not call.get('tool'):
                p.append(f'{where}.{key} must be {{tool, arguments?}}')
            else:
                if call.get('arguments') is not None and not isinstance(call['arguments'], dict):
                    p.append(f'{where}.{key}.arguments must be a mapping')
                _check_refs(f'{where}.{key}.arguments', call.get('arguments') or {}, pnames, seen, p)
            if kind == 'kpis':
                _check_values(where, s.get('values'), p)
            elif kind in ('table', 'chart'):
                _check_table(where, s, p)
            elif kind == 'metric':
                if s.get('values') is not None:
                    _check_values(where, s.get('values'), p)
                if s.get('rows') is not None:
                    _check_table(where, s, p)
                visual = (call or {}).get('visual') if isinstance(call, dict) else None
                if visual is not None and visual not in CHART_TYPES + ('table', 'kpis'):
                    p.append(f'{where}.tile.visual must be one of bar, line, table, kpis')
            if kind == 'chart':
                if not isinstance(s.get('x'), str):
                    p.append(f'{where}.x must name the column on the x axis')
                y = s.get('y')
                if not (isinstance(y, str) or _str_list(y)):
                    p.append(f'{where}.y must name one column or a list of columns')
                if s.get('type', 'bar') not in CHART_TYPES:
                    p.append(f'{where}.type must be bar or line')
        elif kind == 'text':
            if not isinstance(s.get('text'), str) and not isinstance(s.get('narrate'), dict):
                p.append(f'{where} needs text (a string) or narrate {{sections?, length?}}')
            nar = s.get('narrate')
            if isinstance(nar, dict):
                for ref in nar.get('sections') or []:
                    if ref not in seen and ref not in {x.get('id') for x in sections if isinstance(x, dict)}:
                        p.append(f'{where}.narrate.sections names no section {ref!r}')
        elif kind == 'report':
            sub = s.get('report')
            if not isinstance(sub, dict) or not isinstance(sub.get('name'), str):
                p.append(f'{where}.report must be {{name, parameters?}}')
            else:
                if sub.get('name') == name:
                    p.append(f'{where}: a report cannot include itself')
                _check_refs(f'{where}.report.parameters', sub.get('parameters') or {}, pnames, seen, p)
        if isinstance(sid, str):
            seen.add(sid)
    if p:
        raise ReportDefinitionError(p, source)
    return ReportDefinition(
        name=name, title=str(title), description=str(doc.get('description') or ''), owner=str(doc.get('owner') or ''),
        enabled=bool(doc.get('enabled', True)), tags=list(doc.get('tags') or []), roles=list(doc.get('roles') or []),
        parameters={k: dict(v) for k, v in params.items()}, required=list(required),
        sections=[dict(s) for s in sections], formats=list(dict.fromkeys(['markdown'] + list(formats))),
        recipients=list(recipients), classification=classification, schedule=schedule,
        raw=json.loads(json.dumps(doc, default=str)), source=source)


def check_sub_reports(defs: Dict[str, ReportDefinition]) -> Dict[str, str]:
    """name -> problem, for definitions whose sub-reports are missing or would recurse (one level only)."""
    out: Dict[str, str] = {}
    for n, d in defs.items():
        for sub in d.sub_reports():
            other = defs.get(sub)
            if other is None:
                out[n] = f'sub-report {sub!r} does not exist'
            elif other.sub_reports():
                out[n] = f'sub-report {sub!r} has sub-reports of its own (one level only, so nothing recurses)'
    return out


def missing_tools(d: ReportDefinition, exists) -> List[str]:
    """Tools the definition calls that ``exists(name)`` does not know (a warning, not a refusal)."""
    return sorted({c['tool'] for c in d.calls() if not exists(c['tool'])})
