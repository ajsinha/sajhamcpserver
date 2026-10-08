"""
SAJHA Net residency inside SAJHA (design §12 and §13; protocol §15.4 step 12, §17 ``-32012``).

* **Data classes** of a tool come from three places, merged: ``x-sajha-data-class`` marks on its
  ``inputSchema`` and ``outputSchema`` properties (the authoritative marks, protocol §10.2), the tool's
  own ``data_classes: {arguments: [...], results: [...]}`` (whole-tool classes), and the operator's
  ``sajhanet.data_classes.tools`` (``{<tool name or glob>: {arguments: {<path>: <class>}, results:
  {<path>: <class>}}}``, ``*`` for the whole value), so a tool can be classified without editing it.
* **Decisions** are policy-engine residency rules (``sajha/policy/engine.py::PolicyEngine.residency``):
  the rule evaluator ``policy_engine`` (``authz.NetRules``) asks :func:`decide` for ``residency_offer``
  (may a remote tool be offered at all: the classes every call of it sends), ``residency_arguments``
  (home, before the call leaves) and ``residency_result`` (host, before the answer leaves). A deny is the
  protocol's ``-32012`` refusal; ``redact: {data_classes: [...]}`` replaces those fields instead. The home
  checks a result again as it arrives (:func:`on_arrival`; destination ``here``).
* **Audit:** every decision on classified data (allow, redact or refuse) is one ``net.residency`` record
  with the net, the other instance, the tool, the flow, the classes, the rule and the fields redacted
  (never the values). Offer decisions show in the resolution order (``residency rule``) instead.
* **Memory:** :func:`memory_mode` maps the classes of the remote results an answer used to
  ``store``, ``summary`` (figures removed, :func:`without_figures`) or ``none``
  (``sajhanet.memory.remote_results`` and ``sajhanet.memory.by_class``); the strictest wins.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sajha.net import EXTENSION_ID, plugins
from sajha.net import residency as R

logger = logging.getLogger(__name__)

MEMORY_MODES = ('store', 'summary', 'none')
_RANK = {'store': 0, 'summary': 1, 'none': 2}


# ── settings ────────────────────────────────────────────────────────

@dataclass
class ResidencySettings:
    enabled: bool = True
    tools: Dict[str, Dict[str, R.Marks]] = field(default_factory=dict)   # pattern -> {arguments|results: marks}
    memory_default: str = 'store'
    memory_by_class: Dict[str, str] = field(default_factory=dict)


_override: Optional[ResidencySettings] = None
_cache: Optional[Tuple[float, Any, ResidencySettings]] = None      # (checked at, config stamp, settings)
CACHE_SECONDS = 5.0


def set_settings(s: Optional[ResidencySettings]) -> None:
    """Replace the settings (tests); None reads the configuration again."""
    global _override, _cache
    _override = s
    _cache = None


def _stamp() -> Any:
    """What the settings depend on: the configuration file's modification time and the env overrides."""
    import os
    from pathlib import Path
    path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    return (str(path), mtime, tuple(sorted((k, v) for k, v in os.environ.items()
                                           if k.startswith(('SAJHA_SAJHANET_RESIDENCY', 'SAJHA_SAJHANET_MEMORY')))))


def _marks_of(v: Any) -> R.Marks:
    if isinstance(v, dict):
        return {str(k): R.as_classes(x) for k, x in v.items() if R.as_classes(x)}
    if isinstance(v, (list, str)):
        return {R.WHOLE: R.as_classes(v)} if R.as_classes(v) else {}
    return {}


def load_settings() -> ResidencySettings:
    """The settings, read once and again when the configuration file or its env overrides change
    (checked at most every ``CACHE_SECONDS``)."""
    global _cache
    if _override is not None:
        return _override
    import time
    now = time.monotonic()
    cur = _cache
    if cur is not None and now - cur[0] < CACHE_SECONDS:
        return cur[2]
    stamp = _stamp()
    if cur is not None and cur[1] == stamp:
        _cache = (now, stamp, cur[2])
        return cur[2]
    s = _read_settings()
    _cache = (now, stamp, s)
    return s


