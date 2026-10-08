"""
SAJHA MCP Server — the workflow definition: parse (JSON or YAML), validate, normalise.

A workflow is a DAG of steps. Each step has an ``id``, a ``kind`` and ``depends_on``
(plus the implicit dependencies of every ``$steps.<id>`` it reads and of the condition
whose ``then``/``else`` names it). See docs/architecture/Workflows.md for every field.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List

from sajha.workflows import expr

STEP_KINDS = ('tool', 'composite', 'ask', 'condition', 'foreach', 'wait', 'approval')
INNER_KINDS = ('tool', 'composite', 'ask')          # what a foreach runs per item
TRIGGER_TYPES = ('cron', 'webhook', 'file', 'event', 'manual')
JOINS = ('all_success', 'any_success', 'all_done')
ON_ERROR = ('fail', 'continue')
DELIVERY_TYPES = ('webhook', 'file', 'kafka')
EVENT_KINDS = ('tools', 'prompts', 'resources', 'resource_updated')

NAME_RE = re.compile(r'^(?!.*__)[A-Za-z][A-Za-z0-9_\-]{0,99}$')   # no '__': reserved (sajha/tools/naming.py)
RESERVED_NAMES = ('runs', 'validate')
MASK = '********'          # how a webhook secret is shown; saving it back keeps the stored secret
ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,99}$')


class WorkflowError(ValueError):
    """A definition that cannot be saved or run."""


def parse_text(text: str) -> Dict[str, Any]:
    """A definition from JSON or YAML text."""
    text = (text or '').strip()
    if not text:
        raise WorkflowError('the definition is empty')
    try:
        data = json.loads(text)
    except ValueError:
        import yaml
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise WorkflowError(f'neither JSON nor YAML: {e}') from e
    if not isinstance(data, dict):
        raise WorkflowError('a definition is an object (name, steps, ...)')
    return data


def to_yaml(defn: Dict[str, Any]) -> str:
    import yaml
    return yaml.safe_dump(defn, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _num(v: Any, what: str, lo: float = 0, hi: float = 10 ** 9, integer: bool = False):
    try:
        n = int(v) if integer else float(v)
    except (TypeError, ValueError):
        raise WorkflowError(f'{what} must be a number')
    if not lo <= n <= hi:
        raise WorkflowError(f'{what} must be between {lo:g} and {hi:g}')
    return n


def _retry(spec: Any, where: str) -> Dict[str, Any]:
    spec = spec or {}
    if isinstance(spec, int):
        spec = {'max_attempts': spec}
    if not isinstance(spec, dict):
        raise WorkflowError(f'{where}: retry is an object (max_attempts, backoff_seconds, ...)')
    return {
        'max_attempts': _num(spec.get('max_attempts', 1), f'{where}: retry.max_attempts', 1, 20, True),
        'backoff_seconds': _num(spec.get('backoff_seconds', 1), f'{where}: retry.backoff_seconds', 0, 3600),
        'backoff_factor': _num(spec.get('backoff_factor', 2), f'{where}: retry.backoff_factor', 1, 10),
        'max_backoff_seconds': _num(spec.get('max_backoff_seconds', 300), f'{where}: retry.max_backoff_seconds',
                                    0, 86400),
        'on_timeout': bool(spec.get('on_timeout', True)),
    }


def _call(step: Dict[str, Any], where: str, out: Dict[str, Any]) -> None:
    """The fields of a tool / composite / ask call (a step or a foreach body)."""
    kind = out['kind']
    if kind in ('tool', 'composite'):
        tool = step.get('tool') or step.get('composite')
        if not isinstance(tool, str) or not tool.strip():
            raise WorkflowError(f'{where}: a {kind} step names its "tool"')
        out['tool'] = tool.strip()
        params = step.get('params', step.get('arguments', {})) or {}
        if not isinstance(params, dict):
            raise WorkflowError(f'{where}: params is an object of argument -> value or "$..." mapping')
        out['params'] = params
        if step.get('idempotency_param'):
            out['idempotency_param'] = str(step['idempotency_param'])
    else:  # ask
        q = step.get('question')
        if not isinstance(q, str) or not q.strip():
            raise WorkflowError(f'{where}: an ask step has a "question"')
        out['question'] = q
        if step.get('model'):
            out['model'] = str(step['model'])
    out['retry'] = _retry(step.get('retry'), where)
    if step.get('timeout_seconds') is not None:
        out['timeout_seconds'] = _num(step['timeout_seconds'], f'{where}: timeout_seconds', 0.01, 86400)
    if 'idempotent' in step:
        out['idempotent'] = bool(step['idempotent'])


def _step(raw: Any, i: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowError(f'step {i + 1} is not an object')
    sid = raw.get('id')
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise WorkflowError(f'step {i + 1}: id must match {ID_RE.pattern}')
    where = f'step {sid}'
    kind = raw.get('kind') or ('tool' if raw.get('tool') else None)
    if kind not in STEP_KINDS:
        raise WorkflowError(f'{where}: kind must be one of {", ".join(STEP_KINDS)}')
    deps = raw.get('depends_on') or []
    if isinstance(deps, str):
        deps = [deps]
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise WorkflowError(f'{where}: depends_on is a list of step ids')
    out: Dict[str, Any] = {'id': sid, 'kind': kind, 'depends_on': list(dict.fromkeys(deps))}
    if raw.get('title'):
        out['title'] = str(raw['title'])[:200]
    join = raw.get('join', 'all_success')
    if join not in JOINS:
        raise WorkflowError(f'{where}: join must be one of {", ".join(JOINS)}')
    out['join'] = join
    on_error = raw.get('on_error', 'fail')
    if on_error not in ON_ERROR:
        raise WorkflowError(f'{where}: on_error must be fail or continue')
    out['on_error'] = on_error
    if raw.get('when') is not None:
        try:
            expr.check_condition(raw['when'])
        except ValueError as e:
            raise WorkflowError(f'{where}: when: {e}')
        out['when'] = raw['when']

    if kind in INNER_KINDS:
        _call(raw, where, out)
    elif kind == 'condition':
        cond = raw.get('if', raw.get('condition'))
        if cond is None:
            raise WorkflowError(f'{where}: a condition step has "if"')
        try:
            expr.check_condition(cond)
        except ValueError as e:
            raise WorkflowError(f'{where}: if: {e}')
        out['if'] = cond
        for key in ('then', 'else'):
            v = raw.get(key) or []
            if isinstance(v, str):
                v = [v]
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                raise WorkflowError(f'{where}: {key} is a list of step ids')
            out[key] = v
    elif kind == 'foreach':
        items = raw.get('items')
        if items is None:
            raise WorkflowError(f'{where}: a foreach step has "items" (a list or a "$..." reference)')
        out['items'] = items
        body = raw.get('do') or raw.get('step')
        if not isinstance(body, dict):
            raise WorkflowError(f'{where}: a foreach step has "do": the tool, composite or ask call per item')
        bkind = body.get('kind') or ('tool' if body.get('tool') else None)
        if bkind not in INNER_KINDS:
            raise WorkflowError(f'{where}: do.kind must be one of {", ".join(INNER_KINDS)}')
        inner: Dict[str, Any] = {'kind': bkind, 'on_error': body.get('on_error', 'fail')}
        if inner['on_error'] not in ON_ERROR:
            raise WorkflowError(f'{where}: do.on_error must be fail or continue')
        _call(body, f'{where}.do', inner)
        out['do'] = inner
        if raw.get('max_items') is not None:
            out['max_items'] = _num(raw['max_items'], f'{where}: max_items', 1, 100000, True)
        out['parallel'] = _num(raw.get('parallel', 1), f'{where}: parallel', 1, 32, True)
        on_overflow = raw.get('on_overflow', 'truncate')
        if on_overflow not in ('truncate', 'fail'):
            raise WorkflowError(f'{where}: on_overflow must be truncate or fail')
        out['on_overflow'] = on_overflow
    elif kind == 'wait':
        if raw.get('seconds') is None and raw.get('until') is None:
            raise WorkflowError(f'{where}: a wait step has "seconds" (or "until", an epoch or ISO time)')
        if raw.get('seconds') is not None:
            out['seconds'] = raw['seconds'] if expr.is_ref(raw['seconds']) else \
                _num(raw['seconds'], f'{where}: seconds', 0, 86400 * 30)
        if raw.get('until') is not None:
            out['until'] = raw['until']
    elif kind == 'approval':
        out['reason'] = str(raw.get('reason') or f'Workflow step {sid} needs approval')[:500]
        if raw.get('ttl_seconds') is not None:
            out['ttl_seconds'] = _num(raw['ttl_seconds'], f'{where}: ttl_seconds', 60, 86400 * 30, True)
    return out


def _trigger(raw: Any, i: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise WorkflowError(f'trigger {i + 1} is not an object')
    ttype = raw.get('type')
    if ttype not in TRIGGER_TYPES:
        raise WorkflowError(f'trigger {i + 1}: type must be one of {", ".join(TRIGGER_TYPES)}')
    tid = raw.get('id') or f'{ttype}{i + 1}'
    if not ID_RE.match(str(tid)):
        raise WorkflowError(f'trigger {i + 1}: id must match {ID_RE.pattern}')
    where = f'trigger {tid}'
    out: Dict[str, Any] = {'id': str(tid), 'type': ttype, 'enabled': bool(raw.get('enabled', True))}
    if raw.get('input') is not None:
        if not isinstance(raw['input'], dict):
            raise WorkflowError(f'{where}: input is an object')
        out['input'] = raw['input']
    if ttype == 'cron':
        from sajha.workflows.cron import CronError, CronSchedule
        try:
            CronSchedule(raw.get('cron', ''), raw.get('timezone'))
        except CronError as e:
            raise WorkflowError(f'{where}: {e}')
        out['cron'] = str(raw['cron']).strip()
        out['timezone'] = raw.get('timezone') or 'UTC'
    elif ttype == 'webhook':
        secret = raw.get('secret')
        secret_ref = raw.get('secret_ref')
        if secret_ref and not str(secret_ref).startswith('env:'):
            raise WorkflowError(f'{where}: secret_ref is env:NAME')
        if secret is not None and secret != MASK and (not isinstance(secret, str) or len(secret) < 16):
            raise WorkflowError(f'{where}: secret must be at least 16 characters')
        if secret:
            out['secret'] = secret
        if secret_ref:
            out['secret_ref'] = str(secret_ref)
        out['tolerance_seconds'] = _num(raw.get('tolerance_seconds', 300), f'{where}: tolerance_seconds',
                                        10, 3600, True)
    elif ttype == 'file':
        out['prefix'] = str(raw.get('prefix') or '')
        if '..' in out['prefix'].replace('\\', '/').split('/') or out['prefix'].startswith(('/', '\\')) \
                or ':' in out['prefix']:
            raise WorkflowError(f'{where}: prefix is relative to the storage backend (no "..", no absolute path)')
        out['pattern'] = str(raw.get('pattern') or '*')
        out['interval_seconds'] = _num(raw.get('interval_seconds', 30), f'{where}: interval_seconds', 1, 86400)
        out['fire_existing'] = bool(raw.get('fire_existing', False))
    elif ttype == 'event':
        kinds = raw.get('kinds') or ['tools']
        if isinstance(kinds, str):
            kinds = [kinds]
        bad = [k for k in kinds if k not in EVENT_KINDS]
        if bad:
            raise WorkflowError(f'{where}: kinds must be among {", ".join(EVENT_KINDS)}')
        out['kinds'] = list(kinds)
        if raw.get('uri'):
            out['uri'] = str(raw['uri'])
        out['debounce_seconds'] = _num(raw.get('debounce_seconds', 5), f'{where}: debounce_seconds', 0, 3600)
    return out


def _closure(start: List[str], children: Dict[str, List[str]]) -> set:
    seen, stack = set(), list(start)
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen.add(s)
        stack.extend(children.get(s, []))
    return seen


def normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a definition and return it with defaults and implicit dependencies filled in."""
    if not isinstance(raw, dict):
        raise WorkflowError('a definition is an object')
    raw = copy.deepcopy(raw)
    name = raw.get('name')
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise WorkflowError(f'name must match {NAME_RE.pattern}')
    if name in RESERVED_NAMES:
        raise WorkflowError(f'{name} is reserved (it is part of the /api/workflows routes)')
    steps_raw = raw.get('steps')
    if not isinstance(steps_raw, list) or not steps_raw:
        raise WorkflowError('a workflow has at least one step')
    if len(steps_raw) > 200:
        raise WorkflowError('a workflow has at most 200 steps')
    steps = [_step(s, i) for i, s in enumerate(steps_raw)]
    ids = [s['id'] for s in steps]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise WorkflowError(f'step ids must be unique: {", ".join(sorted(dup))}')
    by_id = {s['id']: s for s in steps}

    # implicit dependencies: $steps references and condition branches
    for s in steps:
        reads = set()
        for key in ('params', 'question', 'items', 'when', 'seconds', 'until', 'if'):
            if key in s:
                reads |= expr.refs_in(s[key])
        if 'do' in s:
            reads |= expr.refs_in(s['do'].get('params', {})) | expr.refs_in(s['do'].get('question', ''))
        for r in sorted(reads):
            if r not in by_id:
                raise WorkflowError(f'step {s["id"]} reads $steps.{r}, which is not a step')
            if r != s['id'] and r not in s['depends_on']:
                s['depends_on'].append(r)
    for s in steps:
        if s['kind'] == 'condition':
            for b in s['then'] + s['else']:
                if b not in by_id:
                    raise WorkflowError(f'step {s["id"]}: branch {b} is not a step')
                if s['id'] not in by_id[b]['depends_on']:
                    by_id[b]['depends_on'].append(s['id'])
    for s in steps:
        for d in s['depends_on']:
            if d not in by_id:
                raise WorkflowError(f'step {s["id"]} depends on {d}, which is not a step')
            if d == s['id']:
                raise WorkflowError(f'step {s["id"]} depends on itself')
    topo_order(steps)   # raises on a cycle

    triggers = [_trigger(t, i) for i, t in enumerate(raw.get('triggers') or [])]
    tids = [t['id'] for t in triggers]
    if len(set(tids)) != len(tids):
        raise WorkflowError('trigger ids must be unique')

    out: Dict[str, Any] = {'name': name, 'description': str(raw.get('description') or '')[:2000]}
    if raw.get('input_schema') is not None:
        if not isinstance(raw['input_schema'], dict):
            raise WorkflowError('input_schema is a JSON Schema object')
        out['input_schema'] = raw['input_schema']
    out['steps'] = steps
    if raw.get('output') is not None:
        out['output'] = raw['output']
    out['triggers'] = triggers
    if raw.get('concurrency') is not None:
        out['concurrency'] = _num(raw['concurrency'], 'concurrency', 1, 1000, True)
    if raw.get('max_parallel') is not None:
        out['max_parallel'] = _num(raw['max_parallel'], 'max_parallel', 1, 64, True)
    if raw.get('timeout_seconds') is not None:
        out['timeout_seconds'] = _num(raw['timeout_seconds'], 'timeout_seconds', 1, 86400 * 30)
    delivery = raw.get('delivery')
    if delivery:
        if not isinstance(delivery, dict) or delivery.get('type') not in DELIVERY_TYPES:
            raise WorkflowError(f'delivery.type must be one of {", ".join(DELIVERY_TYPES)}')
        if not delivery.get('destination'):
            raise WorkflowError('delivery.destination is required (URL, file name or topic)')
        on = delivery.get('on') or ['succeeded', 'failed']
        if isinstance(on, str):
            on = [on]
        out['delivery'] = {'type': delivery['type'], 'destination': str(delivery['destination']),
                           'on': [x for x in on if x in ('succeeded', 'failed', 'cancelled')]}
    publish = raw.get('publish')
    if publish:
        if publish is True:
            publish = {'enabled': True}
        if not isinstance(publish, dict):
            raise WorkflowError('publish is an object (enabled, tool_name, timeout_seconds)')
        p = {'enabled': bool(publish.get('enabled', True))}
        tool_name = publish.get('tool_name') or name
        if not NAME_RE.match(tool_name):
            raise WorkflowError(f'publish.tool_name must match {NAME_RE.pattern}')
        p['tool_name'] = tool_name
        p['timeout_seconds'] = _num(publish.get('timeout_seconds', 300), 'publish.timeout_seconds', 1, 3600)
        if publish.get('description'):
            p['description'] = str(publish['description'])[:2000]
        out['publish'] = p
    return out


