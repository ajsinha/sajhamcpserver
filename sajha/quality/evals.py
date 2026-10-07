"""
SAJHA MCP Server — evals for Ask SAJHA: golden question sets, a runner, scores and comparison.

An eval set (``quality.evals_dir``, ``config/evals/*.yaml``) lists questions with the tools
that should be called, checks on the answer, and limits (steps, tokens, cost, latency). The
runner asks every question through ``IntelligenceService.ask`` once per (model, planner) and
scores tool selection, answer checks and limits. A set with ``tool: <name>`` evaluates that LLM
tool instead (sajha/ai/llm_tools): each question's ``arguments`` (default ``{question: ...}``)
are its call, and the checks apply to its answer, text or label. Runs are saved in ``quality_runs`` and two
runs can be compared. Works offline on the mock provider. Docs: docs/architecture/Tool Quality.md §5.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

ANSWER_CHECKS = ('contains', 'not_contains', 'regex', 'number', 'equals')
_NUM = re.compile(r'-?\d[\d,]*(?:\.\d+)?')


class EvalError(ValueError):
    """An eval set that is not valid."""


@dataclass
class EvalQuestion:
    id: str
    question: str
    expect_tools: List[str] = field(default_factory=list)
    forbid_tools: List[str] = field(default_factory=list)
    answer: List[Dict[str, Any]] = field(default_factory=list)
    max_steps: Optional[int] = None
    max_tokens: Optional[int] = None
    max_cost_usd: Optional[float] = None
    max_latency_ms: Optional[float] = None
    expect_stop: str = 'answer'
    arguments: Optional[Dict[str, Any]] = None       # an LLM-tool set: the call's arguments


@dataclass
class EvalSet:
    name: str
    description: str = ''
    models: List[str] = field(default_factory=list)
    planners: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    questions: List[EvalQuestion] = field(default_factory=list)
    source: str = ''
    tool: str = ''                                   # an LLM tool to evaluate instead of Ask SAJHA

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'description': self.description, 'models': self.models,
                'planners': self.planners, 'tools': self.tools, 'questions': len(self.questions),
                'source': self.source, 'tool': self.tool}


def _num(v: Any, what: str, cast=float):
    if v is None:
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        raise EvalError(f'{what} must be a number')


def _validate_check(c: Any, where: str) -> Dict[str, Any]:
    if not isinstance(c, dict) or not (set(c) & set(ANSWER_CHECKS)):
        raise EvalError(f'{where}: an answer check needs one of {", ".join(ANSWER_CHECKS)}')
    unknown = set(c) - set(ANSWER_CHECKS) - {'tolerance', 'flags'}
    if unknown:
        raise EvalError(f'{where}: unknown keys {sorted(unknown)}')
    if 'regex' in c:
        try:
            re.compile(str(c['regex']))
        except re.error as e:
            raise EvalError(f'{where}: bad regex: {e}')
    if 'number' in c:
        _num(c['number'], f'{where}: number')
    return c


def parse_set(doc: Any, source: str = '') -> EvalSet:
    if not isinstance(doc, dict):
        raise EvalError(f'{source}: an eval set is an object with "name" and "questions"')
    name = str(doc.get('name') or Path(source).stem or '')
    if not name:
        raise EvalError(f'{source}: "name" is required')
    defaults = doc.get('defaults') or {}
    if not isinstance(defaults, dict):
        raise EvalError(f'{source}: defaults must be an object')

    def lst(v, what):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        if not isinstance(v, list):
            raise EvalError(f'{source}: {what} must be a list')
        return [str(x) for x in v]

    es = EvalSet(name=name, description=str(doc.get('description') or ''), models=lst(doc.get('models') or doc.get('model'), 'models'),
                 planners=lst(doc.get('planners') or doc.get('planner'), 'planners'), tools=lst(doc.get('tools'), 'tools'),
                 source=source, tool=str(doc.get('tool') or ''))
    qs = doc.get('questions') or []
    if not isinstance(qs, list) or not qs:
        raise EvalError(f'{source}: questions must be a non-empty list')
    seen = set()
    for i, q in enumerate(qs):
        if not isinstance(q, dict) or not str(q.get('question') or '').strip():
            raise EvalError(f'{source}: question {i + 1} needs "question"')
        qid = str(q.get('id') or f'q{i + 1}')
        if qid in seen:
            raise EvalError(f'{source}: duplicate question id {qid!r}')
        seen.add(qid)
        merged = {**defaults, **q}
        if q.get('arguments') is not None and not isinstance(q.get('arguments'), dict):
            raise EvalError(f'{source}: {qid}: arguments must be an object')
        checks = merged.get('answer') or []
        if isinstance(checks, dict):
            checks = [checks]
        es.questions.append(EvalQuestion(
            id=qid, question=str(q['question']).strip(),
            expect_tools=lst(merged.get('expect_tools'), 'expect_tools'),
            forbid_tools=lst(merged.get('forbid_tools'), 'forbid_tools'),
            answer=[_validate_check(c, f'{source}: {qid}') for c in checks],
            max_steps=_num(merged.get('max_steps'), f'{qid}: max_steps', int),
            max_tokens=_num(merged.get('max_tokens'), f'{qid}: max_tokens', int),
            max_cost_usd=_num(merged.get('max_cost_usd'), f'{qid}: max_cost_usd'),
            max_latency_ms=_num(merged.get('max_latency_ms'), f'{qid}: max_latency_ms'),
            expect_stop=str(merged.get('expect_stop') or 'answer'),
            arguments=dict(q['arguments']) if isinstance(q.get('arguments'), dict) else None))
    return es


def load_sets(directory: Optional[str] = None) -> Dict[str, EvalSet]:
    """Every eval set in the directory, by name (invalid files are logged and skipped)."""
    from sajha.quality import evals_dir
    root = Path(directory or evals_dir())
    out: Dict[str, EvalSet] = {}
    if not root.is_dir():
        return out
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.suffix.lower() not in ('.yaml', '.yml', '.json'):
            continue
        try:
            text = p.read_text(encoding='utf-8')
            if p.suffix.lower() == '.json':
                doc = json.loads(text)
            else:
                import yaml
                doc = yaml.safe_load(text)
            es = parse_set(doc, str(p))
            out[es.name] = es
        except Exception as e:
            logger.warning(f'eval set {p}: {e} (skipped)')
    return out


# ── scoring ─────────────────────────────────────────────────────────

def check_answer(check: Dict[str, Any], answer: str) -> Optional[str]:
    """None when the check passes, else why not."""
    text = answer or ''
    low = text.lower()
    if 'contains' in check and str(check['contains']).lower() not in low:
        return f'answer does not contain {check["contains"]!r}'
    if 'not_contains' in check and str(check['not_contains']).lower() in low:
        return f'answer contains {check["not_contains"]!r}'
    if 'equals' in check and text.strip().lower() != str(check['equals']).strip().lower():
        return f'answer is not {check["equals"]!r}'
    if 'regex' in check:
        flags = re.I if 'i' in str(check.get('flags', 'i')) else 0
        if not re.search(str(check['regex']), text, flags):
            return f'answer does not match /{check["regex"]}/'
    if 'number' in check:
        target = float(check['number'])
        tol = float(check.get('tolerance', 0) or 0)
        nums = []
        for m in _NUM.findall(text):
            try:
                nums.append(float(m.replace(',', '')))
            except ValueError:
                pass
        if not any(abs(n - target) <= tol for n in nums):
            return f'no number in the answer is {target:g}' + (f' ± {tol:g}' if tol else '')
    return None


def _matches(name: str, patterns: List[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def score(q: EvalQuestion, result: Any) -> Dict[str, Any]:
    """Score one AskResult (or an LLM tool's RunInfo) against its question."""
    called = [getattr(s, 'name', s) for s in (result.steps or [])]
    called_set = set(called)
    missing = [t for t in q.expect_tools if not any(fnmatch.fnmatchcase(c, t) for c in called_set)]
    forbidden = sorted({c for c in called_set if _matches(c, q.forbid_tools)})
    tool_ok = not missing and not forbidden
    expected_hit = [c for c in called_set if _matches(c, q.expect_tools)]
    recall = (len(q.expect_tools) - len(missing)) / len(q.expect_tools) if q.expect_tools else 1.0
    precision = (len(expected_hit) / len(called_set)) if called_set else (1.0 if not q.expect_tools else 0.0)
    answer_fail = [m for m in (check_answer(c, result.answer) for c in q.answer) if m]
    usage = result.usage
    tokens = int(getattr(usage, 'total_tokens', 0) or 0)
    cost = float(getattr(usage, 'cost_usd', 0.0) or 0.0)
    limits = []
    if q.max_steps is not None and len(called) > q.max_steps:
        limits.append(f'{len(called)} steps > {q.max_steps}')
    if q.max_tokens is not None and tokens > q.max_tokens:
        limits.append(f'{tokens} tokens > {q.max_tokens}')
    if q.max_cost_usd is not None and cost > q.max_cost_usd:
        limits.append(f'${cost:.4f} > ${q.max_cost_usd:.4f}')
    if q.max_latency_ms is not None and result.duration_ms > q.max_latency_ms:
        limits.append(f'{result.duration_ms} ms > {q.max_latency_ms:.0f} ms')
    if q.expect_stop and result.stopped_by != q.expect_stop:
        limits.append(f'stopped by {result.stopped_by}, expected {q.expect_stop}')
    reasons = ([f'missing tools: {", ".join(missing)}'] if missing else []) + \
              ([f'forbidden tools called: {", ".join(forbidden)}'] if forbidden else []) + answer_fail + limits
    return {'id': q.id, 'question': q.question, 'passed': tool_ok and not answer_fail and not limits,
            'tool_ok': tool_ok, 'answer_ok': not answer_fail, 'limits_ok': not limits,
            'tools_called': called, 'expect_tools': q.expect_tools, 'tool_recall': round(recall, 4),
            'tool_precision': round(precision, 4), 'steps': len(called), 'tokens': tokens, 'cost_usd': round(cost, 6),
            'latency_ms': int(result.duration_ms or 0), 'stopped_by': result.stopped_by,
            'answer': (result.answer or '')[:2000], 'error': result.error or '', 'reasons': reasons,
            'models': list(result.models or []), 'planner': result.planner or ''}


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return float(s[min(len(s) - 1, max(0, int(round(0.95 * len(s) + 0.5)) - 1))])


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows) or 1
    lat = [r['latency_ms'] for r in rows]
    return {'questions': len(rows), 'passed': sum(r['passed'] for r in rows),
            'pass_rate': round(sum(r['passed'] for r in rows) / n, 4),
            'tool_selection_accuracy': round(sum(r['tool_ok'] for r in rows) / n, 4),
            'answer_accuracy': round(sum(r['answer_ok'] for r in rows) / n, 4),
            'limits_ok_rate': round(sum(r['limits_ok'] for r in rows) / n, 4),
            'mean_tool_recall': round(sum(r['tool_recall'] for r in rows) / n, 4),
            'mean_tool_precision': round(sum(r['tool_precision'] for r in rows) / n, 4),
            'mean_steps': round(sum(r['steps'] for r in rows) / n, 3),
            'total_tokens': sum(r['tokens'] for r in rows), 'mean_tokens': round(sum(r['tokens'] for r in rows) / n, 1),
            'total_cost_usd': round(sum(r['cost_usd'] for r in rows), 6),
            'mean_latency_ms': round(sum(lat) / n, 1), 'p95_latency_ms': _p95(lat)}


