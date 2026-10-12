"""
SAJHA MCP Server — the tool schema linter (static: no tool runs).

Checks every tool's name (MCP tool-name rule), description, input and output schemas (valid
JSON Schema 2020-12, ``type: object``), property descriptions, ``examples`` and ``default``
values, annotations (boolean hints, no read-only-and-destructive, destructive-sounding names
carry ``destructiveHint``), ``x-sajha-unit`` declarations in the output schema and test-case
arguments. Rules: docs/architecture/Tool Quality.md §3.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

LEVELS = ('error', 'warning', 'info')
NAME_RULE = re.compile(r'^[A-Za-z0-9_.\-]{1,128}$')
_DESTRUCTIVE = re.compile(r'(^|[_.\-])(delete|del|remove|drop|purge|destroy|revoke|truncate|wipe|erase|kill|reset)([_.\-]|$)', re.I)
_READONLY = re.compile(r'(^|[_.\-])(get|list|search|fetch|query|read|lookup|find|describe|show)([_.\-]|$)', re.I)
_HINTS = ('readOnlyHint', 'destructiveHint', 'idempotentHint', 'openWorldHint')


@dataclass
class Finding:
    tool: str
    level: str
    rule: str
    message: str
    where: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {'tool': self.tool, 'level': self.level, 'rule': self.rule, 'message': self.message,
                'where': self.where}


def _min_description() -> int:
    from sajha.quality import setting_int
    return setting_int('lint.min_description', 40)


def _check_schema(schema: Any) -> Optional[str]:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        where = '/'.join(str(p) for p in e.absolute_path)
        return f'{e.message}' + (f' (at {where})' if where else '')
    return None


def _subschemas(schema: Any, where: str = '') -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Every (location, subschema) worth checking for examples/defaults: properties, items, $defs."""
    if not isinstance(schema, dict):
        return
    yield where or '(root)', schema
    for key in ('properties', '$defs', 'definitions', 'patternProperties'):
        for name, sub in (schema.get(key) or {}).items() if isinstance(schema.get(key), dict) else ():
            yield from _subschemas(sub, f'{where}/{key}/{name}' if where else f'{key}/{name}')
    items = schema.get('items')
    if isinstance(items, dict):
        yield from _subschemas(items, f'{where}/items' if where else 'items')
    for key in ('anyOf', 'oneOf', 'allOf', 'prefixItems'):
        for i, sub in enumerate(schema.get(key) or []) if isinstance(schema.get(key), list) else ():
            yield from _subschemas(sub, f'{where}/{key}/{i}' if where else f'{key}/{i}')


def _validate_value(schema: Dict[str, Any], root: Dict[str, Any], value: Any) -> Optional[str]:
    from jsonschema import Draft202012Validator
    try:
        sub = dict(schema)
        for k in ('$defs', 'definitions'):
            if k in root and k not in sub:
                sub[k] = root[k]
        errs = list(Draft202012Validator(sub).iter_errors(value))
    except Exception as e:      # an unresolvable $ref: the schema check reports it
        return None if 'ref' in str(e).lower() else str(e)
    return errs[0].message if errs else None