def topo_order(steps: List[Dict[str, Any]]) -> List[str]:
    """Step ids in a dependency order (Kahn); raises WorkflowError on a cycle."""
    deps = {s['id']: set(s['depends_on']) for s in steps}
    order, ready = [], [s['id'] for s in steps if not deps[s['id']]]
    remaining = dict(deps)
    while ready:
        sid = ready.pop(0)
        order.append(sid)
        remaining.pop(sid, None)
        for other, ds in remaining.items():
            if sid in ds:
                ds.discard(sid)
                if not ds and other not in order and other not in ready:
                    ready.append(other)
    if len(order) != len(steps):
        cyc = sorted(set(deps) - set(order))
        raise WorkflowError(f'the steps form a cycle: {", ".join(cyc)}')
    return order


def descendants(steps: List[Dict[str, Any]], start: str) -> set:
    """``start`` and every step that (transitively) depends on it."""
    children: Dict[str, List[str]] = {}
    for s in steps:
        for d in s['depends_on']:
            children.setdefault(d, []).append(s['id'])
    return _closure([start], children)


def public(defn: Dict[str, Any], reveal_secrets: bool = False) -> Dict[str, Any]:
    """A definition fit to show: webhook secrets masked unless ``reveal_secrets``."""
    d = copy.deepcopy(defn)
    if not reveal_secrets:
        for t in d.get('triggers', []):
            if t.get('secret'):
                t['secret'] = MASK
    return d
