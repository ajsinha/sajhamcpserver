"""
SAJHA MCP Server — the live tool check: call every read-only tool once and report which are broken.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Probes (``probes.py``) run only the cases someone wrote. The live check calls every eligible tool
once with arguments taken from structured data, never from description prose:

1. the tool's ``probe:`` case, else its first test case that is expected to succeed;
2. else the first entry of its ``inputSchema`` ``examples``;
3. else the ``examples`` (first) or ``default`` of each required property ({} when nothing is
   required).

A tool with no derivable arguments is ``not_checked`` (lint rule ``missing-example``). It skips
tools that are not ``readOnlyHint: true``, destructive tools, LLM tools (cost), proxied and SAJHA
Net tools (their own servers' business), tools bound to connected accounts, disabled tools and
``quality.check.exclude`` globs; each skip names its reason. A tool whose configured API key is
empty is ``not_configured`` without a call.

Outcomes: ``ok``, ``empty``, ``error``, ``schema_mismatch``, ``not_configured``, ``not_checked``,
``skipped``. Broken means ``error`` or ``schema_mismatch``. Load on upstreams: one call at a time
per tool folder (a provider), ``quality.check.pause_ms`` between calls in a folder, at most
``quality.check.concurrency`` folders at once, ``quality.check.timeout_seconds`` per call and a
total ``quality.check.budget_seconds``. One ``quality.check:<folder>`` warning notice per folder
with broken tools; it clears when the folder passes. The optional schedule
(``quality.check.cron``) rides the probe scheduler with its single-fire claim.

CLI: ``python -m sajha.quality check [--tool GLOB] [--folder NAME] [--json FILE] [--junit FILE]
[--save]``. Docs: docs/architecture/Tool Quality.md §12.4.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape, quoteattr

logger = logging.getLogger(__name__)

OUTCOMES = ('ok', 'empty', 'error', 'schema_mismatch', 'not_configured', 'not_checked', 'skipped')
BROKEN = frozenset({'error', 'schema_mismatch'})
NOTICE_PREFIX = 'quality.check:'
STATE_KEY = 'quality:check:last'

_KEY_FIELDS = re.compile(r'(^|_)(api_?key|apikey|token|access_key|secret)$', re.I)
_NEEDS_KEY = re.compile(r'(api[\s_-]?key|apikey|access[\s_-]?token|not configured|no credentials?|'
                        r'credentials? (are |is )?(missing|required)|requires? an? (api )?key|'
                        r'environment variable [A-Z0-9_]+ (is )?not set)', re.I)


# ── settings ────────────────────────────────────────────────────────────────

def _setting(key: str, default: str) -> str:
    from sajha.quality import setting
    return setting(f'check.{key}', default)


def _num(key: str, default: float) -> float:
    try:
        return float(_setting(key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def exclude_globs() -> List[str]:
    from sajha.core.config import parse_list
    return parse_list(_setting('exclude', ''))


# ── results ─────────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    tool: str
    folder: str
    outcome: str
    message: str = ''
    arguments_from: str = ''            # probe | test | examples | properties
    arguments: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error_class: str = ''

    def to_dict(self) -> Dict[str, Any]:
        return {'tool': self.tool, 'folder': self.folder, 'outcome': self.outcome, 'message': self.message,
                'arguments_from': self.arguments_from, 'arguments': self.arguments,
                'duration_ms': round(self.duration_ms, 1), 'error_class': self.error_class}


# ── arguments ───────────────────────────────────────────────────────────────

def derive_arguments(schema: Any, cases: Optional[List[Any]] = None,
                     probe_case: str = '') -> Tuple[Optional[Dict[str, Any]], str]:
    """``(arguments, where they came from)``, or ``(None, '')`` when none can be derived."""
    usable = [c for c in (cases or []) if not getattr(c, 'expects_error', False) and not getattr(c, 'skip', '')]
    if probe_case:
        hit = next((c for c in usable if c.name == probe_case), None)
        if hit is not None:
            return dict(hit.arguments or {}), 'probe'
    if usable:
        return dict(usable[0].arguments or {}), 'test'
    if not isinstance(schema, dict):
        return None, ''
    examples = schema.get('examples')
    if isinstance(examples, list) and examples and isinstance(examples[0], dict):
        return dict(examples[0]), 'examples'
    props = schema.get('properties') if isinstance(schema.get('properties'), dict) else {}
    required = schema.get('required') if isinstance(schema.get('required'), list) else []
    args: Dict[str, Any] = {}
    for name in required:
        sub = props.get(name)
        if not isinstance(sub, dict):
            return None, ''
        ex = sub.get('examples')
        if isinstance(ex, list) and ex:
            args[name] = ex[0]
        elif 'default' in sub:
            args[name] = sub['default']
        elif 'const' in sub:
            args[name] = sub['const']
        else:
            return None, ''
    return args, 'properties'


# ── eligibility ─────────────────────────────────────────────────────────────

def skip_reason(tool: Any, excludes: Optional[List[str]] = None) -> str:
    """Why the live check does not call ``tool`` ('' when it does)."""
    name = getattr(tool, 'name', '')
    if any(fnmatch.fnmatchcase(name, g) for g in (excludes if excludes is not None else exclude_globs())):
        return 'excluded by quality.check.exclude'
    if not getattr(tool, 'enabled', True):
        return 'disabled'
    if getattr(tool, 'apply_schema_defaults', True) is False or getattr(tool, 'namespaced_name', False):
        return 'proxied or remote tool (its own server checks it)'
    cfg = getattr(tool, 'config', None) or {}
    if isinstance(cfg.get('llm'), dict) or type(tool).__name__ == 'LLMTool':
        return 'LLM tool (each call costs tokens)'
    auth = cfg.get('auth') if isinstance(cfg.get('auth'), dict) else {}
    if auth.get('connected_account') or cfg.get('connected_account'):
        return 'bound to per-user credentials (connected account)'
    ann = cfg.get('annotations') if isinstance(cfg.get('annotations'), dict) else {}
    if ann.get('destructiveHint') is True:
        return 'destructive'
    if ann.get('readOnlyHint') is not True:
        return 'not marked read-only (readOnlyHint)'
    return ''


def missing_key(tool: Any) -> str:
    """The name of a configured key field that is empty or an unresolved ``${...}`` ('' when none)."""
    cfg = getattr(tool, 'config', None) or {}
    for k, v in cfg.items():
        if not isinstance(k, str) or not _KEY_FIELDS.search(k):
            continue
        if isinstance(v, str) and (not v.strip() or v.strip().startswith('${')):
            return k
    for attr in ('api_key',):
        if hasattr(tool, attr) and isinstance(getattr(tool, attr), str) and attr in cfg:
            if not getattr(tool, attr).strip():
                return attr
    return ''


# ── classification ──────────────────────────────────────────────────────────

def _is_empty(result: Any) -> bool:
    if result is None or result == {} or result == [] or result == '':
        return True
    if isinstance(result, dict):
        lists = [v for v in result.values() if isinstance(v, list)]
        return bool(lists) and all(len(v) == 0 for v in lists) and not any(
            isinstance(v, dict) and v for v in result.values())
    return False


def classify(tool: Any, result: Any = None, error: Optional[BaseException] = None) -> Tuple[str, str, str]:
    """``(outcome, message, error class)`` for one finished call."""
    if error is not None:
        msg = f'{type(error).__name__}: {error}'
        if _NEEDS_KEY.search(str(error)):
            return 'not_configured', msg[:500], type(error).__name__
        return 'error', msg[:500], type(error).__name__
    if isinstance(result, dict) and result.get('error'):
        text = str(result.get('error'))
        if _NEEDS_KEY.search(text):
            return 'not_configured', text[:500], 'error-result'
        return 'error', text[:500], 'error-result'
    if isinstance(result, dict) and result.get('isError') is True:
        return 'error', str(result.get('content') or '')[:500], 'isError'
    if _is_empty(result):
        return 'empty', 'the call succeeded but returned nothing', ''
    out_schema = None
    try:
        out_schema = tool.output_schema
    except Exception:
        pass
    if isinstance(out_schema, dict) and out_schema.get('properties') and isinstance(result, dict):
        try:
            from jsonschema import Draft202012Validator
            errs = sorted(Draft202012Validator(out_schema).iter_errors(result), key=lambda e: list(e.absolute_path))
            if errs:
                where = '/'.join(str(p) for p in errs[0].absolute_path) or '(root)'
                return 'schema_mismatch', f'{where}: {errs[0].message}'[:500], ''
        except Exception:
            pass
    return 'ok', '', ''


def _call_with_timeout(fn: Callable[[], Any], timeout: float) -> Tuple[Any, Optional[BaseException]]:
    box: Dict[str, Any] = {}

    def run():
        try:
            box['r'] = fn()
        except BaseException as e:        # noqa: BLE001 - a tool may raise anything
            box['e'] = e
    t = threading.Thread(target=run, name='sajha-check-call', daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, TimeoutError(f'no answer within {timeout:g} s')
    return box.get('r'), box.get('e')


def check_tool(tool: Any, folder: str, cases: Optional[List[Any]] = None, probe_case: str = '',
               timeout: Optional[float] = None, excludes: Optional[List[str]] = None) -> CheckResult:
    """Check one tool: skip, derive arguments, call it once (live), classify."""
    name = getattr(tool, 'name', '?')
    why = skip_reason(tool, excludes)
    if why:
        return CheckResult(name, folder, 'skipped', why)
    try:
        schema = tool.input_schema
    except Exception:
        schema = None
    args, source = derive_arguments(schema, cases, probe_case)
    if args is None:
        return CheckResult(name, folder, 'not_checked', 'no derivable arguments: add inputSchema examples')
    key = missing_key(tool)
    if key:
        return CheckResult(name, folder, 'not_configured', f'{key} is not set', source, args)
    from sajha.tools.schema_defaults import apply_for_tool
    filled, _ = apply_for_tool(tool, dict(args))
    t0 = time.perf_counter()

    def call():
        tool.validate_arguments(dict(filled))
        return tool.execute(dict(filled))
    result, error = _call_with_timeout(call, timeout if timeout is not None else _num('timeout_seconds', 60))
    elapsed = (time.perf_counter() - t0) * 1000
    outcome, message, err_class = classify(tool, result, error)
    return CheckResult(name, folder, outcome, message, source, args, elapsed, err_class)


# ── a run ───────────────────────────────────────────────────────────────────

def _folder_of(registry: Any, name: str) -> str:
    try:
        f = registry.tool_folder(name)
    except Exception:
        f = None
    return '(root)' if f == '' else (f or '(no file)')


def run_check(registry: Any, tool_glob: str = '', folder: str = '', suite: Any = None,
              pause_ms: Optional[float] = None, concurrency: Optional[int] = None,
              budget_seconds: Optional[float] = None, timeout: Optional[float] = None,
              notify: bool = True) -> List[CheckResult]:
    """Check the selected tools; one call at a time per folder; raise or clear folder notices."""
    if suite is None:
        from sajha.quality.cases import load_suite
        suite = load_suite(registry=registry)
    tools = getattr(registry, 'tools', {}) or {}
    globs = [g.strip() for g in (tool_glob or '').split(',') if g.strip()]
    by_folder: Dict[str, List[str]] = {}
    for name in sorted(tools):
        if globs and not any(fnmatch.fnmatchcase(name, g) for g in globs):
            continue
        f = _folder_of(registry, name)
        if folder and f != folder:
            continue
        by_folder.setdefault(f, []).append(name)
    pause = (pause_ms if pause_ms is not None else _num('pause_ms', 1000)) / 1000.0
    workers = max(1, int(concurrency if concurrency is not None else _num('concurrency', 4)))
    budget = budget_seconds if budget_seconds is not None else _num('budget_seconds', 1800)
    deadline = time.monotonic() + budget
    excludes = exclude_globs()
    probes = getattr(suite, 'probes', {}) or {}

    def run_folder(f: str) -> List[CheckResult]:
        out: List[CheckResult] = []
        called = False
        for name in by_folder[f]:
            tool = tools[name]
            if time.monotonic() > deadline:
                out.append(CheckResult(name, f, 'skipped', 'the run reached quality.check.budget_seconds'))
                continue
            if called and pause > 0 and not skip_reason(tool, excludes):
                time.sleep(pause)
            spec = probes.get(name)
            r = check_tool(tool, f, suite.for_tool(name) if suite is not None else [],
                           getattr(spec, 'case', '') if spec else '', timeout, excludes)
            called = called or r.outcome not in ('skipped', 'not_checked', 'not_configured')
            out.append(r)
        return out

    results: List[CheckResult] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='sajha-check') as pool:
        for chunk in pool.map(run_folder, sorted(by_folder)):
            results.extend(chunk)
    results.sort(key=lambda r: (r.folder, r.tool))
    _remember(results)
    if notify:
        update_notices(results)
    return results


def update_notices(results: List[CheckResult]) -> None:
    """One warning notice per checked folder with broken tools; a folder that passed clears its own."""
    try:
        from sajha import notices
    except Exception:
        return
    folders: Dict[str, List[CheckResult]] = {}
    for r in results:
        folders.setdefault(r.folder, []).append(r)
    for f, rs in folders.items():
        broken = [r for r in rs if r.outcome in BROKEN]
        nid = f'{NOTICE_PREFIX}{f}'
        if broken:
            lines = '; '.join(f'{r.tool}: {r.outcome}' + (f' ({r.message[:120]})' if r.message else '')
                              for r in broken[:20])
            more = f'; and {len(broken) - 20} more' if len(broken) > 20 else ''
            notices.raise_notice(nid, severity='warning', source='quality',
                                 title=f'Live tool check: {len(broken)} broken tool'
                                       f'{"s" if len(broken) != 1 else ""} in {f}',
                                 detail=f'{lines}{more}. Run python -m sajha.quality check --folder {f} '
                                        f'after a fix; the notice clears when the folder passes.',
                                 link='/admin/tool-health', audience='admin', ttl_minutes=0)
        else:
            notices.clear_notice(nid)


def _remember(results: List[CheckResult]) -> None:
    """The latest outcome per tool, in the state store, for the Tool Health page."""
    try:
        from sajha.core.state import get_state_store
        now = time.time()
        entries = {r.tool: {**r.to_dict(), 'at': now} for r in results}

        def upd(cur):
            cur = dict(cur or {})
            cur.update(entries)
            return cur
        get_state_store().update(STATE_KEY, upd)
    except Exception as e:
        logger.debug(f'live check: could not store the results: {e}')


def last_results() -> Dict[str, Dict[str, Any]]:
    try:
        from sajha.core.state import get_state_store
        return get_state_store().get(STATE_KEY) or {}
    except Exception:
        return {}


# ── reports ─────────────────────────────────────────────────────────────────

def summarise(results: List[CheckResult]) -> Dict[str, Any]:
    by = {o: sum(1 for r in results if r.outcome == o) for o in OUTCOMES}
    return {'tools': len(results), **by, 'broken': by['error'] + by['schema_mismatch'],
            'broken_folders': sorted({r.folder for r in results if r.outcome in BROKEN})}


def render_text(results: List[CheckResult], show_skipped: bool = False) -> str:
    lines: List[str] = []
    for r in results:
        if r.outcome == 'skipped' and not show_skipped:
            continue
        lines.append(f'{r.outcome:15} {r.folder:22} {r.tool:44} {r.message[:110]}')
    s = summarise(results)
    lines.append('')
    lines.append(f'{s["tools"]} tools: {s["ok"]} ok, {s["empty"]} empty, {s["error"]} error, '
                 f'{s["schema_mismatch"]} schema_mismatch, {s["not_configured"]} not_configured, '
                 f'{s["not_checked"]} not_checked, {s["skipped"]} skipped')
    return '\n'.join(lines)


def render_junit(results: List[CheckResult]) -> str:
    failures = sum(1 for r in results if r.outcome in BROKEN)
    skipped = sum(1 for r in results if r.outcome in ('skipped', 'not_checked', 'not_configured'))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<testsuites name="sajha.quality.check" tests="{len(results)}" failures="{failures}">',
           f'  <testsuite name="live-check" tests="{len(results)}" failures="{failures}" errors="0" '
           f'skipped="{skipped}">']
    for r in results:
        out.append(f'    <testcase classname={quoteattr("sajha.check." + r.folder)} name={quoteattr(r.tool)} '
                   f'time="{r.duration_ms / 1000:.3f}">')
        if r.outcome in BROKEN:
            out.append(f'      <failure message={quoteattr((r.outcome + ": " + r.message)[:300])}>'
                       f'{escape(r.message)}</failure>')
        elif r.outcome in ('skipped', 'not_checked', 'not_configured'):
            out.append(f'      <skipped message={quoteattr((r.outcome + ": " + r.message)[:300])}/>')
        out.append('    </testcase>')
    out.append('  </testsuite>')
    out.append('</testsuites>')
    return '\n'.join(out) + '\n'


# ── the optional schedule (rides the probe scheduler) ──────────────────────

_running = threading.Lock()


def cron() -> str:
    return (_setting('cron', '') or '').strip()


def scheduled_run(registry: Any) -> bool:
    """Run a whole check in the background unless one is already running here."""
    if not _running.acquire(blocking=False):
        return False

    def go():
        try:
            results = run_check(registry)
            try:
                from sajha.quality.store import get_run_store
                get_run_store().save('check', 'scheduled live check', summarise(results),
                                     [r.to_dict() for r in results], created_by='schedule')
            except Exception as e:
                logger.info(f'live check: run not saved: {e}')
        except Exception as e:
            logger.warning(f'live check failed: {e}', exc_info=True)
        finally:
            _running.release()
    threading.Thread(target=go, name='sajha-live-check', daemon=True).start()
    return True