def lint_tool(name: str, config: Dict[str, Any], input_schema: Any = None, output_schema: Any = None,
              cases: Optional[List[Any]] = None) -> List[Finding]:
    """Findings for one tool. ``input_schema``/``output_schema`` default to the config's."""
    out: List[Finding] = []

    def add(level, rule, message, where=''):
        out.append(Finding(name, level, rule, message, where))

    cfg = config or {}
    if not NAME_RULE.match(name or ''):
        add('error', 'name', f'name {name!r} breaks the MCP tool-name rule: 1-128 of A-Z a-z 0-9 _ - .')
    desc = str(cfg.get('description') or '').strip()
    if not desc:
        add('error', 'description', 'no description: clients and models choose tools by it')
    elif len(desc) < _min_description():
        add('warning', 'description', f'description is {len(desc)} characters; say what the tool does, '
                                      f'returns and when to use it (at least {_min_description()})')

    schema = input_schema if input_schema is not None else cfg.get('inputSchema')
    if not isinstance(schema, dict) or not schema:
        add('error', 'input-schema', 'no inputSchema')
        schema = None
    else:
        problem = _check_schema(schema)
        if problem:
            add('error', 'input-schema', f'not valid JSON Schema 2020-12: {problem}')
        if schema.get('type') != 'object':
            add('error', 'input-schema', f'type must be "object", is {schema.get("type")!r}')
        props = schema.get('properties') if isinstance(schema.get('properties'), dict) else {}
        for req in schema.get('required') if isinstance(schema.get('required'), list) else []:
            if req not in props:
                add('error', 'input-schema', f'required {req!r} is not a property', 'required')
        for pname, pschema in props.items():
            if isinstance(pschema, dict) and not str(pschema.get('description') or '').strip() and '$ref' not in pschema:
                add('warning', 'property-description', f'property {pname!r} has no description',
                    f'properties/{pname}')
        if not problem:
            _lint_examples(schema, add, 'input')
            _lint_defaults(schema, add)
            from sajha.quality.check import derive_arguments
            if derive_arguments(schema, cases)[0] is None:
                add('warning', 'missing-example', 'the live tool check cannot call this tool: give the inputSchema '
                                                  'an examples entry, or examples on every required property')

    if output_schema is None:
        output_schema = cfg.get('outputSchema')
    if isinstance(output_schema, dict) and output_schema:
        problem = _check_schema(output_schema)
        if problem:
            add('error', 'output-schema', f'not valid JSON Schema 2020-12: {problem}')
        else:
            _lint_examples(output_schema, add, 'output')
        if output_schema.get('type') != 'object':
            add('error', 'output-schema', f'outputSchema type must be "object" (MCP), is {output_schema.get("type")!r}')
        _lint_units(output_schema, add)

    ann = cfg.get('annotations')
    if ann is not None and not isinstance(ann, dict):
        add('error', 'annotations', 'annotations must be an object')
        ann = {}
    ann = ann or {}
    for h in _HINTS:
        if h in ann and not isinstance(ann[h], bool):
            add('error', 'annotations', f'{h} must be true or false, is {ann[h]!r}', f'annotations/{h}')
    if ann.get('readOnlyHint') is True and ann.get('destructiveHint') is True:
        add('error', 'annotations', 'readOnlyHint and destructiveHint are both true')
    if _DESTRUCTIVE.search(name or '') and ann.get('destructiveHint') is not True and ann.get('readOnlyHint') is not True:
        add('warning', 'annotations', 'the name says this tool deletes or removes something: set '
                                      'annotations.destructiveHint: true (clients confirm before calling it)')
    elif _READONLY.search(name or '') and not _DESTRUCTIVE.search(name or '') and 'readOnlyHint' not in ann:
        add('info', 'annotations', 'the name says this tool only reads: consider annotations.readOnlyHint: true')

    if schema and not _check_schema(schema):
        for c in cases or []:
            if getattr(c, 'expects_error', False):
                continue
            msg = _validate_value(schema, schema, getattr(c, 'arguments', {}))
            if msg:
                add('error', 'test-arguments', f'test case {getattr(c, "name", "?")!r}: arguments do not match the '
                                               f'inputSchema: {msg}', f'tests/{getattr(c, "name", "?")}')
    return out


def _lint_examples(schema: Dict[str, Any], add, which: str) -> None:
    for where, sub in _subschemas(schema):
        examples = sub.get('examples')
        if examples is not None:
            if not isinstance(examples, list):
                add('error', 'examples', f'{which} {where}: examples must be a list (JSON Schema 2020-12)', where)
            else:
                for i, ex in enumerate(examples):
                    msg = _validate_value(sub, schema, ex)
                    if msg:
                        add('error', 'examples', f'{which} {where}: example {i + 1} does not validate: {msg}', where)
        if 'example' in sub and where != '(root)':
            msg = _validate_value(sub, schema, sub['example'])
            if msg:
                add('error', 'examples', f'{which} {where}: example does not validate: {msg}', where)
        if 'default' in sub:
            msg = _validate_value({k: v for k, v in sub.items() if k != 'default'}, schema, sub['default'])
            if msg:
                add('warning', 'default', f'{which} {where}: default does not validate: {msg}', where)


