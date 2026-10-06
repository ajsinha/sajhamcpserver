"""
SAJHA MCP Server — the policy engine.

:meth:`PolicyEngine.evaluate` is pure: given a call (tool, arguments, caller, source,
time) it returns a :class:`Decision` naming the matching rules, the combined effect
(deny-overrides) and the obligations, without touching a counter. The test bench uses it
as is. :meth:`PolicyEngine.enforce` is what ``BaseMCPTool.execute_with_tracking`` calls
before every tool call: it acts on the decision (denies, asks for approval, consumes a
grant, counts rate limits and quotas, audits and counts the outcome) and returns an
:class:`Enforcement` whose :meth:`~Enforcement.apply_output` redacts and screens the result.

With no enforced rule and ``policy.default_effect: allow`` (the shipped state),
``enforce`` returns None after one list check: no overhead, no behaviour change.
Design: docs/architecture/Policy and Audit.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sajha.observability import metrics as _m
from sajha.policy import approvals
from sajha.policy.errors import ApprovalRequired, PolicyDenied, PolicyError, RateLimited
from sajha.policy.loader import PolicySet
from sajha.policy.model import SCREEN_RANK, Limit, RedactSpec, Rule

logger = logging.getLogger(__name__)

CONFIRM_KEY = 'sajha.policy.confirm'

DECISIONS = _m.Counter(_m.REGISTRY, 'sajha_policy_decisions_total',
                       'Policy decisions on tool calls by decision and deciding rule.', ('decision', 'rule'))
REDACTIONS = _m.Counter(_m.REGISTRY, 'sajha_policy_redactions_total',
                        'Values redacted from tool results by kind.', ('kind',))
OUTPUT_FLAGS = _m.Counter(_m.REGISTRY, 'sajha_policy_output_flags_total',
                          'Tool results in which injection markers were found, by screening mode.', ('mode',))


def _cfg(key: str, default: str = '') -> str:
    from sajha.core.config import _get
    return _get(key, default)


def _cfg_bool(key: str, default: bool) -> bool:
    from sajha.core.config import _bool
    return _bool(key, default)


def default_effect() -> str:
    v = (_cfg('policy.default_effect', 'allow') or 'allow').strip().lower()
    return 'deny' if v == 'deny' else 'allow'


def enabled() -> bool:
    return _cfg_bool('policy.enabled', True)


@dataclass
class Call:
    """What a rule can match on."""
    tool: str
    arguments: Dict[str, Any]
    caller: Any
    source: str = 'other'
    annotations: Dict[str, Any] = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed: bool = False

    @property
    def group(self) -> str:
        return _m.tool_group(self.tool)


@dataclass
class Decision:
    effect: str                                      # allow | deny | require_approval
    reason: str = ''
    rule: str = ''                                   # the deciding rule's key
    kind: str = 'allow'                              # allow | deny | constraint | approval_required | default_deny
    matched: List[Rule] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    approval_rule: Optional[Rule] = None
    limits: List[Tuple[Rule, Limit, str]] = field(default_factory=list)   # (rule, limit, 'rate'|'quota')
    redact: Optional[RedactSpec] = None
    screen: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {'effect': self.effect, 'kind': self.kind, 'reason': self.reason, 'rule': self.rule,
                'matched': [r.key for r in self.matched], 'violations': list(self.violations),
                'approval': ({'rule': self.approval_rule.key, 'approver': self.approval_rule.approver}
                             if self.approval_rule else None),
                'rate_limits': [{'rule': r.key, 'type': t, 'limit': lim.limit,
                                 'window_seconds': lim.seconds if t == 'rate' else None,
                                 'period': lim.period or None, 'per': list(lim.per)} for r, lim, t in self.limits],
                'redact': ({'kinds': list(self.redact.kinds) + [c.name for c in self.redact.custom],
                            'mode': self.redact.mode} if self.redact else None),
                'screen_output': self.screen}


class Enforcement:
    """What still has to happen after the tool ran: redaction and screening of its result."""

    def __init__(self, call: Call, decision: Decision):
        self.call = call
        self.decision = decision

    def apply_output(self, result: Any) -> Any:
        from sajha.policy import redact as R
        d = self.decision
        if d.screen:
            screened, found = R.screen(result, d.screen)
            if found:
                OUTPUT_FLAGS.inc((d.screen,))
                _audit('policy.output_flagged', self.call, outcome=d.screen,
                       details={'markers': found, 'mode': d.screen})
                if d.screen == 'block':
                    DECISIONS.inc(('blocked', _rule_of(d, 'screen')))
                    raise PolicyDenied(f'Policy withheld the result of {self.call.tool}: it contains text that '
                                       f'tries to instruct the model (prompt injection).',
                                       tool=self.call.tool, rule=_rule_of(d, 'screen'),
                                       reason='output blocked: prompt injection markers')
                result = screened
        if d.redact and not d.redact.empty():
            result, counts = R.redact(result, d.redact)
            if counts:
                for kind, n in counts.items():
                    REDACTIONS.inc((kind,), n)
                _audit('policy.redacted', self.call, outcome='redacted', details={'counts': counts})
        return result


def _rule_of(d: Decision, what: str) -> str:
    for r in d.matched:
        if (what == 'screen' and r.screen_output) or (what == 'redact' and r.redact):
            return r.key
    return ''


def _audit(event: str, call: Call, outcome: str, details: Optional[Dict[str, Any]] = None) -> None:
    try:
        from sajha import audit
        c = call.caller
        det = {'source': call.source, 'argument_names': sorted(call.arguments.keys())
               if isinstance(call.arguments, dict) else []}
        if _cfg_bool('policy.audit_arguments', False):
            det['arguments'] = call.arguments
        det.update(details or {})
        audit.record(event, actor={'user': getattr(c, 'user_id', '') or 'anonymous',
                                   'api_key': getattr(c, 'api_key', '') or '',
                                   'roles': list(getattr(c, 'roles', ()) or ()),
                                   'auth': getattr(c, 'auth_type', '') or ''},
                     resource={'type': 'tool', 'id': call.tool}, outcome=outcome, details=det)
    except Exception as e:
        logger.debug(f'policy audit: {e}')


class PolicyEngine:
    def __init__(self, policy_set: Optional[PolicySet] = None):
        self.policy_set = policy_set or PolicySet()

    # -- the rules in force ----------------------------------------------

    def rules(self, include_disabled: bool = False) -> List[Rule]:
        out: List[Rule] = []
        for p in self.policy_set.policies():
            if p.error or not (p.enabled or include_disabled):
                continue
            out.extend(r for r in p.rules if r.enabled or include_disabled)
        return out

    def broken(self) -> List[str]:
        return [p.source or p.name for p in self.policy_set.policies() if p.error and p.enabled]

    # -- pure evaluation ---------------------------------------------------

    def evaluate(self, call: Call, include_disabled: bool = False) -> Decision:
        rules = [r for r in self.rules(include_disabled) if r.match.matches(call)]
        d = Decision(effect='allow', matched=rules)
        broken = self.broken()
        if broken and (_cfg('policy.on_error', 'ignore') or '').strip().lower() == 'deny':
            d.effect, d.kind, d.rule = 'deny', 'deny', 'policy.on_error'
            d.reason = f'a policy file is broken and policy.on_error is deny ({", ".join(broken)})'
            return d
        deny = next((r for r in rules if r.effect == 'deny'), None)
        if deny is not None:
            d.effect, d.kind, d.rule = 'deny', 'deny', deny.key
            d.reason = deny.reason or f'denied by policy rule {deny.key}'
            return d
        if default_effect() == 'deny' and not any(r.effect == 'allow' for r in rules):
            d.effect, d.kind, d.rule = 'deny', 'default_deny', 'policy.default_effect'
            d.reason = f'no policy rule allows {call.tool} (policy.default_effect is deny)'
            return d
        for r in rules:
            for cond in r.constraints:
                why = cond.failure(call.arguments, absent_ok=True)
                if why:
                    d.violations.append(f'{why} (rule {r.key})')
        if d.violations:
            first = next(r for r in rules if any(c.failure(call.arguments, True) for c in r.constraints))
            d.effect, d.kind, d.rule = 'deny', 'constraint', first.key
            d.reason = 'argument constraint: ' + '; '.join(d.violations)
            return d
        appr = next((r for r in rules if r.effect == 'require_approval'), None)
        if appr is not None:
            d.effect, d.kind, d.rule, d.approval_rule = 'require_approval', 'approval_required', appr.key, appr
            d.reason = appr.reason or f'policy rule {appr.key} requires approval'
        else:
            allow = next((r for r in rules if r.effect == 'allow'), None)
            d.rule = allow.key if allow else ''
        for r in rules:
            if r.rate_limit:
                d.limits.append((r, r.rate_limit, 'rate'))
            if r.quota:
                d.limits.append((r, r.quota, 'quota'))
            if r.redact:
                d.redact = r.redact if d.redact is None else d.redact.merge(r.redact)
            if r.screen_output and SCREEN_RANK[r.screen_output] > SCREEN_RANK.get(d.screen or '', 0):
                d.screen = r.screen_output
        return d

    # -- enforcement ---------------------------------------------------------

    def active(self) -> bool:
        if not enabled():
            return False
        if default_effect() == 'deny':
            return True
        if self.broken() and (_cfg('policy.on_error', 'ignore') or '').strip().lower() == 'deny':
            return True
        return bool(self.rules())

    def enforce(self, tool, arguments: Dict[str, Any]) -> Optional[Enforcement]:
        """Called before a tool runs. Raises a :class:`PolicyError` (or MRTR ``InputRequired``)
        to stop the call; returns None or an :class:`Enforcement` for the result."""
        if not self.active():
            return None
        from sajha.observability.caller import current
        from sajha.policy import context
        name = getattr(tool, 'name', str(tool))
        cfg = getattr(tool, 'config', None) or {}
        ann = cfg.get('annotations') if isinstance(cfg, dict) else None
        call = Call(name, arguments if isinstance(arguments, dict) else {}, current(), context.source(),
                    ann if isinstance(ann, dict) else {}, confirmed=context.confirmed())
        try:
            d = self.evaluate(call)
        except Exception as e:
            logger.error(f'policy evaluation failed for {name}: {e}', exc_info=True)
            if _cfg_bool('policy.fail_closed', True):
                DECISIONS.inc(('deny', 'policy.error'))
                raise PolicyDenied(f'Policy evaluation failed for {name}; the call was refused (policy.fail_closed).',
                                   tool=name, rule='policy.error')
            return None
        return self._act(call, d)

    def _act(self, call: Call, d: Decision) -> Optional[Enforcement]:
        name = call.tool
        if d.effect == 'deny':
            DECISIONS.inc((d.kind if d.kind == 'constraint' else 'deny', d.rule))
            _audit('policy.deny', call, outcome=d.kind, details={'rule': d.rule, 'reason': d.reason})
            raise PolicyDenied(f'Denied by policy: {d.reason}', tool=name, rule=d.rule, reason=d.reason)
        if d.effect == 'require_approval':
            self._approval(call, d)
        for r, lim, kind in d.limits:
            self._limit(call, r, lim, kind)
        DECISIONS.inc(('allow', d.rule))
        if _cfg_bool('policy.audit_allow', False):
            _audit('policy.allow', call, outcome='allow', details={'rule': d.rule})
        if d.redact or d.screen:
            return Enforcement(call, d)
        return None

    def _approval(self, call: Call, d: Decision) -> None:
        r = d.approval_rule
        grant = approvals.consume_grant(call.tool, call.arguments, call.caller)
        if grant is not None:
            DECISIONS.inc(('approved', r.key))
            _audit('policy.approved', call, outcome='approved',
                   details={'rule': r.key, 'approval_id': grant.get('id'), 'approved_by': grant.get('decided_by')})
            return
        if r.approver == 'caller':
            if call.confirmed:
                DECISIONS.inc(('approved', r.key))
                _audit('policy.approved', call, outcome='confirmed', details={'rule': r.key, 'by': 'caller'})
                return
            from sajha.policy import context
            if context.confirmable():      # Ask SAJHA: its user confirms with a button, no admin queue
                DECISIONS.inc(('approval_required', r.key))
                raise ApprovalRequired(f'Confirmation required: {d.reason}', tool=call.tool, rule=r.key,
                                       reason=d.reason, status='needs_confirmation', interactive=True)
            if self._mrtr_confirm(call, d):
                return
        rec = approvals.request(tool=call.tool, arguments=call.arguments, caller=call.caller, source=call.source,
                                rule=r.key, reason=d.reason, ttl=r.approval_ttl)
        DECISIONS.inc(('approval_required', r.key))
        raise ApprovalRequired(
            f'Approval required: {d.reason}. An administrator must approve request {rec["id"]} '
            f'(Approvals page, /admin/approvals); then make the same call again.',
            tool=call.tool, rule=r.key, reason=d.reason, approval_id=rec['id'], status=rec.get('status', 'pending'))

    def _mrtr_confirm(self, call: Call, d: Decision) -> bool:
        """2026-07-28 with form elicitation: ask the user (MRTR). True when confirmed."""
        try:
            from sajha.core.mcp_tool_context import current_context
            from sajha.core.mcp_mrtr import accepted_content, elicitation_form_supported, elicitation_request
        except Exception:
            return False
        ctx = current_context()
        if ctx is None or not elicitation_form_supported(ctx.client_capabilities):
            return False
        response = ctx.input_responses.get(CONFIRM_KEY)
        if response is None:
            ctx.require_input({CONFIRM_KEY: elicitation_request(
                f'{d.reason}. Run {call.tool}?',
                {'type': 'object',
                 'properties': {'confirm': {'type': 'boolean', 'title': 'Run this tool',
                                            'description': f'Confirm running {call.tool}', 'default': False}},
                 'required': ['confirm']})})
        content = accepted_content(response)
        if content is not None and content.get('confirm') is True:
            DECISIONS.inc(('approved', d.approval_rule.key))
            _audit('policy.approved', call, outcome='confirmed', details={'rule': d.approval_rule.key, 'by': 'caller'})
            return True
        DECISIONS.inc(('deny', d.approval_rule.key))
        _audit('policy.deny', call, outcome='not_confirmed', details={'rule': d.approval_rule.key})
        raise PolicyDenied(f'Tool {call.tool} was not run: the user did not confirm.', tool=call.tool,
                           rule=d.approval_rule.key, reason='not confirmed by the user')

    def _limit(self, call: Call, r: Rule, lim: Limit, kind: str) -> None:
        from sajha.core.state import get_state_store
        st = get_state_store()
        c = call.caller
        parts = []
        for dim in lim.per:
            if dim == 'tool':
                parts.append('t=' + call.tool)
            elif dim == 'user':
                parts.append('u=' + (getattr(c, 'user_id', '') or 'anonymous'))
            elif dim == 'api_key':
                parts.append('k=' + (getattr(c, 'api_key', '') or '-'))
            elif dim == 'caller':
                key = getattr(c, 'api_key', '') or ''
                parts.append(('k=' + key) if key else ('u=' + (getattr(c, 'user_id', '') or 'anonymous')))
        scope = '|'.join(parts) or 'global'
        if kind == 'rate':
            ok, _hits = st.window_add(f'policy:rate:{r.key}:{scope}', lim.seconds, lim.limit)
            if ok:
                return
            retry = lim.seconds
            what = f'rate limit of {lim.limit} call(s) per {_human(lim.seconds)}'
        else:
            period_id = _period_id(lim.period, call.now)
            key = f'policy:quota:{r.key}:{scope}:{period_id}'

            class _Over(Exception):
                pass

            def fn(cur):
                n = int(cur or 0)
                if n >= lim.limit:
                    raise _Over()
                return n + 1
            try:
                st.update(key, fn, ttl=lim.seconds + 3600)
                return
            except _Over:
                pass
            retry = _period_end(lim.period, call.now) - call.now.timestamp()
            what = f'quota of {lim.limit} call(s) per {lim.period}'
        DECISIONS.inc(('rate_limited', r.key))
        _audit('policy.rate_limited', call, outcome=kind, details={'rule': r.key, 'limit': lim.limit, 'scope': scope})
        raise RateLimited(f'Rate limited by policy rule {r.key}: {what} for {call.tool} reached.',
                          tool=call.tool, rule=r.key, reason=what, retry_after=max(1.0, round(retry, 1)))


def _human(seconds: float) -> str:
    for n, unit in ((86400, 'day'), (3600, 'hour'), (60, 'minute')):
        if seconds >= n and seconds % n == 0:
            k = int(seconds // n)
            return f'{k} {unit}{"s" if k > 1 else ""}'
    return f'{seconds:g} seconds'


def _period_id(period: str, now: datetime) -> str:
    now = now.astimezone(timezone.utc)
    if period == 'hour':
        return now.strftime('%Y%m%d%H')
    if period == 'day':
        return now.strftime('%Y%m%d')
    if period == 'week':
        y, w, _ = now.isocalendar()
        return f'{y}W{w:02d}'
    return now.strftime('%Y%m')


def _period_end(period: str, now: datetime) -> float:
    from datetime import timedelta
    now = now.astimezone(timezone.utc)
    if period == 'hour':
        start = now.replace(minute=0, second=0, microsecond=0)
        return (start + timedelta(hours=1)).timestamp()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'day':
        return (start + timedelta(days=1)).timestamp()
    if period == 'week':
        return (start + timedelta(days=7 - start.weekday())).timestamp()
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt.timestamp()


# ── the process-wide engine ──────────────────────────────────────────

_engine: Optional[PolicyEngine] = None
_lock = threading.Lock()


def get_engine() -> PolicyEngine:
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = PolicyEngine()
    return _engine


def set_engine(engine: Optional[PolicyEngine]) -> None:
    """Replace the process-wide engine (tests); None goes back to the policy directory."""
    global _engine
    _engine = engine