# ── running ─────────────────────────────────────────────────────────

class FilteredRegistry:
    """A registry view that holds only the tools matching ``patterns``."""

    def __init__(self, registry: Any, patterns: List[str]):
        self._registry = registry
        self.patterns = list(patterns)
        self.tools = {n: t for n, t in (getattr(registry, 'tools', {}) or {}).items() if _matches(n, self.patterns)}

    def get_tool(self, name: str):
        return self.tools.get(name)

    def __getattr__(self, item):
        return getattr(self._registry, item)


def run_set(service: Any, es: EvalSet, model: Optional[str] = None, planner: Optional[str] = None,
            ctx: Any = None, on_question: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Ask every question of ``es`` once on ``model``/``planner``; returns {set, model, planner, summary, questions}."""
    from sajha.ai.llm import RequestContext
    if es.tool:
        return run_tool_set(service, es, model, ctx, on_question)
    if es.tools:
        from sajha.ai.intelligence import IntelligenceService
        service = IntelligenceService(service.gateway, FilteredRegistry(service.tools_registry, es.tools),
                                      settings=service.settings, audit=lambda e: None)
    ctx = ctx or RequestContext(user_id='eval', roles=['admin'], is_admin=True)
    rows = []
    t0 = time.time()
    for q in es.questions:
        try:
            res = service.ask(q.question, ctx, model=model or None, planner=planner or None)
            row = score(q, res)
        except Exception as e:
            logger.warning(f'eval {es.name}/{q.id}: {e}', exc_info=True)
            row = {'id': q.id, 'question': q.question, 'passed': False, 'tool_ok': False, 'answer_ok': False,
                   'limits_ok': False, 'tools_called': [], 'expect_tools': q.expect_tools, 'tool_recall': 0.0,
                   'tool_precision': 0.0, 'steps': 0, 'tokens': 0, 'cost_usd': 0.0, 'latency_ms': 0,
                   'stopped_by': 'error', 'answer': '', 'error': str(e), 'reasons': [f'ask failed: {e}'],
                   'models': [], 'planner': planner or ''}
        rows.append(row)
        if on_question:
            on_question(row)
    return {'set': es.name, 'model': model or 'default', 'planner': planner or 'default',
            'started_at': t0, 'duration_s': round(time.time() - t0, 3),
            'summary': summarise(rows), 'questions': rows}


def _llm_tool(service: Any, name: str):
    """The LLM tool ``name`` from the service's registry, or built from its config even when disabled."""
    reg = service.tools_registry
    tool = reg.get_tool(name) if reg is not None else None
    if tool is None:
        cfg = (getattr(reg, 'tool_configs', {}) or {}).get(name)
        if cfg is None:
            raise EvalError(f'no tool {name!r} in the catalog')
        import importlib
        mod, cls = str(cfg.get('implementation')).rsplit('.', 1)
        tool = getattr(importlib.import_module(mod), cls)(cfg)
    if not hasattr(tool, 'run') or not isinstance(getattr(tool, 'config', {}).get('llm'), dict):
        raise EvalError(f'{name} is not an LLM tool')
    tool.registry, tool.service, tool.gateway = reg, service, service.gateway
    return tool


def run_tool_set(service: Any, es: EvalSet, model: Optional[str] = None, ctx: Any = None,
                 on_question: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Call the set's LLM tool once per question (memory off, no audit record) and score each run."""
    from sajha.ai.llm import RequestContext
    tool = _llm_tool(service, es.tool)
    ctx = ctx or RequestContext(user_id='eval', roles=['admin'], is_admin=True)
    rows = []
    t0 = time.time()
    for q in es.questions:
        args = dict(q.arguments) if q.arguments is not None else {'question': q.question}
        try:
            info = tool.run(args, ctx=ctx, model=model or None, remember=False, audit=False)
            row = score(q, info)
        except Exception as e:
            logger.warning(f'eval {es.name}/{q.id}: {e}', exc_info=True)
            row = {'id': q.id, 'question': q.question, 'passed': False, 'tool_ok': False, 'answer_ok': False,
                   'limits_ok': False, 'tools_called': [], 'expect_tools': q.expect_tools, 'tool_recall': 0.0,
                   'tool_precision': 0.0, 'steps': 0, 'tokens': 0, 'cost_usd': 0.0, 'latency_ms': 0,
                   'stopped_by': 'error', 'answer': '', 'error': str(e), 'reasons': [f'call failed: {e}'],
                   'models': [], 'planner': ''}
        rows.append(row)
        if on_question:
            on_question(row)
    return {'set': es.name, 'model': model or 'default', 'planner': f'tool:{es.tool}',
            'started_at': t0, 'duration_s': round(time.time() - t0, 3),
            'summary': summarise(rows), 'questions': rows}


def combos(es: EvalSet, models: Optional[List[str]] = None, planners: Optional[List[str]] = None):
    ms = [m for m in (models or es.models or ['']) if m is not None]
    ps = [p for p in (planners or es.planners or ['']) if p is not None]
    return [(m, p) for m in ms for p in ps]


def run_name(run: Dict[str, Any]) -> str:
    return f'{run["set"]} · {run["model"]} · {run["planner"]}'


# ── comparison ──────────────────────────────────────────────────────

COMPARED = ('pass_rate', 'tool_selection_accuracy', 'answer_accuracy', 'mean_steps', 'mean_tokens',
            'total_cost_usd', 'mean_latency_ms', 'p95_latency_ms')
HIGHER_IS_BETTER = {'pass_rate', 'tool_selection_accuracy', 'answer_accuracy'}


def compare(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Metric deltas (b - a) and the questions that regressed (passed in a, not in b) or improved."""
    sa, sb = a.get('summary') or {}, b.get('summary') or {}
    metrics = []
    for k in COMPARED:
        va, vb = sa.get(k), sb.get(k)
        if va is None or vb is None:
            continue
        delta = round(float(vb) - float(va), 6)
        better = (delta > 0) if k in HIGHER_IS_BETTER else (delta < 0)
        metrics.append({'metric': k, 'a': va, 'b': vb, 'delta': delta,
                        'direction': 'same' if delta == 0 else ('better' if better else 'worse')})
    qa = {q['id']: q for q in a.get('questions') or []}
    qb = {q['id']: q for q in b.get('questions') or []}
    regressed, improved, changed_tools = [], [], []
    for qid in sorted(set(qa) & set(qb)):
        x, y = qa[qid], qb[qid]
        if x['passed'] and not y['passed']:
            regressed.append({'id': qid, 'question': y['question'], 'reasons': y.get('reasons', [])})
        elif y['passed'] and not x['passed']:
            improved.append({'id': qid, 'question': y['question']})
        if x.get('tools_called') != y.get('tools_called'):
            changed_tools.append({'id': qid, 'a': x.get('tools_called'), 'b': y.get('tools_called')})
    return {'a': {'set': a.get('set'), 'model': a.get('model'), 'planner': a.get('planner')},
            'b': {'set': b.get('set'), 'model': b.get('model'), 'planner': b.get('planner')},
            'metrics': metrics, 'regressed': regressed, 'improved': improved, 'changed_tools': changed_tools,
            'only_in_a': sorted(set(qa) - set(qb)), 'only_in_b': sorted(set(qb) - set(qa))}


def render_text(run: Dict[str, Any]) -> str:
    s = run['summary']
    lines = [f'{run_name(run)}']
    for q in run['questions']:
        lines.append(f'  {"PASS" if q["passed"] else "FAIL"} {q["id"]}: tools={",".join(q["tools_called"]) or "-"} '
                     f'steps={q["steps"]} tokens={q["tokens"]} {q["latency_ms"]} ms')
        for r in q['reasons']:
            lines.append(f'       {r}')
    lines.append(f'  pass {s["passed"]}/{s["questions"]} ({s["pass_rate"]:.0%}) · tool selection '
                 f'{s["tool_selection_accuracy"]:.0%} · answers {s["answer_accuracy"]:.0%} · mean steps {s["mean_steps"]} · '
                 f'tokens {s["total_tokens"]} · cost ${s["total_cost_usd"]:.4f} · p95 {s["p95_latency_ms"]:.0f} ms')
    return '\n'.join(lines)


def render_compare(c: Dict[str, Any]) -> str:
    lines = [f'A: {c["a"]["set"]} · {c["a"]["model"]} · {c["a"]["planner"]}',
             f'B: {c["b"]["set"]} · {c["b"]["model"]} · {c["b"]["planner"]}', '']
    for m in c['metrics']:
        lines.append(f'  {m["metric"]:26} {m["a"]!s:>10} -> {m["b"]!s:>10}  ({m["delta"]:+g}, {m["direction"]})')
    if c['regressed']:
        lines.append('')
        lines.append('Regressed:')
        lines += [f'  {q["id"]}: {"; ".join(q["reasons"])}' for q in c['regressed']]
    if c['improved']:
        lines.append('')
        lines.append('Improved: ' + ', '.join(q['id'] for q in c['improved']))
    return '\n'.join(lines)


def render_junit(runs: List[Dict[str, Any]]) -> str:
    from xml.sax.saxutils import escape, quoteattr
    total = sum(len(r['questions']) for r in runs)
    fails = sum(1 for r in runs for q in r['questions'] if not q['passed'])
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites name="sajha.quality.evals" tests="{total}" failures="{fails}">']
    for r in runs:
        f = sum(1 for q in r['questions'] if not q['passed'])
        out.append(f'  <testsuite name={quoteattr(run_name(r))} tests="{len(r["questions"])}" failures="{f}" '
                   f'errors="0" skipped="0" time="{r.get("duration_s", 0):.3f}">')
        for q in r['questions']:
            out.append(f'    <testcase classname={quoteattr("sajha.evals." + r["set"])} name={quoteattr(q["id"])} '
                       f'time="{q["latency_ms"] / 1000:.3f}">')
            if not q['passed']:
                msg = '; '.join(q['reasons']) or 'failed'
                out.append(f'      <failure message={quoteattr(msg[:500])}>{escape(msg)}</failure>')
            out.append('    </testcase>')
        out.append('  </testsuite>')
    out.append('</testsuites>')
    return '\n'.join(out) + '\n'


# ── background runs (the Evals page) ────────────────────────────────

def start_background(service: Any, es: EvalSet, model: str, planner: str, created_by: str, ctx: Any = None) -> str:
    """Record a 'running' row, run the set in a daemon thread, finish the row; returns the run id."""
    import threading
    from sajha.quality.store import get_run_store
    store = get_run_store()
    name = run_name({'set': es.name, 'model': model or 'default', 'planner': planner or 'default'})
    rid = store.start('eval', name, created_by, {'set': es.name, 'model': model or 'default',
                                                 'planner': planner or 'default'})

    def work():
        try:
            run = run_set(service, es, model, planner, ctx)
            store.finish(rid, {**run['summary'], 'set': run['set'], 'model': run['model'], 'planner': run['planner']},
                         run, 'done')
        except Exception as e:
            logger.error(f'eval run {rid} failed: {e}', exc_info=True)
            try:
                store.finish(rid, {'set': es.name, 'error': str(e)}, None, 'failed')
            except Exception:
                pass
    threading.Thread(target=work, name=f'sajha-eval-{rid[:8]}', daemon=True).start()
    return rid


def saved_run(rid: str) -> Optional[Dict[str, Any]]:
    """A saved eval run (its detail is the run dict)."""
    from sajha.quality.store import get_run_store
    row = get_run_store().get(rid)
    if not row or row['kind'] != 'eval' or not isinstance(row.get('detail'), dict):
        return None
    return row['detail']