def _read_settings() -> ResidencySettings:
    from sajha.core.config import parse_bool
    from sajha.net.integration.config import _g, _raw
    raw = _raw()
    s = ResidencySettings(enabled=parse_bool(_g('residency.enabled', 'true'), True))
    tools = ((raw.get('data_classes') or {}).get('tools') or {}) if isinstance(raw.get('data_classes'), dict) else {}
    if isinstance(tools, dict):
        for pat, spec in tools.items():
            if isinstance(spec, dict):
                s.tools[str(pat)] = {'arguments': _marks_of(spec.get('arguments')),
                                     'results': _marks_of(spec.get('results'))}
    mode = str(_g('memory.remote_results', 'store')).strip().lower()
    s.memory_default = mode if mode in MEMORY_MODES else 'store'
    mem = raw.get('memory') if isinstance(raw.get('memory'), dict) else {}
    by = mem.get('by_class') if isinstance(mem.get('by_class'), dict) else {}
    s.memory_by_class = {str(k): str(v).lower() for k, v in by.items() if str(v).lower() in MEMORY_MODES}
    return s


# ── classification ──────────────────────────────────────────────────

@dataclass
class Classes:
    arguments: R.Marks = field(default_factory=dict)
    results: R.Marks = field(default_factory=dict)

    def summary(self) -> Dict[str, List[str]]:
        out = {}
        for k in ('arguments', 'results'):
            cs: List[str] = []
            for v in getattr(self, k).values():
                cs += [c for c in v if c not in cs]
            if cs:
                out[k] = sorted(cs)
        return out


def classify(names: Iterable[str], input_schema: Any = None, output_schema: Any = None,
             declared: Any = None, settings: Optional[ResidencySettings] = None) -> Classes:
    """The marks of a tool known by ``names`` (its own name; a proxy also by its host's name)."""
    s = settings or load_settings()
    d = declared if isinstance(declared, dict) else {}
    args = R.merge_marks(R.schema_marks(input_schema), _marks_of(d.get('arguments')))
    res = R.merge_marks(R.schema_marks(output_schema), _marks_of(d.get('results')))
    names = [n for n in names if n]
    for pat, spec in s.tools.items():
        if any(fnmatch.fnmatchcase(n, pat) for n in names):
            args = R.merge_marks(args, spec.get('arguments'))
            res = R.merge_marks(res, spec.get('results'))
    return Classes(args, res)


def _tool_declared(tool) -> Any:
    cfg = getattr(tool, 'config', None) or {}
    return cfg.get('data_classes') if isinstance(cfg, dict) else None


def classes_of_tool(tool) -> Classes:
    """A registry tool's classes (a SAJHA Net proxy: the host's marks plus this server's overlay)."""
    names = [getattr(tool, 'name', '')]
    declared = _tool_declared(tool)
    meta = getattr(tool, 'meta', None)
    if isinstance(meta, dict) and meta.get('host_tool'):
        names.append(str(meta['host_tool']))
        dc = meta.get('data_classes') if isinstance(meta.get('data_classes'), dict) else {}
        declared = {'arguments': dc.get('arguments') or [], 'results': dc.get('results') or []} if dc else declared
    try:
        ins, outs = tool.input_schema, tool.output_schema
    except Exception:
        ins, outs = None, None
    if isinstance(meta, dict) and meta.get('host_tool'):
        # a proxy's whole-tool classes from the net metadata summarise its fields too; keep only fields
        c = classify(names, ins, outs, None)
        summ = c.summary()
        for k in ('arguments', 'results'):
            extra = [x for x in (declared or {}).get(k) or [] if x not in (summ.get(k) or [])]
            if extra:
                getattr(c, k)[R.WHOLE] = list(dict.fromkeys((getattr(c, k).get(R.WHOLE) or []) + extra))
        return c
    return classify(names, ins, outs, declared)