def _lint_units(schema: Dict[str, Any], add) -> None:
    """``x-sajha-unit`` declarations (Quantitative Planners §2.2): a unit outside the grammar is an
    error (rule ``unit``); one on a property that holds no number is a warning."""
    from sajha.ai.quant.schema_units import KEYWORD, schema_unit_marks, unit_problem
    for where, value, sub in schema_unit_marks(schema):
        error, warning = unit_problem(value, sub)
        if error:
            # the error already names the value and says it is not a known unit: say it once
            add('error', 'unit', f'output {where}: ' + (error if error.startswith(KEYWORD) else f'{KEYWORD}: {error}'),
                where)
        elif warning:
            add('warning', 'unit', f'output {where}: {warning}', where)


_BRANCHES = ('oneOf', 'anyOf', 'allOf', 'if', 'then', 'else', 'not', 'items', 'prefixItems', 'additionalProperties',
             'patternProperties', '$defs', 'definitions', 'dependentSchemas', 'contains')


def _lint_defaults(schema: Dict[str, Any], add) -> None:
    """Defaults the call path cannot apply (sajha/tools/schema_defaults.py; Tool Quality §12.1):
    ``required-default`` (a required property with a default: never filled) and ``unapplied-default``
    (a default under a branch, ``items`` or ``$defs``, which the helper never reads)."""
    def walk(node: Any, where: str, applied: bool) -> None:
        if not isinstance(node, dict):
            return
        props = node.get('properties') if isinstance(node.get('properties'), dict) else {}
        required = set(node.get('required') or []) if isinstance(node.get('required'), list) else set()
        for name, sub in props.items():
            if not isinstance(sub, dict):
                continue
            loc = f'{where}/properties/{name}' if where else f'properties/{name}'
            if 'default' in sub:
                if not applied:
                    add('info', 'unapplied-default', f'input {loc}: this default is never filled in before a call '
                                                     f'(it sits under a branch, items or $defs)', loc)
                elif name in required:
                    add('warning', 'required-default', f'input {loc}: {name!r} is required and has a default; '
                                                       f'a required property is never filled in: drop one', loc)
            walk(sub, loc, applied)
        for key in _BRANCHES:
            val = node.get(key)
            subs = val if isinstance(val, list) else list(val.values()) if key in (
                'patternProperties', '$defs', 'definitions', 'dependentSchemas') and isinstance(val, dict) else [val]
            for i, sub in enumerate(subs):
                if isinstance(sub, dict):
                    if 'default' in sub and key != 'additionalProperties':
                        add('info', 'unapplied-default', f'input {where or "(root)"}/{key}: a default here is never '
                                                         f'filled in before a call', f'{where}/{key}')
                    walk(sub, f'{where}/{key}/{i}' if isinstance(val, list) else f'{where}/{key}', False)
    walk(schema, '', True)


def lint_registry(registry: Any, tool_glob: str = '', suite: Any = None) -> List[Finding]:
    findings: List[Finding] = []
    tools = getattr(registry, 'tools', {}) or {}
    for name in sorted(tools):
        if tool_glob and not any(fnmatch.fnmatchcase(name, g.strip()) for g in tool_glob.split(',') if g.strip()):
            continue
        tool = tools[name]
        cfg = dict(getattr(tool, 'config', None) or {})
        cfg.setdefault('description', getattr(tool, 'description', ''))
        try:
            ins = tool.input_schema
        except Exception:
            ins = cfg.get('inputSchema')
        try:
            outs = tool.output_schema
        except Exception:
            outs = cfg.get('outputSchema')
        cases = suite.for_tool(name) if suite is not None else []
        findings.extend(lint_tool(name, cfg, ins, outs, cases))
        findings.extend(_lint_description_length(name, tool))
        if isinstance(cfg.get('llm'), dict):
            findings.extend(_lint_llm(name, cfg, registry, getattr(tool, 'declared_annotations', None)))
    # LLM tools whose llm block the loader refused are not in the catalog: report why
    for name, cfg in sorted((getattr(registry, 'tool_configs', {}) or {}).items()):
        if name in tools or not isinstance(cfg, dict) or not isinstance(cfg.get('llm'), dict):
            continue
        if tool_glob and not any(fnmatch.fnmatchcase(name, g.strip()) for g in tool_glob.split(',') if g.strip()):
            continue
        findings.extend(_lint_llm(name, cfg, registry, None))
    # planner files (config/planners): rules P001-P071 (docs/architecture/Planner Reference.md §12)
    if not tool_glob or any(fnmatch.fnmatchcase('planner:x', g.strip()) for g in tool_glob.split(',')):
        findings.extend(_lint_planners())
    return findings


