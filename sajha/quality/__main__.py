"""
SAJHA MCP Server — the tool quality command line.

    python -m sajha.quality test    [--tool GLOB] [--case GLOB] [--tag TAG] [--record|--replay|--live]
                                    [--junit FILE] [--json FILE] [--save]
    python -m sajha.quality lint    [--tool GLOB] [--strict] [--info] [--junit FILE] [--json FILE]
    python -m sajha.quality eval    [SET ...] [--model M ...] [--planner P ...] [--json FILE] [--junit FILE] [--no-save]
    python -m sajha.quality compare RUN_A RUN_B      (saved run ids, or JSON files written by eval --json)
    python -m sajha.quality runs    [--kind test|eval] [--limit N]
    python -m sajha.quality probe   TOOL             (run one tool's probe now, live)

Exit status: 0 success, 1 failures (or lint errors), 2 usage error.
Docs: docs/architecture/Tool Quality.md

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, List, Optional


def _registry():
    from sajha.tools.tools_registry import get_tools_registry
    from sajha.core.config import _get
    reg = get_tools_registry(_get('config.tools_dir', 'config/tools') or 'config/tools')
    try:
        reg.stop_monitoring()
    except Exception:
        pass
    return reg


def _write(path: Optional[str], text: str) -> None:
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding='utf-8')


def cmd_test(a) -> int:
    from sajha.quality import cases as C, runner as R
    reg = _registry()
    suite = C.load_suite(registry=reg)
    for e in suite.errors:
        print(f'test file error: {e}', file=sys.stderr)
    selected = C.select(suite.cases, a.tool or '', a.case or '', a.tag or None)
    if not selected:
        print('no test cases matched', file=sys.stderr)
        return 1 if suite.errors else 0
    mode = 'record' if a.record else 'replay' if a.replay else 'live' if a.live else 'auto'
    results = R.run_cases(reg, selected, mode)
    print(R.render_text(results))
    _write(a.junit, R.render_junit(results))
    summary = R.summarise(results)
    if a.json:
        _write(a.json, json.dumps({'summary': summary, 'results': [r.to_dict() for r in results]}, indent=2))
    if a.save:
        try:
            from sajha.quality.store import get_run_store
            rid = get_run_store().save('test', f'cli {a.tool or "all"} ({mode})', {**summary, 'mode': mode},
                                       [r.to_dict() for r in results], created_by='cli')
            print(f'saved run {rid}')
        except Exception as e:
            print(f'could not save the run: {e}', file=sys.stderr)
    return 0 if summary['ok'] and not suite.errors else 1


def cmd_lint(a) -> int:
    from sajha.quality import cases as C, lint as L
    reg = _registry()
    suite = C.load_suite(registry=reg)
    findings = L.lint_registry(reg, a.tool or '', suite)
    import fnmatch
    names = sorted(n for n in reg.tools if not a.tool or any(fnmatch.fnmatchcase(n, g.strip()) for g in a.tool.split(',')))
    print(L.render_text(findings, len(names), show_info=a.info))
    _write(a.junit, L.render_junit(findings, names, a.strict))
    if a.json:
        _write(a.json, json.dumps({'summary': L.summarise(findings), 'findings': [f.to_dict() for f in findings]}, indent=2))
    s = L.summarise(findings)
    return 1 if s['error'] or (a.strict and s['warning']) else 0


def _cli_service():
    from sajha.ai.llm import build_llm_factory
    from sajha.ai.intelligence import IntelligenceService
    gw = build_llm_factory(None)
    return IntelligenceService(gw, _registry(), audit=lambda e: None)


def cmd_eval(a) -> int:
    from sajha.quality import evals as E
    sets = E.load_sets(a.dir)
    if not sets:
        print(f'no eval sets in {a.dir or "quality.evals_dir"}', file=sys.stderr)
        return 2
    chosen = a.sets or sorted(sets)
    unknown = [s for s in chosen if s not in sets]
    if unknown:
        print(f'unknown eval set(s): {", ".join(unknown)}; have: {", ".join(sorted(sets))}', file=sys.stderr)
        return 2
    svc = _cli_service()
    runs = []
    for name in chosen:
        es = sets[name]
        for model, planner in E.combos(es, a.model, a.planner):
            run = E.run_set(svc, es, model or None, planner or None)
            runs.append(run)
            print(E.render_text(run))
            if not a.no_save:
                try:
                    from sajha.quality.store import get_run_store
                    rid = get_run_store().save('eval', E.run_name(run),
                                               {**run['summary'], 'set': run['set'], 'model': run['model'],
                                                'planner': run['planner']}, run, created_by='cli',
                                               started_at=run['started_at'])
                    run['id'] = rid
                    print(f'  saved run {rid}')
                except Exception as e:
                    print(f'  could not save the run: {e}', file=sys.stderr)
            print()
    if a.json:
        _write(a.json, json.dumps(runs[0] if len(runs) == 1 else runs, indent=2, default=str))
    _write(a.junit, E.render_junit(runs))
    return 0 if all(r['summary']['passed'] == r['summary']['questions'] for r in runs) else 1


def _load_run(ref: str) -> Any:
    p = Path(ref)
    if p.is_file():
        data = json.loads(p.read_text(encoding='utf-8'))
        return data[0] if isinstance(data, list) else data
    from sajha.quality.evals import saved_run
    run = saved_run(ref)
    if run is None:
        raise SystemExit(f'no saved eval run or JSON file {ref!r}')
    return run


def cmd_compare(a) -> int:
    from sajha.quality import evals as E
    c = E.compare(_load_run(a.a), _load_run(a.b))
    print(E.render_compare(c))
    if a.json:
        _write(a.json, json.dumps(c, indent=2))
    return 1 if c['regressed'] else 0


def cmd_runs(a) -> int:
    from sajha.quality.store import get_run_store
    import datetime as _dt
    for r in get_run_store().list(a.kind, a.limit):
        s = r['summary']
        when = _dt.datetime.fromtimestamp(r['started_at']).strftime('%Y-%m-%d %H:%M')
        if r['kind'] == 'eval':
            stat = f'pass {s.get("passed", "?")}/{s.get("questions", "?")}'
        else:
            stat = f'pass {s.get("pass", "?")}/{s.get("total", "?")}'
        print(f'{r["id"]}  {when}  {r["kind"]:4}  {r["status"]:7}  {stat:14}  {r["name"]}')
    return 0


def cmd_probe(a) -> int:
    from sajha.quality import cases as C, probes as P
    reg = _registry()
    suite = C.load_suite(registry=reg)
    spec = suite.probes.get(a.tool)
    if spec is None:
        print(f'{a.tool} has no probe (add probe: to its test file)', file=sys.stderr)
        return 2
    entry = P.run_probe(reg, spec, suite, trigger='cli')
    print(f'{a.tool}: {entry["status"]} in {entry["duration_ms"]:.0f} ms {entry["message"]}')
    return 0 if entry['status'] == 'pass' else 1


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog='python -m sajha.quality', description='SAJHA tool quality: tests, lint, evals.')
    p.add_argument('-v', '--verbose', action='store_true', help='log at INFO')
    sub = p.add_subparsers(dest='cmd', required=True)

    t = sub.add_parser('test', help='run tool test cases')
    t.add_argument('--tool', help='tool name glob(s), comma-separated')
    t.add_argument('--case', help='case name glob')
    t.add_argument('--tag', action='append', help='only cases with this tag (repeatable)')
    m = t.add_mutually_exclusive_group()
    m.add_argument('--record', action='store_true', help='call live services and write cassettes')
    m.add_argument('--replay', action='store_true', help='serve HTTP only from cassettes (no network)')
    m.add_argument('--live', action='store_true', help='ignore cassettes')
    t.add_argument('--junit', help='write JUnit XML here')
    t.add_argument('--json', help='write JSON results here')
    t.add_argument('--save', action='store_true', help='save the run (quality_runs) for the Tool Health page')
    t.set_defaults(fn=cmd_test)

    li = sub.add_parser('lint', help='lint every tool\'s schemas, descriptions and annotations')
    li.add_argument('--tool', help='tool name glob(s), comma-separated')
    li.add_argument('--strict', action='store_true', help='warnings fail too')
    li.add_argument('--info', action='store_true', help='show notes')
    li.add_argument('--junit')
    li.add_argument('--json')
    li.set_defaults(fn=cmd_lint)

    e = sub.add_parser('eval', help='run Ask SAJHA eval sets')
    e.add_argument('sets', nargs='*', help='set names (default: all)')
    e.add_argument('--dir', help='eval directory (default quality.evals_dir)')
    e.add_argument('--model', action='append', help='model or alias (repeatable)')
    e.add_argument('--planner', action='append', help='planner (repeatable)')
    e.add_argument('--json')
    e.add_argument('--junit')
    e.add_argument('--no-save', action='store_true', help='do not save the runs')
    e.set_defaults(fn=cmd_eval)

    c = sub.add_parser('compare', help='compare two eval runs')
    c.add_argument('a')
    c.add_argument('b')
    c.add_argument('--json')
    c.set_defaults(fn=cmd_compare)

    r = sub.add_parser('runs', help='list saved runs')
    r.add_argument('--kind', choices=['test', 'eval'])
    r.add_argument('--limit', type=int, default=20)
    r.set_defaults(fn=cmd_runs)

    pr = sub.add_parser('probe', help='run one tool\'s health probe now')
    pr.add_argument('tool')
    pr.set_defaults(fn=cmd_probe)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.ERROR, format='%(levelname)s %(name)s: %(message)s')
    if not a.verbose:
        logging.disable(logging.ERROR)      # a tool's own error logs; results carry the message
    return a.fn(a)


if __name__ == '__main__':
    sys.exit(main())