def tool_classes(tool, arguments: Dict[str, Any]) -> Tuple[List[str], R.Marks]:
    """(classes present in ``arguments``, result marks) for the policy engine's ordinary calls."""
    c = classes_of_tool(tool)
    return R.classes_present(arguments, c.arguments), c.results


def catalog_summary(tool) -> Dict[str, List[str]]:
    """``data_classes`` for a tool's net metadata (protocol §10.2: a summary of the marks)."""
    try:
        return classes_of_tool(tool).summary()
    except Exception:
        return {}


# ── facts and decisions ─────────────────────────────────────────────

def facts(node, instance: Optional[str] = None) -> Dict[str, Any]:
    """{net, instance, region, labels, here} of ``instance`` (None: this instance) as known in its net."""
    if instance is None or instance == node.name:
        return {'net': node.net, 'instance': node.name, 'region': node.cfg.region or '',
                'labels': dict(node.cfg.labels or {}), 'here': True}
    m = node.member(instance)
    rec = (m or {}).get('record') or {}
    return {'net': node.net, 'instance': instance, 'region': str(rec.get('region') or ''),
            'labels': dict(rec.get('labels') or {}), 'here': False}


def _caller(user: Any):
    """What a rule's ``callers`` match on: the home's caller, or the host's mapped net user."""
    if not isinstance(user, dict):
        from sajha.observability.caller import current
        return current()
    return SimpleNamespace(user_id=str(user.get('user_id') or user.get('name') or 'anonymous'),
                           roles=tuple(user.get('roles') or ()), api_key='',
                           auth_type=str(user.get('auth_type') or 'sajhanet'))


def _engine():
    from sajha.policy import engine as E
    if not E.enabled():
        return None
    return E.get_engine()


def _evaluate(tool: str, args: Dict[str, Any], user, classes: List[str], flow: str, dest: Dict[str, Any],
              here: Dict[str, Any]):
    from sajha.policy.engine import Call
    eng = _engine()
    if eng is None:
        return None
    call = Call(tool, args if isinstance(args, dict) else {}, _caller(user), 'sajhanet', data_classes=list(classes),
                flow=flow, destination=dest, here=here)
    return eng.residency(call)


def _audit(net: str, other: str, tool: str, flow: str, classes: List[str], outcome: str, rule: str = '',
           fields: Optional[List[str]] = None, trace_id: str = '', user: Any = None, side: str = 'home') -> None:
    try:
        from sajha.net.integration.authz import linked_audit
        d = {'net': net, 'instance': other, 'tool': tool, 'flow': flow, 'data_classes': sorted(classes),
             'outcome': outcome, 'rule': rule, 'side': side}
        if fields:
            d['fields'] = fields
        if trace_id:
            d['trace_id'] = trace_id
        name = (user or {}).get('name') or (user or {}).get('user_id') if isinstance(user, dict) else None
        linked_audit('net.residency', d, actor=str(name) if name else None)
    except Exception as e:
        logger.debug(f'SAJHA Net residency audit: {e}')
    try:
        _DECISIONS().inc((flow, outcome))
    except Exception:
        pass


_counter = None


def _DECISIONS():
    global _counter
    if _counter is None:
        from sajha.observability import metrics as _m
        _counter = _m.Counter(_m.REGISTRY, 'sajha_net_residency_decisions_total',
                              'SAJHA Net residency decisions on classified data by flow and outcome.',
                              ('flow', 'outcome'))
    return _counter


def _entry_classes(entry: Any, host_tool: str, qualified: str) -> Classes:
    """A host and tool table entry's classes: the schema marks, the net metadata's ``data_classes`` (a class
    with no field mark in the schema counts for the whole value) and this server's overlay."""
    e = entry if isinstance(entry, dict) else {}
    d = e.get('definition') if isinstance(e.get('definition'), dict) else {}
    meta = e.get('meta') if isinstance(e.get('meta'), dict) else {}
    c = classify([host_tool, qualified], d.get('inputSchema'), d.get('outputSchema'), None)
    summ = c.summary()
    dc = meta.get('data_classes') if isinstance(meta.get('data_classes'), dict) else {}
    for k in ('arguments', 'results'):
        extra = [x for x in R.as_classes(dc.get(k)) if x not in (summ.get(k) or [])]
        if extra:
            getattr(c, k)[R.WHOLE] = list(dict.fromkeys((getattr(c, k).get(R.WHOLE) or []) + extra))
    return c