def _lint_description_length(name: str, tool: Any) -> List[Finding]:
    """``description-length``: the tool's own description plus its folder's domain description is longer
    than SAJHA Net's catalog limit, so catalogs get the own description only (Architecture §5)."""
    try:
        from sajha.tools.domain_text import domain_description_of, compose
        domain = domain_description_of(tool)
        if not domain:
            return []
        from sajha.net.integration.catalogs import _description_limit
        limit = _description_limit()
        total = len(compose(getattr(tool, 'description', '') or '', domain))
    except Exception:
        return []
    if total <= limit:
        return []
    return [Finding(name, 'warning', 'description-length',
                    f'description plus the folder\'s domain description is {total} characters, over SAJHA Net\'s '
                    f'{limit}: SAJHA Net catalogs get the tool\'s own description without the domain text; '
                    f'shorten the description (the domain description already says what the folder shares)')]


def _lint_planners() -> List[Finding]:
    try:
        from sajha.ai.planners_engine.registry import lint_findings as planner_findings
        return [Finding(f'planner:{who}', level, code, message, where) for who, level, code, message, where in
                planner_findings()]
    except Exception as e:
        return [Finding('planner:*', 'error', 'planner-load', f'the planner registry could not load: {e}')]


def _lint_llm(name: str, cfg: Dict[str, Any], registry: Any, declared: Any) -> List[Finding]:
    """LLM-tool rules (docs/architecture/Tool Quality.md §3): llm-config, llm-catalog, llm-annotations."""
    from sajha.ai.llm_tools.config import lint_findings
    return [Finding(name, level, rule, message, 'llm') for level, rule, message in
            lint_findings(name, cfg, registry, declared)]


def summarise(findings: List[Finding]) -> Dict[str, Any]:
    by_level = {lvl: sum(1 for f in findings if f.level == lvl) for lvl in LEVELS}
    by_rule: Dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
    return {'findings': len(findings), **by_level, 'tools_with_errors': len({f.tool for f in findings if f.level == 'error'}),
            'tools_with_findings': len({f.tool for f in findings}), 'by_rule': by_rule}


def render_text(findings: List[Finding], tools_checked: int, show_info: bool = False) -> str:
    lines, current = [], None
    for f in findings:
        if f.level == 'info' and not show_info:
            continue
        if f.tool != current:
            current = f.tool
            lines.append(f.tool)
        lines.append(f'  {f.level.upper():7} {f.rule:20} {f.message}')
    s = summarise(findings)
    lines.append('')
    lines.append(f'{tools_checked} tools checked: {s["error"]} errors, {s["warning"]} warnings, {s["info"]} notes '
                 f'({s["tools_with_errors"]} tools with errors)')
    return '\n'.join(lines)


def render_junit(findings: List[Finding], tool_names: List[str], strict: bool = False) -> str:
    """One <testcase> per tool; errors (and warnings with ``strict``) are failures."""
    by_tool: Dict[str, List[Finding]] = {n: [] for n in tool_names}
    for f in findings:
        by_tool.setdefault(f.tool, []).append(f)
    failing = {lvl for lvl in (('error', 'warning') if strict else ('error',))}
    failures = sum(1 for fs in by_tool.values() if any(f.level in failing for f in fs))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites name="sajha.quality.lint" tests="{len(by_tool)}" failures="{failures}">',
           f'  <testsuite name="schema-lint" tests="{len(by_tool)}" failures="{failures}" errors="0" skipped="0">']
    for name, fs in by_tool.items():
        out.append(f'    <testcase classname="sajha.lint" name={quoteattr(name)}>')
        bad = [f for f in fs if f.level in failing]
        if bad:
            body = '\n'.join(f'{f.level}: {f.rule}: {f.message}' for f in bad)
            out.append(f'      <failure message={quoteattr(bad[0].message[:300])}>{escape(body)}</failure>')
        rest = [f for f in fs if f.level not in failing]
        if rest:
            out.append(f'      <system-out>{escape(chr(10).join(f"{f.level}: {f.rule}: {f.message}" for f in rest))}</system-out>')
        out.append('    </testcase>')
    out.append('  </testsuite>')
    out.append('</testsuites>')
    return '\n'.join(out) + '\n'
