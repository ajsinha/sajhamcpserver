"""
The first sources of system notices (docs/architecture/System Notices.md, section 4).

Each source owns the ids under its prefix and clears them when its condition ends:

    db.schema                                the database schema check (sajha/db/schema.py raises it itself)
    resilience.breaker_open:<breaker>        a circuit breaker is open (tools, federated upstreams, LLM providers)
    workflows.scheduled_failing:<workflow>   its scheduled (cron) runs failed notices.workflow_failures times in a row
    llm.alias_unavailable:<alias>            a model alias has no available candidate
    llm.provider_down:<provider>             an active LLM provider reports itself down
    federation.upstream_down:<upstream>      an enabled upstream MCP server is not connected
    federation.approvals:<upstream>          tools from an upstream are held for an administrator's approval
    alerts.rule:<rule>                       an alert rule with the ``notice`` channel (sajha/observability/alerts.py)

Conditions this process judges for itself (breakers, provider health, upstream connections)
are raised with ``holder=WORKER_ID`` so another worker's healthy view does not clear them.
A watcher thread re-checks the polled sources every ``notices.check_interval_seconds`` and
clears notices nobody has refreshed for their ttl.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Iterable, Optional

from sajha import notices as N

logger = logging.getLogger(__name__)


def _worker() -> str:
    from sajha.core.state import WORKER_ID
    return WORKER_ID


def reconcile(prefix: str, desired: Dict[str, Dict[str, Any]], holder: Optional[str] = None) -> None:
    """Raise every notice in ``desired`` (id -> raise_notice kwargs); clear the open ones under
    ``prefix`` that are not desired (only this holder's claim when ``holder`` is given)."""
    for nid, kw in desired.items():
        N.raise_notice(nid, holder=holder, **kw)
    try:
        opened = [n for n in N.get_service().all()
                  if n.get('state') != 'cleared' and str(n.get('id', '')).startswith(prefix)]
    except Exception as e:
        logger.debug(f'notices reconcile {prefix}: {e}')
        return
    for n in opened:
        if n['id'] in desired:
            continue
        if holder and holder not in (n.get('holders') or {}):
            continue
        N.clear_notice(n['id'], holder=holder)


# ── resilience: circuit breakers ────────────────────────────────────

BREAKER_PREFIX = 'resilience.breaker_open:'


def _breaker_notice(name: str, kind: str, b: Dict[str, Any]) -> Dict[str, Any]:
    what = {'llm': 'LLM provider', 'federation': 'federated upstream'}.get(kind, 'tool provider')
    link = {'llm': '/ai/settings', 'federation': '/admin/federation'}.get(kind, '/admin/system-monitor')
    return {'severity': 'warning', 'source': 'resilience', 'link': link,
            'title': f'Circuit breaker open: {name} ({what})',
            'detail': (f'{b.get("failure_count", 0)} failures in a row (threshold {b.get("failure_threshold")}); '
                       f'calls fail fast and a probe is let through every {b.get("recovery_timeout")} s. '
                       'It clears when a probe succeeds. Check the provider or upstream it protects.')}


def breakers_now() -> Dict[str, Dict[str, Any]]:
    """id -> notice for every breaker in this process that is not closed."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from sajha.core.circuit_breaker import get_circuit_registry
        reg = get_circuit_registry()
        with reg._lock:
            items = list(reg._breakers.items())
            extra = dict(reg._extra)
        for prefix, b in items:
            if b.state.value != 'closed':
                out[BREAKER_PREFIX + b.name] = _breaker_notice(b.name, 'federation' if prefix in extra else 'tool',
                                                               b.to_dict())
    except Exception as e:
        logger.debug(f'breaker source: {e}')
    try:
        from sajha.ai.llm import llm_factory
        gw = llm_factory()
        for _, b in list(gw.breaker_states().items()) if gw is not None else []:
            if b.state.value != 'closed':
                out[BREAKER_PREFIX + b.name] = _breaker_notice(b.name, 'llm', b.to_dict())
    except Exception as e:
        logger.debug(f'llm breaker source: {e}')
    return out


def check_breakers() -> None:
    reconcile(BREAKER_PREFIX, breakers_now(), holder=_worker())


def on_breaker_change(breaker, old: str, new: str) -> None:
    """Listener for sajha.core.circuit_breaker: raise at once on open, clear on closed."""
    try:
        name = breaker.name
        kind = 'llm' if name.startswith('llm:') else 'tool'
        if new == 'open':
            if kind == 'tool':
                from sajha.core.circuit_breaker import get_circuit_registry
                reg = get_circuit_registry()
                if any(b is breaker and p in reg._extra for p, b in list(reg._breakers.items())):
                    kind = 'federation'
            N.raise_notice(BREAKER_PREFIX + name, holder=_worker(), **_breaker_notice(name, kind, breaker.to_dict()))
        elif new == 'closed':
            N.clear_notice(BREAKER_PREFIX + name, holder=_worker())
    except Exception as e:
        logger.debug(f'breaker notice: {e}')


# ── workflows ───────────────────────────────────────────────────────

WORKFLOW_PREFIX = 'workflows.scheduled_failing:'


def workflow_failure_threshold() -> int:
    return max(1, int(N._num('notices.workflow_failures', 3)))


def workflow_run_finished(workflow: str, trigger_type: str, status: str, error: Optional[str] = None) -> None:
    """Called when a run ends (sajha/workflows/service.py). Only scheduled (cron) runs count."""
    if trigger_type != 'cron' or status not in ('succeeded', 'failed'):
        return
    try:
        store = N.get_service().store
        key = f'notices:wf_failures:{workflow}'
        nid = WORKFLOW_PREFIX + workflow
        if status == 'succeeded':
            store.delete(key)
            N.clear_notice(nid)
            return
        count = int(store.incr(key, 1, ttl=30 * 86400))
        if count >= workflow_failure_threshold():
            N.raise_notice(nid, severity='error', source='workflows', ttl_minutes=0, link='/workflows',
                           title=f'Workflow {workflow}: {count} scheduled runs failed in a row',
                           detail=(f'The last error: {(error or "unknown")[:400]}. Open the workflow\'s run history '
                                   'to see which step failed. The notice clears after the next scheduled run '
                                   'succeeds, or when the workflow is disabled or deleted.'))
    except Exception as e:
        logger.debug(f'workflow notice: {e}')


def check_workflows() -> None:
    """Clear notices for workflows that are gone or disabled (nothing will run to clear them)."""
    try:
        opened = [n for n in N.get_service().all()
                  if n.get('state') != 'cleared' and str(n.get('id', '')).startswith(WORKFLOW_PREFIX)]
        if not opened:
            return
        from sajha.workflows import get_service
        svc = get_service()
        if svc is None:
            return
        for n in opened:
            wf = svc.store.get_workflow(n['id'][len(WORKFLOW_PREFIX):])
            if not wf or not wf.get('enabled'):
                N.clear_notice(n['id'], reason='workflow disabled or deleted')
    except Exception as e:
        logger.debug(f'workflow notices check: {e}')


# ── intelligence layer ─────────────────────────────────────────────

ALIAS_PREFIX = 'llm.alias_unavailable:'
PROVIDER_PREFIX = 'llm.provider_down:'


def check_llm() -> None:
    aliases: Dict[str, Dict[str, Any]] = {}
    providers: Dict[str, Dict[str, Any]] = {}
    try:
        from sajha.ai.llm import llm_factory
        gw = llm_factory()
    except Exception:
        gw = None
    if gw is not None:
        for name in gw.provider_names():
            p = gw.provider(name)
            if p is None or not p.active:
                continue
            try:
                h = gw.provider_health(name)
            except Exception as e:
                h = None
                detail = str(e)
            if h is None or not h.ok:
                detail = h.detail if h is not None else detail
                providers[PROVIDER_PREFIX + name] = {
                    'severity': 'warning', 'source': 'llm', 'link': '/ai/settings',
                    'title': f'LLM provider {name} is failing',
                    'detail': (f'Its health check says: {detail or "down"}. Aliases fall back to their next '
                               'candidate; check the provider\'s key, URL and quota on the LLM page.')}
        from sajha.ai.llm import LLMError
        for alias in list(gw.settings.aliases):
            try:
                gw.model(alias).info()          # the model that would answer now
            except LLMError as e:
                aliases[ALIAS_PREFIX + alias] = {
                    'severity': 'error' if alias == 'default' else 'warning', 'source': 'llm',
                    'link': '/ai/settings',
                    'title': f'Model alias {alias} has no available model',
                    'detail': (f'{e}. Calls that ask for "{alias}" fail until one of its candidates is enabled '
                               'and healthy (ai.aliases).')}
            except Exception as e:
                logger.debug(f'alias {alias}: {e}')
    reconcile(PROVIDER_PREFIX, providers, holder=_worker())
    reconcile(ALIAS_PREFIX, aliases, holder=_worker())


# ── federation ──────────────────────────────────────────────────────

UPSTREAM_PREFIX = 'federation.upstream_down:'
APPROVAL_PREFIX = 'federation.approvals:'


def check_federation() -> None:
    down: Dict[str, Dict[str, Any]] = {}
    held: Dict[str, Dict[str, Any]] = {}
    try:
        from sajha.federation.manager import get_federation
        fed = get_federation()
        status = fed.status() if fed is not None and fed.settings.enabled else []
    except Exception as e:
        logger.debug(f'federation source: {e}')
        status = []
    for s in status:
        uid, state = s.get('id'), s.get('state')
        if not s.get('enabled') or state == 'disabled':
            continue
        if state == 'error' or (state == 'connecting' and s.get('last_error')):
            approved = (s.get('counts') or {}).get('approved', 0)
            down[UPSTREAM_PREFIX + uid] = {
                'severity': 'error', 'source': 'federation', 'link': '/admin/federation',
                'audience': 'everyone' if approved else 'admin',
                'title': f'Federated server {s.get("title") or uid} is unreachable',
                'detail': (f'{s.get("last_error") or "Not connected"}. Its tools ({approved} approved) fail until '
                           'it reconnects; SAJHA keeps retrying.')}
        n = sum(1 for i in s.get('items') or [] if i.get('kind') == 'tool' and i.get('status') in ('pending', 'changed'))
        if n:
            held[APPROVAL_PREFIX + uid] = {
                'severity': 'warning', 'source': 'federation', 'link': '/admin/federation',
                'title': f'{n} tool{"s" if n != 1 else ""} from {s.get("title") or uid} held for approval',
                'detail': ('New or changed tool definitions from this upstream are not offered to clients until '
                           'an administrator approves them on the Federation page.')}
    reconcile(UPSTREAM_PREFIX, down, holder=_worker())
    reconcile(APPROVAL_PREFIX, held)


# ── alert rules (the notice channel) ───────────────────────────────

ALERT_PREFIX = 'alerts.rule:'


def alert_rule(rule, holds: bool, msg: Optional[Dict[str, Any]] = None) -> None:
    """An alert rule with ``channel: {type: notice}`` was evaluated (sajha/observability/alerts.py)."""
    nid = ALERT_PREFIX + rule.name
    if not holds:
        N.clear_notice(nid, holder=_worker())
        return
    ch = rule.channel or {}
    value = rule.last_value if msg is None else msg.get('value')
    N.raise_notice(nid, severity=str(ch.get('severity') or 'warning'), source='alerts',
                   audience=str(ch.get('audience') or 'admin'), link=str(ch.get('link') or '/monitoring/usage'),
                   holder=_worker(),
                   title=str(ch.get('title') or f'Alert {rule.name}: {rule.metric} {rule.op} {rule.threshold:g}'),
                   detail=(f'{rule.metric} is {value if value is None else round(float(value), 6)} over the last '
                           f'{int(rule.window_s)} s (threshold {rule.op} {rule.threshold:g}). '
                           'It clears when the rule no longer holds.'))


# ── the watcher ─────────────────────────────────────────────────────

POLLED = (check_breakers, check_llm, check_federation, check_workflows)


def check_all() -> None:
    if not N.enabled():
        return
    for fn in POLLED:
        try:
            fn()
        except Exception as e:
            logger.debug(f'notice source {fn.__name__}: {e}')
    try:
        N.get_service().sweep()
    except Exception as e:
        logger.debug(f'notice sweep: {e}')


_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def start() -> bool:
    """Start the watcher (notices.enabled) and the breaker listener. Returns True when started."""
    global _thread, _stop
    if not N.enabled() or _thread is not None:
        return False
    try:
        from sajha.core import circuit_breaker
        circuit_breaker.add_listener(on_breaker_change)
    except Exception as e:
        logger.debug(f'breaker listener: {e}')
    interval = max(5.0, N._num('notices.check_interval_seconds', 30))
    _stop = threading.Event()

    def loop(stop: threading.Event):
        check_all()                         # at start-up, then every interval
        while not stop.wait(interval):
            check_all()

    _thread = threading.Thread(target=loop, args=(_stop,), name='sajha-notices', daemon=True)
    _thread.start()
    return True


def stop() -> None:
    global _thread
    _stop.set()
    _thread = None
    try:
        from sajha.core import circuit_breaker
        circuit_breaker.remove_listener(on_breaker_change)
    except Exception:
        pass