def _structured(result: Dict[str, Any]) -> Any:
    if isinstance(result.get('structuredContent'), (dict, list)):
        return result['structuredContent']
    for b in result.get('content') or []:
        if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str):
            try:
                v = json.loads(b['text'])
            except ValueError:
                continue
            if isinstance(v, (dict, list)):
                return v
    return None


def decide(node, rule: str, s: Dict[str, Any], registry=None) -> plugins.Decision:
    """``residency_offer``, ``residency_arguments`` (home) and ``residency_result`` (host) for one net."""
    st = load_settings()
    if not st.enabled:
        return plugins.Decision(True, rule)
    here = facts(node)
    user = s.get('user')
    if rule in ('residency_offer', 'residency_arguments'):
        host = str(s.get('host') or '')
        c = _entry_classes(s.get('entry'), str(s.get('tool') or ''), str(s.get('qualified_name') or ''))
        if rule == 'residency_offer':
            ins = ((s.get('entry') or {}).get('definition') or {}).get('inputSchema') \
                if isinstance(s.get('entry'), dict) else None
            classes = R.necessary_classes(ins, c.arguments.get(R.WHOLE) or [],
                                          {k: v for k, v in c.arguments.items() if k != R.WHOLE})
        else:
            classes = R.classes_present(s.get('arguments') or {}, c.arguments)
        if not classes:
            return plugins.Decision(True, rule)
        d = _evaluate(str(s.get('tool') or ''), s.get('arguments') or {}, user, classes, 'arguments',
                      facts(node, host), here)
        if d is None:
            return plugins.Decision(True, rule)
        if rule == 'residency_offer':
            return plugins.Decision(d.effect == 'allow', 'residency_arguments' if d.effect != 'allow' else rule)
        tool = str(s.get('qualified_name') or s.get('tool') or '')
        if d.effect != 'allow':
            _audit(node.net, host, tool, 'arguments', classes, 'refused', d.rule, trace_id=str(s.get('trace_id') or ''),
                   user=user)
            return plugins.Decision(False, 'residency_arguments')
        if d.redact and d.redact.data_classes:
            red, touched, _ = R.redact_fields(s.get('arguments') or {}, c.arguments, d.redact.data_classes)
            if R.WHOLE in touched:
                _audit(node.net, host, tool, 'arguments', classes, 'refused', d.rule, ['*'],
                       str(s.get('trace_id') or ''), user)
                return plugins.Decision(False, 'residency_arguments')
            if touched:
                _audit(node.net, host, tool, 'arguments', classes, 'redacted', d.rule, touched,
                       str(s.get('trace_id') or ''), user)
                return plugins.Decision(True, rule, value=red)
        _audit(node.net, host, tool, 'arguments', classes, 'allowed', d.rule, trace_id=str(s.get('trace_id') or ''),
               user=user)
        return plugins.Decision(True, rule)
    if rule == 'residency_result':
        return _result_at_host(node, s, here, user, registry)
    return plugins.Decision(True, rule)


def _local_tool(name: str, registry=None):
    if registry is not None:
        return registry.get_tool(name)
    try:
        from sajha.net.integration import get_service
        svc = get_service()
        reg = getattr(svc, 'tools_registry', None) if svc is not None else None
        if reg is None:
            from sajha.tools.tools_registry import get_tools_registry
            reg = get_tools_registry()
        return reg.get_tool(name) if reg is not None else None
    except Exception:
        return None


