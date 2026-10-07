"""
SAJHA MCP Server — runs tool test cases and renders the results (text, JSON, JUnit XML).

A case runs ``validate_arguments`` then ``execute`` on the tool (or the version the case
pins), inside an HTTP cassette (record | replay | live; ``auto`` replays when a cassette
exists). It tests the tool, not the platform around it: no policy, cache, breaker or usage
row. Docs: docs/architecture/Tool Quality.md §2.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from xml.sax.saxutils import escape, quoteattr

from sajha.quality import assertions as A
from sajha.quality.cases import TestCase
from sajha.quality.cassette import Cassette, CassetteMiss, cassette_path

RUN_MODES = ('auto', 'record', 'replay', 'live')


@dataclass
class CaseResult:
    tool: str
    case: str
    status: str                       # pass | fail | error | skip
    duration_ms: float = 0.0
    message: str = ''
    failures: List[Dict[str, Any]] = field(default_factory=list)
    mode: str = 'live'                # record | replay | live
    http_calls: int = 0
    version: Optional[str] = None
    result_preview: str = ''

    @property
    def ok(self) -> bool:
        return self.status in ('pass', 'skip')

    def to_dict(self) -> Dict[str, Any]:
        return {'tool': self.tool, 'case': self.case, 'status': self.status,
                'duration_ms': round(self.duration_ms, 2), 'message': self.message, 'failures': self.failures,
                'mode': self.mode, 'http_calls': self.http_calls, 'version': self.version,
                'result_preview': self.result_preview}


def _preview(v: Any, n: int = 400) -> str:
    try:
        s = json.dumps(v, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(v)
    return s if len(s) <= n else s[:n] + '...'


def _output_schema(tool: Any) -> Optional[Dict[str, Any]]:
    try:
        s = tool.output_schema
    except Exception:
        return None
    return s if isinstance(s, dict) and s else None


def _target(tool: Any, case: TestCase):
    if not case.version:
        return tool
    from sajha.quality import versions
    inst = versions.get_manager().instance_for(tool, case.version)
    if inst is None:
        raise LookupError(f'{case.tool} has no version {case.version!r} (config/tool_versions)')
    return inst


def run_case(tool: Any, case: TestCase, mode: str = 'auto', cassette_root: Optional[str] = None) -> CaseResult:
    if mode not in RUN_MODES:
        raise ValueError(f'mode must be one of {RUN_MODES}')
    if case.skip:
        return CaseResult(case.tool, case.name, 'skip', message=case.skip, version=case.version)
    if tool is None:
        return CaseResult(case.tool, case.name, 'error', message=f'tool not found: {case.tool}', version=case.version)
    path = cassette_path(case.tool, case.cassette_name, cassette_root)
    effective = mode
    if mode == 'auto':
        effective = 'replay' if path.is_file() else 'live'
    try:
        if effective == 'replay' and not path.is_file():
            cassette = Cassette(None, 'record')          # an empty recorder, switched to strict replay
            cassette.mode = 'replay'
            cassette.path = path
        else:
            cassette = Cassette(str(path), effective)
    except Exception as e:
        return CaseResult(case.tool, case.name, 'error', message=f'cassette: {e}', mode=effective, version=case.version)

    try:
        target = _target(tool, case)
    except LookupError as e:
        return CaseResult(case.tool, case.name, 'error', message=str(e), mode=effective, version=case.version)

    error: Optional[BaseException] = None
    result: Any = None
    t0 = time.perf_counter()
    with cassette.use():
        try:
            target.validate_arguments(dict(case.arguments))
            result = target.execute(dict(case.arguments))
        except BaseException as e:      # noqa: BLE001 - a tool may raise anything; KeyboardInterrupt re-raised below
            if isinstance(e, KeyboardInterrupt):
                raise
            error = e
    elapsed = (time.perf_counter() - t0) * 1000
    res = CaseResult(case.tool, case.name, 'pass', duration_ms=elapsed, mode=effective,
                     http_calls=cassette.requests_seen if effective != 'live' else 0,
                     version=case.version or getattr(target, 'version', None))

    miss = isinstance(error, CassetteMiss) or bool(cassette.misses)
    if miss:
        res.status, res.message = 'error', str(error) if isinstance(error, CassetteMiss) else \
            f'cassette miss: {cassette.misses[0]} (re-record with --record)'
        return res
    if case.expects_error:
        if error is None:
            res.status, res.message = 'fail', 'expected the call to fail, but it succeeded'
            res.result_preview = _preview(A.normalise_result(result))
            return res
        msg = f'{type(error).__name__}: {error}'
        if isinstance(case.error, str) and not re.search(case.error, msg):
            res.status, res.message = 'fail', f'failed as expected, but {msg!r} does not match /{case.error}/'
            return res
        res.message = msg
        return res
    if error is not None:
        res.status, res.message = 'error', f'{type(error).__name__}: {error}'
        return res
    value = A.normalise_result(result)
    res.result_preview = _preview(value)
    schema = _output_schema(target)
    for spec in case.expect:
        o = A.check(spec, value, elapsed, schema)
        if not o.ok:
            res.failures.append(o.to_dict())
    if res.failures:
        res.status = 'fail'
        res.message = res.failures[0]['message'] + (f' (+{len(res.failures) - 1} more)' if len(res.failures) > 1 else '')
    return res


def run_cases(registry: Any, cases: List[TestCase], mode: str = 'auto', cassette_root: Optional[str] = None,
              on_result: Optional[Callable[[CaseResult], None]] = None) -> List[CaseResult]:
    out = []
    for c in cases:
        r = run_case(registry.get_tool(c.tool) if registry else None, c, mode, cassette_root)
        out.append(r)
        if on_result:
            on_result(r)
    return out


def summarise(results: List[CaseResult]) -> Dict[str, Any]:
    counts = {k: sum(1 for r in results if r.status == k) for k in ('pass', 'fail', 'error', 'skip')}
    return {'total': len(results), **counts, 'tools': len({r.tool for r in results}),
            'ok': counts['fail'] == 0 and counts['error'] == 0,
            'duration_ms': round(sum(r.duration_ms for r in results), 2)}


def render_text(results: List[CaseResult]) -> str:
    lines = []
    for r in results:
        mark = {'pass': 'PASS', 'fail': 'FAIL', 'error': 'ERROR', 'skip': 'SKIP'}[r.status]
        extra = f' [{r.mode}]' if r.mode != 'live' else ''
        lines.append(f'{mark:5} {r.tool} :: {r.case}  ({r.duration_ms:.0f} ms){extra}')
        if r.status != 'pass' and r.message:
            lines.append(f'      {r.message}')
            for f in r.failures[1:]:
                lines.append(f'      {f["message"]}')
    s = summarise(results)
    lines.append('')
    lines.append(f'{s["total"]} cases in {s["tools"]} tools: {s["pass"]} passed, {s["fail"]} failed, '
                 f'{s["error"]} errors, {s["skip"]} skipped')
    return '\n'.join(lines)


def render_junit(results: List[CaseResult], suite_name: str = 'sajha.quality') -> str:
    """JUnit XML: one <testsuite> per tool, one <testcase> per case."""
    by_tool: Dict[str, List[CaseResult]] = {}
    for r in results:
        by_tool.setdefault(r.tool, []).append(r)
    s = summarise(results)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites name={quoteattr(suite_name)} tests="{s["total"]}" failures="{s["fail"]}" '
           f'errors="{s["error"]}" skipped="{s["skip"]}" time="{s["duration_ms"] / 1000:.3f}">']
    for tool, rs in by_tool.items():
        ss = summarise(rs)
        out.append(f'  <testsuite name={quoteattr(tool)} tests="{ss["total"]}" failures="{ss["fail"]}" '
                   f'errors="{ss["error"]}" skipped="{ss["skip"]}" time="{ss["duration_ms"] / 1000:.3f}">')
        for r in rs:
            out.append(f'    <testcase classname={quoteattr("sajha.tools." + tool)} name={quoteattr(r.case)} '
                       f'time="{r.duration_ms / 1000:.3f}">')
            if r.status == 'fail':
                body = '\n'.join(f['message'] for f in r.failures) or r.message
                out.append(f'      <failure message={quoteattr(r.message[:500])}>{escape(body)}</failure>')
            elif r.status == 'error':
                out.append(f'      <error message={quoteattr(r.message[:500])}>{escape(r.message)}</error>')
            elif r.status == 'skip':
                out.append(f'      <skipped message={quoteattr(r.message[:500])}/>')
            if r.result_preview and r.status != 'pass':
                out.append(f'      <system-out>{escape(r.result_preview)}</system-out>')
            out.append('    </testcase>')
        out.append('  </testsuite>')
    out.append('</testsuites>')
    return '\n'.join(out) + '\n'