def _with_classes(result: Dict[str, Any], classes: List[str], redacted: Optional[List[str]] = None) -> Dict[str, Any]:
    out = dict(result)
    rm = dict((out.get('_meta') or {}).get(EXTENSION_ID) or {})
    if classes:
        rm['data_classes'] = {'results': sorted(classes)}
    if redacted:
        rm['redacted'] = redacted
    if rm:
        out['_meta'] = dict(out.get('_meta') or {}, **{EXTENSION_ID: rm})
    return out


def _result_at_host(node, s: Dict[str, Any], here: Dict[str, Any], user, registry=None) -> plugins.Decision:
    tool_name = str(s.get('tool') or '')
    result = s.get('result') if isinstance(s.get('result'), dict) else {}
    tool = _local_tool(tool_name, registry)
    c = classes_of_tool(tool) if tool is not None else classify([tool_name])
    value = _structured(result)
    classes = R.classes_present(value, c.results) if value is not None else list(c.results.get(R.WHOLE) or [])
    if R.WHOLE in c.results and value is None and result.get('content'):
        classes = list(dict.fromkeys(classes + c.results[R.WHOLE]))
    if not classes or result.get('isError'):
        return plugins.Decision(True, 'residency_result')
    peer = str(s.get('peer') or '')
    d = _evaluate(tool_name, {}, user, classes, 'results', facts(node, peer), here)
    trace = str(s.get('trace_id') or '')
    if d is None:
        return plugins.Decision(True, 'residency_result', value=_with_classes(result, classes))
    if d.effect != 'allow':
        _audit(node.net, peer, tool_name, 'results', classes, 'refused', d.rule, trace_id=trace, user=user, side='host')
        return plugins.Decision(False, 'residency_result')
    if d.redact and d.redact.data_classes:
        red, touched = R.redact_result(result, c.results, d.redact.data_classes)
        if R.WHOLE in touched:
            _audit(node.net, peer, tool_name, 'results', classes, 'refused', d.rule, ['*'], trace, user, 'host')
            return plugins.Decision(False, 'residency_result')
        if touched:
            left = R.classes_present(_structured(red), {k: v for k, v in c.results.items() if k not in touched})
            _audit(node.net, peer, tool_name, 'results', classes, 'redacted', d.rule, touched, trace, user, 'host')
            return plugins.Decision(True, 'residency_result', value=_with_classes(red, left, touched))
    _audit(node.net, peer, tool_name, 'results', classes, 'allowed', d.rule, trace_id=trace, user=user, side='host')
    return plugins.Decision(True, 'residency_result', value=_with_classes(result, classes))


def on_arrival(node, proxy, result: Dict[str, Any], user=None) -> Dict[str, Any]:
    """The home's own residency rules on a result as it arrives (flow ``results``, destination here):
    redact fields, or refuse with ``residency_result`` (side home, executed). The result's
    ``_meta["io.sajha/net"].data_classes.results`` is completed from this server's knowledge of the tool."""
    if not isinstance(result, dict) or result.get('isError') or not load_settings().enabled:
        return result
    meta = (result.get('_meta') or {}).get(EXTENSION_ID) or {}
    c = classes_of_tool(proxy)
    value = _structured(result)
    classes = R.classes_present(value, c.results) if value is not None else list(c.results.get(R.WHOLE) or [])
    told = R.as_classes(((meta.get('data_classes') or {}).get('results')) if isinstance(meta.get('data_classes'),
                                                                                       dict) else None)
    classes = list(dict.fromkeys(told + classes))
    if not classes:
        return result
    here = facts(node)
    host = str(meta.get('instance') or '')
    tool = str(getattr(proxy, 'name', '') or '')
    d = _evaluate(tool, {}, user, classes, 'results', here, here)
    out = _with_classes(result, classes)
    if d is None or (d.effect == 'allow' and not (d.redact and d.redact.data_classes)):
        return out
    trace = str(meta.get('trace_id') or '')
    if d.effect == 'allow':
        red, touched = R.redact_result(out, c.results, d.redact.data_classes)
        if touched and R.WHOLE not in touched:
            _audit(node.net, host, tool, 'results', classes, 'redacted', d.rule, touched, trace, user)
            m = dict((red.get('_meta') or {}).get(EXTENSION_ID) or {})
            m['redacted'] = sorted(set((m.get('redacted') or []) + touched))
            return dict(red, _meta=dict(red.get('_meta') or {}, **{EXTENSION_ID: m}))
        if not touched:
            return out
    _audit(node.net, host, tool, 'results', classes, 'refused', d.rule, trace_id=trace, user=user)
    from sajha.net.routing import refusal, RPC_RESIDENCY, SAFE_WORDS
    data = refusal(RPC_RESIDENCY, 'residency_result', 'home', node.net, node.name, tool, trace,
                   executed=True)['data'][EXTENSION_ID]
    return {'content': [{'type': 'text', 'text': f'This server refused the result of {tool}: '
                                                 f'{SAFE_WORDS["residency_result"]}.'}],
            'isError': True, '_meta': {EXTENSION_ID: dict(meta, refusal=data)}}


# ── shortlists ──────────────────────────────────────────────────────

def offered(name: str) -> bool:
    """False for a remote tool that residency rules would refuse for the current caller wherever it is
    hosted (design §13: never offered to the caller or a planner)."""
    try:
        from sajha.net.integration.catalogs import get_catalogs
        cats = get_catalogs()
        if cats is None or cats.router is None or name not in cats._proxies:
            return True
        if not _has_residency_rules():
            return True
        from sajha.net.integration.catalogs import _caller_user
        res = cats.router.resolve(name, _caller_user())
        return bool(res.candidates) or not any(c.why_not == 'residency rule' for c in res.skipped)
    except Exception as e:
        logger.debug(f'SAJHA Net residency shortlist {name}: {e}')
        return True


def _has_residency_rules() -> bool:
    eng = _engine()
    return eng is not None and any(r.match.residency for r in eng.rules())


# ── memory (design §12: what the home instance keeps) ───────────────

def memory_mode(classes: Iterable[str], settings: Optional[ResidencySettings] = None) -> str:
    """``store``, ``summary`` or ``none`` for an answer that used remote results of ``classes``: the
    strictest of each class's mode (``sajhanet.memory.by_class``, globs allowed), else the default
    (``sajhanet.memory.remote_results``)."""
    s = settings or load_settings()
    modes = []
    for c in classes:
        m = s.memory_by_class.get(c) or next((v for k, v in s.memory_by_class.items() if fnmatch.fnmatchcase(c, k)),
                                             None)
        modes.append(m or s.memory_default)
    if not modes:
        modes.append(s.memory_default)
    return max(modes, key=lambda m: _RANK.get(m, 0))


_FIGURE = re.compile(r'(?<![\w.])[-+]?\d[\d,_]*(?:\.\d+)?%?(?![\w])')


def without_figures(text: str) -> str:
    """``summary``: the answer with every figure replaced by ``[remote figure]``."""
    return _FIGURE.sub('[remote figure]', text or '')


def remote_classes(steps: Iterable[Any]) -> Tuple[bool, List[str]]:
    """(any remote result used, the classes of those results) from an answer's steps (``AskStep.net``)."""
    remote, out = False, []
    for st in steps or []:
        net = getattr(st, 'net', None)
        if not isinstance(net, dict) or not net.get('instance') or not getattr(st, 'ok', True):
            continue
        remote = True
        for c in R.as_classes(net.get('data_classes')):
            if c not in out:
                out.append(c)
    return remote, out


def memory_answer(answer: str, steps: Iterable[Any]) -> Tuple[str, str]:
    """(the answer to store, the mode applied) for an answer that may rest on remote results."""
    remote, classes = remote_classes(steps)
    if not remote:
        return answer, 'store'
    mode = memory_mode(classes)
    if mode == 'summary':
        return without_figures(answer), mode
    if mode == 'none':
        what = ', '.join(classes) if classes else 'remote'
        return f'[not stored: this answer used {what} data from another instance]', mode
    return answer, mode
